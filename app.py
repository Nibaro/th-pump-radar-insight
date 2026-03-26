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
st.set_page_config(page_title="RSPG Fuel Logistics & Mapping", layout="wide", page_icon="⛽")

# --- 2. CSS เพื่อความคมชัด ---
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
            
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            df['raw_brand'] = df[name_col].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['raw_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            status_col = next((c for c in df.columns if 'avail' in c or 'status' in c), None)
            if status_col:
                def map_status(s):
                    s = str(s).lower()
                    if 'out' in s: return '🔴 น้ำมันหมด'
                    if 'avail' in s: return '🟢 พร้อมบริการ'
                    return '⚪ ไม่ทราบสถานะ'
                df['status_group'] = df[status_col].apply(map_status)
            else:
                df['status_group'] = '⚪ ไม่ทราบสถานะ'
            
            price_col = next((c for c in df.columns if 'price' in c), None)
            if price_col: df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
                
            return df, name_col, price_col
        return pd.DataFrame(), None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None

df_raw, name_col, price_col = fetch_data()

# --- 5. Sidebar ---
LOGO_RSPG = "logo_rspg.png"
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    brand_cols = st.sidebar.columns(3)
    for i, b in enumerate(MAJOR_BRANDS):
        with brand_cols[i % 3]:
            logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
            if os.path.exists(logo_path): st.sidebar.image(logo_path, width=40)
            if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True): selected_brands.append("แบรนด์อื่นๆ")

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด (เป้าหมาย)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (เป้าหมาย)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

# --- 6. Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    df_final['map_link'] = df_final.apply(lambda r: f"https://www.google.com/maps/search/?api=1&query={r['latitude']},{r['longitude']}", axis=1)

    # --- 7. Dashboard Display ---
    st.title("⛽ RSPG Fuel Logistics & Spatial Mapping")
    
    m1, m2, m3, m4 = st.columns(4)
    out_stock_df = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']
    m1.metric("ปั๊มในพื้นที่", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_stock_df), delta=f"-{len(out_stock_df)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_p = df_final[price_col].mean() if price_col and not df_final.empty else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_p:.2f} บ." if avg_p > 0 else "N/A")

    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่ความร้อน & พิกัด", "📊 Market Share", "📍 10 อันดับใกล้ที่สุด", "📋 ตารางข้อมูล"])

    with tab1:
        st.subheader("🗺️ แผนที่วิเคราะห์ความหนาแน่นและพิกัด")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        
        # --- [ใหม่] เพิ่ม HeatMap Layer ---
        if not df_final.empty:
            heat_data = [[row['latitude'], row['longitude']] for index, row in df_final.iterrows()]
            HeatMap(heat_data, radius=15, blur=10, name="Heatmap Density").add_to(m)

        # เพิ่ม Marker พิกัดเป้าหมาย (สวนจิตรลดา)
        folium.Marker(my_loc, popup="จุดเป้าหมาย (สวนจิตรลดา)", icon=folium.Icon(color='darkred', icon='university', prefix='fa')).add_to(m)

        # เพิ่ม Cluster ของปั๊มน้ำมัน
        cluster = MarkerCluster(name="Gas Stations").add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'หมด' in row['status_group'] else 'green'
            popup_html = f"<b>{row[name_col]}</b><br>สถานะ: {row['status_group']}<br><a href='{row['map_link']}' target='_blank'>📍 นำทาง</a>"
            folium.Marker([row['latitude'], row['longitude']], 
                          popup=folium.Popup(popup_html, max_width=250), 
                          icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
        
        folium.LayerControl().add_to(m) # เพิ่มเมนูเปิด-ปิด Layer
        folium_static(m, width=1100)

    # ... [Tab อื่นๆ ทำงานได้ปกติเหมือนเดิม] ...
    with tab2:
        fig_pie = px.pie(df_final, names='major_brand', hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)

    with tab3:
        top_10 = df_final.sort_values('distance_km').head(10)
        fig_near = px.bar(top_10, x='distance_km', y=name_col, orientation='h', text_auto='.2f')
        st.plotly_chart(fig_near, use_container_width=True)

    with tab4:
        st.dataframe(df_final[[name_col, 'major_brand', 'distance_km', 'status_group', 'map_link']], use_container_width=True)

else:
    st.warning("⚠️ ไม่พบข้อมูลในรัศมีที่เลือก")
