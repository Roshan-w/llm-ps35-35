# Multi-PDF Comparison Tool (PS 35)

**Live website:** https://llm-ps35-35.vercel.app · **Open the tool:** https://llm-ps35-35.vercel.app/app

**Demo video (1 min 44 s, narrated):** [watch `demo/demo_video.mp4`](demo/demo_video.mp4)

[![Demo video: Compare documents, side by side](demo/thumbnail.jpg)](demo/demo_video.mp4)

**Problem statement:** Comparing several documents is tedious. Upload 2–3 PDFs and ask comparison questions across them.

**Approach:** Each PDF gets its own FAISS retriever → for a question, the top chunks are retrieved from *each* PDF separately → one prompt asks the LLM to answer as a comparison table (one column per document, "Not mentioned" when a PDF lacks the info).

## Features
- Upload 2–3 PDFs; each gets its own FAISS retriever so no document is left out
- Comparison table + key differences + summary, with page citations
- "Not mentioned" instead of guessing (reduces hallucination)
- One-click **Quick overview** of all documents
- Sample questions, history of all comparisons in the session
- Download each answer as Markdown, CSV or Excel
- Sources panel showing exactly which passages were used
- Default LLM: self-hosted Qwen 2.5 14B (OpenAI-compatible llama.cpp server); Groq, Gemini and Ollama still selectable
- Answers stream in live; clear errors when the server is unreachable, the key is wrong (401) or a request times out
- Works offline for retrieval: falls back to keyword vectors if the embedding model can't download
- Clear errors for scanned, blank, password-protected or invalid PDFs; auto-retry on rate limits

## Tech stack
- Python; Streamlit (local UI) and a web version (HTML/CSS/JS + Python serverless API) on Vercel
- LangChain + FAISS (one vector store per PDF), pypdf for text extraction
- FastEmbed `BAAI/bge-small-en-v1.5` embeddings (free, runs locally on CPU)
- LLM: Qwen 2.5 14B via an OpenAI-compatible endpoint (default), Llama 3.3 70B via Groq, Gemini 2.5 Flash, or a local Ollama model

## Web version (Vercel)
The project is live at **https://llm-ps35-35.vercel.app** and has two pages:

| Page | What it shows |
|---|---|
| **Landing page** (`/`) | What the tool does, a 4-step "How it works" infographic, a chart of why each PDF gets its own index, an architecture diagram, features, a real sample output and an FAQ |
| **Workspace** (`/app`) | The comparison tool: sidebar, composer with PDF chips, live model status, context meter, documents list, recent questions, and streamed answers with sources and CSV/Markdown export |

Design: a soft rose theme with light and dark modes, rounded panels and **Pip**, an animated SVG mascot that thinks while an answer streams and smiles when it's done.

How it works: PDFs are read **in the browser** with pdf.js (files are never uploaded). A small Python serverless
function (standard library only) builds a BM25 index per PDF, takes the top passages from each one, and streams the
answer from Qwen 2.5 14B using the same prompt as the Streamlit app (`src/prompt.py`). The model runs on a lab GPU
and is reached through a key-protected tunnel.

```bash
python web/dev_server.py        # local preview at http://localhost:3000
cd web && vercel deploy --prod  # deploy
```
Vercel environment variables: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY_ENV` and the key itself (`QWEN_API_KEY`).

## Demo video
[`demo/demo_video.mp4`](demo/demo_video.mp4): a 1 min 44 s walkthrough of the website with a narrated voiceover, captions,
music and sound effects. It covers the problem, how it works, why each PDF gets its own index, a live comparison
(including a "Not mentioned" cell and its source passage), the architecture and the key numbers.

## How to run
**Quick start (Windows):** double-click `run.bat` (Mac/Linux: `./run.sh`), then add your key to `.env`.

**Manual:**
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # then paste your GROQ_API_KEY into .env
streamlit run app.py
```
**LLM configuration** (in `.env` or the environment):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `Qwen` | Default provider |
| `LLM_BASE_URL` | `http://127.0.0.1:18205/v1` | OpenAI-compatible server URL |
| `LLM_MODEL` | `qwen2.5-14b` | Model name |
| `LLM_API_KEY_ENV` | `QWEN_API_KEY` | Name of the environment variable that holds the key (the key itself is never stored in `.env`) |
| `LLM_TIMEOUT` | `600` | Request timeout in seconds |
| `LLM_MAX_TOKENS` | `1500` | Max answer length |

For Groq, set `GROQ_API_KEY` (free key at https://console.groq.com/keys).

## Usage
1. Upload 2–3 PDFs (try the ones in `sample_pdfs/`).
2. Pick a sample question or type your own, e.g. *"Compare the price, features and warranty."*
3. Click **Compare** → comparison table, key differences, summary, and the passages retrieved from each PDF.

## Project structure
```
app.py                  Streamlit UI
web/                    Website: landing page, workspace and Vercel serverless API
demo/                   Demo video and its thumbnail
src/prompt.py           The comparison prompt (shared by both UIs)
src/pdf_compare.py      PDF loading, per-PDF retrievers, prompt, LLM call
sample_pdfs/            3 sample laptop spec sheets
tests/                  sample PDF generator + pipeline test (pytest)
```

## Tests
```bash
pytest -q
```
15 tests: indexing, per-PDF retrieval, prompt building, bad/blank PDF handling, table export, a full UI flow test, the web API (BM25 retrieval, validation, health) and a check that both UIs use the same prompt.

## Docker
```bash
docker build -t pdf-compare . && docker run -p 8501:8501 --env-file .env pdf-compare
```

## Screenshots
Website (live on Vercel): landing page, workspace, and dark mode.

![Landing page](screenshots/05_web_ui.png)

![Workspace](screenshots/06_web_result.png)

![Workspace in dark mode](screenshots/07_web_dark.png)

Streamlit app: real outputs from Qwen 2.5 14B on the three sample PDFs (more in `screenshots/`).

![Price, features and warranty comparison](screenshots/01_price_features_warranty.jpg)

![Which laptop suits a student on a budget](screenshots/04_student_budget.jpg)
