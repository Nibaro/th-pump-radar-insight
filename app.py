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
    # ตรวจสอบ URL เต็มของคุณที่มี Token (fbclid)
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
    try:
        response = requests.get(API_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # ดึงพิกัดจาก GeoJSON [lon, lat]
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

    # ค้นหาชื่อคอลัมน์อัตโนมัติ
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'sub' in c), None)
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), df_raw.columns[0])
    fuel_col = next((c for c in df_raw.columns if 'fuel' in c or 'type' in c), None)

    # --- ส่วนเลือกพื้นที่ ---
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

    # --- ส่วนเลือกประเภทน้ำมัน (ใหม่!) ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("⛽ ประเภทน้ำมันที่ต้องการ")
    # กำหนดประเภทน้ำมันมาตรฐาน
    fuel_list = ['E20', '91', '95', 'G91', 'G95', 'B7', 'Diesel', 'E85']
    selected_fuels = st.sidebar.multiselect("เลือกประเภทน้ำมัน (เลือกได้หลายรายการ)", fuel_list, default=['95', 'E20'])

    st.sidebar.markdown("---")
    st.sidebar.subheader("📐 พิกัดและรัศมี")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีค้นหา (กม.)", options=[1, 5, 10, 20, 50], value=10)

# --- 3. การประมวลผล (Filtering Logic) ---
if not df_raw.empty:
    df_f = df_raw.copy()
    
    # 1. กรองเชิงพื้นที่
    if selected_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == selected_prov]
    if selected_dist != "ทั้งหมด" and selected_dist: df_f = df_f[df_f[dist_col] == selected_dist]
    if selected_subdist != "ทั้งหมด" and selected_subdist: df_f = df_f[df_f[subdist_col] == selected_subdist]

    # 2. คำนวณระยะทาง
    df_f['distance_km'] = df_f.apply(lambda r: geodesic((user_lat, user_lon), (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # 3. กรองประเภทน้ำมัน (Logic ค้นหาคำใน String)
    if fuel_col and selected_fuels:
        # สร้าง regex pattern เช่น '95|E20'
        fuel_pattern = '|'.join(selected_fuels)
        df_final = df_final[df_final[fuel_col].str.contains(fuel_pattern, case=False, na=False)]

    # --- 4. การแสดงผล Dashboard ---
    st.title("📊 รายงานสถานะน้ำมันเชิงพื้นที่")
    
    # สรุปตัวเลขด้านบน
    c1, c2, c3 = st.columns(3)
    c1.metric("ปั๊มที่ตรงเงื่อนไข", len(df_final))
    c2.metric("ประเภทน้ำมันที่เลือก", f"{len(selected_fuels)} ประเภท")
    c3.metric("รัศมีวิเคราะห์", f"{radius_km} กม.")

    tab1, tab2, tab3 = st.tabs(["🗺️ แผนที่พิกัด", "📈 วิเคราะห์ระยะทาง", "📋 ข้อมูลรายปั๊ม"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        folium.Circle([user_lat, user_lon], radius=radius_km*1000, color='blue', fill=True, opacity=0.1).add_to(m)
        folium.Marker([user_lat, user_lon], icon=folium.Icon(color='red', icon='home')).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            popup_info = f"<b>{row.get(name_col, 'N/A')}</b><br>ห่าง: {row['distance_km']:.2f} กม.<br>น้ำมัน: {row.get(fuel_col, 'ไม่ระบุ')}"
            folium.Marker(
                [row['latitude'], row['longitude']], 
                popup=folium.Popup(popup_info, max_width=250)
            ).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        if not df_final.empty:
            top_15 = df_final.sort_values('distance_km').head(15)
            fig = px.bar(top_15, x=name_col, y='distance_km', color='distance_km',
                         title="15 ปั๊มที่ใกล้ที่สุดที่แนะนำ", labels={name_col: 'ชื่อปั๊ม', 'distance_km': 'ระยะทาง (กม.)'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่พบปั๊มที่มีน้ำมันประเภทที่เลือกในรัศมีนี้")

    with tab3:
        # เลือกคอลัมน์สำคัญมาแสดงในตาราง
        cols = [name_col, 'distance_km', 'availability']
        if fuel_col: cols.append(fuel_col)
        if subdist_col: cols.insert(1, subdist_col)
        
        st.dataframe(df_final[cols].sort_values('distance_km'), use_container_width=True)
        
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงาน (CSV)", data=csv, file_name='fuel_report.csv', mime='text/csv')

else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API หรือ ลิงก์ API ไม่ถูกต้อง")
