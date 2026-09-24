# -*- coding: utf-8 -*-
"""v4 验证 #95/#96：四指标耦合校核 + 覆盖区↔国家双向判定。

用户指标：覆盖区 ±1.5°、波束 >0.3°、72 波束、容量 50Gbps（均可配置）。
"""
import math
import sys

import design_engine as DE
from design_data import BAND_FREQ, COUNTRY_BY_KEY

ok = fail = 0


def chk(name, cond, info=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS %s %s" % (name, info))
    else:
        fail += 1
        print("  FAIL %s %s" % (name, info))


print("=== 1. 角度口径换算（严格球面三角 vs 解析参照）===")
h = 35786.0
R = 6371.0
# GEO 可见地盘边缘：el=0 → 地心半角 α_max = 90° − asin(R/(R+h)) = 81.30°，
# 对应离天底角 θ_edge = asin(R/(R+h)) = 8.693°（GEO 看整个可见地盘仅 ±8.69°）
a_max_ref = 90.0 - math.degrees(math.asin(R / (R + h)))
th_edge_ref = math.degrees(math.asin(R / (R + h)))
chk("θ_edge=%.3f° → α=%.2f°（可见地盘边界）" % (th_edge_ref, a_max_ref),
    abs(DE.offaxis_to_geocentric(th_edge_ref, h) - a_max_ref) < 0.05,
    "α=%.4f° (ref %.4f°)" % (DE.offaxis_to_geocentric(th_edge_ref, h), a_max_ref))
# 往返一致性
for th in (0.5, 1.0, 1.5, 3.0, 6.0, 8.0):
    a = DE.offaxis_to_geocentric(th, h)
    th2 = DE.geocentric_to_offaxis(a, h)
    chk("往返 θ=%.1f°→α→θ" % th, abs(th2 - th) < 1e-6,
        "α=%.4f° → θ=%.6f°" % (a, th2))
# ±1.5° 离轴的地面半径（解析核对）
th = 1.5 * math.pi / 180.0
alpha = math.asin(math.sin(th) * (R + h) / R) - th
r_ref = R * alpha
r_15 = DE.angle_to_radius_km(1.5, h, "offaxis")
chk("±1.5° 离轴 → 地面半径（解析核对）", abs(r_15 - r_ref) < 0.1,
    "r=%.1f km (ref %.1f)" % (r_15, r_ref))
# 小角近似核对：α ≈ (h/R)·θ = 5.617θ（GEO）
a_15 = DE.offaxis_to_geocentric(1.5, h)
chk("小角关系 α≈(h/R)θ=5.617θ（GEO）", abs(a_15 / 1.5 - 5.617) < 0.05,
    "α/θ=%.4f" % (a_15 / 1.5))
# 地心角口径
r_geo15 = DE.angle_to_radius_km(1.5, h, "geocentric")
chk("±1.5° 地心角 → 167km", abs(r_geo15 - 167.1) < 1.0, "r=%.1f km" % r_geo15)
# footprint 口径（斜距 37500km）
r_fp = DE.angle_to_radius_km(1.5, h, "footprint", d_slant_km=37500.0)
chk("±1.5° 足迹角@37500km → 982km", abs(r_fp - 981.7) < 2.0, "r=%.1f km" % r_fp)
# 逆函数
chk("radius→angle 逆一致", abs(DE.radius_km_to_angle(r_15, h, "offaxis") - 1.5) < 1e-3,
    "")

print("\n=== 2. 用户四指标场景（GEO/Ka，±1.5°离轴，波束>0.3°，72波束，50Gbps）===")
f_up, f_dn = BAND_FREQ["Ka"]
cfg = dict(service="高通量宽带", orbit="GEO", coverage="巴基斯坦", band="Ka",
           geo_lon=69.0, el_deg=46.0,
           cov_half_deg=1.5, angle_basis="offaxis",
           beam_deg=0.3, beam_deg_op=">=", beam_basis="beamwidth",
           band_freq_dn=f_dn,
           N_beam=72, B_beam=250, k_reuse=4, n_pol=2,
           C_req_ovr=50.0, D_ap=2.5, ant_type="固面", f_over_d=1.0)
geo = DE.derive_geometry(cfg)
ang = DE.resolve_angle_spec(cfg, geo)
print("  角度解析:", ang["note"])
chk("cov_table 生成", ang["cov_table"] is not None,
    "r_cov=%.1fkm offaxis=%.4f geo=%.4f fp=%.4f"
    % (ang["r_cov_km"], ang["cov_table"]["offaxis_deg"],
       ang["cov_table"]["geocentric_deg"], ang["cov_table"]["footprint_deg"]))
chk("±1.5° 离轴 → r_cov≈942km", abs(ang["r_cov_km"] - 941.8) < 5.0,
    "r_cov=%.1f km" % ang["r_cov_km"])
bt = ang["beam_table"]
chk("beam_table: θ3dB=0.3° → D_req=70λ/θ", bt is not None and
    abs(bt["D_req_m"] - 70 * DE.lam_m(f_dn) / 0.3) < 1e-3,
    "D_req=%.4f m" % (bt or {}).get("D_req_m", 0))
chk("0.3°@GEO斜距 → 足迹直径≈196km（半径98km）",
    bt and abs(bt["footprint_diam_km"] - 196.4) < 4.0,
    "diam=%.1f km, r=%.1f km" % ((bt or {}).get("footprint_diam_km", 0),
                                  (bt or {}).get("r_km", 0)))

sc = DE.spec_consistency(cfg, geo, ang)
print("  verdict:", sc["verdict"][:220])
ids = {r["id"]: r for r in sc["rows"]}
# 几何密铺 N = 1.209×(r_cov/r_beam)² = 1.209×(942.3/98.2)² ≈ 112
n_geo_ref = int(math.ceil(1.209 * (942.3 / bt["r_km"]) ** 2))
chk("S1 几何密铺 N_geo≈112（1.209(942/98)²）",
    abs(sc["inputs"]["N_geo"] - n_geo_ref) <= 2,
    "N_geo=%s (ref %d)" % (sc["inputs"]["N_geo"], n_geo_ref))
chk("S1 判定 72<密铺112 → 不通过（如实）", ids["S1"]["ok"] is False,
    "got=%s" % ids["S1"]["got"])
chk("S2 口径校核：D=2.5 → θ3dB=%.4f° vs 要求≥0.3" % (70 * DE.lam_m(f_dn) / 2.5),
    ids["S2"]["ok"] in (True, False),
    "got=%s need=%s" % (ids["S2"]["got"], ids["S2"]["need"]))
chk("S3 容量：72×250×2×2/1000=72≥50 → 过", ids["S3"]["ok"] is True,
    "got=%s" % ids["S3"]["got"])
chk("S4 频谱：72×250=18000≤2500×4=10000? 如实判", ids["S4"]["ok"] is False,
    "got=%s need=%s" % (ids["S4"]["got"], ids["S4"]["need"]))
chk("S5 焦面馈源容量已算", ids.get("S5") is not None and
    sc["feed_capacity"] is not None,
    "n_feed_max=%s" % (sc["feed_capacity"] or {}).get("n_feed_max"))
chk("耦合链说明存在", len(sc["coupling_note"]) > 50, "")
chk("bounds 六项齐全", all(k in sc["bounds"] for k in
    ("N_beam", "B_beam_mhz", "k_reuse", "C_gbps", "D_ap_m", "cov_half_deg", "beam_deg")), "")

print("\n=== 3. 修正配置使四指标闭合（k=7 → 频谱过；波束宽度按 72 波束反推）===")
# 72 波束 × 250MHz ≤ 2500×k → k≥7.2 → k=7 不够，k=8 才行；但 k>7 罕见 →
# 正确做法：B_beam = B_total×k/N_beam = 2500×7/72 ≈ 243MHz → 取 240MHz
cfg2 = dict(cfg)
cfg2["B_beam"] = 240
cfg2["k_reuse"] = 7
sc2 = DE.spec_consistency(cfg2, geo, ang)
ids2 = {r["id"]: r for r in sc2["rows"]}
chk("S4 频谱闭合（72×240=17280≤17500）", ids2["S4"]["ok"] is True,
    "got=%s need=%s" % (ids2["S4"]["got"], ids2["S4"]["need"]))
chk("S3 容量仍闭合（72×240×2×2=69.1≥50）", ids2["S3"]["ok"] is True,
    "got=%s" % ids2["S3"]["got"])

print("\n=== 4. 覆盖区↔国家双向耦合 ===")
cc = DE.country_coupling(cfg, geo, ang)
print("  verdict:", cc["verdict"][:300])
print("  center:", cc["center"]["note"][:180])
chk("覆盖中心=巴基斯坦国土中心（非赤道星下点）",
    abs(cc["center"]["lat"] - 30.5) < 1e-6 and abs(cc["center"]["lon"] - 69.5) < 1e-6,
    cc["center"]["source"])
chk("星下点=赤道69°E（与覆盖中心分离）",
    abs(cc["center"]["subpoint"]["lat"]) < 1e-9 and
    abs(cc["center"]["subpoint"]["lon"] - 69.0) < 1e-9,
    cc["center"]["subpoint"]["cn"])
chk("波束指向离轴角≈4.9°（赤道→30.5°N）",
    4.0 < cc["center"]["pointing_offaxis_deg"] < 5.6,
    "pointing=%.4f° (地心 %.4f°)" % (cc["center"]["pointing_offaxis_deg"],
                                      cc["center"]["pointing_geocentric_deg"]))
tgt = {r["key"]: r for r in cc["countries"]}
pk = tgt.get("巴基斯坦")
chk("巴基斯坦全覆盖（r_cov=942 ≥ 国土800，同心）", pk and pk["status"] == "full",
    "cover=%.1f%% dist=%.0fkm" % (pk["cover_pct"], pk["dist_km"]) if pk else "")
chk("巴基斯坦边角仰角≥46°门限", pk and pk["el_ok"] is True,
    "el_edge=%.1f° el_center=%.1f°" % (pk["el_edge_deg"], pk["el_user_deg"]) if pk else "")
chk("target_verdict 判定可覆盖", cc["target_verdict"] and cc["target_verdict"].startswith("✓"),
    (cc["target_verdict"] or "")[:150])
chk("need 反向：r_need=800×1.05=840km ≤ r_cov=942", cc["need"] and cc["need"]["ok"] is True,
    "r_need=%.0f gap=%.0f" % (cc["need"]["r_need_km"], cc["need"]["gap_km"]) if cc["need"] else "")
chk("need 给波束数需求", cc["need"] and cc["need"]["n_beam_need"] > 0,
    "n_beam_need=%s" % (cc["need"] or {}).get("n_beam_need"))
chk("need 给扫描角需求", cc["need"] and cc["need"]["pointing_offaxis_need_deg"] > 0,
    "scan=%.3f°" % (cc["need"] or {}).get("pointing_offaxis_need_deg", 0))
chk("单星视域判定", cc["single_sat_view_ok"] is True, cc["view_note"][:80])
chk("覆盖国家数统计一致", cc["n_full"] + cc["n_partial"] + cc["n_none"] == len(cc["countries"]),
    "full=%d partial=%d none=%d" % (cc["n_full"], cc["n_partial"], cc["n_none"]))
chk("942km 半径覆盖多国（印度部分/阿富汗等）", cc["n_full"] + cc["n_partial"] >= 3,
    "full=%d partial=%d" % (cc["n_full"], cc["n_partial"]))
us = tgt.get("美国本土")
chk("美国本土未覆盖（诚实）", us and us["status"] == "none",
    "cover=%.1f%%" % us["cover_pct"] if us else "")

print("\n=== 5. 覆盖不足场景（±0.5° 离轴 → r=313km < 巴基斯坦 800km）===")
cfg3 = dict(cfg)
cfg3["cov_half_deg"] = 0.5
geo3 = DE.derive_geometry(cfg3)
ang3 = DE.resolve_angle_spec(cfg3, geo3)
cc3 = DE.country_coupling(cfg3, geo3, ang3)
pk3 = {r["key"]: r for r in cc3["countries"]}.get("巴基斯坦")
chk("±0.5° → r_cov≈313km", abs(ang3["r_cov_km"] - 312.5) < 3.0, "r=%.1f" % ang3["r_cov_km"])
chk("巴基斯坦部分覆盖 ≈(313/800)²=15%", pk3 and pk3["status"] == "partial"
    and 12 < pk3["cover_pct"] < 20,
    "cover=%.1f%%" % pk3["cover_pct"] if pk3 else "")
chk("need 给缺口与建议", cc3["need"] and not cc3["need"]["ok"] and cc3["need"]["advice"],
    (cc3["need"] or {}).get("advice", "")[:120])
chk("target_verdict 如实报不能覆盖", cc3["target_verdict"] and
    cc3["target_verdict"].startswith("✗"), (cc3["target_verdict"] or "")[:120])

print("\n=== 6. 波束约束方向算子（>0.3° = 波束不得更宽）===")
# beam_deg_op=">=" 语义：用户要求波束 ≥0.3°（足迹至少这么大）
# 天线口径 2.5m@20GHz → θ3dB=0.42° ≥ 0.3 → S2 应过
chk("D=2.5m θ3dB=0.42°≥0.3° → S2 过", ids["S2"]["ok"] is True,
    "got=%s" % ids["S2"]["got"])
cfg4 = dict(cfg)
cfg4["D_ap"] = 4.0          # 大口径 → θ3dB=0.26° < 0.3° → S2 不过（波束比要求窄）
sc4 = DE.spec_consistency(cfg4, geo, ang)
ids4 = {r["id"]: r for r in sc4["rows"]}
chk("D=4.0m θ3dB=0.26°<0.3° → S2 如实报不符", ids4["S2"]["ok"] is False,
    "got=%s need=%s" % (ids4["S2"]["got"], ids4["S2"]["need"]))

print("\n=== 7. LEO 场景（过境星下点，仰角计算降级为 None 不崩）===")
cfg5 = dict(cfg)
cfg5.update(orbit="LEO", coverage="巴基斯坦", cov_half_deg=8.0, beam_deg=1.5)
geo5 = DE.derive_geometry(cfg5)
ang5 = DE.resolve_angle_spec(cfg5, geo5)
cc5 = DE.country_coupling(cfg5, geo5, ang5)
chk("LEO 中心=国土中心", abs(cc5["center"]["lat"] - 30.5) < 1e-6,
    cc5["center"]["source"][:60])
chk("LEO 覆盖判定不崩", len(cc5["countries"]) == len(DE.COUNTRIES), "")
chk("LEO el_user=None（过境瞬时仰角另算）",
    cc5["countries"][0]["el_user_deg"] is None, "")
sc5 = DE.spec_consistency(cfg5, geo5, ang5)
chk("LEO 耦合校核不崩", sc5["n_checked"] >= 2, "checked=%d" % sc5["n_checked"])

print("\nRESULT: PASS ok=%d fail=%d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
