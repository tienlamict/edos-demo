import subprocess
import time

print("=== Test 1: Kiem tra jmeter path ===")
r = subprocess.run("jmeter.bat --version", shell=True, capture_output=True, text=True)
print(f"Return code: {r.returncode}")
print(f"Stdout: {r.stdout[:200] if r.stdout else 'EMPTY'}")
print(f"Stderr: {r.stderr[:200] if r.stderr else 'EMPTY'}")

print("\n=== Test 2: Chay burst 30 giay ===")
proc = subprocess.Popen(
    "jmeter.bat -n -t attacker-burst.jmx -JTHREADS=50 -JDURATION=30 -l results\\debug_test.jtl",
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
print(f"PID: {proc.pid}")
print("Cho 15 giay...")
time.sleep(15)

if proc.poll() is None:
    print("jMeter DANG CHAY - OK!")
else:
    out, err = proc.communicate()
    print(f"jMeter DA DUNG - co loi!")
    print(f"Stdout: {out.decode()[:500]}")
    print(f"Stderr: {err.decode()[:500]}")

# Cleanup
if proc.poll() is None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    print("Da dung jMeter")