"""The comparison prompt. Shared by the Streamlit app and the web API (web/api/_prompt.py is a copy;
tests/test_prompt_sync.py checks they match)."""

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
