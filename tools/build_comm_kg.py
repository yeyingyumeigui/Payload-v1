# -*- coding: utf-8 -*-
"""构建「通信有效载荷知识图谱」JSON（v3，纯载荷视角，层级化分组）。

用户要求：
  1) 不含卫星系统，只针对通信有效载荷
  2) 层级清晰 → 分系统下设「体制 / 单机分类 / 链路」三个分组层，避免同级平铺 20+ 节点
  3) 一级分系统：天线分系统、转发器分系统、激光通信分系统、智能处理分系统
  4) 射频链路、通信链路下沉到各分系统内部（category = 链路）
  5) 考虑各分系统和链路里面的单机 → 每条链路/体制用 chain 给出「有序组成单机」，
     并派生为 relations 图边（type = 链路组成单机 / 体制组成单机）

层级（最大 L3）：
  L0 通信有效载荷
  L1 天线分系统 / 转发器分系统 / 激光通信分系统 / 智能处理分系统 / 载荷公共基础
  L2 体制分组 / 单机分组 / 链路分组
  L3 具体体制、具体单机、具体链路

输出: output/通信有效载荷知识图谱_2026-09-20.json
"""
from __future__ import annotations

import json
import os
import datetime

OUT_DIR = r"D:\ZWL\文生载荷Workbuddy\output"
OUT_PATH = os.path.join(OUT_DIR, "通信有效载荷知识图谱_2026-09-20.json")
RPT_PATH = os.path.join(OUT_DIR, "_comm_kg_verify_report.txt")

ONT, ATTR, CONS, REL = [], [], [], []
_order: dict = {}


def ont(id, name, desc, parent, cat, chain=None):
    key = parent or "__root__"
    n = _order.get(key, 0)
    _order[key] = n + 1
    d = {"id": id, "name": name, "description": desc,
         "parentId": parent, "order": n, "category": cat}
    if chain:
        d["chain"] = list(chain)
    ONT.append(d)


def attr(id, onto, name, desc, symbol):
    ATTR.append({"id": id, "ontologyId": onto, "name": name,
                 "description": desc, "symbol": symbol})


def con(id, formula, desc, *members):
    CONS.append({"id": id, "formula": formula, "description": desc,
                 "members": [{"attributeId": a, "role": r} for a, r in members]})


def rel(id, frm, to, typ, desc=""):
    REL.append({"id": id, "from": frm, "to": to, "type": typ, "description": desc})


# ================================================================
# L0 通信有效载荷（根）
# ================================================================
ont("comm_payload", "通信有效载荷",
    "卫星通信业务载荷总体，由天线分系统、转发器分系统、激光通信分系统、智能处理分系统四部分组成，"
    "按转发体制（透明/再生/DTP柔性）组织射频链路与通信链路，承载 EIRP、G/T、容量、质量、功耗等顶层指标",
    None, "载荷总体")

# ================================================================
# L1-1 天线分系统
# ================================================================
ont("ant_subsys", "天线分系统",
    "负责业务链路射频能量的辐射与接收，决定 EIRP 与 G/T 两大核心指标。"
    "下设天线体制、有源阵面单机、馈电与无源单机、展开与指向单机、控制与校准单机、天线射频链路六组",
    "comm_payload", "分系统")

# ---- L2 分组：天线体制 ----
ont("ant_types", "天线体制",
    "按工作原理划分的天线类型，选型由 EIRP/G/T/重量/功耗/工作模式五要素与频段共同决定",
    "ant_subsys", "分组")
ont("phased_array", "相控阵天线",
    "由大量 T/R 组件构成的有源电子扫描阵列，支持多波束、波束跳变与在轨重构，"
    "是柔性载荷、高通量 HTS 与手机直连（D2D）的核心体制；增益 G=10lg(N_el×η)+G_el",
    "ant_types", "体制")
ont("reflectarray", "反射阵天线",
    "可展开反射阵面天线，兼顾大口径增益与发射收纳体积，适用于 Ka 频段多波束在轨重构",
    "ant_types", "体制")
ont("reflector", "反射面天线",
    "固定抛物面天线（碳纤维/铝蜂窝），技术成熟、成本低、口面效率高，适用于单波束或固定多波束覆盖",
    "ant_types", "体制")
ont("umbrella", "伞状可展开天线",
    "大口径伞状网面可展开天线（如 Φ12m），适用于 L/S 波段大口径多波束与移动业务",
    "ant_types", "体制")
ont("horn", "喇叭天线",
    "全向或准全向喇叭天线，增益低、覆盖广，用于低速率广覆盖业务或全向辅助链路",
    "ant_types", "体制")
ont("helix", "螺旋天线",
    "四臂螺旋等圆极化天线，体积小、半球覆盖，用于低速率链路、导航增强与物联网业务",
    "ant_types", "体制")

# ---- L2 分组：天线单机 ----
ont("ant_active", "有源阵面单机",
    "相控阵有源通道单机，决定阵面增益、扫描能力、功耗与热控（结温 ≤125℃）",
    "ant_subsys", "分组")
ont("tr_module", "T/R组件",
    "相控阵收发组件（功放+低噪放+移相器+衰减器+开关），是阵面功耗、热控与成本的主要来源；"
    "阵面总功耗 ≈ N_el × P_tr",
    "ant_active", "单机")
ont("phase_shifter", "移相器",
    "控制阵元激励相位实现波束扫描与赋形，位数 n 决定波束指向量化误差 ≈ 180/2^n 度",
    "ant_active", "单机")
ont("var_atten", "可变衰减器",
    "幅度加权与功率电平控制，用于旁瓣抑制与功放线性工作点设置", "ant_active", "单机")
ont("beam_former", "波束赋形网络",
    "实现多波束成形与功率合成，分模拟波束赋形（ABF）与数字波束赋形（DBF）；通道数 = 波束数",
    "ant_active", "单机")
ont("power_combiner", "功率合成器",
    "多路功放输出功率合成（径向/波导/空间合成），合成效率直接影响星上 EIRP",
    "ant_active", "单机")

ont("ant_passive", "馈电与无源单机",
    "馈电、隔离、滤波与波束端口等无源单机，决定馈电损耗、收发隔离与频率规划",
    "ant_subsys", "分组")
ont("feed", "馈源与馈电网络",
    "反射面/反射阵天线的馈源喇叭与馈电网络，决定照射效率、交叉极化与轴比",
    "ant_passive", "单机")
ont("circulator", "环行器/隔离器",
    "实现收发共用天线的隔离与单向传输保护，收发隔离度 ≥100dB，保障功放稳定不自激",
    "ant_passive", "单机")
ont("tx_filter", "发射滤波器",
    "抑制发射谐波与带外杂散，满足 ITU 频率指配与带外发射限值", "ant_passive", "单机")
ont("rx_filter", "接收滤波器",
    "抑制带外干扰与镜像频率，保护 LNA 并改善接收系统噪声温度", "ant_passive", "单机")
ont("rx_switch", "接收通道开关",
    "接收通道冗余切换与主备倒换，实现 LNA/通道级 A/B 备份", "ant_passive", "单机")
ont("beam_port", "波束端口",
    "多波束天线的波束输入/输出端口，端口数决定可同时工作的波束数", "ant_passive", "单机")
ont("beam_switch", "波束切换开关矩阵",
    "波束跳变体制下波束端口与转发通道的动态连接切换", "ant_passive", "单机")

ont("ant_mech", "展开与指向单机",
    "大口径天线的展开锁定与机械指向单机，展开到位精度决定面精度（≤λ/32）",
    "ant_subsys", "分组")
ont("deploy", "天线展开机构",
    "大口径天线的展开/锁定机构（铰链、弹簧、压紧释放装置），展开到位精度决定面精度",
    "ant_mech", "单机")
ont("pointing", "天线指向机构",
    "机械单轴/双轴转台指向，配合相控阵电扫扩展覆盖范围，步距决定指向量化误差",
    "ant_mech", "单机")

ont("ant_ctrl_grp", "控制与校准单机",
    "天线驱动控制、波束校准与在轨重构指令执行单机", "ant_subsys", "分组")
ont("ant_ctrl", "天线控制单元ACU",
    "天线驱动控制、展开时序管理、波束指向标定与在轨重构指令执行", "ant_ctrl_grp", "单机")
ont("cal_network", "波束校准网络",
    "阵面幅相校准与波束指向标定的内部校准通道，保障多波束赋形精度与旁瓣指标",
    "ant_ctrl_grp", "单机")

# ---- L2 分组：天线射频链路 ----
ont("ant_paths", "天线射频链路",
    "天线分系统内部的射频通道链路，按发射/接收/波束调度三条组织，每条链路给出有序组成单机",
    "ant_subsys", "分组")
ont("ant_tx_path", "天线发射通道",
    "下行方向射频链路，决定星上 EIRP；通道插损计入 EIRP 扣减",
    "ant_paths", "链路",
    chain=["power_combiner", "phase_shifter", "var_atten", "tx_filter", "circulator", "feed"])
ont("ant_rx_path", "天线接收通道",
    "上行方向射频链路，决定接收系统噪声温度与 G/T",
    "ant_paths", "链路",
    chain=["feed", "rx_filter", "circulator", "rx_switch", "tr_module"])
ont("beam_link", "波束链路",
    "波束成形与波束调度链路：赋形网络→波束端口→切换矩阵→校准闭环→ACU 控制",
    "ant_paths", "链路",
    chain=["beam_former", "beam_port", "beam_switch", "cal_network", "ant_ctrl"])

# ================================================================
# L1-2 转发器分系统
# ================================================================
ont("trp_subsys", "转发器分系统",
    "业务信号的星上转发与处理，含透明转发、再生处理、DTP 柔性三种体制；"
    "下设转发体制、接收通道单机、功率放大单机、变频与频率单机、滤波与均衡单机、"
    "交换与数字化单机、再生基带单机、通信链路八组",
    "comm_payload", "分系统")

# ---- L2 分组：转发体制 ----
ont("trp_arch", "转发体制",
    "星上信号处理方式，决定链路余量、灵活度、功耗与研制风险；三种体制各有明确适用场景",
    "trp_subsys", "分组")
ont("transparent", "透明转发器",
    "Bent-Pipe 体制：星上仅做滤波、变频与放大，不解调。技术成熟度最高、成本最低、时延最小；"
    "但噪声全链路累积、波束固定、无星上交换能力。适用固定业务广播与传统 VSAT",
    "trp_arch", "体制",
    chain=["lna", "dconv", "imux", "equalizer", "twta", "omux", "uconv", "switch_matrix"])
ont("regenerative", "再生转发器",
    "星上解调/译码/交换/再调制，噪声不累积，链路余量可提升 3~6dB，支持星上路由与抗干扰；"
    "但复杂度高、功耗大、体制升级需换星。适用军事抗干扰与星上组网",
    "trp_arch", "体制",
    chain=["lna", "dconv", "demod", "decoder", "router_unit", "encoder", "modulator",
           "uconv", "sspa", "omux"])
ont("dtp", "DTP数字透明处理器",
    "数字信道化 + 星上交换矩阵的柔性载荷核心：波束图样、子带带宽、功率分配与路由均可在轨重构，"
    "支持子带级灵活调度与 MPA 功率池单管故障重构。适用商业航天批产与需求频繁变更场景",
    "trp_arch", "体制",
    chain=["lna", "dconv", "adc", "dswitch", "dac", "uconv", "mpa", "omux"])

# ---- L2 分组：射频单机 ----
ont("trp_rx", "接收通道单机",
    "上行接收前端单机，噪声系数直接决定系统噪声温度与 G/T", "trp_subsys", "分组")
ont("lna", "低噪声放大器LNA",
    "接收前端低噪声放大，噪声系数 Ka 典型 1.6dB / Ku 1.2dB / L 0.8dB，通常 A/B 冷备",
    "trp_rx", "单机")
ont("imux", "输入多工器IMUX",
    "上行多通道滤波与分路，将宽带接收信号按转发器通道分割", "trp_rx", "单机")
ont("dconv", "下变频器DCONV",
    "将上行射频（Ka 30GHz / Ku 14GHz）下变频至中频或零中频，便于滤波与数字化",
    "trp_rx", "单机")

ont("trp_amp", "功率放大单机",
    "下行功率放大单机，决定星上 EIRP 与直流功耗（P_dc = P_out/η）", "trp_subsys", "分组")
ont("sspa", "固态功放SSPA",
    "GaN/GaAs 固态功率放大器，效率高、寿命长、可批产，适合中低功率与相控阵阵元级放大",
    "trp_amp", "单机")
ont("twta", "行波管功放TWTA",
    "行波管放大器，单管输出功率大、效率高（≈58~62%），适合 GEO 大 EIRP 透明转发；工作温度 −10~+55℃",
    "trp_amp", "单机")
ont("mpa", "多功放矩阵MPA",
    "N×N 功率池，功率在通道间动态分配，单管故障可重构，提高功放利用率与系统可用度",
    "trp_amp", "单机")
ont("epc", "电子功率调节器EPC",
    "行波管高压电源调节与开关机控制，含过流/过压保护与遥测", "trp_amp", "单机")

ont("trp_freq", "变频与频率单机",
    "上变频与本振频率源，相位噪声影响 EVM 与解调门限", "trp_subsys", "分组")
ont("uconv", "上变频器UCONV",
    "将中频上变频至下行射频（Ka 20GHz / Ku 12GHz）", "trp_freq", "单机")
ont("lo_source", "频率源/本振",
    "变频与采样所需的高稳定频率源，相位噪声（dBc/Hz@offset）影响 EVM 与解调门限",
    "trp_freq", "单机")

ont("trp_filter", "滤波与均衡单机",
    "通道选择、杂散抑制与通带平坦度控制单机", "trp_subsys", "分组")
ont("omux", "输出多工器OMUX",
    "下行多通道滤波与合成，隔离各通道并合成至发射天线，是透明转发载荷的关键无源单机",
    "trp_filter", "单机")
ont("filter_rf", "射频滤波器",
    "通道选择与杂散抑制滤波器（腔体/介质/声表），保障频率规划隔离", "trp_filter", "单机")
ont("equalizer", "均衡器/衰减器",
    "通道幅频/群时延均衡与电平控制，保障通带平坦度与功放线性工作点", "trp_filter", "单机")

ont("trp_switch", "交换与数字化单机",
    "DTP 柔性体制的核心单机：数字信道化、子带交换与数模转换", "trp_subsys", "分组")
ont("adc", "数字信道化ADC",
    "宽带模数转换与数字信道化，把射频/中频信号切分为可交换的子带（最小子带带宽 B_sub）",
    "trp_switch", "单机")
ont("dswitch", "星上交换矩阵",
    "子带级非阻塞交换矩阵，实现「任意输入波束→任意输出波束」的在轨重构连接，容量 C_sw",
    "trp_switch", "单机")
ont("dac", "数模转换DAC",
    "交换后子带的数模转换，输出至上变频与功放链", "trp_switch", "单机")
ont("switch_matrix", "微波开关矩阵",
    "SP8T 等开关矩阵，实现通道切换、备份倒换与在轨重构连接", "trp_switch", "单机")

ont("trp_baseband", "再生基带单机",
    "再生体制的星上基带处理单机，实现噪声不累积与星上路由", "trp_subsys", "分组")
ont("demod", "解调器",
    "再生体制星上解调（QPSK/8PSK/16APSK/32APSK，DVBS2X），实现噪声不累积",
    "trp_baseband", "单机")
ont("decoder", "译码器",
    "LDPC/BCH 信道译码，恢复信息比特并提供编码增益与误码统计", "trp_baseband", "单机")
ont("encoder", "编码器",
    "信道编码（LDPC/BCH）与加扰，决定体制的编码增益", "trp_baseband", "单机")
ont("modulator", "调制器",
    "星上再调制，按链路 C/N 自适应选择 MODCOD（ACM/VCM）", "trp_baseband", "单机")

# ---- L2 分组：通信链路 ----
ont("trp_links", "通信链路",
    "转发器分系统承载的星地/星上通信链路，含上行馈电、下行用户、星上波束交换与再生转发通道",
    "trp_subsys", "分组")
ont("uplink", "上行馈电链路",
    "关口站→卫星的上行射频链路（雨衰按上行频段计），星上接收通道决定 G/T 与所需关口站 EIRP",
    "trp_links", "链路",
    chain=["feed", "rx_filter", "circulator", "lna", "imux", "dconv", "adc"])
ont("downlink", "下行用户链路",
    "卫星→用户/关口站的下行射频链路，星上 EIRP 与地面 G/T 决定可达 C/N、余量与容量",
    "trp_links", "链路",
    chain=["dac", "uconv", "equalizer", "mpa", "omux", "circulator", "power_combiner", "feed"])
ont("interbeam_link", "星上波束交换链路",
    "波束间在星上完成交换/路由的内部链路（DTP 子带交换或再生路由），实现「落地不上天」的星上组网",
    "trp_links", "链路",
    chain=["adc", "dswitch", "dac", "switch_matrix", "beam_switch"])
ont("regen_channel", "再生转发通道",
    "端到端再生处理通道：上行解调译码→星上路由→下行编码调制，噪声不累积、余量提升 3~6dB",
    "trp_links", "链路",
    chain=["demod", "decoder", "router_unit", "encoder", "modulator"])

# ================================================================
# L1-3 激光通信分系统
# ================================================================
ont("laser_subsys", "激光通信分系统",
    "星间/星地激光高速链路终端，由光学天线单元、ATP 捕获跟踪单元、光收发单元、控制单元与激光链路组成，"
    "提供 Gbps 级星间组网与低时延回传能力；判据为捕获概率 ≥95%、精跟踪 ≤1μrad",
    "comm_payload", "分系统")

ont("laser_opt", "光学天线单元",
    "激光发射/接收光学口径，增益极高、发散角微弧度级", "laser_subsys", "分组")
ont("optical_antenna", "光学天线",
    "卡塞格林/折射式光学收发天线（如 Φ135mm），等效增益 ≈118dB，发散角 μrad 级",
    "laser_opt", "单机")

ont("laser_atp", "ATP捕获跟踪单元",
    "捕获（Acquisition）—跟踪（Tracking）—瞄准（Pointing）单元，决定建链成功率与跟踪精度",
    "laser_subsys", "分组")
ont("atp_coarse", "ATP粗跟踪机构",
    "万向架/转台式粗跟踪，完成大范围捕获与粗对准，是建链捕获概率的关键",
    "laser_atp", "单机")
ont("fsm", "精跟踪快速反射镜FSM",
    "压电/音圈快速反射镜，补偿平台微振动与指向抖动，实现 ≤1μrad 精跟踪",
    "laser_atp", "单机")
ont("acq_sensor", "捕获跟踪传感器",
    "四象限/CCD 探测器，提取信标光误差信号驱动 ATP 闭环", "laser_atp", "单机")
ont("beacon_laser", "信标激光器",
    "宽发散角信标光发射，用于远距离初始捕获与跟踪引导", "laser_atp", "单机")

ont("laser_trm", "光收发单元",
    "激光发射、接收与调制解调单机，决定链路速率与接收灵敏度", "laser_subsys", "分组")
ont("tx_laser", "通信激光器",
    "窄线宽通信激光发射（1550nm），输出功率与线宽决定链路 EIRP 与相位噪声",
    "laser_trm", "单机")
ont("photodetector", "光探测器",
    "APD/平衡探测器，接收灵敏度决定链路接收门限（DPSK 优于 OOK 约 6dB）",
    "laser_trm", "单机")
ont("dpsk_modem", "DPSK调制解调模块",
    "差分相移键空调制解调，门限约 8dB，是高速激光链路主流体制", "laser_trm", "单机")
ont("edfa", "光放大器EDFA",
    "掺铒光纤放大器，提升发射功率或补偿接收前端损耗", "laser_trm", "单机")
ont("opt_switch", "光开关",
    "多链路光路切换与主备倒换，支持多目标星间组网", "laser_trm", "单机")

ont("laser_ctrl_grp", "激光控制单元",
    "激光终端状态机控制与链路管理", "laser_subsys", "分组")
ont("laser_ctrl", "激光通信控制器",
    "ATP 状态机控制、建链/断链管理、链路遥测与故障处置，接受在轨重构控制器调度",
    "laser_ctrl_grp", "单机")

ont("laser_links", "激光链路",
    "星间与星地激光链路，星间无雨衰但受指向抖动影响，星地需计入云遮蔽与大气湍流代价",
    "laser_subsys", "分组")
ont("isl_laser", "星间激光链路ISL",
    "星座内星间激光链路（典型 5000km、10Gbps 量级），承担组网路由与数据接力，无雨衰、抗截获",
    "laser_links", "链路",
    chain=["beacon_laser", "acq_sensor", "atp_coarse", "fsm", "tx_laser", "edfa",
           "optical_antenna", "photodetector", "dpsk_modem", "opt_switch"])
ont("sgl_laser", "星地激光链路",
    "卫星→地面光学站的激光下行链路，速率高但受云雨与大气湍流影响，需站址分集与天气规避",
    "laser_links", "链路",
    chain=["optical_antenna", "atp_coarse", "fsm", "tx_laser", "edfa",
           "photodetector", "dpsk_modem", "laser_ctrl"])

# ================================================================
# L1-4 智能处理分系统
# ================================================================
ont("ipu_subsys", "智能处理分系统",
    "星上在轨处理与智能计算，含在轨处理单机、控制与组网单机、星内链路三组；"
    "承担数据压缩、AI 智能筛选、星上路由、存储与柔性载荷在轨重构调度",
    "comm_payload", "分系统")

ont("ipu_proc", "在轨处理单机",
    "基带处理、数据压缩、AI 推理与存储单机", "ipu_subsys", "分组")
ont("baseband", "基带处理单元",
    "基带信号处理（同步、均衡、成形、测距），衔接射频通道与数据处理", "ipu_proc", "单机")
ont("dpu", "数据处理单元DPU",
    "载荷数据在轨处理、压缩（CCSDS 无损/有损）、格式编排与下行调度", "ipu_proc", "单机")
ont("ai_unit", "AI推理单元",
    "星上 AI 加速单元（NPU/FPGA，算力 TOPS），支持目标检测、变化检测、云检测、业务预测与在轨智能筛选",
    "ipu_proc", "单机")
ont("storage", "大容量存储器",
    "星上固态存储（NAND），容量须覆盖数据率×最长不可见时段，支持 EDAC 与坏块管理",
    "ipu_proc", "单机")

ont("ipu_mgmt", "控制与组网单机",
    "载荷管理、星上路由、数据总线与在轨重构调度单机", "ipu_subsys", "分组")
ont("obc_payload", "星载计算机",
    "载荷级控制与管理计算机，负责载荷调度、遥控遥测、故障检测隔离与恢复（FDIR）",
    "ipu_mgmt", "单机")
ont("router_unit", "星上路由交换单元",
    "IP/ATM 或专用协议星上路由，支持星上组网与多星接力选路", "ipu_mgmt", "单机")
ont("data_bus", "星上数据总线",
    "SpaceWire/FC-AE/CAN 等星内高速总线，总线速率须大于载荷数据产生率",
    "ipu_mgmt", "单机")
ont("reconfig_ctrl", "在轨重构控制器",
    "柔性载荷在轨重构调度：波束图样、子带带宽、功率分配、路由表的动态配置与生效管理",
    "ipu_mgmt", "单机")

ont("ipu_links", "星内链路",
    "智能处理分系统承载的星内数据、组网与重构配置链路", "ipu_subsys", "分组")
ont("payload_data_link", "载荷数据链路",
    "基带→处理→AI筛选→压缩→存储→下行调度的星内数据链路，带宽须匹配载荷数据产生率",
    "ipu_links", "链路",
    chain=["baseband", "ai_unit", "dpu", "storage", "data_bus", "obc_payload"])
ont("onboard_net", "星上组网链路",
    "星上交换与路由构成的内部网络链路，支撑波束间/载荷间数据交换与多星协同",
    "ipu_links", "链路",
    chain=["router_unit", "dswitch", "data_bus", "obc_payload"])
ont("reconfig_link", "在轨重构配置链路",
    "重构指令下发链路：重构控制器→数据总线→天线控制单元/激光控制器/DTP，实现波束与功率在轨重构",
    "ipu_links", "链路",
    chain=["reconfig_ctrl", "obc_payload", "data_bus", "ant_ctrl", "laser_ctrl", "dtp"])

# ================================================================
# L1-5 载荷公共基础
# ================================================================
ont("base_common", "载荷公共基础",
    "跨分系统共享的约束基础：工作频段、载荷指标预算、行业标准与货架水平，"
    "为链路预算、指标分配与选型校核提供边界条件",
    "comm_payload", "基础")

ont("frequency_band", "工作频段",
    "业务频段选择决定雨衰、天线口径、器件工艺与频率指配（ITU-R S.466）；"
    "上行频率、下行频率、典型雨衰、可用总带宽与频率复用因子为频段级属性",
    "base_common", "基础")
ont("band_l", "L波段", "1.5/1.6GHz，移动业务、物联网与手机直连（D2D），雨衰≈0.1dB，需大口径或大阵面", "frequency_band", "基础")
ont("band_s", "S波段", "2.1/2.3GHz，低速率数传与辅助链路，雨衰≈0.2dB", "frequency_band", "基础")
ont("band_c", "C波段", "6.0/3.8GHz，传统卫星通信，抗雨衰能力强，雨衰≈0.5dB", "frequency_band", "基础")
ont("band_x", "X波段", "8.0/7.5GHz，军用通信与遥感数传，雨衰≈1.0dB", "frequency_band", "基础")
ont("band_ku", "Ku波段", "14/12GHz，直播、VSAT 与宽带接入，雨衰≈2.5dB", "frequency_band", "基础")
ont("band_ka", "Ka波段", "30/20GHz，高通量 HTS 与宽带星座主力频段，雨衰≈6dB，面精度要求 λ/32≈0.27mm", "frequency_band", "基础")
ont("band_qv", "Q/V波段", "45~50/40~42GHz，极高通量试验频段，雨衰 10~14dB，器件与传播特性仍在验证", "frequency_band", "基础")
ont("band_opt", "激光波段", "1550nm（≈193400GHz），星间/星地激光链路，无雨衰但受云雾与大气湍流影响", "frequency_band", "基础")

ont("payload_budget", "载荷指标预算",
    "载荷顶层指标预算与分系统指标分配，是选型闭环与校核的判据来源",
    "base_common", "指标")
ont("eirp_budget", "EIRP预算", "按业务链路余量反推的星上等效全向辐射功率预算（dBW），分配到天线增益与功放功率", "payload_budget", "指标")
ont("gt_budget", "G/T预算", "按上行链路余量反推的接收品质因数预算（dB/K），分配到天线增益与 LNA 噪声系数", "payload_budget", "指标")
ont("capacity_budget", "容量预算", "系统容量需求（Gbps），按 C_sys = N_beam × B_beam × η × k_reuse 分配到波束数与带宽", "payload_budget", "指标")
ont("mass_budget", "质量预算", "载荷总质量预算（kg），按分系统分解并保留 ≥10% 裕度", "payload_budget", "指标")
ont("power_budget", "功耗预算", "载荷总功耗预算（W），含峰值/均值区分与阴影期供电校核", "payload_budget", "指标")

ont("standard", "行业标准规范",
    "ITU-R S.1528（链路预算等效限值）/S.1323（天线方向图）/S.466（频率指配）、"
    "ECSS-E-ST-50-05C（通信链路设计）/E-ST-20C（EMC）/Q-ST-70C（载荷试验）、"
    "CCSDS 131.0-B/401.0-B、GJB 151B/150A/899A，约束链路预算、天线方向图、电磁兼容、环境试验与可靠性鉴定",
    "base_common", "基础")
ont("heritage", "货架水平",
    "单机/分系统成熟度等级：4 飞行继承货架 > 3 飞行继承 > 2 货架（在研转货架）> 1 定制；"
    "选型遵循货架优先原则，定制项须记录缺口、风险与研制周期",
    "base_common", "基础")

# ================================================================
# attributes
# ================================================================
# ---- 载荷总体 ----
attr("a-pay-eirp", "comm_payload", "载荷EIRP能力", "载荷对外等效全向辐射功率能力（dBW）", "EIRP_pay")
attr("a-pay-gt", "comm_payload", "载荷G/T", "载荷接收品质因数（dB/K）", "GT_pay")
attr("a-pay-cap", "comm_payload", "系统容量", "载荷可提供业务总容量（Gbps）", "C_sys")
attr("a-pay-mass", "comm_payload", "载荷总质量", "载荷总质量（kg），为各分系统质量之和加裕度", "M_pay")
attr("a-pay-power", "comm_payload", "载荷总功耗", "载荷总功耗（W）", "P_pay")
attr("a-pay-gap", "comm_payload", "货架缺口数", "需定制（非货架）单机数量，目标为 0", "N_gap")
attr("a-pay-heritage", "comm_payload", "整体货架水平", "方案整体货架继承水平（1定制~4飞行继承货架）", "H_scheme")
attr("a-pay-life", "comm_payload", "设计寿命", "载荷在轨设计寿命（年），GEO 通常 ≥15 年", "L_life")

# ---- 天线分系统 ----
attr("a-ant-gain", "ant_subsys", "天线增益", "天线方向性增益（dBi）", "G_ant")
attr("a-ant-eirp", "ant_subsys", "天线EIRP", "EIRP = P_out + G_ant − L_feed − L_tx（dBW）", "EIRP_ant")
attr("a-ant-gt", "ant_subsys", "天线G/T", "G/T = G_ant − 10lg(T_sys)（dB/K）", "GT_ant")
attr("a-ant-beam", "ant_subsys", "波束数", "可同时形成的独立波束数量", "N_beam")
attr("a-ant-bw-beam", "ant_subsys", "单波束带宽", "单个波束占用带宽（MHz）", "B_beam")
attr("a-ant-aperture", "ant_subsys", "口径/阵面尺寸", "反射面口径或阵面尺寸（m）", "D_ap")
attr("a-ant-hpbw", "ant_subsys", "半功率波束宽度", "波束半功率宽度（°），θ_3dB ≈ 70λ/D", "θ_3dB")
attr("a-ant-surface", "ant_subsys", "面精度", "反射面/阵面表面 RMS 误差（mm），需 ≤ λ/32", "δ_surf")
attr("a-ant-sidelobe", "ant_subsys", "旁瓣电平", "天线方向图旁瓣电平（dB），需 ≤ −20dB", "SLL")
attr("a-ant-axis", "ant_subsys", "轴比", "圆极化轴比（dB），需 ≤ 3dB", "AR")
attr("a-ant-feed-loss", "ant_subsys", "馈电损耗", "馈电网络插损（dB），计入 EIRP 扣减", "L_feed")
attr("a-ant-mass", "ant_subsys", "分系统质量", "天线分系统质量（kg）", "m_ant")
attr("a-ant-power", "ant_subsys", "分系统功耗", "天线分系统功耗（W），相控阵 ≈ N_el × P_tr + 控制功耗", "P_ant")
attr("a-ant-point", "ant_subsys", "波束指向精度", "波束指向误差（°），引起指向损耗 L_pnt=12(θ_e/θ_3dB)²", "θ_e")
attr("a-ant-mode", "ant_subsys", "工作模式", "单波束/多波束/波束跳变/在轨重构，须覆盖需求模式", "Mode")

# ---- 相控阵 ----
attr("a-pa-elements", "phased_array", "阵元数", "相控阵 T/R 组件数量，决定阵列增益 G=10lg(N_el×η)+G_el", "N_el")
attr("a-pa-scan", "phased_array", "扫描角", "电子扫描覆盖范围（±°），大扫描角需扣除 cos^1.5θ 扫描损耗", "θ_scan")
attr("a-pa-reconfig", "phased_array", "在轨重构能力", "波束图样/带宽/功率在轨重构支持度（0~1）", "R_pa")
attr("a-pa-db", "phased_array", "幅相一致性", "阵元幅相一致性（dB/°），决定旁瓣电平与赋形精度", "Δ_amp/Δ_phs")

# ---- 天线单机 ----
attr("a-tr-power", "tr_module", "单组件功耗", "单个 T/R 组件功耗（W），阵面总功耗 ≈ N_el × P_tr", "P_tr")
attr("a-tr-temp", "tr_module", "结温", "T/R 组件结温（℃），需 ≤ 125℃", "T_j")
attr("a-tr-pout", "tr_module", "组件输出功率", "单组件发射输出功率（W）", "P_tr_out")
attr("a-ps-bits", "phase_shifter", "移相位数", "数字移相器位数（bit），指向量化误差 ≈ 180/2^n 度", "n_bit")
attr("a-bf-channels", "beam_former", "成形通道数", "波束赋形网络通道数（= 波束数）", "N_bf")
attr("a-pc-eff", "power_combiner", "合成效率", "功率合成效率（%）与合成路数", "η_cmb")
attr("a-feed-eff", "feed", "照射效率", "馈源照射效率（%），影响天线总效率 η", "η_ill")
attr("a-circ-iso", "circulator", "隔离度", "收发隔离度（dB），需 ≥ 100dB", "I_iso")
attr("a-txf-rej", "tx_filter", "带外抑制", "发射滤波器带外抑制（dB），满足带外发射限值", "A_rej")
attr("a-rxf-rej", "rx_filter", "镜像抑制", "接收滤波器镜像/带外抑制（dB）", "A_img")
attr("a-beamport-n", "beam_port", "端口数", "波束端口数量，决定可同时工作的波束数", "N_port")
attr("a-deploy-acc", "deploy", "展开到位精度", "展开后型面到位精度（mm RMS），须满足 ≤λ/32", "δ_dep")
attr("a-point-step", "pointing", "指向步距", "机械指向最小步距（°）与指向重复精度", "Δ_pnt")
attr("a-cal-acc", "cal_network", "校准精度", "幅相校准精度（dB/°），影响旁瓣与赋形精度", "Δ_cal")
attr("a-acu-time", "ant_ctrl", "控制响应时间", "ACU 指令响应与波束切换时间（ms）", "t_acu")

# ---- 转发器分系统 ----
attr("a-trp-gain", "trp_subsys", "转发增益", "转发器总增益（dB）", "G_trp")
attr("a-trp-nf", "trp_subsys", "噪声系数", "接收通道总噪声系数（dB），决定系统噪声温度", "NF")
attr("a-trp-bw", "trp_subsys", "转发带宽", "转发器总带宽（MHz）", "B_trp")
attr("a-trp-flat", "trp_subsys", "通带平坦度", "通带幅频平坦度（dB）与群时延（ns）", "Δ_flat")
attr("a-trp-mass", "trp_subsys", "分系统质量", "转发器分系统质量（kg）", "m_trp")
attr("a-trp-power", "trp_subsys", "分系统功耗", "转发器分系统功耗（W），功放直流功耗 P_dc=P_out/η 为主", "P_trp")
attr("a-trp-isolation", "trp_subsys", "收发隔离度", "收发通道隔离度（dB），舱内隔离 ≥80dB、收发 ≥100dB", "I_trp")

# ---- 体制 ----
attr("a-trans-delay", "transparent", "转发时延", "透明转发星上时延（ns），近似为零", "τ_trans")
attr("a-regen-gain", "regenerative", "余量提升", "再生相比透明可提升链路余量（dB），典型 3~6dB（噪声不累积）", "ΔM_reg")
attr("a-regen-delay", "regenerative", "处理时延", "星上解调译码再调制时延（ms）", "τ_reg")
attr("a-dtp-subbw", "dtp", "子带带宽", "数字信道化最小子带带宽（MHz），越细越灵活但功耗越大", "B_sub")
attr("a-dtp-switch", "dtp", "交换容量", "星上交换矩阵总容量（Gbps）", "C_sw")
attr("a-dtp-channels", "dtp", "信道数", "数字信道化通道数，须满足 N_ch × B_sub ≥ B_trp", "N_ch")
attr("a-dtp-reconfig", "dtp", "重构时间", "波束/带宽/功率在轨重构切换时间（s）", "t_reconf")

# ---- 射频单机 ----
attr("a-lna-gain", "lna", "增益", "LNA 增益（dB）", "G_lna")
attr("a-lna-nf", "lna", "噪声系数", "LNA 噪声系数（dB），Ka 典型 1.6dB、Ku 1.2dB、L 0.8dB", "NF_lna")
attr("a-imux-ch", "imux", "通道数", "IMUX 通道数与通道间隔（MHz）", "N_imux")
attr("a-conv-gain", "dconv", "变频增益", "变频器转换增益（dB）与镜像抑制（dBc）", "G_conv")
attr("a-sspa-pout", "sspa", "输出功率", "SSPA 饱和输出功率（W）", "P_sspa")
attr("a-sspa-eff", "sspa", "效率", "SSPA 功率附加效率（%）", "η_sspa")
attr("a-sspa-lin", "sspa", "线性度", "输出回退量与三阶交调（dBc），影响高阶调制 EVM", "IMD3")
attr("a-twta-pout", "twta", "输出功率", "TWTA 饱和输出功率（W），Ku 典型 250W、Ka 180W", "P_twta")
attr("a-twta-eff", "twta", "效率", "TWTA 效率（%），典型 58~62%", "η_twta")
attr("a-mpa-nxn", "mpa", "矩阵规模", "MPA N×N 矩阵规模与单管故障重构能力", "N_mpa")
attr("a-epc-hv", "epc", "高压输出", "EPC 高压输出（kV）与保护响应时间", "V_hv")
attr("a-omux-ch", "omux", "通道数", "OMUX 通道数与通道间隔（MHz）", "N_omux")
attr("a-lo-phase", "lo_source", "相位噪声", "本振相位噪声（dBc/Hz@offset），影响 EVM 与解调门限", "L_φ")
attr("a-eq-flat", "equalizer", "均衡量", "幅频/群时延均衡量（dB/ns）", "Δ_eq")
attr("a-adc-bw", "adc", "采样带宽", "ADC 采样带宽（MHz）与有效位数（ENOB）", "B_adc")
attr("a-dsw-cap", "dswitch", "交换容量", "交换矩阵容量（Gbps）与交换粒度", "C_dsw")
attr("a-dac-bw", "dac", "输出带宽", "DAC 输出带宽（MHz）与无杂散动态范围（dBc）", "SFDR")
attr("a-sw-iso", "switch_matrix", "开关隔离度", "开关矩阵隔离度（dB）与切换时间（ns）", "I_sw")
attr("a-modcod", "modulator", "调制编码体制", "MODCOD 阶梯（QPSK~32APSK，DVBS2X），支持 ACM/VCM 自适应", "MODCOD")
attr("a-dec-gain", "decoder", "编码增益", "LDPC/BCH 编码增益（dB）", "G_code")
attr("a-demod-thr", "demod", "解调门限", "各体制解调 C/N 门限（dB，FEC 后准无误码）", "CN_thr")
attr("a-rf-rej", "filter_rf", "带外抑制", "射频滤波器带外抑制（dB）与插损（dB）", "A_rf")

# ---- 激光分系统 ----
attr("a-laser-rate", "laser_subsys", "链路速率", "激光通信速率（Gbps），典型 5/10Gbps", "R_laser")
attr("a-laser-eirp", "laser_subsys", "发射EIRP", "激光发射等效全向辐射功率（dBW），典型 105dBW", "EIRP_opt")
attr("a-laser-gt", "laser_subsys", "接收G/T", "激光接收品质因数（dB/K 等效），典型 118", "GT_opt")
attr("a-laser-wl", "laser_subsys", "工作波长", "激光工作波长（nm），1550nm 为主流", "λ_opt")
attr("a-laser-div", "laser_subsys", "发散角", "发射光束发散角（μrad）", "θ_div")
attr("a-laser-mass", "laser_subsys", "分系统质量", "激光通信分系统质量（kg）", "m_laser")
attr("a-laser-power", "laser_subsys", "分系统功耗", "激光通信分系统功耗（W）", "P_laser")
attr("a-opt-aperture", "optical_antenna", "光学口径", "光学天线口径（mm），典型 Φ135mm 卡塞格林", "D_opt")
attr("a-atp-acq", "atp_coarse", "捕获概率", "ATP 建链捕获概率（%），需 ≥ 95%", "P_acq")
attr("a-atp-time", "atp_coarse", "捕获时间", "初始捕获建链时间（s），影响星座组网可用度", "t_acq")
attr("a-fsm-track", "fsm", "跟踪精度", "精跟踪精度（μrad），需 ≤ 1μrad", "σ_track")
attr("a-fsm-range", "fsm", "偏转范围", "FSM 快反镜偏转范围（±mrad）与带宽（Hz）", "θ_fsm")
attr("a-acq-sens", "acq_sensor", "探测灵敏度", "捕获跟踪传感器探测灵敏度与视场（°）", "S_acq")
attr("a-beacon-pow", "beacon_laser", "信标功率", "信标激光输出功率（W）与发散角（mrad）", "P_bcn")
attr("a-tx-pout", "tx_laser", "发射光功率", "通信激光发射功率（W）与线宽（kHz）", "P_opt")
attr("a-opt-sens", "photodetector", "接收灵敏度", "光接收灵敏度（dBm），DPSK 优于 OOK 约 6dB", "S_opt")
attr("a-dpsk-thr", "dpsk_modem", "解调门限", "DPSK 体制解调门限（dB），约 8dB", "CN_dpsk")
attr("a-edfa-gain", "edfa", "放大增益", "EDFA 增益（dB）与噪声指数（dB）", "G_edfa")

# ---- 智能处理分系统 ----
attr("a-ipu-rate", "ipu_subsys", "处理速率", "在轨处理吞吐（Mbps/Gbps）", "R_ipu")
attr("a-ipu-mass", "ipu_subsys", "分系统质量", "智能处理分系统质量（kg）", "m_ipu")
attr("a-ipu-power", "ipu_subsys", "分系统功耗", "智能处理分系统功耗（W）", "P_ipu")
attr("a-bb-rate", "baseband", "基带速率", "基带处理速率（Mbps）与同步精度", "R_bb")
attr("a-dpu-rate", "dpu", "处理速率", "DPU 在轨处理吞吐（Mbps）", "R_dpu")
attr("a-dpu-compress", "dpu", "压缩比", "数据压缩比（CCSDS 无损/有损），可等效降低总线与存储需求", "CR")
attr("a-ai-tops", "ai_unit", "AI算力", "星上 AI 推理算力（TOPS）与模型规模", "AI_TOPS")
attr("a-store-cap", "storage", "存储容量", "星上存储容量（Tbit），≥ 数据率 × 最长不可见时段", "E_store")
attr("a-obc-mips", "obc_payload", "处理能力", "星载计算机处理能力（MIPS）与 FDIR 覆盖度", "MIPS")
attr("a-router-tbl", "router_unit", "路由表规模", "星上路由表条目数与单跳选路时延", "N_route")
attr("a-bus-rate", "data_bus", "总线速率", "星上数据总线速率（Mbps/Gbps），须 ≥ 载荷数据产生率", "R_bus")
attr("a-rec-time", "reconfig_ctrl", "重构生效时间", "重构指令下发至生效时间（s）与重构粒度", "t_rec")

# ---- 链路属性 ----
attr("a-link-freq", "uplink", "工作频率", "上行中心频率（GHz）", "f_up")
attr("a-link-dist", "uplink", "斜距", "星地斜距（km），GEO 约 36000~41000km、LEO 约 600~2000km", "d_slant")
attr("a-link-fspl", "uplink", "自由空间损耗", "L_fs = 20lg(d)+20lg(f)−147.55（dB）", "L_fs")
attr("a-link-rain", "uplink", "雨衰", "降雨衰减（dB），A(p) ∝ p^−0.6，并按 1/sin(el) 归一到 30°", "A_rain")
attr("a-link-atm", "uplink", "大气损耗", "大气吸收与云雾损耗（dB）", "A_atm")
attr("a-link-point", "uplink", "指向损耗", "L_pnt = 12(θ_e/θ_3dB)²（dB）", "L_pnt")
attr("a-link-polar", "uplink", "极化失配损耗", "极化失配与交叉极化损耗（dB），典型 0.3dB", "L_pol")
attr("a-link-impl", "uplink", "实现损耗", "设备实现损耗（dB），典型 1.0dB", "L_impl")
attr("a-link-cn0", "uplink", "载噪比密度", "C/N0 = EIRP − L_fs − ΣL + G/T − k（dBHz），k=−228.6dBW/Hz/K", "CN0")
attr("a-link-eirp-gs", "uplink", "关口站EIRP", "上行关口站 EIRP（dBW），GEO 典型 75dBW", "EIRP_gs")

attr("a-dl-freq", "downlink", "工作频率", "下行中心频率（GHz）", "f_down")
attr("a-dl-eirp", "downlink", "星上EIRP", "下行星上 EIRP（dBW），由天线能力决定", "EIRP_dl")
attr("a-dl-dist", "downlink", "斜距", "下行斜距（km）", "d_dl")
attr("a-dl-fspl", "downlink", "自由空间损耗", "下行 FSPL（dB）", "L_fs_dl")
attr("a-dl-rain", "downlink", "雨衰", "下行雨衰（dB），Ka 典型 6~12dB（0.01%时间超越概率）", "A_rain_dl")
attr("a-dl-gt", "downlink", "地面站G/T", "接收地面站/用户终端品质因数（dB/K），GEO 关口站典型 30dB/K", "GT_gs")
attr("a-dl-cn0", "downlink", "载噪比密度", "下行 C/N0（dBHz）", "CN0_dl")
attr("a-dl-cn", "downlink", "载噪比", "C/N = C/N0 − 10lg(B)（dB）", "CN")
attr("a-dl-cnreq", "downlink", "解调门限", "所选 MODCOD 的 C/N 门限（dB）", "CN_req")
attr("a-dl-margin", "downlink", "链路余量", "M = C/N − (C/N)_req（dB），判据 ≥ 3dB", "M")
attr("a-dl-cap", "downlink", "链路容量", "C = B × η（Mbps），η 为体制频谱效率", "C_link")
attr("a-dl-avail", "downlink", "链路可用性", "链路可用性要求（%），如 99.9%/99.99%，直接影响雨衰余量", "A_avail")
attr("a-dl-bw", "downlink", "占用带宽", "下行链路占用带宽（MHz）", "B_dl")

attr("a-ib-cap", "interbeam_link", "交换容量", "波束间星上交换容量（Gbps）", "C_ib")
attr("a-ib-delay", "interbeam_link", "交换时延", "星上交换时延（μs~ms），远低于星地往返", "τ_ib")
attr("a-ib-flex", "interbeam_link", "重构粒度", "波束连接关系重构粒度（子带/波束/整通道）", "G_ib")
attr("a-rg-cn", "regen_channel", "再生后C/N", "再生后上下行独立 C/N，总 C/N 由两段功率倒数相加", "CN_reg")
attr("a-rg-delay", "regen_channel", "端到端时延", "再生体制端到端时延（ms）", "τ_e2e")
attr("a-rg-route", "regen_channel", "路由能力", "星上路由表规模与选路时延", "N_rt")

attr("a-isl-dist", "isl_laser", "星间距离", "星间链路距离（km），LEO 星座典型 5000km", "d_isl")
attr("a-isl-fspl", "isl_laser", "光学路径损耗", "激光自由空间损耗（dB），由发散角、口径与距离决定", "L_fs_opt")
attr("a-isl-cn", "isl_laser", "载噪比", "激光链路 C/N（dB），DPSK 门限约 8dB", "CN_isl")
attr("a-isl-margin", "isl_laser", "链路余量", "激光链路余量（dB），含湍流与指向抖动代价", "M_isl")
attr("a-isl-rate", "isl_laser", "链路速率", "星间激光链路速率（Gbps）", "R_isl")
attr("a-isl-jitter", "isl_laser", "指向抖动", "链路指向抖动（μrad），影响瞬时耦合损耗", "σ_jit")
attr("a-sgl-cloud", "sgl_laser", "云遮蔽概率", "站址云遮蔽不可用概率（%），需站址分集规避", "P_cloud")
attr("a-sgl-turb", "sgl_laser", "大气湍流代价", "大气湍流引起的闪烁/相位噪声代价（dB）", "L_turb")
attr("a-sgl-rate", "sgl_laser", "链路速率", "星地激光链路速率（Gbps）", "R_sgl")
attr("a-pdl-rate", "payload_data_link", "数据率", "载荷数据链路数据率（Mbps/Gbps）", "R_pdl")
attr("a-pdl-loss", "payload_data_link", "误码率", "星内数据链路误码率（BER）", "BER_int")
attr("a-pdl-blind", "payload_data_link", "不可见时段", "最长数据不可见时段（min），决定存储容量需求", "T_blind")
attr("a-net-hop", "onboard_net", "跳数与时延", "星上组网最大跳数与单跳时延", "N_hop")
attr("a-rec-cycle", "reconfig_link", "重构周期", "重构指令周期与端到端生效时间（s）", "T_rec")
attr("a-tx-loss", "ant_tx_path", "通道插损", "发射通道总插损（dB），计入 EIRP 扣减", "L_tx")
attr("a-rx-noise", "ant_rx_path", "接收噪声温度", "接收通道贡献的系统噪声温度（K）", "T_sys")
attr("a-bl-nbeam", "beam_link", "波束调度能力", "可同时调度的波束数与波束切换时间（ms）", "N_sch")

# ---- 公共基础 ----
attr("a-band-fup", "frequency_band", "上行频率", "上行中心频率（GHz）", "f_up")
attr("a-band-fdown", "frequency_band", "下行频率", "下行中心频率（GHz）", "f_down")
attr("a-band-rain", "frequency_band", "典型雨衰", "0.01% 时间超越概率、30°仰角的典型雨衰（dB）", "A_band")
attr("a-band-reuse", "frequency_band", "频率复用因子", "多波束频率复用因子（色数），如 4 色/7 色复用", "k_reuse")
attr("a-band-total-bw", "frequency_band", "可用总带宽", "频段可用总带宽（MHz）", "B_total")
attr("a-bg-eirp", "eirp_budget", "EIRP需求", "业务需求 EIRP（dBW），由链路余量反推", "EIRP_req")
attr("a-bg-gt", "gt_budget", "G/T需求", "业务需求 G/T（dB/K），由上行链路余量反推", "GT_req")
attr("a-bg-cap", "capacity_budget", "容量需求", "系统容量需求（Gbps）", "C_req")
attr("a-bg-mass", "mass_budget", "质量预算", "载荷质量预算（kg）", "M_budget")
attr("a-bg-power", "power_budget", "功耗预算", "载荷功耗预算（W）", "P_budget")
attr("a-std-conf", "standard", "标准符合性", "方案对各标准的符合性与偏离项清单", "Std")
attr("a-hg-level", "heritage", "货架等级", "单机/分系统货架等级（1定制~4飞行继承货架）", "H")
attr("a-hg-gap", "heritage", "缺口记录", "定制项的需求描述、研制风险与周期", "Gap")

# ================================================================
# constraints
# ================================================================
con("c-1", "EIRP = P_out + G_ant − L_feed − L_tx",
    "星上等效全向辐射功率由功放输出功率、天线增益、馈电损耗与发射通道插损决定（dB 域加减），"
    "是天线分系统与转发器分系统指标分配的第一判据",
    ("a-ant-eirp", "EIRP"), ("a-ant-gain", "G_ant"), ("a-ant-feed-loss", "L_feed"),
    ("a-tx-loss", "L_tx"), ("a-sspa-pout", "P_out"), ("a-twta-pout", "P_out"))
con("c-2", "G/T = G_ant − 10lg(T_ant + T_rx)",
    "接收品质因数由天线增益与系统噪声温度决定；T_sys 主要由 LNA 噪声系数与接收通道插损主导，"
    "是天线分系统与 LNA 选型的耦合判据（G/T 每差 1dB，链路余量差 1dB）",
    ("a-ant-gt", "GT_ant"), ("a-ant-gain", "G_ant"), ("a-rx-noise", "T_sys"),
    ("a-lna-nf", "NF_lna"), ("a-trp-nf", "NF"))
con("c-3", "G_pa = 10lg(N_el × η) + G_el",
    "相控阵增益由阵元数、阵面效率与单元增益决定（忽略扫描损耗），用于按 EIRP 反推所需阵元数；"
    "扫描角增大时须扣除扫描损耗 cos^1.5(θ)",
    ("a-ant-gain", "G_ant"), ("a-pa-elements", "N_el"), ("a-pa-scan", "θ_scan"))
con("c-4", "G_refl = 10lg(η × (πD/λ)²)，θ_3dB ≈ 70λ/D",
    "反射面/反射阵天线增益由口径、工作频率与口面效率决定，用于按 EIRP 反推所需口径；"
    "半功率波束宽度随口径增大而变窄，进而放大指向损耗",
    ("a-ant-gain", "G_ant"), ("a-ant-aperture", "D_ap"), ("a-band-fdown", "f_down"),
    ("a-ant-hpbw", "θ_3dB"), ("a-feed-eff", "η_ill"))
con("c-5", "δ_surf ≤ λ/32 且 δ_dep ≤ δ_surf",
    "反射面/反射阵表面 RMS 精度须优于工作波长的 1/32（Ka 约 0.27mm），否则增益下降、旁瓣抬升；"
    "展开机构到位精度是面精度的下限约束",
    ("a-ant-surface", "δ_surf"), ("a-band-fdown", "f_down"), ("a-deploy-acc", "δ_dep"))
con("c-6", "L_pnt = 12 × (θ_e / θ_3dB)²",
    "波束指向误差引起的指向损耗由指向精度与半功率波束宽度决定；窄波束（大口径/多波束）对"
    "天线指向机构与平台姿态的要求显著提高",
    ("a-link-point", "L_pnt"), ("a-ant-point", "θ_e"), ("a-ant-hpbw", "θ_3dB"),
    ("a-point-step", "Δ_pnt"))
con("c-7", "L_fs = 20lg(d) + 20lg(f) − 147.55",
    "自由空间损耗由斜距与工作频率决定（d:m，f:Hz），是所有链路预算的基础项；"
    "GEO 约 205dB@30GHz、LEO 约 172dB@30GHz",
    ("a-link-fspl", "L_fs"), ("a-link-dist", "d_slant"), ("a-band-fup", "f_up"))
con("c-8", "C/N0 = EIRP − L_fs − ΣL + G/T − k",
    "载噪比密度由发射 EIRP、自由空间损耗、各类损耗（雨衰/大气/指向/极化/实现）、接收 G/T 与"
    "玻尔兹曼常数（k = −228.6 dBW/Hz/K）决定，k 为常数不入图",
    ("a-link-cn0", "CN0"), ("a-ant-eirp", "EIRP"), ("a-link-fspl", "L_fs"),
    ("a-link-rain", "A_rain"), ("a-link-atm", "A_atm"), ("a-link-point", "L_pnt"),
    ("a-ant-gt", "GT_ant"))
con("c-9", "C/N = C/N0 − 10lg(B)",
    "载噪比由载噪比密度减去带宽归一项得到（B:Hz）；单波束带宽减半约换来 +3dB C/N，"
    "是余量不足时的快速调整手段",
    ("a-dl-cn", "CN"), ("a-dl-cn0", "CN0"), ("a-dl-bw", "B_dl"), ("a-ant-bw-beam", "B_beam"))
con("c-10", "M = C/N − (C/N)_req ≥ 3 dB",
    "链路余量硬判据：实际 C/N 减去所选 MODCOD 门限须 ≥ 3dB 方可闭合；不满足时触发回环——"
    "①降阶调制 ②增大口径/阵元数或功放功率 ③减小单波束带宽 ④放宽可用性要求（换天线重选 ≤2 次）",
    ("a-dl-margin", "M"), ("a-dl-cn", "CN"), ("a-dl-cnreq", "CN_req"), ("a-dl-avail", "A_avail"))
con("c-11", "C_link = B × η(MODCOD)",
    "链路容量由占用带宽与频谱效率决定；η 由实际 C/N 在 DVBS2X 阶梯上自适应选定"
    "（QPSK 1.79 → 8PSK 2.85 → 16APSK 3.70 → 32APSK 4.45 bps/Hz），"
    "即「先有 C/N，再定体制与容量」而非先锁高阶体制",
    ("a-dl-cap", "C_link"), ("a-dl-cn", "CN"), ("a-modcod", "MODCOD"))
con("c-12", "C_sys = N_beam × B_beam × η × k_reuse",
    "系统总容量由波束数、单波束带宽、频谱效率与频率复用因子共同决定，是天线分系统波束数与"
    "转发器带宽指标分配的顶层公式",
    ("a-pay-cap", "C_sys"), ("a-ant-beam", "N_beam"), ("a-ant-bw-beam", "B_beam"),
    ("a-band-reuse", "k_reuse"), ("a-bg-cap", "C_req"))
con("c-13", "N_beam × B_beam ≤ B_total × k_reuse",
    "频率规划约束：波束数×单波束带宽不得超过频段可用总带宽×频率复用因子，否则出现频率冲突"
    "（ITU-R S.466 频率指配 / S.1528 等效限值）",
    ("a-ant-beam", "N_beam"), ("a-ant-bw-beam", "B_beam"),
    ("a-band-total-bw", "B_total"), ("a-band-reuse", "k_reuse"))
con("c-14", "C_sw ≥ N_beam × B_beam 且 N_ch × B_sub ≥ B_trp",
    "DTP 数字信道化与交换容量须覆盖转发器总带宽与波束容量需求，否则星上交换成为容量瓶颈；"
    "子带带宽越细重构越灵活，但 ADC/DAC 与交换功耗显著上升",
    ("a-dtp-switch", "C_sw"), ("a-dtp-channels", "N_ch"), ("a-dtp-subbw", "B_sub"),
    ("a-trp-bw", "B_trp"), ("a-ib-cap", "C_ib"), ("a-dsw-cap", "C_dsw"))
con("c-15", "I_iso ≥ 100 dB 且 I_trp ≥ 80 dB",
    "电磁兼容约束：收发隔离 ≥100dB、舱内隔离 ≥80dB，通过环行器/隔离器、滤波与屏蔽实现，"
    "防止自激与互调（GJB 151B / MIL-STD-461 / ECSS-E-ST-20C）",
    ("a-circ-iso", "I_iso"), ("a-trp-isolation", "I_trp"),
    ("a-txf-rej", "A_rej"), ("a-sw-iso", "I_sw"))
con("c-16", "T_j ≤ 125 ℃ 且 P_dc = P_out / η ≤ P_trp",
    "热控与供电双约束：T/R 组件结温 ≤125℃、行波管 −10~+55℃、LNA −40~+70℃；"
    "功放直流功耗 P_dc = P_out/η 须在分系统功耗预算内，效率越高热控压力越小",
    ("a-tr-temp", "T_j"), ("a-tr-power", "P_tr"), ("a-twta-eff", "η_twta"),
    ("a-sspa-eff", "η_sspa"), ("a-trp-power", "P_trp"))
con("c-17", "M_pay = Σm_i ≤ M_budget 且 P_pay = ΣP_i ≤ P_budget（裕度 ≥10%）",
    "载荷质量与功耗预算约束：四个分系统质量/功耗之和须在载荷预算内并保留 ≥10% 裕度；"
    "超限则换分系统方案（如相控阵改反射阵、单管功放改 MPA 功率池、降低子带精细度）",
    ("a-pay-mass", "M_pay"), ("a-bg-mass", "M_budget"),
    ("a-pay-power", "P_pay"), ("a-bg-power", "P_budget"),
    ("a-ant-mass", "m_ant"), ("a-trp-mass", "m_trp"),
    ("a-laser-mass", "m_laser"), ("a-ipu-mass", "m_ipu"))
con("c-18", "P_acq ≥ 95% 且 σ_track ≤ 1 μrad",
    "激光通信 ATP 判据：建链捕获概率 ≥95%、精跟踪精度 ≤1μrad，方可维持稳定链路；"
    "捕获时间与指向抖动共同影响星座组网可用度",
    ("a-atp-acq", "P_acq"), ("a-atp-time", "t_acq"),
    ("a-fsm-track", "σ_track"), ("a-isl-jitter", "σ_jit"))
con("c-19", "R_laser ≤ f(EIRP_opt, GT_opt, L_fs_opt, L_turb)",
    "激光链路速率受发射 EIRP、接收 G/T、光学路径损耗与大气湍流代价约束；DPSK 体制门限约 8dB、"
    "灵敏度优于 OOK 约 6dB；星间链路无雨衰，星地链路须计入云遮蔽概率并做站址分集",
    ("a-laser-rate", "R_laser"), ("a-laser-eirp", "EIRP_opt"), ("a-laser-gt", "GT_opt"),
    ("a-isl-fspl", "L_fs_opt"), ("a-isl-margin", "M_isl"), ("a-opt-sens", "S_opt"),
    ("a-sgl-turb", "L_turb"), ("a-sgl-cloud", "P_cloud"))
con("c-20", "R_bus ≥ R_pdl 且 E_store ≥ R_pdl × T_blind",
    "星内数据链路约束：数据总线速率须大于载荷数据产生率，存储容量须覆盖最长不可见时段的数据量；"
    "压缩比 CR 与 AI 在轨筛选可等效降低对总线与存储的需求",
    ("a-bus-rate", "R_bus"), ("a-pdl-rate", "R_pdl"), ("a-store-cap", "E_store"),
    ("a-pdl-blind", "T_blind"), ("a-dpu-compress", "CR"), ("a-bb-rate", "R_bb"))
con("c-21", "N_gap → 0 且 H_scheme → 4",
    "货架优先原则：优先选用飞行继承货架(4) > 飞行继承(3) > 货架在研转货架(2) > 定制(1)；"
    "定制缺口 N_gap 目标为 0，每项缺口须记录需求、风险与研制周期",
    ("a-pay-gap", "N_gap"), ("a-pay-heritage", "H_scheme"),
    ("a-hg-level", "H"), ("a-hg-gap", "Gap"))
con("c-22", "EIRP_ant ≥ EIRP_req 且 GT_ant ≥ GT_req 且 Mode ⊇ Mode_req",
    "需求闭环判据：天线能力（EIRP/G/T/工作模式）须覆盖业务需求；工作模式须包含需求模式"
    "（单波束/多波束/波束跳变/在轨重构），否则该天线不可选并触发内环换天线（≤3 次）",
    ("a-ant-eirp", "EIRP_ant"), ("a-bg-eirp", "EIRP_req"),
    ("a-ant-gt", "GT_ant"), ("a-bg-gt", "GT_req"),
    ("a-ant-mode", "Mode"), ("a-pa-reconfig", "R_pa"))
con("c-23", "Δ_amp ≤ 0.5 dB 且 Δ_phs ≤ 5° 且 SLL ≤ −20 dB 且 AR ≤ 3 dB",
    "天线电气性能约束：阵元幅相一致性决定旁瓣与赋形精度；旁瓣电平 ≤−20dB 满足 ITU-R S.1323 "
    "方向图要求并避免邻星干扰；圆极化轴比 ≤3dB；校准精度须优于一致性指标",
    ("a-pa-db", "Δ_amp/Δ_phs"), ("a-ant-sidelobe", "SLL"), ("a-ant-axis", "AR"),
    ("a-cal-acc", "Δ_cal"), ("a-feed-eff", "η_ill"))
con("c-24", "M < 3 dB 且 MODCOD 已最低阶 ⇒ ΔM_reg ≥ 3 dB → 改再生/DTP",
    "体制选择判据：当透明转发链路余量不足且调制已降至最低阶时，改用再生体制可获得 3~6dB 余量提升"
    "（噪声不累积）；需频繁重构波束/带宽/功率时选 DTP 柔性体制，代价为功耗与质量增加",
    ("a-regen-gain", "ΔM_reg"), ("a-dl-margin", "M"), ("a-trans-delay", "τ_trans"),
    ("a-regen-delay", "τ_reg"), ("a-dtp-reconfig", "t_reconf"))
con("c-25", "N_bf ≥ N_beam 且 N_port ≥ N_beam 且 N_sch ≥ N_beam",
    "波束链路能力一致性：波束赋形网络通道数、波束端口数与波束调度能力须不小于设计波束数，"
    "否则波束数指标无法实现（多波束/波束跳变体制的关键闭环）",
    ("a-bf-channels", "N_bf"), ("a-beamport-n", "N_port"),
    ("a-bl-nbeam", "N_sch"), ("a-ant-beam", "N_beam"))

# ================================================================
# relations（chain 自动派生 + 显式补充）
# ================================================================
ont_ids = {o["id"] for o in ONT}
n = 0
for o in ONT:
    for tgt in o.get("chain", []):
        n += 1
        typ = "链路组成单机" if o["category"] == "链路" else "体制组成单机"
        rel(f"r-{n}", o["id"], tgt, typ, f"{o['name']} 的组成单机（有序）")

extra = [
    ("ant_subsys", "eirp_budget", "指标分配", "天线分系统承接 EIRP 指标分配（增益 × 功率 − 损耗）"),
    ("ant_subsys", "gt_budget", "指标分配", "天线分系统承接 G/T 指标分配（增益 / 噪声温度）"),
    ("trp_subsys", "capacity_budget", "指标分配", "转发器分系统承接容量与转发带宽指标分配"),
    ("laser_subsys", "capacity_budget", "指标分配", "激光分系统承担星间回传容量份额"),
    ("ant_subsys", "frequency_band", "频段适配", "天线体制与频段匹配（口径/阵元数由波长 λ 决定）"),
    ("trp_subsys", "frequency_band", "频段适配", "射频单机频段须与任务频段一致，禁止频段错配"),
    ("laser_subsys", "band_opt", "频段适配", "激光分系统工作于 1550nm 光学波段"),
    ("transparent", "trp_subsys", "体制归属", "透明转发为转发器分系统体制之一"),
    ("regenerative", "trp_subsys", "体制归属", "再生处理为转发器分系统体制之一"),
    ("dtp", "trp_subsys", "体制归属", "DTP 柔性为转发器分系统体制之一"),
    ("phased_array", "dtp", "协同", "相控阵天线 + DTP 构成柔性载荷（波束/带宽/功率在轨重构）"),
    ("phased_array", "tr_module", "组成", "相控阵由 N_el 个 T/R 组件构成阵面"),
    ("tr_module", "phase_shifter", "组成", "T/R 组件内含移相器与可变衰减器"),
    ("reflector", "feed", "组成", "反射面天线由反射面与馈源馈电网络组成"),
    ("umbrella", "deploy", "组成", "伞状可展开天线依赖展开机构"),
    ("reconfig_ctrl", "dtp", "控制", "在轨重构控制器驱动 DTP 子带与功率重构"),
    ("reconfig_ctrl", "phased_array", "控制", "在轨重构控制器驱动相控阵波束图样重构"),
    ("ant_ctrl", "pointing", "控制", "ACU 驱动天线指向机构"),
    ("laser_ctrl", "atp_coarse", "控制", "激光控制器驱动 ATP 状态机"),
    ("ai_unit", "dpu", "协同", "AI 推理单元与 DPU 协同完成在轨智能筛选与压缩"),
    ("router_unit", "dswitch", "协同", "星上路由交换单元与 DTP 交换矩阵协同实现星上组网"),
    ("isl_laser", "onboard_net", "承载", "星间激光链路承载星上组网数据的星间转发"),
    ("ant_tx_path", "downlink", "衔接", "下行用户链路末段接入天线发射通道"),
    ("ant_rx_path", "uplink", "衔接", "上行馈电链路前段即天线接收通道"),
    ("beam_link", "interbeam_link", "衔接", "波束链路为星上波束交换链路提供波束侧连接"),
    ("payload_budget", "comm_payload", "指标约束", "载荷指标预算约束载荷总体与四个分系统"),
    ("standard", "comm_payload", "规范约束", "行业标准对链路预算、天线方向图、EMC 与试验的规范约束"),
    ("heritage", "comm_payload", "选型原则", "货架水平决定选型优先级与缺口记录"),
]
for f, t, typ, d in extra:
    n += 1
    rel(f"r-{n}", f, t, typ, d)

# ================================================================
# 校验
# ================================================================
errs = []
attr_ids = {a["id"] for a in ATTR}
if len(ont_ids) != len(ONT):
    errs.append("ontology id 重复")
for o in ONT:
    if o["parentId"] is not None and o["parentId"] not in ont_ids:
        errs.append(f"bad parentId: {o['id']} -> {o['parentId']}")
    for t in o.get("chain", []):
        if t not in ont_ids:
            errs.append(f"chain 指向不存在的节点: {o['id']} -> {t}")
for a in ATTR:
    if a["ontologyId"] not in ont_ids:
        errs.append(f"bad ontologyId: {a['id']} -> {a['ontologyId']}")
    if not a["symbol"]:
        errs.append(f"attribute 缺 symbol: {a['id']}")
for c in CONS:
    for m in c["members"]:
        if m["attributeId"] not in attr_ids:
            errs.append(f"constraint {c['id']} bad member: {m['attributeId']}")
for r in REL:
    if r["from"] not in ont_ids:
        errs.append(f"relation {r['id']} bad from: {r['from']}")
    if r["to"] not in ont_ids:
        errs.append(f"relation {r['id']} bad to: {r['to']}")
if len({a["id"] for a in ATTR}) != len(ATTR):
    errs.append("attribute id 重复")
if len({c["id"] for c in CONS}) != len(CONS):
    errs.append("constraint id 重复")
if len({r["id"] for r in REL}) != len(REL):
    errs.append("relation id 重复")

children: dict = {}
for o in ONT:
    children.setdefault(o["parentId"], []).append(o["id"])


def walk(nid, stack):
    if nid in stack:
        errs.append(f"cycle at {nid}")
        return
    for ch in children.get(nid, []):
        walk(ch, stack | {nid})


walk(None, set())

roots = [o for o in ONT if o["parentId"] is None]
if len(roots) != 1 or roots[0]["id"] != "comm_payload":
    errs.append(f"根节点应唯一且为 comm_payload，实际 {[r['id'] for r in roots]}")

forbidden = ["sat", "platform", "launch_vehicle", "control", "power", "ttc", "camera", "ccd",
             "sar", "nav_payload", "sci_payload", "orbit", "star", "obc", "gyro", "panel", "battery",
             "hyperspectral", "ttc_antenna", "ttc_transponder"]
hit = [f for f in forbidden if f in ont_ids]
if hit:
    errs.append(f"仍含卫星系统级节点: {hit}")

need_l1 = ["ant_subsys", "trp_subsys", "laser_subsys", "ipu_subsys"]
l1 = children.get("comm_payload", [])
miss = [x for x in need_l1 if x not in l1]
if miss:
    errs.append(f"缺少一级分系统: {miss}")

# 层级检查：L1 必须是分系统/基础，L2 必须是分组或基础/指标，L3 是体制/单机/链路
depth_of = {}
for o in ONT:
    d, c = 0, o["parentId"]
    while c:
        d += 1
        c = next(x for x in ONT if x["id"] == c)["parentId"]
    depth_of[o["id"]] = d
max_depth = max(depth_of.values())

kw = {k: (k in json.dumps(ONT, ensure_ascii=False)) for k in
      ["天线", "转发器", "激光", "智能", "相控阵", "DTP", "射频", "单机"]}
if not all(kw.values()):
    errs.append(f"关键词未覆盖: {[k for k, v in kw.items() if not v]}")

# 每条链路/体制必须有 chain 且 chain 中的单机必须存在
for o in ONT:
    if o["category"] in ("链路",) and not o.get("chain"):
        errs.append(f"链路节点缺少 chain: {o['id']}")
    if o["category"] == "体制" and o["id"] in ("transparent", "regenerative", "dtp") and not o.get("chain"):
        errs.append(f"体制节点缺少 chain: {o['id']}")

if errs:
    print("校验失败：")
    for e in errs:
        print("  -", e)
    raise SystemExit(1)

graph = {
    "version": 3,
    "exportedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "name": "通信有效载荷知识图谱",
    "scope": "仅通信有效载荷（不含卫星系统、平台、运载、遥感/导航/科学载荷）",
    "description": (
        "以「通信有效载荷」为唯一根的领域知识图谱，层级清晰（最大 L3）："
        "L1 = 天线分系统 / 转发器分系统 / 激光通信分系统 / 智能处理分系统 / 载荷公共基础；"
        "L2 = 各分系统下的体制分组、单机分组与链路分组；L3 = 具体体制、具体单机与具体链路。"
        "射频链路（天线发射通道/接收通道/波束链路）与通信链路（上行馈电/下行用户/星上波束交换/再生转发通道/"
        "星间激光/星地激光/载荷数据/星上组网/在轨重构配置）均下沉到所属分系统内部，"
        "每条链路与每种转发体制通过 chain 字段给出有序「组成单机」，并在 relations 中派生为图边。"
        "约束 25 条覆盖 EIRP、G/T、阵增益、反射面增益、面精度、指向损耗、FSPL、C/N0、C/N、余量≥3dB、"
        "链路容量、系统容量、频率规划、DTP 交换、EMC 隔离、热控供电、质量功耗预算、激光 ATP、激光速率、"
        "星内数据链路、货架优先、需求闭环、天线电气性能、体制选择与波束链路能力一致性。"
    ),
    "sourceFile": "knowledge-graph-2026-09-20.json（schema 兼容，内容为通信载荷专用重构）",
    "schema": {
        "ontologies": "id / name / description / parentId / order / category / chain?",
        "attributes": "id / ontologyId / name / description / symbol",
        "constraints": "id / formula / description / members[{attributeId, role}]",
        "relations": "id / from / to / type / description",
        "category枚举": ["载荷总体", "分系统", "分组", "体制", "单机", "链路", "基础", "指标"],
        "chain语义": "有序组成单机 id 列表（链路→经过的单机；体制→该体制的单机链）",
    },
    "ontologies": ONT,
    "attributes": ATTR,
    "constraints": CONS,
    "relations": REL,
}

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(graph, f, ensure_ascii=False, indent=2)

# ---------------- 报告 ----------------
cat_count = {}
for o in ONT:
    cat_count[o["category"]] = cat_count.get(o["category"], 0) + 1

lines = ["✅ 校验通过（0 错误）", f"输出: {OUT_PATH}",
         f"ontologies: {len(ONT)}  attributes: {len(ATTR)}  constraints: {len(CONS)}  relations: {len(REL)}",
         f"category 分布: {json.dumps(cat_count, ensure_ascii=False)}",
         f"最大层级深度: L{max_depth}",
         f"一级分支: {', '.join(next(o['name'] for o in ONT if o['id']==i) for i in l1)}",
         "", "== 一级分支规模（含子树）=="]
for x in l1:
    sub, stack = [x], [x]
    while stack:
        cur = stack.pop()
        for k in children.get(cur, []):
            sub.append(k)
            stack.append(k)
    o_ = next(o for o in ONT if o["id"] == x)
    cat_of = {o["id"]: o["category"] for o in ONT}
    units = sum(1 for i in sub if cat_of[i] == "单机")
    links = sum(1 for i in sub if cat_of[i] == "链路")
    archs = sum(1 for i in sub if cat_of[i] == "体制")
    groups = sum(1 for i in sub if cat_of[i] == "分组")
    n_attrs = sum(1 for a in ATTR if a["ontologyId"] in set(sub))
    lines.append(f"  {o_['name']}: 节点 {len(sub)}（分组 {groups} / 体制 {archs} / 单机 {units} / 链路 {links}），属性 {n_attrs}")

lines += ["", "== 层级树（L0~L3）=="]
def dump(nid, d):
    for ch in sorted(children.get(nid, []), key=lambda i: next(o["order"] for o in ONT if o["id"] == i)):
        o = next(x for x in ONT if x["id"] == ch)
        tag = f" [{o['category']}]" if o["category"] != "分系统" else ""
        chain_s = f"\n{'  '*(d+1)}    ↳ 组成单机: {' → '.join(o['chain'])}" if o.get("chain") else ""
        lines.append("  " * d + f"- {o['name']} ({o['id']}){tag}{chain_s}")
        dump(ch, d + 1)
dump(None, 0)

lines += ["", "== 约束清单 =="]
for c in CONS:
    lines.append(f"  {c['id']}: {c['formula']}")

lines += ["", f"== relations 类型分布（共 {len(REL)}）=="]
rc = {}
for r in REL:
    rc[r["type"]] = rc.get(r["type"], 0) + 1
for k, v in sorted(rc.items(), key=lambda x: -x[1]):
    lines.append(f"  {k}: {v}")

lines += ["", f"关键词覆盖: {json.dumps(kw, ensure_ascii=False)}",
          f"含 chain 的节点: {sum(1 for o in ONT if o.get('chain'))} 个（链路 {sum(1 for o in ONT if o.get('chain') and o['category']=='链路')} / 体制 {sum(1 for o in ONT if o.get('chain') and o['category']=='体制')}）",
          f"chain 覆盖单机种类: {len({t for o in ONT for t in o.get('chain', [])})}"]

report = "\n".join(lines)
with open(RPT_PATH, "w", encoding="utf-8") as f:
    f.write(report)
print(report)
