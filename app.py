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
        "name": "Xe tải",
        "type": "truck",
        "max_weight": 2000,
        "speed_kmh": 25,
        "base_cost": 50000,
        "cost_per_km": 8000,
        "co2_factor": 0.75,
        "good_for": ["Hàng nặng", "Hàng cồng kềnh", "Hàng công nghiệp"],
        "note": "Phù hợp hàng nặng, hàng lớn, tuyến dài hoặc cần tải trọng cao.",
    },
    {
        "name": "Xe van",
        "type": "van",
        "max_weight": 800,
        "speed": 30,
        "base_cost": 30000,
        "cost_per_km": 6000,
        "co2_factor": 0.45,
        "good_for": ["Thực phẩm", "Hàng dễ vỡ", "Hàng trung bình", "Hàng giá trị cao"],
        "note": "Bảo vệ hàng tốt, phù hợp mưa lớn và hàng cần che chắn.",
    },
    {
         "name": "Xe máy / xe điện",
        "type": "motorbike",
        "max_weight": 30,
        "speed": 35,
        "base_cost": 10000,
        "cost_per_km": 4000,
        "good_for": ["Tài liệu", "Đồ ăn", "Hàng nhẹ", "Hàng y tế nhỏ"],
        "note": "Linh hoạt trong nội đô, phù hợp khi tắc đường và đơn nhỏ.",
    },
    {
    "name": "Drone",
        "type": "drone",
        "max_weight": 5,
        "speed": 45,
        "base_cost": 20000,
        "cost_per_km": 5000,
        "co2_factor": 0.05,
        "good_for": ["Tài liệu", "Hàng y tế nhỏ", "Hàng rất gấp"],
        "note": "Rất nhanh với hàng nhẹ, nhưng phụ thuộc thời tiết và giới hạn khoảng cách.",
    },
]

CARGO_WEIGHT_HINT = {
    "Tài liệu": 2,
    "Đồ ăn": 5,
    "Thực phẩm": 15,
    "Hàng nhẹ": 10,
    "Hàng trung bình": 80,
    "Hàng nặng": 300,
    "Hàng cồng kềnh": 600,
    "Hàng dễ vỡ": 30,
    "Hàng giá trị cao": 20,
    "Hàng y tế nhỏ": 3,
    "Hàng rất gấp": 2,
    "Hàng công nghiệp": 1200,
}

PRESETS = {
    "Hồ Hoàn Kiếm": (21.028511, 105.852005),
    "Hanoi Tower": (21.026754, 105.846083),
    "Bến xe Mỹ Đình": (21.028762, 105.776900),
    "Sân bay Nội Bài": (21.214184, 105.802827),
    "Đại học Bách Khoa Hà Nội": (21.005312, 105.843066),
    "Royal City": (21.002750, 105.815690),
    "Times City": (20.994540, 105.868650),
    "Aeon Mall Long Biên": (21.027500, 105.899800),
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
    if "việt nam" not in query.lower() and "vietnam" not in query.lower():
        query += ", Hà Nội, Việt Nam"
    loc = _geocode(query)
    if not loc:
        return None
    return (loc.latitude, loc.longitude)

# -------------------- WEATHER / TRAFFIC --------------------
def weather_from_code(code: int, wind_kmh: float) -> str:
    if code in [95, 96, 99] or wind_kmh >= 50:
        return "Bão/Gió mạnh"
    if (51 <= code <= 67) or (80 <= code <= 82) or (61 <= code <= 65):
        return "Mưa"
    return "Tốt"


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
    flood = "Nặng" if precip_sum >= 100 else ("Cục bộ" if precip_sum >= 30 else "Không")
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
        level = "Cao"
    elif weekday < 5 and (10 <= hour_local <= 15):
        level = "Trung bình"
    else:
        level = "Thấp"

    levels = ["Thấp", "Trung bình", "Cao"]
    bump = 0
    if weather == "Mưa":
        bump = 1
    elif weather == "Bão/Gió mạnh":
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
        "language": "vi",
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
                "name": route.get("summary") or f"Tuyến {idx + 1}",
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
        raise RuntimeError("Chưa có ORS_API_KEY")
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
        "source": "Ước lượng đường thẳng",
        "name": "Đường thẳng ước lượng",
        "distance_km": dist,
        "duration_min": (dist / 28) * 60,
        "normal_duration_min": (dist / 28) * 60,
        "path": [origin, destination],
        "start_address": "",
        "end_address": "",
    }

# -------------------- VEHICLE SCORING --------------------
def traffic_multiplier(traffic: str) -> float:
    return {"Thấp": 1.0, "Trung bình": 1.2, "Cao": 1.55}.get(traffic, 1.2)


def weather_multiplier(weather: str) -> float:
    return {"Tốt": 1.0, "Mưa": 1.18, "Bão/Gió mạnh": 1.7}.get(weather, 1.0)


def flood_multiplier(flood: str) -> float:
    return {"Không": 1.0, "Cục bộ": 1.15, "Nặng": 1.6}.get(flood, 1.0)


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

    distance = route["distance_km"]
    base_time = route["duration_min"]

    # --- TIME ---
    speed_adjust = 30 / vehicle.get("speed_kmh", vehicle.get("speed", 30))
    time_min = base_time * speed_adjust

    if vehicle["type"] == "motorbike" and traffic == "Cao":
        time_min *= 0.78
    if vehicle["type"] in ["van", "truck"] and traffic == "Cao":
        time_min *= 1.12
    if weather == "Mưa" and vehicle["type"] in ["motorbike", "drone"]:
        time_min *= 1.25
    if weather == "Bão/Gió mạnh" and vehicle["type"] in ["motorbike", "drone"]:
        time_min *= 1.8
    if flood == "Nặng" and vehicle["type"] in ["motorbike", "van"]:
        time_min *= 1.35

    # --- COST ---
    cost = vehicle["base_cost"] + distance * vehicle["cost_per_km"]

    if traffic == "Cao":
        cost *= 1.2
    if weather == "Bão/Gió mạnh":
        cost *= 1.3
    if flood == "Nặng":
        cost *= 1.25
    if vehicle["type"] == "drone" and distance > 5:
        cost *= 1.5
    if traffic == "Cao" and vehicle["type"] in ["van", "truck"]:
        cost *= 1.15
    if weather in ["Mưa", "Bão/Gió mạnh"] and vehicle["type"] == "motorbike":
        cost *= 1.1

    # --- EMISSION ---
    emissions = distance * vehicle.get("co2_factor", 0.2)

    # --- SCORE ---
    score = 100.0
    reasons = []
    warnings = []

    if weight_kg <= vehicle["max_weight"]:
        score += 18
        reasons.append("Đáp ứng tải trọng")
    else:
        score -= 120
        warnings.append("Vượt tải trọng")

    if cargo_type in vehicle["good_for"]:
        score += 20
        reasons.append("Phù hợp loại hàng")
    else:
        score -= 8

    if vehicle["type"] == "drone":
        if distance > drone_limit_km:
            score -= 100
            warnings.append("Vượt giới hạn km cho drone")
        if weather == "Bão/Gió mạnh":
            score -= 120
            warnings.append("Drone không an toàn")

    if traffic == "Cao":
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 24
        else:
            score -= 18

    if weather in ["Mưa", "Bão/Gió mạnh"]:
        if vehicle["type"] == "van":
            score += 18
        if vehicle["type"] == "motorbike":
            score -= 20

    if flood == "Nặng":
        if vehicle["type"] == "truck":
            score += 25
        if vehicle["type"] == "motorbike":
            score -= 28

    if urgency == "Rất gấp (≤2h)":
        if vehicle["type"] in ["drone", "motorbike"]:
            score += 26
        else:
            score -= 10

    # --- OPTIMIZATION ---
    if priority == "Tiết kiệm chi phí":
        score -= cost / 20000
        score -= time_min / 18
    elif priority == "Nhanh nhất":
        score -= time_min / 6
        score -= cost / 18000
    else:
        score -= cost / 12000
        score -= time_min / 10

    # --- BONUS ---
    if distance <= 3 and vehicle["type"] == "motorbike":
        score += 10

    if distance > 15 and vehicle["type"] in ["van", "truck"]:
        score += 8

    # --- RETURN ---
    return {
        "Phương tiện": vehicle.get("name", "Unknown"),
        "Điểm": round(max(0, score), 2),
        "Chi phí (VNĐ)": int(round(cost)),
        "Thời gian (phút)": int(round(max(1, time_min))),
        "Tải trọng tối đa (kg)": vehicle.get("max_weight", 0),
        "CO₂ ước tính (kg)": round(emissions, 2),
        "Lý do": "; ".join(reasons) if reasons else "Phù hợp ở mức trung bình",
        "Cảnh báo": "; ".join(warnings) if warnings else "Không có",
        "Ghi chú": vehicle.get("note", ""),
    }
