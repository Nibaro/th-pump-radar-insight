import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster, HeatMap
from geopy.distance import geodesic
import plotly.express as px
import os

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="RSPG Fuel Logistics & Spatial Mapping", 
    layout="wide", 
    page_icon="⛽"
)

# --- 2. CSS เพื่อความคมชัดสูง ---
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 2px solid #003366 !important;
        padding: 20px !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15) !important;
    }
    [data-testid="stMetricLabel"] { color: #000000 !important; font-weight: bold !important; font-size: 1.1rem !important; }
    [data-testid="stMetricValue"] { color: #003366 !important; font-weight: 800 !important; font-size: 2.2rem !important; }
    [data-testid="stSidebar"] [data-testid="column"] { display: flex; align-items: center; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. นิยามแบรนด์หลัก ---
MAJOR_BRANDS = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

# --- 4. ฟังก์ชันดึงข้อมูล (API Engine) ---
@st.cache_data(ttl=600)
def fetch_data():
    # *** ตรวจสอบ URL ของคุณที่นี่ ***
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
    try:
        response = requests.get(API_URL, timeout=20)
        data = response.json()
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            name_c = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            price_c = next((c for c in df.columns if 'price' in c), None)
            fuel_c = next((c for c in df.columns if 'fuel' in c or 'type' in c), None)
            
            df['major_brand'] = df[name_c].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['major_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            status_c = next((c for c in df.columns if 'avail' in c or 'status' in c), None)
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_c].apply(map_status) if status_c else '⚪ ไม่ทราบสถานะ'
            
            if price_c: df[price_c] = pd.to_numeric(df[price_c], errors='coerce')
            if not fuel_c:
                df['fuel_types'] = "G95, G91, E20"
                fuel_c = 'fuel_types'
                
            return df, name_c, price_c, fuel_c
        return pd.DataFrame(), None, None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None, None

df_raw, name_col, price_col, fuel_col = fetch_data()

# --- 5. Sidebar (Filters & Contact) ---
LOGO_RSPG = "logo_rspg.png"
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    for b in MAJOR_BRANDS:
        if b in df_raw['major_brand'].values:
            b_cols = st.sidebar.columns([1, 4])
            logo_p = os.path.join("brand_logos", f"{b.lower()}.png")
            with b_cols[0]:
                if os.path.exists(logo_p): st.image(logo_p, width=35)
            with b_cols[1]:
                if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        selected_brands.extend([b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS])

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด (สวนจิตรลดา)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (สวนจิตรลดา)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

st.sidebar.markdown("---")
st.sidebar.info("**จัดทำโดย:** แผนกวิชาการ อพ.สธ.\n📞 02-282-1850 | 📧 rspg.local@gmail.com")

# --- 6. Main Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    out_stock = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']
    
    avg_price = df_final[price_col].mean() if price_col and price_col in df_final.columns else 0

    # --- 7. Dashboard Display ---
    st.title("⛽ ระบบสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ปั๊มในพื้นที่", len(df_final))
    c2.metric("น้ำมันหมด", len(out_stock), delta=f"-{len(out_stock)}", delta_color="inverse")
    c3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    c4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_price:.2f} บ." if avg_price > 0 else "N/A")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗺️ แผนที่พิกัด", "📊 Market Share", "📍 10 อันดับใกล้ที่สุด", "📋 สรุปสถานะ", "⛽ สถิติประเภทน้ำมัน"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัดและความเสี่ยง (Heatmap)")
        if not df_final.empty:
            m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
            if not out_stock.empty:
                HeatMap([[r['latitude'], r['longitude']] for _, r in out_stock.iterrows()], radius=15).add_to(m)
            
            folium.Marker(location=my_loc, popup="สนง. อพ.สธ.", icon=folium.Icon(color='darkred', icon='university', prefix='fa')).add_to(m)
            cluster = MarkerCluster().add_to(m)
            for _, row in df_final.iterrows():
                color = 'red' if 'หมด' in row['status_group'] else 'green'
                clean_n = str(row[name_col]).replace("'", "\\'")
                nav_url = f"https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']}"
                p_html = f"<b>{clean_n}</b><br>ห่าง: {row['distance_km']:.2f} กม.<br><a href='{nav_url}' target='_blank'>📍 นำทาง</a>"
                folium.Marker([row['latitude'], row['longitude']], popup=folium.Popup(p_html, max_width=200), icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
            folium_static(m, width=1100)
        else:
            st.warning("⚠️ ไม่พบข้อมูลในพื้นที่วิเคราะห์")

    with tab5:
        st.subheader("⛽ สถิติแยกตามประเภทน้ำมัน")
        if fuel_col and fuel_col in df_final.columns:
            df_fuel = df_final.assign(fuel=df_final[fuel_col].str.split(',')).explode('fuel')
            df_fuel['fuel'] = df_fuel['fuel'].str.strip().str.upper()
            fuel_sum = df_fuel.groupby('fuel').agg({name_col: 'count', price_col: 'mean'}).reset_index()
            fuel_sum.columns = ['ประเภทน้ำมัน', 'จำนวนปั๊ม', 'ราคาเฉลี่ย']
            st.table(fuel_sum.sort_values('จำนวนปั๊ม', ascending=False))
        else:
            st.info("ℹ️ ไม่พบข้อมูลประเภทน้ำมัน")

else:
    st.warning("⚠️ กำลังรอข้อมูลจาก API...")
