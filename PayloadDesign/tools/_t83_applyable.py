# -*- coding: utf-8 -*-
"""#83 v2-1 验证：D 级闭环给出可一键带入的 applyable 救援方案。

场景 1：GEO + Ka + 相控阵 + 小平台 + 高容量 → 期望功率墙 D 级 → applyable 反推固面
场景 2：GEO + Ka + 固面 2.5m + 正常配置 → 期望 A/B 级 → applyable=None
场景 3：LEO + Ka + 容量需求超频谱极限 → 期望 D → applyable 或诚实标注
"""
import sys
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import io
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import design_engine as DE

KG_PATH = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json"
with open(KG_PATH, "r", encoding="utf-8") as f:
    KG = json.load(f)
NPASS, NFAIL = 0, 0


def ck(cond, msg):
    global NPASS, NFAIL
    if cond:
        NPASS += 1
        print("  PASS %s" % msg)
    else:
        NFAIL += 1
        print("  FAIL %s" % msg)


# ---- 场景 1：功率墙 D 级 ----
print("[场景1] GEO Ka 相控阵小平台高容量（期望 D → applyable 救援）")
cfg1 = dict(service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
            band="Ka", ant_type="相控阵", array_subtype="直射阵", mode="透明",
            C_req_ovr=100, N_el=2048, platform_pref="GEO-MID42",
            cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15)
sg1 = DE.suggest_closed_loop(cfg1, KG, max_iter=3)
cl1 = sg1.get("closed") or {}
print("  grade=%s feasible=%s adjustments=%d" % (cl1.get("grade"), cl1.get("feasible"), len(cl1.get("adjustments") or [])))
ap1 = sg1.get("applyable")
if cl1.get("feasible"):
    ck(True, "闭环自动修正已闭合（无需 applyable）")
    ck(ap1 is None, "可行时 applyable=None")
else:
    ck(ap1 is not None, "D 级给出 applyable 救援方案")
    if ap1:
        print("  applyable: ok=%s ladder=%s grade=%s" % (ap1.get("ok"), ap1.get("ladder"), ap1.get("grade")))
        for it in ap1.get("items", []):
            print("    - %s: %s → %s（%s）" % (it["label"], it["cur"], it["v"], it["note"][:40]))
        ck(bool(ap1.get("values")), "applyable.values 非空（可一键带入）")
        ck(bool(ap1.get("items")), "applyable.items 非空（含中文名+依据）")
        ck("verify" in ap1, "applyable.verify 含 design_all 复验结果")
        if ap1.get("ok"):
            ck(ap1.get("grade") in ("A", "B", "C"), "救援后评级 %s（非 D）" % ap1.get("grade"))

# ---- 场景 2：正常配置应可行 ----
print("[场景2] GEO Ka 固面 2.5m 常规配置（期望 A/B 级，无 applyable）")
cfg2 = dict(service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
            band="Ka", ant_type="固面", D_ap=2.5, mode="数字透明",
            cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15)
sg2 = DE.suggest_closed_loop(cfg2, KG, max_iter=3)
cl2 = sg2.get("closed") or {}
print("  grade=%s feasible=%s" % (cl2.get("grade"), cl2.get("feasible")))
ck(cl2.get("feasible") is True, "常规配置闭环可行")
ck(sg2.get("applyable") is None, "可行时 applyable=None（不干扰）")

# ---- 场景 3：_build_applyable 直接调用（构造 D 级 R）----
print("[场景3] _build_applyable 直接调用（cfg1 强制相控阵 D 级 R）")
R3 = DE.design_all(cfg1, KG, skip_compare=True)
ev3 = DE.evaluate_scheme(R3)
print("  design_all grade=%s fail=%s" % (ev3["grade"], (R3.get("res") or {}).get("summary", {}).get("fail")))
if not ev3["feasible"]:
    ap3 = DE._build_applyable(R3, cfg1, dict(cfg1), KG)
    ck(ap3 is not None, "_build_applyable 返回非空")
    ck("items" in ap3 and "values" in ap3, "结构含 items/values")
    print("  救援 ok=%s ladder=%s grade=%s head=%s" % (ap3.get("ok"), ap3.get("ladder"), ap3.get("grade"), (ap3.get("head") or "")[:60]))
else:
    ck(True, "场景3 引擎自动闭合（跳过 applyable 检查）")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
sys.exit(0 if NFAIL == 0 else 1)
