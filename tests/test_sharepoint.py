from datetime import date
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
import requests

from cvchecker import sharepoint as sp
from cvchecker.transcript_ui import folder_choices


class FakeHTTP:
    """Plays Microsoft's part: a token endpoint, the site, its library, and folders kept in memory."""

    def __init__(self, folders=(), fail=None):
        self.calls = []
        self.folders = set(folders)
        self.files = {}
        self.fail = fail or {}

    def _resp(self, status, body=None):
        return SimpleNamespace(status_code=status, json=lambda: body or {}, text=str(body))

    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url, kw))
        for needle, status in self.fail.items():
            if needle in url:
                if status == "network":
                    raise requests.ConnectionError("no route to host")
                return self._resp(status, {"error": {"code": "accessDenied", "message": "Access denied"}})
        if "oauth2/v2.0/token" in url:
            return self._resp(200, {"access_token": "tok", "expires_in": 3600})
        path = unquote(url.split("v1.0", 1)[-1])
        if method == "GET" and path.startswith("/sites/londonacademytec.sharepoint.com:/sites/CVcheckeradmission"):
            return self._resp(200, {"id": "site-1"})
        if method == "GET" and path == "/sites/site-1/drive":
            return self._resp(200, {"id": "drive-1"})
        if method == "GET" and path.endswith(":/children?$select=name,folder&$top=999"):
            parent = path.split("root:/", 1)[1].split(":/children")[0]
            if parent not in self.folders:
                return self._resp(404, {"error": {"code": "itemNotFound", "message": "The resource could not be found."}})
            kids = sorted({f[len(parent) + 1:].split("/")[0] for f in self.folders if f.startswith(parent + "/")})
            return self._resp(200, {"value": [{"name": k, "folder": {}} for k in kids] + [{"name": "notes.txt"}]})
        if method == "POST" and path.endswith("/children"):
            parent = path.split("root", 1)[1].removeprefix(":/").removesuffix(":/children").removesuffix("/children")
            full = f"{parent}/{kw['json']['name']}".strip("/")
            if full in self.folders:
                return self._resp(409, {"error": {"code": "nameAlreadyExists"}})
            self.folders.add(full)
            return self._resp(201, {"name": kw["json"]["name"]})
        if method == "PUT" and ":/content" in path:
            file_path = path.split("root:/", 1)[1].split(":/content")[0]
            self.files[file_path] = kw["data"]
            return self._resp(201, {"webUrl": f"https://londonacademytec.sharepoint.com/sites/CVcheckeradmission/{file_path}"})
        return self._resp(404, {"error": {"code": "unexpected", "message": f"{method} {path}"}})


def _sp(http):
    return sp.SharePoint("tenant-1", "id", "secret", "londonacademytec.sharepoint.com", "/sites/CVcheckeradmission",
                         http=http)


def test_upload_creates_folders_and_replaces_with_version_history():
    http = FakeHTTP(folders={"CVs"})
    link = _sp(http).upload(b"docx-bytes", "Aisha Khan CV.docx", "CVs", "2026-27 Intake", "Aisha Khan")
    assert http.files == {"CVs/2026-27 Intake/Aisha Khan/Aisha Khan CV.docx": b"docx-bytes"}
    assert {"CVs/2026-27 Intake", "CVs/2026-27 Intake/Aisha Khan"} <= http.folders
    put = next(c for c in http.calls if c[0] == "PUT")
    assert "conflictBehavior=replace" in put[1] and "%20" in put[1]
    assert put[2]["headers"]["Authorization"] == "Bearer tok"
    assert link.endswith("Aisha Khan CV.docx")


def test_existing_folders_are_reused_and_token_is_cached():
    http = FakeHTTP(folders={"CVs", "CVs/2026-27 Intake", "CVs/2026-27 Intake/Aisha Khan"})
    client = _sp(http)
    client.upload(b"1", "Aisha Khan CV.docx", "CVs", "2026-27 Intake", "Aisha Khan")
    client.upload(b"2", "Aisha Khan CV.docx", "CVs", "2026-27 Intake", "Aisha Khan")
    assert http.files["CVs/2026-27 Intake/Aisha Khan/Aisha Khan CV.docx"] == b"2"
    assert sum("oauth2" in c[1] for c in http.calls) == 1


def test_list_folders_returns_only_folders_and_empty_when_missing():
    http = FakeHTTP(folders={"CVs", "CVs/2026-27 Intake", "CVs/2026-27 Intake/Aisha Khan", "CVs/2026-27 Intake/Bilal Ahmed"})
    client = _sp(http)
    assert client.list_folders("CVs", "2026-27 Intake") == ["Aisha Khan", "Bilal Ahmed"]
    assert client.list_folders("CVs", "2030-31 Intake") == []


def test_missing_site_permission_gives_a_clear_message():
    with pytest.raises(sp.SharePointError, match="hasn't been given access|may not have been given access"):
        _sp(FakeHTTP(fail={"/sites/": 403})).upload(b"x", "a.docx", "CVs")


def test_bad_client_secret_gives_a_clear_message():
    http = FakeHTTP()
    http.fail = {"oauth2": 401}
    with pytest.raises(sp.SharePointError, match="signing in to Microsoft"):
        _sp(http).check()


def test_network_failure_gives_a_clear_message():
    with pytest.raises(sp.SharePointError, match="Couldn't reach Microsoft"):
        _sp(FakeHTTP(fail={"oauth2": "network"})).check()


@pytest.mark.parametrize("raw,clean", [
    ('Aisha "AJ" Khan: CV?', "Aisha AJ Khan CV"), ("  ..Name.. ", "Name"), ("~$temp", "$temp"), ("a/b\\c", "a b c"),
])
def test_safe_name(raw, clean):
    assert sp.safe_name(raw) == clean


@pytest.mark.parametrize("day,intake", [(date(2026, 11, 4), "2026-27 Intake"), (date(2027, 3, 1), "2026-27 Intake"),
                                        (date(2027, 8, 20), "2027-28 Intake")])
def test_current_intake(day, intake):
    assert sp.current_intake(day) == intake


def test_settings_come_from_secrets_and_reuse_the_sign_in_app():
    secrets = {"auth": {"client_id": "cid", "client_secret": "sec",
                        "server_metadata_url": "https://login.microsoftonline.com/tid-123/v2.0/.well-known/openid-configuration"},
               "sharepoint": {"hostname": "londonacademytec.sharepoint.com", "site_path": "/sites/CVcheckeradmission"}}
    client = sp.from_secrets(secrets)
    assert (client.tenant, client.client_id, client.folder) == ("tid-123", "cid", "CVs")
    assert sp.from_secrets({"sharepoint": {"hostname": "x"}}) is None


def test_folder_choices_never_guess():
    folders = ["Aisha Khan", "Aisha Noor Khan", "Bilal Ahmed", "Khan Aisha"]
    exact, alike = folder_choices("Aisha Khan", folders)
    assert exact == ["Aisha Khan", "Khan Aisha"]
    assert alike == ["Aisha Noor Khan"]
    assert folder_choices("Chen Li", folders) == ([], [])


def test_network_failure_while_creating_a_folder_is_a_readable_error():
    http = FakeHTTP(folders={"CVs"})
    http.fail = {"/children": "network"}
    with pytest.raises(sp.SharePointError, match="creating the folder"):
        _sp(http).upload(b"x", "Aisha Khan CV.docx", "CVs", "2026-27 Intake", "Aisha Khan")


def test_two_folders_with_the_students_name_need_a_choice():
    from streamlit.testing.v1 import AppTest

    def page():
        from types import SimpleNamespace
        from cvchecker.transcript_ui import save_section
        fake = SimpleNamespace(site_url="https://x/sites/y", folder="CVs",
                               list_folders=lambda *a: ["Aisha Khan", "Khan Aisha", "Bilal Ahmed"],
                               check=lambda: "ok", upload=lambda *a: "https://x/file")
        save_section(fake, "Aisha Khan", "Aisha Khan CV.docx", b"docx", True, "k", "body")

    at = AppTest.from_function(page).run()
    assert not at.exception
    assert at.radio[0].value is None
    assert any("More than one existing folder" in w.value for w in at.warning)
    assert not any(b.label.startswith("☁️ Save") for b in at.button)
