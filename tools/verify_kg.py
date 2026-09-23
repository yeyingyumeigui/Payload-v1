# -*- coding: utf-8 -*-
"""独立验证载荷方案知识图谱 JSON 的合法性与覆盖度，输出报告文件。"""
import json, io, sys

SRC = r"D:\ZWL\文生载荷Workbuddy\output\载荷方案知识图谱_2026-09-20.json"
RPT = r"D:\ZWL\文生载荷Workbuddy\output\_kg_verify_report.txt"

lines = []
def p(*a):
    lines.append(" ".join(str(x) for x in a))

with open(SRC, encoding="utf-8") as f:
    g = json.load(f)

ont, attr, cons = g["ontologies"], g["attributes"], g["constraints"]
p("JSON 解析: OK")
p("version:", g["version"], "| exportedAt:", g["exportedAt"])
p("ontologies:", len(ont), "| attributes:", len(attr), "| constraints:", len(cons))

# 引用完整性
ont_ids = {o["id"] for o in ont}
attr_ids = {a["id"] for a in attr}
errs = []
for o in ont:
    if o["parentId"] is not None and o["parentId"] not in ont_ids:
        errs.append(f"bad parentId: {o['id']} -> {o['parentId']}")
for a in attr:
    if a["ontologyId"] not in ont_ids:
        errs.append(f"bad ontologyId: {a['id']} -> {a['ontologyId']}")
for c in cons:
    for m in c["members"]:
        if m["attributeId"] not in attr_ids:
            errs.append(f"constraint {c['id']} bad member: {m['attributeId']}")
if len({o['id'] for o in ont}) != len(ont): errs.append("dup ontology id")
if len({a['id'] for a in attr}) != len(attr): errs.append("dup attribute id")
if len({c['id'] for c in cons}) != len(cons): errs.append("dup constraint id")
# 无环检查（parentId 树）
children = {}
for o in ont:
    children.setdefault(o["parentId"], []).append(o["id"])
seen = set()
def walk(nid, stack):
    if nid in stack:
        errs.append(f"cycle at {nid}")
        return
    stack = stack | {nid}
    for ch in children.get(nid, []):
        walk(ch, stack)
walk(None, set())

p("引用完整性:", "OK (0 errors)" if not errs else f"FAILED {errs}")

# 用户需求关键词覆盖
required = ["天线", "转发器", "激光", "智能处理单元", "DTP", "相控阵"]
blob = json.dumps(ont, ensure_ascii=False)
for k in required:
    hits = [o["id"] for o in ont if k in o["name"] or k in o["description"]]
    p(f"关键词[{k}]:", "✅" if hits else "❌", "->", ", ".join(hits[:6]))

# 树形预览（顶层展开2级）
p("")
p("== 本体树预览 ==")
def show(nid, depth, maxd=3):
    for ch in sorted(children.get(nid, []), key=lambda i: next(o["order"] for o in ont if o["id"]==i)):
        o = next(x for x in ont if x["id"]==ch)
        p("  "*depth + f"- {o['name']} ({o['id']})")
        if depth < maxd:
            show(ch, depth+1, maxd)
show(None, 0, 2)

# 约束清单
p("")
p("== 约束清单 ==")
for c in cons:
    roles = ",".join(m["role"] for m in c["members"])
    p(f"{c['id']}: {c['formula']}   [{roles}]")

# 源文件 4 条约束保留检查
p("")
src_formulas = {"σ_c ≤ σ_m / 3", "P_pv ≥ E_b × DOD / T_e", "σ_m + ω_s ≤ 0.05°", "GSD = d_px × H_orb / f_cam"}
now_formulas = {c["formula"] for c in cons}
kept = src_formulas & now_formulas
p(f"源约束保留: {len(kept)}/4", "OK" if len(kept)==4 else f"MISSING {src_formulas-now_formulas}")

with open(RPT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
