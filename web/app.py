import streamlit as st
from PIL import Image
from dotenv import load_dotenv
import pandas as pd
import plotly.express as px

# นำเข้าเฉพาะ service ที่ต้องใช้ (ตัด firebase_auth ออกชั่วคราว)
from gemini_service import GeminiService
from forecast_service import ForecastService

load_dotenv()

# 1. จัดการ Session State สำหรับจำลองการเข้าสู่ระบบ
if "user" not in st.session_state:
    st.session_state.user = None

is_logged_in = st.session_state.user is not None

st.set_page_config(
    page_title="RMA Durain | Next-Gen AgriTech",
    page_icon="🍈",
    layout="wide" if is_logged_in else "centered",
    initial_sidebar_state="expanded" if is_logged_in else "collapsed"
)

# 2. Modern Curved & Dynamic UI Design System
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
    /* 1. กำหนดฟอนต์เฉพาะส่วนเนื้อหา */
    html, body, .stMarkdown, p, h1, h2, h3, h4, h5, h6, label {
        font-family: 'Prompt', 'Plus Jakarta Sans', sans-serif !important;
        line-height: 1.6;
    }

    /* 2. ซ่อนปุ่มลูกศร Sidebar ที่เพี้ยนเป็นตัวหนังสือ */
    button[data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }

    /* 3. จัดการปุ่มใน File Uploader และดันช่องว่างข้างหลังเพื่อให้ Upload อยู่กึ่งกลาง */
    [data-testid="stFileUploaderDropzone"] button {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding-top: 6px !important;
        padding-bottom: 6px !important;
        padding-left: 14px !important;
        padding-right: 14px !important;
    }

    [data-testid="stFileUploaderDropzone"] button svg,
    [data-testid="stFileUploaderDropzone"] button [data-testid="stIconMaterial"] {
        display: none !important;
    }

    /* ใส่ช่องว่างด้านหลังตัวหนังสือเพื่อดันข้อความให้มาอยู่ตรงกลาง */
    [data-testid="stFileUploaderDropzone"] button span {
        margin: 0 !important;
        padding-right: 20px !important; /* ช่องว่างข้างหลัง ดันคำว่า Upload ให้อยู่กึ่งกลาง */
        line-height: 1.2 !important;
    }

    [data-testid="stFileUploaderDropzoneInstructions"] {
        font-family: 'Prompt', 'Plus Jakarta Sans', sans-serif !important;
    }

    /* Ambient Lighting Background */
    .stApp {
        background-color: #060b08;
        background-image: 
            radial-gradient(circle at 15% 15%, rgba(34, 197, 94, 0.12) 0%, transparent 40%),
            radial-gradient(circle at 85% 20%, rgba(234, 179, 8, 0.08) 0%, transparent 45%),
            radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.06) 0%, transparent 50%);
        background-attachment: fixed;
        color: #f1f5f9;
    }

    /* ปรับแต่งตำแหน่งความสูงของเนื้อหา */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }

    /* Sidebar แบบ Frosted Glass */
    [data-testid="stSidebar"] {
        background: rgba(11, 20, 14, 0.85) !important;
        backdrop-filter: blur(24px);
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }

    /* การ์ดสไตล์ Curved Glass */
    .curved-card {
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 24px;
        padding: 28px;
        margin-bottom: 20px;
        box-shadow: 0 16px 40px -10px rgba(0, 0, 0, 0.5);
    }

    .curved-card h1, .curved-card h2, .curved-card h3 {
        line-height: 1.35 !important;
    }

    /* Badge ป้ายสถานะทรงแคปซูล */
    .pill-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 16px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 500;
        line-height: 1.3;
        border: 1px solid rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
    }
    .badge-green {
        background: rgba(34, 197, 94, 0.12);
        color: #4ade80;
        border-color: rgba(74, 222, 128, 0.3);
    }
    .badge-gold {
        background: rgba(234, 179, 8, 0.12);
        color: #facc15;
        border-color: rgba(250, 204, 21, 0.3);
    }

    /* จุดไฟสถานะกระพริบ */
    .pulse-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: #22c55e;
        box-shadow: 0 0 10px #22c55e;
        animation: pulse 2s infinite;
        flex-shrink: 0;
    }
    @keyframes pulse {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(34, 197, 94, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
    }

    /* กล่อง Widget ใน Hero */
    .stat-pill {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 20px;
        padding: 14px 18px;
        display: flex;
        align-items: center;
        gap: 14px;
    }

    /* Tabs มนแคปซูล */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(255, 255, 255, 0.03);
        padding: 8px;
        border-radius: 24px;
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        border-radius: 16px;
        color: #94a3b8;
        font-weight: 500;
        padding: 0 24px;
        border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.2) 0%, rgba(234, 179, 8, 0.15) 100%) !important;
        color: #f1f5f9 !important;
        border: 1px solid rgba(74, 222, 128, 0.4) !important;
    }

    /* ปุ่มกดแคปซูลมน */
    .stButton>button {
        border-radius: 9999px !important;
        background: linear-gradient(135deg, #22c55e 0%, #15803d 100%) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        padding: 10px 28px !important;
        border: none !important;
        box-shadow: 0 10px 25px -5px rgba(34, 197, 94, 0.4);
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 15px 30px -5px rgba(34, 197, 94, 0.6);
        background: linear-gradient(135deg, #4ade80 0%, #16a34a 100%) !important;
    }

    #MainMenu, footer {visibility: hidden;}
    header {background: transparent !important;}
</style>
""", unsafe_allow_html=True)

# 3. เรียกใช้งาน Services
gemini_service = GeminiService()
forecast_service = ForecastService()

# ========================================================
# หน้าที่ 1: GATEWAY LOGIN (แบบ Mock ไม่พึ่งพา Firebase)
# ========================================================
if not is_logged_in:
    st.markdown("""
    <style>
        [data-testid="stSidebar"], [data-testid="collapsedControl"] {
            display: none !important;
        }
        .block-container {
            max-width: 480px !important;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown("""
        <div class="curved-card" style="text-align: center; padding: 32px 28px 24px 28px; margin-top: 10px; margin-bottom: 14px;">
            <div style="background: rgba(34,197,94,0.15); width: 60px; height: 60px; border-radius: 18px; display: inline-flex; align-items: center; justify-content: center; font-size: 1.7rem; margin-bottom: 14px;">
                🍈
            </div>
            <div style="display: flex; justify-content: center; margin-bottom: 10px;">
                <span class="pill-badge badge-green"><span class="pulse-dot"></span> Private Access Portal</span>
            </div>
            <h2 style="font-size: 1.75rem; font-weight: 700; margin: 0; background: linear-gradient(90deg, #f8fafc, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                DurianOS Enterprise
            </h2>
            <p style="color: #94a3b8; font-size: 0.85rem; margin-top: 10px; margin-bottom: 0px;">
                กรุณาเข้าสู่ระบบเพื่อเข้าถึงแดชบอร์ดการวิเคราะห์และข้อมูลเชิงลึก
            </p>
        </div>
        """, unsafe_allow_html=True)

        email_input = st.text_input("อีเมลผู้ใช้งาน", value="farmer@durianos.com")
        pwd_input = st.text_input("รหัสผ่าน", type="password", value="password123")
        
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("🔐 เข้าสู่ระบบ", use_container_width=True):
                st.session_state.user = {
                    "email": email_input if email_input else "farmer@durianos.com",
                    "farm_name": "สวนทุเรียนทรัพย์อนันต์ (จันทบุรี)"
                }
                st.rerun()

        with col_btn2:
            if st.button("🚀 เข้าดูแบบ Demo", use_container_width=True):
                st.session_state.user = {
                    "email": "demo_guest@durianos.com",
                    "farm_name": "สวนสาธิตเกษตรอัจฉริยะ"
                }
                st.rerun()
        
        st.caption("<div style='text-align: center; color: #64748b; margin-top: 14px;'>💡 โหมด Standalone: สามารถกดปุ่มใดก็ได้เพื่อเข้าชมระบบทันที</div>", unsafe_allow_html=True)

    st.stop()


# ========================================================
# หน้าที่ 2: FULL DASHBOARD
# ========================================================
st.markdown("""
<style>
    .block-container {
        max-width: 100% !important;
        padding-top: 2.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

# แถบ Sidebar
with st.sidebar:
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px;">
        <span style="font-size: 1.5rem;">🍈</span>
        <span style="font-weight: 700; font-size: 1.1rem; color: #f8fafc;">DurianOS Panel</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 14px; margin-bottom: 20px;">
        <div style="color: #64748b; font-size: 0.75rem;">บัญชีผู้ใช้งาน</div>
        <div style="font-weight: 600; color: #f1f5f9; font-size: 0.9rem; margin-top: 4px;">{st.session_state.user['email']}</div>
        <div style="color: #4ade80; font-size: 0.8rem; margin-top: 6px;">🏡 {st.session_state.user.get('farm_name', '-')}</div>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🚪 ออกจากระบบ", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# แบนเนอร์หัวหน้าหลัก
st.markdown(f"""
<div class="curved-card" style="padding: 32px 36px; margin-bottom: 20px;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px;">
        <div>
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                <span class="pill-badge badge-green"><span class="pulse-dot"></span> สิทธิ์เข้าถึงระดับพรีเมียม</span>
                <span class="pill-badge badge-gold">✨ Engine: Gemini 2.5 Flash</span>
            </div>
            <h1 style="font-size: 2.2rem; font-weight: 700; margin: 0; background: linear-gradient(90deg, #f8fafc, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                DURIAN INTELLIGENCE
            </h1>
            <p style="color: #94a3b8; font-size: 0.95rem; margin-top: 8px; font-weight: 400;">
                ยินดีต้อนรับสู่แดชบอร์ดบริหารจัดการผลผลิตและมาร์เก็ตอินไซต์
            </p>
        </div>
        <div style="display: flex; gap: 12px; flex-wrap: wrap;">
            <div class="stat-pill">
                <div style="background: rgba(34,197,94,0.1); color: #4ade80; width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">🏷️</div>
                <div>
                    <div style="color: #94a3b8; font-size: 0.75rem;">ราคาตลาดกลาง (AB)</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: #4ade80; margin-top: 2px;">145 ฿ <span style="font-size: 0.75rem; font-weight: 400;">/กก.</span></div>
                </div>
            </div>
            <div class="stat-pill">
                <div style="background: rgba(234,179,8,0.1); color: #facc15; width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">🌧️</div>
                <div>
                    <div style="color: #94a3b8; font-size: 0.75rem;">สภาพอากาศ 7 วัน</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: #facc15; margin-top: 2px;">ฝนเบาบาง <span style="font-size: 0.75rem; font-weight: 400;">(ตัดได้)</span></div>
                </div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# แท็บการใช้งาน Dashboard
tab1, tab2, tab3 = st.tabs([
    "🧾 สแกนบิลล้ง & เปรียบเทียบ",
    "📈 พยากรณ์ราคา & สภาพอากาศ",
    "🤖 ผู้ช่วย AI ประจำสวน"
])

# ----------------- TAB 1: OCR & ตรวจราคาล้ง -----------------
with tab1:
    col_upload, col_result = st.columns([1, 1.2], gap="large")
    
    with col_upload:
        st.markdown("""
        <div class="curved-card">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                <div style="background: rgba(34,197,94,0.15); width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">📷</div>
                <h3 style="margin: 0; font-size: 1.1rem; font-weight: 600;">อัปโหลดบิลรับซื้อ</h3>
            </div>
            <p style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 16px;">สแกนใบเสร็จกระดาษหรือบิลดิจิทัลด้วย Gemini Vision</p>
        """, unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader("", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
        
        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, use_container_width=True)
            scan_btn = st.button("✨ วิเคราะห์ข้อมูลด้วย AI", use_container_width=True)
        else:
            scan_btn = False
            st.markdown("""
            <div style="border: 2px dashed rgba(255,255,255,0.08); border-radius: 20px; padding: 36px 20px; text-align: center; background: rgba(255,255,255,0.01);">
                <div style="font-size: 2rem; margin-bottom: 8px; opacity: 0.6;">📄</div>
                <div style="font-size: 0.88rem; color: #94a3b8; font-weight: 500;">ลากไฟล์มาวาง หรือกดเลือกไฟล์รูปภาพ</div>
                <div style="font-size: 0.75rem; color: #64748b; margin-top: 4px;">รองรับ JPG, JPEG, PNG</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_result:
        st.markdown("""
        <div class="curved-card">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="background: rgba(250,204,21,0.15); width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">📊</div>
                    <h3 style="margin: 0; font-size: 1.1rem; font-weight: 600;">สรุปผลการตรวจสอบบิล</h3>
                </div>
                <span class="pill-badge badge-green">Real-time Verified</span>
            </div>
        """, unsafe_allow_html=True)
        
        if scan_btn and uploaded_file:
            with st.spinner("⚡ กำลังแปลงรูปภาพและเปรียบเทียบราคาตลาด..."):
                try:
                    result = gemini_service.extract_receipt(image)
                    
                    c1, c2 = st.columns(2)
                    c1.markdown(f"""
                    <div style="background: rgba(255,255,255,0.02); padding: 14px 16px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="color: #94a3b8; font-size: 0.75rem;">ชื่อล้ง / ผู้ซื้อ</div>
                        <div style="font-size: 1.05rem; font-weight: 600; color: #f8fafc; margin-top: 4px;">{result.get("buyer_name", "-")}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c2.markdown(f"""
                    <div style="background: rgba(255,255,255,0.02); padding: 14px 16px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="color: #94a3b8; font-size: 0.75rem;">ยอดเงินสุทธิ</div>
                        <div style="font-size: 1.05rem; font-weight: 700; color: #facc15; margin-top: 4px;">{result.get('grand_total', 0):,.2f} บาท</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
                    items_df = pd.DataFrame(result.get("items", []))
                    st.dataframe(
                        items_df,
                        use_container_width=True,
                        column_config={
                            "grade": st.column_config.TextColumn("เกรดผลผลิต"),
                            "weight_kg": st.column_config.NumberColumn("น้ำหนัก (กก.)", format="%.2f"),
                            "price_per_kg": st.column_config.NumberColumn("ราคาที่ได้ (บาท)", format="%.2f ฿"),
                            "total_amount": st.column_config.NumberColumn("รวมเป็นเงิน", format="%.2f ฿")
                        }
                    )
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
        else:
            st.markdown("""
            <div style="padding: 50px 20px; text-align: center;">
                <div style="background: rgba(255,255,255,0.02); width: 56px; height: 56px; border-radius: 18px; display: inline-flex; align-items: center; justify-content: center; font-size: 1.6rem; margin-bottom: 12px;">🔍</div>
                <div style="color: #94a3b8; font-weight: 500; font-size: 0.92rem;">รอการอัปโหลดใบเสร็จ</div>
                <div style="color: #64748b; font-size: 0.8rem; margin-top: 4px;">ระบบจะคำนวณส่วนต่างราคาตลาด และแจกแจงเกรดอัตโนมัติที่นี่</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ----------------- TAB 2: พยากรณ์ราคา & ฝน -----------------
with tab2:
    col_chart1, col_chart2 = st.columns(2, gap="large")
    
    with col_chart1:
        st.markdown("""
        <div class="curved-card">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="background: rgba(34,197,94,0.15); width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center;">📈</div>
                    <h3 style="margin: 0; font-size: 1.05rem; font-weight: 600;">คาดการณ์ราคาหมอนทอง (1-4 สัปดาห์)</h3>
                </div>
                <span class="pill-badge badge-green">+8.4% Trend</span>
            </div>
            <p style="color: #94a3b8; font-size: 0.82rem; margin-bottom: 12px;">โมเดล Time-Series รวมกับอัตราแลกเปลี่ยน THB/CNY</p>
        """, unsafe_allow_html=True)
        
        price_df = forecast_service.get_durian_price_forecast()
        fig_price = px.line(
            price_df, x="week", y=["min_price", "max_price"],
            markers=True,
            color_discrete_sequence=["#22c55e", "#facc15"],
            template="plotly_dark"
        )
        fig_price.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title=""),
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)')
        )
        st.plotly_chart(fig_price, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_chart2:
        st.markdown("""
        <div class="curved-card">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="background: rgba(56,189,248,0.15); width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center;">🌧️</div>
                    <h3 style="margin: 0; font-size: 1.05rem; font-weight: 600;">แนวโน้มปริมาณฝน 14 วัน (มม.)</h3>
                </div>
                <span class="pill-badge" style="background: rgba(56,189,248,0.1); color: #38bdf8; border-color: rgba(56,189,248,0.3);">Open-Meteo Live</span>
            </div>
            <p style="color: #94a3b8; font-size: 0.82rem; margin-bottom: 12px;">ตรวจจับความชื้นและฝนสะสมเพื่อป้องกันอาการทุเรียนไส้ซึม</p>
        """, unsafe_allow_html=True)
        
        weather_df = forecast_service.get_weather_forecast()
        fig_weather = px.bar(
            weather_df, x="date", y="rain_mm",
            color="rain_mm",
            color_continuous_scale=["#38bdf8", "#0284c7"],
            template="plotly_dark"
        )
        fig_weather.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)')
        )
        st.plotly_chart(fig_weather, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ----------------- TAB 3: แชท AI -----------------
with tab3:
    st.markdown("""
    <div class="curved-card">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
            <div style="background: rgba(168,85,247,0.15); width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.1rem;">🧠</div>
            <h3 style="margin: 0; font-size: 1.1rem; font-weight: 600;">Agri-Copilot ที่ปรึกษาสวนทุเรียน</h3>
        </div>
        <p style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 16px;">ถามตอบข้อมูลตลาด ประเมินวันตัดผลผลิต และช่วยวิเคราะห์การเจรจาล้ง</p>
    """, unsafe_allow_html=True)
    
    st.markdown("<div style='font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px; font-weight: 500;'>⚡ แนะนำคำถามด่วน (Quick Prompts):</div>", unsafe_allow_html=True)
    qp1, qp2, qp3 = st.columns(3)
    prompt_choice = None
    if qp1.button("🏷️ ล้งให้ 120 บาท ควรปล่อยไหม?"):
        prompt_choice = "ล้งเสนอราคา 120 บาทสำหรับเกรดรวมตอนนี้ ควรขายทันทีหรือรอสัปดาห์หน้า?"
    if qp2.button("🌧️ ดูฝนแล้วควรเลี่ยงตัดวันไหน?"):
        prompt_choice = "ดูจากพยากรณ์ปริมาณฝนช่วงนี้ ควรเลี่ยงตัดทุเรียนวันไหนบ้างเพื่อไม่ให้ผลแฉะหรือไส้ซึม?"
    if qp3.button("📅 เช็กอายุผลและการสะสมแป้ง"):
        prompt_choice = "หมอนทองดอกบานครบ 110 วัน แป้งน่าจะได้เกณฑ์ส่งออกหรือยัง?"

    chat_input = st.text_input("พิมพ์คำถามของคุณที่นี่...", value=prompt_choice if prompt_choice else "", label_visibility="collapsed")
    
    if st.button("🚀 ส่งคำถามไปยัง AI Copilot", use_container_width=True):
        if chat_input:
            with st.spinner("🧠 กำลังประมวลผลคำตอบจากบริบทตลาด..."):
                reply = gemini_service.ask_assistant(
                    user_question=chat_input,
                    farm_context="ทุเรียนหมอนทอง แปลงหลัก 15 ไร่ จันทบุรี กำหนดตัดรอบถัดไปอีก 10 วันข้างหน้า"
                )
                st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
                st.markdown(f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(74,222,128,0.25); border-radius: 18px; padding: 20px 24px;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                        <span class="pill-badge badge-green" style="padding: 4px 12px; font-size: 0.75rem;">AI Insight Response</span>
                    </div>
                    <div style="line-height: 1.75; color: #e2e8f0; font-size: 0.95rem;">
                        {reply}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)