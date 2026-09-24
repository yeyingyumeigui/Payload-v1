# -*- coding: utf-8 -*-
"""v2 整改全套回归 runner：依次跑各验证脚本，输出摘要落盘。"""
import subprocess, os, time

PY = r"C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"
CWD = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"

CASES = [
    ("physics", "_verify_physics.py", ("PASS",)),
    ("smoke_v5", "_smoke_v5.py", ("ALL PASS", "PASS")),
    ("smoke_v4", "_smoke_v4.py", ("ALL PASS", "PASS")),
    ("t_v5", "_t_v5.py", ("PASS",)),
    ("shelf_check", "_shelf_check.py", ("PASS",)),
    ("shelf_func", "_shelf_func.py", ("PASS",)),
    ("t56_infoflow", "_t56_infoflow.py", ("PASS",)),
    ("t59_api", "_t59_api.py", ("PASS",)),
    ("t63_report", "_t63_report.py", ("PASS",)),
    ("t83_applyable", "_t83_applyable.py", ("PASS",)),
    ("t85_diagram", "_t85_diagram.py", ("PASS",)),
    ("t86_flows", "_t86_flows.py", ("PASS",)),
    ("t88_rings", "_t88_rings.py", ("PASS",)),
]

out = []
n_ok, n_bad, n_skip = 0, 0, 0
for name, fn, okwords in CASES:
    if not os.path.exists(os.path.join(CWD, fn)):
        out.append("[%s] SKIP (脚本不存在)" % name); n_skip += 1; continue
    t0 = time.time()
    try:
        r = subprocess.run([PY, "-B", fn], cwd=CWD, env=env, capture_output=True,
                           timeout=600, creationflags=0x08000000)
        txt = r.stdout.decode("utf-8", errors="replace")
        err = r.stderr.decode("utf-8", errors="replace")
        tail = "\n".join(txt.strip().splitlines()[-3:])
        # 判定：exit=0 + 含通过标记 + 无真实 FAIL 行
        # （"FAILS=0" / "FAIL=0" / "0 fail" 属零失败汇总，不算失败）
        import re
        real_fail = any("FAIL" in ln and not re.search(r"FAILS?[=:]\s*0\b", ln)
                        for ln in txt.splitlines())
        ok = r.returncode == 0 and any(w in txt for w in okwords) and not real_fail
        out.append("[%s] %s (%.1fs) exit=%d\n  tail: %s%s" % (
            name, "OK" if ok else "BAD", time.time()-t0, r.returncode,
            tail.replace("\n", " | "),
            ("\n  stderr: " + err.strip().splitlines()[-1] if err.strip() else "")))
        n_ok += ok; n_bad += (not ok)
    except subprocess.TimeoutExpired:
        out.append("[%s] BAD (timeout)" % name); n_bad += 1
    except Exception as e:
        out.append("[%s] BAD (%s: %s)" % (name, type(e).__name__, e)); n_bad += 1

# selftest（design_app --selftest，输出 grade/png）
try:
    t0 = time.time()
    r = subprocess.run([PY, "-B", "design_app.py", "--selftest"], cwd=CWD, env=env,
                       capture_output=True, timeout=600, creationflags=0x08000000)
    txt = r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")
    ok = r.returncode == 0 and "grade" in txt.lower()
    tail = "\n".join(txt.strip().splitlines()[-4:])
    out.append("[selftest] %s (%.1fs) exit=%d\n  tail: %s" % ("OK" if ok else "BAD", time.time()-t0, r.returncode, tail.replace("\n", " | ")))
    n_ok += ok; n_bad += (not ok)
except Exception as e:
    out.append("[selftest] BAD (%s: %s)" % (type(e).__name__, e)); n_bad += 1

out.append("\n== SUMMARY: %d OK / %d BAD / %d SKIP ==" % (n_ok, n_bad, n_skip))
open(os.path.join(CWD, "_regress_v2_out.txt"), "w", encoding="utf-8").write("\n".join(out))
print("done")
