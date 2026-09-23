# -*- coding: utf-8 -*-
"""v5 改造快速验证：体制推断/多覆盖区/星座/D_ap 锁定。"""
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_engine as DE
from design_data import DEFAULT_CFG, SCENARIOS

with open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json",
          encoding="utf-8") as f:
    KG = json.load(f)

ok = fail = 0


def chk(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK] %s %s" % (name, detail))
    else:
        fail += 1
        print("  [FAIL] %s %s" % (name, detail))


print("== T1 体制第一性原理推断 ==")
cases = [
    # 高通量宽带 C=40Gbps → VHTS 大容量多波束（KA-SAT/Konnect 飞行继承；固面反射面体制族）
    (dict(service="高通量宽带", orbit="GEO", coverage="中国全境"), "Ka", "大容量多波束", "数字透明", ""),
    (dict(service="广播电视", orbit="GEO", coverage="中国全境"), "Ku", "固面", "透明", ""),
    # L/S 伞状窄带移动 → 模拟透明（天通/Inmarsat-4 传承）
    (dict(service="移动通信", orbit="GEO", coverage="中国全境"), "L", "伞状", "透明", ""),
    (dict(service="高通量宽带", orbit="LEO", coverage="全球"), "Ka", "相控阵", "再生", "激光"),
    (dict(service="手机直连D2D", orbit="LEO", coverage="全球"), "S", "相控阵", "再生", "激光"),
    (dict(service="物联网", orbit="SSO", coverage="全球"), "S", "相控阵", "数字透明", "激光"),
    (dict(service="中继数传", orbit="MEO", coverage="全球"), "Ka", "相控阵", "再生", "激光"),
    # 军用抗干扰：L 频段伞状（nulling 空间自由度）+ 再生（解调译码后跳频/零陷/路由规避）
    (dict(service="军用抗干扰", orbit="HEO", coverage="极区"), "L", "伞状", "再生", ""),
]
for c, b_exp, a_exp, m_exp, isl_exp in cases:
    arch = DE.infer_architecture(c)
    tag = "%s/%s/%s" % (c["service"], c["orbit"], c["coverage"])
    chk(tag, arch["band"] == b_exp and arch["ant_type"] == a_exp
        and arch["mode"] == m_exp and arch["isl_type"] == isl_exp,
        "→ band=%s ant=%s mode=%s isl=%s（期望 %s/%s/%s/%s）"
        % (arch["band"], arch["ant_type"], arch["mode"], arch["isl_type"] or "无",
           b_exp, a_exp, m_exp, isl_exp or "无"))

print("== T2 GEO+Ka 相控阵功率墙 → 建议值强制改反射面体制 ==")
cfg = dict(DEFAULT_CFG)
cfg.update(service="高通量宽带", orbit="GEO", coverage="中国全境", band="Ka",
           ant_type="相控阵", array_subtype="数字模拟混合", N_beam=64)
s = DE.suggest_params(cfg, KG)
_at = s["values"].get("ant_type")
# 功率墙逃逸目标：反射面体制族（固面 / VHTS 大容量多波束），只要不再是相控阵即可
chk("功率墙强制（反射面体制族）", _at in ("固面", "大容量多波束"),
    "ant_type→%s；note=%s" % (_at, (s["notes"].get("ant_type") or "")[:80]))
chk("用户已选相控阵但物理不可行 → 仍强制", "ant_type" in (s.get("arch") or {}).get("changed", {}), "")

print("== T3 多覆盖区（巴基斯坦+沙特+印尼）按最差区闭合 ==")
cfg = dict(DEFAULT_CFG)
cfg.update(service="高通量宽带", orbit="GEO", band="Ka", ant_type="固面",
           coverage="巴基斯坦", coverage_list="巴基斯坦,沙特阿拉伯,印度尼西亚", mode="数字透明")
R = DE.design_all(cfg, KG, skip_compare=True)
mc = R.get("multi_coverage")
chk("multi_coverage 生成", mc is not None and len(mc["regions"]) == 3,
    "regions=%s" % ([r["key"] for r in mc["regions"]] if mc else None))
if mc:
    w = mc["worst"]
    chk("最差区=印尼（雨衰最强+仰角45）", w["key"] == "印度尼西亚",
        "worst=%s el=%s A_dyn=%s" % (w["key"], w["el_min"], w["A_dyn"]))
    chk("链路按最差区仰角闭合", R["geo"]["el_deg"] == w["el_min"],
        "geo.el=%s" % R["geo"]["el_deg"])
    chk("波束数=Σ各区密铺", R["params"]["N_beam"] == mc["n_beam_total"],
        "N_beam=%s Σ=%s" % (R["params"]["N_beam"], mc["n_beam_total"]))
chk("flows 携带 multi_coverage", bool((R.get("flows") or {}).get("multi_coverage")), "")

print("== T4 星座建议 + 组网指标（LEO 全球宽带）==")
cfg = dict(DEFAULT_CFG)
cfg.update(service="高通量宽带", orbit="LEO", coverage="全球", band="Ka",
           ant_type="相控阵", array_subtype="数字模拟混合", mode="再生",
           isl_type="激光", N_el=1024, θ_scan=45, N_beam=16, B_beam=250, B_carrier=62)
s = DE.suggest_params(cfg, KG)
cs = s.get("constellation")
chk("constellation 建议生成", cs is not None,
    ("Walker=%s/%s/%s incl=%s" % (cs["N_sat"], cs["N_plane"], cs["phase_f"], cs["incl_deg"])) if cs else "")
chk("建议 N_sat 已入 values", s["values"].get("N_sat") == (cs or {}).get("N_sat"),
    "N_sat=%s" % s["values"].get("N_sat"))
# 带星座的 design_all
cfg2 = dict(cfg)
cfg2.update(N_sat=cs["N_sat"], N_plane=cs["N_plane"], incl_deg=cs["incl_deg"], phase_f=cs["phase_f"])
R2 = DE.design_all(cfg2, KG, skip_compare=True)
cm = R2.get("constellation")
chk("constellation_metrics 生成", cm is not None, "")
if cm:
    chk("连续覆盖（mult_min≥1）", cm["mult_min"] >= 1,
        "mult_min=%s mult_mean=%s" % (cm["mult_min"], cm["mult_mean"]))
    chk("系统容量=单星×星数", cm["c_sys_total"] is not None
        and abs(cm["c_sys_total"] - cm["N_sat"] * R2["res"]["summary"]["C_sys"]) < 0.5,
        "C_total=%sGbps（单星 %s × %s 星）" % (cm["c_sys_total"], R2["res"]["summary"]["C_sys"], cm["N_sat"]))
    chk("星间距离物理合理（同轨<4000km@550km）", 0 < cm["d_intra_km"] < 4000,
        "d_intra=%skm d_cross=%skm hop=%sms" % (cm["d_intra_km"], cm["d_cross_km"], cm["hop_ms"]))
    chk("flows 携带 constellation", bool((R2.get("flows") or {}).get("constellation")), "")

print("== T5 D_ap 锁定传导（force_custom_ant：5m 就按 5m 算）==")
cfg = dict(SCENARIOS["geo_ka_hts"]["cfg"])
cfg.update(D_ap=5.0, force_custom_ant=True, ant_type="固面")
R5 = DE.design_all(cfg, KG, skip_compare=True)
ant = R5["res"]["antenna"]
chk("口径=5m 传导", abs(ant["D_m"] - 5.0) < 1e-6, "D_m=%s" % ant.get("D_m"))
G5 = ant["G_ant"]
# 2.5m 场景对照
cfg25 = dict(SCENARIOS["geo_ka_hts"]["cfg"]); cfg25.update(D_ap=2.5, force_custom_ant=True)
R25 = DE.design_all(cfg25, KG, skip_compare=True)
G25 = R25["res"]["antenna"]["G_ant"]
chk("增益按口径增大（5m>2.5m 约 +6dB）", 5.5 < (G5 - G25) < 6.5,
    "G(5m)=%s G(2.5m)=%s Δ=%sdB" % (round(G5, 2), round(G25, 2), round(G5 - G25, 2)))

print("== T6 货架路径 D_ap 替代留痕 ==")
cfg = dict(SCENARIOS["geo_ka_hts"]["cfg"])
cfg.update(D_ap=5.0)          # 不锁定 → 货架替代但须留痕
R6 = DE.design_all(cfg, KG, skip_compare=True)
chk("货架替代留痕 D_ap_override", bool(R6["params"].get("D_ap_override")),
    str(R6["params"].get("D_ap_override"))[:100])

print("== T7 8 场景回归（引擎改动不破坏既有场景）==")
for k, sc in SCENARIOS.items():
    try:
        Rr = DE.design_all(dict(sc["cfg"]), KG, skip_compare=True)
        ev = Rr["eval"]
        chk(k, ev["grade"] in ("A", "B", "C", "D") and Rr["res"]["summary"].get("judge_total"),
            "grade=%s judge=%s/%s" % (ev["grade"], Rr["res"]["summary"].get("judge_pass"),
                                      Rr["res"]["summary"].get("judge_total")))
    except Exception as ex:
        chk(k, False, "EXC %r" % ex)

print("== T8 suggest_params 8 场景 + 闭环 ==")
for k, sc in SCENARIOS.items():
    c = dict(DEFAULT_CFG); c.update(sc["cfg"])
    try:
        cl = DE.suggest_closed_loop(c, KG, max_iter=3)
        g = (cl.get("closed") or {}).get("grade")
        chk(k, g in ("A", "B", "C", "D"), "grade=%s iters=%s" % (g, (cl.get("closed") or {}).get("iters")))
    except Exception as ex:
        chk(k, False, "EXC %r" % ex)

print()
print("RESULT: OK=%d FAIL=%d" % (ok, fail))
sys.exit(1 if fail else 0)
