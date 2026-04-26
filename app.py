# app.py — Last-mile Delivery Vehicle Recommendation for Hanoi, Vietnam
# Streamlit + Folium + Open-Meteo + optional OpenRouteService

import os
import math
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

# Optional geocoder
try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    _geolocator = Nominatim(user_agent="last-mile-delivery-hanoi", timeout=10)
    _geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)
except Exception:
    _geolocator, _geocode = None, None

# Optional OpenRouteService
try:
    import openrouteservice as ors
except Exception:
    ors = None

# -------------------- CONFIG --------------------
st.set_page_config(
    page_title="Last-mile Delivery Vehicle Recommender",
    layout="wide",
    page_icon="🚚"
)

# -------------------- VEHICLE DATA --------------------
VEHICLES = [
    {
        "name": "Xe tải",
        "type": "truck",
        "max_weight": 2000,
        "speed": 25,
        "base_cost": 120000,
        "cost_per_km": 12000,
        "co2_factor": 1.00,
        "good_for": ["hang_nang", "hang_cong_kenh", "hang_so_luong_lon"],
        "profiles": ["driving-hgv", "driving-car"],
        "description": "Phù hợp hàng nặng, hàng cồng kềnh, số lượng lớn. Chi phí cao và kém linh hoạt trong nội đô."
    },
    {
        "name": "Xe van",
        "type": "van",
        "max_weight": 800,
        "speed": 30,
        "base_cost": 80000,
        "cost_per_km": 9000,
        "co2_factor": 0.75,
        "good_for": ["thuc_pham", "hang_de_vo", "hang_trung_binh", "hang_gia_tri", "do_an"],
        "profiles": ["driving-car"],
        "description": "Cân bằng giữa tải trọng, an toàn hàng hóa và chi phí. Tốt khi mưa hoặc cần bảo vệ hàng."
    },
    {
        "name": "Xe máy / xe điện",
        "type": "motorbike",
        "max_weight": 30,
        "speed": 35,
        "base_cost": 25000,
        "cost_per_km": 5000,
        "co2_factor": 0.25,
        "good_for": ["tai_lieu", "hang_nhe", "do_an", "thuc_pham", "hang_y_te_nho"],
        "profiles": ["cycling-electric", "driving-car"],
        "description": "Rất phù hợp giao hàng nhẹ, nhanh trong nội đô Hà Nội, đặc biệt khi tắc đường."
    },
    {
        "name": "Drone",
        "type": "drone",
        "max_weight": 5,
        "speed": 45,
        "base_cost": 40000,
        "cost_per_km": 7000,
        "co2_factor": 0.10,
        "good_for": ["tai_lieu", "hang_y_te_nho", "hang_rat_gap"],
        "profiles": [],
        "description": "Phù hợp hàng rất nhẹ, rất gấp, khoảng cách ngắn, thời tiết tốt. Không phù hợp mưa lớn/gió mạnh."
    },
]

CARGO_LABELS = {
    "tai_lieu": "Tài liệu / hồ sơ",
    "do_an": "Đồ ăn / thực phẩm nóng",
    "thuc_pham": "Thực phẩm / hàng lạnh nhẹ",
    "hang_nhe": "Hàng nhẹ",
    "hang_trung_binh": "Hàng trung bình",
    "hang_nang": "Hàng nặng",
    "hang_cong_kenh": "Hàng cồng kềnh",
    "hang_de_vo": "Hàng dễ vỡ",
    "hang_gia_tri": "Hàng giá trị cao",
    "hang_y_te_nho": "Hàng y tế nhỏ",
    "hang_rat_gap": "Hàng rất gấp",
    "hang_so_luong_lon": "Hàng số lượng lớn",
}

# -------------------- HELPERS --------------------
def haversine_km(a, b):
    R = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def weather_from_code(code, wind):
    if code in [95, 96, 99] or wind >= 50:
        return "Storm"
    if 51 <= code <= 67 or 80 <= code <= 82 or 61 <= code <= 65:
        return "Rain"
    return "Clear"


def get_weather_and_flood(lat, lon):
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
    cw = js["current_weather"]
    code = int(cw["weathercode"])
    wind = float(cw["windspeed"])
    weather = weather_from_code(code, wind)
    precip = js.get("hourly", {}).get("precipitation", [])
    precip_sum = sum(p for p in precip if isinstance(p, (int, float)))
    flood = "Widespread" if precip_sum >= 100 else ("Local" if precip_sum >= 30 else "None")
    hour_local = int(cw["time"][11:13]) if "time" in cw else dt.datetime.now().hour
    tzname = js.get("timezone", "local")
    return weather, flood, hour_local, tzname, wind, precip_sum


def estimate_traffic_level(hour_local, weekday, weather):
    if weekday < 5 and (7 <= hour_local <= 9 or 17 <= hour_local <= 19):
        level = "High"
    elif weekday < 5:
        level = "Medium"
    else:
        level = "Low"
    bump = {"Clear": 0, "Rain": 1, "Storm": 2}.get(weather, 0)
    order = ["Low", "Medium", "High"]
    return order[min(2, order.index(level) + bump)]


def adjusted_speed(vehicle, traffic, weather, flood):
    speed = vehicle["speed"]
    if traffic == "Medium":
        speed *= 0.85
    elif traffic == "High":
        if vehicle["type"] == "motorbike":
            speed *= 0.85
        elif vehicle["type"] == "drone":
            speed *= 1.0
        else:
            speed *= 0.60

    if weather == "Rain":
        if vehicle["type"] == "drone":
            speed *= 0.70
        elif vehicle["type"] == "motorbike":
            speed *= 0.80
        else:
            speed *= 0.90
    elif weather == "Storm":
        if vehicle["type"] == "drone":
            speed *= 0.30
        elif vehicle["type"] == "motorbike":
            speed *= 0.55
        else:
            speed *= 0.75

    if flood == "Local":
        if vehicle["type"] == "motorbike":
            speed *= 0.75
        else:
            speed *= 0.85
    elif flood == "Widespread":
        if vehicle["type"] == "truck":
            speed *= 0.75
        elif vehicle["type"] == "drone":
            speed *= 0.95
        else:
            speed *= 0.45

    return max(speed, 5)


def ors_client():
    if ors is None:
        return None
    key = (getattr(st, "secrets", {}) or {}).get("ORS_API_KEY") or os.getenv("ORS_API_KEY")
    if not key:
        return None
    try:
        return ors.Client(key=key, base_url="https://api.openrouteservice.org", timeout=20)
    except Exception:
        return None


def get_ors_route(client, origin, destination, profile="driving-car"):
    coords = [(origin[1], origin[0]), (destination[1], destination[0])]
    res = client.directions(coordinates=coords, profile=profile, format="geojson")
    line = res["features"][0]["geometry"]["coordinates"]
    path_latlon = [(pt[1], pt[0]) for pt in line]
    summary = res["features"][0]["properties"]["summary"]
    return path_latlon, summary["distance"] / 1000.0, summary["duration"] / 60.0


def vehicle_score(vehicle, cargo_type, weight, urgency, traffic, weather, flood, dist_km, drone_limit_km):
    score = 100.0
    reasons = []
    warnings = []

    # Capacity
    if weight > vehicle["max_weight"]:
        overweight_ratio = weight / vehicle["max_weight"]
        score -= 120 + min(80, overweight_ratio * 10)
        warnings.append("Vượt tải trọng cho phép")
    else:
        score += 20
        reasons.append("Đáp ứng tải trọng")

    # Cargo compatibility
    if cargo_type in vehicle["good_for"]:
        score += 25
        reasons.append("Phù hợp loại hàng")
    else:
        score -= 12

    # Distance and urban rule
    if dist_km <= 3:
        if vehicle["type"] == "motorbike":
            score += 18
            reasons.append("Tối ưu cho quãng đường ngắn trong nội đô")
        if vehicle["type"] in ["truck", "van"]:
            score -= 8
    elif dist_km >= 15:
        if vehicle["type"] in ["van", "truck"]:
            score += 12
            reasons.append("Ổn định hơn cho quãng đường dài")
        if vehicle["type"] == "drone":
            score -= 25

    # Traffic
    if traffic == "High":
        if vehicle["type"] == "motorbike":
            score += 30
            reasons.append("Linh hoạt khi tắc đường")
        elif vehicle["type"] == "drone":
            score += 25
            reasons.append("Ít bị ảnh hưởng bởi giao thông")
        elif vehicle["type"] == "truck":
            score -= 30
            warnings.append("Kém linh hoạt khi tắc đường")
        else:
            score -= 18
    elif traffic == "Low":
        if vehicle["type"] in ["van", "truck"]:
            score += 5

    # Weather
    if weather == "Rain":
        if vehicle["type"] == "van":
            score += 15
            reasons.append("Bảo vệ hàng tốt khi mưa")
        elif vehicle["type"] == "motorbike":
            score -= 12
            warnings.append("Mưa làm giảm an toàn giao hàng bằng xe máy")
        elif vehicle["type"] == "drone":
            score -= 25
            warnings.append("Mưa làm hạn chế drone")
    elif weather == "Storm":
        if vehicle["type"] == "drone":
            score -= 120
            warnings.append("Không khuyến nghị drone khi giông/bão/gió mạnh")
        elif vehicle["type"] == "motorbike":
            score -= 45
            warnings.append("Xe máy rủi ro cao khi thời tiết xấu")
        elif vehicle["type"] in ["van", "truck"]:
            score += 8

    # Flood
    if flood == "Local":
        if vehicle["type"] in ["van", "truck"]:
            score += 8
        if vehicle["type"] == "motorbike":
            score -= 18
    elif flood == "Widespread":
        if vehicle["type"] == "truck":
            score += 25
            reasons.append("Gầm cao hơn, phù hợp khi ngập")
        elif vehicle["type"] == "drone":
            score += 10
        else:
            score -= 35
            warnings.append("Không tối ưu khi ngập diện rộng")

    # Urgency
    if urgency == "Critical (≤2h)":
        if vehicle["type"] == "drone":
            score += 40
            reasons.append("Tốc độ cao cho đơn rất gấp")
        elif vehicle["type"] == "motorbike":
            score += 35
            reasons.append("Phù hợp đơn gấp trong đô thị")
        elif vehicle["type"] == "truck":
            score -= 25
    elif urgency == "High":
        if vehicle["type"] in ["motorbike", "drone"]:
            score += 20
        elif vehicle["type"] == "truck":
            score -= 10
    elif urgency == "Low":
        if vehicle["type"] in ["van", "truck"]:
            score += 5

    # Drone hard constraints
    if vehicle["type"] == "drone":
        if dist_km > drone_limit_km:
            score -= 100
            warnings.append("Vượt giới hạn km cho drone")
        if weight > 5:
            score -= 100
            warnings.append("Drone chỉ phù hợp hàng rất nhẹ")
        if weather == "Storm":
            score -= 100
        if flood == "Widespread" and weather != "Clear":
            score -= 30

    # Cost and time
    cost = vehicle["base_cost"] + vehicle["cost_per_km"] * dist_km
    speed = adjusted_speed(vehicle, traffic, weather, flood)
    time_min = (dist_km / speed) * 60
    co2_score = vehicle["co2_factor"] * dist_km

    # Optimization penalties
    score -= cost / 12000
    score -= time_min / 8
    score -= co2_score * 1.5

    if cost == min([v["base_cost"] + v["cost_per_km"] * dist_km for v in VEHICLES]):
        score += 10
        reasons.append("Chi phí thấp")

    return {
        "Phương tiện": vehicle["name"],
        "Điểm": round(max(score, 0), 2),
        "Chi phí ước tính (VNĐ)": int(round(cost, 0)),
        "Thời gian ước tính (phút)": int(round(time_min, 0)),
        "Tốc độ hiệu dụng (km/h)": round(speed, 1),
        "Tải trọng tối đa (kg)": vehicle["max_weight"],
        "Mức phát thải tương đối": round(co2_score, 2),
        "Lý do": "; ".join(reasons) if reasons else "Phù hợp ở mức trung bình",
        "Cảnh báo": "; ".join(warnings) if warnings else "Không có",
        "Mô tả": vehicle["description"],
        "type": vehicle["type"],
    }


def rank_vehicles(cargo_type, weight, urgency, traffic, weather, flood, dist_km, drone_limit_km):
    results = [
        vehicle_score(v, cargo_type, weight, urgency, traffic, weather, flood, dist_km, drone_limit_km)
        for v in VEHICLES
    ]
    return sorted(results, key=lambda x: x["Điểm"], reverse=True)


def status_badge(value):
    color = {
        "Low": "green",
        "Medium": "orange",
        "High": "red",
        "Clear": "green",
        "Rain": "orange",
        "Storm": "red",
        "None": "green",
        "Local": "orange",
        "Widespread": "red",
    }.get(value, "blue")
    return f":{color}[{value}]"

# -------------------- UI --------------------
st.title("🚚 Hệ thống lựa chọn phương tiện giao hàng chặng cuối")
st.caption("Áp dụng cho đô thị Việt Nam, tập trung khu vực Hà Nội. Tối ưu theo chi phí, thời gian, tải trọng, thời tiết, giao thông và loại hàng.")

with st.sidebar:
    st.header("⚙️ Cấu hình")
    use_auto_status = st.checkbox("Tự động lấy thời tiết & suy luận giao thông", value=True)
    use_ors = st.checkbox("Dùng tuyến đường thật OpenRouteService nếu có API key", value=True)
    drone_limit = st.number_input("Giới hạn km cho drone", min_value=1, max_value=30, value=10)
    st.info("Để vẽ tuyến đường thật, tạo biến môi trường hoặc Streamlit Secret: ORS_API_KEY.")

# -------------------- LOCATION INPUT --------------------
st.markdown("## 1. Nhập điểm lấy hàng và điểm giao hàng")
mode = st.radio(
    "Chọn cách nhập điểm:",
    ["Nhập địa chỉ", "Nhập tọa độ (lat, lon)", "Chọn địa chỉ mẫu Hà Nội"],
    horizontal=True,
)

origin = destination = None
origin_label = "Điểm lấy hàng"
destination_label = "Điểm giao hàng"

if "geo" not in st.session_state:
    st.session_state.geo = {"origin": None, "destination": None}

if mode == "Nhập địa chỉ":
    col1, col2 = st.columns(2)
    with col1:
        start_addr = st.text_input("Điểm lấy hàng", value="Hồ Hoàn Kiếm, Hà Nội")
    with col2:
        dest_addr = st.text_input("Điểm giao hàng", value="Bến xe Mỹ Đình, Hà Nội")

    if _geolocator is None:
        st.warning("Không nạp được geopy. Hãy dùng nhập tọa độ hoặc địa chỉ mẫu.")
    else:
        if st.button("📍 Lấy tọa độ từ địa chỉ"):
            with st.spinner("Đang tìm tọa độ..."):
                loc1 = _geocode(start_addr) if start_addr else None
                loc2 = _geocode(dest_addr) if dest_addr else None
            if loc1 and loc2:
                st.session_state.geo["origin"] = (loc1.latitude, loc1.longitude)
                st.session_state.geo["destination"] = (loc2.latitude, loc2.longitude)
                origin_label = start_addr
                destination_label = dest_addr
                st.success("Đã xác định tọa độ thành công.")
            else:
                st.error("Không tìm thấy tọa độ. Hãy nhập rõ số nhà, phường/quận, Hà Nội.")

    origin = st.session_state.geo["origin"]
    destination = st.session_state.geo["destination"]

elif mode == "Nhập tọa độ (lat, lon)":
    col1, col2 = st.columns(2)
    with col1:
        o_lat = st.number_input("Lấy hàng - latitude", value=21.028511, format="%.6f")
        o_lon = st.number_input("Lấy hàng - longitude", value=105.852005, format="%.6f")
    with col2:
        d_lat = st.number_input("Giao hàng - latitude", value=21.028762, format="%.6f")
        d_lon = st.number_input("Giao hàng - longitude", value=105.776900, format="%.6f")
    origin = (o_lat, o_lon)
    destination = (d_lat, d_lon)

else:
    presets = {
        "Hồ Hoàn Kiếm": (21.028511, 105.852005),
        "Hanoi Tower": (21.026754, 105.846083),
        "Bến xe Mỹ Đình": (21.028762, 105.776900),
        "Sân bay Nội Bài": (21.214184, 105.802827),
        "Royal City": (21.002654, 105.815487),
        "Times City": (20.995203, 105.868056),
        "Đại học Bách Khoa Hà Nội": (21.005596, 105.843180),
        "Cầu Giấy": (21.036237, 105.790583),
    }
    col1, col2 = st.columns(2)
    with col1:
        origin_name = st.selectbox("Điểm lấy hàng", list(presets.keys()), index=0)
    with col2:
        dest_name = st.selectbox("Điểm giao hàng", list(presets.keys()), index=2)
    origin = presets[origin_name]
    destination = presets[dest_name]
    origin_label = origin_name
    destination_label = dest_name

# -------------------- ORDER INPUT --------------------
st.markdown("## 2. Thông tin hàng hóa")
col1, col2, col3 = st.columns(3)
with col1:
    cargo_type = st.selectbox("Loại hàng hóa", list(CARGO_LABELS.keys()), format_func=lambda x: CARGO_LABELS[x])
with col2:
    weight = st.number_input("Khối lượng hàng hóa (kg)", min_value=0.1, max_value=2000.0, value=3.0, step=0.5)
with col3:
    urgency = st.selectbox("Mức độ cấp bách", ["Low", "Normal", "High", "Critical (≤2h)"], index=1)

manual_status = None
if not use_auto_status:
    st.markdown("## 3. Nhập điều kiện tuyến đường thủ công")
    c1, c2, c3 = st.columns(3)
    with c1:
        manual_traffic = st.selectbox("Giao thông", ["Low", "Medium", "High"], index=1)
    with c2:
        manual_weather = st.selectbox("Thời tiết", ["Clear", "Rain", "Storm"], index=0)
    with c3:
        manual_flood = st.selectbox("Ngập úng", ["None", "Local", "Widespread"], index=0)
    manual_status = {
        "traffic": manual_traffic,
        "weather": manual_weather,
        "flood": manual_flood,
        "hour": dt.datetime.now().hour,
        "tz": "manual",
        "wind": None,
        "precip": None,
    }

# -------------------- CALCULATION --------------------
if "calc" not in st.session_state:
    st.session_state.calc = None

pressed = st.button("🚀 Tính toán & đề xuất phương tiện", type="primary")

if pressed:
    if not origin or not destination:
        st.error("Vui lòng nhập hoặc chọn đầy đủ điểm lấy hàng và điểm giao hàng.")
    else:
        dist_km = haversine_km(origin, destination)
        status = manual_status

        if use_auto_status:
            try:
                weather_now, flood_now, hour_local, tzname, wind, precip_sum = get_weather_and_flood(*origin)
                weekday = dt.datetime.now().weekday()
                traffic_now = estimate_traffic_level(hour_local, weekday, weather_now)
                status = {
                    "traffic": traffic_now,
                    "weather": weather_now,
                    "flood": flood_now,
                    "hour": hour_local,
                    "tz": tzname,
                    "wind": wind,
                    "precip": precip_sum,
                }
            except Exception as e:
                st.warning(f"Không lấy được trạng thái tự động. Dùng giá trị mặc định. Lý do: {e}")
                status = {
                    "traffic": "Medium",
                    "weather": "Clear",
                    "flood": "None",
                    "hour": dt.datetime.now().hour,
                    "tz": "fallback",
                    "wind": None,
                    "precip": None,
                }

        results = rank_vehicles(
            cargo_type=cargo_type,
            weight=weight,
            urgency=urgency,
            traffic=status["traffic"],
            weather=status["weather"],
            flood=status["flood"],
            dist_km=dist_km,
            drone_limit_km=drone_limit,
        )

        st.session_state.calc = {
            "origin": origin,
            "destination": destination,
            "origin_label": origin_label,
            "destination_label": destination_label,
            "dist_km": dist_km,
            "cargo_type": cargo_type,
            "weight": weight,
            "urgency": urgency,
            "status": status,
            "results": results,
        }

# -------------------- DISPLAY --------------------
if st.session_state.calc:
    c = st.session_state.calc
    best = c["results"][0]

    st.markdown("## 3. Kết quả đề xuất")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Phương tiện tối ưu", best["Phương tiện"])
    m2.metric("Chi phí", f"{best['Chi phí ước tính (VNĐ)']:,} VNĐ")
    m3.metric("Thời gian", f"{best['Thời gian ước tính (phút)']} phút")
    m4.metric("Điểm phù hợp", best["Điểm"])

    s = c["status"]
    st.markdown(
        f"**Trạng thái tuyến:** Traffic {status_badge(s['traffic'])} • "
        f"Weather {status_badge(s['weather'])} • Flood {status_badge(s['flood'])} • "
        f"Giờ địa phương: `{s['hour']}:00` • TZ: `{s['tz']}`"
    )
    if s.get("wind") is not None:
        st.caption(f"Gió: {s['wind']} km/h • Mưa 24h ước tính: {s['precip']:.1f} mm")

    st.success(f"✅ Đề xuất: **{best['Phương tiện']}** — {best['Lý do']}")
    if best["Cảnh báo"] != "Không có":
        st.warning(best["Cảnh báo"])

    st.markdown("### 📊 Bảng so sánh phương tiện")
    df = pd.DataFrame(c["results"])
    display_cols = [
        "Phương tiện",
        "Điểm",
        "Chi phí ước tính (VNĐ)",
        "Thời gian ước tính (phút)",
        "Tốc độ hiệu dụng (km/h)",
        "Tải trọng tối đa (kg)",
        "Mức phát thải tương đối",
        "Lý do",
        "Cảnh báo",
    ]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    with st.expander("Giải thích chi tiết từng phương tiện"):
        for item in c["results"]:
            st.markdown(f"#### {item['Phương tiện']}")
            st.write(item["Mô tả"])
            st.write(f"**Lý do:** {item['Lý do']}")
            st.write(f"**Cảnh báo:** {item['Cảnh báo']}")

    st.markdown("## 4. Bản đồ tuyến đường")
    profile_label = st.selectbox(
        "Hồ sơ tuyến ORS",
        ["Van/Car (driving-car)", "Motorbike approx (cycling-electric)", "Truck (driving-hgv)"],
        index=0,
    )
    profile_map = {
        "Van/Car (driving-car)": "driving-car",
        "Motorbike approx (cycling-electric)": "cycling-electric",
        "Truck (driving-hgv)": "driving-hgv",
    }
    profile = profile_map[profile_label]

    mid = ((c["origin"][0] + c["destination"][0]) / 2, (c["origin"][1] + c["destination"][1]) / 2)
    fmap = folium.Map(location=mid, zoom_start=12, tiles="OpenStreetMap")
    folium.Marker(c["origin"], tooltip="Điểm lấy hàng", popup=c["origin_label"], icon=folium.Icon(color="green", icon="play")).add_to(fmap)
    folium.Marker(c["destination"], tooltip="Điểm giao hàng", popup=c["destination_label"], icon=folium.Icon(color="red", icon="flag")).add_to(fmap)

    drawn_straight = True
    if use_ors:
        client = ors_client()
        if client:
            try:
                path, dist_real_km, time_real_min = get_ors_route(client, c["origin"], c["destination"], profile=profile)
                folium.PolyLine(path, weight=5, tooltip=f"ORS {profile}", color="blue").add_to(fmap)
                st.info(f"Tuyến ORS: khoảng {dist_real_km:.1f} km • {int(time_real_min)} phút theo hồ sơ `{profile}`")
                drawn_straight = False
            except Exception as e:
                st.warning(f"Không lấy được tuyến ORS, đang vẽ đường thẳng. Lý do: {e}")
        else:
            st.warning("Chưa có ORS_API_KEY hoặc thư viện ORS không khả dụng. Đang vẽ đường thẳng.")

    if drawn_straight:
        folium.PolyLine([c["origin"], c["destination"]], weight=5, tooltip="Đường thẳng ước lượng", color="blue").add_to(fmap)
        st.info(f"Khoảng cách đường thẳng ước lượng: {c['dist_km']:.1f} km")

    status_text = f"Traffic: {s['traffic']} | Weather: {s['weather']} | Flood: {s['flood']}"
    folium.Marker(mid, tooltip=status_text, popup=status_text, icon=folium.Icon(color="blue", icon="info-sign")).add_to(fmap)
    st_folium(fmap, width=1100, height=560)

st.caption("Nguồn dữ liệu tự động: Open-Meteo cho thời tiết; ngập úng được suy luận đơn giản từ lượng mưa 24h; giao thông được suy luận từ giờ cao điểm + thời tiết. ORS chỉ hoạt động khi có ORS_API_KEY.")
