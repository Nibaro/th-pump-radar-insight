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

# --- 2. CSS เพื่อความคมชัดสูง (High Contrast) ---
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
    /* จัดระเบียบ Sidebar Logo */
    [data-testid="stSidebar"] [data-testid="column"] { display: flex; align-items: center; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. นิยามแบรนด์หลัก ---
MAJOR_BRANDS = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

# --- 4. ฟังก์ชันดึงข้อมูล (API Engine) ---
@st.cache_data(ttl=600)
def fetch_data():
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." # ตรวจสอบ URL ของคุณ
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
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_col].apply(map_status) if status_col else '⚪ ไม่ทราบสถานะ'
            
            price_col = next((c for c in df.columns if 'price' in c), None)
            if price_col: df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
                
            return df, name_col, price_col
        return pd.DataFrame(), None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None

df_raw, name_col, price_col = fetch_data()

# --- 5. Sidebar (Filters & Contact) ---
LOGO_RSPG = "logo_rspg.png"
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    for b in MAJOR_BRANDS:
        if b in df_raw['major_brand'].values:
            b_cols = st.sidebar.columns([1, 4])
            logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
            with b_cols[0]:
                if os.path.exists(logo_path): st.image(logo_path, width=35)
            with b_cols[1]:
                if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        selected_brands.extend([b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS])

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด (สวนจิตรลดา)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (สวนจิตรลดา)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

st.sidebar.markdown("---")
st.sidebar.info("**จัดทำโดย:** แผนกวิชาการ อพ.สธ.\n📞 02-282-1850 | 📧 rspg.local@gmail.com")

# --- 6. Main Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    
    # แยกข้อมูลปั๊มที่น้ำมันหมดมาทำ Heatmap
    out_stock = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']

    # --- 7. Dashboard Display ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ปั๊มในพื้นที่", len(df_final))
    c2.metric("น้ำมันหมด", len(out_stock), delta=f"-{len(out_stock)}", delta_color="inverse")
    c3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_v = df_final[price_col].mean() if price_col and not df_final.empty else 0
    c4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_v:.2f} บ." if avg_v > 0 else "N/A")

    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัด & Heatmap", "📊 Market Share", "📍 10 อันดับใกล้ที่สุด", "📋 สรุปสถานะ & นำทาง"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัดและความเสี่ยง (Heatmap: จุดน้ำมันหมด)")
        if not df_final.empty:
            m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
            
            # --- 1. เพิ่ม Heatmap (แสดงความหนาแน่นของจุดที่น้ำมันหมด) ---
            if not out_stock.empty:
                heat_data = [[row['latitude'], row['longitude']] for _, row in out_stock.iterrows()]
                HeatMap(
                    heat_data, 
                    radius=15, 
                    blur=10, 
                    gradient={0.4: 'yellow', 0.65: 'orange', 1: 'red'}
                ).add_to(m)

            # --- 2. ปักหมุด สำนักงาน อพ.สธ. ---
            folium.Marker(
                location=my_loc,
                popup="<b>สำนักงาน อพ.สธ. (สวนจิตรลดา)</b>",
                icon=folium.Icon(color='darkred', icon='university', prefix='fa')
            ).add_to(m)

            # --- 3. Marker Cluster สำหรับสถานีบริการ ---
            cluster = MarkerCluster().add_to(m)
            for _, row in df_final.iterrows():
                color = 'red' if 'หมด' in row['status_group'] else 'green'
                clean_name = str(row[name_col]).replace("'", "\\'")
                nav_url = f"https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']}"
                popup_h = f"<b>{clean_name}</b><br>ห่าง: {row['distance_km']:.2f} กม.<br><a href='{nav_url}' target='_blank'>📍 นำทาง</a>"
                folium.Marker([row['latitude'], row['longitude']], 
                              popup=folium.Popup(popup_h, max_width=200),
                              icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
            
            folium_static(m, width=1100)
            
            # --- คำอธิบายสัญลักษณ์ ---
            st.markdown("""
            ### 🏛️ คำอธิบายสัญลักษณ์ (Legend)
            * 🏛️ **หมุดสีแดงเข้ม** : สำนักงาน อพ.สธ. (จุดวิเคราะห์กลาง)
            * 🟢 **หมุดสีเขียว** : สถานีบริการที่ **พร้อมบริการ**
            * 🔴 **หมุดสีแดง** : สถานีบริการที่ **น้ำมันหมด**
            * 🔥 **แถบสี (Heatmap)** : โซนที่มีน้ำมันหมดหนาแน่น (**สีแดงเข้ม** = ความเสี่ยงสูงสุด)
            """)
        else:
            st.warning("⚠️ ไม่พบข้อมูลสถานีน้ำมันในเงื่อนไขที่เลือก")

    with tab2:
        st.subheader("🏢 ส่วนแบ่งแบรนด์หลัก")
        fig = px.pie(df_final, names='major_brand', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("📍 10 อันดับสถานีที่ใกล้ที่สุด")
        top_10 = df_final.sort_values('distance_km').head(10)
        if not top_10.empty:
            fig_b = px.bar(top_10, x='distance_km', y=name_col, orientation='h', color='distance_km', text_auto='.2f')
            fig_b.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_b, use_container_width=True)

    with tab4:
        st.subheader("📋 สรุปสถานะรายแบรนด์")
        sum_t = pd.crosstab(df_final['major_brand'], df_final['status_group']).reset_index()
        st.table(sum_t)
        st.markdown("---")
        st.subheader("📋 ข้อมูลและระบบนำทาง")
        df_final['Google Maps'] = df_final.apply(lambda r: f"https://www.google.com/maps/dir/?api=1&destination={r['latitude']},{r['longitude']}", axis=1)
        st.dataframe(df_final[[name_col, 'major_brand', 'distance_km', 'status_group', 'Google Maps']].sort_values('distance_km'),
                     column_config={"Google Maps": st.column_config.LinkColumn("🗺️ นำทาง")}, hide_index=True)
else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API...") 
