"""
EDoS Attacker Controller v2 - Fix logic trigger.
"""

import subprocess, requests, time, csv, os, sys
from datetime import datetime

PROMETHEUS_URL = "http://localhost:9090"
JMETER_CMD = r"D:\Tools\apache-jmeter-5.6.3\bin\jmeter.bat"

ATTACK_POWER_K = 5
BURST_DURATION_SEC = 120
CHECK_INTERVAL_SEC = 10
ATTACK_WINDOW_SEC = 900
COOLDOWN_SEC = 30         # Chờ 30s sau mỗi burst trước khi burst tiếp

LEGIT_THREADS = 10
ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

attack_log = []
attack_active = False
attack_process = None
total_bursts = 0


def get_replicas():
    """Lay so replicas - thu Prometheus truoc, fallback kubectl."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": 'kube_deployment_status_replicas{namespace="teastore", deployment="webapp"}'
        }, timeout=5)
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return int(float(data["data"]["result"][0]["value"][1]))
    except:
        pass
    try:
        r = subprocess.run(
            ["kubectl", "get", "deployment", "webapp", "-n", "teastore",
             "-o", "jsonpath={.status.replicas}"],
            capture_output=True, text=True, timeout=10
        )
        if r.stdout.strip():
            return int(r.stdout.strip())
    except:
        pass
    return -1


def get_cpu_percent():
    """Lay CPU utilization hien tai cua webapp pods."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": ('sum(rate(container_cpu_usage_seconds_total'
                      '{namespace="teastore", pod=~"webapp.*"}[1m])) / '
                      'sum(kube_pod_container_resource_requests'
                      '{namespace="teastore", pod=~"webapp.*", resource="cpu"}) * 100')
        }, timeout=5)
        data = resp.json()
        if data["status"] == "success" and data["data"]["result"]:
            return float(data["data"]["result"][0]["value"][1])
    except:
        pass
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
    print("  <<< Burst ket thuc")


def log(ts, su, cpu, action, reason):
    entry = {"time": ts.strftime("%H:%M:%S"), "replicas": su,
             "cpu_pct": f"{cpu:.0f}" if cpu >= 0 else "?",
             "action": action, "reason": reason}
    attack_log.append(entry)
    cpu_str = f"{cpu:.0f}%" if cpu >= 0 else "?"
    icon = {"IDLE": "  ", "LAUNCH": ">>", "ATTACKING": "!!", 
            "BURST_END": "<<", "COOLDOWN": ".."}
    print(f"  [{ts.strftime('%H:%M:%S')}] {icon.get(action,'?')} "
          f"Replicas={su} CPU={cpu_str} | {action} | {reason}")


def save_logs():
    os.makedirs("results", exist_ok=True)
    fname = f"results\\attacker_K{ATTACK_POWER_K}_{datetime.now().strftime('%H%M%S')}.csv"
    with open(fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time","replicas","cpu_pct","action","reason"])
        w.writeheader()
        w.writerows(attack_log)
    frac = (total_bursts * BURST_DURATION_SEC) / ATTACK_WINDOW_SEC if ATTACK_WINDOW_SEC > 0 else 0
    print(f"\n{'='*50}")
    print(f"  KET QUA:")
    print(f"  Attack power K  = {ATTACK_POWER_K}")
    print(f"  Total bursts    = {total_bursts}")
    print(f"  frac_attack     = {frac:.3f}")
    print(f"  Log file        = {fname}")
    print(f"{'='*50}")


def main():
    global ATTACK_POWER_K, ATTACK_THREADS

    if len(sys.argv) > 1:
        ATTACK_POWER_K = int(sys.argv[1])
        ATTACK_THREADS = LEGIT_THREADS * ATTACK_POWER_K

    print("=" * 50)
    print(f"  EDoS Attacker v2")
    print(f"  K={ATTACK_POWER_K} | Threads={ATTACK_THREADS}")
    print(f"  Burst={BURST_DURATION_SEC}s | Window={ATTACK_WINDOW_SEC}s")
    print("=" * 50)

    # Cho ket noi
    print("  Connecting...")
    while get_replicas() == -1:
        time.sleep(3)

    su = get_replicas()
    cpu = get_cpu_percent()
    print(f"  Connected! Replicas={su} CPU={cpu:.0f}%\n")

    start_time = datetime.now()
    burst_end = 0
    cooldown_end = 0
    prev_su = su

    try:
        while (datetime.now() - start_time).total_seconds() < ATTACK_WINDOW_SEC:
            su = get_replicas()
            cpu = get_cpu_percent()
            now = datetime.now()

            if su == -1:
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            # Dang trong burst
            if attack_active:
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

            # === LOGIC ATTACK ===
            # Attack khi:
            #   1. Replicas dang giam (scale-down dang xay ra), HOAC
            #   2. Legitimate traffic da day CPU len (co co hoi day them), HOAC
            #   3. Dinh ky moi 3 phut de duy tri ap luc
            #
            should_attack = False
            reason = ""
            
            elapsed = (now - start_time).total_seconds()
            periodic = (elapsed % 180) < CHECK_INTERVAL_SEC  # Moi 3 phut

            if su < prev_su:
                should_attack = True
                reason = f"Scale-down detected ({prev_su}->{su})"
            elif su >= 1 and periodic:
                should_attack = True
                reason = f"Periodic burst (every 3min, elapsed={elapsed:.0f}s)"
            elif su >= 1 and cpu > 30:
                should_attack = True
                reason = f"CPU={cpu:.0f}% > 30%, pushing harder"

            if should_attack:
                log(now, su, cpu, "LAUNCH", reason)
                start_burst()
                burst_end = time.time() + BURST_DURATION_SEC
            else:
                log(now, su, cpu, "IDLE", "Waiting for opportunity")

            prev_su = su
            time.sleep(CHECK_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n  Ctrl+C - stopping...")

    if attack_active:
        stop_burst()
    save_logs()


if __name__ == "__main__":
    main()