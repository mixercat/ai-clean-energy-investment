"""Firestore ผ่าน REST API (HTTPS ธรรมดา) แทนไลบรารี gRPC
เหตุผล: บน Streamlit Community Cloud การเชื่อม Firestore แบบ gRPC อาจค้างจนหมดเวลา
ส่วน HTTPS (แบบเดียวกับที่ใช้ login) ทำงานได้ปกติ

รองรับเฉพาะคำสั่งที่แอปนี้ใช้ โดยหน้าตาเหมือน firebase_admin.firestore:
    db.collection("users").document(uid).get(timeout=8)  -> snapshot (.exists, .id, .to_dict())
    doc.set(data, merge=True) / doc.delete() / doc.collection("transactions")
    col.stream() / col.add(data) / col.document()  /  db.batch().set(doc, data); batch.commit()
"""
import math
import random
import string
from datetime import date, datetime, timezone

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/datastore"]
API = "https://firestore.googleapis.com/v1"
TIMEOUT = 10
SERVER_TIMESTAMP = object()        # แทน firestore.SERVER_TIMESTAMP -> ใช้เวลาปัจจุบันของเครื่อง


# ---------------------------------------------------------------------- แปลงค่า Python <-> Firestore
def _enc(v):
    if v is SERVER_TIMESTAMP:
        v = datetime.now(timezone.utc)
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"nullValue": None} if math.isnan(v) else {"doubleValue": v}
    if isinstance(v, datetime):
        v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return {"timestampValue": v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    if isinstance(v, date):
        return {"stringValue": v.isoformat()}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _enc(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_enc(x) for x in v]}}
    if hasattr(v, "item"):                       # ตัวเลขจาก numpy/pandas
        return _enc(v.item())
    return {"stringValue": str(v)}


def _dec(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "timestampValue" in v:
        return v["timestampValue"]
    if "stringValue" in v:
        return v["stringValue"]
    if "mapValue" in v:
        return {k: _dec(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [_dec(x) for x in v["arrayValue"].get("values", [])]
    return None


def _leaf_paths(d, prefix=""):
    """field paths สำหรับ merge (เหมือน set(..., merge=True) ของ SDK)"""
    out = []
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            out += _leaf_paths(v, p)
        else:
            out.append(p)
    return out


def _new_id():
    return "".join(random.choices(string.ascii_letters + string.digits, k=20))


class FirestoreError(RuntimeError):
    pass


# ---------------------------------------------------------------------- ตัวแทน client / document / collection
class Snapshot:
    def __init__(self, doc_id, data, exists=True):
        self.id, self._data, self.exists = doc_id, data or {}, exists

    def to_dict(self):
        return dict(self._data) if self.exists else None


class RestFirestore:
    def __init__(self, info):
        self.project = info["project_id"]
        creds = service_account.Credentials.from_service_account_info(dict(info), scopes=SCOPES)
        self.http = AuthorizedSession(creds)
        self.root = f"projects/{self.project}/databases/(default)/documents"

    def _req(self, method, url, timeout=None, **kw):
        r = self.http.request(method, url, timeout=timeout or TIMEOUT, **kw)
        if r.status_code >= 400 and not (method == "GET" and r.status_code == 404):
            try:
                msg = r.json().get("error", {}).get("message", r.text)
            except ValueError:
                msg = r.text
            raise FirestoreError(f"{r.status_code}: {msg[:300]}")
        return r

    def collection(self, name):
        return CollectionRef(self, name)

    def batch(self):
        return Batch(self)


class DocumentRef:
    def __init__(self, db, path):
        self.db, self.path = db, path
        self.id = path.rsplit("/", 1)[-1]

    @property
    def url(self):
        return f"{API}/{self.db.root}/{self.path}"

    @property
    def name(self):
        return f"{self.db.root}/{self.path}"

    def collection(self, name):
        return CollectionRef(self.db, f"{self.path}/{name}")

    def get(self, timeout=None, **_):
        r = self.db._req("GET", self.url, timeout=timeout)
        if r.status_code == 404:
            return Snapshot(self.id, None, exists=False)
        js = r.json()
        return Snapshot(self.id, {k: _dec(v) for k, v in js.get("fields", {}).items()})

    def set(self, data, merge=False, timeout=None, **_):
        body = {"fields": {k: _enc(v) for k, v in data.items()}}
        params = [("updateMask.fieldPaths", p) for p in _leaf_paths(data)] if merge else None
        self.db._req("PATCH", self.url, timeout=timeout, json=body, params=params)

    def delete(self, timeout=None, **_):
        self.db._req("DELETE", self.url, timeout=timeout)


class CollectionRef:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, doc_id=None):
        return DocumentRef(self.db, f"{self.path}/{doc_id or _new_id()}")

    def add(self, data, timeout=None):
        ref = self.document()
        ref.set(data, timeout=timeout)
        return None, ref

    def stream(self, timeout=None, **_):
        url, token, out = f"{API}/{self.db.root}/{self.path}", None, []
        while True:
            params = {"pageSize": 300, **({"pageToken": token} if token else {})}
            js = self.db._req("GET", url, timeout=timeout, params=params).json()
            for d in js.get("documents", []):
                out.append(Snapshot(d["name"].rsplit("/", 1)[-1],
                                    {k: _dec(v) for k, v in d.get("fields", {}).items()}))
            token = js.get("nextPageToken")
            if not token:
                return out


class Batch:
    def __init__(self, db):
        self.db, self.writes = db, []

    def set(self, ref, data):
        self.writes.append({"update": {"name": ref.name, "fields": {k: _enc(v) for k, v in data.items()}}})

    def commit(self, timeout=None):
        if self.writes:
            self.db._req("POST", f"{API}/{self.db.root}:commit", timeout=timeout or 30,
                         json={"writes": self.writes})
        self.writes = []
