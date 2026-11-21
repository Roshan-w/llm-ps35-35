import io
import os
import re
import time
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # before reading LLM_* settings below

import pandas as pd
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K = 4
MAX_PAGES = 300

PROMPT_TEMPLATE = """You are a careful document analyst. You are given excerpts from {n} PDF documents: {names}.
Answer the user's comparison question using ONLY these excerpts.

Rules:
1. Start with a Markdown comparison table. The first column is "Aspect", then one column per document (use the document names exactly as column headers), one row per aspect being compared.
2. If a document does not mention an aspect, write "Not mentioned" in that cell. Never guess or use outside knowledge.
3. After the table, write a "### Key differences" section with 2-4 bullet points.
4. End with "### Summary" and one or two sentences.
5. Cite page numbers like (p. 3) inside table cells where useful.

Question: {question}

{context}
"""

OVERVIEW_QUESTION = ("Give an overview comparison of these documents: their purpose or topic, "
                     "main points, key numbers or facts, and intended audience.")


class TfidfEmbeddings(Embeddings):
    def __init__(self):
        from sklearn.feature_extraction.text import HashingVectorizer
        self.vec = HashingVectorizer(n_features=2048, ngram_range=(1, 2), stop_words="english",
                                     alternate_sign=False, norm="l2")

    def _embed(self, texts):
        return self.vec.transform(texts).toarray().tolist()

    def embed_documents(self, texts):
        return self._embed(texts)

    def embed_query(self, text):
        return self._embed([text])[0]


def get_embeddings():
    if os.getenv("EMBEDDINGS", "").lower() == "offline":
        return TfidfEmbeddings(), "Keyword vectors (offline mode)"
    try:
        from langchain_community.embeddings import FastEmbedEmbeddings
        emb = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        emb.embed_query("test")
        return emb, "FastEmbed (bge-small-en-v1.5)"
    except Exception:
        return TfidfEmbeddings(), "Keyword vectors (offline fallback)"


# Self-hosted OpenAI-compatible server (llama.cpp + Qwen 2.5 14B) reached through an SSH tunnel.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:18205/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-14b")
LLM_API_KEY_ENV = os.getenv("LLM_API_KEY_ENV", "QWEN_API_KEY")  # name of the env var holding the key
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "600"))  # model runs ~5.5 tok/s, so be generous
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1500"))  # answer budget; context window is 32k
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "Qwen")


class LLMError(RuntimeError):
    """LLM failure with a message that is safe and useful to show the user."""


def get_llm(provider=None, model=None, temperature=0.2, api_key=None):
    provider = provider or DEFAULT_PROVIDER
    if provider == "Qwen":
        from langchain_openai import ChatOpenAI
        key = api_key or os.getenv(LLM_API_KEY_ENV)
        if not key:
            raise LLMError(f"{LLM_API_KEY_ENV} is not set in this process's environment. If you just set it "
                           "in Windows, restart the terminal/editor so new programs see it.")
        # max_retries=0: one model serves everyone, so don't silently re-send slow requests.
        return ChatOpenAI(model=model or LLM_MODEL, base_url=LLM_BASE_URL, api_key=key,
                          temperature=temperature, timeout=LLM_TIMEOUT, max_retries=0,
                          max_tokens=LLM_MAX_TOKENS, streaming=True)
    if provider == "Groq":
        from langchain_groq import ChatGroq
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY is missing. Add it to .env or the sidebar.")
        return ChatGroq(model=model or "llama-3.3-70b-versatile", temperature=temperature, api_key=key)
    if provider == "Gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        key = api_key or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ValueError("GOOGLE_API_KEY is missing. Add it to .env or the sidebar.")
        return ChatGoogleGenerativeAI(model=model or "gemini-2.5-flash", temperature=temperature,
                                      google_api_key=key)
    if provider == "Ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model or "llama3.2", temperature=temperature)
    raise ValueError(f"Unknown provider: {provider}")


@dataclass
class PdfIndex:
    name: str
    pages: int
    chunks: int
    words: int
    store: FAISS

    def retrieve(self, question, k=TOP_K):
        return self.store.similarity_search(question, k=min(k, self.chunks))


def load_pdf(file, name):
    try:
        reader = PdfReader(file)
    except Exception as e:
        raise ValueError(f"'{name}' could not be read as a PDF ({e}).")
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError(f"'{name}' is password protected.")
    docs = []
    for i, page in enumerate(reader.pages[:MAX_PAGES], start=1):
        text = re.sub(r"[ \t]+", " ", page.extract_text() or "").strip()
        if text:
            docs.append(Document(page_content=text, metadata={"source": name, "page": i}))
    return docs, len(reader.pages)


def build_index(file, name, embeddings):
    docs, pages = load_pdf(file, name)
    if not docs:
        raise ValueError(f"No extractable text found in '{name}' (it may be a scanned PDF).")
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = splitter.split_documents(docs)
    store = FAISS.from_documents(chunks, embeddings)
    words = sum(len(d.page_content.split()) for d in docs)
    return PdfIndex(name=name, pages=pages, chunks=len(chunks), words=words, store=store)


def build_context(indexes, question, k=TOP_K):
    blocks, retrieved = [], {}
    for idx in indexes:
        hits = idx.retrieve(question, k=k)
        retrieved[idx.name] = hits
        body = "\n---\n".join(f"(p. {d.metadata['page']}) {d.page_content}" for d in hits)
        blocks.append(f"=== Document: {idx.name} ===\n{body}")
    return "\n\n".join(blocks), retrieved


def build_prompt(indexes, question, k=TOP_K):
    context, retrieved = build_context(indexes, question, k)
    names = ", ".join(i.name for i in indexes)
    prompt = PROMPT_TEMPLATE.format(n=len(indexes), names=names, question=question, context=context)
    return prompt, retrieved


def explain_llm_error(e):
    """Turn connection / auth / timeout failures into clear messages (never includes the key)."""
    try:
        import openai
    except ImportError:
        return None
    if isinstance(e, openai.APITimeoutError):
        return (f"The model did not answer within {LLM_TIMEOUT:.0f}s ({LLM_BASE_URL}). It is slow (~5.5 tokens/s); "
                "try fewer chunks per PDF, or raise LLM_TIMEOUT.")
    if isinstance(e, openai.APIConnectionError):
        return (f"Cannot reach the LLM server at {LLM_BASE_URL} (connection refused). The SSH tunnel is probably "
                "down: check `curl http://127.0.0.1:18205/health` and restart the tunnel.")
    if isinstance(e, openai.AuthenticationError):
        return (f"The LLM server rejected the API key (401). Check that {LLM_API_KEY_ENV} is set to the right key "
                "and restart the terminal/editor after changing it.")
    return None


def call_llm(llm, prompt, retries=3, on_token=None):
    for attempt in range(retries):
        try:
            if on_token is None:
                return llm.invoke(prompt).content
            parts = []
            for chunk in llm.stream(prompt):
                text = chunk.content if isinstance(chunk.content, str) else ""
                parts.append(text)
                on_token(text)
            return "".join(parts)
        except Exception as e:
            friendly = explain_llm_error(e)
            if friendly:
                raise LLMError(friendly) from e
            msg = str(e).lower()
            if attempt < retries - 1 and ("rate" in msg or "429" in msg or "quota" in msg):
                time.sleep(2 * (attempt + 1))
                continue
            raise


def compare(indexes, question, llm, k=TOP_K, on_token=None):
    prompt, retrieved = build_prompt(indexes, question, k)
    answer = call_llm(llm, prompt, on_token=on_token)
    if isinstance(answer, list):
        answer = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in answer)
    return answer, retrieved


def extract_table(markdown):
    lines = [l.strip() for l in markdown.splitlines()]
    rows, started = [], False
    for line in lines:
        if line.startswith("|") and line.endswith("|"):
            started = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            rows.append(cells)
        elif started:
            break
    if len(rows) < 2:
        return None
    header, body = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
    return pd.DataFrame(body, columns=header) if body else None


def table_to_excel(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Comparison")
    return buf.getvalue()
