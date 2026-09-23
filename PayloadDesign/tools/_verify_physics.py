# -*- coding: utf-8 -*-
"""独立第一性原理验证（物理层）—— 不复用引擎计算函数，全部公式手工重建后对拍。

覆盖 verify_budget.py(V1~V8) 之外的缺口：
  P1  覆盖几何：斜距/覆盖角/视域半径/波束张角/六边形密铺系数 1.209/GEO ±8.69° 天底角
  P2  天线增益：固面 η(πD/λ)²、相控阵 10lg(N_el·η)+G_el−cos^1.5θ 扫描损耗、θ3dB≈70λ/D
      三处实现互相对拍（antenna_gain_est / antenna_electrical / grasp_bridge.peak_gain_dbi）
  P3  T_sys Friis 级联：逐级 (F−1)·290 / (L−1)·290 / 折算 T_dev·10^(−cum_g/10)，NF_total
  P4  ΣL 分项合成：雨衰 A_ref·(p/0.01)^−0.6·sin30°/sin(el) + 大气 + 指向 + 极化 + 实现 + 动态
  P5  需求反推：EIRP_req / GT_req = CN_des + M + 10lgB − 终端能力 + Lfs + ΣL + k
  P6  MODCOD 选档（独立实现）+ cn_req = Es/N0 + 1.0dB 实现损耗
  P7  端到端 C/N 功率倒数合成 + 再生 bonus
  P8  容量 c-12 / 频谱 c-13 独立复算
  P9  质量功耗链：Σrows → ×1.2 裕度 → c-17 预算 → select_platform 可行性
  P10 激光链路：G_opt / L_fs_opt=20lg(4πd/λ) / L_point=12(σ/θ)² / P_rx / M
  P11 evaluate_scheme 评级规则独立重建（硬全过→A/B/C 按软准则数；否则 D）
  P12 score_scheme 加权总分独立复算 + 各维度∈[0,10]
  P13 阵面功耗口径：P_tr = ARR_P_PER_EL[子体制]、c-16 P_face = N_el·P_tr
  P14 数值卫生：全输出无 NaN/Inf、可 JSON 序列化

输出：tools/_verify_physics_out.txt
"""
import io
import json
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import design_engine as DE
from design_data import (SCENARIOS, ORBITS, COVERAGE, SERVICES, BAND_FREQ, BAND_RAIN,
                         ANT_TYPES, ARRAY_SUBTYPES, PLATFORMS)
from infoflow_data import MODCOD
import grasp_bridge as GB

# 引擎模块级常量（口径对拍用，取自 DE 而非重复定义）
ARR_P_PER_EL = DE.ARR_P_PER_EL

BASE = os.path.dirname(HERE)
with open(os.path.join(BASE, "output", "通信有效载荷知识图谱_2026-09-20.json"),
          "r", encoding="utf-8") as f:
    KG = json.load(f)

# 独立物理常数（不复用引擎常量）
C0 = 299792458.0          # m/s
KDB = -228.6              # 10lg(k)
RE = 6371.0               # km
TOL = 0.02                # dB 容差
TOL_GEO = 0.05            # 几何角度容差 deg / 半径 km 相对容差见各处

fails, lines = [], []


def chk(tag, a, b, tol=TOL):
    ok = abs(a - b) <= tol
    if not ok:
        fails.append(f"{tag}: {a:.6f} vs {b:.6f} (tol {tol})")
    return ok


def chk_rel(tag, a, b, rel=1e-3, absmin=1e-9):
    ok = abs(a - b) <= max(rel * abs(b), absmin)
    if not ok:
        fails.append(f"{tag}: {a:.6f} vs {b:.6f} (rel {rel})")
    return ok


# ---------------- 独立公式实现（全部手工重建） ----------------
def my_slant(h, el):
    s = math.sin(math.radians(el))
    return math.sqrt(RE * RE * s * s + 2 * RE * h + h * h) - RE * s


def my_psi(h, el):
    c = RE * math.cos(math.radians(el)) / (RE + h)
    return math.degrees(math.acos(min(max(c, -1.0), 1.0))) - el


def my_fspl(d_km, f_ghz):
    return 20 * math.log10(4 * math.pi * d_km * 1e3 * f_ghz * 1e9 / C0)


def my_rain(a_ref, avail, el):
    p = max(100.0 - avail, 1e-6)
    return a_ref * (p / 0.01) ** (-0.6) * (math.sin(math.radians(30)) /
                                           math.sin(math.radians(max(el, 5.0))))


def my_gain_refl(D, lam, eta):
    return 10 * math.log10(eta * (math.pi * D / lam) ** 2)


def my_gain_arr(N_el, eta, G_el, th_scan):
    G = 10 * math.log10(N_el * eta) + G_el
    if th_scan > 0:
        G -= -10 * 1.5 * math.log10(math.cos(math.radians(th_scan)))
    return G


def my_modcod(cn, m_target):
    """独立 MODCOD 选档：满足 cn≥cn_req 的最高 η；若给定余量目标优先满足余量。"""
    ok = [m for m in MODCOD if cn >= m["cn_req"]]
    if not ok:
        return None
    best = max(ok, key=lambda m: m["eta"])
    if m_target and m_target > 0:
        okm = [m for m in ok if cn - m["cn_req"] >= m_target]
        if okm:
            best = max(okm, key=lambda m: m["eta"])
    return best


def my_total_cn(up, dn):
    return -10 * math.log10(10 ** (-up / 10) + 10 ** (-dn / 10))


# ================================================================
lines.append("=" * 100)
lines.append("P0 解析锚点（教科书/公开值，不经引擎）")
lines.append("=" * 100)
# GEO 天底角 ±8.69°（asin(R/(R+h))）
h_geo = ORBITS["GEO"]["alt_km"]
nadir = math.degrees(math.asin(RE / (RE + h_geo)))
chk("P0/GEO天底角8.69°", round(nadir, 2), 8.69, tol=0.01)
lines.append(f"  GEO 可见地盘天底角 = asin(6371/(6371+{h_geo:.0f})) = {nadir:.4f}° ≈ ±8.69°  OK")
# GEO 星下点斜距 = h；el=90° 极限
chk("P0/GEO星下点斜距", my_slant(h_geo, 90), h_geo, tol=0.5)
# GEO el=30° 斜距：两条完全独立路径互证
#   路径A（引擎式）：d = sqrt(R²sin²el + 2Rh + h²) − R·sin(el)
#   路径B（余弦定理三角）：先由覆盖角公式求地心角 λ，再 d = sqrt(R²+(R+h)²−2R(R+h)cosλ)
psi30 = my_psi(h_geo, 30)
lamr = math.radians(psi30)
d30 = my_slant(h_geo, 30)
d30_law = math.sqrt(RE ** 2 + (RE + h_geo) ** 2 - 2 * RE * (RE + h_geo) * math.cos(lamr))
chk_rel("P0/GEO-30°斜距(余弦定理互证)", d30, d30_law, rel=1e-9)
# 再反解仰角自洽：tan(el) = (cosλ − R/(R+h))/sinλ
el_back = math.degrees(math.atan((math.cos(lamr) - RE / (RE + h_geo)) / math.sin(lamr)))
chk("P0/覆盖角反解仰角", el_back, 30.0, tol=1e-6)
lines.append(f"  GEO el=30° 斜距 = {d30:.1f} km（余弦定理独立路径 {d30_law:.1f} km，"
             f"ψ={psi30:.3f}° 反解仰角 {el_back:.6f}°）  OK")
# FSPL 锚点：36000km/12GHz，两种独立形式互证（4πdf/c 与 20lg(d)+20lg(f)−147.55）
# 两式差值即常数 −147.55 的舍入误差（精确值 −147.5524），应在 0.02dB 容差内
fs = my_fspl(36000, 12)
fs_ref = 20 * math.log10(36000e3) + 20 * math.log10(12e9) - 147.55
chk("P0/FSPL 两式互证", fs, fs_ref, tol=0.02)
lines.append(f"  FSPL(36000km,12GHz) = {fs:.2f} dB（4πdf/c 式与 20lg 式差 {fs-fs_ref:+.4f}dB "
             f"= 常数舍入）  OK")
# 六边形密铺系数：圆面积/正六边形(外接圆 r)面积 = π/(3√3/2) = 1.2092
hexcoef = math.pi / (1.5 * math.sqrt(3))
chk("P0/六边形密铺系数1.209", round(hexcoef, 3), 1.209, tol=0.001)
lines.append(f"  N_beam 密铺系数 π/(3√3/2) = {hexcoef:.4f} ≈ 1.209  OK")
# k 常数：10lg(1.380649e-23)
kb = 10 * math.log10(1.380649e-23)
chk("P0/玻尔兹曼−228.6", round(kb, 1), -228.6, tol=0.01)
lines.append(f"  10lg(k) = {kb:.4f} dBW/Hz/K ≈ −228.6  OK")
# MODCOD cn_req = esn0 + 1.0
bad_mc = [m["name"] for m in MODCOD if abs(m["cn_req"] - (m["esn0"] + 1.0)) > 1e-9]
if bad_mc:
    fails.append(f"P0/MODCOD cn_req≠esn0+1.0: {bad_mc}")
lines.append(f"  MODCOD 28 档 cn_req = Es/N0 + 1.0dB 实现损耗 全表一致  OK")

# ================================================================
# 补充用户代表场景（除 8 个内置 SCENARIOS 外）：巴基斯坦 GEO HTS（用户长期关注）、
# GEO 功率墙（小平台 + Ka 高增益相控阵，验证 c-17 诊断路径）、固面正解。
EXTRA = {
    "pak_geo_hts": dict(
        label="巴基斯坦 GEO Ka 高通量（用户代表场景）",
        cfg=dict(service="高通量宽带", orbit="GEO", coverage="巴基斯坦", band="Ka",
                 mode="数字透明", ant_type="固面", array_subtype="",
                 user_band="Ka", feeder_band="Ka", isl_on=False, isl_type="",
                 D_ap=2.5, N_beam=0, B_beam=250, B_carrier=62, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.5, el_deg=46, life_yr=15,
                 Mode="多波束", platform_pref="自动")),
    "geo_powerwall": dict(
        label="GEO 功率墙场景（小平台 + Ka 相控阵高增益，验证 c-17 诊断）",
        cfg=dict(service="高通量宽带", orbit="GEO", coverage="区域", band="Ka",
                 mode="数字透明", ant_type="相控阵", array_subtype="数字模拟混合",
                 user_band="Ka", feeder_band="Ka", isl_on=False, isl_type="",
                 D_ap=0.8, N_el=1024, θ_scan=0, N_beam=64, B_beam=250, B_carrier=62,
                 P_out=0, amp_type="MPA", C_req_ovr=40, GT_term="", EIRP_term="",
                 A_avail=99.9, el_deg=40, life_yr=15, Mode="多波束", platform_pref="自动")),
}
ALL_CASES = {}
for _k, _v in SCENARIOS.items():
    ALL_CASES[_k] = _v
for _k, _v in EXTRA.items():
    ALL_CASES[_k] = _v

# ================================================================
for key, sc in ALL_CASES.items():
    cfg = dict(sc["cfg"])
    r = DE.design_all(cfg, KG, skip_compare=True)
    p, res = r["params"], r["res"]
    der = p["_derived"]
    s = res["summary"]
    up, dn, e2e = res["uplink"], res["downlink"], res["e2e"]
    ant, eirp, gt = res["antenna"], res["eirp"], res["gt"]
    geo, totals = r["geo"], r["totals"]
    ev, score = r["eval"], r["score"]
    lines.append("")
    lines.append("=" * 100)
    lines.append(f"### [{key}] {sc['label']}")
    lines.append("=" * 100)

    # ---- P1 覆盖几何 ----
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    el = max(DE.to_f(cfg.get("el_deg"), cov["el_min_deg"]), cov["el_min_deg"])
    h = orb["alt_km"]
    chk_rel(f"{key}/P1/斜距", geo["d_slant"], my_slant(h, el), rel=1e-9)
    chk(f"{key}/P1/覆盖角ψ", geo["psi_cov_deg"], my_psi(h, el), tol=1e-9)
    chk_rel(f"{key}/P1/视域半径", geo["cov_r_cap_km"], RE * math.radians(my_psi(h, el)), rel=1e-9)
    beam_r = DE.to_f(cfg.get("beam_r_km"), cov["beam_r_km"])
    cov_r = DE.to_f(cfg.get("cov_r_km"), cov["r_km"])
    r_eff = min(cov_r, geo["cov_r_cap_km"])
    chk(f"{key}/P1/波束张角", geo["θ_beam_deg"],
        2.0 * math.degrees(math.asin(min(1.0, beam_r / RE))), tol=1e-9)
    chk(f"{key}/P1/密铺波束数", geo["N_beam_geo"],
        max(1, math.ceil(1.209 * (r_eff / max(beam_r, 1e-6)) ** 2)), tol=0)
    lines.append(f"  P1 几何: h={h:.0f}km el={el:.0f}° d={geo['d_slant']:.0f}km ψ={geo['psi_cov_deg']:.2f}° "
                 f"cov_r_cap={geo['cov_r_cap_km']:.0f}km θ_beam={geo['θ_beam_deg']:.3f}° "
                 f"N_geo={geo['N_beam_geo']}  全部独立复算一致")

    # ---- P2 天线增益 ----
    f_up, f_dn = BAND_FREQ.get(cfg.get("band", "Ka"), (30.0, 20.0))
    lam_m = C0 / (f_dn * 1e9)
    if r["is_custom_ant"]:
        if cfg.get("ant_type") == "相控阵":
            sub = cfg.get("array_subtype", "数字模拟混合")
            eta = ARRAY_SUBTYPES.get(sub, {}).get("eta", 0.62)
            N_el = DE.to_f(cfg.get("N_el"), 1024)
            G_ref = my_gain_arr(N_el, eta, DE.to_f(cfg.get("G_el"), 6.0),
                                DE.to_f(cfg.get("θ_scan"), 0))
            chk(f"{key}/P2/相控阵增益", ant["G_ant"], G_ref, tol=0.02)
            # 扫描损耗独立复算
            th = DE.to_f(cfg.get("θ_scan"), 0)
            if th > 0:
                sl_ref = -10 * 1.5 * math.log10(math.cos(math.radians(th)))
                chk(f"{key}/P2/扫描损耗cos^1.5", ant["scan_loss_db"], sl_ref, tol=1e-6)
            lines.append(f"  P2 增益(定制相控阵): N_el={N_el:.0f} η={eta} G_el=6dB θ_scan={th:.0f}° "
                         f"→ G={ant['G_ant']:.2f}dBi（独立式 {G_ref:.2f}）扫描损耗 {ant['scan_loss_db']:.3f}dB  一致")
        else:
            eta = ANT_TYPES.get(cfg.get("ant_type"), {}).get("eta_typ", 0.65)
            D = DE.to_f(cfg.get("D_ap"), 2.5)
            G_ref = my_gain_refl(D, lam_m, eta)
            chk(f"{key}/P2/反射面增益", ant["G_ant"], G_ref, tol=0.02)
            chk(f"{key}/P2/θ3dB≈70λ/D", ant["θ_3dB"], 70.0 * lam_m / D, tol=1e-9)
            # 与 grasp_bridge 独立实现对拍（同 η）
            gb_g = GB.peak_gain_dbi(D, f_dn, eta)
            chk(f"{key}/P2/grasp_bridge对拍", gb_g, G_ref, tol=0.02)
            lines.append(f"  P2 增益(定制反射面): D={D}m λ={lam_m*100:.2f}cm η={eta} → "
                         f"G={ant['G_ant']:.2f}dBi（独立式 {G_ref:.2f} / grasp_bridge {gb_g:.2f}）"
                         f" θ3dB={ant['θ_3dB']:.3f}°  三处一致")
        # 推导侧 antenna_gain_est 与校核侧 antenna_electrical 对拍
        chk(f"{key}/P2/推导-校核同源", der["G_ant_est"], ant["G_ant"], tol=0.02)
    else:
        # 货架天线：G_ant 必须等于所用货架产品增益（手动覆盖通道）
        src = ant.get("G_source")
        ok_ovr = (src == "手动覆盖") and abs(ant["G_ant"] - DE.to_f(p.get("G_ant_ovr"), -1)) < 1e-9
        if not ok_ovr:
            fails.append(f"{key}/P2/货架增益覆盖: G_source={src} G={ant['G_ant']}")
        lines.append(f"  P2 增益(货架): {ant['G_ant']:.2f}dBi = 货架产品增益注入（G_source={src}）  OK")
    # 超增益物理上限：G ≤ η_max(πD/λ)²（η_max=0.82 物理极限，含口面效率上限）
    D_phys = DE.to_f(p.get("D_ap"), 0)
    if D_phys > 0 and cfg.get("ant_type") != "相控阵":
        g_max = my_gain_refl(D_phys, lam_m, 0.82)
        if ant["G_ant"] > g_max + 0.01:
            fails.append(f"{key}/P2/超增益: G={ant['G_ant']:.2f} > 物理上限 {g_max:.2f}")
        lines.append(f"  P2 物理上限: G={ant['G_ant']:.2f} ≤ η0.82 极限 {g_max:.2f}dBi  OK")

    # ---- P3 T_sys Friis 级联 ----
    # 独立重建链解析规则（文档口径）：相控阵→ant_rx_path，其他→uplink；
    # KG 缺节点或链中无首级放大器 → 合成默认链（相控阵 tr_module / 其他 lna+dconv），
    # 既有无源拓扑保留在前。链结构取自 KG+UNITS 数据（非引擎算术），
    # Friis 级联算术全部手工复算。
    from infoflow_data import UNITS as _UNITS
    ont = {o["id"]: o for o in KG["ontologies"]}
    rx_id = gt.get("rx_chain_id")
    base_chain = (ont.get(rx_id) or {}).get("chain") or []
    has_amp = any((_UNITS.get(v) or {}).get("kind") == "amp"
                  and DE.to_f((_UNITS.get(v) or {}).get("nf_db"), 0) > 0 for v in base_chain)
    if base_chain and has_amp:
        chain_ref = base_chain
        synth_ref = False
    else:
        dft = ["tr_module"] if p.get("ant_type") == "相控阵天线" else ["lna", "dconv"]
        chain_ref = (base_chain + dft) if base_chain else dft
        synth_ref = True
    if bool(gt.get("rx_chain_synthesized")) != synth_ref:
        fails.append(f"{key}/P3/合成链标志: 引擎={gt.get('rx_chain_synthesized')} 独立={synth_ref}")
    T_ref = gt["T_ant"]
    cum = 0.0
    n_amp = 0
    for vid in chain_ref:
        u = _UNITS.get(vid) or {}
        g = DE.to_f(u.get("g_db"), 0.0)
        nf = DE.to_f(u.get("nf_db"), 0.0)
        kind = u.get("kind", "pass")
        # lna 级用户覆盖：NF_lna/G_lna 注入（与 unit_params 同语义）
        if vid == "lna":
            g = DE.to_f(p.get("G_lna"), g)
            nf = DE.to_f(p.get("NF_lna"), nf)
        if kind == "amp" and nf > 0:
            td_ref = (10 ** (nf / 10.0) - 1) * 290.0
            n_amp += 1
        elif kind == "pass" and g < 0:
            td_ref = (10 ** (-g / 10.0) - 1) * 290.0
        else:
            td_ref = 0.0
        contrib_ref = td_ref / (10 ** (cum / 10.0)) if cum != 0 else td_ref
        T_ref += contrib_ref
        cum += g
    chk_rel(f"{key}/P3/T_sys级联", gt["T_sys"], T_ref, rel=1e-6)
    nf_ref = 10 * math.log10(1 + T_ref / 290.0)
    chk(f"{key}/P3/NF_total", gt["NF_total_db"], nf_ref, tol=1e-6)
    chk(f"{key}/P3/GT定义", gt["GT"], ant["G_ant"] - 10 * math.log10(T_ref), tol=0.02)
    if gt["T_sys"] < gt["T_ant"] - 1e-9:
        fails.append(f"{key}/P3/T_sys<T_ant 非物理")
    # P3b 首级放大器噪声不得漏算：T_sys 必须 > T_ant（接收机贡献>0）
    if gt["T_sys"] <= gt["T_ant"] + 1e-6:
        fails.append(f"{key}/P3b/接收机噪声缺失: T_sys={gt['T_sys']:.2f} ≈ T_ant={gt['T_ant']:.2f}")
    if n_amp < 1:
        fails.append(f"{key}/P3b/链中无放大器级（物理不可能）")
    # P3c 推导侧/校核侧一致：_derived.t_sys[本体制] == gt.T_sys
    fam_self = {"相控阵天线": "相控阵"}.get(p.get("ant_type"), cfg.get("ant_type", ""))
    t_der = der.get("t_sys", {}).get(fam_self)
    if t_der is None:
        fails.append(f"{key}/P3c/推导侧无 {fam_self} 口径")
    else:
        chk_rel(f"{key}/P3c/推导-校核同源", t_der, gt["T_sys"], rel=1e-9)
    lines.append(f"  P3 T_sys: 链[{rx_id}{'/合成' if synth_ref else ''}]={'+'.join(chain_ref)} "
                 f"Friis 独立级联 = {T_ref:.2f}K (引擎 {gt['T_sys']:.2f}K) NF={nf_ref:.2f}dB → "
                 f"G/T={gt['GT']:.2f}dB/K；推导侧 {t_der if t_der is None else round(t_der,2)}K  一致")

    # ---- P4 ΣL 分项合成 ----
    avail = DE.to_f(p.get("A_avail"), 99.9)
    A_dyn = der["A_dyn"]
    for lk, nm, aref, aatm in ((up, "up", p["A_up_ref"], p["A_atm"]),
                               (dn, "dn", p["A_dn_ref"], p["A_atm_dl"])):
        rain_ref = my_rain(aref, avail, el)
        chk(f"{key}/P4/{nm}雨衰", lk["A_rain"], rain_ref, tol=1e-6)
        lpnt_ref = 12.0 * (DE.to_f(p.get("θ_e"), 0.05) / max(ant["θ_3dB"], 1e-6)) ** 2
        chk(f"{key}/P4/{nm}指向损耗", lk["L_pnt"], lpnt_ref, tol=1e-6)
        sum_ref = rain_ref + aatm + lpnt_ref + 0.3 + 1.0
        if nm == "up":
            sum_ref += A_dyn          # 推导侧 ΣL 含 A_dyn；预算侧 rf_link_budget 不含（引擎口径）
        # 预算侧 sum_L 不含 A_dyn（A_dyn 只进需求反推，保守侧）
        sum_budget = rain_ref + aatm + lpnt_ref + 0.3 + 1.0
        chk(f"{key}/P4/{nm}ΣL", lk["sum_L"], sum_budget, tol=1e-6)
    lines.append(f"  P4 ΣL: 雨衰 A∝p^−0.6·sin30/sin(el)（up={up['A_rain']:.3f} dn={dn['A_rain']:.3f}dB "
                 f"@{avail}%）+ 大气 + 指向 12(θe/θ3)² + 极化0.3 + 实现1.0  逐项一致（A_dyn={A_dyn}dB 仅进需求侧）")

    # ---- P5 需求反推 ----
    req = r["req"]
    B_car = DE.to_f(p.get("B_carrier"), 125)
    B_beam = DE.to_f(p.get("B_beam"), 125)
    M_t = DE.to_f(p.get("M_target"), 3.0)
    CN_des = req["design_cn"]
    B_hz = 10 * math.log10(B_car * 1e6)
    lfs_up_ref = my_fspl(geo["d_slant"], f_up)
    lfs_dn_ref = my_fspl(geo["d_slant"], f_dn)
    chk(f"{key}/P5/Lfs_up", der["Lfs_up"], lfs_up_ref, tol=0.02)
    chk(f"{key}/P5/Lfs_dn", der["Lfs_dn"], lfs_dn_ref, tol=0.02)
    sum_up = der["rain_up"] + p["A_atm"] + der["L_pnt"] + 0.3 + 1.0 + A_dyn
    sum_dn = der["rain_dn"] + p["A_atm_dl"] + der["L_pnt"] + 0.3 + 1.0 + A_dyn
    chk(f"{key}/P5/ΣL_up含dyn", der["ΣL_up"], sum_up, tol=1e-6)
    chk(f"{key}/P5/ΣL_dn含dyn", der["ΣL_dn"], sum_dn, tol=1e-6)
    gt_req_ref = CN_des + M_t + B_hz - req["EIRP_term"] + lfs_up_ref + sum_up + KDB
    eirp_req_ref = (CN_des + M_t + B_hz - req["GT_term"] + lfs_dn_ref + sum_dn + KDB
                    + 10 * math.log10(max(B_beam / B_car, 1.0)))
    chk(f"{key}/P5/GT_req", der["GT_req"], gt_req_ref, tol=0.02)
    chk(f"{key}/P5/EIRP_req", der["EIRP_req"], eirp_req_ref, tol=0.02)
    lines.append(f"  P5 需求反推: GT_req={der['GT_req']:.2f}dB/K EIRP_req={der['EIRP_req']:.2f}dBW "
                 f"（CN_des={CN_des} M_t={M_t} B={B_car}MHz 独立重建一致）")

    # ---- P6/P7 MODCOD + 端到端 ----
    mc_dn = my_modcod(dn["CN"], M_t)
    if mc_dn is None:
        if dn["modcod"] != "无法闭合（低于最低阶门限）":
            fails.append(f"{key}/P6/MODCOD 应为无法闭合, 引擎={dn['modcod']}")
    else:
        if dn["modcod"] != mc_dn["name"]:
            fails.append(f"{key}/P6/MODCOD: 引擎={dn['modcod']} 独立={mc_dn['name']}")
        chk(f"{key}/P6/CN_req", dn["CN_req"], mc_dn["cn_req"], tol=1e-9)
        chk(f"{key}/P6/η", dn["eta"], mc_dn["eta"], tol=1e-9)
    chk(f"{key}/P6/M_dn", dn["M"], dn["CN"] - dn["CN_req"], tol=1e-9)
    cntot_ref = my_total_cn(up["CN"], dn["CN"])
    chk(f"{key}/P7/CN_total", e2e["CN_total"], cntot_ref, tol=1e-9)
    regen_ref = DE.to_f(p.get("ΔM_reg"), 4.5) if p.get("arch") == "再生转发器" else 0.0
    mc_tot = my_modcod(cntot_ref, M_t)
    m_e2e_ref = cntot_ref - (mc_tot["cn_req"] if mc_tot else MODCOD[0]["cn_req"]) + regen_ref
    chk(f"{key}/P7/M_e2e", e2e["M"], m_e2e_ref, tol=1e-9)
    chk(f"{key}/P7/regen_bonus", e2e["regen_bonus"], regen_ref, tol=1e-9)
    lines.append(f"  P6/P7: MODCOD_dn={dn['modcod']}（独立选档一致） CN_total={cntot_ref:.2f}dB "
                 f"= −10lg(10^−{up['CN']:.2f}/10+10^−{dn['CN']:.2f}/10)  M_e2e={e2e['M']:.2f}dB "
                 f"(regen +{regen_ref})  一致")

    # ---- P8 容量/频谱 ----
    N_beam = DE.to_f(p.get("N_beam"), 0)
    n_pol = DE.to_f(p.get("n_pol"), 2)
    B_total = DE.to_f(p.get("B_total"), 2500)
    k_reuse = DE.to_f(p.get("k_reuse"), 4)
    c12 = next(c for c in res["constraints"] if c["id"] == "c-12")
    c13 = next(c for c in res["constraints"] if c["id"] == "c-13")
    c_sys_ref = N_beam * B_beam * dn["eta"] * n_pol / 1000.0
    c_sys_eng = next(it[1] for it in c12["items"] if it[0] == "C_sys")
    chk_rel(f"{key}/P8/C_sys", c_sys_eng, c_sys_ref, rel=1e-9)
    if c12["ok"] != (c_sys_ref >= req["C_req"]):
        fails.append(f"{key}/P8/c-12判定: ok={c12['ok']} 独立={c_sys_ref >= req['C_req']}")
    lhs, rhs = N_beam * B_beam, B_total * k_reuse
    if c13["ok"] != (lhs <= rhs):
        fails.append(f"{key}/P8/c-13判定: ok={c13['ok']} 独立={lhs <= rhs}")
    lines.append(f"  P8 容量: C_sys={c_sys_ref:.2f}Gbps（{N_beam:.0f}×{B_beam:.0f}MHz×η{dn['eta']:.2f}"
                 f"×{n_pol:.0f}pol）vs C_req={req['C_req']}Gbps → {'满足' if c_sys_ref>=req['C_req'] else '缺口'}；"
                 f"频谱 {lhs:.0f}≤{rhs:.0f}MHz → {'闭合' if lhs<=rhs else '冲突'}  与引擎判定一致")

    # ---- P9 质量功耗链 ----（引擎输出经 round(·,1)，容差取 0.051 绝对值）
    m_raw_ref = sum(DE.to_f(row["mass"], 0) for row in r["equipment"])
    p_raw_ref = sum(DE.to_f(row["power"], 0) for row in r["equipment"])
    if abs(totals["m_est"] - m_raw_ref) > 0.051:
        fails.append(f"{key}/P9/m_est: {totals['m_est']} vs Σrows {m_raw_ref:.3f}")
    if abs(totals["p_est"] - p_raw_ref) > 0.051:
        fails.append(f"{key}/P9/p_est: {totals['p_est']} vs Σrows {p_raw_ref:.3f}")
    if abs(totals["m_pay"] - m_raw_ref * 1.2) > 0.051:
        fails.append(f"{key}/P9/m_pay: {totals['m_pay']} vs 1.2×{m_raw_ref:.3f}")
    if abs(totals["p_pay"] - p_raw_ref * 1.2) > 0.051:
        fails.append(f"{key}/P9/p_pay: {totals['p_pay']} vs 1.2×{p_raw_ref:.3f}")
    plat = r["platform"]
    if plat:
        pl = plat[1]
        feas_ref = pl["m_pay"] >= totals["m_pay"] and pl["p_pay"] >= totals["p_pay"]
        # 同轨道候选中独立复算可行域
        cands_ref = [q for q in PLATFORMS if q["orbit"] == cfg.get("orbit", "GEO")
                     and q["m_pay"] >= totals["m_pay"] and q["p_pay"] >= totals["p_pay"]]
        gap_ref = len(cands_ref) == 0
        if bool(p.get("_plat_gap")) != gap_ref:
            fails.append(f"{key}/P9/平台缺口: 引擎={bool(p.get('_plat_gap'))} 独立={gap_ref}")
        if not gap_ref and not feas_ref:
            fails.append(f"{key}/P9/所选平台不可行: {pl['id']}")
        lines.append(f"  P9 质量功耗: Σrows={m_raw_ref:.1f}kg/{p_raw_ref:.1f}W ×1.2 → "
                     f"{totals['m_pay']:.1f}kg/{totals['p_pay']:.1f}W；平台 {pl['id']} "
                     f"承载 {pl['m_pay']}kg/{pl['p_pay']}W → {'可行' if feas_ref else '缺口'}"
                     f"（独立可行域 {len(cands_ref)} 个候选，判定一致）")
    else:
        if not p.get("_plat_gap"):
            fails.append(f"{key}/P9/无平台且无 _plat_gap")
        lines.append(f"  P9 质量功耗: {totals['m_pay']:.1f}kg/{totals['p_pay']:.1f}W → 无可行平台，"
                     f"_plat_gap 已给出（诊断口径一致）")

    # ---- P10 激光链路 ----
    for lk_name in ("laser_isl", "laser_sgl"):
        lz = res.get(lk_name)
        if not lz:
            continue
        D_o = DE.to_f(p.get("D_opt"), 135) / 1000.0
        lam_o = DE.to_f(p.get("λ_opt"), 1550) * 1e-9
        eta_o = DE.to_f(p.get("η_opt"), 60) / 100.0
        g_opt_ref = my_gain_refl(D_o, lam_o, eta_o)          # 同口径公式
        chk(f"{key}/P10/G_opt", lz["G_opt_db"], g_opt_ref, tol=1e-6)
        d_o = lz["d_km"] * 1000.0
        lfs_o_ref = 20 * math.log10(4 * math.pi * d_o / lam_o)
        chk(f"{key}/P10/L_fs_opt", lz["L_fs_opt"], lfs_o_ref, tol=1e-6)
        lp_o_ref = 12.0 * (DE.to_f(p.get("σ_jit"), 3) / DE.to_f(p.get("θ_div"), 100)) ** 2
        chk(f"{key}/P10/L_point", lz["L_point"], lp_o_ref, tol=1e-6)
        ptx_dbm = 10 * math.log10(DE.to_f(p.get("P_opt"), 1.0) * 1000.0)
        prx_ref = (ptx_dbm + min(DE.to_f(p.get("G_edfa"), 25), 20.0) + 2 * g_opt_ref
                   - lfs_o_ref - lp_o_ref - lz["L_turb"] - lz["L_atm"] - 1.5)
        chk(f"{key}/P10/P_rx", lz["P_rx_dbm"], prx_ref, tol=1e-6)
        R_o = max(DE.to_f(p.get("R_isl" if lk_name == "laser_isl" else "R_sgl"), 10), 0.01)
        preq_ref = DE.to_f(p.get("S_opt"), -42) + 10 * math.log10(R_o)
        chk(f"{key}/P10/P_req", lz["P_req_dbm"], preq_ref, tol=1e-6)
        chk(f"{key}/P10/M_laser", lz["M_db"], prx_ref - preq_ref, tol=1e-6)
        lines.append(f"  P10 激光[{lk_name}]: G_opt={g_opt_ref:.2f}dB L_fs={lfs_o_ref:.2f}dB "
                     f"P_rx={prx_ref:.2f}dBm M={lz['M_db']:.2f}dB  全链独立复算一致")

    # ---- P11 评级规则 ----
    hard_ok = all(c["ok"] for c in ev["criteria"] if c["kind"] == "hard")
    n_soft_pass = sum(1 for c in ev["criteria"] if c["kind"] == "soft" and c["ok"])
    grade_ref = ("A" if n_soft_pass >= 4 else "B" if n_soft_pass >= 2 else "C") if hard_ok else "D"
    if ev["grade"] != grade_ref:
        fails.append(f"{key}/P11/评级: 引擎={ev['grade']} 独立={grade_ref}")
    if ev["feasible"] != hard_ok:
        fails.append(f"{key}/P11/feasible: 引擎={ev['feasible']} 独立={hard_ok}")
    # E1~E5/E10 hard 判据与 summary/constraints 交叉一致
    fail_ids = set(s.get("fail") or [])
    e3_ok = ("c-13" not in fail_ids)
    e4_ok = ("c-12" not in fail_ids)
    crit = {c["id"]: c for c in ev["criteria"]}
    if crit["E3"]["ok"] != (e3_ok and bool(der.get("freq_ok"))):
        fails.append(f"{key}/P11/E3 不自洽")
    if crit["E4"]["ok"] != e4_ok:
        fails.append(f"{key}/P11/E4 不自洽")
    lines.append(f"  P11 评级: hard={'全过' if hard_ok else '有失败'} soft={n_soft_pass}/4 → "
                 f"独立评级={grade_ref} 引擎={ev['grade']} feasible={ev['feasible']}  一致")

    # ---- P12 评分 ----
    w = score["weights"]
    tot_ref = sum(score["dims"][k2] * w[k2] for k2 in w)
    chk(f"{key}/P12/加权总分", score["total"], tot_ref, tol=0.011)
    chk(f"{key}/P12/权重和", sum(w.values()), 1.0, tol=1e-9)
    for k2, v in score["dims"].items():
        if not (0.0 <= v <= 10.0):
            fails.append(f"{key}/P12/维度越界 {k2}={v}")
    lines.append(f"  P12 评分: dims={score['dims']} Σw·dim={tot_ref:.2f} = total {score['total']}  一致")

    # ---- P13 阵面功耗口径 ----
    if cfg.get("ant_type") == "相控阵":
        sub = cfg.get("array_subtype", "")
        p_tr_ref = ARR_P_PER_EL.get(sub, 0.9)
        chk(f"{key}/P13/P_tr偏置口径", DE.to_f(p.get("P_tr"), -1), p_tr_ref, tol=1e-9)
        c16 = next(c for c in res["constraints"] if c["id"] == "c-16")
        pface_ref = DE.to_f(p.get("N_el"), 0) * p_tr_ref
        pface_eng = next(it[1] for it in c16["items"] if it[0] == "阵面功耗 N_el×P_tr")
        chk_rel(f"{key}/P13/P_face", pface_eng, max(pface_ref, 1e-12), rel=1e-9)
        lines.append(f"  P13 阵面功耗: P_tr={p_tr_ref}W/元（{sub}偏置口径）× N_el="
                     f"{DE.to_f(p.get('N_el'),0):.0f} = {pface_ref:.0f}W  一致")

    # ---- P14 数值卫生 ----
    def scan_nan(obj, path=""):
        bad = []
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                bad.append(path)
        elif isinstance(obj, dict):
            for k2, v in obj.items():
                bad += scan_nan(v, f"{path}.{k2}")
        elif isinstance(obj, (list, tuple)):
            for i2, v in enumerate(obj):
                bad += scan_nan(v, f"{path}[{i2}]")
        return bad
    nan_hits = scan_nan({kk: r[kk] for kk in ("geo", "params", "totals", "score", "eval")})
    nan_hits += scan_nan({kk: res[kk] for kk in ("summary", "eirp", "gt", "uplink", "downlink", "e2e")})
    if nan_hits:
        fails.append(f"{key}/P14/NaN-Inf: {nan_hits[:5]}")
    try:
        json.dumps({"eval": ev, "score": score, "summary": s}, ensure_ascii=False, default=str)
        js_ok = True
    except Exception as ex:
        js_ok = False
        fails.append(f"{key}/P14/JSON: {ex}")
    lines.append(f"  P14 数值卫生: 无 NaN/Inf（{'0' if not nan_hits else len(nan_hits)} 命中）"
                 f"，eval/score/summary 可 JSON 序列化={js_ok}")

# ================================================================
lines.append("")
lines.append("=" * 100)
n_total = len(fails)
if fails:
    lines.append(f"独立复算不一致 {n_total} 项：")
    for f_ in fails:
        lines.append("  !! " + f_)
    lines.append("RESULT: FAIL")
else:
    lines.append("P0~P14 全部独立复算一致 —— 引擎物理与业务计算数学正确（含解析锚点）。")
    lines.append("RESULT: PASS")
lines.append("=" * 100)

out = "\n".join(lines)
with open(os.path.join(HERE, "_verify_physics_out.txt"), "w", encoding="utf-8") as f:
    f.write(out + "\n")
print(out[-4000:])
print(f"\nFAILS={len(fails)}")
