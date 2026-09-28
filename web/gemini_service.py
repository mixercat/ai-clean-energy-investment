import google.generativeai as genai
import os
import json
import time

class GeminiService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("ยังไม่ได้ระบุ GEMINI_API_KEY ในไฟล์ .env")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-3.8-flash')

    def extract_receipt(self, image):
        # แปลงโหมดภาพ RGBA/P เป็น RGB ป้องกัน Error เรื่อง JPEG format
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
            
        prompt = """
        คุณคือระบบ OCR อ่านใบชั่ง/บิลขายทุเรียน 
        โปรดอ่านข้อมูลจากรูปภาพแล้วตอบกลับเป็น JSON รูปแบบนี้เท่านั้น (ไม่ต้องมีคำอธิบายเพิ่มเติม):
        {
            "buyer_name": "ชื่อล้งหรือผู้ซื้อ",
            "date": "YYYY-MM-DD",
            "grand_total": 0.0
        }
        """
        
        last_error = None
        # วนลูปพยายามส่งใหม่สูงสุด 5 ครั้ง
        for attempt in range(5):
            try:
                response = self.model.generate_content([image, prompt])
                text = response.text.strip()
                
                # ทำความสะอาดสตริง JSON ก่อน parse
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                    
                return json.loads(text)
            except Exception as e:
                last_error = e
                # หากเจอ Error 429 (Quota/Rate Limit) ให้รอ 3 วินาทีแล้วลองส่งใหม่
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(3)
                    continue
                time.sleep(1.5)
                
        raise last_error

    def ask_assistant(self, user_question, farm_context):
        prompt = f"""คุณคือผู้ช่วย AI บริหารจัดการสวนทุเรียน 
        ข้อมูลบริบทของสวน:
        {farm_context}

        คำถามของผู้ใช้: {user_question}
        """
        response = self.model.generate_content(prompt)
        return response.text