# -*- coding: utf-8 -*-
"""通信卫星有效载荷方案设计软件 —— 设计数据层。

与 payload-design skill 对齐：
  · 三级选型闭环：载荷方案(天线+转发器) → 平台选型 → 运载火箭选型
  · 天线五维选型：EIRP / G/T / 重量 / 功耗 / 工作模式（+ 频段硬过滤）
  · 单机货架优先：货架产品(飞行继承) > 飞行继承产品 > 货架产品(在研转货架) > 定制
  · 链路校核：C/N 余量 ≥ 3dB 逐链路核算，不通过返回架构调整

内容：
  ORBITS         : 轨道库（几何/覆盖/典型参数）
  COVERAGE       : 覆盖区库（几何/链路余量/波束密度）
  SERVICES       : 业务类型库（容量/终端/EIRP·G/T 需求）
  MODES          : 转发体制库（透明/数字透明DTP/再生处理）
  ANT_TYPES      : 天线类型库（固面/相控阵/伞状可展开）
  ARRAY_SUBTYPES : 相控阵子体制库（直射阵/反射阵/数字模拟混合/纯数字/模拟拼接）
  SHELF_UNITS    : 单机货架库（三线编号：GAL 银河航天 / CN 国内 / INT 国际）
  UNIT_PRINCIPLES: 单机/载荷功能原理介绍
  PLATFORMS      : 平台库（承载/供电/整星质量/寿命）
  LAUNCHERS      : 运载火箭库（LEO/GTO 能力/整流罩）
  SCENARIOS      : 场景预设库
"""
from __future__ import annotations
import math

# ================================================================
# 一、轨道库
# ================================================================
# 斜距公式（用户最低仰角 el，地球半径 R=6371km）：
#   d = sqrt(R² + 2Rh + h² − R²cos²(el)) − R·cos(el)
#   最大地心覆盖角 θ_cov = arccos(R·cos(el)/(R+h)) − el
#   星下点覆盖半径 r ≈ R·θ_cov(rad)；对地张角 α = 2·asin(R·sin(θ_cov+el)/(R+h))

ORBITS = {
    "GEO": dict(cn="地球静止轨道", alt_km=35786, period_min=1436,
                vel_kms=3.07, ecl_deg=0, d_max_km=41660,
                d_30_km=37500, d_20_km=40500, d_10_km=41300,
                cov_deg=17.3, cov_r_km=16200, alpha_deg=17.3,
                isl_need="星座组网可选（同轨位间隔大，星间微波/激光用于天基组网）",
                isl_typical="激光 10~20Gbps 同轨互联（可选）",
                life_yr=15, launch="GTO 转移 + 星上变轨",
                note="对地静止、全天候连续覆盖单区；大容量宽带/广播首选；斜距大(≈38000km)雨衰与时延大(单跳≈250ms)"),
    "MEO": dict(cn="中地球轨道", alt_km=8000, period_min=287,
                vel_kms=5.6, ecl_deg=0, d_max_km=12500,
                d_30_km=9200, d_20_km=10600, d_10_km=11600,
                cov_deg=54.0, cov_r_km=6000, alpha_deg=76.0,
                isl_need="建议组网（导航增强/连续覆盖星座）",
                isl_typical="激光 5~10Gbps 星间组网",
                life_yr=12, launch="直接入轨或 GTO 转移",
                note="介于 GEO/LEO：覆盖大、时延中(单跳≈60ms)、组网规模小；O3b mPOWER 代表"),
    "LEO": dict(cn="低地球轨道", alt_km=550, period_min=95.6,
                vel_kms=7.58, ecl_deg=0, d_max_km=2100,
                d_30_km=1200, d_20_km=1550, d_10_km=1800,
                cov_deg=20.0, cov_r_km=2200, alpha_deg=44.0,
                isl_need="必须组网（单星覆盖不连续）",
                isl_typical="激光 10~20Gbps 同轨/异轨 + 星地馈电",
                life_yr=7, launch="直接入轨（一箭多星）",
                note="低时延(单跳<10ms)、低路径损耗；需星座组网+波束跳变/DTP 柔性；批产降本核心场景"),
    "SSO": dict(cn="太阳同步轨道", alt_km=700, period_min=98.8,
                vel_kms=7.5, ecl_deg=98.2, d_max_km=2300,
                d_30_km=1300, d_20_km=1700, d_10_km=1950,
                cov_deg=21.5, cov_r_km=2400, alpha_deg=47.0,
                isl_need="可选组网（数传中继/星间接力）",
                isl_typical="激光 2~10Gbps 星间数传接力",
                life_yr=8, launch="直接入轨",
                note="回归周期固定、光照条件一致；多用于遥感，通信上用于数传中继与物联网星座"),
    "HEO": dict(cn="大椭圆轨道（Molniya/Tundra）", alt_km=39500, period_min=720,
                vel_kms=1.5, ecl_deg=63.4, d_max_km=40000,
                d_30_km=34000, d_20_km=37000, d_10_km=38500,
                cov_deg=24.0, cov_r_km=2700, alpha_deg=30.0,
                isl_need="可选（远地点星间链路）",
                isl_typical="激光/微波 远地点互联",
                life_yr=10, launch="GTO/Molniya 转移",
                note="远地点驻留时间长，高纬度覆盖优于 GEO；天线需自动跟踪指向（程序控制指向机构）"),
}
ORBIT_KEYS = ["GEO", "MEO", "LEO", "SSO", "HEO"]

# ================================================================
# 二、覆盖区库
# ================================================================
COVERAGE = {
    "全球": dict(cn="全球覆盖", r_km=20037, beam_r_km=250, k_typ=4,
                 margin_add_db=0.0, el_min_deg=20,
                 note="需多星组网（GEO 单星仅覆盖 42% 地表）或大张角波束；链路取最小仰角最差路径"),
    "中国全境": dict(cn="中国全境覆盖", r_km=2600, beam_r_km=300, k_typ=4,
                 margin_add_db=0.0, el_min_deg=35,
                 note="东西跨度约 5200km；GEO 单星多波束可覆盖；高仰角、雨衰可控"),
    "区域": dict(cn="区域覆盖（约3000km）", r_km=1500, beam_r_km=250, k_typ=4,
                 margin_add_db=0.3, el_min_deg=30,
                 note="典型高通量点波束覆盖区；频率复用增益高"),
    "省域": dict(cn="省域覆盖（约800km）", r_km=400, beam_r_km=150, k_typ=4,
                 margin_add_db=0.5, el_min_deg=35,
                 note="高增益窄波束；容量密度最高"),
    "热点小区": dict(cn="热点小区（约200km）", r_km=100, beam_r_km=100, k_typ=7,
                 margin_add_db=0.8, el_min_deg=40,
                 note="超窄波束+高频复用；适合 D2D/城市热点"),
    "航空航海走廊": dict(cn="航空/航海走廊（动态覆盖）", r_km=3000, beam_r_km=300, k_typ=4,
                 margin_add_db=1.0, el_min_deg=25,
                 note="目标高速移动，需波束跳变与快速指向；仰角变化大、链路余量须加 1dB"),
    "极区": dict(cn="极区覆盖", r_km=2000, beam_r_km=250, k_typ=4,
                 margin_add_db=1.5, el_min_deg=15,
                 note="GEO 不可见/低仰角；HEO 或 LEO 星座承担；链路余量须加 1.5dB"),
    "巴基斯坦": dict(cn="巴基斯坦全境覆盖", r_km=800, beam_r_km=400, k_typ=4,
                     margin_add_db=0.3, el_min_deg=46,
                     note="国土南北约 1450km（纬 24~37°N）、东西约 1550km（经 61~77°E），等效覆盖半径约 800km；"
                          "GEO 星位建议 65~75°E。关键几何：GEO 可见地盘仅 ±8.69°（离天底角），"
                          "覆盖巴基斯坦全境只需电扫约 ±6°（中心纬偏 30° 被 35786km 高轨压缩到 4.8°，边缘 6.0°），"
                          "扫描损耗 cos^1.5(6°)≈0.04dB 可忽略；全境用户仰角 46~61°（最低在 37°N 边角）；"
                          "雨衰区 ITU-R P.618 中等（Ka 参考雨衰 12/7dB@0.01%，@99.5% 约 0.8/0.5dB）"),
    "自定义": dict(cn="自定义覆盖区", r_km=1500, beam_r_km=250, k_typ=4,
                   margin_add_db=0.0, el_min_deg=30,
                   note="用户自填覆盖半径与波束半径"),
}
COVERAGE_KEYS = ["全球", "中国全境", "区域", "省域", "热点小区", "航空航海走廊", "极区", "巴基斯坦", "自定义"]

# ================================================================
# 二·B 全球国家/地区覆盖库（覆盖区可选全球国家）
#   lat/lon：国土几何中心；r_km：等效覆盖半径（国土外接圆半径）；
#   beam_r_km：建议点波束半径；geo_lon：GEO 推荐星位（就近弧段）；
#   el_min：GEO 星位下国土最低用户仰角（近似）；rain：ITU-R P.618 雨衰区备注。
#   运行时由 design_engine.country_coverage() 合成 COVERAGE 同构条目。
# ================================================================
COUNTRIES = [
    # ---- 亚太 ----
    dict(key="中国",       cn="中国",        lat=35.0,  lon=105.0, r_km=2600, beam_r_km=300, geo_lon=105, el_min=35, rain="中等（Ka 7~12dB@0.01%）", k_typ=4, region="亚太"),
    dict(key="巴基斯坦",   cn="巴基斯坦",    lat=30.5,  lon=69.5,  r_km=800,  beam_r_km=400, geo_lon=69,  el_min=46, rain="中等偏干（北部干燥）", k_typ=4, region="亚太"),
    dict(key="印度",       cn="印度",        lat=22.0,  lon=79.0,  r_km=1600, beam_r_km=300, geo_lon=79,  el_min=40, rain="强（季风区，Ka 10~15dB@0.01%）", k_typ=4, region="亚太"),
    dict(key="印度尼西亚", cn="印度尼西亚",  lat=-2.5,  lon=118.0, r_km=2600, beam_r_km=300, geo_lon=118, el_min=45, rain="极强（赤道雨衰区，Ka 15~20dB@0.01%）", k_typ=4, region="亚太"),
    dict(key="泰国",       cn="泰国",        lat=15.5,  lon=101.0, r_km=850,  beam_r_km=250, geo_lon=101, el_min=50, rain="强（季风）", k_typ=4, region="亚太"),
    dict(key="越南",       cn="越南",        lat=16.0,  lon=107.0, r_km=900,  beam_r_km=250, geo_lon=107, el_min=48, rain="强（季风）", k_typ=4, region="亚太"),
    dict(key="马来西亚",   cn="马来西亚",    lat=4.0,   lon=109.0, r_km=1100, beam_r_km=250, geo_lon=109, el_min=55, rain="极强（赤道）", k_typ=4, region="亚太"),
    dict(key="菲律宾",     cn="菲律宾",      lat=12.0,  lon=123.0, r_km=950,  beam_r_km=250, geo_lon=123, el_min=50, rain="极强（台风+赤道）", k_typ=4, region="亚太"),
    dict(key="新加坡",     cn="新加坡",      lat=1.35,  lon=103.8, r_km=30,   beam_r_km=30,  geo_lon=104, el_min=60, rain="极强（赤道）", k_typ=7, region="亚太"),
    dict(key="日本",       cn="日本",        lat=36.5,  lon=138.0, r_km=1100, beam_r_km=250, geo_lon=138, el_min=40, rain="强（梅雨/台风）", k_typ=4, region="亚太"),
    dict(key="韩国",       cn="韩国",        lat=36.5,  lon=127.8, r_km=300,  beam_r_km=150, geo_lon=128, el_min=42, rain="中等", k_typ=4, region="亚太"),
    dict(key="蒙古",       cn="蒙古",        lat=46.5,  lon=103.0, r_km=1200, beam_r_km=400, geo_lon=103, el_min=28, rain="弱（干燥大陆）", k_typ=4, region="亚太"),
    dict(key="哈萨克斯坦", cn="哈萨克斯坦",  lat=48.0,  lon=67.0,  r_km=1500, beam_r_km=400, geo_lon=67,  el_min=27, rain="弱（干燥）", k_typ=4, region="亚太"),
    dict(key="乌兹别克斯坦", cn="乌兹别克斯坦", lat=41.5, lon=64.0, r_km=700,  beam_r_km=250, geo_lon=64,  el_min=36, rain="弱（干燥）", k_typ=4, region="亚太"),
    dict(key="伊朗",       cn="伊朗",        lat=32.5,  lon=54.5,  r_km=1300, beam_r_km=300, geo_lon=54,  el_min=40, rain="弱~中（干旱高原）", k_typ=4, region="中东"),
    dict(key="沙特阿拉伯", cn="沙特阿拉伯",  lat=24.0,  lon=45.0,  r_km=1400, beam_r_km=300, geo_lon=45,  el_min=45, rain="弱（沙漠）", k_typ=4, region="中东"),
    dict(key="阿联酋",     cn="阿联酋",      lat=24.0,  lon=54.0,  r_km=350,  beam_r_km=150, geo_lon=54,  el_min=48, rain="弱（沙漠）", k_typ=4, region="中东"),
    dict(key="土耳其",     cn="土耳其",      lat=39.0,  lon=35.5,  r_km=800,  beam_r_km=250, geo_lon=36,  el_min=38, rain="中等", k_typ=4, region="中东"),
    dict(key="以色列",     cn="以色列",      lat=31.5,  lon=35.0,  r_km=240,  beam_r_km=120, geo_lon=35,  el_min=45, rain="弱~中", k_typ=7, region="中东"),
    dict(key="澳大利亚",   cn="澳大利亚",    lat=-25.5, lon=134.0, r_km=2200, beam_r_km=350, geo_lon=134, el_min=35, rain="弱~中（内陆干燥）", k_typ=4, region="亚太"),
    dict(key="新西兰",     cn="新西兰",      lat=-41.0, lon=173.0, r_km=850,  beam_r_km=250, geo_lon=173, el_min=28, rain="中等", k_typ=4, region="亚太"),
    # ---- 欧洲 ----
    dict(key="英国",       cn="英国",        lat=53.5,  lon=-1.5,  r_km=500,  beam_r_km=180, geo_lon=0,   el_min=26, rain="中等（温带海洋）", k_typ=4, region="欧洲"),
    dict(key="法国",       cn="法国",        lat=46.5,  lon=2.5,   r_km=550,  beam_r_km=200, geo_lon=3,   el_min=28, rain="中等", k_typ=4, region="欧洲"),
    dict(key="德国",       cn="德国",        lat=51.0,  lon=10.0,  r_km=450,  beam_r_km=180, geo_lon=10,  el_min=26, rain="中等", k_typ=4, region="欧洲"),
    dict(key="意大利",     cn="意大利",      lat=42.8,  lon=12.5,  r_km=600,  beam_r_km=200, geo_lon=13,  el_min=30, rain="中等", k_typ=4, region="欧洲"),
    dict(key="西班牙",     cn="西班牙",      lat=40.0,  lon=-3.7,  r_km=650,  beam_r_km=220, geo_lon=0,   el_min=32, rain="弱~中", k_typ=4, region="欧洲"),
    dict(key="俄罗斯",     cn="俄罗斯（欧洲+西伯利亚）", lat=60.0, lon=90.0, r_km=3000, beam_r_km=500, geo_lon=90, el_min=18, rain="弱（高纬）", k_typ=4, region="欧洲"),
    dict(key="乌克兰",     cn="乌克兰",      lat=49.0,  lon=32.0,  r_km=700,  beam_r_km=250, geo_lon=32,  el_min=27, rain="中等", k_typ=4, region="欧洲"),
    dict(key="波兰",       cn="波兰",        lat=52.0,  lon=19.5,  r_km=350,  beam_r_km=160, geo_lon=19,  el_min=25, rain="中等", k_typ=4, region="欧洲"),
    dict(key="瑞典",       cn="瑞典",        lat=62.0,  lon=16.0,  r_km=850,  beam_r_km=250, geo_lon=16,  el_min=18, rain="弱（高纬）", k_typ=4, region="欧洲"),
    # ---- 非洲 ----
    dict(key="埃及",       cn="埃及",        lat=26.5,  lon=30.0,  r_km=650,  beam_r_km=250, geo_lon=30,  el_min=45, rain="极弱（沙漠）", k_typ=4, region="非洲"),
    dict(key="尼日利亚",   cn="尼日利亚",    lat=9.5,   lon=8.0,   r_km=800,  beam_r_km=250, geo_lon=8,   el_min=55, rain="强（热带）", k_typ=4, region="非洲"),
    dict(key="南非",       cn="南非",        lat=-29.0, lon=25.0,  r_km=1100, beam_r_km=300, geo_lon=25,  el_min=35, rain="弱~中", k_typ=4, region="非洲"),
    dict(key="肯尼亚",     cn="肯尼亚",      lat=0.5,   lon=37.5,  r_km=600,  beam_r_km=220, geo_lon=38,  el_min=60, rain="强（赤道）", k_typ=4, region="非洲"),
    dict(key="阿尔及利亚", cn="阿尔及利亚",  lat=28.0,  lon=2.5,   r_km=1100, beam_r_km=350, geo_lon=3,   el_min=42, rain="极弱（撒哈拉）", k_typ=4, region="非洲"),
    dict(key="埃塞俄比亚", cn="埃塞俄比亚",  lat=9.0,   lon=39.5,  r_km=850,  beam_r_km=280, geo_lon=40,  el_min=50, rain="中等（高原）", k_typ=4, region="非洲"),
    dict(key="摩洛哥",     cn="摩洛哥",      lat=31.5,  lon=-6.5,  r_km=650,  beam_r_km=220, geo_lon=8,   el_min=45, rain="弱~中", k_typ=4, region="非洲"),
    # ---- 美洲 ----
    dict(key="美国本土",   cn="美国（本土48州）", lat=39.5, lon=-98.5, r_km=2300, beam_r_km=350, geo_lon=-99, el_min=30, rain="中等（东南部强）", k_typ=4, region="美洲"),
    dict(key="加拿大",     cn="加拿大",      lat=58.0,  lon=-96.0, r_km=2500, beam_r_km=450, geo_lon=-96, el_min=18, rain="弱（高纬）", k_typ=4, region="美洲"),
    dict(key="巴西",       cn="巴西",        lat=-10.5, lon=-53.0, r_km=2100, beam_r_km=350, geo_lon=-53, el_min=45, rain="极强（亚马逊赤道区）", k_typ=4, region="美洲"),
    dict(key="墨西哥",     cn="墨西哥",      lat=23.5,  lon=-102.0, r_km=1500, beam_r_km=300, geo_lon=-102, el_min=45, rain="中等", k_typ=4, region="美洲"),
    dict(key="阿根廷",     cn="阿根廷",      lat=-34.5, lon=-64.0, r_km=1900, beam_r_km=350, geo_lon=-64, el_min=28, rain="中等", k_typ=4, region="美洲"),
    dict(key="智利",       cn="智利",        lat=-33.0, lon=-71.0, r_km=2100, beam_r_km=250, geo_lon=-71, el_min=35, rain="弱（北段极干燥）", k_typ=4, region="美洲"),
    dict(key="秘鲁",       cn="秘鲁",        lat=-9.5,  lon=-75.0, r_km=1000, beam_r_km=280, geo_lon=-75, el_min=50, rain="中等（安第斯/雨林）", k_typ=4, region="美洲"),
    dict(key="哥伦比亚",   cn="哥伦比亚",    lat=4.0,   lon=-74.0, r_km=1000, beam_r_km=280, geo_lon=-74, el_min=58, rain="极强（赤道）", k_typ=4, region="美洲"),
    # ---- 跨区/特殊 ----
    dict(key="一带一路沿线", cn="一带一路沿线（亚太+中东+非洲）", lat=25.0, lon=85.0, r_km=4500, beam_r_km=400, geo_lon=85, el_min=25, rain="混合（需分区设计）", k_typ=4, region="跨区"),
    dict(key="东南亚全域", cn="东南亚全域",  lat=5.0,   lon=110.0, r_km=2600, beam_r_km=300, geo_lon=110, el_min=40, rain="极强（赤道雨衰主导）", k_typ=4, region="亚太"),
    dict(key="中东全域",   cn="中东全域",    lat=28.0,  lon=45.0,  r_km=2000, beam_r_km=300, geo_lon=45,  el_min=38, rain="弱（沙漠为主）", k_typ=4, region="中东"),
    dict(key="非洲全域",   cn="非洲全域",    lat=5.0,   lon=20.0,  r_km=3800, beam_r_km=400, geo_lon=20,  el_min=35, rain="混合（赤道强/沙漠弱）", k_typ=4, region="非洲"),
    dict(key="拉美全域",   cn="拉美全域",    lat=-15.0, lon=-60.0, r_km=3800, beam_r_km=400, geo_lon=-60, el_min=30, rain="混合", k_typ=4, region="美洲"),
    dict(key="欧洲全域",   cn="欧洲全域",    lat=50.0,  lon=15.0,  r_km=2000, beam_r_km=280, geo_lon=15,  el_min=22, rain="中等", k_typ=4, region="欧洲"),
    dict(key="北极航道",   cn="北极航道（高纬）", lat=72.0, lon=100.0, r_km=2500, beam_r_km=400, geo_lon=100, el_min=10, rain="弱；GEO 低仰角→建议 HEO/LEO", k_typ=4, region="跨区"),
]
COUNTRY_KEYS = [c["key"] for c in COUNTRIES]
COUNTRY_BY_KEY = {c["key"]: c for c in COUNTRIES}

# ================================================================
# 三、业务类型库
# ================================================================
# design_cn: 需求推导的名义设计点 (C/N)_req（dB）——高阶调制业务取 10dB（16/32APSK 类），
#            低阶调制业务（广播/手持/物联网）取 5dB（QPSK~8PSK 类）
SERVICES = {
    "高通量宽带": dict(cn="高通量宽带接入（HTS）", C_gbps=40, N_term=10000,
                      GT_term=17.0, EIRP_term=60.0, avail=99.9, design_cn=10.0,
                      note="多波束+频率复用；终端 VSAT/相控阵平板天线（0.74m 级 G/T≈17~20dB/K）；Ka/Q/V 频段为主；单载波 SCPC 小带宽"),
    "广播电视": dict(cn="广播电视（DTH）", C_gbps=0.05, N_term=1000000,
                    GT_term=5.0, EIRP_term=72.0, avail=99.8, design_cn=5.0,
                    note="单波束大区覆盖；Ku/C 频段；终端 0.45~0.6m 天线 G/T≈5dB/K；单转发器 36MHz 容量约 60Mbps"),
    "移动通信": dict(cn="移动通信（L/S 手持）", C_gbps=0.3, N_term=100000,
                      GT_term=-12.0, EIRP_term=55.0, avail=99.5, design_cn=5.0,
                      note="手持终端 G/T≈-12dB/K；大口径伞天线（12m 级 G≈43dBi@L）；单载波窄带（语音 25kHz~数据 100kHz）；L 频段 34MHz 指配下整星容量 0.3~0.4Gbps 量级（天通同类）"),
    "手机直连D2D": dict(cn="手机直连（D2D）", C_gbps=0.5, N_term=1000000,
                      GT_term=-16.0, EIRP_term=50.0, avail=99.0, design_cn=5.0,
                      note="存量手机直连；超大口径可展开相控阵（如 12m+/2500 元）；S 频段；波束跳变；单星聚合容量 0.5Gbps 级（短信/语音起步，逐步扩展宽带）"),
    "机载船载": dict(cn="机载/船载动中通", C_gbps=10, N_term=2000,
                    GT_term=8.0, EIRP_term=65.0, avail=99.5, design_cn=8.0,
                    note="高速移动平台；Ku/Ka；波束跳变+快速跟踪；余量须加动态损耗"),
    "物联网": dict(cn="窄带物联网（IoT）", C_gbps=0.1, N_term=500000,
                  GT_term=-18.0, EIRP_term=48.0, avail=99.0, design_cn=5.0,
                  note="海量小包；L/S 频段；单载波 200kHz 级；星上处理与存储转发"),
    "中继数传": dict(cn="中继数传（星间/星地）", C_gbps=10, N_term=50,
                    GT_term=20.0, EIRP_term=70.0, avail=99.9, design_cn=10.0,
                    note="Ka/激光；大口径天线；高 EIRP/G/T；为遥感星提供天基中继"),
    "军用抗干扰": dict(cn="军用抗干扰通信", C_gbps=0.3, N_term=500,
                      GT_term=6.0, EIRP_term=62.0, avail=99.9, design_cn=8.0,
                      note="跳频/扩频+再生处理+星上路由；nulling 抗干扰波束；UHF/SHF/EHF；L 频段 34MHz 指配下整星 0.3Gbps 量级"),
    "应急专网": dict(cn="应急专网", C_gbps=1, N_term=5000,
                    GT_term=5.0, EIRP_term=58.0, avail=99.5, design_cn=6.0,
                    note="快速部署、可重构；DTP 柔性载荷按需重构波束与带宽"),
}
SERVICE_KEYS = list(SERVICES.keys())

# ================================================================
# 四、转发体制库
# ================================================================
MODES = {
    "透明": dict(cn="透明转发（弯管 Bent-Pipe）",
                 chain="lna→dconv→imux→equalizer→filter→[功放]→omux→uconv",
                 delay="单跳时延 ≈200ns（仅群时延）",
                 noise="上行噪声与下行噪声全链路累积：1/(C/N)总 = 1/(C/N)上 + 1/(C/N)下",
                 flex="波束/带宽/功率固定，在轨不可重构",
                 t_rl=9, complexity="低", cost_mult=1.0, mass_mult=0.85, power_mult=0.75,
                 risk="低（飞行继承最多）",
                 regen_bonus=0.0,
                 units_add=[], units_core=["lna", "dconv", "imux", "equalizer", "omux", "uconv", "switch_matrix"],
                 pros=["技术最成熟、成本最低、功耗质量最小", "时延最小（仅群时延）", "信号格式透明，地面体制升级不影响卫星", "货架单机最齐全，可靠性最高"],
                 cons=["噪声累积，链路余量最低", "波束/带宽固化，在轨不可重构", "无星上交换，跨波束须落地双跳", "易受干扰（无星上处理）"],
                 apps=["传统广播（DTH）", "固定 VSAT 专网", "GEO Ku/C 单波束大覆盖", "寿命长、需求稳定的任务"],
                 hpa_pref="TWTA（高压大功率、效率高，单波束满功率）"),
    "数字透明": dict(cn="数字透明处理（DTP / 柔性载荷）",
                 chain="lna→dconv→adc→dswitch(交换矩阵)→dac→uconv→[功放]→omux",
                 delay="单跳时延 ≈2~5ms（数字化处理+交换）",
                 noise="仍为透明链路（噪声累积），但子带级增益/相位可均衡补偿",
                 flex="波束图样、子带带宽、功率分配、路由均可在轨重构",
                 t_rl=8, complexity="中", cost_mult=1.5, mass_mult=1.15, power_mult=1.35,
                 risk="中（DTP 处理器为核心新研/货架）",
                 regen_bonus=0.0,
                 units_add=["adc", "dswitch", "dac", "reconfig_ctrl"], units_core=["lna", "dconv", "uconv", "omux"],
                 pros=["在轨重构：波束/带宽/功率按需分配，应对需求变更", "子带级信道化，频率利用率高", "MPA 功率池单管故障可重构，可用度高", "商业航天批产首选（一星多用）"],
                 cons=["ADC/DAC 与交换矩阵功耗大（+35%）", "质量增加约 15%", "时延 2~5ms（仍透明链路，噪声累积）", "数字化通道数受交换容量限制"],
                 apps=["商业宽带星座（需求多变）", "应急专网（按需重构）", "GEO 高通量多波束", "一星多任务"],
                 hpa_pref="MPA 多功放矩阵（功率池，单管故障重构）"),
    "再生": dict(cn="再生处理（星上再生 OBPR）",
                 chain="lna→dconv→demod→decoder→router→encoder→modulator→uconv→[功放]→omux",
                 delay="单跳时延 ≈30~60ms（解调译码再调制+路由）",
                 noise="噪声不累积：上下行独立解调，链路余量提升 3~6dB（ΔM_reg）",
                 flex="星上路由交换、波束间信息交换、抗干扰处理",
                 t_rl=6, complexity="高", cost_mult=2.2, mass_mult=1.45, power_mult=1.85,
                 risk="高（基带体制绑定，升级需换星）",
                 regen_bonus=4.5,
                 units_add=["demod", "decoder", "encoder", "modulator", "router_unit", "baseband"],
                 units_core=["lna", "dconv", "uconv", "omux"],
                 pros=["噪声不累积，余量 +3~6dB（等效增大口径/降低功放）", "星上路由交换，跨波束单跳直达（无需落地双跳）", "解调译码后可做抗干扰/加密处理", "支持星间组网与天基互联网"],
                 cons=["复杂度、功耗、质量最高（功耗约 ×1.85）", "体制绑定：地面标准升级需星上软件重构甚至换星", "时延 30~60ms", "基带单机研制风险高"],
                 apps=["LEO 宽带星座（星间组网）", "军用抗干扰", "手机直连 D2D（信令处理）", "天基互联网骨干"],
                 hpa_pref="SSPA（线性度好，适配高阶调制）或 MPA"),
}
MODE_KEYS = ["透明", "数字透明", "再生"]
# 体制 → 功放推荐
MODE_HPA = {"透明": "TWTA", "数字透明": "MPA", "再生": "SSPA"}

# ================================================================
# 五、天线类型库
# ================================================================
ANT_TYPES = {
    "固面": dict(cn="固面反射面天线", key="reflector",
                 gain_formula="G = 10lg(η·(πD/λ)²)（c-4）",
                 eta_typ=0.68, d_typ=2.5, d_max=4.0, mass_per_m2=12.0,
                 scan="机械指向（步距 0.02°），无电扫",
                 beam="单波束或多波束（多馈源+成形反射面）",
                 bands=["L", "S", "C", "X", "Ku", "Ka"],
                 t_rl=9, cost_mult=1.0,
                 pros=["技术最成熟、口径大可获极高增益", "无源损耗小、效率高（η≈0.65~0.7）", "功率容量大（TWTA 百瓦级）", "成本低、飞行继承多"],
                 cons=["波束指向靠机械，切换慢（秒级）", "多波束需多馈源，口径受限", "不可在轨重构波束图样", "大口径需展开机构（固面多为小口径刚性）"],
                 apps=["GEO 单波束广播/大区覆盖", "馈电链路关口站侧", "小口径星载天线（≤4m）"]),
    "相控阵": dict(cn="相控阵天线（AESA）", key="phased",
                 gain_formula="G = 10lg(N_el·η) + G_el − 扫描损耗 cos^1.5θ（c-3）",
                 eta_typ=0.70, n_el_typ=1024, mass_per_el=0.055,
                 scan="电扫描 ±60°，微秒级波束切换",
                 beam="多波束/波束跳变/在轨重构",
                 bands=["L", "S", "C", "X", "Ku", "Ka", "Q/V"],
                 t_rl=8, cost_mult=1.8,
                 pros=["电扫描微秒级波束切换（波束跳变体制核心）", "多波束/在轨重构，灵活度最高", "无机械运动，寿命与可靠性高", "幅相加权可实现低旁瓣/零陷抗干扰"],
                 cons=["T/R 组件数量大、成本高（约占载荷 40%）", "功耗大（N_el×P_tr，百瓦至千瓦级）", "扫描角增大时增益按 cos^1.5θ 下降", "口径受阵面工艺限制（超大口径需展开式相控阵）"],
                 apps=["LEO 宽带星座（多波束+跳变）", "手机直连 D2D（超大口径展开相控阵）", "军用抗干扰（零陷）", "动中通（快速跟踪）"]),
    "伞状": dict(cn="伞状可展开天线", key="umbrella",
                 gain_formula="G = 10lg(η·(πD/λ)²)（c-4），η≈0.60~0.65",
                 eta_typ=0.62, d_typ=12.0, d_max=25.0, mass_per_m2=4.5,
                 scan="机械指向（整体或局部）",
                 beam="单波束或少数波束（大口径高增益）",
                 bands=["L", "S", "UHF"],
                 t_rl=8, cost_mult=1.5,
                 pros=["超大口径（12~25m）获极高增益，L/S 波段移动通信必需", "质量轻（4~5kg/m²），收纳比高", "G/T 大，适合手持终端（G/T≈-12dB/K）", "国内成熟（东方红 12m 伞天线飞行继承）"],
                 cons=["展开机构复杂、可靠性关键（一次展开不可逆）", "面精度低（δ≈1.5~2mm RMS），仅适用低频段（λ≥0.15m）", "波束数少（馈源阵规模受限）", "低频段带宽有限"],
                 apps=["L/S 移动通信（天通/铱星 NEXT）", "手机直连 D2D（S 波段大口径）", "UHF 军用窄带", "低频段大 G/T 需求"]),
    # ---- 大容量体制（用户需求：天线体制考虑大容量、混合多波束）----
    "大容量多波束": dict(cn="大容量多波束天线（VHTS 成形反射面 + 高密度馈源阵）", key="vhts",
                 gain_formula="G = 10lg(η·(πD/λ)²)（c-4），η≈0.68；单波束增益按离轴角折算 −10lg(1+(θ_off/θ3)²)",
                 eta_typ=0.68, d_typ=3.5, d_max=7.0, mass_per_m2=11.0,
                 scan="机械指向（波束图样由成形面+馈源阵固定生成）",
                 beam="超多波束（100~500 波束）+ 高频率复用（k=4~7）+ 双/四极化复用",
                 bands=["Ku", "Ka", "Q/V"],
                 t_rl=9, cost_mult=1.15,
                 hpa_max_w=120,
                 pros=["单星容量最大（100Gbps~1Tbps 级，VHTS 主流）", "反射面口径效率高（η≈0.68），同等容量功耗最低（每 Gbps 功耗远低于相控阵）",
                       "馈源阵规模可控（每波束 1~4 馈源，数百个），无源损耗小", "飞行继承充分（KA-SAT/ViaSat-3/Konnect VHTS/中星26号）",
                       "配合 DTP + MPA 功率池可在波束间动态调配功率（准波束跳变）"],
                 cons=["波束图样在轨不可重构（成形面固化）", "口径大（3.5~7m）需可展开反射面，收纳与展开精度要求高",
                       "馈源阵与 BFN 网络复杂（数百通道幅相一致性）", "离轴波束增益下降（边缘波束需加大功率补偿）"],
                 apps=["GEO 超大容量宽带（HTS/VHTS 主干）", "航空/航海批量接入", "运营商级宽带覆盖（多国多波束）",
                       "Ku/Ka 频段容量密集型任务"]),
    "混合多波束": dict(cn="混合多波束天线（成形反射面 + 相控阵馈电 / 有源阵馈反射面 AFR）", key="hybrid",
                 gain_formula="G = 10lg(η_hyb·(πD/λ)²)（c-4），η_hyb≈0.60（含馈电阵量化/溢出/幅相误差损失）",
                 eta_typ=0.60, d_typ=3.0, d_max=6.0, mass_per_m2=14.0,
                 scan="机械指向 + 馈电阵电扫（±3~8° 波束微调/跳变/零陷）",
                 beam="多波束 + 波束跳变 + 在轨重构（馈电阵幅相加权实时改图样）",
                 bands=["Ku", "Ka", "Q/V"],
                 t_rl=7, cost_mult=1.6,
                 hpa_max_w=250,
                 pros=["兼具反射面高增益/高效率与相控阵灵活性（波束图样在轨可重构）",
                       "馈电阵规模小（数十~数百元），功耗远低于全阵相控阵（同等增益下省 1~2 个数量级）",
                       "可生成抗干扰零陷、波束跳变按需覆盖", "反射面口径增益补偿了馈电阵的低单元增益",
                       "一星多任务/应急专网/需求多变场景首选"],
                 cons=["馈电阵+反射面双重研制，接口与校准复杂（两级幅相一致性）", "TRL 低于纯反射面（7 级，在研为主）",
                       "扫描角有限（±3~8°，受馈源偏离焦面像差限制）", "成本高于纯反射面（×1.6）"],
                 apps=["GEO 柔性载荷（OneSat/702X 类）", "应急专网（波束按需重构）", "军用抗干扰（反射面增益+零陷）",
                       "需求不确定的一星多任务", "大容量+高灵活度兼顾场景"]),
}
ANT_TYPE_KEYS = ["固面", "相控阵", "伞状", "大容量多波束", "混合多波束"]

# 相控阵子体制（五选一）
ARRAY_SUBTYPES = {
    "直射阵": dict(cn="直射阵（DRA，直接辐射阵）",
                   principle="T/R 组件输出直接经阵元辐射，无反射面。阵面即辐射面。",
                   eta=0.55, p_tr_w=6.0, mass_per_el=0.045, cost_mult=1.0, t_rl=9,
                   scan_max=60, n_el_max=4096,
                   pros=["结构最简单、剖面低", "扫描角大（±60°）", "幅相控制直接，波束重构灵活"],
                   cons=["单元增益低（G_el≈5~7dBi），需大量阵元补偿", "阵面功耗/发热集中", "口径受限（大口径需拼接）"],
                   apps=["LEO 宽带用户链路（0.5~2m 阵面）", "机载/船载动中通平板阵", "星上小型多波束阵"]),
    "反射阵": dict(cn="反射阵（Reflectarray）",
                   principle="馈源照射周期性单元阵列，各单元通过可调移相反射实现波束赋形（介于反射面与相控阵之间）。",
                   eta=0.50, p_tr_w=3.5, mass_per_el=0.038, cost_mult=0.85, t_rl=7,
                   scan_max=45, n_el_max=8192,
                   pros=["口径可做大（展开式反射阵）", "无需馈电网络（无源馈电）", "单元功耗低（仅移相器）"],
                   cons=["带宽窄（单元谐振特性，<10%）", "扫描角受限（±45°）", "效率低于直射阵（二次辐射）", "在轨重构单元数量大"],
                   apps=["大口径高增益点波束", "Ka/Q/V 高频段（单元尺寸小）", "可展开大口径相控阵"]),
    "数字模拟混合": dict(cn="数字模拟混合波束赋形",
                   principle="子阵级模拟移相（RF）+ 子阵间数字域加权（基带），以 N_rf 条射频通道驱动 N_el 阵元。",
                   eta=0.62, p_tr_w=4.5, mass_per_el=0.040, cost_mult=1.15, t_rl=8,
                   scan_max=60, n_el_max=8192, subarray=16,
                   pros=["射频通道数少（N_el/16），功耗成本大幅降低", "数字域灵活波束重构", "工程折中最优（大规模阵主流）"],
                   cons=["子阵内波束自由度受限（量化波束）", "子阵划分固定，极端灵活度低于纯数字", "校准复杂（模拟+数字两级）"],
                   apps=["LEO 大规模星座（Starlink 类）", "多波束高通量（64+ 波束）", "手机直连超大阵"]),
    "纯数字": dict(cn="纯数字波束赋形（DBF）",
                   principle="每个阵元独立 ADC/DAC + 数字收发，波束赋形完全在数字域完成。",
                   eta=0.65, p_tr_w=9.0, mass_per_el=0.065, cost_mult=2.2, t_rl=7,
                   scan_max=60, n_el_max=1024,
                   pros=["波束自由度最高（任意波束图样/零陷）", "在轨重构能力最强", "幅相一致性最好（无模拟通道失配）"],
                   cons=["每阵元独立 ADC/DAC，功耗/质量/成本最高", "阵元数受数字通道限制（≤1024）", "数据吞吐极大（交换容量瓶颈）"],
                   apps=["小规模高灵活度阵（≤1024 元）", "军用抗干扰零陷", "科研试验星"]),
    "模拟拼接": dict(cn="模拟拼接阵（Tile 模块化拼接）",
                   principle="标准化天线瓦片（Tile）机械+电气拼接成大阵面，每瓦片含独立 T/R 与馈电。",
                   eta=0.58, p_tr_w=5.5, mass_per_el=0.050, cost_mult=1.35, t_rl=6,
                   scan_max=50, n_el_max=16384,
                   pros=["口径可无限扩展（瓦片批产）", "单瓦片故障可隔离", "批产降本（商业航天核心）"],
                   cons=["瓦片间拼接精度要求高（幅相一致性）", "瓦片间接缝产生栅瓣风险", "整体展开机构复杂"],
                   apps=["超大口径 D2D 相控阵（12m+）", "批产星座（瓦片自动化产线）", "可展开大型阵面"]),
}
ARRAY_SUBTYPE_KEYS = list(ARRAY_SUBTYPES.keys())

# ================================================================
# 六、单机货架库（三线编号，与 SHELF_PRODUCT_HANDBOOK 对齐）
# ================================================================
# level: 4=货架产品(飞行继承) 3=飞行继承产品 2=货架产品(在研转货架) 1=定制
# p: (id, cn, cat, bands, level, mass_kg, power_w, specs, note)
SHELF_UNITS = [
    # ---- 天线类（G 为对应频段理论增益：反射面 10lg(η(πD/λ)²)；相控阵 10lg(N_el·η)+G_el−扫描损耗）----
    ("ANT-UMB-L12",   "12m L/S 伞状可展开天线", "天线", ["L", "S"], 4, 85, 30,
     dict(D=12.0, η=62, G_L=43, G_S=47, GT=21, δ_surf=1.8, N_beam=19),
     "东方红/银河航天飞行继承；L 波段移动通信首选；一次展开不可逆"),
    ("ANT-AESA-L",    "L/S 手机直连可展开相控阵", "天线", ["L", "S"], 3, 210, 1650,
     dict(D=12.0, N_el=2500, G=34, scan=35, P_tr=0.6, N_beam=48),
     "超大口径展开式相控阵（瓦片拼接）；D2D 手机直连专用"),
    ("ANT-AESA-KU",   "Ku 相控阵天线", "天线", ["Ku"], 3, 45, 320,
     dict(N_el=512, G=32, scan=45, B=500, N_beam=16),
     "动中通/机载船载；电扫描快速跟踪"),
    ("ANT-AESA-KA",   "Ka 相控阵天线", "天线", ["Ka"], 3, 60, 380,
     dict(N_el=1024, G=34, scan=50, B=2500, N_beam=16),
     "LEO 宽带用户链路多波束；数字模拟混合赋形"),
    ("ANT-AESA-S-SM", "S 小型相控阵天线", "天线", ["S", "L"], 3, 18, 90,
     dict(N_el=256, G=26, scan=40, B=240, N_beam=8),
     "物联网/窄带小卫星；直射阵 256 元"),
    ("ANT-REFL-KA",   "Ka 反射面多波束天线", "天线", ["Ka"], 4, 95, 120,
     dict(D=2.5, G=52, N_beam=64, η=68, θ3dB=0.42),
     "GEO 高通量多波束（成形反射面+多馈源）；2.5m 口径 G≈52.8dBi@20GHz；飞行继承"),
    ("ANT-REFL-KU",   "Ku 反射面天线", "天线", ["Ku"], 4, 70, 90,
     dict(D=2.5, G=48, N_beam=1, η=68, θ3dB=0.7),
     "广播/大区覆盖单波束；G≈48.5dBi@12GHz；国内成熟货架"),
    ("ANT-REFL-C",    "C 反射面天线", "天线", ["C"], 4, 60, 80,
     dict(D=2.0, G=37, N_beam=1, η=65, θ3dB=1.05),
     "传统 C 波段通信；飞行继承最多"),
    # ---- 大容量多波束（VHTS）与混合多波束货架产品 ----
    ("ANT-VHTS-KA",   "Ka 大容量多波束天线（VHTS 3.5m 成形反射面+馈源阵）", "天线", ["Ka"], 4, 130, 180,
     dict(D=3.5, G=56.3, N_beam=233, η=68, θ3dB=0.30, hpa_max=120),
     "G≈56.3dBi@20GHz；233 波束（KA-SAT 级飞行继承）；可展开成形反射面+高密度馈源阵；VHTS 单星 100Gbps+ 主干"),
    ("ANT-VHTS-KU",   "Ku 大容量多波束天线（VHTS 3.5m）", "天线", ["Ku"], 3, 120, 160,
     dict(D=3.5, G=52.8, N_beam=150, η=68, θ3dB=0.50, hpa_max=140),
     "G≈52.8dBi@12GHz；150 波束；Ku VHTS（Eutelsat Quantum 同级）"),
    ("ANT-HYB-KA",    "Ka 混合多波束天线（3m 反射面+相控阵馈电）", "天线", ["Ka"], 3, 150, 260,
     dict(D=3.0, G=54.2, N_beam=128, η=60, θ3dB=0.35, N_el_feed=256, scan=6, hpa_max=250),
     "G≈54.2dBi@20GHz；成形反射面+256 元馈电阵：波束图样在轨重构/跳变/零陷；OneSat/702X 类柔性载荷（在研转货架）"),
    # ---- 商业航天新货架（银河航天 GAL / 国际参考 INT，2026-09 增补）----
    ("ANT-REFL-QV-GAL", "Q/V 频段第四代轻量化平板天线（银河航天）", "天线", ["Q/V"], 3, 3.2, 15,
     dict(D=0.265, G=38.7, N_beam=1, η=60, θ3dB=1.98),
     "银河航天第四代 Q/V 天线：3.2kg/剖面 0.265m（反射阵-AiP 平板），批产线年产 300 副、在轨 100+；"
     "G≈38.7dBi@40GHz（η=60%）；LEO 宽带馈电链路"),
    ("ANT-AESA-KA8-GAL", "Ka 8 波束 AiP 瓦式相控阵天线（银河航天）", "天线", ["Ka"], 4, 25, 160,
     dict(N_el=512, G=32, scan=60, B=2500, N_beam=8, N_el_chip=8),
     "单片 8 波束波束赋形芯片构建 AiP 瓦式阵面；累计交付 300+/在轨 200+（飞行继承货架）；LEO 宽带用户链路多波束"),
    ("ANT-AESA-D2D-GAL", "手机直连可展开相控阵（银河航天 25㎡级）", "天线", ["L", "S"], 2, 260, 1900,
     dict(N_el=3000, G=35, scan=40, N_beam=64),
     "25㎡级数字化相控阵（模拟拼接瓦片批产）；存量手机直连 D2D；L-E 全频谱可动天线路线（在研转货架）"),
    ("ANT-REFL-X",    "X 反射面数传天线", "天线", ["X"], 4, 25, 30,
     dict(D=0.9, G=36.1, N_beam=1, η=65, θ3dB=2.78),
     "遥感/中继数传主力频段；G≈36.1dBi@8.4GHz（η=65%）；国内成熟货架、飞行继承最多"),
    ("ANT-REFL-S-TTC", "S 测控小口径天线", "天线", ["S"], 4, 6, 10,
     dict(D=0.5, G=19.0, N_beam=1, η=60, θ3dB=19.1),
     "测控链路（TTC 豁免频段）；G≈19dBi@2.2GHz，宽波束近半球覆盖；飞行继承"),
    # ---- LNA ----
    ("LNA-L-01",      "L 波段低噪放", "LNA", ["L"], 4, 0.3, 3.0, dict(G=40, NF=0.8), "GaAs pHEMT；NF 0.8dB"),
    ("LNA-S-01",      "S 波段低噪放", "LNA", ["S"], 4, 0.3, 3.0, dict(G=38, NF=1.0), ""),
    ("LNA-KU-01",     "Ku 低噪放", "LNA", ["Ku"], 4, 0.3, 3.5, dict(G=40, NF=1.2), "A/B 冷备"),
    ("LNA-KA-01",     "Ka 低噪放", "LNA", ["Ka"], 4, 0.3, 3.0, dict(G=35, NF=1.6), "InP HEMT；NF 1.6dB"),
    ("LNA-KA-INT",    "Ka 低噪放（国际）", "LNA", ["Ka"], 3, 0.5, 6.5, dict(G=36, NF=1.4), "Thales/SELEX 飞行继承"),
    ("LNA-QV-01",     "Q/V 频段低噪放", "LNA", ["Q/V"], 2, 0.4, 4.5, dict(G=30, NF=2.5),
     "InP HEMT MMIC；40GHz NF≈2.5dB（与 NF_BY_BAND[Q/V] 同源）；Q/V 馈电接收前端（在研转货架）"),
    # ---- 变频 ----
    ("DCONV-01",      "下变频器", "变频", ["L", "S", "C", "X", "Ku", "Ka", "Q/V"], 4, 0.5, 4.0, dict(G=-2, NF=8), "镜像抑制 >60dBc"),
    ("UCONV-01",      "上变频器", "变频", ["L", "S", "C", "X", "Ku", "Ka", "Q/V"], 4, 0.5, 4.0, dict(G=-2), ""),
    ("LO-SRC-01",     "频率源/本振", "变频", ["*"], 4, 1.0, 8.0, dict(Lφ=-95), "相位噪声 −95dBc/Hz@10kHz"),
    ("LO-USO-INT",    "超稳晶振 USO（国际）", "变频", ["*"], 3, 0.6, 3.0, dict(Lφ=-135, f=100),
     "100MHz 超稳本振，相位噪声 −135dBc/Hz@10kHz（Rakon/Thales 飞行继承，SatNow 目录同类）；相干体制/深空测控基准"),
    # ---- IMUX/OMUX ----
    ("IMUX-01",       "输入多工器", "多工器", ["L", "S", "C", "X", "Ku", "Ka", "Q/V"], 4, 2.0, 0, dict(N=8, IL=1.5), "8 通道"),
    ("OMUX-01",       "输出多工器", "多工器", ["L", "S", "C", "X", "Ku", "Ka", "Q/V"], 4, 3.5, 0, dict(N=8, IL=1.8), "8 通道，插损 1.8dB"),
    # ---- 功放 ----
    ("TWTA-KA-180",   "Ka 180W 行波管功放", "功放", ["Ka"], 4, 6.0, 310, dict(P=180, η=58, G=50), "Thales/国内飞行继承；GEO 大功率单波束"),
    ("TWTA-KA-120",   "Ka 120W 行波管功放", "功放", ["Ka"], 3, 4.5, 207, dict(P=120, η=58, G=49), "HTS 点波束主力（Viasat 同类）"),
    ("TWTA-KA-60",    "Ka 60W 行波管功放", "功放", ["Ka"], 3, 3.0, 112, dict(P=60, η=54, G=47), "HTS 点波束批产型"),
    ("TWTA-KU-140",   "Ku 140W 行波管功放", "功放", ["Ku"], 4, 5.5, 235, dict(P=140, η=60, G=50), "广播转发器主力"),
    ("TWTA-L-60",     "L 60W 行波管功放", "功放", ["L"], 3, 4.0, 130, dict(P=60, η=46, G=48), "移动通信"),
    ("SSPA-KA-100",   "Ka 100W 固态功放（GaN）", "功放", ["Ka"], 3, 3.0, 222, dict(P=100, η=45, IMD3=-25), "线性度优，适配高阶调制"),
    ("SSPA-S-80",     "S 80W GaN 固态功放", "功放", ["S"], 3, 2.5, 178, dict(P=80, η=45), "D2D 功率合成"),
    ("SSPA-KU-50",    "Ku 50W GaN 固态功放", "功放", ["Ku"], 4, 2.0, 111, dict(P=50, η=45), ""),
    ("MPA-8X8",       "8×8 多功放矩阵", "功放", ["Ku", "Ka"], 3, 8.0, 570, dict(N=8, η=42, P_pool=240), "功率池 8 路，单管故障重构（DTP 标配）；功耗按 8×P_out/η 动态计"),
    ("EPC-01",        "电子功率调节器", "功放", ["*"], 4, 2.0, 5.0, dict(V_hv=6.0), "高压 6kV，过流过压保护"),
    # ---- 功放（商业航天增补：Q/V 馈电、X 数传、D2D 大功率合成）----
    ("TWTA-QV-40",    "Q/V 40W 行波管功放", "功放", ["Q/V"], 2, 2.8, 88, dict(P=40, η=46, G=44),
     "Q/V 馈电链路专用（40GHz 下行）；Thales 同级在研转货架；GEO/LEO 馈电小功率点波束"),
    ("SSPA-QV-20",    "Q/V 20W GaN 固态功放", "功放", ["Q/V"], 2, 1.5, 60, dict(P=20, η=33, IMD3=-25),
     "GaN MMIC 功率合成；LEO Q/V 馈电批产型（在研转货架）"),
    ("TWTA-X-40",     "X 40W 行波管功放", "功放", ["X"], 4, 3.2, 85, dict(P=40, η=47, G=48),
     "遥感/数传 X 频段主力；国内飞行继承货架"),
    ("SSPA-L-200",    "L 200W GaN 固态功放（D2D 功率合成）", "功放", ["L"], 2, 5.5, 470, dict(P=200, η=42),
     "手机直连 D2D 下行大功率合成（GaN 空间功率合成）；在研转货架"),
    # ---- 相控阵组件 ----
    ("TR-L-01",       "L/S T/R 组件", "相控阵组件", ["L", "S"], 3, 0.03, 6.0, dict(P=6, NF=2.0, G=20), "GaN；D2D 大阵面"),
    ("TR-KU-01",      "Ku T/R 组件", "相控阵组件", ["Ku"], 3, 0.03, 7.0, dict(P=7, NF=2.2, G=20), ""),
    ("TR-KA-01",      "Ka T/R 组件", "相控阵组件", ["Ka"], 3, 0.03, 8.0, dict(P=8, NF=2.0, G=20, T_j=105), "结温 ≤125℃"),
    ("PS-6BIT",       "6 位数字移相器", "相控阵组件", ["*"], 4, 0.05, 0.6, dict(n_bit=6), "量化 2.8°"),
    ("BFN-01",        "波束赋形网络", "相控阵组件", ["*"], 3, 4.0, 12.0, dict(N=64), "Butler 矩阵/Blass 矩阵"),
    ("CAL-NET-01",    "波束校准网络", "相控阵组件", ["*"], 3, 0.8, 2.0, dict(Δ=0.3), "校准精度 0.3dB"),
    ("BFC-8B-GAL",    "单片 8 波束波束赋形芯片（银河航天）", "相控阵组件", ["Ka", "Q/V"], 3, 0.02, 12.0,
     dict(N_bf=8, G=20, NF=2.5),
     "单芯片 8 波束同时成形（AiP 瓦式阵核心）；银河航天累计交付 300+ 套（飞行继承）；批产降本核心器件"),
    # ---- DTP / 数字 ----
    ("DTP-PROC-01",   "DTP 数字透明处理器", "数字处理", ["*"], 3, 3.0, 45.0, dict(C=100, N_ch=32, B_sub=40), "交换容量 100Gbps；Space INSPIRE/OneSat/702X 同类"),
    ("ADC-1200",      "宽带 ADC（1200MHz）", "数字处理", ["*"], 3, 1.2, 25.0, dict(B=1200, ENOB=10, SFDR=70), ""),
    ("DAC-01",        "宽带 DAC", "数字处理", ["*"], 3, 1.0, 20.0, dict(SFDR=70), ""),
    ("DBF-ASIC-GAL",  "芯片化数字波束成形处理器（银河航天）", "数字处理", ["*"], 3, 0.8, 18.0,
     dict(C=200, N_ch=64, B_sub=50),
     "芯片化基带/DBF 处理组件，64 通道 200Gbps 交换；银河航天星载批产（飞行继承）；商业星座降本核心"),
    ("SDR-SAT-INT",   "星载软件定义无线电 SDR（国际）", "数字处理", ["L", "S", "X", "Ku"], 3, 2.2, 35.0,
     dict(B=400, f_min=0.1, f_max=18, MC="BPSK~64QAM"),
     "全数字可重构收发（100MHz~18GHz，400MHz 瞬时带宽）；SatNow 目录 SDR 类（L3Harris/SpaceMicro 同类）；在轨波形重加载"),
    # ---- 再生基带 ----
    ("MODEM-S2X",     "DVBS2X 调制解调器", "再生基带", ["*"], 3, 1.5, 30.0, dict(MC="QPSK~32APSK", ACM=1), "ACM/VCM 自适应"),
    ("CODER-LDPC",    "LDPC/BCH 编译码器", "再生基带", ["*"], 3, 2.0, 37.0, dict(G=6.5), "编码增益 6.5dB"),
    ("ROUTER-01",     "星上路由交换单元", "再生基带", ["*"], 2, 2.5, 30.0, dict(N_rt=4096, t=1), "路由表 4096 条，单跳选路 <1ms"),
    ("BB-PROC-01",    "基带处理单元", "再生基带", ["*"], 2, 3.0, 35.0, dict(R=2000), "吞吐 2000Mbps"),
    ("GNB-SAT-GAL",   "星载基站（5G NTN 再生，银河航天）", "再生基带", ["L", "S", "Ka"], 2, 8.0, 120.0,
     dict(R=4800, N_ue=2000, MC="QPSK~256QAM"),
     "5G NTN 体制星上再生基站：gNB 协议栈上星，单星 4.8Gbps/2000 用户并发；银河航天手机直连星座（在研转货架）"),
    # ---- 开关/无源 ----
    ("SW-MTX-01",     "微波开关矩阵", "开关", ["*"], 4, 1.5, 4.0, dict(I=80, t="ns"), "隔离度 80dB"),
    ("CIRC-01",       "环行器/隔离器", "开关", ["*"], 4, 0.6, 0, dict(I=100), "收发隔离 ≥100dB"),
    ("SW-BEAM-01",    "波束切换开关矩阵", "开关", ["*"], 3, 1.5, 3.0, dict(I=80), "波束跳变体制核心"),
    ("ATT-01",        "可变衰减器/均衡器", "开关", ["*"], 4, 0.3, 0.2, dict(Δ=1.0), "幅频/群时延均衡"),
    # ---- 激光 ----
    ("LCT-10G",       "10Gbps 激光通信终端", "激光", ["激光"], 3, 38, 160, dict(R=10, P=1.0, D=135, σ=0.8), "含 ATP/EDFA/DPSK；星间组网"),
    ("LCT-5G",        "5Gbps 激光通信终端", "激光", ["激光"], 3, 30, 120, dict(R=5, P=1.0, D=100), "星地激光馈电"),
    ("LCT-INT-20G",   "20Gbps 激光终端（国际）", "激光", ["激光"], 2, 45, 180, dict(R=20), "CACI/Mynaric 同类"),
    ("LCT-GEO-INT",   "GEO 激光通信终端（Tesat LCT135 同级）", "激光", ["激光"], 4, 53, 150,
     dict(R=1.8, P=1.0, D=135, σ=0.8, λ="1064nm"),
     "Tesat LCT135：1.8Gbps/80000km 星间（EDRSL/GEO 飞行继承 14 台，TRL9）；DPSK 相干体制 λ=1064nm；600×600×700mm"),
    ("LCT-CUBEL-INT", "微纳激光通信终端（Tesat CubeL 同级）", "激光", ["激光"], 3, 0.36, 8,
     dict(R=0.1, P=0.05, D=20, λ="1550nm"),
     "Tesat CubeL：100Mbps/8W/360g（SatNow 目录 SmartLCT 同类）；立方星/微纳星座星间轻量组网"),
    ("LCT-DTE-INT",   "星地激光馈电终端 10Gbps（Tesat TOSIRIS 同级）", "激光", ["激光"], 3, 8, 40,
     dict(R=10, P=1.0, D=60, λ="1550nm"),
     "Tesat TOSIRIS-DTE：10Gbps 星地下行/40W/8kg（λ=1550nm）；LEO 对地高速馈电、光学地面站组网"),
    # ---- 信标/测控 ----
    ("BCN-TX-01",     "信标发射机", "测控信标", ["*"], 4, 1.0, 15.0, dict(P=5), "连续波信标，测轨/遥测"),
    ("TTC-TRP-01",    "测控应答机", "测控信标", ["*"], 4, 2.0, 25.0, dict(S=2, R=2), "统一载波测控"),
    ("ACU-01",        "天线控制单元 ACU", "测控信标", ["*"], 3, 3.0, 15.0, dict(t=50), "波束切换响应 50ms"),
    ("TTC-TRP-S-INT", "S 波段测控转发器（国际）", "测控信标", ["S"], 4, 1.6, 20.0,
     dict(S=2, R=2, P=5),
     "SatNow 目录 C-TT-520/同类 S 波段相干测控应答机（5W，测距+测速+遥控遥测）；微纳星座飞行继承"),
    ("TTC-DB-INT",    "双频段测控转发器（国际）", "测控信标", ["S", "X"], 3, 2.2, 28.0,
     dict(S=2, R=2, P=5),
     "SatNow 目录 CXS-2000 同类 S/X 双频段测控数传一体应答机（L3Harris）；测控+高速数传共用，省重量"),
    # ---- 机构 ----
    ("DEP-MECH-12M",  "12m 伞天线展开机构", "机构", ["*"], 3, 18.0, 0, dict(δ=0.20), "到位精度 0.2mm RMS"),
    ("DEP-MECH-AESA", "相控阵展开机构", "机构", ["*"], 2, 25.0, 0, dict(δ=0.15), "瓦片展开+锁紧"),
    ("DEP-MECH-35",   "3.5m 可展开反射面机构（肋-膜/花瓣式）", "机构", ["*"], 3, 28.0, 0, dict(δ=0.10), "VHTS 成形面展开；面精度 0.10mm RMS"),
    ("PNT-2AXIS",     "两轴指向机构", "机构", ["*"], 3, 15.0, 25.0, dict(step=0.02), "步距 0.02°"),
    # ---- 馈电阵（混合多波束专用）----
    ("FEED-ARR-KA",   "Ka 馈电阵模组（64 元）", "相控阵组件", ["Ka"], 3, 2.5, 90.0, dict(N_el=64, P_tr=1.4, scan=6), "混合多波束馈电：焦面有源阵，±6° 电扫微调/波束跳变"),
    # ---- 智能处理 ----
    ("OBC-PAY-01",    "星载计算机（载荷）", "星务", ["*"], 4, 3.5, 18.0, dict(MIPS=4000), "FDIR 覆盖关键单机"),
    ("DPU-01",        "数据处理单元", "星务", ["*"], 3, 2.5, 28.0, dict(R=1500, CR=4), "CCSDS 压缩 4:1"),
    ("STOR-4T",       "4Tbit 大容量存储器", "星务", ["*"], 3, 5.0, 20.0, dict(E=4.0, EDAC=1), "三模冗余+EDAC"),
    ("BUS-FCAE",      "FC-AE 星上数据总线", "星务", ["*"], 3, 1.5, 10.0, dict(R=4000), "4000Mbps"),
    ("RECONF-CTRL",   "在轨重构控制器", "星务", ["*"], 2, 1.0, 8.0, dict(t=5), "重构指令生效 5s"),
    ("AI-UNIT-01",    "AI 推理单元", "星务", ["*"], 2, 2.0, 30.0, dict(TOPS=20), "业务预测/资源调度"),
    ("OBC-RH-INT",    "辐射加固星载计算机（国际）", "星务", ["*"], 3, 1.8, 12.0,
     dict(MIPS=2000, SEU=1e-10, TID=100),
     "抗辐照 SoC（TID 100krad，SEU<1e-10/器件·天）；SatNow 目录 OBC 类（GomSpace/SpaceMicro 同类，63+ 款）；微纳星座批产"),
]
# 索引
SHELF_BY_ID = {u[0]: dict(zip(("id", "cn", "cat", "bands", "level", "mass", "power", "specs", "note"), u))
               for u in SHELF_UNITS}
SHELF_CATS = ["天线", "LNA", "变频", "多工器", "功放", "相控阵组件", "数字处理",
              "再生基带", "开关", "激光", "测控信标", "机构", "星务"]
# 货架水平定义（c-21）
SHELF_LEVELS = {4: "货架产品(飞行继承)", 3: "飞行继承产品", 2: "货架产品(在研转货架)", 1: "定制"}

# ================================================================
# 七、单机/载荷功能原理介绍
# ================================================================
UNIT_PRINCIPLES = {
    "天线": dict(cn="天线分系统", principle=(
        "天线是载荷与空间信道之间的能量转换接口，决定 EIRP（发射能力）与 G/T（接收品质因数）两大核心指标。\n"
        "· 发射：EIRP = P_out(dBW) + G_ant(dBi) − L_feed − L_tx，即功放输出功率经馈电网络损耗后由天线增益放大向空间辐射；\n"
        "· 接收：G/T = G_ant − 10lg(T_sys)，T_sys = T_ant + T_rx（天空噪声+接收机噪声），决定最小可解调信号电平；\n"
        "· 反射面天线增益 G = 10lg(η(πD/λ)²)，口径 D 与效率 η 决定增益，波束宽度 θ_3dB ≈ 70λ/D；\n"
        "· 相控阵增益 G = 10lg(N_el·η) + G_el，扫描损耗按 cos^1.5θ_scan 计；\n"
        "· 面精度约束 δ_surf ≤ λ/32（Ka 波段 λ=15mm → δ≤0.47mm），否则增益下降、旁瓣抬升。"),
        units=["feed", "deploy", "pointing", "beam_former", "ant_ctrl"]),
    "LNA": dict(cn="低噪声放大器", principle=(
        "LNA 位于接收通道最前端，其噪声系数 NF 直接决定整个接收系统的噪声温度：\n"
        "T_rx ≈ (F_LNA−1)·290 + 后级贡献/G_LNA（Friis 级联公式）。\n"
        "· NF 每降 0.1dB，G/T 提升约 0.1dB/K，等效增大接收天线口径；\n"
        "· 增益 30~40dB 足够压制后级噪声贡献；\n"
        "· Ka 波段典型 NF 1.6dB（InP HEMT）、Ku 1.2dB、L 0.8dB；\n"
        "· 工程上 A/B 双机冷备，切换时间 <1ms。"),
        units=["lna"]),
    "变频器": dict(cn="上/下变频器", principle=(
        "转发器频率搬移核心：上行频率 f_up → 中频 IF → 下行频率 f_down，避免收发同频自激。\n"
        "· 下变频 DCONV：f_up 与第一本振混频得中频（典型 L 波段 1.4GHz 或零中频）；\n"
        "· 上变频 UCONV：中频与第二本振混频得 f_down；\n"
        "· 变频损耗 2~3dB，镜像抑制 >60dBc（需前置镜像抑制滤波器）；\n"
        "· 本振相位噪声 L(f) 直接恶化 EVM，要求 −95dBc/Hz@10kHz 以内。"),
        units=["dconv", "uconv", "lo_source"]),
    "功放": dict(cn="功率放大器（HPA）", principle=(
        "发射通道末级，将信号提升到天线所需辐射功率，是载荷最大功耗单机。\n"
        "· TWTA 行波管：效率 58~65%、功率大（百瓦级）、但线性度差，需回退 3~6dB 工作（IMD3 限制）；\n"
        "· SSPA 固态功放（GaN）：效率 40~50%、线性度好（IMD3 −25dBc）、适配高阶调制（16/32APSK），功率中等；\n"
        "· MPA 多功放矩阵：N 台 SSPA 经 8×8 Butler 矩阵功率池化，单管故障时功率重构不中断，DTP 柔性载荷标配；\n"
        "· 直流功耗 P_dc = P_out/η；结温 T_j ≤125℃（c-16）决定寿命。"),
        units=["twta", "sspa", "mpa", "epc"]),
    "多工器": dict(cn="输入/输出多工器", principle=(
        "频率规划与通道隔离的无源网络：\n"
        "· IMUX 输入多工器：将上行接收宽带信号按转发器通道分割（典型 8 通道，间隔 36~250MHz）；\n"
        "· OMUX 输出多工器：将各通道功放输出合路至同一天线馈源，通道间隔离 >80dB 防止互调；\n"
        "· 插损 1.5~2dB 直接计入链路预算；\n"
        "· 通道数与带宽须与频率规划（ITU 指配）严格匹配。"),
        units=["imux", "omux"]),
    "DTP": dict(cn="数字透明处理器", principle=(
        "柔性载荷核心：宽带 ADC 数字信道化 → 非阻塞交换矩阵 → DAC 重构，实现波束/子带/功率/路由四维在轨重构。\n"
        "· 信道化粒度 B_sub（典型 40~250MHz），越细越灵活但功耗越大；\n"
        "· 交换容量 C_sw ≥ N_beam×B_beam×η（c-14）；\n"
        "· 子带级增益/相位均衡可补偿通道幅相失配；\n"
        "· 与 MPA 功率池配合实现单管故障重构；\n"
        "· 国际同类：Thales Space INSPIRE、Airbus OneSat、Boeing 702X。"),
        units=["adc", "dswitch", "dac", "reconfig_ctrl"]),
    "再生基带": dict(cn="再生处理基带", principle=(
        "星上解调/译码/路由/再调制，噪声不累积（上下行独立）：\n"
        "· 解调器：QPSK~32APSK（DVBS2X），ACM/VCM 自适应编码调制；\n"
        "· 译码器：LDPC/BCH，编码增益 6.5dB；\n"
        "· 星上路由：跨波束单跳交换（传统透明需落地双跳），路由表 4096 条，选路 <1ms；\n"
        "· 调制器：按下行链路 C/N 自适应选 MODCOD；\n"
        "· 链路余量提升 ΔM_reg ≈ 3~6dB（c-24），等效增大天线口径或降低功放功率。"),
        units=["demod", "decoder", "encoder", "modulator", "router_unit", "baseband"]),
    "相控阵组件": dict(cn="T/R 组件与波束赋形", principle=(
        "相控阵的幅相控制核心，决定波束扫描与赋形能力：\n"
        "· T/R 组件：收发切换+功率放大（发射）+低噪放（接收）+移相衰减，GaAs/GaN MMIC 集成；\n"
        "· 移相器：6 位数字移相（量化 2.8°），相位加权实现波束电扫 θ_scan；\n"
        "· 波束赋形网络 BFN：Butler/Blass 矩阵将 N 端口变换为 M 波束（模拟域）；\n"
        "· 校准网络：注入校准信号提取各通道幅相误差（须 ≤0.3dB/3°，c-23）；\n"
        "· 阵面功耗 ≈ N_el × P_tr（P_tr 6~9W/组件）。"),
        units=["tr_module", "phase_shifter", "beam_former", "cal_network", "beam_port"]),
    "激光通信": dict(cn="激光通信终端", principle=(
        "星间/星地高速链路（5~20Gbps+），频段 1550nm（大气窗口+EDFA 成熟）：\n"
        "· 光学天线：Φ100~135mm 卡塞格林，增益 G_opt = 10lg(η(πD/λ)²) ≈ 110dBi；\n"
        "· ATP 捕获跟踪瞄准：粗跟踪万向架（视场 ±10°，捕获概率 ≥95%）+ 精跟踪 FSM（σ≤1μrad，带宽 800Hz）；\n"
        "· DPSK 调制：灵敏度 −42dBm@1Gbps（优于 OOK 约 6dB）；\n"
        "· 指向损耗 L = 12(σ_jit/θ_div)²；星地链路须考虑大气湍流（1.5dB）与云遮蔽（站址分集）。"),
        units=["tx_laser", "beacon_laser", "edfa", "optical_antenna", "photodetector", "atp_coarse", "fsm", "dpsk_modem"]),
    "测控信标": dict(cn="测控与信标", principle=(
        "TT&C：遥测（下行状态）+遥控（上行指令）+测轨（距离/速度）：\n"
        "· 统一载波测控应答机：相干转发地面测距音/伪码，支持 USB/S 波段；\n"
        "· 信标发射机：连续波（CW）供地面测轨与角度跟踪（5W 典型）；\n"
        "· 载荷侧由星载计算机 OBC 管理 FDIR（故障检测隔离恢复），覆盖关键单机。"),
        units=["obc_payload", "reconfig_ctrl"]),
    "星务处理": dict(cn="星上数据处理", principle=(
        "载荷数据汇聚、压缩、存储与下传：\n"
        "· 数据处理单元 DPU：CCSDS 无损/有损压缩（典型 4:1），等效降低总线与存储需求；\n"
        "· 大容量存储：4Tbit 级，EDAC+三模冗余抗单粒子翻转；\n"
        "· 数据总线：FC-AE/SpaceWire/1553B，速率须 ≥ R_pdl/CR（c-20）；\n"
        "· 存储容量 E_store ≥ R_pdl×T_blind/CR（覆盖最长不可见时段）。"),
        units=["dpu", "storage", "data_bus", "ai_unit"]),
}

# ================================================================
# 八、平台库
# ================================================================
PLATFORMS = [
    dict(id="DFH-4", cn="东方红四号（DFH-4）", orbit="GEO", m_pay=600, p_pay=2400,
         m_sat=2300, life=15, heritage="中星/亚太系列飞行继承", vendor="CAST",
         note="GEO 大容量成熟平台，承载 600kg/供电 2400W"),
    dict(id="DFH-5", cn="东方红五号（DFH-5）", orbit="GEO", m_pay=1200, p_pay=8000,
         m_sat=5400, life=15, heritage="实践十三号/中星16号飞行继承", vendor="CAST",
         note="GEO 超大容量，Ka 高通量 100Gbps+ 首选；电推进"),
    dict(id="GEO-MID42", cn="中型 GEO 平台（42 型）", orbit="GEO", m_pay=420, p_pay=1900,
         m_sat=2100, life=15, heritage="商业批产平台", vendor="通用",
         note="中等承载，Ku/Ka 透明转发或多波束"),
    dict(id="GEO-LRG65", cn="大型 GEO 平台（65 型）", orbit="GEO", m_pay=800, p_pay=10000,
         m_sat=5200, life=15, heritage="Spacebus Neo/702X 同级", vendor="通用",
         note="大承载大功率，Ka 高通量+DTP 柔性载荷（载荷供电 10kW 级）"),
    dict(id="SSF-LEO300", cn="小型 LEO 平台（300 型）", orbit="LEO", m_pay=120, p_pay=800,
         m_sat=300, life=7, heritage="批产小卫星平台", vendor="GAL/CAST",
         note="LEO 批产星座；承载 120kg"),
    dict(id="SSF-LEO500", cn="中型 LEO 平台（500 型）", orbit="LEO", m_pay=320, p_pay=2400,
         m_sat=500, life=7, heritage="批产小卫星平台", vendor="GAL/CAST",
         note="LEO 宽带星座主力（Starlink v1.5 同级）；相控阵+再生载荷"),
    dict(id="SSF-LEO1000", cn="大型 LEO 平台（1000 型）", orbit="LEO", m_pay=700, p_pay=4500,
         m_sat=1500, life=7, heritage="VHTS/D2D 星座平台", vendor="GAL/CAST",
         note="超大口径展开相控阵（D2D）；承载 700kg"),
    dict(id="MEO-PLAT", cn="MEO 平台", orbit="MEO", m_pay=400, p_pay=3000,
         m_sat=1200, life=12, heritage="O3b 同类", vendor="通用",
         note="MEO 组网星座；中承载"),
    dict(id="SSO-PLAT", cn="SSO 平台", orbit="SSO", m_pay=400, p_pay=2200,
         m_sat=700, life=8, heritage="遥感平台改通信", vendor="CAST",
         note="SSO 数传中继/物联网星座"),
    dict(id="HEO-PLAT", cn="HEO 平台", orbit="HEO", m_pay=480, p_pay=2500,
         m_sat=2400, life=10, heritage="Molniya 继承", vendor="通用",
         note="大椭圆轨道高纬度覆盖；承载 480kg/供电 2500W（军用抗干扰大口径伞天线）"),
]

# ================================================================
# 九、运载火箭库
# ================================================================
LAUNCHERS = [
    dict(id="LM-3B", cn="长征三号乙", leo_t=11500, gto_t=5500, fairing="Φ4.0×9.56m",
         cost="中", heritage="高密度发射（90+次）", vendor="CALT",
         note="GTO 主力；单星 5.5t 级 GEO"),
    dict(id="LM-7A", cn="长征七号甲", leo_t=13500, gto_t=7000, fairing="Φ4.2×13m",
         cost="中高", heritage="新一代无毒推进", vendor="CALT",
         note="GTO 7t 级，大平台 GEO"),
    dict(id="LM-5", cn="长征五号", leo_t=25000, gto_t=14000, fairing="Φ5.2×20.5m",
         cost="高", heritage="重型运载", vendor="CALT",
         note="超大 GEO 平台（DFH-5）"),
    dict(id="LM-2D", cn="长征二号丁", leo_t=3500, gto_t=0, fairing="Φ3.35×8m",
         cost="低", heritage="SSO/LEO 高密度", vendor="CALT",
         note="LEO/SSO 小卫星"),
    dict(id="LM-11", cn="长征十一号", leo_t=700, gto_t=0, fairing="Φ2.0m",
         cost="低", heritage="固体快速发射", vendor="CALT",
         note="小型 LEO 快速补网"),
    dict(id="JK-1", cn="捷龙一号", leo_t=500, gto_t=0, fairing="Φ1.95m",
         cost="低", heritage="商业固体", vendor="CALT",
         note="小卫星拼车"),
    dict(id="ZQ-2", cn="朱雀二号", leo_t=4000, gto_t=0, fairing="Φ4.19m",
         cost="中", heritage="液氧甲烷（蓝箭）", vendor="蓝箭航天",
         note="商业 LEO 星座批产"),
    dict(id="Falcon9", cn="Falcon 9", leo_t=22800, gto_t=8300, fairing="Φ5.2×13.1m",
         cost="中（复用更低）", heritage="复用成熟", vendor="SpaceX",
         note="LEO 星座一箭多星；GTO 8.3t"),
    dict(id="Ariane6", cn="Ariane 6", leo_t=10300, gto_t=4500, fairing="Φ5.4m",
         cost="高", heritage="ESA 主力", vendor="Arianespace",
         note="GEO 商业发射"),
]

# ================================================================
# 十、场景预设库
# ================================================================
SCENARIOS = {
    "geo_ka_hts": dict(
        label="GEO Ka 高通量宽带（64 波束 · DTP 柔性）",
        desc="GEO 轨道、Ka 频段、2.5m 反射面多波束、DTP 数字透明处理，面向中国全境宽带接入。",
        cfg=dict(service="高通量宽带", orbit="GEO", coverage="中国全境", band="Ka",
                 mode="数字透明", ant_type="固面", array_subtype="",
                 user_band="Ka", feeder_band="Ka", isl_on=False, isl_type="",
                 D_ap=2.5, N_beam=64, B_beam=125, B_carrier=36, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.9, el_deg=45, life_yr=15,
                 N_el=1024, θ_scan=0, Mode="多波束", platform_pref="自动")),
    "geo_ku_dth": dict(
        label="GEO Ku 广播电视（单波束 · 透明转发）",
        desc="GEO 轨道、Ku 频段、2.5m 反射面单波束、透明转发器，面向广播电视 DTH。",
        cfg=dict(service="广播电视", orbit="GEO", coverage="中国全境", band="Ku",
                 mode="透明", ant_type="固面", array_subtype="",
                 user_band="Ku", feeder_band="Ku", isl_on=False, isl_type="",
                 D_ap=2.5, N_beam=1, B_beam=36, B_carrier=36, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.8, el_deg=45, life_yr=15,
                 Mode="单波束", platform_pref="自动")),
    "leo_broadband": dict(
        label="LEO 宽带星座（相控阵 · 再生 · 激光 ISL）",
        desc="LEO 550km、Ka 用户链路、数字模拟混合相控阵 16 波束、再生处理 + 激光星间组网。",
        cfg=dict(service="高通量宽带", orbit="LEO", coverage="区域", band="Ka",
                 mode="再生", ant_type="相控阵", array_subtype="数字模拟混合",
                 user_band="Ka", feeder_band="Ka", isl_on=True, isl_type="激光", isl_r_gbps=10,
                 D_ap=0.8, N_el=1024, θ_scan=45, N_beam=16, B_beam=250, B_carrier=62,
                 P_out=0, amp_type="MPA", C_req_ovr=20, GT_term="", EIRP_term="", A_avail=99.5,
                 el_deg=40, life_yr=7, Mode="在轨重构", platform_pref="自动")),
    "leo_d2d": dict(
        label="LEO 手机直连 D2D（12m 可展开相控阵 · S 波段）",
        desc="LEO 500km、S 频段、12m 可展开相控阵（模拟拼接瓦片）、再生处理，面向存量手机直连。",
        cfg=dict(service="手机直连D2D", orbit="LEO", coverage="全球", band="S",
                 mode="再生", ant_type="相控阵", array_subtype="模拟拼接",
                 user_band="S", feeder_band="Ka", isl_on=True, isl_type="激光", isl_r_gbps=10,
                 D_ap=12.0, N_el=2500, θ_scan=35, N_beam=48, B_beam=5, B_carrier=5,
                 P_out=0, amp_type="SSPA", GT_term="", EIRP_term="", A_avail=99.0,
                 el_deg=25, life_yr=7, Mode="波束跳变", platform_pref="自动")),
    "geo_mobile": dict(
        label="GEO L 移动通信（12m 伞天线 · 透明转发）",
        desc="GEO 轨道、L 频段、12m 伞状可展开天线、透明转发，面向手持终端移动通信（天通同类）。",
        cfg=dict(service="移动通信", orbit="GEO", coverage="中国全境", band="L",
                 mode="透明", ant_type="伞状", array_subtype="",
                 user_band="L", feeder_band="C", isl_on=False, isl_type="",
                 D_ap=12.0, N_beam=19, B_beam=10, B_carrier=1, k_reuse=7, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.5, el_deg=40, life_yr=15,
                 Mode="多波束", platform_pref="自动")),
    "meo_relay": dict(
        label="MEO 中继数传星座（Ka + 激光组网）",
        desc="MEO 8000km、Ka 频段、固面多波束、DTP 柔性 + 激光星间组网，面向遥感星天基中继。",
        cfg=dict(service="中继数传", orbit="MEO", coverage="全球", band="Ka",
                 mode="数字透明", ant_type="固面", array_subtype="",
                 user_band="Ka", feeder_band="Ka", isl_on=True, isl_type="激光", isl_r_gbps=10,
                 D_ap=3.0, N_beam=8, B_beam=250, B_carrier=125, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.9, el_deg=30, life_yr=12,
                 Mode="多波束", platform_pref="自动")),
    "heo_military": dict(
        label="HEO 军用抗干扰（再生处理 · 伞天线）",
        desc="HEO 大椭圆轨道、L 频段、12m 伞天线、再生处理 + 星上路由，高纬度抗干扰通信。",
        cfg=dict(service="军用抗干扰", orbit="HEO", coverage="极区", band="L",
                 mode="再生", ant_type="伞状", array_subtype="",
                 user_band="L", feeder_band="Ka", isl_on=False, isl_type="",
                 D_ap=12.0, N_beam=7, B_beam=25, B_carrier=25, k_reuse=7, P_out=0, amp_type="TWTA",
                 GT_term="", EIRP_term="", A_avail=99.9, el_deg=30, life_yr=10,
                 Mode="多波束", platform_pref="自动")),
    "leo_iot": dict(
        label="LEO 窄带物联网星座（S 波段 · DTP）",
        desc="LEO/SSO 700km、S 频段、小型相控阵（直射阵）、DTP 柔性，面向海量物联网终端存储转发。",
        cfg=dict(service="物联网", orbit="SSO", coverage="全球", band="S",
                 mode="数字透明", ant_type="相控阵", array_subtype="直射阵",
                 user_band="S", feeder_band="S", isl_on=False, isl_type="",
                 D_ap=0.5, N_el=256, θ_scan=40, N_beam=8, B_beam=5, B_carrier=0.2,
                 P_out=0, amp_type="SSPA", GT_term="", EIRP_term="", A_avail=99.0,
                 el_deg=30, life_yr=8, Mode="波束跳变", platform_pref="自动")),
}

# 默认配置（新方案起点）
DEFAULT_CFG = dict(
    name="新建方案", service="高通量宽带", orbit="GEO", coverage="中国全境", band="Ka",
    mode="数字透明", ant_type="相控阵", array_subtype="数字模拟混合",
    user_band="Ka", feeder_band="Ka", isl_on=False, isl_type="激光", isl_r_gbps=10,
    D_ap=2.0, N_el=1024, G_el=6.0, η_ill=68, θ_scan=0,
    N_beam=16, B_beam=125, B_carrier=36, P_out=0, amp_type="",
    GT_term="", EIRP_term="", design_cn="", EIRP_gs=75,
    A_avail=99.9, el_deg=30, life_yr=15,
    Mode="多波束", platform_pref="自动", launcher_pref="自动",
    cov_r_km=1500, beam_r_km=250, M_target=3.0,
)

# 频段 → 上行/下行频率默认
BAND_FREQ = {
    "L": (1.6265, 1.525), "S": (2.1, 2.3), "C": (6.0, 4.0), "X": (8.0, 7.5),
    "Ku": (14.0, 12.0), "Ka": (30.0, 20.0), "Q/V": (50.0, 40.0), "UHF": (0.4, 0.3),
    "激光": (193.4e3, 193.4e3),
}
# 频段 → 雨衰参考值（0.01% 超越概率、30°仰角，dB）
BAND_RAIN = {
    "L": (0.2, 0.2), "S": (0.3, 0.3), "C": (0.8, 0.5), "X": (1.2, 1.0),
    "Ku": (2.5, 2.0), "Ka": (12.0, 7.0), "Q/V": (20.0, 14.0), "UHF": (0.1, 0.1),
    "激光": (0, 0),
}
BAND_KEYS = ["L", "S", "C", "X", "Ku", "Ka", "Q/V"]

# ================================================================
# 十二、国家覆盖库 → COVERAGE 同构合成（模块加载时执行一次）
#   使 design_engine 无需区分"通用覆盖区"与"国家覆盖"两套逻辑，
#   el_min_deg/r_km/beam_r_km/k_typ/margin_add_db 已按各国 GEO 几何预算好。
# ================================================================
def _rain_to_margin(rain_text):
    """按 ITU-R P.618 雨衰区定性描述 → 动态余量附加（dB），与既有 COVERAGE 口径一致。"""
    if "极强" in rain_text:
        return 1.0
    if "强" in rain_text:
        return 0.8
    if "中等" in rain_text:
        return 0.5
    if "极弱" in rain_text:
        return 0.2
    if "弱" in rain_text:
        return 0.3
    return 0.6      # 混合/未标注


for _c in COUNTRIES:
    _key = _c["key"]
    _margin = _rain_to_margin(_c["rain"])
    _entry = dict(
        cn=_c["cn"] + ("覆盖" if "覆盖" not in _c["cn"] else ""),
        r_km=_c["r_km"], beam_r_km=_c["beam_r_km"], k_typ=_c["k_typ"],
        margin_add_db=_margin, el_min_deg=_c["el_min"],
        note=(f"{_c['cn']}（{_c['region']}）：国土等效覆盖半径约 {_c['r_km']}km，"
              f"建议波束半径 {_c['beam_r_km']}km；GEO 建议星位约 {_c['geo_lon']}°E；"
              f"最低用户仰角约 {_c['el_min']}°；雨衰区：{_c['rain']}"),
        lat=_c["lat"], lon=_c["lon"], geo_lon=_c["geo_lon"],
        country=True, region=_c["region"], rain_zone=_c["rain"],
    )
    if _key in COVERAGE:
        # 保留既有精细条目（如"巴基斯坦"），仅补充缺失的地理字段
        for k, v in _entry.items():
            COVERAGE[_key].setdefault(k, v)
    else:
        COVERAGE[_key] = _entry

# 覆盖区选项：基础类型 + 全部国家/地区（国家排在基础类型之后，便于 UI 分组）
COVERAGE_KEYS = ["全球", "中国全境", "区域", "省域", "热点小区", "航空航海走廊", "极区", "自定义"] + \
                [c["key"] for c in COUNTRIES]


# ================================================================
# 十一、在轨卫星参考库（ORBITAL_REFS）
#   用途：为选型/设计基准提供"真实在轨对标"——设计方案与同类在轨卫星
#   横向对比（容量/波束/口径/平台/频段），校准货架与平台库的合理性。
#   数据口径：均为公开发布参数（官方新闻稿/运营商资料/公开追踪库），
#   标 src 字段注明量级来源，供追溯；非精确工程值，仅作对标参考。
#   字段：id/cn/operator/orbit/band/capacity_gbps/mass_kg/platform/
#         n_beam/ant_d_m/launch/life_yr/feat/note/src
# ================================================================
ORBITAL_REFS = [
    # ---- GEO 高通量（Ka）----
    dict(id="ChinaSat-26", cn="中星26号", operator="中国卫通/航天五院", orbit="GEO",
         band="Ka", capacity_gbps=100, mass_kg=5400, platform="东方红四号增强型",
         n_beam=105, ant_d_m=None, launch="2023-02-23", life_yr=15,
         feat="全Ka频段·94用户波束+11信关波束·50路转发器·5副天线·星地一体设计",
         note="我国首颗超百Gbps容量民商用高通量卫星，覆盖国土及周边；首次全面使用27~30GHz频段",
         src="新华社/航天科技集团公开发布"),
    dict(id="ChinaSat-16", cn="中星16号", operator="中国卫通/航天五院", orbit="GEO",
         band="Ka", capacity_gbps=20, mass_kg=5200, platform="东方红四号",
         n_beam=26, ant_d_m=None, launch="2017-04-12", life_yr=15,
         feat="我国首颗Ka频段高通量卫星·机载宽带互联网",
         note="高通量卫星家族首发星，20Gbps级；与中星19/26组成Ka应用系统网络",
         src="航天科技集团公开发布"),
    dict(id="APstar-6D", cn="亚太6D", operator="亚太通信卫星/航天五院", orbit="GEO",
         band="Ka/Ku", capacity_gbps=50, mass_kg=5550, platform="东方红四号增强型",
         n_beam=90, ant_d_m=None, launch="2020-07-09", life_yr=15,
         feat="Ku+Ka双频段·90个Ku用户波束·亚太区域宽带",
         note="面向亚太的GEO高通量宽带星，50Gbps级；海上/机载宽带",
         src="运营商公开发布"),
    dict(id="SJT-13", cn="实践十三号", operator="航天五院", orbit="GEO",
         band="Ka", capacity_gbps=20, mass_kg=4600, platform="东方红五号（试验）",
         n_beam=None, ant_d_m=None, launch="2017-04-12", life_yr=15,
         feat="我国首颗Ka频段高通量试验星·电推进·DFH-5平台验证",
         note="高通量技术试验验证星，20Gbps级；DFH-5平台与电推进在轨验证",
         src="航天科技集团公开发布"),
    dict(id="SES-17", cn="SES-17", operator="SES/泰雷兹阿莱尼亚", orbit="GEO",
         band="Ka", capacity_gbps=200, mass_kg=6100, platform="Spacebus Neo（全电推进）",
         n_beam=200, ant_d_m=None, launch="2021-10-23", life_yr=15,
         feat="全数字透明处理DTP·~200可重构波束·16信关站·载荷功率17kW·ARC软件定义",
         note="SES首颗纯Ka高通量星，200Gbps级处理能力，单连接最高2Gbps；面向美洲/大西洋航空海事",
         src="SES官方资料"),
    dict(id="ViaSat-3-Am", cn="卫讯3号（美洲）", operator="Viasat/波音", orbit="GEO",
         band="Ka+Q/V", capacity_gbps=1000, mass_kg=6400, platform="Boeing 702X",
         n_beam=19, ant_d_m=None, launch="2023-05-01", life_yr=15,
         feat="Ka 200Gbps+Q/V 800Gbps=1Tbps单星·超宽带·三星座覆盖全球",
         note="单星吞吐量最大的GEO工程之一；Q/V频段8波束×100Gbps（5GHz×20bps/Hz 4096-QAM）",
         src="Viasat/波音公开发布"),
    # ---- LEO 宽带巨型星座 ----
    dict(id="Starlink-V2Mini", cn="星链V2 Mini", operator="SpaceX", orbit="LEO",
         band="Ka/E", capacity_gbps=96, mass_kg=800, platform="批产小卫星（V2 Mini）",
         n_beam=None, ant_d_m=None, launch="2023-02-27", life_yr=7,
         feat="Ku/Ka/E波段相控阵·激光星间链路·氩霍尔推进·550km/53°·AI波束成形",
         note="单星下行~80~96Gbps（v1.5的4倍）；530~550km、53°倾角；一箭21~23星",
         src="SpaceX/公开追踪库"),
    dict(id="Starlink-V1.5", cn="星链V1.5", operator="SpaceX", orbit="LEO",
         band="Ku/Ka", capacity_gbps=22, mass_kg=306, platform="批产小卫星（V1.5）",
         n_beam=None, ant_d_m=None, launch="2021-09", life_yr=5,
         feat="Ku/Ka相控阵·首批激光星间链路·氪霍尔推进·550km/53°",
         note="单星20~24Gbps；巨型星座主力代际，一箭49~54星",
         src="SpaceX/公开追踪库"),
    dict(id="OneWeb", cn="一网（OneWeb）", operator="Eutelsat OneWeb", orbit="LEO",
         band="Ku/Ka", capacity_gbps=8, mass_kg=150, platform="批产小卫星",
         n_beam=None, ant_d_m=None, launch="2019-02（批产2020~2023）", life_yr=7,
         feat="648星Walker星座·1200km·87.9°近极倾角·Ku用户+Ka馈电",
         note="近极轨道全球覆盖（含极区）；648星一期已组网",
         src="OneWeb/Eutelsat公开发布"),
    dict(id="Qianfan-G60", cn="千帆星座（G60星链）", operator="上海垣信卫星", orbit="LEO",
         band="Ku/Ka", capacity_gbps=48, mass_kg=300, platform="批产平板小卫星",
         n_beam=None, ant_d_m=None, launch="2024-08-06（首批18星）", life_yr=7,
         feat="平板堆叠批产·激光星间链路·一箭多星·规划1.4万星",
         note="我国低轨宽带巨型星座代表；单星48Gbps级，一期千星组网",
         src="垣信卫星/公开发布"),
    dict(id="Guowang-GW", cn="国网星座（GW）", operator="中国星网", orbit="LEO",
         band="Ka/Ku", capacity_gbps=None, mass_kg=None, platform="批产小卫星",
         n_beam=None, ant_d_m=None, launch="2024-12（首批）", life_yr=None,
         feat="国家级低轨互联网星座·规划约1.3万星·多轨道面",
         note="我国卫星互联网国家工程；具体单星参数未完全公开，作规划对标",
         src="中国星网/公开发布"),
    # ---- MEO ----
    dict(id="O3b-mPOWER", cn="O3b mPOWER", operator="SES/波音", orbit="MEO",
         band="Ka", capacity_gbps=10, mass_kg=900, platform="Boeing 702X（MEO）",
         n_beam=5000, ant_d_m=None, launch="2022-12-16（首批）", life_yr=10,
         feat="中轨8000km·全数字载荷·5000+可成形波束·低时延（相对GEO）",
         note="MEO软件定义星座；单星10Gbps级、时延~120ms（远低于GEO 500ms）",
         src="SES/波音公开发布"),
]
ORBITAL_REF_BY_ID = {s["id"]: s for s in ORBITAL_REFS}


def orbital_refs_for(orbit=None, band=None):
    """按轨道/频段过滤在轨参考星（band 支持 'Ka'→匹配含Ka的星）。"""
    out = []
    for s in ORBITAL_REFS:
        if orbit and s["orbit"] != orbit:
            continue
        if band and band.upper().replace("/", "") not in s["band"].upper().replace("/", ""):
            continue
        out.append(s)
    return out

