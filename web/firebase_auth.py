"""ระบบสมาชิกด้วย Firebase Authentication (อีเมล + รหัสผ่าน) + เชื่อม Firestore
- login / สมัครสมาชิก / ลืมรหัสผ่าน ตรวจกับ Firebase จริง (REST API ใช้ FIREBASE_API_KEY)
- Firestore ใช้ service account (FIREBASE_CREDENTIALS_PATH) สำหรับเก็บข้อมูลสวนของผู้ใช้
ชื่อ class / render_login() / st.session_state.user เหมือนเดิม app.py จึงไม่ต้องแก้
st.session_state.user = {"uid", "email", "farm_name", "id_token"}
"""
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

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
    "API_KEY_INVALID": "FIREBASE_API_KEY ไม่ถูกต้อง (ตรวจในหน้า Secrets ว่าเป็น Web API Key ของ Firebase)",
    "API key not valid. Please pass a valid API key.": "FIREBASE_API_KEY ไม่ถูกต้อง (ตรวจในหน้า Secrets)",
    "API_KEY_HTTP_REFERRER_BLOCKED": "API key ถูกจำกัดให้ใช้ได้เฉพาะบางเว็บ — ปลดการจำกัด HTTP referrer ใน Google Cloud Console",
}


class AuthError(Exception):
    pass


def firebase_api_key():
    """อ่าน FIREBASE_API_KEY จาก .env หรือ Secrets (รวมกรณีเผลอวางไว้ใต้หัวข้อ [firebase_service_account])"""
    key = os.getenv("FIREBASE_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("FIREBASE_API_KEY", "") or \
                st.secrets.get("firebase_service_account", {}).get("FIREBASE_API_KEY", "")
        except Exception:   # noqa: BLE001
            key = ""
    return str(key).strip().strip('"').strip("'")


def _auth_request(action, payload):
    api_key = firebase_api_key()
    if not api_key:
        raise AuthError("ระบบยังไม่ได้ตั้งค่า FIREBASE_API_KEY (ในเครื่อง: ไฟล์ .env / บน Streamlit Cloud: หน้า Secrets)")
    try:
        r = requests.post(AUTH_URL.format(action, api_key), json=payload, timeout=15)
    except requests.RequestException as e:
        print(f"[firebase] {action} เชื่อมต่อไม่ได้: {e}")
        raise AuthError("เชื่อมต่อ Firebase ไม่ได้ ตรวจสอบอินเทอร์เน็ต") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        code = data.get("error", {}).get("message", f"HTTP {r.status_code}")
        print(f"[firebase] {action} ไม่สำเร็จ: {code}")          # ดูได้ใน Manage app -> logs
        key = code.split(" ")[0].split(":")[0]          # เช่น "WEAK_PASSWORD : ..."
        raise AuthError(ERRORS_TH.get(key, f"เข้าสู่ระบบไม่สำเร็จ ({code})"))
    return data


_POOL = ThreadPoolExecutor(max_workers=4)
FS_TIMEOUT = 10        # วินาที: ถ้า Firestore ไม่ตอบภายในนี้ ถือว่าใช้ไม่ได้ (ไม่ให้หน้าเว็บค้าง)


def fs_call(fn, timeout=FS_TIMEOUT):
    """เรียก Firestore แบบมีเวลาจำกัดจริง (timeout ของไลบรารีไม่ครอบคลุมขั้นขอสิทธิ์/ต่อเครือข่าย)"""
    fut = _POOL.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout:
        raise TimeoutError(f"Firestore ไม่ตอบภายใน {timeout} วินาที") from None


def firestore_ok():
    """False ถ้าเคยเชื่อม Firestore ไม่ได้ในรอบนี้ -> แอปจะใช้โหมดชั่วคราวแทน ไม่รอซ้ำทุกหน้า"""
    return not st.session_state.get("_fb_db_error")


def _db_error(e):
    """บันทึกปัญหา Firestore ไว้แสดงบนหน้าเว็บ + log (Manage app)"""
    msg = str(e)
    print(f"[firebase] Firestore ใช้ไม่ได้: {e!r}")
    if "PermissionDenied" in type(e).__name__ or "403" in msg or "permission" in msg.lower():
        hint = "service account ไม่มีสิทธิ์ หรือเป็นของคนละโปรเจกต์กับ FIREBASE_API_KEY"
    elif "NotFound" in type(e).__name__ or "404" in msg or "does not exist" in msg:
        hint = "ยังไม่ได้สร้าง Firestore Database ในโปรเจกต์นี้ (Firebase Console → Build → Firestore Database → Create)"
    elif "Deadline" in type(e).__name__ or "timeout" in msg.lower() or "ไม่ตอบภายใน" in msg or "504" in msg:
        hint = "เชื่อมต่อ Firestore ไม่ทันเวลา"
    else:
        hint = msg[:150]
    st.session_state["_fb_db_error"] = hint


class FirebaseAuthService:
    def __init__(self):
        # Firestore: init ครั้งเดียว แต่ต้องตั้ง self.db ทุกครั้ง (Streamlit สร้าง object ใหม่ทุกครั้งที่กดปุ่ม)
        if not firebase_admin._apps:
            cred = None
            try:        # Streamlit Cloud: วางเนื้อหา serviceAccountKey.json ใน Secrets หัวข้อ [firebase_service_account]
                if "firebase_service_account" in st.secrets:
                    cred = credentials.Certificate(dict(st.secrets["firebase_service_account"]))
            except Exception as e:   # noqa: BLE001  ไม่มี secrets (รันในเครื่อง) หรือข้อมูลใน Secrets ผิด
                if "firebase_service_account" in str(e) or "private_key" in str(e) or "Certificate" in str(e):
                    print(f"[firebase] อ่าน [firebase_service_account] ใน Secrets ไม่ได้: {e}")
                    st.session_state["_fb_cred_error"] = str(e)[:200]
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
        if self.db and firestore_ok():
            try:
                fs_call(lambda: self.db.collection("users").document(user["uid"]).set({
                    "email": user["email"], "farm_name": user["farm_name"],
                    "created_at": firestore.SERVER_TIMESTAMP}, timeout=8))
            except Exception as e:   # noqa: BLE001
                _db_error(e)
        return user

    def reset_password(self, email):
        _auth_request("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    def _make_user(self, d, farm_name=None):
        uid = d["localId"]
        if farm_name is None:
            farm_name = DEFAULT_FARM
            if self.db and firestore_ok():
                try:     # จำกัดเวลา ไม่ให้หน้าค้างถ้าเชื่อม Firestore ไม่ได้
                    doc = fs_call(lambda: self.db.collection("users").document(uid).get(timeout=8))
                    if doc.exists:
                        farm_name = doc.to_dict().get("farm_name", DEFAULT_FARM)
                except Exception as e:   # noqa: BLE001
                    _db_error(e)
        return {"uid": uid, "email": d["email"], "farm_name": farm_name,
                "id_token": d["idToken"]}

    # ------------------------------------------------------------------ หน้าจอ
    def render_forms(self):
        """ฟอร์ม 3 แท็บ: เข้าสู่ระบบ / สมัครสมาชิก / ลืมรหัสผ่าน (วางที่ไหนก็ได้)"""
        if not firebase_api_key():
            st.error("ระบบยังไม่ได้ตั้งค่า FIREBASE_API_KEY — เข้าสู่ระบบ/สมัครไม่ได้ "
                     "(บน Streamlit Cloud ให้ใส่ในหน้า Settings → Secrets ไว้บรรทัดบนสุด ก่อนหัวข้อ [firebase_service_account])")
        if self.db is None:
            st.warning("ยังไม่ได้เชื่อม Firestore — " + (st.session_state.get("_fb_cred_error")
                       or "ตรวจหัวข้อ [firebase_service_account] ใน Secrets หรือไฟล์ serviceAccountKey.json"))
        tab_in, tab_up, tab_reset = st.tabs(["เข้าสู่ระบบ", "สมัครสมาชิก", "ลืมรหัสผ่าน"])

        with tab_in, st.form("login_form", border=False):
            email = st.text_input("อีเมล", placeholder="name@gmail.com", key="li_email")
            password = st.text_input("รหัสผ่าน", type="password", key="li_pw")
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

    def render_diagnostics(self):
        """ตัวช่วยหาสาเหตุเมื่อเข้าสู่ระบบไม่ได้ (ไม่แสดง key เต็ม)"""
        with st.expander("เข้าสู่ระบบไม่ได้? ตรวจระบบ", icon=":material/troubleshoot:"):
            st.caption("ใช้อีเมลและรหัสผ่านที่กรอกในแท็บเข้าสู่ระบบ แล้วตรวจทีละขั้น")
            if not st.button("เริ่มตรวจ", key="diag_btn", width="stretch"):
                return
            out = []
            key = firebase_api_key()
            ok_key = key.startswith("AIza") and len(key) >= 35
            out.append((ok_key, "FIREBASE_API_KEY", f"{key[:6]}…{key[-4:]} (ยาว {len(key)} ตัว)" if key else "ไม่พบ"))
            api_project = None
            if key:
                try:
                    r = requests.get(f"https://identitytoolkit.googleapis.com/v1/projects?key={key}", timeout=10)
                    api_project = r.json().get("projectId") if r.ok else None
                    out.append((r.ok, "โปรเจกต์ของ API key", api_project or r.text[:150]))
                except Exception as e:   # noqa: BLE001
                    out.append((False, "โปรเจกต์ของ API key", str(e)[:150]))
            sa_project = None
            try:
                sa_project = st.secrets.get("firebase_service_account", {}).get("project_id")
            except Exception:   # noqa: BLE001
                pass
            if sa_project:
                out.append((sa_project == api_project, "project_id ของ service account",
                             sa_project + ("" if sa_project == api_project else " ← ไม่ตรงกับโปรเจกต์ของ API key")))
            em, pw = st.session_state.get("li_email", "").strip(), st.session_state.get("li_pw", "")
            uid = None
            if em and pw and key:
                try:
                    r = requests.post(AUTH_URL.format("signInWithPassword", key),
                                      json={"email": em, "password": pw, "returnSecureToken": True}, timeout=15)
                    js = r.json()
                    uid = js.get("localId")
                    out.append((r.ok, "ตรวจรหัสผ่าน", "ผ่าน" if r.ok else js.get("error", {}).get("message", r.text[:150])))
                except Exception as e:   # noqa: BLE001
                    out.append((False, "ตรวจรหัสผ่าน", str(e)[:150]))
            else:
                out.append((None, "ตรวจรหัสผ่าน", "ข้าม — กรอกอีเมลและรหัสผ่านในแท็บเข้าสู่ระบบก่อน"))
            for ok, name, msg in out:          # แสดงผลส่วนแรกก่อน เผื่อ Firestore ช้า
                st.markdown(f"{'✅' if ok else ('➖' if ok is None else '❌')} **{name}** — {msg}")
            shown = len(out)
            if self.db is None:
                out.append((False, "Firestore", st.session_state.get("_fb_cred_error") or "ไม่ได้เชื่อม (ไม่มี service account)"))
            else:
                try:
                    fs_call(lambda: self.db.collection("users").document(uid or "diagnostic").get(timeout=8))
                    out.append((True, "Firestore", "อ่านข้อมูลได้"))
                except Exception as e:   # noqa: BLE001
                    out.append((False, "Firestore", f"{type(e).__name__}: {str(e)[:160]}"))
            for ok, name, msg in out[shown:]:
                st.markdown(f"{'✅' if ok else ('➖' if ok is None else '❌')} **{name}** — {msg}")

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
            with st.spinner("กำลังตรวจสอบกับ Firebase..."):
                st.session_state.user = action()
            st.rerun()
        except AuthError as e:
            st.error(str(e))
        except Exception as e:   # noqa: BLE001  เช่น Firestore ปฏิเสธสิทธิ์ -> แสดงให้เห็น ไม่เงียบ
            print(f"[firebase] ผิดพลาดหลังเข้าสู่ระบบ: {e!r}")
            st.error(f"เข้าสู่ระบบไม่สำเร็จ: {str(e)[:200]}")
