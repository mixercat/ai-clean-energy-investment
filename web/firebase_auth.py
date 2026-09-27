import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os

class FirebaseAuthService:
    def __init__(self):
        # เชื่อมต่อ Firestore ถ้ามี service account
        if not firebase_admin._apps:
            cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                self.db = firestore.client()
            else:
                self.db = None

    def render_login(self):
        """ส่วนแสดงผลการเข้าสู่ระบบบน Streamlit Sidebar"""
        if "user" not in st.session_state:
            st.session_state.user = None

        if not st.session_state.user:
            with st.sidebar:
                st.subheader("🔐 เข้าสู่ระบบ")
                email = st.text_input("อีเมล")
                password = st.text_input("รหัสผ่าน", type="password")
                if st.button("เข้าสู่ระบบ", use_container_width=True):
                    # จำลองการยืนยันตัวตน (หรือต่อ Firebase Auth REST API)
                    if email and password:
                        st.session_state.user = {"email": email, "farm_name": "สวนทุเรียนเจริญสุข"}
                        st.rerun()
            return False
        else:
            with st.sidebar:
                st.write(f"👤 สวัสดี: **{st.session_state.user['email']}**")
                st.caption(f"สวน: {st.session_state.user.get('farm_name', '-')}")
                if st.button("ออกจากระบบ"):
                    st.session_state.user = None
                    st.rerun()
            return True