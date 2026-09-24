# -*- coding: utf-8 -*-
"""v4.1 验证：①偏置反射面按天线体制门控（仅反射面族）②耦合冲突联立求解修复
③轨道仿真覆盖区=波束照射足迹（API 集成）④一维方向图升级数据源（反射面口径积分）。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_engine as DE                                   # noqa: E402
import design_data as DD                                     # noqa: E402
import orbit_engine as OE                                    # noqa: E402
import design_app as DA                                      # noqa: E402

with open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json",
          encoding="utf-8") as f:
    KG = json.load(f)

ok = fail = 0


def chk(name, cond, info=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS %s %s" % (name, info))
    else:
        fail += 1
        print("  FAIL %s %s" % (name, info))


BASE = dict(DD.DEFAULT_CFG)
BASE.update(name="v41", service="高通量宽带", orbit="GEO", coverage="巴基斯坦", band="Ka",
            mode="数字透明", ant_type="固面", geo_lon=69.0, el_deg=46.0,
            cov_half_deg=1.5, angle_basis="offaxis", beam_deg=0.3, beam_deg_op=">=",
            beam_basis="beamwidth", N_beam=72, B_beam=250, k_reuse=4, n_pol=2,
            C_req_ovr=50.0, D_ap=2.5, refl_D_r=2.5, f_over_d=1.0, h_over_d=0.55)

print("=== 1. 偏置反射面按天线体制门控（用户要求①）===")
for ant, want_skip in (("固面", False), ("伞状", False), ("大容量多波束", False),
                       ("混合多波束", False), ("相控阵", True)):
    c = dict(BASE)
    c["ant_type"] = ant
    if ant == "相控阵":
        c.update(array_subtype="数字模拟混合", N_el=4096)
    rf = DE.reflector_design(c, {}, None, None)
    got_skip = bool(rf.get("skipped"))
    chk("ant_type=%s → %s" % (ant, "skipped" if want_skip else "输出"),
        got_skip == want_skip,
        ("reason=%s" % str(rf.get("reason"))[:60]) if want_skip
        else ("ok=%s G=%.1fdBi" % (rf.get("ok"),
                                    (rf.get("perf") or {}).get("G_dbi", 0))))
rf_arr = DE.reflector_design(dict(BASE, ant_type="相控阵"), {}, None, None)
chk("相控阵门控返回 ok=False+skipped=True（前端/报告据此不渲染）",
    rf_arr.get("ok") is False and rf_arr.get("skipped") is True, "")
R_arr = DE.design_all(dict(BASE, ant_type="相控阵", array_subtype="数字模拟混合",
                           N_el=4096), KG, skip_compare=True)
chk("design_all 相控阵方案 reflector 被门控", R_arr["reflector"].get("skipped") is True, "")
import report_gen as RG                                       # noqa: E402
html_arr = RG.build_report(R_arr, rasterize=False)
chk("相控阵报告不含偏置反射面节", "偏置反射面天线设计" not in html_arr, "")
html_fix = RG.build_report(DE.design_all(BASE, KG, skip_compare=True), rasterize=False)
chk("固面报告含偏置反射面节", "偏置反射面天线设计" in html_fix, "")
chk("报告已无几何口径示意图（用户要求）", "svg_reflector_geom" not in html_fix
    and "口径投影 D_r" not in html_fix, "")
chk("报告反射面远场方向图保留（用户认可 html 方向图）",
    "口径积分远场方向图" in html_fix, "")

print("\n=== 2. 四指标耦合冲突 → 联立求解修复（用户要求②）===")
R = DE.design_all(BASE, KG, skip_compare=True)
sc = R["spec_check"]
rep = sc["repair"]
fails0 = [r["id"] for r in sc["rows"] if r["ok"] is False]
chk("用户四指标存在冲突（S1/S4）", set(fails0) == {"S1", "S4"},
    "冲突=%s" % fails0)
js = rep["joint_solution"]
chk("联立解 N*=113（几何密铺）", js["N_beam"] == 113, "N*=%s" % js["N_beam"])
chk("联立解 B*=111MHz（容量下限 50000/(113×2×2)）", js["B_beam"] == 111,
    "B*=%s" % js["B_beam"])
chk("联立解 k*=6≤7（频谱闭合 113×111=12543≤15000）", js["k_reuse"] == 6,
    "k*=%s" % js["k_reuse"])
chk("联立解 f_over_d 微调 1.014（焦面容量 110→113）",
    abs(js["f_over_d"] - 1.014) < 0.01, "F/D*=%s" % js["f_over_d"])
chk("修复后重跑校核全闭合（verified.ok）", rep["verified"]["ok"] is True,
    rep["verified"]["note"])
chk("不可解项=0", rep["n_unresolvable"] == 0, "")
chk("cfg_delta 四项", set(rep["cfg_delta"].keys()) == {"N_beam", "B_beam", "k_reuse",
                                                       "f_over_d"},
    str(rep["cfg_delta"]))
# 修复值回填后 design_all 应无 S1/S4 冲突
c_fixed = dict(BASE)
c_fixed.update(rep["cfg_delta"])
R_fix = DE.design_all(c_fixed, KG, skip_compare=True)
fails1 = [r["id"] for r in R_fix["spec_check"]["rows"] if r["ok"] is False]
chk("回填联立解后 design_all 耦合校核全过", len(fails1) == 0,
    "剩余冲突=%s" % (fails1 or "无"))
chk("回填后容量仍≥50G", R_fix["res"]["summary"]["C_sys"] >= 50.0,
    "C_sys=%.1f" % R_fix["res"]["summary"]["C_sys"])
# 不可闭合场景：容量翻倍到 200G（Ka 2500MHz k≤7 上限 140G → 须换频段，如实报）
c_bad = dict(BASE)
c_bad["C_req_ovr"] = 200.0
R_bad = DE.design_all(c_bad, KG, skip_compare=True)
rep_bad = R_bad["spec_check"]["repair"]
chk("不可闭合场景如实报（须换 Q/V，不假装达标）", rep_bad["n_unresolvable"] >= 1
    and any("Q/V" in s.get("reason", "") for s in rep_bad["steps"]),
    [s.get("reason", "")[:50] for s in rep_bad["steps"] if s.get("unresolvable")][:1])

print("\n=== 3. 轨道仿真覆盖区=波束照射足迹（用户要求③④）===")
api = DA.Api()
# GEO 定点 69E + 波束半锥角 0.15°（θ3dB=0.3°）→ 足迹应≈187km 直径，中心=指向点
orb = api.orbit(dict(orbit_key="GEO", h_km=35786, incl_deg=0.05, geo_lon=69.0,
                     targets=[dict(name="巴基斯坦", lat=30.5, lon=69.5)],
                     el_min_deg=10.0, t_offset_min=0,
                     beam_half_cone_deg=0.15, beam_mode="target",
                     beam_target=dict(lat=30.5, lon=69.5)))
chk("orbit API ok", orb.get("ok") is True, str(orb.get("error"))[:80])
snap = orb.get("snapshot") or {}
bf = snap.get("beam_footprint") or {}
chk("快照含波束足迹", bf.get("ok") is True, "n_points=%s" % bf.get("n_points"))
chk("足迹直径：电扫 5.04° 斜距增大 → ≈216km（天底 187km 的 1/cos 效应，真实几何）",
    200 < bf.get("diameter_km", 0) < 235,
    "D=%.0fkm（σ_mean=%.2f°；天底同锥角为 187km）"
    % (bf.get("diameter_km", 0), bf.get("sigma_deg_mean", 0)))
chk("足迹中心=指向点(30.5N,69.5E)",
    abs(bf.get("center_lat", 0) - 30.5) < 0.6
    and abs(bf.get("center_lon", 0) - 69.5) < 0.6,
    "center=(%.2f,%.2f)" % (bf.get("center_lat", 0), bf.get("center_lon", 0)))
chk("指向离轴角≈5.04°（电扫，与耦合校核交叉一致）",
    4.5 < (bf.get("boresight") or {}).get("off_nadir_deg", 0) < 5.6,
    "%.2f°" % (bf.get("boresight") or {}).get("off_nadir_deg", 0))
chk("足迹≪覆盖帽（照射区 vs 可见区，物理量不同）",
    bf.get("sigma_deg_mean", 99) < snap.get("sigma_deg", 0),
    "足迹σ=%.2f° vs 覆盖帽σ=%.1f°" % (bf.get("sigma_deg_mean", 0),
                                        snap.get("sigma_deg", 0)))
chk("足迹多边形点数≥36（可绘制）", bf.get("n_points", 0) >= 36,
    "n=%s miss=%s" % (bf.get("n_points"), bf.get("n_miss")))
# 不给波束参数 → 向后兼容（无足迹，覆盖帽仍在）
orb2 = api.orbit(dict(orbit_key="GEO", h_km=35786, geo_lon=69.0, el_min_deg=10.0))
chk("未给波束参数→向后兼容（无 footprint 键）",
    "beam_footprint" not in (orb2.get("snapshot") or {}), "")
# LEO 天底照射
orb3 = api.orbit(dict(orbit_key="LEO", h_km=550, incl_deg=53.0, el_min_deg=10.0,
                      t_offset_min=0, beam_half_cone_deg=0.5, beam_mode="nadir"))
bf3 = (orb3.get("snapshot") or {}).get("beam_footprint") or {}
chk("LEO 天底足迹（0.5°半锥→D≈11km）", bf3.get("ok") and 8 < bf3.get("diameter_km", 0) < 14,
    "D=%.0fkm mode=%s" % (bf3.get("diameter_km", 0),
                           (bf3.get("boresight") or {}).get("mode")))

print("\n=== 4. 前端配置结构（用户要求②：覆盖角=方案选项，四指标=性能约束）===")
src = DA.FRONT_HTML
chk("性能约束面板存在（四指标）", "性能约束（四指标：覆盖区域 × 波束大小 × 波束数量 × 容量" in src, "")
chk("覆盖角度在需求与轨道面板（方案选项）",
    src.find("覆盖角度 ±(°)（方案选项）") < src.find("性能约束（四指标"), "")
chk("一键修复按钮存在", "btnApplyRepair" in src and "一键修复（回填联立解并重算）" in src, "")
chk("bindRepairBtn 回填+重算", "function bindRepairBtn" in src and "runDesign(false)" in src, "")
chk("反射面配置区容器（动态显隐）", 'id="reflCfgBox"' in src
    and "function updateReflCfgVisibility" in src, "")
chk("门控数组与引擎一致", 'REFL_ANT_TYPES=["固面","伞状","大容量多波束","混合多波束","反射面"]' in src, "")
chk("总览反射面面板同门控", "isReflAnt" in src, "")
chk("总览不再放反射面口径图", src.count("reflPatternSVG(RF.pattern)") == 1
    and "v4.1：按用户要求不在总览放偏置反射面口径图" in src,
    "reflPatternSVG 仅④天线页使用")
chk("④天线页附口径积分方向图", "偏置反射面口径积分远场方向图" in src, "")
chk("轨道页波束照射区图例", "红色实线=波束照射区（天线波束锥∩地球，即实际覆盖区）" in src, "")
chk("轨道页照射区科学口径说明", "照射区科学口径" in src and "射线-球面" in src, "")
chk("轨道 payload 传波束半锥角", "beam_half_cone_deg" in src and "beam_target" in src, "")

print("\nRESULT: PASS ok=%d fail=%d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
