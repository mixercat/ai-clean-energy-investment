"""ตั้งค่ากลางของ pipeline — แก้ที่ไฟล์นี้ไฟล์เดียว"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"          # ข้อมูลดิบที่ดึง/โหลดมา (cache)
MOC_FILES = RAW / "moc"              # วางไฟล์ CSV/Excel ที่โหลดจากเว็บ MOC ไว้ที่นี่
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

# ---- ช่วงเวลา ----
START_DATE = "2010-01-01"            # อากาศ/ค่าเงิน ดึงย้อนหลังตั้งแต่วันนี้ (ให้ครอบคลุมราคา)

# ---- ราคาทุเรียน (MOC Open Data, กรมการค้าภายใน) ----
# key = ราคาขายส่งที่พยากรณ์, retail = ราคาขายปลีกของชนิดเดียวกัน (ใช้เป็นตัวแปรเสริม)
TARGETS = {
    "W14021": {"name": "หมอนทอง", "retail": "P14020", "horizons": [1, 2, 4]},  # ตัวหลัก
    "W14020": {"name": "ชะนี", "retail": "P14019", "horizons": [1, 2]},        # ตัวรอง (ข้อมูลบางกว่า)
}
PRODUCT_IDS = [pid for t, cfg in TARGETS.items() for pid in (t, cfg["retail"])]
MOC_API = "https://dataapi.moc.go.th/gis-product-prices"   # ตอนนี้ขึ้น error -> ใช้ไฟล์ CSV เป็นหลัก

# ---- สภาพอากาศ (Open-Meteo) : จังหวัดแหล่งปลูกหลัก ----
PROVINCES = {
    "chanthaburi": (12.61, 102.10),
    "rayong": (12.68, 101.28),
    "trad": (12.24, 102.52),
    "chumphon": (10.49, 99.18),
}
WEATHER_VARS = [
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_mean",
]

# ---- ค่าเงินหยวน/บาท ----
# "frankfurter" = ไม่ต้องใช้ key (อัตราอ้างอิง ECB) | "bot" = BOT API (ต้องตั้ง env BOT_API_TOKEN)
FX_SOURCE = "frankfurter"

# ---- เทศกาลจีน (ชื่อตามไลบรารี holidays) ----
FESTIVALS = {"春节": "ตรุษจีน", "中秋节": "ไหว้พระจันทร์", "国庆节": "วันชาติจีน"}
PRE_FESTIVAL_DAYS = 30               # ช่วง "ก่อนเทศกาล" กี่วัน (ลองเปลี่ยนเป็น 14 แล้วเทียบผล)

# ---- ฤดูกาล ----
SEASON_GAP_WEEKS = 6                 # ไม่มีราคาติดกันเกินกี่สัปดาห์ = จบฤดู
FILL_GAP_WEEKS = 2                   # ช่องว่างสั้นไม่เกินกี่สัปดาห์ให้เติมด้วยค่าล่าสุด

# ---- โมเดล ----
INTERVAL = (0.1, 0.9)                # ช่วงราคา 80%
