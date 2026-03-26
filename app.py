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
st.set_page_config(page_title="RSPG - Fuel Logistics & Mapping", layout="wide", page_icon="⛽")

# สไตล์ CSS ตกแต่ง
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ฟังก์ชันดึงและประมวลผลข้อมูล (Data Engine) ---
@st.cache_data(ttl=600)
def fetch_data():
    # *** ใส่ URL เต็มที่มี Token ของคุณที่นี่ ***
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
            
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df = df.dropna(subset=['latitude', 'longitude'])
            
            # จัดการคอลัมน์ราคา
            price_cols = [c for c in df.columns if 'price' in c]
            for col in price_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # สร้างคอลัมน์ Brand (ถ้าไม่มี ให้ตัดจากคำแรกของชื่อสถานี)
            name_col = next((c for c in df.columns if 'name' in c or 'station' in c), df.columns[0])
            if 'brand' not in df.columns:
                df['brand'] = df[name_col].astype(str).str.split().str[0]
            
            if 'availability' not in df.columns:
                df['availability'] = 'Available'
                
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ การเชื่อมต่อ API ขัดข้อง: {e}")
        return pd.DataFrame()

df_raw = fetch_data()

# --- 3. ส่วนควบคุมด้านข้าง (Sidebar) ---
LOGO_FILE = "logo_rspg.png" 
if os.path.exists(LOGO_FILE):
    st.sidebar.image(LOGO_FILE, use_container_width=True)
else:
    st.sidebar.warning(f"⚠️ ไม่พบไฟล์ {LOGO_FILE} ในระบบ")

st.sidebar.markdown("<h4 style='text-align: center;'>โครงการอนุรักษ์พันธุกรรมพืชอันเนื่องมาจากพระราชดำริฯ (อพ.สธ.)</h4>", unsafe_allow_html=True)

if not df_raw.empty:
    def get_safe_unique(df, col):
        if col and col in df.columns:
            items = df[col].dropna().unique()
            return sorted([str(i) for i in items])
        return []

    # ค้นหาคอลัมน์สำคัญอัตโนมัติ
    prov_col = next((c for c in df_raw.columns if 'prov' in c), None)
    dist_col = next((c for c in df_raw.columns if 'amphoe' in c or 'dist' in c), None)
    subdist_col = next((c for c in df_raw.columns if 'tambon' in c or 'sub' in c), None)
    name_col = next((c for c in df_raw.columns if 'name' in c or 'station' in c), df_raw.columns[0])
    price_col = next((c for c in df_raw.columns if 'price' in c), None)

    # 1. กรองพื้นที่
    st.sidebar.subheader("📍 พื้นที่ปฏิบัติงาน")
    sel_prov = st.sidebar.selectbox("เลือกจังหวัด", ["ทั้งหมด"] + get_safe_unique(df_raw, prov_col))
    
    df_p = df_raw.copy()
    if sel_prov != "ทั้งหมด": df_p = df_p[df_p[prov_col] == sel_prov]
    sel_dist = st.sidebar.selectbox("เลือกอำเภอ", ["ทั้งหมด"] + get_safe_unique(df_p, dist_col))
    
    df_d = df_p.copy()
    if sel_dist != "ทั้งหมด": df_d = df_d[df_d[dist_col] == sel_dist]
    sel_subdist = st.sidebar.selectbox("เลือกตำบล", ["ทั้งหมด"] + get_safe_unique(df_d, subdist_col))

    # 2. กรองแบรนด์ (Brand)
    st.sidebar.markdown("---")
    st.sidebar.subheader("🏢 คัดกรองแบรนด์")
    all_brands = get_safe_unique(df_raw, 'brand')
    sel_brands = st.sidebar.multiselect("เลือกแบรนด์ที่ต้องการ", all_brands, default=all_brands)

    # 3. ตั้งค่าพิกัดและรัศมี
    st.sidebar.markdown("---")
    st.sidebar.subheader("⛽ ตั้งค่าการวิเคราะห์ (อพ.สธ. สวนจิตรลดา)")
    fuel_list = ['E20', '91', '95', 'G91', 'G95', 'B7', 'Diesel']
    sel_fuels = st.sidebar.multiselect("ประเภทน้ำมัน", fuel_list, default=['95', 'E20'])
    
    user_lat = st.sidebar.number_input("ละติจูด", value=13.769068578125859, format="%.6f")
    user_lon = st.sidebar.number_input("ลองจิจูด", value=100.52425116459443, format="%.6f")
    radius_km = st.sidebar.select_slider("รัศมีวิเคราะห์ (กม.)", options=[1, 5, 10, 20, 50], value=10)

    # ข้อมูลผู้จัดทำ
    st.sidebar.markdown("---")
    st.sidebar.info(f"""
    **ผู้จัดทำ:** นายนิรุตติ์ บาโรส  
    แผนกวิชาการ อพ.สธ. (รองหัวหน้าแผนก ระดับ 7)  
    📞 098-670-9105 | 📧 baroseniruth@gmail.com
    """)

# --- 4. การประมวลผลข้อมูล (Filtering Logic) ---
if not df_raw.empty:
    df_f = df_raw.copy()
    
    # Filter by Area
    if sel_prov != "ทั้งหมด": df_f = df_f[df_f[prov_col] == sel_prov]
    if sel_dist != "ทั้งหมด": df_f = df_f[df_f[dist_col] == sel_dist]
    if sel_subdist != "ทั้งหมด": df_f = df_f[df_f[subdist_col] == sel_subdist]
    
    # Filter by Brand
    df_f = df_f[df_f['brand'].isin(sel_brands)]

    # Calculate Distance
    my_loc = (user_lat, user_lon)
    df_f['distance_km'] = df_f.apply(lambda r: geodesic(my_loc, (r['latitude'], r['longitude'])).km, axis=1)
    df_final = df_f[df_f['distance_km'] <= radius_km].copy()

    # Filter by Fuel Type
    if 'fuel_type' in df_final.columns and sel_fuels:
        pattern = '|'.join(sel_fuels)
        df_final = df_final[df_final['fuel_type'].str.contains(pattern, case=False, na=True)]

    # --- 5. การแสดงผล Dashboard ---
    st.title("⛽ ระบบสารสนเทศภูมิสารสนเทศเพื่อการวางแผนเชื้อเพลิง (RSPG Fuel Logistics)")
    
    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    out_of_stock = len(df_final[df_final['availability'].str.contains('Out', na=False, case=False)])
    m1.metric("ปั๊มที่ตรงเงื่อนไข", len(df_final))
    m2.metric("น้ำมันหมด (แห่ง)", out_of_stock, delta=f"-{out_of_stock}", delta_color="inverse")
    m3.metric("ปั๊มที่ใกล้ที่สุด", f"{df_final['distance_km'].min():.2f} กม." if not df_final.empty else "N/A")
    avg_price = df_final[price_col].mean() if price_col and not df_final[price_col].isnull().all() else 0
    m4.metric("ราคาเฉลี่ยในพื้นที่", f"{avg_price:.2f} บ." if avg_price > 0 else "N/A")

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ แผนที่พิกัดและความเสี่ยง", "📊 วิเคราะห์ราคาเฉลี่ยรายแบรนด์", "📉 จุดคุ้มค่า (Price vs Distance)", "📋 ตารางข้อมูล"])

    with tab1:
        st.subheader("🗺️ แผนที่แสดงสถานะสถานีบริการ")
        m = folium.Map(location=my_loc, zoom_start=13, tiles='CartoDB Positron')
        folium.Circle(my_loc, radius=radius_km*1000, color='blue', fill=True, opacity=0.05).add_to(m)
        folium.Marker(my_loc, popup="อพ.สธ. สวนจิตรลดา", icon=folium.Icon(color='red', icon='university', prefix='fa')).add_to(m)
        
        cluster = MarkerCluster().add_to(m)
        for _, row in df_final.iterrows():
            color = 'red' if 'Out' in str(row['availability']) else 'green'
            price_txt = f"<br>ราคา: {row[price_col]:.2f} บ." if price_col and not pd.isnull(row[price_col]) else ""
            folium.Marker(
                [row['latitude'], row['longitude']],
                popup=f"<b>{row.get(name_col, 'N/A')}</b><br>แบรนด์: {row['brand']}<br>ห่าง: {row['distance_km']:.2f} กม.{price_txt}",
                icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')
            ).add_to(cluster)
        folium_static(m, width=1100)

    with tab2:
        st.subheader("📊 เปรียบเทียบราคาน้ำมันเฉลี่ยรายแบรนด์")
        if price_col and not df_final[price_col].isnull().all():
            brand_price = df_final.groupby('brand')[price_col].mean().reset_index().sort_values(price_col)
            fig_brand = px.bar(brand_price, x='brand', y=price_col, color='brand', text_auto='.2f',
                               title="ราคาเฉลี่ยต่อแบรนด์ (ในพื้นที่วิเคราะห์)",
                               labels={price_col: 'ราคาเฉลี่ย (บาท)', 'brand': 'แบรนด์'})
            st.plotly_chart(fig_brand, use_container_width=True)
        else:
            st.info("💡 ข้อมูลราคาไม่เพียงพอสำหรับการวิเคราะห์รายแบรนด์")

    with tab3:
        st.subheader("📉 การวิเคราะห์ประสิทธิภาพความคุ้มค่า (Efficiency Frontier)")
        if price_col and not df_final[price_col].isnull().all():
            fig_scatter = px.scatter(df_final, x='distance_km', y=price_col, color='brand', 
                                     size='distance_km', hover_name=name_col,
                                     title="ความสัมพันธ์ระหว่างระยะทางและราคาน้ำมัน",
                                     labels={'distance_km': 'ระยะทาง (กม.)', price_col: 'ราคา (บาท)'})
            st.plotly_chart(fig_scatter, use_container_width=True)
            st.caption("หมายเหตุ: ปั๊มที่อยู่มุมซ้ายล่าง คือปั๊มที่คุ้มค่าที่สุด (ราคาถูกและอยู่ใกล้)")
        else:
            st.info("💡 ไม่พบข้อมูลราคาเพียงพอสำหรับการทำ Scatter Chart")

    with tab4:
        st.subheader("📋 รายละเอียดสถานีน้ำมันที่ผ่านการคัดกรอง")
        cols_show = [name_col, 'brand', 'distance_km', 'availability']
        if price_col: cols_show.append(price_col)
        st.dataframe(df_final[cols_show].sort_values('distance_km'), use_container_width=True)
        
        # Download Report
        csv = df_final.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดรายงานฉบับสมบูรณ์ (CSV)", data=csv, file_name='fuel_report_rspg.csv', mime='text/csv')

    # บทสรุปสำหรับผู้บริหาร (ย้ายมาล่างสุดเพื่อให้ดูข้อมูลก่อน)
    st.markdown("---")
    with st.expander("📄 **บทสรุปและข้อเสนอแนะเชิงนโยบาย**", expanded=False):
        st.write(f"**บทสรุป:** พบสถานีในรัศมี {radius_km} กม. ทั้งหมด {len(df_final)} แห่ง มีความพร้อม {len(df_final)-out_of_stock} แห่ง")
        st.write("1. **การลดต้นทุน:** หากเลือกเติมแบรนด์ที่ราคาต่ำที่สุดในพื้นที่ จะประหยัดได้เฉลี่ย " + (f"{(df_final[price_col].max() - df_final[price_col].min()):.2f}" if price_col and len(df_final)>0 else "0") + " บาทต่อลิตร")
        st.write("2. **การปฏิบัติงาน:** ในโซนพื้นที่ " + sel_subdist + " ควรระมัดระวังหากดัชนีน้ำมันหมดสูงกว่า 20%")

else:
    st.warning("⚠️ ไม่พบข้อมูล กรุณาตรวจสอบการเชื่อมต่อ API ของท่าน")
