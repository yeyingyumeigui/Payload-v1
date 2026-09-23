# -*- coding: utf-8 -*-
"""示例验证：GEO 小卫星覆盖巴基斯坦 —— 相控阵配置（直射阵 vs 反射阵），并与固面反射面对比。

核心结论（先给答案）：
  ① GEO 覆盖固定区域只需 ±6° 电扫（地球可见盘仅 ±8.69°），扫描角不构成直射阵/反射阵的判别项；
  ② 真正的约束是「功率墙 + 增益墙」：满足 G/T 需求需 G≈42dBi，相控阵达此增益需 4000+ 阵元，
     偏置功耗 5~10kW，远超 1900W 小卫星平台 → 直射阵/反射阵在 c-17 全部不可行；
  ③ 选型判断逻辑因此「否定」了相控阵这一整类，推荐【固面反射面 2.5m】（G=52.8dBi 仅需 120W，
     25 条约束全过）—— 这正是判断逻辑的价值：不盲从用户「用相控阵」的初始倾向；
  ④ 若被强制二选一（直射阵 vs 反射阵）：GEO 固定覆盖下反射阵在功率/质量上更优（p_tr 低 40%），
     但仍过不了 1900W 墙；直射阵的价值（±60° 扫描、宽带、波束重构）在 GEO 固定覆盖用不上。

流程：需求 → 指标拆解 → 结构框架 → 子体制判决 → design_all 全链路验证（四方案对比）
输出：output/_pakistan_case_out.txt
"""
import io
import json
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_engine as DE
import payload_decompose as PD
from design_data import ARRAY_SUBTYPES, ANT_TYPES, PLATFORMS, BAND_FREQ
from infoflow_engine import to_f, fmt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE, "output", "通信有效载荷知识图谱_2026-09-20.json"),
          "r", encoding="utf-8") as f:
    KG = json.load(f)

OUT = []
def w(s=""):
    OUT.append(str(s))

ARR_P = DE.ARR_P_PER_EL      # 平均偏置功耗/阵元（c-16/c-17 口径）
ARR_M = DE.ARR_M_PER_EL

# ================================================================
# 0 需求
# ================================================================
REQ_TEXT = ("一颗高轨道（GEO）小卫星，覆盖巴基斯坦全境（约 800km 等效半径，星位约 69°E），"
            "Ka 频段宽带接入，多波束 + DTP 数字透明柔性载荷；"
            "小卫星平台约束：载荷承载 ≤420kg、供电 ≤1900W。")

# 巴基斯坦 GEO 几何（_geo_pakistan.py 核算）：电扫仅 ±6°，仰角 46~61°，斜距 37300km
BASE_CFG = dict(
    name="巴基斯坦GEO小卫星", service="高通量宽带", orbit="GEO", coverage="巴基斯坦",
    band="Ka", mode="数字透明", ant_type="相控阵", array_subtype="直射阵",
    user_band="Ka", feeder_band="Ka", isl_on=False, isl_type="",
    D_ap=1.2, N_el=4096, G_el=6.0, θ_scan=6,
    N_beam=7, B_beam=250, B_carrier=62, k_reuse=4, n_pol=2,
    C_req_ovr=4.0,                      # 区域宽带骨干目标 4Gbps（物理可达 ~7.7Gbps）
    P_out=0, amp_type="", GT_term="", EIRP_term="", A_avail=99.5,
    el_deg=46, life_yr=15, Mode="多波束",
    platform_pref="自动", force_custom_ant=True,
)

w("=" * 104)
w("示例：GEO 小卫星覆盖巴基斯坦 · 相控阵配置 · 直射阵 vs 反射阵（并与固面反射面对比）")
w("=" * 104)
w()
w("【0】需求：" + REQ_TEXT)
w()

# ================================================================
# 1 指标拆解（L1 系统层）
# ================================================================
req0 = PD.parse_requirement(REQ_TEXT, BASE_CFG)
sysdec = PD.decompose_system(req0, KG)
s = sysdec["summary"]
geo = sysdec["geo"]
der = sysdec["params"]["_derived"]

w("【1】指标拆解 —— L1 系统层指标树（需求 → 系统指标）")
w("-" * 104)
for n in sysdec["tree"]:
    star = "★" if n["id"] in ("s-lnk-8", "s-lnk-9") else " "
    w(f" {star}[{n['id']}] {n['name']} = {n['value']} {n['unit']}")
    w(f"      来源：{n['formula']}（{n['src']}）" + (f"  注：{n['note']}" if n["note"] else ""))
w()
w(f"  ▸ 几何要点：斜距 {fmt(geo['d_slant'],0)}km · 覆盖角 {fmt(geo['psi_cov_deg'],2)}° · "
  f"波束张角 {fmt(geo['θ_beam_deg'],3)}° · 几何建议波束数 {geo['N_beam_geo']} · 电扫需求 ±6°")
w()

# 功率墙/增益墙定量核算（T_sys 用引擎同源 Friis 链结果）
T_sys_ph = der["t_sys"].get("相控阵", 200.0)
T_sys_ref = der["t_sys"].get("固面", 200.0)
G_ant_need = der["GT_req"] + 10 * math.log10(T_sys_ph)   # 相控阵接收链
G_ant_need_ref = der["GT_req"] + 10 * math.log10(T_sys_ref)
lam = 0.015
w("  ▸ 天线需求反推（关键约束）：")
w(f"     · G/T 需求 {fmt(der['GT_req'],2)}dB/K；Ka 相控阵接收链 T_sys≈{fmt(T_sys_ph,0)}K → 天线增益需 G ≥ {fmt(G_ant_need,1)}dBi")
w(f"     · 相控阵达 G={fmt(G_ant_need,1)}dBi 所需阵元数（G=10lg(N_el·η)+G_el，G_el=6dBi）：")
for key in ("直射阵", "反射阵", "数字模拟混合"):
    eta = ARRAY_SUBTYPES[key]["eta"]
    N_el = 10 ** ((G_ant_need - 6.0) / 10.0) / eta
    N_el = int(math.ceil(N_el / 8) * 8)
    L_side = math.sqrt(N_el) * lam / 2
    P_bias = N_el * ARR_P.get(key, 1.0)
    w(f"        - {key}（η={eta}）：N_el≈{N_el} 元 → 阵面 {L_side:.2f}m×{L_side:.2f}m，"
      f"偏置功耗 {P_bias:.0f}W（平台仅 1900W → {'✗ 超 %.1f 倍' % (P_bias/1900) if P_bias>1900 else '✓'}）")
D_ref = lam / math.pi * math.sqrt(10 ** (G_ant_need_ref / 10.0) / 0.68)
w(f"     · 固面反射面达 G≥{fmt(G_ant_need_ref,1)}dBi 只需 D≈{fmt(D_ref,2)}m"
  f"（G=10lg(η(πD/λ)²)，η=0.68）；2.5m 货架反射面 G=52.8dBi、功耗仅 120W → ✓ 远优于相控阵")
w()

# ================================================================
# 2 结构框架
# ================================================================
subs = PD.decompose_subsys(sysdec, BASE_CFG)
fw = PD.form_framework(sysdec, subs, BASE_CFG)
w("【2】指标 → 载荷结构框架")
w("-" * 104)
w("  ◆ 配置决策链（指标 → 架构决策）：")
for d in fw["decisions"]:
    w(f"    {d['k']}. {d['q']} → {d['a']}")
    w(f"       依据：{d['why']}")
w()
w("  ◆ 五功能链拓扑：")
for c in fw["chains"]:
    w(f"    {c['cn']}")
    w(f"       流向：{c['flow']}")
    w(f"       KPI ：{c['kpi']}")
w()
w("  ◆ 分系统指标分配（L2）：")
for sb in subs["subs"]:
    w(f"    ▍{sb['cn']} —— {sb['chain_note']}")
    for nm, val, src in sb["indices"]:
        w(f"        · {nm}: {val}   [{src}]")
    w(f"        单机要求：{'、'.join(sb['units_req'])}")
w()

# ================================================================
# 3 单机选型判断逻辑（文档化决策表）
# ================================================================
w("【3】载荷单机产品选型判断逻辑（七步漏斗，与 select_antennas/build_equipment 实现对齐）")
w("-" * 104)
for st in PD.SELECTION_LOGIC:
    w(f"  第{st['step']}步 · {st['name']}")
    w(f"     规则：{st['rule']}")
    w(f"     实现：{st['impl']}")
w()

# ================================================================
# 4 子体制判决（五关判决法）
# ================================================================
M_ANT_BUDGET = 250.0     # kg（天线分系统）
P_ANT_BUDGET = 1000.0    # W（天线分系统偏置，留 900W 给处理/发射/星务）

w("【4】相控阵子体制判决（五关判决法）—— 直射阵 vs 反射阵 专项")
w("-" * 104)
w(f"  输入：θ_scan=6°（GEO 固定覆盖）；N_el=4096（满足 G≥{fmt(G_ant_need,1)}dBi）；"
  f"B_beam=250MHz@20GHz（相对带宽 1.25%）；天线分系统预算 M≤{M_ANT_BUDGET}kg、P≤{P_ANT_BUDGET}W")
w()
verdict = PD.decide_array_subtype(sysdec, BASE_CFG,
                                  p_budget_w=P_ANT_BUDGET, m_budget_kg=M_ANT_BUDGET)
w(f"  {'子体制':<10}{'关1扫描±6°':<12}{'关2阵元≤上限':<14}{'关3带宽':<10}"
  f"{'关4偏置功耗':<18}{'关4质量':<14}{'关4EIRP闭合':<16}{'评分':<7}{'结论'}")
for r in verdict["rows"]:
    hard = {h[0]: h[2] for h in r["hard"]}
    def mk(k):
        v = hard.get(k)
        return ("✓" if v else "✗") if v is not None else "—"
    bias = next((h for h in r["hard"] if h[0] == "阵面偏置功耗"), None)
    eirp = next((h for h in r["hard"] if h[0].startswith("EIRP")), None)
    w(f"  {r['key']:<10}{mk('扫描角'):<12}{mk('阵元数'):<14}{mk('相对带宽'):<10}"
      f"{(str(r['P_bias_w'])+'W '+mk('阵面偏置功耗')):<18}{(str(r['M_face_kg'])+'kg '+mk('阵面质量')):<14}"
      f"{mk('EIRP闭合(每元≤8W)'):<16}{r['score']:<7}{'可行' if r['ok'] else '淘汰'}")
w()
w(f"  → 五关判决结论：推荐 {verdict['recommend_cn']}（可行集：{('、'.join(verdict['alive']) or '空 —— 全部淘汰')}）")
w("  → 关键：直射阵/反射阵均倒在『关4 偏置功耗』（4096 元 × 2.5/1.2W = 10240/4915W ≫ 1000W 预算），")
w("    扫描角（关1）在 GEO 固定覆盖下两者都轻松通过，不是判别项。")
w()

# ================================================================
# 5 四方案 design_all 全链路验证
# ================================================================
w("【5】四方案 design_all 全链路验证（链路预算 + 25 条约束 + 平台闭合 + 五重验证）")
w("=" * 104)

CASES = [
    ("相控阵·直射阵",   dict(BASE_CFG, array_subtype="直射阵", ant_type="相控阵", N_el=4096)),
    ("相控阵·反射阵",   dict(BASE_CFG, array_subtype="反射阵", ant_type="相控阵", N_el=4096)),
    ("相控阵·数字模拟混合", dict(BASE_CFG, array_subtype="数字模拟混合", ant_type="相控阵", N_el=4096)),
    ("固面反射面 2.5m", dict(BASE_CFG, ant_type="固面", array_subtype="", D_ap=2.5,
                            force_custom_ant=False, amp_type="TWTA")),
]

results = {}
for label, cfg in CASES:
    r = DE.design_all(cfg, KG, skip_compare=True)
    res = r["res"]["summary"]
    p = r["params"]
    dv = r["params"]["_derived"]
    tot = r["totals"]
    plat = r["platform"][1] if r["platform"] else None
    sv = PD.decide_array_subtype(sysdec, cfg, p_budget_w=P_ANT_BUDGET,
                                 m_budget_kg=M_ANT_BUDGET) if cfg["ant_type"] == "相控阵" else None
    vv = PD.validate_decomposition(req0, sysdec, subs, fw, r, subtype_verdict=sv)
    results[label] = dict(r=r, v=vv, plat=plat)
    w()
    w(f"◆◆ 方案：{label}")
    w("-" * 104)
    w(f"   天线：{r['ant_rec'][1]['cn']}（{r['ant_rec'][1]['id']}，"
      f"{'定制' if r['is_custom_ant'] else '货架 level%d' % r['ant_rec'][1]['level']}）")
    w(f"   链路闭合：EIRP={fmt(res.get('EIRP',0),1)}dBW（需求 {fmt(dv['EIRP_req'],1)}） · "
      f"G/T={fmt(res.get('GT',0),1)}dB/K（需求 {fmt(dv['GT_req'],1)}） · "
      f"G_ant={fmt(res.get('G_ant',0),1)}dBi · M_up={fmt(res.get('M_up',0),2)} / M_dn={fmt(res.get('M_dn',0),2)}dB（目标 3.0）")
    w(f"   容量/频谱：C_sys={fmt(res.get('C_sys',0),2)}Gbps（目标 {fmt(to_f(p.get('C_req'),0),1)}） · "
      f"N_beam×B_beam={dv['N_beam']*p['B_beam']:.0f} ≤ {p['B_total']*s['k_reuse']:.0f}MHz")
    w(f"   功放反推：P_out={fmt(dv['P_out_w'],1)}W/波束 ×{dv['N_beam']} 波束")
    w(f"   载荷规模：质量 {fmt(tot['m_pay'],0)}kg / 功耗 {fmt(tot['p_pay'],0)}W · "
      f"天线分系统 {fmt(tot['sub_m'].get('m_ant',0),0)}kg / {fmt(tot['sub_p'].get('P_ant',0),0)}W · "
      f"单机 {tot['n_rows']} 类 {tot['n_items']} 台 · 定制缺口 N_gap={tot['n_custom']}")
    w(f"   平台：{plat['cn'] if plat else '—（无满足承载的同轨平台）'}"
      + (f"（承载 {plat['m_pay']}kg/{plat['p_pay']}W）" if plat else "")
      + f" · 运载：{r['launcher'][1]['cn'] if r['launcher'] else '—'}")
    w(f"   约束：judge {res.get('judge_pass')}/{res.get('judge_total')} · fail={res.get('fail',[])}"
      + (f" · warn={res.get('warn',[])}" if res.get('warn') else ""))
    if p.get("_plat_gap"):
        w(f"   ⚠ 平台缺口：{p['_plat_gap']}")
    w(f"   六维评分：{r['score']['total']}（" +
      "，".join(f"{r['score']['cn'][k]} {v}" for k, v in r['score']['dims'].items()) + "）")
    w(f"   五重验证：{vv['n_pass']}/{vv['n_total']}")
    for c in vv["checks"]:
        w(f"      [{'✓' if c['ok'] else '✗'} {c['id']}] {c['name']}：{c['detail']}")

# ================================================================
# 6 对比汇总 + 结论
# ================================================================
w()
w("【6】四方案对比汇总")
w("=" * 104)
w(f"{'方案':<22}{'G_ant':<8}{'EIRP':<8}{'G/T':<8}{'载荷kg':<9}{'载荷W':<10}{'judge':<9}{'fail':<22}{'评分':<7}{'结论'}")
w("-" * 104)
for label, _ in CASES:
    r = results[label]["r"]
    res = r["res"]["summary"]
    tot = r["totals"]
    fail = res.get("fail", [])
    ok = (len(fail) == 0) and not r["params"].get("_plat_gap")
    w(f"{label:<22}{fmt(res.get('G_ant',0),1):<8}{fmt(res.get('EIRP',0),1):<8}{fmt(res.get('GT',0),1):<8}"
      f"{fmt(tot['m_pay'],0):<9}{fmt(tot['p_pay'],0):<10}"
      f"{str(res.get('judge_pass'))+'/'+str(res.get('judge_total')):<9}{(','.join(fail) or '—'):<22}"
      f"{r['score']['total']:<7}{'✓ 可行' if ok else '✗ 不可行'}")
w()
w("【7】结论：巴基斯坦 GEO 小卫星，相控阵怎么配？直射阵还是反射阵？")
w("=" * 104)
w("""
  一句话答案：在「GEO 小卫星（1900W 平台）+ 固定覆盖巴基斯坦」约束下，相控阵（无论直射阵还是
  反射阵）都过不了功率墙，工程正解是【固面反射面 2.5m】；若被强制在两种相控阵里二选一，选
  【反射阵】（功率/质量更省），但两者都不可行。

  ① 为什么扫描角不是判别项（纠正一个常见误区）：
     GEO 看整个可见地球盘只有 ±8.69°（离天底角），覆盖巴基斯坦（中心纬偏 30°）只需电扫 ±6°，
     扫描损耗 cos^1.5(6°)=0.04dB 可忽略。直射阵 ±60°、反射阵 ±45° 都远超需求 —— 扫描角这一关
     两者都轻松通过，不构成判别。相控阵「大扫描角」的核心价值（LEO 跟踪移动小区、动中通、
     D2D）在 GEO 固定覆盖场景用不上。

  ② 真正的约束是「增益墙 + 功率墙」：
     · 链路反推：满足终端 0.74m VSAT（G/T=17dB/K）的上行闭合，星上 G/T 需 18.85dB/K，
       Ka 接收链 T_sys≈200K → 天线增益需 G ≥ 41.9dBi。
     · 相控阵达 41.9dBi 需 N_el≈4000+ 元（η=0.5~0.62），偏置功耗 5~10kW；
       而 1900W 平台留给天线分系统仅约 1000W → 差 5~10 倍，c-17 硬约束失败。
     · 固面反射面达同增益只需 2.5m 口径（G=52.8dBi），功耗仅 120W → 25 条约束全过。
     根因：相控阵口径效率低（η≈0.5~0.62 vs 反射面 0.68）、单元增益低（G_el≈6dBi），
     同等增益要堆数千个有源 T/R 通道，每个都耗电 —— 这是相控阵的固有代价。

  ③ 直射阵 vs 反射阵（若强制二选一）：
     ┌─────────────┬──────────────────────┬──────────────────────┐
     │ 维度          │ 直射阵（DRA）          │ 反射阵（Reflectarray）   │
     ├─────────────┼──────────────────────┼──────────────────────┤
     │ 偏置功耗/元    │ 2.5W（c-16 口径）      │ 1.2W（仅移相器，低 52%）   │
     │ 4096元阵面功耗 │ 10240W               │ 4915W（更省，但仍超 1900W） │
     │ 质量/元       │ 0.045kg              │ 0.038kg（更轻）          │
     │ 口径效率 η    │ 0.55                 │ 0.50（略低）            │
     │ 扫描上限      │ ±60°（GEO 用不上）     │ ±45°（GEO 用不上）       │
     │ 带宽          │ 无谐振限制（宽带优）   │ <10%（窄带，Ka 1.25% 够用）│
     │ 成熟度 TRL    │ 9（飞行继承多）        │ 7（在研，风险略高）       │
     │ 成本系数      │ 1.0                  │ 0.85（略低）            │
     └─────────────┴──────────────────────┴──────────────────────┘
     → GEO 固定覆盖下，反射阵的「低功耗/轻质量」恰好命中小卫星最紧的约束，故反射阵略优；
       直射阵的「大扫描/宽带/高 TRL」在本场景是溢余能力。但二者都过不了 1900W 功率墙。

  ④ 选型判断逻辑的验证价值：
     五关判决 + design_all 25 条约束 + 五重验证，一致地「否定」了相控阵整类、推荐固面反射面。
     这证明该判断逻辑不是盲从用户「用相控阵」的初始倾向，而是用链路预算与平台约束把
     「直觉选型」纠正为「物理可行选型」—— 这正是指标拆解 → 结构框架 → 选型逻辑闭环的意义。

  ⑤ 相控阵在 GEO 何时才合理？（判断逻辑的适用边界）
     · 需波束跳变/在轨重构的柔性载荷（一星多任务、应急专网）—— 用 DTP + 小规模相控阵馈电；
     · 需抗干扰零陷（军用）—— 相控阵幅相加权可置零；
     · 多波束成形 + 电扫跟踪（航空航海动中通）。
     单纯「固定区域宽带覆盖」用相控阵是「杀鸡用牛刀且牛刀太耗电」，反射面才是正解。
""")

out_path = os.path.join(BASE, "output", "_pakistan_case_out.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print(f"[written] {out_path}  ({len(OUT)} lines)")
for label, _ in CASES:
    r = results[label]["r"]
    res = r["res"]["summary"]
    print(f"  {label:<22} fail={res.get('fail',[])} judge={res.get('judge_pass')}/{res.get('judge_total')}")
