from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ANSWER = ("| Aspect | laptop_alpha.pdf | laptop_beta.pdf |\n|---|---|---|\n"
          "| Price | Rs. 54,999 (p. 1) | Rs. 72,500 (p. 1) |\n\n### Key differences\n- Alpha is cheaper\n\n"
          "### Summary\nAlpha suits budgets.")


class FakeLLM:
    def invoke(self, prompt):
        assert "laptop_alpha.pdf" in prompt and "laptop_beta.pdf" in prompt
        return type("R", (), {"content": ANSWER})()


def test_app_without_files():
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    assert "Upload PDFs" in at.info[0].value


def test_app_compare_flow():
    import src.pdf_compare as pc
    from src.pdf_compare import TfidfEmbeddings, build_index
    emb = TfidfEmbeddings()
    idx = [build_index(f"sample_pdfs/{n}", n, emb) for n in ("laptop_alpha.pdf", "laptop_beta.pdf")]
    with patch.object(pc, "get_llm", return_value=FakeLLM()):
        import app_harness
        at = AppTest.from_function(app_harness.harness, args=(idx,), default_timeout=60).run()
        at.text_area[0].input("Compare the price").run()
        at.button[0].click().run()
    assert not at.exception
    assert any("Rs. 54,999" in m.value for m in at.markdown)
