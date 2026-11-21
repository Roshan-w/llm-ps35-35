"""Retrieval + LLM call for the web version. Standard library only, so the Vercel function stays tiny.

Same idea as the Streamlit app: every PDF gets its own index, the top chunks are pulled from EACH PDF,
and one prompt asks the model for a comparison table.
"""
import json
import math
import os
import re
import socket
import urllib.error
import urllib.request
from collections import Counter

from _prompt import OVERVIEW_QUESTION, PROMPT_TEMPLATE

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K = 4
MAX_DOCS, MIN_DOCS = 3, 2
MAX_CHARS_PER_DOC = 400_000
MAX_QUESTION = 600

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:18205/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-14b")
LLM_API_KEY_ENV = os.getenv("LLM_API_KEY_ENV", "QWEN_API_KEY")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "280"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1500"))

STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were will with
what which who how does do each their there these those than then into about any all can per vs""".split())


class UserError(ValueError):
    """Bad input: shown to the user as-is."""


class LLMError(RuntimeError):
    """LLM failure with a safe, readable message."""


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in STOP and len(t) > 1]


def split_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end), text.rfind(" ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


class DocIndex:
    """BM25 index over one document's chunks."""

    def __init__(self, name, pages):
        self.name = name
        self.chunks = [(i, c) for i, page in enumerate(pages, start=1) for c in split_text(page)]
        if not self.chunks:
            raise UserError(f"No extractable text found in '{name}' (it may be a scanned PDF).")
        self.docs = [Counter(tokens(c)) for _, c in self.chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / len(self.lens) or 1
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def retrieve(self, question, k=TOP_K, k1=1.5, b=0.75):
        q = tokens(question)
        scores = []
        for i, (d, dl) in enumerate(zip(self.docs, self.lens)):
            s = sum(self.idf.get(t, 0) * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * dl / self.avg)) for t in q if t in d)
            scores.append((s, -i))
        best = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)[:k]
        return [{"page": self.chunks[i][0], "text": self.chunks[i][1]} for i in sorted(best)]


def validate(payload):
    docs = payload.get("docs") or []
    question = (payload.get("question") or "").strip()
    if payload.get("overview"):
        question = OVERVIEW_QUESTION
    if not MIN_DOCS <= len(docs) <= MAX_DOCS:
        raise UserError("Upload 2 or 3 PDFs to compare.")
    if not question:
        raise UserError("Type a question first.")
    if len(question) > MAX_QUESTION:
        raise UserError(f"Keep the question under {MAX_QUESTION} characters.")
    clean = []
    for d in docs:
        name = str(d.get("name", "document.pdf"))[:120]
        pages = [str(p) for p in (d.get("pages") or [])][:300]
        if sum(len(p) for p in pages) > MAX_CHARS_PER_DOC:
            raise UserError(f"'{name}' is too large for the online demo (max ~{MAX_CHARS_PER_DOC // 1000}k characters).")
        clean.append((name, pages))
    k = max(2, min(8, int(payload.get("k") or TOP_K)))
    return clean, question, k


def build_prompt(docs, question, k=TOP_K):
    indexes = [DocIndex(n, p) for n, p in docs]
    blocks, sources = [], {}
    for idx in indexes:
        hits = idx.retrieve(question, k)
        sources[idx.name] = hits
        body = "\n---\n".join(f"(p. {h['page']}) {h['text']}" for h in hits)
        blocks.append(f"=== Document: {idx.name} ===\n{body}")
    names = ", ".join(i.name for i in indexes)
    prompt = PROMPT_TEMPLATE.format(n=len(indexes), names=names, question=question, context="\n\n".join(blocks))
    return prompt, sources


def _key():
    key = os.getenv(LLM_API_KEY_ENV)
    if not key:
        raise LLMError(f"The server has no API key configured ({LLM_API_KEY_ENV}).")
    return key


def _explain(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return "The model server rejected the API key (401). The site owner needs to update it."
        if e.code in (502, 503, 504, 530):
            return "The model server is offline right now (the lab tunnel is down). Please try again later."
        return f"The model server returned an error (HTTP {e.code})."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return f"The model did not answer within {LLM_TIMEOUT:.0f}s. Try fewer chunks per PDF."
    if isinstance(e, urllib.error.URLError):
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return f"The model did not answer within {LLM_TIMEOUT:.0f}s. Try fewer chunks per PDF."
        return "Cannot reach the model server (connection refused). The lab tunnel is probably down."
    return None


def stream_answer(prompt, temperature=0.2):
    """Yield text pieces from the OpenAI-compatible /chat/completions endpoint (streaming)."""
    body = json.dumps({"model": LLM_MODEL, "stream": True, "temperature": temperature, "max_tokens": LLM_MAX_TOKENS,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{LLM_BASE_URL}/chat/completions", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {_key()}", "Accept": "text/event-stream",
        "ngrok-skip-browser-warning": "1"})
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001 - turn network errors into readable ones
        msg = _explain(e)
        if msg:
            raise LLMError(msg) from e
        raise


def health():
    try:
        req = urllib.request.Request(f"{LLM_BASE_URL}/models", headers={"Authorization": f"Bearer {_key()}",
                                                                         "ngrok-skip-browser-warning": "1"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            ids = [m.get("id") for m in json.load(resp).get("data", [])]
        return {"ok": True, "model": LLM_MODEL, "available": LLM_MODEL in ids or bool(ids)}
    except LLMError as e:
        return {"ok": False, "model": LLM_MODEL, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model": LLM_MODEL, "error": _explain(e) or "Model server unavailable."}
