"""อ่านไฟล์ที่ผู้ใช้อัปโหลด: รูป / PDF / Word / Excel / CSV
- ไฟล์เอกสาร (รูป PDF Word) -> ส่งให้ AI อ่านเป็นใบชั่ง/บิล 1 ใบ
- ไฟล์ตาราง (Excel CSV) -> แปลงเป็นรายการบัญชีหลายรายการ แล้วนำเข้าทีเดียว
"""
import io
import re
from pathlib import Path

import pandas as pd

INCOME, EXPENSE = "รายรับ", "รายจ่าย"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp", "pdf", "docx", "xlsx", "csv"]
MAX_TEXT = 30_000            # ส่งข้อความให้ AI ไม่เกินนี้


def file_kind(name):
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    return {".pdf": "pdf", ".docx": "word", ".xlsx": "table", ".csv": "table"}.get(ext, "unknown")


def is_image_path(path):
    return Path(str(path)).suffix.lower() in IMAGE_EXT


# ---------------------------------------------------------------------- PDF / Word
def pdf_info(data):
    """คืน (จำนวนหน้า, ข้อความทั้งหมด) — PDF ที่สแกนมาเป็นรูปจะได้ข้อความว่าง"""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return len(reader.pages), text.strip()


def docx_text(data):
    """ดึงข้อความและตารางจาก Word (.docx) เรียงตามลำดับในเอกสาร"""
    from docx import Document
    doc = Document(io.BytesIO(data))
    lines = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = "".join(n.text or "" for n in block.iter() if n.tag.endswith("}t")).strip()
            if t:
                lines.append(t)
        elif tag == "tbl":
            for row in block.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for cell in row.iterchildren():
                        if cell.tag.endswith("}tc"):
                            cells.append("".join(n.text or "" for n in cell.iter()
                                                 if n.tag.endswith("}t")).strip())
                    if any(cells):
                        lines.append(" | ".join(cells))
    return "\n".join(lines)


# ---------------------------------------------------------------------- Excel / CSV
def sheet_names(data, name):
    if Path(name).suffix.lower() != ".xlsx":
        return []
    return pd.ExcelFile(io.BytesIO(data), engine="openpyxl").sheet_names


def read_raw(data, name, sheet=None):
    """อ่านตารางแบบยังไม่กำหนดหัวตาราง (header=None)"""
    if Path(name).suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp874", "utf-16"):
            try:
                return pd.read_csv(io.BytesIO(data), header=None, dtype=object, encoding=enc,
                                   sep=None, engine="python")
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError("อ่านไฟล์ CSV ไม่ได้ (รหัสภาษาไม่รองรับ) ลองบันทึกเป็น CSV UTF-8 ใหม่")
    return pd.read_excel(io.BytesIO(data), sheet_name=sheet or 0, header=None, dtype=object,
                         engine="openpyxl")


def guess_header_row(raw, max_rows=15):
    """เดาแถวหัวตาราง = แถวแรกที่มีข้อความหลายช่องและไม่ใช่ตัวเลข (ข้ามแถวชื่อรายงานด้านบน)"""
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    need = max(2, int(raw.shape[1] * 0.5))
    for i, (_, row) in enumerate(raw.head(max_rows).iterrows()):
        vals = [v for v in row if pd.notna(v) and str(v).strip()]
        texty = [v for v in vals if not _to_number(v) and not isinstance(v, (pd.Timestamp,))]
        if len(vals) >= need and len(texty) >= need:
            return i
    return 0


def apply_header(raw, header_row):
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    header = [str(v).strip() if pd.notna(v) and str(v).strip() else f"คอลัมน์ {j + 1}"
              for j, v in enumerate(raw.iloc[header_row])]
    seen = {}
    for j, h in enumerate(header):              # ชื่อซ้ำ -> เติมเลขท้าย
        if h in seen:
            seen[h] += 1
            header[j] = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
    df = raw.iloc[header_row + 1:].copy()
    df.columns = header
    return df.dropna(how="all").reset_index(drop=True)


FIELD_KEYWORDS = {
    "date": ["วันที่", "วัน", "date", "เดือน"],
    "amount": ["จำนวนเงิน", "เป็นเงิน", "ยอดเงิน", "ยอดรวม", "รวมเงิน", "ยอด", "เงิน", "amount", "total", "บาท"],
    "income": ["รายรับ", "รับ", "income", "credit"],
    "expense": ["รายจ่าย", "จ่าย", "expense", "debit"],
    "type": ["ประเภท", "type", "รับ/จ่าย", "รายการรับจ่าย"],
    "category": ["หมวด", "หมวดหมู่", "category"],
    "party": ["ล้ง", "ผู้ซื้อ", "ร้าน", "ผู้รับเงิน", "ผู้ขาย", "คู่ค้า", "party", "buyer"],
    "weight": ["น้ำหนัก", "กก", "kg", "กิโล"],
    "note": ["หมายเหตุ", "รายละเอียด", "รายการ", "note", "description", "memo"],
}


def guess_columns(columns):
    """เดาว่าคอลัมน์ไหนคืออะไร จากชื่อหัวตาราง (ผู้ใช้แก้ได้ในหน้าเว็บ)"""
    cols = list(columns)
    low = {c: str(c).lower().replace(" ", "") for c in cols}
    used, out = set(), {}
    exclude = {"weight": ["ราคา", "บาท"], "amount": ["/กก", "ต่อกก", "ราคาต่อ"], "date": ["วันละ"]}
    for field in ["date", "type", "category", "weight", "party", "income", "expense", "amount", "note"]:
        for kw in FIELD_KEYWORDS[field]:
            hit = next((c for c in cols if c not in used and kw.lower().replace(" ", "") in low[c]
                        and not any(x in low[c] for x in exclude.get(field, []))), None)
            if hit is not None:
                out[field] = hit
                used.add(hit)
                break
    # ถ้ามีคอลัมน์รายรับ+รายจ่ายแยกกัน ไม่ต้องใช้คอลัมน์จำนวนเงินเดียว
    if "income" in out and "expense" in out:
        out.pop("amount", None)
    else:
        for k in ("income", "expense"):          # มีแค่อันเดียว -> ใช้เป็นจำนวนเงิน
            if k in out and "amount" not in out:
                out["amount"] = out.pop(k)
            out.pop(k, None)
    return out


def _to_number(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "").replace("฿", "").replace("บาท", "").replace("กก.", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def parse_date(v):
    """รองรับวันที่จาก Excel, dd/mm/yyyy, พ.ศ. (ลบ 543 ให้เอง) และชื่อเดือนไทยย่อ"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"):
        d = pd.Timestamp(v)
    elif isinstance(v, (int, float)) and 20000 < float(v) < 80000:     # เลขวันที่แบบ Excel
        d = pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))
    else:
        s = str(v).strip()
        months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        for i, m in enumerate(months):
            if m in s:
                s = s.replace(m, f"/{i + 1}/").replace(" ", "")
                s = re.sub(r"/+", "/", s)
                break
        m = re.search(r"(\d{4})", s)
        if m and int(m.group(1)) > 2400:
            s = s.replace(m.group(1), str(int(m.group(1)) - 543))
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", s):      # ปี 2 หลัก เช่น 20/5/69 -> พ.ศ. 2569
            dd, mm, yy = s.split("/")
            yy = int(yy) + (2500 if int(yy) >= 50 else 2600) - 543
            s = f"{dd}/{mm}/{yy}"
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}", s):            # แบบ ISO ปี-เดือน-วัน
            d = pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce")
        else:
            d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.isna(d):
        return pd.NaT
    if d.year > 2400:
        d = d - pd.DateOffset(years=543)
    return d.normalize()


def _type_from_text(v):
    s = str(v or "").lower()
    if any(k in s for k in ["รายจ่าย", "จ่าย", "ซื้อ", "expense", "debit"]):
        return EXPENSE
    if any(k in s for k in ["รายรับ", "รับ", "ขาย", "income", "credit"]):
        return INCOME
    return None


CATEGORY_RULES = [("ค่าแรง", ["ค่าแรง", "ค่าจ้าง", "คนงาน", "แรงงาน", "ค่าตัด"]),     # เช็กก่อน เช่น "ค่าแรงพ่นยา"
                  ("ปุ๋ย", ["ปุ๋ย", "ขี้ไก่", "ขี้วัว", "มูลสัตว์"]),
                  ("ยา/สารเคมี", ["ยา", "สาร", "ฮอร์โมน", "เคมี", "พ่น"]),
                  ("ขนส่ง", ["ขนส่ง", "ค่ารถ", "น้ำมัน", "ขน"]),
                  ("น้ำ/ไฟ", ["ไฟฟ้า", "ค่าไฟ", "ค่าน้ำ", "ประปา", "น้ำ/ไฟ"]),
                  ("อุปกรณ์", ["อุปกรณ์", "เครื่อง", "สายยาง", "ปั๊ม", "กรรไกร", "ตะกร้า", "เชือก"])]


def guess_category(ttype, *texts):
    s = " ".join(str(t) for t in texts if t is not None and not (isinstance(t, float) and pd.isna(t)))
    if ttype == INCOME:
        return "ขายทุเรียน" if (not s.strip() or any(k in s for k in ["ทุเรียน", "ขาย", "ล้ง", "หมอนทอง", "ชะนี"])) \
            else "อื่น ๆ"
    for cat, kws in CATEGORY_RULES:
        if any(k in s for k in kws):
            return cat
    return "อื่น ๆ"


TYPE_MODES = ["มีคอลัมน์บอกประเภท", "ดูจากเครื่องหมาย (ติดลบ = รายจ่าย)", "ทั้งหมดเป็นรายรับ", "ทั้งหมดเป็นรายจ่าย",
              "มีคอลัมน์รายรับ/รายจ่ายแยกกัน"]


def build_entries(df, mapping, type_mode, expense_cats, income_cats):
    """แปลงตารางเป็นรายการบัญชี -> (DataFrame รายการที่ใช้ได้, จำนวนแถวที่ข้าม, เหตุผล)"""
    rows, skipped = [], {"ไม่มีวันที่": 0, "ไม่มีจำนวนเงิน": 0, "ไม่รู้ประเภท": 0}
    get = lambda r, f: r[mapping[f]] if mapping.get(f) else None   # noqa: E731
    for _, r in df.iterrows():
        d = parse_date(get(r, "date"))
        if pd.isna(d):
            skipped["ไม่มีวันที่"] += 1
            continue
        if type_mode == "มีคอลัมน์รายรับ/รายจ่ายแยกกัน":
            inc, exp = _to_number(get(r, "income")), _to_number(get(r, "expense"))
            if inc:
                ttype, amount = INCOME, abs(inc)
            elif exp:
                ttype, amount = EXPENSE, abs(exp)
            else:
                skipped["ไม่มีจำนวนเงิน"] += 1
                continue
        else:
            amount = _to_number(get(r, "amount"))
            if not amount:
                skipped["ไม่มีจำนวนเงิน"] += 1
                continue
            if type_mode == "ทั้งหมดเป็นรายรับ":
                ttype = INCOME
            elif type_mode == "ทั้งหมดเป็นรายจ่าย":
                ttype = EXPENSE
            elif type_mode.startswith("ดูจากเครื่องหมาย"):
                ttype = EXPENSE if amount < 0 else INCOME
            else:
                ttype = _type_from_text(get(r, "type"))
                if ttype is None:
                    ttype = EXPENSE if amount < 0 else None
                if ttype is None:
                    skipped["ไม่รู้ประเภท"] += 1
                    continue
            amount = abs(amount)
        cat_raw = get(r, "category")
        cats = income_cats if ttype == INCOME else expense_cats
        cat = str(cat_raw).strip() if cat_raw is not None and str(cat_raw).strip() in cats else \
            guess_category(ttype, cat_raw, get(r, "note"), get(r, "party"))
        w = _to_number(get(r, "weight")) if ttype == INCOME else None
        clean = lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()  # noqa: E731
        rows.append({"date": d, "type": ttype, "category": cat, "amount": round(amount, 2),
                     "party": clean(get(r, "party")), "weight_kg": abs(w) if w else None,
                     "note": clean(get(r, "note"))})
    return pd.DataFrame(rows), {k: v for k, v in skipped.items() if v}


def mark_duplicates(entries, existing):
    """True = มีรายการวันเดียวกัน ประเภทเดียวกัน จำนวนเงินเท่ากันอยู่ในบัญชีแล้ว"""
    if entries.empty or existing.empty:
        return pd.Series(False, index=entries.index)
    key = lambda d, t, a: f"{pd.Timestamp(d):%Y-%m-%d}|{t}|{round(float(a), 2)}"   # noqa: E731
    have = {key(d, t, a) for d, t, a in zip(existing["date"], existing["type"], existing["amount"])
            if pd.notna(d)}
    return pd.Series([key(d, t, a) in have for d, t, a in
                      zip(entries["date"], entries["type"], entries["amount"])], index=entries.index)


def table_as_text(df, max_rows=200):
    """แปลงตารางเป็นข้อความ สำหรับให้ AI อ่านเป็นเอกสาร 1 ใบ"""
    return df.head(max_rows).fillna("").astype(str).to_csv(index=False, sep="|")[:MAX_TEXT]
