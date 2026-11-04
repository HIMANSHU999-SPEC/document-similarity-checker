import re
import time
from datetime import date
from urllib.parse import quote

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
BAD_CHARS = re.compile(r'[\"*:<>?/\\|#%\x00-\x1f]')
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SharePointError(Exception):
    pass


def safe_name(name: str) -> str:
    """A file or folder name SharePoint accepts."""
    name = BAD_CHARS.sub(" ", name)
    name = " ".join(name.split()).strip(" .")
    name = name.lstrip("~")
    return name[:120] or "Unnamed"


def current_intake(today=None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d} Intake"


def tenant_from_metadata_url(url: str) -> str:
    m = re.search(r"login\.microsoftonline\.com/([^/]+)/", url or "")
    return m.group(1) if m else ""


class SharePoint:
    def __init__(self, tenant, client_id, client_secret, hostname, site_path, folder="CVs", library="",
                 http=None):
        self.tenant, self.client_id, self.client_secret = tenant, client_id, client_secret
        self.hostname, self.site_path = hostname, "/" + site_path.strip("/")
        self.folder, self.library = folder.strip("/"), library
        self.http = http or requests.Session()
        self._token, self._token_expires = None, 0.0
        self._drive_id = None

    @property
    def site_url(self):
        return f"https://{self.hostname}{self.site_path}"

    def _check(self, response, what):
        if response.status_code < 400:
            return response
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code") or ""
        else:
            detail = (body.get("error_description") if isinstance(body, dict) else "") or error or response.text[:200]
        if response.status_code in (401, 403):
            raise SharePointError(
                f"SharePoint refused access while {what}. The app may not have been given access to "
                f"{self.site_url} yet (Sites.Selected with write permission). Details: {detail}")
        if response.status_code == 404:
            raise SharePointError(f"Not found while {what}. Check [sharepoint] in secrets.toml. Details: {detail}")
        raise SharePointError(f"SharePoint error {response.status_code} while {what}: {detail}")

    def _call(self, method, url, what, **kwargs):
        try:
            response = self.http.request(method, url, timeout=60, **kwargs)
        except requests.RequestException as e:
            raise SharePointError(f"Couldn't reach Microsoft while {what}: {e}") from e
        return self._check(response, what)

    def token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        response = self._call("POST", TOKEN_URL.format(tenant=self.tenant), "signing in to Microsoft", data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
        })
        data = response.json()
        self._token, self._token_expires = data["access_token"], time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _graph(self, method, path, what, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token()}"
        return self._call(method, GRAPH + path, what, headers=headers, **kwargs)

    def drive_id(self) -> str:
        if self._drive_id:
            return self._drive_id
        site = self._graph("GET", f"/sites/{self.hostname}:{self.site_path}", "finding the SharePoint site").json()
        if self.library:
            drives = self._graph("GET", f"/sites/{site['id']}/drives", "listing document libraries").json()["value"]
            match = [d for d in drives if d.get("name") == self.library]
            if not match:
                raise SharePointError(f"No document library called {self.library!r} on {self.site_url}.")
            self._drive_id = match[0]["id"]
        else:
            self._drive_id = self._graph("GET", f"/sites/{site['id']}/drive", "finding the document library").json()["id"]
        return self._drive_id

    @staticmethod
    def _path(*parts) -> str:
        return "/".join(quote(p, safe="") for part in parts for p in part.split("/") if p)

    def list_folders(self, *parts) -> list[str]:
        """Folder names inside a folder; empty if the folder doesn't exist yet."""
        path = self._path(*parts)
        try:
            data = self._graph("GET", f"/drives/{self.drive_id()}/root:/{path}:/children?$select=name,folder&$top=999",
                               "listing student folders").json()
        except SharePointError as e:
            if str(e).startswith("Not found"):
                return []
            raise
        return sorted(item["name"] for item in data.get("value", []) if "folder" in item)

    def ensure_folder(self, *parts) -> None:
        drive, done = self.drive_id(), []
        for part in [p for part in parts for p in part.split("/") if p]:
            parent = f"/drives/{drive}/root" + (f":/{self._path(*done)}:" if done else "")
            body = {"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            try:
                response = self.http.request("POST", f"{GRAPH}{parent}/children", timeout=60, json=body,
                                             headers={"Authorization": f"Bearer {self.token()}"})
            except requests.RequestException as e:
                raise SharePointError(f"Couldn't reach Microsoft while creating the folder {part!r}: {e}") from e
            if response.status_code != 409:  # 409: the folder already exists
                self._check(response, f"creating the folder {part!r}")
            done.append(part)

    def upload(self, data: bytes, file_name: str, *folder_parts) -> str:
        """Upload (or replace, keeping SharePoint's version history). Returns the file's web link."""
        self.ensure_folder(*folder_parts)
        path = self._path(*folder_parts, file_name)
        response = self._graph(
            "PUT", f"/drives/{self.drive_id()}/root:/{path}:/content?@microsoft.graph.conflictBehavior=replace",
            f"uploading {file_name}", data=data, headers={"Content-Type": DOCX_TYPE},
        )
        return response.json().get("webUrl", self.site_url)

    def check(self) -> str:
        """A quick test of the connection: returns the CV folder's location."""
        self.drive_id()
        self.list_folders(self.folder)
        return f"{self.site_url}, folder {self.folder}"


def from_secrets(secrets) -> SharePoint | None:
    sp = dict(secrets.get("sharepoint") or {})
    auth = dict(secrets.get("auth") or {})
    client_id = sp.get("client_id") or auth.get("client_id")
    client_secret = sp.get("client_secret") or auth.get("client_secret")
    tenant = sp.get("tenant_id") or tenant_from_metadata_url(auth.get("server_metadata_url", ""))
    if not (sp.get("hostname") and sp.get("site_path") and client_id and client_secret and tenant):
        return None
    return SharePoint(tenant, client_id, client_secret, sp["hostname"], sp["site_path"],
                      sp.get("folder", "CVs"), sp.get("library", ""))
