import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- ตั้งค่าหน้าเว็บและสไตล์ ---
st.set_page_config(page_title="TH Pump Radar Insight", layout="wide", page_icon="⛽")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    [data-testid="stSidebar"] { background-color: #f0f2f6; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. ฟังก์ชันดึงและประมวลผลข้อมูล (API Ingestion) ---
@st.cache_data(ttl=600)
def fetch_data():
    # กรุณาตรวจสอบว่าใส่ URL เต็มที่มี Token (fbclid) ของคุณ
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
    try:
        response = requests.get(API_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and 'features' in data:
            # Flatten ข้อมูล GeoJSON
            df = pd.json_normalize(data['features'])
            
            # ลบคำนำหน้า properties. และทำเป็นตัวพิมพ์เล็ก
            df.columns = [c.replace('properties.', '').lower() for c in df.columns]
            
            # ดึงพิกัดจาก geometry.coordinates (ปกติเป็น [longitude, latitude])
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c) > 1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c) > 1 else None for c in coords]
            
            # แปลงค่าเป็นตัวเลขและจัดการค่าว่าง
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # ตั้งค่าเริ่มต้นสถานะหากไม่มีข้อมูล
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
                
            return df
        else:
            st.error("⚠️ โครงสร้างข้อมูล API ไม่ถูกต้อง")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ การเชื่อมต่อ API ขัดข้อง: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 2. ส่วนควบคุมด้านข้าง (Sidebar Filters) ---
st.sidebar.title("⛽ ตัวเลือกการวิเคราะห์")

if not df_raw.empty:
    st.sidebar.subheader("📍 เลือกพื้นที่วิเคราะห์")
    
    # --- ฟังก์ชันช่วย Sort ข้อมูลที่ทนทานต่อค่าว่าง (Fix TypeError) ---
    def get_safe_unique(df, col):
        if col in df.columns:
            items = df[col].dropna().unique()
            return sorted([str(i) for i in items])
        return []

    # 1. จังหวัด
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    provinces = get_safe_unique(df_raw, prov_col)
    selected_prov = st.sidebar.selectbox("จังหวัด", ["ทั้งหมด"] + provinces)

    # 2. อำเภอ (กรองตามจังหวัด)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'district' in c), None)
    if selected_prov != "ทั้งหมด" and dist_col:
        mask_prov = df_raw[prov_col] == selected_prov
        districts = get_safe_unique(df_raw[mask_prov], dist_col)
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"] + districts)
    else:
        selected_dist = st.sidebar.selectbox("อำเภอ", ["ทั้งหมด"], disabled=True)

    # 3. ตำบล (กรองตามอำเภอ)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'subdistrict' in c), None)
    if selected_dist != "ทั้งหมด" and subdist_col:
        mask_dist = (df_raw[prov_col] == selected_prov) & (df_raw[dist_col] == selected_dist)
        subdistricts = get_safe_unique(df_raw[mask_dist], subdist_col)
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"] + subdistricts)
    else:
        selected_subdist = st.sidebar.selectbox("ตำบล", ["ทั้งหมด"], disabled=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("📐 พิกัดและรัศมีค้นหา")
    # พิกัดบ้าน (บางพูด ปากเกร็ด)
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    fuel_options = ['E20', '91', '95', 'G91', 'G95', 'Diesel', 'B7']
    selected_fuels = st.sidebar.multiselect("ประเภทน้ำมัน", fuel_options, default=['E20', '95'])

# --- 3. การประมวลผล Logic การกรอง ---
if not df_raw.empty:
    df_final = df_raw.copy()
    
    # กรองเชิงพื้นที่
    if selected_prov != "ทั้งหมด": df_final = df_final[df_final[prov_col] == selected_prov]
    if selected_dist != "ทั้งหมด": df_final = df_final[df_final[dist_col] == selected_dist]
    if selected_subdist != "ทั้งหมด": df_final = df_final[df_final[subdist_col] == selected_subdist]

    # คำนวณระยะทาง
    my_loc = (user_lat, user_lon)
    df_final['distance_km'] = df_final.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    
    # กรองตามรัศมี
    df_final = df_final[df_final['distance_km'] <= radius_km].copy()
    
    # กรองประเภทน้ำมัน
    if 'fuel_type' in df_final.columns and selected_fuels:
        pattern = '|'.join(selected_fuels)
        df_final = df_final[df_final['fuel_type'].str.contains(pattern, case=False, na=True)]

    # --- 4. การแสดงผล Dashboard ---
    st.title("📊 ระบบติดตามสถานการณ์น้ำมัน (RSPG Insight)")
    st.caption(f"📍 วิเคราะห์รอบพิกัด {user_lat}, {user_lon} | รัศมี {radius_km} กม.")

    # แถบสรุปตัวเลข
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ปั๊มที่พบ", len(df_final))
    out_of_stock = len(df_final[df_final['availability'].str.contains('Out', na=False, case=False)])
    c2.metric("น้ำมันหมด (แห่ง)", out_of_stock, delta=f"-{out_of_stock}" if out_of_stock > 0 else 0, delta_color="inverse")
    c3.metric("ปั๊มที่ใกล้ที่สุด", f"{df_final['distance_km'].min():.2f} กม." if not df_final.empty else "N/A")
    c4.metric("พื้นที่เป้าหมาย", selected_subdist if selected_subdist != "ทั้งหมด" else "หลายตำบล")

    tab1, tab2, tab3 = st.tabs(["🗺️ แผนที่พิกัด", "📈 การวิเคราะห์ระยะทาง", "📋 รายละเอียดสถานี"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        folium.Circle([user_lat, user_lon], radius=radius_km*1000, color='blue', fill=True, opacity=0.1).add_to(m)
        folium.Marker([user_lat, user_lon], popup="คุณอยู่ที่นี่", icon=folium.Icon(color='red', icon='home')).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            status_color = 'red' if 'Out' in str(row['availability']) else 'green'
            popup_html = f"<b>{row.get('station_name', 'N/A')}</b><br>ห่าง: {row['distance_km']:.2f} กม.<br>สถานะ: {row['availability']}"
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color=status_color, icon='gas-pump', prefix='fa')
            ).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        if not df_final.empty:
            top_15 = df_final.sort_values('distance_km').head(15)
            fig = px.bar(top_15, x='station_name', y='distance_km', color='distance_km',
                         title="15 ปั๊มน้ำมันที่ใกล้ที่สุด", labels={'distance_km': 'ระยะทาง (กม.)'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่มีข้อมูลแสดงสถิติ")

    with tab3:
        cols = ['station_name', 'distance_km', 'availability', 'fuel_type']
        if subdist_col in df_final.columns: cols.insert(1, subdist_col)
        st.dataframe(df_final[cols].sort_values('distance_km'), use_container_width=True)
        
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงานพื้นที่ (CSV)", data=csv, file_name='fuel_report.csv', mime='text/csv')

else:
    st.warning("⚠️ ไม่พบข้อมูล... กรุณาตรวจสอบการเชื่อมต่อ API หรือปรับการตั้งค่าการกรอง")
