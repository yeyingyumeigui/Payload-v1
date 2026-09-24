# -*- coding: utf-8 -*-
"""#93 验证：在轨卫星对标 orbital_benchmark() + ORBITAL_REFS 库。"""
import sys, io, traceback
TOOLS = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
sys.path.insert(0, TOOLS)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NPASS = NFAIL = 0
def ck(cond, msg):
    global NPASS, NFAIL
    if cond: NPASS += 1; print("  PASS %s" % msg)
    else:    NFAIL += 1; print("  FAIL %s" % msg)

import design_data as DD, design_engine as DE, design_app as DA

print("=== ORBITAL_REFS 库结构 ===")
ck(len(DD.ORBITAL_REFS) >= 10, "在轨库 %d 颗（≥10）" % len(DD.ORBITAL_REFS))
ids = [s["id"] for s in DD.ORBITAL_REFS]
ck(len(set(ids)) == len(ids), "id 唯一")
for need in ["ChinaSat-26", "SES-17", "Starlink-V2Mini", "OneWeb", "O3b-mPOWER"]:
    ck(need in ids, "含在轨星 %s" % need)
# 关键字段完整
for s in DD.ORBITAL_REFS:
    for k in ("id", "cn", "operator", "orbit", "band", "launch", "src"):
        if k not in s:
            ck(False, "%s 缺字段 %s" % (s.get("id"), k)); break
    else:
        continue
ck(True, "全部卫星关键字段完整")
ck(DD.ORBITAL_REF_BY_ID.get("ChinaSat-26", {}).get("capacity_gbps") == 100, "中星26容量=100Gbps")
ck(DD.ORBITAL_REF_BY_ID.get("SES-17", {}).get("capacity_gbps") == 200, "SES-17容量=200Gbps")

print("\n=== orbital_refs_for 过滤 ===")
geo_ka = DD.orbital_refs_for(orbit="GEO", band="Ka")
ck(len(geo_ka) >= 5, "GEO/Ka 在轨星 %d 颗（≥5）" % len(geo_ka))
ck(all(s["orbit"] == "GEO" for s in geo_ka), "过滤轨道正确")
leo = DD.orbital_refs_for(orbit="LEO")
ck(len(leo) >= 4, "LEO 在轨星 %d 颗（≥4）" % len(leo))
ck(len(DD.orbital_refs_for(orbit="火星")) == 0, "无匹配轨道→空")

print("\n=== GEO Ka 高通量对标 ===")
cfg = dict(DD.DEFAULT_CFG, name="对标自检", service="高通量宽带", orbit="GEO",
           coverage="中国全境", band="Ka", feeder_band="Ka", mode="数字透明",
           ant_type="固面", N_beam=64)
sg = DE.suggest_closed_loop(cfg, DA.KG)
for k, v in (sg.get("values") or {}).items():
    if v != "" and k != "N_beam":
        cfg[k] = v
cfg["N_beam"] = 64
R = DE.design_all(cfg, DA.KG, skip_compare=True)
b = DE.orbital_benchmark(cfg, R)
ck(b.get("ok"), "对标返回 ok=True")
ck(b["orbit"] == "GEO" and b["band"] == "Ka", "轨道/频段=GEO/Ka")
ck(b["n_refs"] >= 5, "对标 %d 颗在轨星" % b["n_refs"])
ck(isinstance(b["dims"], list) and len(b["dims"]) == 3, "3 个对标维度（容量/波束/质量）")
ck(b["dims"][0]["name"].startswith("整星容量"), "维度1=容量")
ck(b["cap_range"][0] is not None and b["cap_range"][1] is not None, "容量区间 %s~%s Gbps" % tuple(b["cap_range"]))
ck(b["position"], "定位结论：%s" % b["position"])
ck(len(b["verdict"]) > 30, "verdict 文本 %d 字" % len(b["verdict"]))
ck(any(s["id"] == "ChinaSat-26" for s in b["refs"]), "对标含中星26")
print("  c_sys=%.1f Gbps, 容量区间=%s" % (b["c_sys"], b["cap_range"]))
print("  position:", b["position"])
print("  verdict:", b["verdict"])

print("\n=== design_all 集成（R.orbital_benchmark）===")
ck("orbital_benchmark" in R, "R 含 orbital_benchmark 键")
ck(R["orbital_benchmark"].get("ok"), "集成对标 ok")
ck(R["orbital_benchmark"]["n_refs"] >= 5, "集成对标 %d 颗" % R["orbital_benchmark"]["n_refs"])

print("\n=== LEO 对标（星链/千帆/一网）===")
cfgL = dict(DD.DEFAULT_CFG, name="LEO对标", service="宽带接入", orbit="LEO",
            coverage="区域", band="Ka", mode="数字透明", ant_type="相控阵")
RL = DE.design_all(cfgL, DA.KG, skip_compare=True)
bL = DE.orbital_benchmark(cfgL, RL)
ck(bL.get("ok"), "LEO 对标 ok")
ck(bL["orbit"] == "LEO", "orbit=LEO")
ck(any(s["id"] in ("Starlink-V2Mini", "Qianfan-G60", "OneWeb") for s in bL["refs"]),
   "对标含星链/千帆/一网")
print("  LEO position:", bL["position"])
print("  LEO verdict:", bL["verdict"][:120])

print("\n=== 无同类在轨星（X 频段 GEO）===")
cfgX = dict(cfg); cfgX["band"] = "X"; cfgX["orbit"] = "GEO"
bX = DE.orbital_benchmark(cfgX, R)
ck(bX.get("ok") is False, "无同轨同频段→ok=False（%s）" % bX.get("verdict", "")[:40])

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
