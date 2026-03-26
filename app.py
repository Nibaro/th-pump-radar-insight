import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="TH Pump Radar Insight", layout="wide", page_icon="⛽")

# --- 1. ฟังก์ชันดึงข้อมูล (API Ingestion) ---
@st.cache_data(ttl=600)
def fetch_data():
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." # ตรวจสอบ URL เต็มของคุณ
    try:
        response = requests.get(API_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # ดึงพิกัดจาก GeoJSON
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c)>1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c)>1 else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"API Error: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 2. ส่วนควบคุมด้านข้าง (Sidebar) ---
st.sidebar.title("⛽ ตัวเลือกการวิเคราะห์")

if not df_raw.empty:
    def get_safe_unique(df, col):
        if col and col in df.columns:
            return sorted([str(i) for i in df[col].dropna().unique()])
        return []

    # ตรวจหาชื่อคอลัมน์อัตโนมัติ
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'sub' in c), None)
    # หาคอลัมน์ชื่อปั๊ม (สำคัญสำหรับแก้ Error กราฟ)
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), df_raw.columns[0])

    selected_prov = st.sidebar.selectbox("จังหวัด", ["ทั้งหมด"] + get_safe_unique(df_raw, prov_col))
    
    if selected_prov != "ทั้งหมด":
        df_p = df_raw[df_raw[prov_col] == selected_prov]
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"] + get_safe_unique(df_p, dist_col))
    else:
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"], disabled=True)

    if selected_dist != "ทั้งหมด":
        df_d = df_raw[(df_raw[prov_col] == selected_prov) & (df_raw[dist_col] == selected_dist)]
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"] + get_safe_unique(df_d, subdist_col))
    else:
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"], disabled=True)

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมี (กม.)", options=[1, 5, 10, 20, 50], value=10)

# --- 3. การประมวลผล ---
if not df_raw.empty:
    df_f = df_raw.copy()
    if selected_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == selected_prov]
    if selected_dist != "ทั้งหมด" and selected_dist: df_f = df_f[df_f[dist_col] == selected_dist]
    if selected_subdist != "ทั้งหมด" and selected_subdist: df_f = df_f[df_f[subdist_col] == selected_subdist]

    df_f['distance_km'] = df_f.apply(lambda r: geodesic((user_lat, user_lon), (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # --- 4. แสดงผล ---
    st.title("📊 รายงานสถานะน้ำมัน")
    
    tab1, tab2, tab3 = st.tabs(["🗺️ แผนที่", "📈 กราฟ", "📋 ตาราง"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=12, tiles='CartoDB Positron')
        marker_cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            folium.Marker(
                [row['latitude'], row['longitude']], 
                popup=f"{row.get(name_col, 'N/A')}: {row['distance_km']:.2f} กม."
            ).add_to(marker_cluster)
        folium_static(m, width=1100)

    with tab2:
        if not df_final.empty:
            # ใช้ name_col ที่หาได้แบบ Dynamic เพื่อแก้ปัญหา ValueError
            top_data = df_final.sort_values('distance_km').head(15)
            fig = px.bar(top_data, x=name_col, y='distance_km', color='distance_km',
                         title="15 ปั๊มที่ใกล้ที่สุด", labels={name_col: 'ชื่อปั๊ม', 'distance_km': 'ระยะทาง (กม.)'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่พบข้อมูลปั๊มน้ำมันในรัศมีที่เลือก")

    with tab3:
        st.dataframe(df_final[[name_col, 'distance_km', 'availability']].sort_values('distance_km'), use_container_width=True)

else:
    st.warning("⚠️ ไม่พบข้อมูล กรุณาตรวจสอบ API")
