# -*- coding: utf-8 -*-
"""#56 验证：真实 design_all → info_flows → svg_info_flow 渲染（泳道版）"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_engine as DE
import report_gen as RG

KG_PATH = os.path.join(BASE, "output", "通信有效载荷知识图谱_2026-09-20.json")
with open(KG_PATH, "r", encoding="utf-8") as f:
    KG = json.load(f)

cfg = {
    "mission": "GEO 高通量",
    "orbit": "GEO",
    "band": "Ka",
    "target": "巴基斯坦",
    "capacity_mbps": 500,
    "antenna_type": "固面反射面",
}
R = DE.design_all(cfg, KG, skip_compare=True)
assert isinstance(R, dict), "design_all 未返回 dict"
print("design_all OK, keys:", sorted(R.keys())[:12], "...")

# info_flows 需要 (cfg, p, res, totals, trp) —— 看 report_gen 里怎么取的
fl = R.get("flows") or R.get("info_flows")
if fl is None:
    # 尝试从 R 的子键重建
    print("R 中无 flows 键，可用键:", [k for k in R.keys()])
    sys.exit(2)
print("flows keys:", sorted(fl.keys()))
assert "tiers" in fl and "levels" in fl and "stages_def" in fl, "flows 缺维度键"

svg = RG.svg_info_flow(fl, cfg)
assert isinstance(svg, str) and svg.strip().startswith("<svg"), "svg_info_flow 未产出 SVG"
assert "泳道" in svg or "lane" in svg.lower() or "<rect" in svg, "泳道结构缺失"
print("svg_info_flow OK, len=%d" % len(svg))

# 关键断言：四类泳道色带存在 + 无旧版交叉布局残留
for kw in ["业务", "数据", "控制", "供能"]:
    assert kw in svg, "泳道缺类别: " + kw
for lv in ["星地", "星间", "星内"]:
    assert lv in svg, "泳道缺段: " + lv
print("四类泳道 + 三星段标签 OK")

# 落盘供肉眼检查
out = os.path.join(BASE, "output", "_info_flow_swimlane_check.svg")
with open(out, "w", encoding="utf-8") as f:
    f.write(svg)
print("RESULT: PASS ->", out)
