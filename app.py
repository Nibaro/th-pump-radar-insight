import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster, HeatMap
from geopy.distance import geodesic
import plotly.express as px
import os

# --- 1. การตั้งค่าหน้าเว็บ (Page Config) ---
st.set_page_config(
    page_title="RSPG Fuel Logistics & Spatial Mapping", 
    layout="wide", 
    page_icon="⛽"
)

# --- 2. CSS เพื่อความคมชัดสูง (High Contrast UI) ---
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    /* ปรับแต่งกล่อง Metric: ตัวเลขน้ำเงินเข้ม หัวข้อดำเข้ม พื้นขาว */
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 2px solid #003366 !important;
        padding: 20px !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15) !important;
    }
    [data-testid="stMetricLabel"] {
        color: #000000 !important;
        font-weight: bold !important;
        font-size: 1.1rem !important;
    }
    [data-testid="stMetricValue"] {
        color: #003366 !important;
        font-weight: 800 !important;
        font-size: 2.2rem !important;
    }
    .st-expander { background-color: #ffffff !important; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. นิยามแบรนด์หลัก ---
MAJOR_BRANDS = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

# --- 4. ฟังก์ชันดึงข้อมูล (API Engine) ---
@st.cache_data(ttl=600)
def fetch_data():
    # *** กรุณาใส่ URL เต็มที่มี Token ของคุณที่นี่ ***
    API_URL = "https://thaipumpradar.com/api/export?fbclid=..." 
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
            
            # สร้างข้อมูลแบรนด์หลัก (รวมสาขาย่อย)
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            df['raw_brand'] = df[name_col].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['raw_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            # จัดการสถานะการให้บริการ
            status_col = next((c for c in df.columns if 'avail' in c or 'status' in c), None)
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_col].apply(map_status) if status_col else '⚪ ไม่ทราบสถานะ'
            
            # จัดการราคา
            price_col = next((c for c in df.columns if 'price' in c), None)
            if price_col: df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
                
            return df, name_col, price_col
        return pd.DataFrame(), None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None

df_raw, name_col, price_col = fetch_data()

# --- 5. Sidebar (Visual Filters & Contact) ---
LOGO_PATH = "logo_rspg.png"
if os.path.exists(LOGO_PATH): st.sidebar.image(LOGO_PATH, use_container_width=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    brand_cols = st.sidebar.columns(3)
    for i, b in enumerate(MAJOR_BRANDS):
        with brand_cols[i % 3]:
            img_p = os.path.join("brand_logos", f"{b.lower()}.png")
            if os.path.exists(img_p): st.image(img_p, use_container_width=True)
            if st.checkbox(b, value=True, key=f"chk_{b}"): selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True): selected_brands.append("แบรนด์อื่นๆ")

    st.sidebar.markdown("---")
    user_lat = st.sidebar.number_input("ละติจูด (สวนจิตรลดา)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (สวนจิตรลดา)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

# ข้อมูลติดต่อหน่วยงาน
st.sidebar.markdown("---")
st.sidebar.info("""
**จัดทำโดย:** แผนกวิชาการ  
โครงการอนุรักษ์พันธุกรรมพืชอันเนื่องมาจากพระราชดำริฯ (อพ.สธ.)  
📞 **โทร:** 02-282-1850  
📧 **อีเมล์:** rspg.local@gmail.com  
🌐 **เว็บไซต์:** [www.rspg.or.th](https://www.rspg.or.th/)
""")

# --- 6. Processing ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # สร้างลิงก์นำทาง Google Maps
    df_final['map_link'] = df_final.apply(lambda r: f"https://www.google.com/maps/dir/?api=1&destination={r['latitude']},{r['longitude']}", axis=1)

    # --- 7. Dashboard Display ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศสถานะน้ำมันเชื้อเพลิงรายสถานี เพื่อการวางแผนเชื้อเพลิงของเจ้าหน้าที่ อพ.สธ. (RSPG Fuel Logistics & Spatial Mapping)")
    
    # 7.1 Metrics
    m1, m2, m3, m4 = st.columns(4)
    out_df = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']
    m1.metric("ปั๊มในพื้นที่", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_df), delta=f"-{len(out_df)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_p = df_final[price_col].mean() if price_col and not df_final.empty else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_p:.2f} บ." if avg_p > 0 else "N/A")

    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัด", "📊 Market Share", "📍 10 อันดับปั๊มใกล้ที่สุด", "📋 สรุปสถานะ & นำทาง"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัด (Heatmap แสดงจุดเสี่ยงน้ำมันหมด)")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        if not out_df.empty:
            HeatMap([[r['latitude'], r['longitude']] for _, r in out_df.iterrows()], radius=15).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'หมด' in row['status_group'] else 'green'
            popup_html = f"""
                <div style="font-family: sans-serif; min-width: 150px;">
                    <b>{row[name_col]}</b><br>
                    สถานะ: {row['status_group']}<br>
                    ห่าง: {row['distance_km']:.2f} กม.<br><br>
                    <a href="{row['map_link']}" target="_blank" 
                       style="background-color: #4285F4; color: white; padding: 5px 10px; border-radius: 5px; text-decoration: none; display: block; text-align: center;">
                       📍 นำทาง
                    </a>
                </div>
            """
            folium.Marker([row['latitude'], row['longitude']], 
                          popup=folium.Popup(popup_html, max_width=250), 
                          icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        st.subheader("🏢 ส่วนแบ่งแบรนด์หลัก (รวมทุกสาขาย่อย)")
        fig_pie = px.pie(df_final, names='major_brand', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
        fig_pie.update_traces(textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)

    with tab3:
        st.subheader("📍 10 อันดับสถานีที่ใกล้สวนจิตรลดาที่สุด")
        top_10 = df_final.sort_values('distance_km').head(10)
        if not top_10.empty:
            fig_near = px.bar(top_10, x='distance_km', y=name_col, orientation='h', color='distance_km', text_auto='.2f')
            fig_near.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_near, use_container_width=True)

    with tab4:
        st.subheader("📋 สรุปสถานะเชื้อเพลิงรายแบรนด์ (Status by Brand)")
        # ตารางสรุป: แบรนด์ | พร้อม | หมด | ไม่ทราบ
        sum_table = pd.crosstab(df_final['major_brand'], df_final['status_group']).reset_index()
        for s in ['🟢 พร้อมบริการ', '🔴 น้ำมันหมด', '⚪ ไม่ทราบสถานะ']:
            if s not in sum_table.columns: sum_table[s] = 0
        sum_table = sum_table[['major_brand', '🟢 พร้อมบริการ', '🔴 น้ำมันหมด', '⚪ ไม่ทราบสถานะ']]
        sum_table.columns = ['แบรนด์', 'พร้อมบริการ', 'น้ำมันหมด', 'ไม่ทราบสถานะ']
        st.table(sum_table.sort_values('พร้อมบริการ', ascending=False))
        
        st.markdown("---")
        st.subheader("📋 ตารางข้อมูลสถานีและระบบนำทาง")
        st.dataframe(
            df_final[[name_col, 'major_brand', 'distance_km', 'status_group', 'map_link']].sort_values('distance_km'),
            column_config={
                "map_link": st.column_config.LinkColumn("📍 นำทาง", display_text="Google Maps"),
                "distance_km": st.column_config.NumberColumn("ห่าง (กม.)", format="%.2f")
            },
            use_container_width=True, hide_index=True
        )

else:
    st.warning("⚠️ ไม่พบข้อมูล กรุณาตรวจสอบ API หรือขยายรัศมีวิเคราะห์")
