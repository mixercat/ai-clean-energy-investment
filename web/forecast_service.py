"""บริการข้อมูลพยากรณ์สำหรับเว็บ
- ราคาทุเรียน: อ่านจาก forecast.json (สร้างโดย forecast/run_all.py) ไม่ใช่ตัวเลขสมมติ
- อากาศ: พยากรณ์ฝน 14 วันจาก Open-Meteo (ไม่ต้องใช้ key)
"""
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
WEB_DIR = Path(__file__).resolve().parent


def _find_forecast():
    """หา forecast.json: ค่าใน .env/Secrets -> web/data/forecast.json -> ../forecast/outputs/forecast.json
    (อ้างอิงจากตำแหน่งไฟล์นี้ จึงใช้ได้ทั้งตอนรันในโฟลเดอร์ web และบน Streamlit Cloud ที่รันจากโฟลเดอร์บนสุด)"""
    cands = []
    env = os.getenv("FORECAST_JSON_PATH")
    if env:
        p = Path(env)
        cands += [p] if p.is_absolute() else [WEB_DIR / p, Path.cwd() / p]
    cands += [WEB_DIR / "data" / "forecast.json", WEB_DIR.parent / "forecast" / "outputs" / "forecast.json"]
    return next((c for c in cands if c.exists()), cands[0])


FORECAST_PATH = _find_forecast()
HEAVY_RAIN_MM = 20          # ฝนต่อวันเกินนี้ = ฝนหนัก
_cache = {"mtime": None, "data": None, "weather": {}}


class ForecastService:
    # ------------------------------------------------------------------ อากาศ
    @staticmethod
    def get_weather_forecast(lat: float = 12.6114, lon: float = 102.1039, days: int = 14):
        """พยากรณ์ฝน/อุณหภูมิรายวัน (ค่าเริ่มต้น: จันทบุรี) จำผลไว้ 1 ชั่วโมง
        คอลัมน์: date, rain_mm, rain_chance, tmax, tmin, heavy_rain"""
        key = (round(lat, 3), round(lon, 3), days)
        hit = _cache["weather"].get(key)
        if hit and time.time() - hit[0] < 3600:
            return hit[1].copy()
        res = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": "Asia/Bangkok", "forecast_days": days,
            "daily": "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min",
        }, timeout=20)
        res.raise_for_status()
        d = res.json().get("daily", {})
        df = pd.DataFrame({
            "date": d.get("time", []),
            "rain_mm": d.get("precipitation_sum", []),
            "rain_chance": d.get("precipitation_probability_max", []),
            "tmax": d.get("temperature_2m_max", []),
            "tmin": d.get("temperature_2m_min", []),
        })
        df["heavy_rain"] = df["rain_mm"].fillna(0) >= HEAVY_RAIN_MM
        _cache["weather"][key] = (time.time(), df)
        return df.copy()

    @staticmethod
    def weather_summary_th(lat: float = 12.6114, lon: float = 102.1039):
        df = ForecastService.get_weather_forecast(lat, lon)
        heavy = df.loc[df["heavy_rain"], "date"].tolist()
        text = f"14 วันข้างหน้า ฝนรวมประมาณ {df['rain_mm'].fillna(0).sum():.0f} มม."
        text += (f" มีฝนหนักวันที่ {', '.join(heavy)}" if heavy else " ไม่มีวันที่ฝนหนัก")
        days = [f"{r.date}: ฝน {r.rain_mm or 0:.0f} มม. โอกาสฝน {r.rain_chance or 0:.0f}% "
                f"อุณหภูมิ {r.tmin or 0:.0f}-{r.tmax or 0:.0f}°C" for r in df.head(7).itertuples()]
        return text + "\n  รายวัน 7 วันข้างหน้า (ใช้แนะนำวันพ่นยา/ใส่ปุ๋ย):\n  " + "\n  ".join(days)

    # ------------------------------------------------------------------ ราคาทุเรียน
    @staticmethod
    def _load():
        """อ่าน forecast.json อ่านใหม่อัตโนมัติเมื่อไฟล์ถูกอัปเดต"""
        global FORECAST_PATH
        if not FORECAST_PATH.exists():
            FORECAST_PATH = _find_forecast()
        if not FORECAST_PATH.exists():
            raise FileNotFoundError(
                "ไม่พบไฟล์ forecast.json — รัน `python run_all.py` ในโฟลเดอร์ forecast "
                "(ถ้าใช้ Streamlit Cloud ต้อง push ไฟล์ forecast/outputs/forecast.json ขึ้น GitHub ด้วย)")
        mtime = FORECAST_PATH.stat().st_mtime
        if _cache["mtime"] != mtime:
            _cache["data"] = json.loads(FORECAST_PATH.read_text(encoding="utf-8"))
            _cache["mtime"] = mtime
        return _cache["data"]

    @staticmethod
    def _product(name="หมอนทอง"):
        for p in ForecastService._load()["products"]:
            if p["name"] == name:
                return p
        raise ValueError(f"ไม่มีข้อมูล {name} ใน forecast.json")

    @staticmethod
    def get_durian_price_forecast(name: str = "หมอนทอง"):
        """ช่วงราคาล่วงหน้า (ช่วงความเชื่อมั่น 80%) — ชื่อฟังก์ชันและคอลัมน์เหมือนของเดิม
        คอลัมน์: week, target_week, min_price, max_price
        หมอนทองมีล่วงหน้า 1, 2, 4 สัปดาห์ / ชะนี 1, 2 สัปดาห์"""
        p = ForecastService._product(name)
        return pd.DataFrame([{
            "week": f"สัปดาห์ที่ {r['horizon_weeks']}",
            "target_week": r["target_week"],
            "min_price": r["low_80"],
            "max_price": r["high_80"],
        } for r in p["price_range"]])

    @staticmethod
    def get_price_card(name: str = "หมอนทอง"):
        """ข้อมูลสำหรับการ์ดราคาหน้าแรก"""
        p = ForecastService._product(name)
        nxt = next((r for r in p["price_range"] if r["horizon_weeks"] == 1), {})
        return {
            "name": p["name"],
            "price_now": p["latest"]["price_mid"],
            "as_of": p["latest"]["week_end"],
            "in_season": p["latest"]["in_season"],
            "next_week_low": nxt.get("low_80"),
            "next_week_high": nxt.get("high_80"),
            "drop_chance_pct": round(p["drop_probability"]["probability"] * 100),
            "drop_level": p["drop_probability"]["level"],
            "advice": p["drop_probability"]["message_th"],
            "vs_last_years_pct": p["vs_previous_years_pct"],
            "warning": p.get("warning_th"),
        }

    @staticmethod
    def get_price_history(name: str = "หมอนทอง", start=None, end=None):
        """ราคาจริงรายสัปดาห์ — คอลัมน์: week_end (datetime), price_mid, price_min, price_max
        ถ้า forecast.json มี "history" (run_all.py รุ่นใหม่) จะได้ย้อนหลังทุกปี ไม่งั้นได้ 12 สัปดาห์ล่าสุด"""
        p = ForecastService._product(name)
        df = pd.DataFrame(p.get("history") or p["recent_weeks"])
        df["week_end"] = pd.to_datetime(df["week_end"])
        if start is not None:
            df = df[df["week_end"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["week_end"] <= pd.Timestamp(end) + pd.Timedelta(days=6)]
        return df.reset_index(drop=True)

    @staticmethod
    def has_full_history(name: str = "หมอนทอง"):
        return bool(ForecastService._product(name).get("history"))

    @staticmethod
    def market_price_on(day, name: str = "หมอนทอง", max_gap_days: int = 10):
        """ราคาขายส่ง กทม. ของสัปดาห์ที่ใกล้วันที่ day ที่สุด (ถ้าห่างเกิน max_gap_days คืน None)"""
        h = ForecastService.get_price_history(name)
        if h.empty or day is None or pd.isna(day):
            return None
        gap = (h["week_end"] - pd.Timestamp(day)).abs()
        i = gap.idxmin()
        return float(h.loc[i, "price_mid"]) if gap[i].days <= max_gap_days else None

    @staticmethod
    def estimate_revenue(kg: float, name: str = "หมอนทอง", price_ratio: float = 1.0):
        """รายได้ถ้าขาย kg กิโลในสัปดาห์หน้า
        price_ratio = ราคาหน้าล้งของสวนเรา / ราคาตลาดกรุงเทพ (ยังไม่รู้ใช้ 1.0)"""
        c = ForecastService.get_price_card(name)
        if c["next_week_low"] is None:
            return None
        return {"kg": kg,
                "low": round(kg * c["next_week_low"] * price_ratio),
                "mid": round(kg * c["price_now"] * price_ratio),
                "high": round(kg * c["next_week_high"] * price_ratio)}

    @staticmethod
    def seasonal_profile(name: str = "หมอนทอง", years: int = 5):
        """ราคาเฉลี่ยรายเดือนของ N ฤดูล่าสุด (ไม่รวมปีนี้) + ปีนี้ -> DataFrame month, avg, this_year"""
        h = ForecastService.get_price_history(name)
        if h.empty:
            return pd.DataFrame()
        h = h.assign(year=h["week_end"].dt.year, month=h["week_end"].dt.month)
        this = int(h["year"].max())
        past = h[(h["year"] < this) & (h["year"] >= this - years)]
        prof = past.groupby("month")["price_mid"].mean().rename("avg").to_frame()
        prof["this_year"] = h[h["year"] == this].groupby("month")["price_mid"].mean()
        return prof.reset_index()

    @staticmethod
    def price_trend_text(name: str = "หมอนทอง"):
        """สรุปแนวโน้มราคาจากข้อมูลจริง สำหรับให้ AI ใช้ตอบเรื่องแนวโน้ม"""
        months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        prof = ForecastService.seasonal_profile(name)
        if prof.empty or prof["avg"].isna().all():
            return ""
        p = prof.dropna(subset=["avg"])
        hi, lo = p.loc[p["avg"].idxmax()], p.loc[p["avg"].idxmin()]
        lines = [f"- แนวโน้มตามฤดูของ{name} (ค่าเฉลี่ยราคาขายส่ง กทม. 5 ฤดูก่อนหน้า): "
                 + ", ".join(f"{months[int(r.month) - 1]} {r.avg:.0f}" for r in p.itertuples())
                 + f" บาท/กก. — มักสูงสุดเดือน{months[int(hi.month) - 1]} ต่ำสุดเดือน{months[int(lo.month) - 1]}"]
        cmp_ = p.dropna(subset=["this_year"])
        if not cmp_.empty:
            lines.append("- ปีนี้เทียบค่าเฉลี่ยเดือนเดียวกัน: " + ", ".join(
                f"{months[int(r.month) - 1]} {r.this_year:.0f} ({(r.this_year / r.avg - 1) * 100:+.0f}%)"
                for r in cmp_.itertuples()))
        h = ForecastService.get_price_history(name).tail(5)
        if len(h) >= 2:
            chg = (h["price_mid"].iloc[-1] / h["price_mid"].iloc[0] - 1) * 100
            lines.append(f"- {len(h) - 1} สัปดาห์ล่าสุดของข้อมูล ราคาเปลี่ยน {chg:+.1f}% "
                         f"({h['price_mid'].iloc[0]:.0f} -> {h['price_mid'].iloc[-1]:.0f} บาท/กก.)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ บริบทให้ Gemini
    @staticmethod
    def context_for_gemini(lat: float = 12.6114, lon: float = 102.1039):
        data = ForecastService._load()
        lines = [f"ข้อมูลราคาทุเรียน (อัปเดต {data['generated_at'][:10]}):"]
        for p in data["products"]:
            c = ForecastService.get_price_card(p["name"])
            line = (f"- {c['name']}: ราคาขายส่งกรุงเทพล่าสุด {c['price_now']} บาท/กก. "
                    f"(สัปดาห์ {c['as_of']}), สัปดาห์หน้าน่าจะอยู่ {c['next_week_low']}–"
                    f"{c['next_week_high']} บาท (ช่วงความเชื่อมั่น 80%), {c['advice']}")
            if c["vs_last_years_pct"] is not None:
                line += f", เทียบช่วงเดียวกันปีก่อน ๆ {c['vs_last_years_pct']:+.1f}%"
            if c["warning"]:
                line += f" [หมายเหตุ: {c['warning']}]"
            lines.append(line)
            try:
                trend = ForecastService.price_trend_text(p["name"])
                if trend:
                    lines.append(trend)
            except Exception:   # noqa: BLE001
                pass
        lines += [f"- {n}" for n in data["notes_th"]]
        try:
            lines.append(f"- อากาศ: {ForecastService.weather_summary_th(lat, lon)}")
        except Exception:
            lines.append("- อากาศ: ดึงข้อมูลไม่ได้ในขณะนี้")
        return "\n".join(lines)
