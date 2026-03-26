import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import plotly.express as px
import os

# --- 1. การตั้งค่าหน้าเว็บ (Page Config) ---
st.set_page_config(
    page_title="RSPG Fuel Logistics & Spatial Mapping", 
    layout="wide", 
    page_icon="⛽"
)

# --- 2. ปรับแต่ง CSS เพื่อความสวยงามและอ่านง่าย (Fix Metric Visibility) ---
st.markdown("""
    <style>
    /* ปรับพื้นหลังหลัก */
    .main { background-color: #f0f2f6; }
    
    /* ปรับแต่งกล่อง Metric ให้ตัวอักษรชัดเจน */
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 2px solid #003366 !important;
        padding: 20px !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15) !important;
    }
    
    /* สีของหัวข้อใน Metric */
    [data-testid="stMetricLabel"] {
        color: #000000 !important;
        font-weight: bold !important;
        font-size: 1.1rem !important;
    }
    
    /* สีของตัวเลขใน Metric - บังคับให้เป็นน้ำเงินเข้ม */
    [data-testid="stMetricValue"] {
        color: #003366 !important;
        font-weight: 800 !important;
        font-size: 2.2rem !important;
    }

    /* ปรับแต่งส่วน Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #ffffff;
        border-radius: 5px 5px 0px 0px;
        padding: 10px 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. ฟังก์ชันดึงข้อมูล (Data Engine) ---
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
            
            if 'geometry.coordinates' in df.columns:
                coords = df['geometry.coordinates'].tolist()
                df['longitude'] = [c[0] if isinstance(c, list) and len(c)>1 else None for c in coords]
                df['latitude'] = [c[1] if isinstance(c, list) and len(c)>1 else None for c in coords]
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # จัดการคอลัมน์ราคา
            price_cols = [c for c in df.columns if 'price' in c]
            for col in price_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # ระบุชื่อคอลัมน์ Brand (ถ้าไม่มี ให้ตัดจากชื่อสถานี)
            if 'brand' not in df.columns:
                name_col_tmp = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
                df['brand'] = df[name_col_tmp].astype(str).str.split().str[0]
            
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ ระบบขัดข้อง: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 4. ส่วนควบคุมด้านข้าง (Sidebar) ---
LOGO_FILE = "logo_rspg.png" 
if os.path.exists(LOGO_FILE):
    st.sidebar.image(LOGO_FILE, use_container_width=True)
else:
    st.sidebar.warning(f"⚠️ กรุณาอัปโหลด {LOGO_FILE} เข้า GitHub")

st.sidebar.markdown("<h4 style='text-align: center;'>โครงการอนุรักษ์พันธุกรรมพืชอันเนื่องมาจากพระราชดำริฯ (อพ.สธ.)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    def get_safe_unique(df, col):
        if col and col in df.columns:
            items = df[col].dropna().unique()
            return sorted([str(i) for i in items])
        return []

    # ค้นหาคอลัมน์สำคัญ
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'sub' in c), None)
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), df_raw.columns[0])
    price_col = next((c for c in df_raw.columns if 'price' in c), None)

    # กรองพื้นที่
    st.sidebar.subheader("📍 พื้นที่ปฏิบัติงาน")
    sel_prov = st.sidebar.selectbox("เลือกจังหวัด", ["ทั้งหมด"] + get_safe_unique(df_raw, prov_col))
    
    df_p = df_raw.copy()
    if sel_prov != "ทั้งหมด": df_p = df_p[df_p[prov_col] == sel_prov]
    sel_dist = st.sidebar.selectbox("เลือกอำเภอ", ["ทั้งหมด"] + get_safe_unique(df_p, dist_col))
    
    df_d = df_p.copy()
    if sel_dist != "ทั้งหมด": df_d = df_d[df_d[dist_col] == sel_dist]
    sel_subdist = st.sidebar.selectbox("เลือกตำบล", ["ทั้งหมด"] + get_safe_unique(df_d, subdist_col))

    # กรองแบรนด์
    st.sidebar.markdown("---")
    st.sidebar.subheader("🏢 คัดกรองแบรนด์")
    all_brands = get_safe_unique(df_raw, 'brand')
    sel_brands = st.sidebar.multiselect("เลือกแบรนด์สถานี", all_brands, default=all_brands)

    st.sidebar.markdown("---")
    st.sidebar.subheader("⛽ ตั้งค่าจุดวิเคราะห์ (อพ.สธ. สวนจิตรลดา)")
    user_lat = st.sidebar.number_input("ละติจูด", value=13.769068, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.524251, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    # ข้อมูลผู้จัดทำ
    st.sidebar.markdown("---")
    st.sidebar.info(f"""
    **ผู้จัดทำ:** นายนิรุตติ์ บาโรส  
    แผนกวิชาการ อพ.สธ. (ระดับ 7)  
    📞 098-670-9105 | 📧 baroseniruth@gmail.com
    """)

# --- 5. การประมวลผลข้อมูล (Logic) ---
if not df_raw.empty:
    df_f = df_raw[df_raw['brand'].isin(sel_brands)].copy()
    
    if sel_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == sel_prov]
    if sel_dist != "ทั้งหมด": df_f = df_f[df_f[dist_col] == sel_dist]
    if sel_subdist != "ทั้งหมด": df_f = df_f[df_f[subdist_col] == sel_subdist]

    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # --- 6. การแสดงผล Dashboard ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    # Metrics Section (Fixed Visibility)
    m1, m2, m3, m4 = st.columns(4)
    out_of_stock = len(df_final[df_final['availability'].str.contains('Out', na=False, case=False)])
    m1.metric("ปั๊มที่พบ", len(df_final))
    m2.metric("น้ำมันหมด (แห่ง)", out_of_stock, delta=f"-{out_of_stock}" if out_of_stock > 0 else 0, delta_color="inverse")
    min_dist = df_final['distance_km'].min() if not df_final.empty else 0
    m3.metric("ใกล้ที่สุด (กม.)", f"{min_dist:.2f}")
    avg_price = df_final[price_col].mean() if price_col and not df_final[price_col].isnull().all() else 0
    m4.metric("ราคาเฉลี่ยพื้นที่", f"{avg_price:.2f} บ." if avg_price > 0 else "N/A")

    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัด", "📊 ราคาเฉลี่ยรายแบรนด์", "📉 จุดคุ้มค่า (Price vs Distance)", "📋 ตารางข้อมูล"])

    with tab1:
        st.subheader("🗺️ แผนที่พิกัดและความเสี่ยง")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        folium.Circle(my_loc, radius=radius_km*1000, color='blue', fill=True, opacity=0.05).add_to(m)
        folium.Marker(my_loc, popup="อพ.สธ. สวนจิตรลดา", icon=folium.Icon(color='red', icon='university', prefix='fa')).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            status_color = 'red' if 'Out' in str(row['availability']) else 'green'
            price_info = f"<br>ราคา: {row[price_col]:.2f} บ." if price_col and not pd.isnull(row[price_col]) else ""
            folium.Marker(
                [row['latitude'], row['longitude']],
                popup=f"<b>{row.get(name_col, 'N/A')}</b><br>แบรนด์: {row['brand']}<br>ห่าง: {row['distance_km']:.2f} กม.{price_info}",
                icon=folium.Icon(color=status_color, icon='gas-pump', prefix='fa')
            ).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        st.subheader("📊 การเปรียบเทียบราคาเฉลี่ยรายแบรนด์")
        if price_col and not df_final[price_col].isnull().all():
            brand_price = df_final.groupby('brand')[price_col].mean().reset_index().sort_values(price_col)
            fig_brand = px.bar(brand_price, x='brand', y=price_col, color='brand', text_auto='.2f',
                               title="ราคาเฉลี่ยต่อแบรนด์ (บาท)", labels={price_col: 'ราคาเฉลี่ย (บาท)', 'brand': 'แบรนด์'})
            st.plotly_chart(fig_brand, use_container_width=True)
        else:
            st.info("💡 ข้อมูลราคาไม่เพียงพอ")

    with tab3:
        st.subheader("📉 การวิเคราะห์จุดคุ้มค่า (Efficiency Frontier)")
        if price_col and not df_final[price_col].isnull().all():
            fig_scatter = px.scatter(df_final, x='distance_km', y=price_col, color='brand', 
                                     hover_name=name_col, size_max=15,
                                     title="ความสัมพันธ์ระหว่างระยะทางและราคา",
                                     labels={'distance_km': 'ระยะทาง (กม.)', price_col: 'ราคา (บาท)'})
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("💡 ข้อมูลราคาไม่เพียงพอสำหรับการวิเคราะห์จุดคุ้มค่า")

    with tab4:
        st.subheader("📋 รายละเอียดสถานีน้ำมัน")
        st.dataframe(df_final[[name_col, 'brand', 'distance_km', 'availability']].sort_values('distance_km'), use_container_width=True)
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงาน (CSV)", data=csv, file_name='fuel_report_rspg.csv', mime='text/csv')

    # Executive Summary & Policy at the bottom
    st.markdown("---")
    with st.expander("📄 **บทสรุปและข้อเสนอแนะเชิงนโยบาย**", expanded=False):
        st.write(f"**ภาพรวม:** ในรัศมี {radius_km} กม. รอบสวนจิตรลดา พบจุดให้บริการที่พร้อมใช้งาน {len(df_final)-out_of_stock} แห่ง")
        st.write("1. **การลดค่าใช้จ่าย:** หากเติมน้ำมันกับแบรนด์ที่ราคาต่ำที่สุดในพื้นที่ จะลดงบประมาณได้เฉลี่ย " + (f"{(df_final[price_col].max() - df_final[price_col].min()):.2f}" if price_col and len(df_final)>0 else "0") + " บาท/ลิตร")
        st.write("2. **การเฝ้าระวัง:** ควรให้ความสำคัญกับโซนที่มีอัตราน้ำมันหมดสูงกว่า 15% เพื่อวางแผนการเดินทางของรถปฏิบัติงานล่วงหน้า")

else:
    st.warning("⚠️ กำลังดึงข้อมูลจาก API...")
