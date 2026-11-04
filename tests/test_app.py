from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_starts_without_errors():
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert "Document Similarity Checker" in at.title[0].value


def test_analyze_without_files_warns():
    at = AppTest.from_file(APP).run(timeout=30)
    at.button[0].click().run(timeout=30)
    assert not at.exception
    assert any("at least two documents" in w.value for w in at.warning)
