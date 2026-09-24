# -*- coding: utf-8 -*-
"""冻结验证：运行 dist/载荷方案设计器.exe --selftest / --guicheck，读取结果文件核验。
GUI exe(console=False) 必须用 subprocess+CREATE_NO_WINDOW 才能阻塞拿退出码。
首次 --selftest 偶发 EXIT=5（沙箱锁 _MEI），删旧结果重跑即恢复。"""
import subprocess, os, time

EXE = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools\dist\载荷方案设计器.exe"
DIST = os.path.dirname(EXE)
LOG = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools\_frozen_out.txt"
CNW = 0x08000000  # CREATE_NO_WINDOW

def run_mode(mode, result_file, tries=2):
    """跑 exe 某模式，返回 (exit, 结果文件文本)。首次 EXIT!=0 自动删结果重试。"""
    rpath = os.path.join(DIST, result_file)
    for d in (DIST, os.environ.get("TEMP", ""), "."):
        p = os.path.join(d, result_file) if d else result_file
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
    last = (None, "")
    for i in range(tries):
        t0 = time.time()
        r = subprocess.run([EXE, mode], cwd=DIST, capture_output=True,
                           timeout=180, creationflags=CNW)
        el = time.time() - t0
        # 结果文件可能在 DIST 或 __file__ 目录或 TEMP
        txt = ""
        for d in (DIST, os.environ.get("TEMP", ""), "."):
            p = os.path.join(d, result_file) if d else result_file
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f: txt = f.read()
                    if txt.strip(): break
                except Exception: pass
        last = (r.returncode, txt)
        if r.returncode == 0 and txt.strip():
            return r.returncode, txt, el
        time.sleep(1.5)  # EXIT=5 偶发，删旧结果重跑
    return last[0], last[1], el

out = []
out.append("=== FROZEN VERIFY %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
out.append("EXE=%s size=%d" % (EXE, os.path.getsize(EXE) if os.path.exists(EXE) else -1))

rc, txt, el = run_mode("--selftest", "payload_designer_selftest.txt")
out.append("\n--- SELFTEST rc=%s (%.1fs) ---" % (rc, el))
out.append(txt[-3500:] if txt else "(no result file)")
st_ok = rc == 0 and "FAIL" not in txt and txt.count("] OK") >= 8 and "RASTERIZED" in txt
out.append("SELFTEST verdict: %s" % ("PASS" if st_ok else "CHECK"))

rc2, txt2, el2 = run_mode("--guicheck", "payload_designer_guicheck.txt")
out.append("\n--- GUICHECK rc=%s (%.1fs) ---" % (rc2, el2))
out.append(txt2[-2500:] if txt2 else "(no result file)")
gui_ok = rc2 == 0 and txt2.strip() != ""
out.append("GUICHECK verdict: %s" % ("PASS" if gui_ok else "CHECK"))

out.append("\n=== FROZEN SUMMARY: selftest=%s guicheck=%s ===" %
           ("PASS" if st_ok else "CHECK", "PASS" if gui_ok else "CHECK"))
with open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("frozen verify done selftest=%s guicheck=%s" % (st_ok, gui_ok))
