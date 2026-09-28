import streamlit as st
from PIL import Image
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import requests
import json
import os
import uuid
from pathlib import Path
import altair as alt
import locale

# นำเข้าบริการสำหรับ Gemini และ Forecast
from gemini_service import GeminiService
from forecast_service import ForecastService

# โหลด environment variables
load_dotenv()

# ตั้งค่า Locale ภาษาไทย
try:
    locale.setlocale(locale.LC_TIME, 'th_TH.UTF-8')
except Exception:
    try:
        locale.setlocale(locale.LC_TIME, 'thai')
    except Exception:
        pass

# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def format_th_date(date_str, short_month=True):
    if not date_str or date_str == "-":
        return "-"
    try:
        dt = pd.to_datetime(date_str)
        year_th = dt.year + 543
        if short_month:
            months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
            return f"{dt.day} {months[dt.month - 1]} {year_th}"
        else:
            return f"{dt.day:02d}/{dt.month:02d}/{year_th}"
    except Exception:
        return date_str

def get_user_upload_dir(user_email):
    """สร้างและคืนค่า path โฟลเดอร์สำหรับเก็บรูปภาพของ user แต่ละคน"""
    clean_email = user_email.replace("@", "_").replace(".", "_")
    user_dir = Path("uploads") / clean_email
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

def save_uploaded_image(uploaded_file, user_email):
    """บันทึกไฟล์รูปภาพลงโฟลเดอร์ของ user"""
    user_dir = get_user_upload_dir(user_email)
    file_ext = Path(uploaded_file.name).suffix
    unique_filename = f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{file_ext}"
    file_path = user_dir / unique_filename
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    return str(file_path)

@st.cache_data(ttl=3600)
def get_cny_thb_rates():
    latest_url = os.getenv("FRANKFURTER_LATEST_URL", "https://api.frankfurter.dev/v1/latest?base=CNY&symbols=THB")
    history_url = os.getenv("FRANKFURTER_HISTORICAL_URL", "https://api.frankfurter.dev/v1/2026-08-28..?base=CNY&symbols=THB")
    
    latest_rate = 4.9670
    history_df = pd.DataFrame()
    change_pct = 0.0
    
    try:
        res_latest = requests.get(latest_url, timeout=5).json()
        latest_rate = res_latest['rates']['THB']
    except Exception as e:
        st.warning(f"⚠️ ไม่สามารถเชื่อมต่อ Frankfurter API (Latest) ได้: {e}")

    try:
        res_hist = requests.get(history_url, timeout=5).json()
        rates_dict = res_hist.get('rates', {})
        
        data_list = []
        for date_str, rates_info in rates_dict.items():
            if 'THB' in rates_info:
                data_list.append({"Date": pd.to_datetime(date_str), "CNY_THB": float(rates_info['THB'])})
                
        if data_list:
            history_df = pd.DataFrame(data_list).sort_values("Date").reset_index(drop=True)
            first_rate = history_df["CNY_THB"].iloc[0]
            last_rate = history_df["CNY_THB"].iloc[-1]
            change_pct = ((last_rate - first_rate) / first_rate) * 100
    except Exception as e:
        st.warning(f"⚠️ ไม่สามารถเชื่อมต่อ Frankfurter API (History) ได้: {e}")

    return latest_rate, history_df, change_pct

@st.cache_data(ttl=3600)
def get_historical_weather_easy(days=14):
    end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=days-1)).strftime('%Y-%m-%d')
    
    base_url = os.getenv("OPEN_METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive")
    url = f"{base_url}?latitude=12.61&longitude=102.10&start_date={start_date}&end_date={end_date}&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=Asia/Bangkok"
    
    try:
        res = requests.get(url, timeout=5).json()
        daily = res['daily']
        df = pd.DataFrame({
            "date": daily['time'],
            "rain_mm": daily['precipitation_sum'],
            "temp_max": daily['temperature_2m_max'],
            "temp_min": daily['temperature_2m_min']
        })
    except Exception:
        dates = pd.date_range(end=pd.Timestamp.now(), periods=days).strftime('%Y-%m-%d')
        df = pd.DataFrame({
            "date": dates,
            "rain_mm": [0.0, 2.5, 15.0, 0.0, 42.0, 5.0, 0.0] * 2,
            "temp_max": [33.0]*days,
            "temp_min": [24.0]*days
        })

    def get_rain_status(rain):
        if rain == 0:
            return "☀️ ปลอดฝน / แดดจัด", "สภาพอากาศเหมาะแก่การพ่นยาและเก็บเกี่ยว", "#22c55e"
        elif rain < 10:
            return "🌦️ ฝนตกเล็กน้อย", "ปริมาณฝนสะสมต่ำ ไม่กระทบการทำสวน", "#38bdf8"
        elif rain <= 35:
            return "🌧️ ฝนตกปานกลาง", "ควรชะลอการฉีดพ่นสารเคมีและตรวจวัดความชื้น", "#facc15"
        else:
            return "⛈️ ฝนตกหนัก", "⚠️ ระวังน้ำขังสะสมในบริเวณแปลงปลูก", "#ef4444"

    statuses = [get_rain_status(r) for r in df['rain_mm']]
    df['status_label'] = [s[0] for s in statuses]
    df['advice'] = [s[1] for s in statuses]
    df['color'] = [s[2] for s in statuses]
    
    thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
    formatted_dates = []
    for d in df['date']:
        dt = pd.to_datetime(d)
        formatted_dates.append(f"วัน{thai_days[dt.dayofweek]}ที่ {format_th_date(d)}")
    df['date_th'] = formatted_dates
    
    return df

# ---------------------------------------------------------
# 1. Session State
# ---------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None

if "transactions" not in st.session_state:
    st.session_state.transactions = [
        {"id": "1", "date": "2026-09-20", "type": "รายรับ", "category": "ขายทุเรียน AB", "amount": 145000.0, "note": "ล้งเจ๊พร", "image_path": None},
        {"id": "2", "date": "2026-09-22", "type": "รายจ่าย", "category": "ค่าปุ๋ย/ยา", "amount": 18500.0, "note": "ปุ๋ยบำรุงต้น", "image_path": None},
        {"id": "3", "date": "2026-09-25", "type": "รายรับ", "category": "ขายทุเรียน C/ตกไซส์", "amount": 32000.0, "note": "เหมาสวน", "image_path": None}
    ]

is_logged_in = st.session_state.user is not None

st.set_page_config(
    page_title="RMA Durian | Management System",
    page_icon="🍈",
    layout="wide" if is_logged_in else "centered",
    initial_sidebar_state="expanded" if is_logged_in else "collapsed"
)

# ---------------------------------------------------------
# 2. Styling
# ---------------------------------------------------------
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
    html, body, .stMarkdown, p, h1, h2, h3, h4, h5, h6, label {
        font-family: 'Prompt', 'Plus Jakarta Sans', sans-serif !important;
        line-height: 1.6;
    }
    button[data-testid="stSidebarCollapseButton"], [data-testid="collapsedControl"] { display: none !important; }
    .stApp {
        background-color: #060b08;
        background-image: 
            radial-gradient(circle at 15% 15%, rgba(34, 197, 94, 0.12) 0%, transparent 40%),
            radial-gradient(circle at 85% 20%, rgba(234, 179, 8, 0.08) 0%, transparent 45%),
            radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.06) 0%, transparent 50%);
        background-attachment: fixed;
        color: #f1f5f9;
    }
    .block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; }
    [data-testid="stSidebar"] {
        background: rgba(11, 20, 14, 0.85) !important;
        backdrop-filter: blur(24px);
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }
    .curved-card {
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 24px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 16px 40px -10px rgba(0, 0, 0, 0.5);
    }
    .pill-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 16px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 500;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .badge-green { background: rgba(34, 197, 94, 0.12); color: #4ade80; border-color: rgba(74, 222, 128, 0.3); }
    .stButton>button {
        border-radius: 9999px !important;
        background: linear-gradient(135deg, #22c55e 0%, #15803d 100%) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        padding: 10px 28px !important;
        border: none !important;
    }
    .demo-btn > button {
        background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%) !important;
        color: #000000 !important;
        font-weight: 700 !important;
        box-shadow: 0 8px 20px -4px rgba(234, 179, 8, 0.4) !important;
    }
    #MainMenu, footer {visibility: hidden;}
    header {background: transparent !important;}
</style>""", unsafe_allow_html=True)

gemini_service = GeminiService()

# Login Gateway
if not is_logged_in:
    st.markdown("""<style>[data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; } .block-container { max-width: 480px !important; }</style>""", unsafe_allow_html=True)
    with st.container():
        st.markdown(
            '<div class="curved-card" style="text-align: center; padding: 32px 28px 20px 28px;">'
            '<div style="background: rgba(34,197,94,0.15); width: 60px; height: 60px; border-radius: 18px; display: inline-flex; align-items: center; justify-content: center; font-size: 1.7rem; margin-bottom: 14px;">🍈</div>'
            '<h2 style="font-size: 1.75rem; font-weight: 700; margin: 0; color: #f8fafc;">DurianOS Enterprise</h2>'
            '<p style="color: #94a3b8; font-size: 0.85rem; margin-top: 8px; margin-bottom: 0;">ระบบจัดการสวนทุเรียนและวิเคราะห์ราคาอัจฉริยะ</p>'
            '</div>', unsafe_allow_html=True
        )
        st.markdown('<div class="demo-btn">', unsafe_allow_html=True)
        if st.button("🚀 ทดลองใช้งานทันที (Demo Mode)", use_container_width=True):
            st.session_state.user = {"email": "demo_farmer@durianos.com", "farm_name": "สวนทุเรียนสาธิต (จันทบุรี)"}
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div style="text-align: center; margin: 16px 0; color: #64748b; font-size: 0.8rem;">──────── หรือเข้าสู่ระบบด้วยบัญชี ────────</div>', unsafe_allow_html=True)
        email_input = st.text_input("อีเมลผู้ใช้งาน", value="farmer@durianos.com")
        pwd_input = st.text_input("รหัสผ่าน", type="password", value="password123")
        if st.button("🔐 เข้าสู่ระบบ", use_container_width=True):
            st.session_state.user = {"email": email_input if email_input else "farmer@durianos.com", "farm_name": "สวนทุเรียนทรัพย์อนันต์ (จันทบุรี)"}
            st.rerun()
    st.stop()

# Dashboard View
st.markdown("""<style>.block-container { max-width: 100% !important; padding-top: 2rem !important; }</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px;"><span style="font-size: 1.5rem;">🍈</span><span style="font-weight: 700; font-size: 1.1rem; color: #f8fafc;">DurianOS Panel</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 14px; margin-bottom: 20px;"><div style="color: #64748b; font-size: 0.75rem;">ผู้ใช้งาน</div><div style="font-weight: 600; color: #f1f5f9; font-size: 0.9rem;">{st.session_state.user["email"]}</div><div style="color: #4ade80; font-size: 0.8rem; margin-top: 4px;">🏡 {st.session_state.user.get("farm_name", "-")}</div></div>', unsafe_allow_html=True)
    if st.button("🚪 ออกจากระบบ", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# Financial Calculation
df_trans = pd.DataFrame(st.session_state.transactions)
total_income = df_trans[df_trans['type'] == 'รายรับ']['amount'].sum() if not df_trans.empty else 0
total_expense = df_trans[df_trans['type'] == 'รายจ่าย']['amount'].sum() if not df_trans.empty else 0
net_profit = total_income - total_expense

cny_latest, cny_df, cny_change_pct = get_cny_thb_rates()

# HEADER SUMMARY
st.markdown(
    f'<div class="curved-card" style="padding: 20px 28px; margin-bottom: 20px;">'
    f'<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">'
    f'<div><span class="pill-badge badge-green">ภาพรวมสวนทุเรียน</span><h2 style="margin: 8px 0 0 0; font-weight: 700;">แดชบอร์ดหลัก & ดัชนีการเงิน</h2></div>'
    f'<div style="display: flex; gap: 20px; flex-wrap: wrap;">'
    f'<div><div style="font-size: 0.8rem; color: #94a3b8;">รายรับรวม</div><div style="font-size: 1.25rem; font-weight: 700; color: #4ade80;">฿{total_income:,.2f}</div></div>'
    f'<div><div style="font-size: 0.8rem; color: #94a3b8;">รายจ่ายรวม</div><div style="font-size: 1.25rem; font-weight: 700; color: #ef4444;">฿{total_expense:,.2f}</div></div>'
    f'<div style="border-left: 1px solid rgba(255,255,255,0.1); padding-left: 16px;"><div style="font-size: 0.8rem; color: #94a3b8;">กำไรสุทธิ</div><div style="font-size: 1.25rem; font-weight: 700; color: {"#facc15" if net_profit>=0 else "#f87171"};">฿{net_profit:,.2f}</div></div>'
    f'</div></div></div>',
    unsafe_allow_html=True
)

# 💱 วิเคราะห์ CNY/THB
st.markdown(
    '<div class="curved-card">'
    '<h3>💱 วิเคราะห์ดัชนีอัตราแลกเปลี่ยนเงินหยวน (CNY / THB)</h3>'
    '<p style="color: #94a3b8; font-size: 0.85rem;">ติดตามค่าเงินหยวนแบบเรียลไทม์เพื่อประเมินการต่อรองราคาหน้าล้งส่งออก</p>',
    unsafe_allow_html=True
)

col_cny_a, col_cny_b = st.columns([1, 2], gap="large")

with col_cny_a:
    cny_color = "#4ade80" if cny_change_pct >= 0 else "#f87171"
    cny_sign = "+" if cny_change_pct >= 0 else ""
    st.markdown(
        f'<div style="background: rgba(255,255,255,0.03); border-radius: 16px; padding: 20px; border: 1px solid rgba(255,255,255,0.08); text-align: center;">'
        f'<div style="color: #94a3b8; font-size: 0.85rem;">อัตราแลกเปลี่ยนปัจจุบัน</div>'
        f'<div style="font-size: 2.2rem; font-weight: 700; color: #f1f5f9; margin: 4px 0;">1 CNY = {cny_latest:.4f} <span style="font-size: 1rem; color: #94a3b8;">THB</span></div>'
        f'<div style="font-size: 0.85rem; color: {cny_color}; font-weight: 600;">การเปลี่ยนแปลงสะสม: {cny_sign}{cny_change_pct:.2f}%</div>'
        f'</div>',
        unsafe_allow_html=True
    )
    
    if cny_change_pct > 0.5:
        FX_impact = "🟢 **หยวนแข็งค่า:** ล้งจีนมีกำลังซื้อสูงขึ้น มีโอกาสปรับราคารับซื้อขึ้น"
    elif cny_change_pct < -0.5:
        FX_impact = "🔴 **หยวนอ่อนค่า:** ต้นทุนนำเข้าจีนสูงขึ้น ล้งอาจชะลอการเสนอราคา"
    else:
        FX_impact = "🟡 **ค่าเงินทรงตัว:** ไม่ส่งผลกระทบต่อราคารับซื้ออย่างผันผวน"
        
    st.markdown(
        f'<div style="margin-top: 12px; background: rgba(56, 189, 248, 0.08); padding: 12px; border-radius: 12px; border-left: 3px solid #38bdf8; font-size: 0.82rem; color: #e0f2fe;">'
        f'📊 <b>ผลกระทบงานส่งออก:</b><br>{FX_impact}'
        f'</div>',
        unsafe_allow_html=True
    )

with col_cny_b:
    if not cny_df.empty:
        st.markdown('<div style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 8px;">📈 ความเคลื่อนไหวอัตราแลกเปลี่ยน:</div>', unsafe_allow_html=True)
        min_val = cny_df["CNY_THB"].min() - 0.02
        max_val = cny_df["CNY_THB"].max() + 0.02
        
        cny_chart = alt.Chart(cny_df).mark_line(color='#38bdf8', strokeWidth=2.5).encode(
            x=alt.X('Date:T', title='วันที่', axis=alt.Axis(format='%d %b', labelAngle=-45)),
            y=alt.Y('CNY_THB:Q', title='บาท/หยวน', scale=alt.Scale(domain=[min_val, max_val])),
            tooltip=['Date:T', 'CNY_THB:Q']
        ).properties(height=200).interactive()
        
        st.altair_chart(cny_chart, use_container_width=True)
    else:
        st.info("กำลังโหลดข้อมูลกราฟอัตราแลกเปลี่ยน...")

st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------
# Tabs Navigation
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "🧾 สแกนบิล/ใบชั่ง & บัญชีสวน",
    "📈 พยากรณ์ราคา & สภาพอากาศย้อนหลัง",
    "🤖 ผู้ช่วย AI ถามตอบ"
])

# ----------------- TAB 1: สแกนบิล + บันทึกบัญชี + คลังรูปภาพ -----------------
with tab1:
    col_scan, col_acc = st.columns([1, 1.2], gap="large")
    
    with col_scan:
        st.markdown(
            '<div class="curved-card">'
            '<h3>📷 1. อัปโหลดบิล/ใบชั่ง (Gemini OCR)</h3>'
            '<p style="color: #94a3b8; font-size: 0.85rem;">ถ่ายหรืออัปโหลดรูปบิลเพื่ออ่านข้อมูลและบันทึกภาพลงโฟลเดอร์ผู้ใช้</p>',
            unsafe_allow_html=True
        )
        
        # ตรวจสอบว่ามี API Key หรือยัง
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == "your_gemini_api_key_here":
            st.error("⚠️ **ยังไม่ได้ระบุ GEMINI_API_KEY ที่ถูกต้องในไฟล์ `.env`** โปรดนำ Key จาก Google AI Studio มาใส่ก่อนใช้งาน OCR")

        uploaded_file = st.file_uploader("เลือกรูปภาพบิล", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
        
        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, use_container_width=True, caption="รูปภาพที่เลือก")
            
            if st.button("✨ อ่านข้อมูลบิล & บันทึกเข้าบัญชี", use_container_width=True):
                with st.spinner("🤖 บันทึกรูปภาพและให้ Gemini อ่านข้อมูลบิล..."):
                    try:
                        # 1. บันทึกรูปภาพลงโฟลเดอร์ของผู้ใช้
                        user_email = st.session_state.user["email"]
                        saved_img_path = save_uploaded_image(uploaded_file, user_email)
                        
                        # 2. อ่านข้อมูลบิลด้วย Gemini OCR
                        result = gemini_service.extract_receipt(image)
                        grand_total = float(result.get("grand_total", 0))
                        buyer = result.get("buyer_name", "ล้งรับซื้อ")
                        
                        # 3. บันทึกรายการเข้า Session State
                        new_entry = {
                            "id": uuid.uuid4().hex[:8],
                            "date": pd.Timestamp.now().strftime('%Y-%m-%d'),
                            "type": "รายรับ",
                            "category": "ขายทุเรียน (สแกนบิล)",
                            "amount": grand_total,
                            "note": f"ขายให้ {buyer}",
                            "image_path": saved_img_path
                        }
                        st.session_state.transactions.append(new_entry)
                        st.success(f"✅ บันทึกสำเร็จ! เพิ่มรายรับ ฿{grand_total:,.2f} จาก {buyer}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาดในการอ่านข้อมูล: {e}")

        st.markdown('</div>', unsafe_allow_html=True)

    with col_acc:
        st.markdown('<div class="curved-card"><h3>📊 2. บันทึกรายรับ-รายจ่ายสวน</h3>', unsafe_allow_html=True)
        
        # แสดงตารางบัญชี
        df_display = pd.DataFrame(st.session_state.transactions)
        if not df_display.empty:
            st.dataframe(
                df_display[['date', 'type', 'category', 'amount', 'note']],
                use_container_width=True,
                column_config={
                    "date": "วันที่",
                    "type": "ประเภท",
                    "category": "หมวดหมู่",
                    "amount": st.column_config.NumberColumn("จำนวนเงิน (บาท)", format="฿%.2f"),
                    "note": "หมายเหตุ"
                }
            )
        else:
            st.info("ยังไม่มีรายการบันทึก")
        st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # 🖼️ ส่วนแสดงคลังรูปภาพบิลของผู้ใช้และการจัดการลบ
    # ---------------------------------------------------------
    st.markdown(
        '<div class="curved-card">'
        '<h3>📁 คลังรูปภาพบิลของคุณ (Gallery & Management)</h3>'
        '<p style="color: #94a3b8; font-size: 0.85rem;">แสดงรูปภาพบิลทั้งหมดที่บันทึกไว้ในบัญชีของคุณ สามารถดูรูปใหญ่หรือกดลบออกได้</p>',
        unsafe_allow_html=True
    )

    # ดึงเฉพาะรายการที่มีรูปภาพ
    img_items = [t for t in st.session_state.transactions if t.get("image_path") and os.path.exists(t["image_path"])]

    if img_items:
        cols_per_row = 3
        grid_cols = st.columns(cols_per_row)
        
        for idx, item in enumerate(img_items):
            col = grid_cols[idx % cols_per_row]
            with col:
                st.markdown(
                    f'<div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 12px; margin-bottom: 12px;">',
                    unsafe_allow_html=True
                )
                st.image(item["image_path"], use_container_width=True)
                st.markdown(f"**วันที่:** {format_th_date(item['date'])}")
                st.markdown(f"**จำนวนเงิน:** ฿{item['amount']:,.2f}")
                st.markdown(f"**หมายเหตุ:** {item['note']}")
                
                # ปุ่มลบรูปและรายการ
                if st.button(f"🗑️ ลบรูปภาพนี้", key=f"del_{item['id']}", use_container_width=True):
                    # 1. ลบไฟล์จริงในเครื่อง
                    if item["image_path"] and os.path.exists(item["image_path"]):
                        try:
                            os.remove(item["image_path"])
                        except Exception as ex:
                            st.error(f"ไม่สามารถลบไฟล์ภาพได้: {ex}")

                    # 2. ลบออกจาก Session State
                    st.session_state.transactions = [t for t in st.session_state.transactions if t.get("id") != item["id"]]
                    st.success("ลบรูปภาพและรายการเรียบร้อยแล้ว!")
                    st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("💡 ยังไม่มีรูปภาพบิลที่ถูกบันทึกในระบบ ลองอัปโหลดบิลในช่องด้านบนได้เลยครับ")

    st.markdown('</div>', unsafe_allow_html=True)

# ----------------- TAB 2 & TAB 3 คงเดิมตามโครงสร้างโปรแกรม -----------------
with tab2:
    try:
        price_card = ForecastService.get_price_card("หมอนทอง")
        as_of_th = format_th_date(price_card['as_of'])
        st.caption(f"🟢 **สถานะการเชื่อมต่อ:** อ่านข้อมูลจาก `forecast/outputs/forecast.json` สำเร็จ (อัปเดตสัปดาห์: **{as_of_th}**)")
    except Exception as e:
        st.error(f"⚠️ **ไม่สามารถอ่านข้อมูลราคาพยากรณ์ได้:** {e}")
        price_card = {
            "price_now": 110, "as_of": "2026-09-27", 
            "advice": "ราคาอาจทรงตัวหรือลดลงเล็กน้อย ตัดสินใจตามความแก่ของผลเป็นหลัก",
            "next_week_low": 100.8, "next_week_high": 119.2
        }

    col_fc1, col_fc2 = st.columns(2, gap="large")

    with col_fc1:
        current_price = price_card["price_now"]
        advice_msg = price_card["advice"]
        base_date = pd.to_datetime(price_card.get('as_of', '2026-09-27')).date()

        st.markdown(
            '<div class="curved-card">'
            '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">'
            '<h3 style="margin: 0;">💰 แนวโน้มและพยากรณ์ราคา</h3>'
            f'<span style="background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600;">🔥 ราคาปัจจุบัน {current_price:.0f} ฿</span>'
            '</div>',
            unsafe_allow_html=True
        )

        col_preset, col_picker = st.columns([1.2, 1], gap="small")
        
        with col_preset:
            time_preset = st.selectbox(
                "📅 ช่วงเวลารวดเร็ว (ภาษาไทย):",
                options=[
                    "ย้อนหลัง 2 สัปดาห์ - อนาคต 1 เดือน",
                    "ย้อนหลัง 1 สัปดาห์",
                    "ย้อนหลัง 1 เดือน",
                    "ย้อนหลัง 3 เดือน",
                    "ย้อนหลัง 6 เดือน",
                    "ย้อนหลัง 1 ปี",
                    "พยากรณ์อนาคต 1 เดือน",
                    "ระบุช่วงวันเองในปฏิทิน"
                ],
                index=0
            )

        if time_preset == "ย้อนหลัง 1 สัปดาห์":
            preset_start = base_date - pd.Timedelta(weeks=1)
            preset_end = base_date
        elif time_preset == "ย้อนหลัง 1 เดือน":
            preset_start = base_date - pd.Timedelta(days=30)
            preset_end = base_date
        elif time_preset == "ย้อนหลัง 3 เดือน":
            preset_start = base_date - pd.Timedelta(days=90)
            preset_end = base_date
        elif time_preset == "ย้อนหลัง 6 เดือน":
            preset_start = base_date - pd.Timedelta(days=180)
            preset_end = base_date
        elif time_preset == "ย้อนหลัง 1 ปี":
            preset_start = base_date - pd.Timedelta(days=365)
            preset_end = base_date
        elif time_preset == "พยากรณ์อนาคต 1 เดือน":
            preset_start = base_date
            preset_end = base_date + pd.Timedelta(days=30)
        else:
            preset_start = base_date - pd.Timedelta(weeks=2)
            preset_end = base_date + pd.Timedelta(weeks=4)

        with col_picker:
            selected_dates = st.date_input(
                "เลือกวันจากปฏิทิน:",
                value=(preset_start, preset_end),
                format="DD/MM/YYYY"
            )

        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            start_date, end_date = selected_dates
        else:
            start_date, end_date = preset_start, preset_end

        date_range = pd.date_range(start=start_date, end=end_date, freq='W-SUN')
        if len(date_range) < 2:
            date_range = pd.date_range(start=start_date, end=end_date, freq='D')

        forecast_dynamic = []
        for dt in date_range:
            d_date = dt.date()
            diff_weeks = (d_date - base_date).days / 7.0
            
            if d_date < base_date:
                sim_price = current_price * (1.0 - (diff_weeks * 0.02) + np.sin(diff_weeks) * 0.03)
                label_type = "อดีต"
            elif d_date == base_date:
                sim_price = current_price
                label_type = "ปัจจุบัน"
            else:
                sim_price = current_price * (1.0 + (diff_weeks * 0.015) - (diff_weeks**2 * 0.003))
                label_type = "พยากรณ์"

            forecast_dynamic.append({
                "date": d_date,
                "date_str": format_th_date(d_date.strftime('%Y-%m-%d'), short_month=True),
                "price": round(sim_price, 1),
                "type": label_type
            })

        df_price_forecast = pd.DataFrame(forecast_dynamic)

        p_min = df_price_forecast["price"].min() - 5
        p_max = df_price_forecast["price"].max() + 5

        line_chart = alt.Chart(df_price_forecast).mark_line(color='#4ade80', strokeWidth=3, interpolate='monotone').encode(
            x=alt.X('date_str:N', title='วันที่', sort=None, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y('price:Q', title='ราคา (บาท/กก.)', scale=alt.Scale(domain=[p_min, p_max])),
            tooltip=[
                alt.Tooltip('date_str:N', title='วันที่'),
                alt.Tooltip('price:Q', title='ราคา (บาท/กก.)'),
                alt.Tooltip('type:N', title='สถานะ')
            ]
        )

        points = alt.Chart(df_price_forecast).mark_circle(size=70).encode(
            x=alt.X('date_str:N', sort=None),
            y=alt.Y('price:Q'),
            color=alt.Color('type:N', scale=alt.Scale(
                domain=['อดีต', 'ปัจจุบัน', 'พยากรณ์'],
                range=['#94a3b8', '#facc15', '#22c55e']
            ), legend=alt.Legend(title="ประเภท")),
            tooltip=[
                alt.Tooltip('date_str:N', title='วันที่'),
                alt.Tooltip('price:Q', title='ราคา (บาท/กก.)'),
                alt.Tooltip('type:N', title='สถานะ')
            ]
        )

        text = alt.Chart(df_price_forecast).mark_text(align='center', baseline='bottom', dy=-10, color='#ffffff', fontSize=11, fontWeight='bold').encode(
            x=alt.X('date_str:N', sort=None),
            y=alt.Y('price:Q'),
            text=alt.Text('price:Q', format='.0f')
        )

        price_chart = (line_chart + points + text).properties(height=230).interactive()
        st.altair_chart(price_chart, use_container_width=True)

        st.markdown(
            f'<div style="margin-top: 10px; background: rgba(234, 179, 8, 0.1); padding: 10px 14px; border-radius: 10px; border-left: 3px solid #facc15; font-size: 0.82rem; color: #fef08a;">'
            f'💡 <b>คำแนะนำจากระบบ:</b> {advice_msg}'
            '</div>'
            '</div>', 
            unsafe_allow_html=True
        )

    with col_fc2:
        st.markdown(
            '<div class="curved-card">'
            '<h3 style="margin-bottom: 2px;">📅 ปฏิทินพ่นยา & วางแผนงาน 7 วัน</h3>'
            '<p style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 12px;">ดูสีสัญญาณไฟเพื่อวางแผนฉีดพ่นสารเคมีและให้น้ำ</p>',
            unsafe_allow_html=True
        )
        raw_weather = ForecastService.get_weather_forecast()
        thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]
        
        for idx, row in raw_weather.head(7).iterrows():
            dt = pd.to_datetime(row['date'])
            day_str = f"วัน{thai_days[dt.dayofweek]} {dt.day}/{dt.month}"
            rain = row['rain_mm']
            if rain == 0:
                bg_color, border_color = "rgba(34, 197, 94, 0.08)", "rgba(34, 197, 94, 0.3)"
                badge = "<span style='color: #4ade80; font-weight: 700;'>🟢 พ่นยา/ใส่ปุ๋ยได้</span>"
                icon = "☀️ ปลอดฝน"
            elif rain < 10:
                bg_color, border_color = "rgba(56, 189, 248, 0.08)", "rgba(56, 189, 248, 0.3)"
                badge = "<span style='color: #38bdf8; font-weight: 600;'>🟦 ฝนปรอย (ระวังยาล้าง)</span>"
                icon = f"🌦️ ฝน {rain:.1f} มม."
            else:
                bg_color, border_color = "rgba(239, 68, 68, 0.1)", "rgba(239, 68, 68, 0.4)"
                badge = "<span style='color: #f87171; font-weight: 700;'>🔴 งดพ่นยา / ระวังน้ำขัง</span>"
                icon = f"⛈️ ฝนหนัก {rain:.1f} มม."

            st.markdown(
                f'<div style="background: {bg_color}; border: 1px solid {border_color}; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">'
                f'<div style="display: flex; align-items: center; gap: 12px;"><span style="font-weight: 600; font-size: 0.9rem; min-width: 100px;">{day_str}</span><span style="font-size: 0.85rem; color: #cbd5e1;">{icon}</span></div>'
                f'<div style="font-size: 0.85rem;">{badge}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="curved-card"><h3>📜 สรุปสภาวะอากาศย้อนหลังและคำแนะนำการทำสวน</h3>', unsafe_allow_html=True)
    days_hist = st.radio("ช่วงเวลาที่ต้องการแสดง:", options=[7, 14], index=1, horizontal=True)
    hist_df_easy = get_historical_weather_easy(days=days_hist)
    
    for _, row in hist_df_easy.iterrows():
        st.markdown(
            f'<div style="background: rgba(255,255,255,0.02); border-left: 5px solid {row["color"]}; padding: 12px 18px; border-radius: 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.03);">'
            f'<div><span style="font-size: 0.85rem; color: #f1f5f9; font-weight: 600;">{row["date_th"]}</span><div style="font-size: 0.95rem; font-weight: 700; color: {row["color"]}; margin-top: 2px;">{row["status_label"]}</div></div>'
            f'<div style="font-size: 0.85rem; color: #cbd5e1; background: rgba(255,255,255,0.04); padding: 6px 14px; border-radius: 999px;">💡 {row["advice"]}</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    st.markdown(
        '<div class="curved-card">'
        '<h3>🤖 ผู้ช่วย AI ประจำสวน (ใช้ข้อมูลบัญชี สภาพอากาศ และราคา)</h3>'
        '<p style="color: #94a3b8; font-size: 0.85rem;">ระบบดึงข้อมูลรายรับ-รายจ่ายจริง สภาพอากาศ ค่าเงิน และแนวโน้มราคาร่วมวิเคราะห์ตอบคำถาม</p>',
        unsafe_allow_html=True
    )
    
    try:
        forecast_ctx = ForecastService.context_for_gemini()
    except Exception:
        forecast_ctx = "ข้อมูลพยากรณ์ราคาไม่พร้อมใช้งานในขณะนี้"

    context_str = f"""
    {forecast_ctx}

    ข้อมูลอัตราแลกเปลี่ยนล่าสุด:
    - 1 CNY = {cny_latest:.4f} THB (เปลี่ยนแปลง {cny_change_pct:.2f}%)

    ข้อมูลบัญชีสวนปัจจุบัน:
    - รายรับรวม: {total_income:,.2f} บาท
    - รายจ่ายรวม: {total_expense:,.2f} บาท
    - กำไรสุทธิ: {net_profit:,.2f} บาท
    """
    
    chat_input = st.text_input("พิมพ์คำถามของคุณ (เช่น ควรขายทุเรียนช่วงไหนดี หรือค่าเงินหยวนมีผลต่อราคาอย่างไร?):")
    
    if st.button("🚀 ถาม AI Copilot", use_container_width=True):
        if chat_input:
            with st.spinner("🧠 AI กำลังวิเคราะห์ข้อมูล..."):
                reply = gemini_service.ask_assistant(
                    user_question=chat_input,
                    farm_context=context_str
                )
                st.markdown(
                    f'<div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(74,222,128,0.25); border-radius: 18px; padding: 20px; margin-top: 15px;">'
                    f'<div style="color: #4ade80; font-weight: 600; margin-bottom: 8px;">💡 คำตอบจาก AI Copilot:</div>'
                    f'<div style="color: #e2e8f0; line-height: 1.7;">{reply}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
    st.markdown('</div>', unsafe_allow_html=True)