# Kịch Bản Demo: Tấn Công EDoS và Phòng Thủ Randomized HPA

## Tổng quan

**Thời lượng:** ~25-30 phút
**Mục tiêu:** Trình diễn trực quan cuộc tấn công EDoS lên Kubernetes autoscaling và cơ chế phòng thủ bằng randomized custom metrics.

**Cửa sổ cần mở sẵn trước khi demo:**

| Cửa sổ | Nội dung | Mục đích |
|--------|----------|----------|
| Browser tab 1 | Grafana http://localhost:3000 | Theo dõi replicas + CPU |
| Browser tab 2 | http://localhost:8080/ | Chứng minh app đang chạy |
| Terminal 1 | HPA watcher | Hiển thị HPA real-time |
| Terminal 2 | Legitimate traffic | jMeter |
| Terminal 3 | Attacker | Python script |
| Terminal 4 | Adapter logs (phần 2) | Xem quyết định REAL/FAKE |

---

## CHUẨN BỊ TRƯỚC KHI DEMO (15 phút trước)

### Reset hệ thống về trạng thái sạch

```powershell
# Dam bao dang dung Standard HPA (khong phai Randomized)
kubectl delete hpa --all -n teastore
kubectl apply -f hpa-lite.yaml

# Scale ve 1 replica
kubectl scale deployment webapp -n teastore --replicas=1

# Kiem tra moi thu ok
kubectl get pods -n teastore
kubectl get hpa -n teastore

# Mo app trong browser de chac chan hoat dong
# http://localhost:8080/
```

### Cấu hình Grafana

Mở http://localhost:3000, vào dashboard **EDoS Attack Monitor**:
- Time range: **Last 15 minutes**
- Auto refresh: **5s**
- Đảm bảo có ít nhất 2 panels: **Replicas** và **CPU %**

### Setup Terminal 1: HPA Watcher

```powershell
while ($true) {
    Clear-Host
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  HPA STATUS - $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    kubectl get hpa -n teastore
    Write-Host ""
    Write-Host "  PODS:" -ForegroundColor Cyan
    kubectl get pods -n teastore -l app=webapp -o custom-columns="NAME:.metadata.name,STATUS:.status.phase,CPU:.spec.containers[0].resources.requests.cpu,RESTARTS:.status.containerStatuses[0].restartCount,AGE:.metadata.creationTimestamp" --no-headers
    Start-Sleep 3
}
```

---

## PHẦN 1: TRÌNH DIỄN TẤN CÔNG EDoS (12 phút)

### Cảnh 1: Giới thiệu hệ thống (2 phút)

**Lời dẫn:**

> "Chúng ta có một ứng dụng web đang chạy trên Kubernetes với HPA autoscaling.
> Khi CPU vượt 50%, HPA sẽ tự động tạo thêm pod (scale up).
> Khi CPU giảm, HPA sẽ xóa bớt pod (scale down).
> Đây là cơ chế rất phổ biến trong cloud — nhưng cũng chính là điểm yếu mà attacker khai thác."

**Thao tác:** Mở browser tab 2, nhấn F5 vài lần → app phản hồi bình thường.

**Chỉ vào Terminal 1:**

> "Hiện tại hệ thống có 1 pod, CPU thấp, mọi thứ bình thường."

### Cảnh 2: Chạy Baseline Traffic (3 phút)

**Lời dẫn:**

> "Bây giờ tôi sẽ mô phỏng lượng người dùng bình thường truy cập vào hệ thống."

**Terminal 2 — Chạy legitimate traffic:**

```powershell
cd D:\Project\Golang\edos-demo
jmeter -n -t legitimate-random.jmx -l results\demo_baseline.jtl
```

**Lời dẫn (trong khi chờ):**

> "Traffic đang được gửi theo phân phối Poisson — giống mô hình trong bài báo.
> 10 threads, mỗi thread gửi request đến các endpoint homepage, browse, và buy."

**Chỉ vào Grafana (chờ 1-2 phút):**

> "Quan sát trên Grafana: CPU tăng dần lên khoảng 30-50%.
> HPA có thể scale lên 2 pods nếu CPU vượt 50%.
> Đây là trạng thái baseline — chi phí bình thường mà ứng dụng phải trả."

**Chỉ vào Terminal 1:**

> "HPA đang hiển thị CPU hiện tại và số replicas. Đây là trạng thái 'hòa bình'."

### Cảnh 3: Khởi động tấn công EDoS K=5 (4 phút)

**Lời dẫn:**

> "Bây giờ, kẻ tấn công xuất hiện. Attacker sẽ gửi lượng traffic gấp 5 lần (K=5)
> legitimate traffic. Nhưng quan trọng hơn, attacker là STATE-AWARE — nó theo dõi
> hệ thống qua Prometheus và chỉ tấn công khi phát hiện cluster đang scale down.
> Mục tiêu: buộc cluster liên tục duy trì nhiều pods → tăng hóa đơn cloud."

**Terminal 3 — Chạy attacker:**

```powershell
cd D:\Project\Golang\edos-demo
python attacker_controller.py 5
```

**Chỉ vào Terminal 3 output:**

> "Attacker đang kết nối Prometheus, đọc số replicas...
> Và BẮT ĐẦU BURST — 50 threads gửi đồng loạt trong 2 phút."

**Chờ 1-2 phút, chỉ vào Grafana:**

> "Nhìn Grafana — đây là điểm mấu chốt:
>
> 1. CPU NHẢY VỌT lên 80-100% khi burst bắt đầu
> 2. HPA phản ứng: tạo thêm pods — từ 1 lên 2, rồi 3, có thể 4
> 3. Khi burst dừng, CPU giảm... pods bắt đầu scale down
> 4. Nhưng attacker PHÁT HIỆN scale-down → lại burst tiếp!
>
> Đây chính là vòng lặp EDoS: scale up → trả tiền → scale down → attack → scale up lại."

**Chỉ vào Terminal 1:**

> "Số replicas dao động liên tục. Mỗi pod tồn tại = tiền cloud.
> Trong bài báo, tấn công K=5 có thể tăng chi phí lên 1.15x đến 1.5x
> so với baseline, tùy billing model."

### Cảnh 4: Tăng cường tấn công K=10 (3 phút)

**Dừng attacker K=5** (Ctrl+C ở Terminal 3), chờ 30 giây.

**Lời dẫn:**

> "Nếu attacker tăng gấp đôi sức mạnh thì sao? K=10 — traffic gấp 10 lần."

**Terminal 3:**

```powershell
python attacker_controller.py 10
```

**Chỉ vào Grafana (chờ 1 phút):**

> "CPU cao hơn, pods nhiều hơn — nhưng chú ý điều thú vị:
> Hiệu quả tấn công KHÔNG tăng tuyến tính theo K.
>
> Bài báo chứng minh: tăng K từ 5 lên 10, chi phí attacker tăng gấp đôi,
> nhưng số SU tạo thêm không tăng gấp đôi.
> Có một giới hạn trên cho lợi ích của việc tăng traffic."

**Dừng attacker** (Ctrl+C), dừng legitimate traffic (Ctrl+C ở Terminal 2).

**Tóm tắt Phần 1:**

> "Tóm lại, EDoS khai thác chính cơ chế autoscaling — thứ được thiết kế để bảo vệ hệ thống.
> Attacker không cần đánh sập service, chỉ cần buộc nó scale liên tục.
> Bây giờ, câu hỏi là: làm sao phòng thủ?"

---

## PHẦN 2: TRÌNH DIỄN PHÒNG THỦ RANDOMIZED HPA (12 phút)

### Cảnh 5: Giải thích cơ chế phòng thủ (2 phút)

**Lời dẫn:**

> "Bài báo đề xuất một countermeasure đơn giản nhưng hiệu quả:
> RANDOMIZE quyết định scaling.
>
> Thay vì HPA luôn đọc CPU thật, chúng ta chèn một Custom Metrics Adapter
> ở giữa. Mỗi lần HPA hỏi 'CPU bao nhiêu?':
>
> - 50% xác suất: trả lời CPU THẬT → HPA scale bình thường
> - 50% xác suất: trả lời CPU THẤP GIẢ → HPA nghĩ hệ thống rảnh, KHÔNG scale
>
> Attacker không thể biết lần nào HPA sẽ phản ứng, lần nào không.
> Chiến lược dự đoán scaling bị phá vỡ."

### Cảnh 6: Chuyển sang Randomized HPA (2 phút)

**Thao tác:**

```powershell
# Xoa HPA cu (standard)
kubectl delete hpa hpa-webapp -n teastore

# Scale ve 1 replica
kubectl scale deployment webapp -n teastore --replicas=1

# Apply HPA randomized
kubectl apply -f hpa-randomized.yaml

# Kiem tra
kubectl get hpa -n teastore
```

**Lời dẫn:**

> "Tôi vừa chuyển từ Standard HPA sang Randomized HPA.
> HPA bây giờ đọc metric 'randomized_cpu' từ custom adapter thay vì CPU thật."

**Terminal 4 — Mở logs adapter:**

```powershell
kubectl logs -f -n teastore deployment/custom-metrics-adapter --tail=5
```

**Chỉ vào Terminal 4:**

> "Đây là logs của adapter. Mỗi dòng cho thấy quyết định: REAL hay FAKE.
> Bây giờ chạy lại cùng kịch bản tấn công."

### Cảnh 7: Chạy Baseline với Randomized HPA (2 phút)

**Terminal 2:**

```powershell
cd D:\Project\Golang\edos-demo
jmeter -n -t legitimate-random.jmx -l results\demo_rand_baseline.jtl
```

**Chờ 1-2 phút, chỉ vào Grafana:**

> "Với traffic bình thường, randomized HPA vẫn hoạt động tốt.
> Có thể scaling chậm hơn một chút — nhưng service vẫn phục vụ được.
>
> Bài báo đo: baseline charges dưới randomized HPA bằng 90% standard HPA.
> Nghĩa là tiết kiệm được ~10% chi phí ngay cả khi KHÔNG bị tấn công."

**Chỉ vào Terminal 4:**

> "Nhìn logs: khi adapter trả FAKE, HPA thấy CPU thấp và không tạo thêm pod.
> Khi trả REAL, HPA phản ứng bình thường.
> Kết quả: scaling ít hung hãn hơn, ít pod thừa hơn."

### Cảnh 8: Tấn công vào Randomized HPA (4 phút)

**Lời dẫn:**

> "Bây giờ, attacker tấn công lại — cùng K=5 như trước."

**Terminal 3:**

```powershell
cd D:\Project\Golang\edos-demo
python attacker_controller.py 5
```

**Chờ 2-3 phút, chỉ vào từng thành phần:**

**Chỉ Grafana:**

> "So sánh với Phần 1: replicas KHÔNG tăng mạnh như trước.
> Có lúc burst gửi đến nhưng HPA nhận FAKE metric → không scale.
> Attacker lãng phí traffic mà không đạt được mục tiêu."

**Chỉ Terminal 4 (adapter logs):**

> "Nhìn logs adapter: dù CPU thật đang 80-90%, có những lần
> adapter trả về 10% → HPA hoàn toàn bỏ qua burst đó.
>
> [REAL ] CPU=85% → HPA scale up
> [FAKE ] return=10% actual=82% → HPA KHÔNG scale
> [FAKE ] return=10% actual=90% → HPA KHÔNG scale
> [REAL ] CPU=78% → HPA scale up
>
> Attacker không thể dự đoán pattern này vì nó là RANDOM."

**Chỉ Terminal 3 (attacker output):**

> "Attacker vẫn phát hiện scale-down và gửi burst — nhưng hiệu quả thấp hơn.
> Nhiều burst bị 'lãng phí' vì HPA không phản ứng."

### Cảnh 9: Dừng tấn công và so sánh (2 phút)

**Dừng tất cả traffic** (Ctrl+C ở Terminal 2 và 3).

**Lời dẫn (chỉ vào Grafana, zoom ra xem toàn bộ timeline):**

> "Hãy so sánh hai giai đoạn:
>
> PHẦN 1 — Standard HPA bị tấn công:
> - Replicas dao động mạnh: 1 → 3 → 4 → 2 → 4 liên tục
> - CPU lên xuống theo burst
> - Chi phí cao vì pods tồn tại lâu
>
> PHẦN 2 — Randomized HPA bị tấn công:
> - Replicas ổn định hơn, dao động ít hơn
> - Nhiều burst bị HPA bỏ qua
> - Chi phí thấp hơn đáng kể

**Thu thập số liệu:**

```powershell
python collect_metrics.py 15 results\demo_comparison.csv
```

> "Kết quả từ bài báo với cùng kịch bản:
>
> | Metric | Standard HPA | Randomized HPA |
> |--------|-------------|----------------|
> | Baseline SU charges | 4.87 | 4.41 (giảm 10%) |
> | Attack K=5 charges | 5.52 | 5.11 (giảm 7%) |
> | Attack K=10 charges | 6.16 | 6.07 (giảm 2%) |
> | Attack K=20 charges | 7.92 | 8.00 (tăng 1%) |
>
> Với K thấp-trung bình, randomization rất hiệu quả.
> Với K cực cao (K=20), traffic quá lớn có thể vượt qua defense."

---

## KẾT LUẬN (2 phút)

**Lời dẫn:**

> "Tóm tắt những gì chúng ta vừa thấy:
>
> 1. EDoS là mối đe dọa THỰC TẾ: attacker không cần đánh sập service,
>    chỉ cần khai thác autoscaling để tăng hóa đơn cloud.
>
> 2. Attacker thông minh (state-aware) hiệu quả hơn Yo-Yo attack đơn giản
>    vì họ theo dõi trạng thái hệ thống và chỉ tấn công đúng lúc.
>
> 3. Billing model ảnh hưởng lớn: per-hour mean billing giảm thiểu
>    impact tốt nhất so với per-minute hoặc per-hour max.
>
> 4. Tăng K không tỷ lệ thuận hiệu quả: có giới hạn trên,
>    K=10 thường hiệu quả hơn K=20 tính theo efficiency.
>
> 5. Randomized HPA là countermeasure đơn giản nhưng hiệu quả:
>    tiết kiệm ~10% baseline, giảm impact tấn công K thấp-trung bình,
>    không cần training ML model.
>
> 6. Hạn chế: với traffic cực lớn (K>=20), randomization không đủ.
>    Cần kết hợp thêm các biện pháp khác."

---

## PHỤ LỤC: LỆNH KHÔI PHỤC SAU DEMO

```powershell
# Dung tat ca traffic
# Ctrl+C tat ca terminal

# Chuyen ve Standard HPA
kubectl delete hpa --all -n teastore
kubectl apply -f hpa-lite.yaml
kubectl scale deployment webapp -n teastore --replicas=1

# Hoac xoa toan bo cluster
kind delete cluster --name edos-cluster
```

---

## PHỤ LỤC: XỬ LÝ SỰ CỐ KHI DEMO

**HPA không scale khi có traffic:**
```powershell
kubectl describe hpa -n teastore
# Kiem tra TARGETS co hien so khong
kubectl top pods -n teastore
# Kiem tra pod co CPU cao khong
```

**Adapter trả CPU=0%:**
```powershell
kubectl logs -n teastore deployment/custom-metrics-adapter --tail=5
# Neu CPU=0 -> restart adapter
kubectl rollout restart deployment/custom-metrics-adapter -n teastore
```

**jMeter không gửi được request:**
```powershell
curl.exe http://localhost:8080/buy
# Neu loi -> kiem tra pod
kubectl get pods -n teastore
kubectl logs -n teastore deployment/webapp
```

**Grafana không hiện data:**
```powershell
# Kiem tra Prometheus
curl.exe http://localhost:9090/api/v1/query?query=up
# Kiem tra datasource trong Grafana Settings
```
