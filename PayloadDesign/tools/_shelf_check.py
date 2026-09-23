# -*- coding: utf-8 -*-
"""货架库增补后完整性校验：ID 唯一/类别合法/频段代码/元组结构/天线体制归类。"""
import sys

sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_data as DD
import design_engine as DE

BANDS_OK = set(DD.BAND_KEYS) | {"激光", "*"}
fails = []


def ck(name, cond, msg=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + msg if msg else ""))
    if not cond:
        fails.append(name)


# 1. 结构：每条 9 字段
ck("全部元组 9 字段", all(len(u) == 9 for u in DD.SHELF_UNITS),
   "n=%d" % len(DD.SHELF_UNITS))
# 2. ID 唯一
ids = [u[0] for u in DD.SHELF_UNITS]
dup = [i for i in set(ids) if ids.count(i) > 1]
ck("ID 唯一无重复", not dup, str(dup))
# 3. 类别都在 SHELF_CATS
badcat = sorted(set(u[2] for u in DD.SHELF_UNITS) - set(DD.SHELF_CATS))
ck("类别均在 SHELF_CATS", not badcat, str(badcat))
# 4. 频段代码合法
badband = []
for u in DD.SHELF_UNITS:
    for b in u[3]:
        if b not in BANDS_OK:
            badband.append((u[0], b))
ck("频段代码合法", not badband, str(badband))
# 5. level 在 1..4
badlv = [(u[0], u[4]) for u in DD.SHELF_UNITS if u[4] not in (1, 2, 3, 4)]
ck("level∈{1,2,3,4}", not badlv, str(badlv))
# 6. mass/power 数值非负
badnum = [(u[0], u[5], u[6]) for u in DD.SHELF_UNITS
          if not (isinstance(u[5], (int, float)) and u[5] >= 0
                  and isinstance(u[6], (int, float)) and u[6] >= 0)]
ck("mass/power 非负数值", not badnum, str(badnum))
# 7. specs 是 dict
badsp = [u[0] for u in DD.SHELF_UNITS if not isinstance(u[7], dict)]
ck("specs 均为 dict", not badsp, str(badsp))
# 8. SHELF_BY_ID 与 SHELF_UNITS 数量一致
ck("SHELF_BY_ID 一致", len(DD.SHELF_BY_ID) == len(DD.SHELF_UNITS),
   "%d vs %d" % (len(DD.SHELF_BY_ID), len(DD.SHELF_UNITS)))
# 9. 天线体制归类：每个天线 ID 都能被 _ant_family 解析（不抛异常）
ant = [u for u in DD.SHELF_UNITS if u[2] == "天线"]
fam_bad = []
for u in ant:
    try:
        DE._ant_family(u[0])
    except Exception as e:
        fam_bad.append((u[0], str(e)))
ck("天线 _ant_family 可解析", not fam_bad, str(fam_bad))
# 10. 新增产品确实入库
new_ids = ["ANT-REFL-QV-GAL", "ANT-AESA-KA8-GAL", "ANT-AESA-D2D-GAL", "ANT-REFL-X",
           "ANT-REFL-S-TTC", "LNA-QV-01", "LO-USO-INT", "TWTA-QV-40", "SSPA-QV-20",
           "TWTA-X-40", "SSPA-L-200", "BFC-8B-GAL", "DBF-ASIC-GAL", "SDR-SAT-INT",
           "GNB-SAT-GAL", "LCT-GEO-INT", "LCT-CUBEL-INT", "LCT-DTE-INT",
           "TTC-TRP-S-INT", "TTC-DB-INT", "OBC-RH-INT"]
missing = [i for i in new_ids if i not in DD.SHELF_BY_ID]
ck("21 条新增全部入库", not missing, str(missing))
# 11. Q/V 频段现在有完整链路货架（天线/LNA/变频/功放）
qv_cats = set(u[2] for u in DD.SHELF_UNITS if "Q/V" in u[3])
ck("Q/V 链路货架齐全", {"天线", "LNA", "变频", "功放", "多工器"} <= qv_cats, str(sorted(qv_cats)))

# 12. 每类计数报告
from collections import Counter
cnt = Counter(u[2] for u in DD.SHELF_UNITS)
print("\n各类别货架数（共 %d 条）：" % len(DD.SHELF_UNITS))
for c in DD.SHELF_CATS:
    print("  %-8s %d" % (c, cnt.get(c, 0)))

print()
if fails:
    print("SHELF CHECK FAIL: %d -> %s" % (len(fails), fails))
    sys.exit(1)
print("SHELF CHECK ALL PASS")
