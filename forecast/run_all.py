"""รันทั้ง pipeline ในคำสั่งเดียว + เช็กคุณภาพข้อมูล

    python run_all.py              # อัปเดตประจำสัปดาห์: ดึงข้อมูล -> ตารางรายสัปดาห์ -> forecast.json
    python run_all.py --refresh    # ดึงข้อมูลใหม่ทั้งหมด (ใช้หลังวาง CSV ราคาชุดใหม่ใน data/raw/moc/)
    python run_all.py --full       # รวมขั้นทดสอบโมเดล (3, 4) ด้วย ใช้เวลานานกว่า

ขั้นตอนประจำสัปดาห์:
    1. โหลด CSV ราคาช่วงล่าสุดจากเว็บ MOC มาวางใน data/raw/moc/ (ไฟล์เก่าไม่ต้องลบ แถวซ้ำจะถูกตัด)
    2. python run_all.py --refresh
    3. ส่ง outputs/forecast.json ให้ทีมเว็บ
"""
import argparse
import json
import subprocess
import sys

import pandas as pd

import config as C

JUMP_PCT = 30        # ราคากลางเปลี่ยนเกินกี่ % ในสัปดาห์เดียว = น่าสงสัย
STALE_DAYS = 7       # ราคาล่าสุดเก่ากว่านี้ในช่วงฤดู = เตือนให้โหลดใหม่


def run(script, *args):
    print(f"\n{'=' * 20} {script} {' '.join(args)} {'=' * 20}")
    r = subprocess.run([sys.executable, script, *args], cwd=C.ROOT)
    if r.returncode != 0:
        sys.exit(f"✗ {script} ล้มเหลว — หยุดตรงนี้ แก้ปัญหาแล้วรันใหม่")


def quality_checks():
    """เตือนเมื่อข้อมูลดูผิดปกติ ไม่หยุดการทำงาน"""
    print(f"\n{'=' * 20} เช็กคุณภาพข้อมูล {'=' * 20}")
    counts_file = C.OUTPUTS / "row_counts.json"
    prev = json.loads(counts_file.read_text()) if counts_file.exists() else {}
    now, warns = {}, []
    for pid in C.PRODUCT_IDS:
        f = C.RAW / f"moc_{pid}.csv"
        if not f.exists():
            warns.append(f"{pid}: ไม่มีไฟล์ราคา")
            continue
        d = pd.read_csv(f, parse_dates=["date"])
        now[pid] = len(d)
        if pid in prev and len(d) < prev[pid]:
            warns.append(f"{pid}: จำนวนแถวลดลง {prev[pid]} -> {len(d)} (โหลดไฟล์มาไม่ครบหรือเปล่า?)")
        real = d[(d["price_min"] > 0) | (d["price_max"] > 0)].copy()
        if real.empty:
            warns.append(f"{pid}: ไม่มีราคาจริงเลย")
            continue
        age = (pd.Timestamp.today().normalize() - real["date"].max()).days
        if 7 < age <= 42:   # เกิน 6 สัปดาห์ถือว่านอกฤดู ไม่ต้องเตือน
            warns.append(f"{pid}: ราคาล่าสุดเก่า {age} วัน ({real['date'].max().date()}) "
                         "ถ้ายังอยู่ในฤดู ให้โหลด CSV ชุดใหม่")
        real["mid"] = (real["price_min"] + real["price_max"]) / 2
        w = real.set_index("date")["mid"].resample("W-SUN").mean().dropna().tail(8)
        jumps = w.pct_change().abs() * 100
        for dt, v in jumps[jumps > JUMP_PCT].items():
            warns.append(f"{pid}: ราคาสัปดาห์ {dt.date()} เปลี่ยน {v:.0f}% จากสัปดาห์ก่อน ตรวจว่าถูกต้องไหม")
    for p in ("weather_daily.csv", "fx_cny_thb.csv"):
        if not (C.RAW / p).exists():
            warns.append(f"ไม่มีไฟล์ {p}")
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    counts_file.write_text(json.dumps(now, indent=2))
    if warns:
        print("⚠ พบสิ่งที่ควรตรวจ:")
        for w in warns:
            print("   -", w)
    else:
        print("✓ ข้อมูลปกติ")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ดึงข้อมูลใหม่ทั้งหมด")
    ap.add_argument("--full", action="store_true", help="รวมขั้นทดสอบโมเดล 3 และ 4")
    a = ap.parse_args()
    run("1_fetch_data.py", *(["--refresh"] if a.refresh else []))
    quality_checks()
    run("2_build_features.py")
    if a.full:
        run("3_baseline.py")
        run("4_direction_model.py")
    run("5_export_for_web.py")
    print(f"\n✓ เสร็จ — ส่ง {C.OUTPUTS / 'forecast.json'} ให้ทีมเว็บ")