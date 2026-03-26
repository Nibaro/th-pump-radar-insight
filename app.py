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
    page_title="ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics & Spatial Mapping)", 
    layout="wide", 
    page_icon="⛽"
)

# --- 2. ปรับแต่ง CSS เพื่อความคมชัดสูง (High Contrast UI) ---
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    /* ปรับแต่งกล่อง Metric ให้อ่านง่าย 100% บังคับสีตัวอักษรให้ชัดเจน */
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
    /* ปรับแต่งแถบข้างและองค์ประกอบทั่วไป */
    .st-expander { background-color: #ffffff !important; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. ฟังก์ชันดึงและประมวลผลข้อมูล (Data Engine) ---
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
            return df, name_col
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"❌ การเชื่อมต่อ API ขัดข้อง: {e}")
        return pd.DataFrame(), None

df_raw, station_name_col = fetch_data()

# --- 4. ส่วนควบคุมด้านข้าง (Sidebar Visual Filters) ---
LOGO_RSPG = "logo_rspg.png" 
if os.path.exists(LOGO_RSPG): st.sidebar.image(LOGO_RSPG, use_container_width=True)
st.sidebar.markdown("<h4 style='text-align: center;'>โครงการอนุรักษ์พันธุกรรมพืชอันเนื่องมาจากพระราชดำริฯ (อพ.สธ.)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    st.sidebar.subheader("🏢 เลือกแบรนด์สถานี")
    # รายชื่อแบรนด์หลักที่จะแสดง Logo
    major_brands_list = ["PTT", "BANGCHAK", "PT", "SHELL", "CALTEX", "SUSCO", "ESSO"]
    
    # สร้าง Grid 3 คอลัมน์สำหรับ Logo ใน Sidebar
    selected_brands = []
    brand_cols = st.sidebar.columns(3)
    
    for i, b in enumerate(major_brands_list):
        # ตรวจสอบว่ามีข้อมูลแบรนด์นี้ใน API หรือไม่
        if b in df_raw['major_brand'].values:
            with brand_cols[i % 3]:
                logo_path = os.path.join("brand_logos", f"{b.lower()}.png")
                if os.path.exists(logo_path):
                    st.image(logo_path, use_container_width=True)
                else:
                    st.caption(f"**{b}**")
                # สร้าง Checkbox เลือกแบรนด์ (ซ่อน Label เพื่อความสวยงาม)
                if st.checkbox("", value=True, key=f"chk_{b}"):
                    selected_brands.append(b)
    
    if st.sidebar.checkbox("แบรนด์อื่นๆ", value=True):
        others = [b for b in df_raw['major_brand'].unique() if b not in major_brands_list]
        selected_brands.extend(others)

    st.sidebar.markdown("---")
    # พิกัดจุดวิเคราะห์ (สวนจิตรลดา)
    st.sidebar.subheader("⛽ จุดวิเคราะห์ (สวนจิตรลดา)")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    # ข้อมูลผู้จัดทำ
    st.sidebar.info(f"**ผู้จัดทำ:** นายนิรุตติ์ บาโรส (รองหัวหน้าแผนก ระดับ 7) \n แผนกวิชาการ โครงการอนุรักษ์พันธุกรรมพืชอันเนื่องมาจากพระราชดำริฯ (อพ.สธ.)\n📞 098-670-9105 | 📧 baroseniruth@gmail.com")

# --- 5. การประมวลผลข้อมูล (Processing) ---
if not df_raw.empty:
    # กรองแบรนด์หลัก (ซึ่งจะรวมทุกสาขาย่อยอัตโนมัติ)
    df_f = df_raw[df_raw['major_brand'].isin(selected_brands)].copy()
    
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()
    
    price_col = next((c for c in df_final.columns if 'price' in c), None)
    out_of_stock_df = df_final[df_final['availability'].str.contains('Out', na=False, case=False)]

    # --- 6. การแสดงผล Dashboard ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    # 6.1 Metrics Section (High Contrast Boxes)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ปั๊มที่พบ", len(df_final))
    m2.metric("สถานะน้ำมันหมด", len(out_of_stock_df), delta=f"-{len(out_of_stock_df)}", delta_color="inverse")
    m3.metric("ใกล้ที่สุด (กม.)", f"{df_final['distance_km'].min():.2f}" if not df_final.empty else "N/A")
    avg_price = df_final[price_col].mean() if price_col and not df_final.empty else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_price:.2f} บ." if avg_price > 0 else "N/A")

    # 6.2 Analysis Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัดและความเสี่ยง", "📊 ส่วนแบ่งแบรนด์และราคา", "📍 10 อันดับปั๊มใกล้ที่สุด", "📋 ข้อมูลรายสถานี"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัด (Heatmap: พื้นที่ความเสี่ยงน้ำมันขาดแคลน)")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        
        # แสดง Heatmap สำหรับจุดเสี่ยง (ที่น้ำมันหมด)
        if not out_of_stock_df.empty:
            heat_data = [[row['latitude'], row['longitude']] for _, row in out_of_stock_df.iterrows()]
            HeatMap(heat_data, radius=15, blur=10, gradient={0.4: 'yellow', 0.6: 'orange', 1: 'red'}).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            status_color = 'red' if 'Out' in str(row['availability']) else 'green'
            folium.Marker([row['latitude'], row['longitude']],
                          popup=f"<b>{row[station_name_col]}</b><br>ห่าง: {row['distance_km']:.2f} กม.",
                          icon=folium.Icon(color=status_color, icon='gas-pump', prefix='fa')).add_to(cluster)
        folium_static(m, width=1100)
        st.caption("🔥 พื้นที่สีแดงจางๆ แสดงความหนาแน่นของสถานีที่พบบัญหาน้ำมันหมด (Scarcity Zone)")

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🏢 ส่วนแบ่งแบรนด์ในพื้นที่ (Market Share)")
            fig_pie = px.pie(df_final, names='major_brand', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.subheader("💰 ราคาเฉลี่ยรายแบรนด์")
            if price_col:
                brand_price = df_final.groupby('major_brand')[price_col].mean().reset_index().sort_values(price_col)
                fig_bar = px.bar(brand_price, x='major_brand', y=price_col, color='major_brand', text_auto='.2f')
                st.plotly_chart(fig_bar, use_container_width=True)

    with tab3:
        st.subheader("📍 10 อันดับสถานีที่ใกล้สวนจิตรลดาที่สุด (รวมทุกสาขา)")
        top_10 = df_final.sort_values('distance_km').head(10)
        if not top_10.empty:
            fig_near = px.bar(top_10, x='distance_km', y=station_name_col, orientation='h', 
                              color='distance_km', text_auto='.2f', labels={'distance_km': 'ระยะทาง (กม.)'})
            fig_near.update_layout(yaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_near, use_container_width=True)
        else:
            st.info("ไม่พบข้อมูลปั๊มในรัศมีที่กำหนด")

    with tab4:
        st.subheader("📋 รายละเอียดสาขาย่อยทั้งหมด")
        st.dataframe(df_final.sort_values('distance_km'), use_container_width=True)
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงานฉบับสมบูรณ์ (CSV)", data=csv, file_name='fuel_report_rspg.csv')

    # 6.3 Executive Summary & Policy at the bottom
    st.markdown("---")
    with st.expander("📄 **บทสรุปและข้อเสนอแนะเชิงนโยบาย**", expanded=False):
        st.write(f"**ภาพรวม:** ในรัศมี {radius_km} กม. รอบสวนจิตรลดา พบสถานีบริการที่พร้อมใช้งาน {len(df_final)-len(out_of_stock_df)} แห่ง จากแบรนด์หลักที่ท่านเลือก")
        st.write("1. **การบริหารงบประมาณ:** หากเลือกเติมกับแบรนด์ราคาต่ำสุด จะช่วยลดภาระงบประมาณได้เฉลี่ย " + (f"{(df_final[price_col].max() - df_final[price_col].min()):.2f}" if price_col and len(df_final)>0 else "0") + " บาท/ลิตร")
        st.write("2. **การเฝ้าระวัง:** โซนที่พบบัญหาน้ำมันหมดหนาแน่น (ตาม Heatmap) ควรหลีกเลี่ยงในการวางแผนเส้นทางเดินรถภาคสนาม")

else:
    st.warning("⚠️ กำลังรอการเชื่อมต่อข้อมูล API...")
