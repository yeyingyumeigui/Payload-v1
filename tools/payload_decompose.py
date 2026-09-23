# -*- coding: utf-8 -*-
"""载荷指标拆解 → 结构框架 → 单机选型判断逻辑 → 验证（四级流水线）。

与 design_engine / infoflow_engine 完全同源：
  · 几何：slant_range / coverage_angle / derive_geometry
  · 链路需求反推：EIRP_req / GT_req 公式与 cfg_to_params 一致（c-7/c-8）
  · 增益公式：固面 G=10lg(η(πD/λ)²)（c-4）；相控阵 G=10lg(N_el·η)+G_el−扫描损耗（c-3）
  · 容量：C_sys = N_beam × B_beam × η × n_pol（c-12，不乘 k_reuse）
  · 频谱：N_beam × B_beam ≤ B_total × k_reuse（c-13）

四级输出：
  L0 需求层   parse_requirement   —— 任务书语言 → 结构化需求
  L1 系统层   decompose_system    —— 几何/链路/频谱/平台接口四类系统指标
  L2 分系统层 decompose_subsys    —— 天线/接收/处理/发射/测控星务五分系统指标分配
  L3 单机层   unit_requirements   —— 单机指标要求（复用 design_all 的选型结果）

结构框架：
  form_framework       —— 指标 → 载荷结构框架（五功能链 + 配置决策链）
  decide_array_subtype —— 相控阵子体制五关判决（硬门槛×3 + 功率闭合 + 软指标评分）

选型判断逻辑：
  SELECTION_LOGIC      —— 七步漏斗（文档化决策表，与 select_antennas/build_equipment 实现对齐）
  trace_selection      —— 对 design_all 结果生成每类单机的判断链追溯

验证：
  validate_decomposition —— V1 指标树自洽 / V2 拆解vs引擎 / V3 约束闭合 /
                            V4 平台闭合 / V5 子体制判决复核
"""
from __future__ import annotations
import math

from infoflow_engine import to_f, fmt, fspl, rain_at_avail, K_BOLTZ_DB
from infoflow_data import BANDS
from design_data import (ORBITS, COVERAGE, SERVICES, MODES, ANT_TYPES,
                         ARRAY_SUBTYPES, BAND_FREQ, BAND_RAIN, SHELF_BY_ID)
import design_engine as DE

R_EARTH = DE.R_EARTH
L_TX_BY_AMP = DE.L_TX_BY_AMP
ARR_P_PER_EL = DE.ARR_P_PER_EL
ARR_M_PER_EL = DE.ARR_M_PER_EL
EIRP_GUARD_DB = DE.EIRP_GUARD_DB
NF_BY_BAND = DE.NF_BY_BAND
T_ANT_BY_BAND = DE.T_ANT_BY_BAND
ETA_PA = DE.ETA_PA


# ================================================================
# L0 需求层：任务书 → 结构化需求
# ================================================================
def parse_requirement(req_text, cfg=None):
    """把任务书式需求（自然语言要点 + 可选 cfg）解析为结构化需求字典。

    cfg 缺省时按需求要点给出默认建议值（可被显式 cfg 覆盖）。
    """
    cfg = dict(cfg or {})
    svc = SERVICES.get(cfg.get("service", "高通量宽带"), SERVICES["高通量宽带"])
    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    cov = COVERAGE.get(cfg.get("coverage", "区域"), COVERAGE["区域"])
    return dict(
        text=req_text,
        mission=dict(
            orbit=cfg.get("orbit", "GEO"), orbit_cn=orb["cn"], alt_km=orb["alt_km"],
            coverage=cfg.get("coverage", "区域"), coverage_cn=cov["cn"],
            service=cfg.get("service", "高通量宽带"), service_cn=svc["cn"],
            band=cfg.get("band", "Ka"), mode=cfg.get("mode", "数字透明"),
            ant_type=cfg.get("ant_type", "相控阵"),
            array_subtype=cfg.get("array_subtype", ""),
            C_req=to_f(cfg.get("C_req_ovr"), svc["C_gbps"]),
            avail=to_f(cfg.get("A_avail"), svc["avail"]),
            life_yr=to_f(cfg.get("life_yr"), orb["life_yr"]),
            sat_scale=cfg.get("sat_scale", "小卫星"),
        ),
        cfg=cfg,
    )


# ================================================================
# L1 系统层：几何/链路/频谱/平台接口
# ================================================================
def decompose_system(req0, kg):
    """系统级指标拆解：几何 → 链路需求反推 → 频谱规划 → 容量 → 平台接口预算。

    返回指标树节点列表（每节点：id/层级/名称/值/单位/公式/来源/追溯）。
    """
    cfg = req0["cfg"]
    geo = DE.derive_geometry(cfg)
    parsed = DE.parse_config(cfg)
    p = DE.cfg_to_params(cfg, geo, parsed, kg)
    der = p["_derived"]
    band = cfg.get("band", "Ka")
    f_up, f_dn = BAND_FREQ.get(band, (30.0, 20.0))
    Bd = BANDS.get(band, BANDS["Ka"])
    k_reuse = der["k_reuse"]
    n_pol = to_f(p.get("n_pol"), 2)

    tree = []

    def n(id, name, value, unit, formula, src, note="", level=1):
        tree.append(dict(id=id, level=level, name=name, value=value, unit=unit,
                         formula=formula, src=src, note=note))

    # ---- A 几何类 ----
    n("s-geo-1", "轨道高度 h", geo["orbit_alt_km"], "km", "轨道库", "任务约束",
      f"{ORBITS.get(cfg.get('orbit'),{}).get('cn','')}")
    n("s-geo-2", "最小用户仰角 el", geo["el_deg"], "°", "覆盖区库 el_min", "覆盖约束",
      COVERAGE.get(cfg.get("coverage"), {}).get("note", "")[:60])
    n("s-geo-3", "最差路径斜距 d", round(geo["d_slant"], 1), "km",
      "d=√(R²sin²el+2Rh+h²)−R·sin(el)", "几何推导")
    n("s-geo-4", "覆盖地心角 ψ", round(geo["psi_cov_deg"], 2), "°",
      "ψ=arccos(R·cos(el)/(R+h))−el", "几何推导")
    n("s-geo-5", "单星覆盖半径上限", round(geo["cov_r_cap_km"], 0), "km",
      "r_cap=R·ψ(rad)", "几何推导",
      f"配置覆盖半径 {fmt(geo['cov_r_km'],0)}km → {'单星可覆盖' if geo['cov_r_km']<=geo['cov_r_cap_km'] else '需星座'}")
    n("s-geo-6", "波束地心张角 θ_beam", round(geo["θ_beam_deg"], 3), "°",
      "θ=2·arcsin(r_beam/R)", "波束半径假设",
      f"波束半径 {fmt(geo['beam_r_km'],0)}km")
    n("s-geo-7", "几何建议波束数 N_beam", geo["N_beam_geo"], "个",
      "N≈1.209·(r_cov/r_beam)²（六边形密铺）", "覆盖密铺")
    # ---- B 链路类（需求反推）----
    n("s-lnk-1", "上行自由空间损耗 Lfs_up", round(der["Lfs_up"], 2), "dB",
      "20lg(d)+20lg(f_up)+20lg(4π/c)", f"d={fmt(geo['d_slant'],0)}km, f={f_up}GHz")
    n("s-lnk-2", "下行自由空间损耗 Lfs_dn", round(der["Lfs_dn"], 2), "dB",
      "同上", f"f={f_dn}GHz")
    n("s-lnk-3", "上行总损耗 ΣL_up", round(der["ΣL_up"], 2), "dB",
      "雨衰(p)+大气+指向+极化+实现+动态", f"雨衰={fmt(der['rain_up'],2)}dB@{parsed['avail']}%")
    n("s-lnk-4", "下行总损耗 ΣL_dn", round(der["ΣL_dn"], 2), "dB",
      "同上", f"雨衰={fmt(der['rain_dn'],2)}dB@{parsed['avail']}%")
    n("s-lnk-5", "设计 (C/N)req", der["CN_des"], "dB",
      "业务设计点（MODCOD 门槛+目标余量）", f"服务库 {cfg.get('service')}")
    n("s-lnk-6", "终端 EIRP", parsed["EIRP_term"], "dBW", "业务终端能力", "服务库")
    n("s-lnk-7", "终端 G/T", parsed["GT_term"], "dB/K", "业务终端能力", "服务库")
    n("s-lnk-8", "★星上 G/T 需求", round(der["GT_req"], 2), "dB/K",
      "GT_req=(C/N)des+M_t+10lg(B_car)−EIRP_term+Lfs_up+ΣL_up+228.6",
      "上行链路闭合反推（c-8）")
    n("s-lnk-9", "★星上整波束 EIRP 需求", round(der["EIRP_req"], 2), "dBW",
      "EIRP_req=(C/N)des+M_t+10lg(B_car)−GT_term+Lfs_dn+ΣL_dn+228.6+10lg(B_beam/B_car)",
      "下行链路闭合反推（c-7）")
    n("s-lnk-10", "单波束功放功率需求 P_out", round(der["P_out_w"], 1), "W",
      "P_out=10^((EIRP_req+0.3−G_ant+L_feed+L_tx)/10)",
      f"按预估天线增益 {fmt(der['G_ant_est'],1)}dBi 反推（选定货架/定制后重反推）")
    # ---- C 频谱/容量类 ----
    B_total = p["B_total"]
    n("s-frq-1", "频段可用带宽 B_total", B_total, "MHz", "ITU 指配（口径库）", band)
    n("s-frq-2", "频率复用色数 k", k_reuse, "色", "覆盖区库 k_typ/用户指定", "")
    n("s-frq-3", "单波束带宽 B_beam", p["B_beam"], "MHz", "配置/业务", "")
    lhs = der["N_beam"] * p["B_beam"]
    n("s-frq-4", "频谱占用 N_beam×B_beam", round(lhs, 0), "MHz",
      f"≤ B_total×k={B_total*k_reuse}MHz（c-13）",
      "频率规划闭合", "OK" if lhs <= B_total * k_reuse else "冲突！")
    eta_nom = 2.0   # 名义频谱效率（bps/Hz，DVB-S2X 8PSK~16APSK 量级）
    C_sys = der["N_beam"] * p["B_beam"] * eta_nom * n_pol / 1000.0
    n("s-cap-1", "系统容量 C_sys", round(C_sys, 2), "Gbps",
      "C_sys=N_beam×B_beam×η×n_pol（c-12）",
      f"η={eta_nom}bps/Hz 名义 · n_pol={n_pol:.0f}",
      f"需求 {fmt(parsed['C_req'],1)}Gbps → {'满足' if C_sys>=parsed['C_req'] else '缺口'}")
    # ---- D 平台接口类 ----
    m_ant = DE.estimate_antenna_mass(cfg, p)
    p_ant = DE.estimate_antenna_power(cfg, p)
    n("s-plf-1", "天线分系统质量（估）", round(m_ant, 1), "kg",
      "相控阵 N_el×m_el+10 / 反射面 πD²/4×m_m2+8", "初步估算")
    n("s-plf-2", "天线分系统功耗（估）", round(p_ant, 1), "W",
      "相控阵 N_el×P_tr+30", "初步估算")
    n("s-plf-3", "载荷质量预算（含20%裕度）", round((m_ant + 150) * 1.2, 1), "kg",
      "(m_ant+转发器等)×1.2", "平台选型输入")
    n("s-plf-4", "载荷功耗预算（含20%裕度）", round((p_ant + 800) * 1.2, 1), "W",
      "(P_ant+P_trp等)×1.2", "平台选型输入")
    n("s-plf-5", "寿命", req0["mission"]["life_yr"], "年", "任务约束", "")

    return dict(tree=tree, geo=geo, params=p, parsed=parsed,
                summary=dict(d_slant=geo["d_slant"], GT_req=der["GT_req"],
                             EIRP_req=der["EIRP_req"], P_out_w=der["P_out_w"],
                             N_beam=der["N_beam"], B_beam=p["B_beam"],
                             C_sys=C_sys, k_reuse=k_reuse, n_pol=n_pol,
                             θ_beam_deg=geo["θ_beam_deg"], warns=geo["warns"]))


# ================================================================
# L2 分系统层：五分系统指标分配
# ================================================================
def decompose_subsys(sysdec, cfg):
    """把系统级指标分配到五个分系统（天线/接收/处理/发射/测控星务）。

    每个分系统给出：承担的系统指标、自身关键指标、指标来源公式、下游单机要求。
    """
    p = sysdec["params"]
    der = p["_derived"]
    s = sysdec["summary"]
    band = cfg.get("band", "Ka")
    ant = cfg.get("ant_type", "相控阵")
    sub = cfg.get("array_subtype", "")
    mode = cfg.get("mode", "数字透明")
    subinfo = ARRAY_SUBTYPES.get(sub, {})
    N_beam = s["N_beam"]
    n_pol = to_f(p.get("n_pol"), 2)

    subs = []

    def S(key, cn, indices, units_req, chain_note):
        subs.append(dict(key=key, cn=cn, indices=indices, units_req=units_req,
                         chain_note=chain_note))

    # ① 天线分系统
    if ant == "相控阵":
        eta = subinfo.get("eta", 0.62)
        G_el = to_f(cfg.get("G_el"), 6.0)
        θ_scan = to_f(cfg.get("θ_scan"), 0)
        scan_loss = (-10 * 1.5 * math.log10(max(math.cos(math.radians(θ_scan)), 1e-6))
                     if θ_scan > 0 else 0.0)
        # 反推阵元数：N_el ≥ 10^((G_req − G_el + scan_loss)/10) / η
        G_need = der["G_ant_est"]
        N_el_need = 10 ** ((G_need - G_el + scan_loss) / 10.0) / max(eta, 1e-6)
        N_el = to_f(cfg.get("N_el"), 1024)
        ant_idx = [
            ("增益 G", f"{fmt(der['G_ant_est'],1)} dBi",
             f"G=10lg(N_el·η)+G_el−扫描损耗；N_el={fmt(N_el,0)}, η={eta}, 扫描{fmt(θ_scan,0)}°(损耗{fmt(scan_loss,2)}dB)"),
            ("阵元数 N_el", f"{fmt(N_el,0)} 元（按增益需求 ≥{fmt(N_el_need,0)}）",
             "c-3 反推"),
            ("波束宽度 θ3dB", f"{fmt(der['θ_3dB_est'],3)}°",
             "θ3=0.886λ/L, L=√(N_el)·λ/2"),
            ("扫描角", f"±{fmt(θ_scan,0)}°（子体制上限 ±{subinfo.get('scan_max','—')}°）",
             "覆盖偏角需求（c-21）"),
            ("波束数", f"{N_beam} 个", "c-13 频谱规划"),
            ("极化", f"{n_pol:.0f} 极化（复用）", "c-12 容量"),
            ("面精度/幅相一致性", "Δ_amp≤0.5dB, Δ_phs≤5°, 校准Δ≤0.3dB", "c-23"),
        ]
        ant_units = ["T/R 组件", "移相器/幅相控制", "波束赋形网络 BFN", "校准网络", "阵面结构/展开机构"]
    else:
        D = to_f(cfg.get("D_ap"), 2.5)
        ant_idx = [
            ("增益 G", f"{fmt(der['G_ant_est'],1)} dBi", f"G=10lg(η(πD/λ)²), D={D}m"),
            ("口径 D", f"{fmt(D,2)} m", "c-4 反推"),
            ("波束宽度 θ3dB", f"{fmt(der['θ_3dB_est'],3)}°", "θ3≈70λ/D"),
            ("波束数", f"{N_beam} 个", "多馈源+成形反射面"),
            ("面精度 δ_surf", f"≤ λ/32 = {fmt(DE.lam_m(BAND_FREQ[band][1])*1000/32,2)}mm" if band in BAND_FREQ else "—", "c-5"),
            ("指向精度", "θ_e≤0.1θ3dB", "c-6"),
        ]
        ant_units = ["反射面/展开机构", "馈源/多馈源阵", "指向机构", "BFN", "天线控制单元 ACU"]

    S("ant", f"天线分系统（{ANT_TYPES.get(ant,{}).get('cn','')}"
             + (f"·{subinfo.get('cn','')}" if subinfo else "") + "）",
      ant_idx, ant_units,
      "承担 s-lnk-8/9（G/T、EIRP 的天线增益项）与 s-geo-6/7（波束宽度/波束数）")

    # ② 接收分系统（上行）
    T_fam = der["t_sys"].get("相控阵" if ant == "相控阵" else "固面", 200)
    NF = NF_BY_BAND.get(band, 1.6)
    rx_idx = [
        ("G/T 分配", f"整星需求 {fmt(der['GT_req'],1)} dB/K；T_sys={fmt(T_fam,0)}K 时天线需 G≥{fmt(der['GT_req']+10*math.log10(max(T_fam,1e-6)),1)}dBi",
         "G/T=G_ant−10lg(T_sys)（c-2）"),
        ("LNA 噪声系数", f"≤ {fmt(NF,1)} dB", f"{band} 频段货架水平（c-2 首级主导）"),
        ("接收链增益", "≥ 35dB（抑制后级噪声）", "Friis 级联"),
        ("收发隔离", "≥ 100dB", "c-15（环行器+空间隔离）"),
        ("通道数", f"{max(1, math.ceil(N_beam / max(int(to_f(p.get('k_reuse'), 4)), 1)))} 路（N_beam/k_reuse）",
         "同色波束共链，异色分链"),
    ]
    S("rx", "接收分系统（上行通道）", rx_idx,
      ["环行器/隔离器", "低噪放 LNA（A/B 冷备）", "下变频器", "频率源/本振"],
      "承担 s-lnk-8 的 T_sys 项（噪声温度分配）")

    # ③ 处理/交换分系统
    C_need_gbps = N_beam * p["B_beam"] * 2.0 / 1000.0
    if mode == "透明":
        proc_idx = [("信道化", "整带滤波（IMUX/OMUX）", "透明弯管"),
                    ("群时延平坦度", "≤ 1dB/通道", "c-19"),
                    ("通道倒换", "微波开关矩阵 80dB 隔离", "备份重构")]
        proc_units = ["输入多工器 IMUX", "均衡器/衰减器", "微波开关矩阵", "输出多工器 OMUX"]
        chain_note = "透明转发：无星上交换，跨波束落地双跳"
    elif mode == "数字透明":
        proc_idx = [("交换容量 C_sw", f"≥ {fmt(max(50, math.ceil(C_need_gbps / 50) * 50 + 50),0)} Gbps",
                     f"c-14：C_sw ≥ N_beam×B_beam×η = {fmt(C_need_gbps,1)}Gbps"),
                    ("信道化子带", f"B_sub={fmt(p['B_sub'],0)}MHz × N_ch={p['N_ch']}", "c-14"),
                    ("ADC/DAC", "ENOB≥10bit, SFDR≥70dBc", "数字化链路指标"),
                    ("重构时延", f"≤ {fmt(p['t_rec'],0)}s（波束/子带/功率/路由四维）", "在轨重构"),
                    ("处理时延", "≈3ms", "DTP 群时延")]
        proc_units = ["DTP 处理器", "宽带 ADC", "宽带 DAC", "在轨重构控制器"]
        chain_note = "数字透明（DTP）：子带级交换与重构，柔性载荷"
    else:
        proc_idx = [("解调/译码", "DVB-S2X ACM/VCM，LDPC 编码增益 6.5dB", "再生体制"),
                    ("星上路由", "路由表≥4096，跨波束单跳", "再生交换"),
                    ("体制增益", f"ΔM_reg=+{fmt(p['ΔM_reg'],1)}dB（噪声不累积）", "c-24"),
                    ("处理时延", "30~60ms", "解调译码再调制")]
        proc_units = ["调制解调器", "LDPC 编译码器", "星上路由交换", "基带处理单元", "AI 推理单元"]
        chain_note = "再生处理（OBPR）：噪声不累积，星上路由"
    S("proc", f"处理/交换分系统（{MODES.get(mode,{}).get('cn','')}）", proc_idx,
      proc_units, chain_note)

    # ④ 发射分系统（下行）
    amp = cfg.get("amp_type") or DE.MODE_HPA.get(mode, "TWTA")
    if ant == "相控阵":
        P_face_rf = der["P_out_w"] * N_beam
        tx_idx = [
            ("单波束功率 P_out", f"{fmt(der['P_out_w'],1)} W/波束", der["p_out_source"]),
            ("阵面射频总功率", f"{fmt(P_face_rf,0)} W", f"P_out×N_beam（{N_beam} 波束同时）"),
            ("每阵元辐射功率", f"{fmt(der['P_out_w']*N_beam/max(to_f(cfg.get('N_el'),1024),1),2)} W/元 ≤ 8W",
             "T/R 组件功率容量"),
            ("功放直流功耗", f"≈{fmt(P_face_rf/0.30,0)} W（η_PA≈30% 阵元级）", "c-16 P_dc≤P_trp"),
            ("EIRP 达成", f"≥ {fmt(der['EIRP_req'],1)} dBW（+0.3dB 守卫）", "c-1/c-22"),
        ]
        tx_units = ["T/R 组件功放（分布式）", "EPC 功率调节器", "上变频器", "OMUX"]
    else:
        n_hpa = N_beam + math.ceil(N_beam / 8)
        tx_idx = [
            ("单波束功率 P_out", f"{fmt(der['P_out_w'],1)} W/波束", der["p_out_source"]),
            ("功放类型", f"{amp}（η={ETA_PA.get(amp,58)}%）", f"体制偏好 {MODES.get(mode,{}).get('hpa_pref','')}"),
            ("功放数量", f"{n_hpa} 台（N_beam+1/8 环备份）", "备份策略"),
            ("直流总功耗", f"≈{fmt(der['P_out_w']*N_beam/(ETA_PA.get(amp,58)/100),0)} W", "c-16"),
            ("EIRP 达成", f"≥ {fmt(der['EIRP_req'],1)} dBW", "c-1/c-22"),
        ]
        tx_units = [f"{amp} 行波管/固态功放", "EPC", "上变频器", "OMUX"]
    S("tx", f"发射分系统（下行通道·{amp}）", tx_idx, tx_units,
      "承担 s-lnk-9/10（EIRP 的功放功率项）")

    # ⑤ 测控与星务分系统
    ttc_idx = [
        ("测控应答机", "1+1 统一载波 TT&C", "测控链路"),
        ("信标", "1+1，5W CW 测轨", "定轨"),
        ("星载计算机", "1+1，4000MIPS，FDIR 覆盖关键单机", "载荷管理"),
        ("数据总线", f"FC-AE {fmt(p['R_bus'],0)}Mbps ≥ R_pdl/CR", "c-18 数传匹配"),
        ("存储", f"≥{fmt(p['E_store'],1)}Tb（盲区 15min 存储转发）", "c-18"),
    ]
    S("ttc", "测控与星务分系统", ttc_idx,
      ["测控应答机", "信标发射机", "星载计算机", "数据总线", "大容量存储器"],
      "承担平台接口与载荷自主管理")

    return dict(subs=subs, p=p, summary=s)


# ================================================================
# 结构框架：指标 → 五功能链 + 配置决策
# ================================================================
def form_framework(sysdec, subs, cfg):
    """按拆解出的指标生成载荷结构框架（配置决策链 + 五功能链拓扑）。"""
    p = subs["p"]
    der = p["_derived"]
    s = sysdec["summary"]
    band = cfg.get("band", "Ka")
    ant = cfg.get("ant_type", "相控阵")
    sub = cfg.get("array_subtype", "")
    mode = cfg.get("mode", "数字透明")

    decisions = []

    def D(k, q, a, why):
        decisions.append(dict(k=k, q=q, a=a, why=why))

    orb = ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"])
    D("d1", "轨道体制？", f"{orb['cn']}（h={fmt(orb['alt_km'],0)}km）",
      f"覆盖{cfg.get('coverage')}需连续驻留 → GEO 单星可覆盖（r_cap={fmt(sysdec['geo']['cov_r_cap_km'],0)}km ≥ "
      f"{fmt(sysdec['geo']['cov_r_km'],0)}km）" if cfg.get("orbit") == "GEO" else "任务约束")
    D("d2", "频段？", band,
      f"业务 {cfg.get('service')}（终端 G/T={fmt(sysdec['parsed']['GT_term'],0)}dB/K）+ 可用带宽 "
      f"{p['B_total']}MHz + 雨衰 {fmt(BAND_RAIN.get(band,(0,0))[1],1)}dB@0.01%")
    D("d3", "转发体制？", MODES.get(mode, {}).get("cn", mode),
      f"时延 {DE.MODE_DELAY_MS.get(mode,0)}ms/单跳；"
      + (MODES.get(mode, {}).get("flex", "")))
    D("d4", "天线类型？", ANT_TYPES.get(ant, {}).get("cn", ant),
      f"波束数 {s['N_beam']}（≥2 → 多波束成形）；扫描需求；增益需求 {fmt(der['G_ant_est'],1)}dBi")
    if ant == "相控阵":
        D("d5", "相控阵子体制？", ARRAY_SUBTYPES.get(sub, {}).get("cn", sub or "待定"),
          "见 decide_array_subtype 五关判决（口径/扫描角/阵元数硬门槛 + 功率质量闭合 + 成本风险评分）")
    D("d6", "波束规划？", f"{s['N_beam']} 波束 × {fmt(s['B_beam'],0)}MHz × {s['k_reuse']} 色 × {s['n_pol']:.0f} 极化",
      f"c-13 频谱闭合：{fmt(s['N_beam']*s['B_beam'],0)} ≤ {p['B_total']*s['k_reuse']}MHz")

    chains = [
        dict(cn="① 天线链（空间能量接口）",
             flow=("用户终端 ⇄ 阵面/反射面 ⇄ T/R 组件或馈源 ⇄ BFN/校准网络"
                   if ant == "相控阵" else
                   "用户终端 ⇄ 反射面 ⇄ 馈源阵 ⇄ 指向机构/ACU"),
             kpi=f"G={fmt(der['G_ant_est'],1)}dBi · θ3={fmt(der['θ_3dB_est'],3)}° · N_beam={s['N_beam']}"),
        dict(cn="② 接收链（上行）",
             flow="环行器 → LNA（A/B）→ 下变频 → 中频/数字信道化",
             kpi=f"GT_req={fmt(der['GT_req'],1)}dB/K · T_sys={fmt(der['t_sys'].get('相控阵' if ant=='相控阵' else '固面',0),0)}K · NF≤{fmt(NF_BY_BAND.get(band,1.6),1)}dB"),
        dict(cn=f"③ 处理链（{MODES.get(mode,{}).get('cn','')}）",
             flow={"透明": "IMUX → 均衡/滤波 → 开关矩阵",
                   "数字透明": "ADC → DTP 交换矩阵 → DAC",
                   "再生": "解调 → 译码 → 路由 → 编码 → 调制"}.get(mode, ""),
             kpi=f"C_sw≥{fmt(max(50, s['N_beam']*s['B_beam']*2.0/1000.0),0)}Gbps · 重构 {fmt(p['t_rec'],0)}s"),
        dict(cn="④ 发射链（下行）",
             flow=("上变频 → T/R 功放（分布式，集成于阵面）" if ant == "相控阵"
                   else f"上变频 → {cfg.get('amp_type') or DE.MODE_HPA.get(mode,'TWTA')} 功放 ×{s['N_beam']+math.ceil(s['N_beam']/8)} → OMUX → 馈源"),
             kpi=f"EIRP≥{fmt(der['EIRP_req'],1)}dBW · P_out={fmt(der['P_out_w'],1)}W/波束"),
        dict(cn="⑤ 测控星务链",
             flow="TT&C 应答机（1+1）+ 信标（1+1）+ 星载计算机（1+1）+ FC-AE 总线",
             kpi=f"总线 {fmt(p['R_bus'],0)}Mbps · 存储 {fmt(p['E_store'],1)}Tb · FDIR"),
    ]
    return dict(decisions=decisions, chains=chains)


# ================================================================
# 相控阵子体制判决（直射阵 vs 反射阵 vs 混合 vs 纯数字 vs 拼接）
# ================================================================
def solve_nel_for_eirp(EIRP_req, N_beam, eta, G_el, scan_loss,
                       L_feed=0.5, L_tx=3.8, p_el_max=8.0):
    """解「每阵元辐射功率 ≤ p_el_max」所需的最小阵元数（EIRP 闭合反推）。

    P_out(N_el) = 10^((EIRP_req+0.3−G(N_el)+L_feed+L_tx)/10)，G=10lg(N_el·η)+G_el−scan_loss
    约束：P_out×N_beam/N_el ≤ p_el_max。G 随 N_el 增大 → P_out 减小，单调可数值求解。
    """
    for n in (64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        G = 10 * math.log10(n * eta) + G_el - scan_loss
        P_out = 10 ** ((EIRP_req + EIRP_GUARD_DB - G + L_feed + L_tx) / 10.0)
        if P_out * N_beam / n <= p_el_max:
            return n, G, P_out
    return None, None, None


def array_envelope(P_ant_budget_w, P_rf_dc_budget_w, N_beam, EIRP_req,
                   L_feed=0.5, L_tx=3.8):
    """各子体制在给定平台功率预算下的「能力包络」：

    · N_el 上限（偏置功耗）：(P_ant−30)/ARR_P_PER_EL
    · 该上限对应的最大增益 G_max 与可达波束 EIRP_max（受 RF 直流预算限制）
    · EIRP 闭合所需最小阵元数（solve_nel_for_eirp）→ 是否在包络内
    与引擎同源：ARR_P_PER_EL（c-16 阵面功耗口径）、EIRP 反推公式（c-22）。
    """
    rows = []
    for key, st in ARRAY_SUBTYPES.items():
        eta = st["eta"]
        G_el = 6.0
        n_bias_max = int((P_ant_budget_w - 30.0) / ARR_P_PER_EL.get(key, 1.0))
        n_bias_max = min(n_bias_max, st["n_el_max"])
        G_max = 10 * math.log10(max(n_bias_max * eta, 1e-9)) + G_el
        P_rf_total = P_rf_dc_budget_w * 0.30        # 阵元级功放 η≈30%
        P_out_max = P_rf_total / max(N_beam, 1)
        EIRP_max = (10 * math.log10(max(P_out_max, 1e-9)) + G_max - L_feed - L_tx)
        n_req, G_req, P_out_req = solve_nel_for_eirp(EIRP_req, N_beam, eta, G_el, 0.0)
        rows.append(dict(
            key=key, cn=st["cn"],
            n_bias_max=n_bias_max, G_max=round(G_max, 1),
            EIRP_max=round(EIRP_max, 1),
            n_req_for_EIRP=n_req,
            n_req_ok=bool(n_req and n_req <= n_bias_max),
            gap_db=round(EIRP_req - EIRP_max, 1),
            mass_at_max=round(n_bias_max * st["mass_per_el"] + 10.0, 1),
        ))
    return rows


def decide_array_subtype(sysdec, cfg, p_budget_w=None, m_budget_kg=None,
                         p_rf_dc_budget_w=None):
    """五关判决法（与引擎功率口径同源）：

    关1 扫描角硬门槛   θ_scan ≤ scan_max
    关2 阵元数硬门槛   N_el ≤ n_el_max
    关3 带宽门槛       反射阵单元谐振：单波束相对带宽 <10%
    关4 功率/质量闭合  偏置功耗 N_el×ARR_P_PER_EL+30 ≤ P_budget（c-16 口径）；
                       阵面质量 N_el×m_el+10 ≤ M_budget；
                       EIRP 闭合：每阵元辐射 ≤8W 所需 N_el_req ≤ N_el
    关5 软指标评分     效率η(0.25)+成本(0.20)+成熟度t_rl(0.20)+功耗(0.20)+扩展性(0.15)
    """
    p = sysdec["params"]
    der = p["_derived"]
    band = cfg.get("band", "Ka")
    f_dn = BAND_FREQ.get(band, (30, 20))[1]
    θ_scan = to_f(cfg.get("θ_scan"), 0)
    N_el = to_f(cfg.get("N_el"), 1024)
    B_beam = p["B_beam"]
    B_rel = B_beam / (f_dn * 1000.0) * 100.0     # 单波束相对带宽 %
    N_beam = der["N_beam"]
    EIRP_req = der["EIRP_req"]
    rows = []
    for key, st in ARRAY_SUBTYPES.items():
        r = dict(key=key, cn=st["cn"], hard=[], soft={}, ok=True, note=[])
        # 关1 扫描角
        ok1 = θ_scan <= st["scan_max"]
        r["hard"].append(("扫描角", f"θ={fmt(θ_scan,0)}° ≤ ±{st['scan_max']}°", ok1))
        # 关2 阵元数
        ok2 = N_el <= st["n_el_max"]
        r["hard"].append(("阵元数", f"N_el={fmt(N_el,0)} ≤ {st['n_el_max']}", ok2))
        # 关3 带宽（反射阵单元谐振带宽 <10%，按单波束带宽口径）
        if key == "反射阵":
            ok3 = B_rel < 10.0
            r["hard"].append(("相对带宽", f"B_beam/f_dn={fmt(B_rel,2)}% < 10%（单元谐振）", ok3))
        else:
            ok3 = True
            r["hard"].append(("相对带宽", f"{fmt(B_rel,2)}%（无谐振限制）", True))
        # 关4a 偏置功耗（与引擎 c-16/estimate_antenna_power 同口径：ARR_P_PER_EL 平均偏置）
        P_bias = N_el * ARR_P_PER_EL.get(key, 1.0) + 30.0
        if p_budget_w:
            ok4p = P_bias <= p_budget_w
            r["hard"].append(("阵面偏置功耗", f"N_el×P_tr+30={fmt(P_bias,0)}W ≤ 预算 {fmt(p_budget_w,0)}W"
                              f"（峰值口径 N_el×p_tr_w={fmt(N_el*st['p_tr_w'],0)}W 供热控参考）", ok4p))
        else:
            ok4p = True
            r["note"].append(f"阵面偏置功耗 {fmt(P_bias,0)}W（未给预算，不淘汰）")
        # 关4b 质量
        M_face = N_el * st["mass_per_el"] + 10.0
        if m_budget_kg:
            ok4m = M_face <= m_budget_kg
            r["hard"].append(("阵面质量", f"N_el×m_el+10={fmt(M_face,0)}kg ≤ 预算 {fmt(m_budget_kg,0)}kg", ok4m))
        else:
            ok4m = True
        # 关4c EIRP 闭合（每阵元辐射 ≤8W 所需阵元数）
        scan_loss = (-10 * 1.5 * math.log10(math.cos(math.radians(θ_scan)))
                     if θ_scan > 0 else 0.0)
        n_req, g_req, p_out_req = solve_nel_for_eirp(EIRP_req, N_beam, st["eta"],
                                                     to_f(cfg.get("G_el"), 6.0), scan_loss)
        if n_req:
            ok4e = N_el >= n_req
            r["hard"].append(("EIRP闭合(每元≤8W)",
                              f"N_el={fmt(N_el,0)} ≥ 需求 {fmt(n_req,0)}（G={fmt(g_req,1)}dBi 时 "
                              f"P_out={fmt(p_out_req,1)}W/波束×{N_beam}波束）", ok4e))
            r["n_req_for_EIRP"] = n_req
        else:
            ok4e = False
            r["hard"].append(("EIRP闭合(每元≤8W)", f"EIRP_req={fmt(EIRP_req,1)}dBW 超出阵元功率物理极限", False))
            r["n_req_for_EIRP"] = None
        r["ok"] = all(x[2] for x in r["hard"])
        # 关5 软指标（0~10 分）
        soft = {
            "口径效率η": st["eta"] / 0.65 * 10,
            "成本": (2.5 - st["cost_mult"]) / 1.5 * 10,
            "成熟度": st["t_rl"],
            "单阵元功耗": (10 - st["p_tr_w"]) / 9.0 * 10,
            "扩展性(阵元上限)": min(10.0, st["n_el_max"] / 1638.4),
        }
        w = {"口径效率η": 0.25, "成本": 0.20, "成熟度": 0.20,
             "单阵元功耗": 0.20, "扩展性(阵元上限)": 0.15}
        r["soft"] = {k: round(v, 1) for k, v in soft.items()}
        r["score"] = round(sum(soft[k] * w[k] for k in w), 2)
        r["P_bias_w"] = round(P_bias, 0)
        r["M_face_kg"] = round(M_face, 0)
        rows.append(r)

    alive = [r for r in rows if r["ok"]]
    alive.sort(key=lambda r: -r["score"])
    rec = alive[0]["key"] if alive else None
    verdict = dict(rows=rows, alive=[r["key"] for r in alive],
                   recommend=rec,
                   recommend_cn=ARRAY_SUBTYPES[rec]["cn"] if rec else "无可行子体制",
                   θ_scan=θ_scan, N_el=N_el, B_rel=B_rel,
                   EIRP_req=EIRP_req, N_beam=N_beam)
    return verdict


# ================================================================
# 单机选型判断逻辑（文档化决策表 + 引擎追溯）
# ================================================================
SELECTION_LOGIC = [
    dict(step=1, name="频段硬过滤", rule="单机 bands 必须包含任务频段（或 *），否则直接淘汰",
         impl="select_antennas: band not in bands → skip；build_equipment: pick_shelf(cat, band)"),
    dict(step=2, name="体制一致性", rule="天线家族（固面/相控阵/伞状）与架构决策 d4/d5 一致者优先（+1.0 分）",
         impl="select_antennas: fam == ant_want → score += 1.0"),
    dict(step=3, name="EIRP 闭环（①0.30）", rule=(
         "按货架增益反推功放 P_cand=10^((EIRP_req+0.3−G_prod+L_feed+L_tx)/10)；"
         "相控阵：每阵元辐射功率 ≤8W；反射面：P_cand ≤250W；伞状 ≤120W。"
         "可行→满分；超限按 4·lg(超限比) 扣分"),
         impl="hpa_feasible + s_eirp"),
    dict(step=4, name="G/T 闭环（②0.25）", rule=(
         "G/T_cap = G_prod − 10lg(T_sys_family)（Friis 级联噪声温度，与引擎同源）；"
         "≥GT_req 满分，缺口按 1.5·Δ 扣分；GT 分 <6 → 转定制"),
         impl="gt_cap / s_gt / is_custom 判据"),
    dict(step=5, name="平台承载（③④各0.15）", rule=(
         "质量/功耗占平台预算比例越低分越高：s=10·(1−mass/m_cap)"),
         impl="s_mass / s_pow（m_cap/p_cap 来自预选平台）"),
    dict(step=6, name="工作模式与波束数（⑤0.15）", rule=(
         "天线体制模式上限（固面2/相控阵4/伞状2）≥ 任务模式等级；"
         "货架 N_beam ≥ 需求 N_beam，否则 ×0.6"),
         impl="ANT_MODE_CAP / n_beam_cap / s_mode"),
    dict(step=7, name="货架水平与定制兜底", rule=(
         "同等条件下 level 高者优先（4=飞行继承货架 → 1=定制，+0.2/级）；"
         "货架电气不满足（EIRP 不可行或 G/T 分<6）→ 定制（计入 N_gap）；"
         "非天线单机按 pick_shelf(cat,band) 取 level 最高、质量最小者"),
         impl="score += 0.2*(level−3)；ANT-CUSTOM 分支；pick_shelf key=(level,−mass)"),
]


def trace_selection(design, cfg):
    """对 design_all 结果生成每类单机的判断链追溯（判断逻辑的实例化证据）。"""
    out = []
    band = cfg.get("band", "Ka")
    # 天线：五维评分表
    ant_cands = design.get("ant_cands", [])
    ant_rec = design.get("ant_rec")
    for sc, prod, reasons, ds in ant_cands[:5]:
        out.append(dict(cat="天线", id=prod["id"], cn=prod["cn"], score=sc,
                        picked=bool(ant_rec and ant_rec[1]["id"] == prod["id"]),
                        trace=reasons,
                        dims=ds))
    if design.get("is_custom_ant"):
        out.append(dict(cat="天线", id="ANT-CUSTOM", cn=design["custom_ant"]["cn"],
                        score=None, picked=True,
                        trace=["货架不满足 → 定制（N_gap+1）：" +
                               (ant_rec[2][0] if ant_rec else "")], dims={}))
    # 其余单机：数量与选型理由（build_equipment 已给出 why）
    for r in design.get("equipment", []):
        if r["cat"] == "天线":
            continue
        out.append(dict(cat=r["cat"], id=r["id"], cn=r["cn"], qty=r["qty"],
                        level=r["level"], mass=r["mass"], power=r["power"],
                        picked=True, trace=[r["why"]], dims={}))
    return out


# ================================================================
# 验证：V1~V5
# ================================================================
def validate_decomposition(req0, sysdec, subs, framework, design, subtype_verdict=None,
                           tol=0.05):
    """五重验证：

    V1 指标树自洽：L1 拆解值 vs 引擎 design_all 输出（EIRP/GT/C_sys/N_beam）
    V2 需求闭环：EIRP 达成 ≥ EIRP_req；G/T 达成 ≥ GT_req；余量 ≥ M_target
    V3 约束闭合：引擎 25 条约束 fail 列表为空（或仅信息项）
    V4 平台闭合：m_pay/p_pay ≤ 平台承载；无 _plat_gap
    V5 子体制判决复核：推荐子体制硬门槛全部通过；功率/质量与 design 结果一致方向
    """
    p = sysdec["params"]
    der = p["_derived"]
    res = design["res"]
    s = res["summary"]
    totals = design["totals"]
    checks = []

    def V(vid, name, ok, detail):
        checks.append(dict(id=vid, name=name, ok=bool(ok), detail=detail))

    # V1 指标树自洽
    e1 = abs(res["eirp"]["EIRP"] - der["EIRP_req"]) <= max(tol, 1.0)   # 货架增益重反推允许 1dB 内
    nb_ok = int(to_f(p.get("N_beam", 0))) == der["N_beam"]
    cs_ok = abs(to_f(s.get("C_sys"), 0) - der["N_beam"] * to_f(p.get("B_beam"), 0)
                * to_f(res.get("e2e", {}).get("eta", 0), 2.0) * to_f(p.get("n_pol"), 2) / 1000.0) <= 0.05
    V("V1", "指标树 vs 引擎一致", e1 and nb_ok and cs_ok,
      f"EIRP：拆解 {fmt(der['EIRP_req'],2)} vs 引擎 {fmt(res['eirp']['EIRP'],2)}dBW（差 {fmt(res['eirp']['EIRP']-der['EIRP_req'],2)}）；"
      f"N_beam：拆解 {der['N_beam']} vs 引擎参数 {p.get('N_beam')}；"
      f"C_sys：拆解口径 N_beam×B_beam×η×n_pol={fmt(der['N_beam']*to_f(p.get('B_beam'),0)*2.0*to_f(p.get('n_pol'),2)/1000,2)}Gbps"
      f" vs 引擎 {fmt(s.get('C_sys',0),2)}Gbps（η 按实际 MODCOD {fmt(res.get('e2e',{}).get('eta',0),2)}）")
    # V2 需求闭环
    eirp_done = res["eirp"]["EIRP"] >= der["EIRP_req"] - tol
    gt_done = to_f(res["gt"]["GT"], -999) >= der["GT_req"] - tol
    M_dn = to_f(s.get("M_dn"), 0)
    M_t = to_f(p.get("M_target"), 3.0)
    V("V2", "链路需求闭环", eirp_done and gt_done and M_dn >= M_t - 0.01,
      f"EIRP {fmt(res['eirp']['EIRP'],2)}≥{fmt(der['EIRP_req'],2)}dBW：{'✓' if eirp_done else '✗'}；"
      f"G/T {fmt(res['gt']['GT'],2)}≥{fmt(der['GT_req'],2)}dB/K：{'✓' if gt_done else '✗'}；"
      f"下行余量 {fmt(M_dn,2)}dB ≥ 目标 {fmt(M_t,1)}dB：{'✓' if M_dn>=M_t-0.01 else '✗'}；"
      f"上行余量 {fmt(s.get('M_up',0),2)}dB")
    # V3 约束闭合
    fail = s.get("fail", [])
    V("V3", "25 条约束闭合", len(fail) == 0,
      f"judge {s.get('judge_pass')}/{s.get('judge_total')}；fail={fail if fail else '[]'}；"
      f"warn={s.get('warn', [])}")
    # V4 平台闭合
    plat = design.get("platform")
    gap = p.get("_plat_gap")
    if plat:
        m_ok = totals["m_pay"] <= plat[1]["m_pay"]
        p_ok = totals["p_pay"] <= plat[1]["p_pay"]
        V("V4", "平台承载闭合", m_ok and p_ok and not gap,
          f"{plat[1]['cn']}：质量 {fmt(totals['m_pay'],0)}/{plat[1]['m_pay']}kg "
          f"{'✓' if m_ok else '✗'}；功耗 {fmt(totals['p_pay'],0)}/{plat[1]['p_pay']}W "
          f"{'✓' if p_ok else '✗'}" + (f"；{gap}" if gap else ""))
    else:
        V("V4", "平台承载闭合", False, f"无同轨道平台可选；{gap or ''}")
    # V5 子体制判决复核
    if subtype_verdict and cfg_sub_ok(subtype_verdict):
        rec = subtype_verdict["recommend"]
        st = ARRAY_SUBTYPES.get(rec, {})
        N_el = to_f(cfg_of(design).get("N_el"), 1024)
        P_face = N_el * ARR_P_PER_EL.get(rec, 1.0) + 30.0
        ant_pow = totals["sub_p"].get("P_ant", 0)
        dir_ok = ant_pow >= P_face * 0.8   # 引擎功耗口径含 T/R+控制，方向一致
        rec_row = max((r for r in subtype_verdict["rows"] if r["key"] == rec),
                      key=lambda r: r["score"], default={})
        V("V5", "子体制判决复核", rec is not None and dir_ok,
          f"推荐 {st.get('cn', rec)}（评分 {rec_row.get('score','—')}，硬门槛全过）；"
          f"偏置功耗口径 N_el×P_tr+30={fmt(P_face,0)}W vs 引擎天线分系统 {fmt(ant_pow,0)}W（含控制/校准，方向一致）")
    elif subtype_verdict and not subtype_verdict.get("recommend"):
        dead = [f"{r['key']}（{'、'.join(h[0] for h in r['hard'] if not h[2])}）"
                for r in subtype_verdict["rows"] if not r["ok"]]
        V("V5", "子体制判决复核", True,
          f"判决结论=无可行子体制（全部被硬门槛淘汰）：{'；'.join(dead)}——"
          f"与设计结果一致方向：fail={s.get('fail',[])}（判决先行预警了功率/EIRP 墙，验证判定为『判决有效』）")
    else:
        V("V5", "子体制判决复核", True, "非相控阵或未启用子体制判决（跳过）")

    all_ok = all(c["ok"] for c in checks)
    return dict(checks=checks, all_ok=all_ok,
                n_pass=sum(1 for c in checks if c["ok"]), n_total=len(checks))


def cfg_sub_ok(v):
    return bool(v and v.get("recommend"))


def cfg_of(design):
    return design.get("cfg", {})


# ================================================================
# 主流水线：需求 → 拆解 → 框架 → 选型逻辑 → 验证
# ================================================================
def decompose_pipeline(req_text, cfg, kg, subtype_verdict=None):
    req0 = parse_requirement(req_text, cfg)
    sysdec = decompose_system(req0, kg)
    subs = decompose_subsys(sysdec, req0["cfg"])
    framework = form_framework(sysdec, subs, req0["cfg"])
    design = DE.design_all(req0["cfg"], kg, skip_compare=True)
    trace = trace_selection(design, req0["cfg"])
    verdict = validate_decomposition(req0, sysdec, subs, framework, design,
                                     subtype_verdict=subtype_verdict)
    return dict(req=req0, system=sysdec, subsys=subs, framework=framework,
                design=design, trace=trace, verdict=verdict,
                subtype_verdict=subtype_verdict)
