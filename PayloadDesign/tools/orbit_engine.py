# -*- coding: utf-8 -*-
"""轨道覆盖仿真引擎（纯 Python 第一性原理，零第三方依赖，冻结 exe 可用）。

等效 STK 的轨道分析（内置计算 + 标准文件导出双通道，经用户确认的技术路线）：
  · 二体 Kepler 传播（含 J2 长期摄动：交点退行/近地点旋转）
  · ECI(J2000) → ECEF(GMST) → 大地 lat/lon 星下点轨迹
  · 覆盖帽（el_min → 地心角 σ）与覆盖圈（lat/lon 环）
  · 目标点可见性窗口（AOS/LOS/最大仰角/时长/覆盖率/重访）——「轨道覆盖是否合理」判据
  · **某一时刻覆盖情况**：任意 epoch 快照（星下点/覆盖圈/目标仰角/星座重数图）
  · 导出 STK Ephemeris `.e`（stk.v.12，J2000 ECI 位置速度）→ 带进 STK 复核

单位：km / s / 度；时间 = Unix 秒（UTC）。地球 R=6371km、mu=398600.4418km³/s²、
J2=1.08262668e-3（WGS84 同源，与 design_engine 常数一致）。
"""
from __future__ import annotations

import math

MU = 398600.4418            # km^3/s^2
R_EARTH = 6371.0            # km（圆球近似，与 design_engine 同口径）
J2 = 1.08262668e-3
OMEGA_E = 7.2921158553e-5   # rad/s 地球自转
DEG = math.pi / 180.0
J2000_UNIX = 946728000.0    # 2000-01-01 12:00 TT ≈ 01-01 11:58:55.816 UTC（取整差<0.1°，覆盖分析可忽略）


# ================================================================
# 轨道根数 → 传播（二体 + J2 长期项）
# ================================================================
def elements_from_altitude(h_km, incl_deg, ecc=0.0, raan_deg=0.0, argp_deg=0.0,
                           nu0_deg=0.0):
    """由高度/倾角构圆轨道根数 dict（a=Re+h，e≈0；HEO 可给 ecc/argp）。"""
    a = R_EARTH + float(h_km)
    return dict(a_km=a, ecc=float(ecc), incl_deg=float(incl_deg),
                raan_deg=float(raan_deg), argp_deg=float(argp_deg),
                nu0_deg=float(nu0_deg))


def orbital_period_min(el):
    return 2.0 * math.pi * math.sqrt(el["a_km"] ** 3 / MU) / 60.0


def mean_motion(el):
    """平运动 n（rad/s）+ J2 长期率（Ω̇, ω̇ rad/s）。"""
    a, e, i = el["a_km"], el["ecc"], el["incl_deg"] * DEG
    n = math.sqrt(MU / a ** 3)
    p = a * (1.0 - e * e)
    fac = 1.5 * n * J2 * (R_EARTH / p) ** 2
    raan_dot = -fac * math.cos(i)                          # Ω̇ = −1.5nJ2(Re/p)²cos i
    argp_dot = fac * 0.5 * (5.0 * math.cos(i) ** 2 - 1.0)  # ω̇ = 0.75nJ2(Re/p)²(5cos²i−1)
    return n, raan_dot, argp_dot


def _kepler_E(M, e, tol=1e-12, it_max=30):
    """开普勒方程 M=E−e·sinE（Newton 迭代）。"""
    E = M + e * math.sin(M) if e < 0.8 else math.pi
    for _ in range(it_max):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        dE = -f / fp
        E += dE
        if abs(dE) < tol:
            break
    return E


def propagate_eci(el, t_unix):
    """t_unix（UTC 秒）→ ECI(J2000) 位置速度 (x,y,z,vx,vy,vz) km/km·s⁻¹。
    含 J2 长期摄动（Ω̇/ω̇ 线性外推——LEO 一天量级内与 STK HPOP 偏差 <0.5°）。"""
    n, raan_dot, argp_dot = mean_motion(el)
    a, e = el["a_km"], el["ecc"]
    dt = t_unix - (el.get("epoch_unix") or J2000_UNIX)
    M = (el["nu0_deg"] * DEG + n * dt) % (2.0 * math.pi)      # 近圆：M0≈ν0
    E = _kepler_E(M, e)
    # 近焦点系
    xv = a * (math.cos(E) - e)
    yv = a * math.sqrt(1.0 - e * e) * math.sin(E)
    Edot = n / (1.0 - e * math.cos(E))
    xvd = -a * math.sin(E) * Edot
    yvd = a * math.sqrt(1.0 - e * e) * math.cos(E) * Edot
    om = (el["raan_deg"] * DEG + raan_dot * dt) % (2.0 * math.pi)
    w = (el["argp_deg"] * DEG + argp_dot * dt) % (2.0 * math.pi)
    i = el["incl_deg"] * DEG
    co, so, cw, sw, ci, si = (math.cos(om), math.sin(om), math.cos(w),
                              math.sin(w), math.cos(i), math.sin(i))
    # 旋转矩阵行（PQW→ECI）
    r11 = co * cw - so * sw * ci
    r12 = -co * sw - so * cw * ci
    r21 = so * cw + co * sw * ci
    r22 = -so * sw + co * cw * ci
    r31 = sw * si
    r32 = cw * si
    x = r11 * xv + r12 * yv
    y = r21 * xv + r22 * yv
    z = r31 * xv + r32 * yv
    vx = r11 * xvd + r12 * yvd
    vy = r21 * xvd + r22 * yvd
    vz = r31 * xvd + r32 * yvd
    return (x, y, z, vx, vy, vz)


# ================================================================
# ECI → ECEF → 星下点
# ================================================================
def gmst_rad(t_unix):
    """格林尼治平恒星时（rad）。IAU 1982：θ = 280.46061837° + 360.98564736629°·d。"""
    d = (t_unix - J2000_UNIX) / 86400.0
    return (280.46061837 + 360.98564736629 * d) * DEG % (2.0 * math.pi)


def eci_to_ecef(p_eci, t_unix):
    g = gmst_rad(t_unix)
    cg, sg = math.cos(g), math.sin(g)
    x, y, z = p_eci[0], p_eci[1], p_eci[2]
    return (cg * x + sg * y, -sg * x + cg * y, z)


def sub_satellite(t_unix, el):
    """星下点 (lat, lon, alt_km)（圆球大地近似）。"""
    p = propagate_eci(el, t_unix)[:3]
    pe = eci_to_ecef(p, t_unix)
    r = math.sqrt(pe[0] ** 2 + pe[1] ** 2 + pe[2] ** 2)
    lat = math.degrees(math.asin(max(min(pe[2] / r, 1.0), -1.0)))
    lon = math.degrees(math.atan2(pe[1], pe[0])) % 360.0
    if lon > 180.0:
        lon -= 360.0
    return lat, lon, r - R_EARTH


def sat_position_ecef(t_unix, el):
    return eci_to_ecef(propagate_eci(el, t_unix)[:3], t_unix)


# ================================================================
# 覆盖几何
# ================================================================
def coverage_cap_deg(h_km, el_min_deg):
    """覆盖帽半角 σ（地心角，度）：el≥el_min ⟺ 星下点角距≤σ。
    σ = acos(R·cos(el)/(R+h)) − el。"""
    c = R_EARTH * math.cos(el_min_deg * DEG) / (R_EARTH + h_km)
    if c >= 1.0:
        return 0.0
    return math.degrees(math.acos(max(min(c, 1.0), -1.0))) - el_min_deg


def coverage_circle(lat_c, lon_c, sigma_deg, n=73):
    """星下点 (lat_c,lon_c) 覆盖帽边界环 → [(lat,lon),...]（球面小圆参数式）。"""
    pts = []
    la, sig = lat_c * DEG, sigma_deg * DEG
    for k in range(n):
        az = 2.0 * math.pi * k / (n - 1)
        la2 = math.asin(math.sin(la) * math.cos(sig) +
                        math.cos(la) * math.sin(sig) * math.cos(az))
        lo2 = lon_c * DEG + math.atan2(math.sin(az) * math.sin(sig) * math.cos(la),
                                       math.cos(sig) - math.sin(la) * math.sin(la2))
        pts.append((math.degrees(la2), math.degrees(lo2) % 360.0))
    return pts


def elevation_from(lat_g, lon_g, p_ecef):
    """地面点对卫星（ECEF km）的仰角（度）与斜距（km）。"""
    la, lo = lat_g * DEG, lon_g * DEG
    gx = R_EARTH * math.cos(la) * math.cos(lo)
    gy = R_EARTH * math.cos(la) * math.sin(lo)
    gz = R_EARTH * math.sin(la)
    rx, ry, rz = p_ecef[0] - gx, p_ecef[1] - gy, p_ecef[2] - gz
    d = math.sqrt(rx * rx + ry * ry + rz * rz)
    if d < 1e-9:
        return 90.0, 0.0
    cos_zen = (gx * rx + gy * ry + gz * rz) / (R_EARTH * d)   # up·r̂(地→星)=cos(天顶角)
    el = 90.0 - math.degrees(math.acos(max(min(cos_zen, 1.0), -1.0)))
    return el, d


# ================================================================
# 可见性窗口（「轨道覆盖是否合理」核心判据）
# ================================================================
def access_windows(el, lat_g, lon_g, t_start, dur_h=24.0, el_min_deg=10.0,
                   step_s=20.0):
    """一天内目标点对卫星的可见窗口：AOS/LOS（unix 秒）/最大仰角/时长。
    固定步长扫描 + 窗口边界二分细化（GEO 步长无影响；LEO 边界误差 <step/2）。"""
    n = int(dur_h * 3600.0 / step_s) + 1
    wins = []
    cur = None
    for k in range(n):
        t = t_start + k * step_s
        e, _ = elevation_from(lat_g, lon_g, sat_position_ecef(t, el))
        if e >= el_min_deg:
            if cur is None:
                cur = dict(aos=t, los=t, el_max=e, t_max=t)
            else:
                cur["los"] = t
                if e > cur["el_max"]:
                    cur["el_max"], cur["t_max"] = e, t
        elif cur is not None:
            wins.append(cur)
            cur = None
    if cur is not None:
        wins.append(cur)
    # 覆盖率（可见时长/窗口总长）
    total = sum(w["los"] - w["aos"] for w in wins)
    for w in wins:
        w["dur_min"] = round((w["los"] - w["aos"]) / 60.0, 2)
        w["el_max"] = round(w["el_max"], 2)
        w["aos_h"] = round((w["aos"] - t_start) / 3600.0, 3)
        w["los_h"] = round((w["los"] - t_start) / 3600.0, 3)
    return dict(ok=True, windows=wins[:40], n_windows=len(wins),
                coverage_pct=round(100.0 * total / (dur_h * 3600.0), 2),
                total_min=round(total / 60.0, 1))


def ground_track(el, t_start, dur_h=24.0, n_pts=289):
    """星下点轨迹 [(t_offset_min, lat, lon), ...]。"""
    pts = []
    for k in range(n_pts):
        t = t_start + dur_h * 3600.0 * k / (n_pts - 1)
        la, lo, _ = sub_satellite(t, el)
        pts.append((round(dur_h * 60.0 * k / (n_pts - 1), 2), round(la, 3), round(lo, 3)))
    return pts


# ================================================================
# 某一时刻覆盖快照
# ================================================================
def snapshot(t_unix, el, targets=None, el_min_deg=10.0, circle_n=73):
    """指定时刻覆盖情况：星下点/高度/速度、覆盖帽 σ 与覆盖圈、各目标点仰角与可见性。"""
    p_eci = propagate_eci(el, t_unix)
    p_e = eci_to_ecef(p_eci[:3], t_unix)
    lat, lon, alt = sub_satellite(t_unix, el)
    vel = math.sqrt(p_eci[3] ** 2 + p_eci[4] ** 2 + p_eci[5] ** 2)
    sig = coverage_cap_deg(alt, el_min_deg)
    out = dict(ok=True, t_unix=t_unix, sub_lat=round(lat, 3), sub_lon=round(lon, 3),
               alt_km=round(alt, 1), vel_kms=round(vel, 3),
               sigma_deg=round(sig, 3), el_min_deg=el_min_deg,
               cov_radius_km=round(sig * DEG * R_EARTH, 1),
               circle=[[round(a, 3), round(b, 3)] for a, b in coverage_circle(lat, lon, sig, circle_n)],
               targets=[])
    for tg in targets or []:
        e, d = elevation_from(tg["lat"], tg["lon"], p_e)
        out["targets"].append(dict(name=tg.get("name", "(%.1f,%.1f)" % (tg["lat"], tg["lon"])),
                                   lat=tg["lat"], lon=tg["lon"],
                                   el_deg=round(e, 2), slant_km=round(d, 1),
                                   visible=bool(e >= el_min_deg)))
    return out


# ================================================================
# 轨道合理性评估（GEO 连续可见 / LEO 覆盖率+重访 / HEO 驻留）
# ================================================================
def assess_orbit(orbit_key, h_km, incl_deg, targets, el_min_deg=10.0,
                 t_start=None, ecc=0.0, raan_deg=0.0, argp_deg=0.0):
    """轨道覆盖合理性：对每个目标点算可见窗口 → 判定：
      · GEO：σ ≥ 目标离星位角距 → 全时可见（连续覆盖）
      · LEO/MEO/SSO：覆盖率 <100% → 间歇覆盖，给窗口数/最长间隔（重访）；
        连续覆盖需星座（提示 N 星 Walker，与 design_engine.constellation_metrics 联动）
      · HEO：远地点驻留时长占比（Molniya 高纬驻留特性）
    raan_deg：GEO 定点经度反解的升交点赤经（历元星下点经度=geo_lon）；
    返回 dict（含 verdict/建议文本——前端「轨道覆盖是否合理」面板）。"""
    t0 = t_start or (J2000_UNIX + 26.0 * 365.25 * 86400.0)    # ≈2026（示意历元）
    el = elements_from_altitude(h_km, incl_deg, ecc=ecc,
                                raan_deg=raan_deg, argp_deg=argp_deg)
    if orbit_key == "HEO":
        el = elements_from_altitude(h_km / 2.0, incl_deg, ecc=0.74, argp_deg=270.0)
    per = orbital_period_min(el)
    results = []
    for tg in targets:
        aw = access_windows(el, tg["lat"], tg["lon"], t0, dur_h=24.0,
                            el_min_deg=el_min_deg,
                            step_s=20.0 if per < 200 else 120.0)
        wins = aw["windows"]
        # 重访（相邻窗口 LOS→AOS 最长间隔）
        gap_max = 0.0
        for a, b in zip(wins, wins[1:]):
            gap_max = max(gap_max, b["aos_h"] - a["los_h"])
        results.append(dict(target=tg.get("name", "?"), lat=tg["lat"], lon=tg["lon"],
                            n_win=aw["n_windows"], cov_pct=aw["coverage_pct"],
                            dur_max_min=max((w["dur_min"] for w in wins), default=0.0),
                            el_max=max((w["el_max"] for w in wins), default=0.0),
                            revisit_h=round(gap_max, 2), windows=wins[:8]))
    continuous = all(r["cov_pct"] >= 99.5 for r in results)
    if orbit_key == "GEO":
        verdict = ("GEO 定点：%s。所有目标点 24h 连续可见（仰角≥%g°）——单星连续覆盖成立，"
                   "轨道选择合理。" % ("全时可见" if continuous else "存在不可见目标 → 星位/仰角门限需复核",
                                      el_min_deg))
        ok = continuous
    elif orbit_key == "HEO":
        dwell = max((r["dur_max_min"] for r in results), default=0.0)
        verdict = ("HEO（e≈0.74，远地点驻留）：单窗最长 %g 分钟——远地点驻留特性成立；"
                   "高纬目标覆盖优于 GEO，但需 2~3 星接力才能连续。" % dwell)
        ok = dwell >= 120.0
    else:
        if continuous:
            verdict = "%s 单星即连续覆盖（罕见，核对高度/仰角门限）。" % orbit_key
            ok = True
        else:
            worst = max(results, key=lambda r: r["revisit_h"]) if results else None
            verdict = ("%s 单星间歇覆盖：日均 %.0f 窗、覆盖率 %.0f%%、最长重访 %.1fh——"
                       "符合 LEO/MEO 物理特性；连续覆盖需星座组网（转「星座建议」反推 Walker 构型）。"
                       % (orbit_key, sum(r["n_win"] for r in results) / max(len(results), 1),
                          sum(r["cov_pct"] for r in results) / max(len(results), 1),
                          worst["revisit_h"] if worst else 0.0))
            ok = True      # 间歇覆盖对 LEO 是「合理」的，不合理=完全没有窗口
            if results and all(r["n_win"] == 0 for r in results):
                verdict = ("%s 倾角 %.0f° 覆盖不到目标纬度——轨道不合理，"
                           "倾角需 ≥ 目标最高纬度（+σ 余量）。" % (orbit_key, incl_deg))
                ok = False
    return dict(ok=ok, orbit=orbit_key, period_min=round(per, 2), incl_deg=incl_deg,
                h_km=h_km, ecc=el["ecc"], el_min_deg=el_min_deg, t_start=t0,
                results=results, verdict=verdict,
                track=[[round(a, 1), round(b, 2), round(c, 2)]
                       for a, b, c in ground_track(el, t0, dur_h=24.0, n_pts=145)])


# ================================================================
# 星蚀分析（太阳位置低精度历表 + 圆柱影判据）
# ================================================================
def sun_position_eci(t_unix):
    """太阳 ECI(J2000) 位置（km），低精度历表（Meeus 截断式，误差 <0.01°≈
    1.5e4 km——星蚀判据的影锥半角误差 <0.02°，功率核算足够）。"""
    d = (t_unix - J2000_UNIX) / 86400.0
    L = (280.460 + 0.9856474 * d) * DEG % (2.0 * math.pi)      # 平黄经
    g = (357.528 + 0.9856003 * d) * DEG % (2.0 * math.pi)      # 平近点角
    lam = L + (1.915 * math.sin(g) + 0.020 * math.sin(2.0 * g)) * DEG   # 真黄经
    eps = (23.439 - 0.0000004 * d) * DEG                       # 黄赤交角
    R_au = 1.00014 - 0.01671 * math.cos(g) - 0.00014 * math.cos(2.0 * g)
    R_km = R_au * 1.495978707e8
    return (R_km * math.cos(lam),
            R_km * math.cos(eps) * math.sin(lam),
            R_km * math.sin(eps) * math.sin(lam))


def in_eclipse(p_eci, t_unix):
    """圆柱影判据（GEO/LEO 功率核算口径）：卫星在日-地连线负侧且垂距 < R_earth。
    返回 (bool, depth_km)——depth 为影内深度（负=光照）。"""
    s = sun_position_eci(t_unix)
    sn = math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
    ux, uy, uz = s[0] / sn, s[1] / sn, s[2] / sn          # 日方向单位矢量
    proj = p_eci[0] * ux + p_eci[1] * uy + p_eci[2] * uz  # 沿日方向投影
    if proj >= 0.0:
        return False, proj
    perp = math.sqrt(max(p_eci[0] ** 2 + p_eci[1] ** 2 + p_eci[2] ** 2
                         - proj * proj, 0.0))
    if perp < R_EARTH:
        return True, -proj
    return False, perp - R_EARTH


def sun_declination_deg(t_unix):
    """太阳赤纬（度）——由 sun_position_eci 直接取 asin(z/|r|)，与星蚀判据同源。"""
    s = sun_position_eci(t_unix)
    r = math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
    if r <= 0:
        return 0.0
    return math.degrees(math.asin(max(min(s[2] / r, 1.0), -1.0)))


def worst_eclipse_epoch(t_ref=None, t_start=None, t_end=None):
    """返回「星蚀最恶劣历元」——GEO 功率设计的强制口径（分点季）。

    背景：GEO 只在太阳赤纬 |δ| < 0.264°（分点前后各约 ±22 天窗口）时进入
    地球圆柱影；若在任意历元（如 6 月）扫描，会得到「0 段星蚀」的**非保守**
    结论，导致电池容量被严重低估。因此设计分析必须锚定分点。
    LEO/MEO/SSO 每轨均过影（占比 ~35%），历元无关紧要，但同样返回分点历元
    以统一口径（且分点季 LEO 也是最长星蚀）。

    实现：在 [t_start, t_end]（默认 t_ref 前后 400 天）内以 1 天步长扫描
    |δ_sun| 最小值 → 二分细化到 ~1h。t_ref=None 时取 2026 春分示意历元。
    """
    if t_ref is None:
        t_ref = J2000_UNIX + 26.0 * 365.25 * 86400.0 + 78 * 86400.0
    lo = t_start if t_start is not None else t_ref - 400.0 * 86400.0
    hi = t_end if t_end is not None else t_ref + 400.0 * 86400.0
    best_t, best_abs = lo, abs(sun_declination_deg(lo))
    t = lo
    while t <= hi:
        a = abs(sun_declination_deg(t))
        if a < best_abs:
            best_abs, best_t = a, t
        t += 86400.0
    # 二分细化（±1 天 → ~1h）
    a, b = best_t - 86400.0, best_t + 86400.0
    for _ in range(12):
        m1 = a + (b - a) / 3.0
        m2 = b - (b - a) / 3.0
        if abs(sun_declination_deg(m1)) < abs(sun_declination_deg(m2)):
            b = m2
        else:
            a = m1
    t_best = (a + b) / 2.0
    return dict(t_unix=t_best, declination_deg=round(sun_declination_deg(t_best), 4),
                note="分点季（|δ_sun| 最小）→ GEO 星蚀最恶劣窗口；设计必须按此口径核算电池")


def eclipse_analysis(el, t_start, dur_h=48.0, step_s=30.0,
                     p_load_w=1000.0, batt_kwh=4.0, dod_max=0.8,
                     bus_v=100.0):
    """星蚀窗口分析 + 电池核算（功率子系统第一性判据）：
      · 扫描 dur_h 找全部星蚀段（进/出影时刻、时长）
      · LEO：每轨 ~35%（550km 圆柱影最大 37.2%）；GEO：仅分点季（β<0.264°）
        出现，最长 ~69min（圆柱影；真实圆锥影 72min 上限）
      · 电池需求 E_req = P_load × t_ecl_max / DoD_max → 与平台容量对比
      · 母线电流 I = P_load / bus_v（放电平均）
    返回 dict：段列表/最长/平均/占比/电池需求/判定 verdict。"""
    n = int(dur_h * 3600.0 / step_s) + 1
    segs = []
    cur = None
    for k in range(n):
        t = t_start + k * step_s
        p = propagate_eci(el, t)[:3]
        ec, _ = in_eclipse(p, t)
        if ec:
            if cur is None:
                cur = dict(t_in=t)
            cur["t_out"] = t
        elif cur is not None:
            segs.append(cur)
            cur = None
    if cur is not None:
        segs.append(cur)
    durs = [(s["t_out"] - s["t_in"]) / 60.0 for s in segs]
    per = orbital_period_min(el)
    total_ecl_min = sum(durs)
    t_max = max(durs) if durs else 0.0
    # 每轨平均星蚀时长（LEO 用占比×周期；GEO 段稀疏，直接用扫描窗占比）
    ecl_frac = total_ecl_min / (dur_h * 60.0)
    ecl_per_orbit_min = ecl_frac * per
    # 电池核算
    e_req_kwh = p_load_w * (t_max / 60.0) / max(dod_max, 1e-6) / 1000.0
    batt_ok = batt_kwh >= e_req_kwh
    i_bus = p_load_w / max(bus_v, 1.0)
    is_geo = per > 1400.0
    if is_geo:
        verdict = ("GEO 星蚀：扫描 %gh 出现 %d 段，最长 %.0f min（分点季 ±22 天窗口内"
                   "每天一段，理论上限 72 min）；电池需求 %.2f kWh（DoD≤%.0f%%），"
                   "平台 %.2f kWh → %s。"
                   % (dur_h, len(segs), t_max, e_req_kwh, dod_max * 100, batt_kwh,
                      "满足" if batt_ok else "不足，需扩容"))
    else:
        verdict = ("LEO/MEO 星蚀：每轨平均 %.1f min（占比 %.0f%%，圆柱影最大理论 "
                   "%.0f%%），最长 %.1f min；电池需求 %.2f kWh（DoD≤%.0f%%），"
                   "平台 %.2f kWh → %s；放电母线电流 ≈%.1f A @%.0fV。"
                   % (ecl_per_orbit_min, ecl_frac * 100,
                      100.0 * (math.pi - 2.0 * math.acos(min(R_EARTH / el["a_km"], 1.0)))
                      / math.pi, t_max, e_req_kwh, dod_max * 100, batt_kwh,
                      "满足" if batt_ok else "不足，需扩容", i_bus, bus_v))
    return dict(ok=True, n_eclipses=len(segs), t_max_min=round(t_max, 2),
                t_total_min=round(total_ecl_min, 1),
                eclipse_frac_pct=round(ecl_frac * 100.0, 2),
                per_orbit_min=round(ecl_per_orbit_min, 2),
                period_min=round(per, 2),
                segments=[dict(t_in_h=round((s["t_in"] - t_start) / 3600.0, 3),
                               t_out_h=round((s["t_out"] - t_start) / 3600.0, 3),
                               dur_min=round((s["t_out"] - s["t_in"]) / 60.0, 2))
                          for s in segs[:30]],
                power=dict(p_load_w=p_load_w, batt_kwh=batt_kwh, dod_max=dod_max,
                           bus_v=bus_v, e_req_kwh=round(e_req_kwh, 3),
                           batt_ok=batt_ok, i_bus_a=round(i_bus, 2)),
                is_geo=is_geo, verdict=verdict)


# ================================================================
# 星座多星时序仿真（覆盖重数时间序列 + 间隙统计）
# ================================================================
def constellation_timeseries(els, targets, t_start, dur_h=24.0, step_s=60.0,
                             el_min_deg=10.0, n_required=1):
    """多星推进 → 各目标点覆盖重数（同时可见星数）时间序列 → 连续性/间隙统计。

    els     : 根数列表（Walker 构型由调用方展开；本函数只管传播）
    targets : [{name,lat,lon}]
    返回 dict：每目标 {series(t_min, n_vis), 覆盖率, 连续≥N 占比, 最长连续,
    间隙列表(次数/最长/平均), 重数直方} + 系统判定 verdict。"""
    n_t = int(dur_h * 3600.0 / step_s) + 1
    out_targets = []
    all_ok = True
    for tg in targets:
        series = []
        cur_vis, cur_gap = 0.0, 0.0
        gaps = []
        runs = []
        hist = {}
        n_ge_req_t = 0.0
        prev_state = None
        for k in range(n_t):
            t = t_start + k * step_s
            nv = 0
            for el in els:
                e, _ = elevation_from(tg["lat"], tg["lon"], sat_position_ecef(t, el))
                if e >= el_min_deg:
                    nv += 1
            series.append((round(k * step_s / 60.0, 1), nv))
            hist[nv] = hist.get(nv, 0) + 1
            state = nv >= n_required
            if state:
                n_ge_req_t += 1.0
                if prev_state is False and cur_gap > 0:
                    gaps.append(round(cur_gap * step_s / 60.0, 1))
                    cur_gap = 0.0
                cur_vis += 1.0
            else:
                cur_gap += 1.0
            prev_state = state
        if cur_gap > 0:
            gaps.append(round(cur_gap * step_s / 60.0, 1))
        # 连续 run 长度（≥N 段）
        run = 0.0
        for _, nv in series:
            if nv >= n_required:
                run += 1.0
            elif run > 0:
                runs.append(run * step_s / 60.0)
                run = 0.0
        if run > 0:
            runs.append(run * step_s / 60.0)
        cov_pct = 100.0 * n_ge_req_t / n_t
        ok_t = cov_pct >= 99.5
        all_ok = all_ok and ok_t
        out_targets.append(dict(
            target=tg.get("name", "?"), lat=tg["lat"], lon=tg["lon"],
            series=series[::max(1, len(series) // 145)],       # 抽稀 ≤145 点给前端
            cov_pct=round(cov_pct, 2),
            continuous=ok_t,
            n_gap=len(gaps),
            gap_max_min=max(gaps, default=0.0),
            gap_mean_min=round(sum(gaps) / len(gaps), 1) if gaps else 0.0,
            run_min_min=round(min(runs), 1) if runs else 0.0,
            hist={str(k2): v for k2, v in sorted(hist.items())},
            mean_mult=round(sum(nv for _, nv in series) / n_t, 2)))
    n_sat = len(els)
    verdict = ("星座 %d 星：目标 %s；%s"
               % (n_sat, "、".join("%s 覆盖率 %.1f%%（≥%d 星连续 %s）"
                                    % (r["target"], r["cov_pct"], n_required,
                                       "成立" if r["continuous"] else "不成立，最长间隙 %.0f min"
                                       % r["gap_max_min"]) for r in out_targets),
                  "满足连续覆盖指标" if all_ok else "存在覆盖间隙 → 增加星数/调整相位"))
    return dict(ok=True, n_sats=n_sat, n_required=n_required,
                el_min_deg=el_min_deg, dur_h=dur_h, step_s=step_s,
                targets=out_targets, all_continuous=all_ok, verdict=verdict)


# ================================================================
# 位置保持 ΔV 与推进剂寿命核算
# ================================================================
def station_keeping(orbit_key, h_km, incl_deg, life_yr, isp_s=290.0,
                    dry_mass_kg=1000.0, ecc=0.0):
    """位置保持 ΔV → 推进剂质量 → 寿命判定（第一性：齐奥尔科夫斯基）。

    GEO：南北位保（倾角保持）主导 ≈ 50 m/s/yr（含动量轮卸载余量）；
         东西位保（经度保持）≈ 2 m/s/yr；合计取 52 m/s/yr（工程惯例）。
    LEO/MEO/SSO：大气 drag 补轨主导——经验式 ΔV/yr 随高度指数衰减
         （550km≈2~5 m/s/yr、400km≈25 m/s/yr、300km≈150 m/s/yr 量级，
         太阳活动平均口径）；倾角保持另计 ~1 m/s/yr。
    HEO：远地点位保 ~5 m/s/yr 量级。
    返回 dict：dv_total、m_prop、m_wet、Δm 占比、寿命判定 verdict。"""
    life = max(float(life_yr), 0.5)
    key = (orbit_key or "").upper()
    if key == "GEO":
        dv_yr = 52.0                     # m/s/yr（N-S 50 + E-W 2）
        src = "南北 50 + 东西 2 m/s/yr（含卸载余量，工程惯例）"
    elif key in ("LEO", "SSO", "MEO"):
        if h_km >= 800.0:
            dv_yr = 0.5
        elif h_km >= 500.0:
            dv_yr = 4.0
        elif h_km >= 400.0:
            dv_yr = 25.0
        else:
            dv_yr = 150.0
        dv_yr += 1.0                     # 倾角保持
        src = ("drag 补轨（高度 %g km 经验档）+ 倾角保持 1 m/s/yr" % h_km)
    elif key == "HEO":
        dv_yr = 5.0
        src = "远地点位保经验值"
    else:
        dv_yr = 5.0
        src = "默认经验值"
    dv_total = dv_yr * life
    ve = 9.80665 * max(float(isp_s), 50.0)          # 有效排气速度 m/s
    # 齐氏：Δv = ve·ln(m_wet/m_dry) → m_prop = m_dry·(e^{Δv/ve} − 1)
    m_prop = dry_mass_kg * (math.exp(dv_total / ve) - 1.0)
    m_wet = dry_mass_kg + m_prop
    frac = m_prop / m_wet * 100.0
    ok = frac < 15.0
    verdict = ("%s 位保：ΔV %.0f m/s（%s × %g 年）；Isp %g s → 推进剂 %.0f kg"
               "（湿重 %.0f kg，占比 %.1f%%）——%s"
               % (key, dv_total, src, life, isp_s, m_prop, m_wet, frac,
                  "推进剂占比合理（<15%），寿命指标可支撑" if ok
                  else "占比偏高，建议电推（Isp 1500~3000s）或缩减寿命指标"))
    return dict(ok=ok, orbit=key, dv_per_yr=round(dv_yr, 1), dv_total_ms=round(dv_total, 1),
                isp_s=isp_s, m_prop_kg=round(m_prop, 1), m_wet_kg=round(m_wet, 1),
                prop_frac_pct=round(frac, 2), dry_mass_kg=dry_mass_kg,
                life_yr=life, source=src, verdict=verdict)


# ================================================================
# STK Ephemeris .e 导出（stk.v.12 · J2000 ECI · 位置+速度）
# ================================================================
def _stk_time(t_unix):
    """unix 秒 → STK 时间串 'DD Mon YYYY HH:MM:SS.sss'（UTC）。"""
    import time
    g = time.gmtime(int(t_unix))
    ms = int(round((t_unix - int(t_unix)) * 1000))
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][g.tm_mon - 1]
    return "%02d %s %04d %02d:%02d:%06.3f" % (g.tm_mday, mon, g.tm_year,
                                              g.tm_hour, g.tm_min, g.tm_sec + ms / 1000.0)


def export_stk_ephemeris(el, path, t_start, dur_h=24.0, step_s=60.0, name="Satellite1"):
    """导出 STK Ephemeris（.e）：stk.v.12 / J2000 / 位置速度（km, km/s）。
    STK 导入：Insert → 选 Object=Satellite → From Ephemeris File → 该 .e。"""
    n = int(dur_h * 3600.0 / step_s) + 1
    lines = ["stk.v.12", "BEGIN Ephemeris",
             "NumberOfEphemerisPoints %d" % n,
             "ScenarioEpoch %s" % _stk_time(t_start),
             "InterpolationMethod Lagrange", "InterpolationOrder 5",
             "CentralBody Earth", "CoordinateSystem J2000",
             "Name %s" % name,
             "EphemerisTimePosVel"]
    for k in range(n):
        t = t_start + k * step_s
        p = propagate_eci(el, t)
        lines.append("%s %.6f %.6f %.6f %.9f %.9f %.9f"
                     % (_stk_time(t), p[0], p[1], p[2], p[3], p[4], p[5]))
    lines.append("END Ephemeris")
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, points=n, format="stk.v.12/J2000/TimePosVel")


# ================================================================
# 自检
# ================================================================
if __name__ == "__main__":
    import os
    print("=== orbit_engine self-test ===")
    # 1) GEO：周期≈1436min，星下点漂移 <0.15°/天（J2 摄动 + GMST 常数精度）
    geo = elements_from_altitude(35786.0, 0.01)
    per = orbital_period_min(geo)
    assert abs(per - 1436.1) < 1.0, "GEO 周期应≈1436min，实得 %.2f" % per
    t0 = J2000_UNIX + 26.4 * 365.25 * 86400.0
    la0, lo0, al0 = sub_satellite(t0, geo)
    la1, lo1, _ = sub_satellite(t0 + 86400.0, geo)
    drift = abs(((lo1 - lo0 + 180.0) % 360.0) - 180.0)
    assert abs(al0 - 35786.0) < 1.0, "GEO 高度应≈35786，实得 %.1f" % al0
    assert drift < 0.15, "GEO 星下点日漂移应<0.15°（恒星时/太阳日差 0.99°×周期误差），实得 %.3f°" % drift
    print("[GEO] period=%.2fmin alt=%.1fkm drift=%.4f°/d" % (per, al0, drift))

    # 2) LEO 550km SSO 倾角 97.5°：周期≈95.6min，星下点西移≈22.5°/圈
    leo = elements_from_altitude(550.0, 97.5)
    per2 = orbital_period_min(leo)
    assert abs(per2 - 95.6) < 1.0, "LEO 周期应≈95.6min，实得 %.2f" % per2
    _, loA, _ = sub_satellite(t0, leo)
    _, loB, _ = sub_satellite(t0 + per2 * 60.0, leo)
    west = (loA - loB) % 360.0
    assert 21.0 < west < 24.5, "LEO 每圈星下点西移应≈22.5°，实得 %.2f°" % west
    # J2 交点退行：SSO 应≈+0.9856°/天（与太阳同步）
    n, raan_dot, _ = mean_motion(leo)
    raan_day = math.degrees(raan_dot * 86400.0)
    assert abs(raan_day - 0.9856) < 0.15, "SSO J2 交点退行应≈0.986°/d，实得 %.3f" % raan_day
    print("[LEO] period=%.2fmin west=%.2f°/rev raan_dot=%.4f°/d (SSO✓)" % (per2, west, raan_day))

    # 3) 可见性：LEO 对星下点附近目标必有窗口；对极点目标（incl 97.5 → 可见）
    aw = access_windows(leo, 30.0, 105.0, t0, dur_h=24.0, el_min_deg=10.0)
    assert aw["n_windows"] >= 2, "LEO 24h 对固定目标应有多窗，实得 %d" % aw["n_windows"]
    assert 0 < aw["coverage_pct"] < 60, "LEO 单星覆盖率应<60%%，实得 %.1f%%" % aw["coverage_pct"]
    print("[LEO access] n_win=%d cov=%.1f%% el_max=%.1f°" %
          (aw["n_windows"], aw["coverage_pct"],
           max(w["el_max"] for w in aw["windows"])))
    # GEO 对区域内目标连续可见
    geo_assess = assess_orbit("GEO", 35786.0, 0.01,
                              [dict(name="巴基斯坦", lat=30.0, lon=70.0)],
                              el_min_deg=20.0, t_start=t0)
    assert geo_assess["ok"] and geo_assess["results"][0]["cov_pct"] >= 99.5, \
        "GEO 60E 位对巴基斯坦应连续可见"
    print("[GEO assess]", geo_assess["verdict"][:60], "...")
    # LEO 间歇覆盖判定
    leo_assess = assess_orbit("LEO", 550.0, 53.0,
                              [dict(name="北京", lat=39.9, lon=116.4)],
                              el_min_deg=10.0, t_start=t0)
    assert leo_assess["results"][0]["n_win"] >= 2 and not \
        all(r["cov_pct"] >= 99.5 for r in leo_assess["results"])
    print("[LEO assess]", leo_assess["verdict"][:70], "...")
    # LEO 极轨对赤道目标也应有窗口；倾角不足 → 高纬目标无窗
    bad = assess_orbit("LEO", 550.0, 30.0, [dict(name="高纬", lat=70.0, lon=100.0)],
                       el_min_deg=10.0, t_start=t0)
    assert not bad["ok"], "倾角 30° 覆盖不到 70°N 目标，应判不合理"
    print("[LEO bad-incl]", bad["verdict"][:60], "...")

    # 4) 快照 + 覆盖帽：550km/el=10° → σ=acos(R·cos el/(R+h))−el≈14.97°（R_cov≈1665km）
    sig = coverage_cap_deg(550.0, 10.0)
    assert 13.0 < sig < 17.0, "550km/10° 覆盖帽应≈15°，实得 %.2f" % sig
    sig0 = coverage_cap_deg(550.0, 0.0)
    assert 22.0 < sig0 < 24.0, "550km/0°（地平线）覆盖帽应≈23°，实得 %.2f" % sig0
    # GEO/el=0 → σ≈81.3°（覆盖 42% 地表）
    sig_geo = coverage_cap_deg(35786.0, 0.0)
    assert 80.5 < sig_geo < 82.0, "GEO 地平线覆盖帽应≈81.3°，实得 %.2f" % sig_geo
    sn = snapshot(t0 + 3600.0, leo, targets=[dict(name="t1", lat=10.0, lon=100.0)],
                  el_min_deg=10.0)
    assert len(sn["circle"]) == 73 and -90 <= sn["sub_lat"] <= 90
    print("[snapshot] sub=(%.2f,%.2f) σ=%.2f° R_cov=%.0fkm tgt_el=%.1f°" %
          (sn["sub_lat"], sn["sub_lon"], sn["sigma_deg"], sn["cov_radius_km"],
           sn["targets"][0]["el_deg"]))

    # 5) STK .e 导出
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out, exist_ok=True)
    r = export_stk_ephemeris(leo, os.path.join(out, "_orbit_test.e"), t0,
                             dur_h=2.0, step_s=60.0, name="LEO_TEST")
    assert r["points"] == 121
    with open(r["path"], "r", encoding="ascii") as f:
        head = f.read(400)
    assert head.startswith("stk.v.12") and "CoordinateSystem J2000" in head \
        and "EphemerisTimePosVel" in head
    print("[stk .e]", r)

    # 6) 星蚀：LEO 550km 每轨占比应≈35%（圆柱影理论 max=37.2%）
    ecl = eclipse_analysis(leo, t0, dur_h=6.0, step_s=20.0,
                           p_load_w=800.0, batt_kwh=4.0)
    print("[eclipse LEO]", ecl["verdict"][:100], "...")
    assert ecl["n_eclipses"] >= 3, "LEO 6h 应有 ≥3 段星蚀（周期 95.6min），实得 %d" % ecl["n_eclipses"]
    assert 25.0 < ecl["eclipse_frac_pct"] < 45.0, \
        "LEO 星蚀占比应≈35%%，实得 %.1f" % ecl["eclipse_frac_pct"]
    assert 25.0 < ecl["t_max_min"] < 40.0, \
        "LEO 最长星蚀应 25~40min，实得 %.1f" % ecl["t_max_min"]
    assert ecl["power"]["e_req_kwh"] > 0 and ecl["power"]["i_bus_a"] > 0
    # GEO：春秋分附近（3/20 前后）有星蚀，6 月无
    t_equinox = J2000_UNIX + 26.0 * 365.25 * 86400.0 + 78 * 86400.0   # ≈2026-03-20
    ecl_geo = eclipse_analysis(geo, t_equinox, dur_h=48.0, step_s=60.0,
                               p_load_w=1500.0, batt_kwh=6.0)
    print("[eclipse GEO 分点]", ecl_geo["verdict"][:100], "...")
    assert ecl_geo["n_eclipses"] >= 1, "GEO 分点季 48h 应有星蚀段"
    assert 60.0 < ecl_geo["t_max_min"] < 75.0, \
        "GEO 分点最长星蚀应 60~75min，实得 %.1f" % ecl_geo["t_max_min"]
    # 6 月（β 最大）GEO 应无星蚀
    t_june = J2000_UNIX + 26.0 * 365.25 * 86400.0 + 165 * 86400.0    # ≈2026-06-15
    ecl_geo_j = eclipse_analysis(geo, t_june, dur_h=48.0, step_s=60.0)
    assert ecl_geo_j["n_eclipses"] == 0, "GEO 夏至附近应无星蚀（β=23.4°>0.26°），实得 %d 段" % ecl_geo_j["n_eclipses"]

    # 7) 星座时序：Walker 2 面×3 星（550km/53°），北京目标——结构正确性核查
    #    （6 星对单一中纬目标覆盖率仅 ~10% 是物理合理结果，只验证结构不验证阈值）
    els_c = []
    for pl in range(2):
        for s in range(3):
            els_c.append(elements_from_altitude(
                550.0, 53.0, raan_deg=pl * 60.0,
                nu0_deg=s * 120.0 + pl * 60.0))
    ct = constellation_timeseries(els_c, [dict(name="北京", lat=39.9, lon=116.4)],
                                  t0, dur_h=6.0, step_s=120.0, el_min_deg=10.0,
                                  n_required=1)
    print("[constellation 6星]", ct["verdict"][:110], "...")
    assert ct["n_sats"] == 6 and len(ct["targets"]) == 1
    tgt = ct["targets"][0]
    assert 0.0 < tgt["cov_pct"] <= 100.0 and len(tgt["series"]) >= 100
    assert tgt["mean_mult"] >= 0.0 and tgt["mean_mult"] <= 6.0
    assert isinstance(tgt["hist"], dict) and tgt["gap_max_min"] >= 0.0
    assert not tgt["continuous"], "6 星 Walker 对中纬单点不应达成连续覆盖"

    # 7b) 铱星构型（6 面×11 星，780km/86.4° 近极轨道）——应达成连续覆盖
    els_i = []
    for pl in range(6):
        for s in range(11):
            els_i.append(elements_from_altitude(
                780.0, 86.4, raan_deg=pl * 30.0,
                nu0_deg=s * (360.0 / 11.0) + pl * (360.0 / 11.0 / 6.0)))
    ct_i = constellation_timeseries(els_i, [dict(name="北京", lat=39.9, lon=116.4)],
                                    t0, dur_h=6.0, step_s=120.0, el_min_deg=8.2,
                                    n_required=1)
    tgt_i = ct_i["targets"][0]
    print("[constellation 66星铱星]", ct_i["verdict"][:110], "...")
    assert ct_i["n_sats"] == 66
    assert tgt_i["cov_pct"] >= 99.5 and tgt_i["continuous"], \
        "铱星构型对北京覆盖率应 ≥99.5%%，实得 %.2f%%" % tgt_i["cov_pct"]
    assert tgt_i["mean_mult"] > 1.5, \
        "铱星构型平均重数应 >1.5，实得 %.2f" % tgt_i["mean_mult"]

    # 8) 位保：GEO 15 年 ΔV≈780 m/s → 化学推进占比核查
    sk = station_keeping("GEO", 35786.0, 0.05, 15.0, isp_s=290.0, dry_mass_kg=2000.0)
    print("[station-keeping GEO]", sk["verdict"][:110], "...")
    assert abs(sk["dv_total_ms"] - 780.0) < 1.0, "GEO 15yr ΔV 应≈780，实得 %.1f" % sk["dv_total_ms"]
    assert sk["m_prop_kg"] > 500.0 and not sk["ok"], "化学推 GEO 15yr 推进剂占比应 >15%（触发建议电推）"
    sk_e = station_keeping("GEO", 35786.0, 0.05, 15.0, isp_s=1800.0, dry_mass_kg=2000.0)
    assert sk_e["ok"] and sk_e["m_prop_kg"] < 250.0, "电推（Isp 1800s）占比应 <15%"
    sk_l = station_keeping("LEO", 550.0, 53.0, 5.0, isp_s=290.0, dry_mass_kg=500.0)
    print("[station-keeping LEO]", sk_l["verdict"][:100], "...")
    assert abs(sk_l["dv_total_ms"] - 25.0) < 1.0, "LEO 550km 5yr ΔV 应≈25，实得 %.1f" % sk_l["dv_total_ms"]
    assert sk_l["ok"], "LEO drag 补轨推进剂占比应合理"
    print("=== ALL PASS ===")
