import streamlit as st
import pandas as pd
import numpy as np
import json
import requests
import streamlit.components.v1 as components

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="OND 2026 Vetting Farmers Dashboard",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 OND 2026 Vetting Farmers — Live GPS Audit & Analytics")

# 2. CREDENTIALS & API SETUP
API_TOKEN = "558c639f2c31d384271394486b678df92f28a341"
ASSET_UID = "azi42PaQTVCKXoD4dBA2o4"

# Primary KC API v1 Endpoint
DATA_URL = f"https://kc.kobotoolbox.org/api/v1/data/{ASSET_UID}.json"

@st.cache_data(ttl=300)  # Fetches fresh data every 5 minutes
def load_kobo_data():
    headers = {"Authorization": f"Token {API_TOKEN}"}
    try:
        response = requests.get(DATA_URL, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return pd.DataFrame(data)
        else:
            # Fallback to KF API v2 if KC v1 structure differs
            v2_url = f"https://kf.kobotoolbox.org/api/v2/assets/{ASSET_UID}/data.json"
            res2 = requests.get(v2_url, headers=headers, timeout=30)
            if res2.status_code == 200:
                return pd.DataFrame(res2.json().get('results', []))
            st.error(f"API Error {response.status_code}: {response.text}")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Connection failed: {str(e)}")
        return pd.DataFrame()

# Sidebar Controls
st.sidebar.header("⚙️ Data Settings")
if st.sidebar.button("🔄 Refresh Data From Kobo"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Connecting to KoboToolbox and fetching live submissions..."):
    df_raw = load_kobo_data()

if df_raw.empty:
    st.warning("No data retrieved from KoboToolbox. Check API connection.")
    st.stop()

# 3. DATA CLEANING & TRANSFORMATION
df = df_raw.copy()

# Standardize Field Officer Names
fo_clean = {
    'Caroline': 'Caroline Kalovoto', 'Kklonzi': 'Kilonzi', 'Dou': 'Douglas',
    'Dominic': 'Dominic Kioko', 'Amani Thoya Karisa': 'Amani Thoya',
    'Paul Kamau Muraya': 'Paul Kamau', 'Paul kamau muraya': 'Paul Kamau',
    'Pk And Mary': 'PK & Mary', 'Pk and mary': 'PK & Mary', 'Peter And Mary': 'PK & Mary',
    'Dominic kioko': 'Dominic Kioko', 'Francis kisese': 'Francis Kisese',
    'Peter king\'ola': 'Peter King\'ola', 'Shadrack kieti': 'Shadrack Kieti'
}

officer_col = [c for c in df.columns if 'officer' in c.lower() or 'Field Officer' in c][0]
df['officer'] = df[officer_col].astype(str).str.strip().replace(fo_clean).str.title()

# Time & Operational Date Adjustment (5 AM cutoff)
start_col = [c for c in df.columns if 'start' in c.lower()][0]
df['start_dt'] = pd.to_datetime(df[start_col])

def assign_op_date_and_day(dt):
    op_dt = dt - pd.Timedelta(days=1) if dt.hour < 5 else dt
    return op_dt.strftime('%Y-%m-%d'), op_dt.strftime('%A')

res = df['start_dt'].apply(assign_op_date_and_day)
df['date_str'] = [r[0] for r in res]
df['day_name'] = [r[1] for r in res]
df['time_visited'] = df['start_dt'].dt.strftime('%I:%M %p')

# Farmer & Location Details
farmer_col = [c for c in df.columns if 'farmer' in c.lower() or 'Farmer Name' in c][0]
df['farmer'] = df[farmer_col].fillna('Unknown').astype(str).str.title()

county_col = [c for c in df.columns if 'county' in c.lower()][0]
df['county'] = df[county_col].astype(str).str.strip().str.title()

loc_col = [c for c in df.columns if 'location' in c.lower() and 'farm' not in c.lower()][0]
df['location'] = df[loc_col].astype(str).str.strip().str.title()

vill_col = [c for c in df.columns if 'village' in c.lower()][0]
df['village'] = df[vill_col].astype(str).str.strip().str.title()

# Acres Parsing
acre_col = [c for c in df.columns if 'acre' in c.lower()][0]
raw_acres = df[acre_col].astype(str).str.replace(',', '.', regex=False).str.strip()
numeric_acres = pd.to_numeric(raw_acres, errors='coerce').fillna(0).clip(lower=0)
df['acres'] = np.where(numeric_acres > 20.0, 0.0, numeric_acres)

app_col = [c for c in df.columns if 'approve' in c.lower()][0]
df['approved'] = df[app_col].fillna('Unknown').astype(str).str.title()

# Extract Latitude & Longitude (Handles both separate columns and Kobo GPS strings)
lat_cols = [c for c in df.columns if 'latitude' in c.lower()]
lon_cols = [c for c in df.columns if 'longitude' in c.lower()]

if lat_cols and lon_cols:
    df['lat'] = pd.to_numeric(df[lat_cols[0]], errors='coerce')
    df['lon'] = pd.to_numeric(df[lon_cols[0]], errors='coerce')
elif '_geolocation' in df.columns:
    df['lat'] = df['_geolocation'].apply(lambda x: float(x[0]) if isinstance(x, list) and len(x)>1 else np.nan)
    df['lon'] = df['_geolocation'].apply(lambda x: float(x[1]) if isinstance(x, list) and len(x)>1 else np.nan)
elif '_Farm_Location' in df.columns or 'Farm Location' in df.columns:
    gps_col = '_Farm_Location' if '_Farm_Location' in df.columns else 'Farm Location'
    df['lat'] = df[gps_col].apply(lambda x: float(str(x).split()[0]) if pd.notnull(x) and len(str(x).split())>=2 else np.nan)
    df['lon'] = df[gps_col].apply(lambda x: float(str(x).split()[1]) if pd.notnull(x) and len(str(x).split())>=2 else np.nan)

df_coords = df.dropna(subset=['lat', 'lon']).copy()

# 4. AUDIT CALCULATION (Haversine & Overlaps)
df_coords = df_coords.sort_values(by=['officer', 'start_dt']).reset_index(drop=True)

def haversine_km(lat1, lon1, lat2, lon2):
    if pd.isnull(lat1) or pd.isnull(lon1) or pd.isnull(lat2) or pd.isnull(lon2):
        return 0.0
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

df_coords['prev_lat'] = df_coords.groupby(['officer', 'date_str'])['lat'].shift(1)
df_coords['prev_lon'] = df_coords.groupby(['officer', 'date_str'])['lon'].shift(1)
df_coords['dist_from_prev_km'] = df_coords.apply(lambda r: haversine_km(r['prev_lat'], r['prev_lon'], r['lat'], r['lon']), axis=1)

def flag_status(row):
    if pd.notnull(row['dist_from_prev_km']) and row['dist_from_prev_km'] < 0.01:
        return "⚠️ Suspicious (0km from last farm)"
    elif pd.notnull(row['dist_from_prev_km']) and row['dist_from_prev_km'] > 50:
        return "🚨 GPS Outlier (>50km jump)"
    return "✅ Valid GPS Distance"

df_coords['audit_status'] = df_coords.apply(flag_status, axis=1)
df_coords['dist_from_prev_km'] = df_coords['dist_from_prev_km'].fillna(0).round(2)
df_coords['coord_key'] = df_coords['lat'].round(5).astype(str) + '_' + df_coords['lon'].round(5).astype(str)

# 5. STREAMLIT FILTERS
st.sidebar.header("🔍 Filters")
counties = ["All"] + sorted(list(df_coords['county'].unique()))
sel_county = st.sidebar.selectbox("Select County", counties)

dates = ["All"] + sorted(list(df_coords['date_str'].unique()), reverse=True)
sel_date = st.sidebar.selectbox("Select Date", dates)

filtered_df = df_coords.copy()
if sel_county != "All":
    filtered_df = filtered_df[filtered_df['county'] == sel_county]
if sel_date != "All":
    filtered_df = filtered_df[filtered_df['date_str'] == sel_date]

officers = ["All"] + sorted(list(filtered_df['officer'].unique()))
sel_officer = st.sidebar.selectbox("Select Field Officer", officers)

if sel_officer != "All":
    filtered_df = filtered_df[filtered_df['officer'] == sel_officer]

# Metrics Overview Bar
col1, col2, col3, col4 = st.columns(4)
col1.metric("Farmers Vetted", len(filtered_df))
col2.metric("Acres Vetted", f"{filtered_df['acres'].sum():.1f}")
col3.metric("Farmers Approved", len(filtered_df[filtered_df['approved'].isin(['Yes', 'Approved'])]))

overlap_groups_count = (filtered_df.groupby('coord_key').size() > 1).sum()
col4.metric("GPS Overlap Groups", overlap_groups_count)

# 6. LEAFLET MAP GENERATION
records = filtered_df[['farmer', 'officer', 'county', 'location', 'village', 'acres', 'approved', 'lat', 'lon', 'date_str', 'day_name', 'time_visited', 'audit_status', 'dist_from_prev_km', 'coord_key']].to_dict(orient='records')
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
        .farmer-item {{ background: #f4f6f8; padding: 4px; margin: 3px 0; border-radius: 3px; font-size: 11px; }}
        .warning {{ color: #C00000; font-weight: bold; }}
    </style>
</head>
<body>
<div id="map"></div>
<script>
    var rawData = {records_json};
    var map = L.map('map').setView([-2.4, 38.0], 8);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 18 }}).addTo(map);

    var layerGroup = L.layerGroup().addTo(map);
    var colors = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#008080', '#9a6324', '#e6beff', '#9a6324', '#800000'];
    var officers = [...new Set(rawData.map(d => d.officer))].sort();
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
            var c = colorMap[d.officer];
            var isWarn = d.audit_status.includes('⚠️') || d.audit_status.includes('🚨');
            
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

            var popup = `<div style="font-size:12px; width:220px;">
                <b style="color:#1F4E78;">${{d.farmer}}</b> ${{items.length > 1 ? `<span style="background:#e1f5fe; color:#0288d1; padding:2px 4px; border-radius:3px; font-size:10px; float:right;">Pt ${{idx+1}} of ${{items.length}}</span>` : ''}}<br/>
                <b>Officer:</b> ${{d.officer}}<br/>
                <b>Date:</b> ${{d.date_str}} (${{d.day_name}})<br/>
                <b>Time:</b> ${{d.time_visited}}<br/><hr style="margin:4px 0;"/>
                <b>County:</b> ${{d.county}}<br/>
                <b>Loc/Vill:</b> ${{d.location}} / ${{d.village}}<br/>
                <b>Acres:</b> ${{d.acres.toFixed(1)}} (App: ${{d.approved}})<br/><hr style="margin:4px 0;"/>
                <b>Status:</b> <span class="${{isWarn ? 'warning' : ''}}">${{d.audit_status}}</span><br/>
                <i>Dist from prev: ${{d.dist_from_prev_km}} km</i>
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

st.subheader(" Interactive Farmer Map")
components.html(html_code, height=700)
