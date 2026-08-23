import streamlit as st
import pandas as pd
import numpy as np
import json
import subprocess
import sys
import os
import streamlit.components.v1 as components

# Persistent file path
DATA_FILE_PATH = "latest_recruitment_data.csv"

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="SAFA — OND 2026 Farmer Preselection Dashboard",
    page_icon="🌱",
    layout="wide"
)

# 2. BRANDING & HEADER
st.markdown("""
    <style>
        .safa-header {
            display: flex;
            align-items: center;
            background: linear-gradient(90deg, #0A3A2A 0%, #1E5E43 100%);
            padding: 18px 25px;
            border-radius: 10px;
            color: white;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .safa-logo-box {
            background-color: #FFFFFF;
            padding: 8px 14px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 20px;
        }
        .safa-logo-text {
            color: #0A3A2A;
            font-weight: 900;
            font-size: 26px;
            letter-spacing: 2px;
            font-family: 'Helvetica Neue', Arial, sans-serif;
        }
        .safa-logo-sub {
            color: #27AE60;
            font-size: 10px;
            font-weight: 700;
            display: block;
            margin-top: -4px;
            letter-spacing: 1px;
        }
        .safa-title {
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            color: #FFFFFF !important;
        }
        .safa-subtitle {
            margin: 2px 0 0 0;
            font-size: 13px;
            color: #A3E4D7;
            font-weight: 400;
        }
    </style>
    
    <div class="safa-header">
        <div class="safa-logo-box">
            <div>
                <span class="safa-logo-text">SAFA</span>
                <span class="safa-logo-sub">SUSTAINABLE AGRI</span>
            </div>
        </div>
        <div>
            <h1 class="safa-title">OND 2026 Farmer Preselection</h1>
            <p class="safa-subtitle">Recruitment Audit & Live Field Movement Dashboard</p>
        </div>
    </div>
""", unsafe_allow_html=True)

# 3. ADMIN DATA UPDATE SECTION
st.sidebar.header("🔑 Admin Controls")
admin_pin = st.sidebar.text_input("Enter Admin PIN to Update Data", type="password", help="Type 1234 and press ENTER")

ADMIN_PASSCODE = "1234"

if admin_pin == ADMIN_PASSCODE:
    st.sidebar.success("✅ Admin Unlocked")
    uploaded_file = st.sidebar.file_uploader(
        "Upload Preselection Dataset (.xlsx or .csv)", 
        type=["xlsx", "xls", "csv"]
    )
    
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                new_df = pd.read_csv(uploaded_file)
            else:
                try:
                    new_df = pd.read_excel(uploaded_file, engine='openpyxl')
                except ImportError:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
                    new_df = pd.read_excel(uploaded_file, engine='openpyxl')
            
            # Save persistently locally
            new_df.to_csv(DATA_FILE_PATH, index=False)
            st.sidebar.success("Saved successfully! Reloading dashboard...")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Failed to process file: {str(e)}")

# Load persistent dataset or display initial prompt
if os.path.exists(DATA_FILE_PATH):
    df_raw = pd.read_csv(DATA_FILE_PATH)
else:
    st.info("👈 No active preselection dataset uploaded yet. Enter the Admin PIN in the sidebar to perform the initial dataset upload.")
    st.stop()

if df_raw.empty:
    st.warning("The active preselection dataset is empty.")
    st.stop()

# 4. PRESELECTION DATA CLEANING & TRANSFORMATION
df = df_raw.copy()

# A. Acres Committed Parsing
acres_col = [c for c in df.columns if 'acre' in c.lower() or 'commit' in c.lower()]
if acres_col:
    raw_acres = df[acres_col[0]].astype(str).str.replace(',', '.', regex=False).str.strip()
    df['acres_committed'] = pd.to_numeric(raw_acres, errors='coerce').fillna(0).clip(lower=0)
else:
    df['acres_committed'] = 0.0

# B. Multi-column GPS Extraction Logic
def extract_coords(row):
    lat1, lon1 = row.get('_Farm Location_latitude', np.nan), row.get('_Farm Location_longitude', np.nan)
    lat2, lon2 = row.get('_Farm Location_latitude.1', np.nan), row.get('_Farm Location_longitude.1', np.nan)
    
    # Fallback to general column search if named coordinates are missing
    if pd.isnull(lat1) and pd.isnull(lat2):
        lats = [row[c] for c in df.columns if 'lat' in c.lower() and pd.notnull(row[c])]
        lons = [row[c] for c in df.columns if 'lon' in c.lower() and pd.notnull(row[c])]
        lat = lats[0] if lats else np.nan
        lon = lons[0] if lons else np.nan
    else:
        lat = lat1 if pd.notnull(lat1) else lat2
        lon = lon1 if pd.notnull(lon1) else lon2
        
    return pd.Series([pd.to_numeric(lat, errors='coerce'), pd.to_numeric(lon, errors='coerce')])

df[['lat', 'lon']] = df.apply(extract_coords, axis=1)

# C. Multi-column Village Extraction
def extract_village(row):
    v1, v2 = row.get('Village', np.nan), row.get('Village.1', np.nan)
    if pd.notnull(v1) and str(v1).strip() != '':
        return str(v1).strip().title()
    if pd.notnull(v2) and str(v2).strip() != '':
        return str(v2).strip().title()
    
    vill_cols = [c for c in df.columns if 'village' in c.lower()]
    if vill_cols and pd.notnull(row[vill_cols[0]]):
        return str(row[vill_cols[0]]).strip().title()
    return 'Unknown'

df['clean_village'] = df.apply(extract_village, axis=1)

# D. Officer & Location Cleaning
fo_clean = {
    'Caroline': 'Caroline Kalovoto', 'Kklonzi': 'Kilonzi', 'Dou': 'Douglas',
    'Dominic': 'Dominic Kioko', 'Amani Thoya Karisa': 'Amani Thoya',
    'Paul Kamau Muraya': 'Paul Kamau', 'Paul kamau muraya': 'Paul Kamau',
    'Pk And Mary': 'PK & Mary', 'Pk and mary': 'PK & Mary', 'Peter And Mary': 'PK & Mary'
}

officer_cols = [c for c in df.columns if 'officer' in c.lower() or 'Field Officer' in c]
officer_col = officer_cols[0] if officer_cols else df.columns[0]
df['field_officer'] = df[officer_col].astype(str).str.strip().str.title().replace(fo_clean)

county_cols = [c for c in df.columns if 'county' in c.lower()]
county_col = county_cols[0] if county_cols else df.columns[0]
df['county'] = df[county_col].astype(str).str.strip().str.title()

farmer_cols = [c for c in df.columns if 'farmer' in c.lower() or 'name' in c.lower()]
farmer_col = farmer_cols[0] if farmer_cols else df.columns[0]
df['farmer_name'] = df[farmer_col].fillna('Unknown Farmer').astype(str).str.title()

# E. Date & Operational Time Adjustments (5 AM cutoff)
start_cols = [c for c in df.columns if 'start' in c.lower()]
end_cols = [c for c in df.columns if 'end' in c.lower()]

start_col = start_cols[0] if start_cols else df.columns[0]
end_col = end_cols[0] if end_cols else df.columns[0]

df['start_dt'] = pd.to_datetime(df[start_col], errors='coerce').fillna(pd.Timestamp.now())
df['end_dt'] = pd.to_datetime(df[end_col], errors='coerce').fillna(df['start_dt'])

def assign_op_date_and_day(dt):
    op_dt = dt - pd.Timedelta(days=1) if dt.hour < 5 else dt
    return op_dt.strftime('%Y-%m-%d'), op_dt.strftime('%A')

res = df['start_dt'].apply(assign_op_date_and_day)
df['date_str'] = [r[0] for r in res]
df['day_name'] = [r[1] for r in res]
df['time_visited'] = df['start_dt'].dt.strftime('%I:%M %p')

df['survey_duration_min'] = (df['end_dt'] - df['start_dt']).dt.total_seconds() / 60.0
df = df.sort_values(by=['field_officer', 'start_dt']).reset_index(drop=True)

df['prev_end'] = df.groupby(['field_officer', 'date_str'])['end_dt'].shift(1)
df['transit_gap_min'] = (df['start_dt'] - df['prev_end']).dt.total_seconds() / 60.0

df_coords = df.dropna(subset=['lat', 'lon']).copy()

if df_coords.empty:
    st.error("No valid GPS coordinates found in dataset.")
    st.stop()

# 5. HAVERSINE & AUDIT STATUS LOGIC
def haversine_km(lat1, lon1, lat2, lon2):
    if pd.isnull(lat1) or pd.isnull(lon1) or pd.isnull(lat2) or pd.isnull(lon2):
        return 0.0
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

df_coords['prev_lat'] = df_coords.groupby(['field_officer', 'date_str'])['lat'].shift(1)
df_coords['prev_lon'] = df_coords.groupby(['field_officer', 'date_str'])['lon'].shift(1)
df_coords['dist_km'] = df_coords.apply(lambda r: haversine_km(r['prev_lat'], r['prev_lon'], r['lat'], r['lon']), axis=1)

def evaluate_point_status(row):
    start_hour = row['start_dt'].hour
    if start_hour < 6 or start_hour >= 21:
        return "Critical Outlier (Late Night)"
    elif row['dist_km'] < 0.01 and row['survey_duration_min'] < 3.0:
        return "Critical Outlier (0km / Low Duration)"
    elif row['dist_km'] <= 0.5:
        return "Low Distance / Genuine"
    return "Normal Fieldwork"

df_coords['audit_status'] = df_coords.apply(evaluate_point_status, axis=1)
df_coords['dist_km'] = df_coords['dist_km'].fillna(0).round(2)
df_coords['coord_key'] = df_coords['lat'].round(5).astype(str) + '_' + df_coords['lon'].round(5).astype(str)

# 6. STREAMLIT FILTERS & METRICS
st.sidebar.header("🔍 Dashboard Filters")
counties = ["All"] + sorted(list(df_coords['county'].unique()))
sel_county = st.sidebar.selectbox("Select County", counties)

dates = ["All"] + sorted(list(df_coords['date_str'].unique()), reverse=True)
sel_date = st.sidebar.selectbox("Select Date", dates)

filtered_df = df_coords.copy()
if sel_county != "All":
    filtered_df = filtered_df[filtered_df['county'] == sel_county]
if sel_date != "All":
    filtered_df = filtered_df[filtered_df['date_str'] == sel_date]

officers = ["All"] + sorted(list(filtered_df['field_officer'].unique()))
sel_officer = st.sidebar.selectbox("Select Recruitment Officer", officers)

if sel_officer != "All":
    filtered_df = filtered_df[filtered_df['field_officer'] == sel_officer]

# Metrics Bar
col1, col2, col3, col4 = st.columns(4)
col1.metric("Farmers Recruited", len(filtered_df))
col2.metric("Acres Committed", f"{filtered_df['acres_committed'].sum():.2f} Ac")
col3.metric("Villages Covered", filtered_df['clean_village'].nunique())
col4.metric("Critical Audit Flags", len(filtered_df[filtered_df['audit_status'].str.contains("Critical")]))

# 7. LEAFLET INTERACTIVE MAP GENERATION
records = filtered_df[['farmer_name', 'field_officer', 'county', 'clean_village', 'acres_committed', 'lat', 'lon', 'date_str', 'day_name', 'time_visited', 'audit_status', 'dist_km', 'survey_duration_min', 'coord_key']].to_dict(orient='records')
records_json = json.dumps(records)

html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: Arial; }}
        #map {{ height: 680px; width: 100%; border-radius: 8px; }}
        .warning {{ color: #C00000; font-weight: bold; }}
        .normal {{ color: #385723; font-weight: bold; }}
    </style>
</head>
<body>
<div id="map"></div>
<script>
    var rawData = {records_json};
    var map = L.map('map').setView([-2.4, 38.0], 8);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 18 }}).addTo(map);

    var layerGroup = L.layerGroup().addTo(map);
    var colors = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#008080', '#9a6324', '#e6beff', '#800000'];
    var officers = [...new Set(rawData.map(d => d.field_officer))].sort();
    var colorMap = {{}};
    officers.forEach((o, i) => colorMap[o] = colors[i % colors.length]);

    var groupedCoords = {{}};
    rawData.forEach(d => {{
        if(!groupedCoords[d.coord_key]) groupedCoords[d.coord_key] = [];
        groupedCoords[d.coord_key].push(d);
    }});

    Object.keys(groupedCoords).forEach(key => {{
        var items = groupedCoords[key];
        items.forEach((d, idx) => {{
            var c = colorMap[d.field_officer];
            var isWarn = d.audit_status.includes('Critical');
            
            var lat = d.lat, lon = d.lon;
            if (items.length > 1 && idx > 0) {{
                var angle = idx * (2 * Math.PI / 6);
                var radius = 0.00025 * Math.ceil(idx / 6);
                lat += radius * Math.cos(angle);
                lon += radius * Math.sin(angle);
            }}

            var marker = L.circleMarker([lat, lon], {{
                radius: items.length > 1 ? 7 : 6,
                fillColor: c,
                color: isWarn ? '#ff0000' : '#000',
                weight: isWarn ? 2 : 1,
                fillOpacity: 0.85
            }});

            var popup = `<div style="font-size:12px; width:230px;">
                <b style="color:#0A3A2A;">${{d.farmer_name}}</b> ${{items.length > 1 ? `<span style="background:#e1f5fe; color:#0288d1; padding:2px 4px; border-radius:3px; font-size:10px; float:right;">Pt ${{idx+1}} of ${{items.length}}</span>` : ''}}<br/>
                <b>Officer:</b> ${{d.field_officer}}<br/>
                <b>Date:</b> ${{d.date_str}} (${{d.day_name}})<br/>
                <b>Time:</b> ${{d.time_visited}}<br/><hr style="margin:4px 0;"/>
                <b>County:</b> ${{d.county}}<br/>
                <b>Village:</b> ${{d.clean_village}}<br/>
                <b>Acres Committed:</b> ${{d.acres_committed.toFixed(2)}} Ac<br/><hr style="margin:4px 0;"/>
                <b>Audit Status:</b> <span class="${{isWarn ? 'warning' : 'normal'}}">${{d.audit_status}}</span><br/>
                <i>Transit Dist: ${{d.dist_km}} km</i><br/>
                <i>Survey Duration: ${{d.survey_duration_min.toFixed(1)}} mins</i>
            </div>`;

            marker.bindPopup(popup);
            layerGroup.addLayer(marker);
        }});
    }});

    if(rawData.length > 0) {{
        var bounds = rawData.map(d => [d.lat, d.lon]);
        map.fitBounds(bounds, {{padding: [30, 30], maxZoom: 14}});
    }}
</script>
</body>
</html>
"""

st.subheader("Interactive Preselection & Movement Map")
components.html(html_code, height=700)
