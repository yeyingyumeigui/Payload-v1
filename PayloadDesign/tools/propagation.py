# -*- coding: utf-8 -*-
"""ITU-R 传播模型库（纯 Python 零依赖，冻结 exe 可用）。

覆盖星地链路三类传播损耗的第一性原理计算：
  · ITU-R P.838-3  雨致比衰减 γ_R = k·R^α（k/α 四表高斯和拟合系数，逐字核对原建议书）
  · ITU-R P.839-4  雨高 h_R = h_0 + 0.36 km（0°C 等温线高度的纬度近似式）
  · ITU-R P.618    斜路径雨衰 A_0.01 = γ_R·L_E；时间百分比换算 A_p；反演 p(A)
  · ITU-R P.837    雨气候区 R_0.01（本库用「纬度带 + 世界主要干/湿区地理盒」
                   气候学近似，见 _R001_* 注释；绝对值可按工程基准归一）
  · 大气气体损耗   按 1/sin(el) 斜路径放大引擎既有天顶参考值（与 design_all 同源）

设计约定（重要）：
  本库提供**空间分布结构**，绝对量级可通过 normalize_to 锚定到引擎既有雨衰参考
  （design_data.BAND_RAIN / COVERAGE.margin_add_db），保证与链路预算同源、不引入回归。
  raw=True 时输出未归一的 ITU 原始预测值。

所有系数均来自 ITU-R 建议书原文（P.838-3 Table 1~4、P.839-4 §2、P.618 §2.2.1.1
步骤 1~10），不凭记忆填数。
"""
from __future__ import annotations

import math

DEG = math.pi / 180.0
R_EARTH_KM = 6371.0
R_EFF_KM = 8500.0          # P.618 采用的等效地球半径（4/3 近似）


# ================================================================
# 一、ITU-R P.838-3：雨致比衰减 γ_R = k·R^α
# ================================================================
# log10 k = Σ_{j=1..4} a_j·exp[−((log10 f − b_j)/c_j)²] + m_k·log10 f + c_k
# α       = Σ_{j=1..5} a_j·exp[−((log10 f − b_j)/c_j)²] + m_α·log10 f + c_α
# 四张表的系数（P.838-3 Table 1 k_H / Table 2 k_V / Table 3 α_H / Table 4 α_V）
_K_H = dict(a=(-5.33980, -0.35351, -0.23789, -0.94158),
            b=(-0.10008, 1.26970, 0.86036, 0.64552),
            c=(1.13098, 0.45400, 0.15354, 0.16817),
            m=-0.18961, k=0.71147)
_K_V = dict(a=(-3.80595, -3.44965, -0.39902, 0.50167),
            b=(0.56934, -0.22911, 0.73042, 1.07319),
            c=(0.81061, 0.51059, 0.11899, 0.27195),
            m=-0.16398, k=0.63297)
_A_H = dict(a=(-0.14318, 0.29591, 0.32177, -5.37610, 16.1721),
            b=(1.82442, 0.77564, 0.63773, -0.96230, -3.29980),
            c=(-0.55187, 0.19822, 0.13164, 1.47828, 3.43990),
            m=0.67849, k=-1.95537)
_A_V = dict(a=(-0.07771, 0.56727, -0.20238, -48.2991, 48.5833),
            b=(2.33840, 0.95545, 1.14520, 0.791669, 0.791459),
            c=(-0.76284, 0.54039, 0.26809, 0.116226, 0.116479),
            m=-0.053739, k=0.83433)


def _gauss_sum(tab, log_f):
    s = 0.0
    for aj, bj, cj in zip(tab["a"], tab["b"], tab["c"]):
        s += aj * math.exp(-((log_f - bj) / cj) ** 2)
    return s


def p838_k_alpha(f_ghz, pol="V"):
    """ITU-R P.838-3 → (k, α)。pol: "H"/"V"/"C"（圆极化按 P.838-3 §注 2 合成）。
    有效范围 1~1000 GHz。"""
    f = max(float(f_ghz), 0.5)
    lf = math.log10(f)
    kH = 10.0 ** (_gauss_sum(_K_H, lf) + _K_H["m"] * lf + _K_H["k"])
    kV = 10.0 ** (_gauss_sum(_K_V, lf) + _K_V["m"] * lf + _K_V["k"])
    aH = _gauss_sum(_A_H, lf) + _A_H["m"] * lf + _A_H["k"]
    aV = _gauss_sum(_A_V, lf) + _A_V["m"] * lf + _A_V["k"]
    p = (pol or "V").strip().upper()[:1]
    if p == "H":
        return kH, aH
    if p == "C":
        # 圆极化（τ=45°，θ 影响 <1% 时取 cos²θcos2τ→0）：k=(kH+kV)/2
        kc = 0.5 * (kH + kV)
        ac = (kH * aH + kV * aV) / (2.0 * kc) if kc > 0 else 0.5 * (aH + aV)
        return kc, ac
    return kV, aV


def specific_atten(f_ghz, R_mm_h, pol="V"):
    """比衰减 γ_R（dB/km）= k·R^α。R≤0 → 0。"""
    R = float(R_mm_h)
    if R <= 0.0:
        return 0.0
    k, a = p838_k_alpha(f_ghz, pol)
    return k * (R ** a)


# ================================================================
# 二、ITU-R P.839-4：雨高 h_R
# ================================================================
def isotherm0_km(lat_deg, lon_deg=0.0):
    """年均 0°C 等温线高度 h_0（km）——P.839 早期版本的纬度近似式
    （无数字地图时的工程近似；P.839-4 正式数据为 1.5°×1.5° 全球网格）。
    北美与西欧（lon<60°E，35°<lat<70°）另有专用式。"""
    la = float(lat_deg)
    lo = float(lon_deg) % 360.0
    if lo > 180.0:
        lo -= 360.0
    if 35.0 < la < 70.0 and lo < 60.0:
        return max(3.2 - 0.075 * (la - 35.0), 0.5)
    if la > 23.0:
        return max(5.0 - 0.075 * (la - 23.0), 0.5)
    if la >= 0.0:
        return 5.0
    if la > -21.0:
        return 5.0
    if la > -71.0:
        return max(5.0 + 0.1 * (la + 21.0), 0.5)
    return 0.5


def rain_height_km(lat_deg, lon_deg=0.0):
    """年均雨高 h_R = h_0 + 0.36 km（P.839-4 §2，0.36 km 计入融化层影响）。"""
    return isotherm0_km(lat_deg, lon_deg) + 0.36


# ================================================================
# 三、ITU-R P.837：R_0.01 气候学近似
# ----------------------------------------------------------------
# 正式做法是查 P.837-7 的 1.5°×1.5° 全球 R_0.01 数字地图（ITU 提供 ZIP）。
# 本库在**无数字地图**条件下用「纬度带基值 + 世界主要干旱/多雨区地理盒」
# 近似（地理盒依据：ITCZ 赤道多雨带、副热带高压干旱带、季风区、
# 亚马逊/刚果/东南亚雨林、撒哈拉/阿拉伯/戈壁/澳洲内陆/阿塔卡马荒漠）。
# 用途是**空间相对分布**；绝对量级由 normalize_to 锚定工程基准（见模块头）。
# ================================================================
# R_0.01 参考量级（P.837 Table 1，0.01% 行）：A=8 B=12 C=15 D=19 E=22 F=28
# G=30 H=32 J=35 K=42 L=60 M=63 N=95 P=145 Q=115
R001_BY_ZONE = dict(A=8.0, B=12.0, C=15.0, D=19.0, E=22.0, F=28.0, G=30.0,
                    H=32.0, J=35.0, K=42.0, L=60.0, M=63.0, N=95.0,
                    P=145.0, Q=115.0)

# 纬度带基值（|lat| → R_0.01 mm/h）：赤道 ITCZ 高、副热带低、中高纬递减、极地极低
_LAT_BANDS = ((5.0, 70.0), (10.0, 55.0), (15.0, 42.0), (23.0, 32.0),
              (30.0, 25.0), (40.0, 22.0), (50.0, 18.0), (60.0, 14.0),
              (70.0, 9.0), (90.1, 4.0))

# 多雨区地理盒 (lat_lo, lat_hi, lon_lo, lon_hi, R001)
_WET_BOXES = (
    (-15.0, 5.0, -78.0, -45.0, 130.0),    # 亚马逊盆地
    (-10.0, 5.0, 10.0, 32.0, 120.0),      # 刚果盆地
    (-10.0, 10.0, 95.0, 140.0, 110.0),    # 印度尼西亚/马来西亚（赤道雨衰主导）
    (-12.0, 0.0, 130.0, 155.0, 130.0),    # 巴布亚新几内亚
    (0.0, 10.0, -10.0, 10.0, 110.0),      # 几内亚湾沿岸（喀麦隆/加蓬，ITU P 区量级）
    (7.0, 22.0, -92.0, -60.0, 95.0),      # 中美洲/加勒比
    (8.0, 16.0, 73.0, 77.5, 110.0),       # 印度西高止山脉西南海岸
    (20.0, 28.0, 86.0, 93.0, 120.0),      # 印度东北/孟加拉（世界雨极邻域）
    (8.0, 30.0, 70.0, 90.0, 45.0),        # 南亚季风区（印度大部）
    (18.0, 28.0, 105.0, 122.0, 60.0),     # 华南/中南半岛东部季风
    (30.0, 42.0, 128.0, 146.0, 45.0),     # 日本/朝鲜半岛（梅雨+台风）
    (25.0, 42.0, -92.0, -70.0, 45.0),     # 美国东部/东南部
    (-40.0, -15.0, 142.0, 154.0, 45.0),   # 澳大利亚东海岸
    (-10.0, 10.0, -85.0, -60.0, 70.0),    # 亚马逊口/圭亚那
)

# 干旱区地理盒
_DRY_BOXES = (
    (15.0, 32.0, -17.0, 35.0, 3.0),       # 撒哈拉
    (12.0, 32.0, 34.0, 60.0, 3.0),        # 阿拉伯半岛
    (25.0, 40.0, 44.0, 72.0, 6.0),        # 伊朗/阿富汗高原
    (24.0, 32.0, 66.0, 75.0, 8.0),        # 塔尔沙漠
    (36.0, 48.0, 75.0, 110.0, 4.0),       # 戈壁/塔克拉玛干
    (-32.0, -18.0, 113.0, 145.0, 3.0),    # 澳大利亚内陆
    (-32.0, -12.0, -78.0, -66.0, 1.5),    # 阿塔卡马/秘鲁沿岸
    (-30.0, -15.0, 12.0, 25.0, 3.0),      # 纳米布/卡拉哈里
    (-50.0, -38.0, -73.0, -63.0, 5.0),    # 巴塔哥尼亚
    (30.0, 45.0, -120.0, -105.0, 6.0),    # 美国大盆地
)


def _in_box(lat, lon, box):
    la0, la1, lo0, lo1, val = box
    if not (la0 <= lat <= la1):
        return None
    # 经度盒统一化到 [−180,180)；跨 180° 的盒本库未使用
    lo = ((lon + 180.0) % 360.0) - 180.0
    if lo0 <= lo1:
        return val if lo0 <= lo <= lo1 else None
    return val if (lo >= lo0 or lo <= lo1) else None


def r001_climatology(lat_deg, lon_deg):
    """R_0.01（mm/h，1 分钟积分）气候学近似：纬度带基值 + 干/湿区地理盒覆盖。
    返回 (R001, tag)，tag ∈ {"equatorial","monsoon","temperate","arid","polar","base"}。

    地理盒判定顺序：**干旱盒优先**——干旱区（撒哈拉/阿拉伯/塔尔/戈壁/阿塔卡马…）
    边界锐利且与相邻多雨盒（季风区）在国界处相接，先判干旱可避免把巴基斯坦/
    印度西北部误判为季风区（ITU 雨区实测：巴基斯坦属 A/B 干旱区，非 K 季风区）。"""
    la = float(lat_deg)
    ala = abs(la)
    for box in _DRY_BOXES:
        v = _in_box(la, lon_deg, box)
        if v is not None:
            return v, "arid"
    for box in _WET_BOXES:
        v = _in_box(la, lon_deg, box)
        if v is not None:
            return v, ("equatorial" if abs(box[0]) < 15.0 and abs(box[1]) < 15.0
                       else "monsoon")
    for hi, val in _LAT_BANDS:
        if ala <= hi:
            if ala >= 70.0:
                return val, "polar"
            return val, ("equatorial" if ala < 10.0 else
                         ("temperate" if ala >= 30.0 else "base"))
    return 4.0, "polar"


def rain_intensity_tag(lat_deg, lon_deg):
    """雨衰强度中文标签（供报告/前端展示）。"""
    r, _ = r001_climatology(lat_deg, lon_deg)
    if r >= 100.0:
        return "极强（赤道雨衰区）"
    if r >= 60.0:
        return "很强（热带）"
    if r >= 40.0:
        return "强（季风/热带）"
    if r >= 20.0:
        return "中等"
    if r >= 8.0:
        return "弱"
    return "极弱（干旱/荒漠）"


# ================================================================
# 四、ITU-R P.618：斜路径雨衰
# ================================================================
def rain_atten_slant(f_ghz, R001_mm_h, el_deg, lat_deg, p_pct=0.01,
                     pol="V", h_s_km=0.0, lon_deg=0.0, detail=False):
    """P.618 §2.2.1.1 步骤 1~10 → 超过 p% 时间的斜路径雨衰 A_p（dB）。

    f_ghz    : 频率（GHz，适用 1~55 GHz）
    R001     : 0.01% 时间超过的雨强（mm/h，1 min 积分）
    el_deg   : 仰角 θ（度）；lat_deg : 地面站纬度 φ（度，带符号）
    p_pct    : 目标时间百分比（0.001~5，单位 %）
    h_s_km   : 地面站海拔（km）
    detail   : True → 返回 (A_p, dict) 含 γ_R/L_s/L_G/r/v/L_R/L_E/A_0.01/β/h_R
    """
    el = max(float(el_deg), 0.5)
    se, ce = math.sin(el * DEG), math.cos(el * DEG)
    h_R = rain_height_km(lat_deg, lon_deg)
    h_s = max(float(h_s_km), 0.0)
    # 步骤 1~2：斜路径长度 L_s 与水平投影 L_G
    if el > 5.0:
        L_s = (h_R - h_s) / se
    else:
        # 低仰角：球面修正（P.618 式 10b）
        L_s = 2.0 * (h_R - h_s) / (se + math.sqrt(se * se + 2.0 * (h_R - h_s) / R_EFF_KM))
    L_s = max(L_s, 0.0)
    L_G = L_s * ce
    # 步骤 3~4：比衰减 γ_R
    gR = specific_atten(f_ghz, R001_mm_h, pol)
    f = max(float(f_ghz), 1.0)
    # 步骤 5：水平路径缩减因子 r_0.01（弱雨长路径时式可 >1 → 钳制到 1：
    # 有效路径不应超过几何路径）
    r001 = 1.0 / (1.0 + 0.78 * math.sqrt(max(L_G * gR / f, 0.0))
                  - 0.38 * (1.0 - math.exp(-2.0 * L_G)))
    r001 = min(r001, 1.0)
    # 步骤 6~7：垂直调整因子 v_0.01 → 有效路径 L_E
    chi = max(36.0 - abs(lat_deg), 0.0)
    if el > 5.0:
        L_R = L_G * r001 / ce
    else:
        L_R = L_s
    v001 = 1.0 / (1.0 + math.sqrt(se) * (31.0 * (1.0 - math.exp(-el / (1.0 + chi)))
                                         * math.sqrt(max(L_R * gR, 0.0)) / (f * f)
                                         - 0.45))
    L_E = L_R * v001
    A001 = gR * L_E
    # 步骤 10：换算到其他时间百分比
    A_p, beta = rain_atten_at_pct(A001, p_pct, el, lat_deg)
    if detail:
        return A_p, dict(h_R_km=round(h_R, 3), h_s_km=h_s, L_s_km=round(L_s, 3),
                         L_G_km=round(L_G, 3), gamma_R=round(gR, 4),
                         r001=round(r001, 4), v001=round(v001, 4),
                         L_R_km=round(L_R, 3), L_E_km=round(L_E, 3),
                         A001_db=round(A001, 3), A_p_db=round(A_p, 3),
                         p_pct=p_pct, beta=round(beta, 5), el_deg=round(el, 3),
                         lat_deg=lat_deg, R001=R001_mm_h, f_ghz=f, pol=pol)
    return A_p


def rain_atten_at_pct(A001_db, p_pct, el_deg, lat_deg):
    """P.618 式 (25)~(27)：A_p = A_0.01·(p/0.01)^[−(0.655+0.033ln p−0.045ln A_0.01
    −β(1−p)sinθ)]，有效范围 0.001% ≤ p ≤ 5%。返回 (A_p, β)。"""
    A001 = max(float(A001_db), 1e-9)
    p = min(max(float(p_pct), 0.001), 5.0)
    el = max(float(el_deg), 0.5)
    ala = abs(float(lat_deg))
    se = math.sin(el * DEG)
    # β（P.618 式 27 注）
    if p >= 1.0 or ala >= 36.0:
        beta = 0.0
    elif el >= 25.0:
        beta = -0.005 * (ala - 36.0)
    else:
        beta = -0.005 * (ala - 36.0) + 1.8 - 4.25 * se
    expo = -(0.655 + 0.033 * math.log(p) - 0.045 * math.log(A001)
             - beta * (1.0 - p) * se)
    return A001 * (p / 0.01) ** expo, beta


def unavailability_from_atten(A001_db, A_target_db, el_deg, lat_deg):
    """反演：给定可承受雨衰 A_target（dB），求对应的超出时间百分比 p（%）。
    A_p 对 p 单调递减 → 二分求解；A_target ≥ A_0.001 → 返回 0.001（下限），
    A_target ≤ A_5 → 返回 5.0（上限，链路几乎不可用）。"""
    A001 = max(float(A001_db), 1e-9)
    At = float(A_target_db)
    if At <= 0.0:
        return 5.0
    # A_p 对 p 单调递减：A(0.001%) 最大、A(5%) 最小
    a_hi_p, _ = rain_atten_at_pct(A001, 0.001, el_deg, lat_deg)   # 最小 p → 最大 A
    if At >= a_hi_p:
        return 0.001          # 目标衰减超过 0.001% 档 → 截断下限
    a_lo_p, _ = rain_atten_at_pct(A001, 5.0, el_deg, lat_deg)     # 最大 p → 最小 A
    if At <= a_lo_p:
        return 5.0            # 目标衰减低于 5% 档 → 截断上限（链路几乎不可用）
    lo, hi = 0.001, 5.0
    for _ in range(60):
        mid = math.sqrt(lo * hi)          # 对数域二分（p 跨 3 个数量级）
        v, _ = rain_atten_at_pct(A001, mid, el_deg, lat_deg)
        if v > At:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1.0005:
            break
    return math.sqrt(lo * hi)


def availability_from_atten(A001_db, A_target_db, el_deg, lat_deg):
    """链路可用度（%）= 100 − p_unavail，p 由 unavailability_from_atten 反演。"""
    return max(min(100.0 - unavailability_from_atten(A001_db, A_target_db,
                                                     el_deg, lat_deg), 100.0), 0.0)


# ================================================================
# 五、大气气体损耗（斜路径放大，与 design_all 同源）
# ================================================================
def gas_atten_slant(A_zenith_db, el_deg, f_ghz=None):
    """气体（O₂+H₂O）斜路径损耗：天顶参考值按 1/sin(el) 放大。

    A_zenith_db 取引擎既有同口径值（design_engine.cfg_to_params 的 A_atm/A_atm_dl，
    Ka≈0.4/0.2 dB、Ku/X≈0.15/0.12 dB、L/S≈0.05 dB）——保持与链路预算同源，
    避免与 ITU-R P.676 逐线计算产生口径冲突（P.676 Annex 2 在 20/30 GHz
    与上述天顶值偏差 <0.1 dB，工程可互换）。
    低仰角钳制到 5°（P.676 简化式适用下限；更低仰角由链路预算按最差区闭合）。
    """
    A0 = max(float(A_zenith_db), 0.0)
    el = max(float(el_deg), 5.0)
    return A0 / math.sin(el * DEG)


# ================================================================
# 六、统计工具（蒙特卡洛用）
# ================================================================
def percentile(sorted_vals, q):
    """已排序序列的 q 分位（q∈[0,1]，线性插值）。空序列 → 0。"""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    idx = q * (n - 1)
    i0 = int(math.floor(idx))
    i1 = min(i0 + 1, n - 1)
    w = idx - i0
    return float(sorted_vals[i0]) * (1.0 - w) + float(sorted_vals[i1]) * w


def norm_ppf(p):
    """标准正态分位数（Acklam 有理逼近，|误差|<1.15e-9）——蒙特卡洛无需 random.gauss
    之外的库，但报告里给 P10/P90 的分位因子时用得上。"""
    p = min(max(float(p), 1e-9), 1.0 - 1e-9)
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# ================================================================
# 去极化 / 交叉极化鉴别率 XPD（ITU-R P.618-12 §4.1）
# ================================================================
def xpd_v_freq(f_ghz):
    """XPD 雨衰依赖项系数 V(f)（P.618-12，6~55GHz 分段）。"""
    f = float(f_ghz)
    if f < 9.0:
        return 30.8 * f ** -0.21
    if f < 20.0:
        return 12.8 * f ** 0.19
    if f < 40.0:
        return 22.6
    return 13.0 * f ** 0.15           # 40~55 GHz


def xpd_c_freq(f_ghz):
    """XPD 频率相关项 C_f（P.618-12，6~55GHz 分段）。"""
    f = float(f_ghz)
    if f < 9.0:
        return 60.0 * math.log10(f) - 28.3
    if f < 36.0:
        return 26.0 * math.log10(f) + 4.1
    return 35.9 * math.log10(f) - 11.3


def _sigma_canting(p_pct):
    """雨滴倾斜角标准差 σ（度）：按超出时间百分比取值（P.618 Step 5）。"""
    if p_pct >= 1.0:
        return 0.0
    if p_pct >= 0.1:
        return 5.0
    if p_pct >= 0.01:
        return 10.0
    return 15.0


def xpd_from_rain(f_ghz, A_p_db, p_pct=0.01, el_deg=30.0, tau_deg=0.0):
    """由同路径共极雨衰 A_p 预测交叉极化鉴别率 XPD（P.618-12 §4.1 Step 1~8）。

    f_ghz   : 频率（GHz，有效 6~55）
    A_p_db  : p% 时间超出的共极雨衰（dB）
    p_pct   : 超出时间百分比（%）
    el_deg  : 路径仰角（度，≤60 有效）
    tau_deg : 线极化倾角（0/90=水平/垂直，45=圆极化）
    返回 dict：XPD_rain（未含冰晶）、C_ice、XPD_p（含冰晶，p% 时间不超出值）。
    物理：雨滴去极化随雨衰增大而恶化（XPD 降低），随频率升高、仰角降低而恶化。"""
    A_p = max(float(A_p_db), 1e-3)
    C_f = xpd_c_freq(f_ghz)
    V = xpd_v_freq(f_ghz)
    C_A = V * math.log10(A_p)
    # 极化改善因子 C_tau（圆极化 tau=45° → 0；线极化 tau=0/90° → 最大 ~15dB）
    tau = math.radians(float(tau_deg))
    arg = 1.0 - 0.484 * (1.0 + math.cos(4.0 * tau))
    C_tau = -10.0 * math.log10(arg) if arg > 1e-6 else 15.0
    # 仰角项 C_theta
    el = min(max(float(el_deg), 1.0), 60.0)
    C_th = -40.0 * math.log10(math.cos(math.radians(el)))
    # 倾斜角项 C_sigma
    sigma = _sigma_canting(p_pct)
    C_sig = 0.0052 * sigma ** 2
    XPD_rain = C_f - C_A + C_tau + C_th + C_sig
    # 冰晶项（Step 7/8）
    C_ice = XPD_rain * (0.3 + 0.1 * math.log10(p_pct)) / 2.0 if XPD_rain > 0 else 0.0
    XPD_p = XPD_rain - C_ice
    return dict(XPD_rain=round(XPD_rain, 2), C_ice=round(C_ice, 2),
                XPD_p=round(XPD_p, 2), C_f=round(C_f, 2), C_A=round(C_A, 2),
                C_tau=round(C_tau, 2), C_theta=round(C_th, 2),
                C_sigma=round(C_sig, 2), V=round(V, 2), sigma=sigma,
                f_ghz=float(f_ghz), A_p_db=round(A_p, 3), p_pct=float(p_pct),
                el_deg=el, tau_deg=float(tau_deg))


def crosspol_isolation_margin(f_ghz, A_p_db, p_pct, el_deg, xpd_spec_db,
                              reuse_xpol_db=30.0, tau_deg=0.0):
    """双极化频率复用的极化隔离核查：预测 XPD vs 天线交极化隔离指标。

    reuse_xpol_db : 天线本身的交极化隔离（典型 30~35dB），系统实际隔离取
                    min(天线隔离, 雨致 XPD)——雨大时由传播主导。
    返回 dict：XPD_p、有效隔离、相对复用要求的隔离裕度、是否满足判定。"""
    x = xpd_from_rain(f_ghz, A_p_db, p_pct, el_deg, tau_deg)
    xpd_p = x["XPD_p"]
    eff_iso = min(xpd_p, float(reuse_xpol_db))     # 雨/天线取劣
    # 双极化复用要求：交极分量比同极低 (C/I)_pol，工程取 ~30dB 隔离
    margin = eff_iso - float(xpd_spec_db)
    ok = margin >= 0.0
    verdict = ("频率 %.1fGHz 雨衰 %.2fdB@%.3f%%：预测 XPD=%.1fdB，"
               "有效极化隔离 %.1fdB（天线 %.0fdB 与雨致取劣），"
               "相对复用要求 %.0fdB 裕度 %+.1fdB → %s"
               % (f_ghz, A_p_db, p_pct, xpd_p, eff_iso, reuse_xpol_db,
                  xpd_spec_db, margin, "满足" if ok else "不满足（去极化严重，需 XPIC/降复用）"))
    return dict(ok=ok, eff_iso_db=round(eff_iso, 2), margin_db=round(margin, 2),
                xpd=x, reuse_xpol_db=float(reuse_xpol_db),
                xpd_spec_db=float(xpd_spec_db), verdict=verdict)


# ================================================================
# 自检
# ================================================================
if __name__ == "__main__":
    print("=== propagation self-test (ITU-R P.838-3 / P.839-4 / P.618 / P.837) ===")
    # 1) P.838-3 系数：与文献核对。独立基准①RACOM 表（P.838 圆整值）：
    #    11GHz kV=0.02/αV=1.16，17GHz kV=0.07/αV=1.01，24GHz kV=0.14/αV=0.96
    #    ②MDPI Sensors 23(4642)：20.2GHz 垂直极化 k=0.0981、α=0.9831
    kV20, aV20 = p838_k_alpha(20.0, "V")
    kH20, aH20 = p838_k_alpha(20.0, "H")
    print("[P.838-3 20GHz] kV=%.5f αV=%.4f | kH=%.5f αH=%.4f" % (kV20, aV20, kH20, aH20))
    assert 0.085 < kV20 < 0.110, "20GHz kV 应≈0.096~0.098（MDPI 基准），实得 %.5f" % kV20
    assert 0.93 < aV20 < 1.05, "20GHz αV 应≈0.983（MDPI 基准），实得 %.4f" % aV20
    assert aH20 > aV20, "同频水平极化 α 应大于垂直极化"
    assert 0.5 < kH20 / kV20 < 2.0, "20GHz kH/kV 应同量级（交叉频段），实得 %.3f" % (kH20 / kV20)
    # 12 GHz（Ku 下行）：RACOM 11GHz kV=0.02/αV=1.16 → 12GHz kV≈0.025/αV≈1.14
    kV12, aV12 = p838_k_alpha(12.0, "V")
    assert 0.015 < kV12 < 0.038 and 1.05 < aV12 < 1.25, \
        "12GHz kV/αV 应在 0.025/1.14 附近，实得 %.5f/%.4f" % (kV12, aV12)
    # 30 GHz（Ka 上行）：RACOM 24GHz kV=0.14/αV=0.96 → 30GHz kV≈0.20/αV≈0.95
    kV30, aV30 = p838_k_alpha(30.0, "V")
    assert 0.14 < kV30 < 0.28 and 0.88 < aV30 < 1.02, \
        "30GHz kV/αV 异常：%.5f/%.4f" % (kV30, aV30)
    # 10 GHz 低频：RACOM kH=0.01/αH=1.26
    kH10, aH10 = p838_k_alpha(10.0, "H")
    assert 0.006 < kH10 < 0.016 and 1.20 < aH10 < 1.32, \
        "10GHz kH/αH 应≈0.010/1.26，实得 %.5f/%.4f" % (kH10, aH10)
    # 圆极化介于 H/V 之间
    kC, aC = p838_k_alpha(20.0, "C")
    assert min(kV20, kH20) <= kC <= max(kV20, kH20), "圆极化 k 应在 H/V 之间"
    # 1 GHz 低频率：γ 极小（L 波段雨衰≈0）
    assert specific_atten(1.5, 50.0, "V") < 0.05, "L 波段 50mm/h 雨衰应 <0.05 dB/km"

    # 2) P.839-4 雨高：赤道 5.36 km、中纬 4~5 km、高纬更低
    hR0 = rain_height_km(0.0, 0.0)
    hR30 = rain_height_km(30.0, 105.0)
    hR60 = rain_height_km(60.0, 100.0)
    print("[P.839-4] h_R(0°)=%.2f h_R(30°)=%.2f h_R(60°)=%.2f km" % (hR0, hR30, hR60))
    assert abs(hR0 - 5.36) < 0.01, "赤道雨高应=5.36km，实得 %.3f" % hR0
    assert hR60 < hR30 < hR0, "雨高应随纬度递减"
    assert 3.0 < hR30 < 5.0, "30°N 雨高应 3~5km，实得 %.2f" % hR30

    # 3) R_0.01 气候学：赤道雨林 > 季风区 > 温带 > 荒漠 > 极地
    r_amz, t_amz = r001_climatology(-3.0, -60.0)      # 亚马逊
    r_ind, t_ind = r001_climatology(22.0, 79.0)       # 印度中部
    r_chn, t_chn = r001_climatology(35.0, 105.0)      # 中国中部
    r_sah, t_sah = r001_climatology(23.0, 13.0)       # 撒哈拉
    r_pak, t_pak = r001_climatology(30.5, 69.5)       # 巴基斯坦
    r_idn, t_idn = r001_climatology(-2.5, 118.0)      # 印度尼西亚
    r_pol, t_pol = r001_climatology(78.0, 15.0)       # 极地
    print("[P.837 近似] 亚马逊=%.0f(%s) 印尼=%.0f(%s) 印度=%.0f(%s) 中国=%.0f(%s) "
          "巴基斯坦=%.0f(%s) 撒哈拉=%.1f(%s) 极地=%.0f(%s)"
          % (r_amz, t_amz, r_idn, t_idn, r_ind, t_ind, r_chn, t_chn,
             r_pak, t_pak, r_sah, t_sah, r_pol, t_pol))
    assert r_amz > r_chn > r_sah, "雨林 > 温带 > 荒漠 排序错误"
    assert r_idn > 90.0, "印度尼西亚应属极强雨衰区，实得 %.0f" % r_idn
    assert r_pak < 10.0 and t_pak == "arid", "巴基斯坦北部应为干旱区，实得 %.0f/%s" % (r_pak, t_pak)
    assert r_pol < 6.0, "极地应极干，实得 %.0f" % r_pol
    # 与项目既有 COUNTRIES 雨衰描述定性一致
    assert rain_intensity_tag(-2.5, 118.0).startswith("极强"), "印尼应标为极强"
    assert rain_intensity_tag(30.5, 69.5).startswith("极弱"), "巴基斯坦应标为极弱"

    # 4) P.618 斜路径：GEO Ka 下行 20GHz、仰角 45°、赤道雨林 R001=110
    A001, det = rain_atten_slant(20.0, 110.0, 45.0, -2.5, p_pct=0.01, detail=True)
    print("[P.618 赤道 20GHz el45] γ_R=%.2f dB/km L_E=%.2f km A_0.01=%.1f dB"
          % (det["gamma_R"], det["L_E_km"], det["A001_db"]))
    # 强降雨+长水平投影时 r_0.01 可低至 0.5 量级（P.618 式 10 分母含 0.78√(L_Gγ/f)）
    assert 0.3 < det["r001"] < 1.0, "路径缩减因子应在 (0,1]，实得 %.3f" % det["r001"]
    # v_0.01 按标准式原样计算；31(1−e^… )√(L_Rγ)/f²−0.45 为负时可略 >1
    # （不钳制——A 更大属保守口径，与 itur 开源实现一致）
    assert 0.5 < det["v001"] < 1.2, "垂直调整因子异常，实得 %.3f" % det["v001"]
    assert det["L_E_km"] < det["L_s_km"], "有效路径应短于斜路径"
    assert abs(A001 - det["A001_db"]) < 1e-3, "p=0.01% 时 A_p 应=A_0.01（容差含四舍五入）"
    assert 15.0 < A001 < 60.0, "赤道 Ka 下行 A_0.01 应在 15~60dB，实得 %.1f" % A001
    # 时间百分比换算：p 越大（可用度越低）雨衰越小，且单调
    A01, _ = rain_atten_at_pct(A001, 0.1, 45.0, -2.5)
    A1, _ = rain_atten_at_pct(A001, 1.0, 45.0, -2.5)
    A5, _ = rain_atten_at_pct(A001, 5.0, 45.0, -2.5)
    print("[P.618 换算] A(0.001%%)=%.1f A(0.01%%)=%.1f A(0.1%%)=%.1f A(1%%)=%.1f A(5%%)=%.1f"
          % (rain_atten_at_pct(A001, 0.001, 45.0, -2.5)[0], A001, A01, A1, A5))
    assert A5 < A1 < A01 < A001, "A_p 应随 p 增大单调递减"
    # 5) 反演：可用度
    p_inv = unavailability_from_atten(A001, A01, 45.0, -2.5)
    assert abs(p_inv - 0.1) < 0.02, "反演 p 应≈0.1%%，实得 %.4f" % p_inv
    av = availability_from_atten(A001, A01, 45.0, -2.5)
    assert abs(av - 99.9) < 0.05, "可用度应≈99.9%%，实得 %.3f" % av
    # 可承受雨衰极小 → 超出概率截断到上限 5% → 可用度≈95%（链路几乎不可用）
    assert availability_from_atten(A001, 0.1, 45.0, -2.5) < 95.5, "小余量→低可用度"
    # 可承受雨衰超过 0.001% 档 → 截断下限 0.001% → 可用度≈99.999%
    assert availability_from_atten(A001, 500.0, 45.0, -2.5) > 99.99, "大余量→高可用度"

    # 6) 干旱区雨衰应远小于赤道（同频同仰角）：巴基斯坦 vs 印尼
    A_pak = rain_atten_slant(20.0, r_pak, 46.0, 30.5, 0.01, lon_deg=69.5)
    A_idn = rain_atten_slant(20.0, r_idn, 45.0, -2.5, 0.01, lon_deg=118.0)
    print("[对比] 巴基斯坦 A_0.01=%.2f dB  印尼 A_0.01=%.1f dB  差 %.1f dB"
          % (A_pak, A_idn, A_idn - A_pak))
    assert A_idn > A_pak * 5.0, "赤道雨衰应比干旱区大一个量级以上"

    # 7) 低仰角路径更长 → 雨衰更大
    A_hi = rain_atten_slant(20.0, 42.0, 60.0, 22.0, 0.01)
    A_lo = rain_atten_slant(20.0, 42.0, 15.0, 22.0, 0.01)
    assert A_lo > A_hi, "低仰角雨衰应更大"
    # 8) 频段依赖：Ku 雨衰 << Ka << Q/V
    A_ku = rain_atten_slant(12.0, 42.0, 40.0, 22.0, 0.01)
    A_ka = rain_atten_slant(20.0, 42.0, 40.0, 22.0, 0.01)
    A_qv = rain_atten_slant(40.0, 42.0, 40.0, 22.0, 0.01)
    print("[频段] Ku(12G)=%.2f Ka(20G)=%.2f Q/V(40G)=%.2f dB" % (A_ku, A_ka, A_qv))
    assert A_ku < A_ka < A_qv, "雨衰应随频率升高而增大"

    # 9) 气体损耗斜路径放大
    g45 = gas_atten_slant(0.2, 45.0)
    g10 = gas_atten_slant(0.2, 10.0)
    assert abs(g45 - 0.2 / math.sin(45 * DEG)) < 1e-9 and g10 > g45
    assert gas_atten_slant(0.2, 2.0) == gas_atten_slant(0.2, 5.0), "低仰角应钳制到 5°"

    # 10) 统计工具
    assert abs(percentile([1, 2, 3, 4, 5], 0.5) - 3.0) < 1e-9
    assert abs(percentile([1, 2, 3, 4], 0.0) - 1.0) < 1e-9
    assert abs(percentile([1, 2, 3, 4], 1.0) - 4.0) < 1e-9
    assert abs(norm_ppf(0.5)) < 1e-9, "Φ⁻¹(0.5) 应=0"
    assert abs(norm_ppf(0.9) - 1.2815515655) < 1e-6, "Φ⁻¹(0.9) 应≈1.28155"
    assert abs(norm_ppf(0.1) + 1.2815515655) < 1e-6, "对称性"
    assert abs(norm_ppf(0.975) - 1.959963985) < 1e-6, "Φ⁻¹(0.975) 应≈1.95996"

    # 11) XPD（P.618-12 §4.1）：雨衰越大 XPD 越低；频率越高越差；仰角越低越差
    x1 = xpd_from_rain(20.0, 3.0, 0.01, 45.0, tau_deg=0.0)
    x2 = xpd_from_rain(20.0, 15.0, 0.01, 45.0, tau_deg=0.0)
    print("[XPD] Ka 20GHz el45：A=3dB → XPD=%.1f dB（含冰晶 %.1f）；A=15dB → XPD=%.1f dB"
          % (x1["XPD_rain"], x1["XPD_p"], x2["XPD_rain"]))
    assert x1["XPD_rain"] > x2["XPD_rain"], "雨衰越大 XPD 应越低（去极化越严重）"
    assert 10.0 < x1["XPD_rain"] < 60.0, "Ka 轻雨 XPD 应在 10~60dB，实得 %.1f" % x1["XPD_rain"]
    assert x1["XPD_p"] < x1["XPD_rain"], "含冰晶 XPD 应低于纯雨 XPD"
    # 圆极化（tau=45°）C_tau=0；线极化（tau=0°）C_tau≈15dB → 线极化 XPD 更好
    xc = xpd_from_rain(20.0, 3.0, 0.01, 45.0, tau_deg=45.0)
    assert abs(xc["C_tau"]) < 0.01 and x1["C_tau"] > 14.0, \
        "圆极化 C_tau 应=0、线极化应≈15dB，实得 %.2f/%.2f" % (xc["C_tau"], x1["C_tau"])
    assert x1["XPD_rain"] > xc["XPD_rain"], "线极化 XPD 应优于圆极化"
    # 频率：同一时间百分比下（A_p 随频率增大），Ka 去极化比 Ku 严重；低仰角更差
    # （注：固定 A_p 比较无意义——P.618 的 C_f 项随频率增大，须按同 p 取各自 A_p）
    A_ku_p = rain_atten_slant(12.0, 42.0, 40.0, 22.0, 0.01)
    A_ka_p = rain_atten_slant(20.0, 42.0, 40.0, 22.0, 0.01)
    xku = xpd_from_rain(12.0, A_ku_p, 0.01, 40.0)
    xka = xpd_from_rain(20.0, A_ka_p, 0.01, 40.0)
    print("[XPD 同 p] Ku(12G,A=%.1fdB)→XPD=%.1f  Ka(20G,A=%.1fdB)→XPD=%.1f"
          % (A_ku_p, xku["XPD_rain"], A_ka_p, xka["XPD_rain"]))
    assert xku["XPD_rain"] > xka["XPD_rain"], "同 p 下 Ka 去极化应比 Ku 严重"
    xlo = xpd_from_rain(20.0, 3.0, 0.01, 15.0)
    assert x1["XPD_rain"] > xlo["XPD_rain"], "同频同雨衰下低仰角 XPD 应更差"
    # V(f) 分段连续性（20GHz 处两侧应接近）
    assert abs(xpd_v_freq(19.99) - xpd_v_freq(20.01)) < 1.0, "V(f) 20GHz 分段应连续"
    # 极化隔离核查：大雨 + 高要求 → 不满足；轻雨 + 常规要求 → 满足
    m_bad = crosspol_isolation_margin(20.0, 20.0, 0.01, 30.0, xpd_spec_db=30.0)
    m_ok = crosspol_isolation_margin(20.0, 2.0, 0.01, 45.0, xpd_spec_db=25.0)
    print("[XPD 隔离]", m_ok["verdict"][:88])
    assert not m_bad["ok"] and m_ok["ok"], "极化隔离裕度判定应能区分满足/不满足"
    assert m_ok["eff_iso_db"] <= 30.0 + 1e-6, "有效隔离不应超过天线交极化隔离上限"
    print("=== ALL PASS ===")
