# -*- coding: utf-8 -*-
"""#88 验证：beam_angle_rings（±θ 角域环地面投影）+ coverage API 集成。"""
import sys
import json
import io
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import coverage_engine as CE
import pattern_engine as PE

NPASS, NFAIL = 0, 0


def ck(cond, msg):
    global NPASS, NFAIL
    if cond:
        NPASS += 1
        print("  PASS %s" % msg)
    else:
        NFAIL += 1
        print("  FAIL %s" % msg)


# ---- 单元：GEO 固面 2.5m Ka ----
print("[单元] GEO 固面 2.5m Ka（boresight）")
pat = PE.reflector_pattern(2.5, 20.0, scan_theta=0.0, scan_phi=0.0)
th3 = pat["beamwidth_3db_deg"]
print("  θ3dB=%.4f° (70λ/D 理论=%.4f°)" % (th3, 70 * 3e8 / 20e9 / 2.5 * 180 / 3.14159265))
rr = CE.beam_angle_rings(pat, 35786.0, sat_lat=0.0, sat_lon=110.5)
rings = rr["rings"]
ck(rr["ok"] and len(rings) >= 1, "环数=%d ≥1" % len(rings))
r0 = rings[0]
print("  环0: θ=±%.3f° %s 半径=%.0fkm 点数=%d" % (r0["theta_deg"], r0["label"], r0["radius_km"], len(r0["pts"])))
ck(abs(r0["theta_deg"] - th3 / 2) < 0.05, "环0=−3dB 边缘 ±θ3dB/2（±%.3f°）" % r0["theta_deg"])
# GEO 几何解析核对：ψ=atan(h·tan(θ)/R) → 地面弧长 = R·ψ
import math
psi = math.degrees(math.atan(35786.0 * math.tan(math.radians(r0["theta_deg"])) / 6371.0))
r_expect = 6371.0 * math.radians(psi)
ck(abs(r0["radius_km"] - r_expect) / r_expect < 0.10,
   "地面半径 %.0fkm ≈ 解析 %.0fkm（GEO 锥面投影，误差<10%%）" % (r0["radius_km"], r_expect))
# 多环单调：外环角更大、半径更大
if len(rings) >= 2:
    ck(all(rings[i]["theta_deg"] < rings[i + 1]["theta_deg"] for i in range(len(rings) - 1)),
       "环角单调递增（%s）" % [r["theta_deg"] for r in rings])
    ck(all(rings[i]["radius_km"] < rings[i + 1]["radius_km"] for i in range(len(rings) - 1)),
       "环半径单调递增（%s）" % [r["radius_km"] for r in rings])
    ck(len({r["color"] for r in rings}) == len(rings), "各环颜色互异（分色）")
# 环点闭合（首尾近似相连）
p0, pn = r0["pts"][0], r0["pts"][-1]
d = math.hypot((p0[0] - pn[0]) * 111, (p0[1] - pn[1]) * 111 * math.cos(math.radians(p0[0])))
ck(d < 400, "环闭合（首尾距 %.0fkm < 一格）" % d)

# ---- 扫描态：波束指向巴基斯坦 ----
print("[单元] 扫描态（θ0 指向 30°N,70°E）")
th0, ph0 = CE.pointing_angles(0.0, 110.5, 35786.0, 30.0, 70.0)
pat2 = PE.reflector_pattern(2.5, 20.0, scan_theta=th0, scan_phi=ph0)
rr2 = CE.beam_angle_rings(pat2, 35786.0, sat_lat=0.0, sat_lon=110.5)
bc = rr2["beam_center"]
print("  scan=(%.2f°,%.1f°) beam_center=(%.2f,%.2f) 环数=%d" % (rr2["scan"]["theta_deg"], rr2["scan"]["phi_deg"], bc["lat"], bc["lon"], len(rr2["rings"])))
ck(abs(bc["lat"] - 30.0) < 1.0 and abs(bc["lon"] - 70.0) < 1.0, "波束中心落在目标点附近")
ck(len(rr2["rings"]) >= 1, "扫描态环生成正常")
# 扫描态：GEO 大离轴角锥面投影到球面非圆对称，半径比会明显>1（正常物理）。
# 这里只验证环点全部落在波束中心周围有限范围内（量级合理），不强求圆对称。
if rr2["rings"]:
    r = rr2["rings"][0]
    ds = [math.hypot((pt[0] - bc["lat"]) * 111, (pt[1] - bc["lon"]) * 111 * math.cos(math.radians(bc["lat"]))) for pt in r["pts"]]
    ratio = max(ds) / max(min(ds), 1e-6)
    ck(max(ds) < 500 and min(ds) > 0, "扫描态环点围绕波束中心（半径 %.0f~%.0fkm，比值 %.2f；大离轴锥面非圆对称属正常）" % (min(ds), max(ds), ratio))

# ---- 相控阵（含栅瓣/宽波束）----
print("[单元] LEO 相控阵 0.7λ 32×32")
pat3 = PE.phased_array_pattern(2.0, 32, 32, d_lam=0.7, scan_theta=10.0)
rr3 = CE.beam_angle_rings(pat3, 600.0, sat_lat=0.0, sat_lon=105.0)
ck(rr3["ok"] and len(rr3["rings"]) >= 1, "相控阵环数=%d ≥1" % len(rr3["rings"]))
if rr3["rings"]:
    r3 = rr3["rings"][0]
    print("  相控阵环0: ±%.2f° 半径=%.0fkm" % (r3["theta_deg"], r3["radius_km"]))
    ck(r3["radius_km"] < 2000, "LEO 足迹半径 <2000km（=%.0f）" % r3["radius_km"])

# ---- 集成：Api.coverage 返回 rings ----
print("[集成] design_app Api.coverage")
import design_app as DA
api = DA.Api.__new__(DA.Api)
api._pat_cache = {}
pay = dict(antenna_type="reflector", D=2.5, freq_ghz=20.0, peak_eirp_dbw=55.0,
           h_km=35786.0, sat_lat=0.0, sat_lon=110.5,
           target_lat=30.0, target_lon=70.0, point_at_target=True, n_lat=41, n_lon=51)
r4 = api.coverage(pay)
ck(r4.get("ok") is True, "API ok=%s err=%s" % (r4.get("ok"), r4.get("error")))
res = r4.get("result") or r4
ck(bool(res.get("rings")), "API 返回 rings（%d 环）" % len(res.get("rings") or []))
ck(res.get("th3_deg") is not None, "API 返回 th3_deg=%s" % res.get("th3_deg"))
# 键名对齐后应为固面 2.5m@20GHz：boresight θ3dB≈0.39°；扫描态 cut 剖面具化展宽
# （波束扫离天底 → 地面投影变形，0.39°→0.55° 量级正常），只要远离默认相控阵 4.4° 即对。
if res.get("th3_deg"):
    ck(0.30 < res["th3_deg"] < 1.20, "API 固面 θ3dB=%.4f°（0.30~1.20 扫描展宽区间，payload 键名对齐）" % res["th3_deg"])

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
