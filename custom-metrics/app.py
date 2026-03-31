"""
Custom Metrics Adapter v2 - Randomized HPA Defense.
Fix: doc CPU bang kubectl top thay vi Metrics API.
"""

from flask import Flask, jsonify, request
import subprocess
import random
import time
import os
import logging
import re

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

RANDOMIZATION_WEIGHT = float(os.environ.get("RANDOMIZATION_WEIGHT", "0.5"))
FAKE_LOW_VALUE = int(os.environ.get("FAKE_LOW_VALUE", "10"))
NAMESPACE = os.environ.get("NAMESPACE", "teastore")
DEPLOYMENT = os.environ.get("DEPLOYMENT", "webapp")

stats = {"total": 0, "real": 0, "fake": 0}

# Cache CPU de khong goi kubectl qua nhieu
cpu_cache = {"value": 50, "timestamp": 0}
CACHE_TTL = 5  # seconds


def get_real_cpu():
    """Lay CPU bang kubectl top pods."""
    now = time.time()
    if now - cpu_cache["timestamp"] < CACHE_TTL:
        return cpu_cache["value"]

    try:
        result = subprocess.run(
            ["kubectl", "top", "pods", "-n", NAMESPACE,
             "-l", f"app={DEPLOYMENT}", "--no-headers"],
            capture_output=True, text=True, timeout=10
        )
        # Output: "webapp-xxx   45m   32Mi"
        # Parse CPU mCores
        total_cpu_m = 0
        pod_count = 0
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                cpu_str = parts[1]  # "45m" hoac "1"
                match = re.match(r'(\d+)m?', cpu_str)
                if match:
                    val = int(match.group(1))
                    # Neu khong co 'm' suffix -> dang la cores, nhan 1000
                    if 'm' not in cpu_str:
                        val = val * 1000
                    total_cpu_m += val
                    pod_count += 1

        if pod_count == 0:
            return cpu_cache["value"]

        # CPU request cua webapp la 100m per pod
        cpu_request_m = 100 * pod_count
        cpu_percent = int((total_cpu_m / cpu_request_m) * 100)
        cpu_percent = min(cpu_percent, 200)  # cap at 200%

        cpu_cache["value"] = cpu_percent
        cpu_cache["timestamp"] = now
        return cpu_percent

    except Exception as e:
        log.error(f"kubectl top error: {e}")
        return cpu_cache["value"]


def get_randomized_cpu():
    stats["total"] += 1
    real_cpu = get_real_cpu()

    if random.random() < RANDOMIZATION_WEIGHT:
        stats["real"] += 1
        log.info(f"[REAL ] CPU={real_cpu}% "
                 f"({stats['real']}/{stats['total']} = "
                 f"{stats['real']*100//stats['total']}% real)")
        return real_cpu, "real"
    else:
        stats["fake"] += 1
        log.info(f"[FAKE ] return={FAKE_LOW_VALUE}% actual={real_cpu}% "
                 f"({stats['fake']}/{stats['total']} = "
                 f"{stats['fake']*100//stats['total']}% fake)")
        return FAKE_LOW_VALUE, "fake"


# === API Endpoints ===

@app.route("/apis/custom.metrics.k8s.io/v1beta1", methods=["GET"])
def api_discovery():
    return jsonify({
        "kind": "APIResourceList",
        "apiVersion": "v1",
        "groupVersion": "custom.metrics.k8s.io/v1beta1",
        "resources": [{
            "name": "pods/randomized_cpu",
            "singularName": "",
            "namespaced": True,
            "kind": "MetricValueList",
            "verbs": ["get"]
        }]
    })


@app.route("/apis/custom.metrics.k8s.io/v1beta1/namespaces/<namespace>/pods/<path:selector>/randomized_cpu",
           methods=["GET"])
def get_metric(namespace, selector):
    cpu_value, decision = get_randomized_cpu()

    return jsonify({
        "kind": "MetricValueList",
        "apiVersion": "custom.metrics.k8s.io/v1beta1",
        "metadata": {"selfLink": request.path},
        "items": [{
            "describedObject": {
                "kind": "Pod",
                "namespace": namespace,
                "name": "*",
                "apiVersion": "/v1"
            },
            "metricName": "randomized_cpu",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "value": str(cpu_value)
        }]
    })


@app.route("/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "total": stats["total"],
        "real": stats["real"],
        "fake": stats["fake"],
        "real_pct": round(stats["real"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
        "weight": RANDOMIZATION_WEIGHT,
        "current_cpu": cpu_cache["value"]
    })


@app.route("/healthz", methods=["GET"])
def health():
    return "ok", 200


if __name__ == "__main__":
    log.info(f"Custom Metrics Adapter v2")
    log.info(f"  Weight:    {RANDOMIZATION_WEIGHT}")
    log.info(f"  Fake val:  {FAKE_LOW_VALUE}%")
    log.info(f"  Namespace: {NAMESPACE}")
    log.info(f"  Deploy:    {DEPLOYMENT}")
    app.run(host="0.0.0.0", port=6443, ssl_context="adhoc")