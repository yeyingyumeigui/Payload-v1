# -*- coding: utf-8 -*-
"""清理 v2 整改的一次性调试产物（保留可复用验证/回归/打包脚本）。"""
import os

CWD = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
# 一次性调试脚本与中间输出（可删）
TARGETS = [
    "_dbg_bool.py", "_dbg_deps.py", "_dbg_tb.txt", "_dbg_fail_lines.txt",
    "_t88_out.txt", "_build_out.txt", "_frozen_out.txt", "_dom_e2e_out.txt",
    "_regress_v2_out.txt", "_test_port.txt",
    # 冻结 exe 自检产物（写在 dist/ 与 tools/）
    os.path.join("dist", "payload_designer_selftest.txt"),
    os.path.join("dist", "payload_designer_guicheck.txt"),
    "payload_designer_selftest.txt", "payload_designer_guicheck.txt",
    "payload_designer_boot.log",
]
removed, missing = [], []
for t in TARGETS:
    p = os.path.join(CWD, t)
    if os.path.exists(p):
        try:
            os.remove(p); removed.append(t)
        except Exception as e:
            removed.append("%s (ERR %s)" % (t, e))
    else:
        missing.append(t)
print("removed:", removed)
print("missing(skip):", missing)
