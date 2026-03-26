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

# --- 2. ปรับแต่ง CSS เพื่อความคมชัดสูง (High Contrast Metric Boxes) ---
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

# --- 3. นิยามแบรนด์หลักและประเภทน้ำมัน ---
MAJOR_BRANDS = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

# เพิ่มรายการประเภทน้ำมันตัวอย่าง (E20, G91, G95 ฯลฯ)
AVAILABLE_FUEL_TYPES = ["E20", "G91", "G95", "Diesel", "Diesel B7", "Super Saver"]

# --- 4. ฟังก์ชันดึงและประมวลผลข้อมูล (Data Engine) ---
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
            
            # ดึงพิกัด
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c)>1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c)>1 else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # สร้างข้อมูลแบรนด์หลัก
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            df['raw_brand'] = df[name_col].astype(str).str.split().str[0].str.upper()
            df['major_brand'] = df['raw_brand'].apply(lambda x: x if x in MAJOR_BRANDS else "แบรนด์อื่นๆ")
            
            # จัดการสถานะ (Ready/Out)
            status_col = next((c for c in df.columns if 'avail' in c or 'status' in c), None)
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 น้ำมันหมด'
                if 'avail' in s: return '🟢 พร้อมบริการ'
                return '⚪ ไม่ทราบสถานะ'
            df['status_group'] = df[status_col].apply(map_status) if status_col else '⚪ ไม่ทราบสถานะ'
            
            # --- จัดการข้อมูลราคาและประเภทน้ำมัน (สร้างข้อมูลจำลองเพื่อการสาธิต) ---
            # *** ในระบบจริง ข้อมูลเหล่านี้ควรมาจาก API โดยตรง ***
            if 'price' not in df.columns:
                df['price'] = 30 + (df.index % 10) * 1.5 # สร้างราคาจำลอง 30-45 บาท
            if 'fuel_types' not in df.columns:
                # สร้างประเภทน้ำมันจำลองแบบ Comma-separated
                import random
                fuels_pool = AVAILABLE_FUEL_TYPES
                df['fuel_types'] = df.apply(lambda r: ",".join(random.sample(fuels_pool, random.randint(1, 4))), axis=1)
                
            return df, name_col, 'price', 'fuel_types'
        return pd.DataFrame(), None, None, None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None, None, None

# ดึงข้อมูลมาใช้งาน
df_raw, name_col, price_col, fuel_types_col = fetch_data()

# --- 5. ประมวลผลลอจิกขั้นสูงสำหรับสถิติรายน้ำมัน ---
# แตกข้อมูลประเภทน้ำมันแบบ comma-separated เป็นข้อมูลรายบรรทัด (Explode)
if not df_raw.empty:
    df_long_fuel = df_raw.assign(fuel_type=df_raw[fuel_types_col].str.split(',')).explode('fuel_type')
    df_long_fuel['fuel_type'] = df_long_fuel['fuel_type'].str.strip()

# --- 6. ส่วนควบคุมด้านข้าง (Sidebar Visual Filters & Contact) ---
LOGO_RSPG = "logo_rspg.png" 
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)
st.sidebar.markdown("<h4 style='text-align: center;'>โครงการ อพ.สธ. (สวนจิตรลดา)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    # --- ฟิลเตอร์เลือกแบรนด์ด้วย Logo ---
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    selected_brands = []
    brand_cols = st.sidebar.columns(3)
    for i, b in enumerate(MAJOR_BRANDS):
        if b in df_raw['major_brand'].values:
            with brand_cols[i % 3]:
                logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
                if os.path.exists(logo_path):
                    st.image(logo_path, width=35)
                else:
                    st.caption(b)
                if st.checkbox("", value=True, key=f"chk_{b}"):
                    selected_brands.append(b)
    
    # เพิ่มแบรนด์อื่นๆ
    if st.sidebar.checkbox("แบรนด์อื่นๆ (ท้องถิ่น)", value=True):
        selected_brands.extend([b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS])

    st.sidebar.markdown("---")
    # พื้นที่ปฏิบัติงานและรัศมี (จากสวนจิตรลดา)
    user_lat = st.sidebar.number_input("ละติจูด (สวนจิตรลดา)", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด (สวนจิตรลดา)", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    # ข้อมูลติดต่อผู้จัดทำ (Footer Sidebar)
    st.sidebar.markdown("---")
    st.sidebar.info("**จัดทำโดย:** แผนกวิชาการ อพ.สธ.\n📞 02-282-1850 | 📧 rspg.local@gmail.com")

# --- 7. ประมวลผลข้อมูลลอจิกหลัก ---
if not df_raw.empty:
    # 7.1 กรองตามแบรนด์
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    
    # 7.2 คำนวณระยะทางและกรองตามรัศมี (เป้าหมายคือ อพ.สธ. สวนจิตรลดา)
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    
    # แยกข้อมูลปั๊มที่น้ำมันหมดมาทำ Heatmap
    out_stock_df = df_final[df_final['status_group'] == '🔴 น้ำมันหมด']

    # 7.3 กรองข้อมูลสำหรับการวิเคราะห์ประเภทน้ำมัน (แตกบรรทัดไว้แล้ว)
    # กรองแบรนด์และพื้นที่เหมือนข้อมูลหลัก
    df_long_fuel_f = df_long_fuel[df_long_fuel['major_brand'].isin(selected_brands)].copy()
    df_long_fuel_f['distance_km'] = df_long_fuel_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_long_fuel_final = df_long_fuel_f[df_long_fuel_f['distance_km'] <= radius_km].copy()

    # --- 8. แสดงผล Dashboard ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    # 8.1 Metrics (สถิติรวมพื้นที่)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ปั๊มที่พบ (แห่ง)", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_stock_df), delta=f"-{len(out_stock_df)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_price = df_final[price_col].mean() if not df_final.empty else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_price:.2f} บ." if avg_p := avg_price > 0 else "N/A")

    # 8.2 Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗺️ แผนที่พิกัด & Heatmap", "📊 Market Share", "📍 10 อันดับใกล้ที่สุด", "📋 สรุปสถานะพื้นที่", "⛽ สถิติรายประเภทน้ำมัน"])

    with tab1:
        # แผนที่พิกัดและ Heatmap แสดงพื้นที่วิกฤต (น้ำมันหมด)
        st.subheader("🗺️ แผนที่พิกัดและความเสี่ยง (Heatmap: จุดน้ำมันหมด)")
        if not df_final.empty:
            m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
            
            # --- 1. เพิ่ม Heatmap (แสดงความหนาแน่นของจุดที่น้ำมันหมด) ---
            if not out_stock_df.empty:
                HeatMap([[r['latitude'], r['longitude']] for _, r in out_stock_df.iterrows()], radius=15).add_to(m)

            # --- 2. ปักหมุด สำนักงาน อพ.สธ. (หมุดพิเศษ ไม่ Cluster) ---
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
            | สัญลักษณ์ | ความหมาย |
            | :--- | :--- |
            | 🏛️ **หมุดสีแดงเข้ม** | **สำนักงาน อพ.สธ. (สวนจิตรลดา)** จุดวิเคราะห์กลาง |
            | 🟢 **หมุดสีเขียว** | สถานีบริการที่ **พร้อมบริการ** |
            | 🔴 **หมุดสีแดง** | สถานีบริการที่ **น้ำมันหมด** |
            | 🔥 **แถบสี (Heatmap)** | โซนที่มีน้ำมันหมดหนาแน่น (**สีแดงเข้ม** = ความเสี่ยงสูงสุด) |
            """)
        else:
            st.warning("⚠️ ไม่พบข้อมูลสถานีน้ำมันในเงื่อนไขที่เลือก")

    with tab2:
        # ส่วนแบ่งแบรนด์ (Market Share)
        st.subheader("🏢 ส่วนแบ่งแบรนด์หลัก (รวมทุกสาขาย่อย)")
        fig = px.pie(df_final, names='major_brand', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
        fig.update_traces(textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        # 10 อันดับสถานีที่ใกล้สวนจิตรลดาที่สุด
        st.subheader("📍 10 อันดับสถานีที่ใกล้ที่สุด")
        top_10 = df_final.sort_values('distance_km').head(10)
        if not top_10.empty:
            fig_b = px.bar(top_10, x='distance_km', y=name_col, orientation='h', color='distance_km', text_auto='.2f')
            fig_b.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_b, use_container_width=True)

    with tab4:
        # สรุปสถานะรายแบรนด์และข้อมูลดิบ
        st.subheader("📋 สรุปสถานะรายแบรนด์ (Ready/Out Matrix)")
        sum_t = pd.crosstab(df_final['major_brand'], df_final['status_group']).reset_index()
        st.table(sum_t)
        
        st.markdown("---")
        st.subheader("📋 ข้อมูลและระบบนำทาง (Google Maps)")
        df_final['Google Maps'] = df_final.apply(lambda r: f"https://www.google.com/maps/dir/?api=1&destination={r['latitude']},{r['longitude']}", axis=1)
        st.dataframe(df_final[[name_col, 'major_brand', 'distance_km', 'status_group', fuel_types_col, 'Google Maps']].sort_values('distance_km'),
                     column_config={"Google Maps": st.column_config.LinkColumn("🗺️ นำทาง")}, hide_index=True)

    with tab5:
        # --- ใหม่: Tab สถิติรายประเภทน้ำมัน (E20, G91, G95 ฯลฯ) ---
        st.subheader("⛽ สถิติและราคาเฉลี่ยแยกตามประเภทน้ำมัน (Fuel Type Statistics)")
        
        # 5.1 ฟิลเตอร์เลือกประเภทน้ำมัน
        all_avail_fuels = sorted(df_long_fuel_final['fuel_type'].dropna().unique())
        selected_fuels = st.multiselect("เลือกประเภทน้ำมันเพื่อดูสถิติ", all_avail_fuels, default=["G91", "G95", "Diesel"])
        
        if selected_fuels:
            # กรองข้อมูลตามประเภทน้ำมันที่เลือก
            df_long_f_f_filtered = df_long_fuel_final[df_long_fuel_final['fuel_type'].isin(selected_fuels)]
            
            # 5.2 Metrics รายประเภทน้ำมัน
            c1, c2 = st.columns(2)
            fuel_counts = df_long_f_f_filtered.groupby('fuel_type').size().sort_values(ascending=False)
            c1.write("**จำนวนสถานีแยกตามประเภทน้ำมันที่เลือก:**")
            c1.table(fuel_counts)
            
            fuel_prices = df_long_f_f_filtered.groupby('fuel_type')[price_col].mean().sort_values().reset_index()
            fuel_prices.columns = ['ประเภทน้ำมัน', 'ราคาเฉลี่ย (บาท)']
            c2.write("**ราคาเฉลี่ยแยกตามประเภทน้ำมันที่เลือก:**")
            c2.table(fuel_prices.sort_values('ราคาเฉลี่ย (บาท)').reset_index(drop=True))

            # 5.3 กราฟ
            st.markdown("---")
            gc1, gc2 = st.columns(2)
            
            with gc1:
                # กราฟราคาเฉลี่ย
                st.write("**💰 กราฟราคาเฉลี่ยรายประเภทน้ำมัน**")
                fig_f_price = px.bar(fuel_prices, x='ประเภทน้ำมัน', y='ราคาเฉลี่ย (บาท)', color='ประเภทน้ำมัน', text_auto='.2f')
                st.plotly_chart(fig_f_price, use_container_width=True)
                
            with gc2:
                # กราฟจำนวนสถานี
                st.write("**⛽ กราฟจำนวนสถานีที่ให้บริการน้ำมันแต่ละประเภท**")
                fig_f_count = px.bar(df_long_f_f_filtered, x='fuel_type', color='major_brand', title="จำนวนสถานีรายแบรนด์")
                fig_f_count.update_layout(xaxis_title="ประเภทน้ำมัน", yaxis_title="จำนวนสถานี (แห่ง)")
                st.plotly_chart(fig_f_count, use_container_width=True)

        else:
            st.warning("⚠️ กรุณาเลือกประเภทน้ำมันอย่างน้อย 1 ประเภท")

else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API...")
