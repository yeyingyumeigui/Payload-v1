# -*- coding: utf-8 -*-
"""从 design_app.py 提取 FRONT_HTML → _front_extract.js（script 体）与 _front_extract.html（完整）。"""
import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design_app as DA

html = DA.FRONT_HTML
with open(os.path.join(HERE, "_front_extract.html"), "w", encoding="utf-8") as f:
    f.write(html)
m = re.findall(r"<script>(.*?)</script>", html, re.S)
js = "\n".join(m)
with open(os.path.join(HERE, "_front_extract.js"), "w", encoding="utf-8") as f:
    f.write(js)
print("html chars:", len(html), "| script blocks:", len(m), "| js chars:", len(js))
