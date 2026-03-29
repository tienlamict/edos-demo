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