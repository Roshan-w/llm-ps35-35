import io
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from src.pdf_compare import (LLM_MODEL, OVERVIEW_QUESTION, build_index, compare, extract_table, get_embeddings,
                             get_llm, table_to_excel)

load_dotenv()

st.set_page_config(page_title="Multi-PDF Comparison Tool", page_icon="📑", layout="wide")

SAMPLE_QUESTIONS = [
    "Compare the price, features and warranty offered in each document.",
    "What are the main objectives of each document?",
    "Compare the eligibility criteria, deadlines and fees.",
    "Which option is better for a student on a budget, and why?",
    "List the strengths and weaknesses mentioned in each document.",
]
DEFAULT_MODELS = {"Qwen": LLM_MODEL, "Groq": "llama-3.3-70b-versatile", "Gemini": "gemini-2.5-flash", "Ollama": "llama3.2"}


@st.cache_resource(show_spinner="Loading embedding model...")
def embeddings():
    return get_embeddings()


@st.cache_resource(show_spinner=False)
def cached_index(name, data, _emb, emb_label):
    return build_index(io.BytesIO(data), name, _emb)


if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.header("⚙️ Settings")
    provider = st.selectbox("LLM provider", list(DEFAULT_MODELS))  # Qwen (self-hosted) is the default
    model = st.text_input("Model", DEFAULT_MODELS[provider])
    api_key = None
    if provider not in ("Ollama", "Qwen"):  # Qwen key comes only from the environment
        api_key = st.text_input("API key (optional, overrides .env)", type="password") or None
    top_k = st.slider("Chunks retrieved per PDF", 2, 8, 4)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.1)
    emb, emb_label = embeddings()
    st.caption(f"Embeddings: {emb_label}")
    if st.session_state.history and st.button("Clear history"):
        st.session_state.history = []
        st.rerun()
    st.divider()
    st.markdown("**How it works**\n1. Each PDF gets its own retriever\n2. Relevant chunks are pulled from "
                "every PDF\n3. One prompt asks the LLM for a comparison table")

st.title("📑 Multi-PDF Comparison Tool")
st.caption("Upload 2–3 PDFs and ask comparison questions across them.")

files = st.file_uploader("Upload 2–3 PDF files", type="pdf", accept_multiple_files=True)

if not files:
    st.info("👆 Upload PDFs to begin. Sample PDFs are in the `sample_pdfs/` folder.")
    st.stop()
if len(files) < 2:
    st.warning("Please upload at least 2 PDFs to compare.")
    st.stop()
if len(files) > 3:
    st.warning("Only the first 3 PDFs are used.")
    files = files[:3]

indexes = []
with st.spinner("Reading and indexing PDFs..."):
    for f in files:
        try:
            indexes.append(cached_index(f.name, f.getvalue(), emb, emb_label))
        except ValueError as e:
            st.error(str(e))
if len(indexes) < 2:
    st.stop()

cols = st.columns(len(indexes))
for col, idx in zip(cols, indexes):
    with col.container(border=True):
        st.markdown(f"**📄 {idx.name}**")
        st.caption(f"{idx.pages} pages · {idx.words:,} words · {idx.chunks} chunks")


def run(question):
    try:
        llm = get_llm(provider, model, temperature, api_key)
        live, buf = st.empty(), []

        def show(tok):
            buf.append(tok)
            live.markdown("".join(buf) + " ▌")

        with st.spinner("Retrieving from each PDF and comparing (the self-hosted model is slow; answer streams below)..."):
            answer, retrieved = compare(indexes, question, llm, k=top_k, on_token=show)
        live.empty()
        st.session_state.history.insert(0, {
            "question": question, "answer": answer, "retrieved": retrieved,
            "docs": [i.name for i in indexes], "time": datetime.now().strftime("%H:%M:%S"),
            "model": f"{provider} · {model}",
        })
    except Exception as e:
        st.error(f"LLM call failed: {e}")


c1, c2 = st.columns([3, 1])
with c1:
    sample = st.selectbox("Sample questions", ["— type your own —"] + SAMPLE_QUESTIONS)
    question = st.text_area("Your comparison question", value="" if sample.startswith("—") else sample,
                            height=90, placeholder="e.g. Compare the price and warranty in each document")
with c2:
    st.write("")
    st.write("")
    compare_clicked = st.button("🔍 Compare", type="primary", use_container_width=True)
    overview_clicked = st.button("📋 Quick overview", use_container_width=True)

if compare_clicked:
    if question.strip():
        run(question.strip())
    else:
        st.warning("Type a question first.")
if overview_clicked:
    run(OVERVIEW_QUESTION)

for n, item in enumerate(st.session_state.history):
    with st.container(border=True):
        st.markdown(f"#### ❓ {item['question']}")
        st.caption(f"{item['time']} · {item['model']} · {', '.join(item['docs'])}")
        st.markdown(item["answer"])
        d1, d2, d3 = st.columns(3)
        d1.download_button("⬇️ Markdown", item["answer"], file_name="comparison.md", key=f"md{n}")
        df = extract_table(item["answer"])
        if df is not None:
            d2.download_button("⬇️ CSV", df.to_csv(index=False), file_name="comparison.csv",
                               mime="text/csv", key=f"csv{n}")
            d3.download_button("⬇️ Excel", table_to_excel(df), file_name="comparison.xlsx", key=f"xl{n}")
        with st.expander("Sources: passages retrieved from each PDF"):
            for name, docs in item["retrieved"].items():
                st.markdown(f"**{name}**")
                for d in docs:
                    st.caption(f"Page {d.metadata['page']}")
                    st.text(d.page_content[:600])
