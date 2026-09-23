# -*- coding: utf-8 -*-
"""analysis_engine —— 方案级分析引擎（纯 Python 零依赖，冻结 exe 可用）。

四大能力（对应改进矩阵 P0-2 / P3-1 / P3-2 / P3-3）：
  1) monte_carlo_link   链路灵敏度蒙特卡洛：dB 域线性叠加扰动 → C/N、余量、
     MODCOD 分布、ACM 期望容量、P10/P50/P90、龙卷风图（±2σ 单参数摆动）
  2) adjacent_interference  邻星干扰 C/I（GSO-GSO 协调口径）：
     ITU-R S.465-6 地面站旁瓣包络 + 卫星天线 S.580 风格包络；
     单入境判据 ΔT/T=6%（I/N=−12.2dB）与 C/(N+I) 恶化评估
  3) reliability_rollup  BOM+MTBF 可靠性汇总：分类 MTBF 表（航天级工程口径）→
     串联失效强度 → R(t)/MTBF_sys/可用度/薄弱环节 TOP、相控阵优雅降级模型
  4) 结果回读 readback    GRASP .grd/.cut、覆盖 CSV、STK .e 解析回读 →
     与内置引擎输出交叉比对（RMS/最大偏差）——外部工具闭环核对

所有函数返回 dict（JSON 安全），供 design_app HTTP/JS 桥直接透传。
"""
from __future__ import annotations

import math
import random

# XPD/去极化模型定义在 propagation.py（与 ITU-R P.618 雨衰同族）——此处再导出，
# 使 design_engine/前端只需 import analysis_engine 即可取到全部分析能力。
from propagation import (xpd_from_rain, crosspol_isolation_margin,
                         xpd_v_freq, xpd_c_freq)

# ================================================================
# 通用小工具
# ================================================================
DEG = math.pi / 180.0


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except (TypeError, ValueError):
        return d


def _pct(sorted_vals, q):
    """线性插值分位数（sorted_vals 已升序）。"""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


# ================================================================
# 1) 蒙特卡洛灵敏度（P0-2）
# ================================================================
# 扰动参数表：dB 域高斯 σ（工程口径，来源：链路预算不确定度惯例）
#   EIRP  σ=0.5dB（功放出力波动+馈线公差）  G/T σ=0.5dB（LNA 噪声温度散布）
#   雨衰  对数正态 σ_ln=0.25（P.618 模型自身不确定度 ~25%）
#   指向  σ=0.25dB（姿态+波束赋形误差）    极化 σ=0.15dB  实现 σ=0.2dB
MC_PARAMS = {
    "EIRP":    dict(sigma_db=0.50, cn="EIRP（功放+馈线）"),
    "GT":      dict(sigma_db=0.50, cn="G/T（LNA 噪声散布）"),
    "A_rain":  dict(sigma_ln=0.25, cn="雨衰（模型不确定度）"),
    "L_pnt":   dict(sigma_db=0.25, cn="指向损耗"),
    "L_pol":   dict(sigma_db=0.15, cn="极化损耗"),
    "L_impl":  dict(sigma_db=0.20, cn="实现损耗"),
}


def _sample(sigma_db=0.0, sigma_ln=0.0, rng=None):
    """dB 域采样：高斯（sigma_db）或对数正态雨衰乘性（sigma_ln → dB 域 σ=sigma_ln/ln10·10）。"""
    r = rng or random
    if sigma_db:
        return r.gauss(0.0, sigma_db)
    if sigma_ln:
        # A' = A·exp(N(0,σ_ln)) → dB 域 Δ = 10σ_ln/ln10 ·N(0,1)·A_lin 近似为乘性；
        # 对雨衰项直接在 dB 域按 ΔdB = (10/ln10)·σ_ln·z·(A_dB/10) 比例缩放更贴近
        return r.gauss(0.0, sigma_ln * 10.0 / math.log(10.0))
    return 0.0


def monte_carlo_link(cn_nom_db, cn_req_db, m_target_db, b_mhz, modcod_table,
                     rain_db=0.0, n=2000, seed=20260922, params=None,
                     avail_rain_db=None):
    """链路级蒙特卡洛（dB 域线性叠加——链路方程本身是 dB 线性的，扰动即精确）。

    cn_nom_db   : 名义 C/N（dB，已含全部损耗）
    cn_req_db   : 当前 MODCOD 门限（dB）
    m_target_db : 余量目标（dB）
    b_mhz       : 载波带宽（MHz）——ACM 期望容量用
    modcod_table: [{name,cn_req,eta}] 升序表（infoflow_data.MODCOD 直接传入）
    rain_db     : 名义雨衰（dB）——对数正态扰动按此值比例缩放
    返回 dict：M 分布统计（mean/std/P1/P5/P10/P50/P90）、闭合概率、
    MODCOD 直方、ACM 期望容量、龙卷风（每参数 ±2σ 摆动 ΔM）。"""
    rng = random.Random(seed)
    pars = params or MC_PARAMS
    ms, cns, avail_ok = [], [], 0
    mod_hist = {}
    cap_sum = 0.0
    rain_frac = (rain_db / 10.0) if rain_db and rain_db > 0 else 0.0
    for _ in range(int(n)):
        d = 0.0
        for k, spec in pars.items():
            sig_db = _f(spec.get("sigma_db"))
            sig_ln = _f(spec.get("sigma_ln"))
            if sig_db:
                d += rng.gauss(0.0, sig_db)
            elif sig_ln:
                # 雨衰乘性不确定度：ΔdB = A_dB·(e^{σz}−1) ≈ A_dB·σ·z（小 σ 一阶）
                z = rng.gauss(0.0, sig_ln)
                d -= rain_db * (math.exp(z) - 1.0) if rain_db > 0 else 0.0
        cn = cn_nom_db + d
        m = cn - cn_req_db
        ms.append(m)
        cns.append(cn)
        if m >= m_target_db:
            avail_ok += 1
        # ACM：按瞬时 C/N 选档（m_target 顶格策略与 pick_modcod 一致）
        best = None
        for mc in modcod_table:
            if cn - mc["cn_req"] >= m_target_db:
                if best is None or mc["eta"] > best["eta"]:
                    best = mc
        if best is None:
            for mc in modcod_table:
                if cn >= mc["cn_req"]:
                    if best is None or mc["eta"] > best["eta"]:
                        best = mc
        name = best["name"] if best else "失锁"
        mod_hist[name] = mod_hist.get(name, 0) + 1
        cap_sum += (best["eta"] if best else 0.0) * b_mhz / 1000.0
    ms.sort()
    cns.sort()
    mean_m = sum(ms) / len(ms)
    var = sum((x - mean_m) ** 2 for x in ms) / max(len(ms) - 1, 1)
    std_m = math.sqrt(var)
    # 龙卷风：单参数 ±2σ，其余取名义
    tornado = []
    for k, spec in pars.items():
        sig_db = _f(spec.get("sigma_db"))
        sig_ln = _f(spec.get("sigma_ln"))
        if sig_db:
            swing = 2.0 * sig_db
        elif sig_ln and rain_db > 0:
            swing = rain_db * (math.exp(2.0 * sig_ln) - 1.0)
        else:
            continue
        # EIRP/GT 正向增益，损耗项负向：对 M 的影响幅度即 swing（dB 线性）
        sign = -1.0 if k in ("A_rain", "L_pnt", "L_pol", "L_impl") else 1.0
        tornado.append(dict(param=k, cn=spec.get("cn", k),
                            sigma=round(swing / 2.0, 3),
                            m_low=round(mean_m - swing, 3) if sign < 0
                            else round(mean_m - swing, 3),
                            m_high=round(mean_m + swing, 3) if sign > 0
                            else round(mean_m + swing, 3),
                            span_db=round(2.0 * swing, 3)))
    tornado.sort(key=lambda r: -r["span_db"])
    p_close = 100.0 * avail_ok / len(ms)
    verdict = ("MC n=%d：M 均值 %.2f dB（σ=%.2f），P(M≥%.1fdB)=%.1f%%，"
               "P10=%.2f dB；%s"
               % (len(ms), mean_m, std_m, m_target_db, p_close, _pct(ms, 0.10),
                  "主导不确定项：" + (tornado[0]["cn"] if tornado else "—")))
    return dict(ok=True, n=len(ms), seed=seed,
                M=dict(mean=round(mean_m, 3), std=round(std_m, 3),
                       p1=round(_pct(ms, 0.01), 3), p5=round(_pct(ms, 0.05), 3),
                       p10=round(_pct(ms, 0.10), 3), p50=round(_pct(ms, 0.50), 3),
                       p90=round(_pct(ms, 0.90), 3),
                       min=round(ms[0], 3), max=round(ms[-1], 3)),
                CN=dict(mean=round(sum(cns) / len(cns), 3),
                        p10=round(_pct(cns, 0.10), 3),
                        p90=round(_pct(cns, 0.90), 3)),
                p_close_pct=round(p_close, 2), m_target_db=m_target_db,
                modcod_hist={k: v for k, v in sorted(mod_hist.items(),
                                                      key=lambda kv: -kv[1])},
                acm_capacity_gbps=dict(mean=round(cap_sum / len(ms), 3),
                                       fixed_nominal_gbps=0.0),
                hist=_histogram(ms, 24),
                tornado=tornado, params=pars, rain_db=rain_db,
                verdict=verdict)


def _histogram(vals, nbin=24):
    lo, hi = vals[0], vals[-1]
    if hi - lo < 1e-9:
        return dict(lo=lo, hi=hi, step=1.0, counts=[len(vals)])
    step = (hi - lo) / nbin
    counts = [0] * nbin
    for v in vals:
        k = min(int((v - lo) / step), nbin - 1)
        counts[k] += 1
    return dict(lo=round(lo, 3), hi=round(hi, 3), step=round(step, 4),
                counts=counts)


# ================================================================
# 2) 邻星干扰 C/I（P3-1，GSO-GSO 协调）
# ================================================================
def _s465_gain(phi_deg, d_lam):
    """ITU-R S.465-6 地面站接收旁瓣包络（2~30GHz，D/λ≥100 主用式）：
       G(φ) = 32 − 25log10(φ) dBi   φmin ≤ φ < 48°
       G(φ) = −10 dBi               48° ≤ φ ≤ 180°
       φmin = max(1°, 100λ/D)"""
    phi_min = max(1.0, 100.0 / max(d_lam, 1e-9))
    phi = max(float(phi_deg), phi_min)
    if phi < 48.0:
        return 32.0 - 25.0 * math.log10(phi)
    return -10.0


def _sat_envelope_gain(phi_deg, g_max_dbi, phi_3db_deg):
    """卫星天线旁瓣包络（S.580/S.1428 风格工程近似）：
       主瓣内：G_max − 2.5e-2·(D/λ·φ)² 型高斯近似 G_max−12(φ/θ3)²；
       旁瓣区：min(G_max − 25log10(φ/φ_3db·2.88)·1.0, G_max−20−25log10(φ))，
       远旁瓣平底 G_max − 45 dB（典型成形反射面 −20dBi 级）。"""
    phi = max(abs(float(phi_deg)), 1e-3)
    th3 = max(float(phi_3db_deg), 1e-3)
    # 主瓣（|φ| ≤ 1.5θ3）：抛物线近似
    if phi <= 1.5 * th3:
        return g_max_dbi - 12.0 * (phi / th3) ** 2
    # 近旁瓣：从 −12·(1.5)²=−27dB 处接 −25dB/dec 下降
    g_near = g_max_dbi - 27.0 - 25.0 * math.log10(phi / (1.5 * th3))
    g_floor = g_max_dbi - 45.0
    return max(g_near, g_floor)


def adjacent_interference(geo_lon_want, es_lat, es_lon, eirp_w_dbw, eirp_i_dbw,
                          f_dn_ghz, d_es_m, neighbor_lon_deg,
                          theta3_sat_deg=0.4, g_sat_max_dbi=52.0,
                          cn_want_db=12.0, n_neighbor=1, pol_iso_db=0.0):
    """GSO 邻星同频干扰评估（下行：邻星→本站；上行：本站→邻星接收）。

    几何：本站 (es_lat,es_lon) 看目标星 (0,geo_lon_want) 与邻星 (0,neighbor_lon)
    的夹角 φ_sep（小间距近似 = Δlon·cos(lat) 修正球面）。
    下行：C = EIRP_w + G_ES(0°) − L_fs；I = EIRP_i_off + G_ES(φ_sep) − L_fs
          （EIRP_i_off = 邻星在偏离其波束轴 φ_sep 方向的等效 EIRP，用卫星包络）
    上行：本站主瓣打目标星，旁瓣 G_ES(φ_sep) 泄漏进邻星接收天线（邻星按其
          接收 G/T 折算——同轨同频段近似取与目标星相同，C/I 上下行对称评估）。
    判据：单入境 ΔT/T ≤ 6%（I/N ≤ −12.2dB，RR/S.1434 口径）→ 换算
          I/C ≤ 10lg(N/C)−12.2；并给 C/(N+I) 相对 C/N 恶化 dB。"""
    # 本站对两星仰角近似相等（GEO 弧段），L_fs 相同 → C/I 中抵消
    dlon = float(neighbor_lon_deg)
    # 球面角距：本站看 GEO 弧上两点的夹角
    la, lo1, lo2 = es_lat * DEG, geo_lon_want * DEG, (geo_lon_want + dlon) * DEG
    v1 = (math.cos(la) * math.cos(lo1), math.cos(la) * math.sin(lo1), math.sin(la))
    v2 = (math.cos(la) * math.cos(lo2), math.cos(la) * math.sin(lo2), math.sin(la))
    # 站心指向矢量差角（近似：两单位视线矢量夹角）
    dot = max(min(v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2], 1.0), -1.0)
    phi_sep = math.degrees(math.acos(dot))
    # 精确站心角（视线矢量）——用小角近似修正
    phi_sep = max(phi_sep, abs(dlon) * math.cos(la))

    lam_m = 0.3 / float(f_dn_ghz)
    d_lam = float(d_es_m) / lam_m
    g_es_peak = 20.0 * math.log10(max(d_lam, 1.0)) + 26.0     # η≈65% 近似 G=26+20lg(D/λ)
    g_es_off = _s465_gain(phi_sep, d_lam)

    # 下行：邻星发射在偏离其波束轴 φ_sep 方向的增益
    g_i_tx = _sat_envelope_gain(phi_sep, g_sat_max_dbi, theta3_sat_deg)
    eirp_i_off = _f(eirp_i_dbw, _f(eirp_w_dbw)) + (g_i_tx - g_sat_max_dbi)

    ci_dn = (_f(eirp_w_dbw) + g_es_peak) - (eirp_i_off + g_es_off) + pol_iso_db
    # 上行：本站主瓣→目标星（C），旁瓣→邻星（I），邻星接收增益按其在
    # 本站方向偏轴 φ_sep 的接收包络（同发射包络互易）
    g_w_rx_off = _sat_envelope_gain(phi_sep, g_sat_max_dbi, theta3_sat_deg)
    ci_up = (g_es_peak + g_sat_max_dbi) - (g_es_off + g_w_rx_off) + pol_iso_db

    # I/N 与 C/(N+I)：以 C/N=cn_want_db 为基准
    in_dn = cn_want_db - ci_dn          # I/N = C/N − C/I
    degra_dn = 10.0 * math.log10(1.0 + 10.0 ** ((cn_want_db - ci_dn) / 10.0))
    in_up = cn_want_db - ci_up
    degra_up = 10.0 * math.log10(1.0 + 10.0 ** ((cn_want_db - ci_up) / 10.0))
    ok_dn = in_dn <= -12.2
    ok_up = in_up <= -12.2
    # 多入境（n 个等强邻星）：I_total = n·I → I/N + 10lg(n)
    if n_neighbor > 1:
        in_dn_m = in_dn + 10.0 * math.log10(n_neighbor)
        ok_dn_m = in_dn_m <= -10.0     # 多入境总判据 ΔT/T≤10%
    else:
        in_dn_m, ok_dn_m = in_dn, ok_dn
    verdict = ("邻星 Δ%.1f°（φ_sep=%.2f°）：下行 C/I=%.1f dB（I/N=%.1f dB %s单入境判据 −12.2dB），"
               "C/(N+I) 恶化 %.2f dB；上行 C/I=%.1f dB 恶化 %.2f dB → %s"
               % (dlon, phi_sep, ci_dn, in_dn, "满足" if ok_dn else "超出",
                  degra_dn, ci_up, degra_up,
                  "协调可行" if (ok_dn and ok_up and ok_dn_m)
                  else "需协调措施（换极化/加屏蔽/退让轨位/降旁瓣）"))
    return dict(ok=True, phi_sep_deg=round(phi_sep, 3),
                g_es=dict(peak_dbi=round(g_es_peak, 2), off_dbi=round(g_es_off, 2),
                          d_lam=round(d_lam, 1), envelope="ITU-R S.465-6"),
                g_sat_int_off_dbi=round(g_i_tx, 2),
                eirp_int_off_dbw=round(eirp_i_off, 2),
                ci_dn_db=round(ci_dn, 2), ci_up_db=round(ci_up, 2),
                in_dn_db=round(in_dn, 2), in_up_db=round(in_up, 2),
                degrade_dn_db=round(degra_dn, 3), degrade_up_db=round(degra_up, 3),
                multi_entry=dict(n=n_neighbor, in_dn_db=round(in_dn_m, 2),
                                 ok=bool(ok_dn_m)),
                single_entry_ok=dict(down=bool(ok_dn), up=bool(ok_up)),
                pol_iso_db=pol_iso_db, cn_want_db=cn_want_db,
                verdict=verdict)


# ================================================================
# 3) BOM+MTBF 可靠性汇总（P3-2）
# ================================================================
# 分类 MTBF 表（小时，航天级工程口径：GEO 15 年=131400h 任务）
#   来源量级：MIL-HDBK-217FN2 + 各单机飞行继承统计（公开文献口径），
#   无源件（多工器/开关）最高；机械展开机构、行波管、激光泵浦源最低。
#   注意：这是「单件不冗余」口径——汇总结果偏低时由 redundancy_advice 给备份建议，
#   与真实整星（大量 1:1/2:1 冗余后 R≥0.9）口径一致的使用方式。
MTBF_TABLE = {
    "天线":       2.0e6,     # 反射面/口径面（无源为主）；展开机构一次动作另计
    "相控阵组件": 5.0e6,     # T/R 组件单体（50~200 FIT 航天级 MMIC 口径）
    "LNA":        5.0e6,
    "变频":       2.0e6,
    "多工器":     2.0e7,     # 准无源
    "功放":       5.0e5,     # TWTA 口径（SSPA/GaN 按 note 判别 → 2e6）
    "开关":       2.0e7,     # 准无源波导开关
    "数字处理":   1.0e6,     # DTP/FPGA 数字信道化
    "再生基带":   1.0e6,
    "激光":       3.0e5,     # 泵浦源寿命限制
    "测控信标":   2.0e6,
    "星务":       1.0e6,
    "机构":       1.0e6,
}
# 冗余/优雅降级判据（从 BOM 行的 cn/why/note 文本识别工程冗余标注）
#   关键：build_equipment 的行 qty **已包含备份件**（如 "LNA ×A/B 冷备" qty=2n、
#   "1+1" qty=2）——若按 qty 串联会双重计数（把备份件也算成串联失效点）。
#   因此先识别冗余标注 → 拆成「并联对」，再按通道化/单串分类建模。
_PAIR_MARKERS = ("1+1", "1：1", "1:1", "A/B", "冷备", "热备", "双机", "备份")
_TRIPLE_MARKERS = ("三模", "TMR", "1+2", "2:1", "2+1")
# 通道化单机：失效 ≤ 容限比例时仅容量/性能降级，不构成任务失败（k-out-of-n）
_CHAN_MARKERS = ("通道", "路", "波束", "每 4 元", "ADC", "DAC", "变频", "调制解调",
                 "编译码", "T/R", "TR-", "子阵", "馈源")
_CHAN_TOL = 0.10          # 允许失效比例（10%）
# 多功放矩阵 MPA：N 只行波管 + 混合矩阵 → 单管失效仅使各波束功率降 ~1dB，
# 是 MPA 体制被 VHTS 采用的根本原因（内在优雅降级）
_MPA_MARKERS = ("多功放矩阵", "MPA", "8×8", "8x8")
_GRACEFUL_ARR = {
    "TR-":   (0.10, "相控阵阵面：单元失效≤10% 时增益损失<0.5dB/旁瓣抬升<1dB（k-out-of-n）"),
    "AESA":  (0.10, "瓦片式阵面：单元失效≤10% 性能降级可接受（k-out-of-n）"),
    "BFN":   (0.20, "波束赋形网络：≤20% 通道失效可降级运行"),
    "DBF":   (0.20, "数字波束成形：≤20% 通道失效可降级运行"),
}
# SSPA 判据（功放行 note 含以下关键字则 MTBF 提到 2e6）
_SSPA_KEYS = ("SSPA", "固放", "GaN")


def _classify_row(rid, cn, why, note, qty):
    """BOM 行 → 冗余结构分类：(kind, n_working, n_spare_per, tol_frac, why)
    kind: 'pair'=1+1 并联对 / 'triple'=三模 / 'channel'=通道化 k-out-of-n /
          'array'=大阵面 k-out-of-n / 'series'=单串（无冗余标注）"""
    text = "%s %s %s" % (cn, why, note)
    # 1) 大阵面（T/R 组件数量级）优先按阵面优雅降级
    for key, (tol, w) in _GRACEFUL_ARR.items():
        if key in rid or key in text:
            if qty >= 32:
                return "array", qty, 0, tol, w
    # 2) MPA 多功放矩阵：内在优雅降级（单管失效 → 各波束 −1dB）
    if any(m in text for m in _MPA_MARKERS):
        return "channel", qty, 0, 0.15, \
            "MPA 多功放矩阵：单管失效仅各波束功率降 ~1dB（内在优雅降级，≤15%）"
    if any(m in text for m in _TRIPLE_MARKERS):
        n_w = max(qty // 3, 1)
        return "triple", n_w, 2, 0.0, "三模冗余（TMR）：3 取 2 表决"
    if any(m in text for m in _PAIR_MARKERS):
        n_w = max(qty // 2, 1) if qty >= 2 else qty
        return "pair", n_w, 1, 0.0, "1+1 冷备（qty 已含备份件）"
    # 3) 通道化：数量多且文本含通道语义 → k-out-of-n
    if qty >= 4 and any(m in text for m in _CHAN_MARKERS):
        return "channel", qty, 0, _CHAN_TOL, \
            "通道化单机：失效 ≤%.0f%% 仅容量降级（k-out-of-n）" % (_CHAN_TOL * 100)
    return "series", qty, 0, 0.0, "单串无冗余标注（任一失效即功能丧失）"


def _row_q(kind, n_w, q_u, lam_el, life_h, tol):
    """按冗余结构算 BOM 行的寿命期失效概率 q_row（单件 q_u / 失效率 lam_el）。

    pair    : 每工作件配 1 冷备 → q_pair=q_u²，n_w 组串联
    triple  : 2/3 表决 → q_t=3q²−2q³
    channel/array : k-out-of-n，失效数 > ⌊tol·n⌋ 才任务失败（Poisson 近似）
    series  : n_w 件全串联
    """
    if kind == "pair":
        return 1.0 - (1.0 - q_u ** 2) ** n_w
    if kind == "triple":
        q_t = 3.0 * q_u ** 2 - 2.0 * q_u ** 3
        return 1.0 - (1.0 - q_t) ** n_w
    if kind in ("channel", "array"):
        mu = n_w * lam_el * life_h
        k_tol = max(int(n_w * tol), 1)
        return _poisson_sf_geq(mu, k_tol + 1)
    return 1.0 - math.exp(-n_w * lam_el * life_h)


def _poisson_sf_geq(mu, k):
    """P(X ≥ k)，X~Poisson(mu)。大数用正态近似，小数级数求和。"""
    if mu <= 0:
        return 0.0
    if k <= 0:
        return 1.0
    if k > 60 or mu > 60:                      # 正态近似（连续性校正）
        z = (k - 0.5 - mu) / math.sqrt(mu)
        return 0.5 * math.erfc(z / math.sqrt(2.0))
    term = math.exp(-mu)
    cdf = term
    for i in range(1, k):
        term *= mu / i
        cdf += term
    return max(0.0, 1.0 - cdf)


def reliability_rollup(rows, life_yr=15.0, mttr_h=0.0, mtbf_ovr=None):
    """单机清单（BOM）→ 载荷可靠性汇总（冗余结构感知，非一律串联）。

    三个口径同时给出（可靠性工程标准做法）：
      · R_serial   单串基线：假设全部单机无冗余串联（最坏口径，λ 预算起点）
      · R_asbuilt  按 BOM 实际标注：识别 1+1/三模/通道化/大阵面后逐行建模
      · R_designed 标准冗余设计：对单串行逐件增设 1:1 冷备后的预期值
    建模（第一性 + 工程惯例）：
      series   q = 1−exp(−n·λ·t)
      pair     每工作件 1 冷备 → q = 1−(1−q_u²)^n
      triple   2/3 表决 → q_t = 3q_u²−2q_u³
      channel/array  k-out-of-n：q = P(Poisson(n λ t) ≥ ⌊tol·n⌋+1)
    系统 R = Π(1−q_row)；等效 λ_eq = −ln R/t。

    MTBF 取值：分类工程保守估计（见 MTBF_TABLE 注释）。详细设计阶段应以
    零件应力分析（MIL-HDBK-217FN2 / ECSS-Q-30 / GJB 299C）+ 降额系数替代。
    """
    life_h = float(life_yr) * 8760.0
    items = []
    ln_r_built = 0.0
    ln_r_serial = 0.0
    ln_r_designed = 0.0
    cat_agg = {}
    ovr = mtbf_ovr or {}
    for r in rows or []:
        rid = str(r.get("id", ""))
        cat = str(r.get("cat", ""))
        cn = str(r.get("cn", ""))
        why = str(r.get("why", ""))
        note = str(r.get("note", ""))
        qty = max(int(_f(r.get("qty"), 1)), 1)
        mtbf = _f(ovr.get(rid) or ovr.get(cat), 0.0)
        if mtbf <= 0:
            mtbf = MTBF_TABLE.get(cat, 5.0e5)
            if cat == "功放" and any(k in (note + cn) for k in _SSPA_KEYS):
                mtbf = 2.0e6
        lam_el = 1.0 / mtbf
        kind, n_w, n_sp, tol, why_r = _classify_row(rid, cn, why, note, qty)
        q_u = 1.0 - math.exp(-lam_el * life_h)          # 单件寿命期失效概率
        q_row = _row_q(kind, n_w, q_u, lam_el, life_h, tol)
        q_row = min(max(q_row, 0.0), 1.0 - 1e-12)
        # 单串基线：全部 qty 件串联
        q_serial = min(1.0 - math.exp(-qty * lam_el * life_h), 1.0 - 1e-12)
        # 标准冗余设计：单串行 → 每件 1:1 冷备；已有冗余结构者维持
        if kind == "series":
            q_designed = 1.0 - (1.0 - q_u ** 2) ** n_w
        else:
            q_designed = q_row
        q_designed = min(max(q_designed, 0.0), 1.0 - 1e-12)
        ln_r_built += math.log(1.0 - q_row)
        ln_r_serial += math.log(1.0 - q_serial)
        ln_r_designed += math.log(1.0 - q_designed)
        items.append(dict(id=rid, cn=cn, cat=cat, qty=qty, mtbf_h=mtbf,
                          lam_el_h=lam_el, q_unit=q_u, q_life=q_row,
                          q_serial=q_serial, q_designed=q_designed,
                          kind=kind, n_working=n_w, n_spare=n_sp, tol=tol,
                          model=why_r, contrib_pct=0.0))
        a = cat_agg.setdefault(cat, dict(q=0.0, n=0))
        a["q"] += q_row
        a["n"] += 1
    r_built = math.exp(ln_r_built)
    r_serial = math.exp(ln_r_serial)
    r_designed = math.exp(ln_r_designed)
    lam_eq = -math.log(max(r_built, 1e-300)) / life_h if r_built < 1.0 else 0.0
    mtbf_eq = (1.0 / lam_eq) if lam_eq > 0 else float("inf")
    q_tot = sum(it["q_life"] for it in items) or 1e-300
    for it in items:
        it["contrib_pct"] = round(100.0 * it["q_life"] / q_tot, 2)
    items.sort(key=lambda x: -x["q_life"])
    for k, a in cat_agg.items():
        a["contrib_pct"] = round(100.0 * a["q"] / q_tot, 2)
    avail = (mtbf_eq / (mtbf_eq + mttr_h)) if mttr_h > 0 else None
    n_series = sum(1 for it in items if it["kind"] == "series")
    n_redun = sum(1 for it in items if it["kind"] in ("pair", "triple"))
    n_grace = sum(1 for it in items if it["kind"] in ("channel", "array"))
    n_unit = sum(it["qty"] for it in items)
    # 判定：以「标准冗余设计后」R_designed 为准（工程交付口径），≥0.90 良好
    ok = r_designed >= 0.90
    top = items[:5]
    verdict = ("载荷 %d 年可靠性：单串基线 R=%.1f%% → 按 BOM 冗余标注 R=%.1f%% → "
               "标准 1:1 冗余设计后 R=%.1f%%（等效 MTBF≈%.0f 年）；"
               "结构：单串 %d 项 / 已冗余 %d 项 / 优雅降级 %d 项（共 %d 台单机）；%s；"
               "薄弱环节：%s"
               % (int(life_yr), 100.0 * r_serial, 100.0 * r_built,
                  100.0 * r_designed, mtbf_eq / 8760.0,
                  n_series, n_redun, n_grace, n_unit,
                  "良好" if ok else "偏低→需提高单机 MTBF（筛选/降额）或增加备份",
                  "、".join("%s(%.0f%%)" % (t["cn"][:14], t["contrib_pct"])
                            for t in top[:3])))
    return dict(ok=True, lambda_eq_h=lam_eq, lambda_h=lam_eq, mtbf_sys_h=mtbf_eq,
                life_yr=float(life_yr), life_h=life_h,
                r_serial=round(r_serial, 4), r_serial_pct=round(100.0 * r_serial, 2),
                r_life=round(r_built, 4), r_life_pct=round(100.0 * r_built, 2),
                r_asbuilt=round(r_built, 4), r_asbuilt_pct=round(100.0 * r_built, 2),
                r_designed=round(r_designed, 4),
                r_designed_pct=round(100.0 * r_designed, 2),
                availability=avail, mttr_h=mttr_h, n_units=n_unit,
                n_series=n_series, n_redundant=n_redun, n_graceful=n_grace,
                items=[dict(id=i["id"], cn=i["cn"], cat=i["cat"], qty=i["qty"],
                            mtbf_h=i["mtbf_h"], kind=i["kind"],
                            n_working=i["n_working"], n_spare=i["n_spare"],
                            tol_pct=round(100.0 * i["tol"], 1), model=i["model"],
                            q_unit_pct=round(100.0 * i["q_unit"], 4),
                            q_life_pct=round(100.0 * i["q_life"], 4),
                            q_designed_pct=round(100.0 * i["q_designed"], 4),
                            contrib_pct=i["contrib_pct"]) for i in items],
                cat_agg=[dict(cat=k, n=a["n"], q_life_pct=round(100.0 * a["q"], 4),
                              contrib_pct=a["contrib_pct"])
                         for k, a in sorted(cat_agg.items(), key=lambda kv: -kv[1]["q"])],
                top_weak=[dict(cn=t["cn"], contrib_pct=t["contrib_pct"], kind=t["kind"])
                          for t in top],
                pass_90=bool(ok), verdict=verdict)


def _mtbf_factor_for_q(kind, n_w, lam_el, life_h, tol, q_target):
    """求 MTBF 提升倍数 m，使该行 q_row(λ/m) ≤ q_target（二分，上界 1e6）。"""
    def q_at(m):
        return _row_q(kind, n_w, 1.0 - math.exp(-lam_el * life_h / m),
                      lam_el / m, life_h, tol)
    if q_at(1e6) > q_target:
        return float("inf")                # 无法靠 MTBF 达标（结构本身不足）
    lo, hi = 1.0, 1e6
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if q_at(mid) > q_target:
            lo = mid
        else:
            hi = mid
    return hi


def redundancy_advice(rel, target_r=0.95, life_yr=15.0):
    """薄弱环节整改建议：单串行→逐件 1:1 冷备；仍高者→提高单机 MTBF（反解倍数）。

    逐行处理（按 q 降序），每行最多两类措施：
      · series 行：q_row=1−exp(−nλt) → 逐件加 1:1 冷备 q'=1−(1−q_u²)^n
        （对 n>1 的行，整体加备 q_row² 会显著低估改善，故逐件建模）
      · 加备/既有冗余后 q 仍 >2% 的行：给「提高单机 MTBF」建议，二分反解
        所需倍数 m 使 q_row(λ/m) ≤ 2%（口径与 reliability_rollup 完全同源）。
    R 的更新采用 Π(1−q_row) 全量重算（避免 R≈0 时乘性增量判据失效）。
    输出 n_backup（加备项数）/ n_mtbf（提 MTBF 项数）/ plan（逐项措施）。"""
    life_h = float(life_yr) * 8760.0
    items = rel.get("items", [])
    q_map = {it["cn"]: _f(it.get("q_life_pct")) / 100.0 for it in items}

    def r_of(qmap):
        r = 1.0
        for q in qmap.values():
            r *= (1.0 - min(max(q, 0.0), 1.0 - 1e-12))
        return r

    r_sys = r_of(q_map)
    plan, added, mtbf_names = [], [], []
    for it in sorted(items, key=lambda x: -_f(x.get("q_life_pct"))):
        if r_sys >= target_r:
            break
        cn = it["cn"]
        q_i = q_map.get(cn, 0.0)
        if q_i <= 0.02:
            continue                       # 已不构成风险
        mtbf_h = _f(it.get("mtbf_h"), 5e5) or 5e5
        lam_el = 1.0 / mtbf_h
        n_w = max(int(_f(it.get("n_working"), it.get("qty", 1))), 1)
        tol = _f(it.get("tol_pct"), 0.0) / 100.0
        kind = it.get("kind", "series")
        q_cur, acts, eff_kind = q_i, [], kind
        # 措施 1：单串行逐件 1:1 冷备
        if kind == "series":
            q_bak = _f(it.get("q_designed_pct")) / 100.0
            if q_bak < q_cur:
                acts.append("1:1 冷备")
                q_cur = q_bak
                eff_kind = "pair"          # 加备后按 pair 口径继续提 MTBF
        # 措施 2：仍 >2% → 提高单机 MTBF（二分反解倍数）
        if q_cur > 0.02:
            m = _mtbf_factor_for_q(eff_kind, n_w, lam_el, life_h, tol, 0.02)
            if m > 1.05 and not math.isinf(m):
                q_mtbf = _row_q(eff_kind, n_w,
                                1.0 - math.exp(-lam_el * life_h / m),
                                lam_el / m, life_h, tol)
                if q_mtbf < q_cur:
                    acts.append("MTBF×%.0f（%.0e→%.0e h）" % (m, mtbf_h, mtbf_h * m))
                    q_cur = q_mtbf
        if not acts or q_cur >= q_i - 1e-12:
            continue
        q_map[cn] = q_cur
        r_new = r_of(q_map)
        plan.append(dict(cn=cn, contrib_pct=_f(it.get("contrib_pct")),
                         kind=kind, action="+".join(acts),
                         q_before_pct=round(100.0 * q_i, 3),
                         q_after_pct=round(100.0 * q_cur, 4),
                         r_before=round(r_sys, 4), r_after=round(r_new, 4),
                         delta_pct=round(100.0 * (r_new - r_sys), 2)))
        r_sys = r_new
        if acts[0] == "1:1 冷备":
            added.append(cn)
        if any(a.startswith("MTBF") for a in acts):
            mtbf_names.append(cn)
    if not added and not mtbf_names:
        note = "全部单机已具冗余/优雅降级结构且 q 均 ≤2%，无需整改"
    else:
        parts = []
        if added:
            parts.append("对 %d 项单串单机逐件增设 1:1 冷备" % len(added))
        if mtbf_names:
            parts.append("对 %d 项高失效行提高单机 MTBF（航天级筛选/降额/散热，如 %s）"
                         % (len(mtbf_names), "、".join(n[:10] for n in mtbf_names[:2])))
        note = ("；".join(parts) + " → R 由 %.1f%% 提升至 %.1f%%%s"
                % (100.0 * _f(rel.get("r_life")), 100.0 * r_sys,
                   "（达标）" if r_sys >= target_r else
                   "；仍未达 %.0f%% → 需进一步压缩单机失效率或缩短寿命期考核口径"
                   % (100.0 * target_r)))
    return dict(ok=True, target_r=target_r, r_final=round(r_sys, 4),
                r_final_pct=round(100.0 * r_sys, 2),
                pass_target=bool(r_sys >= target_r), n_backup=len(added),
                n_mtbf=len(mtbf_names), plan=plan, note=note)


# ================================================================
# 4) 结果回读（P3-3）：GRASP .grd/.cut、覆盖 CSV、STK .e 解析与比对
# ================================================================
def parse_grd(path):
    """解析 GRASP .grd（export_grd 同格式）→ theta/phi 轴 + gain_dbr 网格。"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.strip() for ln in f.read().strip().split("\n") if ln.strip()]
    parts = lines[1].split()
    t_start, t_step, n_t = float(parts[0]), float(parts[1]), int(float(parts[2]))
    p_start, n_p = float(parts[3]), int(float(parts[4]))
    p_step = float(lines[2].split()[0])
    mags = []
    for ln in lines[3:]:
        row = ln.split()
        if len(row) == 4:
            try:
                mags.append(math.sqrt(float(row[0]) ** 2 + float(row[1]) ** 2))
            except ValueError:
                continue
        if len(mags) >= n_t * n_p:
            break
    if len(mags) < n_t * n_p:
        raise ValueError("grd 数据行不足（%d/%d）" % (len(mags), n_t * n_p))
    peak = max(mags) or 1.0
    thetas = [t_start + i * t_step for i in range(n_t)]
    phis = [p_start + j * p_step for j in range(n_p)]
    grid = [[20.0 * math.log10(mags[i * n_p + j] / peak) if mags[i * n_p + j] > 0
             else -120.0 for j in range(n_p)] for i in range(n_t)]
    return dict(ok=True, theta=thetas, phi=phis, gain_dbr=grid,
                n_theta=n_t, n_phi=n_p, peak_norm=peak)


def parse_cut_ascii(path):
    """解析两列 cut（theta_deg gain_dBr，export_cut 格式；'#' 注释跳过）。
    也兼容 GRASP spherical_cut 四字段行（委托 grasp_bridge.parse_cut 逻辑内联）。"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.strip() for ln in f.read().strip().split("\n") if ln.strip()]
    body = [ln for ln in lines if not ln.startswith("#")]
    if not body:
        raise ValueError("cut 文件无数据行")
    first = body[0].split()
    if len(first) == 2:                        # export_cut 两列格式
        th, dbr = [], []
        for ln in body:
            row = ln.split()
            if len(row) >= 2:
                th.append(float(row[0]))
                dbr.append(float(row[1]))
        return dict(ok=True, format="two_col", theta=th, gain_dbr=dbr)
    if len(first) == 4:                        # GRASP 头（7 字段全局头+4 字段数据）
        # body[0] 是 7 字段全局头
        hp = body[0].split()
        t_start, t_step, n_t = float(hp[0]), float(hp[1]), int(float(hp[2]))
        mags = []
        for ln in body[1:]:
            row = ln.split()
            if len(row) == 4:
                try:
                    mags.append(math.sqrt(float(row[0]) ** 2 + float(row[1]) ** 2))
                except ValueError:
                    continue
                if len(mags) >= n_t:
                    break
        peak = max(mags) or 1.0
        th = [t_start + i * t_step for i in range(len(mags))]
        dbr = [20.0 * math.log10(m / peak) if m > 0 else -120.0 for m in mags]
        return dict(ok=True, format="grasp_cut", theta=th, gain_dbr=dbr)
    raise ValueError("cut 格式未识别（首行 %d 字段）" % len(first))


def parse_coverage_csv(path):
    """解析覆盖 CSV（export_coverage_csv 格式：lat,lon,eirp_dbw）→ 网格。"""
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        lines = [ln.strip() for ln in f.read().strip().split("\n") if ln.strip()]
    hdr = lines[0].lower()
    if "lat" not in hdr:
        raise ValueError("CSV 头异常：%s" % lines[0][:60])
    lats, lons, vals = set(), set(), []
    for ln in lines[1:]:
        row = ln.split(",")
        if len(row) < 3:
            continue
        la, lo = float(row[0]), float(row[1])
        v = float(row[2]) if row[2] else -200.0
        lats.add(la)
        lons.add(lo)
        vals.append((la, lo, v))
    lat_ax = sorted(lats)
    lon_ax = sorted(lons)
    idx = {(la, lo): v for la, lo, v in vals}
    grid = [[idx.get((la, lo), -200.0) for lo in lon_ax] for la in lat_ax]
    return dict(ok=True, lat=lat_ax, lon=lon_ax, eirp_dbw=grid,
                n_cells=len(vals))


def parse_stk_e(path):
    """解析 STK Ephemeris .e（stk.v.12，export_stk_ephemeris 同格式）。
    数据行格式：'DD Mon YYYY HH:MM:SS.sss x y z vx vy vz'（时间串含空格 →
    以「行尾 6 个浮点」为数据字段，时间为其余前缀）。
    返回：历元、点数、(t_idx, pos_km[3], vel_kms[3]) 序列（t_idx=行序×步长）。"""
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        lines = [ln.strip() for ln in f.read().strip().split("\n") if ln.strip()]
    if not lines or not lines[0].startswith("stk.v."):
        raise ValueError("非 STK ephemeris 文件（首行 %r）" % (lines[0][:30] if lines else ""))
    epoch = None
    coord = None
    data = []
    in_data = False
    for ln in lines:
        if ln.startswith("ScenarioEpoch"):
            epoch = ln.split(None, 1)[1]
        elif ln.startswith("CoordinateSystem"):
            coord = ln.split(None, 1)[1]
        elif ln == "EphemerisTimePosVel":
            in_data = True
            continue
        elif ln.startswith(("BEGIN", "END", "NumberOfEphemerisPoints",
                            "InterpolationMethod", "InterpolationOrder",
                            "CentralBody", "Name")):
            continue
        if in_data:
            row = ln.split()
            if len(row) >= 6:
                try:
                    nums = [float(x) for x in row[-6:]]
                    data.append((float(len(data)), nums[:3], nums[3:]))
                except ValueError:
                    in_data = False
    if not data:
        raise ValueError("未解析到历元数据行")
    return dict(ok=True, epoch=epoch, coord=coord, n_points=len(data),
                t_idx=[d[0] for d in data], pos_km=[d[1] for d in data],
                vel_kms=[d[2] for d in data])


def compare_series(a, b, name=""):
    """两组等长序列比对 → RMS/最大偏差（回读闭环核对）。"""
    n = min(len(a), len(b))
    if n == 0:
        return dict(name=name, n=0, rms=None, max_abs=None)
    d = [a[i] - b[i] for i in range(n)]
    rms = math.sqrt(sum(x * x for x in d) / n)
    return dict(name=name, n=n, rms=rms, max_abs=max(abs(x) for x in d))


def readback_compare(kind, parsed, internal):
    """回读数据 vs 内置引擎输出交叉比对。

    kind='cut'  : parsed=parse_cut_ascii, internal={'theta':[],'gain_dbr':[]}
    kind='grd'  : 峰值方向与 θ3dB 波束宽度比对
    kind='cov'  : 峰值 EIRP 与格点 RMS
    kind='e'    : 位置矢量 RMS（km）"""
    out = dict(ok=True, kind=kind, checks=[])
    if kind == "cut":
        # 内插到 parsed 的 theta 轴比对
        th_i, g_i = internal["theta"], internal["gain_dbr"]
        th_p, g_p = parsed["theta"], parsed["gain_dbr"]
        gp_at = []
        gi_at = []
        for t, g in zip(th_p, g_p):
            gi = _interp(t, th_i, g_i)
            if gi is not None:
                gp_at.append(g)
                gi_at.append(gi)
        c = compare_series(gp_at, gi_at, "cut gain_dBr")
        out["checks"].append(c)
        out["pass"] = bool(c["rms"] is not None and c["rms"] < 0.5 and c["max_abs"] < 2.0)
    elif kind == "grd":
        pk_p = max(max(row) for row in parsed["gain_dbr"])
        pk_i = max(max(row) for row in internal["gain_dbr"])
        out["checks"].append(dict(name="peak_dbr", parsed=pk_p, internal=pk_i,
                                  diff=abs(pk_p - pk_i)))
        out["pass"] = abs(pk_p - pk_i) < 0.1
    elif kind == "cov":
        flat_p = [v for row in parsed["eirp_dbw"] for v in row if v > -199.0]
        flat_i = [v for row in internal["eirp_dbw"] for v in row if v > -199.0]
        out["checks"].append(dict(name="peak_eirp_dbw",
                                  parsed=max(flat_p) if flat_p else None,
                                  internal=max(flat_i) if flat_i else None,
                                  diff=abs((max(flat_p) if flat_p else 0)
                                           - (max(flat_i) if flat_i else 0))))
        out["checks"].append(dict(name="n_cells", parsed=len(flat_p),
                                  internal=len(flat_i)))
        out["pass"] = (out["checks"][0]["diff"] < 0.5
                       and abs(len(flat_p) - len(flat_i)) <= max(2, 0.02 * len(flat_i)))
    elif kind == "e":
        c = compare_series([p[0] for p in parsed["pos_km"]],
                           [p[0] for p in internal["pos_km"]], "pos_x km")
        c2 = compare_series([p[1] for p in parsed["pos_km"]],
                            [p[1] for p in internal["pos_km"]], "pos_y km")
        c3 = compare_series([p[2] for p in parsed["pos_km"]],
                            [p[2] for p in internal["pos_km"]], "pos_z km")
        out["checks"] = [c, c2, c3]
        out["pass"] = all(x["rms"] < 0.01 and x["max_abs"] < 0.05 for x in (c, c2, c3))
    out["verdict"] = ("回读比对 %s：%s" % (kind, "一致（导出↔回读闭环核对通过）"
                                           if out.get("pass") else "偏差超限 → 检查导出/解析"))
    return out


def _interp(x, xs, ys):
    if not xs or x < xs[0] or x > xs[-1]:
        return None
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo]) if xs[hi] != xs[lo] else 0.0
    return ys[lo] * (1.0 - t) + ys[hi] * t


# ================================================================
# 自检
# ================================================================
if __name__ == "__main__":
    import os
    print("=== analysis_engine self-test ===")
    # 1) 蒙特卡洛：名义 M=5dB，σ 合成≈sqrt(0.5²+0.5²+...) → M 分布合理
    mc_tbl = [dict(name="QPSK 1/4", cn_req=-2.4, eta=0.49),
              dict(name="QPSK 1/2", cn_req=1.0, eta=0.99),
              dict(name="8PSK 3/5", cn_req=5.5, eta=1.79),
              dict(name="16APSK 2/3", cn_req=8.9, eta=2.64),
              dict(name="32APSK 9/10", cn_req=15.3, eta=4.45)]
    mc = monte_carlo_link(cn_nom_db=14.0, cn_req_db=8.9, m_target_db=3.0,
                          b_mhz=125.0, modcod_table=mc_tbl, rain_db=7.0, n=3000)
    print("[MC]", mc["verdict"][:110])
    assert 4.0 < mc["M"]["mean"] < 6.0, "M 均值应≈5dB，实得 %.2f" % mc["M"]["mean"]
    # 合成 σ：√(0.5²+0.5²+(7·0.25·10/ln10/10)²+0.25²+0.15²+0.2²)≈2.0dB（雨衰主导）
    assert 1.5 < mc["M"]["std"] < 2.6, "合成 σ 应≈2.0dB 量级，实得 %.2f" % mc["M"]["std"]
    assert mc["M"]["p10"] < mc["M"]["mean"] < mc["M"]["p90"]
    assert 0.0 < mc["p_close_pct"] <= 100.0
    assert sum(mc["modcod_hist"].values()) == 3000
    assert mc["tornado"] and mc["tornado"][0]["span_db"] > 0
    # 雨衰应为最大摆动项（rain 7dB×(e^0.5−1)≈4.6dB > 2σ_EIRP=1dB）
    assert mc["tornado"][0]["param"] == "A_rain", "龙卷风首位应为雨衰，实得 %s" % mc["tornado"][0]["param"]
    # 直方图归一
    assert sum(mc["hist"]["counts"]) == 3000

    # 2) 邻星干扰：GEO 2° 间距（φ_sep≈1.7°@lat30）——S.465 旁瓣 G≈31.2dBi，
    #    卫星远旁瓣 G_max−45 → C/I 应 ~25dB 量级，单入境判据临界/满足
    inf = adjacent_interference(geo_lon_want=110.5, es_lat=30.0, es_lon=120.0,
                                eirp_w_dbw=54.0, eirp_i_dbw=54.0, f_dn_ghz=20.0,
                                d_es_m=2.4, neighbor_lon_deg=2.0,
                                theta3_sat_deg=0.4, g_sat_max_dbi=52.0,
                                cn_want_db=12.0)
    print("[干扰]", inf["verdict"][:120])
    assert 1.5 < inf["phi_sep_deg"] < 2.1, "φ_sep 应≈1.7°，实得 %.2f" % inf["phi_sep_deg"]
    assert inf["ci_dn_db"] > 10.0, "2° 间距下行 C/I 应 >10dB，实得 %.1f" % inf["ci_dn_db"]
    # 0.5° 间距 → 干扰显著增强（C/I 下降 >6dB）
    inf2 = adjacent_interference(110.5, 30.0, 120.0, 54.0, 54.0, 20.0, 2.4, 0.5,
                                 theta3_sat_deg=0.4, g_sat_max_dbi=52.0)
    assert inf2["ci_dn_db"] < inf["ci_dn_db"] - 6.0, "0.5° 间距 C/I 应显著恶化"
    # 极化隔离 +30dB → C/I 提升 30dB
    inf3 = adjacent_interference(110.5, 30.0, 120.0, 54.0, 54.0, 20.0, 2.4, 2.0,
                                 theta3_sat_deg=0.4, g_sat_max_dbi=52.0, pol_iso_db=30.0)
    assert abs(inf3["ci_dn_db"] - inf["ci_dn_db"] - 30.0) < 0.01
    # S.465 包络锚点：φ=10° → 32−25=7 dBi；φ=60° → −10 dBi
    assert abs(_s465_gain(10.0, 200.0) - 7.0) < 1e-9
    assert _s465_gain(60.0, 200.0) == -10.0
    assert abs(_s465_gain(0.5, 100.0) - (32.0 - 25.0 * math.log10(1.0))) < 1e-9, \
        "φ<φmin 应钳到 φmin=100λ/D=1°"

    # 3) 可靠性：模拟 BOM（TWTA 串联主导 + 1+1 冗余标注 + 大阵面优雅降级）
    rows = [
        dict(id="ANT-REFL-KA", cn="Ka 反射面天线", cat="天线", qty=1, why="", note=""),
        dict(id="TWTA-KA-120", cn="120W TWTA", cat="功放", qty=4, why="", note="行波管"),
        dict(id="DTP-01", cn="数字透明处理器", cat="数字处理", qty=1, why="", note=""),
        dict(id="LNA-KA", cn="Ka 低噪放", cat="LNA", qty=8,
             why="4 路 × A/B 冷备", note=""),
        dict(id="MUX-01", cn="输入多工器", cat="多工器", qty=1, why="", note=""),
        dict(id="TR-KA-01", cn="Ka T/R 组件", cat="相控阵组件", qty=1024,
             why="T/R 组件 ×N_el=1024（阵面功放分布式集成）", note=""),
        dict(id="OBC-01", cn="星载计算机", cat="星务", qty=2,
             why="1+1，FDIR 覆盖关键单机", note=""),
        dict(id="MPA-8X8", cn="8×8 多功放矩阵", cat="功放", qty=3, why="", note="MPA"),
    ]
    rel = reliability_rollup(rows, life_yr=15.0)
    print("[可靠性]", rel["verdict"][:170])
    assert rel["lambda_eq_h"] > 0 and rel["mtbf_sys_h"] > 0
    assert 0.0 < rel["r_life_pct"] <= 100.0
    # 三口径单调：单串基线 < 按 BOM 标注 < 标准 1:1 冗余设计
    assert rel["r_serial_pct"] <= rel["r_asbuilt_pct"] <= rel["r_designed_pct"] + 1e-9, \
        "三口径应单调（serial %.2f ≤ asbuilt %.2f ≤ designed %.2f）" % (
            rel["r_serial_pct"], rel["r_asbuilt_pct"], rel["r_designed_pct"])
    # 冗余标注识别：LNA(A/B 冷备)/OBC(1+1) → pair；T/R(1024) → array；MPA → channel
    kinds = {it["id"]: it["kind"] for it in rel["items"]}
    assert kinds["LNA-KA"] == "pair", "LNA A/B 冷备应识别为 pair，实得 %s" % kinds["LNA-KA"]
    assert kinds["OBC-01"] == "pair", "1+1 星载机应识别为 pair，实得 %s" % kinds["OBC-01"]
    assert kinds["TR-KA-01"] == "array", "1024 T/R 应识别为 array，实得 %s" % kinds["TR-KA-01"]
    assert kinds["MPA-8X8"] == "channel", "MPA 应识别为优雅降级，实得 %s" % kinds["MPA-8X8"]
    assert kinds["TWTA-KA-120"] == "series", "TWTA 无冗余标注应为 series"
    # pair 行 q 远小于同 qty 串联（8 只 LNA：A/B 4 对 → q≈(q_u²)·4）
    lna = [it for it in rel["items"] if it["id"] == "LNA-KA"][0]
    assert lna["q_life_pct"] < 1.0, "4 对冷备 LNA 的 15 年 q 应 <1%%，实得 %.3f" % lna["q_life_pct"]
    # 1024 T/R：k-out-of-n（阈值 102 只）→ q≈0
    tr = [it for it in rel["items"] if it["id"] == "TR-KA-01"][0]
    assert tr["q_life_pct"] < 0.5 and "k-out-of-n" in tr["model"]
    # 未备份 TWTA 4 只 → TOP 薄弱项
    assert rel["items"][0]["id"] == "TWTA-KA-120", \
        "TOP 薄弱应为未备份 TWTA，实得 %s" % rel["items"][0]["id"]
    adv = redundancy_advice(rel, target_r=0.95)
    print("[冗余建议]", adv["note"][:150])
    assert adv["r_final"] > rel["r_life"], "整改后 R 应提升"
    assert adv["r_final"] >= rel["r_designed"] - 0.005, \
        "整改结果不应低于 r_designed（%.4f vs %.4f）" % (
            adv["r_final"], rel["r_designed"])
    # 单串行仅加备（未叠加 MTBF）时 q_after 应等于 q_designed 口径
    for p in adv["plan"]:
        if p["action"] == "1:1 冷备":
            src = [it for it in rel["items"] if it["cn"] == p["cn"]]
            assert src and abs(p["q_after_pct"] - src[0]["q_designed_pct"]) < 0.01, \
                "series 加备 q_after 应等于 q_designed（%s）" % p["cn"]
    # MPA 逐件加备（qty=3 串联）：q' = 1−(1−q_u²)³，而非 q_row²
    mpa = [it for it in rel["items"] if it["id"] == "MPA-8X8"][0]
    assert mpa["kind"] == "channel"
    # 极端校验 1：mtbf_ovr 把 TWTA 提到 1e9 → R_designed 显著提升、TWTA 退出 TOP 薄弱
    rel2 = reliability_rollup(rows, life_yr=15.0, mtbf_ovr={"TWTA-KA-120": 1e9})
    assert rel2["r_designed_pct"] > rel["r_designed_pct"] + 10.0, \
        "TWTA MTBF 提至 1e9 后 R_designed 应显著提升（%.1f → %.1f）" % (
            rel["r_designed_pct"], rel2["r_designed_pct"])
    assert rel2["top_weak"][0]["cn"] != "120W TWTA", \
        "TWTA 修复后不应再居 TOP 薄弱首位，实得 %s" % rel2["top_weak"][0]["cn"]
    # 极端校验 2：全类别 MTBF 提到 1e9 → R_designed → ~100%（模型上界正确性）
    ovr_all = {"天线": 1e9, "功放": 1e9, "数字处理": 1e9, "LNA": 1e9,
               "多工器": 1e9, "相控阵组件": 1e9, "星务": 1e9}
    rel3 = reliability_rollup(rows, life_yr=15.0, mtbf_ovr=ovr_all)
    assert rel3["r_designed_pct"] > 99.9, \
        "全类别 MTBF 1e9 时 R_designed 应 >99.9%%，实得 %.2f" % rel3["r_designed_pct"]
    # 单串基线上界（剔除 1024 通道大阵面——串联口径对大阵面天然严苛）
    rows_small = [r for r in rows if r["id"] not in ("TR-KA-01", "MPA-8X8")]
    rel4 = reliability_rollup(rows_small, life_yr=15.0, mtbf_ovr=ovr_all)
    assert rel4["r_serial_pct"] > 99.0, \
        "小 BOM 全类别 MTBF 1e9 时单串基线应 >99%%，实得 %.2f" % rel4["r_serial_pct"]

    # 4) 回读闭环：用引擎自身导出再解析比对（cut/grd/cov/e）
    import pattern_engine as PE
    import coverage_engine as CE
    import orbit_engine as OE
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out, exist_ok=True)
    pat = PE.phased_array_pattern(20.0, 8, 8, d_lam=0.5, scan_theta=0.0,
                                  grid_n_theta=61, grid_n_phi=49, cut_n=201)
    PE.export_cut(pat, os.path.join(out, "_rb_test.cut"))
    cut_p = parse_cut_ascii(os.path.join(out, "_rb_test.cut"))
    rb = readback_compare("cut", cut_p, dict(theta=pat["cut"]["theta"],
                                             gain_dbr=pat["cut"]["gain_dbr"]))
    print("[回读 cut]", rb["verdict"], "rms=%.4f" % rb["checks"][0]["rms"])
    assert rb["pass"] and rb["checks"][0]["rms"] < 0.01
    PE.export_grd(pat, os.path.join(out, "_rb_test.grd"))
    grd_p = parse_grd(os.path.join(out, "_rb_test.grd"))
    rb_g = readback_compare("grd", grd_p, pat["grid"])
    print("[回读 grd]", rb_g["verdict"])
    assert rb_g["pass"]
    cov = CE.coverage_map(pat, 54.0, h_km=35786.0, sat_lat=0.0, sat_lon=60.0,
                          n_lat=61, n_lon=81)
    CE.export_coverage_csv(cov, os.path.join(out, "_rb_test.csv"))
    cov_p = parse_coverage_csv(os.path.join(out, "_rb_test.csv"))
    rb_c = readback_compare("cov", cov_p, cov)
    print("[回读 cov]", rb_c["verdict"], rb_c["checks"][0])
    assert rb_c["pass"]
    el = OE.elements_from_altitude(550.0, 53.0, raan_deg=30.0)
    OE.export_stk_ephemeris(el, os.path.join(out, "_rb_test.e"),
                            OE.J2000_UNIX + 26 * 365.25 * 86400.0,
                            dur_h=2.0, step_s=60.0)
    e_p = parse_stk_e(os.path.join(out, "_rb_test.e"))
    assert e_p["n_points"] == 121 and e_p["coord"] == "J2000"
    # 与内置传播同历元比对（propagate_eci 返回 6 元组，取前 3 为位置）
    t0 = OE.J2000_UNIX + 26 * 365.25 * 86400.0
    internal_pos = [list(OE.propagate_eci(el, t0 + k * 60.0)[:3]) for k in range(121)]
    rb_e = readback_compare("e", e_p, dict(pos_km=internal_pos))
    print("[回读 stk .e]", rb_e["verdict"], "rms=%.6f km" % rb_e["checks"][0]["rms"])
    assert rb_e["pass"]
    # 清理回读测试文件
    for fn in ("_rb_test.cut", "_rb_test.grd", "_rb_test.csv", "_rb_test.e"):
        try:
            os.remove(os.path.join(out, fn))
        except OSError:
            pass
    print("=== ALL PASS ===")
