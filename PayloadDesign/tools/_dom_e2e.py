# -*- coding: utf-8 -*-
"""DOM E2E runner：提取前端 → 启 HTTP(8765) → node _test_dom.js → 停服务 → 落盘结果。"""
import subprocess, os, time

PY = r"C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"
NODE = r"C:\Users\Lenovo\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
CWD = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
LOG = os.path.join(CWD, "_dom_e2e_out.txt")
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
CNW = 0x08000000

out = []
def log(m):
    out.append(m)

# 1) 重新提取前端（本轮改了 #83/#86/#88 前端 JS，必须重提取）
r = subprocess.run([PY, "-B", "_extract_front.py"], cwd=CWD, env=env,
                   capture_output=True, timeout=120, creationflags=CNW)
log("[extract] rc=%d %s" % (r.returncode, r.stdout.decode("utf-8", errors="replace").strip()))

# 2) 启动测试 HTTP 服务（后台，固定 8765）
srv = subprocess.Popen([PY, "-B", "_serve_test.py"], cwd=CWD, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CNW)
# 等服务就绪（_test_port.txt 或直接探端口）
ready = False
for _ in range(40):
    time.sleep(0.5)
    try:
        import socket
        s = socket.create_connection(("127.0.0.1", 8765), timeout=0.5); s.close()
        ready = True; break
    except Exception:
        pass
log("[serve] pid=%d ready=%s" % (srv.pid, ready))

# 3) node DOM E2E
try:
    r = subprocess.run([NODE, "_test_dom.js", "_front_extract.js", "_front_extract.html"],
                       cwd=CWD, env=env, capture_output=True, timeout=300, creationflags=CNW)
    so = r.stdout.decode("utf-8", errors="replace")
    se = r.stderr.decode("utf-8", errors="replace")
    log("[node] rc=%d" % r.returncode)
    log("--- stdout tail ---\n" + so[-3000:])
    if se.strip():
        log("--- stderr tail ---\n" + se[-1500:])
finally:
    # 4) 停服务
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(srv.pid)],
                       capture_output=True, creationflags=CNW)
    except Exception:
        pass
    log("[serve] stopped")

with open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("dom e2e done, see _dom_e2e_out.txt")
