import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- การตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="TH Pump Radar Insight", layout="wide", page_icon="⛽")

# Custom CSS เพื่อความสวยงาม
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 1. การดึงข้อมูล (API Ingestion) ---
@st.cache_data(ttl=600)
def fetch_data():
    # เปลี่ยน URL เป็นลิงก์เต็มของคุณที่มี Token (fbclid)
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
    try:
        response = requests.get(API_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        # จัดการโครงสร้าง GeoJSON
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            # ลบคำนำหน้า properties. ออก
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # ดึงพิกัดจาก geometry.coordinates [lon, lat]
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c)>1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c)>1 else None for c in coords]
            
            # ทำความสะอาดข้อมูลเบื้องต้น
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # ตรวจสอบสถานะ (ถ้าไม่มีให้ Default เป็น Available)
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
            
            return df
        else:
            st.error("ไม่พบโครงสร้างข้อมูล Features ใน API")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"การเชื่อมต่อ API ขัดข้อง: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 2. ส่วนควบคุมด้านข้าง (Sidebar Filters) ---
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/3448/3448650.png", width=100)
st.sidebar.title("📍 ตัวเลือกการวิเคราะห์")

if not df_raw.empty:
    # --- การกรองเชิงพื้นที่ (Hierarchy) ---
    st.sidebar.subheader("เลือกพื้นที่")
    
    # จังหวัด
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    provinces = sorted(df_raw[prov_col].unique()) if prov_col else []
    selected_prov = st.sidebar.selectbox("จังหวัด", ["ทั้งหมด"] + provinces)

    # อำเภอ
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'district' in c), None)
    if selected_prov != "ทั้งหมด" and dist_col:
        districts = sorted(df_raw[df_raw[prov_col] == selected_prov][dist_col].unique())
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"] + districts)
    else:
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"], disabled=True)

    # ตำบล
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'subdistrict' in c), None)
    if selected_dist != "ทั้งหมด" and subdist_col:
        subdistricts = sorted(df_raw[(df_raw[prov_col] == selected_prov) & (df_raw[dist_col] == selected_dist)][subdist_col].unique())
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"] + subdistricts)
    else:
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"], disabled=True)

    # --- การกรองตามรัศมีและประเภทน้ำมัน ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("ตั้งค่าพิกัดและรัศมี")
    # พิกัดบ้านของคุณ (บางพูด ปากเกร็ด)
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมี (กม.)", options=[1, 5, 10, 20, 50], value=10)

    fuel_options = ['E20', '91', '95', 'G91', 'G95', 'B7', 'Diesel']
    selected_fuels = st.sidebar.multiselect("เลือกประเภทน้ำมัน", fuel_options, default=['E20', '95'])

# --- 3. การประมวลผลข้อมูล (Logic) ---
if not df_raw.empty:
    # กรองตามพื้นที่
    df_filtered = df_raw.copy()
    if selected_prov != "ทั้งหมด": df_filtered = df_filtered[df_filtered[prov_col] == selected_prov]
    if selected_dist != "ทั้งหมด": df_filtered = df_filtered[df_filtered[dist_col] == selected_dist]
    if selected_subdist != "ทั้งหมด": df_filtered = df_filtered[df_filtered[subdist_col] == selected_subdist]

    # คำนวณระยะทาง
    my_loc = (user_lat, user_lon)
    df_filtered['distance_km'] = df_filtered.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    
    # กรองตามรัศมี
    df_final = df_filtered[df_filtered['distance_km'] <= radius_km].copy()
    
    # กรองประเภทน้ำมัน (ถ้ามีข้อมูล)
    if 'fuel_type' in df_final.columns and selected_fuels:
        pattern = '|'.join(selected_fuels)
        df_final = df_final[df_final['fuel_type'].str.contains(pattern, case=False, na=True)]

    # --- 4. การแสดงผล (Dashboard) ---
    st.title("📊 ระบบติดตามสถานการณ์น้ำมัน Real-time")
    st.caption(f"ข้อมูลล่าสุด ณ ตำแหน่งของคุณ (รัศมี {radius_km} กม.)")

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ปั๊มทั้งหมดในรัศมี", len(df_final))
    out_of_stock = len(df_final[df_final['availability'].str.contains('Out', na=False, case=False)])
    c2.metric("น้ำมันหมด (แห่ง)", out_of_stock, delta=f"-{out_of_stock}", delta_color="inverse")
    c3.metric("ปั๊มที่ใกล้ที่สุด", f"{df_final['distance_km'].min():.2f} กม." if not df_final.empty else "N/A")
    c4.metric("ตำบลที่วิเคราะห์", selected_subdist if selected_subdist != "ทั้งหมด" else "หลายตำบล")

    # Tab แสดงผล
    tab1, tab2, tab3 = st.tabs(["🗺️ แผนที่อัจฉริยะ", "📈 สถิติเชิงพื้นที่", "📋 รายละเอียดสถานี"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        # วงกลมรัศมี
        folium.Circle([user_lat, user_lon], radius=radius_km*1000, color='blue', fill=True, opacity=0.1).add_to(m)
        # หมุดบ้าน
        folium.Marker([user_lat, user_lon], popup="คุณอยู่ที่นี่", icon=folium.Icon(color='red', icon='home')).add_to(m)
        
        marker_cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'Out' in str(row['availability']) else 'green'
            popup_text = f"<b>{row.get('station_name', 'N/A')}</b><br>ระยะทาง: {row['distance_km']:.2f} กม.<br>สถานะ: {row['availability']}"
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=folium.Popup(popup_text, max_width=250),
                icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')
            ).add_to(marker_cluster)
        folium_static(m, width=1100)

    with tab2:
        if not df_final.empty:
            fig = px.bar(df_final.sort_values('distance_km').head(15), 
                         x='station_name', y='distance_km', color='distance_km',
                         title="15 ปั๊มน้ำมันที่ใกล้ตำแหน่งของคุณที่สุด",
                         labels={'distance_km': 'ระยะทาง (กม.)', 'station_name': 'ชื่อปั๊ม'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่มีข้อมูลแสดงสถิติ")

    with tab3:
        cols_to_show = ['station_name', 'distance_km', 'availability', 'fuel_type']
        if subdist_col in df_final.columns: cols_to_show.insert(1, subdist_col)
        st.dataframe(df_final[cols_to_show].sort_values('distance_km'), use_container_width=True)
        
        # ปุ่มดาวน์โหลด
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงานพื้นที่นี้ (CSV)", data=csv, file_name='pump_report.csv', mime='text/csv')

else:
    st.warning("⚠️ กำลังรอการเชื่อมต่อข้อมูล... กรุณาตรวจสอบลิงก์ API และสถานะเครือข่าย")
