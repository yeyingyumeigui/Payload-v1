# -*- coding: utf-8 -*-
"""天线远场方向图引擎（纯 Python 第一性原理，零第三方依赖，冻结 exe 可用）。

产出 GRASP 风格的 grid（θ×φ 全空间）与 cut（±span 主面切面）方向图，
区分「不扫描（boresight）」与「扫描到指定角（θ0,φ0）」，画出**次级方向图**
（secondary pattern = 单元/馈源方向图 × 阵因子，或反射面口径远场），
并在 ±15° cut 内做**栅瓣（grating lobe）检测**。

两条物理路径：
  A) 相控阵（planar array）——可分离阵因子 AF(θ,φ)=AFx(u)·AFy(v)，
     u=sinθcosφ、v=sinθsinφ；扫描 = 相位梯度 u0=sinθ0cosφ0、v0=sinθ0sinφ0。
     栅瓣解析判据：sinθ_gl·cosφ = u0 + n_x·λ/dx，sinθ_gl·sinφ = v0 + n_y·λ/dy，
     落在可见区（u²+v²≤1）即为真栅瓣。次级方向图 = |AF|²·|E_el(θ)|²。
  B) 反射面（reflector）——圆口径 Hankel 变换 E(u)=∫₀ᵃ t(ρ)J₀(kρu)ρdρ 出次级
     方向图（含真实次瓣）；扫描 = 波束斜移（u→u−sinθ0）。连续口径**无栅瓣**。

所有方向图归一化到峰值（dBr），另给峰值增益（dBi）。
导出：GRASP 球面网格 .grd（复 E 场 θ×φ）+ 通用三列 ASCII（theta,phi,gain_dBi）。
"""
from __future__ import annotations

import math

from grasp_bridge import lam_m, peak_gain_dbi, DEFAULT_ETA

C_M_S = 299792458.0
DEG = math.pi / 180.0


# ================================================================
# 通用工具
# ================================================================
def _db(v, floor=-120.0):
    """**功率**(线性比) → dB（10·log10）。本模块 grid/cut 值一律是功率比
    （|AF|²·el、(E/E_pk)²），必须用 10·log10；用 20·log10 会把所有 dBr 翻倍
    （旁瓣 -25→-50、θ3dB 变成 -1.5dB 宽度）。v≤0 或极小 → floor。"""
    if v is None:
        return floor
    try:
        v = float(v)
    except (TypeError, ValueError):
        return floor
    if v <= 1e-12:
        return floor
    return max(10.0 * math.log10(v), floor)


def _norm_db(vals, peak=None):
    """把一组**功率**线性值归一化为 dBr（峰值=0）。返回 (dbr_list, peak)。"""
    if peak is None:
        peak = max(vals) if vals else 1.0
    if peak <= 0:
        peak = 1.0
    return [_db(v / peak) for v in vals], peak


def element_pattern_dbr(theta_deg, q=1.5, backend_null_db=-25.0):
    """阵元/馈源**功率**方向图（dB）：G_el(θ)∝cos^q(θ)（θ<90°），背瓣按 backend_null 截止。
    cos^q 是功率口径（微带贴片/偶极子工程近似），故 dB=10·q·log10(cosθ)。"""
    th = theta_deg * DEG
    c = math.cos(th)
    if c <= 0.0:
        return backend_null_db
    return max(10.0 * q * math.log10(c), backend_null_db)


# ================================================================
# 幅度锥削（taper）
# ================================================================
def taper_weights(n, kind="cosine", p=1.0, edge_db=-10.0, pedestal=0.0):
    """一维 N 元的实幅度权（m=0..N-1，对称）。
    kind: uniform / cosine(cos^p) / gaussian / taylor(低旁瓣近似)。
    edge_db 用于 gaussian 定标；pedestal 为幅度底（0~1）。"""
    if n <= 1:
        return [1.0] * max(n, 1)
    w = []
    if kind == "uniform":
        w = [1.0] * n
    elif kind == "cosine":
        for m in range(n):
            x = (m - (n - 1) / 2.0) / ((n - 1) / 2.0)      # -1..1
            w.append(max(math.cos(math.pi / 2.0 * x), 0.0) ** p)
    elif kind == "gaussian":
        c = -edge_db * math.log(10.0) / 20.0              # t(1)/t(0)=10^(edge/20)
        for m in range(n):
            x = (m - (n - 1) / 2.0) / ((n - 1) / 2.0)
            w.append(math.exp(-c * x * x))
    elif kind == "taylor":
        # Taylor 低旁瓣近似：cosine-on-pedestal（工程上旁瓣 ~ -25dB）
        ped = max(pedestal, 0.18)
        for m in range(n):
            x = (m - (n - 1) / 2.0) / ((n - 1) / 2.0)
            w.append(ped + (1.0 - ped) * max(math.cos(math.pi / 2.0 * x), 0.0))
    else:
        w = [1.0] * n
    # 归一到最大 1
    mx = max(w) or 1.0
    return [x / mx for x in w]


# ================================================================
# A) 相控阵：可分离阵因子
# ================================================================
def _af_axis(weights, d_over_lam, s, s0):
    """单轴阵因子（复）。s=方向余弦(u 或 v)，s0=扫描方向余弦。
    AF = Σ_m a_m·exp(j·2π·(d/λ)·(s−s0)·m_c)，m_c 为居中索引。"""
    n = len(weights)
    re = 0.0
    im = 0.0
    k = 2.0 * math.pi * d_over_lam * (s - s0)
    for m in range(n):
        mc = m - (n - 1) / 2.0
        psi = k * mc
        a = weights[m]
        re += a * math.cos(psi)
        im += a * math.sin(psi)
    return re, im


def array_gain_db(nx, ny, d_lam, peak_gain=None, taper="cosine", taper_p=1.0,
                 el_q=1.5):
    """相控阵峰值增益（dBi）：G=η_ap·4π·(nx·ny·d²)/λ²=η_ap·4π·nx·ny·(d/λ)²。
    η_ap 由 taper 效率近似（uniform=1.0, cosine≈0.75, taylor≈0.8）。"""
    if peak_gain is not None:
        return float(peak_gain)
    eta = {"uniform": 1.0, "cosine": 0.75, "gaussian": 0.7, "taylor": 0.8}.get(taper, 0.75)
    g = eta * 4.0 * math.pi * nx * ny * d_lam * d_lam
    return 10.0 * math.log10(max(g, 1e-9))


def phased_array_pattern(freq_ghz, nx, ny, d_lam=0.5, scan_theta=0.0, scan_phi=0.0,
                         taper="cosine", taper_p=1.0, edge_db=-10.0, el_q=1.5,
                         peak_gain_dbi=None, grid_n_theta=91, grid_n_phi=73,
                         cut_span=15.0, cut_n=301, cut_phi=0.0, theta_max=90.0):
    """平面相控阵次级方向图（element×array factor）。

    返回 dict：grid(θ×φ dBr)、cut(±cut_span dBr)、栅瓣(解析+数值)、峰值增益、θ3dB、首旁瓣。
    scan_theta/scan_phi=0 → boresight（不扫描）；>0 → 扫描到指定角。
    """
    lam = lam_m(freq_ghz)
    wx = taper_weights(nx, taper, taper_p, edge_db)
    wy = taper_weights(ny, taper, taper_p, edge_db)
    u0 = math.sin(scan_theta * DEG) * math.cos(scan_phi * DEG)
    v0 = math.sin(scan_theta * DEG) * math.sin(scan_phi * DEG)

    g0 = array_gain_db(nx, ny, d_lam, peak_gain_dbi, taper)

    def gain_dbr_at(theta_deg, phi_deg):
        th = theta_deg * DEG
        u = math.sin(th) * math.cos(phi_deg * DEG)
        v = math.sin(th) * math.sin(phi_deg * DEG)
        axr, axi = _af_axis(wx, d_lam, u, u0)
        ayr, ayi = _af_axis(wy, d_lam, v, v0)
        # 复乘
        re = axr * ayr - axi * ayi
        im = axr * ayi + axi * ayr
        af2 = re * re + im * im
        el = element_pattern_dbr(theta_deg, el_q)      # dBr（θ=0→0）
        el_lin = 10.0 ** (el / 10.0)
        return af2 * el_lin, af2

    # 精确查询闭包（coverage_engine 逐地面点投影用，**不经 grid 插值**——
    # grid θ 分辨率 1°/点对 0.4° 级窄波束不足以解析 −3dB 等值线）。
    # 入参 = 单位方向（星→目标）在阵体坐标系的分量：x=北参考、y=东参考、z=boresight。
    pk_val, _ = gain_dbr_at(scan_theta, scan_phi)
    pk_val = pk_val if pk_val > 0 else 1.0

    def _gain_arr(a, b, c):
        u = max(min(a, 1.0), -1.0)
        vv = max(min(b, 1.0), -1.0)
        axr, axi = _af_axis(wx, d_lam, u, u0)
        ayr, ayi = _af_axis(wy, d_lam, vv, v0)
        re = axr * ayr - axi * ayi
        im = axr * ayi + axi * ayr
        af2 = re * re + im * im
        cc = max(min(c, 1.0), -1.0)
        if cc <= 0.0:                                   # 背向：阵元方向图截止
            return 0.0
        return af2 * (cc ** el_q) / pk_val              # cos^q 功率口径，峰值归一

    # ---- grid（θ×φ 全空间，找栅瓣用）----
    thetas = [theta_max * i / (grid_n_theta - 1) for i in range(grid_n_theta)]
    phis = [360.0 * j / (grid_n_phi - 1) for j in range(grid_n_phi)]
    grid = []
    peak_val = 0.0
    for th in thetas:
        row = []
        for ph in phis:
            val, _ = gain_dbr_at(th, ph)
            if val > peak_val:
                peak_val = val
            row.append(val)
        grid.append(row)
    # 归一化 dBr
    grid_dbr = [[_db(v / peak_val if peak_val > 0 else 0) for v in row] for row in grid]

    # ---- cut（以波束指向为中心 ±cut_span；扫描后主瓣仍在窗内，同时检查栅瓣）----
    cut_thetas = [(scan_theta - cut_span + 2 * cut_span * i / (cut_n - 1))
                  for i in range(cut_n)]
    cut_vals = []
    cut_peak = 0.0
    for th in cut_thetas:
        val, _ = gain_dbr_at(th, cut_phi)
        if val > cut_peak:
            cut_peak = val
        cut_vals.append(val)
    cut_dbr = [_db(v / cut_peak if cut_peak > 0 else 0) for v in cut_vals]

    # ---- wide cut（签名 θ −90..+90：负 θ 代表 φ+180 反侧，GRASP 惯例，
    #      栅瓣通常出现在主瓣远侧，必须宽窗才能看到）----
    wide_n = cut_n
    wide_thetas = [(-90.0 + 180.0 * i / (wide_n - 1)) for i in range(wide_n)]
    wide_vals = []
    for th in wide_thetas:
        val, _ = gain_dbr_at(th, cut_phi)
        wide_vals.append(val)
    wide_dbr = [_db(v / peak_val if peak_val > 0 else 0) for v in wide_vals]

    # ---- θ3dB（从 grid 主轴估计：沿 cut 找主瓣 -3dB 全宽）----
    th3 = _beamwidth_from_cut(cut_thetas, cut_dbr, 3.0, scan_theta)
    # ---- 首旁瓣（cut 内主瓣外最高瓣）----
    fsl = _first_sidelobe(cut_thetas, cut_dbr, scan_theta, th3)

    # ---- 栅瓣：解析 + 数值 + 是否在 cut 窗内 ----
    gl_analytic = grating_lobes_analytic(nx, ny, d_lam, scan_theta, scan_phi, theta_max)
    gl_numeric = grating_lobes_numeric(thetas, phis, grid_dbr, scan_theta, scan_phi,
                                       exclude_deg=max(th3 * 1.5, 6.0), level_db=-13.0)
    gl_in_cut = [g for g in gl_analytic
                 if _gl_in_window(g, scan_theta, cut_span, cut_phi)]
    gl_in_wide = [g for g in gl_analytic
                  if _gl_signed_theta(g, cut_phi) is not None]

    return dict(ok=True, antenna_type="phased_array", freq_ghz=freq_ghz, lam_m=lam,
                nx=nx, ny=ny, n_el=nx * ny, d_lam=d_lam, d_mm=round(d_lam * lam * 1000, 3),
                scan_theta_deg=scan_theta, scan_phi_deg=scan_phi,
                peak_gain_dbi=round(g0, 2), beamwidth_3db_deg=round(th3, 4),
                first_sidelobe_dbr=round(fsl, 2),
                taper=taper, el_q=el_q, _gain_arr=_gain_arr,
                grid=dict(theta=[round(t, 3) for t in thetas],
                          phi=[round(p, 3) for p in phis],
                          gain_dbr=[[round(v, 2) for v in row] for row in grid_dbr]),
                cut=dict(theta=[round(t, 4) for t in cut_thetas], gain_dbr=[round(v, 3) for v in cut_dbr],
                         phi_deg=cut_phi, span=cut_span, center=scan_theta),
                cut_wide=dict(theta=[round(t, 3) for t in wide_thetas],
                              gain_dbr=[round(v, 3) for v in wide_dbr], phi_deg=cut_phi),
                grating_lobes=gl_analytic, grating_lobes_numeric=gl_numeric,
                grating_in_cut=gl_in_cut, grating_in_wide=gl_in_wide,
                has_grating=bool(gl_analytic),
                note=_array_note(nx, ny, d_lam, scan_theta, gl_analytic, gl_in_cut, cut_span))


def _gl_signed_theta(gl, cut_phi):
    """栅瓣在 cut 平面（φ=cut_phi）内的签名 θ：GL 方位与 cut 平面同侧→+θ，反侧→−θ；
    偏离 cut 平面 >5° → None（不在此剖面内）。"""
    dphi = (gl["phi_deg"] - cut_phi) % 360.0
    if dphi <= 5.0:
        return gl["theta_deg"]
    if abs(dphi - 180.0) <= 5.0:
        return -gl["theta_deg"]
    return None


def _gl_in_window(gl, center, span, cut_phi):
    st = _gl_signed_theta(gl, cut_phi)
    return st is not None and abs(st - center) <= span + 1e-6


def _array_note(nx, ny, d_lam, scan_theta, gl, gl_in_cut, cut_span):
    lam_ratio = 1.0 / d_lam if d_lam > 0 else 0
    onset = math.degrees(math.asin(max(min(lam_ratio - 1.0, 1.0), -1.0))) if lam_ratio - 1.0 <= 1.0 else None
    if not gl:
        return (f"{nx}×{ny} 阵（d={d_lam}λ），扫描 {scan_theta:.1f}°：可见区无栅瓣。"
                f"λ/d={lam_ratio:.2f}，栅瓣 onset≈{('%.1f°' % onset) if onset is not None else '不可见'}。")
    s = (f"{nx}×{ny} 阵（d={d_lam}λ），扫描 {scan_theta:.1f}°：检出 {len(gl)} 个栅瓣"
         f"（θ={', '.join('%.1f°' % g['theta_deg'] for g in gl[:4])}）。")
    if gl_in_cut:
        s += f" ⚠ 其中 {len(gl_in_cut)} 个落在 ±{cut_span:.0f}° cut 内，会污染覆盖区——需减小阵元间距或限制扫描角。"
    else:
        s += f" 栅瓣均在 ±{cut_span:.0f}° cut 外，覆盖区未受污染。"
    return s


def grating_lobes_analytic(nx, ny, d_lam, scan_theta, scan_phi, theta_max=90.0):
    """解析栅瓣：解 sinθcosφ=u0+n_xλ/dx、sinθsinφ=v0+n_yλ/dy 在可见区(u²+v²≤1)的实根。
    返回 [{order:(nx,ny), theta_deg, phi_deg, u, v}]。"""
    u0 = math.sin(scan_theta * DEG) * math.cos(scan_phi * DEG)
    v0 = math.sin(scan_theta * DEG) * math.sin(scan_phi * DEG)
    step = 1.0 / d_lam if d_lam > 0 else 0.0       # λ/d
    out = []
    nmax = int(math.ceil(2.0 / max(d_lam, 1e-6))) + 1
    for ix in range(-nmax, nmax + 1):
        for iy in range(-nmax, nmax + 1):
            if ix == 0 and iy == 0:
                continue
            u = u0 + ix * step
            v = v0 + iy * step
            r2 = u * u + v * v
            if r2 > 1.0 + 1e-9:                      # 不可见（隐失）
                continue
            theta = math.degrees(math.asin(min(math.sqrt(r2), 1.0)))
            if theta > theta_max + 1e-6:
                continue
            phi = math.degrees(math.atan2(v, u)) % 360.0
            # 排除主瓣本身（θ 接近 scan_theta 且 φ 接近 scan_phi）
            if _ang_sep(theta, phi, scan_theta, scan_phi) < 2.0:
                continue
            out.append(dict(order=(ix, iy), theta_deg=round(theta, 3),
                            phi_deg=round(phi, 3), u=round(u, 4), v=round(v, 4)))
    out.sort(key=lambda g: g["theta_deg"])
    return out


def grating_lobes_numeric(thetas, phis, grid_dbr, scan_theta, scan_phi,
                          exclude_deg=6.0, level_db=-13.0):
    """数值栅瓣：在 grid 上找局部极大（高于 level_db）且离主瓣 > exclude_deg 的瓣。"""
    out = []
    nt, np_ = len(thetas), len(phis)
    for i in range(1, nt - 1):
        for j in range(np_):
            jm = (j - 1) % np_
            jp = (j + 1) % np_
            v = grid_dbr[i][j]
            if v < level_db:
                continue
            # θ 方向局部极大
            if not (v >= grid_dbr[i - 1][j] and v >= grid_dbr[i + 1][j]):
                continue
            # φ 方向局部极大
            if not (v >= grid_dbr[i][jm] and v >= grid_dbr[i][jp]):
                continue
            sep = _ang_sep(thetas[i], phis[j], scan_theta, scan_phi)
            if sep < exclude_deg:
                continue
            out.append(dict(theta_deg=round(thetas[i], 2), phi_deg=round(phis[j], 2),
                            level_dbr=round(v, 2), sep_deg=round(sep, 2)))
    out.sort(key=lambda g: -g["level_dbr"])
    return out[:12]


def _ang_sep(t1, p1, t2, p2):
    """两方向 (θ,φ) 的球面角距（度）。"""
    a1, a2 = t1 * DEG, t2 * DEG
    dphi = (p1 - p2) * DEG
    c = math.cos(a1) * math.cos(a2) + math.sin(a1) * math.sin(a2) * math.cos(dphi)
    return math.degrees(math.acos(max(min(c, 1.0), -1.0)))


def _beamwidth_from_cut(thetas, dbr, level, center_hint=0.0):
    """从 cut 找主瓣 -level dB 全宽。主瓣取最接近 center_hint 的峰。"""
    if not dbr:
        return 0.0
    # 找主瓣峰（离 center_hint 最近的最大值）
    ipk = max(range(len(dbr)), key=lambda i: (dbr[i], -abs(thetas[i] - center_hint)))
    # 更稳妥：先取全局最大，再在附近找
    gmax = max(range(len(dbr)), key=lambda i: dbr[i])
    if abs(thetas[gmax] - center_hint) < abs(thetas[ipk] - center_hint) + 1e-9:
        ipk = gmax
    li = ipk
    while li > 0 and dbr[li] > -level:
        li -= 1
    ri = ipk
    while ri < len(dbr) - 1 and dbr[ri] > -level:
        ri += 1

    def cross(i0, i1):
        y0, y1 = dbr[i0], dbr[i1]
        x0, x1 = thetas[i0], thetas[i1]
        if y1 == y0:
            return x1
        return x0 + (-level - y0) * (x1 - x0) / (y1 - y0)
    left = cross(li, li + 1) if li < ipk else thetas[li]
    right = cross(ri - 1, ri) if ri > ipk else thetas[ri]
    return abs(right - left)


def _first_sidelobe(thetas, dbr, center_hint, th3):
    """cut 内首旁瓣电平（dBr）：从主瓣峰沿两侧下行到第一个局部极小（零深）后，
    取窗内剩余部分的最大值。比固定倍率阈值稳健（波束 0.27°~7° 均适用）。"""
    if not dbr:
        return -120.0
    ipk = max(range(len(dbr)), key=lambda i: dbr[i])
    best = -120.0
    # 向右：先找第一个局部极小，再取其后的峰
    for direction in (1, -1):
        i = ipk
        n = len(dbr)
        # 下行段
        while 0 <= i + direction < n and dbr[i + direction] <= dbr[i]:
            i += direction
        # 若已到窗边 → 无旁瓣（此侧）
        if not (0 <= i + direction < n):
            continue
        # 此后取全窗剩余最大值
        seg = dbr[i + direction:] if direction > 0 else dbr[:i + 1]
        if seg:
            best = max(best, max(seg))
    return best


# ================================================================
# B) 反射面：圆口径 Hankel 变换（次级方向图，含次瓣）
# ================================================================
def _hankel_table(D, freq_ghz, illum, n_u=481):
    """预计算 E(u) 查表（u=sinθ'∈[0,1]，旋转对称只需一维）。
    Simpson 积分点数按 ka 自适应：每 J0 振荡周期 ≥16 点（欠采样会混叠出假深旁瓣——
    2.5m@20GHz 时 ka≈524，n_rad 必须 ≥ ~4200 才能解析 u→1 的振荡）。"""
    lam = lam_m(freq_ghz)
    k = 2.0 * math.pi / lam
    a = D / 2.0
    ka = k * a
    # 每周期 16 点：周期数 = ka·u_max/(2π)；u_max=1
    n_rad = max(401, int(math.ceil(ka / (2.0 * math.pi) * 16.0)) + 1)
    if n_rad % 2 == 0:
        n_rad += 1
    n_rad = min(n_rad, 20001)                          # 上限保护（超大口径降密度）
    rhos = [a * i / (n_rad - 1) for i in range(n_rad)]
    tvals = [illum(r / a) for r in rhos]
    h = rhos[1] - rhos[0]
    us = [i / (n_u - 1) for i in range(n_u)]
    es = []
    for u in us:
        s = 0.0
        ku = k * u
        for i in range(n_rad):
            rho = rhos[i]
            wgt = 1.0 if i in (0, n_rad - 1) else (4.0 if i % 2 == 1 else 2.0)
            s += wgt * tvals[i] * _j0(ku * rho) * rho
        es.append(s * h / 3.0)
    return us, es, n_rad


def _interp_table(us, es, u):
    """查表线性插值（u∈[0,1]；>1 返回 0）。"""
    if u <= 0.0:
        return es[0]
    if u >= 1.0:
        return 0.0
    x = u * (len(us) - 1)
    i = int(x)
    if i >= len(us) - 1:
        return es[-1]
    w = x - i
    return es[i] * (1.0 - w) + es[i + 1] * w


def reflector_pattern(D, freq_ghz, eta=DEFAULT_ETA, edge_db=-12.0, taper_kind="cosine",
                      taper_p=1.0, scan_theta=0.0, scan_phi=0.0, n_u=481,
                      grid_n_theta=91, grid_n_phi=73, cut_span=15.0, cut_n=301,
                      cut_phi=0.0, theta_max=90.0, peak_gain_dbi=None):
    """偏馈/正馈反射面次级方向图：圆口径场 Hankel 变换 E(u)=∫₀ᵃt(ρ)J₀(kρu)ρdρ。
    方向图关于波束指向（扫描轴）旋转对称 → 预计算 E(u) 一维查表，grid/cut 通过
    离扫描轴角 θ'=ang_sep(θφ, θ0φ0) 查 u=sinθ'。连续口径无栅瓣。
    θ'>90°（后向）按前向 90° 电平 − 后瓣抑制（-30dB）处理（覆盖分析只用前向）。"""
    lam = lam_m(freq_ghz)
    g0 = peak_gain_dbi if peak_gain_dbi is not None else peak_gain_dbi_fn(D, freq_ghz, eta)

    ped = 10.0 ** (edge_db / 20.0)

    def illum(rho_norm):
        if taper_kind == "uniform":
            return 1.0
        if taper_kind == "gaussian":
            c = -edge_db * math.log(10.0) / 20.0
            return math.exp(-c * rho_norm * rho_norm)
        return ped + (1.0 - ped) * max(math.cos(math.pi / 2.0 * rho_norm), 0.0) ** taper_p

    us, es, n_rad = _hankel_table(D, freq_ghz, illum, n_u)
    peak_e = max(abs(v) for v in es) or 1.0

    def gain_rel_at(theta_deg, phi_deg):
        """离扫描轴角 θ' → u=sinθ' → |E|²（归一化功率）。"""
        sep = _ang_sep(theta_deg, phi_deg, scan_theta, scan_phi)
        if sep <= 90.0:
            e = _interp_table(us, es, math.sin(sep * DEG))
            return (e / peak_e) ** 2
        return (es[-1] / peak_e) ** 2 * 1e-3             # 后向：90°电平再压 30dB

    # 精确查询闭包（coverage_engine 逐地面点投影用，不经 grid 插值）。
    # 入参 = 单位方向在**天线体坐标系**的分量 (a=北参考, b=东参考, c=boresight/z)。
    # 方向图关于扫描轴旋转对称 → 离扫描轴角 sep 决定 u=sin(sep)。
    _st, _sp = scan_theta * DEG, scan_phi * DEG
    _scan_vec = (math.sin(_st) * math.cos(_sp), math.sin(_st) * math.sin(_sp), math.cos(_st))

    def _gain_arr(a, b, c):
        sep_cos = max(min(a * _scan_vec[0] + b * _scan_vec[1] + c * _scan_vec[2], 1.0), -1.0)
        if sep_cos < 0.0:                                # 后向
            return (es[-1] / peak_e) ** 2 * 1e-3
        u = math.sin(math.acos(sep_cos))                 # =sqrt(1−sep_cos²)
        e = _interp_table(us, es, u)
        return (e / peak_e) ** 2

    # grid（θ×φ 全空间，供 .grd 导出与数值检查）
    thetas = [theta_max * i / (grid_n_theta - 1) for i in range(grid_n_theta)]
    phis = [360.0 * j / (grid_n_phi - 1) for j in range(grid_n_phi)]
    peak_val = 0.0
    grid = []
    for th in thetas:
        row = []
        for ph in phis:
            v = gain_rel_at(th, ph)
            if v > peak_val:
                peak_val = v
            row.append(v)
        grid.append(row)
    grid_dbr = [[_db(v / peak_val if peak_val > 0 else 0) for v in row] for row in grid]

    # cut（以波束指向为中心 ±cut_span；宽 cut 签名 −90..+90 看全空域次瓣）
    cut_thetas = [(scan_theta - cut_span + 2 * cut_span * i / (cut_n - 1)) for i in range(cut_n)]
    cut_vals = [gain_rel_at(th, cut_phi) for th in cut_thetas]
    cut_peak = max(cut_vals) if cut_vals else 1.0
    cut_dbr = [_db(v / cut_peak if cut_peak > 0 else 0) for v in cut_vals]
    wide_thetas = [(-90.0 + 180.0 * i / (cut_n - 1)) for i in range(cut_n)]
    wide_vals = [gain_rel_at(th, cut_phi) for th in wide_thetas]
    wide_dbr = [_db(v / peak_val if peak_val > 0 else 0) for v in wide_vals]
    th3 = _beamwidth_from_cut(cut_thetas, cut_dbr, 3.0, scan_theta)
    fsl = _first_sidelobe(cut_thetas, cut_dbr, scan_theta, th3)

    return dict(ok=True, antenna_type="reflector", freq_ghz=freq_ghz, lam_m=lam,
                D_m=D, eta=eta, scan_theta_deg=scan_theta, scan_phi_deg=scan_phi,
                peak_gain_dbi=round(g0, 2), beamwidth_3db_deg=round(th3, 4),
                first_sidelobe_dbr=round(fsl, 2), taper=taper_kind, edge_db=edge_db,
                _gain_arr=_gain_arr,
                grid=dict(theta=[round(t, 3) for t in thetas],
                          phi=[round(p, 3) for p in phis],
                          gain_dbr=[[round(v, 2) for v in row] for row in grid_dbr]),
                cut=dict(theta=[round(t, 4) for t in cut_thetas], gain_dbr=[round(v, 3) for v in cut_dbr],
                         phi_deg=cut_phi, span=cut_span, center=scan_theta),
                cut_wide=dict(theta=[round(t, 3) for t in wide_thetas],
                              gain_dbr=[round(v, 3) for v in wide_dbr], phi_deg=cut_phi),
                grating_lobes=[], grating_lobes_numeric=[], grating_in_cut=[], grating_in_wide=[],
                has_grating=False,
                note=(f"反射面 D={D}m @ {freq_ghz}GHz（η={eta}），口径 Hankel 变换次级方向图"
                      f"（积分 {n_rad} 点/ka 自适应），扫描 {scan_theta:.1f}°。"
                      f"连续口径无栅瓣；首旁瓣 {fsl:.1f}dBr，θ3dB={th3:.3f}°。"))


def _j0(x):
    """Bessel J0（Abramowitz-Stegun 9.4.1/9.4.4，无第三方依赖）。"""
    ax = abs(x)
    if ax < 3.0:
        y = x * x
        ans1 = 57568490574.0 + y * (-13362590354.0 + y * (651619640.7
              + y * (-11214424.18 + y * (77392.33017 + y * (-184.9052456)))))
        ans2 = 57568490411.0 + y * (1029532985.0 + y * (9494680.718
              + y * (59272.64853 + y * (267.8532712 + y * 1.0))))
        return ans1 / ans2
    else:
        z = 3.0 / ax
        y = z * z
        xx = ax - 0.785398164
        ans1 = 1.0 + y * (-0.1098628627e-2 + y * (0.2734510407e-4
              + y * (-0.2073370639e-5 + y * 0.2093887211e-6)))
        ans2 = -0.1562499995e-1 + y * (0.1430488765e-3
              + y * (-0.6911147651e-5 + y * (0.7621095161e-6 - y * 0.934935152e-7)))
        return math.sqrt(0.636619772 / ax) * (math.cos(xx) * ans1 - z * math.sin(xx))


def peak_gain_dbi_fn(D, freq_ghz, eta=DEFAULT_ETA):
    return peak_gain_dbi(D, freq_ghz, eta)


# ================================================================
# 高层调度：按配置/天线类型出方向图
# ================================================================
def compute_pattern(antenna_type="phased_array", freq_ghz=20.0, D=None, nx=None, ny=None,
                    n_el=None, d_lam=0.5, scan_theta=0.0, scan_phi=0.0, **kw):
    """统一入口。antenna_type: phased_array | reflector。
    相控阵：给 nx,ny,d_lam（或 n_el→nx=ny=√n_el）；反射面：给 D。
    其余 kw 透传（taper/edge_db/grid_n_*/cut_span/cut_n/cut_phi/theta_max/peak_gain_dbi）。"""
    if antenna_type in ("phased_array", "array", "相控阵", "AESA"):
        if nx is None or ny is None:
            n = int(n_el or 1024)
            side = max(int(round(math.sqrt(n))), 2)
            nx = ny = side
        return phased_array_pattern(freq_ghz, nx, ny, d_lam=d_lam,
                                    scan_theta=scan_theta, scan_phi=scan_phi, **kw)
    else:
        D = float(D or 2.5)
        return reflector_pattern(D, freq_ghz, scan_theta=scan_theta, scan_phi=scan_phi, **kw)


# ================================================================
# 导出：GRASP .grd 球面网格 + 通用三列 ASCII
# ================================================================
def export_grd(pat, path, component="co"):
    """导出 GRASP 风格球面网格 .grd（ASCII）。
    结构（与 grasp_bridge.parse_cut 同族，扩展到 n_phi>1）：
      行1  标题
      行2  全局头 7 字段：theta_start theta_step n_theta  phi_start n_phi  freq_idx comp
      行3  phi_step
      其后 n_theta×n_phi 行，每行 4 字段：E_co_re E_co_im E_x_re E_x_im
    幅度由 dBr 反推（峰值=1），相位置 0（远场功率方向图导出，覆盖分析只需幅度）。"""
    g = pat["grid"]
    thetas, phis, gdbr = g["theta"], g["phi"], g["gain_dbr"]
    nt, np_ = len(thetas), len(phis)
    t_start = thetas[0]
    t_step = (thetas[1] - thetas[0]) if nt > 1 else 0.0
    p_start = phis[0]
    p_step = (phis[1] - phis[0]) if np_ > 1 else 0.0
    lines = ["Field data in grid (PayloadDesign pattern_engine)"]
    lines.append("%g %g %d %g %d %d %s" % (t_start, t_step, nt, p_start, np_, 0, component))
    lines.append("%g" % p_step)
    for i in range(nt):
        for j in range(np_):
            amp = 10.0 ** (gdbr[i][j] / 20.0)        # dBr → 线性幅度（峰值=1）
            lines.append("%.8e %.8e %.8e %.8e" % (amp, 0.0, 0.0, 0.0))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, n_theta=nt, n_phi=np_, format="grasp_grd_ascii")


def export_ascii_pattern(pat, path, with_phi=True):
    """通用三列 ASCII：theta_deg  phi_deg  gain_dBi（绝对增益）。
    任何覆盖分析工具（SATSOFT/自研）均可直接导入。"""
    g = pat["grid"]
    thetas, phis, gdbr = g["theta"], g["phi"], g["gain_dbr"]
    g0 = pat.get("peak_gain_dbi", 0.0)
    lines = ["# theta_deg  phi_deg  gain_dBi  (peak=%.3f dBi, %s)"
             % (g0, pat.get("antenna_type", ""))]
    for i, th in enumerate(thetas):
        for j, ph in enumerate(phis):
            lines.append("%.4f %.4f %.4f" % (th, ph, gdbr[i][j] + g0))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, rows=len(thetas) * len(phis), format="ascii_theta_phi_gain")


def export_cut(pat, path, which="main"):
    """导出 cut（theta_deg, gain_dBr）两列 ASCII。"""
    c = pat["cut"]
    lines = ["# cut phi=%.2f deg span=+/-%.2f  theta_deg gain_dBr" % (c.get("phi_deg", 0), c.get("span", 15))]
    for t, v in zip(c["theta"], c["gain_dbr"]):
        lines.append("%.4f %.4f" % (t, v))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, rows=len(c["theta"]))


# ================================================================
# 自检
# ================================================================
if __name__ == "__main__":
    print("=== pattern_engine self-test ===")
    # 1) 相控阵 boresight（d=0.5λ，无栅瓣）
    p1 = phased_array_pattern(20.0, 16, 16, d_lam=0.5, scan_theta=0.0,
                              grid_n_theta=61, grid_n_phi=49, cut_n=201)
    print("[boresight d=0.5λ] G0=%.1fdBi th3=%.3f° FSL=%.1fdBr grating=%d"
          % (p1["peak_gain_dbi"], p1["beamwidth_3db_deg"], p1["first_sidelobe_dbr"],
             len(p1["grating_lobes"])))
    assert not p1["has_grating"], "d=0.5λ boresight 不应有栅瓣"

    # 2) 相控阵扫描 30°（d=0.7λ → onset=25.4°，扫描 30° 应有可见栅瓣；
    #    注意 scan20° 时栅瓣尚未进入可见区——onset 判据本身就是设计约束）
    p2 = phased_array_pattern(20.0, 16, 16, d_lam=0.7, scan_theta=30.0,
                              grid_n_theta=91, grid_n_phi=73, cut_n=301, cut_span=15.0)
    print("[scan30 d=0.7λ] G0=%.1fdBi th3=%.3f° grating=%d in_cut=%d"
          % (p2["peak_gain_dbi"], p2["beamwidth_3db_deg"], len(p2["grating_lobes"]),
             len(p2["grating_in_cut"])))
    print("   analytic GL:", [(g["order"], g["theta_deg"], g["phi_deg"]) for g in p2["grating_lobes"][:5]])
    print("   numeric  GL:", [(g["theta_deg"], g["phi_deg"], g["level_dbr"]) for g in p2["grating_lobes_numeric"][:5]])
    assert p2["has_grating"], "d=0.7λ scan30° 应有栅瓣（onset 25.4°）"
    assert not p2["grating_in_cut"], "栅瓣在 ±15° cut 外（远离主瓣），不应误报在窗内"
    # 宽 cut（签名 −90..+90）应包含栅瓣方向
    assert len(p2["cut_wide"]["theta"]) == 301

    # 3) 反射面次级方向图（含次瓣；2.5m@20GHz → θ3dB≈0.27°，首旁瓣≈-23dBr 量级）
    p3 = reflector_pattern(2.5, 20.0, eta=0.65, edge_db=-12.0, scan_theta=0.0,
                           grid_n_theta=91, grid_n_phi=73, cut_n=601)
    print("[reflector D=2.5m] G0=%.1fdBi th3=%.3f° FSL=%.1fdBr grating=%d"
          % (p3["peak_gain_dbi"], p3["beamwidth_3db_deg"], p3["first_sidelobe_dbr"],
             len(p3["grating_lobes"])))
    assert not p3["has_grating"], "反射面不应有栅瓣"
    assert -30.0 < p3["first_sidelobe_dbr"] < -10.0, \
        "反射面首旁瓣应在 -30~-10dBr（cosine-on-pedestal 典型 -23dBr），实得 %.1f" % p3["first_sidelobe_dbr"]
    # θ3dB 与经典近似 70λ/D（度）一致性（±25% 容差；λ、D 同单位）
    th3_approx = 70.0 * lam_m(20.0) / 2.5
    assert abs(p3["beamwidth_3db_deg"] - th3_approx) / th3_approx < 0.25, \
        "θ3dB=%.3f° 偏离 70λ/D=%.3f° 超 25%%" % (p3["beamwidth_3db_deg"], th3_approx)
    # 扫描 6°：主瓣应移到 6°
    p3s = reflector_pattern(2.5, 20.0, scan_theta=6.0, grid_n_theta=46, grid_n_phi=37, cut_n=301)
    ipk = max(range(len(p3s["cut"]["gain_dbr"])), key=lambda i: p3s["cut"]["gain_dbr"][i])
    assert abs(p3s["cut"]["theta"][ipk] - 6.0) < 0.3, "扫描后主瓣应在 6°"

    # 4) 导出
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out, exist_ok=True)
    g = export_grd(p2, os.path.join(out, "_pattern_test.grd"))
    a = export_ascii_pattern(p2, os.path.join(out, "_pattern_test.pat"))
    c = export_cut(p2, os.path.join(out, "_pattern_test.cut"))
    print("export grd:", g)
    print("export pat:", a)
    print("export cut:", c)
    print("=== ALL PASS ===")
