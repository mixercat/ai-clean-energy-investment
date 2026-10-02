"""ตั้งค่าของผู้ใช้แต่ละคน: ข้อมูลสวน (ชื่อ จังหวัด พิกัด) + API key ของ AI ที่ผู้ใช้ใส่เอง
- เก็บใน Firestore users/{uid}.settings  (ถ้าไม่ได้เชื่อม Firestore เก็บใน session ชั่วคราว)
- API key ที่ผู้ใช้ใส่ในหน้าเว็บ ถูกเข้ารหัสก่อนบันทึก (ระบบสร้างกุญแจ .app_secret.key ให้เองอัตโนมัติ
  หรือกำหนด APP_SECRET_KEY ใน .env ก็ได้ ถ้าจะรันหลายเครื่องให้ใช้กุญแจเดียวกัน)
"""
import os
from pathlib import Path

import streamlit as st

# จังหวัดที่ปลูกทุเรียนมาก (พิกัดตัวเมือง ใช้ดึงพยากรณ์อากาศ)
PROVINCES = {
    "จันทบุรี": (12.6114, 102.1039), "ระยอง": (12.6814, 101.2816), "ตราด": (12.2428, 102.5175),
    "ปราจีนบุรี": (14.0509, 101.3717), "ชุมพร": (10.4930, 99.1800), "สุราษฎร์ธานี": (9.1382, 99.3217),
    "นครศรีธรรมราช": (8.4304, 99.9631), "ระนอง": (9.9529, 98.6085), "พังงา": (8.4509, 98.5255),
    "ยะลา": (6.5411, 101.2804), "นราธิวาส": (6.4255, 101.8253), "ปัตตานี": (6.8698, 101.2501),
    "สงขลา": (7.1898, 100.5954), "ศรีสะเกษ": (15.1186, 104.3220), "อุตรดิตถ์": (17.6201, 100.0993),
}
DEFAULT_PROVINCE = "จันทบุรี"
KEY_FIELDS = ["gemini_key", "groq_key", "azure_key"]          # ช่องที่ต้องเข้ารหัส
PLAIN_FIELDS = ["gemini_model", "azure_endpoint", "azure_deployment"]


SECRET_FILE = Path(__file__).with_name(".app_secret.key")


def _fernet():
    """กุญแจเข้ารหัส API key: ใช้ APP_SECRET_KEY ใน .env ถ้ามี ไม่งั้นสร้างไฟล์ .app_secret.key ให้เองครั้งแรก
    (ห้ามลบ/แชร์ไฟล์นี้ ถ้าหาย key ที่ผู้ใช้บันทึกไว้จะถอดรหัสไม่ได้ ผู้ใช้ต้องใส่ใหม่)"""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    secret = os.getenv("APP_SECRET_KEY")
    try:
        if not secret:
            if not SECRET_FILE.exists():
                SECRET_FILE.write_text(Fernet.generate_key().decode(), encoding="utf-8")
            secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        return Fernet(secret.encode())
    except Exception:   # noqa: BLE001  key ผิดรูปแบบ / เขียนไฟล์ไม่ได้
        return None


def can_persist_keys():
    return _fernet() is not None


def server_keys_allowed():
    """ALLOW_SERVER_KEYS=false -> ผู้ใช้ทุกคนต้องใส่ key ของตัวเอง (เหมาะตอนขายให้คนอื่น)"""
    return os.getenv("ALLOW_SERVER_KEYS", "true").strip().lower() not in ("0", "false", "no")


def mask(key):
    return "" if not key else (key[:4] + "••••" + key[-4:] if len(key) > 10 else "••••")


class SettingsService:
    def __init__(self, db, uid):
        self.db = db
        self.uid = uid
        self._skey = f"ledger_settings_{uid}"      # ขึ้นต้น ledger_ เพื่อให้ถูกล้างตอน logout
        self._keys_skey = f"ai_keys_{uid}"         # key ที่จำไว้แค่ใน session (กรณีไม่มี APP_SECRET_KEY)

    def _doc(self):
        return self.db.collection("users").document(self.uid)

    # ------------------------------------------------------------------ อ่าน
    def load(self):
        if self._skey in st.session_state:
            return dict(st.session_state[self._skey])
        raw = {}
        if self.db is not None:
            try:
                from firebase_auth import fs_call
                snap = fs_call(lambda: self._doc().get(timeout=8))
                raw = (snap.to_dict() or {}).get("settings", {}) if snap.exists else {}
            except Exception as e:   # noqa: BLE001
                from firebase_auth import _db_error
                _db_error(e)
        s = {"province": raw.get("province", DEFAULT_PROVINCE),
             "lat": raw.get("lat"), "lon": raw.get("lon"), "ai": {}}
        if s["lat"] is None or s["lon"] is None:
            s["lat"], s["lon"] = PROVINCES.get(s["province"], PROVINCES[DEFAULT_PROVINCE])
        ai_raw = raw.get("ai", {})
        f = _fernet()
        for k in KEY_FIELDS:
            enc = ai_raw.get(k)
            if enc and f:
                try:
                    s["ai"][k] = f.decrypt(enc.encode()).decode()
                except Exception:   # noqa: BLE001  เปลี่ยน APP_SECRET_KEY แล้ว -> ถอดไม่ได้
                    s["ai"][k] = ""
        for k in PLAIN_FIELDS:
            if ai_raw.get(k):
                s["ai"][k] = ai_raw[k]
        s["ai"].update({k: v for k, v in st.session_state.get(self._keys_skey, {}).items() if v})
        st.session_state[self._skey] = s
        return dict(s)

    def user_ai_keys(self):
        """dict ของ key ที่ผู้ใช้ใส่เอง หรือ None ถ้ายังไม่ได้ใส่ key ใดเลย"""
        ai = self.load()["ai"]
        has_any = ai.get("gemini_key") or ai.get("groq_key") or (
            ai.get("azure_key") and ai.get("azure_endpoint") and ai.get("azure_deployment"))
        return dict(ai) if has_any else None

    # ------------------------------------------------------------------ บันทึก
    def save_farm(self, farm_name, province, lat, lon):
        s = self.load()
        s.update(province=province, lat=float(lat), lon=float(lon))
        st.session_state[self._skey] = s
        if self.db is not None:
            self._doc().set({"farm_name": farm_name,
                             "settings": {"province": province, "lat": float(lat), "lon": float(lon)}}, merge=True)

    def save_ai(self, ai):
        """ai: dict ของค่าที่ผู้ใช้กรอก (ค่าว่าง = ลบ) -> True ถ้าจำ key ข้ามการเข้าสู่ระบบได้"""
        ai = {k: (v or "").strip() for k, v in ai.items()}
        s = self.load()
        s["ai"] = {k: v for k, v in ai.items() if v}
        st.session_state[self._skey] = s
        f = _fernet()
        if self.db is not None and f:
            stored = {k: (f.encrypt(ai[k].encode()).decode() if ai.get(k) else None) for k in KEY_FIELDS}
            stored.update({k: ai.get(k) or None for k in PLAIN_FIELDS})
            self._doc().set({"settings": {"ai": stored}}, merge=True)
            st.session_state.pop(self._keys_skey, None)
            return True
        # ไม่มี APP_SECRET_KEY หรือไม่ได้เชื่อม Firestore -> จำไว้แค่ session นี้ (ไม่บันทึก key แบบไม่เข้ารหัส)
        st.session_state[self._keys_skey] = {k: v for k, v in ai.items() if v}
        return False

    def clear_ai(self):
        return self.save_ai({k: "" for k in KEY_FIELDS + PLAIN_FIELDS})
