import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web" / "api"))
import _core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def sample_docs():
    out = []
    for n in ("laptop_alpha.pdf", "laptop_beta.pdf", "laptop_gamma.pdf"):
        out.append((n, [p.extract_text() for p in PdfReader(ROOT / "sample_pdfs" / n).pages]))
    return out


def test_retrieval_finds_warranty_page():
    idx = _core.DocIndex(*sample_docs()[0])
    top = idx.retrieve("warranty years onsite", k=1)[0]
    assert top["page"] == 2 and "Warranty" in top["text"]


def test_prompt_has_every_document():
    prompt, sources = _core.build_prompt(sample_docs(), "Compare the price", k=2)
    for name, _ in sample_docs():
        assert f"=== Document: {name} ===" in prompt and sources[name]
    assert "Not mentioned" in prompt


def test_validation_errors():
    with pytest.raises(_core.UserError):
        _core.validate({"docs": [{"name": "a.pdf", "pages": ["x"]}], "question": "q"})
    with pytest.raises(_core.UserError):
        _core.validate({"docs": [{"name": "a", "pages": ["x"]}] * 2, "question": ""})
    _, q, _ = _core.validate({"docs": [{"name": "a", "pages": ["x"]}] * 2, "overview": True})
    assert q == _core.OVERVIEW_QUESTION


def test_blank_document_rejected():
    with pytest.raises(_core.UserError):
        _core.DocIndex("blank.pdf", ["", "  "])


def test_health_without_key_reports_offline(monkeypatch):
    monkeypatch.delenv(_core.LLM_API_KEY_ENV, raising=False)
    h = _core.health()
    assert h["ok"] is False and "API key" in h["error"]


def test_split_text_overlaps_and_covers():
    text = " ".join(f"word{i}" for i in range(600))
    chunks = _core.split_text(text)
    assert len(chunks) > 1 and all(len(c) <= _core.CHUNK_SIZE for c in chunks)
    assert chunks[-1].endswith("word599")
