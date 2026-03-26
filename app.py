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
    # ตรวจสอบ URL API ให้ถูกต้อง
    API_URL = "https://thaipumpradar.com/api/export?fbclid=IwY2xjawQxb09leHRuA2FlbQIxMABicmlkETFxcmF4bm9VNVVnMFEzdUI4c3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHuXzVKJDQfjTdZLhr7h4Ks0wT4U-X03zvJv2WzUdSiyUmUKIfuin3onhoCao_aem_cM8VyyTuQRkh2EXh03E4Bg" 
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # 1. จัดการข้อมูลรูปแบบ GeoJSON (เจาะไปที่ 'features')
        if isinstance(data, dict) and 'features' in data:
            # ใช้ pd.json_normalize แผ่ข้อมูลใน features ออกมา
            df = pd.json_normalize(data['features'])
            
            # ลบคำนำหน้า 'properties.' ออกเพื่อให้เรียกใช้ง่ายขึ้น
            df.columns = [c.replace('properties.', '') for c in df.columns]
            
            # 2. ดึงพิกัดจาก geometry.coordinates
            # โดยปกติ GeoJSON จะเก็บเป็น [longitude, latitude]
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) else None for c in coords]
            
            # 3. ตรวจหาคอลัมน์สำรอง ถ้า geometry.coordinates ไม่มี
            if 'latitude' not in df.columns or df['latitude'].isnull().all():
                lat_col = next((c for c in df.columns if 'lat' in c.lower()), None)
                lon_col = next((c for c in df.columns if 'lon' in c.lower() or 'lng' in c.lower()), None)
                if lat_col and lon_col:
                    df = df.rename(columns={lat_col: 'latitude', lon_col: 'longitude'})

            # แปลงค่าเป็นตัวเลขและลบแถวที่ไม่มีพิกัด
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])

            # ตรวจสอบสถานะน้ำมัน (ถ้าไม่มีคอลัมน์ availability ให้มองว่าเป็น Available ไว้ก่อน)
            if 'availability' not in df.columns:
                # ลองหาคอลัมน์ที่มีคำว่า status หรือ available
                status_col = next((c for c in df.columns if 'status' in c.lower()), None)
                if status_col:
                    df['availability'] = df[status_col]
                else:
                    df['availability'] = 'Available'
            
            return df
        else:
            st.error("❌ ข้อมูลที่ได้รับไม่ใช่รูปแบบ GeoJSON ที่คาดไว้")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
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
