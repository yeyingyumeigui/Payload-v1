# -*- coding: utf-8 -*-
"""#92 验证：多星协同覆盖单一服务区 regional_coverage()——GEO 空间分区 + LEO 时间接力。"""
import sys, io, traceback
TOOLS = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
sys.path.insert(0, TOOLS)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NPASS = NFAIL = 0
def ck(cond, msg):
    global NPASS, NFAIL
    if cond: NPASS += 1; print("  PASS %s" % msg)
    else:    NFAIL += 1; print("  FAIL %s" % msg)

import design_data as DD, design_engine as DE

print("=== GEO 多星协同覆盖巴基斯坦（空间分区）===")
cfg = dict(DD.DEFAULT_CFG, name="GEO区域协同", service="高通量宽带", orbit="GEO",
           coverage="巴基斯坦", band="Ka", mode="数字透明", ant_type="固面", N_sat=3)
geo = DE.derive_geometry(cfg)
print("  geo: el_deg=%.1f cov_r=%.0f h=%.0f" % (geo["el_deg"], geo["cov_r_km"], geo["orbit_alt_km"]))
r = DE.regional_coverage(cfg, geo)
ck(r is not None, "GEO regional_coverage 返回非空")
ck(r and r.get("ok"), "ok=True")
ck(r and r["orbit"] == "GEO", "orbit=GEO")
ck(r and r["n_sat"] == 3, "n_sat=3")
ck(r and len(r["sats"]) == 3, "3 个星位 %s" % ([s["lon"] for s in r["sats"]] if r else "?"))
ck(r and r["grid_pts"] > 100, "服务区网格点 %d" % (r["grid_pts"] if r else 0))
ck(r and 0 <= r["worst_el"] <= 90, "最差点最佳仰角 %.1f°" % (r["worst_el"] if r else -1))
ck(r and r["min_mult"] >= 0, "最小覆盖重数 %d" % (r["min_mult"] if r else -1))
ck(r and (r["min_sat_for_el"] is None or 1 <= r["min_sat_for_el"] <= 3),
   "达标最小星数 %s（None=纬度向仰角受限）" % (r["min_sat_for_el"] if r else "?"))
ck(r and isinstance(r["mult_hist"], dict) and r["mult_hist"], "重数直方非空")
ck(r and "spread_half_deg" in r and "single_sat_ok" in r, "含展开半宽/单星达标标志")
# 物理一致性：GEO 星位限于赤道，若服务区边缘仰角受限，多星不应假装达标
ck(r and (r["feasible"] == (r["worst_el"] >= r["el_min"] - 1e-6)),
   "feasible 与 worst_el≥el_min 一致（不假装达标）")
print("  verdict:", r["verdict"] if r else "N/A")
print("  note:", r["note"] if r else "N/A")

print("\n=== GEO 单星对照（应返回 None）===")
cfg1 = dict(cfg); cfg1["N_sat"] = 1
ck(DE.regional_coverage(cfg1, DE.derive_geometry(cfg1)) is None, "N_sat=1 → None（未启用协同）")

print("\n=== GEO 省域（单星视域内 → 聚拢/冗余）===")
cfgS = dict(DD.DEFAULT_CFG, name="GEO省域协同", service="高通量宽带", orbit="GEO",
            coverage="省域", band="Ka", mode="数字透明", ant_type="固面", N_sat=2)
geoS = DE.derive_geometry(cfgS)
rS = DE.regional_coverage(cfgS, geoS)
ck(rS and rS["single_sat_ok"] is True, "省域单星即达标 single_sat_ok=True")
ck(rS and rS["spread_half_deg"] < 5, "星位聚拢（展开半宽 %.1f° <5°）" % (rS["spread_half_deg"] if rS else -1))
ck(rS and rS["min_sat_for_el"] == 1, "达标最小星数=1（多星为冗余）")
print("  verdict:", rS["verdict"] if rS else "N/A")

print("\n=== LEO 多星协同覆盖巴基斯坦（时间接力）===")
cfgL = dict(DD.DEFAULT_CFG, name="LEO区域协同", service="宽带接入", orbit="LEO",
            coverage="巴基斯坦", band="Ka", mode="数字透明", ant_type="相控阵",
            N_sat=8, incl_deg=45, N_plane=2)
geoL = DE.derive_geometry(cfgL)
print("  geo: el_deg=%.1f h=%.0f" % (geoL["el_deg"], geoL["orbit_alt_km"]))
rL = DE.regional_coverage(cfgL, geoL)
ck(rL is not None and rL.get("ok"), "LEO regional_coverage ok=True")
ck(rL and rL["orbit"] == "LEO", "orbit=LEO")
ck(rL and rL["n_sat"] == 8, "n_sat=8")
ck(rL and rL["grid_pts"] == 9, "代表点=中心+8方位=9（%d）" % (rL["grid_pts"] if rL else 0))
ck(rL and 0 <= rL["cov_pct"] <= 100, "覆盖率 %.1f%%" % (rL["cov_pct"] if rL else -1))
ck(rL and rL["min_mult"] >= 0, "最小重数 %d" % (rL["min_mult"] if rL else -1))
ck(rL and isinstance(rL.get("targets"), list) and len(rL["targets"]) == 9, "逐代表点结果 9 条")
ck(rL and "continuous" in rL, "含 continuous 标志")
print("  verdict:", rL["verdict"] if rL else "N/A")
print("  note:", rL["note"] if rL else "N/A")

print("\n=== 大圆距离/网格辅助函数 ===")
d = DE._great_circle_km(30.5, 69.5, 30.5, 70.5)
ck(80 < d < 110, "巴基斯坦经度1°大圆距离 %.1fkm（≈95）" % d)
g = DE._region_grid(30.5, 69.5, 800, n=11)
ck(len(g) > 50, "服务区网格点 %d（圆盘内）" % len(g))
tg = DE._region_targets(30.5, 69.5, 800)
ck(len(tg) == 9 and tg[0]["name"] == "中心", "代表点 9 个，首个=中心")

print("\n=== design_all 集成（N_sat≥2 → R.regional_coverage）===")
try:
    import design_app as DA
    R = DE.design_all(cfg, DA.KG, skip_compare=True)
    ck("regional_coverage" in R, "R 含 regional_coverage 键")
    ck(R.get("regional_coverage") and R["regional_coverage"].get("ok"), "集成结果 ok")
except Exception:
    traceback.print_exc()
    ck(False, "design_all 集成异常")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
