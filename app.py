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
            
            name_c = next((c for c in df.columns if 'name' in c or 'station' in c), "station_name")
            price_c = next((c for c in df.columns if 'price' in c), "price")
            fuel_c = next((c for c in df.columns if 'fuel' in c or 'type' in c), "fuel_types")
            
            df['major_brand'] = df[name_c].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['major_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            status_c = next((c for c in df.columns if 'avail' in c or 'status' in c), "status")
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_c].apply(map_status) if status_c in df.columns else '⚪ ไม่ทราบสถานะ'
            
            if price_c in df.columns: 
                df[price_c] = pd.to_numeric(df[price_c], errors='coerce').fillna(0)
            else:
                df[price_c] = 0
                
            if fuel_c not in df.columns:
                df[fuel_c] = "G95, G91, E20"
                
            return df, name_c, price_c, fuel_c
        return pd.DataFrame(), "name", "price", "fuel"
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), "name", "price", "fuel"

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
            if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        selected_brands.extend([b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS])

    user_lat, user_lon = 13.769068, 100.524251 # สวนจิตรลดา
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

# --- 6. Main Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    out_stock = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']
    
    avg_p = df_final[price_col].mean() if not df_final.empty else 0

    st.title("⛽ ระบบสารสนเทศ อพ.สธ. (RSPG Fuel Logistics)")
    
    # 7.1 Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ปั๊มในพื้นที่", len(df_final))
    c2.metric("น้ำมันหมด", len(out_stock), delta=f"-{len(out_stock)}", delta_color="inverse")
    c3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    c4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_p:.2f} บ." if avg_p > 0 else "N/A")

    # 7.2 Tab Setup (จัดเรียงย่อหน้าใหม่)
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🗺️ แผนที่พิกัด & Heatmap", 
        "📊 Market Share", 
        "📍 10 อันดับใกล้ที่สุด", 
        "📋 สรุปสถานะ", 
        "⛽ สถิติประเภทน้ำมัน"
    ])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัดและความเสี่ยงเชิงพื้นที่")
        if not df_final.empty:
            m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
            if not out_stock.empty:
                HeatMap([[r['latitude'], r['longitude']] for _, r in out_stock.iterrows()], radius=15).add_to(m)
            folium.Marker(location=my_loc, popup="สนง. อพ.สธ.", icon=folium.Icon(color='darkred', icon='university', prefix='fa')).add_to(m)
            cluster = MarkerCluster().add_to(m)
            for _, row in df_final.iterrows():
                color = 'red' if 'หมด' in row['status_group'] else 'green'
                folium.Marker([row['latitude'], row['longitude']], popup=row[name_col], icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
            folium_static(m, width=1100)
        else:
            st.warning("⚠️ ไม่พบข้อมูลในรัศมีที่เลือก")

    with tab2:
        st.subheader("🏢 ส่วนแบ่งแบรนด์หลัก (Market Share)")
        if not df_final.empty:
            fig_p = px.pie(df_final, names='major_brand', hole=0.4)
            st.plotly_chart(fig_p, use_container_width=True)

    with tab3:
        st.subheader("📍 10 อันดับสถานีที่ใกล้สวนจิตรลดาที่สุด")
        if not df_final.empty:
            top_10 = df_final.sort_values('distance_km').head(10)
            fig_b = px.bar(top_10, x='distance_km', y=name_col, orientation='h', color='distance_km', text_auto='.2f')
            fig_b.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_b, use_container_width=True)

    with tab4:
        st.subheader("📋 สรุปสถานะรายแบรนด์")
        if not df_final.empty:
            sum_t = pd.crosstab(df_final['major_brand'], df_final['status_group']).reset_index()
            st.table(sum_t)
            st.markdown("---")
            st.subheader("📋 ตารางข้อมูลนำทาง")
            df_final['Maps'] = df_final.apply(lambda r: f"https://www.google.com/maps/dir/?api=1&destination={r['latitude']},{r['longitude']}", axis=1)
            st.dataframe(df_final[[name_col, 'major_brand', 'distance_km', 'status_group', 'Maps']].sort_values('distance_km'),
                         column_config={"Maps": st.column_config.LinkColumn("🗺️ นำทาง")}, hide_index=True)

    with tab5:
        st.subheader("⛽ สถิติแยกตามประเภทน้ำมัน (E20, G91, G95)")
        if not df_final.empty and fuel_col in df_final.columns:
            df_fuel = df_final.assign(fuel=df_final[fuel_col].str.split(',')).explode('fuel')
            df_fuel['fuel'] = df_fuel['fuel'].str.strip().str.upper()
            fuel_sum = df_fuel.groupby('fuel').agg({name_col: 'count', price_col: 'mean'}).reset_index()
            fuel_sum.columns = ['ประเภทน้ำมัน', 'จำนวนปั๊ม', 'ราคาเฉลี่ย']
            st.table(fuel_sum.sort_values('จำนวนปั๊ม', ascending=False))
        else:
            st.info("ℹ️ ไม่พบข้อมูลประเภทน้ำมัน")

    st.sidebar.markdown("---")
    st.sidebar.info("""
    **จัดทำโดย:** แผนกวิชาการ อพ.สธ.
    📞 02-282-1850 | 📧 rspg.local@gmail.com
    """)
else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API...")
