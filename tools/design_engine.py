# -*- coding: utf-8 -*-
"""通信卫星有效载荷方案设计软件 —— 设计引擎。

实现 payload-design skill 的五步闭环：
  1 需求解析     : parse_config()      —— 场景/业务/轨道/覆盖/频段 → 结构化需求
  2 架构规划     : derive_geometry() + cfg_to_params() —— 体制选型 + 几何推导 + 参数映射
  3a 天线五维选型: select_antennas()   —— EIRP/G/T/重量/功耗/模式 + 频段硬过滤
  3b 转发器方案  : plan_transponder()  —— EIRP 反推功放 + HPA 选型 + 信道化
  4 货架单机选型 : build_equipment()   —— 货架优先三线编号 + 单机清单
  5 链路校核     : compute_all         —— 复用 infoflow_engine（c-1~c-25）
  平台/运载选型  : select_platform() / select_launcher()
  方案对比       : compare_schemes()   —— 六维评分
  框图/信息流    : block_diagram() / info_flows()

关键设计决策（与引擎一致性）：
  · EIRP/G/T 需求由业务终端能力 + 目标 (C/N) + 余量反推（skill 步骤 1→5 闭环）
  · 选定货架天线后：G_ant_ovr = 货架增益，P_out 按 EIRP_req+0.3dB 守卫重新反推
  · G/T 能力用与引擎相同的 Friis 级联链（propagate_rx）精确预估，避免估值偏差
  · 所有 ΣL 分项与 infoflow_engine.rf_link_budget 完全同源（雨衰/大气/指向/极化/实现）

所有公式与判据 id 对齐知识图谱 constraints，结果可追溯。
"""
from __future__ import annotations
import math

from infoflow_data import BANDS, MODCOD
from infoflow_engine import (to_f, fmt, w2dbw, lam_m, rain_at_avail, fspl,
                             propagate_rx, K_BOLTZ_DB, compute_all)
from design_data import (ORBITS, COVERAGE, SERVICES, MODES, ANT_TYPES,
                         ARRAY_SUBTYPES, SHELF_UNITS, SHELF_BY_ID, UNIT_PRINCIPLES,
                         PLATFORMS, LAUNCHERS, BAND_FREQ, BAND_RAIN, MODE_HPA,
                         COUNTRIES, COUNTRY_BY_KEY)

R_EARTH = 6371.0
NF_BY_BAND = {"L": 0.8, "S": 1.0, "C": 1.2, "X": 1.5, "Ku": 1.2, "Ka": 1.6, "Q/V": 2.5, "UHF": 0.9}
T_ANT_BY_BAND = {"L": 80, "S": 60, "C": 50, "X": 45, "Ku": 40, "Ka": 50, "Q/V": 60, "UHF": 100}
# L 波段移动卫星业务实际指配带宽（1626.5-1660.5/1525-1559MHz ≈ 34MHz）
B_TOTAL_OVR = {"L": 34}
ETA_PA = {"TWTA": 58, "SSPA": 45, "MPA": 42}
L_TX_BY_AMP = {"TWTA": 4.7, "SSPA": 3.5, "MPA": 3.8}
# HPA 可行功率上限（货架单管/合成）：反射面 250W、伞状 120W（2×60W 合成）、相控阵按阵元 8W
# 大容量多波束：TWTA 单管 ≤120W（VHTS 批产行波管）；混合多波束：单管/合成 ≤250W
P_HPA_MAX = {"固面": 250.0, "伞状": 120.0, "大容量多波束": 120.0, "混合多波束": 250.0}
P_PER_EL_MAX = 8.0
MODE_CAP = {"单波束": 1, "多波束": 2, "波束跳变": 3, "在轨重构": 4}
# 大容量多波束：波束图样成形面固化（多波束级），配 DTP+MPA 可准波束跳变 → 3
# 混合多波束：馈电阵电扫实时改图样（在轨重构级）→ 4
ANT_MODE_CAP = {"固面": 2, "相控阵": 4, "伞状": 2, "大容量多波束": 3, "混合多波束": 4}
MODE_DELAY_MS = {"透明": 0.0002, "数字透明": 3.0, "再生": 40.0}
ANT_MAP = {"固面": "反射面天线", "相控阵": "相控阵天线", "伞状": "伞状可展开天线",
           "大容量多波束": "大容量多波束天线", "混合多波束": "混合多波束天线"}
ARCH_MAP = {"透明": "透明转发器", "数字透明": "DTP数字透明处理器", "再生": "再生转发器"}
ARR_P_PER_EL = {"直射阵": 2.5, "反射阵": 1.2, "数字模拟混合": 0.9, "纯数字": 4.0, "模拟拼接": 1.0}
ARR_M_PER_EL = {"直射阵": 0.045, "反射阵": 0.038, "数字模拟混合": 0.040, "纯数字": 0.065, "模拟拼接": 0.050}
EIRP_GUARD_DB = 0.3          # EIRP 反推守卫（保证 c-22 浮点闭合）


# ================================================================
# 1 需求解析
# ================================================================
def parse_config(cfg):
    """把用户配置解析为结构化需求（对齐 IntentChain.parse 输出语义）。"""
    svc = SERVICES.get(cfg.get("service", "高通量宽带"), SERVICES["高通量宽带"])
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    return dict(
        payload_type="通信", service=cfg.get("service"), service_cn=svc["cn"],
        orbit=cfg.get("orbit"), orbit_cn=orb["cn"], coverage=cfg.get("coverage"),
        coverage_cn=cov["cn"], band=cfg.get("band", "Ka"), mode=cfg.get("mode", "数字透明"),
        mode_cn=MODES.get(cfg.get("mode", "数字透明"), {}).get("cn", ""),
        ant_type=cfg.get("ant_type", "相控阵"),
        ant_type_cn=ANT_TYPES.get(cfg.get("ant_type", "相控阵"), {}).get("cn", ""),
        array_subtype=cfg.get("array_subtype", ""),
        array_subtype_cn=ARRAY_SUBTYPES.get(cfg.get("array_subtype", ""), {}).get("cn", ""),
        C_req=to_f(cfg.get("C_req_ovr"), svc["C_gbps"]),
        GT_term=to_f(cfg.get("GT_term"), svc["GT_term"]),
        EIRP_term=to_f(cfg.get("EIRP_term"), svc["EIRP_term"]),
        avail=to_f(cfg.get("A_avail"), svc["avail"]),
        design_cn=to_f(cfg.get("design_cn"), svc.get("design_cn", 10.0)),
        isl_on=bool(cfg.get("isl_on")), isl_type=cfg.get("isl_type", "激光"),
        special=svc["note"],
    )


# ================================================================
# 2 轨道/覆盖几何
# ================================================================
def slant_range(h_km, el_deg):
    """用户仰角 el 下的斜距(km)：d = sqrt(R²sin²el + 2Rh + h²) − R·sin(el)"""
    R, h = R_EARTH, to_f(h_km)
    s = math.sin(math.radians(max(to_f(el_deg, 30), 1.0)))
    return math.sqrt(R * R * s * s + 2 * R * h + h * h) - R * s


def coverage_angle(h_km, el_deg):
    """最大覆盖地心角 ψ(deg)"""
    R, h = R_EARTH, to_f(h_km)
    c = R * math.cos(math.radians(max(to_f(el_deg, 30), 1.0))) / (R + h)
    return math.degrees(math.acos(min(max(c, -1.0), 1.0))) - to_f(el_deg, 30)


def derive_geometry(cfg):
    """轨道 + 覆盖区 → 斜距/覆盖角/波束数建议/覆盖一致性提示。"""
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    el = max(to_f(cfg.get("el_deg"), cov["el_min_deg"]), cov["el_min_deg"])
    h = orb["alt_km"]
    d = slant_range(h, el)
    psi = coverage_angle(h, el)
    cov_r_cap = R_EARTH * math.radians(psi)

    cov_r = to_f(cfg.get("cov_r_km"), cov["r_km"])
    beam_r = to_f(cfg.get("beam_r_km"), cov["beam_r_km"])
    r_eff = min(cov_r, cov_r_cap)
    n_geo = max(1, math.ceil(1.209 * (r_eff / max(beam_r, 1e-6)) ** 2))
    need_const = cfg.get("orbit") in ("LEO", "SSO", "MEO") or cov_r > cov_r_cap
    th_beam = 2.0 * math.degrees(math.asin(min(1.0, beam_r / R_EARTH)))

    warns = []
    if cov_r > cov_r_cap:
        warns.append(f"覆盖半径 {fmt(cov_r,0)}km 超出单星视域上限 {fmt(cov_r_cap,0)}km → "
                     f"需星座组网或压缩覆盖（{orb['cn']}）")
    n_cfg = to_f(cfg.get("N_beam"), 0)
    if n_cfg > 0 and n_cfg < n_geo * 0.5:
        warns.append(f"配置波束数 {n_cfg:.0f} 远小于几何建议 {n_geo}（波束半径 {fmt(beam_r,0)}km 密铺 "
                     f"{fmt(cov_r,0)}km 覆盖区）→ 单波束覆盖将大于配置波束半径，请核对波束宽度/覆盖匹配")
    return dict(el_deg=el, d_slant=d, psi_cov_deg=psi, cov_r_cap_km=cov_r_cap,
                cov_r_km=cov_r, beam_r_km=beam_r, N_beam_geo=n_geo,
                θ_beam_deg=th_beam, need_constellation=need_const,
                d_max_km=orb["d_max_km"], orbit_alt_km=h, warns=warns,
                note=f"仰角 {fmt(el,0)}° 最差路径斜距 {fmt(d,0)}km；单星覆盖半径上限 "
                     f"{fmt(cov_r_cap,0)}km；波束地心张角 {fmt(th_beam,2)}°")


def antenna_gain_est(cfg, f_dn):
    """按天线类型/子体制预估增益与波束宽度（需求推导用，与引擎公式一致）。"""
    lam = lam_m(f_dn)
    ant = cfg.get("ant_type", "相控阵")
    if ant == "相控阵":
        sub = cfg.get("array_subtype", "数字模拟混合")
        eta = to_f(cfg.get("η_ill"), ARRAY_SUBTYPES.get(sub, {}).get("eta", 0.62) * 100) / 100.0
        N_el = to_f(cfg.get("N_el"), 1024)
        G_el = to_f(cfg.get("G_el"), 6.0)
        th_scan = to_f(cfg.get("θ_scan"), 0)
        G = 10 * math.log10(max(N_el * eta, 1e-9)) + G_el
        scan_loss = (-10 * 1.5 * math.log10(max(math.cos(math.radians(th_scan)), 1e-6))
                     if th_scan > 0 else 0.0)
        G -= scan_loss
        L_side = math.sqrt(N_el * (lam / 2) ** 2)
        th3 = math.degrees(0.886 * lam / max(L_side, 1e-6))
        D_eff = 2 * L_side / math.sqrt(math.pi)
    else:
        eta = to_f(cfg.get("η_ill"), ANT_TYPES.get(ant, {}).get("eta_typ", 0.65) * 100) / 100.0
        D = to_f(cfg.get("D_ap"), 2.5)
        G = 10 * math.log10(max(eta * (math.pi * D / lam) ** 2, 1e-9))
        scan_loss = 0.0
        th3 = 70.0 * lam / D if D > 0 else 0.5
        D_eff = D
    return dict(G=G, θ3=th3, lam=lam, eta=eta, scan_loss=scan_loss, D_eff=D_eff, ant=ant)


def _t_sys_family(p, kg, fam):
    """与引擎同源的接收链 Friis 噪声温度（相控阵→ant_rx_path；其他→uplink）。"""
    ont = {o["id"]: o for o in kg["ontologies"]}
    chain_id = "ant_rx_path" if fam == "相控阵" else "uplink"
    chain = (ont.get(chain_id) or {}).get("chain") or []
    if not chain:
        return to_f(p.get("T_ant"), 50) + 150.0
    return propagate_rx(chain, p)["T_sys"]


# ================================================================
# 3 配置 → 引擎参数映射（需求推导 + 功放初反推）
# ================================================================
def cfg_to_params(cfg, geo, req, kg):
    band = cfg.get("band", "Ka")
    f_up, f_dn = BAND_FREQ.get(band, (30.0, 20.0))
    A_up, A_dn = BAND_RAIN.get(band, (0.0, 0.0))
    Bd = BANDS.get(band, BANDS["Ka"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    ant = cfg.get("ant_type", "相控阵")
    mode = cfg.get("mode", "数字透明")

    N_beam = int(to_f(cfg.get("N_beam"), geo["N_beam_geo"]) or geo["N_beam_geo"])
    B_beam = to_f(cfg.get("B_beam"), 125)
    B_car = min(to_f(cfg.get("B_carrier"), B_beam), B_beam)
    k_reuse = int(to_f(cfg.get("k_reuse"), cov["k_typ"]))

    ag = antenna_gain_est(cfg, f_dn)
    G_ant, th3 = ag["G"], ag["θ3"]
    θ_e = min(0.10, th3 / 20.0) if ant == "相控阵" else min(0.05, th3 / 14.0)
    L_pnt = min(12.0 * (θ_e / max(th3, 1e-6)) ** 2, 1.5)

    # 大气损耗（与 p 中存值完全一致，避免推导/引擎偏差）
    A_atm = 0.4 if band in ("Ka", "Q/V") else (0.15 if band in ("Ku", "X") else 0.05)
    A_atm_dl = 0.2 if band in ("Ka", "Q/V") else (0.12 if band in ("Ku", "X") else 0.05)

    d = geo["d_slant"]
    Lfs_up = fspl(d, f_up)
    Lfs_dn = fspl(d, f_dn)
    avail = to_f(cfg.get("A_avail"), req["avail"])
    A_dyn = cov.get("margin_add_db", 0.0)
    el = geo["el_deg"]
    ΣL_up = rain_at_avail(A_up, avail, el) + A_atm + L_pnt + 0.3 + 1.0 + A_dyn
    ΣL_dn = rain_at_avail(A_dn, avail, el) + A_atm_dl + L_pnt + 0.3 + 1.0 + A_dyn
    M_t = to_f(cfg.get("M_target"), 3.0)
    CN_des = req["design_cn"]
    B_hz = 10 * math.log10(max(B_car, 1e-9) * 1e6)
    share_db = 10 * math.log10(max(B_beam / max(B_car, 1e-9), 1.0))

    # 需求反推：星上 G/T 需求（上行闭合）与星上整波束 EIRP 需求（下行闭合）
    GT_req = CN_des + M_t + B_hz - req["EIRP_term"] + Lfs_up + ΣL_up + K_BOLTZ_DB
    EIRP_req_car = CN_des + M_t + B_hz - req["GT_term"] + Lfs_dn + ΣL_dn + K_BOLTZ_DB
    EIRP_req = EIRP_req_car + share_db

    # 功放初反推（选定货架天线后在 design_all 中按货架增益重新反推）
    L_feed = to_f(cfg.get("L_feed"), 0.5 if ant == "相控阵" else (1.0 if ant == "伞状" else 0.8))
    amp_guess = cfg.get("amp_type") or MODE_HPA.get(mode, "TWTA")
    L_tx = L_TX_BY_AMP.get(amp_guess, 4.7)
    P_out_w = to_f(cfg.get("P_out"), 0)
    p_out_source = "用户指定"
    if P_out_w <= 0:
        P_out_w = 10 ** ((EIRP_req + EIRP_GUARD_DB - G_ant + L_feed + L_tx) / 10.0)
        p_out_source = (f"EIRP 需求反推：P_out = EIRP_req({fmt(EIRP_req,1)}dBW)+{EIRP_GUARD_DB}守卫 "
                        f"− G_ant({fmt(G_ant,1)}dBi) + L_feed({fmt(L_feed,1)}) + L_tx({fmt(L_tx,1)})")

    freq_ok = N_beam * B_beam <= B_TOTAL_OVR.get(band, Bd["B_total"]) * k_reuse

    p = dict(
        orbit=cfg.get("orbit", "GEO"), d_slant=d, d_dl=d, el_deg=el,
        A_avail=str(avail), L_life=to_f(cfg.get("life_yr"), orb["life_yr"]),
        band=band, f_up=f_up, f_down=f_dn, A_up_ref=A_up, A_dn_ref=A_dn,
        A_atm=A_atm, A_atm_dl=A_atm_dl,
        L_pol=0.3, L_impl=1.0, B_total=B_TOTAL_OVR.get(band, Bd["B_total"]),
        k_reuse=str(k_reuse),
        ant_type=ANT_MAP.get(ant, "相控阵天线"),
        D_ap=to_f(cfg.get("D_ap"), 2.5 if ant != "相控阵" else ag["D_eff"]),
        N_el=to_f(cfg.get("N_el"), 1024), G_el=to_f(cfg.get("G_el"), 6.0),
        η_ill=ag["eta"] * 100, θ_scan=to_f(cfg.get("θ_scan"), 0), G_ant_ovr="",
        δ_surf=(0.20 if band in ("Ka", "Q/V") else (0.35 if band in ("Ku", "X")
                else (2.0 if ant == "伞状" else 1.0))),
        δ_dep=(0.20 if band in ("Ka", "Q/V") else (0.30 if band in ("Ku", "X")
               else (1.5 if ant == "伞状" else 0.8))),
        SLL=-22, AR=1.5, Δ_amp=0.4, Δ_phs=4.0, Δ_cal=0.3,
        θ_e=θ_e, Δ_pnt=0.02, L_feed=L_feed,
        N_beam=N_beam, B_beam=B_beam, B_carrier=B_car,
        n_pol=to_f(cfg.get("n_pol"), 2),
        Mode=cfg.get("Mode", "多波束"), Mode_req=cfg.get("Mode", "多波束"),
        N_bf=max(N_beam, 1), N_port=max(N_beam, 1), N_sch=max(N_beam, 1),
        T_ant=T_ANT_BY_BAND.get(band, 50),
        amp_type=amp_guess, P_out=round(P_out_w, 3),
        η_pa=ETA_PA.get(amp_guess, 58), L_tx=L_tx, IMD3=-25, I_iso=100, A_rej=60,
        NF_lna=NF_BY_BAND.get(band, 1.6),
        G_lna=40 if band in ("L", "S", "Ku") else 35,
        NF_trp="", T_sys_ovr="", I_sw=80,
        arch=ARCH_MAP.get(mode, "DTP数字透明处理器"),
        B_trp=max(36.0, math.ceil(N_beam * B_beam / max(k_reuse, 1) / 36.0) * 36.0),
        G_trp="", Δ_flat=1.0, I_trp=85, τ_trans=200,
        ΔM_reg=MODES.get(mode, {}).get("regen_bonus", 4.5),
        τ_reg=40 if mode == "再生" else 3,
        C_sw=10, N_ch=1, B_sub=40 if band in ("Ku", "Ka") else 25,
        t_reconf=10, C_dsw=100, C_ib=80, T_j=105,
        P_tr=ARR_P_PER_EL.get(cfg.get("array_subtype", ""), 0.9) if ant == "相控阵" else 8.0,
        EIRP_gs=to_f(cfg.get("EIRP_gs"), 75), GT_gs=to_f(cfg.get("GT_term"), req["GT_term"]),
        P_opt=1.0, D_opt=135, λ_opt=1550, η_opt=60, θ_div=100,
        d_isl=5000 if cfg.get("orbit") == "LEO" else (8000 if cfg.get("orbit") == "MEO" else 30000),
        G_edfa=25, S_opt=-42, CN_dpsk=8.0, EIRP_opt=105, GT_opt=118,
        σ_track=0.8, σ_jit=3.0, P_acq=97, t_acq=30, θ_fsm=3.0, L_turb=1.5, P_cloud=8,
        R_isl=to_f(cfg.get("isl_r_gbps"), 10) if cfg.get("isl_on") else 0, R_sgl=0,
        R_pdl=0, T_blind=15, CR=4, R_bus=4000, E_store=4.0,
        R_bb=2000, R_dpu=1500, AI_TOPS=20, MIPS=4000, N_hop=2, t_rec=5, BER_int=1e-12,
        EIRP_req=EIRP_req, GT_req=GT_req, C_req=req["C_req"],
        M_budget=0, P_budget=0, N_gap=0, H_scheme="4", M_target=M_t,
    )
    # 体制相关的信道化/交换参数
    B_trp = p["B_trp"]
    if mode == "数字透明":
        C_need = N_beam * B_beam * 2.5 / 1000.0
        p["C_sw"] = math.ceil(C_need / 50.0) * 50.0 + 50.0
        p["N_ch"] = max(8, math.ceil(B_trp / p["B_sub"]))
        p["C_dsw"] = p["C_sw"]
    elif mode == "再生":
        C_need = N_beam * B_beam * 2.5 / 1000.0
        p["C_sw"] = math.ceil(C_need / 50.0) * 50.0 + 50.0
        p["N_ch"] = N_beam
        p["B_sub"] = B_beam
        p["C_dsw"] = p["C_sw"]
    else:  # 透明：整带信道
        p["N_ch"] = 1
        p["B_sub"] = B_trp
        p["C_sw"] = 10

    # 与引擎同源的接收链噪声温度（供天线 G/T 能力精确评估）
    t_sys = {fam: _t_sys_family(p, kg, fam) for fam in ("相控阵", "固面", "伞状")}
    # 反射面类体制（大容量多波束/混合多波束）接收链与固面同源（LNA 首级）
    t_sys["大容量多波束"] = t_sys["固面"]
    t_sys["混合多波束"] = t_sys["固面"]

    p["_derived"] = dict(
        G_ant_est=G_ant, θ_3dB_est=th3, Lfs_up=Lfs_up, Lfs_dn=Lfs_dn,
        ΣL_up=ΣL_up, ΣL_dn=ΣL_dn, GT_req=GT_req, EIRP_req_car=EIRP_req_car,
        EIRP_req=EIRP_req, freq_ok=freq_ok, A_dyn=A_dyn, k_reuse=k_reuse,
        N_beam=N_beam, share_db=share_db, CN_des=CN_des, L_pnt=L_pnt,
        P_out_req_w=P_out_w, P_out_w=P_out_w, p_out_source=p_out_source,
        L_feed=L_feed, L_tx=L_tx, design_cn=CN_des, d_slant=d, B_hz=B_hz,
        t_sys=t_sys, rain_up=rain_at_avail(A_up, avail, el), rain_dn=rain_at_avail(A_dn, avail, el),
    )
    return p


def rederive_power(p, G_used, amp):
    """选定天线（货架增益 G_used）后重新反推功放功率，并写回参数。"""
    der = p["_derived"]
    L_tx = L_TX_BY_AMP.get(amp, 4.7)
    P_out_w = to_f(p.get("P_out_user"), 0)
    src = "用户指定"
    if P_out_w <= 0:
        P_out_w = 10 ** ((der["EIRP_req"] + EIRP_GUARD_DB - G_used + der["L_feed"] + L_tx) / 10.0)
        src = (f"EIRP 需求反推：P_out = EIRP_req({fmt(der['EIRP_req'],1)}dBW)+{EIRP_GUARD_DB}dB守卫 "
               f"− G_ant({fmt(G_used,1)}dBi) + L_feed({fmt(der['L_feed'],1)}dB) + L_tx({fmt(L_tx,1)}dB)")
    p["P_out"] = round(P_out_w, 3)
    p["amp_type"] = amp
    p["η_pa"] = ETA_PA.get(amp, 58)
    p["L_tx"] = L_tx
    p["G_ant_ovr"] = G_used
    der.update(P_out_w=P_out_w, P_out_req_w=P_out_w, p_out_source=src,
               G_ant_used=G_used, L_tx=L_tx)
    return P_out_w


# ================================================================
# 4 天线五维选型（货架产品评分）
# ================================================================
def _ant_family(uid):
    if "AESA" in uid:
        return "相控阵"
    if "UMB" in uid:
        return "伞状"
    if "VHTS" in uid:
        return "大容量多波束"
    if "HYB" in uid:
        return "混合多波束"
    return "固面"


def _shelf_ant_gain(prod, band):
    sp = prod["specs"]
    if band == "L" and sp.get("G_L"):
        return to_f(sp["G_L"])
    if band == "S" and sp.get("G_S"):
        return to_f(sp["G_S"])
    return to_f(sp.get("G"), 40.0)


def hpa_feasible(fam, G_prod, P_out_cand, N_beam, N_el_prod, specs):
    """功放可行性：反推功率是否可被该天线体制承载。返回 (ok, s_eirp, detail)"""
    if fam == "相控阵":
        n_el = to_f(specs.get("N_el"), N_el_prod or 1024)
        p_per_el = P_out_cand * max(N_beam, 1) / max(n_el, 1)
        ok = p_per_el <= P_PER_EL_MAX
        s = 10.0 if ok else max(0.0, 10 - 4 * math.log10(p_per_el / P_PER_EL_MAX))
        return ok, s, f"每阵元辐射 {fmt(p_per_el,2)}W（上限 {P_PER_EL_MAX}W）"
    p_max = P_HPA_MAX.get(fam, 250.0)
    ok = P_out_cand <= p_max
    s = 10.0 if ok else max(0.0, 10 - 4 * math.log10(P_out_cand / p_max))
    return ok, s, f"单波束功放 {fmt(P_out_cand,1)}W（{fam}体制上限 {fmt(p_max,0)}W）"


def select_antennas(cfg, p, platform=None):
    """频段硬过滤 + 五维评分（① EIRP ② G/T ③ 重量 ④ 功耗 ⑤ 工作模式）。

    语义：选定天线后按货架增益反推功放 → 功放可行则 EIRP 维满分；
    G/T 用与引擎同源的 Friis 链噪声温度精确评估。
    返回 (candidates, recommended, is_custom, custom)
    """
    band = cfg.get("band", "Ka")
    ant_want = cfg.get("ant_type", "相控阵")
    der = p.get("_derived", {})
    EIRP_req = der.get("EIRP_req", 60.0)
    GT_req = der.get("GT_req", 10.0)
    mode_req = MODE_CAP.get(cfg.get("Mode", "多波束"), 2)
    N_beam_req = der.get("N_beam", 1)
    m_cap = platform["m_pay"] if platform else 1200.0
    p_cap = platform["p_pay"] if platform else 10000.0
    L_feed = der.get("L_feed", 0.8)
    amp_guess = cfg.get("amp_type") or MODE_HPA.get(cfg.get("mode", "数字透明"), "TWTA")
    L_tx = L_TX_BY_AMP.get(amp_guess, 4.7)
    t_sys = der.get("t_sys", {})

    cands = []
    for u in SHELF_UNITS:
        uid, cn, cat, bands, level, mass, power, specs, note = u
        if cat != "天线" or band not in bands:
            continue                              # 频段硬过滤
        fam = _ant_family(uid)
        G_prod = _shelf_ant_gain(SHELF_BY_ID[uid], band)
        # ① EIRP：按货架增益反推所需功放 → 体制可行性
        P_cand = 10 ** ((EIRP_req + EIRP_GUARD_DB - G_prod + L_feed + L_tx) / 10.0)
        ok_e, s_eirp, e_detail = hpa_feasible(fam, G_prod, P_cand, N_beam_req,
                                              to_f(cfg.get("N_el"), 0), specs)
        # ② G/T：货架增益 − 与引擎同源的接收链噪声温度
        T_fam = to_f(t_sys.get(fam), to_f(p.get("T_ant"), 50) + 150.0)
        gt_cap = G_prod - 10 * math.log10(max(T_fam, 1e-6))
        s_gt = 10.0 if gt_cap >= GT_req else max(0.0, 10 - 1.5 * (GT_req - gt_cap))
        # ③④ 重量/功耗：占平台比例
        s_mass = max(0.0, min(10.0, 10 * (1 - mass / max(m_cap, 1e-6))))
        s_pow = max(0.0, min(10.0, 10 * (1 - power / max(p_cap, 1e-6))))
        # ⑤ 工作模式与波束数
        cap_mode = ANT_MODE_CAP.get(fam, 2)
        n_beam_cap = to_f(specs.get("N_beam"), 64 if fam != "伞状" else 19)
        s_mode = 10.0 if cap_mode >= mode_req else 10.0 * cap_mode / max(mode_req, 1)
        if n_beam_cap < N_beam_req:
            s_mode *= 0.6
        score = 0.30 * s_eirp + 0.25 * s_gt + 0.15 * s_mass + 0.15 * s_pow + 0.15 * s_mode
        if fam == ant_want:
            score += 1.0
        score += 0.2 * (level - 3)
        reasons = [
            f"① EIRP：G={fmt(G_prod,1)}dBi → 反推 P_out={fmt(P_cand,1)}W/波束；{e_detail} → {fmt(s_eirp,1)}/10",
            f"② G/T：{fmt(G_prod,1)} − 10lg({fmt(T_fam,0)}K) = {fmt(gt_cap,1)}dB/K vs 需求 {fmt(GT_req,1)}dB/K → {fmt(s_gt,1)}/10",
            f"③ 质量：{fmt(mass,0)}kg（平台承载 {fmt(m_cap,0)}kg）→ {fmt(s_mass,1)}/10",
            f"④ 功耗：{fmt(power,0)}W（平台供电 {fmt(p_cap,0)}W）→ {fmt(s_pow,1)}/10",
            f"⑤ 模式：{['—','单波束','多波束','波束跳变','在轨重构'][cap_mode]}、波束数 {fmt(n_beam_cap,0)} "
            f"vs 需求 {cfg.get('Mode','多波束')}/{N_beam_req} → {fmt(s_mode,1)}/10",
        ]
        if fam == ant_want:
            reasons.append(f"类型与指定一致（{ANT_TYPES[ant_want]['cn']}，+1.0）")
        reasons.append(f"货架水平 {level}（{['','定制','在研转货架','飞行继承','飞行继承货架'][level]}，{0.2*(level-3):+.1f}）")
        cands.append((round(score, 2), SHELF_BY_ID[uid], reasons,
                      dict(EIRP=round(s_eirp, 1), GT=round(s_gt, 1), mass=round(s_mass, 1),
                           power=round(s_pow, 1), mode=round(s_mode, 1), fam=fam,
                           P_cand=round(P_cand, 2), gt_cap=round(gt_cap, 2), G=G_prod,
                           ok_eirp=ok_e)))
    cands.sort(key=lambda x: -x[0])

    m_cust = estimate_antenna_mass(cfg, p)
    p_cust = estimate_antenna_power(cfg, p)
    custom = dict(id="ANT-CUSTOM", cn=f"自研{ANT_TYPES.get(ant_want, {}).get('cn', '天线')}",
                  cat="天线", bands=[band], level=1, mass=round(m_cust, 1), power=round(p_cust, 1),
                  specs=dict(G=round(der.get("G_ant_est", 0), 1), N_beam=der.get("N_beam", 1),
                             N_el=to_f(cfg.get("N_el"), 0), D=to_f(cfg.get("D_ap"), 0)),
                  note="按用户配置电气参数估算（非货架，计入 N_gap）")

    recommended, is_custom = None, False
    if cands:
        same = [c for c in cands if c[3]["fam"] == ant_want]
        recommended = same[0] if same else cands[0]
        ds = recommended[3]
        # 货架电气能力不足（EIRP 功放不可行或 G/T 缺口大）→ 转定制
        if (not ds["ok_eirp"]) or ds["GT"] < 6.0:
            is_custom = True
            custom = dict(custom)
            custom["specs"] = dict(custom["specs"], G=round(der.get("G_ant_est", 0), 1))
            recommended = (round(recommended[0] - 2.0, 2), custom,
                           [f"货架产品不满足需求：最接近 {cands[0][1]['id']}（{cands[0][1]['cn']}）"
                            f"，EIRP 可行={ds['ok_eirp']}、G/T 能力 {fmt(ds['gt_cap'],1)}dB/K vs 需求 "
                            f"{fmt(GT_req,1)}dB/K → 转定制（N_gap+1）或增大口径/阵元数"]
                           + recommended[2], ds)
    else:
        is_custom = True
        recommended = (0.0, custom, [f"{band} 频段无货架天线产品 → 转定制（N_gap+1）"],
                       dict(EIRP=0, GT=0, mass=0, power=0, mode=0, fam=ant_want,
                            P_cand=0, gt_cap=0, G=der.get("G_ant_est", 0), ok_eirp=False))
    return cands, recommended, is_custom, custom


def estimate_antenna_mass(cfg, p):
    ant = cfg.get("ant_type", "相控阵")
    if ant == "相控阵":
        sub = cfg.get("array_subtype", "数字模拟混合")
        return to_f(cfg.get("N_el"), 1024) * ARR_M_PER_EL.get(sub, 0.045) + 10.0
    D = to_f(cfg.get("D_ap"), 2.5)
    m = math.pi * (D / 2) ** 2 * ANT_TYPES.get(ant, {}).get("mass_per_m2", 10.0) + 8.0
    if ant == "混合多波束":
        # 馈电阵模组（2.5kg/64元模组）
        m += to_f(cfg.get("N_el_feed"), 256) / 64.0 * 2.5
    if ant == "大容量多波束" and to_f(cfg.get("D_ap"), 3.5) > 3.0:
        m += 28.0     # 3.5m 级可展开机构
    return m


def estimate_antenna_power(cfg, p):
    ant = cfg.get("ant_type", "相控阵")
    if ant == "相控阵":
        sub = cfg.get("array_subtype", "数字模拟混合")
        return to_f(cfg.get("N_el"), 1024) * ARR_P_PER_EL.get(sub, 0.9) + 30.0
    if ant == "混合多波束":
        # 馈电阵（默认 256 元 × 1.4W）+ 反射面无源部分
        n_feed = to_f(cfg.get("N_el_feed"), 256)
        return n_feed * 1.4 + 60.0
    if ant == "大容量多波束":
        # 成形反射面无源 + 馈电网络/校准（波束数相关的低功率电子）
        n_beam = to_f(cfg.get("N_beam"), 233)
        return 120.0 + min(n_beam, 400) * 0.15
    return 95.0 if ant == "固面" else 40.0


# ================================================================
# 5 转发器方案（EIRP 反推 → HPA 选型 → 信道化）
# ================================================================
def plan_transponder(cfg, p, is_custom_ant=False):
    """按体制 + 功放需求选 HPA（货架优先、功率就近），给出转发器方案。"""
    der = p.get("_derived", {})
    band = cfg.get("band", "Ka")
    mode = cfg.get("mode", "数字透明")
    ant = cfg.get("ant_type", "相控阵")
    N_beam = der.get("N_beam", 16)
    P_out_req = der.get("P_out_w", 100.0)
    amp_pref = cfg.get("amp_type") or MODE_HPA.get(mode, "TWTA")

    distributed = (ant == "相控阵")
    hpa, n_hpa, p_hpa_dc, hpa_note = None, 0, 0.0, ""
    if distributed:
        n_el = to_f(cfg.get("N_el"), 1024)
        p_per_el_w = P_out_req * N_beam / max(n_el, 1)
        η_el = 0.30
        p_hpa_dc = P_out_req * N_beam / η_el
        if is_custom_ant:
            hpa = dict(id="TR-ARRAY", cn=f"{band} T/R 阵列功放（分布式）", cat="功放",
                       mass=0.0, power=round(p_hpa_dc, 1), level=2,
                       specs=dict(P_total=round(P_out_req * N_beam, 1)),
                       note=(f"功放分布式集成于 T/R 组件：每阵元辐射 {fmt(p_per_el_w,2)}W，"
                             f"阵面射频总功率 {fmt(P_out_req*N_beam,0)}W，直流 {fmt(p_hpa_dc,0)}W"))
        else:
            p_hpa_dc = 0.0        # 货架相控阵天线的功放功耗已含在天线产品功耗内
            hpa = dict(id="TR-IN-ANT", cn="T/R 功放（集成于货架天线）", cat="功放",
                       mass=0.0, power=0.0, level=4,
                       specs=dict(P_total=round(P_out_req * N_beam, 1)),
                       note=(f"货架相控阵天线已集成 T/R 功放链：每波束 {fmt(P_out_req,1)}W × {N_beam} 波束 = "
                             f"射频 {fmt(P_out_req*N_beam,0)}W（功耗已计入天线产品，不重复计）"))
        hpa_note = hpa["note"]
    else:
        best = None
        for u in SHELF_UNITS:
            uid, cn, cat, bands, level, mass, power, specs, note = u
            if cat != "功放" or band not in bands or uid in ("MPA-8X8", "EPC-01"):
                continue
            P_prod = to_f(specs.get("P"), 0)
            if P_prod < P_out_req * 0.95:
                continue
            flight = 1 if level >= 3 else 0
            key = (flight, -abs(P_prod - P_out_req), level)
            if best is None or key > best[0]:
                best = (key, SHELF_BY_ID[uid], P_prod)
        if best is None:
            pool = [SHELF_BY_ID[u[0]] for u in SHELF_UNITS
                    if u[2] == "功放" and band in u[3] and u[0] not in ("MPA-8X8", "EPC-01")]
            pool.sort(key=lambda x: -to_f(x["specs"].get("P"), 0))
            base = pool[0] if pool else SHELF_BY_ID["TWTA-KA-180"]
            n_comb = max(1, math.ceil(P_out_req / max(to_f(base["specs"].get("P"), 1), 1e-6)))
            hpa = dict(base, level=1,
                       note=base["note"] + f"；单管 {to_f(base['specs'].get('P'),0):.0f}W 不足 → "
                            f"{n_comb} 路功率合成至 {fmt(P_out_req,0)}W（定制缺口）")
            hpa_note = hpa["note"]
        else:
            hpa, P_prod = best[1], best[2]
            hpa_note = (f"单波束需求 {fmt(P_out_req,1)}W → 货架就近选 {hpa['id']}"
                        f"（{to_f(hpa['specs'].get('P'),0):.0f}W，功率余量 {fmt(P_prod-P_out_req,1)}W）")
        if amp_pref == "MPA":
            n_mpa = math.ceil(N_beam / 8)
            n_hpa = n_mpa + (1 if n_mpa > 1 else 0)
            hpa = SHELF_BY_ID["MPA-8X8"]
            p_hpa_dc = P_out_req * N_beam / 0.42
            hpa_note = (f"MPA 功率池：8×8 矩阵 {n_hpa} 台（每台覆盖 8 波束 + 1 备），"
                        f"射频总功率 {fmt(P_out_req*N_beam,0)}W，直流 {fmt(p_hpa_dc,0)}W；单管故障功率重构")
        else:
            n_hpa = N_beam + math.ceil(N_beam / 8)
            p_hpa_dc = P_out_req * N_beam / (ETA_PA.get(amp_pref, 58) / 100.0)
            hpa_note += f"；环备份 1/8 → 共 {n_hpa} 台；直流总功耗 {fmt(p_hpa_dc,0)}W"

    B_trp = to_f(p.get("B_trp"), 1000)
    B_sub = to_f(p.get("B_sub"), 40)
    N_ch = int(to_f(p.get("N_ch"), 1))
    trp = dict(mode=mode, mode_cn=MODES.get(mode, {}).get("cn", mode),
               chain=MODES.get(mode, {}).get("chain", ""),
               N_beam=N_beam, B_beam=to_f(p.get("B_beam"), 125),
               B_carrier=to_f(p.get("B_carrier"), 36), B_trp=B_trp,
               N_ch=N_ch, B_sub=B_sub, C_sw=to_f(p.get("C_sw"), 100),
               P_out_w=P_out_req, P_out_source=der.get("p_out_source", ""),
               amp=amp_pref, distributed=distributed,
               hpa=hpa, n_hpa=n_hpa, p_hpa_dc=round(p_hpa_dc, 1), hpa_note=hpa_note,
               delay_ms=MODE_DELAY_MS.get(mode, 1.0),
               noise=MODES.get(mode, {}).get("noise", ""),
               flex=MODES.get(mode, {}).get("flex", ""),
               regen_bonus=MODES.get(mode, {}).get("regen_bonus", 0.0),
               n_trp_chan=max(1, math.ceil(N_beam / max(int(to_f(p.get("k_reuse"), 4)), 1))))
    return trp


# ================================================================
# 6 货架单机清单
# ================================================================
def pick_shelf(cat, band, exclude=()):
    best = None
    for u in SHELF_UNITS:
        uid, cn, c, bands, level, mass, power, specs, note = u
        if c != cat or uid in exclude:
            continue
        if band not in bands and "*" not in bands:
            continue
        key = (level, -mass)
        if best is None or key > best[0]:
            best = (key, SHELF_BY_ID[uid])
    return best[1] if best else None


def build_equipment(cfg, p, trp, ant_rec, is_custom_ant, custom_ant):
    """按体制+频段+天线方案生成单机清单（货架优先，数量/功耗由链路预算反推）。"""
    band = cfg.get("band", "Ka")
    fband = cfg.get("feeder_band", band)
    mode = cfg.get("mode", "数字透明")
    ant = cfg.get("ant_type", "相控阵")
    sub = cfg.get("array_subtype", "")
    N_beam = trp["N_beam"]
    n_trp = trp["n_trp_chan"]
    rows = []

    def add(cat, band_sel, qty, why, force_id=None, power_ovr=None, mass_ovr=None, level_ovr=None):
        qty = int(max(qty, 0))
        if qty <= 0:
            return None
        prod = SHELF_BY_ID.get(force_id) if force_id else pick_shelf(cat, band_sel)
        if prod is None and force_id is None:
            prod = pick_shelf(cat, "*")
        if prod is None:
            rows.append(dict(id="定制", cn=f"定制{cat}", cat=cat, band=band_sel, qty=qty,
                             mass=round(to_f(mass_ovr, 0), 2), power=round(to_f(power_ovr, 0), 1),
                             level=1, note=f"无货架 {cat} 产品（{band_sel}）→ 定制", why=why))
            return None
        rows.append(dict(id=prod["id"], cn=prod["cn"], cat=prod["cat"], band=band_sel, qty=qty,
                         mass=round(to_f(mass_ovr, prod["mass"] * qty), 2),
                         power=round(to_f(power_ovr, prod["power"] * qty), 1),
                         level=level_ovr if level_ovr else prod["level"],
                         note=prod["note"], why=why, specs=prod["specs"]))
        return prod

    # ---- 天线分系统 ----
    aprod = ant_rec[1]
    rows.append(dict(id=aprod["id"], cn=aprod["cn"], cat="天线", band=band, qty=1,
                     mass=round(aprod["mass"], 1), power=round(aprod["power"], 1),
                     level=1 if is_custom_ant else aprod["level"],
                     note=aprod["note"],
                     why=("货架缺口 → 定制（计入 N_gap）" if is_custom_ant else "五维选型评分第一"),
                     specs=aprod.get("specs", {})))
    if fband != band:
        fp = pick_shelf("天线", fband)
        if fp:
            rows.append(dict(id=fp["id"], cn=fp["cn"] + "（馈电）", cat="天线", band=fband, qty=1,
                             mass=fp["mass"], power=fp["power"], level=fp["level"],
                             note=fp["note"], why=f"馈电链路 {fband} 频段独立天线",
                             specs=fp["specs"]))
        else:
            rows.append(dict(id="定制", cn=f"定制{fband}馈电天线", cat="天线", band=fband, qty=1,
                             mass=60.0, power=80.0, level=1,
                             note=f"无货架 {fband} 天线 → 定制", why="馈电链路独立频段"))
    if ant == "相控阵":
        n_el = int(to_f(cfg.get("N_el"), 1024))
        tr_id = {"L": "TR-L-01", "S": "TR-L-01", "Ku": "TR-KU-01", "Ka": "TR-KA-01"}.get(band)
        if is_custom_ant and tr_id:
            add("相控阵组件", band, n_el, f"T/R 组件 ×N_el={n_el}（阵面功放分布式集成）",
                force_id=tr_id, power_ovr=trp["p_hpa_dc"],
                mass_ovr=n_el * ARR_M_PER_EL.get(sub, 0.045), level_ovr=2)
        if sub == "数字模拟混合":
            add("相控阵组件", band, math.ceil(n_el / 16),
                f"子阵级波束赋形通道（N_el/16={math.ceil(n_el/16)}）", force_id="BFN-01")
        elif sub == "纯数字":
            add("数字处理", band, math.ceil(n_el / 4), "纯数字 DBF 通道（每 4 元 1 路 ADC/DAC）",
                force_id="ADC-1200")
        elif sub in ("直射阵", "模拟拼接"):
            add("相控阵组件", band, math.ceil(n_el / 8), "模拟移相/幅相控制通道（N_el/8）",
                force_id="PS-6BIT")
        add("相控阵组件", band, 1, "波束校准网络（幅相一致性 c-23 ≤0.5dB/5°）", force_id="CAL-NET-01")
        if is_custom_ant:
            add("机构", band, 1,
                "相控阵展开机构（大口径）" if to_f(cfg.get("D_ap"), 0) > 3 else "阵面安装结构",
                force_id="DEP-MECH-AESA")
    if ant == "伞状":
        add("机构", band, 1, "伞天线展开机构（到位精度 ≤δ_surf，c-5）", force_id="DEP-MECH-12M")
        add("机构", band, 1, "两轴指向机构（步距 0.02°）", force_id="PNT-2AXIS")
    if ant == "大容量多波束":
        if to_f(cfg.get("D_ap"), 3.5) > 3.0:
            add("机构", band, 1, "3.5m 级可展开反射面机构（面精度 0.10mm RMS，c-5）",
                force_id="DEP-MECH-35")
        add("测控信标", band, 1, "天线控制单元 ACU（指向/波束切换 50ms）", force_id="ACU-01")
        add("相控阵组件", band, math.ceil(N_beam / 8),
            f"高密度馈源阵波束赋形网络（{N_beam} 波束成形，BFN 通道 {math.ceil(N_beam/8)*64}）",
            force_id="BFN-01")
        add("相控阵组件", band, 1, "馈源阵幅相校准网络（数百通道一致性 ≤0.3dB）",
            force_id="CAL-NET-01")
    if ant == "混合多波束":
        if to_f(cfg.get("D_ap"), 3.0) > 3.0:
            add("机构", band, 1, "3.5m 级可展开反射面机构（面精度 0.10mm RMS，c-5）",
                force_id="DEP-MECH-35")
        add("测控信标", band, 1, "天线控制单元 ACU（指向/波束切换 50ms）", force_id="ACU-01")
        n_feed = int(to_f(cfg.get("N_el_feed"), 256))
        add("相控阵组件", band, math.ceil(n_feed / 64),
            f"焦面有源馈电阵模组（{n_feed} 元，±6° 电扫波束重构/跳变/零陷）",
            force_id="FEED-ARR-KA" if band == "Ka" else None)
        add("相控阵组件", band, 1, "馈电阵幅相校准网络（两级一致性 ≤0.3dB）",
            force_id="CAL-NET-01")
        add("开关", band, 1, "波束切换开关矩阵（波束跳变体制）", force_id="SW-BEAM-01")
    if ant in ("固面", "伞状"):
        add("测控信标", band, 1, "天线控制单元 ACU（指向/波束切换 50ms）", force_id="ACU-01")
        if N_beam > 1:
            add("相控阵组件", band, math.ceil(N_beam / 8),
                f"多馈源波束赋形网络（{N_beam} 波束成形）", force_id="BFN-01")

    # ---- 接收通道 ----
    add("开关", band, n_trp, "环行器/隔离器（收发隔离 ≥100dB，c-15）", force_id="CIRC-01")
    add("LNA", band, 2 * n_trp, f"低噪放 LNA（{n_trp} 路 × A/B 冷备）")
    add("变频", band, n_trp, "下变频器（变频损耗 2dB，镜像抑制 >60dBc）", force_id="DCONV-01")
    add("变频", band, 2, "频率源/本振（1+1，相位噪声 −95dBc/Hz@10kHz）", force_id="LO-SRC-01")

    # ---- 转发器（体制单机链）----
    if mode == "透明":
        add("多工器", band, math.ceil(n_trp / 8),
            f"输入多工器 IMUX（{n_trp} 通道 / 8 通道每台）", force_id="IMUX-01")
        add("开关", band, n_trp, "均衡器/可变衰减器（通带平坦度 ≤1dB）", force_id="ATT-01")
        add("开关", band, 2, "微波开关矩阵（通道倒换，隔离 80dB）", force_id="SW-MTX-01")
        add("变频", band, n_trp, "上变频器", force_id="UCONV-01")
    elif mode == "数字透明":
        n_dtp = max(1, math.ceil(trp["B_trp"] / 1200.0))
        add("数字处理", band, n_dtp,
            f"DTP 数字透明处理器（B_trp={fmt(trp['B_trp'],0)}MHz，交换容量 {fmt(trp['C_sw'],0)}Gbps）",
            force_id="DTP-PROC-01")
        add("数字处理", band, n_dtp * 4, "宽带 ADC 数字信道化（每台 DTP 4 路）", force_id="ADC-1200")
        add("数字处理", band, n_dtp * 4, "宽带 DAC 重构", force_id="DAC-01")
        add("星务", band, 1, "在轨重构控制器（波束/子带/功率/路由四维重构）", force_id="RECONF-CTRL")
        add("变频", band, n_trp, "上变频器", force_id="UCONV-01")
    else:
        add("再生基带", band, n_trp, f"DVBS2X 调制解调器（{n_trp} 通道，ACM/VCM 自适应）",
            force_id="MODEM-S2X")
        add("再生基带", band, n_trp, "LDPC/BCH 编译码器（编码增益 6.5dB）", force_id="CODER-LDPC")
        add("再生基带", band, 2, "星上路由交换单元（1+1，跨波束单跳）", force_id="ROUTER-01")
        add("再生基带", band, 2, "基带处理单元（1+1）", force_id="BB-PROC-01")
        add("星务", band, 1, "AI 推理单元（资源调度/业务预测/抗干扰）", force_id="AI-UNIT-01")
        add("变频", band, n_trp, "上变频器", force_id="UCONV-01")

    # ---- 发射通道（HPA 由 EIRP 反推选型）----
    h = trp["hpa"]
    if h:
        if trp["distributed"]:
            if h["power"] > 0 or h["id"] == "TR-ARRAY":
                rows.append(dict(id=h["id"], cn=h["cn"], cat="功放", band=band,
                                 qty=int(to_f(cfg.get("N_el"), 1024)) if h["id"] == "TR-ARRAY" else 1,
                                 mass=0.0, power=h["power"], level=h["level"], note=h["note"],
                                 why=f"EIRP 反推：{trp['P_out_source']}", specs=h["specs"]))
            else:
                rows.append(dict(id=h["id"], cn=h["cn"], cat="功放", band=band, qty=1,
                                 mass=0.0, power=0.0, level=h["level"], note=h["note"],
                                 why=f"EIRP 反推：{trp['P_out_source']}", specs=h["specs"]))
            if h["id"] == "TR-ARRAY":
                add("功放", band, 4, "EPC 电子功率调节器（6kV 高压，过流过压保护）", force_id="EPC-01")
        else:
            n_h = trp["n_hpa"]
            rows.append(dict(id=h["id"], cn=h["cn"], cat="功放", band=band, qty=n_h,
                             mass=round(h["mass"] * n_h, 1), power=trp["p_hpa_dc"],
                             level=h["level"], note=h["note"],
                             why=f"EIRP 反推：{trp['P_out_source']}；{h['note']}",
                             specs=h["specs"]))
            add("功放", band, max(1, math.ceil(n_h / 4)), "EPC 电子功率调节器", force_id="EPC-01")
    add("多工器", band, math.ceil(n_trp / 8), "输出多工器 OMUX（合路至馈源，插损 1.8dB）",
        force_id="OMUX-01")

    # ---- 测控信标 ----
    add("测控信标", band, 2, "测控应答机（1+1，统一载波 TT&C）", force_id="TTC-TRP-01")
    add("测控信标", band, 2, "信标发射机（1+1，5W CW 测轨）", force_id="BCN-TX-01")

    # ---- 激光（星间组网）----
    if cfg.get("isl_on"):
        orbit = cfg.get("orbit", "GEO")
        n_lct = 3 if orbit in ("LEO", "SSO", "MEO") else 2
        r_isl = to_f(cfg.get("isl_r_gbps"), 10)
        lct = "LCT-INT-20G" if r_isl > 10 else ("LCT-10G" if r_isl >= 10 else "LCT-5G")
        add("激光", "激光", n_lct,
            f"激光通信终端（{orbit} 组网 {n_lct} 台：同轨前/后向 ×2 + 异轨侧向 ×1，{fmt(r_isl,0)}Gbps）",
            force_id=lct)

    # ---- 星务 ----
    add("星务", band, 2, "星载计算机（1+1，FDIR 覆盖关键单机）", force_id="OBC-PAY-01")
    if mode != "透明":
        add("星务", band, 1, "数据处理单元 DPU（CCSDS 压缩 4:1）", force_id="DPU-01")
        add("星务", band, 1, "大容量存储器（EDAC + 三模冗余）", force_id="STOR-4T")
    add("星务", band, 1, "FC-AE 星上数据总线（4000Mbps）", force_id="BUS-FCAE")

    return rows


def equipment_totals(rows):
    """单机清单 → 分系统质量/功耗汇总（含 20% 裕度，skill 规范）。"""
    CAT_SUB = {"天线": "ant", "相控阵组件": "ant", "机构": "ant",
               "LNA": "trp", "变频": "trp", "多工器": "trp", "功放": "trp",
               "开关": "trp", "数字处理": "trp", "再生基带": "trp", "测控信标": "trp",
               "激光": "laser", "星务": "ipu"}
    sub_m = {"ant": 0.0, "trp": 0.0, "laser": 0.0, "ipu": 0.0}
    sub_p = {"ant": 0.0, "trp": 0.0, "laser": 0.0, "ipu": 0.0}
    n_custom, lv_sum, lv_n = 0, 0, 0
    for r in rows:
        k = CAT_SUB.get(r["cat"], "trp")
        sub_m[k] += to_f(r["mass"], 0)
        sub_p[k] += to_f(r["power"], 0)
        if to_f(r["level"], 3) <= 1:
            n_custom += 1
        lv_sum += to_f(r["level"], 3)
        lv_n += 1
    m_raw, p_raw = sum(sub_m.values()), sum(sub_p.values())
    return dict(sub_m={f"m_{k}": round(v, 1) for k, v in sub_m.items()},
                sub_p={f"P_{k}": round(v, 1) for k, v in sub_p.items()},
                m_est=round(m_raw, 1), p_est=round(p_raw, 1),
                m_pay=round(m_raw * 1.2, 1), p_pay=round(p_raw * 1.2, 1),
                n_custom=n_custom, H_scheme=int(round(lv_sum / lv_n)) if lv_n else 3,
                n_rows=len(rows), n_items=sum(int(r["qty"]) for r in rows))


# ================================================================
# 7 平台/运载选型（三级闭环后两级）
# ================================================================
def select_platform(cfg, totals):
    orbit = cfg.get("orbit", "GEO")
    need_m, need_p = totals["m_pay"], totals["p_pay"]
    cands = []
    for pl in PLATFORMS:
        if pl["orbit"] != orbit:
            continue
        ok = pl["m_pay"] >= need_m and pl["p_pay"] >= need_p
        margin = min((pl["m_pay"] - need_m) / max(pl["m_pay"], 1e-6),
                     (pl["p_pay"] - need_p) / max(pl["p_pay"], 1e-6))
        # 最小可行平台优先：满足约束下整星质量小者得分高
        score = (20 if ok else 0) - pl["m_sat"] / 100.0 + margin * 4
        cands.append((round(score, 2), pl, ok,
                      f"承载 {pl['m_pay']}kg vs 需求 {fmt(need_m,0)}kg（{'满足' if pl['m_pay']>=need_m else '不足'}）；"
                      f"供电 {pl['p_pay']}W vs 需求 {fmt(need_p,0)}W（{'满足' if pl['p_pay']>=need_p else '不足'}）"))
    cands.sort(key=lambda x: (-x[2], -x[0]))
    pref = cfg.get("platform_pref", "自动")
    rec = next((c for c in cands if c[1]["id"] == pref), None) if pref not in ("", "自动") else None
    if rec is None:
        rec = next((c for c in cands if c[2]), None)
    return cands, rec


def select_launcher(cfg, platform, totals):
    orbit = cfg.get("orbit", "GEO")
    m_sat = platform[1]["m_sat"] if platform else totals["m_pay"] * 4
    need_gto = orbit in ("GEO", "HEO")
    fairing_need = 0.0
    if cfg.get("ant_type") == "伞状" or to_f(cfg.get("D_ap"), 0) > 6:
        fairing_need = 4.0
    cands = []
    for lv in LAUNCHERS:
        cap = lv["gto_t"] if need_gto else lv["leo_t"]
        if cap <= 0:
            continue
        ok = cap >= m_sat
        fd = to_f(lv["fairing"].replace("Φ", "").split("×")[0], 4.0)
        if fairing_need and fd < fairing_need:
            ok = False
        score = ((10 if ok else 0) + (5 if ("复用" in lv["heritage"] or "高密度" in lv["heritage"]) else 0)
                 - {"低": 0, "中": 2, "中高": 3, "高": 4}.get(lv["cost"], 2))
        cands.append((round(score, 2), lv, ok,
                      f"{'GTO' if need_gto else 'LEO'} 能力 {cap/1000.0:.2f}t vs 整星 {m_sat/1000.0:.2f}t；"
                      f"整流罩 {lv['fairing']}"
                      + (f"（大口径展开天线需 ≥{fairing_need}m）" if fairing_need else "")))
    cands.sort(key=lambda x: (-x[2], -x[0]))
    pref = cfg.get("launcher_pref", "自动")
    rec = next((c for c in cands if c[1]["id"] == pref), None) if pref not in ("", "自动") else None
    if rec is None:
        rec = next((c for c in cands if c[2]), None)
    return cands, rec


# ================================================================
# 8 载荷组成框图
# ================================================================
def block_diagram(cfg, p, trp, rows):
    band = cfg.get("band", "Ka")
    fband = cfg.get("feeder_band", band)
    mode = cfg.get("mode", "数字透明")
    ant = cfg.get("ant_type", "相控阵")
    der = p.get("_derived", {})
    N_beam = trp["N_beam"]
    G_used = to_f(der.get("G_ant_used"), der.get("G_ant_est", 0))
    cols = [dict(id="col_ant", cn="天线分系统", x=0),
            dict(id="col_rx", cn="接收通道（上行）", x=1),
            dict(id="col_proc", cn=f"处理/交换（{mode}）", x=2),
            dict(id="col_tx", cn="发射通道（下行）", x=3),
            dict(id="col_ttc", cn="测控/星务", x=4)]
    nodes, edges = [], []

    def node(col, nid, cn, qty=1, note="", kind="rf"):
        nodes.append(dict(col=col, id=nid, cn=cn, qty=qty, note=note, kind=kind))
        return nid

    node("col_ant", "ANT", f"用户天线\n{ANT_TYPES.get(ant,{}).get('cn','天线')}·{band}", 1,
         f"G={fmt(G_used,1)}dBi · N_beam={N_beam} · θ3dB={fmt(der.get('θ_3dB_est'),2)}°", "ant")
    if fband != band:
        node("col_ant", "FANT", f"馈电天线\n{fband}", 1, "馈电链路专用", "ant")
    if cfg.get("isl_on"):
        node("col_ant", "LCT", "激光通信终端\n星间组网",
             3 if cfg.get("orbit") in ("LEO", "MEO", "SSO") else 2,
             f"{to_f(cfg.get('isl_r_gbps'),10):.0f}Gbps/链路", "opt")

    node("col_rx", "CIRC", "环行器/隔离器", trp["n_trp_chan"], "收发隔离 ≥100dB（c-15）", "rf")
    node("col_rx", "LNA", "低噪放 LNA（A/B 冷备）", 2 * trp["n_trp_chan"],
         f"NF {to_f(p.get('NF_lna'),1.6)}dB · G {to_f(p.get('G_lna'),35)}dB", "amp")
    node("col_rx", "DCON", "下变频器", trp["n_trp_chan"], f"{band} → 中频", "rf")

    if mode == "透明":
        node("col_proc", "IMUX", "输入多工器 IMUX", math.ceil(trp["n_trp_chan"] / 8), "8 通道/台", "rf")
        node("col_proc", "EQ", "均衡器 + 开关矩阵", 2, "幅频均衡 ≤1dB · 通道倒换", "rf")
        proc_out = "EQ"
    elif mode == "数字透明":
        node("col_proc", "ADC", "数字信道化 ADC", 4, f"子带 {to_f(p.get('B_sub'),40):.0f}MHz · ENOB≥10bit", "dig")
        node("col_proc", "DSW", "星上交换矩阵 DTP", 1,
             f"C_sw={to_f(p.get('C_sw'),100):.0f}Gbps · 在轨重构", "dig")
        node("col_proc", "DAC", "重构 DAC", 4, "SFDR ≥70dBc", "dig")
        proc_out = "DAC"
    else:
        node("col_proc", "DEM", "解调器", trp["n_trp_chan"], "QPSK~32APSK · ACM", "dig")
        node("col_proc", "DEC", "译码器 LDPC/BCH", trp["n_trp_chan"], "编码增益 6.5dB", "dig")
        node("col_proc", "RT", "星上路由交换（1+1）", 2, "跨波束单跳 · 路由表 4096", "dig")
        node("col_proc", "ENC", "编码器 + 调制器", trp["n_trp_chan"], "按下行 C/N 自适应 MODCOD", "dig")
        proc_out = "ENC"

    if trp["distributed"]:
        node("col_tx", "HPA", f"{band} T/R 阵列功放\n（分布式）", int(to_f(cfg.get("N_el"), 1024)),
             f"射频 {fmt(trp['P_out_w']*N_beam,0)}W · 每波束 {fmt(trp['P_out_w'],1)}W", "amp")
    else:
        node("col_tx", "HPA", f"{trp['amp']} 功放 ×{trp['n_hpa']}", trp["n_hpa"],
             f"{fmt(trp['P_out_w'],1)}W/波束 · η={to_f(p.get('η_pa'),58):.0f}% · 直流 {fmt(trp['p_hpa_dc'],0)}W", "amp")
    node("col_tx", "UCON", "上变频器", trp["n_trp_chan"], f"中频 → {band}", "rf")
    node("col_tx", "OMUX", "输出多工器 OMUX", math.ceil(trp["n_trp_chan"] / 8), "合路至馈源 · 插损 1.8dB", "rf")

    node("col_ttc", "TTC", "测控应答机（1+1）", 2, "统一载波 TT&C", "ctrl")
    node("col_ttc", "BCN", "信标发射机（1+1）", 2, "5W CW 测轨", "ctrl")
    node("col_ttc", "OBC", "星载计算机（1+1）", 2, "FDIR 管理 · 4000MIPS", "ctrl")
    if mode != "透明":
        node("col_ttc", "RC", "在轨重构控制器", 1, f"重构生效 {to_f(p.get('t_rec'),5):.0f}s", "ctrl")

    edges += [
        dict(f="ANT", t="CIRC", label=f"用户上行 {band}", kind="rf_up"),
        dict(f="CIRC", t="LNA", label="", kind="rf_up"),
        dict(f="LNA", t="DCON", label=f"T_sys={fmt(der.get('t_sys',{}).get('固面',0),0)}K", kind="rf_up"),
        dict(f="DCON", t=("IMUX" if mode == "透明" else ("ADC" if mode == "数字透明" else "DEM")),
             label="", kind="if"),
    ]
    if mode == "透明":
        edges.append(dict(f="IMUX", t="EQ", label="", kind="if"))
    elif mode == "数字透明":
        edges += [dict(f="ADC", t="DSW", label="子带交换", kind="dig"),
                  dict(f="DSW", t="DAC", label="", kind="dig")]
    else:
        edges += [dict(f="DEM", t="DEC", label="", kind="dig"),
                  dict(f="DEC", t="RT", label="IP 交换", kind="dig"),
                  dict(f="RT", t="ENC", label="", kind="dig")]
    edges += [
        dict(f=proc_out, t="HPA", label="", kind="if"),
        dict(f="HPA", t="UCON", label=f"EIRP={fmt(der.get('EIRP_req'),1)}dBW", kind="rf_dn"),
        dict(f="UCON", t="OMUX", label="", kind="rf_dn"),
        dict(f="OMUX", t="ANT", label="用户下行", kind="rf_dn"),
    ]
    if fband != band:
        edges += [dict(f="FANT", t="CIRC", label=f"馈电上行 {fband}", kind="rf_up"),
                  dict(f="OMUX", t="FANT", label="馈电下行", kind="rf_dn")]
    if cfg.get("isl_on"):
        edges.append(dict(f=("RT" if mode == "再生" else ("DSW" if mode == "数字透明" else "EQ")),
                          t="LCT", label="星间业务", kind="opt"))
    edges += [
        dict(f="OBC", t=(proc_out if mode != "透明" else "EQ"), label="重构/调度指令", kind="ctrl"),
        dict(f="OBC", t="TTC", label="", kind="ctrl"),
        dict(f="TTC", t="ANT", label="遥控/遥测载波", kind="ctrl"),
    ]
    return dict(cols=cols, nodes=nodes, edges=edges)


# ================================================================
# 9 信息流设计（星地 / 星间 / 星内）
# ================================================================
def info_flows(cfg, p, res, totals, trp):
    band = cfg.get("band", "Ka")
    fband = cfg.get("feeder_band", band)
    mode = cfg.get("mode", "数字透明")
    orbit = cfg.get("orbit", "GEO")
    orb = ORBITS.get(orbit, ORBITS["GEO"])
    der = p.get("_derived", {})
    dn, up = res.get("downlink", {}), res.get("uplink", {})
    csys = res.get("summary", {}).get("C_sys")
    prop = to_f(der.get("d_slant"), 38000) / 299792.458        # ms 单程
    onb = MODE_DELAY_MS.get(mode, 1.0)
    chain_txt = {"透明": "滤波/变频/放大（不解调，噪声累积）",
                 "数字透明": "数字信道化/子带交换/重构（柔性）",
                 "再生": "解调/译码/路由/再调制（噪声不累积）"}[mode]

    sg = [dict(id="sg1", name="用户上行业务流（用户链路）",
               path=f"用户终端 →〔{band} 上行 {to_f(p.get('f_up'),30):.3f}GHz〕→ 用户天线 → 环行器/滤波 → LNA → 下变频 → {chain_txt} → 上变频 → 功放 → OMUX → 用户下行波束",
               medium=f"{band} 射频",
               rate=f"单载波 {fmt(up.get('C_link_mbps'),2)} Mbps × {der.get('N_beam',1)} 波束"
                    f" × {to_f(p.get('n_pol'),2):.0f} 极化（{der.get('k_reuse',4)} 色频率复用共存）",
               delay=f"单跳 {fmt(2*prop + onb,3)} ms（传播 {fmt(2*prop,3)} + 星上 {fmt(onb,3)}）",
               key=f"C/N上={fmt(up.get('CN'),1)}dB · MODCOD {up.get('modcod','—')} · 余量 {fmt(up.get('M'),1)}dB")]
    if fband != band:
        sg.append(dict(id="sg2", name="馈电上行业务流（馈电链路）",
                       path=f"关口站/信关站 →〔{fband} 上行〕→ 馈电天线 → 接收通道 → {chain_txt} → 用户下行波束 → 用户终端",
                       medium=f"{fband} 射频",
                       rate=f"关口站 EIRP {to_f(p.get('EIRP_gs'),75):.0f}dBW · 整星容量 {fmt(csys,1)} Gbps",
                       delay=f"单跳 {fmt(2*prop + onb,3)} ms",
                       key="馈电链路 EIRP 大、余量充裕；收发隔离 ≥85dB（c-15）"))
        sg.append(dict(id="sg3", name="馈电下行业务流（落地/回传）",
                       path=("用户上行 → 星上再生解调 → IP 路由 → 馈电下行波束 → 关口站 → 地面核心网"
                             if mode == "再生" else
                             "用户上行 → 星上透明/数字透明转发 → 馈电下行波束 → 关口站 → 地面核心网"),
                       medium=f"{fband} 射频", rate=f"整星 {fmt(csys,1)} Gbps",
                       delay=f"单跳 {fmt(2*prop + onb,3)} ms",
                       key=("再生体制：星上路由单跳直达" if mode == "再生"
                            else "透明体制：跨波束须落地双跳")))
    sg.append(dict(id="sg4", name="测控信息流 TT&C",
                   path="地面测控站 ⇄〔S 统一载波〕⇄ 测控应答机 ⇄ 星载计算机 ⇄〔1553B/CAN〕⇄ 各单机",
                   medium="S 波段统一载波 + 星内总线", rate="遥控 2kbps / 遥测 64kbps / 信标 5W CW",
                   delay="指令闭环 <1s", key="FDIR 自主故障检测隔离恢复；信标供地面测轨定轨"))
    if cfg.get("isl_type") == "激光" and to_f(p.get("R_isl"), 0) > 0 and orbit == "LEO":
        sg.append(dict(id="sg5", name="星地激光馈电流（可选）",
                       path="星上交换/路由 → 激光终端 → 地面光学站（云遮蔽需站址分集）",
                       medium="1550nm 激光", rate=f"{to_f(p.get('R_sgl'),5):.0f} Gbps",
                       delay=f"单跳 {fmt(prop,3)} ms",
                       key=f"可用性受云遮蔽（P_cloud≈{to_f(p.get('P_cloud'),8):.0f}%）→ 多站分集"))

    si = []
    if cfg.get("isl_on"):
        li = res.get("laser_isl") or {}
        si.append(dict(id="si1", name="同轨星间链路 ×2（前向/后向）",
                       path="星上交换/路由 → 激光终端（粗跟踪万向架 + 精跟踪 FSM）→ 同轨邻星",
                       medium=f"1550nm 激光 · d={fmt(to_f(p.get('d_isl'),5000),0)}km",
                       rate=f"{to_f(cfg.get('isl_r_gbps'),10):.0f} Gbps/链路",
                       delay=f"{fmt(to_f(p.get('d_isl'),5000)/299792.458,3)} ms 单跳",
                       key=f"P_rx={fmt(li.get('P_rx_dbm'),1)}dBm vs P_req={fmt(li.get('P_req_dbm'),1)}dBm → 余量 {fmt(li.get('M_db'),1)}dB · ATP σ≤1μrad（c-18/c-19）"))
        si.append(dict(id="si2", name="异轨星间链路 ×1（侧向）",
                       path="星上路由 → 侧向激光终端 → 异轨平面邻星",
                       medium="1550nm 激光", rate=f"{to_f(cfg.get('isl_r_gbps'),10):.0f} Gbps",
                       delay="组网最大跳数 ≤4", key="星座路由（再生体制单跳直达，透明体制须落地）"))
        if mode == "再生":
            si.append(dict(id="si3", name="星间业务路由信息流",
                           path="解调译码 → IP 路由（路由表 4096 条，选路 <1ms）→ 目的波束 / 目的星激光终端",
                           medium="星内数字域", rate=f"交换容量 {to_f(p.get('C_sw'),100):.0f} Gbps",
                           delay="选路 <1ms", key="跨波束/跨星单跳直达，避免落地双跳"))
        else:
            si.append(dict(id="si3", name="星间透明中继信息流",
                           path="子带交换（DTP）→ 激光终端调制 → 邻星",
                           medium="星内数字域 + 光域", rate=f"交换容量 {to_f(p.get('C_sw'),100):.0f} Gbps",
                           delay=f"星上 {fmt(onb,2)} ms", key="DTP 子带级路由；透明体制无星上 IP 处理"))
    else:
        si.append(dict(id="si0", name="（未配置星间链路）",
                       path="业务经馈电链路落地中转（双跳）；星间无直接信息流",
                       medium="—", rate="—",
                       delay=f"双跳 ≈{fmt(4*prop + 2*onb,1)} ms",
                       key=orb["isl_need"]))

    sn = [
        dict(id="sn1", name="射频信息流（业务主干）",
             path="天线馈源 → 环行器/接收滤波 → LNA → 下变频 → 处理交换 → 上变频 → 功放 → OMUX → 天线馈源",
             medium="射频/中频", rate=f"转发器总带宽 {to_f(p.get('B_trp'),1000):.0f} MHz · {trp['n_trp_chan']} 通道",
             delay=f"星上 {fmt(onb,4)} ms",
             key=f"G/T={fmt(res.get('gt',{}).get('GT'),1)}dB/K · EIRP={fmt(res.get('eirp',{}).get('EIRP'),1)}dBW · 收发隔离 ≥85dB（c-15）"),
        dict(id="sn2", name="数据信息流（载荷数据）",
             path=("基带/路由数据 → DPU 压缩（CCSDS 4:1）→ FC-AE 总线 → 大容量存储器 → 数传/馈电下行"
                   if mode != "透明" else
                   "遥测采集 → 数据总线 → 测控应答机 → 地面"),
             medium=f"FC-AE {to_f(p.get('R_bus'),4000):.0f} Mbps",
             rate=f"R_pdl={to_f(p.get('R_pdl'),0):.0f} Mbps（压缩后 {to_f(p.get('R_pdl'),0)/max(to_f(p.get('CR'),4),1):.0f} Mbps）",
             delay="ms 级", key=f"E_store={to_f(p.get('E_store'),4):.1f}Tbit ≥ R_pdl×T_blind/CR（c-20）"),
        dict(id="sn3", name="控制信息流",
             path="星载计算机（FDIR）→〔1553B/CAN〕→ 在轨重构控制器 / ACU / EPC / DTP / 各单机",
             medium="1553B 总线", rate="指令级（kbps）",
             delay=f"重构生效 {to_f(p.get('t_rec'),5):.0f}s",
             key=("波束/子带/功率/路由四维在轨重构" if mode != "透明" else "通道倒换与功放备份切换（透明体制波束固定）")),
        dict(id="sn4", name="供能信息流（功率流）",
             path="平台一次电源（母线 100V）→ EPC（6kV 高压）→ 功放 TWTA/SSPA/MPA 或 T/R 阵列；二次电源 → 数字单机",
             medium="电力", rate=f"载荷总功耗 {fmt(totals['p_pay'],0)}W（含 20% 裕度）",
             delay="—",
             key=f"P_dc=P_out/η（c-16）；T_j ≤125℃；转发器分系统功耗占比 {fmt(100*totals['sub_p'].get('P_trp',0)/max(totals['p_est'],1),0)}%"),
    ]
    return dict(sg=sg, si=si, sn=sn,
                delay_note=dict(prop_ms=prop, onboard_ms=onb, mode=mode, orbit=orbit,
                                total_ms=2 * prop + onb))


# ================================================================
# 10 方案对比（六维评分）
# ================================================================
SCORE_W = dict(perf=0.30, mass=0.10, power=0.10, cost=0.15, flex=0.15, risk=0.20)
SCORE_CN = dict(perf="性能闭合", mass="质量", power="功耗", cost="成本",
                flex="灵活度", risk="成熟度/风险")


def score_scheme(res, totals, cfg, platform_rec):
    s = res.get("summary", {})
    jp, jt = s.get("judge_pass", 0), max(s.get("judge_total", 1), 1)
    worst_M = min(to_f(s.get("M_up"), 0), to_f(s.get("M_dn"), 0))
    perf = 6.0 * jp / jt + min(4.0, max(0.0, 4.0 * worst_M / 6.0))
    m_cap = platform_rec[1]["m_pay"] if platform_rec else 1200.0
    p_cap = platform_rec[1]["p_pay"] if platform_rec else 10000.0
    mass = max(0.0, 10.0 * (1 - totals["m_pay"] / max(m_cap, 1e-6)))
    power = max(0.0, 10.0 * (1 - totals["p_pay"] / max(p_cap, 1e-6)))
    mode_c = MODES.get(cfg.get("mode", "数字透明"), {}).get("cost_mult", 1.5)
    ant_c = ANT_TYPES.get(cfg.get("ant_type", "相控阵"), {}).get("cost_mult", 1.5)
    sub_c = ARRAY_SUBTYPES.get(cfg.get("array_subtype", ""), {}).get("cost_mult", 1.0)
    cost = max(0.0, min(10.0, 10.0 * (1 - (mode_c * ant_c * sub_c - 1) / 4.0)))
    flex = min(10.0, to_f(MODES.get(cfg.get("mode"), {}).get("t_rl", 7)) * 0.6
               + MODE_CAP.get(cfg.get("Mode", "多波束"), 2) / 4.0 * 4.0)
    risk = max(0.0, min(10.0, to_f(MODES.get(cfg.get("mode"), {}).get("t_rl", 7)) * 0.7
                        + totals.get("H_scheme", 3) * 0.6 - totals.get("n_custom", 0) * 0.4))
    dims = dict(perf=round(perf, 1), mass=round(mass, 1), power=round(power, 1),
                cost=round(cost, 1), flex=round(flex, 1), risk=round(risk, 1))
    return dict(dims=dims, total=round(sum(dims[k] * SCORE_W[k] for k in SCORE_W), 2),
                weights=SCORE_W, cn=SCORE_CN)


def compare_schemes(base_cfg, kg, variants=None):
    """当前方案 + 体制/天线替代方案，全流程跑通后六维评分对比。"""
    if variants is None:
        variants = []
        mode = base_cfg.get("mode", "数字透明")
        for m in MODES:
            if m != mode:
                variants.append((f"体制替代：{MODES[m]['cn']}",
                                 dict(base_cfg, mode=m, name=base_cfg.get("name", ""))))
        ant = base_cfg.get("ant_type", "相控阵")
        band = base_cfg.get("band", "Ka")
        for a in ANT_TYPES:
            if a != ant and band in ANT_TYPES[a]["bands"]:
                c2 = dict(base_cfg, ant_type=a, name=base_cfg.get("name", ""))
                if a == "相控阵" and not c2.get("array_subtype"):
                    c2["array_subtype"] = "数字模拟混合"
                if a == "固面" and to_f(c2.get("D_ap"), 0) > 4.0:
                    c2["D_ap"] = 2.5
                if a == "伞状" and to_f(c2.get("D_ap"), 0) < 6.0:
                    c2["D_ap"] = 12.0
                if a == "大容量多波束":
                    if to_f(c2.get("D_ap"), 0) > 7.0:
                        c2["D_ap"] = 3.5
                    c2.setdefault("N_el_feed", 0)
                if a == "混合多波束":
                    if to_f(c2.get("D_ap"), 0) > 6.0:
                        c2["D_ap"] = 3.0
                    c2.setdefault("N_el_feed", 256)
                variants.append((f"天线替代：{ANT_TYPES[a]['cn']}", c2))
    out = []
    for label, cfgv in [("当前方案", dict(base_cfg))] + variants:
        try:
            r = design_all(cfgv, kg, skip_compare=True)
            s = r["res"]["summary"]
            out.append(dict(label=label, cfg=cfgv, score=r["score"], totals=r["totals"],
                            platform=r["platform"][1]["cn"] if r["platform"] else "—",
                            launcher=r["launcher"][1]["cn"] if r["launcher"] else "—",
                            antenna=r["ant_rec"][1]["id"],
                            antenna_cn=r["ant_rec"][1]["cn"],
                            mode=cfgv.get("mode"), ant_type=cfgv.get("ant_type"),
                            fail=s.get("fail", []), warn=s.get("warn", []),
                            judge=f"{s.get('judge_pass')}/{s.get('judge_total')}",
                            EIRP=round(r["res"]["eirp"]["EIRP"], 2),
                            GT=round(r["res"]["gt"]["GT"], 2),
                            M_up=round(to_f(s.get("M_up"), 0), 2),
                            M_dn=round(to_f(s.get("M_dn"), 0), 2),
                            C_sys=round(to_f(s.get("C_sys"), 0), 2),
                            m=r["totals"]["m_pay"], pw=r["totals"]["p_pay"],
                            n_rows=r["totals"]["n_rows"], n_items=r["totals"]["n_items"],
                            n_custom=r["totals"]["n_custom"], H=r["totals"]["H_scheme"],
                            note=_scheme_note(cfgv, r)))
        except Exception as e:                     # noqa: BLE001
            out.append(dict(label=label, cfg=cfgv, error=f"{type(e).__name__}: {e}"))
    return out


def _scheme_note(cfgv, r):
    mode = MODES.get(cfgv.get("mode"), {})
    ant = ANT_TYPES.get(cfgv.get("ant_type"), {})
    return (f"{mode.get('cn','')} + {ant.get('cn','')}"
            + (f"（{ARRAY_SUBTYPES[cfgv['array_subtype']]['cn']}）"
               if cfgv.get("array_subtype") in ARRAY_SUBTYPES else "")
            + f"；星上时延 {MODE_DELAY_MS.get(cfgv.get('mode'),1)}ms；"
            + (mode.get("cons") or [""])[0])


# ================================================================
# 11 主入口
# ================================================================
def design_all(cfg, kg, skip_compare=False):
    """全流程：需求解析 → 几何 → 参数映射 → 天线选型 → 功放反推 → 转发器方案
    → 单机清单 → 平台/运载 → 链路校核 → 框图/信息流 → 评分/对比。"""
    cfg = dict(cfg)
    if to_f(cfg.get("P_out"), 0) > 0:
        cfg["P_out_user"] = to_f(cfg["P_out"])       # 用户显式指定功放功率
    req = parse_config(cfg)
    geo = derive_geometry(cfg)
    p = cfg_to_params(cfg, geo, req, kg)

    # 平台预选（粗估）
    coarse = dict(m_pay=(estimate_antenna_mass(cfg, p) + 150) * 1.2,
                  p_pay=(estimate_antenna_power(cfg, p) + 800) * 1.2)
    _, plat_pre = select_platform(cfg, coarse)

    # 步骤 3a：天线五维选型
    ant_cands, ant_rec, is_custom_ant, custom_ant = select_antennas(
        cfg, p, plat_pre[1] if plat_pre else None)
    if cfg.get("force_custom_ant"):
        # 用户强制按配置电气参数走定制路径（子体制/口径由用户指定，不接受货架替代）
        is_custom_ant = True
        ant_rec = (round(ant_rec[0], 2), custom_ant,
                   ["用户强制定制天线：按 array_subtype/D_ap/N_el 电气参数估算（货架候选仅列参考）"]
                   + ant_rec[2], ant_rec[3])

    # 选定天线后：G_ant_ovr = 货架增益，功放功率按 EIRP 需求重新反推
    amp_pref = cfg.get("amp_type") or MODE_HPA.get(cfg.get("mode", "数字透明"), "TWTA")
    if is_custom_ant:
        G_used = p["_derived"]["G_ant_est"]
        p["G_ant_ovr"] = ""                          # 引擎按公式自算（与推导一致）
        if to_f(cfg.get("P_out_user"), 0) <= 0:
            rederive_power(p, G_used, amp_pref)
            p["G_ant_ovr"] = ""                      # 自研天线不用覆盖
    else:
        prod = ant_rec[1]
        G_used = _shelf_ant_gain(prod, cfg.get("band", "Ka"))
        sp = prod.get("specs", {})
        if to_f(sp.get("D"), 0) > 0:
            p["D_ap"] = to_f(sp["D"])
        if to_f(sp.get("N_el"), 0) > 0:
            p["N_el"] = to_f(sp["N_el"])
        if to_f(cfg.get("P_out_user"), 0) > 0:
            p["G_ant_ovr"] = G_used
            p["_derived"]["G_ant_used"] = G_used
            p["_derived"]["P_out_w"] = to_f(cfg["P_out_user"])
            p["P_out"] = to_f(cfg["P_out_user"])
        else:
            rederive_power(p, G_used, amp_pref)

    # 步骤 3b：转发器方案
    trp = plan_transponder(cfg, p, is_custom_ant)
    # 步骤 4：货架单机清单
    rows = build_equipment(cfg, p, trp, ant_rec, is_custom_ant, custom_ant)
    totals = equipment_totals(rows)

    # 回填预算与星内数据参数
    p.update(totals["sub_m"])
    p.update(totals["sub_p"])
    p["N_gap"] = totals["n_custom"]
    p["H_scheme"] = str(totals["H_scheme"])
    # 数传速率按修正后的系统容量口径估算（η≈2.0 名义值 × n_pol 极化复用；不再乘 k_reuse）
    C_sys_est = (to_f(p.get("N_beam"), 16) * to_f(p.get("B_beam"), 125) * 2.0
                 * to_f(p.get("n_pol"), 2) / 1000.0)
    p["R_pdl"] = min(C_sys_est * 1000.0, 8000.0) if cfg.get("mode") != "透明" else 150.0
    p["R_bus"] = max(4000.0, math.ceil(p["R_pdl"] / max(to_f(p.get("CR"), 4), 1) / 1000.0) * 1000.0)
    p["E_store"] = max(1.0, p["R_pdl"] * to_f(p.get("T_blind"), 15) * 60
                       / max(to_f(p.get("CR"), 4), 1) / 1e6 * 1.5)
    p["R_bb"] = max(2000.0, p["R_pdl"])
    p["R_dpu"] = max(1500.0, p["R_pdl"])

    # 平台/运载正式选型（三级闭环后两级）
    plat_cands, plat_rec = select_platform(cfg, totals)
    if plat_rec:
        p["M_budget"] = plat_rec[1]["m_pay"]
        p["P_budget"] = plat_rec[1]["p_pay"]
    else:
        # 无满足承载的同轨道平台：取该轨道最大承载平台作预算基准，
        # 使 c-17 给出真实的超支裕度（而非因 M_budget=0 而除零误判）
        same = [c for c in plat_cands] or []
        if same:
            biggest = max(same, key=lambda c: c[1]["m_pay"])
            p["M_budget"] = biggest[1]["m_pay"]
            p["P_budget"] = biggest[1]["p_pay"]
            p["_plat_gap"] = (f"无满足承载的 {cfg.get('orbit')} 平台："
                              f"需求 {fmt(totals['m_pay'],0)}kg/{fmt(totals['p_pay'],0)}W > "
                              f"最大候选 {biggest[1]['cn']} {biggest[1]['m_pay']}kg/{biggest[1]['p_pay']}W"
                              f" → 须减配载荷或换更大平台")
    launch_cands, launch_rec = select_launcher(cfg, plat_rec, totals)

    # 步骤 5：链路预算与 25 条约束校核
    res = compute_all(p, kg)

    score = score_scheme(res, totals, cfg, plat_rec)
    diagram = block_diagram(cfg, p, trp, rows)
    flows = info_flows(cfg, p, res, totals, trp)

    # 原理介绍（当前方案涉及的子系统）
    used = set(r["cat"] for r in rows)
    cat2p = {"天线": "天线", "相控阵组件": "相控阵组件", "LNA": "LNA", "变频": "变频器",
             "多工器": "多工器", "功放": "功放", "开关": "多工器", "数字处理": "DTP",
             "再生基带": "再生基带", "激光": "激光通信", "测控信标": "测控信标",
             "机构": "天线", "星务": "星务处理"}
    principles, seen = [], set()
    for c in ["天线", "相控阵组件", "LNA", "变频", "多工器", "功放", "数字处理",
              "再生基带", "激光", "测控信标", "星务"]:
        k = cat2p.get(c)
        if c in used and k and k in UNIT_PRINCIPLES and k not in seen:
            seen.add(k)
            principles.append(dict(key=k, **UNIT_PRINCIPLES[k]))

    compare = None if skip_compare else compare_schemes(cfg, kg)

    diag = diagnose_result(cfg, p, res, totals, plat_rec, launch_rec, is_custom_ant,
                           geo, req)

    return dict(cfg=cfg, req=req, geo=geo, params=p, res=res, transponder=trp,
                ant_cands=ant_cands, ant_rec=ant_rec, is_custom_ant=is_custom_ant,
                custom_ant=custom_ant, equipment=rows, totals=totals,
                platforms=plat_cands, platform=plat_rec,
                launchers=launch_cands, launcher=launch_rec,
                diagram=diagram, flows=flows, principles=principles,
                mode_info=MODES.get(cfg.get("mode"), {}),
                ant_info=ANT_TYPES.get(cfg.get("ant_type"), {}),
                sub_info=ARRAY_SUBTYPES.get(cfg.get("array_subtype", ""), {}),
                score=score, compare=compare, diagnosis=diag)


# ================================================================
# 12 参数建议引擎（其余参数给出建议值）
# ================================================================
def suggest_params(cfg, kg=None):
    """按当前配置（轨道/覆盖区/业务/频段/天线体制）给出全部参数的建议值。

    返回 dict：
      values : {参数key: 建议值}（仅给出建议，不强制覆盖用户已填项——由前端决定）
      notes  : {参数key: 建议依据（一句话）}
      auto   : {参数key: 建议值}（切换场景/覆盖区时可直接自动填充的项）
    """
    cfg = dict(cfg or {})
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    svc = SERVICES.get(cfg.get("service", "高通量宽带"), SERVICES["高通量宽带"])
    band = cfg.get("band", "Ka")
    ant = cfg.get("ant_type", "相控阵")
    mode = cfg.get("mode", "数字透明")
    Bd = BAND_FREQ.get(band, (30.0, 20.0))
    f_dn = Bd[1]

    values, notes = {}, {}

    # ---- 几何/链路（覆盖区库直接给出）----
    values["el_deg"] = cov.get("el_min_deg", 30)
    notes["el_deg"] = f"{cov.get('cn','')} GEO 最低用户仰角建议 ≥{cov.get('el_min_deg',30)}°"
    values["A_avail"] = svc.get("avail", 99.5)
    notes["A_avail"] = f"{svc.get('cn','')} 业务可用性设计点 {svc.get('avail',99.5)}%"
    values["M_target"] = 3.0
    notes["M_target"] = "skill 规范：C/N 余量 ≥3dB"
    values["life_yr"] = orb.get("life_yr", 15)
    notes["life_yr"] = f"{orb.get('cn','')} 典型设计寿命 {orb.get('life_yr',15)} 年"
    values["EIRP_gs"] = 75
    notes["EIRP_gs"] = "Ka/Ku 关口站典型 EIRP 75dBW（大口径站）"

    # ---- 覆盖几何 → 波束规划 ----
    geo = derive_geometry(cfg)
    cov_r = geo["cov_r_km"]
    beam_r = geo["beam_r_km"]
    n_beam_geo = geo["N_beam_geo"]
    values["cov_r_km"] = round(cov_r, 0)
    values["beam_r_km"] = round(beam_r, 0)
    # 波束数：HTS/大容量体制取几何建议（≥64 时用大容量典型值）；广播单波束
    if svc.get("C_gbps", 0) >= 20 or ant in ("大容量多波束",):
        n_sug = max(n_beam_geo, 64)
        n_sug = min(int(math.ceil(n_sug / 8.0) * 8), 500)   # 8 的整数倍，上限 500
        notes["N_beam"] = (f"大容量：几何密铺建议 {n_beam_geo} → 取 {n_sug}（8 的倍数，"
                           f"配合 k={cov.get('k_typ',4)} 色复用）")
    elif "广播" in svc.get("cn", "") or svc.get("C_gbps", 0) < 0.1:
        n_sug = 1
        notes["N_beam"] = "广播业务：单波束大区覆盖"
    else:
        n_sug = max(n_beam_geo, 7)
        notes["N_beam"] = f"几何密铺建议 {n_beam_geo} → 取 {n_sug}（含边缘余量）"
    values["N_beam"] = n_sug

    # ---- 频段规划 ----
    B_total = B_TOTAL_OVR.get(band, BANDS.get(band, {}).get("B_total", 2500))
    k = cov.get("k_typ", 4)
    # 单波束带宽：频谱约束 c-13 反推 B_beam ≤ B_total×k/N_beam，再与业务需求取小
    b_beam_cap = B_total * k / max(n_sug, 1)
    if band in ("Ka", "Q/V"):
        b_typ = 250.0
    elif band == "Ku":
        b_typ = 36.0 if n_sug <= 2 else 125.0
    else:
        b_typ = 25.0 if n_sug <= 8 else 10.0
    b_sug = min(b_typ, max(5.0, math.floor(b_beam_cap)))
    values["B_beam"] = b_sug
    notes["B_beam"] = (f"c-13 频谱闭合上限 {fmt(b_beam_cap,0)}MHz（B_total={fmt(B_total,0)}×k={k}/N_beam={n_sug}）"
                       f"→ 取 {fmt(b_sug,0)}MHz")
    values["k_reuse"] = k
    notes["k_reuse"] = f"{cov.get('cn','')} 典型复用色数 k={k}"
    values["n_pol"] = 2
    notes["n_pol"] = "双极化复用（c-12 容量 ×2）"
    b_car = min(max(1.0, b_sug / 4), 62.0) if n_sug > 1 else b_sug
    values["B_carrier"] = round(b_car, 1)
    notes["B_carrier"] = "单载波取波束带宽 1/4 左右（SCPC 小载波，噪声带宽最优）"

    # ---- 容量 ----
    values["C_req_ovr"] = ""
    notes["C_req_ovr"] = (f"留空取业务库默认 {svc.get('C_gbps')} Gbps"
                          f"（该频段频谱物理上限约 {fmt(B_total*k*2.0*2/1000,1)} Gbps）")

    # ---- 终端参数（业务库默认，留空即取库值）----
    values["GT_term"] = ""
    notes["GT_term"] = f"留空取业务库默认 {svc.get('GT_term')} dB/K（{svc.get('cn','')}）"
    values["EIRP_term"] = ""
    notes["EIRP_term"] = f"留空取业务库默认 {svc.get('EIRP_term')} dBW"

    # ---- 天线口径/阵元 ----
    if ant == "相控阵":
        sub = cfg.get("array_subtype", "数字模拟混合")
        # 由 G/T 需求反推最小阵元数（与 payload_decompose 同口径）
        req = parse_config(cfg)
        p_tmp = cfg_to_params(cfg, geo, req, kg or {})
        gt_req = p_tmp["_derived"]["GT_req"]
        t_sys = p_tmp["_derived"]["t_sys"].get("相控阵", 200.0)
        g_need = gt_req + 10 * math.log10(max(t_sys, 1e-6))
        eta = ARRAY_SUBTYPES.get(sub, {}).get("eta", 0.62)
        g_el = 6.0
        n_need = 10 ** ((g_need - g_el) / 10.0) / max(eta, 0.01)
        n_sug_el = int(min(max(math.ceil(n_need / 64.0) * 64, 64),
                           ARRAY_SUBTYPES.get(sub, {}).get("n_el_max", 8192)))
        values["N_el"] = n_sug_el
        notes["N_el"] = (f"G/T 需求 {fmt(gt_req,1)}dB/K + T_sys {fmt(t_sys,0)}K → G≥{fmt(g_need,1)}dBi → "
                         f"N_el≥{int(n_need)} → 取 {n_sug_el}（{sub} 上限 "
                         f"{ARRAY_SUBTYPES.get(sub, {}).get('n_el_max', 8192)}）")
        th = geo.get("θ_beam_deg", 1.0)
        scan_sug = 6 if cfg.get("orbit") == "GEO" else 45
        values["θ_scan"] = scan_sug
        notes["θ_scan"] = ("GEO 固定覆盖：地盘视锥仅 ±8.69°，±6° 足够（扫描损耗≈0.04dB）"
                           if cfg.get("orbit") == "GEO" else
                           "LEO/MEO：波束需跟踪地面小区，±45° 典型")
        values["D_ap"] = round(math.sqrt(n_sug_el) * (lam_m(f_dn) / 2) * 1.1, 2)
        notes["D_ap"] = "阵面等效口径 = √N_el×λ/2（半波长栅格，方形阵）"
        values["η_ill"] = int(ARRAY_SUBTYPES.get(sub, {}).get("eta", 0.62) * 100)
        notes["η_ill"] = f"{sub} 口径效率典型值"
    elif ant == "伞状":
        values["D_ap"] = 12.0
        notes["D_ap"] = "L/S 移动通信伞天线典型 12m（东方红飞行继承）"
        values["N_beam"] = max(n_sug, 19) if n_sug > 1 else 19
        notes["N_beam"] = "伞天线馈源阵典型 19 波束（七元六环）"
    elif ant == "大容量多波束":
        values["D_ap"] = 3.5
        notes["D_ap"] = "VHTS 成形反射面典型 3.5m（KA-SAT/Konnect 级；G≈56dBi@Ka）"
        values["N_beam"] = max(n_sug, 233) if svc.get("C_gbps", 0) >= 40 else max(n_sug, 100)
        notes["N_beam"] = "VHTS 大容量：233 波束级（k=4 复用 + 双极化，单星 100Gbps+）"
        values["B_beam"] = min(b_sug if b_sug <= 250 else 250, 250)
    elif ant == "混合多波束":
        values["D_ap"] = 3.0
        notes["D_ap"] = "混合多波束典型 3m 成形反射面（η≈0.60，G≈54dBi@Ka）"
        values["N_el_feed"] = 256
        notes["N_el_feed"] = "馈电阵 256 元（±6° 电扫，波束重构/跳变/零陷；功耗 ≈420W）"
        values["N_beam"] = max(n_sug, 64)
        notes["N_beam"] = "柔性多波束 64+（馈电阵幅相加权在轨重构）"
    else:   # 固面
        d_typ = 2.5 if band in ("Ka", "Ku") else 2.0
        values["D_ap"] = d_typ
        notes["D_ap"] = f"{band} 固面反射面典型 {d_typ}m 口径"
        values["η_ill"] = 68
        notes["η_ill"] = "反射面口径效率典型 68%"

    # ---- c-13 频谱闭合归一（关键：天线分支可能改写了 N_beam，须用最终值复核 B_beam）----
    # 否则 N_beam=233 配 B_beam=156（按旧 n_sug=64 算）会突破频谱上限触发 c-13，
    # 且 B_beam 过大使 HPA 功率飙升触发 c-17 功率墙。
    n_final = int(to_f(values.get("N_beam", n_sug), n_sug))
    b_cap = B_total * k / max(n_final, 1)
    b_now = float(to_f(values.get("B_beam", b_sug), b_sug))
    if b_now > b_cap:
        b_fix = max(5.0, math.floor(b_cap))
        values["B_beam"] = b_fix
        notes["B_beam"] = (f"c-13 频谱闭合：N_beam={n_final} → B_beam ≤ B_total×k/N_beam "
                           f"= {fmt(B_total,0)}×{k}/{n_final} = {fmt(b_cap,0)}MHz → 取 {fmt(b_fix,0)}MHz"
                           f"（原 {fmt(b_now,0)}MHz 超限已下调）")
        # B_carrier 随最终 B_beam 同步
        values["B_carrier"] = round(min(max(1.0, b_fix / 4), 62.0) if n_final > 1 else b_fix, 1)
        notes["B_carrier"] = "单载波取波束带宽 1/4 左右（SCPC 小载波，噪声带宽最优）"

    # ---- 功放/体制 ----
    amp = MODE_HPA.get(mode, "TWTA")
    if ant == "大容量多波束":
        amp = "MPA"
    values["amp_type"] = amp
    notes["amp_type"] = (f"{MODES.get(mode,{}).get('cn',mode)} 推荐 {amp}"
                         + ("；VHTS 标配 MPA 功率池（波束间动态调配）" if ant == "大容量多波束" else ""))
    values["P_out"] = 0
    notes["P_out"] = "留空由 EIRP 需求自动反推（skill 五维①核心，勿手填）"
    values["mode"] = mode
    values["isl_r_gbps"] = 10
    notes["isl_r_gbps"] = "激光星间链路货架主流 10Gbps（5/10/20 可选）"

    # ---- 工作模式需求 ----
    mode_req = "多波束"
    if n_sug <= 1:
        mode_req = "单波束"
    if ant in ("相控阵", "混合多波束") and cfg.get("orbit") in ("LEO", "MEO", "SSO"):
        mode_req = "在轨重构"
    if ant == "混合多波束" and cfg.get("orbit") == "GEO" and svc.get("C_gbps", 0) < 20:
        mode_req = "波束跳变"
    values["Mode"] = mode_req
    notes["Mode"] = f"按体制/轨道/业务建议工作模式需求：{mode_req}"

    auto = {k: v for k, v in values.items() if v != ""}
    return dict(values=values, notes=notes, auto=auto)


# ================================================================
# 13 问题诊断器（方案不合适 → 弹出具体问题，便于修改）
# ================================================================
# 每条硬约束失败 → 结构化问题（什么/差多少/改哪个参数/建议动作）
def diagnose_result(cfg, p, res, totals, plat_rec, launch_rec, is_custom_ant, geo, req):
    """把 25 条约束失败 + 平台缺口 + 链路不闭合翻译成『可操作的问题清单』。

    返回 dict(ok, level, issues[])：
      level: ok（全过）/ warn（仅警告）/ bad（硬失败，方案不合适）
      issues: [{id, title, detail, gap, param, suggestion, sev}]
    """
    issues = []
    der = p.get("_derived", {})
    summary = res.get("summary", {})
    fail_ids = set(summary.get("fail", []))
    warn_ids = set(summary.get("warn", []))
    c_by_id = {c["id"]: c for c in res.get("constraints", [])}

    def item(c, name):
        for it in (c.get("items") or []):
            if it[0] == name:
                return it[1]
        return None

    # ---- c-17 质量/功耗超平台预算（最常见：相控阵功率墙）----
    if "c-17" in fail_ids:
        c = c_by_id["c-17"]
        m, mb = item(c, "M_pay"), item(c, "M_budget")
        pw, pb = item(c, "P_pay"), item(c, "P_budget")
        gap_m = (to_f(m, 0) - to_f(mb, 1))
        gap_p = (to_f(pw, 0) - to_f(pb, 1))
        detail = []
        sugg = []
        if gap_p > 0:
            detail.append(f"载荷功耗 {fmt(pw,0)}W 超平台预算 {fmt(pb,0)}W（超 {fmt(gap_p,0)}W，"
                          f"{fmt(pw/max(pb,1e-9),1)} 倍）")
            if cfg.get("ant_type") == "相控阵":
                n_el = to_f(cfg.get("N_el"), 0)
                sub = cfg.get("array_subtype", "")
                p_el = ARR_P_PER_EL.get(sub, 0.9)
                sugg.append(f"根因＝相控阵功率墙：N_el={fmt(n_el,0)}×{fmt(p_el,1)}W/元（偏置）即 "
                            f"{fmt(n_el*p_el,0)}W。建议：①改固面/大容量多波束反射面（同增益功耗降 1~2 个数量级）；"
                            f"②若必须相控阵→减 N_el 并降容量指标，或换大供电平台（GEO-LRG65 10kW/DFH-5 8kW）；"
                            f"③选低功耗子体制（反射阵 1.2W/元、数字模拟混合 0.9W/元）")
            else:
                sugg.append("减配载荷（功放/波束数）或换更大供电平台")
        if gap_m > 0:
            detail.append(f"载荷质量 {fmt(m,0)}kg 超平台预算 {fmt(mb,0)}kg（超 {fmt(gap_m,0)}kg）")
            sugg.append("减口径/阵元数，或换更大承载平台（DFH-5 1200kg / GEO-LRG65 800kg）")
        issues.append(dict(id="c-17", sev="bad",
                           title="载荷质量/功耗超出平台承载（方案不可行）",
                           detail="；".join(detail) or c.get("note", ""),
                           param="ant_type / N_el / D_ap / platform_pref",
                           suggestion=" ".join(sugg) or "减配载荷或升级平台"))

    # ---- c-12 容量缺口 ----
    if "c-12" in fail_ids:
        c = c_by_id["c-12"]
        cs, cr = item(c, "C_sys"), item(c, "C_req")
        ceil_ = item(c, "C_ceil")
        gap = to_f(cr, 0) - to_f(cs, 0)
        issues.append(dict(id="c-12", sev="bad",
                           title="系统容量不满足需求",
                           detail=(f"C_sys={fmt(cs,2)}Gbps < 需求 {fmt(cr,2)}Gbps（缺口 {fmt(gap,2)}Gbps）；"
                                   f"该频段频谱物理上限 {fmt(ceil_,1)}Gbps"),
                           param="N_beam / B_beam / k_reuse / n_pol / C_req_ovr",
                           suggestion=(f"①增波束数（当前 {fmt(to_f(p.get('N_beam'),0),0)}，容量 ∝ N_beam）；"
                                       f"②增单波束带宽（c-13 允许至 B_total×k/N_beam）；"
                                       f"③提频率复用色数 k（当前 {fmt(to_f(p.get('k_reuse'),4),0)}）；"
                                       f"④确认双极化 n_pol=2；⑤若需求本身超频谱上限（{fmt(ceil_,1)}Gbps）"
                                       f"→ 降 C_req_ovr 或改多星组网")))

    # ---- c-13 频率规划冲突 ----
    if "c-13" in fail_ids:
        c = c_by_id["c-13"]
        lhs, rhs = item(c, "N_beam×B_beam"), item(c, "B_total×k_reuse")
        n_sug = int(to_f(rhs, 0) // max(to_f(p.get("B_beam"), 1), 1e-9))
        issues.append(dict(id="c-13", sev="bad",
                           title="频率规划冲突（频谱超限）",
                           detail=f"N_beam×B_beam={fmt(lhs,0)}MHz > B_total×k={fmt(rhs,0)}MHz",
                           param="N_beam / B_beam / k_reuse",
                           suggestion=(f"①减波束数至 ≤{n_sug}；②减单波束带宽；"
                                       f"③增复用色数 k（{to_f(p.get('k_reuse'),4):.0f}→7）")))

    # ---- c-10 链路余量不足（上下行）----
    loop = res.get("loop", {})
    if loop.get("need"):
        worst = loop.get("worst_M", 0)
        deficit = loop.get("deficit", 0)
        adv = (loop.get("advice") or [])[:3]
        adv_txt = "；".join(f"{a['step']}（{a['action']}，+{fmt(a['gain_db'],2) if a.get('gain_db') else '—'}dB"
                            f"{'' if a.get('enough') else '·不足'}）" for a in adv)
        issues.append(dict(id="c-10", sev="bad",
                           title="链路余量不闭合（低于 3dB 门限）",
                           detail=f"最差链路余量 {fmt(worst,2)}dB，缺口 {fmt(deficit,2)}dB",
                           param="D_ap / N_el / P_out / B_carrier / A_avail / mode",
                           suggestion=adv_txt or "增大天线口径/功放功率，或降阶调制、减小单载波带宽"))

    # ---- c-22 需求闭环（EIRP/G/T 缺口 → 天线能力不足）----
    if "c-22" in fail_ids:
        c = c_by_id["c-22"]
        ea, er = item(c, "EIRP_ant"), item(c, "EIRP_req")
        ga, gr = item(c, "GT_ant"), item(c, "GT_req")
        detail = []
        sugg = []
        if to_f(ea, 0) < to_f(er, 0):
            detail.append(f"EIRP {fmt(ea,1)} < 需求 {fmt(er,1)}dBW（差 {fmt(to_f(er,0)-to_f(ea,0),2)}dB）")
            sugg.append("增大功放功率或天线增益（口径/阵元数）")
        if to_f(ga, 0) < to_f(gr, 0):
            detail.append(f"G/T {fmt(ga,1)} < 需求 {fmt(gr,1)}dB/K（差 {fmt(to_f(gr,0)-to_f(ga,0),2)}dB）")
            if cfg.get("ant_type") == "相控阵":
                g_need = to_f(gr, 0) + 10 * math.log10(max(to_f(der.get("t_sys", {}).get("相控阵", 200), 1), 1e-6))
                sugg.append(f"天线增益需 ≥{fmt(g_need,1)}dBi → 增大 N_el 或改反射面体制")
            else:
                sugg.append("增大反射面口径（G=10lg(η(πD/λ)²)）或降低接收链噪声温度")
        issues.append(dict(id="c-22", sev="bad",
                           title="天线能力不满足链路需求闭环",
                           detail="；".join(detail) or c.get("note", ""),
                           param="D_ap / N_el / ant_type / array_subtype",
                           suggestion="；".join(sugg) or "触发内环换天线（≤3 次）"))

    # ---- 平台缺口（无同轨道可行平台）----
    if p.get("_plat_gap"):
        issues.append(dict(id="platform", sev="bad",
                           title="无满足承载的同轨道平台",
                           detail=p["_plat_gap"],
                           param="ant_type / N_el / D_ap / platform_pref",
                           suggestion="减配载荷（降功耗/质量）或改选更大平台；见 c-17 建议"))

    # ---- 运载缺口 ----
    if not launch_rec and plat_rec:
        issues.append(dict(id="launcher", sev="warn",
                           title="无满足能力的运载火箭",
                           detail=f"整星质量 {fmt(plat_rec[1].get('m_sat',0)/1000,2)}t 超出候选运载能力或整流罩受限",
                           param="D_ap / orbit",
                           suggestion="减小天线口径（整流罩约束）或换重型运载"))

    # ---- c-21 定制缺口（警告级）----
    if "c-21" in warn_ids:
        c = c_by_id["c-21"]
        issues.append(dict(id="c-21", sev="warn",
                           title="存在定制单机缺口（货架化不足）",
                           detail=c.get("note", ""),
                           param="ant_type / band",
                           suggestion="优先选货架产品（level 3~4）；定制项须记录需求/风险/研制周期"))

    # ---- 其余未覆盖的硬失败 ----
    covered = {"c-17", "c-12", "c-13", "c-10", "c-22"}
    for cid in sorted(fail_ids - covered):
        c = c_by_id.get(cid)
        if not c:
            continue
        issues.append(dict(id=cid, sev="bad",
                           title=f"约束 {cid} 未闭合",
                           detail=c.get("note", ""),
                           param="见约束页公式与明细",
                           suggestion=c.get("formula", "")))
    for cid in sorted(warn_ids - {"c-21"}):
        c = c_by_id.get(cid)
        if not c:
            continue
        issues.append(dict(id=cid, sev="warn",
                           title=f"约束 {cid} 警告",
                           detail=c.get("note", ""),
                           param="见约束页",
                           suggestion=""))

    # ---- 几何警告（覆盖超视域等）----
    for w in (geo.get("warns") or []):
        issues.append(dict(id="geo", sev="warn", title="覆盖几何提示",
                           detail=w, param="orbit / coverage / cov_r_km",
                           suggestion="改轨道（LEO→星座组网）或压缩覆盖半径"))

    level = "ok"
    if any(i["sev"] == "warn" for i in issues):
        level = "warn"
    if any(i["sev"] == "bad" for i in issues):
        level = "bad"
    return dict(ok=(level == "ok"), level=level, issues=issues,
                judge=f"{summary.get('judge_pass')}/{summary.get('judge_total')}",
                fail=sorted(fail_ids), warn=sorted(warn_ids))
