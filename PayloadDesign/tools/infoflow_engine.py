# -*- coding: utf-8 -*-
"""载荷信息流仿真软件 —— 计算引擎。

核心模型：信号沿 chain 逐级流动。
  发射链(tx)：P_out(dBW) → 每级 g_db 累加 → 出口功率 → +G_ant −L_feed = EIRP
  接收链(rx)：天线口 T_ant → 逐级 Friis 级联噪声温度 → T_sys → G/T = G_ant − 10lg(T_sys)
  空间段    ：c-7 FSPL → c-8 C/N0 → c-9 C/N → MODCOD 自适应 → c-10 余量 → c-11 容量
  激光链    ：G_opt → EIRP_opt → L_fs_opt → 指向抖动/湍流代价 → 接收功率 → 灵敏度余量
  数据链    ：c-20 总线速率/存储容量闭环
  系统级    ：c-12/c-13/c-14/c-15/c-16/c-17/c-18/c-21/c-22/c-23/c-25

所有公式与判据 id 均对齐知识图谱 constraints[].id，结果可追溯到具体约束。
"""
from __future__ import annotations
import math

from infoflow_data import UNITS, BANDS, MODCOD, LINK_META

K_BOLTZ_DB = -228.6          # dBW/Hz/K，c-8
C_LIGHT = 299792458.0        # m/s


# ================================================================
# 工具
# ================================================================
def to_f(v, default=0.0):
    """容错转 float：空串/None/非法 → default"""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def dbm2w(dbm):
    return 10 ** ((dbm - 30) / 10.0)


def w2dbm(w):
    """W → dBm（= dBW + 30）"""
    return 10 * math.log10(w) + 30.0 if w > 0 else -999.0


def w2dbw(w):
    return 10 * math.log10(w) if w > 0 else -999.0


def fmt(v, nd=2, unit=""):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    try:
        if math.isnan(v) or math.isinf(v):
            return "—"
    except TypeError:
        return str(v)
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".") if "." in f"{v:.{nd}f}" else f"{v:.{nd}f}"
    return f"{s}{unit}" if unit else s


def lam_m(f_ghz):
    """波长(m)：f 单位 GHz"""
    f = to_f(f_ghz)
    return C_LIGHT / (f * 1e9) if f > 0 else 0.0


# ================================================================
# 一、逐级信号流（chain propagation）
# ================================================================
def unit_params(vid, p):
    """按当前参数解析单机的实际增益/噪声/功耗/质量（支持用户覆盖）。"""
    u = UNITS.get(vid)
    if not u:
        return dict(id=vid, cn=vid, kind="pass", g_db=0.0, nf_db=0.0, p_w=0.0, m_kg=0.0,
                    note="知识图谱节点（无电气默认值）", specs={}, overridden=False)
    g = u.get("g_db", 0.0)
    nf = u.get("nf_db", 0.0)
    pw = u.get("p_w", 0.0)
    mk = u.get("m_kg", 0.0)
    specs = dict(u.get("specs", {}))
    note = u.get("note", "")
    ovr = False

    # --- 用户参数覆盖关键单机 ---
    if vid == "lna":
        g = to_f(p.get("G_lna"), g)
        nf = to_f(p.get("NF_lna"), nf)
        specs["G_lna"], specs["NF_lna"] = g, nf
        ovr = True
    elif vid == "twta":
        specs["P_twta"] = to_f(p.get("P_out"), specs.get("P_twta")) if p.get("amp_type") == "TWTA" else specs.get("P_twta")
        specs["η_twta"] = to_f(p.get("η_pa"), specs.get("η_twta")) if p.get("amp_type") == "TWTA" else specs.get("η_twta")
        # TWTA 饱和增益近似 50dB；功放级增益按 P_out 与输入电平差体现
        ovr = True
    elif vid == "sspa":
        specs["P_sspa"] = to_f(p.get("P_out"), specs.get("P_sspa")) if p.get("amp_type") == "SSPA" else specs.get("P_sspa")
        specs["η_sspa"] = to_f(p.get("η_pa"), specs.get("η_sspa")) if p.get("amp_type") == "SSPA" else specs.get("η_sspa")
        specs["IMD3"] = to_f(p.get("IMD3"), specs.get("IMD3"))
        ovr = True
    elif vid == "mpa":
        specs["P_sspa"] = to_f(p.get("P_out"), 100.0) if p.get("amp_type") == "MPA" else 100.0
        specs["η_sspa"] = to_f(p.get("η_pa"), specs.get("η_sspa")) if p.get("amp_type") == "MPA" else specs.get("η_sspa")
        ovr = True
    elif vid == "tr_module":
        specs["T_j"] = to_f(p.get("T_j"), specs.get("T_j"))
        specs["P_tr"] = to_f(p.get("P_tr"), specs.get("P_tr"))
        pw = specs["P_tr"]
        ovr = True
    elif vid == "circulator":
        specs["I_iso"] = to_f(p.get("I_iso"), specs.get("I_iso"))
        ovr = True
    elif vid == "tx_filter":
        specs["A_rej"] = to_f(p.get("A_rej"), specs.get("A_rej"))
        ovr = True
    elif vid == "switch_matrix":
        specs["I_sw"] = to_f(p.get("I_sw"), specs.get("I_sw"))
        ovr = True
    elif vid == "feed":
        specs["η_ill"] = to_f(p.get("η_ill"), specs.get("η_ill"))
        ovr = True
    elif vid == "deploy":
        specs["δ_dep"] = to_f(p.get("δ_dep"), specs.get("δ_dep"))
        ovr = True
    elif vid == "pointing":
        specs["Δ_pnt"] = to_f(p.get("Δ_pnt"), specs.get("Δ_pnt"))
        ovr = True
    elif vid == "beam_former":
        specs["N_bf"] = to_f(p.get("N_bf"), specs.get("N_bf"))
        ovr = True
    elif vid == "beam_port":
        specs["N_port"] = to_f(p.get("N_port"), specs.get("N_port"))
        ovr = True
    elif vid == "cal_network":
        specs["Δ_cal"] = to_f(p.get("Δ_cal"), specs.get("Δ_cal"))
        ovr = True
    elif vid == "dswitch":
        specs["C_dsw"] = to_f(p.get("C_dsw"), specs.get("C_dsw"))
        pw = 45.0 + 0.35 * max(0.0, specs["C_dsw"] - 100)
        ovr = True
    elif vid == "adc":
        pw = 25.0 * max(1, int(to_f(p.get("N_ch"), 32)) // 8)
        specs["N_ch"] = to_f(p.get("N_ch"), 32)
        specs["B_sub"] = to_f(p.get("B_sub"), 40)
        ovr = True
    elif vid == "dac":
        pw = 20.0 * max(1, int(to_f(p.get("N_ch"), 32)) // 8)
        ovr = True
    elif vid == "atp_coarse":
        specs["P_acq"] = to_f(p.get("P_acq"), specs.get("P_acq"))
        specs["t_acq"] = to_f(p.get("t_acq"), specs.get("t_acq"))
        ovr = True
    elif vid == "fsm":
        specs["σ_track"] = to_f(p.get("σ_track"), specs.get("σ_track"))
        specs["θ_fsm"] = to_f(p.get("θ_fsm"), specs.get("θ_fsm"))
        ovr = True
    elif vid == "tx_laser":
        specs["P_opt"] = to_f(p.get("P_opt"), specs.get("P_opt"))
        ovr = True
    elif vid == "edfa":
        specs["G_edfa"] = to_f(p.get("G_edfa"), specs.get("G_edfa"))
        g = specs["G_edfa"]
        ovr = True
    elif vid == "optical_antenna":
        specs["D_opt"] = to_f(p.get("D_opt"), specs.get("D_opt"))
        ovr = True
    elif vid == "photodetector":
        specs["S_opt"] = to_f(p.get("S_opt"), specs.get("S_opt"))
        ovr = True
    elif vid == "dpsk_modem":
        specs["CN_dpsk"] = to_f(p.get("CN_dpsk"), specs.get("CN_dpsk"))
        ovr = True
    elif vid == "data_bus":
        specs["R_bus"] = to_f(p.get("R_bus"), specs.get("R_bus"))
        ovr = True
    elif vid == "storage":
        specs["E_store"] = to_f(p.get("E_store"), specs.get("E_store"))
        ovr = True
    elif vid == "dpu":
        specs["CR"] = to_f(p.get("CR"), specs.get("CR"))
        specs["R_dpu"] = to_f(p.get("R_dpu"), specs.get("R_dpu"))
        ovr = True
    elif vid == "baseband":
        specs["R_bb"] = to_f(p.get("R_bb"), specs.get("R_bb"))
        ovr = True
    elif vid == "ai_unit":
        specs["AI_TOPS"] = to_f(p.get("AI_TOPS"), specs.get("AI_TOPS"))
        ovr = True
    elif vid == "obc_payload":
        specs["MIPS"] = to_f(p.get("MIPS"), specs.get("MIPS"))
        ovr = True
    elif vid == "reconfig_ctrl":
        specs["t_rec"] = to_f(p.get("t_rec"), specs.get("t_rec"))
        ovr = True
    elif vid == "router_unit":
        specs["N_route"] = to_f(p.get("N_route"), specs.get("N_route"))
        ovr = True

    return dict(id=vid, cn=u["cn"], kind=u["kind"], g_db=float(g), nf_db=float(nf),
                p_w=float(pw), m_kg=float(mk), note=note, specs=specs, overridden=ovr)


def propagate_tx(chain, p):
    """发射链逐级信号流。

    返回 stages: [{seq, id, cn, kind, g_db, p_in_dbw, p_out_dbw, note, specs}]
    以及出口功率与累计插损。功放级按「饱和输出功率」置电平（而非线性增益），
    以体现 EIRP = P_out + G_ant − L_feed − L_tx 的工程语义。
    """
    amp_type = p.get("amp_type", "TWTA")
    amp_vid = {"TWTA": "twta", "SSPA": "sspa", "MPA": "mpa"}.get(amp_type, "twta")
    amp_pout_w = to_f(p.get("P_out"), 180.0)
    amp_pout_dbw = w2dbw(amp_pout_w)

    # 输入电平：上变频前的中频电平，取功放回退前的驱动电平（典型 +10dBm = −20dBW）
    cur = -20.0
    stages, total_loss, total_gain = [], 0.0, 0.0
    amp_seen = False

    for i, vid in enumerate(chain, 1):
        u = unit_params(vid, p)
        if vid == amp_vid:
            # 功放级：直接置为饱和输出功率（含回退由用户 P_out 体现）
            g_eff = amp_pout_dbw - cur
            p_in, p_out = cur, amp_pout_dbw
            amp_seen = True
            note = f"{amp_type} 饱和输出 {fmt(amp_pout_w,1)}W = {fmt(amp_pout_dbw,2)}dBW；" \
                   f"本级等效增益 {fmt(g_eff,2)}dB；P_dc = P_out/η = " \
                   f"{fmt(amp_pout_w/max(1e-6,to_f(p.get('η_pa'),58)/100),1)}W"
        elif u["kind"] == "amp" and not amp_seen:
            # 前级有源（如 LNA 在再生链中）：按增益线性放大
            p_in, p_out = cur, cur + u["g_db"]
            g_eff = u["g_db"]
            total_gain += max(0.0, u["g_db"])
            note = u["note"] or f"增益 {fmt(u['g_db'],2)}dB"
        elif u["kind"] in ("dig", "ctrl", "mech", "opt"):
            # 数字/控制/机构/光学级不改变射频电平（光链路另算）
            p_in, p_out = cur, cur + u["g_db"]
            g_eff = u["g_db"]
            if u["g_db"] < 0:
                total_loss += -u["g_db"]
            note = u["note"] or "电平不变（数字/控制域）"
        else:
            # 无源损耗级
            p_in, p_out = cur, cur + u["g_db"]
            g_eff = u["g_db"]
            if u["g_db"] < 0:
                total_loss += -u["g_db"]
            note = u["note"] or f"插损 {fmt(-u['g_db'],2)}dB"
        stages.append(dict(seq=i, id=vid, cn=u["cn"], kind=u["kind"], g_db=g_eff,
                           p_in=p_in, p_out=p_out, note=note, specs=u["specs"],
                           p_w=u["p_w"], m_kg=u["m_kg"]))
        cur = p_out

    return dict(stages=stages, p_exit_dbw=cur, total_loss_db=total_loss,
                total_gain_db=total_gain, amp_dbw=amp_pout_dbw, amp_w=amp_pout_w)


def propagate_rx(chain, p, T_ant=None):
    """接收链逐级 Friis 噪声级联。

    T_sys = T_ant·ΠL_i + Σ_j (T_j · Π L_after_j) / Π G_before_j
    返回 stages（含每级累计增益、本级噪声贡献）与 T_sys、NF_total。
    """
    if T_ant is None:
        T_ant = to_f(p.get("T_ant"), 50.0)

    us = [unit_params(vid, p) for vid in chain]
    stages, cum_g = [], 0.0          # cum_g = 该级之前的累计增益(dB)
    T_total = T_ant                  # 天线噪声经馈线后进入接收机
    # 天线口到第一级之间若无损耗，T_ant 直接计入
    for i, (vid, u) in enumerate(zip(chain, us)):
        L_lin = 10 ** (-u["g_db"] / 10.0) if u["g_db"] < 0 else 1.0   # 无源损耗线性
        G_lin = 10 ** (u["g_db"] / 10.0) if u["g_db"] > 0 else 1.0
        if u["kind"] == "amp" and u["nf_db"] > 0:
            F = 10 ** (u["nf_db"] / 10.0)
            T_dev = (F - 1) * 290.0
        elif u["kind"] == "pass" and u["g_db"] < 0:
            T_dev = (L_lin - 1) * 290.0        # 无源器件噪声 = (L−1)·T_phys
        else:
            T_dev = 0.0
        # 本级噪声折算到天线口：除以之前累计增益
        contrib = T_dev / (10 ** (cum_g / 10.0)) if cum_g != 0 else T_dev
        stages.append(dict(seq=i + 1, id=vid, cn=u["cn"], kind=u["kind"], g_db=u["g_db"],
                           nf_db=u["nf_db"], T_dev=T_dev, cum_g_db=cum_g,
                           T_contrib=contrib, note=u["note"], specs=u["specs"],
                           p_w=u["p_w"], m_kg=u["m_kg"]))
        T_total += contrib
        cum_g += u["g_db"]

    NF_total = 10 * math.log10(1 + T_total / 290.0) if T_total > 0 else 0.0
    return dict(stages=stages, T_sys=T_total, NF_total_db=NF_total,
                G_rx_total_db=cum_g, T_ant=T_ant)


# KG 缺接收链节点（如旧版图谱无 ant_rx_path）或链中无首级放大器（如仅有
# reflector/feed_array/beam_ctrl 无源拓扑）时按体制合成的物理默认链：
#   相控阵 → tr_module（T/R 组件接收通道即首级低噪放，NF≈2dB）
#   其他   → lna→dconv（标准接收前端；uplink 链前部无源节点 g=0 不影响噪声）
# 保证「首级放大器噪声不被漏算」（否则 T_sys=T_ant，G/T 偏乐观 6dB 量级）。
DEFAULT_RX_CHAIN = {"相控阵天线": ["tr_module"], "_default": ["lna", "dconv"]}


def _chain_has_amp(chain):
    return any((UNITS.get(vid) or {}).get("kind") == "amp"
               and to_f((UNITS.get(vid) or {}).get("nf_db"), 0) > 0 for vid in chain)


def resolve_rx_chain(ont, rx_chain_id, ant_type):
    """解析接收链；空链/缺节点/无首级放大器时合成默认链。返回 (chain, synthesized)。"""
    chain = (ont.get(rx_chain_id) or {}).get("chain") or []
    if chain and _chain_has_amp(chain):
        return chain, False
    synth = DEFAULT_RX_CHAIN.get(ant_type, DEFAULT_RX_CHAIN["_default"])
    # 保留 KG 既有无源拓扑（可追溯），在其后补首级放大器链
    return (chain + synth) if chain else synth, True


# ================================================================
# 二、天线电气（c-3 / c-4 / c-5 / c-6 / c-23）
# ================================================================
def antenna_electrical(p):
    f_dn = to_f(p.get("f_down"), 20.0)
    lam = lam_m(f_dn)                       # m
    lam_mm = lam * 1000
    at = p.get("ant_type", "反射面天线")
    eta = to_f(p.get("η_ill"), 68) / 100.0
    res = dict(lam_m=lam, lam_mm=lam_mm, ant_type=at)

    if at == "相控阵天线":
        N_el = to_f(p.get("N_el"), 1024)
        G_el = to_f(p.get("G_el"), 6.0)
        th_scan = to_f(p.get("θ_scan"), 0)
        # c-3: G_pa = 10lg(N_el × η) + G_el，扫描损耗 cos^1.5θ（增益扣减）
        G_pa = 10 * math.log10(max(N_el * eta, 1e-9)) + G_el
        scan_loss = -10 * 1.5 * math.log10(max(math.cos(math.radians(th_scan)), 1e-6)) if th_scan > 0 else 0.0
        G_calc = G_pa - scan_loss
        # 等效口径（阵面尺寸）
        D = to_f(p.get("D_ap"), 0.8)
        A_phys = math.pi * (D / 2) ** 2 if D > 0 else N_el * (lam / 2) ** 2
        res.update(formula="c-3", G_pa_db=G_pa, scan_loss_db=scan_loss,
                   A_phys_m2=A_phys, D_equiv_m=2 * math.sqrt(A_phys / math.pi))
        th3 = math.degrees(lam / max(D, 1e-6)) * 1.0 if D > 0 else 0
        # 阵面半功率波束宽度：θ ≈ 0.886λ/L（L 为阵面边长），方形阵 L=√A
        L_side = math.sqrt(A_phys)
        th3 = math.degrees(0.886 * lam / max(L_side, 1e-6))
        res["θ_3dB"] = th3
    else:
        D = to_f(p.get("D_ap"), 2.5)
        # c-4: G_refl = 10lg(η(πD/λ)²)，θ_3dB ≈ 70λ/D
        G_calc = 10 * math.log10(max(eta * (math.pi * D / lam) ** 2, 1e-9))
        res.update(formula="c-4", G_refl_db=G_calc, D_m=D,
                   A_phys_m2=math.pi * (D / 2) ** 2,
                   θ_3dB=70.0 * lam / D if D > 0 else 0)
        res["scan_loss_db"] = 0.0

    # 手动覆盖
    ovr = to_f(p.get("G_ant_ovr"), None)
    if p.get("G_ant_ovr") not in (None, "") and ovr is not None:
        G_ant = ovr
        res["G_source"] = "手动覆盖"
    else:
        G_ant = G_calc
        res["G_source"] = res["formula"]
    res["G_ant"] = G_ant

    # c-5 面精度：δ_surf ≤ λ/32
    lim = lam_mm / 32.0
    d_surf = to_f(p.get("δ_surf"), 0.20)
    d_dep = to_f(p.get("δ_dep"), 0.20)
    res["c5"] = dict(limit_mm=lim, δ_surf=d_surf, δ_dep=d_dep,
                     ok_surf=d_surf <= lim, ok_dep=d_dep <= d_surf,
                     ok=(d_surf <= lim and d_dep <= d_surf))

    # c-6 指向损耗：L_pnt = 12(θ_e/θ_3dB)²
    th_e = to_f(p.get("θ_e"), 0.05)
    th3 = res.get("θ_3dB", 0.5) or 0.5
    L_pnt = 12.0 * (th_e / th3) ** 2
    res["c6"] = dict(θ_e=th_e, θ_3dB=th3, L_pnt_db=L_pnt)

    # c-23 电气性能
    res["c23"] = dict(Δ_amp=to_f(p.get("Δ_amp"), 0.4), Δ_phs=to_f(p.get("Δ_phs"), 4.0),
                      SLL=to_f(p.get("SLL"), -22), AR=to_f(p.get("AR"), 1.5),
                      Δ_cal=to_f(p.get("Δ_cal"), 0.3),
                      ok=(to_f(p.get("Δ_amp"), 0.4) <= 0.5 and to_f(p.get("Δ_phs"), 4.0) <= 5.0
                          and to_f(p.get("SLL"), -22) <= -20 and to_f(p.get("AR"), 1.5) <= 3.0
                          and to_f(p.get("Δ_cal"), 0.3) <= to_f(p.get("Δ_amp"), 0.4)))
    return res


# ================================================================
# 三、EIRP / G/T（c-1 / c-2）
# ================================================================
def eirp_calc(p, ant, tx_flow):
    """c-1: EIRP = P_out + G_ant − L_feed − L_tx"""
    P_out_w = to_f(p.get("P_out"), 180.0)
    P_out_dbw = w2dbw(P_out_w)
    G_ant = ant["G_ant"]
    L_feed = to_f(p.get("L_feed"), 0.8)
    # L_tx：优先用用户值，否则由发射链无源级累加
    L_tx_user = to_f(p.get("L_tx"), None)
    L_tx_chain = sum(-s["g_db"] for s in tx_flow["stages"]
                     if s["g_db"] < 0 and s["id"] not in ("twta", "sspa", "mpa"))
    L_tx = L_tx_user if p.get("L_tx") not in (None, "") else L_tx_chain
    # 每波束功率分配（多波束：单波束功放功率 = 总功率 / 同时工作波束数的份额）
    EIRP = P_out_dbw + G_ant - L_feed - L_tx
    η_pa = to_f(p.get("η_pa"), 58) / 100.0
    P_dc = P_out_w / η_pa if η_pa > 0 else 0.0
    return dict(c="c-1", P_out_w=P_out_w, P_out_dbw=P_out_dbw, G_ant=G_ant,
                L_feed=L_feed, L_tx=L_tx, L_tx_chain=L_tx_chain,
                L_tx_source="用户输入" if p.get("L_tx") not in (None, "") else "发射链累加",
                EIRP=EIRP, P_dc_w=P_dc, η_pa_pct=to_f(p.get("η_pa"), 58))


def gt_calc(p, ant, rx_flow):
    """c-2: G/T = G_ant − 10lg(T_ant + T_rx)"""
    G_ant = ant["G_ant"]
    T_ovr = to_f(p.get("T_sys_ovr"), None)
    if p.get("T_sys_ovr") not in (None, "") and T_ovr and T_ovr > 0:
        T_sys = T_ovr
        src = "手动覆盖"
    else:
        T_sys = rx_flow["T_sys"]
        src = "接收链 Friis 级联"
    GT = G_ant - 10 * math.log10(T_sys) if T_sys > 0 else -999
    return dict(c="c-2", G_ant=G_ant, T_sys=T_sys, T_ant=rx_flow["T_ant"],
                T_rx=T_sys - rx_flow["T_ant"], GT=GT, source=src,
                NF_total_db=rx_flow["NF_total_db"])


# ================================================================
# 四、链路预算（c-7 ~ c-11, c-24）
# ================================================================
def rain_at_avail(A_ref, avail_pct, el_deg):
    """A(p) ∝ p^−0.6，并按 1/sin(el) 归一到 30°。
    A_ref 定义在 p=0.01%（99.99% 可用性）与 30° 仰角。"""
    p_ref = 0.01
    p = max(100.0 - to_f(avail_pct, 99.9), 1e-6)
    el = max(to_f(el_deg, 30), 5.0)
    k = (p / p_ref) ** (-0.6)
    # p 越大（可用性越低）雨衰越小
    A = to_f(A_ref, 0.0) * k
    # 仰角归一：路径长度 ∝ 1/sin(el)，以 30° 为参考
    A *= (math.sin(math.radians(30)) / math.sin(math.radians(el)))
    return A


def fspl(d_km, f_ghz):
    """c-7: L_fs = 20lg(d) + 20lg(f) − 147.55，d:m，f:Hz"""
    d = to_f(d_km, 38000) * 1000.0
    f = to_f(f_ghz, 20.0) * 1e9
    if d <= 0 or f <= 0:
        return 0.0
    return 20 * math.log10(d) + 20 * math.log10(f) - 147.55


def pick_modcod(cn_db, forced=None, m_target=None):
    """c-11: 由实际 C/N 在 DVBS2X 阶梯上自适应选定 MODCOD（先有 C/N 再定体制）。

    m_target: 设计余量目标(dB)。给定时优先在「满足 cn − cn_req ≥ m_target」的
    档位中选频谱效率最高者（ACM 工程做法：不留余量地顶格选档会让 c-10 恒不闭合）；
    若没有任何档位满足余量目标，则退回顶格选档（此时余量不足，触发回环）。
    """
    if forced:
        for m in MODCOD:
            if m["name"] == forced:
                return m
    # 选满足 cn ≥ cn_req 的最高频谱效率档
    ok = [m for m in MODCOD if cn_db >= m["cn_req"]]
    if not ok:
        return None
    best = max(ok, key=lambda m: m["eta"])
    if m_target is not None and m_target > 0:
        ok_m = [m for m in ok if cn_db - m["cn_req"] >= m_target]
        if ok_m:
            best = max(ok_m, key=lambda m: m["eta"])
    return best


def rf_link_budget(p, ant, direction="down"):
    """射频链路预算：上行(地面→星) 或 下行(星→地面)。

    带宽模型（标准做法）：
      · 噪声带宽取「单载波占用带宽 B_carrier」，而非整波束带宽；
      · 下行星上 EIRP 为整波束总功率，被 N_carrier = B_beam/B_carrier 个载波分享，
        故单载波 EIRP = EIRP_total − 10lg(B_beam/B_carrier)；
      · 上行关口站 EIRP 工程上按单载波给出，不折算。
    如此 C/N 与「整功率+整带宽」口径等价，但物理含义清晰，且可分别给出
    单载波容量与整波束容量。
    """
    f = to_f(p.get("f_up" if direction == "up" else "f_down"), 30.0)
    d = to_f(p.get("d_slant" if direction == "up" else "d_dl"), 38000)
    avail = to_f(p.get("A_avail"), 99.9)
    el = to_f(p.get("el_deg"), 30)
    A_ref = to_f(p.get("A_up_ref" if direction == "up" else "A_dn_ref"), 7.0)
    A_rain = rain_at_avail(A_ref, avail, el)
    A_atm = to_f(p.get("A_atm" if direction == "up" else "A_atm_dl"), 0.3)
    L_pnt = ant["c6"]["L_pnt_db"]
    L_pol = to_f(p.get("L_pol"), 0.3)
    L_impl = to_f(p.get("L_impl"), 1.0)

    L_fs = fspl(d, f)
    sum_L = A_rain + A_atm + L_pnt + L_pol + L_impl

    B_beam = to_f(p.get("B_beam"), 125)
    B_car = to_f(p.get("B_carrier"), B_beam) or B_beam
    B_car = min(B_car, B_beam) if B_beam > 0 else B_car
    N_carrier = (B_beam / B_car) if B_car > 0 else 1.0

    if direction == "up":
        EIRP_total = to_f(p.get("EIRP_gs"), 75.0)
        EIRP = EIRP_total                     # 关口站按单载波给出
        GT = ant.get("_GT", 0.0)
        gt_sym = "GT_ant"
        share_db = 0.0
    else:
        EIRP_total = ant.get("_EIRP", 0.0)
        share_db = 10 * math.log10(N_carrier) if N_carrier > 1 else 0.0
        EIRP = EIRP_total - share_db          # 单载波 EIRP
        GT = to_f(p.get("GT_gs"), 15.0)
        gt_sym = "GT_gs"

    # c-8: C/N0 = EIRP − L_fs − ΣL + G/T − k
    CN0 = EIRP - L_fs - sum_L + GT - K_BOLTZ_DB
    # c-9: C/N = C/N0 − 10lg(B_carrier)
    B_hz = B_car * 1e6
    CN = CN0 - 10 * math.log10(B_hz) if B_hz > 0 else CN0

    mc = pick_modcod(CN, m_target=to_f(p.get("M_target"), 3.0))
    CN_req = mc["cn_req"] if mc else MODCOD[0]["cn_req"]
    eta = mc["eta"] if mc else 0.0
    M = CN - CN_req                                   # c-10

    # c-11: C_link = B × η
    C_car_mbps = B_car * eta
    C_beam_mbps = B_beam * eta
    return dict(direction=direction, f_ghz=f, d_km=d, L_fs=L_fs,
                EIRP=EIRP, EIRP_total=EIRP_total, share_db=share_db,
                N_carrier=N_carrier, GT=GT, gt_sym=gt_sym,
                A_rain=A_rain, A_atm=A_atm, L_pnt=L_pnt, L_pol=L_pol, L_impl=L_impl,
                sum_L=sum_L, CN0=CN0, B_mhz=B_car, B_beam_mhz=B_beam, CN=CN,
                modcod=mc["name"] if mc else "无法闭合（低于最低阶门限）",
                eta=eta, CN_req=CN_req, M=M,
                C_link_mbps=C_car_mbps, C_link_gbps=C_car_mbps / 1000.0,
                C_beam_mbps=C_beam_mbps, C_beam_gbps=C_beam_mbps / 1000.0,
                avail=avail, el=el,
                c8="C/N0 = EIRP − L_fs − ΣL + G/T − k", c9="C/N = C/N0 − 10lg(B)",
                c10="M = C/N − (C/N)_req ≥ 3dB", c11="C_link = B × η(MODCOD)")


def total_cn(cn_up, cn_dn, arch):
    """再生体制：上下行独立 C/N 功率倒数相加；透明体制：噪声累积（近似取较小者再扣 3dB）。"""
    def lin(x):
        return 10 ** (x / 10.0)
    if arch == "再生转发器":
        return -10 * math.log10(1.0 / lin(cn_up) + 1.0 / lin(cn_dn))
    # 透明：总 C/N 由两段噪声功率相加
    return -10 * math.log10(1.0 / lin(cn_up) + 1.0 / lin(cn_dn))


# ================================================================
# 五、激光链路（c-18 / c-19）
# ================================================================
def laser_link(p, kind="isl"):
    """激光链路预算（灵敏度模型，工程常用）。

    G_opt = 10lg(η(πD/λ)²)（收发同口径，各一次）
    L_fs_opt = 20lg(4πd/λ)
    L_point = 12(σ_jit/θ_div)²（μrad 同量纲）
    P_rx = P_tx + G_tx + G_rx − L_fs − L_point − L_turb − L_atm
    M = P_rx − P_req，P_req = S_opt + 10lg(R/1Gbps)
    """
    D_mm = to_f(p.get("D_opt"), 135)
    D = D_mm / 1000.0
    lam_nm = to_f(p.get("λ_opt"), 1550)
    lam = lam_nm * 1e-9
    eta = to_f(p.get("η_opt"), 60) / 100.0
    G_opt = 10 * math.log10(max(eta * (math.pi * D / lam) ** 2, 1e-9))

    d_km = to_f(p.get("d_isl"), 5000) if kind == "isl" else to_f(p.get("d_dl"), 1200)
    d = d_km * 1000.0
    L_fs_opt = 20 * math.log10(max(4 * math.pi * d / lam, 1e-9))

    θ_div = to_f(p.get("θ_div"), 100)
    σ_jit = to_f(p.get("σ_jit"), 3.0)
    L_point = 12.0 * (σ_jit / θ_div) ** 2 if θ_div > 0 else 0.0

    P_tx_w = to_f(p.get("P_opt"), 1.0)
    P_tx_dbm = w2dbm(P_tx_w)
    G_edfa = to_f(p.get("G_edfa"), 25)
    # EDFA 在发射侧提升等效发射功率（受限于饱和功率，典型 +20dB 有效）
    G_edfa_eff = min(G_edfa, 20.0)

    L_turb = to_f(p.get("L_turb"), 1.5) if kind == "sgl" else 0.0
    L_atm = 0.0
    if kind == "sgl":
        # 星地：大气吸收（晴好）约 0.2dB + 云遮蔽按可用度折算
        L_atm = 0.2
    L_opt_sw = 1.5      # 光开关插损

    EIRP_opt = P_tx_dbm + G_edfa_eff + G_opt        # dBm 域
    P_rx_dbm = EIRP_opt + G_opt - L_fs_opt - L_point - L_turb - L_atm - L_opt_sw

    # 速率与所需灵敏度
    R = to_f(p.get("R_isl" if kind == "isl" else "R_sgl"), 10)
    R = max(R, 0.01)
    S_opt = to_f(p.get("S_opt"), -42)               # dBm @1Gbps
    P_req = S_opt + 10 * math.log10(R / 1.0)
    M = P_rx_dbm - P_req

    CN_dpsk = to_f(p.get("CN_dpsk"), 8.0)
    # 等效 C/N（相对 DPSK 门限的余量语义）
    CN_equiv = CN_dpsk + M

    # 最大可支持速率（余量=0 时）
    R_max = R * (10 ** (M / 10.0)) if M < 100 else R

    # c-18 ATP 判据
    P_acq = to_f(p.get("P_acq"), 97)
    σ_track = to_f(p.get("σ_track"), 0.8)
    t_acq = to_f(p.get("t_acq"), 30)
    c18 = dict(P_acq=P_acq, σ_track=σ_track, t_acq=t_acq,
               ok_acq=P_acq >= 95.0, ok_track=σ_track <= 1.0,
               ok=(P_acq >= 95.0 and σ_track <= 1.0))
    # 云遮蔽可用度（星地）
    P_cloud = to_f(p.get("P_cloud"), 8) if kind == "sgl" else 0.0
    avail = 100.0 - P_cloud
    return dict(kind=kind, D_mm=D_mm, lam_nm=lam_nm, G_opt_db=G_opt, d_km=d_km,
                L_fs_opt=L_fs_opt, θ_div=θ_div, σ_jit=σ_jit, L_point=L_point,
                P_tx_w=P_tx_w, P_tx_dbm=P_tx_dbm, G_edfa=G_edfa, G_edfa_eff=G_edfa_eff,
                EIRP_opt_dbm=EIRP_opt, L_turb=L_turb, L_atm=L_atm, L_opt_sw=L_opt_sw,
                P_rx_dbm=P_rx_dbm, R_gbps=R, S_opt_dbm=S_opt, P_req_dbm=P_req,
                M_db=M, CN_equiv=CN_equiv, CN_dpsk=CN_dpsk, R_max_gbps=R_max,
                c18=c18, P_cloud=P_cloud, avail_pct=avail,
                ok=M >= to_f(p.get("M_target"), 3.0))


# ================================================================
# 六、星内数据链路（c-20）
# ================================================================
def data_link(p):
    R_pdl = to_f(p.get("R_pdl"), 1200)          # Mbps
    CR = max(to_f(p.get("CR"), 4), 1.0)
    R_bus = to_f(p.get("R_bus"), 4000)          # Mbps
    R_bb = to_f(p.get("R_bb"), 2000)
    R_dpu = to_f(p.get("R_dpu"), 1500)
    T_blind = to_f(p.get("T_blind"), 15)        # min
    E_store = to_f(p.get("E_store"), 4.0)       # Tbit

    R_need_bus = R_pdl / CR
    ok_bus = R_bus >= R_need_bus
    ok_bb = R_bb >= R_pdl
    ok_dpu = R_dpu >= R_pdl

    # E_store ≥ R_pdl × T_blind / CR （Mbps×min → Mbit → Tbit）
    E_need_tbit = (R_pdl * T_blind * 60.0 / CR) / 1e6      # Mbit→Tbit: /1e6
    ok_store = E_store >= E_need_tbit
    return dict(c="c-20", R_pdl=R_pdl, CR=CR, R_bus=R_bus, R_bb=R_bb, R_dpu=R_dpu,
                R_need_bus=R_need_bus, T_blind=T_blind, E_store=E_store,
                E_need_tbit=E_need_tbit, ok_bus=ok_bus, ok_bb=ok_bb,
                ok_dpu=ok_dpu, ok_store=ok_store,
                ok=(ok_bus and ok_bb and ok_dpu and ok_store),
                bus_margin_pct=(R_bus / R_need_bus - 1) * 100 if R_need_bus > 0 else 0,
                store_margin_pct=(E_store / E_need_tbit - 1) * 100 if E_need_tbit > 0 else 0)


# ================================================================
# 七、系统级约束（c-12 ~ c-17, c-21, c-22, c-25）
# ================================================================
def system_checks(p, ant, eirp, gt, dn, up, laser_isl, laser_sgl, dl_data):
    R = []
    def add(cid, formula, items, ok, note="", sev="hard"):
        R.append(dict(id=cid, formula=formula, items=items, ok=bool(ok),
                      note=note, sev=sev))

    N_beam = to_f(p.get("N_beam"), 64)
    B_beam = to_f(p.get("B_beam"), 125)
    B_total = to_f(p.get("B_total"), 2500)
    k_reuse = to_f(p.get("k_reuse"), 4)

    # c-12 系统容量
    #   C_sys = N_beam × B_beam × η × n_pol
    #   · k_reuse（频率复用）不在此相乘：复用增益已体现在 c-13 允许 N_beam×B_beam
    #     达到 B_total×k_reuse 的频谱口径上，再乘一次即重复计入（容量虚高 k 倍）。
    #   · n_pol（极化复用）在此相乘：c-13 按单极化频谱口径约束，双极化时同一 B_beam
    #     可承载 2 路正交独立信道。
    eta = dn["eta"] if dn.get("eta") else 0.0
    n_pol = to_f(p.get("n_pol"), 2)
    C_sys_gbps = N_beam * B_beam * eta * n_pol / 1000.0
    C_req = to_f(p.get("C_req"), 20)
    # 频谱物理上限：B_total × k_reuse × η × n_pol（c-13 取等号时的容量）
    C_ceil = B_total * k_reuse * eta * n_pol / 1000.0
    add("c-12", "C_sys = N_beam × B_beam × η × n_pol",
        [("N_beam", N_beam, ""), ("B_beam", B_beam, "MHz"), ("η", eta, "bps/Hz"),
         ("n_pol", n_pol, "极化"), ("k_reuse", k_reuse, "色"),
         ("C_sys", C_sys_gbps, "Gbps"), ("C_req", C_req, "Gbps"),
         ("C_ceil", C_ceil, "Gbps")],
        C_sys_gbps >= C_req,
        f"系统容量 {fmt(C_sys_gbps,2)} Gbps {'≥' if C_sys_gbps>=C_req else '<'} 需求 {fmt(C_req,2)} Gbps；"
        f"该频段频谱物理上限 {fmt(C_ceil,2)} Gbps（=B_total×k_reuse×η×n_pol）"
        + ("" if C_sys_gbps >= C_req else
           "；容量缺口须靠增波束/增带宽/提复用度/双极化/多星组网闭合"))

    # c-13 频率规划（单极化频谱口径）
    lhs, rhs = N_beam * B_beam, B_total * k_reuse
    add("c-13", "N_beam × B_beam ≤ B_total × k_reuse",
        [("N_beam×B_beam", lhs, "MHz"), ("B_total×k_reuse", rhs, "MHz"),
         ("n_pol", n_pol, "极化"), ("占用率", lhs / rhs * 100 if rhs else 0, "%")],
        lhs <= rhs,
        "无频率冲突（ITU-R S.466 指配 / S.1528 限值）" if lhs <= rhs else
        f"频率冲突！占用率 {fmt(lhs / rhs * 100 if rhs else 0,0)}% > 100%，"
        "需减波束数/带宽或增复用色数")

    # c-14 DTP 交换容量
    C_sw = to_f(p.get("C_sw"), 100)
    N_ch = to_f(p.get("N_ch"), 32)
    B_sub = to_f(p.get("B_sub"), 40)
    B_trp = to_f(p.get("B_trp"), 1000)
    C_need = N_beam * B_beam * eta / 1000.0        # Gbps
    ok_sw = C_sw >= C_need
    ok_ch = N_ch * B_sub >= B_trp
    add("c-14", "C_sw ≥ N_beam×B_beam×η 且 N_ch×B_sub ≥ B_trp",
        [("C_sw", C_sw, "Gbps"), ("需求交换容量", C_need, "Gbps"),
         ("N_ch×B_sub", N_ch * B_sub, "MHz"), ("B_trp", B_trp, "MHz")],
        ok_sw and ok_ch,
        ("DTP 信道化与交换容量覆盖需求" if (ok_sw and ok_ch) else
         ("交换容量瓶颈！" if not ok_sw else "") + ("；信道化不足！" if not ok_ch else "")))

    # c-15 EMC 隔离
    I_iso = to_f(p.get("I_iso"), 100)
    I_trp = to_f(p.get("I_trp"), 85)
    add("c-15", "I_iso ≥ 100dB 且 I_trp ≥ 80dB",
        [("I_iso（收发）", I_iso, "dB"), ("I_trp（舱内）", I_trp, "dB")],
        I_iso >= 100 and I_trp >= 80,
        "符合 GJB 151B / MIL-STD-461 / ECSS-E-ST-20C" if (I_iso >= 100 and I_trp >= 80)
        else "隔离不足，存在自激/互调风险")

    # c-16 热控与供电
    T_j = to_f(p.get("T_j"), 105)
    P_out = to_f(p.get("P_out"), 180)
    η_pa = to_f(p.get("η_pa"), 58) / 100.0
    P_dc = P_out / η_pa if η_pa > 0 else 0
    P_trp = to_f(p.get("P_trp"), 900)
    N_el = to_f(p.get("N_el"), 0) if p.get("ant_type") == "相控阵天线" else 0
    P_tr = to_f(p.get("P_tr"), 8.0)
    P_face = N_el * P_tr
    add("c-16", "T_j ≤ 125℃ 且 P_dc = P_out/η ≤ P_trp",
        [("T_j", T_j, "℃"), ("P_dc（功放直流）", P_dc, "W"), ("P_trp（分系统预算）", P_trp, "W"),
         ("阵面功耗 N_el×P_tr", P_face, "W")],
        T_j <= 125 and P_dc <= P_trp,
        (f"结温 {'达标' if T_j<=125 else '超限'}；功放直流功耗 {fmt(P_dc,1)}W "
         f"{'≤' if P_dc<=P_trp else '>'} 预算 {fmt(P_trp,1)}W"))

    # c-17 质量功耗预算
    m_sum = sum(to_f(p.get(k), 0) for k in ("m_ant", "m_trp", "m_laser", "m_ipu"))
    p_sum = sum(to_f(p.get(k), 0) for k in ("P_ant", "P_trp", "P_laser", "P_ipu"))
    M_budget = to_f(p.get("M_budget"), 480)
    P_budget = to_f(p.get("P_budget"), 1900)
    m_marg = (1 - m_sum / M_budget) * 100 if M_budget else 0
    p_marg = (1 - p_sum / P_budget) * 100 if P_budget else 0
    add("c-17", "M_pay = Σm_i ≤ M_budget 且 P_pay = ΣP_i ≤ P_budget（裕度≥10%）",
        [("M_pay", m_sum, "kg"), ("M_budget", M_budget, "kg"), ("质量裕度", m_marg, "%"),
         ("P_pay", p_sum, "W"), ("P_budget", P_budget, "W"), ("功耗裕度", p_marg, "%")],
        m_sum <= M_budget and p_sum <= P_budget and m_marg >= 10 and p_marg >= 10,
        f"质量 {fmt(m_sum,1)}/{fmt(M_budget,1)}kg（裕度 {fmt(m_marg,1)}%）、"
        f"功耗 {fmt(p_sum,1)}/{fmt(P_budget,1)}W（裕度 {fmt(p_marg,1)}%）")

    # c-18 激光 ATP
    c18 = (laser_isl or laser_sgl or {}).get("c18", {})
    if c18:
        add("c-18", "P_acq ≥ 95% 且 σ_track ≤ 1μrad",
            [("P_acq", c18.get("P_acq"), "%"), ("σ_track", c18.get("σ_track"), "μrad"),
             ("t_acq", c18.get("t_acq"), "s")],
            c18.get("ok"), "ATP 建链判据达标" if c18.get("ok") else "ATP 判据不达标")

    # c-19 激光速率/余量
    for lk, res in (("星间 ISL", laser_isl), ("星地", laser_sgl)):
        if res and res.get("R_gbps", 0) > 0:
            add("c-19", f"R_laser ≤ f(EIRP_opt, GT_opt, L_fs_opt, L_turb) [{lk}]",
                [("EIRP_opt", res["EIRP_opt_dbm"], "dBm"), ("L_fs_opt", res["L_fs_opt"], "dB"),
                 ("L_point", res["L_point"], "dB"), ("P_rx", res["P_rx_dbm"], "dBm"),
                 ("P_req", res["P_req_dbm"], "dBm"), ("M", res["M_db"], "dB"),
                 ("R", res["R_gbps"], "Gbps"), ("R_max", res["R_max_gbps"], "Gbps")],
                res["ok"],
                f"{lk} 激光链路余量 {fmt(res['M_db'],2)}dB "
                f"{'≥' if res['ok'] else '<'} {fmt(to_f(p.get('M_target'),3),1)}dB")

    # c-20 星内数据链路
    if dl_data:
        add("c-20", "R_bus ≥ R_pdl/CR 且 E_store ≥ R_pdl×T_blind/CR",
            [("R_pdl", dl_data["R_pdl"], "Mbps"), ("CR", dl_data["CR"], ":1"),
             ("R_bus", dl_data["R_bus"], "Mbps"), ("需求总线速率", dl_data["R_need_bus"], "Mbps"),
             ("E_store", dl_data["E_store"], "Tbit"), ("需求存储", dl_data["E_need_tbit"], "Tbit")],
            dl_data["ok"],
            f"总线裕度 {fmt(dl_data['bus_margin_pct'],0)}%、存储裕度 {fmt(dl_data['store_margin_pct'],0)}%")

    # c-21 货架优先（趋近型目标：N_gap→0、H→4 是持续改进方向，不作硬性失败）
    N_gap = to_f(p.get("N_gap"), 2)
    H = to_f(p.get("H_scheme"), 3)
    ok21 = N_gap <= 2 and H >= 3
    add("c-21", "N_gap → 0 且 H_scheme → 4",
        [("N_gap", N_gap, "项"), ("H_scheme", H, "级")],
        ok21,
        f"缺口 {int(N_gap)} 项、货架水平 {int(H)}（1定制~4飞行继承货架）；"
        + ("每项缺口须记录需求/风险/研制周期" if N_gap > 0 else "无定制缺口")
        + ("" if ok21 else "（趋近型目标：建议提升货架化水平，不作硬性拦截）"),
        sev="warning")

    # c-22 需求闭环
    EIRP_req = to_f(p.get("EIRP_req"), 65)
    GT_req = to_f(p.get("GT_req"), 25)
    EIRP_ant = eirp["EIRP"]
    GT_ant = gt["GT"]
    MODE_ORDER = {"单波束": 1, "多波束": 2, "波束跳变": 3, "在轨重构": 4}
    Mode = p.get("Mode", "多波束")
    Mode_req = p.get("Mode_req", "多波束")
    ok_mode = MODE_ORDER.get(Mode, 0) >= MODE_ORDER.get(Mode_req, 0)
    add("c-22", "EIRP_ant ≥ EIRP_req 且 GT_ant ≥ GT_req 且 Mode ⊇ Mode_req",
        [("EIRP_ant", EIRP_ant, "dBW"), ("EIRP_req", EIRP_req, "dBW"),
         ("GT_ant", GT_ant, "dB/K"), ("GT_req", GT_req, "dB/K"),
         ("Mode", Mode, ""), ("Mode_req", Mode_req, "")],
        EIRP_ant >= EIRP_req and GT_ant >= GT_req and ok_mode,
        f"EIRP 余 {fmt(EIRP_ant-EIRP_req,2)}dB、G/T 余 {fmt(GT_ant-GT_req,2)}dB、"
        f"模式{'覆盖' if ok_mode else '不覆盖'}需求；不满足触发内环换天线（≤3次）")

    # c-23 天线电气性能
    c23 = ant["c23"]
    add("c-23", "Δ_amp≤0.5dB 且 Δ_phs≤5° 且 SLL≤−20dB 且 AR≤3dB",
        [("Δ_amp", c23["Δ_amp"], "dB"), ("Δ_phs", c23["Δ_phs"], "°"),
         ("SLL", c23["SLL"], "dB"), ("AR", c23["AR"], "dB"), ("Δ_cal", c23["Δ_cal"], "dB")],
        c23["ok"], "满足 ITU-R S.1323 方向图要求" if c23["ok"] else "旁瓣/轴比/一致性超限")

    # c-24 体制选择判据
    arch = p.get("arch", "透明转发器")
    M_dn = dn["M"]
    ΔM_reg = to_f(p.get("ΔM_reg"), 4.5)
    M_target = to_f(p.get("M_target"), 3.0)
    need_up = (M_dn < M_target)
    lowest = dn["modcod"].startswith("QPSK")
    trig = need_up and lowest and arch == "透明转发器"
    add("c-24", "M < 3dB 且 MODCOD 已最低阶 ⇒ ΔM_reg ≥ 3dB → 改再生/DTP",
        [("当前体制", arch, ""), ("下行余量 M", M_dn, "dB"),
         ("当前 MODCOD", dn["modcod"], ""), ("ΔM_reg", ΔM_reg, "dB"),
         ("τ_trans", to_f(p.get("τ_trans"), 200), "ns"), ("τ_reg", to_f(p.get("τ_reg"), 30), "ms")],
        not trig,
        ("触发体制升级：透明余量不足且已降至最低阶，建议改再生（+"
         + fmt(ΔM_reg, 1) + "dB）或 DTP") if trig else
        (f"体制 {arch} 可闭合（余量 {fmt(M_dn,2)}dB）" if not need_up else
         f"余量 {fmt(M_dn,2)}dB 偏低但 MODCOD 未至最低阶，可先降阶/减带宽"))

    # c-25 波束链路能力一致性
    N_bf = to_f(p.get("N_bf"), 64)
    N_port = to_f(p.get("N_port"), 64)
    N_sch = to_f(p.get("N_sch"), 64)
    add("c-25", "N_bf ≥ N_beam 且 N_port ≥ N_beam 且 N_sch ≥ N_beam",
        [("N_beam", N_beam, ""), ("N_bf", N_bf, ""), ("N_port", N_port, ""), ("N_sch", N_sch, "")],
        N_bf >= N_beam and N_port >= N_beam and N_sch >= N_beam,
        "波束赋形/端口/调度能力一致" if (N_bf >= N_beam and N_port >= N_beam and N_sch >= N_beam)
        else "能力不足，波束数指标无法实现")

    # c-5 / c-6 附加
    c5 = ant["c5"]
    add("c-5", "δ_surf ≤ λ/32 且 δ_dep ≤ δ_surf",
        [("λ/32 限值", c5["limit_mm"], "mm"), ("δ_surf", c5["δ_surf"], "mm"),
         ("δ_dep", c5["δ_dep"], "mm")],
        c5["ok"], f"面精度限值 {fmt(c5['limit_mm'],3)}mm（f={fmt(to_f(p.get('f_down'),20),1)}GHz）")

    add("c-6", "L_pnt = 12×(θ_e/θ_3dB)²",
        [("θ_e", ant["c6"]["θ_e"], "°"), ("θ_3dB", ant["c6"]["θ_3dB"], "°"),
         ("L_pnt", ant["c6"]["L_pnt_db"], "dB")],
        ant["c6"]["L_pnt_db"] <= 1.0,
        f"指向损耗 {fmt(ant['c6']['L_pnt_db'],3)}dB（判据 ≤1.0dB 为宜）")

    # c-3 / c-4 增益公式（信息项，恒 pass）
    if ant["formula"] == "c-3":
        add("c-3", "G_pa = 10lg(N_el × η) + G_el − 扫描损耗",
            [("N_el", to_f(p.get("N_el"), 0), ""), ("η", to_f(p.get("η_ill"), 68), "%"),
             ("G_el", to_f(p.get("G_el"), 6), "dBi"),
             ("扫描损耗", -ant.get("scan_loss_db", 0), "dB"), ("G_ant", ant["G_ant"], "dBi")],
            True, f"相控阵增益 {fmt(ant['G_ant'],2)}dBi（θ_scan={fmt(to_f(p.get('θ_scan'),0),0)}°）")
    else:
        add("c-4", "G_refl = 10lg(η(πD/λ)²)，θ_3dB ≈ 70λ/D",
            [("D", ant.get("D_m"), "m"), ("λ", ant["lam_m"] * 100, "cm"),
             ("η", to_f(p.get("η_ill"), 68), "%"), ("G_ant", ant["G_ant"], "dBi"),
             ("θ_3dB", ant.get("θ_3dB"), "°")],
            True, f"反射面增益 {fmt(ant['G_ant'],2)}dBi，波束宽度 {fmt(ant.get('θ_3dB'),3)}°")

    return R


# ================================================================
# 八、主计算入口
# ================================================================
def compute_all(p, kg):
    """按参数 p 计算全部信息流与约束校验，返回结构化结果。"""
    ont = {o["id"]: o for o in kg["ontologies"]}
    res = dict(params=p, meta=dict(version=kg.get("version"), name=kg.get("name")))

    # --- 天线电气 ---
    ant = antenna_electrical(p)

    # --- 全部 15 条链路的逐级信息流 ---
    flows = {}
    for lid, meta in LINK_META.items():
        node = ont.get(lid)
        chain = (node or {}).get("chain") or []
        if not chain:
            continue
        if meta["dir"] == "tx":
            f = propagate_tx(chain, p)
            f["meta"] = dict(name=node["name"], dir="tx", kind=meta["kind"],
                             cat=meta["cat"], chain=chain)
        elif meta["dir"] == "rx":
            f = propagate_rx(chain, p)
            f["meta"] = dict(name=node["name"], dir="rx", kind=meta["kind"],
                             cat=meta["cat"], chain=chain)
        else:
            # both：同时给出发射与接收两个视图
            ft = propagate_tx(chain, p)
            fr = propagate_rx(chain, p)
            f = dict(tx=ft, rx=fr,
                     meta=dict(name=node["name"], dir="both", kind=meta["kind"],
                               cat=meta["cat"], chain=chain))
        flows[lid] = f
    res["flows"] = flows

    # --- EIRP / G/T ---
    tx_ant = flows.get("ant_tx_path", {})
    tx_stages = tx_ant.get("stages", []) if isinstance(tx_ant, dict) else []
    eirp = eirp_calc(p, ant, dict(stages=tx_stages))

    # G/T 的接收链按天线体制选择：
    #   相控阵 → ant_rx_path（首级放大是 T/R 组件，链中无独立 LNA）
    #   其他   → uplink（feed→rx_filter→circulator→lna→…，LNA 为首级低噪声放大）
    rx_chain_id = "ant_rx_path" if p.get("ant_type") == "相控阵天线" else "uplink"
    rx_chain, rx_synth = resolve_rx_chain(ont, rx_chain_id, p.get("ant_type"))
    rx = propagate_rx(rx_chain, p)
    gt = gt_calc(p, ant, rx)
    gt["rx_chain_id"] = rx_chain_id
    gt["rx_chain_synthesized"] = rx_synth
    gt["rx_chain_name"] = (ont.get(rx_chain_id, {}).get("name", rx_chain_id)
                           + ("（合成默认链）" if rx_synth else ""))
    ant["_EIRP"] = eirp["EIRP"]
    ant["_GT"] = gt["GT"]
    res["antenna"], res["eirp"], res["gt"] = ant, eirp, gt

    # --- 射频链路预算 ---
    dn = rf_link_budget(p, ant, "down")
    up = rf_link_budget(p, ant, "up")
    arch = p.get("arch", "透明转发器")
    CN_total = total_cn(up["CN"], dn["CN"], arch)
    mc_total = pick_modcod(CN_total, m_target=to_f(p.get("M_target"), 3.0))
    M_total = CN_total - (mc_total["cn_req"] if mc_total else MODCOD[0]["cn_req"])
    regen_bonus = to_f(p.get("ΔM_reg"), 4.5) if arch == "再生转发器" else 0.0
    res["uplink"], res["downlink"] = up, dn
    res["e2e"] = dict(arch=arch, CN_up=up["CN"], CN_dn=dn["CN"], CN_total=CN_total,
                      modcod=mc_total["name"] if mc_total else "无法闭合",
                      eta=mc_total["eta"] if mc_total else 0.0,
                      CN_req=mc_total["cn_req"] if mc_total else 0,
                      M=M_total + regen_bonus, regen_bonus=regen_bonus,
                      C_link_gbps=dn["C_link_gbps"])

    # --- 激光 ---
    R_isl = to_f(p.get("R_isl"), 0)
    R_sgl = to_f(p.get("R_sgl"), 0)
    res["laser_isl"] = laser_link(p, "isl") if R_isl > 0 else None
    res["laser_sgl"] = laser_link(p, "sgl") if R_sgl > 0 else None

    # --- 数据链 ---
    res["data"] = data_link(p) if to_f(p.get("R_pdl"), 0) > 0 else None

    # --- 25 条约束校验 ---
    res["checks"] = system_checks(p, ant, eirp, gt, dn, up,
                                  res["laser_isl"], res["laser_sgl"], res["data"])
    # 补 c-1/c-2/c-7/c-8/c-9/c-10/c-11 为信息型校验项
    info = []
    info.append(dict(id="c-1", formula="EIRP = P_out + G_ant − L_feed − L_tx", ok=True,
                     items=[("P_out", eirp["P_out_dbw"], "dBW"), ("G_ant", eirp["G_ant"], "dBi"),
                            ("L_feed", eirp["L_feed"], "dB"), ("L_tx", eirp["L_tx"], "dB"),
                            ("EIRP", eirp["EIRP"], "dBW")],
                     note=f"星上 EIRP = {fmt(eirp['EIRP'],2)} dBW（功放 {fmt(eirp['P_out_w'],0)}W）"))
    info.append(dict(id="c-2", formula="G/T = G_ant − 10lg(T_ant + T_rx)", ok=True,
                     items=[("G_ant", gt["G_ant"], "dBi"), ("T_ant", gt["T_ant"], "K"),
                            ("T_rx", gt["T_rx"], "K"), ("T_sys", gt["T_sys"], "K"),
                            ("G/T", gt["GT"], "dB/K")],
                     note=f"接收品质因数 G/T = {fmt(gt['GT'],2)} dB/K（{gt['source']}）"))
    for lk, nm in ((up, "上行"), (dn, "下行")):
        info.append(dict(id="c-7", formula="L_fs = 20lg(d) + 20lg(f) − 147.55", ok=True,
                         items=[("d", lk["d_km"], "km"), ("f", lk["f_ghz"], "GHz"),
                                ("L_fs", lk["L_fs"], "dB")],
                         note=f"{nm}自由空间损耗 {fmt(lk['L_fs'],2)} dB"))
        info.append(dict(id="c-8", formula="C/N0 = EIRP − L_fs − ΣL + G/T − k", ok=True,
                         items=[("EIRP", lk["EIRP"], "dBW"), ("L_fs", lk["L_fs"], "dB"),
                                ("ΣL", lk["sum_L"], "dB"), ("G/T", lk["GT"], "dB/K"),
                                ("k", K_BOLTZ_DB, "dBW/Hz/K"), ("C/N0", lk["CN0"], "dBHz")],
                         note=f"{nm} C/N0 = {fmt(lk['CN0'],2)} dBHz（雨衰 {fmt(lk['A_rain'],2)}dB @可用性 {fmt(lk['avail'],2)}%）"))
        info.append(dict(id="c-9", formula="C/N = C/N0 − 10lg(B)", ok=True,
                         items=[("C/N0", lk["CN0"], "dBHz"), ("B", lk["B_mhz"], "MHz"),
                                ("C/N", lk["CN"], "dB")],
                         note=f"{nm} C/N = {fmt(lk['CN'],2)} dB"))
        M_t = to_f(p.get("M_target"), 3.0)
        info.append(dict(id="c-10", formula="M = C/N − (C/N)_req ≥ 3dB",
                         ok=lk["M"] >= M_t,
                         items=[("C/N", lk["CN"], "dB"), ("MODCOD", lk["modcod"], ""),
                                ("(C/N)_req", lk["CN_req"], "dB"), ("M", lk["M"], "dB")],
                         note=f"{nm}余量 {fmt(lk['M'],2)}dB "
                              f"{'≥' if lk['M']>=M_t else '<'} {fmt(M_t,1)}dB "
                              f"{'闭合' if lk['M']>=M_t else '不闭合，触发回环'}"))
        info.append(dict(id="c-11", formula="C_link = B × η(MODCOD)", ok=True,
                         items=[("B", lk["B_mhz"], "MHz"), ("η", lk["eta"], "bps/Hz"),
                                ("C_link", lk["C_link_gbps"], "Gbps")],
                         note=f"{nm}链路容量 {fmt(lk['C_link_gbps'],3)} Gbps"))

    # 排序：c-1 .. c-25 按数字序，信息项与校验项合并
    allc = {c["id"]: c for c in info}
    for c in res["checks"]:
        allc[c["id"]] = c          # 校验项覆盖信息项（保留 ok 判定）
    order = [f"c-{i}" for i in range(1, 26)]
    res["constraints"] = [allc[i] for i in order if i in allc]

    # --- 回环建议（外环）---
    res["loop"] = build_loop_advice(p, res)

    # --- 汇总 KPI ---
    n_pass = sum(1 for c in res["constraints"] if c.get("ok"))
    n_judge = sum(1 for c in res["constraints"] if c["id"] in
                  ("c-5", "c-6", "c-10", "c-12", "c-13", "c-14", "c-15", "c-16",
                   "c-17", "c-18", "c-19", "c-20", "c-21", "c-22", "c-23", "c-24", "c-25"))
    n_jpass = sum(1 for c in res["constraints"] if c["id"] in
                  ("c-5", "c-6", "c-10", "c-12", "c-13", "c-14", "c-15", "c-16",
                   "c-17", "c-18", "c-19", "c-20", "c-21", "c-22", "c-23", "c-24", "c-25")
                  and c.get("ok"))
    res["summary"] = dict(
        EIRP=eirp["EIRP"], GT=gt["GT"], G_ant=ant["G_ant"], T_sys=gt["T_sys"],
        CN0_dn=dn["CN0"], CN_dn=dn["CN"], M_dn=dn["M"], modcod=dn["modcod"],
        C_link=dn["C_link_gbps"], CN0_up=up["CN0"], CN_up=up["CN"], M_up=up["M"],
        M_e2e=res["e2e"]["M"], C_sys=None,
        pass_count=n_pass, total_count=len(res["constraints"]),
        judge_pass=n_jpass, judge_total=n_judge,
        fail=[c["id"] for c in res["constraints"]
              if not c.get("ok") and c.get("sev", "hard") == "hard"],
        warn=[c["id"] for c in res["constraints"]
              if not c.get("ok") and c.get("sev") == "warning"])
    # 系统容量
    for c in res["constraints"]:
        if c["id"] == "c-12":
            for it in c["items"]:
                if it[0] == "C_sys":
                    res["summary"]["C_sys"] = it[1]
    return res


def build_loop_advice(p, res):
    """外环回环建议：余量不足时的调整手段（按优先级）。"""
    dn, up, e2e = res["downlink"], res["uplink"], res["e2e"]
    M_t = to_f(p.get("M_target"), 3.0)
    adv = []
    worst = min(dn["M"], up["M"], e2e["M"])
    if worst >= M_t:
        return dict(need=False, worst_M=worst, target=M_t, advice=[], note="全部链路余量达标，无需回环")
    deficit = M_t - worst
    # ① 降阶调制
    cur_eta = dn["eta"]
    lower = [m for m in MODCOD if m["cn_req"] < dn["CN_req"]]
    if lower:
        best = max(lower, key=lambda m: m["eta"])
        gain = dn["CN_req"] - best["cn_req"]
        adv.append(dict(step="① 降阶调制", action=f"{dn['modcod']} → {best['name']}",
                        gain_db=gain, cost=f"容量 {fmt(dn['B_mhz']*cur_eta/1000,3)} → "
                        f"{fmt(dn['B_mhz']*best['eta']/1000,3)} Gbps（−{fmt((1-best['eta']/max(cur_eta,1e-9))*100,1)}%）",
                        enough=gain >= deficit))
    # ② 减小单载波带宽（噪声带宽 ∝ B_carrier，C/N 直接 +10lg(1/frac)）
    B = dn["B_mhz"]
    for frac, lbl in ((0.5, "减半"), (0.25, "减至 1/4")):
        g = -10 * math.log10(frac)
        adv.append(dict(step="② 减小单载波带宽", action=f"B_carrier {fmt(B,0)} → {fmt(B*frac,0)} MHz（{lbl}）",
                        gain_db=g, cost=f"单载波容量同比 −{fmt((1-frac)*100,0)}%",
                        enough=g >= deficit))
        if g >= deficit:
            break
    # ③ 增大 EIRP
    need_db = deficit
    P_out = to_f(p.get("P_out"), 180)
    P_new = P_out * (10 ** (need_db / 10.0))
    adv.append(dict(step="③ 增大功放功率 / 天线口径", action=f"P_out {fmt(P_out,0)} → {fmt(P_new,0)} W（+{fmt(need_db,2)}dB）",
                    gain_db=need_db,
                    cost=f"直流功耗 {fmt(P_out/max(to_f(p.get('η_pa'),58)/100,1e-6),0)} → "
                         f"{fmt(P_new/max(to_f(p.get('η_pa'),58)/100,1e-6),0)} W；热控与供电压力上升（c-16/c-17）",
                    enough=True))
    # ④ 放宽可用性
    A_ref = to_f(p.get("A_dn_ref"), 7.0)
    cur_rain = dn["A_rain"]
    for tgt in (99.5, 99.0, 98.0):
        new_rain = rain_at_avail(A_ref, tgt, dn["el"])
        g = cur_rain - new_rain
        if g > 0:
            adv.append(dict(step="④ 放宽可用性要求", action=f"A_avail {fmt(dn['avail'],2)}% → {tgt}%",
                            gain_db=g, cost=f"雨衰 {fmt(cur_rain,2)} → {fmt(new_rain,2)} dB；业务可用度下降",
                            enough=g >= deficit))
            if g >= deficit:
                break
    # ⑤ 体制升级
    if p.get("arch") == "透明转发器":
        dMr = to_f(p.get("ΔM_reg"), 4.5)
        adv.append(dict(step="⑤ 体制升级（c-24）", action="透明 → 再生/DTP",
                        gain_db=dMr, cost=f"时延 +{fmt(to_f(p.get('τ_reg'),30),0)}ms；功耗/质量上升；"
                        f"基带与路由单机增加", enough=dMr >= deficit))
    # ⑥ 换天线重选（内环，≤2 次）
    adv.append(dict(step="⑥ 换天线重选（外环 ≤2 次）", action="增大口径/阵元数或改体制（相控阵↔反射面）",
                    gain_db=None, cost="触发内环平台可行性回环（≤3 次），质量/功耗需重新闭环",
                    enough=False))
    return dict(need=True, worst_M=worst, target=M_t, deficit=deficit, advice=adv,
                note=f"最差链路余量 {fmt(worst,2)}dB < 目标 {fmt(M_t,1)}dB，缺口 {fmt(deficit,2)}dB")
