import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px

# --- การตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="RSPG - Fuel Analysis Dashboard", layout="wide", page_icon="⛽")

# Custom CSS เพื่อความเป็นระเบียบและสวยงาม
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .css-1n76uvr { font-family: 'Sarabun', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. การดึงและประมวลผลข้อมูล (API Ingestion) ---
@st.cache_data(ttl=600)
def fetch_data():
    # หมายเหตุ: กรุณาใส่ URL เต็มที่มี Token ของคุณในบรรทัดนี้
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
            
            # แปลงพิกัดเป็นตัวเลข
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # จัดการคอลัมน์ราคา
            price_cols = [c for c in df.columns if 'price' in c]
            for col in price_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
                
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"การดึงข้อมูลขัดข้อง: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 2. ส่วนควบคุมด้านข้าง (Sidebar) ---
LOGO_URL = "https://www.rspg.or.th/images/logo_rspg.png" 
st.sidebar.image(LOGO_URL, use_container_width=True)
st.sidebar.markdown("<h4 style='text-align: center;'>โครงการอนุรักษ์พันธุกรรมพืชฯ (อพ.สธ.)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    st.sidebar.subheader("📍 พื้นที่ปฏิบัติงาน")
    
    def get_safe_unique(df, col):
        if col and col in df.columns:
            return sorted([str(i) for i in df[col].dropna().unique()])
        return []

    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'sub' in c), None)
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), df_raw.columns[0])
    price_col = next((c for c in df_raw.columns if 'price' in c), None)

    # Filter จังหวัด > อำเภอ > ตำบล
    sel_prov = st.sidebar.selectbox("เลือกจังหวัด", ["ทั้งหมด"] + get_safe_unique(df_raw, prov_col))
    
    df_p = df_raw.copy()
    if sel_prov != "ทั้งหมด": df_p = df_p[df_p[prov_col] == sel_prov]
    sel_dist = st.sidebar.selectbox("เลือกอำเภอ", ["ทั้งหมด"] + get_safe_unique(df_p, dist_col))
    
    df_d = df_p.copy()
    if sel_dist != "ทั้งหมด": df_d = df_d[df_d[dist_col] == sel_dist]
    sel_subdist = st.sidebar.selectbox("เลือกตำบล", ["ทั้งหมด"] + get_safe_unique(df_d, subdist_col))

    st.sidebar.markdown("---")
    st.sidebar.subheader("⛽ ตั้งค่าการวิเคราะห์")
    fuel_list = ['E20', '91', '95', 'G91', 'G95', 'B7', 'Diesel']
    sel_fuels = st.sidebar.multiselect("ประเภทน้ำมัน", fuel_list, default=['95', 'E20'])
    
    user_lat = st.sidebar.number_input("ละติจูด", value=13.935809, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.514827, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    # ข้อมูลผู้จัดทำ
    st.sidebar.markdown("---")
    st.sidebar.info(f"""
    **ผู้จัดทำ:** นายนิรุตติ์ บาโรส  
    แผนกวิชาการ อพ.สธ. (รองหัวหน้าแผนก ระดับ 7)  
    📞 098-670-9105  
    📧 baroseniruth@gmail.com
    """)
    # แก้ไขตรงนี้: ใช้ st.sidebar.caption เพื่อแสดงที่มาข้อมูล
    st.sidebar.caption("ขอขอบคุณข้อมูล API จาก https://thaipumpradar.com/")

# --- 3. การประมวลผลข้อมูล (Processing) ---
if not df_raw.empty:
    df_f = df_raw.copy()
    
    if sel_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == sel_prov]
    if sel_dist != "ทั้งหมด": df_f = df_f[df_f[dist_col] == sel_dist]
    if sel_subdist != "ทั้งหมด": df_f = df_f[df_f[subdist_col] == sel_subdist]

    df_f['distance_km'] = df_f.apply(lambda r: geodesic((user_lat, user_lon), (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    if 'fuel_type' in df_final.columns and sel_fuels:
        pattern = '|'.join(sel_fuels)
        df_final = df_final[df_final['fuel_type'].str.contains(pattern, case=False, na=True)]

    # --- 4. การแสดงผล Dashboard ---
    st.title("⛽ ระบบบริหารจัดการพลังงานเชิงพื้นที่ (RSPG Energy Insight)")
    
    with st.expander("📄 **บทสรุปผู้บริหาร (Executive Summary)**", expanded=True):
        out_of_stock = len(df_final[df_final['availability'].str.contains('Out', na=False, case=False)])
        st.write(f"""
        จากการวิเคราะห์ข้อมูลเชิงพื้นที่ในรัศมี **{radius_km} กม.** รอบตำแหน่งเป้าหมาย 
        พบสถานีบริการน้ำมันที่พร้อมให้บริการ **{len(df_final)} แห่ง** และพบปัญหาน้ำมันขาดแคลน (Out of Stock) จำนวน **{out_of_stock} แห่ง** ซึ่งอาจส่งผลกระทบต่อการเดินทางปฏิบัติงานในพื้นที่ **{sel_subdist if sel_subdist != 'ทั้งหมด' else 'โครงการฯ'}**
        """)

    with st.expander("💡 **ข้อเสนอแนะเชิงนโยบาย (Policy Recommendations)**"):
        st.write("""
        1. **มาตรการสำรอง:** ในพื้นที่ที่มีปัญหาน้ำมันขาดแคลนเกิน 20% ของสถานีทั้งหมด ควรพิจารณาสำรองเชื้อเพลิงที่ส่วนกลางอย่างน้อย 3 วัน
        2. **การวางแผนเส้นทาง:** ให้เจ้าหน้าที่ตรวจสอบแผนที่ Real-time นี้ก่อนออกปฏิบัติงานภาคสนามเพื่อหลีกเลี่ยงจุดเสี่ยง
        3. **ความร่วมมือ:** ควรใช้ข้อมูลนี้ประสานงานกับหน่วยงานที่เกี่ยวข้องในพื้นที่หากพบปัญหาน้ำมันขาดแคลนต่อเนื่องเกิน 48 ชั่วโมง
        """)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ปั๊มในพื้นที่วิเคราะห์", len(df_final))
    m2.metric("สถานะน้ำมันหมด", out_of_stock, delta=f"-{out_of_stock}", delta_color="inverse")
    min_dist = df_final['distance_km'].min() if not df_final.empty else 0
    m3.metric("ปั๊มที่ใกล้ที่สุด", f"{min_dist:.2f} กม.")
    
    low_price = df_final[price_col].min() if price_col and not df_final[price_col].isnull().all() else 0
    m4.metric("ราคาต่ำสุดในรัศมี", f"{low_price:.2f} บ." if low_price > 0 else "N/A")

    tab1, tab2, tab3 = st.tabs(["🗺️ แผนที่พิกัดความเสี่ยง", "📊 วิเคราะห์เปรียบเทียบ", "📋 ข้อมูลรายสถานี"])

    with tab1:
        m = folium.Map(location=[user_lat, user_lon], zoom_start=13, tiles='CartoDB Positron')
        folium.Circle([user_lat, user_lon], radius=radius_km*1000, color='blue', fill=True, opacity=0.1).add_to(m)
        folium.Marker([user_lat, user_lon], popup="ตำแหน่งพิกัดเป้าหมาย", icon=folium.Icon(color='red', icon='home')).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'Out' in str(row['availability']) else 'green'
            price_val = f"<br>ราคา: {row[price_col]:.2f} บาท" if price_col and not pd.isnull(row[price_col]) else ""
            folium.Marker(
                [row['latitude'], row['longitude']],
                popup=f"<b>{row.get(name_col, 'N/A')}</b><br>ระยะทาง: {row['distance_km']:.2f} กม.{price_val}",
                icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')
            ).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        if not df_final.empty:
            fig = px.bar(df_final.sort_values('distance_km').head(15), 
                         x=name_col, y='distance_km', color='distance_km',
                         title="15 สถานีน้ำมันที่ใกล้ที่สุด", labels={name_col: 'ชื่อสถานี', 'distance_km': 'ระยะทาง (กม.)'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่พบข้อมูลสำหรับการวิเคราะห์กราฟ")

    with tab3:
        st.subheader("📋 ตารางข้อมูลสรุปรายสถานี")
        cols_show = [name_col, 'distance_km', 'availability']
        if price_col: cols_show.append(price_col)
        st.dataframe(df_final[cols_show].sort_values('distance_km'), use_container_width=True)
        
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงาน (CSV)", data=csv, file_name='fuel_report_rspg.csv', mime='text/csv')
else:
    st.warning("⚠️ ไม่พบข้อมูล กรุณาตรวจสอบการเชื่อมต่อ API ของท่าน")
