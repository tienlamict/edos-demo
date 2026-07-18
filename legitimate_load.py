"""
Legitimate Load Generator - EDoS Demo (ban nhe).

Mo phong nguoi dung binh thuong truy cap webapp theo phan phoi Poisson
(thoi gian giua cac request tuan theo phan phoi mu - exponential),
giong mo hinh legitimate traffic trong bai bao. KHONG phai kich ban tan cong:
tai vua phai, on dinh, ty le endpoint giong hanh vi thuc te.

Cach dung:
    python legitimate_load.py                 # 10 users, chay 1800s (30 phut)
    python legitimate_load.py --threads 15    # 15 users dong thoi
    python legitimate_load.py --duration 300  # chay 5 phut
    python legitimate_load.py --rate 2.0      # trung binh 2 req/giay moi user
    Ctrl+C de dung sap.

So sanh voi attacker_controller.py (K=5): script nay la "K=1" - tai nen hoa binh.
"""

import argparse
import random
import sys
import threading
import time
from collections import Counter

try:
    import requests
except ImportError:
    print("Thieu thu vien 'requests'. Cai bang: pip install requests")
    sys.exit(1)


BASE_URL = "http://localhost:8080"

# Ty le truy cap tung endpoint (hanh vi nguoi dung binh thuong):
#   trang chu nhieu, browse vua, buy it (giong ty le xem/mua thuc te).
ENDPOINTS = [
    ("/",       0.40),   # homepage - nhe
    ("/browse", 0.40),   # xem san pham - vua
    ("/buy",    0.20),   # dat hang - ton CPU
]

# --- Thong ke dung chung giua cac thread ---
stats_lock = threading.Lock()
stats = {
    "total": 0,
    "ok": 0,
    "err": 0,
    "latency_sum": 0.0,
    "by_endpoint": Counter(),
    "by_status": Counter(),
}
stop_event = threading.Event()


def pick_endpoint():
    """Chon endpoint theo trong so."""
    r = random.random()
    cum = 0.0
    for path, weight in ENDPOINTS:
        cum += weight
        if r <= cum:
            return path
    return ENDPOINTS[0][0]


def user_worker(user_id, mean_interval, session):
    """Mot 'nguoi dung' - gui request lien tuc voi khoang cach Poisson."""
    while not stop_event.is_set():
        path = pick_endpoint()
        url = BASE_URL + path
        t0 = time.perf_counter()
        try:
            resp = session.get(url, timeout=10)
            latency = time.perf_counter() - t0
            ok = 200 <= resp.status_code < 400
            with stats_lock:
                stats["total"] += 1
                stats["latency_sum"] += latency
                stats["by_endpoint"][path] += 1
                stats["by_status"][resp.status_code] += 1
                if ok:
                    stats["ok"] += 1
                else:
                    stats["err"] += 1
        except requests.RequestException:
            with stats_lock:
                stats["total"] += 1
                stats["err"] += 1
                stats["by_status"]["conn_error"] += 1

        # Poisson process: thoi gian cho tuan theo phan phoi mu (exponential).
        delay = random.expovariate(1.0 / mean_interval)
        stop_event.wait(delay)


def reporter(interval=5.0):
    """In thong ke dinh ky."""
    last_total = 0
    last_time = time.time()
    while not stop_event.is_set():
        stop_event.wait(interval)
        now = time.time()
        with stats_lock:
            total = stats["total"]
            ok = stats["ok"]
            err = stats["err"]
            lat_avg = (stats["latency_sum"] / ok * 1000) if ok else 0.0
            ep = dict(stats["by_endpoint"])
        dt = now - last_time
        rps = (total - last_total) / dt if dt > 0 else 0.0
        last_total, last_time = total, now
        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"total={total:<6} rps={rps:5.1f} ok={ok} err={err} "
            f"avg_latency={lat_avg:6.1f}ms  endpoints={ep}"
        )


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Legitimate load generator (EDoS demo)")
    parser.add_argument("--url", default=BASE_URL, help="Base URL (default http://localhost:8080)")
    parser.add_argument("--threads", type=int, default=10, help="So user dong thoi (default 10)")
    parser.add_argument("--duration", type=int, default=1800, help="Thoi luong chay giay (default 1800)")
    parser.add_argument("--rate", type=float, default=2.0,
                        help="Trung binh req/giay moi user (default 2.0 ~ giong Poisson timer 350ms)")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")
    mean_interval = 1.0 / args.rate if args.rate > 0 else 0.5

    print("=" * 60)
    print("  LEGITIMATE LOAD GENERATOR (tai hop le - K=1)")
    print("=" * 60)
    print(f"  Target      : {BASE_URL}")
    print(f"  Users       : {args.threads}")
    print(f"  Rate/user   : {args.rate} req/s  (mean interval {mean_interval*1000:.0f} ms, phan phoi Poisson)")
    print(f"  Duration    : {args.duration}s")
    print(f"  Endpoint mix: {', '.join(f'{p}={int(w*100)}%' for p, w in ENDPOINTS)}")
    print("=" * 60)
    print("  Nhan Ctrl+C de dung sap.\n")

    # Session dung chung connection pool cho tung thread.
    threads = []
    rep = threading.Thread(target=reporter, daemon=True)
    rep.start()

    for i in range(args.threads):
        s = requests.Session()
        t = threading.Thread(target=user_worker, args=(i, mean_interval, s), daemon=True)
        t.start()
        threads.append(t)

    try:
        stop_event.wait(args.duration)
    except KeyboardInterrupt:
        print("\n[!] Nhan Ctrl+C - dang dung...")
    finally:
        stop_event.set()
        time.sleep(1.0)

    # Bao cao tong ket
    with stats_lock:
        total = stats["total"]
        ok = stats["ok"]
        err = stats["err"]
        lat_avg = (stats["latency_sum"] / ok * 1000) if ok else 0.0
        by_status = dict(stats["by_status"])
        by_ep = dict(stats["by_endpoint"])
    print("\n" + "=" * 60)
    print("  KET QUA")
    print("=" * 60)
    print(f"  Tong request : {total}")
    print(f"  Thanh cong   : {ok}")
    print(f"  Loi          : {err}")
    print(f"  Latency TB   : {lat_avg:.1f} ms")
    print(f"  Theo status  : {by_status}")
    print(f"  Theo endpoint: {by_ep}")
    print("=" * 60)


if __name__ == "__main__":
    main()
