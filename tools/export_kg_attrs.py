# -*- coding: utf-8 -*-
"""导出全部 167 属性（id/ontologyId/name/symbol）与 25 约束的完整 members，
供设计信息流计算引擎时做 attributeId ↔ symbol 精确映射。"""
import json

SRC = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\_kg_attrs_full.txt"

with open(SRC, "r", encoding="utf-8") as f:
    kg = json.load(f)

ont = {o["id"]: o for o in kg["ontologies"]}
atts = kg["attributes"]
att_by_id = {a["id"]: a for a in atts}

L = []
def p(*a): L.append(" ".join(str(x) for x in a))

p("=" * 78)
p("全部属性（按本体分组）")
p("=" * 78)
by_ont = {}
for a in atts:
    by_ont.setdefault(a["ontologyId"], []).append(a)

for oid in [o["id"] for o in kg["ontologies"]]:
    if oid not in by_ont:
        continue
    o = ont[oid]
    p("")
    p(f"### {oid} | {o['name']} | [{o['category']}]")
    if o.get("chain"):
        p(f"    chain: {' → '.join(o['chain'])}")
    for a in by_ont[oid]:
        p(f"    - {a['id']:<24} symbol={str(a.get('symbol')):<14} {a['name']}")
        if a.get("description"):
            p(f"      desc: {a['description'][:150]}")

p("")
p("=" * 78)
p("全部 25 约束的完整 members（attributeId → role，含解析后的 symbol/name）")
p("=" * 78)
for c in kg["constraints"]:
    p("")
    p(f"[{c['id']}] {c['formula']}")
    p(f"  desc: {c['description']}")
    p(f"  members ({len(c['members'])}):")
    for m in c["members"]:
        aid = m.get("attributeId")
        a = att_by_id.get(aid)
        if a:
            p(f"    role={str(m.get('role')):<16} attrId={aid:<24} symbol={str(a.get('symbol')):<14} name={a['name']}  (on {a['ontologyId']})")
        else:
            p(f"    role={str(m.get('role')):<16} attrId={aid:<24} *** NOT FOUND ***")

# 统计：有多少 attributeId 在约束中被引用
refd = set()
missing = []
for c in kg["constraints"]:
    for m in c["members"]:
        refd.add(m["attributeId"])
        if m["attributeId"] not in att_by_id:
            missing.append((c["id"], m["attributeId"]))
p("")
p("=" * 78)
p(f"约束引用的属性数: {len(refd)} / 总属性 {len(atts)}")
p(f"引用但缺失的属性: {missing if missing else '无'}")
p("=" * 78)

# symbol 全集（用于计算引擎变量命名）
p("")
p("symbol 全集（去重）:")
syms = sorted({str(a.get("symbol")) for a in atts if a.get("symbol")})
p("  " + ", ".join(syms))

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print(f"written: {OUT}, lines={len(L)}, attrs={len(atts)}, constraints={len(kg['constraints'])}, missing_refs={len(missing)}")
