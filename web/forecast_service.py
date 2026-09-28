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
FORECAST_PATH = Path(os.getenv("FORECAST_JSON_PATH", "../forecast/outputs/forecast.json"))
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
        return text + (f" มีฝนหนักวันที่ {', '.join(heavy)}" if heavy else " ไม่มีวันที่ฝนหนัก")

    # ------------------------------------------------------------------ ราคาทุเรียน
    @staticmethod
    def _load():
        """อ่าน forecast.json อ่านใหม่อัตโนมัติเมื่อไฟล์ถูกอัปเดต"""
        if not FORECAST_PATH.exists():
            raise FileNotFoundError(
                f"ไม่พบ {FORECAST_PATH} — รัน `python run_all.py` ในโฟลเดอร์ forecast ก่อน "
                "หรือแก้ FORECAST_JSON_PATH ใน .env")
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
    def get_price_history(name: str = "หมอนทอง"):
        """ราคา 12 สัปดาห์ล่าสุด สำหรับทำกราฟ — คอลัมน์: week_end, price_mid"""
        return pd.DataFrame(ForecastService._product(name)["recent_weeks"])

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
        lines += [f"- {n}" for n in data["notes_th"]]
        try:
            lines.append(f"- อากาศ: {ForecastService.weather_summary_th(lat, lon)}")
        except Exception:
            lines.append("- อากาศ: ดึงข้อมูลไม่ได้ในขณะนี้")
        return "\n".join(lines)


if __name__ == "__main__":
    fs = ForecastService
    print("== ช่วงราคาล่วงหน้า ==")
    print(fs.get_durian_price_forecast())
    print("\n== การ์ดราคา ==")
    print(fs.get_price_card())
    print("\n== รายได้ถ้าขาย 1,000 กก. ==")
    print(fs.estimate_revenue(1000))
    print("\n== พยากรณ์ฝน 5 วันแรก ==")
    print(fs.get_weather_forecast().head())
    print("\n== บริบทให้ Gemini ==")
    print(fs.context_for_gemini())