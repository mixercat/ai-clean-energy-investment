"""DurianOS — สมุดบัญชีสวนทุเรียนอัจฉริยะ
รัน:  python -m streamlit run app.py   (จากในโฟลเดอร์ web)
"""
import io
import os
import re
from datetime import date

import altair as alt
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image

load_dotenv()


def _load_cloud_secrets():
    """Streamlit Community Cloud ไม่มีไฟล์ .env -> คัดลอกค่าจากหน้า Secrets เข้า os.environ
    (ค่าที่เป็นตาราง เช่น [firebase_service_account] จะถูกอ่านตรงจาก st.secrets ใน firebase_auth.py)"""
    try:
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float, bool)) and k not in os.environ:
                os.environ[k] = str(v)
    except Exception:   # noqa: BLE001  ไม่มีไฟล์ secrets (รันในเครื่อง) -> ใช้ .env ตามเดิม
        pass
    os.environ.setdefault("TZ", "Asia/Bangkok")        # เซิร์ฟเวอร์ cloud ใช้เวลา UTC -> ตั้งเป็นเวลาไทย
    if hasattr(__import__("time"), "tzset"):
        __import__("time").tzset()


_load_cloud_secrets()

st.set_page_config(page_title="DurianOS | สมุดบัญชีสวนทุเรียน", page_icon=":material/eco:", layout="wide",
                   initial_sidebar_state="expanded")

from firebase_auth import FirebaseAuthService, firestore_ok          # noqa: E402  (ต้อง import หลัง set_page_config)
from forecast_service import ForecastService           # noqa: E402
from chat_service import ChatService                  # noqa: E402
from file_import import (UPLOAD_TYPES, TYPE_MODES, apply_header, build_entries,  # noqa: E402
                         docx_text, file_kind, guess_columns, guess_header_row, is_image_path,
                         mark_duplicates, pdf_info, read_raw, sheet_names, table_as_text)
from gemini_service import GeminiService               # noqa: E402
from settings_service import (PROVINCES, VARIETIES, SettingsService, can_persist_keys,  # noqa: E402
                              mask, profile_text, server_keys_allowed)
from knowledge import knowledge_text                  # noqa: E402
from ledger_service import (EXPENSE, EXPENSE_CATS, INCOME, INCOME_CATS,  # noqa: E402
                            LedgerService)

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
THAI_DAYS = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]
# สีสำหรับ HTML = ตัวแปร CSS (เปลี่ยนตามโหมดสว่าง/มืดอัตโนมัติ)
C_GREEN, C_RED, C_GOLD, C_SKY, C_MUTED = "var(--green)", "var(--red)", "var(--gold)", "var(--sky)", "var(--muted)"
# สีสำหรับกราฟ = โทนกลาง อ่านชัดทั้งพื้นสว่างและพื้นมืด
CH = {"green": "#22c55e", "red": "#ef4444", "gold": "#eab308", "sky": "#0ea5e9", "slate": "#8595a8",
      "axis": "#8a9a91", "grid": "rgba(128,128,128,.16)"}

# ====================================================================== STYLE
# ระบบสี: พื้นเรียบ ขอบบาง สีเขียวใช้เฉพาะจุดสำคัญ ตัวเลขใช้ตัวอักษรความกว้างเท่ากัน (tabular)
LIGHT_VARS = """
  --bg:#f6f7f5; --card:#ffffff; --card-2:#f3f5f2; --card-hover:#fafbfa;
  --line:#e3e7e2; --line-2:#d4dad3; --text:#111b15; --text-2:#3d4841; --muted:#6a756d;
  --green:#15803d; --red:#c52a2a; --gold:#a15c07; --sky:#0b6aa2;
  --brand:#15803d; --brand-ink:#ffffff; --accent-bg:#ebf5ee; --accent-bd:#b9dcc4;
  --sidebar:#fbfcfb; --shadow:0 1px 2px rgba(17,27,21,.05);
  --gold-bg:#fdf7eb; --gold-bd:#f0d49b; --gold-tx:#7a4a06;
  --sky-bg:#f0f6fb; --sky-bd:#bfd9ec; --sky-tx:#0b4f78;
  --red-bg:#fdf1f1; --red-bd:#f1c0c0; --red-tx:#8f1d1d;
"""
DARK_VARS = """
  --bg:#0c100d; --card:#131914; --card-2:#18201a; --card-hover:#161d18;
  --line:#232d26; --line-2:#2e3a31; --text:#e6ebe7; --text-2:#b9c3bc; --muted:#87938a;
  --green:#4ade80; --red:#f87171; --gold:#fbbf24; --sky:#60a5fa;
  --brand:#22c55e; --brand-ink:#05140a; --accent-bg:#15251a; --accent-bd:#24472f;
  --sidebar:#0f1411; --shadow:0 1px 2px rgba(0,0,0,.3);
  --gold-bg:#1d1809; --gold-bd:#4a3a12; --gold-tx:#f5d38a;
  --sky-bg:#0d1a26; --sky-bd:#1e3a52; --sky-tx:#b9dbf5;
  --red-bg:#221011; --red-bd:#4d2224; --red-tx:#fbc4c4;
"""
FONT = "'IBM Plex Sans Thai', 'IBM Plex Sans', system-ui, sans-serif"
CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{ {DARK_VARS} }}
@media (prefers-color-scheme: light){{ html:not([data-theme]){{ {LIGHT_VARS} }} }}
html[data-theme="light"]{{ {LIGHT_VARS} }}
html[data-theme="dark"]{{ {DARK_VARS} }}
html, body, [class*="css"], .stMarkdown, p, label, input, textarea, button, h1, h2, h3, h4, li {{
  font-family:{FONT} !important;
}}
.ms{{font-family:'Material Symbols Rounded' !important; font-weight:400; font-style:normal; line-height:1;
  letter-spacing:normal; text-transform:none; display:inline-block; white-space:nowrap; direction:ltr;
  -webkit-font-feature-settings:'liga'; font-feature-settings:'liga'; -webkit-font-smoothing:antialiased;
  font-size:20px; vertical-align:-4px; font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 20;}}
.ms.fill{{font-variation-settings:'FILL' 1,'wght' 400,'GRAD' 0,'opsz' 20;}}
.num, .kpi .val, .stat b, .day .r{{font-variant-numeric:tabular-nums; letter-spacing:-.01em;}}
.stApp{{color:var(--text);}}
.block-container{{padding:2.4rem 2.25rem 3rem 2.25rem; max-width:1480px;}}
#MainMenu, footer, [data-testid="stToolbar"]{{visibility:hidden;}}
header[data-testid="stHeader"]{{background:transparent; height:0;}}
[data-testid="stSidebar"]{{background:var(--sidebar); border-right:1px solid var(--line);}}
[data-testid="stSidebar"] .block-container{{padding-top:1.2rem;}}
p, li{{line-height:1.6;}}
/* ไอคอนใช้ฟอนต์ Material Symbols ที่มากับ Streamlit อยู่แล้ว (ไม่ต้องโหลดเพิ่ม) */
/* การ์ด: st.container(key="card-...") */
[class*="st-key-card"]{{background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:20px 22px; box-shadow:var(--shadow);}}
.card-title{{font-size:1rem; font-weight:600; margin:0; color:var(--text); letter-spacing:-.005em;}}
.card-sub{{font-size:.84rem; color:var(--muted); margin:2px 0 14px 0;}}
.card-head-rule{{height:1px; background:var(--line); margin:0 -22px 16px;}}
/* KPI */
.kpi{{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px;
  height:100%; box-shadow:var(--shadow);}}
.kpi .lbl{{font-size:.8rem; color:var(--muted); font-weight:500; display:flex; gap:6px; align-items:center;}}
.kpi .lbl .ms{{font-size:18px; vertical-align:0;}}
.kpi .val{{font-size:1.6rem; font-weight:600; margin-top:6px; color:var(--text);}}
.kpi .sub{{font-size:.78rem; color:var(--muted); margin-top:4px;}}
.kpi .neg{{color:var(--red);}}
/* ส่วนหัวหน้า */
.page-eyebrow{{font-size:.78rem; color:var(--muted); font-weight:500; display:flex; align-items:center; gap:6px;}}
.page-title{{font-size:1.6rem; font-weight:600; margin:4px 0 2px; color:var(--text); letter-spacing:-.015em;}}
.page-meta{{color:var(--muted); font-size:.86rem; display:flex; gap:14px; flex-wrap:wrap; align-items:center;}}
.page-meta span{{display:inline-flex; align-items:center; gap:5px;}}
.page-meta .ms{{font-size:17px; vertical-align:0;}}
/* callout */
.note{{border-radius:10px; padding:10px 14px; font-size:.87rem; line-height:1.6; margin:8px 0;
  display:flex; gap:10px; align-items:flex-start; border:1px solid;}}
.note .ms{{font-size:19px; margin-top:1px; vertical-align:0;}}
.note.gold{{background:var(--gold-bg); border-color:var(--gold-bd); color:var(--gold-tx);}}
.note.sky{{background:var(--sky-bg); border-color:var(--sky-bd); color:var(--sky-tx);}}
.note.red{{background:var(--red-bg); border-color:var(--red-bd); color:var(--red-tx);}}
.note.ok{{background:var(--accent-bg); border-color:var(--accent-bd); color:var(--text);}}
.muted{{color:var(--muted);}}
.badge{{display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:6px; font-size:.74rem;
  font-weight:500; background:var(--card-2); border:1px solid var(--line); color:var(--text-2);}}
.dot{{width:7px; height:7px; border-radius:50%; display:inline-block; margin-right:6px; vertical-align:1px;}}
/* ปุ่ม */
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button, [data-testid="stPopover"] button{{
  border-radius:8px; font-weight:500; min-height:38px; transition:background .12s, border-color .12s;}}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"]{{
  background:var(--brand); border:1px solid var(--brand); color:var(--brand-ink);}}
.stButton>button[kind="primary"]:hover, .stFormSubmitButton>button[kind="primary"]:hover{{filter:brightness(1.07);}}
.stButton>button[kind="secondary"], .stDownloadButton>button{{background:var(--card); border:1px solid var(--line-2);}}
.stButton>button[kind="secondary"]:hover, .stDownloadButton>button:hover{{border-color:var(--brand); color:var(--brand);}}
/* แท็บ: เส้นใต้แบบแอปทั่วไป */
.stTabs [role="tablist"]{{gap:2px; border-bottom:1px solid var(--line); overflow-x:auto;}}
.stTabs [data-testid="stTab"]{{padding:10px 14px 11px; border-radius:0; margin-bottom:-1px;
  border-bottom:2px solid transparent; transition:color .12s;}}
.stTabs [data-testid="stTab"] p{{font-weight:500; color:var(--muted); font-size:.92rem;}}
.stTabs [data-testid="stTab"]:hover p{{color:var(--text);}}
.stTabs [data-testid="stTab"][aria-selected="true"]{{border-bottom-color:var(--brand);}}
.stTabs [data-testid="stTab"][aria-selected="true"] p{{color:var(--text); font-weight:600;}}
.stTabs .react-aria-SelectionIndicator{{display:none;}}
.stTabs [role="tabpanel"]{{padding-top:18px;}}
html.theme-switching [data-testid="stMainMenuPopover"]{{opacity:0 !important; pointer-events:none !important;}}
/* input */
[data-baseweb="input"], [data-baseweb="select"]>div, [data-baseweb="textarea"]{{border-radius:8px !important;}}
[data-testid="stExpander"] details{{border-radius:10px; border-color:var(--line);}}
/* ตารางสรุปตัวเลขย่อย */
.stat{{display:flex; flex-wrap:wrap; gap:1px; margin:6px 0 14px; background:var(--line);
  border:1px solid var(--line); border-radius:10px; overflow:hidden;}}
.stat div{{flex:1 1 120px; font-size:.76rem; color:var(--muted); padding:10px 14px; background:var(--card);}}
.stat b{{display:block; font-size:1.02rem; color:var(--text); font-weight:600; margin-top:3px;}}
/* พยากรณ์รายวัน */
.day{{background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 8px; text-align:center; height:100%;}}
.day .d{{font-size:.78rem; color:var(--muted); font-weight:500;}}
.day .i .ms{{font-size:28px; margin:6px 0 4px; vertical-align:0;}}
.day .r{{font-weight:600; font-size:.92rem;}} .day .t{{font-size:.74rem; color:var(--muted);}}
.day .a{{font-size:.72rem; margin-top:6px; line-height:1.35;}}
/* sidebar */
.side-brand{{display:flex; gap:10px; align-items:center; margin:0 0 20px;}}
.side-brand .logo{{width:34px; height:34px; border-radius:9px; display:flex; align-items:center; justify-content:center;
  background:var(--brand); color:var(--brand-ink);}}
.side-brand .logo .ms{{font-size:21px; vertical-align:0;}}
.side-brand b{{font-size:1rem; color:var(--text); font-weight:600;}} .side-brand span{{display:block; font-size:.72rem; color:var(--muted);}}
.side-user{{display:flex; gap:10px; align-items:center; padding:12px; border:1px solid var(--line); border-radius:10px;
  background:var(--card); margin-bottom:14px;}}
.avatar{{width:36px; height:36px; border-radius:50%; background:var(--accent-bg); color:var(--green); flex-shrink:0;
  display:flex; align-items:center; justify-content:center; font-weight:600; font-size:.9rem; border:1px solid var(--accent-bd);}}
.side-user .em{{font-size:.84rem; font-weight:500; color:var(--text); word-break:break-all; line-height:1.3;}}
.side-user .fm{{font-size:.76rem; color:var(--muted);}}
.side-row{{font-size:.8rem; color:var(--text-2); padding:6px 2px; display:flex; align-items:center; gap:8px;}}
.side-row .ms{{font-size:17px; color:var(--muted); vertical-align:0;}}
.side-sec{{font-size:.72rem; letter-spacing:.04em; color:var(--muted); margin:18px 0 2px; font-weight:600;}}
/* ปุ่มสลับธีม */
.theme-wrap{{display:flex; justify-content:flex-end; align-items:center; gap:8px;}}
.theme-btn{{font-family:{FONT}; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:6px;
  height:36px; padding:0 12px; border-radius:8px; border:1px solid var(--line-2); background:var(--card);
  color:var(--text-2); font-size:.84rem; font-weight:500; transition:.12s;}}
.theme-btn:hover{{border-color:var(--brand); color:var(--text);}}
.theme-btn .ms{{font-size:18px; vertical-align:0;}}
.theme-btn .to-light{{display:inline-flex; align-items:center; gap:6px;}} .theme-btn .to-dark{{display:none;}}
html[data-theme="light"] .theme-btn .to-light{{display:none;}}
html[data-theme="light"] .theme-btn .to-dark{{display:inline-flex; align-items:center; gap:6px;}}
.date-chip{{font-size:.82rem; color:var(--text-2); height:36px; padding:0 12px; border-radius:8px; border:1px solid var(--line);
  background:var(--card); display:inline-flex; align-items:center; gap:6px;}}
.date-chip .ms{{font-size:18px; color:var(--muted); vertical-align:0;}}
/* หน้า login */
.auth-brand{{display:flex; gap:10px; align-items:center; margin:6vh 0 34px;}}
.auth-brand .logo{{width:38px; height:38px; border-radius:10px; background:var(--brand); color:var(--brand-ink);
  display:flex; align-items:center; justify-content:center;}}
.auth-brand .logo .ms{{font-size:23px; vertical-align:0;}}
.auth-brand b{{font-size:1.1rem; font-weight:600;}}
.auth-h1{{font-size:2.1rem; line-height:1.25; font-weight:600; letter-spacing:-.02em; color:var(--text); margin:0 0 12px;}}
.auth-lead{{font-size:1rem; color:var(--text-2); line-height:1.65; margin:0 0 28px; max-width:34rem;}}
.feat{{display:flex; gap:14px; align-items:flex-start; padding:14px 0; border-top:1px solid var(--line); max-width:34rem;}}
.feat .ic{{width:34px; height:34px; border-radius:8px; background:var(--accent-bg); color:var(--green); flex-shrink:0;
  display:flex; align-items:center; justify-content:center;}}
.feat .ic .ms{{vertical-align:0; font-size:20px;}}
.feat b{{display:block; font-size:.93rem; color:var(--text); font-weight:600;}}
.feat span{{font-size:.86rem; color:var(--muted);}}
.auth-foot{{font-size:.76rem; color:var(--muted); margin-top:26px;}}
.auth-form-title{{font-size:1.15rem; font-weight:600; margin:0 0 2px;}}
.auth-form-sub{{font-size:.85rem; color:var(--muted); margin:0 0 10px;}}
.st-key-card-login{{margin-top:12vh;}}
.doc-tile{{background:var(--card-2); border:1px dashed var(--line-2); border-radius:10px; aspect-ratio:4/3;
  display:flex; flex-direction:column; align-items:center; justify-content:center; color:var(--muted);
  font-size:.78rem; font-weight:600; margin-bottom:8px; gap:6px;}}
.doc-tile .ms{{font-size:34px; vertical-align:0;}}
.empty{{text-align:center; padding:40px 0; color:var(--muted); font-size:.9rem;}}
.empty .ms{{font-size:36px; display:block; margin:0 auto 8px; color:var(--line-2);}}
[data-testid="stChatMessage"]{{background:transparent;}}
/* ---------- หน้าภาพรวม ---------- */
.hero{{position:relative; overflow:hidden; display:grid; grid-template-columns:1.25fr 1fr; gap:28px;
  padding:26px 28px; border-radius:16px; color:#ecfdf3;
  background:linear-gradient(135deg,#0d3320 0%,#14532d 55%,#166534 100%); border:1px solid #1d5c36;}}
.hero::after{{content:""; position:absolute; right:-80px; top:-120px; width:360px; height:360px; border-radius:50%;
  background:radial-gradient(closest-side, rgba(134,239,172,.16), transparent); pointer-events:none;}}
.hero-eyebrow{{font-size:.78rem; color:rgba(236,253,243,.72); font-weight:500; display:flex; gap:6px; align-items:center;}}
.hero-eyebrow .ms{{font-size:17px; vertical-align:0;}}
.hero-head{{font-size:1.45rem; font-weight:600; line-height:1.35; margin:10px 0 8px; letter-spacing:-.01em; color:#fff;}}
.hero-text{{font-size:.9rem; line-height:1.65; color:rgba(236,253,243,.82); max-width:40rem;}}
.hero-tags{{display:flex; flex-wrap:wrap; gap:8px; margin-top:16px;}}
.hero-tag{{display:inline-flex; align-items:center; gap:6px; font-size:.78rem; padding:5px 10px; border-radius:999px;
  background:rgba(255,255,255,.09); border:1px solid rgba(255,255,255,.14); color:#ecfdf3;}}
.hero-tag .ms{{font-size:16px; vertical-align:0;}}
.hero-side{{display:grid; grid-template-columns:1fr; gap:10px; position:relative; z-index:1;}}
.hero-stat{{background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:12px 16px;
  display:grid; grid-template-columns:1fr auto; align-items:end; column-gap:12px;}}
.hero-stat .k{{grid-column:1/-1; font-size:.76rem; color:rgba(236,253,243,.7);}}
.hero-stat .v{{font-size:1.55rem; font-weight:600; color:#fff; font-variant-numeric:tabular-nums; letter-spacing:-.01em;}}
.hero-stat .v small{{font-size:.8rem; font-weight:500; color:rgba(236,253,243,.75);}}
.hero-note{{font-size:.72rem; color:rgba(236,253,243,.62); text-align:right; max-width:13rem;}}
.hero-delta{{display:inline-flex; align-items:center; gap:2px; font-size:.76rem; font-weight:600; padding:3px 8px;
  border-radius:999px; background:rgba(255,255,255,.1);}}
.hero-delta .ms{{font-size:15px; vertical-align:0;}}
.hero-delta.up{{color:#86efac;}} .hero-delta.down{{color:#fca5a5;}} .hero-delta.flat{{color:#e5e7eb;}}
.kpi{{display:flex; flex-direction:column;}}
.val-row{{display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;}}
.delta{{display:inline-flex; align-items:center; gap:1px; font-size:.74rem; font-weight:600; padding:2px 7px;
  border-radius:999px; font-variant-numeric:tabular-nums;}}
.delta .ms{{font-size:14px; vertical-align:0;}}
.delta.up{{color:var(--green); background:var(--accent-bg);}}
.delta.down{{color:var(--red); background:var(--red-bg);}}
.delta.flat{{color:var(--muted); background:var(--card-2);}}
.spark{{width:100%; height:34px; margin-top:auto; padding-top:10px; display:block;}}
.spark-empty{{height:34px; margin-top:auto;}}
.kpi .lbl .ms{{color:var(--muted);}}
.wx-list{{display:flex; flex-direction:column;}}
.wx-row{{display:grid; grid-template-columns:62px 24px 1fr 52px; align-items:center; gap:10px; padding:8px 0;
  border-bottom:1px solid var(--line); font-size:.84rem;}}
.wx-row:last-child{{border-bottom:none;}}
.wx-row .wd{{font-weight:600; color:var(--text);}} .wx-row .wd span{{font-weight:400; color:var(--muted); font-size:.76rem;}}
.wx-row .ms{{font-size:20px; vertical-align:0;}}
.wbar{{height:6px; border-radius:99px; background:var(--card-2); overflow:hidden;}}
.wbar i{{display:block; height:100%; border-radius:99px; min-width:3px;}}
.wmm{{text-align:right; font-variant-numeric:tabular-nums; color:var(--text-2);}}
.wadv{{grid-column:3/-1; font-size:.72rem; margin-top:-6px;}}
.tx-list{{display:flex; flex-direction:column;}}
.tx{{display:flex; align-items:center; gap:12px; padding:10px 0; border-bottom:1px solid var(--line);}}
.tx:last-child{{border-bottom:none;}}
.tx-ic{{width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center; flex-shrink:0;}}
.tx-ic .ms{{font-size:19px; vertical-align:0;}}
.tx-ic.in{{background:var(--accent-bg); color:var(--green);}} .tx-ic.out{{background:var(--card-2); color:var(--text-2);}}
.tx-body{{flex:1; min-width:0;}} .tx-body b{{display:block; font-size:.88rem; font-weight:600; color:var(--text);}}
.tx-body span{{font-size:.76rem; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;}}
.tx-amt{{text-align:right; font-weight:600; font-size:.9rem; font-variant-numeric:tabular-nums;}}
.tx-amt span{{display:block; font-size:.72rem; font-weight:400; color:var(--muted);}}
.tx-amt.in{{color:var(--green);}} .tx-amt.out{{color:var(--text);}}
.link-more{{display:inline-flex; align-items:center; gap:4px; margin-top:10px; font-size:.84rem; font-weight:500;
  color:var(--green) !important; text-decoration:none !important;}}
.link-more .ms{{font-size:17px; vertical-align:0;}}
.cbar{{margin-bottom:12px;}}
.cbar-top{{display:flex; justify-content:space-between; font-size:.84rem; color:var(--text);}}
.cbar-top span{{display:inline-flex; gap:6px; align-items:center;}} .cbar-top .ms{{font-size:17px; color:var(--muted); vertical-align:0;}}
.cbar-top b{{font-weight:600; font-variant-numeric:tabular-nums;}}
.cbar-track{{height:7px; border-radius:99px; background:var(--card-2); margin:6px 0 3px; overflow:hidden;}}
.cbar-track i{{display:block; height:100%; border-radius:99px; background:var(--brand);}}
.cbar-pct{{font-size:.72rem; color:var(--muted);}}
.cost-kg{{margin-top:6px; padding-top:12px; border-top:1px solid var(--line); font-size:.82rem; color:var(--muted);}}
.cost-kg b{{color:var(--text); font-weight:600;}}
a.qa{{display:flex; align-items:center; gap:12px; padding:11px 12px; border:1px solid var(--line); border-radius:10px;
  margin-bottom:8px; text-decoration:none !important; color:var(--text) !important; background:var(--card);
  transition:border-color .12s, background .12s, transform .12s;}}
a.qa:hover{{border-color:var(--brand); background:var(--card-hover); transform:translateY(-1px);}}
a.qa > .ms{{margin-left:auto; color:var(--muted); vertical-align:0;}}
.qa-ic{{width:34px; height:34px; border-radius:9px; background:var(--accent-bg); color:var(--green); flex-shrink:0;
  display:flex; align-items:center; justify-content:center;}}
.qa-ic .ms{{font-size:19px; vertical-align:0;}}
.qa-tx b{{display:block; font-size:.86rem; font-weight:600;}} .qa-tx span{{font-size:.74rem; color:var(--muted);}}
@media (max-width: 1100px){{ .hero{{grid-template-columns:1fr;}} }}
.pick-label{{font-size:.875rem; color:var(--text); margin:6px 0 -4px;}}
[data-testid="stPills"] button p{{font-size:.84rem;}}
/* ---------- แถบด้านข้าง ---------- */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:.45rem;}}
.side-empty{{font-size:.8rem; color:var(--muted); padding:2px 4px 6px;}}
.st-key-side-chats [data-testid="stVerticalBlock"]{{gap:2px;}}
.st-key-side-chats .stButton>button{{min-height:34px; justify-content:flex-start; padding:4px 8px; border-radius:8px;}}
.st-key-side-chats .stButton>button p{{white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:.84rem;
  font-weight:400; text-align:left;}}
.st-key-side-chats .stButton>button[kind="tertiary"]:hover{{background:var(--card-2);}}
.st-key-side-chats .stButton>button[kind="secondary"]{{background:var(--accent-bg); border-color:var(--accent-bd);}}
.st-key-side-chats [class*="st-key-chatdel"] button{{justify-content:center; padding:4px; color:var(--muted); opacity:.6;}}
.st-key-side-chats [class*="st-key-chatdel"] button:hover{{opacity:1; color:var(--red);}}
.side-tx{{display:flex; align-items:center; gap:8px; padding:6px 4px; font-size:.8rem; border-bottom:1px solid var(--line);}}
.side-tx:last-of-type{{border-bottom:none;}}
.side-tx .sd{{width:6px; height:6px; border-radius:50%; flex-shrink:0;}}
.side-tx .sd.in{{background:var(--green);}} .side-tx .sd.out{{background:var(--muted);}}
.side-tx .st{{flex:1; min-width:0; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}}
.side-tx .st small{{color:var(--muted); margin-left:6px;}}
.side-tx b{{font-weight:600; font-variant-numeric:tabular-nums;}} .side-tx b.in{{color:var(--green);}}
.side-link{{display:inline-flex; align-items:center; gap:3px; font-size:.8rem; margin:6px 4px 0;
  color:var(--green) !important; text-decoration:none !important;}}
.side-link .ms{{font-size:16px; vertical-align:0;}}
[data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"]{{visibility:visible !important; opacity:1 !important;}}
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
  document.addEventListener('click', (e) => {          // ทางลัดไปแท็บอื่น: ลิงก์ที่มี data-tab = ลำดับแท็บ
    const link = e.target.closest('[data-tab]');
    if (!link) return;
    e.preventDefault();
    const tab = document.querySelectorAll('[data-testid="stTab"]')[+link.dataset.tab];
    if (tab) { press(tab); window.scrollTo({top: 0, behavior: 'smooth'}); }
  });
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


def icon(name, fill=False, style=""):
    """ไอคอน Material Symbols สำหรับใช้ใน HTML"""
    return f'<span class="ms{" fill" if fill else ""}" style="{style}">{name}</span>'


def theme_toggle(extra=""):
    st.html(f'<div class="theme-wrap">{extra}<button class="theme-btn" type="button" title="สลับโหมดสว่าง/มืด">'
            f'<span class="to-light">{icon("light_mode")}โหมดสว่าง</span>'
            f'<span class="to-dark">{icon("dark_mode")}โหมดมืด</span></button></div>'
            + THEME_JS, unsafe_allow_javascript=True)


# ====================================================================== HELPERS
def th_date(d, with_year=True):
    if d is None or pd.isna(d):
        return "-"
    d = pd.to_datetime(d)
    return f"{d.day} {THAI_MONTHS[d.month - 1]}" + (f" {d.year + 543}" if with_year else "")


def baht(x, dec=0):
    return f"฿{x:,.{dec}f}"


_EMOJI = re.compile("^[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\uFE0F\u200d\s]+")


def _plain(text):
    """ตัดอีโมจินำหน้าข้อความออก (ให้หน้าตาเรียบแบบแอปทั่วไป)"""
    return _EMOJI.sub("", text or "")


def kpi(label, value, color=None, sub="", ic=None, spark="", delta=None):
    """การ์ดตัวเลข: delta = (ข้อความ, "up"|"down"|"flat")  spark = svg จาก sparkline()"""
    neg = " neg" if color == C_RED else ""
    d = ""
    if delta:
        arrow = {"up": "arrow_upward", "down": "arrow_downward"}.get(delta[1], "remove")
        d = f'<span class="delta {delta[1]}">{icon(arrow)}{delta[0]}</span>'
    return (f'<div class="kpi"><div class="lbl">{icon(ic) if ic else ""}{_plain(label)}</div>'
            f'<div class="val-row"><div class="val{neg}">{value}</div>{d}</div>'
            f'<div class="sub">{sub}</div>{spark}</div>')


def sparkline(vals, color="var(--green)", h=34):
    """เส้นแนวโน้มเล็ก ๆ (SVG) สำหรับการ์ดตัวเลข"""
    vals = [float(v) for v in vals if v is not None and v == v]
    if len(vals) < 2:
        return '<div class="spark-empty"></div>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    w = 100
    pts = [(i * w / (len(vals) - 1), h - 3 - (v - lo) / rng * (h - 8)) for i, v in enumerate(vals)]
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polygon points="0,{h} {line} {w},{h}" style="fill:{color};opacity:.10"/>'
            f'<polyline points="{line}" style="fill:none;stroke:{color};stroke-width:1.8" '
            f'vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/></svg>')


def card_header(title, sub=""):
    st.markdown(f'<div class="card-title">{_plain(title)}</div>'
                + (f'<div class="card-sub">{sub}</div>' if sub else '<div style="height:12px"></div>'),
                unsafe_allow_html=True)


NOTE_ICON = {"gold": "warning", "sky": "info", "red": "error", "ok": "check_circle"}


def note(text, tone="gold", ic=None):
    st.markdown(f'<div class="note {tone}">{icon(ic or NOTE_ICON.get(tone, "info"))}'
                f'<div>{_plain(text)}</div></div>', unsafe_allow_html=True)


def chart_style(chart, height=260):
    """แต่งกราฟ Altair ให้อ่านง่ายทั้งโหมดสว่างและมืด (พื้นโปร่ง สีแกนกลาง ๆ)"""
    return (chart.properties(height=height, background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=CH["axis"], titleColor=CH["axis"], gridColor=CH["grid"],
                            domainColor=CH["grid"], tickColor=CH["grid"], labelFont="IBM Plex Sans Thai", titleFont="IBM Plex Sans Thai")
            .configure_legend(labelColor=CH["axis"], titleColor=CH["axis"], labelFont="IBM Plex Sans Thai",
                              titleFont="IBM Plex Sans Thai", orient="top", symbolType="circle")
            .configure_text(font="IBM Plex Sans Thai"))


def ai_error_message(e):
    s = str(e)
    if "ไม่ว่าง" in s or "503" in s or "429" in s or "UNAVAILABLE" in s:
        return "ระบบ AI มีผู้ใช้งานมากในขณะนี้ กรุณารอสักครู่แล้วลองใหม่อีกครั้ง"
    return f"เกิดข้อผิดพลาดจากระบบ AI: {s[:300]}"


@st.cache_resource(show_spinner=False)
def get_gemini(user_keys=None):
    """user_keys: tuple ของ (ชื่อ, ค่า) ที่ผู้ใช้ใส่เอง หรือ None = ใช้ key ของระบบใน .env"""
    try:
        return GeminiService(dict(user_keys) if user_keys is not None else None), None
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
def get_weather(lat, lon, past_days=7, forecast_days=14):
    """ฝน/อุณหภูมิรายวัน ย้อนหลัง + ล่วงหน้า จาก Open-Meteo ในคำขอเดียว (ตามพิกัดสวน)"""
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": "Asia/Bangkok",
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
def get_rain(start, end, lat, lon):
    """ฝน/อุณหภูมิรายวันช่วงใดก็ได้: อดีตไกลใช้ archive API, 3 เดือนล่าสุด + อนาคต 16 วันใช้ forecast API"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    today = pd.Timestamp.today().normalize()
    daily = "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min"
    frames = []
    try:
        recent_from = today - pd.Timedelta(days=90)
        if start < recent_from:
            r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
                "latitude": lat, "longitude": lon, "timezone": "Asia/Bangkok",
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": min(end, recent_from - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min"}, timeout=20)
            r.raise_for_status()
            frames.append(pd.DataFrame(r.json()["daily"]))
        if end >= recent_from:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon, "timezone": "Asia/Bangkok",
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
    """-> (ชื่อไอคอน, คำแนะนำ, สี)"""
    if mm is None or pd.isna(mm):
        return "help", "ไม่มีข้อมูล", C_MUTED
    if mm < 1:
        return "sunny", "พ่นยา/ใส่ปุ๋ยได้", C_GREEN
    if mm < 10:
        return "partly_cloudy_day", "ฝนเล็กน้อย ระวังยาล้าง", C_SKY
    if mm < 20:
        return "rainy", "ฝนปานกลาง ควรเลื่อนพ่นยา", C_GOLD
    return "thunderstorm", "ฝนหนัก งดพ่นยา", C_RED


# ====================================================================== AUTH
auth = FirebaseAuthService()
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']"
                "{display:none;}</style>", unsafe_allow_html=True)
    theme_toggle()
    left, _, right = st.columns([1.2, 0.12, 0.9])
    with left:
        feats = [("document_scanner", "อ่านใบชั่งและบิลให้อัตโนมัติ",
                  "ถ่ายรูป หรืออัปโหลด PDF, Word, Excel แล้วตรวจทานก่อนบันทึก"),
                 ("account_balance_wallet", "รู้ต้นทุนและกำไรจริงของสวน",
                  "รายรับ รายจ่าย ค่าปุ๋ย ค่ายา ค่าแรง รวมไว้ในที่เดียว"),
                 ("monitoring", "ราคาตลาดและพยากรณ์อากาศ",
                  "ราคาขายส่งย้อนหลัง 17 ฤดู ช่วงราคาที่คาด และฝนรายวันของพื้นที่คุณ")]
        st.markdown(
            f'<div class="auth-brand"><div class="logo">{icon("eco")}</div><b>DurianOS</b></div>'
            '<div class="auth-h1">สมุดบัญชีสวนทุเรียน<br>ที่ทำงานแทนคุณ</div>'
            '<div class="auth-lead">บันทึกรายรับรายจ่ายจากใบชั่ง ดูราคาตลาด และวางแผนงานสวนตามสภาพอากาศ '
            'ในระบบเดียว</div>'
            + "".join(f'<div class="feat"><div class="ic">{icon(i)}</div><div><b>{t}</b><span>{d}</span></div></div>'
                      for i, t, d in feats)
            + '<div class="auth-foot">ข้อมูลราคา: กรมการค้าภายใน · อากาศ: Open-Meteo</div>',
            unsafe_allow_html=True)
    with right:
        with st.container(key="card-login"):
            st.markdown('<div class="auth-form-title">เข้าสู่ระบบ</div>'
                        '<div class="auth-form-sub">ใช้อีเมลและรหัสผ่านที่สมัครไว้ หรือสมัครสมาชิกใหม่</div>',
                        unsafe_allow_html=True)
            auth.render_forms()
        auth.render_diagnostics()
    st.stop()

# ====================================================================== LOGGED IN
user = st.session_state.user
db = auth.db if firestore_ok() else None       # Firestore มีปัญหา -> ใช้โหมดชั่วคราว ไม่ให้ทุกหน้าค้าง
ledger = LedgerService(db, user["uid"])
df_tx = ledger.list()
summary = LedgerService.summary(df_tx)
settings = SettingsService(db, user["uid"])
farm = settings.load()
FARM_LAT, FARM_LON, PROVINCE = farm["lat"], farm["lon"], farm["province"]
user_keys = settings.user_ai_keys()
if user_keys:
    gemini, gemini_err = get_gemini(tuple(sorted(user_keys.items())))
elif server_keys_allowed() and (os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY")):
    gemini, gemini_err = get_gemini()
else:
    gemini, gemini_err = None, "ยังไม่ได้ใส่ API key ของคุณ — ไปที่แท็บ ตั้งค่า"
ai_mode = "ใช้ API key ของคุณ" if user_keys else ("ใช้ AI ของระบบ" if gemini else "ยังไม่ได้ตั้งค่า AI")

try:
    card_main = ForecastService.get_price_card("หมอนทอง")
    forecast_err = None
except Exception as e:   # noqa: BLE001
    card_main, forecast_err = None, str(e)

if st.session_state.get("_fb_db_error"):
    note(f"เชื่อมฐานข้อมูล Firestore ไม่ได้ — {st.session_state['_fb_db_error']} "
         "(เข้าสู่ระบบได้ แต่ข้อมูลอาจไม่ถูกบันทึกถาวร)", "red")

# ---------------------------------------------------------------- sidebar (เปิด/ปิดได้ด้วยปุ่ม « / »)
chats = ChatService(db, user["uid"])
chat_key, cur_key = f"chat_{user['uid']}", f"chat_cur_{user['uid']}"
TAB_AI = 4


def open_chat(chat_id):
    st.session_state[cur_key] = chat_id
    st.session_state[chat_key] = chats.messages(chat_id) if chat_id else []
    st.session_state.goto_tab = TAB_AI


with st.sidebar:
    st.markdown(f'<div class="side-brand"><div class="logo">{icon("eco")}</div>'
                '<div><b>DurianOS</b><span>สมุดบัญชีสวนทุเรียน</span></div></div>', unsafe_allow_html=True)
    initials = (user.get("farm_name") or user["email"]).strip()[:1].upper()
    st.markdown(f'<div class="side-user"><div class="avatar">{initials}</div><div>'
                f'<div class="em">{user.get("farm_name", "สวนของฉัน")}</div>'
                f'<div class="fm">{user["email"]}</div></div></div>', unsafe_allow_html=True)

    if st.button("แชทใหม่", icon=":material/add_comment:", type="primary", width="stretch", key="side_new_chat"):
        open_chat(None)
        st.rerun()

    st.markdown('<div class="side-sec">ประวัติการสนทนา</div>', unsafe_allow_html=True)
    clist = chats.list()
    if not clist:
        st.markdown('<div class="side-empty">ยังไม่มีประวัติ — ลองถามผู้ช่วย AI ได้เลย</div>', unsafe_allow_html=True)
    with st.container(key="side-chats"):
        for c in clist:
            active = c["id"] == st.session_state.get(cur_key)
            a, b = st.columns([6, 1], gap=None, vertical_alignment="center")
            if a.button(c["title"], key=f"chatopen_{c['id']}", icon=":material/chat_bubble_outline:",
                        type="secondary" if active else "tertiary", width="stretch"):
                open_chat(c["id"])
                st.rerun()
            if b.button("", key=f"chatdel_{c['id']}", icon=":material/close:", type="tertiary", help="ลบบทสนทนานี้"):
                chats.delete(c["id"])
                if active:
                    open_chat(None)
                st.rerun()

    st.markdown('<div class="side-sec">รายการบัญชีล่าสุด</div>', unsafe_allow_html=True)
    if df_tx.empty:
        st.markdown('<div class="side-empty">ยังไม่มีรายการ</div>', unsafe_allow_html=True)
    else:
        rows = []
        for _, r in df_tx.head(5).iterrows():
            inc = r["type"] == INCOME
            rows.append(f'<div class="side-tx"><span class="sd {"in" if inc else "out"}"></span>'
                        f'<span class="st">{r["category"]}<small>{th_date(r["date"], False)}</small></span>'
                        f'<b class="{"in" if inc else "out"}">{"+" if inc else "−"}{baht(r["amount"])}</b></div>')
        st.markdown("".join(rows) + f'<a class="side-link" data-tab="1" href="#">ดูทั้งหมด {icon("arrow_forward")}</a>',
                    unsafe_allow_html=True)

    st.markdown('<div class="side-sec">บัญชีผู้ใช้</div>', unsafe_allow_html=True)
    if st.button("ออกจากระบบ", icon=":material/logout:", width="stretch", key="side_logout"):
        auth.logout()

# ---------------------------------------------------------------- header + KPI
h1, h2 = st.columns([3, 1.2], vertical_alignment="center")
with h1:
    st.markdown(f'<div class="page-eyebrow">{icon("eco")} {user.get("farm_name", "สวนของฉัน")}</div>'
                '<div class="page-title">ภาพรวมสวน</div>'
                f'<div class="page-meta"><span>{icon("location_on")}จังหวัด{PROVINCE}</span>'
                + (f'<span>{icon("park")}{farm["profile"]["rai"]:,.0f} ไร่ · {farm["profile"]["trees"]:,} ต้น</span>'
                   if farm.get("profile", {}).get("rai") or farm.get("profile", {}).get("trees") else "")
                + f'<span>{icon("receipt_long")}{summary["count"]} รายการในบัญชี</span></div>',
                unsafe_allow_html=True)
with h2:
    theme_toggle(f'<span class="date-chip">{icon("calendar_today")}'
                 f'{THAI_DAYS[date.today().weekday()]} {th_date(date.today())}</span>')

st.write("")
tab_home, tab_book, tab_price, tab_env, tab_ai, tab_set = st.tabs(
    [":material/space_dashboard: ภาพรวม", ":material/receipt_long: บัญชีสวน", ":material/monitoring: ราคาทุเรียน",
     ":material/partly_cloudy_day: อากาศและค่าเงิน", ":material/forum: ผู้ช่วย AI", ":material/settings: ตั้งค่า"])

# ====================================================================== TAB 0: ภาพรวม
CAT_ICON = {"ขายทุเรียน": "sell", "ปุ๋ย": "compost", "ยา/สารเคมี": "science", "ค่าแรง": "groups",
            "อุปกรณ์": "handyman", "ขนส่ง": "local_shipping", "น้ำ/ไฟ": "bolt", "อื่น ๆ": "more_horiz"}

# ช่องกรอกเฉพาะของแต่ละหมวด (ใช้ในฟอร์ม "เพิ่มรายการเอง") -> รวมเป็นข้อความในช่องหมายเหตุ
def _j(*parts):
    return " · ".join(str(p) for p in parts if p not in (None, "", 0, 0.0))


def _n(v, unit):
    return f"{v:,.0f} {unit}" if v else ""


CAT_FORM = {
    "ขายทุเรียน": {
        "party": "ล้ง / ผู้ซื้อ",
        "hint": "ใส่น้ำหนักและราคาต่อกก. ระบบคำนวณจำนวนเงินให้ (หรือใส่จำนวนเงินเองก็ได้)",
        "fields": [("variety", "พันธุ์", "select", ["หมอนทอง", "ชะนี", "ก้านยาว", "พวงมณี", "กระดุม", "อื่น ๆ"]),
                   ("grade", "เกรด", "select", ["AB", "C", "ตกไซซ์", "คละเกรด"]),
                   ("kg", "น้ำหนัก (กก.)", "num", 10.0), ("price", "ราคาต่อกก. (บาท)", "num", 1.0)],
        "detail": lambda v: _j(f"{v['variety']} {v['grade']}",
                               f"{v['kg']:,.0f} กก.@{v['price']:,.0f}" if v.get("kg") and v.get("price") else ""),
    },
    "ปุ๋ย": {
        "party": "ร้านค้า",
        "fields": [("formula", "สูตร / ชนิดปุ๋ย", "text", "เช่น 15-15-15, ขี้ไก่"),
                   ("qty", "จำนวน (กระสอบ)", "num", 1.0)],
        "detail": lambda v: _j(f"สูตร {v['formula']}" if v["formula"] else "", _n(v["qty"], "กระสอบ")),
    },
    "ยา/สารเคมี": {
        "party": "ร้านค้า",
        "hint": "เก็บชื่อสารไว้เป็นหลักฐาน GAP ได้",
        "fields": [("name", "ชื่อยา / สาร", "text", "เช่น ฟอสโฟนิก แอซิด"),
                   ("qty", "ปริมาณ", "text", "เช่น 2 ขวด, 5 ลิตร")],
        "detail": lambda v: _j(v["name"], v["qty"]),
    },
    "ค่าแรง": {
        "party": "ชื่อคนงาน / หัวหน้าทีม",
        "fields": [("job", "งานที่จ้าง", "select", ["ตัดทุเรียน", "พ่นยา", "ใส่ปุ๋ย", "ตัดหญ้า", "ตัดแต่งกิ่ง", "อื่น ๆ"]),
                   ("people", "จำนวนคน", "num", 1.0), ("days", "จำนวนวัน", "num", 1.0)],
        "detail": lambda v: _j(v["job"], f"{v['people']:,.0f} คน × {v['days']:,.0f} วัน"
                               if v["people"] and v["days"] else _n(v["people"], "คน")),
    },
    "อุปกรณ์": {
        "party": "ร้านค้า",
        "fields": [("item", "ชื่ออุปกรณ์", "text", "เช่น สายยาง, กรรไกรตัดกิ่ง"), ("qty", "จำนวน (ชิ้น)", "num", 1.0)],
        "detail": lambda v: _j(v["item"], _n(v["qty"], "ชิ้น")),
    },
    "ขนส่ง": {
        "party": "ผู้ขนส่ง",
        "fields": [("route", "รายละเอียด", "text", "เช่น ค่ารถขนทุเรียนไปล้ง"), ("trips", "จำนวนเที่ยว", "num", 1.0)],
        "detail": lambda v: _j(v["route"], _n(v["trips"], "เที่ยว")),
    },
    "น้ำ/ไฟ": {
        "party": "ผู้ให้บริการ เช่น การไฟฟ้าส่วนภูมิภาค",
        "fields": [("kind", "ประเภทบิล", "select", ["ค่าไฟ", "ค่าน้ำ", "น้ำมันเครื่องสูบน้ำ"]),
                   ("period", "งวดเดือน", "text", "เช่น ก.ย. 2569")],
        "detail": lambda v: _j(v["kind"], f"งวด {v['period']}" if v["period"] else ""),
    },
}


with tab_home:
    wx_home = get_weather(FARM_LAT, FARM_LON)
    wx_next = wx_home[wx_home["period"] == "พยากรณ์"].head(7) if wx_home is not None else None
    hist12 = pd.DataFrame()
    if card_main:
        try:
            hist12 = ForecastService.get_price_history("หมอนทอง").tail(12)
        except Exception:   # noqa: BLE001
            pass
    wk_chg = None
    if len(hist12) >= 2:
        wk_chg = (hist12["price_mid"].iloc[-1] / hist12["price_mid"].iloc[-2] - 1) * 100

    # ---------- การ์ดสรุปสัปดาห์
    if card_main:
        lvl = card_main["drop_level"]
        headline = {"ต่ำ": "ราคาค่อนข้างทรงตัว ขายตามความแก่ของผลได้ตามปกติ",
                    "ปานกลาง": "ราคามีโอกาสอ่อนตัวลงเล็กน้อยในสัปดาห์หน้า",
                    "สูง": "ระวังราคาลงในสัปดาห์หน้า วางแผนการตัดให้ดี"}.get(lvl, "ติดตามราคาอย่างใกล้ชิด")
        advice = card_main["advice"]
    else:
        headline, advice = "ยังไม่มีข้อมูลราคา", "รัน run_all.py ในโฟลเดอร์ forecast เพื่อดึงข้อมูลราคาล่าสุด"
    tags = []
    if wx_next is not None and not wx_next.empty:
        for label, (_, r) in zip(["วันนี้", "พรุ่งนี้"], wx_next.head(2).iterrows()):
            ic, adv, _c = rain_advice(r["rain"])
            tags.append(f'<span class="hero-tag">{icon(ic)}{label}: {adv} ({(r["rain"] or 0):.0f} มม.)</span>')
    tags.append(f'<span class="hero-tag">{icon("location_on")}{PROVINCE}</span>')
    side = ""
    if card_main:
        chg_html = ""
        if wk_chg is not None:
            cls = "up" if wk_chg > 0.05 else "down" if wk_chg < -0.05 else "flat"
            arrow = {"up": "arrow_upward", "down": "arrow_downward", "flat": "remove"}[cls]
            chg_html = f'<span class="hero-delta {cls}">{icon(arrow)}{abs(wk_chg):.1f}% จากสัปดาห์ก่อน</span>'
        side = (f'<div class="hero-stat"><div class="k">หมอนทอง ขายส่ง กทม.</div>'
                f'<div class="v">{card_main["price_now"]:.0f}<small> ฿/กก.</small></div>{chg_html}</div>'
                f'<div class="hero-stat"><div class="k">ช่วงที่คาด สัปดาห์หน้า</div>'
                f'<div class="v">{card_main["next_week_low"]:.0f}–{card_main["next_week_high"]:.0f}<small> ฿</small></div>'
                f'<span class="hero-note">ครอบคลุมราคาจริง ~81% ในการทดสอบย้อนหลัง</span></div>'
                f'<div class="hero-stat"><div class="k">โอกาสราคาลง ≥5฿ ใน 1 สัปดาห์</div>'
                f'<div class="v">{card_main["drop_chance_pct"]}<small>%</small></div>'
                f'<span class="hero-note">ระดับ{card_main["drop_level"]} ตามสถิติช่วงฤดู</span></div>')
    st.markdown(
        f'<div class="hero"><div class="hero-main">'
        f'<div class="hero-eyebrow">{icon("insights")}สรุปประจำสัปดาห์ · {th_date(date.today())}</div>'
        f'<div class="hero-head">{headline}</div><div class="hero-text">{advice}</div>'
        f'<div class="hero-tags">{"".join(tags)}</div></div>'
        f'<div class="hero-side">{side}</div></div>', unsafe_allow_html=True)

    # ---------- KPI + เส้นแนวโน้ม
    st.write("")
    months = (df_tx.dropna(subset=["date"])
              .assign(m=lambda d: d["date"].dt.to_period("M"))
              .pivot_table(index="m", columns="type", values="amount", aggfunc="sum", fill_value=0)
              if not df_tx.empty else pd.DataFrame())
    if not months.empty:
        months = months.reindex(pd.period_range(months.index.min(), max(months.index.max(),
                                pd.Timestamp.today().to_period("M"))), fill_value=0).tail(8)
    inc_series = months[INCOME].tolist() if INCOME in months else []
    exp_series = months[EXPENSE].tolist() if EXPENSE in months else []
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi("รายรับรวม", baht(summary["income"]), None,
                    f"ขายไป {summary['sold_kg']:,.0f} กก." if summary["sold_kg"] else "จากใบชั่งที่บันทึก",
                    ic="payments", spark=sparkline(inc_series, "var(--green)")), unsafe_allow_html=True)
    k2.markdown(kpi("รายจ่ายรวม", baht(summary["expense"]), None, "ปุ๋ย ยา ค่าแรง และอื่น ๆ",
                    ic="shopping_cart", spark=sparkline(exp_series, "var(--red)")), unsafe_allow_html=True)
    margin = summary["profit"] / summary["income"] * 100 if summary["income"] else None
    k3.markdown(kpi("กำไรสุทธิ", baht(summary["profit"]), None if summary["profit"] >= 0 else C_RED,
                    "กำไรหลังหักต้นทุนที่บันทึก", ic="account_balance_wallet",
                    spark=sparkline(pd.Series(inc_series or [0] * len(exp_series)).cumsum()
                                    .sub(pd.Series(exp_series or [0] * len(inc_series)).cumsum()).tolist()
                                    if (inc_series or exp_series) else [], "var(--gold)"),
                    delta=(f"อัตรากำไร {margin:.0f}%", "up" if margin >= 0 else "down") if margin is not None else None),
                unsafe_allow_html=True)
    if card_main:
        k4.markdown(kpi("ราคาหมอนทอง", f"{card_main['price_now']:.0f} ฿/กก.", None,
                        f"ข้อมูลสัปดาห์ {th_date(card_main['as_of'], False)}", ic="storefront",
                        spark=sparkline(hist12["price_mid"].tolist() if not hist12.empty else [], "var(--sky)"),
                        delta=(f"{wk_chg:+.1f}%", "up" if wk_chg > 0 else "down" if wk_chg < 0 else "flat")
                        if wk_chg is not None else None), unsafe_allow_html=True)
    else:
        k4.markdown(kpi("ราคาหมอนทอง", "—", None, "ยังไม่มีข้อมูล", ic="storefront"), unsafe_allow_html=True)

    # ---------- กราฟราคา + ฝน 7 วัน
    st.write("")
    r1, r2 = st.columns([1.65, 1], gap="medium")
    with r1, st.container(key="card-home-price"):
        card_header("ราคาหมอนทอง 12 สัปดาห์ล่าสุด", "ราคากลางขายส่งตลาดกรุงเทพฯ และช่วงที่คาดในสัปดาห์ถัดไป")
        if hist12.empty:
            st.markdown(f'<div class="empty">{icon("show_chart")}ยังไม่มีข้อมูลราคา</div>', unsafe_allow_html=True)
        else:
            base = alt.Chart(hist12).encode(x=alt.X("week_end:T", title=None, axis=alt.Axis(format="%d %b", tickCount=6)))
            lo_, hi_ = float(hist12["price_mid"].min()), float(hist12["price_mid"].max())
            if card_main:
                lo_, hi_ = min(lo_, card_main["next_week_low"]), max(hi_, card_main["next_week_high"])
            pad = max((hi_ - lo_) * 0.15, 3)
            yscale = alt.Scale(domain=[lo_ - pad, hi_ + pad], nice=False)
            area = base.mark_area(clip=True, line={"color": CH["green"], "strokeWidth": 2.2}, color=alt.Gradient(
                gradient="linear", x1=1, x2=1, y1=1, y2=0,
                stops=[alt.GradientStop(color="rgba(34,197,94,0)", offset=0),
                       alt.GradientStop(color="rgba(34,197,94,.28)", offset=1)])).encode(
                y=alt.Y("price_mid:Q", title=None, scale=yscale),
                tooltip=[alt.Tooltip("week_end:T", title="สัปดาห์", format="%d %b %Y"),
                         alt.Tooltip("price_mid:Q", title="บาท/กก.", format=".1f")])
            pts = base.mark_circle(size=34, color=CH["green"]).encode(y=alt.Y("price_mid:Q", scale=yscale))
            layers = [area, pts]
            prod0 = ForecastService._product("หมอนทอง")
            fc0 = pd.DataFrame(prod0["price_range"]).assign(week_end=lambda d: pd.to_datetime(d["target_week"]))
            band0 = pd.concat([pd.DataFrame([{"week_end": hist12["week_end"].iloc[-1],
                                              "low_80": hist12["price_mid"].iloc[-1],
                                              "high_80": hist12["price_mid"].iloc[-1]}]),
                               fc0[["week_end", "low_80", "high_80"]]])
            layers.insert(0, alt.Chart(band0).mark_area(color=CH["sky"], opacity=.18, clip=True).encode(
                x="week_end:T", y=alt.Y("low_80:Q", scale=yscale), y2="high_80:Q",
                tooltip=[alt.Tooltip("week_end:T", title="สัปดาห์", format="%d %b %Y"),
                         alt.Tooltip("low_80:Q", title="คาดต่ำสุด", format=".0f"),
                         alt.Tooltip("high_80:Q", title="คาดสูงสุด", format=".0f")]))
            st.altair_chart(chart_style(alt.layer(*layers), 372), width="stretch")
    with r2, st.container(key="card-home-wx"):
        card_header(f"ฝน 7 วันข้างหน้า · {PROVINCE}", "ใช้วางแผนพ่นยาและใส่ปุ๋ย")
        if wx_next is None or wx_next.empty:
            st.markdown(f'<div class="empty">{icon("cloud_off")}ดึงพยากรณ์อากาศไม่ได้ในขณะนี้</div>',
                        unsafe_allow_html=True)
        else:
            mx = max(float(wx_next["rain"].fillna(0).max()), 10.0)
            rows = []
            for _, r in wx_next.iterrows():
                ic, adv, color = rain_advice(r["rain"])
                mm = r["rain"] or 0
                rows.append(
                    f'<div class="wx-row"><div class="wd">{THAI_DAYS[r["date"].dayofweek]} '
                    f'<span>{r["date"].day}/{r["date"].month}</span></div>'
                    f'{icon(ic, style=f"color:{color}")}'
                    f'<div class="wbar"><i style="width:{min(mm / mx * 100, 100):.0f}%;background:{color}"></i></div>'
                    f'<div class="wmm">{mm:.0f} มม.</div><div class="wadv" style="color:{color}">{adv}</div></div>')
            st.markdown('<div class="wx-list">' + "".join(rows) + "</div>", unsafe_allow_html=True)

    # ---------- รายการล่าสุด + ต้นทุนแยกหมวด + ทางลัด
    st.write("")
    c1, c2, c3 = st.columns([1.25, 1, 0.8], gap="medium")
    with c1, st.container(key="card-home-recent"):
        card_header("รายการล่าสุด", f"ทั้งหมด {summary['count']} รายการ")
        if df_tx.empty:
            st.markdown(f'<div class="empty">{icon("inbox")}ยังไม่มีรายการ<br>เริ่มจากสแกนใบชั่งใบแรก</div>',
                        unsafe_allow_html=True)
        else:
            items = []
            for _, r in df_tx.head(6).iterrows():
                inc = r["type"] == INCOME
                sub = " · ".join(x for x in [th_date(r["date"]), r["party"] or ""] if x)
                kg = f'{r["weight_kg"]:,.0f} กก.' if inc and pd.notna(r["weight_kg"]) and r["weight_kg"] else ""
                items.append(
                    f'<div class="tx"><div class="tx-ic {"in" if inc else "out"}">{icon(CAT_ICON.get(r["category"], "receipt"))}</div>'
                    f'<div class="tx-body"><b>{r["category"]}</b><span>{sub}</span></div>'
                    f'<div class="tx-amt {"in" if inc else "out"}">{"+" if inc else "−"}{baht(r["amount"])}'
                    f'<span>{kg}</span></div></div>')
            st.markdown('<div class="tx-list">' + "".join(items) + "</div>"
                        '<a class="link-more" data-tab="1" href="#">ดูบัญชีทั้งหมด ' + icon("arrow_forward") + "</a>",
                        unsafe_allow_html=True)
    with c2, st.container(key="card-home-cost"):
        card_header("ต้นทุนแยกหมวด", "สัดส่วนรายจ่ายทั้งหมดที่บันทึก")
        exp_cat = (df_tx[df_tx["type"] == EXPENSE].groupby("category")["amount"].sum()
                   .sort_values(ascending=False) if not df_tx.empty else pd.Series(dtype=float))
        if exp_cat.empty:
            st.markdown(f'<div class="empty">{icon("pie_chart")}ยังไม่มีรายจ่าย</div>', unsafe_allow_html=True)
        else:
            tot = exp_cat.sum()
            bars = "".join(
                f'<div class="cbar"><div class="cbar-top"><span>{icon(CAT_ICON.get(k, "more_horiz"))}{k}</span>'
                f'<b>{baht(v)}</b></div><div class="cbar-track"><i style="width:{v / tot * 100:.1f}%"></i></div>'
                f'<div class="cbar-pct">{v / tot * 100:.0f}% ของต้นทุน</div></div>' for k, v in exp_cat.items())
            per_kg = (f'<div class="cost-kg">ต้นทุนต่อกิโลที่ขายได้ <b>{tot / summary["sold_kg"]:,.1f} ฿/กก.</b></div>'
                      if summary["sold_kg"] else "")
            st.markdown(bars + per_kg, unsafe_allow_html=True)
    with c3, st.container(key="card-home-actions"):
        card_header("ทางลัด")
        acts = [("document_scanner", "สแกนใบชั่ง / บิล", "ให้ AI ลงบัญชีให้", 1),
                ("monitoring", "ดูราคาและพยากรณ์", "ย้อนหลัง 17 ฤดู", 2),
                ("forum", "ถามผู้ช่วย AI", "กำไร ราคา การพ่นยา", 4),
                ("tune", "ตั้งค่าสวนและ AI", "จังหวัด และ API key", 5)]
        st.markdown("".join(
            f'<a class="qa" data-tab="{t}" href="#"><span class="qa-ic">{icon(i)}</span>'
            f'<span class="qa-tx"><b>{a}</b><span>{d}</span></span>{icon("chevron_right")}</a>'
            for i, a, d, t in acts), unsafe_allow_html=True)

# ====================================================================== TAB 1: บัญชีสวน
with tab_book:
    col_scan, col_list = st.columns([1, 1.35], gap="large")

    # -------------------------------------------------- สแกน
    with col_scan:
        with st.container(key="card-scan"):
            card_header("สแกนเอกสาร / นำเข้าไฟล์บัญชี",
                        "รูปใบชั่ง/บิล · PDF · Word ให้ AI อ่านเป็นรายการ · Excel/CSV นำเข้าได้ทีละหลายรายการ")
            if gemini_err:
                note(f"ใช้ AI ไม่ได้: {gemini_err}", "red")
            up_key = f"uploader_{st.session_state.get('upload_n', 0)}"
            up = st.file_uploader("เลือกไฟล์", type=UPLOAD_TYPES, key=up_key, label_visibility="collapsed")
            st.caption("รองรับ JPG · PNG · PDF · Word (.docx) · Excel (.xlsx) · CSV — ไฟล์ .xls/.doc รุ่นเก่า "
                       "ให้เปิดแล้ว 'บันทึกเป็น' .xlsx/.docx ก่อน")

            def reset_upload():
                st.session_state.pop("ocr_result", None)
                st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
                st.rerun()

            sig = f"{up.name}|{up.size}" if up is not None else None
            if st.session_state.get("ocr_sig") != sig:        # เปลี่ยนไฟล์ -> ล้างผลอ่านของไฟล์เก่า
                st.session_state.pop("ocr_result", None)
                st.session_state.ocr_sig = sig
            kind = file_kind(up.name) if up is not None else None
            data = up.getvalue() if up is not None else b""

            # ---------- Excel / CSV: นำเข้าเป็นตารางหลายรายการ
            as_doc = False
            if kind == "table":
                mode = st.segmented_control(
                    "วิธีอ่าน", ["นำเข้าเป็นตารางบัญชี", "ให้ AI อ่านเป็นบิล 1 ใบ"],
                    default="นำเข้าเป็นตารางบัญชี", key="table_mode", label_visibility="collapsed")
                as_doc = mode == "ให้ AI อ่านเป็นบิล 1 ใบ"
                try:
                    sheets = sheet_names(data, up.name)
                    sheet = st.selectbox("ชีต", sheets, key="imp_sheet") if len(sheets) > 1 else None
                    raw = read_raw(data, up.name, sheet)
                except Exception as e:   # noqa: BLE001
                    note(f"เปิดไฟล์ไม่ได้: {e}", "red")
                    raw = None
                if raw is not None and raw.dropna(how="all").empty:
                    note("ไฟล์นี้ไม่มีข้อมูล", "gold")
                    raw = None
                if raw is not None and not as_doc:
                    h0 = guess_header_row(raw)
                    n_rows = len(raw.dropna(how="all"))
                    hdr = st.number_input("หัวตารางอยู่แถวที่", 1, max(1, min(n_rows, 30)), h0 + 1,
                                          help="ถ้ามีชื่อรายงานอยู่ด้านบนตาราง ให้เลื่อนเป็นแถวที่มีชื่อคอลัมน์") - 1
                    tbl = apply_header(raw, hdr)
                    st.dataframe(tbl.head(6).fillna(""), hide_index=True, width="stretch")
                    st.caption(f"ทั้งหมด {len(tbl)} แถว · แสดง 6 แถวแรก")
                    st.markdown("**จับคู่คอลัมน์** (ระบบเดาให้แล้ว ตรวจและแก้ได้)")
                    g = guess_columns(tbl.columns)
                    opts = ["— ไม่มี —"] + list(tbl.columns)

                    def pick(label, field, col):
                        v = col.selectbox(label, opts, index=opts.index(g[field]) if g.get(field) in opts else 0,
                                          key=f"map_{field}_{up_key}")
                        return None if v == "— ไม่มี —" else v

                    default_mode = ("มีคอลัมน์รายรับ/รายจ่ายแยกกัน" if "income" in g and "expense" in g
                                    else "มีคอลัมน์บอกประเภท" if "type" in g
                                    else "ดูจากเครื่องหมาย (ติดลบ = รายจ่าย)")
                    type_mode = st.selectbox("แยกรายรับ/รายจ่ายอย่างไร", TYPE_MODES,
                                             index=TYPE_MODES.index(default_mode), key=f"map_mode_{up_key}")
                    a1, a2 = st.columns(2)
                    mapping = {"date": pick("วันที่ *", "date", a1)}
                    if type_mode == "มีคอลัมน์รายรับ/รายจ่ายแยกกัน":
                        mapping["income"] = pick("คอลัมน์รายรับ *", "income", a2)
                        mapping["expense"] = pick("คอลัมน์รายจ่าย *", "expense", a1)
                    else:
                        mapping["amount"] = pick("จำนวนเงิน *", "amount", a2)
                    if type_mode == "มีคอลัมน์บอกประเภท":
                        mapping["type"] = pick("ประเภท (รับ/จ่าย) *", "type", a1)
                    b1_, b2_ = st.columns(2)
                    mapping["category"] = pick("หมวดหมู่", "category", b1_)
                    mapping["weight"] = pick("น้ำหนัก (กก.)", "weight", b2_)
                    mapping["party"] = pick("ล้ง / ร้านค้า", "party", b1_)
                    mapping["note"] = pick("หมายเหตุ / รายการ", "note", b2_)

                    entries, skipped = build_entries(tbl, mapping, type_mode, EXPENSE_CATS, INCOME_CATS)
                    if entries.empty:
                        note("ยังไม่พบรายการที่นำเข้าได้ ตรวจว่าเลือกคอลัมน์วันที่และจำนวนเงินถูกต้อง"
                             + (f" (ข้าม: {', '.join(f'{k} {v} แถว' for k, v in skipped.items())})" if skipped else ""),
                             "gold")
                    else:
                        dup = mark_duplicates(entries, df_tx)
                        es = LedgerService.summary(entries)
                        stats_row([("พร้อมนำเข้า", f"{len(entries)} รายการ"), ("รายรับ", baht(es["income"])),
                                   ("รายจ่าย", baht(es["expense"])),
                                   ("ช่วงวันที่", f"{th_date(entries['date'].min(), False)} – "
                                                  f"{th_date(entries['date'].max())}")])
                        if skipped:
                            st.caption("ข้ามแถวที่อ่านไม่ได้: " + ", ".join(f"{k} {v} แถว" for k, v in skipped.items()))
                        prev = entries.assign(**{"วันที่": entries["date"].map(th_date),
                                                 "สถานะ": dup.map({True: "มีในบัญชีแล้ว", False: "ใหม่"})})
                        st.dataframe(prev[["วันที่", "type", "category", "amount", "weight_kg", "party", "สถานะ"]]
                                     .rename(columns={"type": "ประเภท", "category": "หมวด", "amount": "บาท",
                                                      "weight_kg": "กก.", "party": "ล้ง/ร้าน"}),
                                     hide_index=True, width="stretch", height=min(300, 40 + 35 * len(prev)))
                        keep_dup = False
                        if dup.any():
                            keep_dup = st.checkbox(f"นำเข้ารายการที่ดูเหมือนซ้ำด้วย ({int(dup.sum())} รายการ: "
                                                   "วัน ประเภท และจำนวนเงินตรงกับที่มีในบัญชี)", value=False)
                        todo = entries if keep_dup else entries[~dup]
                        c_ok, c_no = st.columns(2)
                        if c_ok.button(f"นำเข้า {len(todo)} รายการ", icon=":material/download:", type="primary", width="stretch",
                                       disabled=todo.empty):
                            n = ledger.add_many(todo.to_dict("records"), source="import")
                            st.toast(f"นำเข้า {n} รายการแล้ว", icon=":material/check_circle:")
                            reset_upload()
                        if c_no.button("ยกเลิก", width="stretch", key="imp_cancel"):
                            reset_upload()

            # ---------- รูป / PDF / Word / (Excel ที่ให้ AI อ่าน): อ่านเป็นเอกสาร 1 ใบ
            doc_text, can_read = None, True
            if kind == "image":
                img = Image.open(io.BytesIO(data))
                st.image(img, width="stretch")
            elif kind == "pdf":
                if len(data) > 15 * 1024 * 1024:
                    note("ไฟล์ PDF ใหญ่เกิน 15 MB กรุณาแยกเฉพาะหน้าที่เป็นใบเสร็จ", "red")
                    can_read = False
                else:
                    try:
                        pages, ptext = pdf_info(data)
                        st.markdown(f'<div class="note sky">{icon("picture_as_pdf")}<div><b>{up.name}</b> · {pages} หน้า · '
                                    f'{"มีข้อความในไฟล์" if ptext else "เป็นภาพสแกน (AI อ่านจากภาพ)"}</div></div>',
                                    unsafe_allow_html=True)
                        if ptext:
                            with st.expander("ดูข้อความในไฟล์"):
                                st.text(ptext[:3000])
                    except Exception as e:   # noqa: BLE001
                        note(f"เปิด PDF ไม่ได้ (ไฟล์อาจเสียหรือมีรหัสผ่าน): {e}", "red")
                        can_read = False
            elif kind == "word":
                try:
                    doc_text = docx_text(data)
                except Exception as e:   # noqa: BLE001
                    note(f"เปิดไฟล์ Word ไม่ได้: {e}", "red")
                    can_read = False
                else:
                    if not doc_text.strip():
                        note("ไม่พบข้อความในไฟล์ Word นี้ (ถ้าเป็นรูปที่แปะไว้ ให้บันทึกรูปแล้วอัปโหลดเป็นรูปแทน)", "gold")
                        can_read = False
                    else:
                        st.markdown(f'<div class="note sky">{icon("description")}<div><b>{up.name}</b> · {len(doc_text):,} ตัวอักษร</div></div>',
                                    unsafe_allow_html=True)
                        with st.expander("ดูข้อความในไฟล์"):
                            st.text(doc_text[:3000])
            elif kind == "table" and as_doc:
                if raw is None:
                    can_read = False
                else:
                    doc_text = table_as_text(raw.dropna(how="all").dropna(axis=1, how="all"))
                    st.dataframe(raw.dropna(how="all").dropna(axis=1, how="all").head(15).fillna(""), width="stretch")

            is_doc = kind in ("image", "pdf", "word") or (kind == "table" and as_doc)
            if is_doc and can_read and "ocr_result" not in st.session_state:
                if st.button("ให้ AI อ่านข้อมูล", icon=":material/auto_awesome:", type="primary", width="stretch", disabled=gemini is None):
                    with st.spinner("AI กำลังอ่านเอกสาร..."):
                        try:
                            if kind == "image":
                                st.session_state.ocr_result = gemini.extract_receipt(img)
                            elif kind == "pdf":
                                st.session_state.ocr_result = gemini.extract_receipt_pdf(data)
                            else:
                                st.session_state.ocr_result = gemini.extract_receipt_text(doc_text)
                            st.rerun()
                        except Exception as e:   # noqa: BLE001
                            note(ai_error_message(e), "red")

            res = st.session_state.get("ocr_result")
            if is_doc and res:
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
                if b1.button("บันทึกเข้าบัญชี", icon=":material/save:", type="primary", width="stretch"):
                    ledger.add({"date": tdate, "type": ttype, "category": tcat, "amount": tamount,
                                "party": tparty, "weight_kg": tweight if ttype == INCOME else None,
                                "note": tnote, "image_path": ledger.save_image(up),
                                "source": "ai" if kind == "image" else f"ai-{kind}"})
                    st.toast(f"บันทึก{ttype} {baht(tamount)} แล้ว", icon=":material/check_circle:")
                    reset_upload()
                if b2.button("ยกเลิก", width="stretch"):
                    reset_upload()

        st.write("")
        if True:
            with st.expander("เพิ่มรายการเอง (ไม่มีบิล เช่น ค่าแรง)", icon=":material/edit_note:"):
                m_type = st.radio("ประเภท", [EXPENSE, INCOME], horizontal=True, key="m_type")
                m_cats = EXPENSE_CATS if m_type == EXPENSE else INCOME_CATS
                st.markdown('<div class="pick-label">เลือกหมวดหมู่</div>', unsafe_allow_html=True)
                m_cat = st.pills("หมวดหมู่", m_cats, default=m_cats[0], key=f"m_cat_{m_type}",
                                 format_func=lambda c: f":material/{CAT_ICON.get(c, 'more_horiz')}: {c}",
                                 label_visibility="collapsed") or m_cats[0]
                spec = CAT_FORM.get(m_cat, {})
                if spec.get("hint"):
                    st.caption(spec["hint"])
                with st.form(f"manual_form_{m_type}_{m_cat}", clear_on_submit=True, border=False):
                    c1, c2 = st.columns(2)
                    m_date = c1.date_input("วันที่", value=date.today(), format="DD/MM/YYYY")
                    m_amount = c2.number_input("จำนวนเงิน (บาท)", min_value=0.0, step=100.0,
                                               help="ขายทุเรียน: เว้น 0 ได้ ระบบคำนวณจากน้ำหนัก × ราคาให้"
                                               if m_cat == "ขายทุเรียน" else None)
                    vals = {}
                    fields = spec.get("fields", [])
                    for i in range(0, len(fields), 2):          # ช่องเฉพาะหมวด เรียงทีละ 2 ช่อง
                        cols = st.columns(2)
                        for col, (fid, label, kind, opt) in zip(cols, fields[i:i + 2]):
                            if kind == "select":
                                vals[fid] = col.selectbox(label, opt)
                            elif kind == "num":
                                vals[fid] = col.number_input(label, min_value=0.0, step=opt or 1.0)
                            else:
                                vals[fid] = col.text_input(label, placeholder=opt or "")
                    m_party = st.text_input(spec.get("party", "ร้านค้า / ผู้รับเงิน"))
                    m_note = st.text_input("หมายเหตุเพิ่มเติม")
                    if st.form_submit_button(f"เพิ่ม{m_type} · {m_cat}", icon=":material/add:", type="primary",
                                             width="stretch"):
                        kg = vals.get("kg") or None
                        amount = m_amount or ((vals.get("kg") or 0) * (vals.get("price") or 0))
                        if amount <= 0:
                            st.error("กรุณาใส่จำนวนเงิน" + (" หรือใส่น้ำหนักกับราคาต่อกก." if m_cat == "ขายทุเรียน" else ""))
                        else:
                            detail = spec["detail"](vals) if spec.get("detail") else ""
                            ledger.add({"date": m_date, "type": m_type, "category": m_cat, "amount": amount,
                                        "party": m_party, "weight_kg": kg if m_type == INCOME else None,
                                        "note": " · ".join(x for x in [detail, m_note.strip()] if x),
                                        "image_path": None, "source": "manual"})
                            st.toast(f"เพิ่ม{m_cat} {baht(amount)} แล้ว", icon=":material/check_circle:")
                            st.rerun()

    # -------------------------------------------------- รายการ
    with col_list:
        with st.container(key="card-list"):
            card_header("รายการบัญชี", "กรองตามช่วงเวลา ประเภท และหมวดหมู่ · ตารางจะเปลี่ยนตามหมวดที่เลือก")
            if df_tx.empty:
                st.markdown(f'<div class="empty">{icon("inbox")}ยังไม่มีรายการ<br>'
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
                period = df_tx[(df_tx["date"] >= l_start) & (df_tx["date"] <= l_end)]
                view = period if flt in (None, "ทั้งหมด") else period[period["type"] == flt]
                cat_opts = [c for c in dict.fromkeys(INCOME_CATS + EXPENSE_CATS) if c in set(view["category"])]
                cat_pick = st.pills("หมวด", cat_opts, key=f"ledger_cat_{flt}", label_visibility="collapsed",
                                    format_func=lambda c: f":material/{CAT_ICON.get(c, 'more_horiz')}: {c}")
                if cat_pick:
                    view = view[view["category"] == cat_pick]

                # รูปแบบการแสดงผลตามสิ่งที่เลือก: ขายทุเรียน / รายจ่าย / ปนกัน
                types = set(view["type"])
                mode = "sale" if types == {INCOME} else "cost" if types == {EXPENSE} else "mix"
                vs_ = LedgerService.summary(view)
                if mode == "sale":
                    kg_tot = vs_["sold_kg"]
                    stats_row([("รายรับ", baht(vs_["income"])), ("น้ำหนักรวม", f"{kg_tot:,.0f} กก."),
                               ("ราคาเฉลี่ย", f"{vs_['income'] / kg_tot:,.1f} ฿/กก." if kg_tot else "–"),
                               ("ขายไป", f"{vs_['count']} ครั้ง")])
                elif mode == "cost":
                    all_cost = LedgerService.summary(period)["expense"]
                    sold_kg = LedgerService.summary(period)["sold_kg"]
                    stats_row([(f"รวม{cat_pick or 'รายจ่าย'}", baht(vs_["expense"])),
                               ("สัดส่วนของต้นทุนทั้งหมด", f"{vs_['expense'] / all_cost * 100:.0f}%" if all_cost else "–"),
                               ("ต่อกก.ที่ขายได้", f"{vs_['expense'] / sold_kg:,.1f} ฿" if sold_kg else "–"),
                               ("จำนวน", f"{vs_['count']} รายการ")])
                else:
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
                    "จำนวนเงิน": [a if (t == INCOME or mode == "cost") else -a
                                  for a, t in zip(view["amount"], view["type"])],
                    "บาท/กก.": [a / w if t == INCOME and w and not pd.isna(w) else None
                                for a, w, t in zip(view["amount"], view["weight_kg"], view["type"])],
                    "เทียบตลาด": [vs_market(r) for _, r in view.iterrows()],
                }).rename(columns={"type": "ประเภท", "category": "หมวด", "party": "ล้ง/ร้าน",
                                  "weight_kg": "กก.", "note": "หมายเหตุ"})
                if mode == "sale":
                    cols = ["วันที่", "หมวด", "จำนวนเงิน", "กก.", "บาท/กก.", "เทียบตลาด", "ล้ง/ร้าน", "หมายเหตุ"]
                    labels = {"ล้ง/ร้าน": "ล้ง / ผู้ซื้อ", "หมายเหตุ": "เกรด / รายละเอียด"}
                elif mode == "cost":
                    cols = ["วันที่", "หมวด", "จำนวนเงิน", "หมายเหตุ", "ล้ง/ร้าน"]
                    labels = {"ล้ง/ร้าน": "ร้าน / ผู้รับเงิน", "หมายเหตุ": "รายละเอียด"}
                else:
                    cols = ["วันที่", "ประเภท", "หมวด", "จำนวนเงิน", "กก.", "บาท/กก.", "เทียบตลาด", "ล้ง/ร้าน", "หมายเหตุ"]
                    labels = {}

                def fmt(pattern):      # ช่องว่างแสดงเป็น "–" แทนคำว่า None
                    return lambda v: "–" if v is None or pd.isna(v) or v == "" else pattern.format(v)
                table["กก."] = table["กก."].map(fmt("{:,.0f}"))
                table["บาท/กก."] = table["บาท/กก."].map(fmt("{:,.1f}"))
                table["เทียบตลาด"] = table["เทียบตลาด"].map(fmt("{:+.1f}%"))
                table["ล้ง/ร้าน"] = table["ล้ง/ร้าน"].fillna("")
                table["หมายเหตุ"] = table["หมายเหตุ"].fillna("")
                out = table[cols].rename(columns=labels)
                if out.empty:
                    st.markdown(f'<div class="empty">{icon("filter_alt_off")}ไม่มีรายการในช่วงหรือหมวดที่เลือก</div>',
                                unsafe_allow_html=True)
                else:
                    st.dataframe(
                        out, hide_index=True, width="stretch", height=min(430, 40 + 35 * max(len(out), 1)),
                        column_config={
                            "จำนวนเงิน": st.column_config.NumberColumn(
                                "จำนวนเงิน (บาท)" if mode != "cost" else "จ่าย (บาท)", format="localized"),
                            "เทียบตลาด": st.column_config.TextColumn(
                                "เทียบตลาด กทม.",
                                help="ราคาต่อกก.ที่ขายได้ เทียบราคาขายส่งหมอนทอง กทม. สัปดาห์เดียวกัน "
                                     "(ราคาหน้าล้งแยกเกรด อาจต่างจากราคาตลาดได้มาก ใช้ดูเป็นแนวทาง)"),
                        })
                d1, d2 = st.columns(2)
                csv = out.to_csv(index=False).encode("utf-8-sig")   # utf-8-sig ให้ Excel อ่านไทยได้
                fname = f"บัญชีสวน_{cat_pick or (flt if flt not in (None, 'ทั้งหมด') else 'ทั้งหมด')}_{date.today()}.csv"
                d1.download_button("ดาวน์โหลด Excel (CSV)", csv, icon=":material/download:", file_name=fname,
                                   mime="text/csv", width="stretch")
                with d2.popover("ลบรายการ", icon=":material/delete:", width="stretch"):
                    labels = {r["id"]: f"{th_date(r['date'])} · {r['type']} · {r['category']} · {baht(r['amount'])}"
                              for _, r in df_tx.iterrows()}
                    del_id = st.selectbox("เลือกรายการที่จะลบ", list(labels), format_func=labels.get)
                    if st.button("ยืนยันลบ", width="stretch"):
                        row = df_tx[df_tx["id"] == del_id].iloc[0]
                        ledger.delete(del_id, row.get("image_path"))
                        st.toast("ลบแล้ว", icon=":material/delete:")
                        st.rerun()

        if not view.empty:
            st.write("")
            g1, g2 = st.columns(2, gap="medium")
            with g1, st.container(key="card-exp"):
                card_header("รายจ่ายแยกหมวด")
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
                card_header("รายเดือน")
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
                card_header("ให้ AI สรุปบัญชีช่วงนี้", "สรุปกำไร ต้นทุนที่สูง และข้อสังเกต เป็นภาษาง่าย ๆ")
                if st.button("สรุปบัญชีช่วงนี้", icon=":material/auto_awesome:", disabled=gemini is None, width="stretch"):
                    with st.spinner("AI กำลังอ่านบัญชี..."):
                        try:
                            st.session_state.ai_summary = gemini.ask_assistant(
                                "สรุปบัญชีสวนช่วงนี้ให้หน่อย: กำไรเท่าไหร่ ต้นทุนหมวดไหนสูงสุด คิดเป็นกี่ % "
                                "ขายได้เฉลี่ยกก.ละเท่าไหร่ และมีข้อสังเกตอะไรที่ควรระวัง ตอบเป็นข้อ ๆ ไม่เกิน 6 ข้อ",
                                LedgerService.context_text(view, user.get("farm_name", "สวน")) + "\n"
                                + profile_text(farm.get("profile"), LedgerService.summary(view), user.get("farm_name", "")))
                        except Exception as e:   # noqa: BLE001
                            st.session_state.ai_summary = f"**ใช้ AI ไม่ได้:** {ai_error_message(e)}"
                if st.session_state.get("ai_summary"):
                    st.markdown(st.session_state.ai_summary)

    # -------------------------------------------------- คลังรูป
    imgs = df_tx[df_tx["image_path"].notna()] if not df_tx.empty else df_tx
    imgs = imgs[[bool(p) and os.path.exists(p) for p in imgs["image_path"]]] if not imgs.empty else imgs
    if not imgs.empty:
        st.write("")
        with st.container(key="card-gallery"):
            n_img = sum(is_image_path(p) for p in imgs["image_path"])
            card_header("เอกสารที่บันทึกไว้", f"รูป {n_img} ไฟล์ · เอกสารอื่น {len(imgs) - n_img} ไฟล์")
            cols = st.columns(4)
            icons = {".pdf": "picture_as_pdf", ".docx": "description", ".xlsx": "table_view", ".csv": "table_view"}
            for i, (_, r) in enumerate(imgs.iterrows()):
                with cols[i % 4]:
                    path = r["image_path"]
                    if is_image_path(path):
                        st.image(path, width="stretch")
                    else:
                        ext = os.path.splitext(path)[1].lower()
                        st.markdown(f'<div class="doc-tile">{icon(icons.get(ext, "attach_file"))}'
                                    f'<div>{ext[1:].upper()}</div></div>', unsafe_allow_html=True)
                        with open(path, "rb") as fh:
                            st.download_button("เปิดไฟล์", fh.read(), icon=":material/open_in_new:", file_name=os.path.basename(path),
                                               key=f"dl_{r['id']}", width="stretch")
                    color = C_GREEN if r["type"] == INCOME else C_RED
                    st.markdown(f'<div style="font-size:.82rem;margin:-4px 0 14px">{th_date(r["date"])} · '
                                f'<span style="color:{color};font-weight:600">{baht(r["amount"])}</span><br>'
                                f'<span class="muted">{r["party"] or r["category"]}</span></div>',
                                unsafe_allow_html=True)

# ====================================================================== TAB 2: ราคา
with tab_price:
    if forecast_err:
        note(f"อ่านข้อมูลราคาไม่ได้: {forecast_err}", "red")
    else:
        variety = st.segmented_control("พันธุ์", ["หมอนทอง", "ชะนี"], default="หมอนทอง",
                                       label_visibility="collapsed") or "หมอนทอง"
        pc = ForecastService.get_price_card(variety)
        prod = ForecastService._product(variety)
        if pc.get("warning"):
            note(f"{pc['warning']}", "red")

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
                card_header("ราคาขายส่ง กทม. ย้อนหลัง + ช่วงราคาที่คาดไว้",
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
                note(pc["advice"], "sky", ic="lightbulb")

            st.write("")
            with st.container(key="card-years"):
                card_header("เทียบราคาแต่ละปี ช่วงเดียวกันของฤดู",
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
                card_header("ถ้าขายสัปดาห์หน้า จะได้เท่าไหร่?",
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
                            f'<div class="kpi" style="margin-top:10px"><div class="lbl">ราคาคุ้มทุน (ต้นทุน ÷ ผลผลิตทั้งฤดู)</div>'
                            f'<div class="val" style="color:{C_GREEN if good else C_RED}">{be:,.1f} ฿/กก.</div>'
                            f'<div class="sub">ผลผลิตรวม {total_kg:,.0f} กก. · ราคาที่คาดว่าจะได้ {mkt:,.0f} ฿/กก. '
                            f'{"สูงกว่าจุดคุ้มทุน" if good else "ต่ำกว่าจุดคุ้มทุน"}</div></div>',
                            unsafe_allow_html=True)
            st.write("")
            with st.container(key="card-sameweek"):
                sw = prod["same_week_previous_years"]
                card_header("สัปดาห์นี้ในปีก่อน ๆ")
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
        card_header(f"ฝนและอุณหภูมิ ({PROVINCE})",
                    "เลือกช่วงวันที่ดูย้อนหลังได้ถึงปี 2010 · ล่วงหน้าได้ 16 วัน · ข้อมูลจาก Open-Meteo")
        r_start, r_end = date_range_picker("rain", {
            "7 วันก่อน + 14 วันหน้า": (today_ts - pd.Timedelta(days=7), today_ts + pd.Timedelta(days=14)),
            "30 วันที่ผ่านมา": (today_ts - pd.Timedelta(days=30), today_ts),
            "90 วันที่ผ่านมา": (today_ts - pd.Timedelta(days=90), today_ts),
            "1 ปีที่ผ่านมา": (today_ts - pd.DateOffset(years=1), today_ts),
        }, "7 วันก่อน + 14 วันหน้า")
        r_end = min(r_end, today_ts + pd.Timedelta(days=15))
        with st.spinner("กำลังดึงข้อมูลอากาศ..."):
            wx = get_rain(r_start, r_end, FARM_LAT, FARM_LON) if r_start <= r_end else None
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

        fc = get_weather(FARM_LAT, FARM_LON)
        if fc is not None:
            st.markdown('<div class="card-title" style="margin-top:8px">7 วันข้างหน้า</div>'
                        '<div class="card-sub">ความเหมาะสมในการพ่นยาและใส่ปุ๋ย ตามปริมาณฝนที่คาด</div>',
                        unsafe_allow_html=True)
            nxt = fc[fc["period"] == "พยากรณ์"].head(7)
            cols = st.columns(7)
            for c, (_, r) in zip(cols, nxt.iterrows()):
                ic, adv, color = rain_advice(r["rain"])
                c.markdown(
                    f'<div class="day"><div class="d">{THAI_DAYS[r["date"].dayofweek]} {r["date"].day}/{r["date"].month}</div>'
                    f'<div class="i">{icon(ic, style=f"color:{color}")}</div>'
                    f'<div class="r">{(r["rain"] or 0):.0f} มม.</div>'
                    f'<div class="t">{(r["tmin"] or 0):.0f}–{(r["tmax"] or 0):.0f}°C</div>'
                    f'<div class="a" style="color:{color}">{adv}</div></div>',
                    unsafe_allow_html=True)

    st.write("")
    with st.container(key="card-fx"):
        card_header("ค่าเงินหยวน / บาท", "ผู้ซื้อหลักของทุเรียนไทยคือจีน · ข้อมูลอ้างอิง ECB ผ่าน Frankfurter")
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
            note("จากการทดสอบย้อนหลังของทีม ค่าเงินหยวนไม่ได้ช่วยพยากรณ์ราคาทุเรียนรายสัปดาห์อย่างมีนัยสำคัญ "
                 "ใช้ดูเป็นบริบทของตลาดเท่านั้น", "sky")

# ====================================================================== TAB 4: ผู้ช่วย AI
with tab_ai:
    with st.container(key="card-chat"):
        card_header("ผู้ช่วย AI ประจำสวน",
                    "ตอบจากบัญชีของสวนคุณ ราคาและแนวโน้มตลาด อากาศ และคลังความรู้ทุเรียน (กรมวิชาการเกษตร มกษ.) "
                    "· AI อาจผิดพลาดได้ ควรตรวจสอบก่อนตัดสินใจ")
        if gemini_err:
            note(f"ใช้ AI ไม่ได้: {gemini_err}", "red")
        history = st.session_state.setdefault(chat_key, [])

        if not history:
            st.markdown('<div class="muted" style="margin:6px 0 8px">ลองถาม:</div>', unsafe_allow_html=True)
            examples = ["ต้นทุนและกำไรต่อไร่ของสวนเราเท่าไหร่", "ราคาหมอนทองช่วงนี้แนวโน้มเป็นยังไง",
                        "สัปดาห์นี้พ่นยาได้วันไหนบ้าง", "เดือนนี้ต้องทำอะไรในสวนบ้าง",
                        "ใบอ่อนเหี่ยวเหลือง โคนต้นมีน้ำเยิ้ม เป็นอะไร", "เกรด AB กับ C ต่างกันยังไง ทำยังไงให้ได้ AB เยอะ"]
            ex_icons = [":material/payments:", ":material/trending_up:", ":material/water_drop:",
                        ":material/calendar_month:", ":material/eco:", ":material/workspace_premium:"]
            ec = st.columns(3)
            for i, q in enumerate(examples):
                if ec[i % 3].button(q, icon=ex_icons[i], key=f"ex_{i}", width="stretch"):
                    st.session_state.pending_q = q
                    st.rerun()

        for m in history:
            with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/eco:"):
                st.markdown(m["content"])

        q = st.chat_input("พิมพ์คำถาม เช่น ควรขายช่วงไหนดี", disabled=gemini is None)
        q = q or st.session_state.pop("pending_q", None)
        if q:
            history.append({"role": "user", "content": q})
            with st.chat_message("user", avatar=":material/person:"):
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
            prev_q = next((m["content"] for m in reversed(history[:-1]) if m["role"] == "user"), "")
            kb = knowledge_text(q) or knowledge_text(prev_q + " " + q)     # คำถามต่อเนื่องใช้หัวข้อเดิม
            context = (f"วันนี้: {date.today().isoformat()} · สวนอยู่จังหวัด{PROVINCE}\n"
                       f"{LedgerService.context_text(df_tx, user.get('farm_name', 'สวนของผู้ใช้'))}\n"
                       f"{profile_text(farm.get('profile'), summary, user.get('farm_name', ''))}\n\n"
                       f"{fctx}\n{fx_ctx}\n\n{kb}\n\nบทสนทนาก่อนหน้า:\n{recent or '-'}")
            with st.chat_message("assistant", avatar=":material/eco:"):
                with st.spinner("กำลังคิด..."):
                    try:
                        answer = gemini.ask_assistant(q, context)
                    except Exception as e:   # noqa: BLE001
                        answer = f"**ใช้ AI ไม่ได้:** {ai_error_message(e)}"
                st.markdown(answer)
            history.append({"role": "assistant", "content": answer})
            if not st.session_state.get(cur_key):
                st.session_state[cur_key] = chats.new_id()
            chats.save(st.session_state[cur_key], history)     # บันทึกลงประวัติ (แถบด้านข้าง)
            st.rerun()

        if history and st.button("เริ่มแชทใหม่", icon=":material/add_comment:"):
            open_chat(None)
            st.rerun()

# ====================================================================== TAB 5: ตั้งค่า
with tab_set:
    cS1, cS2 = st.columns([1, 1.25], gap="large")
    with cS1, st.container(key="card-farm"):
        card_header("ข้อมูลสวน", "ชื่อสวนและที่ตั้ง ใช้กับพยากรณ์อากาศและผู้ช่วย AI")
        with st.form("farm_form", border=False):
            f_name = st.text_input("ชื่อสวน", value=user.get("farm_name", ""))
            plist = list(PROVINCES) + ["กำหนดพิกัดเอง"]
            f_prov = st.selectbox("จังหวัด", plist, index=plist.index(PROVINCE) if PROVINCE in plist else len(plist) - 1)
            c1, c2 = st.columns(2)
            f_lat = c1.number_input("ละติจูด", value=float(FARM_LAT), format="%.4f",
                                    help="ใช้เมื่อเลือก 'กำหนดพิกัดเอง' (ดูจาก Google Maps: กดค้างที่สวน)")
            f_lon = c2.number_input("ลองจิจูด", value=float(FARM_LON), format="%.4f")
            prof = farm.get("profile", {})
            st.markdown('<div class="pick-label" style="margin-top:10px"><b>ขนาดสวน</b> · ให้ผู้ช่วย AI คำนวณต้นทุน '
                        'ผลผลิต และกำไรต่อไร่/ต่อต้นได้</div>', unsafe_allow_html=True)
            p1, p2 = st.columns(2)
            f_rai = p1.number_input("พื้นที่ (ไร่)", min_value=0.0, value=float(prof.get("rai") or 0), step=1.0)
            f_trees = p2.number_input("จำนวนต้น", min_value=0, value=int(prof.get("trees") or 0), step=10)
            p3, p4 = st.columns(2)
            f_age = p3.number_input("อายุต้นโดยประมาณ (ปี)", min_value=0, value=int(prof.get("tree_age") or 0), step=1)
            vlist = VARIETIES
            f_var = p4.selectbox("พันธุ์หลัก", vlist, index=vlist.index(prof.get("variety")) if prof.get("variety") in vlist else 0)
            if st.form_submit_button("บันทึกข้อมูลสวน", icon=":material/save:", type="primary", width="stretch"):
                lat, lon = (f_lat, f_lon) if f_prov == "กำหนดพิกัดเอง" else PROVINCES[f_prov]
                settings.save_farm(f_name.strip() or "สวนของฉัน", f_prov, lat, lon,
                                   profile={"rai": float(f_rai), "trees": int(f_trees), "tree_age": int(f_age),
                                            "variety": f_var})
                st.session_state.user = {**user, "farm_name": f_name.strip() or "สวนของฉัน"}
                st.toast("บันทึกข้อมูลสวนแล้ว", icon=":material/check_circle:")
                st.rerun()
        st.caption(f"พิกัดที่ใช้อยู่: {FARM_LAT:.4f}, {FARM_LON:.4f}")

    with cS2, st.container(key="card-apikey"):
        card_header("API key ของ AI",
                    "ใส่ key ของคุณเองได้ ถ้าใส่แล้วระบบจะใช้ key ของคุณแทน key ของระบบ")
        ai = farm["ai"]
        if user_keys:
            note("ตอนนี้ใช้ <b>API key ของคุณ</b>", "ok")
        elif gemini is not None:
            note("ตอนนี้ใช้ <b>AI ของระบบ</b> — ใส่ key ของคุณเองเพื่อใช้โควตาของคุณ", "sky")
        else:
            note("ยังไม่มี API key — ใส่ Gemini API key ด้านล่าง (สร้างฟรีได้ใน 1 นาที) แล้วกดบันทึก", "gold")
        if not can_persist_keys():
            note("ระบบเข้ารหัสไม่พร้อม (ติดตั้ง cryptography) — key ที่ใส่จะถูกจำไว้แค่จนกว่าจะออกจากระบบ", "gold")

        with st.form("ai_form", border=False):
            st.markdown("**Gemini (ตัวหลัก — แนะนำ)** · สร้าง key ฟรีที่ [Google AI Studio](https://aistudio.google.com/apikey)")
            k_gem = st.text_input("Gemini API key", type="password", placeholder=mask(ai.get("gemini_key")) or "AIza...",
                                  help="เว้นว่างไว้ = ใช้ค่าเดิม")
            k_model = st.text_input("รุ่น Gemini (ไม่บังคับ)", value=ai.get("gemini_model", ""),
                                    placeholder="เว้นว่าง = ใช้รุ่นมาตรฐานของระบบ")
            st.markdown("**Groq (สำรอง ไม่บังคับ)** · สร้าง key ที่ [console.groq.com](https://console.groq.com/keys)")
            k_groq = st.text_input("Groq API key", type="password", placeholder=mask(ai.get("groq_key")) or "gsk_...")
            with st.expander("Azure OpenAI (สำรอง ไม่บังคับ)"):
                k_az_ep = st.text_input("Endpoint", value=ai.get("azure_endpoint", ""),
                                        placeholder="https://<ชื่อ-resource>.openai.azure.com")
                k_az_key = st.text_input("Azure API key", type="password", placeholder=mask(ai.get("azure_key")))
                k_az_dep = st.text_input("ชื่อ Deployment", value=ai.get("azure_deployment", ""))
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("บันทึก key", icon=":material/save:", type="primary", width="stretch")
            test = b2.form_submit_button("ทดสอบการเชื่อมต่อ", icon=":material/network_check:", width="stretch")

        new_ai = {"gemini_key": k_gem or ai.get("gemini_key", ""), "gemini_model": k_model,
                  "groq_key": k_groq or ai.get("groq_key", ""), "azure_endpoint": k_az_ep,
                  "azure_key": k_az_key or ai.get("azure_key", ""), "azure_deployment": k_az_dep}
        if save:
            kept = settings.save_ai(new_ai)
            get_gemini.clear()
            st.toast("บันทึก key แล้ว" + ("" if kept else " (จำไว้จนกว่าจะออกจากระบบ)"), icon=":material/key:")
            st.rerun()
        if test:
            keys = {k: v for k, v in new_ai.items() if v}
            if not keys.get("gemini_key") and not keys.get("groq_key") and not keys.get("azure_key"):
                note("ยังไม่ได้กรอก key ให้ทดสอบ", "gold")
            else:
                with st.spinner("กำลังทดสอบ..."):
                    try:
                        results = GeminiService(keys).test_connections()
                    except Exception as e:   # noqa: BLE001
                        results = [("การตั้งค่า", False, str(e)[:150], 0)]
                for name, ok, msg, sec in results:
                    note(f"<b>{name}</b> — {msg} ({sec:.1f} วินาที)", "ok" if ok else "red")

        if user_keys:
            with st.popover("ลบ key ของฉัน", icon=":material/delete:", width="stretch"):
                st.caption("ลบแล้วจะกลับไปใช้ AI ของระบบ (ถ้าระบบอนุญาต)")
                if st.button("ยืนยันลบ key", width="stretch"):
                    settings.clear_ai()
                    get_gemini.clear()
                    st.rerun()
        st.caption(("key ถูกเข้ารหัสก่อนเก็บในฐานข้อมูล และไม่แสดงเต็มบนหน้าจอ · " if can_persist_keys() else
                    "key ไม่ถูกบันทึกลงฐานข้อมูล และไม่แสดงเต็มบนหน้าจอ · ")
                   + "ค่าใช้จ่ายการเรียก AI จะคิดกับบัญชีเจ้าของ key")

# ---------------------------------------------------------------- สลับไปแท็บที่ต้องการ (เช่น เปิดแชทจากแถบด้านข้าง)
_goto = st.session_state.pop("goto_tab", None)
if _goto is not None:
    st.html(f"""<script>(() => {{
      let n = 0; const t = setInterval(() => {{
        const tab = document.querySelectorAll('[data-testid="stTab"]')[{_goto}];
        if (tab || ++n > 60) {{ clearInterval(t); if (tab) ['pointerdown','mousedown','pointerup','mouseup','click']
          .forEach(tp => tab.dispatchEvent(new (tp.startsWith('pointer') ? PointerEvent : MouseEvent)(tp,
            {{bubbles: true, cancelable: true, view: window, button: 0, pointerId: 1, pointerType: 'mouse', isPrimary: true}}))); }}
      }}, 50); }})(); /* {pd.Timestamp.now().value} */</script>""", unsafe_allow_javascript=True)
