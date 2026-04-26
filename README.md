# Last-mile Delivery Vehicle Recommender

Ứng dụng Streamlit hỗ trợ lựa chọn phương tiện giao hàng chặng cuối tại đô thị, tập trung khu vực Hà Nội.

## Chức năng

- Nhập điểm lấy hàng và điểm giao hàng bằng địa chỉ, tọa độ hoặc địa điểm mẫu.
- Bản đồ Folium/OpenStreetMap.
- Hỗ trợ nhiều tuyến đường giống Google Maps nếu có Google Directions API key.
- Fallback sang OpenRouteService nếu có ORS API key.
- Nếu không có API key, vẫn chạy bằng đường thẳng ước lượng.
- Tự lấy thời tiết từ Open-Meteo.
- Suy luận giao thông theo giờ cao điểm và thời tiết.
- Chấm điểm xe tải, xe van, xe máy/xe điện và drone theo chi phí, thời gian, tải trọng, thời tiết, giao thông, độ gấp và loại hàng.

## Chạy local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud Secrets

Vào App > Settings > Secrets, thêm nếu muốn dùng tuyến thật:

```toml
GOOGLE_MAPS_API_KEY = "your_google_maps_key"
ORS_API_KEY = "your_openrouteservice_key"
```

Google key cần bật Directions API.
