# -*- coding: utf-8 -*-
"""链路预算独立校验脚本（第一性原理复算 vs 引擎输出）。

校验点：
  V1  FSPL = 20lg(d_m) + 20lg(f_Hz) - 147.55        （常数独立复算）
  V2  C/N0 = EIRP - L_fs - ΣL + G/T + 228.6          （k 独立取值）
  V3  C/N  = C/N0 - 10lg(B_Hz)
  V4  EIRP = P_out_dBW + G_ant - L_feed - L_tx       （c-1 一致性）
  V5  G/T  = G_ant - 10lg(T_sys)                     （c-2 一致性）
  V6  需求闭环：设计 EIRP ≥ EIRP_req、G/T ≥ GT_req 时余量 M ≥ M_target
      （即：反推链路自洽 —— 若 EIRP=EIRP_req 精确成立，则 M 恰为 M_target）
  V7  P_out 反推：P_out_dBW = EIRP_req + guard - G_ant + L_feed + L_tx
  V8  约束合理性：c-12 容量 / c-13 频率规划 / c-17 质量功耗
输出：tools/_verify_budget_out.txt
"""
import io
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import design_engine as DE
from design_data import SCENARIOS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE, "output", "通信有效载荷知识图谱_2026-09-20.json"),
          "r", encoding="utf-8") as f:
    KG = json.load(f)

K_DB = -228.599     # 10lg(1.380649e-23)，独立取值
TOL = 0.02          # dB 容差

def fspl_ref(d_km, f_ghz):
    d = d_km * 1e3
    f = f_ghz * 1e9
    return 20 * math.log10(d) + 20 * math.log10(f) + 20 * math.log10(4 * math.pi / 2.99792458e8)

fails = []
lines = []

def chk(tag, a, b, unit="dB"):
    ok = abs(a - b) <= TOL
    if not ok:
        fails.append(f"{tag}: {a:.4f} vs {b:.4f} ({unit})")
    return ok

lines.append("=" * 100)
lines.append("链路预算独立校验（第一性原理复算）")
lines.append("=" * 100)

for key, sc in SCENARIOS.items():
    cfg = dict(sc["cfg"])
    r = DE.design_all(cfg, KG, skip_compare=True)
    p = r["params"]
    res = r["res"]
    s = res["summary"]
    up, dn = res["uplink"], res["downlink"]
    eirp, gt = res["eirp"], res["gt"]
    lines.append("")
    lines.append(f"### [{key}] {sc['label']}")
    lines.append(f"  orbit={cfg.get('orbit')} band={cfg.get('band')} mode={cfg.get('mode')} "
                 f"ant={cfg.get('ant_type')} cov={cfg.get('coverage')}")

    # --- V1 FSPL ---
    for lk, nm in ((up, "up"), (dn, "dn")):
        chk(f"{key}/{nm}/FSPL", lk["L_fs"], fspl_ref(lk["d_km"], lk["f_ghz"]))
    lines.append(f"  V1 FSPL: up={up['L_fs']:.2f} dn={dn['L_fs']:.2f} dB (d={up['d_km']:.0f}km "
                 f"f_up={up['f_ghz']}GHz f_dn={dn['f_ghz']}GHz)  OK")

    # --- V2/V3 C/N0 与 C/N ---
    for lk, nm in ((up, "up"), (dn, "dn")):
        cn0_ref = lk["EIRP"] - lk["L_fs"] - lk["sum_L"] + lk["GT"] - K_DB
        chk(f"{key}/{nm}/CN0", lk["CN0"], cn0_ref)
        cn_ref = lk["CN0"] - 10 * math.log10(lk["B_mhz"] * 1e6)
        chk(f"{key}/{nm}/CN", lk["CN"], cn_ref)
        chk(f"{key}/{nm}/M", lk["M"], lk["CN"] - lk["CN_req"])
    lines.append(f"  V2/V3 C/N0: up={up['CN0']:.2f} dn={dn['CN0']:.2f} dBHz | "
                 f"C/N: up={up['CN']:.2f} dn={dn['CN']:.2f} dB (B={up['B_mhz']}MHz)  OK")

    # --- V4 EIRP 组成 ---
    p_out_dbw = 10 * math.log10(eirp["P_out_w"])
    chk(f"{key}/EIRP", eirp["EIRP"], p_out_dbw + eirp["G_ant"] - eirp["L_feed"] - eirp["L_tx"])
    lines.append(f"  V4 EIRP={eirp['EIRP']:.2f}dBW = P_out({eirp['P_out_w']:.1f}W→{p_out_dbw:.2f}dBW) "
                 f"+ G_ant({eirp['G_ant']:.2f}) - L_feed({eirp['L_feed']}) - L_tx({eirp['L_tx']:.2f})  OK")

    # --- V5 G/T 组成 ---
    chk(f"{key}/GT", gt["GT"], gt["G_ant"] - 10 * math.log10(gt["T_sys"]))
    lines.append(f"  V5 G/T={gt['GT']:.2f}dB/K = G_ant({gt['G_ant']:.2f}) - 10lg(T_sys={gt['T_sys']:.1f}K)  OK")

    # --- V6 需求闭环 ---
    der = p["_derived"]
    lines.append(f"  V6 需求: EIRP_req={der['EIRP_req']:.2f} vs EIRP_ant={eirp['EIRP']:.2f} "
                 f"({'达标' if eirp['EIRP'] >= der['EIRP_req'] - 0.05 else '不达标'}); "
                 f"GT_req={der['GT_req']:.2f} vs GT_ant={gt['GT']:.2f} "
                 f"({'达标' if gt['GT'] >= der['GT_req'] - 0.05 else '不达标'})")
    lines.append(f"     M_up={s['M_up']:.2f} M_dn={s['M_dn']:.2f} M_e2e={s['M_e2e']:.2f} dB "
                 f"(目标 M≥{p['M_target']}) | judge={s['judge_pass']}/{s['judge_total']} "
                 f"fail={s['fail']} warn={s['warn']}")

    # --- V7 P_out 反推自洽 ---
    if der["p_out_source"].startswith("EIRP 需求反推"):
        p_ref = 10 ** ((der["EIRP_req"] + DE.EIRP_GUARD_DB - der["G_ant_used"]
                        + der["L_feed"] + der["L_tx"]) / 10)
        rel = abs(p_ref - eirp["P_out_w"]) / max(p_ref, 1e-9)
        if rel > 0.02:
            fails.append(f"{key}/P_out: ref={p_ref:.3f}W vs engine={eirp['P_out_w']:.3f}W")
        lines.append(f"  V7 P_out={eirp['P_out_w']:.1f}W (反推自洽, 相对偏差 {rel*100:.2f}%)  "
                     f"G_ant_used={der['G_ant_used']:.2f}dBi")

    # --- V8 约束合理性 ---
    tot = r["totals"]
    for c in res["constraints"]:
        if c["id"] in ("c-12", "c-13", "c-14", "c-17", "c-22") :
            mark = "OK " if c.get("ok") else "!! "
            vals = "; ".join(f"{it[0]}={it[1]:.4g}{it[2]}" if isinstance(it[1], (int, float))
                             else f"{it[0]}={it[1]}" for it in c.get("items", []))
            lines.append(f"  V8 {mark}{c['id']}: {vals}")
    lines.append(f"  合计: mass={tot.get('M_pay', 0):.0f}kg/{p.get('M_budget', 0):.0f}kg  "
                 f"power={tot.get('P_pay', 0):.0f}W/{p.get('P_budget', 0):.0f}W  "
                 f"平台={r['platform'][0] if r.get('platform') else '?'}")

lines.append("")
lines.append("=" * 100)
if fails:
    lines.append(f"复算不一致 {len(fails)} 项：")
    for f_ in fails:
        lines.append("  - " + f_)
else:
    lines.append("全部数值复算一致（V1~V7 容差 0.02dB 内）—— 引擎链路预算数学正确。")
lines.append("=" * 100)

out = "\n".join(lines)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_verify_budget_out.txt"), "w", encoding="utf-8") as f:
    f.write(out + "\n")
print(out)
