# -*- coding: utf-8 -*-
"""PyInstaller 打包 runner：envs/default python + PYTHONNET_RUNTIME=netfx。"""
import subprocess, os, time, shutil

PY = r"C:\Users\Lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
CWD = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
LOG = os.path.join(CWD, "_build_out.txt")

env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONNET_RUNTIME"] = "netfx"   # pythonnet 用 .NET Framework（冻结验证铁律）

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

open(LOG, "w", encoding="utf-8").write("")

# 1) 杀运行中 exe（打包铁律）
subprocess.run(["taskkill", "/F", "/T", "/IM", "载荷方案设计器.exe"],
               capture_output=True, creationflags=0x08000000)
time.sleep(1)

# 2) 清旧 build（被锁文件 trash 失败会 EXIT=1，用 shutil 强删）
for d in ["build"]:
    p = os.path.join(CWD, d)
    if os.path.exists(p):
        try:
            shutil.rmtree(p); log("removed %s" % d)
        except Exception as e:
            log("rmtree %s failed: %s" % (d, e))

# 3) 打包
log("=== pyinstaller start %s ===" % time.strftime("%H:%M:%S"))
t0 = time.time()
r = subprocess.run([PY, "-m", "PyInstaller", "--noconfirm", "--clean", "design_app.spec"],
                   cwd=CWD, env=env, capture_output=True, timeout=900,
                   creationflags=0x08000000)
so = r.stdout.decode("utf-8", errors="replace")
se = r.stderr.decode("utf-8", errors="replace")
log("exit=%d elapsed=%.1fs" % (r.returncode, time.time() - t0))
log("--- stdout tail ---\n" + so[-2500:])
log("--- stderr tail ---\n" + se[-2500:])

# 4) 核验产物
exe = os.path.join(CWD, "dist", "载荷方案设计器.exe")
if os.path.exists(exe):
    log("EXE OK %s size=%d" % (exe, os.path.getsize(exe)))
else:
    log("EXE MISSING %s" % exe)
log("=== done %s ===" % time.strftime("%H:%M:%S"))
print("build finished rc=%d" % r.returncode)
