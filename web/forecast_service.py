import requests
import pandas as pd

class ForecastService:
    @staticmethod
    def get_weather_forecast(lat: float = 12.6114, lon: float = 102.1039):
        """ดึงพยากรณ์ฝน 14 วันจาก Open-Meteo (พิกัดตัวอย่าง: จันทบุรี)"""
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&daily=precipitation_sum,rain_sum&timezone=Asia%2FBangkok"
        )
        res = requests.get(url).json()
        daily = res.get("daily", {})
        df = pd.DataFrame({
            "date": daily.get("time", []),
            "rain_mm": daily.get("precipitation_sum", [])
        })
        return df

    @staticmethod
    def get_durian_price_forecast():
        """จำลองช่วงราคาพยากรณ์ล่วงหน้า 4 สัปดาห์"""
        return pd.DataFrame({
            "week": ["สัปดาห์ที่ 1", "สัปดาห์ที่ 2", "สัปดาห์ที่ 3", "สัปดาห์ที่ 4"],
            "min_price": [130, 125, 140, 145],
            "max_price": [150, 140, 160, 165]
        })