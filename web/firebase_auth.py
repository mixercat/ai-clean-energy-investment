"""ระบบสมาชิกด้วย Firebase Authentication (อีเมล + รหัสผ่าน) + เชื่อม Firestore
- login / สมัครสมาชิก / ลืมรหัสผ่าน ตรวจกับ Firebase จริง (REST API ใช้ FIREBASE_API_KEY)
- Firestore ใช้ service account (FIREBASE_CREDENTIALS_PATH) สำหรับเก็บข้อมูลสวนของผู้ใช้
ชื่อ class / render_login() / st.session_state.user เหมือนเดิม app.py จึงไม่ต้องแก้
st.session_state.user = {"uid", "email", "farm_name", "id_token"}
"""
import os

import firebase_admin
import requests
import streamlit as st
from firebase_admin import credentials, firestore

AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:{}?key={}"
DEFAULT_FARM = "สวนของฉัน"

ERRORS_TH = {
    "EMAIL_NOT_FOUND": "ไม่พบอีเมลนี้ในระบบ",
    "INVALID_PASSWORD": "รหัสผ่านไม่ถูกต้อง",
    "INVALID_LOGIN_CREDENTIALS": "อีเมลหรือรหัสผ่านไม่ถูกต้อง",
    "USER_DISABLED": "บัญชีนี้ถูกระงับ",
    "EMAIL_EXISTS": "อีเมลนี้สมัครไว้แล้ว ให้เข้าสู่ระบบแทน",
    "INVALID_EMAIL": "รูปแบบอีเมลไม่ถูกต้อง",
    "WEAK_PASSWORD": "รหัสผ่านต้องยาวอย่างน้อย 6 ตัวอักษร",
    "MISSING_PASSWORD": "กรุณากรอกรหัสผ่าน",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "ลองผิดหลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่",
    "OPERATION_NOT_ALLOWED": "ยังไม่ได้เปิดการเข้าสู่ระบบด้วยอีเมลใน Firebase Console",
    "CONFIGURATION_NOT_FOUND": "ยังไม่ได้เปิดใช้ Authentication ใน Firebase Console",
}


class AuthError(Exception):
    pass


def _auth_request(action, payload):
    api_key = os.getenv("FIREBASE_API_KEY")
    if not api_key:
        raise AuthError("ยังไม่ได้ระบุ FIREBASE_API_KEY ในไฟล์ .env")
    try:
        r = requests.post(AUTH_URL.format(action, api_key), json=payload, timeout=15)
    except requests.RequestException:
        raise AuthError("เชื่อมต่อ Firebase ไม่ได้ ตรวจสอบอินเทอร์เน็ต") from None
    data = r.json()
    if r.status_code != 200:
        code = data.get("error", {}).get("message", "UNKNOWN")
        key = code.split(" ")[0].split(":")[0]          # เช่น "WEAK_PASSWORD : ..."
        raise AuthError(ERRORS_TH.get(key, f"เข้าสู่ระบบไม่สำเร็จ ({code})"))
    return data


class FirebaseAuthService:
    def __init__(self):
        # Firestore: init ครั้งเดียว แต่ต้องตั้ง self.db ทุกครั้ง (Streamlit สร้าง object ใหม่ทุกครั้งที่กดปุ่ม)
        if not firebase_admin._apps:
            cred = None
            try:        # Streamlit Cloud: วางเนื้อหา serviceAccountKey.json ใน Secrets หัวข้อ [firebase_service_account]
                if "firebase_service_account" in st.secrets:
                    cred = credentials.Certificate(dict(st.secrets["firebase_service_account"]))
            except Exception:   # noqa: BLE001  ไม่มี secrets (รันในเครื่อง)
                pass
            if cred is None:
                cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")
                if not os.path.isabs(cred_path) and not os.path.exists(cred_path):
                    cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cred_path)
                if os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
            if cred is not None:
                firebase_admin.initialize_app(cred)
        self.db = firestore.client() if firebase_admin._apps else None

    # ------------------------------------------------------------------ Firebase Auth
    def sign_in(self, email, password):
        d = _auth_request("signInWithPassword",
                          {"email": email, "password": password, "returnSecureToken": True})
        return self._make_user(d)

    def sign_up(self, email, password, farm_name):
        d = _auth_request("signUp",
                          {"email": email, "password": password, "returnSecureToken": True})
        user = self._make_user(d, farm_name=farm_name or DEFAULT_FARM)
        if self.db:
            self.db.collection("users").document(user["uid"]).set({
                "email": user["email"], "farm_name": user["farm_name"],
                "created_at": firestore.SERVER_TIMESTAMP})
        return user

    def reset_password(self, email):
        _auth_request("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    def _make_user(self, d, farm_name=None):
        uid = d["localId"]
        if farm_name is None:
            farm_name = DEFAULT_FARM
            if self.db:
                doc = self.db.collection("users").document(uid).get()
                if doc.exists:
                    farm_name = doc.to_dict().get("farm_name", DEFAULT_FARM)
        return {"uid": uid, "email": d["email"], "farm_name": farm_name,
                "id_token": d["idToken"]}

    # ------------------------------------------------------------------ หน้าจอ
    def render_forms(self):
        """ฟอร์ม 3 แท็บ: เข้าสู่ระบบ / สมัครสมาชิก / ลืมรหัสผ่าน (วางที่ไหนก็ได้)"""
        tab_in, tab_up, tab_reset = st.tabs(["เข้าสู่ระบบ", "สมัครสมาชิก", "ลืมรหัสผ่าน"])

        with tab_in, st.form("login_form", border=False):
            email = st.text_input("อีเมล", placeholder="name@gmail.com")
            password = st.text_input("รหัสผ่าน", type="password")
            if st.form_submit_button("เข้าสู่ระบบ", type="primary", width="stretch"):
                if not email or not password:
                    st.error("กรุณากรอกอีเมลและรหัสผ่าน")
                else:
                    self._run(lambda: self.sign_in(email.strip(), password))

        with tab_up, st.form("signup_form", border=False):
            email = st.text_input("อีเมล", key="su_email", placeholder="name@gmail.com")
            farm = st.text_input("ชื่อสวน", placeholder="เช่น สวนทุเรียนบ้านนา (จันทบุรี)")
            p1 = st.text_input("ตั้งรหัสผ่าน (อย่างน้อย 6 ตัว)", type="password", key="su_p1")
            p2 = st.text_input("ยืนยันรหัสผ่าน", type="password", key="su_p2")
            st.caption("ตั้งรหัสผ่านใหม่สำหรับเว็บนี้ ไม่ต้องใช้รหัสผ่าน Gmail")
            if st.form_submit_button("สมัครสมาชิก", type="primary", width="stretch"):
                if not email or not p1:
                    st.error("กรุณากรอกอีเมลและรหัสผ่าน")
                elif p1 != p2:
                    st.error("รหัสผ่านทั้งสองช่องไม่ตรงกัน")
                else:
                    self._run(lambda: self.sign_up(email.strip(), p1, farm.strip()))

        with tab_reset, st.form("reset_form", border=False):
            email = st.text_input("อีเมลที่ใช้สมัคร", key="rs_email")
            if st.form_submit_button("ส่งลิงก์ตั้งรหัสผ่านใหม่", width="stretch"):
                try:
                    self.reset_password(email.strip())
                    st.success("ส่งลิงก์ไปที่อีเมลแล้ว (เช็กในกล่องจดหมายขยะด้วย)")
                except AuthError as e:
                    st.error(str(e))

    def render_login(self):
        """แบบเดิม: ฟอร์มใน sidebar คืนค่า True ถ้าเข้าสู่ระบบแล้ว"""
        if "user" not in st.session_state:
            st.session_state.user = None
        if st.session_state.user:
            return True
        with st.sidebar:
            st.subheader("🔐 เข้าสู่ระบบ")
            self.render_forms()
        return False

    @staticmethod
    def logout():
        st.session_state.user = None
        for k in [k for k in st.session_state if k.startswith(("ledger_", "ocr_", "chat_", "ai_"))]:
            del st.session_state[k]
        st.rerun()

    @staticmethod
    def _run(action):
        try:
            st.session_state.user = action()
            st.rerun()
        except AuthError as e:
            st.error(str(e))
