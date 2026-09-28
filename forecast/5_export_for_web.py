"""ขั้นที่ 5: รวมผลทั้งหมดเป็นไฟล์เดียวให้ทีมเว็บ -> outputs/forecast.json
 
    python 5_export_for_web.py
 
ใช้วิธีที่ทดสอบแล้วว่าเชื่อถือได้ (ดูผลขั้นที่ 3–4):
    ช่วงราคาสัปดาห์หน้า   = ราคาล่าสุด ± error จริงในอดีต (naive, ครอบคลุมราคาจริง ~80%)
    โอกาสราคาลงใน 1 สัปดาห์ = % ที่ราคาเคยลงในช่วงเดียวกันของฤดู (seasonal)
                             (logistic ชนะแค่ 5/8 ฤดู และแพ้ในปีที่ตลาดนิ่ง จึงไม่ใช้)
    ราคาช่วงเดียวกันปีก่อน ๆ = สัปดาห์เดียวกันของปี ย้อนหลัง 5 ปี
"""
import json
from datetime import datetime
 
import numpy as np
import pandas as pd
 
import config as C
 
DROP_BAHT = 5          # นับว่า "ราคาลง" เมื่อลดอย่างน้อยกี่บาท/กก.
WINDOW = 1             # ภายในกี่สัปดาห์ (แม่บอกว่าผลแก่แล้วรอได้ไม่เกิน 1 สัปดาห์)
HISTORY_YEARS = 5      # เทียบราคาช่วงเดียวกันย้อนหลังกี่ปี
RECENT_WEEKS = 12      # ส่งราคาย้อนหลังกี่สัปดาห์ไปทำกราฟ
STALE_DAYS = 21        # ข้อมูลเก่ากว่านี้ = น่าจะอยู่นอกฤดู
PHASE_BINS, PHASE_LABELS = [0, 6, 14, 999], ["ต้นฤดู", "กลางฤดู", "ปลายฤดู"]   # สัปดาห์ที่ของฤดู
 
 
def r1(x):
    return None if x is None or pd.isna(x) else round(float(x), 1)
 
 
def price_range(df, last, horizons):
    """ช่วงราคา 80% = ราคาล่าสุด x ควอนไทล์ของ log(ราคาอีก h สัปดาห์ / ราคาตอนนี้) ในอดีต"""
    base = df.loc[last, "price_mid"]
    out = []
    for h in horizons:
        col = f"target_h{h}"
        if col not in df:
            continue
        r = np.log(df[col] / df["price_mid"]).dropna()
        if len(r) < 20:
            continue
        lo, hi = r.quantile(C.INTERVAL[0]), r.quantile(C.INTERVAL[1])
        out.append({"horizon_weeks": h,
                    "target_week": (last + pd.DateOffset(weeks=int(h))).date().isoformat(),
                    "expected": r1(base), "low_80": r1(base * np.exp(lo)),
                    "high_80": r1(base * np.exp(hi))})
    return out
 
 
def drop_probability(df, last):
    """% ที่ราคาเคยลง >= DROP_BAHT ภายใน WINDOW สัปดาห์ แยกตามช่วงของฤดู (ถ่วงเข้าหาค่ารวม)"""
    fut = [f"target_h{h}" for h in range(1, WINDOW + 1) if f"target_h{h}" in df]
    d = df[df["price_mid"].notna() & df[f"target_h{WINDOW}"].notna()].copy()
    d["y"] = (d[fut].min(axis=1) <= d["price_mid"] - DROP_BAHT).astype(int)
    d["phase"] = pd.cut(d["week_of_season"], bins=PHASE_BINS, labels=PHASE_LABELS)
    overall = d["y"].mean()
    g = d.groupby("phase", observed=False)["y"].agg(["sum", "count"])
    k = 10
    rate = (g["sum"] + k * overall) / (g["count"] + k)
    phase = pd.cut(pd.Series([df.loc[last, "week_of_season"]]), bins=PHASE_BINS,
                   labels=PHASE_LABELS).iloc[0]
    p = float(rate.get(phase, overall))
    price = df.loc[last, "price_mid"]
    if p >= 0.35:
        level, advice = "สูง", "ช่วงนี้ของฤดูราคามักลงบ่อย ถ้าผลแก่พร้อมตัดแล้ว ไม่ควรรอ"
    elif p <= 0.10:
        level, advice = "ต่ำ", "ช่วงนี้ของฤดูราคามักทรงตัว ถ้าผลยังไม่แก่เต็มที่ รอได้โดยไม่เสี่ยงมาก"
    else:
        level, advice = "ปานกลาง", "ราคาอาจทรงตัวหรือลดเล็กน้อย ตัดสินใจตามความแก่ของผลเป็นหลัก"
    return {
        "window_weeks": WINDOW, "drop_baht": DROP_BAHT,
        "threshold_price": r1(price - DROP_BAHT),
        "probability": round(p, 3), "level": level, "season_phase": str(phase),
        "overall_rate": round(float(overall), 3),
        "method": "seasonal_rate",
        "message_th": (f"ในอดีต ช่วง{phase} ราคาลดลงถึง {price - DROP_BAHT:.0f} บาท/กก. หรือต่ำกว่า "
                       f"ภายใน {WINDOW} สัปดาห์ ประมาณ {p * 100:.0f}% ของครั้ง (โอกาส{level}) — {advice}"),
        "caveat_th": "เป็นสถิติจากอดีต ไม่ใช่คำทำนายที่แน่นอน ต้องตรวจความแก่ของผลก่อนตัดเสมอ",
    }
 
 
def same_week_history(df, last):
    wk = last.isocalendar().week
    rows = []
    for y in range(last.year - HISTORY_YEARS, last.year):
        g = df[(df.index.year == y) & (df.index.isocalendar().week == wk) & (df["observed"] == 1)]
        if not g.empty:
            rows.append({"year": y, "price": r1(g["price_mid"].iloc[0])})
    avg = r1(np.mean([r["price"] for r in rows])) if rows else None
    return {"iso_week": int(wk), "years": rows, "average": avg}
 
 
def product_block(pid, cfg):
    path = C.PROCESSED / f"weekly_features_{pid}.csv"
    if not path.exists():
        print(f"⚠ ไม่มี {path.name} — รัน 2_build_features.py ก่อน")
        return None
    df = pd.read_csv(path, index_col="week_end", parse_dates=True)
    last = df[df["observed"] == 1].index.max()
    age = (pd.Timestamp.today().normalize() - last).days
    price = df.loc[last, "price_mid"]
    hist = same_week_history(df, last)
    recent = df.loc[:last].tail(RECENT_WEEKS)
    block = {
        "product_id": pid, "name": cfg["name"], "unit": "บาท/กก.",
        "market": "ราคาขายส่ง ตลาดกรุงเทพฯ (กรมการค้าภายใน)",
        "latest": {"week_end": last.date().isoformat(), "price_mid": r1(price),
                   "price_min": r1(df.loc[last, "price_min"]),
                   "price_max": r1(df.loc[last, "price_max"]),
                   "week_of_season": int(df.loc[last, "week_of_season"]),
                   "days_old": int(age), "in_season": bool(age <= STALE_DAYS)},
        "price_range": price_range(df, last, cfg["horizons"]),
        "drop_probability": drop_probability(df, last),
        "same_week_previous_years": hist,
        "vs_previous_years_pct": (round((price / hist["average"] - 1) * 100, 1)
                                  if hist["average"] else None),
        "recent_weeks": [{"week_end": i.date().isoformat(), "price_mid": r1(v)}
                         for i, v in recent["price_mid"].items()],
        # ราคาจริงทุกสัปดาห์ที่มีข้อมูล (ให้เว็บเลือกช่วงวันดูย้อนหลังได้)
        "history": [{"week_end": i.date().isoformat(), "price_mid": r1(r["price_mid"]),
                     "price_min": r1(r["price_min"]), "price_max": r1(r["price_max"])}
                    for i, r in df[df["observed"] == 1].iterrows()],
    }
    if age > STALE_DAYS:
        block["warning_th"] = (f"ราคาล่าสุดเก่า {age} วัน น่าจะอยู่นอกฤดูของ{cfg['name']} "
                               "ตัวเลขพยากรณ์ใช้อ้างอิงไม่ได้จนกว่าฤดูใหม่จะเริ่ม")
    return block
 
 
if __name__ == "__main__":
    products = [b for pid, cfg in C.TARGETS.items() if (b := product_block(pid, cfg))]
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "products": products,
        "notes_th": [
            "ราคาในไฟล์นี้เป็นราคาขายส่งตลาดกรุงเทพฯ ไม่ใช่ราคาหน้าสวน/หน้าล้ง "
            "ราคาหน้าล้งเกรด AB อาจสูงหรือต่ำกว่านี้ ใช้ดูทิศทางตลาดเป็นหลัก",
            "ช่วงราคา 80% ทดสอบย้อนหลังแล้วครอบคลุมราคาจริงประมาณ 81% ของสัปดาห์",
            "โอกาสราคาลงมาจากสถิติตามช่วงของฤดู โมเดล ML ที่ทดสอบไม่ชนะวิธีนี้อย่างสม่ำเสมอ",
        ],
    }
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = C.OUTPUTS / "forecast.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"บันทึก {path}")
    for p in products:
        lt, dp = p["latest"], p["drop_probability"]
        rng = next((r for r in p["price_range"] if r["horizon_weeks"] == 1), None)
        print(f"\n[{p['name']}] สัปดาห์ {lt['week_end']} ราคา {lt['price_mid']} บาท/กก.")
        if rng:
            print(f"  สัปดาห์หน้า: {rng['low_80']}–{rng['high_80']} บาท (ช่วง 80%)")
        print(f"  {dp['message_th']}")
        h = p["same_week_previous_years"]
        if h["average"]:
            print(f"  ช่วงเดียวกัน {len(h['years'])} ปีก่อน เฉลี่ย {h['average']} บาท "
                  f"(ปีนี้ {p['vs_previous_years_pct']:+.1f}%)")
        if "warning_th" in p:
            print(f"  ⚠ {p['warning_th']}")
 
