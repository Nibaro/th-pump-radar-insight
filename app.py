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
st.set_page_config(page_title="RSPG Fuel Logistics & Spatial Mapping", layout="wide", page_icon="⛽")

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
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." # ใส่ URL ของคุณ
    try:
        response = requests.get(API_URL, timeout=20)
        data = response.json()
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # พิกัด
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # ค้นหาคอลัมน์สำคัญ
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            price_col = next((c for c in df.columns if 'price' in c), None)
            fuel_col = next((c for c in df.columns if 'fuel' in c or 'type' in c), None)
            
            # จัดการแบรนด์
            df['major_brand'] = df[name_col].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['major_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            # จัดการสถานะ
            status_col = next((c for c in df.columns if 'avail' in c or 'status' in c), None)
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_col].apply(map_status) if status_col else '⚪ ไม่ทราบสถานะ'
            
            if price_col: df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
                
            return df, name_col, price_col, fuel_col
        return pd.DataFrame(), None, None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None, None

df_raw, name_col, price_col, fuel_col = fetch_data()

# --- 5. Sidebar (Filters) ---
LOGO_RSPG = "logo_rspg.png"
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    for b in MAJOR_BRANDS:
        if b in df_raw['major_brand'].values:
            b_cols = st.sidebar.columns([1, 4])
            logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
            with b_cols[0]:
                if os.path.exists(logo_path): st.image(logo_path, width=35)
            with b_cols[1]:
                if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        selected_brands.extend([b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS])

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด (สวนจิตรลดา)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (สวนจิตรลดา)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

st.sidebar.markdown("---")
st.sidebar.info("**จัดทำโดย:** แผนกวิชาการ อพ.สธ.\n📞 02-282-1850")

# --- 6. Main Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    
    # --- แก้ไขจุดที่เกิด KeyError ---
    if price_col and price_col in df_final.columns:
        avg_price = df_final[price_col].mean()
    else:
        avg_price = 0

    # --- 7. Dashboard Display ---
    st.title("⛽ RSPG Fuel Logistics Dashboard")
    
    m1, m2, m3, m4 = st.columns(4)
    out_stock = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']
    m1.metric("ปั๊มในพื้นที่", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_stock), delta=f"-{len(out_stock)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_price:.2f} บ." if avg_price > 0 else "N/A")

    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัด", "📊 Market Share", "📍 10 อันดับใกล้ที่สุด", "⛽ สถิติรายประเภทน้ำมัน"])

    with tab1:
        if not df_final.empty:
            m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
            folium.Marker(location=my_loc, popup="สนง. อพ.สธ.", icon=folium.Icon(color='darkred', icon='university', prefix='fa')).add_to(m)
            cluster = MarkerCluster().add_to(m)
            for _, row in df_final.iterrows():
                color = 'red' if 'หมด' in row['status_group'] else 'green'
                popup_c = f"<b>{row[name_col]}</b><br>ห่าง: {row['distance_km']:.2f} กม."
                folium.Marker([row['latitude'], row['longitude']], popup=popup_c, icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
            folium_static(m, width=1100)

    with tab4:
        st.subheader("📊 ข้อมูลแยกประเภทน้ำมัน (E20, G91, G95, Diesel)")
        if fuel_col and fuel_col in df_final.columns:
            # แตกข้อมูลประเภทน้ำมัน (Explode)
            df_fuel = df_final.assign(fuel=df_final[fuel_col].str.split(',')).explode('fuel')
            df_fuel['fuel'] = df_fuel['fuel'].str.strip()
            
            f_summary = df_fuel.groupby('fuel').agg({name_col: 'count', 'distance_km': 'min'}).reset_index()
            f_summary.columns = ['ประเภทน้ำมัน', 'จำนวนสถานี', 'ใกล้ที่สุด (กม.)']
            st.table(f_summary.sort_values('จำนวนสถานี', ascending=False))
            
            fig_fuel = px.bar(f_summary, x='ประเภทน้ำมัน', y='จำนวนสถานี', color='ประเภทน้ำมัน', text_auto=True)
            st.plotly_chart(fig_fuel, use_container_width=True)
        else:
            st.info("ℹ️ ข้อมูลจาก API ไม่ระบุประเภทน้ำมันย่อย")
else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API...")
