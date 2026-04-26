# Last-mile Delivery Vehicle Recommender

Ứng dụng Streamlit hỗ trợ lựa chọn phương tiện giao hàng chặng cuối tại đô thị, tập trung khu vực Hà Nội.

## Chức năng

- Nhập điểm lấy hàng và điểm giao hàng bằng địa chỉ, tọa độ hoặc địa chỉ mẫu Hà Nội.
- Hiển thị bản đồ bằng Folium/OpenStreetMap.
- Tự động lấy thời tiết bằng Open-Meteo.
- Suy luận tình trạng giao thông theo giờ cao điểm và thời tiết.
- Suy luận ngập úng dựa trên lượng mưa 24h.
- Chấm điểm và so sánh các phương tiện:
  - Xe tải
  - Xe van
  - Xe máy / xe điện
  - Drone
- Tối ưu theo:
  - Chi phí
  - Thời gian
  - Tải trọng
  - Loại hàng hóa
  - Mức độ cấp bách
  - Giao thông
  - Thời tiết
  - Ngập úng

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy ứng dụng

```bash
streamlit run app.py
```

## OpenRouteService API Key

Ứng dụng vẫn chạy nếu không có ORS_API_KEY, nhưng chỉ vẽ đường thẳng ước lượng.

Để dùng tuyến đường thật:

### Cách 1: biến môi trường

```bash
export ORS_API_KEY="your_api_key"
streamlit run app.py
```

### Cách 2: Streamlit secrets

Tạo file:

```text
.streamlit/secrets.toml
```

Nội dung:

```toml
ORS_API_KEY = "your_api_key"
```
