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
    /* ปรับแต่งกล่อง Metric ให้อ่านง่ายที่สุด: ตัวเลขน้ำเงินเข้ม หัวข้อดำเข้ม */
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
    /* ปรับแต่งตารางและส่วนขยาย */
    .st-expander { background-color: #ffffff !important; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. นิยามแบรนด์หลัก ---
MAJOR_BRANDS_LIST = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]

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
            
            # ดึงพิกัดจาก GeoJSON
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c)>1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c)>1 else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # ค้นหาคอลัมน์ชื่อสถานีและสร้างแบรนด์หลัก
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            df['major_brand'] = df[name_col].astype(str).str.split().str[0].str.upper()
            
            # จัดการราคา
            price_cols = [c for c in df.columns if 'price' in c]
            for col in price_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if 'availability' not in df.columns: df['availability'] = 'Available'
            if 'fuel_type' not in df.columns: df['fuel_type'] = 'Unknown'
            return df, name_col
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame(), None

df_raw, station_name_col = fetch_data()

# --- 5. ส่วนควบคุมด้านข้าง (Sidebar Visual Filters) ---
LOGO_RSPG = "logo_rspg.png" 
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)
st.sidebar.markdown("<h4 style='text-align: center;'>โครงการอนุรักษ์พันธุกรรมพืชฯ (อพ.สธ.)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    def get_safe_unique(df, col):
        if col and col in df.columns:
            items = df[col].dropna().unique()
            return sorted([str(i) for i in items])
        return []

    # คัดกรองแบรนด์สถานีด้วย Logo
    st.sidebar.subheader("🏢 คัดกรองแบรนด์สถานี")
    selected_brands = []
    brand_cols = st.sidebar.columns(3)
    for i, b in enumerate(MAJOR_BRANDS_LIST):
        if b in df_raw['major_brand'].values:
            with brand_cols[i % 3]:
                logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
                if os.path.exists(logo_path):
                    st.image(logo_path, use_container_width=True)
                else:
                    st.caption(f"**{b}**")
                if st.checkbox("", value=True, key=f"chk_{b}"):
                    selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        others = [b for b in df_raw['major_brand'].unique() if b not in MAJOR_BRANDS_LIST]
        selected_brands.extend(others)

    st.sidebar.markdown("---")
    # พื้นที่ปฏิบัติงาน
    st.sidebar.subheader("📍 พื้นที่ปฏิบัติงาน")
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    
    sel_prov = st.sidebar.selectbox("เลือกจังหวัด", ["ทั้งหมด"] + get_safe_unique(df_raw, prov_col))
    df_p = df_raw.copy()
    if sel_prov != "ทั้งหมด": df_p = df_p[df_p[prov_col] == sel_prov]
    sel_dist = st.sidebar.selectbox("เลือกอำเภอ", ["ทั้งหมด"] + get_safe_unique(df_p, dist_col))

    st.sidebar.markdown("---")
    # พิกัดจุดวิเคราะห์ (สวนจิตรลดา)
    st.sidebar.subheader("⛽ จุดวิเคราะห์ (สวนจิตรลดา)")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    st.sidebar.info(f"**ผู้จัดทำ:** นายนิรุตติ์ บาโรส (ระดับ 7)\n📞 098-670-9105")

# --- 6. ประมวลผลข้อมูล (Logic) ---
if not df_raw.empty:
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    if sel_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == sel_prov]
    if sel_dist != "ทั้งหมด": df_f = df_f[df_f[dist_col] == sel_dist]

    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    
    price_col = next((c for c in df_final.columns if 'price' in c), None)
    out_of_stock_df = df_final[df_final['availability'].str.contains('Out', na=False, case=False)]

    # --- 7. การแสดงผล Dashboard ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    # 7.1 Metrics Section (Fixed High Contrast)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ปั๊มที่พบ", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_of_stock_df), delta=f"-{len(out_of_stock_df)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_p = df_final[price_col].mean() if price_col and not df_final.empty else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_p:.2f} บ." if avg_p > 0 else "N/A")

    # 7.2 Tabs Section
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัดและความเสี่ยง", "📊 การวิเคราะห์แบรนด์และราคา", "📍 10 อันดับปั๊มใกล้ที่สุด", "📋 ข้อมูลสรุปรายน้ำมัน & ข้อมูลดิบ"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัด (Heatmap แสดงพื้นที่ความเสี่ยงน้ำมันขาดแคลน)")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        if not out_of_stock_df.empty:
            heat_data = [[row['latitude'], row['longitude']] for _, row in out_of_stock_df.iterrows()]
            HeatMap(heat_data, radius=15, blur=10, gradient={0.4: 'yellow', 0.65: 'orange', 1: 'red'}).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'Out' in str(row['availability']) else 'green'
            folium.Marker([row['latitude'], row['longitude']],
                          popup=f"<b>{row[station_name_col]}</b><br>ห่าง: {row['distance_km']:.2f} กม.",
                          icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')).add_to(cluster)
        folium_static(m, width=1100)
        st.caption("🔥 พื้นที่สีส้ม/แดง แสดงความหนาแน่นของสถานีที่พบบัญหาน้ำมันหมด (Risk Zone)")

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🏢 ส่วนแบ่งแบรนด์ (Market Share)")
            df_pie = df_final.copy()
            df_pie['agg_brand'] = df_pie['major_brand'].apply(lambda x: x if x in MAJOR_BRANDS_LIST else 'อื่นๆ')
            fig_pie = px.pie(df_pie, names='agg_brand', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.subheader("💰 ราคาเฉลี่ยรายแบรนด์หลัก")
            if price_col:
                brand_price = df_final.groupby('major_brand')[price_col].mean().reset_index().sort_values(price_col)
                fig_bar = px.bar(brand_price, x='major_brand', y=price_col, color='major_brand', text_auto='.2f')
                st.plotly_chart(fig_bar, use_container_width=True)

    with tab3:
        st.subheader("📍 10 อันดับสถานีที่ใกล้สวนจิตรลดาที่สุด")
        top_10 = df_final.sort_values('distance_km').head(10)
        if not top_10.empty:
            fig_near = px.bar(top_10, x='distance_km', y=station_name_col, orientation='h', 
                              color='distance_km', text_auto='.2f', labels={'distance_km': 'ระยะทาง (กม.)'})
            fig_near.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_near, use_container_width=True)

    with tab4:
        # --- ตารางสรุปสถานะรายชนิดน้ำมัน (New Highlight!) ---
        st.subheader("📋 สรุปสถานะเชื้อเพลิงแยกตามประเภท (Fuel Type Status Summary)")
        if not df_final.empty:
            # ประมวลผลแยกชนิดน้ำมัน (Explode)
            df_fuel = df_final.assign(fuel=df_final['fuel_type'].str.split(',')).explode('fuel')
            df_fuel['fuel'] = df_fuel['fuel'].str.strip().str.upper()
            
            def map_status(s):
                s = str(s).lower()
                if 'out' in s: return '🔴 Out'
                if 'available' in s: return '🟢 Available'
                return '⚪ Unknown'
            
            df_fuel['status_group'] = df_fuel['availability'].apply(map_status)
            fuel_sum = pd.crosstab(df_fuel['fuel'], df_fuel['status_group']).reset_index()
            
            # เติมคอลัมน์ที่ขาด
            for s in ['🟢 Available', '🔴 Out', '⚪ Unknown']:
                if s not in fuel_sum.columns: fuel_sum[s] = 0
            
            fuel_sum = fuel_sum[['fuel', '🟢 Available', '🔴 Out', '⚪ Unknown']]
            fuel_sum.columns = ['ชนิดน้ำมัน', 'พร้อมบริการ (แห่ง)', 'น้ำมันหมด (แห่ง)', 'ไม่ทราบสถานะ']
            st.table(fuel_sum)
        
        st.markdown("---")
        st.subheader("📋 ข้อมูลรายละเอียดสถานีทั้งหมด (Raw Data)")
        st.dataframe(df_final.sort_values('distance_km'), use_container_width=True)
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงานฉบับเต็ม (CSV)", data=csv, file_name='fuel_report_rspg.csv')

    # บทสรุปเชิงนโยบาย
    st.markdown("---")
    with st.expander("📄 **บทสรุปและข้อเสนอแนะเชิงนโยบาย**", expanded=False):
        st.write(f"สรุปสถานการณ์: ในรัศมี {radius_km} กม. พบสถานีพร้อมให้บริการรวมทุกแบรนด์ {len(df_final)-len(out_of_stock_df)} แห่ง")
        st.write("1. **การบริหารงบประมาณ:** แนะนำให้เลือกเติมกับแบรนด์ที่มีราคาต่ำที่สุดในพื้นที่วิเคราะห์เพื่อความคุ้มค่าสูงสุด")
        st.write("2. **การเฝ้าระวัง:** หากพบพื้นที่ Heatmap สีแดงเข้มหนาแน่น ควรหลีกเลี่ยงการเดินทางภาคสนามในโซนดังกล่าวในช่วงเวลาวิกฤต")
else:
    st.warning("⚠️ ระบบกำลังรอการเชื่อมต่อข้อมูล API...")
