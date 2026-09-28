"""บริการ AI ของเว็บ: ใช้ Gemini เป็นหลัก และ Azure OpenAI (Microsoft Foundry) เป็นตัวสำรองสุดท้าย
- extract_receipt(): อ่านรูปใบชั่ง/ใบรับซื้อ หรือบิลค่าใช้จ่าย -> dict
- ask_assistant():  ตอบคำถามจากบริบทของสวน (บัญชี + ราคา + อากาศ)
ลำดับ: Gemini รุ่นหลัก -> Gemini รุ่นสำรอง -> Azure (ถ้าตั้งค่า AZURE_OPENAI_* ใน .env)
ชื่อ class และชื่อฟังก์ชันเหมือนเวอร์ชันเดิม app.py จึงไม่ต้องแก้
"""
import base64
import io
import json
import os
import time

from google import genai
from google.genai import errors, types

DEFAULT_MODEL = "gemini-3.8-flash"   # ถ้ารุ่นนี้ใช้ไม่ได้ ให้ตั้ง GEMINI_MODEL ใน .env ตามชื่อใน AI Studio

RECEIPT_PROMPT = """คุณคือระบบอ่านเอกสารของสวนทุเรียน อ่านรูปแล้วตอบเป็น JSON ตาม schema เท่านั้น
กติกา:
- doc_type = "sale" ถ้าเป็นใบชั่ง/ใบรับซื้อที่สวนขายทุเรียนให้ล้ง
  doc_type = "expense" ถ้าเป็นบิลที่สวนจ่ายเงิน (ปุ๋ย ยา ค่าแรง อุปกรณ์ ค่าขนส่ง ฯลฯ)
- date เป็น YYYY-MM-DD (ค.ศ.) ถ้าในรูปเป็น พ.ศ. ให้ลบ 543
- ตัวเลขเงินและน้ำหนักเป็นตัวเลขล้วน ไม่มีคอมมาหรือหน่วย
- ถ้าอ่านค่าไหนไม่ออกหรือไม่มีในรูป ให้ใส่ null ห้ามเดา
- sale: ใส่ทุกบรรทัดใน items (เกรด น้ำหนัก ราคาต่อกก. เป็นเงิน) และค่าหักใน deductions
- expense: ใส่รายการสินค้าใน items (ใช้ description, quantity, unit_price, amount) และเลือก category
- confidence = ความมั่นใจโดยรวม 0-1 และ notes = สิ่งที่อ่านไม่ชัด (ภาษาไทย)"""

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["sale", "expense", "unknown"]},
        "buyer_name": {"type": "string", "nullable": True,
                       "description": "ชื่อล้ง/ผู้ซื้อ (sale) หรือชื่อร้าน/ผู้ขาย (expense)"},
        "date": {"type": "string", "nullable": True},
        "variety": {"type": "string", "nullable": True, "description": "พันธุ์ เช่น หมอนทอง ชะนี"},
        "category": {"type": "string", "nullable": True,
                     "enum": ["ปุ๋ย", "ยา/สารเคมี", "ค่าแรง", "อุปกรณ์", "ขนส่ง", "อื่น ๆ"]},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string", "nullable": True},
            "grade": {"type": "string", "nullable": True},
            "quantity": {"type": "number", "nullable": True, "description": "น้ำหนัก กก. หรือจำนวน"},
            "unit_price": {"type": "number", "nullable": True},
            "amount": {"type": "number", "nullable": True},
        }}},
        "total_weight_kg": {"type": "number", "nullable": True},
        "deductions": {"type": "number", "nullable": True},
        "grand_total": {"type": "number", "nullable": True},
        "confidence": {"type": "number"},
        "notes": {"type": "string", "nullable": True},
    },
    "required": ["doc_type", "grand_total", "confidence"],
}

ASSISTANT_RULES = """คุณคือผู้ช่วย AI ของเจ้าของสวนทุเรียน ตอบภาษาไทย สั้น เข้าใจง่าย เหมือนคุยกับเกษตรกร
กติกา:
1. ใช้เฉพาะตัวเลขที่อยู่ในข้อมูลบริบท ห้ามแต่งตัวเลขหรือราคาขึ้นเอง ถ้าข้อมูลไม่พอให้บอกตรง ๆ ว่าไม่มีข้อมูล
2. ราคาในบริบทเป็นราคาขายส่งตลาดกรุงเทพฯ ไม่ใช่ราคาหน้าล้ง ต้องบอกผู้ใช้ทุกครั้งที่พูดถึงราคาตลาด
3. ช่วงราคาและโอกาสราคาลงเป็นการประมาณจากสถิติ ไม่ใช่คำทำนายที่แน่นอน
4. ห้ามแนะนำให้ตัดทุเรียนก่อนแก่ได้เกณฑ์เพื่อรอราคา ต้องตรวจความแก่ของผลก่อนเสมอ
5. ถ้าคำนวณเงิน ให้แสดงวิธีคิดสั้น ๆ"""


REQUEST_TIMEOUT_MS = 25_000   # รอแต่ละคำขอไม่เกิน 25 วินาที
TOTAL_BUDGET_S = 40           # ลองทุกรุ่นรวมกันไม่เกิน 40 วินาที แล้วแจ้งผู้ใช้
BUSY_COOLDOWN_S = 120         # รุ่นที่เพิ่งตอบ 503/429 จะถูกย้ายไปลองท้ายสุด 2 นาที

# จำสถานะข้ามการเรียก (อยู่ระดับ module จึงใช้ร่วมกันทุกผู้ใช้ใน process เดียว)
_last_good = {"model": None}
_busy_until = {}


class GeminiBusyError(RuntimeError):
    """ทุกรุ่นไม่ว่างภายในเวลาที่กำหนด"""


class GeminiService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("ยังไม่ได้ระบุ GEMINI_API_KEY ในไฟล์ .env")
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),   # ไม่ให้ SDK ลองซ้ำเอง
        )
        self.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        # รุ่นสำรอง คั่นด้วยคอมมา เช่น GEMINI_FALLBACK_MODELS=รุ่นA,รุ่นB
        fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "")
        self.models = [self.model] + [m.strip() for m in fallbacks.split(",") if m.strip()]
        self.last_model_used = None
        self.azure = AzureFallback.from_env()

    def _order(self):
        """เรียงลำดับรุ่นที่จะลอง: รุ่นที่ตอบได้ล่าสุดก่อน -> รุ่นปกติ -> รุ่นที่เพิ่งไม่ว่างไว้ท้าย"""
        now = time.time()
        models = list(self.models)
        good = _last_good["model"]
        if good in models:
            models.remove(good)
            models.insert(0, good)
        ready = [m for m in models if _busy_until.get(m, 0) <= now]
        cooling = [m for m in models if _busy_until.get(m, 0) > now]
        return ready + cooling

    def _generate(self, contents, config):
        """ลองแต่ละรุ่นครั้งเดียว ไม่รอระหว่างรุ่น ถ้ารวมเกิน TOTAL_BUDGET_S ให้หยุดแล้วแจ้งผู้ใช้"""
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        t0 = time.time()
        last_err = None
        order = self._order()
        if self.azure and all(_busy_until.get(m, 0) > time.time() for m in order):
            raise GeminiBusyError("Gemini ทุกรุ่นเพิ่งไม่ว่าง ข้ามไปใช้ Azure")
        for model in order:
            if time.time() - t0 > TOTAL_BUDGET_S:
                break
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                _last_good["model"] = model
                _busy_until.pop(model, None)
                self.last_model_used = model
                return resp
            except errors.APIError as e:
                last_err = e
                if not (e.code == 429 or (e.code or 0) >= 500):
                    raise                      # key ผิด / รุ่นไม่มี / รูปพัง -> แจ้งทันที
                _busy_until[model] = time.time() + BUSY_COOLDOWN_S
                if _last_good["model"] == model:
                    _last_good["model"] = None
                print(f"⚠ {model} ไม่ว่าง ({e.code}) -> ลองรุ่นถัดไป")
            except Exception as e:             # noqa: BLE001  timeout / เน็ตหลุด -> ลองรุ่นถัดไป
                last_err = e
                _busy_until[model] = time.time() + BUSY_COOLDOWN_S
                print(f"⚠ {model} ไม่ตอบ ({type(e).__name__}) -> ลองรุ่นถัดไป")
        raise GeminiBusyError(f"ทุกรุ่นไม่ว่าง ใช้เวลา {time.time() - t0:.0f} วินาที "
                              f"(error ล่าสุด: {last_err})")

    def extract_receipt(self, image):
        """image: PIL.Image -> dict (มี buyer_name, date, grand_total เหมือนเดิม + ช่องใหม่)"""
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=RECEIPT_SCHEMA,
        )
        try:
            text = self._generate([image, RECEIPT_PROMPT], config).text
        except GeminiBusyError:
            if not self.azure:
                raise
            text = self._use_azure(self.azure.read_receipt, image)
        return _parse_receipt(text)

    def ask_assistant(self, user_question, farm_context):
        config = types.GenerateContentConfig(system_instruction=ASSISTANT_RULES, temperature=0.3)
        prompt = f"ข้อมูลบริบทของสวน:\n{farm_context}\n\nคำถามของผู้ใช้: {user_question}"
        try:
            return self._generate(prompt, config).text
        except GeminiBusyError:
            if not self.azure:
                raise
            return self._use_azure(self.azure.chat, prompt)

    def _use_azure(self, fn, arg):
        print(f"↪ Gemini ไม่ว่าง -> ใช้ Azure ({self.azure.deployment})")
        try:
            out = fn(arg)
        except Exception as e:   # noqa: BLE001
            raise GeminiBusyError(f"ทุกรุ่นไม่ว่าง รวม Azure (error: {e})") from e
        self.last_model_used = f"azure:{self.azure.deployment}"
        return out


def _parse_receipt(text):
    text = (text or "").strip()
    if text.startswith("```"):                      # กันไว้เผื่อโมเดลห่อด้วย ```json
        text = text.split("```")[1].removeprefix("json").strip()
    data = json.loads(text)
    data.setdefault("buyer_name", None)
    data.setdefault("date", None)
    data.setdefault("confidence", 0.5)
    return data


class AzureFallback:
    """Azure OpenAI / Microsoft Foundry ใช้เมื่อ Gemini ไม่ว่างทุกรุ่น
    ตั้งค่าใน .env:
        AZURE_OPENAI_ENDPOINT=https://<ชื่อ-resource>.openai.azure.com
        AZURE_OPENAI_API_KEY=...
        AZURE_OPENAI_DEPLOYMENT=<ชื่อ deployment ที่ตั้งตอน deploy โมเดล>
        AZURE_OPENAI_API_VERSION=   (เว้นว่าง = ใช้ v1 API / ถ้าใช้ไม่ได้ ใส่เวอร์ชันตามหน้า Deployment)
    โมเดลต้องอ่านรูปได้ (vision) ถ้าจะใช้อ่านใบชั่ง
    """

    def __init__(self, endpoint, key, deployment, api_version=None):
        from openai import AzureOpenAI, OpenAI
        endpoint = endpoint.rstrip("/")
        if api_version:
            self.client = AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=api_version,
                                      timeout=30, max_retries=1)
        else:
            base = endpoint if endpoint.endswith("/openai/v1") else f"{endpoint}/openai/v1"
            self.client = OpenAI(base_url=base + "/", api_key=key, timeout=30, max_retries=1)
        self.deployment = deployment

    @classmethod
    def from_env(cls):
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        key = os.getenv("AZURE_OPENAI_API_KEY")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not (endpoint and key and deployment):
            return None
        try:
            return cls(endpoint, key, deployment, os.getenv("AZURE_OPENAI_API_VERSION") or None)
        except Exception as e:   # noqa: BLE001
            print(f"⚠ ตั้งค่า Azure ไม่สำเร็จ ({e}) -> ใช้ Gemini อย่างเดียว")
            return None

    def chat(self, prompt):
        r = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": ASSISTANT_RULES},
                      {"role": "user", "content": prompt}])
        return r.choices[0].message.content

    def read_receipt(self, image):
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=90)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        instructions = (RECEIPT_PROMPT + "\n\nรูปแบบ JSON (JSON schema):\n"
                        + json.dumps(RECEIPT_SCHEMA, ensure_ascii=False))
        r = self.client.chat.completions.create(
            model=self.deployment,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": instructions},
                {"type": "image_url", "image_url": {"url": data_url}}]}])
        return r.choices[0].message.content


if __name__ == "__main__":
    # ทดสอบ: python gemini_service.py [path/to/receipt.jpg]
    import sys

    from dotenv import load_dotenv
    load_dotenv()
    g = GeminiService()
    print("รุ่นที่ตั้งไว้:", g.models, "+ Azure:", g.azure.deployment if g.azure else "ไม่ได้ตั้งค่า")
    print(g.ask_assistant("ตอบสั้น ๆ ว่าคุณพร้อมใช้งานไหม", "ยังไม่มีข้อมูล"))
    print("รุ่นที่ตอบจริง:", g.last_model_used)
    if len(sys.argv) > 1:
        from PIL import Image
        print(json.dumps(g.extract_receipt(Image.open(sys.argv[1])), ensure_ascii=False, indent=2))
