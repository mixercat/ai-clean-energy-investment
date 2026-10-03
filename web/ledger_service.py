"""สมุดบัญชีสวน: เก็บรายรับ-รายจ่ายของผู้ใช้แต่ละคน
- ถ้าเชื่อม Firestore ได้ -> users/{uid}/transactions/{id} (ข้อมูลอยู่ถาวร)
- ถ้ายังไม่เชื่อม -> เก็บใน session ชั่วคราว (หายเมื่อปิดเว็บ)
- ไฟล์แนบ (รูปใบชั่ง/บิล ฯลฯ) เก็บใน Firestore: users/{uid}/files/{id} (ย่อรูปก่อน) -> image_path = "fs:<id>:<นามสกุล>"
  (Streamlit Cloud ล้างดิสก์ทุกครั้งที่รีสตาร์ต จึงเก็บไฟล์บนเครื่องเซิร์ฟเวอร์ไม่ได้)
"""
import base64
import io
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

UPLOAD_ROOT = Path("uploads")
FS_PREFIX = "fs:"
MAX_FILE_B64 = 900_000        # เอกสาร Firestore จำกัด 1 MB ต่อชิ้น
EDITABLE = ["date", "type", "category", "amount", "party", "weight_kg", "note"]
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
            try:
                from firebase_auth import fs_call
                rows = fs_call(lambda: [{**d.to_dict(), "id": d.id} for d in self._col().stream(timeout=15)], 15)
            except Exception as e:   # noqa: BLE001
                from firebase_auth import _db_error
                _db_error(e)
                st.error(f"อ่านข้อมูลบัญชีจาก Firestore ไม่ได้: {str(e)[:160]}")
                rows = []
        else:
            rows = list(st.session_state.get(self._key, []))
        df = pd.DataFrame(rows, columns=COLUMNS) if rows else pd.DataFrame(columns=COLUMNS)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        df["weight_kg"] = pd.to_numeric(df["weight_kg"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for c in ("party", "note", "source"):           # ช่องข้อความที่ว่าง -> "" (กัน NaN ทำให้หน้าเว็บพัง)
            df[c] = df[c].map(lambda v: v if isinstance(v, str) else "")
        df["category"] = df["category"].map(lambda v: v if isinstance(v, str) and v else "อื่น ๆ")
        df["image_path"] = df["image_path"].where(df["image_path"].map(lambda v: isinstance(v, str) and bool(v)), None)
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

    def update(self, tid, changes):
        """แก้ไขรายการ (เฉพาะช่องใน EDITABLE)"""
        changes = {k: v for k, v in changes.items() if k in EDITABLE}
        if "date" in changes:
            changes["date"] = pd.to_datetime(changes["date"]).strftime("%Y-%m-%d")
        if "amount" in changes:
            changes["amount"] = float(changes["amount"] or 0)
        if "weight_kg" in changes and (changes["weight_kg"] is None or pd.isna(changes["weight_kg"])
                                       or not changes["weight_kg"]):
            changes["weight_kg"] = None
        changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if self.persistent:
            from firebase_auth import fs_call
            fs_call(lambda: self._col().document(tid).set(changes, merge=True))
        else:
            for t in st.session_state.get(self._key, []):
                if t["id"] == tid:
                    t.update(changes)

    def delete(self, tid, image_path=None):
        if self.persistent:
            from firebase_auth import fs_call
            fs_call(lambda: self._col().document(tid).delete())
        else:
            st.session_state[self._key] = [t for t in st.session_state.get(self._key, [])
                                           if t["id"] != tid]
        # รายการที่ไม่มีรูปจะได้ค่าว่าง/NaN จากตาราง -> ข้าม (เดิมทำให้ลบแล้วเกิด TypeError)
        if isinstance(image_path, str) and image_path.startswith(FS_PREFIX):
            self._delete_file(image_path)
        elif isinstance(image_path, str) and image_path and Path(image_path).exists():
            try:
                Path(image_path).unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ ไฟล์แนบ (รูป / PDF / Word / Excel)
    def _files(self):
        return self.db.collection("users").document(self.uid).collection("files")

    @staticmethod
    def _shrink(data, name):
        """ย่อรูปให้ยาวสุด 1600 px แล้วบีบอัด -> (bytes, นามสกุล) ไฟล์อื่นคืนตามเดิม"""
        ext = Path(name).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            return data, ext
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            for fmt, out_ext, kw in (("JPEG", ".jpg", {"quality": 72, "optimize": True}),
                                     ("WEBP", ".webp", {"quality": 72}), ("PNG", ".png", {"optimize": True})):
                try:
                    buf = io.BytesIO()
                    img.save(buf, format=fmt, **kw)
                    return buf.getvalue(), out_ext
                except (KeyError, OSError):
                    continue
        except Exception:   # noqa: BLE001  เปิดรูปไม่ได้ -> เก็บไฟล์เดิม
            pass
        return data, ext

    def save_image(self, uploaded_file):
        """บันทึกไฟล์แนบ -> path สำหรับเก็บในรายการ (Firestore: "fs:<id>:<ext>", ไม่มี Firestore: ไฟล์ในเครื่อง)"""
        raw = bytes(uploaded_file.getbuffer())
        if self.persistent:
            data, ext = self._shrink(raw, uploaded_file.name)
            b64 = base64.b64encode(data).decode()
            if len(b64) <= MAX_FILE_B64:
                fid = uuid.uuid4().hex[:16]
                try:
                    from firebase_auth import fs_call
                    fs_call(lambda: self._files().document(fid).set({
                        "name": uploaded_file.name, "ext": ext, "data": b64,
                        "created_at": datetime.now().isoformat(timespec="seconds")}), 20)
                    return f"{FS_PREFIX}{fid}:{ext}"
                except Exception as e:   # noqa: BLE001
                    print(f"[ledger] เก็บไฟล์ใน Firestore ไม่ได้ ใช้ไฟล์ในเครื่องแทน: {e!r}")
            else:
                print(f"[ledger] ไฟล์ {uploaded_file.name} ใหญ่เกินเก็บใน Firestore ({len(b64):,} ตัวอักษร)")
        folder = UPLOAD_ROOT / self.uid
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}{Path(uploaded_file.name).suffix}"
        path = folder / name
        path.write_bytes(raw)
        return str(path)

    @staticmethod
    def file_available(path):
        return isinstance(path, str) and bool(path) and (path.startswith(FS_PREFIX) or Path(path).exists())

    def load_file(self, path):
        """-> (bytes, ชื่อไฟล์) หรือ (None, None) ถ้าไม่มีแล้ว (จำไว้ใน session ไม่โหลดซ้ำ)"""
        if not isinstance(path, str) or not path:
            return None, None
        if not path.startswith(FS_PREFIX):
            p = Path(path)
            return (p.read_bytes(), p.name) if p.exists() else (None, None)
        cache = st.session_state.setdefault(f"ledger_files_{self.uid}", {})
        if path not in cache:
            fid, ext = path[len(FS_PREFIX):].split(":", 1) if ":" in path[len(FS_PREFIX):] else (path[3:], "")
            cache[path] = (None, None)
            if self.persistent:
                try:
                    from firebase_auth import fs_call
                    snap = fs_call(lambda: self._files().document(fid).get())
                    if snap.exists:
                        d = snap.to_dict()
                        stem = Path(d.get("name") or f"file{ext}").stem
                        cache[path] = (base64.b64decode(d["data"]), f"{stem}{d.get('ext') or ext}")
                except Exception as e:   # noqa: BLE001
                    print(f"[ledger] อ่านไฟล์แนบไม่ได้: {e!r}")
                    cache.pop(path, None)
        return cache.get(path, (None, None))

    def _delete_file(self, path):
        fid = path[len(FS_PREFIX):].split(":", 1)[0]
        st.session_state.get(f"ledger_files_{self.uid}", {}).pop(path, None)
        if self.persistent:
            try:
                from firebase_auth import fs_call
                fs_call(lambda: self._files().document(fid).delete())
            except Exception as e:   # noqa: BLE001
                print(f"[ledger] ลบไฟล์แนบไม่ได้: {e!r}")

    # ------------------------------------------------------------------ ฤดูกาล
    @staticmethod
    def season_of(dates, start_month=1):
        """ปี ค.ศ. ของ "ฤดู" ที่แต่ละวันอยู่ (ฤดูเริ่มเดือน start_month; ฤดู S จบในปี S)
        เช่น เริ่ม ก.ย.: ก.ย. 2025 - ส.ค. 2026 = ฤดู 2026 (พ.ศ. 2569)"""
        d = pd.to_datetime(pd.Series(dates), errors="coerce")
        start_month = int(start_month or 1)
        return (d.dt.year + (d.dt.month >= start_month).astype(int) * (1 if start_month > 1 else 0)).astype("Int64")

    @staticmethod
    def season_range(season, start_month=1):
        """(วันแรก, วันสุดท้าย) ของฤดู (ปี ค.ศ.)"""
        start_month = int(start_month or 1)
        first = pd.Timestamp(year=season - (1 if start_month > 1 else 0), month=start_month, day=1)
        return first, first + pd.DateOffset(years=1) - pd.Timedelta(days=1)

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
