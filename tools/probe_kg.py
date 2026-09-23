# -*- coding: utf-8 -*-
"""探测通信有效载荷知识图谱的 schema 与关键数据，输出结构化摘要供设计信息流软件使用。"""
import json, collections, os

SRC = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\_kg_probe.txt"

with open(SRC, "r", encoding="utf-8") as f:
    kg = json.load(f)

L = []
def p(*a):
    L.append(" ".join(str(x) for x in a))

p("=" * 70)
p("顶层键：", list(kg.keys()))
p("=" * 70)

# 元信息
for k in kg:
    v = kg[k]
    if isinstance(v, (str, int, float)):
        p(f"meta.{k} = {v}")
    elif isinstance(v, dict) and k not in ("ontologies", "attributes", "constraints", "relations"):
        p(f"meta.{k} = {json.dumps(v, ensure_ascii=False)[:300]}")
    elif isinstance(v, list):
        p(f"list.{k} : len={len(v)}")
        if v and isinstance(v[0], dict):
            p(f"   首元素键: {list(v[0].keys())}")

p("")
p("=" * 70)
p("一、ontologies 结构")
p("=" * 70)
ont = kg.get("ontologies", [])
p("总数:", len(ont))
if ont:
    p("字段全集:", sorted({k for o in ont for k in o.keys()}))
    p("")
    p("--- 前 3 个节点完整内容 ---")
    for o in ont[:3]:
        p(json.dumps(o, ensure_ascii=False, indent=2)[:1200])
        p("-" * 40)

# category 分布
cats = collections.Counter(o.get("category", "?") for o in ont)
p("")
p("--- category 分布 ---")
for c, n in cats.most_common():
    p(f"  {c}: {n}")

# level 分布
lv = collections.Counter(str(o.get("level", "?")) for o in ont)
p("")
p("--- level 分布 ---")
for c, n in sorted(lv.items()):
    p(f"  L{c}: {n}")

# 带 chain 的节点
chains = [o for o in ont if o.get("chain")]
p("")
p(f"--- 带 chain 字段的节点：{len(chains)} 个 ---")
for o in chains:
    p(f"  [{o.get('category')}] {o.get('id')} | {o.get('name')} | chain({len(o['chain'])}): {' → '.join(o['chain'][:14])}")

p("")
p("=" * 70)
p("二、attributes 结构")
p("=" * 70)
att = kg.get("attributes", [])
p("总数:", len(att))
if att:
    p("字段全集:", sorted({k for a in att for k in a.keys()}))
    p("")
    p("--- 前 8 条完整内容 ---")
    for a in att[:8]:
        p(json.dumps(a, ensure_ascii=False))
    # 按 ontologyId 统计
    byont = collections.Counter(a.get("ontologyId", "?") for a in att)
    p("")
    p(f"--- 属性最多的 12 个本体 ---")
    for oid, n in byont.most_common(12):
        p(f"  {oid}: {n}")
    # 属性名样例
    p("")
    p("--- 属性 name/code 样例（30条）---")
    for a in att[:30]:
        p(f"  {a.get('ontologyId')} :: {a.get('name')} | code={a.get('code')} | unit={a.get('unit')} | value={str(a.get('value'))[:40]} | type={a.get('type')}")

p("")
p("=" * 70)
p("三、constraints 结构")
p("=" * 70)
con = kg.get("constraints", [])
p("总数:", len(con))
if con:
    p("字段全集:", sorted({k for c in con for k in c.keys()}))
    p("")
    p("--- 全部约束 ---")
    for c in con:
        p(json.dumps(c, ensure_ascii=False)[:400])

p("")
p("=" * 70)
p("四、relations 结构")
p("=" * 70)
rel = kg.get("relations", [])
p("总数:", len(rel))
if rel:
    p("字段全集:", sorted({k for r in rel for k in r.keys()}))
    types = collections.Counter(r.get("type", r.get("relation", "?")) for r in rel)
    p("")
    p("--- 关系类型分布 ---")
    for t, n in types.most_common():
        p(f"  {t}: {n}")
    p("")
    p("--- 前 10 条 ---")
    for r in rel[:10]:
        p(json.dumps(r, ensure_ascii=False))

p("")
p("=" * 70)
p("五、层级树（id / name / category / level / parent）")
p("=" * 70)
for o in ont:
    indent = "  " * int(o.get("level", 0) or 0)
    p(f"{indent}[{o.get('level')}|{o.get('category')}] {o.get('id')} — {o.get('name')}  (parent={o.get('parentId') or o.get('parent') or '-'})")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print(f"probe written: {OUT}, lines={len(L)}")
