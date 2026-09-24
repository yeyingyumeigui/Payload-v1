# -*- coding: utf-8 -*-
"""v3 打包 runner：① 备份 v2 exe（先行、确认成功）② 杀 exe ③ 清 build
④ PyInstaller（envs/default python + PYTHONNET_RUNTIME=netfx）⑤ 核验产物。"""
import subprocess, os, time, shutil

PY = r"C:\Users\Lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
TOOLS = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
BASE = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign"
LOG = os.path.join(TOOLS, "_build_v3_out.txt")
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONNET_RUNTIME"] = "netfx"   # pythonnet 用 .NET Framework（冻结验证铁律）

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

open(LOG, "w", encoding="utf-8").write("")

# ---- ① 备份 v2 exe（当前 dist 即 v2 最终版；打包会覆盖，必须先备份）----
dist_exe = os.path.join(TOOLS, "dist", "载荷方案设计器.exe")
bk_dir = os.path.join(BASE, "backup_v2final_20260923")
bk_exe = os.path.join(bk_dir, "载荷方案设计器_v2.exe")
if os.path.exists(dist_exe):
    v2_size = os.path.getsize(dist_exe)
    os.makedirs(bk_dir, exist_ok=True)
    shutil.copy2(dist_exe, bk_exe)
    if os.path.exists(bk_exe) and os.path.getsize(bk_exe) == v2_size:
        log("[备份] v2 exe → %s (%d 字节，核验一致)" % (bk_exe, v2_size))
    else:
        log("[备份] 失败！中止打包（避免丢失 v2）")
        raise SystemExit(1)
else:
    log("[备份] dist exe 不存在，跳过备份（首次打包）")

# ---- ② 杀运行中 exe（打包铁律）----
subprocess.run(["taskkill", "/F", "/T", "/IM", "载荷方案设计器.exe"],
               capture_output=True, creationflags=0x08000000)
time.sleep(1)

# ---- ③ 清旧 build（被锁文件 trash 失败会 EXIT=1，用 shutil 强删）----
for d in ["build"]:
    p = os.path.join(TOOLS, d)
    if os.path.exists(p):
        try:
            shutil.rmtree(p); log("[清理] removed %s" % d)
        except Exception as e:
            log("[清理] rmtree %s failed: %s" % (d, e))

# ---- ④ 打包 ----
log("=== pyinstaller start %s ===" % time.strftime("%H:%M:%S"))
t0 = time.time()
r = subprocess.run([PY, "-m", "PyInstaller", "--noconfirm", "--clean", "design_app.spec"],
                   cwd=TOOLS, env=env, capture_output=True, timeout=900,
                   creationflags=0x08000000)
so = r.stdout.decode("utf-8", errors="replace")
se = r.stderr.decode("utf-8", errors="replace")
log("pyinstaller exit=%d elapsed=%.1fs" % (r.returncode, time.time() - t0))
log("--- stdout tail ---\n" + so[-1500:])
log("--- stderr tail ---\n" + se[-1500:])

# ---- ⑤ 核验产物 ----
exe = os.path.join(TOOLS, "dist", "载荷方案设计器.exe")
if os.path.exists(exe):
    log("[产物] EXE OK %s size=%d" % (exe, os.path.getsize(exe)))
else:
    log("[产物] EXE MISSING %s" % exe)
log("=== done %s ===" % time.strftime("%H:%M:%S"))
print("BUILD_V3_RC=%d" % r.returncode)
