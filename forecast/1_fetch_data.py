"""ขั้นที่ 1: รวบรวมข้อมูลดิบทั้งหมดไว้ที่ data/raw/

    python 1_fetch_data.py            # ทำเฉพาะที่ยังไม่มีไฟล์
    python 1_fetch_data.py --refresh  # ทำใหม่ทั้งหมด (เช่น หลังโหลด CSV ราคาชุดใหม่มา)
    python 1_fetch_data.py --api      # ลองดึงราคาจาก MOC API ก่อน (ตอนนี้ API ขึ้น error)

ราคา: วางไฟล์ CSV ที่กดโหลดจากเว็บ MOC ทั้ง 4 ตัวไว้ที่ data/raw/moc/
      (ชื่อไฟล์อะไรก็ได้ วางหลายไฟล์/หลายช่วงเวลาก็ได้ สคริปต์ดูรหัสสินค้าในไฟล์เอง แถวซ้ำจะถูกตัด)
อากาศ + ค่าเงิน: ดึงจาก API อัตโนมัติ (ไม่ต้องใช้ key)
"""
import argparse
import os
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

import config as C

HEADERS = {"User-Agent": "durian-forecast/1.0 (student project)"}


def _get(url, params=None, headers=None, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"   ลองใหม่ ({e})")
            time.sleep(2 * (i + 1))


def _year_chunks(start, end):
    s = pd.Timestamp(start)
    end = pd.Timestamp(end)
    while s <= end:
        e = min(pd.Timestamp(year=s.year, month=12, day=31), end)
        yield s.date().isoformat(), e.date().isoformat()
        s = e + pd.Timedelta(days=1)


# ------------------------------------------------------------------ MOC prices
THAI_COLS = {
    "รหัสสินค้า": "product_id",
    "ชื่อสินค้า": "product_name",
    "ราคาสูงสุด": "price_max",
    "ราคาต่ำสุด": "price_min",
}


def _read_any(path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "cp874"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: อ่าน encoding ไม่ได้")


def normalize_moc_file(path):
    """อ่านไฟล์ที่โหลดจากเว็บ MOC (CSV/Excel) -> date(YYYY-MM-DD), product_id, price_min, price_max"""
    df = _read_any(path)
    df.columns = [str(c).strip() for c in df.columns]
    ren = {}
    for c in df.columns:
        if c in THAI_COLS:
            ren[c] = THAI_COLS[c]
        elif c.startswith("วันที่"):
            ren[c] = "date"
    df = df.rename(columns=ren)
    missing = {"date", "product_id", "price_min", "price_max"} - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: หาคอลัมน์ไม่เจอ {missing} (คอลัมน์ที่มี: {list(df.columns)})")
    # เว็บให้วันที่แบบ เดือน/วัน/ปี เช่น "4/1/2010 12:00:00 AM" = 1 เม.ย. 2010
    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False).dt.strftime("%Y-%m-%d")
    df["product_id"] = df["product_id"].astype(str).str.strip()
    return df[["date", "product_id", "price_min", "price_max"]]


def fetch_moc_api(product_id):
    rows = []
    for s, e in _year_chunks(C.START_DATE, date.today()):
        data = _get(C.MOC_API, {"product_id": product_id, "from_date": s, "to_date": e})
        items = data if isinstance(data, list) else [data]
        for it in items:
            for p in (it or {}).get("price_list") or []:
                rows.append({"date": str(p.get("date"))[:10], "product_id": product_id,
                             "price_min": p.get("price_min"), "price_max": p.get("price_max")})
        print(f"   {product_id} {s[:4]}: รวม {len(rows)} แถว")
    return pd.DataFrame(rows, columns=["date", "product_id", "price_min", "price_max"])


def load_moc_files():
    files = sorted([*C.MOC_FILES.glob("*.csv"), *C.MOC_FILES.glob("*.xls*")])
    if not files:
        return pd.DataFrame(columns=["date", "product_id", "price_min", "price_max"])
    frames = []
    for f in files:
        d = normalize_moc_file(f)
        print(f"   อ่าน {f.name}: {d['product_id'].unique().tolist()} {len(d)} แถว "
              f"({d['date'].min()} → {d['date'].max()})")
        frames.append(d)
    return pd.concat(frames)


def fetch_prices(refresh, use_api=False):
    todo = [p for p in C.PRODUCT_IDS if refresh or not (C.RAW / f"moc_{p}.csv").exists()]
    for p in set(C.PRODUCT_IDS) - set(todo):
        print(f"✓ มีแล้ว moc_{p}.csv")
    if not todo:
        return
    print(f"→ อ่านไฟล์ราคาใน {C.MOC_FILES}")
    files = load_moc_files()
    for pid in todo:
        df = files[files["product_id"] == pid]
        if use_api:
            try:
                api = fetch_moc_api(pid)
                df = pd.concat([df, api])
            except Exception as e:  # noqa: BLE001
                print(f"   API ใช้ไม่ได้ ({e}) -> ใช้เฉพาะไฟล์")
        if df.empty:
            print(f"   ⚠ ไม่พบข้อมูล {pid} — โหลด CSV ของตัวนี้จากเว็บ MOC มาวางใน {C.MOC_FILES}")
            continue
        df = df.drop_duplicates(["date", "product_id"], keep="last").sort_values("date")
        out = C.RAW / f"moc_{pid}.csv"
        df.to_csv(out, index=False)
        print(f"   บันทึก {out.name} ({len(df)} แถว, {df['date'].min()} → {df['date'].max()})")


# ------------------------------------------------------------------ weather
def fetch_weather(refresh):
    out = C.RAW / "weather_daily.csv"
    if out.exists() and not refresh:
        print(f"✓ มีแล้ว {out.name}")
        return
    end = (date.today() - timedelta(days=6)).isoformat()  # archive มีดีเลย์ ~5 วัน
    frames = []
    for name, (lat, lon) in C.PROVINCES.items():
        print(f"→ ดึงอากาศ {name}")
        d = _get("https://archive-api.open-meteo.com/v1/archive", {
            "latitude": lat, "longitude": lon, "start_date": C.START_DATE, "end_date": end,
            "daily": ",".join(C.WEATHER_VARS), "timezone": "Asia/Bangkok"})
        f = pd.DataFrame(d["daily"]).rename(columns={"time": "date"})
        f["province"] = name
        frames.append(f)
    pd.concat(frames).to_csv(out, index=False)
    print(f"   บันทึก {out.name}")


# ------------------------------------------------------------------ FX
def fx_frankfurter():
    rows = []
    for s, e in _year_chunks(C.START_DATE, date.today()):
        d = _get(f"https://api.frankfurter.dev/v1/{s}..{e}", {"base": "CNY", "symbols": "THB"})
        rows += [{"date": k, "cny_thb": v["THB"]} for k, v in d.get("rates", {}).items()]
    return pd.DataFrame(rows)


def fx_bot():
    """BOT API (อัตราแลกเปลี่ยนเฉลี่ยรายวัน)
    ⚠ ตรวจ URL / ชื่อ header กับเอกสารใน portal.api.bot.or.th ก่อนใช้ แล้วแก้ผ่าน env ได้"""
    token = os.environ.get("BOT_API_TOKEN")
    if not token:
        raise RuntimeError("ยังไม่ได้ตั้ง env BOT_API_TOKEN")
    url = os.environ.get("BOT_FX_URL",
                         "https://gateway.api.bot.or.th/Stat-ExchangeRate/v2/DAILY_AVG_EXG_RATE/")
    header = os.environ.get("BOT_AUTH_HEADER", "Authorization")
    rows = []
    for s, e in _year_chunks(C.START_DATE, date.today()):
        # แบ่งเป็นรายเดือน เผื่อ API จำกัดช่วงวันต่อครั้ง
        for ms in pd.date_range(s, e, freq="MS"):
            me = min(ms + pd.offsets.MonthEnd(0), pd.Timestamp(e))
            d = _get(url, {"start_period": ms.date().isoformat(), "end_period": me.date().isoformat(),
                           "currency": "CNY"}, headers={header: token})
            for r in d["result"]["data"]["data_detail"]:
                if not r.get("period"):
                    continue
                mid = r.get("mid_rate") or None
                if mid in (None, ""):
                    mid = (float(r["buying_transfer"]) + float(r["selling"])) / 2
                rows.append({"date": r["period"], "cny_thb": float(mid)})
    return pd.DataFrame(rows)


def fetch_fx(refresh):
    out = C.RAW / "fx_cny_thb.csv"
    if out.exists() and not refresh:
        print(f"✓ มีแล้ว {out.name}")
        return
    print(f"→ ดึงค่าเงินหยวน/บาท ({C.FX_SOURCE})")
    df = fx_bot() if C.FX_SOURCE == "bot" else fx_frankfurter()
    df.drop_duplicates("date").sort_values("date").to_csv(out, index=False)
    print(f"   บันทึก {out.name} ({len(df)} วัน)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ทำใหม่ทั้งหมด")
    ap.add_argument("--api", action="store_true", help="ลองดึงราคาจาก MOC API ด้วย")
    a = ap.parse_args()
    C.MOC_FILES.mkdir(parents=True, exist_ok=True)
    ok = True
    steps = [lambda r: fetch_prices(r, a.api), fetch_weather, fetch_fx]
    for step, name in zip(steps, ("ราคา", "อากาศ", "ค่าเงิน")):
        try:
            step(a.refresh)
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"✗ {name} ล้มเหลว: {e}")
    sys.exit(0 if ok else 1)
