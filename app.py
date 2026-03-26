import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="TH Pump Radar - Price & Stock", layout="wide", page_icon="⛽")

# --- 1. ฟังก์ชันดึงข้อมูล (เพิ่มการจัดการราคา) ---
@st.cache_data(ttl=600)
def fetch_data():
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." # ตรวจสอบ URL ของคุณ
    try:
        response = requests.get(API_URL, timeout=20)
        data = response.json()
        
        if isinstance(data, dict) and 'features' in data:
            df = pd.json_normalize(data['features'])
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # จัดการพิกัด
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # --- จัดการข้อมูลราคา (Price) ---
            # ค้นหาคอลัมน์ที่มีคำว่า 'price' หรือ 'cost'
            price_cols = [c for c in df.columns if 'price' in c or 'cost' in c]
            for col in price_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"⚠️ API Error: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 2. ส่วนควบคุมด้านข้าง (Sidebar) ---
st.sidebar.title("⛽ วิเคราะห์ราคาน้ำมัน")

if not df_raw.empty:
    # ค้นหาชื่อคอลัมน์ที่จำเป็น
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), 'id')
    fuel_col = next((c for c in df_raw.columns if 'fuel' in c or 'type' in c), None)
    price_col = next((c for c in df_raw.columns if 'price' in c), None) # หาคอลัมน์ราคาหลัก

    # ตัวเลือกประเภทน้ำมัน
    st.sidebar.subheader("⛽ กรองประเภทน้ำมัน")
    fuel_list = ['E20', '91', '95', 'G91', 'G95', 'B7', 'Diesel']
    selected_fuels = st.sidebar.multiselect("เลือกประเภทเพื่อดูราคา", fuel_list, default=['95', 'E20'])

    st.sidebar.markdown("---")
    st.sidebar.subheader("📍 พิกัดปากเกร็ด (บางพูด)")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีค้นหา (กม.)", options=[1, 5, 10, 20, 50], value=10)

# --- 3. การประมวลผล ---
if not df_raw.empty:
    df_f = df_raw.copy()
    
    # คำนวณระยะทาง
    df_f['distance_km'] = df_f.apply(lambda r: geodesic((user_lat, user_lon), (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # กรองประเภทน้ำมัน
    if fuel_col and selected_fuels:
        pattern = '|'.join(selected_fuels)
        df_final = df_final[df_final[fuel_col].str.contains(pattern, case=False, na=False)]

    # --- 4. การแสดงผล Dashboard ---
    st.title("💰 ตรวจสอบราคาน้ำมันและสถานะ Real-time")
    
    # สรุปราคาสูงสุด-ต่ำสุดในรัศมี
    if price_col in df_final.columns and not df_final[price_col].isnull().all():
        c1, c2, c3 = st.columns(3)
        c1.metric("ราคาต่ำสุดในพื้นที่", f"{df_final[price_col].min():.2f} บาท")
        c2.metric("ราคาสูงสุดในพื้นที่", f"{df_final[price_col].max():.2f} บาท")
        c3.metric("ปั๊มที่พบในรัศมี", f"{len(df_final)} แห่ง")
    else:
        st.info("💡 หมายเหตุ: API ปัจจุบันอาจยังไม่ส่งข้อมูลราคาในรูปแบบตัวเลขมาให้ หรือไม่มีคอลัมน์ราคาสำหรับประเภทนี้")

    tab1, tab2 = st.tabs(["🗺️ แผนที่ราคาและพิกัด", "📋 ตารางเปรียบเทียบราคา"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        marker_cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            price_val = f"{row[price_col]:.2f} บาท" if price_col and not pd.isnull(row[price_col]) else "ไม่ระบุ"
            popup_html = f"""
                <div style='font-family: sans-serif;'>
                    <b>{row.get(name_col, 'N/A')}</b><br>
                    <span style='color:blue;'>ราคา: {price_val}</span><br>
                    ระยะทาง: {row['distance_km']:.2f} กม.<br>
                    น้ำมัน: {row.get(fuel_col, 'N/A')}
                </div>
            """
            folium.Marker(
                [row['latitude'], row['longitude']], 
                popup=folium.Popup(popup_html, max_width=200),
                icon=folium.Icon(color='green' if 'Available' in str(row.get('availability','')) else 'red', icon='info-sign')
            ).add_to(marker_cluster)
        folium_static(m, width=1100)

    with tab2:
        # แสดงตารางพร้อมราคา เรียงจากถูกที่สุดไปแพงที่สุด
        sort_col = price_col if price_col in df_final.columns else 'distance_km'
        display_cols = [name_col, 'distance_km', 'availability']
        if price_col: display_cols.append(price_col)
        if fuel_col: display_cols.append(fuel_col)
        
        st.subheader("📍 ปั๊มน้ำมันเรียงตามความคุ้มค่า")
        st.dataframe(df_final[display_cols].sort_values(sort_col), use_container_width=True)

else:
    st.warning("⚠️ กำลังรอข้อมูลจาก API...")
