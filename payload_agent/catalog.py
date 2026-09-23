"""货架产品库 (Catalog)

文生载荷智能体的知识底座。四类货架目录 + 频段/轨道基础数据。
所有条目均为 dict，扩充产品直接追加即可，选型引擎自动覆盖。

货架水平 (heritage) 优先级:
  4 飞行继承货架 > 3 飞行继承 > 2 货架(在研转货架) > 1 定制
"""

from __future__ import annotations

from typing import Dict, List

# ============================================================
# 频段定义
# ============================================================

FREQUENCY_BANDS: Dict[str, Dict[str, float]] = {
    # 名称: 上行中心频率 GHz / 下行中心频率 GHz / 典型雨衰 dB(0.01%)
    "L":  {"up": 1.6,  "down": 1.5,  "rain": 0.1,  "use": "移动/物联网/手机直连"},
    "S":  {"up": 2.1,  "down": 2.3,  "rain": 0.2,  "use": "测控/低速率数传"},
    "C":  {"up": 6.0,  "down": 3.8,  "rain": 0.5,  "use": "传统卫星通信/抗雨衰"},
    "X":  {"up": 8.0,  "down": 7.5,  "rain": 1.0,  "use": "军用/遥感数传"},
    "Ku": {"up": 14.0, "down": 12.0, "rain": 2.5,  "use": "直播/VSAT/宽带"},
    "Ka": {"up": 30.0, "down": 20.0, "rain": 6.0,  "use": "高通量HTS/宽带星座"},
    "Q":  {"up": 45.0, "down": 42.0, "rain": 10.0, "use": "极高通量(试验)"},
    "V":  {"up": 50.0, "down": 40.0, "rain": 14.0, "use": "极高通量(试验)"},
    "激光": {"up": 193400.0, "down": 193400.0, "rain": 0.0, "use": "星间链路/高速数传"},
}

# ============================================================
# 轨道定义
# ============================================================

ORBIT_TYPES: Dict[str, Dict[str, object]] = {
    "LEO": {"alt_km": (500, 1200),   "period_min": (95, 110),    "desc": "低地球轨道，时延小、单星覆盖小、需星座组网"},
    "MEO": {"alt_km": (8000, 20000), "period_min": (300, 720),   "desc": "中地球轨道，导航星座典型轨道"},
    "GEO": {"alt_km": (35786, 35786), "period_min": (1436, 1436), "desc": "地球静止轨道，单星覆盖约1/3地球、时延约250ms"},
    "SSO": {"alt_km": (500, 800),    "period_min": (95, 100),    "desc": "太阳同步轨道，遥感典型轨道、光照条件一致"},
    "HEO": {"alt_km": (500, 40000),  "period_min": (720, 1440),  "desc": "大椭圆轨道，高纬度覆盖"},
}

# ============================================================
# 天线货架库
# ============================================================

CATALOG_ANTENNAS: List[dict] = [
    {
        "model": "ANT-AESA-KA-HTS", "name": "Ka 频段多波束相控阵天线",
        "type": "相控阵", "band": "Ka",
        "eirp_cap_dbw": 62.0, "gt_dbk": 12.0, "mass_kg": 180.0, "power_w": 2200.0,
        "aperture": "1.2m×1.0m 平面阵", "elements": 1024,
        "modes": ["多波束", "波束跳变", "在轨重构"],
        "heritage": 3, "heritage_desc": "飞行继承（低轨宽带星座批量在轨）",
        "vendor": "GAL-银河航天", "beam_num": 48,
    },
    {
        "model": "ANT-AESA-KU-FLEX", "name": "Ku 频段柔性波束相控阵天线",
        "type": "相控阵", "band": "Ku",
        "eirp_cap_dbw": 54.0, "gt_dbk": 8.0, "mass_kg": 120.0, "power_w": 1500.0,
        "aperture": "1.0m×0.8m 平面阵", "elements": 512,
        "modes": ["多波束", "波束跳变", "在轨重构"],
        "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内", "beam_num": 16,
    },
    {
        "model": "ANT-UMB-L12", "name": "12m L 波段可展开伞状天线",
        "type": "反射面(展开式)", "band": "L",
        "eirp_cap_dbw": 48.0, "gt_dbk": 6.0, "mass_kg": 320.0, "power_w": 400.0,
        "aperture": "Φ12m 伞状网面", "elements": 0,
        "modes": ["多波束", "单波束"],
        "heritage": 2, "heritage_desc": "货架（在研转货架）", "vendor": "CN-国内", "beam_num": 19,
    },
    {
        "model": "ANT-AESA-L-D2D", "name": "L 波段手机直连相控阵天线",
        "type": "相控阵", "band": "L",
        "eirp_cap_dbw": 50.0, "gt_dbk": 4.0, "mass_kg": 210.0, "power_w": 1800.0,
        "aperture": "3.0m×1.5m 平面阵", "elements": 2048,
        "modes": ["多波束", "波束跳变", "在轨重构"],
        "heritage": 3, "heritage_desc": "飞行继承", "vendor": "INT-国际/国内并列", "beam_num": 64,
    },
    {
        "model": "ANT-REFL-KA-25", "name": "Ka 频段 2.5m 单反射面天线",
        "type": "反射面(固定)", "band": "Ka",
        "eirp_cap_dbw": 58.0, "gt_dbk": 14.0, "mass_kg": 95.0, "power_w": 150.0,
        "aperture": "Φ2.5m 碳纤维反射面", "elements": 0,
        "modes": ["单波束", "多波束"],
        "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "INT-国际", "beam_num": 4,
    },
    {
        "model": "ANT-REFL-KA-RA", "name": "Ka 频段可展开反射阵天线",
        "type": "反射阵(展开式)", "band": "Ka",
        "eirp_cap_dbw": 60.0, "gt_dbk": 13.0, "mass_kg": 260.0, "power_w": 320.0,
        "aperture": "Φ4.5m 展开反射阵", "elements": 0,
        "modes": ["多波束", "在轨重构"],
        "heritage": 2, "heritage_desc": "货架（在研转货架）", "vendor": "CN-国内", "beam_num": 32,
    },
    {
        "model": "ANT-REFL-KU-30", "name": "Ku 频段 3m 单反射面天线",
        "type": "反射面(固定)", "band": "Ku",
        "eirp_cap_dbw": 56.0, "gt_dbk": 8.5, "mass_kg": 85.0, "power_w": 120.0,
        "aperture": "Φ3.0m 碳纤维反射面", "elements": 0,
        "modes": ["单波束", "多波束"],
        "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内", "beam_num": 2,
    },
    {
        "model": "ANT-HORN-C-OMNI", "name": "C 频段全向喇叭天线",
        "type": "喇叭", "band": "C",
        "eirp_cap_dbw": 32.0, "gt_dbk": -2.0, "mass_kg": 12.0, "power_w": 40.0,
        "aperture": "全向喇叭", "elements": 0,
        "modes": ["单波束"],
        "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内", "beam_num": 1,
    },
    {
        "model": "ANT-HELIX-S-TTC", "name": "S 频段测控螺旋天线",
        "type": "螺旋", "band": "S",
        "eirp_cap_dbw": 24.0, "gt_dbk": -4.0, "mass_kg": 6.0, "power_w": 25.0,
        "aperture": "四臂螺旋", "elements": 0,
        "modes": ["单波束"],
        "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内", "beam_num": 1,
    },
    {
        "model": "ANT-OPT-ISL", "name": "星间激光通信终端光学天线",
        "type": "光学", "band": "激光",
        "eirp_cap_dbw": 105.0, "gt_dbk": 118.0, "mass_kg": 45.0, "power_w": 350.0,
        "aperture": "Φ135mm 卡塞格林", "elements": 0,
        "modes": ["单波束", "在轨重构"],
        "heritage": 3, "heritage_desc": "飞行继承", "vendor": "INT-国际", "beam_num": 1,
    },
]

# ============================================================
# 单机货架库
# ============================================================

CATALOG_EQUIPMENT: List[dict] = [
    {"model": "LNA-KA-01", "name": "Ka 频段低噪声放大器", "cat": "LNA", "band": "Ka",
     "gain_db": 40.0, "nf_db": 1.6, "mass_kg": 2.5, "power_w": 28.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "LNA-KU-01", "name": "Ku 频段低噪声放大器", "cat": "LNA", "band": "Ku",
     "gain_db": 45.0, "nf_db": 1.2, "mass_kg": 2.2, "power_w": 25.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "LNA-L-01", "name": "L 频段低噪声放大器", "cat": "LNA", "band": "L",
     "gain_db": 50.0, "nf_db": 0.8, "mass_kg": 1.8, "power_w": 20.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "SSPA-KA-60", "name": "Ka 频段 60W GaN 固态功放", "cat": "SSPA", "band": "Ka",
     "p_out_w": 60.0, "gain_db": 55.0, "eff_pct": 32.0, "mass_kg": 6.5, "power_w": 240.0,
     "heritage": 3, "heritage_desc": "飞行继承", "vendor": "GAL-银河航天"},
    {"model": "SSPA-KU-40", "name": "Ku 频段 40W GaN 固态功放", "cat": "SSPA", "band": "Ku",
     "p_out_w": 40.0, "gain_db": 52.0, "eff_pct": 35.0, "mass_kg": 5.2, "power_w": 165.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "SSPA-L-40", "name": "L 频段 40W GaN 固态功放", "cat": "SSPA", "band": "L",
     "p_out_w": 40.0, "gain_db": 48.0, "eff_pct": 45.0, "mass_kg": 4.0, "power_w": 110.0,
     "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "TWTA-KU-250", "name": "Ku 频段 250W 行波管功放", "cat": "TWTA", "band": "Ku",
     "p_out_w": 250.0, "gain_db": 52.0, "eff_pct": 62.0, "mass_kg": 8.8, "power_w": 480.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "INT-国际"},
    {"model": "TWTA-KA-180", "name": "Ka 频段 180W 行波管功放", "cat": "TWTA", "band": "Ka",
     "p_out_w": 180.0, "gain_db": 50.0, "eff_pct": 58.0, "mass_kg": 9.5, "power_w": 420.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "INT-国际"},
    {"model": "DCONV-KAKU-01", "name": "Ka/Ku 下变频器", "cat": "DCONV", "band": "Ka/Ku",
     "gain_db": 10.0, "mass_kg": 3.0, "power_w": 45.0,
     "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "UCONV-KAKU-01", "name": "Ka/Ku 上变频器", "cat": "UCONV", "band": "Ka/Ku",
     "gain_db": 10.0, "mass_kg": 3.2, "power_w": 48.0,
     "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "IMUX-OMUX-KA-16", "name": "Ka 16 通道输入/输出多工器", "cat": "OMUX", "band": "Ka",
     "channels": 16, "mass_kg": 18.0, "power_w": 0.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "INT-国际"},
    {"model": "MPA-8X8-KA", "name": "Ka 8×8 多功放矩阵", "cat": "MPA", "band": "Ka",
     "channels": 8, "mass_kg": 42.0, "power_w": 320.0,
     "heritage": 3, "heritage_desc": "飞行继承（功率池单管重构）", "vendor": "INT-国际"},
    {"model": "DTP-PROC-01", "name": "数字透明处理器（DTP）", "cat": "DTP", "band": "全频段",
     "sub_bw_mhz": 4.0, "switch_gbps": 40.0, "mass_kg": 28.0, "power_w": 380.0,
     "heritage": 2, "heritage_desc": "货架（在研转货架，FlexSat 类）", "vendor": "GAL-银河航天"},
    {"model": "BCN-TX-01", "name": "信标发射机", "cat": "BCN", "band": "S",
     "p_out_w": 2.0, "mass_kg": 1.5, "power_w": 30.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "TTC-TRP-01", "name": "测控应答机", "cat": "TTC", "band": "S",
     "mass_kg": 4.5, "power_w": 55.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "SWITCH-SP8T-01", "name": "SP8T 微波开关矩阵", "cat": "SWITCH", "band": "全频段",
     "mass_kg": 2.0, "power_w": 18.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "CIRC-KA-01", "name": "Ka 频段环行器/隔离器", "cat": "CIRC", "band": "Ka",
     "mass_kg": 0.8, "power_w": 0.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "OMUX-KU-08", "name": "Ku 8 通道输入/输出多工器", "cat": "OMUX", "band": "Ku",
     "channels": 8, "mass_kg": 12.0, "power_w": 0.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "CIRC-KU-01", "name": "Ku 频段环行器/隔离器", "cat": "CIRC", "band": "Ku",
     "mass_kg": 0.9, "power_w": 0.0,
     "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "OPT-TRM-01", "name": "激光通信收发模块（ATP+DPSK）", "cat": "OPT", "band": "激光",
     "rate_gbps": 10.0, "mass_kg": 32.0, "power_w": 260.0,
     "heritage": 3, "heritage_desc": "飞行继承", "vendor": "INT-国际"},
]

# ============================================================
# 非通信载荷货架库（遥感/导航/科学）
# ============================================================
# 说明: 天线五维选型（EIRP/G/T/重量/功耗/工作模式）仅适用于通信载荷。
# 遥感/导航/科学载荷的选型判据不同（分辨率/幅宽/灵敏度等），单列目录。

CATALOG_RS_PAYLOADS: List[dict] = [
    {"model": "RS-PAN-05", "name": "0.5m 全色相机", "cat": "光学遥感", "subtype": "全色",
     "resolution_m": 0.5, "swath_km": 12.0, "mass_kg": 95.0, "power_w": 280.0,
     "data_rate_mbps": 900.0, "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "RS-PAN-20", "name": "2m 全色相机", "cat": "光学遥感", "subtype": "全色",
     "resolution_m": 2.0, "swath_km": 45.0, "mass_kg": 60.0, "power_w": 180.0,
     "data_rate_mbps": 450.0, "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "RS-MS-20", "name": "8m 多光谱相机", "cat": "光学遥感", "subtype": "多光谱",
     "resolution_m": 8.0, "swath_km": 60.0, "mass_kg": 55.0, "power_w": 160.0,
     "data_rate_mbps": 400.0, "heritage": 4, "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "RS-SAR-X-1", "name": "X 频段 SAR（1m）", "cat": "微波遥感", "subtype": "SAR",
     "resolution_m": 1.0, "swath_km": 10.0, "mass_kg": 180.0, "power_w": 1200.0,
     "data_rate_mbps": 900.0, "heritage": 3, "heritage_desc": "飞行继承", "vendor": "INT-国际"},
    {"model": "RS-SAR-C-3", "name": "C 频段 SAR（3m）", "cat": "微波遥感", "subtype": "SAR",
     "resolution_m": 3.0, "swath_km": 20.0, "mass_kg": 150.0, "power_w": 900.0,
     "data_rate_mbps": 600.0, "heritage": 3, "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "RS-HYP-30", "name": "30m 高光谱成像仪", "cat": "光学遥感", "subtype": "高光谱",
     "resolution_m": 30.0, "swath_km": 60.0, "mass_kg": 70.0, "power_w": 200.0,
     "data_rate_mbps": 300.0, "heritage": 2, "heritage_desc": "货架（在研转货架）", "vendor": "CN-国内"},
]

CATALOG_NAV_PAYLOADS: List[dict] = [
    {"model": "NAV-SIG-B1C", "name": "B1C/B2a 导航信号生成与放大单元", "cat": "导航",
     "bands": "L", "mass_kg": 45.0, "power_w": 320.0, "heritage": 4,
     "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
    {"model": "NAV-ANT-L12", "name": "导航 L 频段 12 单元螺旋天线阵", "cat": "导航天线",
     "bands": "L", "mass_kg": 38.0, "power_w": 40.0, "heritage": 3,
     "heritage_desc": "飞行继承", "vendor": "CN-国内"},
    {"model": "NAV-TWTA-L-60", "name": "L 频段 60W 导航行波管功放", "cat": "导航功放",
     "bands": "L", "mass_kg": 6.5, "power_w": 190.0, "heritage": 4,
     "heritage_desc": "飞行继承货架", "vendor": "CN-国内"},
]

CATALOG_SCI_PAYLOADS: List[dict] = [
    {"model": "SCI-ATM-01", "name": "大气掩星探测仪", "cat": "科学探测",
     "mass_kg": 55.0, "power_w": 120.0, "heritage": 3, "heritage_desc": "飞行继承",
     "vendor": "CN-国内"},
    {"model": "SCI-GRV-01", "name": "重力场探测加速度计", "cat": "科学探测",
     "mass_kg": 25.0, "power_w": 60.0, "heritage": 3, "heritage_desc": "飞行继承",
     "vendor": "INT-国际"},
    {"model": "SCI-MAG-01", "name": "磁强计", "cat": "科学探测",
     "mass_kg": 8.0, "power_w": 25.0, "heritage": 4, "heritage_desc": "飞行继承货架",
     "vendor": "CN-国内"},
]

# 非通信载荷的选型判据（替代天线五要素）
NONCOMM_SELECTION_CRITERIA: Dict[str, List[dict]] = {
    "remote_sensing": [
        {"dim": "空间分辨率", "weight": 30, "action": "按任务最小可分辨目标尺寸确定（优于需求一档）"},
        {"dim": "幅宽/覆盖", "weight": 20, "action": "按重访周期与区域覆盖要求确定"},
        {"dim": "数据率与存储", "weight": 15, "action": "分辨率×幅宽×量化位数反推数传与存储容量"},
        {"dim": "重量", "weight": 15, "action": "须在平台承载内"},
        {"dim": "功耗", "weight": 10, "action": "SAR 峰值功耗远高于光学，须校核平台供电峰值"},
        {"dim": "指向精度/稳定度", "weight": 10, "action": "高分辨率要求平台侧摆能力与微振动抑制"},
    ],
    "navigation": [
        {"dim": "信号体制与频段", "weight": 30, "action": "B1C/B2a/L1/L5 等，决定天线与功放"},
        {"dim": "EIRP 与用户等效距离误差", "weight": 25, "action": "按 UERE 预算反推 EIRP"},
        {"dim": "原子钟配置", "weight": 20, "action": "铷钟/铯钟/氢钟，决定守时精度与冗余"},
        {"dim": "重量", "weight": 15, "action": "须在平台承载内"},
        {"dim": "功耗", "weight": 10, "action": "须在平台供电内"},
    ],
    "science": [
        {"dim": "探测灵敏度/精度", "weight": 35, "action": "由科学目标反推探测器指标"},
        {"dim": "观测几何与指向", "weight": 25, "action": "掩星/对日/对地决定安装与指向要求"},
        {"dim": "数据率", "weight": 15, "action": "科学数据量决定数传能力"},
        {"dim": "重量", "weight": 15, "action": "须在平台承载内"},
        {"dim": "功耗", "weight": 10, "action": "须在平台供电内"},
    ],
}

# ============================================================
# 卫星平台库
# ============================================================

SATELLITE_PLATFORMS: List[dict] = [
    {"model": "PLT-LEO-SMALL-01", "name": "小卫星平台（LEO）", "orbits": "LEO/SSO",
     "payload_mass_kg": 150.0, "payload_power_w": 800.0, "sat_mass_kg": 300.0,
     "envelope_m": 1.5, "life_years": 5, "heritage": 3, "heritage_desc": "飞行继承",
     "vendor": "GAL-银河航天"},
    {"model": "PLT-LEO-MID-02", "name": "中型低轨平台", "orbits": "LEO",
     "payload_mass_kg": 450.0, "payload_power_w": 2500.0, "sat_mass_kg": 900.0,
     "envelope_m": 2.2, "life_years": 7, "heritage": 3, "heritage_desc": "飞行继承",
     "vendor": "CN-国内"},
    {"model": "GEO-MID42", "name": "GEO 中型平台", "orbits": "GEO",
     "payload_mass_kg": 650.0, "payload_power_w": 6000.0, "sat_mass_kg": 3200.0,
     "envelope_m": 4.0, "life_years": 15, "heritage": 4, "heritage_desc": "飞行继承货架",
     "vendor": "CN-国内"},
    {"model": "GEO-LRG65", "name": "GEO 大型平台", "orbits": "GEO",
     "payload_mass_kg": 1200.0, "payload_power_w": 12000.0, "sat_mass_kg": 5800.0,
     "envelope_m": 4.6, "life_years": 15, "heritage": 4, "heritage_desc": "飞行继承货架",
     "vendor": "INT-国际"},
    {"model": "PLT-MEO-NAV-01", "name": "MEO 导航平台", "orbits": "MEO",
     "payload_mass_kg": 380.0, "payload_power_w": 1800.0, "sat_mass_kg": 1000.0,
     "envelope_m": 2.5, "life_years": 12, "heritage": 4, "heritage_desc": "飞行继承货架",
     "vendor": "CN-国内"},
    {"model": "PLT-SSO-RS-01", "name": "SSO 遥感平台", "orbits": "SSO/LEO",
     "payload_mass_kg": 300.0, "payload_power_w": 1200.0, "sat_mass_kg": 700.0,
     "envelope_m": 2.0, "life_years": 8, "heritage": 3, "heritage_desc": "飞行继承",
     "vendor": "CN-国内"},
]

# ============================================================
# 运载火箭库
# ============================================================

LAUNCH_VEHICLES: List[dict] = [
    {"name": "长征二号丁", "country": "中国", "gto_kg": None, "leo_kg": 4000.0,
     "sso_kg": 3000.0, "fairing_m": 3.35, "flights": 90, "cost_musd": 30.0},
    {"name": "长征三号乙", "country": "中国", "gto_kg": 5500.0, "leo_kg": 11200.0,
     "sso_kg": 6800.0, "fairing_m": 4.2, "flights": 100, "cost_musd": 70.0},
    {"name": "长征五号", "country": "中国", "gto_kg": 14000.0, "leo_kg": 25000.0,
     "sso_kg": 15000.0, "fairing_m": 5.2, "flights": 8, "cost_musd": 120.0},
    {"name": "长征七号甲", "country": "中国", "gto_kg": 7000.0, "leo_kg": 13500.0,
     "sso_kg": 8000.0, "fairing_m": 4.2, "flights": 6, "cost_musd": 85.0},
    {"name": "长征八号", "country": "中国", "gto_kg": 2800.0, "leo_kg": 7600.0,
     "sso_kg": 4500.0, "fairing_m": 4.2, "flights": 5, "cost_musd": 45.0},
    {"name": "捷龙三号", "country": "中国", "gto_kg": None, "leo_kg": 1500.0,
     "sso_kg": 1000.0, "fairing_m": 2.9, "flights": 3, "cost_musd": 20.0},
    {"name": "力箭一号", "country": "中国", "gto_kg": None, "leo_kg": 2000.0,
     "sso_kg": 1500.0, "fairing_m": 2.65, "flights": 3, "cost_musd": 25.0},
    {"name": "朱雀二号", "country": "中国", "gto_kg": None, "leo_kg": 4000.0,
     "sso_kg": 2500.0, "fairing_m": 3.35, "flights": 3, "cost_musd": 35.0},
    {"name": "Falcon 9", "country": "美国", "gto_kg": 8300.0, "leo_kg": 22800.0,
     "sso_kg": 13000.0, "fairing_m": 5.2, "flights": 300, "cost_musd": 67.0},
    {"name": "Falcon Heavy", "country": "美国", "gto_kg": 26700.0, "leo_kg": 63800.0,
     "sso_kg": 30000.0, "fairing_m": 5.2, "flights": 10, "cost_musd": 97.0},
    {"name": "Ariane 6", "country": "欧洲", "gto_kg": 11500.0, "leo_kg": 21600.0,
     "sso_kg": 13000.0, "fairing_m": 5.4, "flights": 3, "cost_musd": 90.0},
    {"name": "New Glenn", "country": "美国", "gto_kg": 13000.0, "leo_kg": 45000.0,
     "sso_kg": 25000.0, "fairing_m": 7.0, "flights": 1, "cost_musd": 110.0},
]

# ============================================================
# 转发体制模板
# ============================================================

ARCH_TEMPLATES: Dict[str, dict] = {
    "transparent": {
        "name": "透明转发 (Bent-Pipe)",
        "desc": "星上仅做变频与放大，不做解调。技术成熟、成本低、时延小。",
        "chain": ["接收天线", "LNA", "下变频 DCONV", "IMUX", "TWTA/SSPA", "OMUX", "上变频 UCONV", "发射天线"],
        "pros": ["技术成熟度最高", "成本最低", "星上处理时延小"],
        "cons": ["波束固定、灵活性差", "噪声全链路累积", "无星上交换能力"],
        "适用": "固定业务广播、传统 VSAT、成熟轨道位",
    },
    "regenerative": {
        "name": "处理转发 (星上再生)",
        "desc": "星上完成解调/解码/交换/再调制，噪声不累积，可星上路由。",
        "chain": ["接收天线", "LNA", "下变频", "解调译码", "星上交换/路由", "调制编码", "上变频", "SSPA", "发射天线"],
        "pros": ["链路余量提升 3-6 dB", "支持星上交换与路由", "抗干扰能力强"],
        "cons": ["复杂度高、功耗大", "体制升级需换星", "研制周期长"],
        "适用": "军事/抗干扰、星上组网、需星间路由场景",
    },
    "dtp": {
        "name": "柔性载荷 (DTP 数字透明处理)",
        "desc": "数字信道化 + 星上交换矩阵，波束/带宽/功率可在轨重构。",
        "chain": ["接收天线", "LNA", "下变频", "ADC/数字信道化", "交换矩阵", "DAC", "上变频", "MPA 功率池", "发射天线"],
        "pros": ["波束与功率在轨重构", "子带级灵活调度", "功率池单管故障可重构"],
        "cons": ["功耗与质量代价高", "算法与硬件耦合复杂", "货架化程度仍在提升"],
        "适用": "商业航天批产、多任务复用、需求频繁变更场景",
    },
}

# ============================================================
# 天线五要素选型依据
# ============================================================

ANTENNA_SELECTION_CRITERIA: List[dict] = [
    {"dim": "EIRP", "weight": 30, "formula": "EIRP = 功放输出(dBW) + 天线增益(dBi) − 馈电损耗(dB)",
     "action": "反推所需口径或阵元数"},
    {"dim": "G/T", "weight": 25, "formula": "G/T = 接收增益(dBi) − 10lg(系统噪声温度 K)",
     "action": "确定接收构型与 LNA 噪声系数分配"},
    {"dim": "重量", "weight": 20, "formula": "m_antenna ≤ m_平台承载 − m_其他载荷 − 裕度",
     "action": "超限则改展开式（伞状/环形桁架/反射阵）"},
    {"dim": "功耗", "weight": 15, "formula": "P = P_功放 + P_波束赋形 + P_展开机构",
     "action": "超限则降功放效率或改 MPA 功率池"},
    {"dim": "工作模式", "weight": 10, "formula": "单波束/多波束/波束跳变/在轨重构",
     "action": "重构需求→相控阵或反射阵；固定覆盖→反射面"},
]

# ============================================================
# 行业标准索引
# ============================================================

INDUSTRY_STANDARDS: Dict[str, str] = {
    "ITU": "ITU-R S.1528（链路预算等效限值）、ITU-R S.1323（卫星天线方向图）、ITU-R S.466（频率指配）",
    "ESA": "ECSS-E-ST-50-05C（通信链路设计）、ECSS-Q-ST-70C（载荷环境试验）、ECSS-E-ST-20C（电磁兼容）",
    "CCSDS": "CCSDS 131.0-B（TM/TC 同步与信道编码）、CCSDS 401.0-B（射频调制与解调）",
    "MIL": "MIL-STD-461（电磁兼容）、MIL-STD-810（环境试验）、MIL-PRF-38534（混合集成电路）",
    "GJB": "GJB 151B（电磁兼容）、GJB 150A（环境试验）、GJB 899A（可靠性鉴定）",
    "天线": "面精度 RMS ≤ λ/32（Ka 约 0.27mm）、旁瓣 ≤ −20dB、轴比 ≤ 3dB",
    "链路预算": "C/N 余量 ≥ 3 dB（含雨衰/极化失配/指向损耗）、EIRP/G/T 逐链路核算",
    "激光": "ATP 捕获概率 ≥ 95%、跟踪精度 ≤ 1 μrad、DPSK 灵敏度优于 OOK 约 6 dB",
    "热控": "行波管 −10~+55℃、LNA −40~+70℃、相控阵 T/R 组件结温 ≤ 125℃",
    "电磁兼容": "舱内隔离 ≥ 80dB、收发隔离 ≥ 100dB、频段间加滤波与屏蔽",
    "可靠性": "载荷 MTBF ≥ 15 年（GEO）、单点故障零容忍、关键单机 A/B 冷备或环备份",
    "抗辐射": "GEO 总剂量 ≥ 100 krad(Si)、单粒子翻转需 EDAC、锁流需自恢复设计",
}


def get_catalog_summary() -> dict:
    """产品库规模概览（用于自检与前端展示）"""
    def by_heritage(items):
        d = {4: 0, 3: 0, 2: 0, 1: 0}
        for it in items:
            d[it.get("heritage", 1)] = d.get(it.get("heritage", 1), 0) + 1
        return d

    return {
        "天线": {"count": len(CATALOG_ANTENNAS), "models": [a["model"] for a in CATALOG_ANTENNAS],
               "by_heritage": by_heritage(CATALOG_ANTENNAS)},
        "单机": {"count": len(CATALOG_EQUIPMENT), "models": [e["model"] for e in CATALOG_EQUIPMENT],
               "by_heritage": by_heritage(CATALOG_EQUIPMENT)},
        "平台": {"count": len(SATELLITE_PLATFORMS),
               "models": [p["model"] for p in SATELLITE_PLATFORMS]},
        "运载": {"count": len(LAUNCH_VEHICLES),
               "models": [l["name"] for l in LAUNCH_VEHICLES]},
        "转发体制": list(ARCH_TEMPLATES.keys()),
        "频段": list(FREQUENCY_BANDS.keys()),
        "遥感载荷": {"count": len(CATALOG_RS_PAYLOADS),
                   "models": [x["model"] for x in CATALOG_RS_PAYLOADS]},
        "导航载荷": {"count": len(CATALOG_NAV_PAYLOADS),
                   "models": [x["model"] for x in CATALOG_NAV_PAYLOADS]},
        "科学载荷": {"count": len(CATALOG_SCI_PAYLOADS),
                   "models": [x["model"] for x in CATALOG_SCI_PAYLOADS]},
        "标准条目": len(INDUSTRY_STANDARDS),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_catalog_summary(), ensure_ascii=False, indent=2))
