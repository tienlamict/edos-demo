# Phương án thay thế TeaStore — Lightweight EDoS Demo

## So sánh các phương án

| Phương án | RAM/pod | Số pods tối thiểu | Tổng RAM ước tính | Phù hợp |
|-----------|---------|-------------------|-------------------|---------|
| TeaStore (6 services) | 512-1024 MB | 7 pods | ~5-7 GB | Máy 32GB+ |
| **Nginx stress app** | **30-64 MB** | **1 pod** | **~200 MB** | **Máy 8GB+** |
| httpbin | 50-128 MB | 1 pod | ~300 MB | Máy 8GB+ |
| Podinfo | 20-50 MB | 1 pod | ~150 MB | Máy 8GB+ |

> Chọn: **Nginx stress app** — nhẹ nhất, dễ trigger CPU để HPA scale,
> mô phỏng đủ hiện tượng EDoS của bài báo.

---

## Bước 1: Xóa TeaStore (nếu đã deploy)

```powershell
kubectl delete -f teastore.yaml 2>$null
kubectl delete -f teastore-lite.yaml 2>$null
kubectl delete hpa --all -n teastore 2>$null
```

---

## Bước 2: Deploy ứng dụng Nginx stress

Ứng dụng này làm 2 việc:
- Trả về HTTP response (mô phỏng web app)
- Tốn CPU khi xử lý request (để HPA có thể trigger scale)

Tạo file `C:\edos-demo\webapp.yaml`:

```yaml
# ConfigMap chứa nginx config + script tốn CPU
apiVersion: v1
kind: ConfigMap
metadata:
  name: webapp-config
  namespace: teastore
data:
  nginx.conf: |
    worker_processes 1;
    events { worker_connections 256; }
    http {
      server {
        listen 8080;

        # Trang chủ - nhẹ
        location / {
          default_type text/html;
          return 200 '<html><body><h1>EDoS Demo Store</h1><p>OK</p></body></html>';
        }

        # Endpoint tốn CPU - dùng để trigger HPA scaling
        location /buy {
          default_type text/html;
          content_by_lua_block {
            -- Tiêu tốn CPU: tính toán vô nghĩa
            local sum = 0
            for i = 1, 50000 do
              sum = sum + math.sqrt(i) * math.sin(i)
            end
            ngx.say("<html><body><h1>Order processed</h1><p>Result: " .. sum .. "</p></body></html>")
          }
        }

        # Endpoint vừa phải
        location /browse {
          default_type text/html;
          content_by_lua_block {
            local sum = 0
            for i = 1, 10000 do
              sum = sum + math.sqrt(i)
            end
            ngx.say("<html><body><h1>Products</h1><p>Items: " .. sum .. "</p></body></html>")
          }
        }

        # Health check
        location /health {
          default_type text/plain;
          return 200 'ok';
        }
      }
    }
---
# Deployment dùng OpenResty (Nginx + Lua) - rất nhẹ
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: webapp
  template:
    metadata:
      labels:
        app: webapp
    spec:
      containers:
        - name: webapp
          image: openresty/openresty:alpine
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /usr/local/openresty/nginx/conf/nginx.conf
              subPath: nginx.conf
          resources:
            requests:
              cpu: 100m
              memory: 32Mi
            limits:
              cpu: 250m
              memory: 64Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: config
          configMap:
            name: webapp-config
---
apiVersion: v1
kind: Service
metadata:
  name: webapp
  namespace: teastore
spec:
  type: NodePort
  selector:
    app: webapp
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30080
```

**Deploy:**

```powershell
kubectl apply -f webapp.yaml

# Chờ pod ready (~10 giây, rất nhanh)
kubectl get pods -n teastore -w
```

**Kiểm tra:**

```powershell
# Trang chủ
curl.exe http://localhost:8080/

# Endpoint tốn CPU
curl.exe http://localhost:8080/buy

# Browse
curl.exe http://localhost:8080/browse
```

---

## Bước 3: Cấu hình HPA

Tạo file `C:\edos-demo\hpa-lite.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-webapp
  namespace: teastore
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp
  minReplicas: 1
  maxReplicas: 6
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 15
      policies:
        - type: Pods
          value: 2
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
```

> **Chú ý:** Target CPU giảm xuống 50% (thay vì 80%) và scale nhanh hơn
> vì mỗi pod rất nhẹ → dễ quan sát hiện tượng scaling.

```powershell
kubectl apply -f hpa-lite.yaml
kubectl get hpa -n teastore
```

---

## Bước 4: Cập nhật jMeter test plans

Tạo file `C:\edos-demo\legitimate-random.jmx`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan"
              testname="Legitimate Traffic"/>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup"
                   testname="Users">
        <intProp name="ThreadGroup.num_threads">10</intProp>
        <intProp name="ThreadGroup.ramp_time">10</intProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">1800</stringProp>
        <elementProp name="ThreadGroup.main_controller"
                     elementType="LoopController">
          <boolProp name="LoopController.continue_forever">true</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <PoissonRandomTimer guiclass="PoissonRandomTimerGui"
                            testclass="PoissonRandomTimer"
                            testname="Poisson Timer">
          <stringProp name="ConstantTimer.delay">200</stringProp>
          <stringProp name="RandomTimer.range">300</stringProp>
        </PoissonRandomTimer>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui"
                          testclass="HTTPSamplerProxy"
                          testname="Homepage">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui"
                          testclass="HTTPSamplerProxy"
                          testname="Browse">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/browse</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui"
                          testclass="HTTPSamplerProxy"
                          testname="Buy">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/buy</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <ResultCollector guiclass="SummaryReport"
                         testclass="ResultCollector"
                         testname="Summary">
          <stringProp name="filename">C:\edos-demo\results\legitimate.jtl</stringProp>
        </ResultCollector>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
```

Tạo file `C:\edos-demo\attacker-burst.jmx`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan"
              testname="EDoS Attack Burst"/>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup"
                   testname="Attack">
        <stringProp name="ThreadGroup.num_threads">${__P(THREADS,50)}</stringProp>
        <intProp name="ThreadGroup.ramp_time">3</intProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">${__P(DURATION,120)}</stringProp>
        <elementProp name="ThreadGroup.main_controller"
                     elementType="LoopController">
          <boolProp name="LoopController.continue_forever">true</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <ConstantTimer guiclass="ConstantTimerGui"
                       testclass="ConstantTimer" testname="Fast">
          <stringProp name="ConstantTimer.delay">30</stringProp>
        </ConstantTimer>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui"
                          testclass="HTTPSamplerProxy"
                          testname="Attack-Buy">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/buy</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui"
                          testclass="HTTPSamplerProxy"
                          testname="Attack-Browse">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/browse</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
```

---

## Bước 5: Cập nhật Attacker Controller

Tạo file `C:\edos-demo\attacker_controller.py`:

```python
"""
EDoS Attacker Controller - Phien ban nhe.
Theo doi replicas qua Prometheus, gui burst khi phat hien scale-down.
"""

import subprocess, requests, time, csv, os, sys
from datetime import datetime

PROMETHEUS_URL = "http://localhost:9090"
JMETER_CMD = r"C:\Tools\apache-jmeter-5.6.3\bin\jmeter.bat"

ATTACK_POWER_K = 5
SU_THRESHOLD = 2          # Thap hon vi chi co 1 deployment
BURST_DURATION_SEC = 120
CHECK_INTERVAL_SEC = 10
ATTACK_WINDOW_SEC = 900   # 15 phut (ngan hon de test nhanh)

LEGIT_THREADS = 10
ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

attack_log = []
previous_su = 0
attack_active = False
attack_process = None
total_bursts = 0


def get_replicas():
    """Lay so replicas cua webapp."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": 'kube_deployment_status_replicas{namespace="teastore", deployment="webapp"}'
        }, timeout=5)
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return int(float(data["data"]["result"][0]["value"][1]))
    except:
        pass
    # Fallback: dung kubectl
    try:
        r = subprocess.run(
            ["kubectl", "get", "deployment", "webapp", "-n", "teastore",
             "-o", "jsonpath={.status.replicas}"],
            capture_output=True, text=True, timeout=10
        )
        return int(r.stdout.strip())
    except:
        return -1


def start_burst():
    global attack_process, attack_active, total_bursts
    cmd = [
        JMETER_CMD, "-n", "-t", "attacker-burst.jmx",
        f"-JTHREADS={ATTACK_THREADS}",
        f"-JDURATION={BURST_DURATION_SEC}",
        "-l", f"results\\attack-{total_bursts}.jtl"
    ]
    print(f"  >>> BURST #{total_bursts+1}: {ATTACK_THREADS} threads x {BURST_DURATION_SEC}s")
    attack_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    attack_active = True
    total_bursts += 1


def stop_burst():
    global attack_process, attack_active
    if attack_process and attack_process.poll() is None:
        attack_process.terminate()
        try: attack_process.wait(timeout=10)
        except: attack_process.kill()
    attack_active = False
    print("  >>> Burst ket thuc")


def log(ts, su, action, reason):
    entry = {"time": ts.strftime("%H:%M:%S"), "replicas": su,
             "action": action, "reason": reason}
    attack_log.append(entry)
    icon = {"IDLE": ".", "LAUNCH": "!!", "ATTACKING": ">>", "BURST_END": "<<"}
    print(f"  [{ts.strftime('%H:%M:%S')}] {icon.get(action,'?')} "
          f"Replicas={su} | {action} | {reason}")


def save_logs():
    os.makedirs("results", exist_ok=True)
    fname = f"results\\attacker_K{ATTACK_POWER_K}_{datetime.now().strftime('%H%M%S')}.csv"
    with open(fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time","replicas","action","reason"])
        w.writeheader()
        w.writerows(attack_log)
    frac = (total_bursts * BURST_DURATION_SEC) / ATTACK_WINDOW_SEC
    print(f"\n  Saved: {fname}")
    print(f"  Total bursts: {total_bursts}")
    print(f"  frac_attack:  {frac:.3f}")


def main():
    global previous_su, ATTACK_POWER_K, ATTACK_THREADS

    if len(sys.argv) > 1:
        ATTACK_POWER_K = int(sys.argv[1])
        ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

    print("=" * 50)
    print(f"  EDoS Attacker | K={ATTACK_POWER_K} | "
          f"Threads={ATTACK_THREADS}")
    print("=" * 50)

    while get_replicas() == -1:
        print("  Waiting for metrics...")
        time.sleep(5)

    previous_su = get_replicas()
    start_time = datetime.now()
    burst_end = 0

    print(f"  Start: replicas={previous_su}\n")

    try:
        while (datetime.now() - start_time).total_seconds() < ATTACK_WINDOW_SEC:
            su = get_replicas()
            now = datetime.now()
            if su == -1:
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            if attack_active:
                if time.time() > burst_end:
                    stop_burst()
                    log(now, su, "BURST_END", "Done")
                else:
                    log(now, su, "ATTACKING", f"Running ({int(burst_end - time.time())}s left)")
                    time.sleep(CHECK_INTERVAL_SEC)
                    previous_su = su
                    continue

            # Logic attack: khi SU >= threshold VA (dang giam HOAC o muc cao)
            if su >= SU_THRESHOLD and su <= previous_su:
                log(now, su, "LAUNCH", f"SU>={SU_THRESHOLD} & stable/decreasing")
                start_burst()
                burst_end = time.time() + BURST_DURATION_SEC
            else:
                log(now, su, "IDLE", f"SU={su} (prev={previous_su})")

            previous_su = su
            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n  Ctrl+C")

    if attack_active:
        stop_burst()
    save_logs()


if __name__ == "__main__":
    main()
```

---

## Bước 6: Kiểm tra tài nguyên tổng

Sau khi deploy xong, kiểm tra:

```powershell
# Tong tai nguyen dang dung
kubectl top nodes
kubectl top pods -A

# Kiem tra HPA
kubectl get hpa -n teastore
```

Tổng tài nguyên dự kiến:

| Component | CPU request | Memory request |
|-----------|-------------|----------------|
| webapp (1 pod) | 100m | 32Mi |
| Metrics Server | 100m | 200Mi |
| Prometheus | 200m | 256Mi |
| Grafana | 100m | 128Mi |
| kube-state-metrics | 10m | 32Mi |
| node-exporter (x3) | 30m | 90Mi |
| Kind system pods | ~300m | ~400Mi |
| **Tổng** | **~840m** | **~1.1 GB** |

So với TeaStore cần ~5-7 GB → giảm **5-6 lần**.

---

## Bước 7: Chạy thí nghiệm nhanh

### Terminal 1: Theo dõi

```powershell
while ($true) {
    Clear-Host
    Write-Host "=== $(Get-Date -Format 'HH:mm:ss') ===" -ForegroundColor Cyan
    kubectl get hpa -n teastore
    Write-Host ""
    kubectl get pods -n teastore -o wide
    Start-Sleep 5
}
```

### Terminal 2: Legitimate traffic

```powershell
cd C:\edos-demo
jmeter -n -t legitimate-random.jmx -l results\baseline.jtl
```

### Terminal 3: Attacker (chờ ~2 phút cho baseline ổn định)

```powershell
cd C:\edos-demo

# Test K=5
python attacker_controller.py 5

# Sau khi xong, test K=10
python attacker_controller.py 10
```

### Quan sát ở Terminal 1:

Bạn sẽ thấy:
- Baseline: 1-2 replicas
- Khi attacker burst: replicas tăng lên 3-6
- Khi burst dừng: replicas từ từ giảm
- Attacker phát hiện giảm → burst mới → replicas tăng lại

Đây chính là hiện tượng EDoS mà bài báo mô tả.

---

## Mapping với bài báo

| Khái niệm bài báo | Trong demo này |
|-------------------|----------------|
| Service Unit (SU) | 1 pod webapp |
| M (max SUs) | maxReplicas = 6 |
| λ (legitimate rate) | 10 threads jMeter |
| K (attack power) | Hệ số nhân threads |
| HPA threshold 80% | CPU target 50% |
| Billing per-minute | Đếm replicas mỗi phút qua Prometheus |
| Yo-Yo pattern | Burst 2 phút ON → scale down → burst lại |
| Hysteresis | scaleUp nhanh (15s) vs scaleDown chậm (60s) |
| Attack efficiency | (SU_attack - SU_baseline) / (K × frac_attack) |
