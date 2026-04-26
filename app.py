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
    """Chấm điểm một phương tiện cho một tuyến giao hàng.

    Hàm này đã được clean lại để:
    - không lỗi indent / return outside function
    - dùng đúng biến distance thay cho dist_km
    - dùng đúng nhãn tiếng Việt: Cao, Mưa, Bão/Gió mạnh, Nặng
    - xử lý an toàn khi một phương tiện thiếu speed_kmh hoặc co2_factor
    """
    distance = float(route.get("distance_km", 0) or 0)
    base_time = float(route.get("duration_min", 0) or 0)

    vehicle_speed = float(vehicle.get("speed_kmh", vehicle.get("speed", 30)) or 30)

    # -------------------- TIME --------------------
    # Route time thường là profile driving-car. Điều chỉnh theo tốc độ từng phương tiện.
    speed_adjust = 30 / vehicle_speed
    time_min = max(1.0, base_time * speed_adjust)

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

    # -------------------- COST --------------------
    cost = vehicle["base_cost"] + distance * vehicle["cost_per_km"]

    # Tăng giá theo điều kiện thực tế đô thị.
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

    # -------------------- EMISSION --------------------
    emissions = distance * float(vehicle.get("co2_factor", 0.12))

    # -------------------- SCORE --------------------
    score = 100.0
    reasons = []
    warnings = []

    # Tải trọng
    if weight_kg <= vehicle["max_weight"]:
        score += 18
        reasons.append("Đáp ứng tải trọng")
    else:
        score -= 120
        warnings.append("Vượt tải trọng")

    # Loại hàng
    if cargo_type in vehicle["good_for"]:
        score += 20
        reasons.append("Phù hợp loại hàng")
    else:
        score -= 8

    # Drone constraints
    if vehicle["type"] == "drone":
        if distance > drone_limit_km:
            score -= 100
            warnings.append("Vượt giới hạn km cho drone")
        if weight_kg > vehicle["max_weight"]:
            score -= 80
        if weather == "Bão/Gió mạnh":
            score -= 120
            warnings.append("Drone không an toàn khi gió mạnh/bão")
        if flood == "Nặng":
            score -= 20

    # Giao thông
    if traffic == "Cao":
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 24
            reasons.append("Linh hoạt khi tắc đường")
        else:
            score -= 18

    # Thời tiết
    if weather in ["Mưa", "Bão/Gió mạnh"]:
        if vehicle["type"] == "van":
            score += 18
            reasons.append("Bảo vệ hàng tốt khi thời tiết xấu")
        if vehicle["type"] == "truck":
            score += 10
        if vehicle["type"] == "motorbike":
            score -= 20
            warnings.append("Xe máy kém ổn định khi mưa/gió")

    # Ngập
    if flood == "Nặng":
        if vehicle["type"] == "truck":
            score += 25
            reasons.append("Gầm cao, phù hợp ngập nặng")
        if vehicle["type"] == "motorbike":
            score -= 28

    # Cấp bách
    if urgency == "Rất gấp (≤2h)":
        if vehicle["type"] in ["drone", "motorbike"]:
            score += 26
            reasons.append("Phù hợp đơn gấp")
        else:
            score -= 10
    elif urgency == "Gấp":
        if vehicle["type"] in ["motorbike", "van"]:
            score += 12

    # Mục tiêu tối ưu
    if priority == "Tiết kiệm chi phí":
        score -= cost / 20000
        score -= time_min / 18
        score -= emissions * 1.5
    elif priority == "Nhanh nhất":
        score -= time_min / 6
        score -= cost / 18000
    elif priority == "Cân bằng":
        score -= cost / 12000
        score -= time_min / 10
        score -= emissions
    else:  # Thân thiện môi trường
        score -= emissions * 6
        score -= cost / 15000
        score -= time_min / 12
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 12

    # Bonus theo khoảng cách
    if distance <= 3 and vehicle["type"] == "motorbike":
        score += 10
    if distance > 15 and vehicle["type"] in ["van", "truck"]:
        score += 8

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


def evaluate_all_vehicles(*args, **kwargs) -> List[Dict]:
    results = [evaluate_vehicle(v, *args, **kwargs) for v in VEHICLES]
    return sorted(results, key=lambda x: x["Điểm"], reverse=True)

# -------------------- UI HEADER --------------------
st.markdown('<div class="main-title">🚚 Last-mile Delivery Vehicle Recommender</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Chọn tuyến đường giống Google Maps và đề xuất phương tiện giao hàng tối ưu cho đô thị Hà Nội.</div>',
    unsafe_allow_html=True,
)

# -------------------- SIDEBAR INPUTS --------------------
with st.sidebar:
    st.header("⚙️ Cấu hình")
    auto_status = st.checkbox("Tự động lấy thời tiết & suy luận giao thông", value=True)
    use_real_route = st.checkbox("Dùng tuyến đường thật nếu có API key", value=True)
    drone_limit = st.number_input("Giới hạn km cho drone", min_value=1, max_value=50, value=10)
    priority = st.selectbox(
        "Mục tiêu tối ưu",
        ["Cân bằng", "Tiết kiệm chi phí", "Nhanh nhất", "Thân thiện môi trường"],
        index=0,
    )
    st.info("Muốn có nhiều tuyến như Google Maps: thêm GOOGLE_MAPS_API_KEY trong Streamlit Secrets.")

# -------------------- INPUT LOCATIONS --------------------
st.markdown("## 1. Điểm lấy hàng và điểm giao hàng")
mode = st.radio(
    "Chọn cách nhập điểm",
    ["Địa điểm mẫu Hà Nội", "Nhập tọa độ", "Nhập địa chỉ"],
    horizontal=True,
)

origin = None
destination = None

if mode == "Địa điểm mẫu Hà Nội":
    col1, col2 = st.columns(2)
    with col1:
        origin_name = st.selectbox("Điểm lấy hàng", list(PRESETS.keys()), index=1)
    with col2:
        dest_name = st.selectbox("Điểm giao hàng", list(PRESETS.keys()), index=2)
    origin = PRESETS[origin_name]
    destination = PRESETS[dest_name]

elif mode == "Nhập tọa độ":
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Điểm lấy hàng")
        o_lat = st.number_input("Latitude lấy hàng", value=21.026754, format="%.6f")
        o_lon = st.number_input("Longitude lấy hàng", value=105.846083, format="%.6f")
    with col2:
        st.caption("Điểm giao hàng")
        d_lat = st.number_input("Latitude giao hàng", value=21.028762, format="%.6f")
        d_lon = st.number_input("Longitude giao hàng", value=105.776900, format="%.6f")
    origin = (o_lat, o_lon)
    destination = (d_lat, d_lon)

else:
    if "geo" not in st.session_state:
        st.session_state.geo = {"origin": None, "destination": None}
    col1, col2 = st.columns(2)
    with col1:
        start_addr = st.text_input("Địa chỉ lấy hàng", "Hanoi Tower, Hà Nội")
    with col2:
        dest_addr = st.text_input("Địa chỉ giao hàng", "Bến xe Mỹ Đình, Hà Nội")
    if st.button("📍 Lấy tọa độ từ địa chỉ"):
        if not _geocode:
            st.error("Geocoder chưa khả dụng. Hãy dùng tọa độ hoặc địa điểm mẫu.")
        else:
            with st.spinner("Đang tìm tọa độ..."):
                loc1 = geocode_address(start_addr)
                loc2 = geocode_address(dest_addr)
            if loc1 and loc2:
                st.session_state.geo = {"origin": loc1, "destination": loc2}
                st.success("Đã lấy tọa độ thành công.")
            else:
                st.error("Không tìm thấy địa chỉ. Hãy nhập cụ thể hơn.")
    origin = st.session_state.geo["origin"]
    destination = st.session_state.geo["destination"]

# -------------------- ORDER INPUTS --------------------
st.markdown("## 2. Thông tin đơn hàng")
col1, col2, col3, col4 = st.columns(4)
with col1:
    cargo_type = st.selectbox("Loại hàng", list(CARGO_WEIGHT_HINT.keys()), index=0)
with col2:
    default_weight = CARGO_WEIGHT_HINT[cargo_type]
    weight_kg = st.number_input("Khối lượng hàng (kg)", min_value=0.1, max_value=2500.0, value=float(default_weight), step=0.5)
with col3:
    urgency = st.selectbox("Mức độ cấp bách", ["Thấp", "Bình thường", "Gấp", "Rất gấp (≤2h)"], index=1)
with col4:
    manual_distance_note = st.empty()

# -------------------- STATUS --------------------
st.markdown("## 3. Điều kiện tuyến đường")
status_source = "Thủ công"
weather = "Tốt"
flood = "Không"
traffic = "Trung bình"
weather_details = {}

if origin and destination and auto_status:
    try:
        weather_details = get_weather_and_flood(*origin)
        weather = weather_details["weather"]
        flood = weather_details["flood"]
        traffic = estimate_traffic_level(weather_details["hour"], weather)
        status_source = "Tự động"
    except Exception as exc:
        st.warning(f"Không lấy được thời tiết tự động: {exc}. Chuyển sang nhập thủ công.")

if not auto_status or status_source == "Thủ công":
    col1, col2, col3 = st.columns(3)
    with col1:
        traffic = st.selectbox("Giao thông", ["Thấp", "Trung bình", "Cao"], index=1)
    with col2:
        weather = st.selectbox("Thời tiết", ["Tốt", "Mưa", "Bão/Gió mạnh"], index=0)
    with col3:
        flood = st.selectbox("Ngập", ["Không", "Cục bộ", "Nặng"], index=0)
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Giao thông", traffic)
    c2.metric("Thời tiết", weather)
    c3.metric("Ngập", flood)
    c4.metric("Mưa 24h", f"{weather_details.get('rain_24h_mm', 0)} mm")

# -------------------- CALCULATION --------------------
if "routes" not in st.session_state:
    st.session_state.routes = []
if "route_message" not in st.session_state:
    st.session_state.route_message = ""

calc = st.button("🚀 Tính tuyến & đề xuất phương tiện", type="primary")

if calc:
    if not origin or not destination:
        st.error("Vui lòng nhập đủ điểm lấy hàng và điểm giao hàng.")
        st.stop()

    routes = []
    messages = []

    if use_real_route:
        google_key = get_secret("GOOGLE_MAPS_API_KEY")
        if google_key:
            try:
                routes = get_google_routes(origin, destination, google_key)
                messages.append(f"Đã lấy {len(routes)} tuyến từ Google Directions.")
            except Exception as exc:
                messages.append(f"Google Directions lỗi: {exc}")
        else:
            messages.append("Chưa có GOOGLE_MAPS_API_KEY nên chưa lấy được nhiều tuyến Google Maps.")

        if not routes:
            for profile in ["driving-car", "cycling-electric", "driving-hgv"]:
                try:
                    routes.append(get_ors_route(origin, destination, profile))
                except Exception as exc:
                    messages.append(f"ORS {profile}: {exc}")
            if routes:
                messages.append("Đã dùng OpenRouteService fallback.")

    if not routes:
        routes = [fallback_straight_route(origin, destination)]
        messages.append("Đang dùng đường thẳng ước lượng vì chưa có API key hợp lệ.")

    st.session_state.routes = routes
    st.session_state.route_message = " | ".join(messages)

routes = st.session_state.routes

if routes:
    st.markdown("## 4. Chọn tuyến đường")
    if st.session_state.route_message:
        if "đường thẳng" in st.session_state.route_message.lower() or "chưa" in st.session_state.route_message.lower():
            st.warning(st.session_state.route_message)
        else:
            st.success(st.session_state.route_message)

    route_labels = [
        f"Tuyến {i + 1}: {r['name']} — {r['distance_km']:.1f} km — {int(r['duration_min'])} phút — {r['source']}"
        for i, r in enumerate(routes)
    ]
    selected_idx = st.selectbox("Chọn tuyến giống Google Maps", range(len(routes)), format_func=lambda i: route_labels[i])
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

    st.markdown("## 5. Kết quả đề xuất")
    st.markdown(
        f"""
        <div class="best-box">
            <h3>✅ Phương tiện tối ưu: {best['Phương tiện']}</h3>
            <p><b>Điểm:</b> {best['Điểm']} &nbsp; | &nbsp; <b>Chi phí:</b> {best['Chi phí (VNĐ)']:,} VNĐ &nbsp; | &nbsp; <b>Thời gian:</b> {best['Thời gian (phút)']} phút</p>
            <p><b>Lý do:</b> {best['Lý do']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tuyến đã chọn", f"{selected_route['distance_km']:.1f} km")
    m2.metric("Thời gian tuyến", f"{int(selected_route['duration_min'])} phút")
    m3.metric("Nguồn tuyến", selected_route["source"])
    m4.metric("Mục tiêu", priority)

    df = pd.DataFrame(results)
    st.dataframe(
        df[["Phương tiện", "Điểm", "Chi phí (VNĐ)", "Thời gian (phút)", "Tải trọng tối đa (kg)", "CO₂ ước tính (kg)", "Lý do", "Cảnh báo"]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Giải thích chi tiết từng phương tiện"):
        for item in results:
            st.markdown(
                f"""
                <div class="route-box">
                <b>{item['Phương tiện']}</b><br>
                Điểm: {item['Điểm']} | Chi phí: {item['Chi phí (VNĐ)']:,} VNĐ | Thời gian: {item['Thời gian (phút)']} phút<br>
                Lý do: {item['Lý do']}<br>
                Cảnh báo: {item['Cảnh báo']}<br>
                Ghi chú: {item['Ghi chú']}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # -------------------- MAP --------------------
    st.markdown("## 6. Bản đồ tuyến đường")
    center = ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2)
    fmap = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")

    folium.Marker(origin, tooltip="Điểm lấy hàng", popup="Điểm lấy hàng", icon=folium.Icon(color="green", icon="play")).add_to(fmap)
    folium.Marker(destination, tooltip="Điểm giao hàng", popup="Điểm giao hàng", icon=folium.Icon(color="red", icon="flag")).add_to(fmap)

    route_colors = ["blue", "gray", "green", "purple", "orange"]
    for i, route in enumerate(routes):
        color = route_colors[i % len(route_colors)]
        is_selected = i == selected_idx
        tooltip = f"Tuyến {i + 1}: {route['distance_km']:.1f} km, {int(route['duration_min'])} phút"
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
                    {'✅ ' if is_selected else ''}Tuyến {i+1}: {route['distance_km']:.1f} km
                    </div>
                    """
                ),
            ).add_to(fmap)

    st_folium(fmap, width=None, height=560)

else:
    st.info("Nhập thông tin rồi bấm **Tính tuyến & đề xuất phương tiện** để bắt đầu.")

st.caption(
    "Ghi chú: Google Directions API cho nhiều tuyến giống Google Maps nếu có GOOGLE_MAPS_API_KEY. Nếu không có, app tự fallback sang OpenRouteService hoặc đường thẳng ước lượng."
)
