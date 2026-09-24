# -*- coding: utf-8 -*-
"""#83 正面验证：D 级救援在可救援场景下能否 ok=True（把不可行变可行）。

场景C：GEO Ka 固面大口径 + 强制最小平台 → c-17 承载超限（可救援：换大平台承载）
场景D：GEO Ka 固面 + 极低复用色 k 导致 c-13 频谱超限（可救援：提 k + 压 B_beam）
"""
import sys
import json
import io
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import design_engine as DE

KG = json.load(open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json", encoding="utf-8"))
NPASS, NFAIL = 0, 0


def ck(cond, msg):
    global NPASS, NFAIL
    if cond:
        NPASS += 1
        print("  PASS %s" % msg)
    else:
        NFAIL += 1
        print("  FAIL %s" % msg)


def probe(name, cfg):
    print("[%s]" % name)
    R = DE.design_all(cfg, KG, skip_compare=True)
    ev = DE.evaluate_scheme(R)
    s = R["res"]["summary"]
    plat = (R.get("platform") or [None, {}])[1]
    print("  design_all: grade=%s fail=%s m_pay=%.0fkg M_budget=%.0fkg plat=%s" % (
        ev["grade"], s.get("fail"), R["totals"].get("m_pay", 0),
        R["params"].get("M_budget", 0), plat.get("cn")))
    if ev["feasible"]:
        print("  [!] 未触发 D 级，无法验证救援（需调整场景）")
        return None
    ap = DE._build_applyable(R, cfg, dict(cfg), KG)
    print("  救援: ok=%s ladder=%s grade=%s" % (ap.get("ok"), ap.get("ladder"), ap.get("grade")))
    for it in ap.get("items", []):
        print("    - %s: %s → %s" % (it["label"], it["cur"], it["v"]))
    vf = ap.get("verify") or {}
    print("  verify: grade=%s pass_hard=%s fail=%s C_sys=%s" % (
        vf.get("grade"), vf.get("pass_hard"), vf.get("fail"), vf.get("C_sys")))
    return ap


# 场景C：固面大口径 + 强制最小 GEO 平台 → 承载超限
apC = probe("场景C 承载超限（换大平台可救援）", dict(
    service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
    band="Ka", ant_type="固面", D_ap=4.5, mode="数字透明",
    platform_pref="GEO-MID42", cov_r_km=600, el_deg=15,
    A_avail=99.5, M_target=3, life_yr=15))
if apC is not None:
    ck(apC.get("ok") is True, "场景C 救援后闭合（ok=True）")

# 场景D：固面 + 极低复用色 → 频谱超限
apD = probe("场景D 频谱超限（提k可救援）", dict(
    service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
    band="Ka", ant_type="固面", D_ap=2.5, mode="数字透明",
    N_beam=120, B_beam=250, k_reuse=1,
    cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15))
if apD is not None:
    ck(apD.get("ok") is True, "场景D 救援后闭合（ok=True）")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
