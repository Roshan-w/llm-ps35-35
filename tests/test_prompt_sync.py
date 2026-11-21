from pathlib import Path


def test_web_prompt_matches_app_prompt():
    root = Path(__file__).resolve().parents[1]
    assert (root / "web/api/_prompt.py").read_text(encoding="utf-8") == \
        (root / "src/prompt.py").read_text(encoding="utf-8")
