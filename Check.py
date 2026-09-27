from pathlib import Path
import pandas as pd

FOLDER = Path(__file__).parent
files = sorted(FOLDER.glob("*.csv"))
print("เจอไฟล์:", [f.name for f in files])

summary = []
for f in files:
    try:
        d = pd.read_csv(f, encoding="utf-8-sig")
    except UnicodeDecodeError:
        d = pd.read_csv(f, encoding="cp874")

    date_col = [c for c in d.columns if "วันที่" in c][0]
    d[date_col] = pd.to_datetime(d[date_col], format="mixed", dayfirst=False)
    price_cols = [c for c in d.columns if "ราคา" in c and "เฉลี่ย" not in c]
    prices = d[price_cols].apply(pd.to_numeric, errors="coerce")
    real = d[(prices > 0).any(axis=1)]
    per_year = real.groupby(real[date_col].dt.year).size()

    summary.append({
        "รหัส": d.iloc[0, 0],
        "ชื่อ": d.iloc[0, 1],
        "หมวด": d.iloc[0, 2],
        "แถวทั้งหมด": len(d),
        "วันที่มีราคาจริง": len(real),
        "เริ่ม": real[date_col].min().date(),
        "ล่าสุด": real[date_col].max().date(),
        "ปีที่มีข้อมูล": len(per_year),
        "ปีที่ >=60 วัน": int((per_year >= 60).sum()),
    })
    print(f"\n== {f.name}")
    print("วันที่มีราคาจริงต่อปี:", per_year.to_dict())

print("\n===== สรุป =====")
print(pd.DataFrame(summary).to_string(index=False))