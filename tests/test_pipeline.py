import os
import glob
import io

import pytest
from pypdf import PdfWriter

from src.pdf_compare import (TfidfEmbeddings, build_index, build_prompt, extract_table, load_pdf,
                             table_to_excel)

PDFS = sorted(glob.glob("sample_pdfs/*.pdf"))


@pytest.fixture(scope="module")
def indexes():
    emb = TfidfEmbeddings()
    return [build_index(p, p.split("/")[-1], emb) for p in PDFS]


def test_indexes_built(indexes):
    assert len(indexes) == 3
    assert all(i.pages == 2 and i.chunks >= 1 and i.words > 20 for i in indexes)


def test_prompt_has_every_pdf(indexes):
    prompt, retrieved = build_prompt(indexes, "Compare the warranty", k=2)
    for i in indexes:
        assert f"=== Document: {i.name} ===" in prompt
        assert retrieved[i.name]
    assert "Not mentioned" in prompt


def test_retrieval_finds_relevant_page(indexes):
    alpha = next(i for i in indexes if os.path.basename(i.name) == "laptop_alpha.pdf")
    top = alpha.retrieve("warranty years onsite", k=1)[0]
    assert "Warranty" in top.page_content and top.metadata["page"] == 2


def test_blank_pdf_rejected():
    w = PdfWriter()
    w.add_blank_page(200, 200)
    buf = io.BytesIO()
    w.write(buf)
    buf.seek(0)
    with pytest.raises(ValueError, match="No extractable text"):
        build_index(buf, "blank.pdf", TfidfEmbeddings())


def test_invalid_file_rejected():
    with pytest.raises(ValueError, match="could not be read"):
        load_pdf(io.BytesIO(b"not a pdf"), "bad.pdf")


def test_extract_table():
    md = ("| Aspect | A | B |\n|---|---|---|\n| Price | 10 | 20 |\n| Warranty | 1 yr | Not mentioned |\n\n"
          "### Key differences\n- A is cheaper")
    df = extract_table(md)
    assert list(df.columns) == ["Aspect", "A", "B"] and len(df) == 2
    assert table_to_excel(df)[:2] == b"PK"
    assert extract_table("no table here") is None
