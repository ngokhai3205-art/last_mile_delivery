# app.py — Last-mile Delivery Vehicle Recommender
# Google Maps-like routes + ORS fallback + Streamlit/Folium UI

import os
import math
import datetime as dt
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st
import folium
import polyline
from streamlit_folium import st_folium

try:
    import openrouteservice as ors
except Exception:
    ors = None

try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    _geolocator = Nominatim(user_agent="last-mile-delivery-hanoi", timeout=10)
    _geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)
except Exception:
    _geolocator, _geocode = None, None

Coordinate = Tuple[float, float]

# -------------------- PAGE CONFIG --------------------
st.set_page_config(
    page_title="Last-mile Delivery Vehicle Recommender",
    page_icon="🚚",
    layout="wide",
)

# -------------------- CSS --------------------
st.markdown(
    """
    <style>
    .main-title {
        font-size: 34px;
        font-weight: 800;
        margin-bottom: 4px;
    }
    .sub-title {
        color: #5b6472;
        font-size: 16px;
        margin-bottom: 22px;
    }
    .metric-card {
        padding: 16px 18px;
        border-radius: 16px;
        background: #ffffff;
        border: 1px solid #e6e8ec;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    }
    .best-box {
        border-left: 6px solid #16a34a;
        padding: 18px;
        border-radius: 14px;
        background: #f0fdf4;
        margin-bottom: 12px;
    }
    .warning-box {
        border-left: 6px solid #f59e0b;
        padding: 14px;
        border-radius: 12px;
        background: #fffbeb;
    }
    .route-box {
        padding: 12px 14px;
        border-radius: 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        margin-bottom: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------- VEHICLES --------------------
VEHICLES = [
    {
        "name": "Truck",
        "type": "truck",
        "max_weight": 2000,
        "speed_kmh": 25,
        "base_cost": 50000,
        "cost_per_km": 8000,
        "co2_factor": 0.75,
        "good_for": ["Heavy cargo", "Bulky cargo", "Industrial cargo"],
        "note": "Suitable for heavy cargo, large items, long routes, or high payload requirements.",
    },
    {
        "name": "Van",
        "type": "van",
        "max_weight": 800,
        "speed": 30,
        "base_cost": 30000,
        "cost_per_km": 6000,
        "co2_factor": 0.45,
        "good_for": ["Groceries", "Fragile cargo", "Medium cargo", "High-value cargo"],
        "note": "Protects goods well; suitable for heavy rain and cargo that needs cover.",
    },
    {
         "name": "Motorbike / Electric bike",
        "type": "motorbike",
        "max_weight": 30,
        "speed": 35,
        "base_cost": 10000,
        "cost_per_km": 4000,
        "good_for": ["Documents", "Food", "Light cargo", "Small medical items"],
        "note": "Flexible in urban areas; suitable for traffic congestion and small orders.",
    },
    {
    "name": "Drone",
        "type": "drone",
        "max_weight": 5,
        "speed": 45,
        "base_cost": 20000,
        "cost_per_km": 5000,
        "co2_factor": 0.05,
        "good_for": ["Documents", "Small medical items", "Very urgent cargo"],
        "note": "Very fast for light cargo, but depends on weather and distance limits.",
    },
]

CARGO_WEIGHT_HINT = {
    "Documents": 2,
    "Food": 5,
    "Groceries": 15,
    "Light cargo": 10,
    "Medium cargo": 80,
    "Heavy cargo": 300,
    "Bulky cargo": 600,
    "Fragile cargo": 30,
    "High-value cargo": 20,
    "Small medical items": 3,
    "Very urgent cargo": 2,
    "Industrial cargo": 1200,
}

PRESETS = {
    "Hoan Kiem Lake": (21.028511, 105.852005),
    "Hanoi Tower": (21.026754, 105.846083),
    "My Dinh Bus Station": (21.028762, 105.776900),
    "Noi Bai Airport": (21.214184, 105.802827),
    "Hanoi University of Science and Technology": (21.005312, 105.843066),
    "Royal City": (21.002750, 105.815690),
    "Times City": (20.994540, 105.868650),
    "Aeon Mall Long Bien": (21.027500, 105.899800),
}

# -------------------- BASIC HELPERS --------------------
def get_secret(name: str) -> Optional[str]:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    value = os.getenv(name)
    return value if value else None


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    radius = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(x))


def geocode_address(address: str) -> Optional[Coordinate]:
    if not address or not _geocode:
        return None
    query = address
    if "vietnam" not in query.lower() and "vietnam" not in query.lower():
        query += ", Hanoi, Vietnam"
    loc = _geocode(query)
    if not loc:
        return None
    return (loc.latitude, loc.longitude)

# -------------------- WEATHER / TRAFFIC --------------------
def weather_from_code(code: int, wind_kmh: float) -> str:
    if code in [95, 96, 99] or wind_kmh >= 50:
        return "Storm/Strong wind"
    if (51 <= code <= 67) or (80 <= code <= 82) or (61 <= code <= 65):
        return "Rain"
    return "Good"


def get_weather_and_flood(lat: float, lon: float) -> Dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "hourly": "precipitation",
        "past_days": 1,
        "timezone": "auto",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    js = r.json()
    cw = js.get("current_weather", {})
    code = int(cw.get("weathercode", 0))
    wind = float(cw.get("windspeed", 0))
    weather = weather_from_code(code, wind)
    precip = js.get("hourly", {}).get("precipitation", [])
    precip_sum = sum(p for p in precip if isinstance(p, (int, float)))
    if precip_sum >= 150:
        flood = "Heavy"
    elif precip_sum >= 80:
        flood = "Localized"
    else:
        flood = "None"
    hour_local = int(cw.get("time", "2024-01-01T12:00")[11:13]) if cw.get("time") else dt.datetime.now().hour
    return {
        "weather": weather,
        "flood": flood,
        "wind_kmh": wind,
        "rain_24h_mm": round(precip_sum, 1),
        "hour": hour_local,
        "timezone": js.get("timezone", "local"),
    }


def estimate_traffic_level(hour_local: int, weather: str) -> str:
    weekday = dt.datetime.now().weekday()
    if weekday < 5 and (7 <= hour_local <= 9 or 16 <= hour_local <= 19):
        level = "High"
    elif weekday < 5 and (10 <= hour_local <= 15):
        level = "Medium"
    else:
        level = "Low"

    levels = ["Low", "Medium", "High"]
    bump = 0
    if weather == "Rain":
        bump = 1
    elif weather == "Storm/Strong wind":
        bump = 2
    return levels[min(2, levels.index(level) + bump)]

# -------------------- ROUTING --------------------
def get_google_routes(origin: Coordinate, destination: Coordinate, api_key: str) -> List[Dict]:
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "alternatives": "true",
        "mode": "driving",
        "language": "en",
        "region": "vn",
        "departure_time": "now",
        "key": api_key,
    }
    res = requests.get(url, params=params, timeout=20)
    res.raise_for_status()
    data = res.json()
    if data.get("status") != "OK":
        raise RuntimeError(data.get("error_message") or data.get("status") or "Google Directions error")

    routes = []
    for idx, route in enumerate(data.get("routes", [])):
        leg = route["legs"][0]
        duration_value = leg.get("duration_in_traffic", leg.get("duration", {})).get("value", 0)
        normal_duration = leg.get("duration", {}).get("value", duration_value)
        routes.append(
            {
                "source": "Google Directions",
                "name": route.get("summary") or f"Route {idx + 1}",
                "distance_km": leg["distance"]["value"] / 1000,
                "duration_min": duration_value / 60,
                "normal_duration_min": normal_duration / 60,
                "path": polyline.decode(route["overview_polyline"]["points"]),
                "start_address": leg.get("start_address", ""),
                "end_address": leg.get("end_address", ""),
            }
        )
    return routes


def ors_client():
    if ors is None:
        return None
    key = get_secret("ORS_API_KEY")
    if not key:
        return None
    return ors.Client(key=key, base_url="https://api.openrouteservice.org", timeout=20)


def get_ors_route(origin: Coordinate, destination: Coordinate, profile: str) -> Dict:
    client = ors_client()
    if client is None:
        raise RuntimeError("ORS_API_KEY is missing")
    coords = [(origin[1], origin[0]), (destination[1], destination[0])]
    res = client.directions(coordinates=coords, profile=profile, format="geojson")
    feature = res["features"][0]
    line = feature["geometry"]["coordinates"]
    path = [(p[1], p[0]) for p in line]
    summary = feature["properties"]["summary"]
    return {
        "source": "OpenRouteService",
        "name": f"ORS {profile}",
        "distance_km": summary["distance"] / 1000,
        "duration_min": summary["duration"] / 60,
        "normal_duration_min": summary["duration"] / 60,
        "path": path,
        "start_address": "",
        "end_address": "",
    }


def fallback_straight_route(origin: Coordinate, destination: Coordinate) -> Dict:
    dist = haversine_km(origin, destination)
    return {
        "source": "Straight-line estimate",
        "name": "Estimated straight line",
        "distance_km": dist,
        "duration_min": (dist / 28) * 60,
        "normal_duration_min": (dist / 28) * 60,
        "path": [origin, destination],
        "start_address": "",
        "end_address": "",
    }

# -------------------- VEHICLE SCORING --------------------
def traffic_multiplier(traffic: str) -> float:
    return {"Low": 1.0, "Medium": 1.2, "High": 1.55}.get(traffic, 1.2)


def weather_multiplier(weather: str) -> float:
    return {"Good": 1.0, "Rain": 1.18, "Storm/Strong wind": 1.7}.get(weather, 1.0)


def flood_multiplier(flood: str) -> float:
    return {"None": 1.0, "Localized": 1.15, "Heavy": 1.6}.get(flood, 1.0)


def evaluate_vehicle(
    vehicle: Dict,
    cargo_type: str,
    weight_kg: float,
    urgency: str,
    traffic: str,
    weather: str,
    flood: str,
    route: Dict,
    drone_limit_km: float,
    priority: str,
) -> Dict:
    """Scores one vehicle for one delivery route.

    This function has been cleaned up to:
    - avoid indentation errors / return outside function errors
    - use the correct distance variable instead of dist_km
    - use the correct English labels: High, Rain, Storm/Strong wind, Heavy
    - safely handle vehicles missing speed_kmh or co2_factor
    """
    distance = float(route.get("distance_km", 0) or 0)
    base_time = float(route.get("duration_min", 0) or 0)

    vehicle_speed = float(vehicle.get("speed_kmh", vehicle.get("speed", 30)) or 30)

    # -------------------- TIME --------------------
    # Route time is usually based on the driving-car profile. Adjust it by each vehicle speed.
    speed_adjust = 30 / vehicle_speed
    time_min = max(1.0, base_time * speed_adjust)

    if vehicle["type"] == "motorbike" and traffic == "High":
        time_min *= 0.78
    if vehicle["type"] in ["van", "truck"] and traffic == "High":
        time_min *= 1.12
    if weather == "Rain" and vehicle["type"] in ["motorbike", "drone"]:
        time_min *= 1.25
    if weather == "Storm/Strong wind" and vehicle["type"] in ["motorbike", "drone"]:
        time_min *= 1.8
    if flood == "Heavy" and vehicle["type"] in ["motorbike", "van"]:
        time_min *= 1.35

    # -------------------- COST --------------------
    cost = vehicle["base_cost"] + distance * vehicle["cost_per_km"]

    # Increase cost based on real urban conditions.
    if traffic == "High":
        cost *= 1.2
    if weather == "Storm/Strong wind":
        cost *= 1.3
    if flood == "Heavy":
        cost *= 1.25
    if vehicle["type"] == "drone" and distance > 5:
        cost *= 1.5
    if traffic == "High" and vehicle["type"] in ["van", "truck"]:
        cost *= 1.15
    if weather in ["Rain", "Storm/Strong wind"] and vehicle["type"] == "motorbike":
        cost *= 1.1

    # -------------------- EMISSION --------------------
    emissions = distance * float(vehicle.get("co2_factor", 0.12))

    # -------------------- SCORE --------------------
    score = 100.0
    reasons = []
    warnings = []

    # Payload
    if weight_kg <= vehicle["max_weight"]:
        score += 18
        reasons.append("Meets payload requirement")
    else:
        score -= 120
        warnings.append("Exceeds payload limit")

    # Cargo type
    if cargo_type in vehicle["good_for"]:
        score += 20
        reasons.append("Suitable for cargo type")
    else:
        score -= 8

    # Drone constraints
    if vehicle["type"] == "drone":
        if distance > drone_limit_km:
            score -= 100
            warnings.append("Exceeds drone distance limit")
        if weight_kg > vehicle["max_weight"]:
            score -= 80
        if weather == "Storm/Strong wind":
            score -= 120
            warnings.append("Drone is unsafe in strong wind/storms")
        if flood == "Heavy":
            score -= 20

    # Traffic
    if traffic == "High":
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 24
            reasons.append("Flexible in traffic congestion")
        else:
            score -= 18

    # Weather
    if weather in ["Rain", "Storm/Strong wind"]:
        if vehicle["type"] == "van":
            score += 18
            reasons.append("Protects cargo well in bad weather")
        if vehicle["type"] == "truck":
            score += 10
        if vehicle["type"] == "motorbike":
            score -= 20
            warnings.append("Motorbikes are less stable in rain/wind")

    # Flooding
    if flood == "Heavy":
        if vehicle["type"] == "truck":
            score += 25
            reasons.append("High ground clearance, suitable for heavy flooding")
        if vehicle["type"] == "motorbike":
            score -= 28

    # Urgency
    if urgency == "Very urgent (≤2h)":
        if vehicle["type"] in ["drone", "motorbike"]:
            score += 26
            reasons.append("Suitable for urgent orders")
        else:
            score -= 10
    elif urgency == "Urgent":
        if vehicle["type"] in ["motorbike", "van"]:
            score += 12

    # Optimization goal
    if priority == "Lowest cost":
        score -= cost / 20000
        score -= time_min / 18
        score -= emissions * 1.5
    elif priority == "Fastest":
        score -= time_min / 6
        score -= cost / 18000
    elif priority == "Balanced":
        score -= cost / 12000
        score -= time_min / 10
        score -= emissions
    else:  # Eco-friendly
        score -= emissions * 6
        score -= cost / 15000
        score -= time_min / 12
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 12

    # Distance-based bonus
    if distance <= 3 and vehicle["type"] == "motorbike":
        score += 10
    if distance > 15 and vehicle["type"] in ["van", "truck"]:
        score += 8

    return {
        "Vehicle": vehicle.get("name", "Unknown"),
        "Score": round(max(0, score), 2),
        "Cost (VND)": int(round(cost)),
        "Time (minutes)": int(round(max(1, time_min))),
        "Maximum payload (kg)": vehicle.get("max_weight", 0),
        "Estimated CO₂ (kg)": round(emissions, 2),
        "Reason": "; ".join(reasons) if reasons else "Moderately suitable",
        "Warning": "; ".join(warnings) if warnings else "None",
        "Note": vehicle.get("note", ""),
    }


def evaluate_all_vehicles(*args, **kwargs) -> List[Dict]:
    results = [evaluate_vehicle(v, *args, **kwargs) for v in VEHICLES]
    return sorted(results, key=lambda x: x["Score"], reverse=True)

# -------------------- UI HEADER --------------------
st.markdown('<div class="main-title">🚚 Last-mile Delivery Vehicle Recommender</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Choose a Google Maps-like route and recommend the optimal delivery vehicle for urban Hanoi.</div>',
    unsafe_allow_html=True,
)

# -------------------- SIDEBAR INPUTS --------------------
with st.sidebar:
    st.header("⚙️ Settings")
    auto_status = st.checkbox("Automatically fetch weather & infer traffic", value=True)
    use_real_route = st.checkbox("Use real routes if an API key is available", value=True)
    drone_limit = st.number_input("Drone distance limit (km)", min_value=1, max_value=50, value=10)
    priority = st.selectbox(
        "Optimization goal",
        ["Balanced", "Lowest cost", "Fastest", "Eco-friendly"],
        index=0,
    )
    st.info("To get multiple Google Maps-like routes, add GOOGLE_MAPS_API_KEY in Streamlit Secrets.")

# -------------------- INPUT LOCATIONS --------------------
st.markdown("## 1. Pickup and delivery locations")
mode = st.radio(
    "Choose location input method",
    ["Sample Hanoi locations", "Enter coordinates", "Enter addresses"],
    horizontal=True,
)

origin = None
destination = None

if mode == "Sample Hanoi locations":
    col1, col2 = st.columns(2)
    with col1:
        origin_name = st.selectbox("Pickup location", list(PRESETS.keys()), index=1)
    with col2:
        dest_name = st.selectbox("Delivery location", list(PRESETS.keys()), index=2)
    origin = PRESETS[origin_name]
    destination = PRESETS[dest_name]

elif mode == "Enter coordinates":
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Pickup location")
        o_lat = st.number_input("Pickup latitude", value=21.026754, format="%.6f")
        o_lon = st.number_input("Pickup longitude", value=105.846083, format="%.6f")
    with col2:
        st.caption("Delivery location")
        d_lat = st.number_input("Delivery latitude", value=21.028762, format="%.6f")
        d_lon = st.number_input("Delivery longitude", value=105.776900, format="%.6f")
    origin = (o_lat, o_lon)
    destination = (d_lat, d_lon)

else:
    if "geo" not in st.session_state:
        st.session_state.geo = {"origin": None, "destination": None}
    col1, col2 = st.columns(2)
    with col1:
        start_addr = st.text_input("Pickup address", "Hanoi Tower, Hanoi")
    with col2:
        dest_addr = st.text_input("Delivery address", "My Dinh Bus Station, Hanoi")
    if st.button("📍 Get coordinates from address"):
        if not _geocode:
            st.error("Geocoder is not available. Please use coordinates or sample locations.")
        else:
            with st.spinner("Finding coordinates..."):
                loc1 = geocode_address(start_addr)
                loc2 = geocode_address(dest_addr)
            if loc1 and loc2:
                st.session_state.geo = {"origin": loc1, "destination": loc2}
                st.success("Coordinates retrieved successfully.")
            else:
                st.error("Address not found. Please enter a more specific address.")
    origin = st.session_state.geo["origin"]
    destination = st.session_state.geo["destination"]

# -------------------- ORDER INPUTS --------------------
st.markdown("## 2. Order information")
col1, col2, col3, col4 = st.columns(4)
with col1:
    cargo_type = st.selectbox("Cargo type", list(CARGO_WEIGHT_HINT.keys()), index=0)
with col2:
    default_weight = CARGO_WEIGHT_HINT[cargo_type]
    weight_kg = st.number_input("Cargo weight (kg)", min_value=0.1, max_value=2500.0, value=float(default_weight), step=0.5)
with col3:
    urgency = st.selectbox("Urgency level", ["Low", "Normal", "Urgent", "Very urgent (≤2h)"], index=1)
with col4:
    manual_distance_note = st.empty()

# -------------------- STATUS --------------------
st.markdown("## 3. Route conditions")
status_source = "Manual"
weather = "Good"
flood = "None"
traffic = "Medium"
weather_details = {}

if origin and destination and auto_status:
    try:
        weather_details = get_weather_and_flood(*origin)
        weather = weather_details["weather"]
        flood = weather_details["flood"]
        traffic = estimate_traffic_level(weather_details["hour"], weather)
        status_source = "Automatic"
    except Exception as exc:
        st.warning(f"Could not fetch weather automatically: {exc}. Switching to manual input.")

if not auto_status or status_source == "Manual":
    col1, col2, col3 = st.columns(3)
    with col1:
        traffic = st.selectbox("Traffic", ["Low", "Medium", "High"], index=1)
    with col2:
        weather = st.selectbox("Weather", ["Good", "Rain", "Storm/Strong wind"], index=0)
    with col3:
        flood = st.selectbox("Flooding", ["None", "Localized", "Heavy"], index=0)
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Traffic", traffic)
    c2.metric("Weather", weather)
    c3.metric("Flooding", flood)
    c4.metric("24h rain", f"{weather_details.get('rain_24h_mm', 0)} mm")

# -------------------- CALCULATION --------------------
if "routes" not in st.session_state:
    st.session_state.routes = []
if "route_message" not in st.session_state:
    st.session_state.route_message = ""

calc = st.button("🚀 Calculate route & recommend vehicle", type="primary")

if calc:
    if not origin or not destination:
        st.error("Please enter both pickup and delivery locations.")
        st.stop()

    routes = []
    messages = []

    if use_real_route:
        google_key = get_secret("GOOGLE_MAPS_API_KEY")
        if google_key:
            try:
                routes = get_google_routes(origin, destination, google_key)
                messages.append(f"Retrieved {len(routes)} routes from Google Directions.")
            except Exception as exc:
                messages.append(f"Google Directions error: {exc}")
        else:
            messages.append("GOOGLE_MAPS_API_KEY is missing, so multiple Google Maps routes cannot be retrieved.")

        if not routes:
            for profile in ["driving-car", "cycling-electric", "driving-hgv"]:
                try:
                    routes.append(get_ors_route(origin, destination, profile))
                except Exception as exc:
                    messages.append(f"ORS {profile}: {exc}")
            if routes:
                messages.append("Used OpenRouteService fallback.")

    if not routes:
        routes = [fallback_straight_route(origin, destination)]
        messages.append("Using an estimated straight-line route because no valid API key is available.")

    st.session_state.routes = routes
    st.session_state.route_message = " | ".join(messages)

routes = st.session_state.routes

if routes:
    st.markdown("## 4. Choose a route")
    if st.session_state.route_message:
        if "straight-line" in st.session_state.route_message.lower() or "missing" in st.session_state.route_message.lower():
            st.warning(st.session_state.route_message)
        else:
            st.success(st.session_state.route_message)

    route_labels = [
        f"Route {i + 1}: {r['name']} — {r['distance_km']:.1f} km — {int(r['duration_min'])} min — {r['source']}"
        for i, r in enumerate(routes)
    ]
    selected_idx = st.selectbox("Choose a Google Maps-like route", range(len(routes)), format_func=lambda i: route_labels[i])
    selected_route = routes[selected_idx]

    results = evaluate_all_vehicles(
        cargo_type,
        weight_kg,
        urgency,
        traffic,
        weather,
        flood,
        selected_route,
        drone_limit,
        priority,
    )
    best = results[0]

    st.markdown("## 5. Recommendation results")
    st.markdown(
        f"""
        <div class="best-box">
            <h3>✅ Best vehicle: {best['Vehicle']}</h3>
            <p><b>Score:</b> {best['Score']} &nbsp; | &nbsp; <b>Cost:</b> {best['Cost (VND)']:,} VND &nbsp; | &nbsp; <b>Time:</b> {best['Time (minutes)']} min</p>
            <p><b>Reason:</b> {best['Reason']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Selected route", f"{selected_route['distance_km']:.1f} km")
    m2.metric("Route time", f"{int(selected_route['duration_min'])} min")
    m3.metric("Route source", selected_route["source"])
    m4.metric("Goal", priority)

    df = pd.DataFrame(results)
    st.dataframe(
        df[["Vehicle", "Score", "Cost (VND)", "Time (minutes)", "Maximum payload (kg)", "Estimated CO₂ (kg)", "Reason", "Warning"]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Detailed explanation for each vehicle"):
        for item in results:
            st.markdown(
                f"""
                <div class="route-box">
                <b>{item['Vehicle']}</b><br>
                Score: {item['Score']} | Cost: {item['Cost (VND)']:,} VND | Time: {item['Time (minutes)']} min<br>
                Reason: {item['Reason']}<br>
                Warning: {item['Warning']}<br>
                Note: {item['Note']}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # -------------------- MAP --------------------
    st.markdown("## 6. Route map")
    center = ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2)
    fmap = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")

    folium.Marker(origin, tooltip="Pickup location", popup="Pickup location", icon=folium.Icon(color="green", icon="play")).add_to(fmap)
    folium.Marker(destination, tooltip="Delivery location", popup="Delivery location", icon=folium.Icon(color="red", icon="flag")).add_to(fmap)

    route_colors = ["blue", "gray", "green", "purple", "orange"]
    for i, route in enumerate(routes):
        color = route_colors[i % len(route_colors)]
        is_selected = i == selected_idx
        tooltip = f"Route {i + 1}: {route['distance_km']:.1f} km, {int(route['duration_min'])} min"
        folium.PolyLine(
            route["path"],
            color=color,
            weight=8 if is_selected else 4,
            opacity=0.95 if is_selected else 0.35,
            tooltip=tooltip,
        ).add_to(fmap)

        # Midpoint label marker
        if route["path"]:
            mid_point = route["path"][len(route["path"]) // 2]
            folium.Marker(
                mid_point,
                tooltip=tooltip,
                icon=folium.DivIcon(
                    html=f"""
                    <div style='background:#ffffff;border:1px solid #cbd5e1;border-radius:12px;padding:4px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.15);white-space:nowrap;'>
                    {'✅ ' if is_selected else ''}Route {i+1}: {route['distance_km']:.1f} km
                    </div>
                    """
                ),
            ).add_to(fmap)

    st_folium(fmap, width=None, height=560)

else:
    st.info("Enter the information, then click **Calculate route & recommend vehicle** to begin.")

st.caption(
    "Note: Google Directions API provides multiple Google Maps-like routes if GOOGLE_MAPS_API_KEY is available. Otherwise, the app automatically falls back to OpenRouteService or an estimated straight-line route."
)
