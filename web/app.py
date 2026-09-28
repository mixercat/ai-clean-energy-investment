"""DurianOS — สมุดบัญชีสวนทุเรียนอัจฉริยะ
รัน:  python -m streamlit run app.py   (จากในโฟลเดอร์ web)
"""
import os
from datetime import date
 
import altair as alt
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image
 
load_dotenv()
 
st.set_page_config(page_title="DurianOS | สมุดบัญชีสวนทุเรียน", page_icon="🍈", layout="wide",
                   initial_sidebar_state="expanded")
 
from firebase_auth import FirebaseAuthService          # noqa: E402  (ต้อง import หลัง set_page_config)
from forecast_service import ForecastService           # noqa: E402
from gemini_service import GeminiService               # noqa: E402
from ledger_service import (EXPENSE, EXPENSE_CATS, INCOME, INCOME_CATS,  # noqa: E402
                            LedgerService)
 
FARM_LAT, FARM_LON = 12.6114, 102.1039      # จันทบุรี (ใช้กับพยากรณ์อากาศ)
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
THAI_DAYS = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]
# สีสำหรับ HTML = ตัวแปร CSS (เปลี่ยนตามโหมดสว่าง/มืดอัตโนมัติ)
C_GREEN, C_RED, C_GOLD, C_SKY, C_MUTED = "var(--green)", "var(--red)", "var(--gold)", "var(--sky)", "var(--muted)"
# สีสำหรับกราฟ = โทนกลาง อ่านชัดทั้งพื้นสว่างและพื้นมืด
CH = {"green": "#22c55e", "red": "#ef4444", "gold": "#eab308", "sky": "#0ea5e9", "slate": "#8595a8",
      "axis": "#8a9a91", "grid": "rgba(128,128,128,.16)"}
 
# ====================================================================== STYLE
DARK_VARS = """
  --bg:#07110b; --glow1:rgba(34,197,94,.16); --glow2:rgba(250,204,21,.07);
  --card:rgba(255,255,255,.035); --card-2:rgba(255,255,255,.065); --card-hover:rgba(255,255,255,.05);
  --line:rgba(255,255,255,.08); --text:#e8f5ec; --text-2:#cbd5e1; --muted:#94a3b8;
  --green:#4ade80; --red:#f87171; --gold:#facc15; --sky:#38bdf8;
  --accent-bg:rgba(34,197,94,.13); --accent-bd:rgba(74,222,128,.28);
  --sidebar:rgba(9,18,12,.94); --shadow:0 18px 40px -24px rgba(0,0,0,.85);
  --gold-bg:rgba(250,204,21,.08); --gold-bd:rgba(250,204,21,.25); --gold-tx:#fde68a;
  --sky-bg:rgba(56,189,248,.08); --sky-bd:rgba(56,189,248,.25); --sky-tx:#bae6fd;
  --red-bg:rgba(248,113,113,.08); --red-bd:rgba(248,113,113,.3); --red-tx:#fecaca;
"""
LIGHT_VARS = """
  --bg:#f3f7f4; --glow1:rgba(34,197,94,.13); --glow2:rgba(234,179,8,.10);
  --card:#ffffff; --card-2:#f1f6f2; --card-hover:#fbfdfb;
  --line:rgba(15,36,23,.09); --text:#0f2417; --text-2:#334155; --muted:#64748b;
  --green:#15803d; --red:#dc2626; --gold:#b45309; --sky:#0369a1;
  --accent-bg:rgba(22,163,74,.10); --accent-bd:rgba(22,163,74,.30);
  --sidebar:#ffffff; --shadow:0 12px 32px -20px rgba(15,36,23,.28);
  --gold-bg:#fffbeb; --gold-bd:#fcd34d; --gold-tx:#854d0e;
  --sky-bg:#f0f9ff; --sky-bd:#7dd3fc; --sky-tx:#075985;
  --red-bg:#fef2f2; --red-bd:#fca5a5; --red-tx:#991b1b;
"""
CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{ {DARK_VARS} }}
@media (prefers-color-scheme: light){{ html:not([data-theme]){{ {LIGHT_VARS} }} }}
html[data-theme="light"]{{ {LIGHT_VARS} }}
html[data-theme="dark"]{{ {DARK_VARS} }}
html, body, [class*="css"], .stMarkdown, p, label, input, textarea, button, h1, h2, h3, h4 {{
  font-family:'Prompt', sans-serif !important;
}}
.stApp{{
  background-image:
    radial-gradient(1200px 600px at 8% -12%, var(--glow1), transparent 60%),
    radial-gradient(900px 500px at 100% 0%, var(--glow2), transparent 60%);
  background-attachment:fixed; color:var(--text);
}}
.block-container{{padding:1.6rem 2.5rem 3rem 2.5rem; max-width:none;}}
#MainMenu, footer, [data-testid="stToolbar"]{{visibility:hidden;}}
header[data-testid="stHeader"]{{background:transparent;}}
[data-testid="stSidebar"]{{background:var(--sidebar); border-right:1px solid var(--line);}}
/* การ์ด: st.container(key="card-...") */
[class*="st-key-card"]{{
  background:var(--card); border:1px solid var(--line); border-radius:20px;
  padding:22px 24px; box-shadow:var(--shadow); transition:border-color .2s, box-shadow .2s;
}}
[class*="st-key-card"]:hover{{border-color:var(--accent-bd);}}
.card-title{{font-size:1.12rem; font-weight:600; margin:0 0 2px 0; color:var(--text); display:flex; gap:8px; align-items:center;}}
.card-sub{{font-size:.84rem; color:var(--muted); margin:0 0 14px 0;}}
/* KPI */
.kpi{{position:relative; overflow:hidden; background:var(--card); border:1px solid var(--line);
  border-radius:18px; padding:16px 18px; height:100%; box-shadow:var(--shadow);}}
.kpi::before{{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--accent, transparent); opacity:.9;}}
.kpi .lbl{{font-size:.8rem; color:var(--muted); display:flex; gap:6px; align-items:center;}}
.kpi .val{{font-size:1.55rem; font-weight:700; margin-top:4px; letter-spacing:-.01em;}}
.kpi .sub{{font-size:.78rem; color:var(--muted); margin-top:2px;}}
/* hero / badge / note */
.hero-kicker{{display:inline-block; padding:4px 12px; border-radius:999px; font-size:.78rem;
  background:var(--accent-bg); color:var(--green); border:1px solid var(--accent-bd);}}
.hero-title{{font-size:1.95rem; font-weight:700; margin:10px 0 2px 0; color:var(--text); letter-spacing:-.01em;}}
.hero-sub{{color:var(--muted); font-size:.92rem;}}
.note{{border-radius:14px; padding:12px 16px; font-size:.88rem; line-height:1.6; margin:8px 0;}}
.note.gold{{background:var(--gold-bg); border:1px solid var(--gold-bd); color:var(--gold-tx);}}
.note.sky{{background:var(--sky-bg); border:1px solid var(--sky-bd); color:var(--sky-tx);}}
.note.red{{background:var(--red-bg); border:1px solid var(--red-bd); color:var(--red-tx);}}
.pill{{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:600;}}
.muted{{color:var(--muted);}}
/* ปุ่ม */
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button{{border-radius:12px; font-weight:600; transition:.15s;}}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"]{{
  background:linear-gradient(135deg,#22c55e,#15803d); border:none; color:#fff;}}
.stButton>button:hover, .stDownloadButton>button:hover{{transform:translateY(-1px);}}
/* แท็บแบบแคปซูล */
.stTabs [role="tablist"]{{gap:4px; padding:5px; background:var(--card); border:1px solid var(--line);
  border-radius:16px; width:fit-content; max-width:100%; overflow-x:auto; box-shadow:var(--shadow);}}
.stTabs [data-testid="stTab"]{{padding:9px 18px; border-radius:12px; transition:background .15s;}}
.stTabs [data-testid="stTab"] p{{font-weight:500; color:var(--muted);}}
.stTabs [data-testid="stTab"]:hover{{background:var(--card-2);}}
.stTabs [data-testid="stTab"][aria-selected="true"]{{background:var(--accent-bg);}}
.stTabs [data-testid="stTab"][aria-selected="true"] p{{color:var(--green); font-weight:600;}}
.stTabs .react-aria-SelectionIndicator{{display:none;}}
.stTabs [role="tabpanel"]{{padding-top:14px;}}
html.theme-switching [data-testid="stMainMenuPopover"]{{opacity:0 !important; pointer-events:none !important;}}
/* วันพยากรณ์อากาศ */
.day{{background:var(--card-2); border:1px solid var(--line); border-radius:14px; padding:10px 8px; text-align:center; height:100%;}}
.day .d{{font-size:.78rem; color:var(--muted);}} .day .i{{font-size:1.4rem; margin:2px 0;}}
.day .r{{font-weight:600; font-size:.9rem;}} .day .t{{font-size:.72rem; color:var(--muted);}}
.stat{{display:flex; gap:10px; flex-wrap:wrap; margin:6px 0 12px;}}
.stat div{{font-size:.76rem; color:var(--muted); background:var(--card-2); border:1px solid var(--line);
  border-radius:12px; padding:8px 12px; min-width:110px;}}
.stat b{{display:block; font-size:1.05rem; color:var(--text); font-weight:600; margin-top:2px;}}
/* sidebar */
.side-brand{{display:flex; gap:10px; align-items:center; margin:4px 0 18px;}}
.side-brand .logo{{width:38px; height:38px; border-radius:12px; display:flex; align-items:center; justify-content:center;
  font-size:1.3rem; background:var(--accent-bg); border:1px solid var(--accent-bd);}}
.side-brand b{{font-size:1.1rem; color:var(--text);}} .side-brand span{{display:block; font-size:.72rem; color:var(--muted);}}
/* ปุ่มสลับธีม */
.theme-wrap{{display:flex; justify-content:flex-end; align-items:center; gap:8px; padding-top:6px;}}
.theme-btn{{font-family:'Prompt',sans-serif; cursor:pointer; display:inline-flex; align-items:center; gap:8px;
  padding:8px 14px; border-radius:999px; border:1px solid var(--line); background:var(--card);
  color:var(--text); font-size:.85rem; font-weight:500; box-shadow:var(--shadow); transition:.15s;}}
.theme-btn:hover{{border-color:var(--accent-bd); transform:translateY(-1px);}}
.theme-btn .to-light{{display:inline;}} .theme-btn .to-dark{{display:none;}}
html[data-theme="light"] .theme-btn .to-light{{display:none;}} html[data-theme="light"] .theme-btn .to-dark{{display:inline;}}
.date-chip{{font-size:.8rem; color:var(--muted); padding:8px 12px; border-radius:999px; border:1px solid var(--line); background:var(--card);}}
/* หน้า login */
.login-brand{{text-align:center; margin:3vh 0 18px 0;}}
.login-logo{{width:68px; height:68px; border-radius:20px; display:inline-flex; align-items:center;
  justify-content:center; font-size:2.1rem; background:var(--accent-bg); border:1px solid var(--accent-bd); box-shadow:var(--shadow);}}
.feat{{display:flex; gap:12px; align-items:flex-start; margin:10px 0; font-size:.9rem; color:var(--text-2);
  background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 14px;}}
.feat b{{color:var(--text);}}
</style>
"""
# Streamlit จะแสดง CSS เป็นข้อความถ้ามีบรรทัดว่าง จึงตัดบรรทัดว่างออกอัตโนมัติ
st.markdown("\n".join(line for line in CSS.splitlines() if line.strip()), unsafe_allow_html=True)
 
# ปุ่มสลับโหมดสว่าง/มืด: สั่งตัวเลือกธีมในเมนูของ Streamlit (จำค่าไว้ในเบราว์เซอร์ ไม่ต้อง login ใหม่)
# และติดป้าย data-theme ที่ <html> ให้ CSS ด้านบนเปลี่ยนสีตาม
THEME_JS = """
<script>
if (!window.__durianTheme) {
  window.__durianTheme = true;
  const detect = () => {
    const app = document.querySelector('.stApp');
    if (!app) return;
    const m = getComputedStyle(app).backgroundColor.match(/\\d+/g);
    if (!m) return;
    const lum = (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255;
    const t = lum > 0.5 ? 'light' : 'dark';
    if (document.documentElement.dataset.theme !== t) document.documentElement.dataset.theme = t;
  };
  detect(); setInterval(detect, 300);
  const press = (el) => ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(tp =>
    el.dispatchEvent(new (tp.startsWith('pointer') ? PointerEvent : MouseEvent)(tp,
      {bubbles: true, cancelable: true, view: window, button: 0})));
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.theme-btn')) return;
    const want = document.documentElement.dataset.theme === 'light' ? 'Dark' : 'Light';
    const menu = document.querySelector('[data-testid="stMainMenuButton"]');
    if (!menu) { alert('เปลี่ยนธีมได้ที่เมนู ⋮ มุมขวาบน'); return; }
    const root = document.documentElement;
    root.classList.add('theme-switching');           // ซ่อนเมนูระหว่างสลับ ไม่ให้กระพริบ
    press(menu);
    let n = 0;
    const t = setInterval(() => {
      const item = document.querySelector('[data-testid="stMainMenuItem-theme-' + want + '"]');
      if (item || ++n > 40) {
        clearInterval(t);
        if (item) item.click();
        setTimeout(() => {
          if (document.querySelector('[data-testid="stMainMenuList"]')) press(menu);   // ปิดเมนู
          setTimeout(() => root.classList.remove('theme-switching'), 250);
        }, 60);
      }
    }, 25);
  });
}
</script>
"""
 
 
def theme_toggle(extra=""):
    st.html(f'<div class="theme-wrap">{extra}<button class="theme-btn" type="button">'
            '<span class="to-light">☀️ โหมดสว่าง</span><span class="to-dark">🌙 โหมดมืด</span></button></div>'
            + THEME_JS, unsafe_allow_javascript=True)
 
 
# ====================================================================== HELPERS
def th_date(d, with_year=True):
    if d is None or pd.isna(d):
        return "-"
    d = pd.to_datetime(d)
    return f"{d.day} {THAI_MONTHS[d.month - 1]}" + (f" {d.year + 543}" if with_year else "")
 
 
def baht(x, dec=0):
    return f"฿{x:,.{dec}f}"
 
 
def kpi(label, value, color=None, sub=""):
    color = color or "var(--text)"
    return (f'<div class="kpi" style="--accent:{color}"><div class="lbl">{label}</div>'
            f'<div class="val" style="color:{color}">{value}</div>'
            f'<div class="sub">{sub}</div></div>')
 
 
def card_header(title, sub=""):
    st.markdown(f'<div class="card-title">{title}</div>'
                + (f'<div class="card-sub">{sub}</div>' if sub else ""), unsafe_allow_html=True)
 
 
def note(text, tone="gold"):
    st.markdown(f'<div class="note {tone}">{text}</div>', unsafe_allow_html=True)
 
 
def chart_style(chart, height=260):
    """แต่งกราฟ Altair ให้อ่านง่ายทั้งโหมดสว่างและมืด (พื้นโปร่ง สีแกนกลาง ๆ)"""
    return (chart.properties(height=height, background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=CH["axis"], titleColor=CH["axis"], gridColor=CH["grid"],
                            domainColor=CH["grid"], tickColor=CH["grid"], labelFont="Prompt", titleFont="Prompt")
            .configure_legend(labelColor=CH["axis"], titleColor=CH["axis"], labelFont="Prompt",
                              titleFont="Prompt", orient="top")
            .configure_text(font="Prompt"))
 
 
def ai_error_message(e):
    s = str(e)
    if "ทุกรุ่นไม่ว่าง" in s or "503" in s or "429" in s or "UNAVAILABLE" in s:
        return "ระบบ AI มีผู้ใช้งานมากในขณะนี้ กรุณารอสักครู่แล้วลองใหม่อีกครั้ง"
    return f"เกิดข้อผิดพลาดจากระบบ AI: {s[:300]}"
 
 
@st.cache_resource(show_spinner=False)
def get_gemini():
    try:
        return GeminiService(), None
    except Exception as e:   # noqa: BLE001
        return None, str(e)
 
 
@st.cache_data(ttl=3600, show_spinner=False)
def get_fx(days=60):
    """ค่าเงินหยวน/บาท จาก Frankfurter (ECB) -> DataFrame date, rate หรือ None ถ้าดึงไม่ได้"""
    start = (pd.Timestamp.today() - pd.DateOffset(days=days)).strftime("%Y-%m-%d")
    try:
        r = requests.get(f"https://api.frankfurter.dev/v1/{start}..",
                         params={"base": "CNY", "symbols": "THB"}, timeout=10)
        r.raise_for_status()
        rates = r.json().get("rates", {})
        df = pd.DataFrame([{"date": pd.to_datetime(k), "rate": v["THB"]} for k, v in rates.items()])
        return df.sort_values("date").reset_index(drop=True) if not df.empty else None
    except Exception:   # noqa: BLE001
        return None
 
 
@st.cache_data(ttl=3600, show_spinner=False)
def get_weather(past_days=7, forecast_days=14):
    """ฝน/อุณหภูมิรายวัน ย้อนหลัง + ล่วงหน้า จาก Open-Meteo ในคำขอเดียว"""
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": FARM_LAT, "longitude": FARM_LON, "timezone": "Asia/Bangkok",
            "past_days": past_days, "forecast_days": forecast_days,
            "daily": "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min",
        }, timeout=15)
        r.raise_for_status()
        d = r.json()["daily"]
        df = pd.DataFrame({"date": pd.to_datetime(d["time"]), "rain": d["precipitation_sum"],
                           "chance": d["precipitation_probability_max"],
                           "tmax": d["temperature_2m_max"], "tmin": d["temperature_2m_min"]})
        df["period"] = ["ย้อนหลัง" if x < pd.Timestamp.today().normalize() else "พยากรณ์"
                        for x in df["date"]]
        return df
    except Exception:   # noqa: BLE001
        return None
 
 
def date_range_picker(key, presets, default):
    """ปุ่มช่วงเวลาสำเร็จรูป + ปฏิทินเลือกเอง -> (start, end) เป็น pd.Timestamp"""
    labels = list(presets) + ["เลือกวันเอง"]
    choice = st.segmented_control("ช่วงเวลา", labels, default=default, key=f"{key}_preset",
                                  label_visibility="collapsed") or default
    if choice != "เลือกวันเอง":
        a, b = presets[choice]
        return pd.Timestamp(a).normalize(), pd.Timestamp(b).normalize()
    a0, b0 = presets[default]
    picked = st.date_input("เลือกช่วงวันที่", value=(pd.Timestamp(a0).date(), pd.Timestamp(b0).date()),
                           format="DD/MM/YYYY", key=f"{key}_dates")
    if isinstance(picked, (list, tuple)) and len(picked) == 2:
        return pd.Timestamp(picked[0]), pd.Timestamp(picked[1])
    return pd.Timestamp(a0).normalize(), pd.Timestamp(b0).normalize()
 
 
def stats_row(items):
    st.markdown('<div class="stat">' + "".join(f"<div>{k}<b>{v}</b></div>" for k, v in items) + "</div>",
                unsafe_allow_html=True)
 
 
@st.cache_data(ttl=3600, show_spinner=False)
def get_rain(start, end):
    """ฝน/อุณหภูมิรายวันช่วงใดก็ได้: อดีตไกลใช้ archive API, 3 เดือนล่าสุด + อนาคต 16 วันใช้ forecast API"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    today = pd.Timestamp.today().normalize()
    daily = "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min"
    frames = []
    try:
        recent_from = today - pd.Timedelta(days=90)
        if start < recent_from:
            r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
                "latitude": FARM_LAT, "longitude": FARM_LON, "timezone": "Asia/Bangkok",
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": min(end, recent_from - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min"}, timeout=20)
            r.raise_for_status()
            frames.append(pd.DataFrame(r.json()["daily"]))
        if end >= recent_from:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": FARM_LAT, "longitude": FARM_LON, "timezone": "Asia/Bangkok",
                "past_days": 92, "forecast_days": 16, "daily": daily}, timeout=20)
            r.raise_for_status()
            frames.append(pd.DataFrame(r.json()["daily"]))
    except Exception:   # noqa: BLE001
        return None
    if not frames:
        return None
    d = pd.concat(frames).rename(columns={"time": "date", "precipitation_sum": "rain",
                                          "precipitation_probability_max": "chance",
                                          "temperature_2m_max": "tmax", "temperature_2m_min": "tmin"})
    d["date"] = pd.to_datetime(d["date"])
    d = d.drop_duplicates("date", keep="last").sort_values("date")
    d = d[(d["date"] >= start) & (d["date"] <= end)].reset_index(drop=True)
    if "chance" not in d:
        d["chance"] = None
    d["period"] = ["ย้อนหลัง" if x < today else "พยากรณ์" for x in d["date"]]
    return d
 
 
def rain_advice(mm):
    if mm is None or pd.isna(mm):
        return "❔", "ไม่มีข้อมูล", C_MUTED
    if mm < 1:
        return "☀️", "พ่นยา/ใส่ปุ๋ยได้", C_GREEN
    if mm < 10:
        return "🌦️", "ฝนเล็กน้อย ระวังยาล้าง", C_SKY
    if mm < 20:
        return "🌧️", "ฝนปานกลาง ควรเลื่อนพ่นยา", C_GOLD
    return "⛈️", "ฝนหนัก งดพ่นยา ระวังน้ำขัง", C_RED
 
 
# ====================================================================== AUTH
auth = FirebaseAuthService()
if "user" not in st.session_state:
    st.session_state.user = None
 
if not st.session_state.user:
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']"
                "{display:none;}</style>", unsafe_allow_html=True)
    theme_toggle()
    left, mid, right = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(
            '<div class="login-brand"><div class="login-logo">🍈</div>'
            '<div class="hero-title" style="font-size:1.7rem">DurianOS</div>'
            '<div class="hero-sub">สมุดบัญชีสวนทุเรียนอัจฉริยะ สำหรับเจ้าของสวน</div></div>',
            unsafe_allow_html=True)
        with st.container(key="card-login"):
            auth.render_forms()
        st.markdown(
            '<div style="margin-top:18px">'
            '<div class="feat">📸 <div><b>ถ่ายรูปใบชั่ง/บิล</b> ให้ AI อ่านและลงบัญชีให้อัตโนมัติ</div></div>'
            '<div class="feat">💰 <div><b>รู้กำไรจริง</b> รายรับ รายจ่าย ต้นทุนปุ๋ย ยา ค่าแรง ในที่เดียว</div></div>'
            '<div class="feat">📈 <div><b>ดูแนวโน้มราคา</b> จากข้อมูลตลาด 17 ฤดูย้อนหลัง</div></div>'
            '</div>', unsafe_allow_html=True)
    st.stop()
 
# ====================================================================== LOGGED IN
user = st.session_state.user
ledger = LedgerService(auth.db, user["uid"])
df_tx = ledger.list()
summary = LedgerService.summary(df_tx)
gemini, gemini_err = get_gemini()
 
try:
    card_main = ForecastService.get_price_card("หมอนทอง")
    forecast_err = None
except Exception as e:   # noqa: BLE001
    card_main, forecast_err = None, str(e)
 
# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown('<div class="side-brand"><div class="logo">🍈</div>'
                '<div><b>DurianOS</b><span>สมุดบัญชีสวนทุเรียนอัจฉริยะ</span></div></div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div class="kpi" style="margin-bottom:14px"><div class="lbl">ผู้ใช้งาน</div>'
        f'<div style="font-weight:600;margin-top:4px;word-break:break-all">{user["email"]}</div>'
        f'<div style="color:var(--green-2);font-size:.85rem;margin-top:6px">🏡 {user.get("farm_name", "-")}</div>'
        f'</div>', unsafe_allow_html=True)
    if ledger.persistent:
        st.caption("🟢 บันทึกข้อมูลลง Firebase แล้ว")
    else:
        st.caption("🟠 ยังไม่ได้เชื่อม Firestore — ข้อมูลจะหายเมื่อปิดเว็บ")
    if forecast_err is None:
        st.caption(f"📊 ข้อมูลราคาล่าสุด: สัปดาห์ {th_date(card_main['as_of'])}")
    if st.button("ออกจากระบบ", width="stretch"):
        auth.logout()
 
# ---------------------------------------------------------------- header + KPI
h1, h2 = st.columns([3, 1.2], vertical_alignment="center")
with h1:
    hour = pd.Timestamp.now(tz="Asia/Bangkok").hour
    greet = ("สวัสดีตอนเช้า" if 5 <= hour < 12 else "สวัสดีตอนบ่าย" if 12 <= hour < 17
             else "สวัสดีตอนเย็น" if 17 <= hour < 20 else "สวัสดีตอนค่ำ")
    st.markdown(f'<span class="hero-kicker">🏡 {user.get("farm_name", "สวนของฉัน")}</span>'
                f'<div class="hero-title">{greet} 👋</div>'
                f'<div class="hero-sub">ภาพรวมสวนทุเรียนของคุณ ข้อมูล ณ {th_date(date.today())}</div>',
                unsafe_allow_html=True)
with h2:
    theme_toggle(f'<span class="date-chip">📅 {THAI_DAYS[date.today().weekday()]} {th_date(date.today())}</span>')
 
k1, k2, k3, k4 = st.columns(4)
k1.markdown(kpi("💵 รายรับรวม", baht(summary["income"]), C_GREEN,
                f"ขายไป {summary['sold_kg']:,.0f} กก." if summary["sold_kg"] else "จากใบชั่งที่บันทึก"),
            unsafe_allow_html=True)
k2.markdown(kpi("🧾 รายจ่ายรวม", baht(summary["expense"]), C_RED, "ปุ๋ย ยา ค่าแรง และอื่น ๆ"),
            unsafe_allow_html=True)
k3.markdown(kpi("🏆 กำไรสุทธิ", baht(summary["profit"]),
                C_GOLD if summary["profit"] >= 0 else C_RED, f"{summary['count']} รายการในบัญชี"),
            unsafe_allow_html=True)
if card_main:
    k4.markdown(kpi("🍈 ราคาหมอนทอง (ขายส่ง กทม.)", f"{card_main['price_now']:.0f} ฿/กก.", "var(--text)",
                    f"สัปดาห์หน้า {card_main['next_week_low']:.0f}–{card_main['next_week_high']:.0f} ฿"),
                unsafe_allow_html=True)
else:
    k4.markdown(kpi("🍈 ราคาหมอนทอง", "—", C_MUTED, "ยังไม่มีข้อมูลพยากรณ์"), unsafe_allow_html=True)
 
st.write("")
tab_book, tab_price, tab_env, tab_ai = st.tabs(
    ["📒 บัญชีสวน", "📈 ราคาทุเรียน", "🌦️ อากาศ & ค่าเงิน", "🤖 ผู้ช่วย AI"])
 
# ====================================================================== TAB 1: บัญชีสวน
with tab_book:
    col_scan, col_list = st.columns([1, 1.35], gap="large")
 
    # -------------------------------------------------- สแกน
    with col_scan:
        with st.container(key="card-scan"):
            card_header("📸 สแกนใบชั่ง / บิล", "ถ่ายรูปหรืออัปโหลด แล้วให้ AI อ่านข้อมูลให้ ตรวจทานก่อนบันทึก")
            if gemini_err:
                note(f"⚠️ ใช้ AI ไม่ได้: {gemini_err}", "red")
            up_key = f"uploader_{st.session_state.get('upload_n', 0)}"
            up = st.file_uploader("เลือกรูป", type=["jpg", "jpeg", "png"], key=up_key,
                                  label_visibility="collapsed")
            if up is None:
                st.session_state.pop("ocr_result", None)
            else:
                img = Image.open(up)
                st.image(img, width="stretch")
                if "ocr_result" not in st.session_state:
                    if st.button("✨ ให้ AI อ่านข้อมูล", type="primary", width="stretch",
                                 disabled=gemini is None):
                        with st.spinner("AI กำลังอ่านเอกสาร..."):
                            try:
                                st.session_state.ocr_result = gemini.extract_receipt(img)
                                st.rerun()
                            except Exception as e:   # noqa: BLE001
                                note(ai_error_message(e), "red")
 
            res = st.session_state.get("ocr_result")
            if up is not None and res:
                st.divider()
                st.markdown("**ตรวจทานข้อมูลก่อนบันทึก**")
                items = pd.DataFrame(res.get("items") or [])
                is_sale = res.get("doc_type") != "expense"
                conf = res.get("confidence") or 0
                if conf < 0.7:
                    note(f"AI มั่นใจเพียง {conf * 100:.0f}% กรุณาตรวจตัวเลขให้ดี"
                         + (f" — {res['notes']}" if res.get("notes") else ""), "gold")
                if not items.empty and "amount" in items and items["amount"].notna().any():
                    s = items["amount"].sum()
                    gt = res.get("grand_total") or 0
                    ded = res.get("deductions") or 0
                    if gt and abs(s - ded - gt) > 1:
                        note(f"ผลรวมรายการ ({s:,.0f}) หักค่าหัก ({ded:,.0f}) ไม่ตรงกับยอดรวมในใบ ({gt:,.0f}) "
                             "ตรวจสอบอีกครั้ง", "gold")
                    show = items.rename(columns={"description": "รายการ", "grade": "เกรด",
                                                 "quantity": "จำนวน/กก.", "unit_price": "ราคา/หน่วย",
                                                 "amount": "เป็นเงิน"})
                    st.dataframe(show, hide_index=True, width="stretch")
 
                ttype = st.radio("ประเภท", [INCOME, EXPENSE], index=0 if is_sale else 1, horizontal=True)
                c1, c2 = st.columns(2)
                try:
                    d0 = pd.to_datetime(res.get("date")).date() if res.get("date") else date.today()
                except Exception:   # noqa: BLE001
                    d0 = date.today()
                tdate = c1.date_input("วันที่", value=d0, format="DD/MM/YYYY")
                cats = INCOME_CATS if ttype == INCOME else EXPENSE_CATS
                cat_guess = "ขายทุเรียน" if ttype == INCOME else (res.get("category") or "อื่น ๆ")
                tcat = c2.selectbox("หมวดหมู่", cats, index=cats.index(cat_guess) if cat_guess in cats else 0)
                c3, c4 = st.columns(2)
                amount0 = float(res.get("grand_total") or (items["amount"].sum() if "amount" in items else 0) or 0)
                tamount = c3.number_input("จำนวนเงิน (บาท)", min_value=0.0, value=amount0, step=100.0)
                w0 = res.get("total_weight_kg")
                if not w0 and is_sale and "quantity" in items:
                    w0 = items["quantity"].sum()
                tweight = c4.number_input("น้ำหนักรวม (กก.)", min_value=0.0, value=float(w0 or 0), step=10.0,
                                          disabled=ttype != INCOME)
                tparty = st.text_input("ล้ง/ผู้ซื้อ หรือ ร้านค้า", value=res.get("buyer_name") or "")
                note0 = ""
                if is_sale and not items.empty:
                    parts = [f"{r.get('grade') or r.get('description') or ''} {r.get('quantity') or 0:,.0f} กก."
                             f"@{r.get('unit_price') or 0:,.0f}" for _, r in items.iterrows()]
                    note0 = ((res.get("variety") or "") + " " + ", ".join(parts)).strip()
                tnote = st.text_input("หมายเหตุ", value=note0)
 
                b1, b2 = st.columns(2)
                if b1.button("💾 บันทึกเข้าบัญชี", type="primary", width="stretch"):
                    ledger.add({"date": tdate, "type": ttype, "category": tcat, "amount": tamount,
                                "party": tparty, "weight_kg": tweight if ttype == INCOME else None,
                                "note": tnote, "image_path": ledger.save_image(up), "source": "ai"})
                    st.session_state.pop("ocr_result", None)
                    st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
                    st.toast(f"บันทึก{ttype} {baht(tamount)} แล้ว", icon="✅")
                    st.rerun()
                if b2.button("ยกเลิก", width="stretch"):
                    st.session_state.pop("ocr_result", None)
                    st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
                    st.rerun()
 
        st.write("")
        if True:
            with st.expander("✍️ เพิ่มรายการเอง (ไม่มีบิล เช่น ค่าแรง)"):
                m_type = st.radio("ประเภท", [EXPENSE, INCOME], horizontal=True, key="m_type")
                with st.form("manual_form", clear_on_submit=True, border=False):
                    c1, c2 = st.columns(2)
                    m_date = c1.date_input("วันที่", value=date.today(), format="DD/MM/YYYY")
                    m_cat = c2.selectbox("หมวดหมู่", EXPENSE_CATS if m_type == EXPENSE else INCOME_CATS)
                    c3, c4 = st.columns(2)
                    m_amount = c3.number_input("จำนวนเงิน (บาท)", min_value=0.0, step=100.0)
                    m_weight = c4.number_input("น้ำหนัก (กก.) ถ้าเป็นการขาย", min_value=0.0, step=10.0)
                    m_party = st.text_input("ล้ง / ร้านค้า / ผู้รับเงิน")
                    m_note = st.text_input("หมายเหตุ")
                    if st.form_submit_button("เพิ่มรายการ", type="primary", width="stretch"):
                        if m_amount <= 0:
                            st.error("กรุณาใส่จำนวนเงิน")
                        else:
                            ledger.add({"date": m_date, "type": m_type, "category": m_cat,
                                        "amount": m_amount, "party": m_party,
                                        "weight_kg": m_weight if m_type == INCOME and m_weight else None,
                                        "note": m_note, "image_path": None, "source": "manual"})
                            st.toast("เพิ่มรายการแล้ว", icon="✅")
                            st.rerun()
 
    # -------------------------------------------------- รายการ
    with col_list:
        with st.container(key="card-list"):
            card_header("📒 รายการบัญชี", "เลือกช่วงเวลาและประเภทเพื่อกรองรายการ")
            if df_tx.empty:
                st.markdown('<div style="text-align:center;padding:36px 0" class="muted">'
                            '<div style="font-size:2.4rem">🗒️</div>ยังไม่มีรายการ<br>'
                            'เริ่มจากสแกนใบชั่งหรือบิลใบแรกทางด้านซ้าย</div>', unsafe_allow_html=True)
                view = df_tx
            else:
                today = pd.Timestamp.today().normalize()
                first = df_tx["date"].min() if df_tx["date"].notna().any() else today
                l_start, l_end = date_range_picker("ledger", {
                    "ปีนี้": (pd.Timestamp(today.year, 1, 1), today),
                    "30 วัน": (today - pd.Timedelta(days=30), today),
                    "90 วัน": (today - pd.Timedelta(days=90), today),
                    "ทั้งหมด": (min(first, today), today),
                }, "ทั้งหมด")
                flt = st.segmented_control("ประเภท", ["ทั้งหมด", INCOME, EXPENSE], default="ทั้งหมด",
                                           key="ledger_type", label_visibility="collapsed")
                view = df_tx[(df_tx["date"] >= l_start) & (df_tx["date"] <= l_end)]
                if flt not in (None, "ทั้งหมด"):
                    view = view[view["type"] == flt]
                vs_ = LedgerService.summary(view)
                stats_row([("รายรับ", baht(vs_["income"])), ("รายจ่าย", baht(vs_["expense"])),
                           ("กำไร", baht(vs_["profit"])), ("จำนวน", f"{vs_['count']} รายการ")])
 
                # ราคาที่ขายได้ต่อกก. เทียบราคาขายส่ง กทม. สัปดาห์เดียวกัน
                def vs_market(r):
                    if r["type"] != INCOME or not r["weight_kg"] or pd.isna(r["weight_kg"]):
                        return None
                    try:
                        mkt = ForecastService.market_price_on(r["date"])
                    except Exception:   # noqa: BLE001
                        return None
                    return None if not mkt else round((r["amount"] / r["weight_kg"] / mkt - 1) * 100, 1)
 
                table = view.assign(**{      # ใช้ dict เพราะชื่อคอลัมน์ไทยที่มี "ำ" ใช้เป็น keyword ไม่ได้
                    "วันที่": view["date"].map(th_date),
                    "จำนวนเงิน": [(a if t == INCOME else -a) for a, t in zip(view["amount"], view["type"])],
                    "บาท/กก.": [a / w if t == INCOME and w and not pd.isna(w) else None
                                for a, w, t in zip(view["amount"], view["weight_kg"], view["type"])],
                    "เทียบตลาด": [vs_market(r) for _, r in view.iterrows()],
                }).rename(columns={"type": "ประเภท", "category": "หมวด", "party": "ล้ง/ร้าน",
                                  "weight_kg": "กก.", "note": "หมายเหตุ"})
                cols = ["วันที่", "ประเภท", "หมวด", "จำนวนเงิน", "กก.", "บาท/กก.", "เทียบตลาด", "ล้ง/ร้าน", "หมายเหตุ"]
 
                def fmt(pattern):      # ช่องว่างแสดงเป็น "–" แทนคำว่า None
                    return lambda v: "–" if v is None or pd.isna(v) or v == "" else pattern.format(v)
                table["กก."] = table["กก."].map(fmt("{:,.0f}"))
                table["บาท/กก."] = table["บาท/กก."].map(fmt("{:,.1f}"))
                table["เทียบตลาด"] = table["เทียบตลาด"].map(fmt("{:+.1f}%"))
                table["ล้ง/ร้าน"] = table["ล้ง/ร้าน"].fillna("")
                table["หมายเหตุ"] = table["หมายเหตุ"].fillna("")
                st.dataframe(
                    table[cols], hide_index=True, width="stretch", height=min(430, 40 + 35 * max(len(table), 1)),
                    column_config={
                        "จำนวนเงิน": st.column_config.NumberColumn("จำนวนเงิน (บาท)", format="localized"),
                        "เทียบตลาด": st.column_config.TextColumn(
                            "เทียบตลาด กทม.",
                            help="ราคาต่อกก.ที่ขายได้ เทียบราคาขายส่งหมอนทอง กทม. สัปดาห์เดียวกัน "
                                 "(ราคาหน้าล้งแยกเกรด อาจต่างจากราคาตลาดได้มาก ใช้ดูเป็นแนวทาง)"),
                    })
                d1, d2 = st.columns(2)
                csv = table[cols].to_csv(index=False).encode("utf-8-sig")   # utf-8-sig ให้ Excel อ่านไทยได้
                d1.download_button("⬇️ ดาวน์โหลด Excel (CSV)", csv, file_name=f"บัญชีสวน_{date.today()}.csv",
                                   mime="text/csv", width="stretch")
                with d2.popover("🗑️ ลบรายการ", width="stretch"):
                    labels = {r["id"]: f"{th_date(r['date'])} · {r['type']} · {r['category']} · {baht(r['amount'])}"
                              for _, r in df_tx.iterrows()}
                    del_id = st.selectbox("เลือกรายการที่จะลบ", list(labels), format_func=labels.get)
                    if st.button("ยืนยันลบ", width="stretch"):
                        row = df_tx[df_tx["id"] == del_id].iloc[0]
                        ledger.delete(del_id, row.get("image_path"))
                        st.toast("ลบแล้ว", icon="🗑️")
                        st.rerun()
 
        if not view.empty:
            st.write("")
            g1, g2 = st.columns(2, gap="medium")
            with g1, st.container(key="card-exp"):
                card_header("🧾 รายจ่ายแยกหมวด")
                exp = view[view["type"] == EXPENSE].groupby("category", as_index=False)["amount"].sum()
                if exp.empty:
                    st.caption("ไม่มีรายจ่ายในช่วงที่เลือก")
                else:
                    ch = alt.Chart(exp).mark_arc(innerRadius=55, cornerRadius=4).encode(
                        theta="amount:Q",
                        color=alt.Color("category:N", title=None,
                                        scale=alt.Scale(scheme="goldgreen")),
                        tooltip=[alt.Tooltip("category:N", title="หมวด"),
                                 alt.Tooltip("amount:Q", title="บาท", format=",.0f")])
                    st.altair_chart(chart_style(ch, 230), width="stretch")
            with g2, st.container(key="card-month"):
                card_header("📅 รายเดือน")
                m = view.dropna(subset=["date"]).assign(
                    **{"เดือน": lambda d: d["date"].dt.to_period("M").dt.to_timestamp()})
                m = m.groupby(["เดือน", "type"], as_index=False)["amount"].sum()
                ch = alt.Chart(m).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("yearmonth(เดือน):O", title=None, axis=alt.Axis(labelAngle=0)),
                    xOffset="type:N",
                    y=alt.Y("amount:Q", title="บาท"),
                    color=alt.Color("type:N", title=None,
                                    scale=alt.Scale(domain=[INCOME, EXPENSE], range=[CH["green"], CH["red"]])),
                    tooltip=[alt.Tooltip("type:N", title="ประเภท"),
                             alt.Tooltip("amount:Q", title="บาท", format=",.0f")])
                st.altair_chart(chart_style(ch, 230), width="stretch")
 
            st.write("")
            with st.container(key="card-aisum"):
                card_header("🤖 ให้ AI สรุปบัญชีช่วงนี้", "สรุปกำไร ต้นทุนที่สูง และข้อสังเกต เป็นภาษาง่าย ๆ")
                if st.button("✨ สรุปให้หน่อย", disabled=gemini is None, width="stretch"):
                    with st.spinner("AI กำลังอ่านบัญชี..."):
                        try:
                            st.session_state.ai_summary = gemini.ask_assistant(
                                "สรุปบัญชีสวนช่วงนี้ให้หน่อย: กำไรเท่าไหร่ ต้นทุนหมวดไหนสูงสุด คิดเป็นกี่ % "
                                "ขายได้เฉลี่ยกก.ละเท่าไหร่ และมีข้อสังเกตอะไรที่ควรระวัง ตอบเป็นข้อ ๆ ไม่เกิน 6 ข้อ",
                                LedgerService.context_text(view, user.get("farm_name", "สวน")))
                        except Exception as e:   # noqa: BLE001
                            st.session_state.ai_summary = f"⚠️ {ai_error_message(e)}"
                if st.session_state.get("ai_summary"):
                    st.markdown(st.session_state.ai_summary)
 
    # -------------------------------------------------- คลังรูป
    imgs = df_tx[df_tx["image_path"].notna()] if not df_tx.empty else df_tx
    imgs = imgs[[bool(p) and os.path.exists(p) for p in imgs["image_path"]]] if not imgs.empty else imgs
    if not imgs.empty:
        st.write("")
        with st.container(key="card-gallery"):
            card_header("🖼️ รูปใบชั่ง/บิลที่บันทึกไว้", f"{len(imgs)} รูป")
            cols = st.columns(4)
            for i, (_, r) in enumerate(imgs.iterrows()):
                with cols[i % 4]:
                    st.image(r["image_path"], width="stretch")
                    color = C_GREEN if r["type"] == INCOME else C_RED
                    st.markdown(f'<div style="font-size:.82rem;margin:-4px 0 14px">{th_date(r["date"])} · '
                                f'<span style="color:{color};font-weight:600">{baht(r["amount"])}</span><br>'
                                f'<span class="muted">{r["party"] or r["category"]}</span></div>',
                                unsafe_allow_html=True)
 
# ====================================================================== TAB 2: ราคา
with tab_price:
    if forecast_err:
        note(f"⚠️ อ่านข้อมูลราคาไม่ได้: {forecast_err}", "red")
    else:
        variety = st.segmented_control("พันธุ์", ["หมอนทอง", "ชะนี"], default="หมอนทอง",
                                       label_visibility="collapsed") or "หมอนทอง"
        pc = ForecastService.get_price_card(variety)
        prod = ForecastService._product(variety)
        if pc.get("warning"):
            note(f"⚠️ {pc['warning']}", "red")
 
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(kpi("ราคาล่าสุด (ขายส่ง กทม.)", f"{pc['price_now']:.0f} ฿/กก.", "var(--text)",
                        f"สัปดาห์ {th_date(pc['as_of'])}"), unsafe_allow_html=True)
        m2.markdown(kpi("สัปดาห์หน้า (ช่วง 80%)", f"{pc['next_week_low']:.0f}–{pc['next_week_high']:.0f} ฿",
                        C_SKY, "ทดสอบย้อนหลังครอบคลุมราคาจริง ~81%"), unsafe_allow_html=True)
        lvl_color = {"สูง": C_RED, "ปานกลาง": C_GOLD, "ต่ำ": C_GREEN}.get(pc["drop_level"], C_MUTED)
        m3.markdown(kpi("โอกาสราคาลง ≥5฿ ใน 1 สัปดาห์", f"{pc['drop_chance_pct']}%", lvl_color,
                        f"ระดับ{pc['drop_level']} (สถิติตามช่วงฤดู)"), unsafe_allow_html=True)
        vs = pc["vs_last_years_pct"]
        m4.markdown(kpi("เทียบช่วงเดียวกันปีก่อน ๆ", f"{vs:+.1f}%" if vs is not None else "—",
                        C_GREEN if (vs or 0) >= 0 else C_RED, "ค่าเฉลี่ยสัปดาห์เดียวกัน 5 ปี"),
                    unsafe_allow_html=True)
 
        st.write("")
        cA, cB = st.columns([1.7, 1], gap="large")
        with cA:
            with st.container(key="card-pricechart"):
                card_header("📈 ราคาขายส่ง กทม. ย้อนหลัง + ช่วงราคาที่คาดไว้",
                            "เส้นเขียว = ราคากลาง · แถบเทา = ต่ำสุด–สูงสุดของสัปดาห์ · แถบฟ้า = ช่วงที่คาด (80%)")
                last_week = pd.Timestamp(pc["as_of"])
                p_start, p_end = date_range_picker("price", {
                    "3 เดือน": (last_week - pd.DateOffset(months=3), last_week),
                    "6 เดือน": (last_week - pd.DateOffset(months=6), last_week),
                    "1 ปี": (last_week - pd.DateOffset(years=1), last_week),
                    "3 ปี": (last_week - pd.DateOffset(years=3), last_week),
                    "ทั้งหมด": (pd.Timestamp("2010-01-01"), last_week),
                }, "3 เดือน")
                if not ForecastService.has_full_history(variety):
                    note("ตอนนี้มีข้อมูลแค่ 12 สัปดาห์ล่าสุด — รัน <b>run_all.py</b> ในโฟลเดอร์ forecast ใหม่ "
                         "เพื่อให้เลือกดูย้อนหลังได้ทุกปี", "sky")
                hist = ForecastService.get_price_history(variety, p_start, p_end)
                if hist.empty:
                    note("ไม่มีราคาในช่วงที่เลือก (อาจอยู่นอกฤดูทุเรียน)", "gold")
                else:
                    chg = (hist["price_mid"].iloc[-1] / hist["price_mid"].iloc[0] - 1) * 100
                    stats_row([("เฉลี่ย", f"{hist['price_mid'].mean():.1f} ฿"),
                               ("ต่ำสุด", f"{hist['price_mid'].min():.0f} ฿ ({th_date(hist.loc[hist['price_mid'].idxmin(), 'week_end'], False)})"),
                               ("สูงสุด", f"{hist['price_mid'].max():.0f} ฿ ({th_date(hist.loc[hist['price_mid'].idxmax(), 'week_end'], False)})"),
                               ("เปลี่ยนแปลงในช่วง", f"{chg:+.1f}%"),
                               ("จำนวนสัปดาห์ที่มีราคา", f"{len(hist)}")])
                    x = alt.X("week_end:T", title=None,
                              axis=alt.Axis(format="%b %Y" if (p_end - p_start).days > 200 else "%d %b"))
                    layers = []
                    if "price_min" in hist:
                        layers.append(alt.Chart(hist).mark_area(color=CH["slate"], opacity=.22).encode(
                            x=x, y="price_min:Q", y2="price_max:Q"))
                    pts = len(hist) <= 60
                    layers.append(alt.Chart(hist).mark_line(
                        color=CH["green"], strokeWidth=2.5,
                        point=alt.OverlayMarkDef(color=CH["green"], size=35) if pts else False).encode(
                        x=x, y=alt.Y("price_mid:Q", title="บาท/กก.", scale=alt.Scale(zero=False)),
                        tooltip=[alt.Tooltip("week_end:T", title="สัปดาห์", format="%d %b %Y"),
                                 alt.Tooltip("price_mid:Q", title="ราคากลาง", format=".1f")]
                        + ([alt.Tooltip("price_min:Q", title="ต่ำสุด", format=".1f"),
                            alt.Tooltip("price_max:Q", title="สูงสุด", format=".1f")] if "price_min" in hist else [])))
                    if p_end >= last_week - pd.Timedelta(days=1):      # ช่วงที่เลือกถึงปัจจุบัน -> แสดงช่วงที่คาด
                        fc = pd.DataFrame(prod["price_range"]).assign(
                            week_end=lambda d: pd.to_datetime(d["target_week"]))
                        band = pd.concat([pd.DataFrame([{"week_end": last_week, "low_80": pc["price_now"],
                                                         "high_80": pc["price_now"]}]),
                                          fc[["week_end", "low_80", "high_80"]]])
                        layers.append(alt.Chart(band).mark_area(color=CH["sky"], opacity=.25).encode(
                            x="week_end:T", y="low_80:Q", y2="high_80:Q",
                            tooltip=[alt.Tooltip("week_end:T", title="สัปดาห์", format="%d %b %Y"),
                                     alt.Tooltip("low_80:Q", title="คาดต่ำสุด", format=".1f"),
                                     alt.Tooltip("high_80:Q", title="คาดสูงสุด", format=".1f")]))
                    st.altair_chart(chart_style(alt.layer(*layers), 320), width="stretch")
                note(f"💡 {pc['advice']}", "gold")
 
            st.write("")
            with st.container(key="card-years"):
                card_header("🗓️ เทียบราคาแต่ละปี ช่วงเดียวกันของฤดู",
                            "ดูว่าปีนี้ราคาสูงหรือต่ำกว่าปีก่อน ๆ ในช่วงเดือนเดียวกัน")
                allh = ForecastService.get_price_history(variety)
                allh["ปี"] = allh["week_end"].dt.year
                years = sorted(allh["ปี"].unique())
                if len(years) < 2:
                    st.caption("ต้องมีข้อมูลย้อนหลังหลายปี (รัน run_all.py ใหม่)")
                else:
                    pick = st.multiselect("เลือกปีที่จะเทียบ", years, default=years[-4:],
                                          format_func=lambda y: f"{y + 543}")
                    yy = allh[allh["ปี"].isin(pick)].copy()
                    yy["วันในปี"] = pd.to_datetime("2000-" + yy["week_end"].dt.strftime("%m-%d"),
                                                    errors="coerce")
                    yy["year_th"] = (yy["ปี"] + 543).astype(str)
                    this_year = str(last_week.year + 543)
                    ch = alt.Chart(yy.dropna(subset=["วันในปี"])).mark_line(strokeWidth=2.2).encode(
                        x=alt.X("วันในปี:T", title=None, axis=alt.Axis(format="%b", tickCount="month")),
                        y=alt.Y("price_mid:Q", title="บาท/กก.", scale=alt.Scale(zero=False)),
                        color=alt.Color("year_th:N", title="ปี", scale=alt.Scale(scheme="tableau10")),
                        strokeWidth=alt.condition(alt.datum.year_th == this_year, alt.value(4), alt.value(1.8)),
                        tooltip=[alt.Tooltip("year_th:N", title="ปี"), alt.Tooltip("week_end:T", title="สัปดาห์", format="%d %b"),
                                 alt.Tooltip("price_mid:Q", title="ราคา", format=".1f")])
                    st.altair_chart(chart_style(ch, 280), width="stretch")
 
        with cB:
            with st.container(key="card-revenue"):
                card_header("🧮 ถ้าขายสัปดาห์หน้า จะได้เท่าไหร่?",
                            "ใช้ช่วงราคาที่คาดไว้ คำนวณกับรายรับ-ต้นทุนที่บันทึกไว้")
                kg = st.number_input("น้ำหนักที่คาดว่าจะขายเพิ่ม (กก.)", min_value=0.0, value=1000.0, step=100.0)
                ratio = st.slider("ราคาหน้าล้งของสวนเรา เทียบราคาตลาด กทม.", 50, 150, 100, 5,
                                  format="%d%%",
                                  help="ถ้ารู้ว่าล้งมักให้ต่ำกว่าราคาตลาด 10% ให้ตั้ง 90% "
                                       "(ดูค่าจริงได้จากคอลัมน์ 'เทียบตลาด' ในหน้าบัญชี)")
                rev = ForecastService.estimate_revenue(kg, variety, ratio / 100)
                if rev:
                    cost = summary["expense"]
                    st.markdown(
                        f'<div class="kpi" style="margin-top:6px"><div class="lbl">รายได้ที่คาด</div>'
                        f'<div class="val" style="color:{C_SKY}">{baht(rev["low"])} – {baht(rev["high"])}</div>'
                        f'<div class="sub">ค่ากลาง {baht(rev["mid"])}</div></div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="kpi" style="margin-top:10px"><div class="lbl">กำไรทั้งฤดู (รายรับที่มีแล้ว + ที่คาด − ต้นทุน)</div>'
                        f'<div class="val" style="color:{C_GOLD}">'
                        f'{baht(summary["income"] + rev["low"] - cost)} – {baht(summary["income"] + rev["high"] - cost)}</div>'
                        f'<div class="sub">ต้นทุนที่บันทึกไว้ {baht(cost)}</div></div>', unsafe_allow_html=True)
                    total_kg = summary["sold_kg"] + kg
                    if total_kg > 0 and cost > 0:
                        be = cost / total_kg
                        mkt = pc["price_now"] * ratio / 100
                        good = mkt >= be
                        st.markdown(
                            f'<div class="kpi" style="margin-top:10px"><div class="lbl">⚖️ ราคาคุ้มทุน (ต้นทุน ÷ ผลผลิตทั้งฤดู)</div>'
                            f'<div class="val" style="color:{C_GREEN if good else C_RED}">{be:,.1f} ฿/กก.</div>'
                            f'<div class="sub">ผลผลิตรวม {total_kg:,.0f} กก. · ราคาที่คาดว่าจะได้ {mkt:,.0f} ฿/กก. '
                            f'{"สูงกว่าจุดคุ้มทุน ✅" if good else "ต่ำกว่าจุดคุ้มทุน ⚠️"}</div></div>',
                            unsafe_allow_html=True)
            st.write("")
            with st.container(key="card-sameweek"):
                sw = prod["same_week_previous_years"]
                card_header("📊 สัปดาห์นี้ในปีก่อน ๆ")
                if sw["years"]:
                    swd = pd.DataFrame(sw["years"] + [{"year": pd.to_datetime(pc["as_of"]).year,
                                                       "price": pc["price_now"]}])
                    swd["ปี"] = (swd["year"] + 543).astype(str)
                    swd["สี"] = ["ปีก่อน"] * len(sw["years"]) + ["ปีนี้"]
                    ch = alt.Chart(swd).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
                        x=alt.X("ปี:N", title=None, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("price:Q", title="บาท/กก."),
                        color=alt.Color("สี:N", legend=None,
                                        scale=alt.Scale(domain=["ปีก่อน", "ปีนี้"], range=[CH["slate"], CH["green"]])),
                        tooltip=[alt.Tooltip("ปี:N"), alt.Tooltip("price:Q", title="ราคา", format=".1f")])
                    st.altair_chart(chart_style(ch, 190), width="stretch")
                else:
                    st.caption("ไม่มีข้อมูลสัปดาห์เดียวกันในปีก่อน ๆ")
 
        st.caption("ที่มา: ราคาขายส่งตลาดกรุงเทพฯ กรมการค้าภายใน (MOC) · ไม่ใช่ราคาหน้าล้ง · "
                   "ช่วงราคาคำนวณจากความคลาดเคลื่อนจริงในอดีต 17 ฤดู · ไม่ใช่คำทำนายที่แน่นอน")
 
# ====================================================================== TAB 3: อากาศ & ค่าเงิน
with tab_env:
    today_ts = pd.Timestamp.today().normalize()
    with st.container(key="card-weather"):
        card_header("🌦️ ฝนและอุณหภูมิ (จันทบุรี)",
                    "เลือกช่วงวันที่ดูย้อนหลังได้ถึงปี 2010 · ล่วงหน้าได้ 16 วัน · ข้อมูลจาก Open-Meteo")
        r_start, r_end = date_range_picker("rain", {
            "7 วันก่อน + 14 วันหน้า": (today_ts - pd.Timedelta(days=7), today_ts + pd.Timedelta(days=14)),
            "30 วันที่ผ่านมา": (today_ts - pd.Timedelta(days=30), today_ts),
            "90 วันที่ผ่านมา": (today_ts - pd.Timedelta(days=90), today_ts),
            "1 ปีที่ผ่านมา": (today_ts - pd.DateOffset(years=1), today_ts),
        }, "7 วันก่อน + 14 วันหน้า")
        r_end = min(r_end, today_ts + pd.Timedelta(days=15))
        with st.spinner("กำลังดึงข้อมูลอากาศ..."):
            wx = get_rain(r_start, r_end) if r_start <= r_end else None
        if wx is None or wx.empty:
            note("ดึงข้อมูลอากาศช่วงนี้ไม่ได้ (หรือช่วงวันที่ไม่ถูกต้อง) ลองเลือกช่วงอื่นหรือลองใหม่ภายหลัง", "red")
        else:
            rain = wx["rain"].fillna(0)
            stats_row([
                ("ฝนรวม", f"{rain.sum():,.0f} มม."),
                ("วันฝนตก (≥1 มม.)", f"{int((rain >= 1).sum())} / {len(wx)} วัน"),
                ("ฝนหนัก (≥20 มม.)", f"{int((rain >= 20).sum())} วัน"),
                ("ฝนมากสุดใน 1 วัน", f"{rain.max():,.0f} มม." + (f" ({th_date(wx.loc[rain.idxmax(), 'date'])})" if rain.max() > 0 else "")),
                ("อุณหภูมิสูงสุดเฉลี่ย", f"{wx['tmax'].mean():.1f}°C"),
            ])
            weekly = len(wx) > 120
            plot = wx
            if weekly:   # ช่วงยาว รวมเป็นรายสัปดาห์ให้อ่านง่าย
                plot = (wx.set_index("date").resample("W-SUN")
                        .agg({"rain": "sum", "tmax": "mean", "tmin": "mean", "period": "last"}).reset_index())
            bars = alt.Chart(plot).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b %y" if weekly else "%d %b")),
                y=alt.Y("rain:Q", title="ฝนรายสัปดาห์ (มม.)" if weekly else "ฝน (มม.)"),
                color=alt.Color("period:N", title=None,
                                scale=alt.Scale(domain=["ย้อนหลัง", "พยากรณ์"], range=[CH["slate"], CH["sky"]])),
                tooltip=[alt.Tooltip("date:T", title="สัปดาห์สิ้นสุด" if weekly else "วันที่", format="%d %b %Y"),
                         alt.Tooltip("rain:Q", title="ฝน มม.", format=".1f"),
                         alt.Tooltip("tmax:Q", title="สูงสุด °C", format=".1f"),
                         alt.Tooltip("tmin:Q", title="ต่ำสุด °C", format=".1f")])
            temp = alt.Chart(plot).mark_line(color=CH["gold"], strokeWidth=2, opacity=.85).encode(
                x="date:T", y=alt.Y("tmax:Q", title="อุณหภูมิสูงสุด (°C)", scale=alt.Scale(zero=False)))
            layers = alt.layer(bars, temp).resolve_scale(y="independent")
            if wx["date"].min() <= today_ts <= wx["date"].max():
                rule = alt.Chart(pd.DataFrame({"d": [today_ts]})).mark_rule(
                    color=CH["gold"], strokeDash=[4, 4]).encode(x="d:T")
                layers = alt.layer(bars, temp, rule).resolve_scale(y="independent")
            st.altair_chart(chart_style(layers, 260), width="stretch")
            st.caption("แท่ง = ปริมาณฝน · เส้นสีทอง = อุณหภูมิสูงสุด · เส้นประ = วันนี้"
                       + (" · ช่วงยาวเกิน 120 วันแสดงเป็นผลรวมรายสัปดาห์" if weekly else ""))
 
        fc = get_weather()
        if fc is not None:
            st.markdown("**7 วันข้างหน้า — วันไหนพ่นยา/ใส่ปุ๋ยได้**")
            nxt = fc[fc["period"] == "พยากรณ์"].head(7)
            cols = st.columns(7)
            for c, (_, r) in zip(cols, nxt.iterrows()):
                icon, adv, color = rain_advice(r["rain"])
                c.markdown(
                    f'<div class="day"><div class="d">{THAI_DAYS[r["date"].dayofweek]} {r["date"].day}/{r["date"].month}</div>'
                    f'<div class="i">{icon}</div>'
                    f'<div class="r" style="color:{color}">{(r["rain"] or 0):.0f} มม.</div>'
                    f'<div class="t">{(r["tmin"] or 0):.0f}–{(r["tmax"] or 0):.0f}°C</div>'
                    f'<div class="t" style="color:{color};margin-top:4px">{adv}</div></div>',
                    unsafe_allow_html=True)
 
    st.write("")
    with st.container(key="card-fx"):
        card_header("💱 ค่าเงินหยวน / บาท", "ผู้ซื้อหลักของทุเรียนไทยคือจีน · ข้อมูลอ้างอิง ECB ผ่าน Frankfurter")
        fx_days = {"30 วัน": 30, "90 วัน": 90, "6 เดือน": 182, "1 ปี": 365, "3 ปี": 1095}
        fx_pick = st.segmented_control("ช่วงค่าเงิน", list(fx_days), default="90 วัน", key="fx_range",
                                       label_visibility="collapsed") or "90 วัน"
        fx = get_fx(fx_days[fx_pick])
        if fx is None or fx.empty:
            note("ดึงข้อมูลค่าเงินไม่ได้ในขณะนี้", "red")
        else:
            now, first = fx["rate"].iloc[-1], fx["rate"].iloc[0]
            chg = (now / first - 1) * 100
            f1, f2 = st.columns([1, 2.4], gap="large")
            with f1:
                st.markdown(kpi("1 หยวน (CNY)", f"{now:.3f} ฿", "var(--text)",
                                f'<span style="color:{C_GREEN if chg >= 0 else C_RED}">{chg:+.2f}%</span> ใน {fx_pick}'),
                            unsafe_allow_html=True)
                stats_row([("สูงสุด", f"{fx['rate'].max():.3f}"), ("ต่ำสุด", f"{fx['rate'].min():.3f}")])
            with f2:
                ch = alt.Chart(fx).mark_line(color=CH["sky"], strokeWidth=2.5).encode(
                    x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b %y")),
                    y=alt.Y("rate:Q", title="บาท/หยวน", scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("date:T", title="วันที่", format="%d %b %Y"),
                             alt.Tooltip("rate:Q", title="บาท", format=".4f")])
                st.altair_chart(chart_style(ch, 200), width="stretch")
            note("ℹ️ จากการทดสอบย้อนหลังของทีม ค่าเงินหยวนไม่ได้ช่วยพยากรณ์ราคาทุเรียนรายสัปดาห์อย่างมีนัยสำคัญ "
                 "ใช้ดูเป็นบริบทของตลาดเท่านั้น", "sky")
 
# ====================================================================== TAB 4: ผู้ช่วย AI
with tab_ai:
    with st.container(key="card-chat"):
        card_header("🤖 ผู้ช่วย AI ประจำสวน",
                    "ตอบจากบัญชีของสวนคุณ ราคาตลาด อากาศ และค่าเงิน · AI อาจผิดพลาดได้ ควรตรวจสอบก่อนตัดสินใจ")
        if gemini_err:
            note(f"⚠️ ใช้ AI ไม่ได้: {gemini_err}", "red")
        chat_key = f"chat_{user['uid']}"
        history = st.session_state.setdefault(chat_key, [])
 
        if not history:
            st.markdown('<div class="muted" style="margin:6px 0 8px">ลองถาม:</div>', unsafe_allow_html=True)
            examples = ["ฤดูนี้กำไรเท่าไหร่ ต้นทุนไหนสูงสุด", "ราคาหมอนทองสัปดาห์หน้าเป็นยังไง",
                        "ถ้าขายอีก 1,500 กก. จะได้กำไรประมาณเท่าไหร่", "สัปดาห์นี้พ่นยาได้วันไหนบ้าง"]
            ec = st.columns(2)
            for i, q in enumerate(examples):
                if ec[i % 2].button(q, key=f"ex_{i}", width="stretch"):
                    st.session_state.pending_q = q
                    st.rerun()
 
        for m in history:
            with st.chat_message(m["role"], avatar="🧑‍🌾" if m["role"] == "user" else "🍈"):
                st.markdown(m["content"])
 
        q = st.chat_input("พิมพ์คำถาม เช่น ควรขายช่วงไหนดี", disabled=gemini is None)
        q = q or st.session_state.pop("pending_q", None)
        if q:
            history.append({"role": "user", "content": q})
            with st.chat_message("user", avatar="🧑‍🌾"):
                st.markdown(q)
            try:
                fctx = ForecastService.context_for_gemini(FARM_LAT, FARM_LON)
            except Exception:   # noqa: BLE001
                fctx = "ข้อมูลราคาไม่พร้อมใช้งานในขณะนี้"
            fx_ctx = "ไม่มีข้อมูลค่าเงิน"
            fxd = get_fx()
            if fxd is not None and not fxd.empty:
                fx_ctx = (f"ค่าเงิน: 1 หยวน = {fxd['rate'].iloc[-1]:.3f} บาท "
                          f"(เปลี่ยน {(fxd['rate'].iloc[-1] / fxd['rate'].iloc[0] - 1) * 100:+.2f}% ใน 60 วัน)")
            recent = "\n".join(f"ผู้ใช้: {m['content']}" if m["role"] == "user" else f"ผู้ช่วย: {m['content']}"
                               for m in history[-7:-1])
            context = (f"วันนี้: {date.today().isoformat()}\n"
                       f"{LedgerService.context_text(df_tx, user.get('farm_name', 'สวนของผู้ใช้'))}\n\n"
                       f"{fctx}\n{fx_ctx}\n\nบทสนทนาก่อนหน้า:\n{recent or '-'}")
            with st.chat_message("assistant", avatar="🍈"):
                with st.spinner("กำลังคิด..."):
                    try:
                        answer = gemini.ask_assistant(q, context)
                    except Exception as e:   # noqa: BLE001
                        answer = f"⚠️ {ai_error_message(e)}"
                st.markdown(answer)
            history.append({"role": "assistant", "content": answer})
 
        if history and st.button("ล้างบทสนทนา"):
            st.session_state[chat_key] = []
            st.rerun()
 
