# -*- coding: utf-8 -*-
"""infoflow 引擎冒烟测试：用 4 个预设跑通全部计算，输出关键指标与约束判定。"""
from __future__ import annotations
import json, os, sys, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from infoflow_data import PARAMS, PRESETS
from infoflow_engine import compute_all, fspl, rain_at_avail, pick_modcod, lam_m

SRC = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\_infoflow_smoke.txt"

with open(SRC, "r", encoding="utf-8") as f:
    kg = json.load(f)

L = []
def p(*a): L.append(" ".join(str(x) for x in a))

# ---- 基础公式自检 ----
p("=" * 78)
p("一、基础公式自检")
p("=" * 78)
# FSPL GEO@20GHz: 20lg(38e6)+20lg(20e9)-147.55 ≈ 205.8-? 手算
d, f = 38000e3, 20e9
manual = 20 * math.log10(d) + 20 * math.log10(f) - 147.55
p(f"FSPL(GEO 38000km @20GHz): 引擎={fspl(38000,20):.3f} 手算={manual:.3f} "
  f"[{'PASS' if abs(fspl(38000,20)-manual)<1e-6 else 'FAIL'}]")
# 图谱 c-7 描述文字勘误：图谱写"GEO 约 205dB@30GHz"，实际 30GHz 为 213.6dB，
# 205dB 对应约 12GHz。引擎按标准公式计算，以物理正确值为准。
p(f"FSPL(GEO @30GHz): {fspl(38000,30):.2f} dB（物理正确值≈213.6；图谱 c-7 文字'205dB@30GHz'有误，205dB 实为 ~12GHz）"
  f"[{'PASS' if abs(fspl(38000,30)-213.59)<0.1 else 'FAIL'}]")
p(f"FSPL(GEO @12GHz): {fspl(38000,12):.2f} dB（对应图谱误写的 205dB）"
  f"[{'PASS' if abs(fspl(38000,12)-205.6)<1.0 else 'FAIL'}]")
p(f"FSPL(LEO 1200km @30GHz): {fspl(1200,30):.2f} dB（图谱参考值'≈172dB'对应 ~550km 斜距；1200km 实为 183.6dB）"
  f"[{'PASS' if abs(fspl(1200,30)-183.58)<0.1 else 'FAIL'}]")
# MODCOD 自适应
mc = pick_modcod(16.5)
p(f"MODCOD(C/N=16.5dB) → {mc['name'] if mc else None}（期望 32APSK 9/10 附近）[{'PASS' if mc and '32APSK' in mc['name'] else 'FAIL'}]")
mc2 = pick_modcod(2.0)
p(f"MODCOD(C/N=2.0dB) → {mc2['name'] if mc2 else None}（期望 QPSK 低阶）[{'PASS' if mc2 and 'QPSK' in mc2['name'] else 'FAIL'}]")
mc3 = pick_modcod(-5.0)
p(f"MODCOD(C/N=-5dB) → {mc3}（期望 None 无法闭合）[{'PASS' if mc3 is None else 'FAIL'}]")
# 雨衰：可用性降低 → 雨衰减小
r99 = rain_at_avail(7.0, 99.9, 30)
r999 = rain_at_avail(7.0, 99.99, 30)
p(f"雨衰 A(99.9%)={r99:.2f}dB, A(99.99%)={r999:.2f}dB [PASS]" if r99 < r999 else f"雨衰单调性 FAIL: {r99} vs {r999}")
# 波长
p(f"λ(20GHz)={lam_m(20)*1000:.2f}mm（期望 15mm）[{'PASS' if abs(lam_m(20)*1000-15)<0.5 else 'FAIL'}]")
p(f"λ/32(20GHz)={lam_m(20)*1000/32:.3f}mm（期望 ≈0.469mm）")

# ---- 4 预设全流程 ----
p("")
p("=" * 78)
p("二、4 个预设场景全流程计算")
p("=" * 78)
defaults = {d["sym"]: d["def"] for d in PARAMS}
results = {}
for key, pre in PRESETS.items():
    vals = dict(defaults)
    vals.update(pre["values"])
    r = compute_all(vals, kg)
    results[key] = r
    s = r["summary"]
    p("")
    p(f"### {pre['label']}")
    p(f"  天线: {vals['ant_type']} G_ant={s['G_ant']:.2f}dBi T_sys={s['T_sys']:.1f}K")
    p(f"  EIRP={s['EIRP']:.2f}dBW  G/T={s['GT']:.2f}dB/K")
    p(f"  上行: C/N0={s['CN0_up']:.2f}dBHz C/N={s['CN_up']:.2f}dB M={s['M_up']:.2f}dB")
    p(f"  下行: C/N0={s['CN0_dn']:.2f}dBHz C/N={s['CN_dn']:.2f}dB M={s['M_dn']:.2f}dB MODCOD={s['modcod']}")
    p(f"  端到端({r['e2e']['arch']}): CN={r['e2e']['CN_total']:.2f}dB M={s['M_e2e']:.2f}dB")
    p(f"  下行容量={s['C_link']:.3f}Gbps 系统容量={s['C_sys']}")
    if r["laser_isl"]:
        li = r["laser_isl"]
        p(f"  激光ISL: G_opt={li['G_opt_db']:.1f}dB L_fs={li['L_fs_opt']:.1f}dB P_rx={li['P_rx_dbm']:.1f}dBm M={li['M_db']:.2f}dB ATP_ok={li['c18']['ok']}")
    if r["data"]:
        dd = r["data"]
        p(f"  数据链: R_pdl={dd['R_pdl']}Mbps CR={dd['CR']} R_bus={dd['R_bus']}Mbps 需求={dd['R_need_bus']:.0f} E_store={dd['E_store']}Tbit 需求={dd['E_need_tbit']:.2f}Tbit ok={dd['ok']}")
    p(f"  约束: {s['pass_count']}/{s['total_count']} 通过；判据型 {s['judge_pass']}/{s['judge_total']}；"
      f"硬性不通过: {s['fail'] if s['fail'] else '无'}；警告: {s.get('warn') if s.get('warn') else '无'}")
    for c in r["constraints"]:
        if not c.get("ok"):
            tag = "WARN" if c.get("sev") == "warning" else "FAIL"
            p(f"    [{tag}] {c['id']} {c['formula']} → {c['note']}")
    # 流程覆盖检查
    nf = len(r["flows"])
    p(f"  信息流链路: {nf} 条")

# ---- 链路流完整性 ----
p("")
p("=" * 78)
p("三、信息流链路覆盖检查（15 条 chain 全部有 flow）")
p("=" * 78)
r0 = results["geo_ka_hts"]
chain_nodes = [o["id"] for o in kg["ontologies"] if o.get("chain")]
p(f"知识图谱带 chain 节点: {len(chain_nodes)}")
p(f"引擎 flows 数: {len(r0['flows'])}")
missing = [c for c in chain_nodes if c not in r0["flows"]]
p(f"缺失: {missing if missing else '无'} [{'PASS' if not missing else 'FAIL'}]")
for lid, fl in r0["flows"].items():
    if "tx" in fl:
        n = len(fl["tx"]["stages"])
        p(f"  {lid}: both, tx {n} 级 / rx {len(fl['rx']['stages'])} 级")
    else:
        key = "stages"
        p(f"  {lid}: {fl['meta']['dir']}, {len(fl[key])} 级")

# ---- 逐级信号流示例（透明转发体制）----
p("")
p("=" * 78)
p("四、逐级信号流示例：透明转发体制 (transparent)")
p("=" * 78)
fl = r0["flows"]["transparent"]
p("发射视图（tx）:")
for s in fl["tx"]["stages"]:
    p(f"  [{s['seq']:>2}] {s['cn']:<16} g={s['g_db']:+7.2f}dB  P_in={s['p_in']:8.2f} → P_out={s['p_out']:8.2f} dBW")
p(f"  出口功率: {fl['tx']['p_exit_dbw']:.2f} dBW, 总插损 {fl['tx']['total_loss_db']:.2f} dB")
p("接收视图（rx，Friis 噪声级联）:")
for s in fl["rx"]["stages"]:
    p(f"  [{s['seq']:>2}] {s['cn']:<16} g={s['g_db']:+7.2f}dB NF={s['nf_db']:5.2f}dB "
      f"T_dev={s['T_dev']:9.2f}K cumG={s['cum_g_db']:+7.2f}dB 折算贡献={s['T_contrib']:9.3f}K")
p(f"  T_sys={fl['rx']['T_sys']:.2f}K, NF_total={fl['rx']['NF_total_db']:.2f}dB")

# ---- 下行发射链（downlink）----
p("")
p("=" * 78)
p("五、下行用户链路发射流 (downlink)")
p("=" * 78)
fl = r0["flows"]["downlink"]
for s in fl["stages"]:
    p(f"  [{s['seq']:>2}] {s['cn']:<16} g={s['g_db']:+7.2f}dB  {s['p_in']:8.2f} → {s['p_out']:8.2f} dBW")

# ---- 回环建议 ----
p("")
p("=" * 78)
p("六、回环建议机制测试（构造余量不足场景）")
p("=" * 78)
vals = dict(defaults)
vals.update(PRESETS["geo_ka_hts"]["values"])
vals["P_out"] = 8           # 功放功率大幅调小 → MODCOD 降至最低阶仍不闭合
vals["D_ap"] = 0.9          # 口径调小
r_bad = compute_all(vals, kg)
p(f"  劣化场景: 下行 M={r_bad['summary']['M_dn']:.2f}dB (目标 3dB)")
lp = r_bad["loop"]
p(f"  需要回环: {lp['need']}, 缺口 {lp.get('deficit',0):.2f}dB")
for a in lp.get("advice", []):
    g = a['gain_db']
    p(f"    {a['step']}: {a['action']} → +{f'{g:.2f}' if g is not None else '?'}dB "
      f"[{'足够' if a.get('enough') else '不足'}] 代价: {a['cost']}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print(f"smoke test written: {OUT}, lines={len(L)}")
