# -*- coding: utf-8 -*-
"""v4 整改全套回归 runner：v4新增(reflector/四指标耦合/国家耦合/集成) + v3全套 + selftest。"""
import subprocess, os, time, re

PY = r"C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"
CWD = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"

CASES = [
    # ---- v4 新增（快速反馈在前）----
    ("reflector", "reflector_engine.py", ("ALL PASS", "PASS", "fail=0")),
    ("orbit", "orbit_engine.py", ("ALL PASS",)),
    ("t95_spec", "_t95_spec.py", ("PASS", "fail=0")),
    ("t97_v4int", "_t97_v4int.py", ("PASS", "fail=0")),
    ("t98_word", "_t98_word.py", ("PASS", "fail=0")),
    ("t101_v41", "_t101_v41.py", ("PASS", "fail=0")),
    # ---- v3 全套（验证 v4 改动无回归）----
    ("physics", "_verify_physics.py", ("PASS",)),
    ("smoke_v5", "_smoke_v5.py", ("ALL PASS", "PASS", "FAIL=0", "OK=72")),
    ("smoke_v4", "_smoke_v4.py", ("ALL PASS", "PASS")),
    ("t_v5", "_t_v5.py", ("PASS", "FAIL=0", "OK=41")),
    ("shelf_check", "_shelf_check.py", ("PASS",)),
    ("shelf_func", "_shelf_func.py", ("PASS",)),
    ("t56_infoflow", "_t56_infoflow.py", ("PASS",)),
    ("t59_api", "_t59_api.py", ("PASS",)),
    ("t63_report", "_t63_report.py", ("PASS",)),
    ("t83_applyable", "_t83_applyable.py", ("PASS",)),
    ("t85_diagram", "_t85_diagram.py", ("PASS",)),
    ("t86_flows", "_t86_flows.py", ("PASS",)),
    ("t88_rings", "_t88_rings.py", ("PASS",)),
    ("t91_word", "_t91_word.py", ("PASS",)),
    ("t92_regional", "_t92_regional.py", ("PASS",)),
    ("t92_word", "_t92_word.py", ("PASS",)),
    ("t93_orbital", "_t93_orbital.py", ("PASS",)),
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
        real_fail = any("FAIL" in ln and not re.search(r"FAILS?[=:]\s*0\b|\d+ fail", ln)
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
open(os.path.join(CWD, "_regress_v4_out.txt"), "w", encoding="utf-8").write("\n".join(out))
print("done")
