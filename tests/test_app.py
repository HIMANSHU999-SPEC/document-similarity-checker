from pathlib import Path

from streamlit.testing.v1 import AppTest

from cvchecker.auth import email_allowed

APP = str(Path(__file__).resolve().parents[1] / "app.py")
AUTH = {
    "redirect_uri": "http://localhost:8501/oauth2callback",
    "cookie_secret": "test-secret",
    "client_id": "id",
    "client_secret": "secret",
    "server_metadata_url": "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration",
}


def test_app_starts_without_login_configured():
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert "Document Similarity Checker" in at.title[0].value


def test_analyze_without_files_warns():
    at = AppTest.from_file(APP).run(timeout=30)
    next(b for b in at.button if b.label == "Analyze Documents").click().run(timeout=30)
    assert not at.exception
    assert any("at least two documents" in w.value for w in at.warning)


def test_signed_out_user_only_sees_sign_in():
    at = AppTest.from_file(APP)
    at.secrets["auth"] = AUTH
    at.run(timeout=30)
    assert not at.exception
    assert [b.label for b in at.button] == ["Sign in with Microsoft"]
    assert not any(b.label == "Analyze Documents" for b in at.button)


def test_email_domain_check():
    assert email_allowed("Staff@LAAT.ac.uk", ["laat.ac.uk"])
    assert not email_allowed("someone@gmail.com", ["laat.ac.uk"])
    assert not email_allowed("", ["laat.ac.uk"])
    assert email_allowed("anyone@anywhere.org", [])
