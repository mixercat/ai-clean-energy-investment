import os
import json
from google import genai
from google.genai import types
from PIL import Image

class GeminiService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)
        # กำหนดโมเดลเป็น gemini-3.8-flash ตามที่ API แนะนำ
        self.model_name = "gemini-3.8-flash"

    def extract_receipt(self, image: Image.Image) -> dict:
        """สแกนใบรับซื้อทุเรียนแล้วคืนค่าเป็น JSON"""
        prompt = """
        วิเคราะห์ภาพใบเสร็จรับซื้อทุเรียนนี้ แล้วสกัดข้อมูลเป็น JSON ตามรูปแบบต่อไปนี้:
        {
            "date": "YYYY-MM-DD",
            "buyer_name": "ชื่อล้งหรือผู้รับซื้อ",
            "items": [
                {
                    "grade": "เกรด เช่น AB, C, หรือ ตกไซซ์",
                    "weight_kg": 0.0,
                    "price_per_kg": 0.0,
                    "total_amount": 0.0
                }
            ],
            "grand_total": 0.0
        }
        ตอบเฉพาะ JSON ล้วนๆ ไม่ต้องมี markdown หรือคำอธิบายเพิ่มเติม
        """
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[image, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        clean_text = response.text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        return json.loads(clean_text.strip())

    def ask_assistant(self, user_question: str, farm_context: str) -> str:
        """ถาม-ตอบข้อสงสัยการขายทุเรียน"""
        prompt = f"""
        คุณคือที่ปรึกษาชาวสวนทุเรียนมืออาชีพ
        ข้อมูลสวนและสถานการณ์ปัจจุบัน:
        {farm_context}

        คำถามของชาวสวน:
        {user_question}
        """
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text