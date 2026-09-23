# -*- coding: utf-8 -*-
"""功能验证：新增货架产品是否被选型引擎真实选中（Q/V 方案、Ka 宽带、X 数传、激光、pick_shelf）。"""
import sys

sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_data as DD
import design_engine as DE
import design_app as DA

KG = DA.KG
fails = []


def ck(name, cond, msg=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + msg if msg else ""))
    if not cond:
        fails.append(name)


# 1. pick_shelf：Q/V 链路各单机不再落定制
#    注意 pick_shelf 语义 = level 优先、质量次之；bands="*" 的 EPC-01(level4) 会赢过
#    Q/V 专用功放(level2)。引擎真实功放选型走专用循环（排除 MPA-8X8/EPC-01，按 P 匹配），
#    故此处用排除语义验证。
for cat, want in [("LNA", "LNA-QV-01"), ("变频", "DCONV-01"), ("多工器", "IMUX-01")]:
    prod = DE.pick_shelf(cat, "Q/V")
    ck("pick_shelf(%s,Q/V)=%s" % (cat, want), prod and prod["id"] == want,
       prod["id"] if prod else "None")
prod = DE.pick_shelf("功放", "Q/V", exclude=("MPA-8X8", "EPC-01"))
ck("pick_shelf(功放,Q/V,排除EPC/MPA) 为 Q/V 专用功放",
   prod and prod["id"] in ("TWTA-QV-40", "SSPA-QV-20"), prod["id"] if prod else "None")
prod = DE.pick_shelf("功放", "X", exclude=("MPA-8X8", "EPC-01"))
ck("pick_shelf(功放,X,排除EPC/MPA)=TWTA-X-40", prod and prod["id"] == "TWTA-X-40",
   prod["id"] if prod else "None")

# 2. X 数传天线
ck("pick_shelf(天线,X)=ANT-REFL-X", DE.pick_shelf("天线", "X")["id"] == "ANT-REFL-X")
# 测控应答机在引擎中为 force_id=TTC-TRP-01；S 双频转发器在库可查
ck("TTC-TRP-S-INT/TTC-DB-INT 在库",
   "TTC-TRP-S-INT" in DD.SHELF_BY_ID and "TTC-DB-INT" in DD.SHELF_BY_ID)
ck("pick_shelf(星务,*) 仍为 OBC-PAY-01(level4 优先)",
   DE.pick_shelf("星务", "*")["id"] == "OBC-PAY-01", DE.pick_shelf("星务", "*")["id"])

# 3. Ka 宽带相控阵方案：银河 Ka8 应进入五维候选（level4 + 小质量加分）
cfg = dict(DD.DEFAULT_CFG, name="Ka宽带银河候选", service="高通量宽带", orbit="LEO",
           coverage="区域", band="Ka", feeder_band="Q/V", mode="数字透明",
           ant_type="相控阵", Mode="相控扫描", N_beam=8, B_beam=500,
           k_reuse=4, n_pol=2, D_ap="", N_el=512, θ_scan="", η_ill="",
           C_req_ovr="", M_target="", platform_pref="自动", amp_type="", P_out="",
           isl_type="", isl_r_gbps="", life_yr="", EIRP_gs="", el_deg="", A_avail="",
           B_carrier="", GT_term="", EIRP_term="", cov_r_km="", beam_r_km="")
r = DE.design_all(cfg, KG, skip_compare=True)
cand_ids = [c[1]["id"] for c in r["ant_cands"]]
ck("Ka 五维候选含 ANT-AESA-KA8-GAL", "ANT-AESA-KA8-GAL" in cand_ids, str(cand_ids[:6]))
eq_ids = set(row["id"] for row in r["equipment"])
ck("Q/V 馈电天线入选（ANT-REFL-QV-GAL）", "ANT-REFL-QV-GAL" in eq_ids, str(sorted(eq_ids))[:400])
ck("方案可算 judge>=15", r["res"]["summary"]["judge_total"] >= 15,
   str(r["res"]["summary"]["judge_total"]))
print("  推荐天线: %s (%s) score=%.2f" % (r["ant_rec"][1]["id"], r["ant_rec"][1]["cn"], r["ant_rec"][0]))
s = r["res"]["summary"]
print("  EIRP=%.1f GT=%.1f M_up=%.2f M_dn=%.2f fail=%s" % (s["EIRP"], s["GT"], s["M_up"], s["M_dn"], s["fail"]))

# 4. 激光：LCT 速率映射仍正确（现有逻辑 force_id），新产品在 /api/meta 货架中可见
meta_shelf_ids = set(u[0] for u in DD.SHELF_UNITS)
ck("激光新 3 款在库", {"LCT-GEO-INT", "LCT-CUBEL-INT", "LCT-DTE-INT"} <= meta_shelf_ids)

# 5. design_app meta 端点数据量
api = DA._api_singleton
m = api.meta()
ck("meta shelf=86", len(m["shelf"]) == 86, str(len(m["shelf"])))
ck("meta band_keys 含 Q/V", "Q/V" in m["band_keys"], str(m["band_keys"]))

# 6. GEO Ka 固面场景不受影响（回归：ANT-REFL-KA 仍被推荐）
cfg2 = dict(cfg, name="GEO巴基斯坦回归", orbit="GEO", coverage="巴基斯坦", ant_type="固面",
            Mode="区域赋形", N_beam="", B_beam="", N_el="", platform_pref="")
sg = DE.suggest_params(cfg2, KG)
cfg2s = dict(cfg2, **{k: v for k, v in sg["auto"].items()})
r2 = DE.design_all(cfg2s, KG, skip_compare=True)
ck("GEO 巴基斯坦仍推荐 ANT-REFL-KA", r2["ant_rec"][1]["id"] == "ANT-REFL-KA",
   r2["ant_rec"][1]["id"])
ck("GEO 巴基斯坦方案闭合", not r2["res"]["summary"]["fail"], str(r2["res"]["summary"]["fail"]))

print()
if fails:
    print("FUNC FAIL: %d -> %s" % (len(fails), fails))
    sys.exit(1)
print("FUNC ALL PASS")
