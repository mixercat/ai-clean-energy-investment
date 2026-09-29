"""บริการ AI ของเว็บ: Gemini เป็นหลัก -> Groq สำรอง -> Azure OpenAI สำรองสุดท้าย
- extract_receipt(): อ่านรูปใบชั่ง/ใบรับซื้อ หรือบิลค่าใช้จ่าย -> dict
- extract_receipt_pdf(): อ่านไฟล์ PDF (ทั้งแบบมีข้อความและแบบสแกน)
- extract_receipt_text(): อ่านข้อความที่ดึงจาก Word / Excel
- ask_assistant():  ตอบคำถามจากบริบทของสวน (บัญชี + ราคา + อากาศ)
ลำดับ: Gemini รุ่นหลัก -> Gemini รุ่นสำรอง -> Groq (ถ้าตั้ง GROQ_API_KEY) -> Azure (ถ้าตั้ง AZURE_OPENAI_*)
ตัวสำรองที่ไม่ได้ตั้งค่าใน .env จะถูกข้ามไปเอง
ชื่อ class และชื่อฟังก์ชันเหมือนเวอร์ชันเดิม app.py จึงไม่ต้องแก้
"""
import base64
import hashlib
import io
import json
import os
import re
import time

from google import genai
from google.genai import errors, types

DEFAULT_MODEL = "gemini-3.8-flash"   # ถ้ารุ่นนี้ใช้ไม่ได้ ให้ตั้ง GEMINI_MODEL ใน .env ตามชื่อใน AI Studio

RECEIPT_PROMPT = """คุณคือระบบอ่านเอกสารของสวนทุเรียน อ่านเอกสาร (รูป PDF หรือข้อความ) แล้วตอบเป็น JSON ตาม schema เท่านั้น
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
5. ถ้าคำนวณเงิน ให้แสดงวิธีคิดสั้น ๆ
6. เรื่องปุ๋ย ยา และสารเคมี ให้ยึดตาม "คลังความรู้" ในบริบทและฉลากผลิตภัณฑ์ ห้ามแต่งชื่อสารหรืออัตราผสมขึ้นเอง
   ห้ามแนะนำสารต้องห้าม (เช่น พาราควอต คลอร์ไพริฟอส) และถ้าอาการรุนแรงให้แนะนำปรึกษาสำนักงานเกษตรอำเภอ
7. ถ้าถามเรื่องพ่นยาหรือใส่ปุ๋ย ให้ดูพยากรณ์ฝนรายวันในบริบท แล้วบอกวันที่เหมาะและวันที่ควรเลี่ยง
8. ถ้าใช้ข้อมูลจากคลังความรู้ ให้บอกที่มาสั้น ๆ ท้ายคำตอบ ถ้าไม่มีในบริบทให้บอกว่าเป็นคำแนะนำทั่วไป"""


REQUEST_TIMEOUT_MS = 25_000   # รอ Gemini แต่ละคำขอไม่เกิน 25 วินาที
TOTAL_BUDGET_S = 40           # ลอง Gemini ทุกรุ่นรวมกันไม่เกิน 40 วินาที แล้วไปตัวสำรอง
BUSY_COOLDOWN_S = 120         # รุ่นที่เพิ่งตอบ 503/429 จะถูกย้ายไปลองท้ายสุด 2 นาที

# จำสถานะข้ามการเรียก (อยู่ระดับ module จึงใช้ร่วมกันทุกผู้ใช้ใน process เดียว)
_last_good = {}       # {key-id: รุ่นที่ตอบได้ล่าสุด}  แยกตาม API key แต่ละชุด
_busy_until = {}      # {(key-id, รุ่น): เวลาที่พ้นช่วงพัก}


class GeminiBusyError(RuntimeError):
    """Gemini และตัวสำรองทุกตัวไม่ว่าง"""


class GeminiService:
    """keys=None -> ใช้ key ของระบบจาก .env
    keys=dict   -> ใช้ key ที่ผู้ใช้ใส่เองในหน้าตั้งค่าเท่านั้น (ไม่ใช้ key ของระบบ)
        {"gemini_key", "gemini_model", "groq_key", "azure_endpoint", "azure_key", "azure_deployment"}"""

    def __init__(self, keys=None):
        self.user_keys = keys is not None
        get = (lambda k, env, d=None: (keys.get(k) or d)) if keys is not None \
            else (lambda k, env, d=None: os.getenv(env) or d)
        api_key = get("gemini_key", "GEMINI_API_KEY")
        self.client = None
        self._ns = hashlib.sha1((api_key or "-").encode()).hexdigest()[:10]
        if api_key:
            self.client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),   # ไม่ให้ SDK ลองซ้ำเอง
            )
        self.model = get("gemini_model", "GEMINI_MODEL") or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        # รุ่นสำรอง คั่นด้วยคอมมา เช่น GEMINI_FALLBACK_MODELS=รุ่นA,รุ่นB
        fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "")
        self.models = [self.model] + [m.strip() for m in fallbacks.split(",") if m.strip() and m.strip() != self.model]
        self.last_model_used = None
        # ตัวสำรองนอก Gemini ตามลำดับ (ตัวที่ไม่ได้ตั้งค่าจะเป็น None และถูกตัดออก)
        self.backups = [b for b in (
            GroqFallback.from_env(key=get("groq_key", "GROQ_API_KEY")),
            AzureFallback.from_env(endpoint=get("azure_endpoint", "AZURE_OPENAI_ENDPOINT"),
                                   key=get("azure_key", "AZURE_OPENAI_API_KEY"),
                                   deployment=get("azure_deployment", "AZURE_OPENAI_DEPLOYMENT")),
        ) if b]
        if not self.client and not self.backups:
            raise ValueError("ยังไม่ได้ใส่ API key ของ AI (Gemini หรือ Groq) — ไปที่แท็บ ⚙️ ตั้งค่า"
                             if keys is not None else "ยังไม่ได้ระบุ GEMINI_API_KEY ในไฟล์ .env")

    def test_connections(self):
        """ทดสอบทุกผู้ให้บริการที่ตั้งค่าไว้ -> list ของ (ชื่อ, สำเร็จไหม, ข้อความ, วินาที)"""
        out = []
        if self.client:
            t0 = time.time()
            try:
                r = self.client.models.generate_content(model=self.model, contents="ตอบคำเดียวว่า พร้อม")
                out.append((f"Gemini ({self.model})", True, (r.text or "").strip()[:40], time.time() - t0))
            except Exception as e:   # noqa: BLE001
                out.append((f"Gemini ({self.model})", False, _short_err(e), time.time() - t0))
        for b in self.backups:
            t0 = time.time()
            try:
                out.append((b.label, True, b.chat("ตอบคำเดียวว่า พร้อม")[:40], time.time() - t0))
            except Exception as e:   # noqa: BLE001
                out.append((b.label, False, _short_err(e), time.time() - t0))
        return out

    @property
    def azure(self):          # เผื่อโค้ดเก่าที่อ้าง .azure
        return next((b for b in self.backups if b.name == "azure"), None)

    def _order(self):
        """เรียงลำดับรุ่นที่จะลอง: รุ่นที่ตอบได้ล่าสุดก่อน -> รุ่นปกติ -> รุ่นที่เพิ่งไม่ว่างไว้ท้าย"""
        now = time.time()
        models = list(self.models)
        good = _last_good.get(self._ns)
        if good in models:
            models.remove(good)
            models.insert(0, good)
        ready = [m for m in models if _busy_until.get((self._ns, m), 0) <= now]
        cooling = [m for m in models if _busy_until.get((self._ns, m), 0) > now]
        return ready + cooling

    def _generate(self, contents, config):
        """ลองแต่ละรุ่นครั้งเดียว ไม่รอระหว่างรุ่น ถ้ารวมเกิน TOTAL_BUDGET_S ให้หยุด"""
        if self.client is None:
            raise GeminiBusyError("ไม่ได้ตั้งค่า Gemini ใช้ตัวสำรองแทน")
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        t0 = time.time()
        last_err = None
        order = self._order()
        if self.backups and all(_busy_until.get((self._ns, m), 0) > time.time() for m in order):
            raise GeminiBusyError("Gemini ทุกรุ่นเพิ่งไม่ว่าง ข้ามไปใช้ตัวสำรอง")
        for model in order:
            if time.time() - t0 > TOTAL_BUDGET_S:
                break
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                _last_good[self._ns] = model
                _busy_until.pop((self._ns, model), None)
                self.last_model_used = model
                return resp
            except errors.APIError as e:
                last_err = e
                if not (e.code == 429 or (e.code or 0) >= 500):
                    raise                      # key ผิด / รุ่นไม่มี / ไฟล์พัง -> แจ้งทันที
                _busy_until[(self._ns, model)] = time.time() + BUSY_COOLDOWN_S
                if _last_good.get(self._ns) == model:
                    _last_good.pop(self._ns, None)
                print(f"⚠ {model} ไม่ว่าง ({e.code}) -> ลองรุ่นถัดไป")
            except Exception as e:             # noqa: BLE001  timeout / เน็ตหลุด -> ลองรุ่นถัดไป
                last_err = e
                _busy_until[(self._ns, model)] = time.time() + BUSY_COOLDOWN_S
                print(f"⚠ {model} ไม่ตอบ ({type(e).__name__}) -> ลองรุ่นถัดไป")
        raise GeminiBusyError(f"Gemini ทุกรุ่นไม่ว่าง ใช้เวลา {time.time() - t0:.0f} วินาที "
                              f"(error ล่าสุด: {last_err})")

    def _use_backups(self, method, arg):
        """ลองตัวสำรองทีละตัว (Groq -> Azure) คืนผลของตัวแรกที่ตอบได้"""
        if not self.backups:
            raise GeminiBusyError("Gemini ไม่ว่าง และยังไม่ได้ตั้งค่าตัวสำรอง (GROQ / AZURE) ใน .env")
        errs = []
        for b in self.backups:
            fn = getattr(b, method, None)
            if fn is None or not b.supports(method):
                continue
            print(f"↪ ใช้ตัวสำรอง {b.label}")
            try:
                out = fn(arg)
                self.last_model_used = b.label
                return out
            except Exception as e:   # noqa: BLE001
                print(f"⚠ {b.label} ใช้ไม่ได้ ({type(e).__name__}: {str(e)[:200]})")
                errs.append(f"{b.label}: {e}")
        raise GeminiBusyError("ทุกรุ่นไม่ว่าง รวมตัวสำรอง (" + " | ".join(errs)[:500] + ")")

    # ------------------------------------------------------------------ งานที่ app เรียก
    def extract_receipt(self, image):
        """image: PIL.Image -> dict (มี buyer_name, date, grand_total + รายการสินค้า)"""
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_schema=RECEIPT_SCHEMA)
        try:
            text = self._generate([image, RECEIPT_PROMPT], config).text
        except GeminiBusyError:
            text = self._use_backups("read_receipt", image)
        return _parse_receipt(text)

    def extract_receipt_pdf(self, pdf_bytes):
        """PDF -> dict  Gemini อ่าน PDF ได้ตรง ๆ (รวม PDF ที่สแกนเป็นรูป)
        ตัวสำรองอ่านได้เฉพาะข้อความใน PDF (PDF สแกนจึงอ่านได้แค่ด้วย Gemini)"""
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_schema=RECEIPT_SCHEMA)
        part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        try:
            text = self._generate([part, RECEIPT_PROMPT], config).text
        except GeminiBusyError:
            from file_import import pdf_info
            _, content = pdf_info(pdf_bytes)
            if len(content) < 20:
                raise GeminiBusyError("Gemini ไม่ว่าง และ PDF นี้เป็นภาพสแกน ตัวสำรองอ่านไม่ได้") from None
            text = self._use_backups("read_receipt_text", content)
        return _parse_receipt(text)

    def extract_receipt_text(self, content):
        """ข้อความจาก Word/Excel -> dict (อ่านเป็นเอกสาร 1 ใบ)"""
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_schema=RECEIPT_SCHEMA)
        prompt = f"{RECEIPT_PROMPT}\n\nเนื้อหาเอกสาร:\n{content[:30000]}"
        try:
            text = self._generate(prompt, config).text
        except GeminiBusyError:
            text = self._use_backups("read_receipt_text", content)
        return _parse_receipt(text)

    def ask_assistant(self, user_question, farm_context):
        config = types.GenerateContentConfig(system_instruction=ASSISTANT_RULES, temperature=0.3)
        prompt = f"ข้อมูลบริบทของสวน:\n{farm_context}\n\nคำถามของผู้ใช้: {user_question}"
        try:
            return self._generate(prompt, config).text
        except GeminiBusyError:
            return self._use_backups("chat", prompt)


def _short_err(e):
    s = str(e)
    for code, th in [("401", "API key ไม่ถูกต้อง"), ("403", "key นี้ไม่มีสิทธิ์ใช้งานรุ่นนี้"),
                     ("API_KEY_INVALID", "API key ไม่ถูกต้อง"), ("404", "ไม่พบรุ่น/ชื่อ deployment นี้"),
                     ("429", "ใช้งานเกินโควตา ลองใหม่ภายหลัง"), ("503", "ผู้ให้บริการไม่ว่างชั่วคราว")]:
        if code in s:
            return th
    return s[:120]


def _strip_think(text):
    """ตัดส่วน <think>...</think> ที่บางโมเดล (เช่น Qwen) ใส่มาก่อนคำตอบ"""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def _parse_receipt(text):
    text = _strip_think(text)
    if text.startswith("```"):                      # กันไว้เผื่อโมเดลห่อด้วย ```json
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:                    # มีข้อความอื่นปน -> ดึงเฉพาะก้อน {...}
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise ValueError("AI ตอบกลับมาไม่ใช่ JSON ลองใหม่อีกครั้ง") from None
        data = json.loads(m.group(0))
    data.setdefault("buyer_name", None)
    data.setdefault("date", None)
    data.setdefault("confidence", 0.5)
    return data


def _image_data_url(image, max_side=1600):
    """ย่อรูปแล้วแปลงเป็น data URL (Groq รับรูปแบบ base64 ได้ไม่เกิน ~4 MB)"""
    img = image.convert("RGB") if image.mode not in ("RGB", "L") else image.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    try:
        img.save(buf, format="JPEG", quality=85)
        mime = "image/jpeg"
    except (KeyError, OSError):                      # เครื่องที่ไม่มีตัวเข้ารหัส JPEG
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


RECEIPT_JSON_INSTRUCTIONS = (RECEIPT_PROMPT + "\n\nตอบเป็น JSON object ก้อนเดียว ไม่มีข้อความอื่น ตามรูปแบบ (JSON schema):\n"
                             + json.dumps(RECEIPT_SCHEMA, ensure_ascii=False))


class OpenAICompatibleBackup:
    """ตัวสำรองที่ใช้ API แบบ OpenAI (Groq, Azure OpenAI)
    api = "chat" ใช้ Chat Completions / "responses" ใช้ Responses API (จำเป็นสำหรับรุ่น pro)"""
    name = "backup"

    def __init__(self, client, chat_model, vision_model=None, api="chat", reasoning=None):
        self.client = client
        self.chat_model = chat_model
        self.vision_model = vision_model
        self.api = api
        self.reasoning = reasoning
        self.label = f"{self.name}:{chat_model}"

    def supports(self, method):
        return method != "read_receipt" or bool(self.vision_model)

    # ---------------------------------------------------------------- เรียกโมเดล
    def _call(self, model, system, user_content, json_mode=False):
        if self.api == "responses":
            parts = [{"type": "input_text", "text": c["text"]} if c["type"] == "text"
                     else {"type": "input_image", "image_url": c["image_url"]["url"]} for c in user_content]
            kw = {"reasoning": {"effort": self.reasoning}} if self.reasoning else {}
            r = self.client.responses.create(model=model, instructions=system,
                                             input=[{"role": "user", "content": parts}], **kw)
            return r.output_text
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            r = self.client.chat.completions.create(model=model, messages=messages, **kw)
        except Exception as e:   # noqa: BLE001  บางรุ่นไม่รองรับ JSON mode -> ลองแบบธรรมดา
            if not json_mode or getattr(e, "status_code", None) != 400:
                raise
            r = self.client.chat.completions.create(model=model, messages=messages)
        return _strip_think(r.choices[0].message.content)

    # ---------------------------------------------------------------- งานที่ GeminiService เรียก
    def chat(self, prompt):
        return self._call(self.chat_model, ASSISTANT_RULES, [{"type": "text", "text": prompt}])

    def read_receipt(self, image):
        content = [{"type": "text", "text": "อ่านเอกสารในรูปนี้"},
                   {"type": "image_url", "image_url": {"url": _image_data_url(image)}}]
        return self._call(self.vision_model, RECEIPT_JSON_INSTRUCTIONS, content, json_mode=True)

    def read_receipt_text(self, content):
        return self._call(self.chat_model, RECEIPT_JSON_INSTRUCTIONS,
                          [{"type": "text", "text": "เนื้อหาเอกสาร:\n" + content[:30000]}], json_mode=True)


class GroqFallback(OpenAICompatibleBackup):
    """Groq (สมัครฟรีที่ console.groq.com) ตั้งค่าใน .env:
        GROQ_API_KEY=gsk_...
        GROQ_MODEL=openai/gpt-oss-120b          (ตอบแชต + อ่านข้อความจาก Word/Excel/PDF)
        GROQ_VISION_MODEL=qwen/qwen3.8-27b      (อ่านรูป ถ้าไม่อยากใช้ให้เว้นว่าง)
    """
    name = "groq"

    @classmethod
    def from_env(cls, key=None):
        key = key or None
        if not key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key,
                            timeout=float(os.getenv("GROQ_TIMEOUT", "30")), max_retries=0)
            vision = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip() or None
            return cls(client, os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), vision)
        except Exception as e:   # noqa: BLE001
            print(f"⚠ ตั้งค่า Groq ไม่สำเร็จ ({e}) -> ข้าม Groq")
            return None


class AzureFallback(OpenAICompatibleBackup):
    """Azure OpenAI / Microsoft Foundry ตั้งค่าใน .env:
        AZURE_OPENAI_ENDPOINT=https://<ชื่อ-resource>.openai.azure.com
        AZURE_OPENAI_API_KEY=...
        AZURE_OPENAI_DEPLOYMENT=<ชื่อ deployment เช่น gpt-5.4-pro>
        AZURE_OPENAI_API_VERSION=   (เว้นว่าง = ใช้ v1 API ซึ่งแนะนำ)
        AZURE_OPENAI_API=auto       (auto = รุ่นชื่อมี "pro" ใช้ Responses API นอกนั้นใช้ Chat Completions)
        AZURE_OPENAI_REASONING=     (เช่น medium; รุ่น pro รองรับ medium/high/xhigh)
        AZURE_OPENAI_TIMEOUT=120    (วินาที รุ่น pro คิดนาน)
    """
    name = "azure"

    @classmethod
    def from_env(cls, endpoint=None, key=None, deployment=None):
        if not (endpoint and key and deployment):
            return None
        try:
            from openai import AzureOpenAI, OpenAI
            endpoint = endpoint.rstrip("/")
            api = os.getenv("AZURE_OPENAI_API", "auto").lower()
            if api == "auto":
                api = "responses" if "pro" in deployment.lower() else "chat"
            timeout = float(os.getenv("AZURE_OPENAI_TIMEOUT", "120" if api == "responses" else "30"))
            version = os.getenv("AZURE_OPENAI_API_VERSION") or None
            if version:
                client = AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=version,
                                     timeout=timeout, max_retries=0)
            else:
                base = endpoint if endpoint.endswith("/openai/v1") else f"{endpoint}/openai/v1"
                client = OpenAI(base_url=base + "/", api_key=key, timeout=timeout, max_retries=0)
            reasoning = os.getenv("AZURE_OPENAI_REASONING") or None
            return cls(client, deployment, deployment, api=api, reasoning=reasoning)   # รุ่นเดียวอ่านรูปได้
        except Exception as e:   # noqa: BLE001
            print(f"⚠ ตั้งค่า Azure ไม่สำเร็จ ({e}) -> ข้าม Azure")
            return None


if __name__ == "__main__":
    # ทดสอบ: python gemini_service.py [path/to/receipt.jpg]   (ทดสอบตัวสำรอง: เพิ่ม --backup)
    import sys

    from dotenv import load_dotenv
    load_dotenv()
    g = GeminiService()
    print("Gemini:", g.models, "| ตัวสำรอง:", [b.label for b in g.backups] or "ไม่ได้ตั้งค่า")
    if "--backup" in sys.argv:
        for b in g.backups:
            t0 = time.time()
            try:
                print(f"{b.label}: {b.chat('ตอบสั้น ๆ ว่าพร้อมใช้งานไหม')[:120]} ({time.time() - t0:.1f} วิ)")
            except Exception as e:   # noqa: BLE001
                print(f"{b.label}: ใช้ไม่ได้ -> {e}")
    else:
        print(g.ask_assistant("ตอบสั้น ๆ ว่าคุณพร้อมใช้งานไหม", "ยังไม่มีข้อมูล"))
        print("รุ่นที่ตอบจริง:", g.last_model_used)
    imgs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if imgs:
        from PIL import Image
        print(json.dumps(g.extract_receipt(Image.open(imgs[0])), ensure_ascii=False, indent=2))
