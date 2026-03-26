# วางโค้ดทั้งหมดที่นี่
import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- CONFIG ---
st.set_page_config(page_title="Pump Radar Analysis", layout="wide", page_icon="⛽")

# --- 1. DATA INGESTION ---
@st.cache_data(ttl=600)
def fetch_data():
    # URL API ของคุณ (ตรวจสอบว่าใส่ Token ครบถ้วน)
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # 1. จัดการโครงสร้าง JSON ให้เป็น DataFrame
        if isinstance(data, list):
            df = pd.json_normalize(data)
        elif isinstance(data, dict):
            target_key = next((k for k in ['reports', 'data', 'results'] if k in data), None)
            df = pd.json_normalize(data[target_key]) if target_key else pd.json_normalize([data])
        else:
            return pd.DataFrame()

        if df.empty:
            return df

        # 2. ปรับชื่อ Column ให้เป็นพิมพ์เล็กทั้งหมดเพื่อป้องกัน Case Sensitive
        df.columns = [str(c).lower() for c in df.columns]
        
        # 3. ตรวจจับชื่อ Column พิกัด (ค้นหาคำว่า lat, lon, lng)
        lat_col = next((c for c in df.columns if 'lat' in c), None)
        lon_col = next((c for c in df.columns if 'lon' in c or 'lng' in c), None)

        if lat_col and lon_col:
            # เปลี่ยนชื่อคอลัมน์ที่หาเจอให้เป็น 'latitude' และ 'longitude' มาตรฐาน
            df = df.rename(columns={lat_col: 'latitude', lon_col: 'longitude'})
            
            # แปลงค่าเป็นตัวเลข
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            
            # ตรวจสอบสถานะ (Availability) - ถ้าไม่มีให้สร้างค่า Default
            status_col = next((c for c in df.columns if 'availability' in c or 'status' in c), None)
            if status_col:
                df['availability'] = df[status_col].astype(str).str.strip()
            else:
                df['availability'] = 'Available' # สมมติว่ามีถ้าไม่มีคอลัมน์ระบุ
                
            return df.dropna(subset=['latitude', 'longitude'])
        else:
            # ถ้าหาไม่เจอจริงๆ ให้โชว์ชื่อคอลัมน์ทั้งหมดเพื่อ Debug
            st.error(f"❌ หาพิกัดไม่เจอ! คอลัมน์ที่พบคือ: {list(df.columns)}")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาด: {e}")
        return pd.DataFrame()

# --- 2. SIDEBAR FILTERS ---
st.sidebar.header("📍 ตั้งค่าตำแหน่งและพื้นที่")
lat_default = 13.935809
lon_default = 100.514827

user_lat = st.sidebar.number_input("ละติจูด (Lat)", value=lat_default, format="%.6f")
user_lon = st.sidebar.number_input("ลองจิจูด (Lon)", value=lon_default, format="%.6f")
radius_km = st.sidebar.select_slider("รัศมีการค้นหา (กม.)", options=[1, 5, 10, 20, 50], value=10)

st.sidebar.markdown("---")
fuel_options = ['E20', '91', '95', 'G91', 'G95']
selected_fuels = st.sidebar.multiselect("เลือกประเภทน้ำมัน", fuel_options, default=['E20', '95'])

# --- 3. MAIN LOGIC ---
df_raw = fetch_data()

if not df_raw.empty:
    # คำนวณระยะทาง
    my_loc = (user_lat, user_lon)
    df_raw['distance_km'] = df_raw.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)

    # กรองตามรัศมีและประเภทน้ำมัน
    mask = (df_raw['distance_km'] <= radius_km) & (df_raw['availability'] == 'Available')
    df_filtered = df_raw[mask].copy()

    # การแสดงผล Metric
    st.title("⛽ Fuel Availability Insights")
    m1, m2, m3 = st.columns(3)
    m1.metric("ปั๊มที่พร้อมให้บริการ", len(df_filtered))
    m2.metric("ระยะทางที่ใกล้ที่สุด", f"{df_filtered['distance_km'].min():.2f} กม." if not df_filtered.empty else "N/A")
    m3.metric("รัศมีวิเคราะห์", f"{radius_km} กม.")

    # --- 4. VISUALIZATION ---
    tab1, tab2 = st.tabs(["🗺️ แผนที่ Interactive", "📊 สถิติรายพื้นที่"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        folium.Circle(location=[user_lat, user_lon], radius=radius_km*1000, color='blue', fill=True, opacity=0.1).add_to(m)
        folium.Marker([user_lat, user_lon], tooltip="ตำแหน่งของคุณ", icon=folium.Icon(color='red', icon='home')).add_to(m)

        marker_cluster = MarkerCluster().add_to(m)
        for _, row in df_filtered.iterrows():
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=f"<b>{row.get('station_name', 'N/A')}</b><br>ระยะทาง: {row['distance_km']:.2f} กม.<br>ประเภท: {row.get('fuel_type','N/A')}",
                icon=folium.Icon(color='green', icon='gas-pump', prefix='fa')
            ).add_to(marker_cluster)
        folium_static(m, width=1000)

    with tab2:
        if not df_filtered.empty:
            fig = px.bar(df_filtered.sort_values('distance_km').head(10),
                         x='station_name', y='distance_km', color='distance_km',
                         title="10 อันดับปั๊มที่ใกล้ที่สุด (กม.)",
                         labels={'distance_km': 'ระยะทาง (กม.)', 'station_name': 'ชื่อสถานี'})
            st.plotly_chart(fig, use_container_width=True)

    # --- 5. REPORT DOWNLOAD ---
    st.markdown("---")
    csv = df_filtered.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 ดาวน์โหลดรายงาน (CSV)", data=csv, file_name='fuel_report.csv', mime='text/csv')
else:
    st.warning("กำลังรอข้อมูลจาก API หรือ ข้อมูลไม่ถูกต้อง...")
