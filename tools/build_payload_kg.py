# -*- coding: utf-8 -*-
"""构建「载荷方案知识图谱」JSON（扩展 knowledge-graph-2026-09-20.json 的 schema）。

源 schema:
  - ontologies: [{id, name, description, parentId, order}]  （树形）
  - attributes: [{id, ontologyId, name, description, symbol}]
  - constraints: [{id, formula, description, members:[{attributeId, role}]}]

本脚本在保留原 15 个本体节点与 4 条约束的基础上，扩展通信载荷领域：
  天线（相控阵/反射面/反射阵/喇叭/螺旋/光学）、转发器（透明/再生）、
  激光通信终端、智能处理单元（DPU/星载计算机/AI推理单元）、
  DTP（数字信道化/交换矩阵/DAC）、射频单机链（LNA/SSPA/TWTA/OMUX/MPA/环行器/变频器）、
  链路（上行/下行/星间激光）、频段、轨道、平台、运载、转发体制、遥感/导航/科学载荷，
  并新增 16 条通信域约束（EIRP/G_T/FSPL/C_N0/容量/质量功耗/链路余量/激光 ATP/货架缺口等）。

输出: D:/ZWL/文生载荷Workbuddy/output/载荷方案知识图谱_2026-09-20.json
"""
from __future__ import annotations

import json
import datetime
import os

OUT_DIR = r"D:\ZWL\文生载荷Workbuddy\output"
OUT_PATH = os.path.join(OUT_DIR, "载荷方案知识图谱_2026-09-20.json")

# ----------------------------------------------------------------
# ontologies
# ----------------------------------------------------------------
ONT = []


def ont(id, name, desc, parent, order):
    ONT.append({
        "id": id, "name": name, "description": desc,
        "parentId": parent, "order": order,
    })


# ===== 顶层：卫星系统（保留源结构） =====
ont("sat", "卫星系统", "卫星总体，承载任务与平台顶层指标", None, 0)
ont("payload", "有效载荷分系统", "执行卫星核心任务的有效载荷集合（通信/遥感/导航/科学）", "sat", 0)
ont("control", "控制分系统", "负责卫星姿态与轨道控制", "sat", 1)
ont("power", "电源分系统", "卫星电能的产生、存储与分配", "sat", 2)
ont("ttc", "测控分系统", "卫星遥测、遥控与测距", "sat", 3)
ont("platform", "卫星平台", "提供结构/热控/姿轨控/供电等通用支撑的公用平台（货架化程度高）", "sat", 4)
ont("launch_vehicle", "运载火箭", "将卫星送入目标轨道的运输系统，按 GTO/LEO/SSO 运力与整流罩包络选型", "sat", 5)

# ===== 控制分系统子节点（保留） =====
ont("star", "星敏感器", "通过恒星观测提供高精度姿态基准", "control", 0)
ont("obc", "控制计算机", "姿态控制律解算与指令输出", "control", 1)
ont("gyro", "陀螺组件", "惯性姿态角速率测量", "control", 2)

# ===== 电源子节点（保留） =====
ont("panel", "太阳能帆板", "光照期发电单元", "power", 0)
ont("battery", "蓄电池组", "阴影期供电与能量存储", "power", 1)

# ===== 测控子节点（保留） =====
ont("ttc_transponder", "测控应答机", "测控信号的收发与相干转发", "ttc", 0)
ont("ttc_antenna", "测控天线", "测控链路射频信号辐射与接收", "ttc", 1)

# ===== 遥感载荷（保留 camera/dpu/ccd，重挂到 payload 下） =====
ont("camera", "光学相机", "对地观测的高分辨率光学载荷（全色/多光谱/高光谱）", "payload", 0)
ont("ccd", "CCD探测器", "光学相机成像焦平面器件", "camera", 0)
ont("sar", "合成孔径雷达", "主动微波成像载荷，全天时全天候对地观测", "payload", 1)
ont("hyperspectral", "高光谱成像仪", "多光谱段连续成像，用于物质成分反演", "payload", 2)

# ============================================================
# 通信载荷分支（本次扩展重点）
# ============================================================
ont("comm_payload", "通信有效载荷", "卫星通信业务载荷，含天线/转发器/处理/激光等，按转发体制（透明/再生/DTP柔性）组织", "payload", 3)

# ---- 通信天线 ----
ont("comm_antenna", "通信天线", "业务链路射频信号辐射与接收，按体制分为相控阵/反射面/反射阵/喇叭/螺旋/光学等", "comm_payload", 0)
ont("phased_array", "相控阵天线", "由 T/R 组件构成的有源电子扫描阵列，支持多波束/波束跳变/在轨重构，是柔性载荷与手机直连的核心天线体制", "comm_antenna", 0)
ont("reflectarray", "反射阵天线", "由可展开反射阵面构成的天线，兼顾大口径与展开收纳，适用于 Ka 多波束重构", "comm_antenna", 1)
ont("reflector", "反射面天线", "固定或可展开抛物面天线，技术成熟、成本低，适用于单波束或固定多波束覆盖", "comm_antenna", 2)
ont("umbrella", "伞状可展开天线", "大口径伞状网面可展开天线，适用于 L 波段大口径多波束（如 12m 伞状）", "comm_antenna", 3)
ont("horn", "喇叭天线", "全向或准全向喇叭天线，用于低增益广覆盖（如 C 频段全向）", "comm_antenna", 4)
ont("helix", "螺旋天线", "四臂螺旋等圆极化天线，用于测控/导航/低速率链路", "comm_antenna", 5)
ont("optical_antenna", "光学天线", "激光通信终端的卡塞格林/折射式光学收发天线", "comm_antenna", 6)
ont("tr_module", "T/R组件", "相控阵的收发组件，含功放/低噪放/移相器/衰减器，是阵面功耗与热控关键", "phased_array", 0)
ont("beam_former", "波束赋形网络", "实现多波束成形与功率合成的网络（模拟 BFN 或数字 DBF）", "phased_array", 1)

# ---- 转发器 ----
ont("transponder", "通信转发器", "业务信号星上转发处理单元，按体制分为透明转发/再生处理/柔性DTP", "comm_payload", 1)
ont("transparent", "透明转发器", "仅做变频与放大（Bent-Pipe），不解调，技术成熟、时延小、成本低", "transponder", 0)
ont("regenerative", "再生转发器", "星上解调/译码/交换/再调制，噪声不累积、链路余量提升、支持星上路由", "transponder", 1)
ont("dtp", "DTP数字透明处理器", "数字信道化+星上交换矩阵，波束/带宽/功率在轨重构（FlexSat 类柔性载荷核心）", "transponder", 2)

# ---- 射频单机链 ----
ont("rf_chain", "射频单机链", "通信转发器的射频通道单机集合（接收/变频/放大/合成/隔离）", "comm_payload", 2)
ont("lna", "低噪声放大器LNA", "接收前端低噪声放大，决定接收系统噪声温度与 G/T", "rf_chain", 0)
ont("sspa", "固态功放SSPA", "GaN/GaAs 固态功率放大器，高可靠、长寿命，适合批产", "rf_chain", 1)
ont("twta", "行波管功放TWTA", "高效率大功率放大，适合 GEO 大 EIRP 透明转发", "rf_chain", 2)
ont("dconv", "下变频器DCONV", "将上行射频下变频至中频/零中频", "rf_chain", 3)
ont("uconv", "上变频器UCONV", "将中频上变频至下行射频", "rf_chain", 4)
ont("omux", "输出多工器OMUX", "多通道下行滤波与合成，隔离各通道并合至发射天线", "rf_chain", 5)
ont("imux", "输入多工器IMUX", "多通道上行滤波与分路", "rf_chain", 6)
ont("mpa", "多功放矩阵MPA", "N×N 功率池，单管故障可重构，提高功放利用率与可靠性", "rf_chain", 7)
ont("circulator", "环行器/隔离器", "收发隔离与单向传输保护，提升功放稳定性", "rf_chain", 8)
ont("switch_matrix", "微波开关矩阵", "SP8T 等开关矩阵，实现通道切换与重构", "rf_chain", 9)

# ---- 激光通信 ----
ont("laser_com", "激光通信终端", "星间/星地激光高速链路终端（ATP 捕获跟踪瞄准 + DPSK/OOK 调制）", "comm_payload", 3)
ont("atp", "ATP捕获跟踪瞄准", "激光链路的粗跟踪+精跟踪+瞄准子系统，决定建链捕获概率与跟踪精度", "laser_com", 0)
ont("optical_trm", "光收发模块", "激光器/探测器/DPSK调制解调，决定激光链路速率与灵敏度", "laser_com", 1)

# ---- 智能处理单元 ----
ont("intelligent_processing", "智能处理单元", "星上在轨处理与智能计算单元，含数据压缩/AI推理/在轨重构调度", "comm_payload", 4)
ont("dpu", "数据处理单元DPU", "载荷数据在轨处理、压缩、缓存与下行调度", "intelligent_processing", 0)
ont("obc_payload", "星载计算机", "载荷级控制与管理计算机，负责载荷调度/遥控遥测/故障管理", "intelligent_processing", 1)
ont("ai_unit", "AI推理单元", "星上 AI 加速单元，支持目标检测/变化检测/云检测/在轨智能筛选", "intelligent_processing", 2)
ont("reconfig_controller", "在轨重构控制器", "柔性载荷在轨重构调度（波束图样/带宽/功率/路由的动态配置）", "intelligent_processing", 3)

# ---- 链路（通信链路抽象） ----
ont("link", "通信链路", "星地/星间射频或激光链路的抽象，承载 EIRP/G_T/带宽/余量等预算指标", "comm_payload", 5)
ont("uplink", "上行链路", "关口站→卫星上行链路（雨衰按上行频段计）", "link", 0)
ont("downlink", "下行链路", "卫星→用户/关口站下行链路（EIRP 由星上决定）", "link", 1)
ont("isl_laser", "星间激光链路", "星间激光高速链路（ISL），用于星座组网与回传", "link", 2)
ont("isl_rf", "星间射频链路", "星间射频链路（Ka/毫米波），用于星座组网", "link", 3)

# ---- 频段/轨道/体制（选型约束基础） ----
ont("frequency_band", "频段", "业务频段（L/S/C/X/Ku/Ka/Q/V/激光），决定雨衰、天线口径、器件工艺与频率指配", "comm_payload", 6)
ont("orbit", "轨道类型", "LEO/MEO/GEO/SSO/HEO，决定斜距、覆盖、时延与平台/运载选型", "sat", 6)
ont("arch_template", "转发体制", "透明转发/再生处理/DTP 柔性，决定载荷架构与单机链组成", "comm_payload", 7)

# ---- 导航/科学载荷 ----
ont("nav_payload", "导航载荷", "导航信号生成与放大、导航天线、原子钟（B1C/B2a/L1/L5）", "payload", 4)
ont("sci_payload", "科学探测载荷", "大气掩星/重力场/磁强计等科学探测载荷", "payload", 5)

# ============================================================
# attributes
# ============================================================
ATTR = []


def attr(id, onto, name, desc, symbol):
    ATTR.append({
        "id": id, "ontologyId": onto, "name": name,
        "description": desc, "symbol": symbol,
    })


# ---- 保留源属性 ----
attr("a-star-fov", "star", "视场角", "星敏感器可观测天区的角度范围，影响可用恒星数量", "FOV")
attr("a-star-acc", "star", "测量精度", "星敏感器输出的姿态测量误差（3σ）", "σ_m")
attr("a-star-update", "star", "更新速率", "姿态数据输出频率（Hz）", "f_hr")
attr("a-obc-point", "obc", "姿态控制精度", "卫星稳定后的姿态偏差（3σ）", "σ_c")
attr("a-obc-stab", "obc", "姿态稳定度", "姿态角速率波动范围（°/s）", "ω_s")
attr("a-cam-res", "camera", "地面分辨率", "图像可分辨的最小地面距离（m）", "GSD")
attr("a-cam-swath", "camera", "幅宽", "单景图像覆盖的地面宽度（km）", "W_sw")
attr("a-panel-power", "panel", "输出功率", "光照期帆板输出电功率（W）", "P_pv")
attr("a-bat-cap", "battery", "容量", "蓄电池组可用储能（Wh）", "E_b")
attr("a-bat-dod", "battery", "放电深度", "蓄电池组单圈放电比例（%）", "DOD")
attr("a-ttc-ant-gain", "ttc_antenna", "增益", "测控天线方向性增益（dBi）", "G_t")
attr("a-control-acc", "control", "姿态测量精度", "分系统级姿态测量精度指标", "σ_ctl")
attr("a-ccd-pixel", "ccd", "像元尺寸", "CCD单个像元的物理尺寸（μm）", "d_px")

# ---- 通信天线属性 ----
attr("a-comm-ant-eirp", "comm_antenna", "EIRP能力", "天线等效全向辐射功率能力（dBW），= P_out + G_ant − L_feed", "EIRP")
attr("a-comm-ant-gt", "comm_antenna", "G/T品质因数", "接收增益与系统噪声温度之比（dB/K）", "G/T")
attr("a-comm-ant-gain", "comm_antenna", "天线增益", "天线方向性增益（dBi）", "G_ant")
attr("a-comm-ant-beam", "comm_antenna", "波束数", "可同时形成的独立波束数量", "N_beam")
attr("a-comm-ant-mass", "comm_antenna", "质量", "天线系统质量（kg）", "m_ant")
attr("a-comm-ant-power", "comm_antenna", "功耗", "天线系统总功耗（W）", "P_ant")
attr("a-comm-ant-mode", "comm_antenna", "工作模式", "单波束/多波束/波束跳变/在轨重构", "Mode")
attr("a-comm-ant-aperture", "comm_antenna", "口径/阵面尺寸", "反射面口径或阵面尺寸（m）", "D_ap")

# ---- 相控阵属性 ----
attr("a-pa-elements", "phased_array", "阵元数", "相控阵 T/R 组件数量", "N_el")
attr("a-pa-scan", "phased_array", "扫描角", "电子扫描覆盖范围（±°）", "θ_scan")
attr("a-pa-reconfig", "phased_array", "在轨重构能力", "波束图样/带宽/功率在轨重构支持度（0-1）", "R_pa")

# ---- 反射阵/反射面属性 ----
attr("a-ra-aperture", "reflectarray", "展开口径", "展开后反射阵口径（m）", "D_ra")
attr("a-refl-surface", "reflector", "面精度", "反射面表面 RMS 误差（mm），需 ≤ λ/32", "δ_surf")

# ---- T/R 组件属性 ----
attr("a-tr-power", "tr_module", "单组件功耗", "单个 T/R 组件功耗（W）", "P_tr")
attr("a-tr-temp", "tr_module", "结温", "T/R 组件结温（℃），需 ≤ 125℃", "T_j")

# ---- 转发器属性 ----
attr("a-trp-gain", "transponder", "转发增益", "转发器总增益（dB）", "G_trp")
attr("a-trp-nf", "transponder", "噪声系数", "接收通道噪声系数（dB），影响 G/T", "NF")
attr("a-trp-bw", "transponder", "转发带宽", "单转发器带宽（MHz）", "B_trp")
attr("a-trp-mass", "transponder", "质量", "转发器质量（kg）", "m_trp")
attr("a-trp-power", "transponder", "功耗", "转发器功耗（W）", "P_trp")

# ---- 透明转发属性 ----
attr("a-trans-delay", "transparent", "转发时延", "透明转发星上处理时延（ns），近零", "τ_trans")

# ---- 再生转发属性 ----
attr("a-regen-gain", "regenerative", "链路余量增益", "再生相比透明可提升链路余量（dB）", "ΔM_reg")
attr("a-regen-delay", "regenerative", "处理时延", "星上解调译码再调制时延（ms）", "τ_reg")

# ---- DTP 属性 ----
attr("a-dtp-sub-bw", "dtp", "子带带宽", "数字信道化最小子带带宽（MHz）", "B_sub")
attr("a-dtp-switch", "dtp", "交换容量", "星上交换矩阵总容量（Gbps）", "C_sw")
attr("a-dtp-channels", "dtp", "信道数", "数字信道化通道数", "N_ch")
attr("a-dtp-mass", "dtp", "质量", "DTP 质量（kg）", "m_dtp")
attr("a-dtp-power", "dtp", "功耗", "DTP 功耗（W）", "P_dtp")

# ---- 射频单机属性 ----
attr("a-lna-gain", "lna", "增益", "LNA 增益（dB）", "G_lna")
attr("a-lna-nf", "lna", "噪声系数", "LNA 噪声系数（dB），决定接收系统温度", "NF_lna")
attr("a-sspa-pout", "sspa", "输出功率", "SSPA 饱和输出功率（W）", "P_sspa")
attr("a-sspa-eff", "sspa", "效率", "SSPA 功率附加效率（%）", "η_sspa")
attr("a-twta-pout", "twta", "输出功率", "TWTA 饱和输出功率（W）", "P_twta")
attr("a-twta-eff", "twta", "效率", "TWTA 效率（%）", "η_twta")
attr("a-omux-channels", "omux", "通道数", "OMUX 通道数", "N_omux")
attr("a-mpa-channels", "mpa", "矩阵规模", "MPA N×N 矩阵规模", "N_mpa")

# ---- 激光通信属性 ----
attr("a-laser-rate", "laser_com", "链路速率", "激光通信速率（Gbps）", "R_laser")
attr("a-laser-eirp", "laser_com", "发射EIRP", "激光发射等效全向辐射功率（dBW）", "EIRP_opt")
attr("a-laser-gt", "laser_com", "G/T", "激光接收品质因数（dB/K 等效）", "GT_opt")
attr("a-atp-acq", "atp", "捕获概率", "ATP 建链捕获概率（%），需 ≥95%", "P_acq")
attr("a-atp-track", "atp", "跟踪精度", "ATP 精跟踪精度（μrad），需 ≤1μrad", "σ_track")
attr("a-opt-trm-sens", "optical_trm", "接收灵敏度", "光接收灵敏度（dBm），DPSK 优于 OOK 约6dB", "S_opt")

# ---- 智能处理单元属性 ----
attr("a-dpu-rate", "dpu", "处理速率", "DPU 在轨处理吞吐（Mbps）", "R_dpu")
attr("a-dpu-compress", "dpu", "压缩比", "数据压缩比", "CR")
attr("a-obcp-mips", "obc_payload", "处理能力", "星载计算机处理能力（MIPS）", "MIPS")
attr("a-ai-tops", "ai_unit", "AI算力", "星上 AI 推理算力（TOPS）", "AI_TOPS")
attr("a-reconfig-time", "reconfig_controller", "重构时间", "在轨重构切换时间（s）", "t_rec")

# ---- 链路属性 ----
attr("a-link-fspl", "link", "自由空间损耗", "FSPL = 20lg(d)+20lg(f)−147.55（dB）", "L_fs")
attr("a-link-rain", "link", "雨衰", "降雨衰减（dB），按频段/仰角/可用性计", "A_rain")
attr("a-link-cn0", "link", "载噪比密度", "C/N0 = EIRP − FSPL − ΣL + G/T − k（dBHz）", "CN0")
attr("a-link-cn", "link", "载噪比", "C/N = C/N0 − 10lg(B)（dB）", "CN")
attr("a-link-margin", "link", "链路余量", "M = C/N − (C/N)_req（dB），需 ≥3dB", "M")
attr("a-link-cap", "link", "链路容量", "C = B × η（Mbps）", "C_link")
attr("a-link-dist", "link", "斜距", "星地/星间斜距（km）", "d_slant")
attr("a-link-bw", "link", "带宽", "链路占用带宽（MHz）", "B_link")

# ---- 频段/轨道/体制属性 ----
attr("a-band-fup", "frequency_band", "上行频率", "上行中心频率（GHz）", "f_up")
attr("a-band-fdown", "frequency_band", "下行频率", "下行中心频率（GHz）", "f_down")
attr("a-band-rain", "frequency_band", "典型雨衰", "0.01%时间超越概率典型雨衰（dB）", "A_band")
attr("a-orbit-alt", "orbit", "轨道高度", "轨道高度（km）", "H_orb")
attr("a-orbit-period", "orbit", "轨道周期", "轨道周期（min）", "T_orb")
attr("a-arch-flex", "arch_template", "体制灵活度", "在轨重构/灵活性等级（透明<再生<DTP）", "F_arch")

# ---- 平台属性 ----
attr("a-plat-mass-cap", "platform", "载荷承载质量", "平台可承载载荷质量（kg）", "M_plat")
attr("a-plat-power-cap", "platform", "载荷供电功率", "平台可提供载荷功率（W）", "P_plat")
attr("a-plat-sat-mass", "platform", "整星质量", "整星发射质量（kg）", "M_sat")
attr("a-plat-envelope", "platform", "包络尺寸", "平台包络/整流罩适配尺寸（m）", "D_env")
attr("a-plat-life", "platform", "设计寿命", "平台设计寿命（年）", "L_life")

# ---- 运载属性 ----
attr("a-lv-gto", "launch_vehicle", "GTO运力", "GTO 转移轨道运力（kg）", "C_gto")
attr("a-lv-leo", "launch_vehicle", "LEO运力", "LEO 运力（kg）", "C_leo")
attr("a-lv-sso", "launch_vehicle", "SSO运力", "SSO 运力（kg）", "C_sso")
attr("a-lv-fairing", "launch_vehicle", "整流罩直径", "整流罩直径（m）", "D_fair")

# ---- 导航载荷属性 ----
attr("a-nav-eirp", "nav_payload", "导航EIRP", "导航信号 EIRP（dBW）", "EIRP_nav")
attr("a-nav-uere", "nav_payload", "用户等效距离误差", "UERE（m）", "UERE")
attr("a-nav-clock", "nav_payload", "原子钟守时精度", "原子钟频率稳定度/守时精度", "σ_clk")

# ---- 科学载荷属性 ----
attr("a-sci-sens", "sci_payload", "探测灵敏度", "科学探测灵敏度/精度", "S_sci")

# ---- SAR/高光谱属性 ----
attr("a-sar-res", "sar", "空间分辨率", "SAR 距离/方位分辨率（m）", "GSD_sar")
attr("a-sar-swath", "sar", "幅宽", "SAR 测绘幅宽（km）", "W_sar")
attr("a-hyp-bands", "hyperspectral", "光谱通道数", "高光谱连续光谱通道数", "N_band")

# ---- 方案级（顶层）属性：用于货架/质量/功耗汇总约束 ----
attr("a-scheme-mass", "comm_payload", "载荷总质量", "通信载荷总质量（kg）", "M_pay")
attr("a-scheme-power", "comm_payload", "载荷总功耗", "通信载荷总功耗（W）", "P_pay")
attr("a-scheme-gap", "comm_payload", "货架缺口数", "需定制（非货架）单机数量，目标为0", "N_gap")
attr("a-scheme-heritage", "comm_payload", "货架水平", "方案整体货架继承水平（1定制~4飞行继承货架）", "H_scheme")

# ============================================================
# constraints
# ============================================================
CONS = []


def con(id, formula, desc, *members):
    CONS.append({
        "id": id, "formula": formula, "description": desc,
        "members": [{"attributeId": a, "role": r} for a, r in members],
    })


# ---- 保留源约束 c-1 ~ c-4 ----
con("c-1", "σ_c ≤ σ_m / 3",
    "姿态控制精度应优于测量精度的三分之一，保证测量噪声不被放大",
    ("a-star-acc", "σ_m"), ("a-obc-point", "σ_c"))
con("c-2", "P_pv ≥ E_b × DOD / T_e",
    "光照期输出功率需覆盖整星阴影期功耗（E_b 为蓄电池容量，DOD 放电深度，T_e 阴影时长）",
    ("a-panel-power", "P_pv"), ("a-bat-cap", "E_b"), ("a-bat-dod", "DOD"))
con("c-3", "σ_m + ω_s ≤ 0.05°",
    "星敏感器测量精度与姿态稳定度共同决定的姿态确定误差上限",
    ("a-star-acc", "σ_m"), ("a-obc-stab", "ω_s"))
con("c-4", "GSD = d_px × H_orb / f_cam",
    "地面分辨率由像元尺寸、轨道高度与相机焦距共同约束，其中像元尺寸为耦合输入",
    ("a-cam-res", "GSD"), ("a-ccd-pixel", "d_px"))

# ---- 新增：通信载荷域约束 c-5 ~ c-20 ----
con("c-5", "EIRP = P_out + G_ant − L_feed",
    "等效全向辐射功率由功放输出功率、天线增益与馈电损耗决定（dB 域加减），是天线五要素选型第一维（权重30）",
    ("a-comm-ant-eirp", "EIRP"), ("a-comm-ant-gain", "G_ant"),
    ("a-sspa-pout", "P_out"), ("a-twta-pout", "P_out"))
con("c-6", "G/T = G_ant − 10lg(T_sys)",
    "接收品质因数由接收天线增益与系统噪声温度决定；T_sys 主要由 LNA 噪声系数主导，是天线五要素第二维（权重25）",
    ("a-comm-ant-gt", "G/T"), ("a-comm-ant-gain", "G_ant"), ("a-lna-nf", "NF_lna"))
con("c-7", "G_pa = 10lg(N_el × η) + G_el",
    "相控阵增益由阵元数、阵面效率与单元增益决定（忽略扫描损耗），用于反推满足 EIRP 所需阵元数",
    ("a-comm-ant-gain", "G_ant"), ("a-pa-elements", "N_el"))
con("c-8", "G_refl = 10lg(η × (πD/λ)²)",
    "反射面天线增益由口径、频率与口面效率决定，用于按 EIRP 反推所需口径",
    ("a-comm-ant-gain", "G_ant"), ("a-comm-ant-aperture", "D_ap"),
    ("a-band-fdown", "f_down"))
con("c-9", "L_fs = 20lg(d) + 20lg(f) − 147.55",
    "自由空间损耗由斜距与频率决定（d:m, f:Hz），是链路预算的基础项",
    ("a-link-fspl", "L_fs"), ("a-link-dist", "d_slant"), ("a-band-fdown", "f_down"))
con("c-10", "C/N0 = EIRP − L_fs − ΣL + G/T − k",
    "载噪比密度由发射 EIRP、自由空间损耗、各类损耗（雨衰/指向/极化/大气/实现）、接收 G/T 与玻尔兹曼常数决定（k=−228.6 dBW/Hz/K）",
    ("a-link-cn0", "CN0"), ("a-comm-ant-eirp", "EIRP"),
    ("a-link-fspl", "L_fs"), ("a-link-rain", "A_rain"), ("a-comm-ant-gt", "G/T"))
con("c-11", "C/N = C/N0 − 10lg(B)",
    "载噪比由载噪比密度减去带宽归一项得到（B:Hz）",
    ("a-link-cn", "CN"), ("a-link-cn0", "CN0"), ("a-link-bw", "B_link"))
con("c-12", "M = C/N − (C/N)_req ≥ 3 dB",
    "链路余量判据：实际 C/N 减去所选调制编码体制的门限，须 ≥3dB 方可闭合，否则触发回环（降阶/增 EIRP/减带宽/放宽可用性）",
    ("a-link-margin", "M"), ("a-link-cn", "CN"))
con("c-13", "C_link = B × η",
    "链路容量由带宽与频谱效率决定（η 由 C/N 自适应选定的 MODCOD 给出，DVBS2X 阶梯：QPSK 1.79~32APSK 4.45 bps/Hz）",
    ("a-link-cap", "C_link"), ("a-link-bw", "B_link"))
con("c-14", "C_sw ≥ N_beam × B_beam × η_reuse",
    "DTP 交换容量须不小于波束数×单波束带宽×频率复用增益，否则星上交换成为容量瓶颈",
    ("a-dtp-switch", "C_sw"), ("a-comm-ant-beam", "N_beam"))
con("c-15", "M_pay ≤ M_plat 且 P_pay ≤ P_plat",
    "载荷总质量与总功耗须在平台承载与供电能力内（平台可行性硬约束，超限则换大平台或减配载荷）",
    ("a-scheme-mass", "M_pay"), ("a-plat-mass-cap", "M_plat"),
    ("a-scheme-power", "P_pay"), ("a-plat-power-cap", "P_plat"))
con("c-16", "M_sat ≤ C_orbit(launch_vehicle)",
    "整星发射质量须不大于所选运载对应轨道（GTO/LEO/SSO）的运力，且包络须适配整流罩直径",
    ("a-plat-sat-mass", "M_sat"), ("a-lv-gto", "C_gto"),
    ("a-lv-leo", "C_leo"), ("a-lv-sso", "C_sso"), ("a-plat-envelope", "D_env"), ("a-lv-fairing", "D_fair"))
con("c-17", "P_acq ≥ 95% 且 σ_track ≤ 1 μrad",
    "激光通信 ATP 捕获概率须 ≥95%、精跟踪精度须 ≤1μrad，方可维持稳定激光链路",
    ("a-atp-acq", "P_acq"), ("a-atp-track", "σ_track"))
con("c-18", "R_laser ≤ C_isl(G/T_opt, EIRP_opt, L_fs_opt)",
    "激光链路速率受发射 EIRP、接收 G/T 与光学自由空间损耗约束（DPSK 体制门限约8dB，灵敏度优于 OOK 约6dB）",
    ("a-laser-rate", "R_laser"), ("a-laser-eirp", "EIRP_opt"), ("a-laser-gt", "GT_opt"))
con("c-19", "δ_surf ≤ λ/32",
    "反射面/反射阵天线表面 RMS 精度须优于工作波长的 1/32（Ka 约0.27mm），否则增益下降、旁瓣抬升",
    ("a-refl-surface", "δ_surf"), ("a-band-fdown", "f_down"))
con("c-20", "N_gap → 0 且 H_scheme → 4",
    "货架优先原则：定制缺口数 N_gap 目标为0，方案整体货架水平 H_scheme 优先取飞行继承货架(4)>飞行继承(3)>货架(2)>定制(1)",
    ("a-scheme-gap", "N_gap"), ("a-scheme-heritage", "H_scheme"))

# ============================================================
# 组装 + 校验 + 落盘
# ============================================================

graph = {
    "version": 2,
    "exportedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "name": "载荷方案知识图谱",
    "description": "在卫星系统知识图谱基础上扩展的载荷方案领域图谱，覆盖通信天线（相控阵/反射阵/反射面/伞状/喇叭/螺旋/光学）、转发器（透明/再生/DTP柔性）、激光通信终端、智能处理单元（DPU/星载计算机/AI推理/在轨重构）、射频单机链（LNA/SSPA/TWTA/OMUX/MPA等）、通信链路（上行/下行/星间激光/星间射频）、频段/轨道/转发体制、平台/运载，以及遥感/导航/科学载荷。约束含 EIRP/G_T/FSPL/C_N0/链路余量/容量/DTP交换/质量功耗/激光ATP/货架优先等工程判据。",
    "sourceFile": "knowledge-graph-2026-09-20.json",
    "ontologies": ONT,
    "attributes": ATTR,
    "constraints": CONS,
}

# ---- 一致性校验 ----
ont_ids = {o["id"] for o in ONT}
attr_ids = {a["id"] for a in ATTR}
errors = []

# 1) ontology parentId 必须存在
for o in ONT:
    if o["parentId"] is not None and o["parentId"] not in ont_ids:
        errors.append(f"ontology {o['id']} 的 parentId {o['parentId']} 不存在")

# 2) attribute.ontologyId 必须存在
for a in ATTR:
    if a["ontologyId"] not in ont_ids:
        errors.append(f"attribute {a['id']} 的 ontologyId {a['ontologyId']} 不存在")

# 3) constraint.members.attributeId 必须存在
for c in CONS:
    for m in c["members"]:
        if m["attributeId"] not in attr_ids:
            errors.append(f"constraint {c['id']} 引用了不存在的 attributeId {m['attributeId']}")

# 4) id 唯一性
if len(ont_ids) != len(ONT):
    errors.append("ontology id 存在重复")
if len(attr_ids) != len(ATTR):
    errors.append("attribute id 存在重复")
cons_ids = [c["id"] for c in CONS]
if len(set(cons_ids)) != len(cons_ids):
    errors.append("constraint id 存在重复")

# 5) 必备字段非空
for o in ONT:
    if not o["name"] or not o["id"]:
        errors.append(f"ontology {o} 缺少 id/name")
for a in ATTR:
    if not a["symbol"]:
        errors.append(f"attribute {a['id']} 缺少 symbol")

if errors:
    print("校验失败：")
    for e in errors:
        print("  -", e)
    raise SystemExit(1)

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(graph, f, ensure_ascii=False, indent=2)

# ---- 统计 ----
print("✅ 校验通过，已写出:", OUT_PATH)
print(f"   ontologies: {len(ONT)} 个")
print(f"   attributes: {len(ATTR)} 个")
print(f"   constraints: {len(CONS)} 条（保留源4条 + 新增{len(CONS)-4}条）")

# 统计通信载荷分支节点
comm_branch = [o["id"] for o in ONT if o["id"] in {
    "comm_payload", "comm_antenna", "phased_array", "reflectarray", "reflector",
    "umbrella", "horn", "helix", "optical_antenna", "tr_module", "beam_former",
    "transponder", "transparent", "regenerative", "dtp",
    "rf_chain", "lna", "sspa", "twta", "dconv", "uconv", "omux", "imux",
    "mpa", "circulator", "switch_matrix",
    "laser_com", "atp", "optical_trm",
    "intelligent_processing", "dpu", "obc_payload", "ai_unit", "reconfig_controller",
    "link", "uplink", "downlink", "isl_laser", "isl_rf",
    "frequency_band", "arch_template",
}]
print(f"   通信载荷领域节点: {len(comm_branch)} 个")

# 关键需求覆盖检查
required = ["天线", "转发器", "激光", "智能处理单元", "DTP", "相控阵"]
name_blob = json.dumps([o["name"] + o["description"] for o in ONT], ensure_ascii=False)
covered = [k for k in required if k in name_blob]
print(f"   用户需求关键词覆盖: {len(covered)}/{len(required)} -> {covered}")
missing = [k for k in required if k not in name_blob]
if missing:
    print("   ⚠️ 未覆盖关键词:", missing)
else:
    print("   ✅ 全部需求关键词已覆盖")
