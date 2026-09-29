"""สมุดบัญชีสวน: เก็บรายรับ-รายจ่ายของผู้ใช้แต่ละคน
- ถ้าเชื่อม Firestore ได้ -> users/{uid}/transactions/{id} (ข้อมูลอยู่ถาวร)
- ถ้ายังไม่เชื่อม -> เก็บใน session ชั่วคราว (หายเมื่อปิดเว็บ)
"""
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

UPLOAD_ROOT = Path("uploads")
INCOME, EXPENSE = "รายรับ", "รายจ่าย"
INCOME_CATS = ["ขายทุเรียน", "อื่น ๆ"]
EXPENSE_CATS = ["ปุ๋ย", "ยา/สารเคมี", "ค่าแรง", "อุปกรณ์", "ขนส่ง", "น้ำ/ไฟ", "อื่น ๆ"]
COLUMNS = ["id", "date", "type", "category", "amount", "party", "weight_kg", "note",
           "image_path", "source"]


class LedgerService:
    def __init__(self, db, uid):
        self.db = db
        self.uid = uid
        self._key = f"ledger_{uid}"

    @property
    def persistent(self):
        return self.db is not None

    def _col(self):
        return self.db.collection("users").document(self.uid).collection("transactions")

    # ------------------------------------------------------------------ อ่าน/เขียน
    def list(self):
        if self.persistent:
            rows = [{**d.to_dict(), "id": d.id} for d in self._col().stream()]
        else:
            rows = list(st.session_state.get(self._key, []))
        df = pd.DataFrame(rows, columns=COLUMNS) if rows else pd.DataFrame(columns=COLUMNS)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        df["weight_kg"] = pd.to_numeric(df["weight_kg"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.sort_values("date", ascending=False).reset_index(drop=True)

    def add(self, entry):
        entry = {c: entry.get(c) for c in COLUMNS if c != "id"}
        entry["date"] = pd.to_datetime(entry["date"]).strftime("%Y-%m-%d")
        entry["amount"] = float(entry["amount"] or 0)
        entry["created_at"] = datetime.now().isoformat(timespec="seconds")
        if self.persistent:
            return self._col().add(entry)[1].id
        tid = uuid.uuid4().hex[:10]
        st.session_state.setdefault(self._key, []).append({**entry, "id": tid})
        return tid

    def add_many(self, entries, source="import"):
        """นำเข้าหลายรายการทีเดียว (Firestore ใช้ batch ครั้งละไม่เกิน 500) -> จำนวนที่บันทึก"""
        now = datetime.now().isoformat(timespec="seconds")
        clean = []
        for e in entries:
            e = {c: e.get(c) for c in COLUMNS if c != "id"}
            e["date"] = pd.to_datetime(e["date"]).strftime("%Y-%m-%d")
            e["amount"] = float(e["amount"] or 0)
            if e.get("weight_kg") is not None and pd.isna(e["weight_kg"]):
                e["weight_kg"] = None
            e["source"], e["created_at"] = source, now
            clean.append(e)
        if self.persistent:
            for i in range(0, len(clean), 450):
                batch = self.db.batch()
                for e in clean[i:i + 450]:
                    batch.set(self._col().document(), e)
                batch.commit()
        else:
            store = st.session_state.setdefault(self._key, [])
            store.extend({**e, "id": uuid.uuid4().hex[:10]} for e in clean)
        return len(clean)

    def delete(self, tid, image_path=None):
        if self.persistent:
            self._col().document(tid).delete()
        else:
            st.session_state[self._key] = [t for t in st.session_state.get(self._key, [])
                                           if t["id"] != tid]
        if image_path and Path(image_path).exists():
            Path(image_path).unlink()

    # ------------------------------------------------------------------ ไฟล์แนบ (รูป / PDF / Word / Excel)
    def save_image(self, uploaded_file):
        folder = UPLOAD_ROOT / self.uid
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}{Path(uploaded_file.name).suffix}"
        path = folder / name
        path.write_bytes(uploaded_file.getbuffer())
        return str(path)

    # ------------------------------------------------------------------ สรุป
    @staticmethod
    def summary(df):
        inc = df.loc[df["type"] == INCOME, "amount"].sum()
        exp = df.loc[df["type"] == EXPENSE, "amount"].sum()
        kg = pd.to_numeric(df.loc[df["type"] == INCOME, "weight_kg"], errors="coerce").sum()
        return {"income": float(inc), "expense": float(exp), "profit": float(inc - exp),
                "count": int(len(df)), "sold_kg": float(kg or 0)}

    @staticmethod
    def context_text(df, farm_name):
        """สรุปบัญชีเป็นข้อความ สำหรับส่งให้ Gemini"""
        s = LedgerService.summary(df)
        lines = [f"บัญชีของ{farm_name}:",
                 f"- รายรับรวม {s['income']:,.0f} บาท, รายจ่ายรวม {s['expense']:,.0f} บาท, "
                 f"กำไรสุทธิ {s['profit']:,.0f} บาท, จำนวน {s['count']} รายการ"]
        if s["sold_kg"]:
            lines.append(f"- ขายทุเรียนรวม {s['sold_kg']:,.0f} กก. "
                         f"เฉลี่ย {s['income'] / s['sold_kg']:,.1f} บาท/กก.")
        exp = df[df["type"] == EXPENSE].groupby("category")["amount"].sum().sort_values(ascending=False)
        if not exp.empty:
            lines.append("- รายจ่ายแยกหมวด: " + ", ".join(f"{k} {v:,.0f} บาท" for k, v in exp.items()))
        if not df.empty:
            lines.append("- รายการล่าสุด:")
            for _, r in df.head(10).iterrows():
                d = r["date"].strftime("%Y-%m-%d") if pd.notna(r["date"]) else "-"
                extra = f", {r['weight_kg']:,.0f} กก." if pd.notna(r["weight_kg"]) and r["weight_kg"] else ""
                lines.append(f"  {d} {r['type']} {r['category']} {r['amount']:,.0f} บาท"
                             f"{extra} ({r['party'] or r['note'] or '-'})")
        else:
            lines.append("- ยังไม่มีรายการบันทึก")
        return "\n".join(lines)
