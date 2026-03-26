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
</style>
""", unsafe_allow_html=True)

# --- 3. นิยามแบรนด์หลัก ---
MAJOR_BRANDS = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

# --- 4. ฟังก์ชันดึงข้อมูล ---
@st.cache_data(ttl=600)
def fetch_data():
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
            return df, name_c, price_c, fuel_c
        return pd.DataFrame(), None, None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None, None

df_raw, name_col, price_col, fuel_col = fetch_data()

# --- 5. Main Processing ---
if not df_raw.empty:
    user_lat, user_lon = 13.769068, 100.524251 # สวนจิตรลดา
    df_f = df_raw.copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= 10].copy()
    
    st.title("⛽ RSPG Fuel Logistics Dashboard")
    
    tab1, tab2 = st.tabs(["🗺️ แผนที่", "📊 ข้อมูล"])
    with tab1:
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        folium.Marker(location=my_loc, popup="สนง. อพ.สธ.", icon=folium.Icon(color='darkred', icon='university', prefix='fa')).add_to(m)
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'หมด' in row['status_group'] else 'green'
            folium.Marker([row['latitude'], row['longitude']], popup=row[name_col], icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
        folium_static(m, width=1100)
else:
    st.warning("⚠️ กำลังดึงข้อมูล...")
