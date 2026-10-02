"""ประวัติการสนทนากับผู้ช่วย AI
- Firestore: users/{uid}/chats/{chat_id} = {title, updated_at, messages: [{role, content}]}
- ไม่ได้เชื่อม Firestore -> เก็บใน session ชั่วคราว
"""
import uuid
from datetime import datetime, timezone

import streamlit as st

MAX_CHATS = 30          # แสดงในแถบด้านข้างไม่เกินนี้
MAX_MESSAGES = 60       # เก็บข้อความต่อบทสนทนาไม่เกินนี้ (กันเอกสารใหญ่เกิน)


def _now():
    return datetime.now(timezone.utc).isoformat()


class ChatService:
    def __init__(self, db, uid):
        self.db, self.uid = db, uid
        self._key = f"chat_store_{uid}"       # ขึ้นต้น chat_ -> ถูกล้างตอน logout

    def _col(self):
        return self.db.collection("users").document(self.uid).collection("chats")

    def _call(self, fn, default=None):
        from firebase_auth import _db_error, fs_call
        try:
            return fs_call(fn)
        except Exception as e:   # noqa: BLE001
            _db_error(e)
            return default

    # ------------------------------------------------------------------ อ่าน
    def list(self):
        """[{id, title, updated_at}] ใหม่สุดก่อน (จำไว้ใน session ไม่อ่านซ้ำทุกครั้งที่กดปุ่ม)"""
        if self._key not in st.session_state:
            chats = {}
            if self.db is not None:
                for d in self._call(lambda: self._col().stream(timeout=10), []) or []:
                    data = d.to_dict() or {}
                    chats[d.id] = {"title": data.get("title", "บทสนทนา"),
                                   "updated_at": data.get("updated_at", ""),
                                   "messages": data.get("messages") or []}
            st.session_state[self._key] = chats
        items = [{"id": k, **v} for k, v in st.session_state[self._key].items()]
        return sorted(items, key=lambda c: c.get("updated_at") or "", reverse=True)[:MAX_CHATS]

    def messages(self, chat_id):
        return list(st.session_state.get(self._key, {}).get(chat_id, {}).get("messages", []))

    # ------------------------------------------------------------------ เขียน
    def new_id(self):
        return uuid.uuid4().hex[:12]

    def save(self, chat_id, messages):
        messages = [{"role": m["role"], "content": m["content"]} for m in messages][-MAX_MESSAGES:]
        first_q = next((m["content"] for m in messages if m["role"] == "user"), "บทสนทนา")
        title = first_q.strip().replace("\n", " ")
        title = title[:42] + ("…" if len(title) > 42 else "")
        store = st.session_state.setdefault(self._key, {})
        old = store.get(chat_id, {})
        rec = {"title": old.get("title") or title, "updated_at": _now(), "messages": messages}
        store[chat_id] = rec
        if self.db is not None:
            self._call(lambda: self._col().document(chat_id).set(rec, timeout=10))

    def delete(self, chat_id):
        st.session_state.get(self._key, {}).pop(chat_id, None)
        if self.db is not None:
            self._call(lambda: self._col().document(chat_id).delete(timeout=10))
