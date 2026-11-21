def harness(idx):
    import streamlit as st
    from unittest.mock import patch
    import src.pdf_compare as pc

    class FakeLLM:
        def invoke(self, prompt):
            from tests.test_app import ANSWER
            return type("R", (), {"content": ANSWER})()

        def stream(self, prompt):
            yield self.invoke(prompt)

    files = [type("F", (), {"name": i.name, "getvalue": lambda self, n=i.name: n.encode()})() for i in idx]
    lookup = {i.name: i for i in idx}
    with patch("streamlit.file_uploader", return_value=files), \
         patch("src.pdf_compare.get_llm", return_value=FakeLLM()), \
         patch("src.pdf_compare.get_embeddings", return_value=(pc.TfidfEmbeddings(), "test")), \
         patch("src.pdf_compare.build_index", side_effect=lambda f, n, e: lookup[n]):
        src = open("app.py", encoding="utf-8").read()
        exec(compile(src, "app.py", "exec"), {"__name__": "__main__"})
