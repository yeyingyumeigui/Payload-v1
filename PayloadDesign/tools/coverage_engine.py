# -*- coding: utf-8 -*-
"""地面覆盖区引擎（纯 Python 第一性原理，零第三方依赖，冻结 exe 可用）。

等效 SATSOFT 的覆盖分析：把 pattern_engine 的天线方向图（grid/cut，次级方向图）
投影到地面 —— 卫星位置 + 波束指向 + 方向图增益 → 地面 EIRP 分布图与等值线。

物理链路（每个地面格点）：
  1. 卫星 ECEF 位置 P_sat（星下点 lat_s, lon_s, 高度 h）
  2. 波束轴单位矢量 b：星下点指向（nadir）或指向目标点（扫描波束）
  3. 格点方向矢量 v = normalize(P_g − P_sat)；离轴角 θ_off = acos(b·v)；
     波束系方位 φ_b（由波束框架正交基投影）
  4. 方向图插值 G(θ_off, φ_b)（dBr，功率口径）→ G_dBi = G_peak + dBr
  5. 斜距 d = |P_g − P_sat|；EIRP = EIRP_peak + dBr（自由空间损耗在链路预算里算，
     覆盖图惯例只画 EIRP；GEO 覆盖区内斜距变化 <0.5dB 可并入峰值口径）
  6. 地平线判据：格点对卫星仰角 el > 0 才可见（球面地球遮挡）

产出：
  · eirp 网格（lat×lon dBW）+ 指定电平等值线（marching squares，线段集）
  · 覆盖度量：−3dB/指定电平足迹直径、覆盖面积、边缘电平
  · SVG 前端可直接绘制（等值线段 + 网格热图数据）
  · CSV 导出（SATSOFT 交叉核对用）：格点表 + 等值线表

与 .grd 导出的关系：pattern_engine.export_grd 产 GRASP 标准网格文件（可带进
GRASP/SATSOFT 商业软件复核）；本引擎是同物理口径的内置计算，两者同源可比对。
"""
from __future__ import annotations

import math

R_EARTH_KM = 6371.0
DEG = math.pi / 180.0


# ================================================================
# 几何基元（ECEF，单位 km；纬度 lat、经度 lon 单位度）
# ================================================================
def ecef(lat_deg, lon_deg, r_km):
    la, lo = lat_deg * DEG, lon_deg * DEG
    return (r_km * math.cos(la) * math.cos(lo),
            r_km * math.cos(la) * math.sin(lo),
            r_km * math.sin(la))


def sat_position(lat_sub, lon_sub, h_km):
    return ecef(lat_sub, lon_sub, R_EARTH_KM + h_km)


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 0 else (0.0, 0.0, 1.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def beam_axis(lat_sub, lon_sub, h_km, target_lat=None, target_lon=None):
    """波束轴单位矢量：给了目标点 → 指向目标（扫描波束）；否则指向星下点（nadir）。
    同时返回扫描角（离 nadir 的偏角，度）——与 pattern_engine scan_theta 同口径。"""
    p_sat = sat_position(lat_sub, lon_sub, h_km)
    p_nad = ecef(lat_sub, lon_sub, R_EARTH_KM)
    nadir = _norm(_sub(p_nad, p_sat))
    if target_lat is None or target_lon is None:
        return nadir, p_sat, 0.0
    p_tgt = ecef(target_lat, target_lon, R_EARTH_KM)
    axis = _norm(_sub(p_tgt, p_sat))
    scan = math.degrees(math.acos(max(min(_dot(axis, nadir), 1.0), -1.0)))
    return axis, p_sat, scan


def _beam_frame(axis, lat_sub, lon_sub):
    """波束系正交基 (x', y', z'=axis)：x' 取 axis 与当地「北」方向的投影分量
    （nadir 波束时退化为北/东系），保证 φ_b 与天线系方位角定义连续。"""
    up = _norm(ecef(lat_sub, lon_sub, 1.0))
    # 真北 = Z 轴减去其在 up 上的投影（当地水平面内指北）
    z_ax = (0.0, 0.0, 1.0)
    north = _sub(z_ax, (up[0] * _dot(z_ax, up), up[1] * _dot(z_ax, up), up[2] * _dot(z_ax, up)))
    nn = math.sqrt(_dot(north, north))
    if nn < 1e-9:                        # 极区星下点：北方向退化 → 用格林尼治方向
        gx = ecef(lat_sub, 0.0, 1.0)
        north = _sub(gx, (up[0] * _dot(gx, up), up[1] * _dot(gx, up), up[2] * _dot(gx, up)))
        nn = math.sqrt(_dot(north, north)) or 1.0
    north = (north[0] / nn, north[1] / nn, north[2] / nn)
    x_p = _norm(_sub(north, (axis[0] * _dot(axis, north),
                             axis[1] * _dot(axis, north),
                             axis[2] * _dot(axis, north))))
    y_p = _cross(axis, x_p)
    return x_p, y_p


def elevation_deg(p_sat, lat_g, lon_g):
    """地面点对卫星的仰角（度）：cos 判据 el = acos( ... ) − 90° 等价式。"""
    p_g = ecef(lat_g, lon_g, R_EARTH_KM)
    up = _norm(p_g)
    look = _norm(_sub(p_sat, p_g))
    zen = math.degrees(math.acos(max(min(_dot(up, look), 1.0), -1.0)))
    return 90.0 - zen


# ================================================================
# 方向图 → 增益查询（θ_off, φ_b）双线性插值（功率口径 dBr）
# ================================================================
def _grid_lookup(pat, theta_deg, phi_deg):
    """在 pat["grid"]（theta×phi 增益 dBr，功率口径）上双线性插值。
    θ 越界钳制到 [theta[0], theta[-1]]；φ 环绕。反射面方向图旋转对称，
    φ 插值自然退化为常数；相控阵 grid 含真实 φ 依赖。"""
    g = pat["grid"]
    ths, phs, vals = g["theta"], g["phi"], g["gain_dbr"]
    nt, np_ = len(ths), len(phs)
    if nt < 2 or np_ < 2:
        return -120.0
    t = max(min(theta_deg, ths[-1]), ths[0])
    # θ 二分
    lo, hi = 0, nt - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ths[mid] <= t:
            lo = mid
        else:
            hi = mid
    wt = (t - ths[lo]) / (ths[hi] - ths[lo]) if ths[hi] > ths[lo] else 0.0
    p = phi_deg % 360.0
    dphi = phs[1] - phs[0]
    j0 = int(p / dphi) % np_
    j1 = (j0 + 1) % np_
    wp = (p - phs[j0]) / dphi if dphi > 0 else 0.0
    if wp < 0:
        wp += 1.0
    v00, v01 = vals[lo][j0], vals[lo][j1]
    v10, v11 = vals[hi][j0], vals[hi][j1]
    return (v00 * (1 - wt) + v10 * wt) * (1 - wp) + (v01 * (1 - wt) + v11 * wt) * wp


def gain_dbr_at_offaxis(pat, theta_off_deg, phi_beam_deg):
    """离轴角/波束系方位 → 方向图 dBr（相对峰值功率增益）。
    θ_off>grid 上限（后向）按最后一行电平 −30dB 截止（覆盖分析只用前向）。"""
    ths = pat["grid"]["theta"]
    if theta_off_deg > ths[-1]:
        return _grid_lookup(pat, ths[-1], phi_beam_deg) - 30.0
    return _grid_lookup(pat, theta_off_deg, phi_beam_deg)


# ================================================================
# EIRP 覆盖网格
# ================================================================
def pointing_angles(sat_lat, sat_lon, h_km, target_lat, target_lon):
    """从星下点 (sat_lat,sat_lon,h) 指向目标 (target_lat,lon) 所需的**波束扫描角**
    (scan_theta, scan_phi)（度），定义在天线体系：z=nadir、x=北、y=东，
    scan_theta=离 nadir 偏角、scan_phi=方位（北起算，东为 90°）。
    → 前端据此 build pattern_engine.reflector_pattern/phased_array_pattern(scan_theta,scan_phi)，
    再 coverage_map，波束峰值即精确落在 target。"""
    p_sat = sat_position(sat_lat, sat_lon, h_km)
    p_tgt = ecef(target_lat, target_lon, R_EARTH_KM)
    axis = _norm(_sub(p_tgt, p_sat))
    up = _norm(ecef(sat_lat, sat_lon, 1.0))
    z_ax = (-up[0], -up[1], -up[2])                       # nadir
    z_w = (0.0, 0.0, 1.0)
    pu = _dot(z_w, up)                                    # =up[2]=sin(lat)
    north = _sub(z_w, (up[0] * pu, up[1] * pu, up[2] * pu))
    nn = math.sqrt(_dot(north, north))
    if nn < 1e-9:
        gx0 = ecef(sat_lat, 0.0, 1.0)
        north = _sub(gx0, (up[0] * _dot(gx0, up), up[1] * _dot(gx0, up), up[2] * _dot(gx0, up)))
        nn = math.sqrt(_dot(north, north)) or 1.0
    x_ax = (north[0] / nn, north[1] / nn, north[2] / nn)
    y_ax = _cross(z_ax, x_ax)
    c0 = _dot(axis, z_ax)
    a0, b0 = _dot(axis, x_ax), _dot(axis, y_ax)
    th = math.degrees(math.acos(max(min(c0, 1.0), -1.0)))
    ph = math.degrees(math.atan2(b0, a0)) % 360.0
    return round(th, 4), round(ph, 4)


def _body_frame(sat_lat, sat_lon):
    """天线体系正交基 (x=北, y=东, z=nadir)（ECEF 单位矢量）。"""
    up = _norm(ecef(sat_lat, sat_lon, 1.0))
    z_ax = (-up[0], -up[1], -up[2])
    z_w = (0.0, 0.0, 1.0)
    pu = _dot(z_w, up)                                    # =up[2]=sin(lat)
    north = _sub(z_w, (up[0] * pu, up[1] * pu, up[2] * pu))
    nn = math.sqrt(_dot(north, north))
    if nn < 1e-9:
        gx0 = ecef(sat_lat, 0.0, 1.0)
        north = _sub(gx0, (up[0] * _dot(gx0, up), up[1] * _dot(gx0, up), up[2] * _dot(gx0, up)))
        nn = math.sqrt(_dot(north, north)) or 1.0
    x_ax = (north[0] / nn, north[1] / nn, north[2] / nn)
    return x_ax, _cross(z_ax, x_ax), z_ax


def coverage_map(pat, peak_eirp_dbw, h_km, sat_lat=0.0, sat_lon=0.0,
                 lat_span=None, lon_span=None, n_lat=121, n_lon=161,
                 el_min_deg=0.0):
    """方向图 → 地面 EIRP 覆盖网格（SATSOFT 等效内置计算）。

    波束指向**由 pat 自带的 scan_theta/scan_phi 决定**（在天线体系 z=nadir、x=北、
    y=东 下：scan_theta=离 nadir 偏角、scan_phi=北起方位）。要让波束落在某目标点，
    先用 pointing_angles() 算出 (θ0,φ0) → build pattern_engine(scan_theta=θ0,scan_phi=φ0)
    → 本函数峰值即精确落在目标（boresight pat → 波束在星下点）。

    pat            : pattern_engine 输出（含 _gain_arr 精确查询闭包；grid 为功率 dBr 后备）
    peak_eirp_dbw  : 波束峰值 EIRP（dBW；= P_out + G_peak − L_feed − L_tx）
    h_km           : 轨道高度；sat_lat/sat_lon : 星下点（GEO 定点 lat=0）
    lat_span/lon_span : 计算窗半宽（度；None → 由 θ3dB 足迹 + 扫描偏移自动估计）
    n_lat/n_lon    : 网格点数；el_min_deg : 可见性判据（默认地平线以上）

    增益用 pat["_gain_arr"](a,b,c) 精确查询（不经 grid 插值——grid θ 分辨率 1°/点
    对 0.4° 级窄波束不足以解析 −3dB 等值线；无闭包时回退 grid 双线性）。

    返回 dict：lat/lon 轴、eirp_dbw 网格（不可见=floor -200）、扫描角、
    波束中心、地面峰值位置等。
    """
    p_sat = sat_position(sat_lat, sat_lon, h_km)
    x_ax, y_ax, z_ax = _body_frame(sat_lat, sat_lon)
    gain_arr = pat.get("_gain_arr")
    g0_dbi = float(pat.get("peak_gain_dbi", 0.0))

    # 波束轴：pat 扫描方向 (θ0,φ0) 映射到 ECEF（体系 z=nadir、x=北、y=东）
    th0 = float(pat.get("scan_theta_deg", 0.0) or 0.0)
    ph0 = float(pat.get("scan_phi_deg", 0.0) or 0.0)
    st, ct = math.sin(th0 * DEG), math.cos(th0 * DEG)
    sp, cp = math.sin(ph0 * DEG), math.cos(ph0 * DEG)
    axis = (st * cp * x_ax[0] + st * sp * y_ax[0] + ct * z_ax[0],
            st * cp * x_ax[1] + st * sp * y_ax[1] + ct * z_ax[1],
            st * cp * x_ax[2] + st * sp * y_ax[2] + ct * z_ax[2])
    axis = _norm(axis)
    scan_deg = th0
    # 波束中心地面点（轴与球面交点；boresight 时即星下点）
    c_lat, c_lon = _axis_ground_point(p_sat, axis)

    # 窗半宽：由 θ3dB 地面足迹中心角估计。足迹半中心角 ψ=atan(h·tan(α)/R)
    # （α=θ3dB/2；GEO/LEO 通用——LEO 足迹远小于「(R+h)/R 线性外推」的错误估计）。
    if lat_span is None or lon_span is None:
        th3 = float(pat.get("beamwidth_3db_deg", 1.0) or 1.0)
        alpha = (th3 / 2.0) * DEG
        psi = math.degrees(math.atan(h_km * math.tan(alpha) / R_EARTH_KM))
        span = max(min(psi * 4.0 + scan_deg * 0.35, 90.0), 0.3)
        lat_span = lat_span if lat_span is not None else span
        lon_span = lon_span if lon_span is not None else span / max(math.cos(c_lat * DEG), 0.2)

    lats = [c_lat - lat_span + 2 * lat_span * i / (n_lat - 1) for i in range(n_lat)]
    lons = [c_lon - lon_span + 2 * lon_span * i / (n_lon - 1) for i in range(n_lon)]
    FLOOR = -200.0
    sin_elmin = math.sin(el_min_deg * DEG)     # up_g·(地面→卫星) = sin(el)
    eirp = []
    peak_val = FLOOR
    peak_ij = (0, 0)
    for i, la in enumerate(lats):
        row = []
        cla, sla = math.cos(la * DEG), math.sin(la * DEG)
        for j, lo in enumerate(lons):
            clo, slo = math.cos(lo * DEG), math.sin(lo * DEG)
            gx, gy, gz = R_EARTH_KM * cla * clo, R_EARTH_KM * cla * slo, R_EARTH_KM * sla
            rx, ry, rz = gx - p_sat[0], gy - p_sat[1], gz - p_sat[2]
            d2 = rx * rx + ry * ry + rz * rz
            d = math.sqrt(d2)
            # 可见性：仰角 ≥ el_min。r̂=星→地面，up_g·r̂ = −sin(el)
            # → el≥el_min ⟺ up_g·r̂ ≤ −sin(el_min)（球面遮挡）
            if (gx * rx + gy * ry + gz * rz) / (R_EARTH_KM * d) > -sin_elmin:
                row.append(FLOOR)
                continue
            # 体系分量 → 精确方向图查询（功率相对峰值）
            a = (rx * x_ax[0] + ry * x_ax[1] + rz * x_ax[2]) / d
            b = (rx * y_ax[0] + ry * y_ax[1] + rz * y_ax[2]) / d
            c = (rx * z_ax[0] + ry * z_ax[1] + rz * z_ax[2]) / d
            if gain_arr is not None:
                rel = gain_arr(a, b, c)
                dbr = 10.0 * math.log10(rel) if rel > 1e-12 else -120.0
            else:                                          # 回退：grid 插值（离波束轴角，旋转对称口径）
                cos_sep = a * st * cp + b * st * sp + c * ct
                th_off = math.degrees(math.acos(max(min(cos_sep, 1.0), -1.0)))
                dbr = gain_dbr_at_offaxis(pat, th_off, 0.0)
            val = peak_eirp_dbw + dbr
            row.append(round(val, 2))
            if val > peak_val:
                peak_val = val
                peak_ij = (i, j)
        eirp.append(row)

    return dict(ok=True, lat=[round(x, 4) for x in lats], lon=[round(x, 4) for x in lons],
                eirp_dbw=eirp, floor=FLOOR,
                sat=dict(lat=sat_lat, lon=sat_lon, h_km=h_km),
                beam_center=dict(lat=round(c_lat, 4), lon=round(c_lon, 4)),
                scan=dict(theta_deg=round(th0, 3), phi_deg=round(ph0, 3)),
                peak_ground=dict(lat=round(lats[peak_ij[0]], 4), lon=round(lons[peak_ij[1]], 4),
                                 eirp_dbw=round(peak_val, 2)),
                scan_deg=round(scan_deg, 3), peak_gain_dbi=g0_dbi,
                peak_eirp_dbw=peak_eirp_dbw, n_lat=n_lat, n_lon=n_lon,
                exact=bool(gain_arr is not None),
                note=("地面 EIRP 覆盖（内置 SATSOFT 等效，%s）：波束指向 (%.2f°N, %.2f°E)，"
                      "扫描角 %.2f°，地面峰值 EIRP %.1f dBW。"
                      % ("精确方向图查询" if gain_arr is not None else "grid 插值",
                         c_lat, c_lon, scan_deg, peak_val if peak_val > FLOOR else peak_eirp_dbw)))


def _axis_ground_point(p_sat, axis):
    """波束轴与地球球面交点 (lat, lon)：解析求射线-球交点。"""
    # |p_sat + t·axis| = R → t² + 2(axis·p_sat)t + |p_sat|²−R² = 0
    b = _dot(axis, p_sat)
    c = _dot(p_sat, p_sat) - R_EARTH_KM * R_EARTH_KM
    disc = b * b - c
    if disc < 0:                     # 轴不与地球相交（指向深空）→ 返回星下点
        la = math.degrees(math.asin(max(min(p_sat[2] / math.sqrt(_dot(p_sat, p_sat)), 1.0), -1.0)))
        return la, math.degrees(math.atan2(p_sat[1], p_sat[0]))
    t = -b - math.sqrt(disc)
    p = (p_sat[0] + t * axis[0], p_sat[1] + t * axis[1], p_sat[2] + t * axis[2])
    r = math.sqrt(_dot(p, p))
    la = math.degrees(math.asin(max(min(p[2] / r, 1.0), -1.0)))
    lo = math.degrees(math.atan2(p[1], p[0]))
    return la, lo


def _contour_offaxis(pat, level_dbr):
    """方向图 −level 等值线的离轴角（度）：沿 φ=0 径向找首个下穿点（插值）。"""
    g = pat["grid"]
    ths = g["theta"]
    vals = g["gain_dbr"]
    nphi = len(g["phi"])
    j0 = 0
    prev = None
    for i, th in enumerate(ths):
        v = vals[i][j0]
        if prev is not None and prev >= level_dbr > v:
            w = (prev - level_dbr) / (prev - v) if prev > v else 0.0
            return ths[i - 1] + w * (th - ths[i - 1])
        prev = v
    return None


# ================================================================
# 等值线提取（marching squares，纯 Python）
# ================================================================
def contour_segments(cov, level_dbw):
    """EIRP 网格上提取 level 等值线段集：[[ (lat1,lon1),(lat2,lon2) ], ...]。
    marching squares 线性插值；FLOOR（不可见）格点不参与。"""
    lats, lons, vals = cov["lat"], cov["lon"], cov["eirp_dbw"]
    floor = cov.get("floor", -200.0)
    segs = []
    nl, no = len(lats), len(lons)

    def interp(va, vb, la_a, la_b, lo_a, lo_b, axis):
        w = (level_dbw - va) / (vb - va) if vb != va else 0.0
        if axis == "lat":
            return (la_a + w * (la_b - la_a), lo_a)
        return (la_a, lo_a + w * (lo_b - lo_a))

    for i in range(nl - 1):
        for j in range(no - 1):
            v00, v01 = vals[i][j], vals[i][j + 1]
            v10, v11 = vals[i + 1][j], vals[i + 1][j + 1]
            if min(v00, v01, v10, v11) <= floor:
                continue
            idx = (1 if v00 >= level_dbw else 0) | (2 if v01 >= level_dbw else 0) | \
                  (4 if v11 >= level_dbw else 0) | (8 if v10 >= level_dbw else 0)
            if idx in (0, 15):
                continue
            la0, la1 = lats[i], lats[i + 1]
            lo0, lo1 = lons[j], lons[j + 1]
            # 四边交点（按需算）
            def e_bottom():   # i 边（v00-v01）
                return interp(v00, v01, la0, la0, lo0, lo1, "lon")
            def e_top():      # i+1 边（v10-v11）
                return interp(v10, v11, la1, la1, lo0, lo1, "lon")
            def e_left():     # j 边（v00-v10）
                return interp(v00, v10, la0, la1, lo0, lo0, "lat")
            def e_right():    # j+1 边（v01-v11）
                return interp(v01, v11, la0, la1, lo1, lo1, "lat")
            table = {
                1: [(e_left, e_bottom)], 2: [(e_bottom, e_right)],
                3: [(e_left, e_right)], 4: [(e_right, e_top)],
                5: [(e_left, e_bottom), (e_right, e_top)],
                6: [(e_bottom, e_top)], 7: [(e_left, e_top)],
                8: [(e_top, e_left)], 9: [(e_bottom, e_top)],
                10: [(e_left, e_top), (e_bottom, e_right)],
                11: [(e_top, e_right)], 12: [(e_right, e_left)],
                13: [(e_bottom, e_right)], 14: [(e_left, e_bottom)],
            }
            for a, b in table[idx]:
                segs.append([a(), b()])
    return segs


def coverage_metrics(cov, levels_dbw=None):
    """覆盖度量：各电平足迹直径（km，多方位平均）与面积（km²）、峰值/边缘电平。
    足迹直径：从波束中心沿 8 方位射线找电平下穿点的地面距离 ×2。"""
    levels_dbw = levels_dbw or [cov["peak_eirp_dbw"] - 3.0, cov["peak_eirp_dbw"] - 10.0]
    lats, lons, vals = cov["lat"], cov["lon"], cov["eirp_dbw"]
    floor = cov.get("floor", -200.0)
    c = cov["beam_center"]
    dlat = lats[1] - lats[0] if len(lats) > 1 else 1.0
    dlon = lons[1] - lons[0] if len(lons) > 1 else 1.0
    km_deg = R_EARTH_KM * DEG                      # 每度大圆弧长 ≈111.2km

    def sample(la, lo):
        """双线性采样 eirp（出窗/floor → None）"""
        if la < lats[0] or la > lats[-1] or lo < lons[0] or lo > lons[-1]:
            return None
        fi = (la - lats[0]) / dlat
        fj = (lo - lons[0]) / dlon
        i0 = min(int(fi), len(lats) - 2)
        j0 = min(int(fj), len(lons) - 2)
        wi, wj = fi - i0, fj - j0
        v = (vals[i0][j0] * (1 - wi) * (1 - wj) + vals[i0 + 1][j0] * wi * (1 - wj) +
             vals[i0][j0 + 1] * (1 - wi) * wj + vals[i0 + 1][j0 + 1] * wi * wj)
        return None if v <= floor else v

    out = {}
    # 射线步长：随网格分辨率自适应（LEO 足迹 ~90km 时 0.1°≈11km 太粗）
    step = max(min(dlat, dlon) * 0.5, 0.002)
    r_max = max(lats[-1] - lats[0], lons[-1] - lons[0])   # 窗对角限
    for lv in levels_dbw:
        radii = []
        for az in range(0, 360, 45):
            ca, sa = math.cos(az * DEG), math.sin(az * DEG)
            r_prev, v_prev = 0.0, sample(c["lat"], c["lon"])
            if v_prev is None:
                continue
            r = step
            hit = None
            while r < r_max:
                la = c["lat"] + ca * r
                lo = c["lon"] + sa * r / max(math.cos(la * DEG), 0.1)
                v = sample(la, lo)
                if v is None or v < lv:
                    if v_prev is not None and v_prev >= lv:
                        w = (v_prev - lv) / (v_prev - v) if v is not None and v_prev > v else 1.0
                        hit = r_prev + w * step
                    break
                r_prev, v_prev = r, v
                r += step
            if hit is not None:
                radii.append(hit * km_deg)
        diam = 2.0 * sum(radii) / len(radii) if radii else None
        # 面积：格点计数 × 格元面积（cos(lat) 修正；下限 0.05 防极区归零）
        area = 0.0
        for i, la in enumerate(lats):
            for j in range(len(lons)):
                if vals[i][j] > floor and vals[i][j] >= lv:
                    area += km_deg * dlat * km_deg * dlon * max(math.cos(la * DEG), 0.05)
        out[round(lv, 1)] = dict(diameter_km=round(diam, 1) if diam else None,
                                 area_km2=round(area, 0), n_rays=len(radii))
    return out


# ================================================================
# 雨衰空间分布叠加 + 链路可用度地图（ITU-R P.618/P.838-3/P.837/P.839-4）
# ================================================================
def rain_atten_grid(cov, freq_ghz, p_pct=0.01, pol="V", normalize_to=None,
                    h_s_km=0.0):
    """覆盖网格逐格点雨衰 A_p(lat,lon)（dB，超过 p% 时间）。

    物理链路（P.618 §2.2.1.1，propagation.py 同源实现）：
      格点 → R_0.01 气候学（P.837 近似）→ γ_R=k·R^α（P.838-3）
      → 斜路径 L_s=(h_R−h_s)/sin(el)（逐格点仰角 el 由卫星几何算出）
      → 缩减因子 r/v（P.618）→ A_0.01=γ_R·L_E → 换算 A_p。

    normalize_to：给定时（引擎 BAND_RAIN 同口径参考雨衰，dB@0.01%）把空间分布
      归一锚定到工程基准——即 波束中心 A_p × (ref/A_center_raw)，保持相对分布
      结构、绝对量级与链路预算同源（默认 None=ITU 原始预测）。
    返回 dict：atten_db 网格（不可见=floor）、R001 网格、tag 网格、A_center、note。
    """
    import propagation as PR
    lats, lons = cov["lat"], cov["lon"]
    floor = cov.get("floor", -200.0)
    sat = cov["sat"]
    p_sat = sat_position(sat["lat"], sat["lon"], sat["h_km"])
    atten, r001g, tagg = [], [], []
    a_center = None
    for i, la in enumerate(lats):
        ra, rt, rg = [], [], []
        for j, lo in enumerate(lons):
            if cov["eirp_dbw"][i][j] <= floor:
                ra.append(floor)
                rt.append(-1)
                rg.append("")
                continue
            R, tag = PR.r001_climatology(la, lo)
            el = elevation_deg(p_sat, la, lo)
            A = PR.rain_atten_slant(freq_ghz, R, max(el, 5.0), la, p_pct=p_pct,
                                    pol=pol, h_s_km=h_s_km, lon_deg=lo)
            ra.append(round(A, 3))
            rt.append(R)
            rg.append(tag)
            if a_center is None and abs(la - cov["beam_center"]["lat"]) < 1e-3 \
                    and abs(lo - cov["beam_center"]["lon"]) < 1e-3:
                a_center = A
        atten.append(ra)
        r001g.append(rt)
        tagg.append(rg)
    # 波束中心不在格点上（扫描波束）→ 取峰值 EIRP 格点的雨衰作归一锚点
    if a_center is None:
        pg = cov.get("peak_ground") or {}
        a_center = PR.rain_atten_slant(
            freq_ghz, PR.r001_climatology(pg.get("lat", lats[len(lats) // 2]),
                                          pg.get("lon", lons[len(lons) // 2]))[0],
            max(elevation_deg(p_sat, pg.get("lat", sat["lat"]),
                              pg.get("lon", sat["lon"])), 5.0),
            pg.get("lat", sat["lat"]), p_pct=p_pct, pol=pol,
            lon_deg=pg.get("lon", sat["lon"]))
    scale = 1.0
    if normalize_to and a_center and a_center > 1e-6:
        scale = float(normalize_to) / a_center
        atten = [[(v * scale if v > floor else floor) for v in row] for row in atten]
        a_center = float(normalize_to)
    return dict(ok=True, atten_db=atten, r001=r001g, tags=tagg,
                floor=floor, p_pct=p_pct, freq_ghz=freq_ghz, pol=pol,
                A_center_db=round(a_center, 3), scale=round(scale, 4),
                normalized=bool(normalize_to),
                note=("雨衰空间分布（ITU-R P.618/P.838-3/P.837）：%.2fGHz %s 极化 "
                      "p=%.3f%%，波束中心 A=%.1f dB%s"
                      % (freq_ghz, pol, p_pct, a_center,
                         ("（归一锚定 %.1f dB 工程基准）" % normalize_to)
                         if normalize_to else "")))


def availability_map(cov, rain, eirp_req_dbw, extra_loss_db=0.0):
    """链路可用度地图：逐格点 A_tol = EIRP_cell − EIRP_req − 其他损耗 → 反演
    超出时间百分比 p（P.618 换算式二分）→ 可用度 = 100 − p（%）。

    eirp_req_dbw : 满足 C/N+余量的最低 EIRP 需求（链路预算口径，与 cov 的
                   peak_eirp_dbw 同口径——整波束或单载波）
    extra_loss_db: 雨衰外附加损耗（大气/指向/实现，可从 p 参数带下）
    rain         : rain_atten_grid 输出（atten_db 网格 = A_p @ rain.p_pct；
                   p≠0.01 时逐格点换算回 A_0.01 口径再反演）
    返回 dict：avail_pct 网格（floor=不可见）、等值线（99/99.5/99.9%）、统计。
    """
    import propagation as PR
    lats, lons = cov["lat"], cov["lon"]
    floor = cov.get("floor", -200.0)
    sat = cov["sat"]
    p_sat = sat_position(sat["lat"], sat["lon"], sat["h_km"])
    p_grid = float(rain.get("p_pct") or 0.01)
    av, vals = [], []
    for i, la in enumerate(lats):
        row = []
        for j, lo in enumerate(lons):
            e = cov["eirp_dbw"][i][j]
            if e <= floor:
                row.append(floor)
                continue
            a_tol = e - eirp_req_dbw - extra_loss_db
            el = max(elevation_deg(p_sat, la, lo), 5.0)
            A001_eff = rain["atten_db"][i][j]
            if abs(p_grid - 0.01) > 1e-9:
                # 网格存 A_p（p≠0.01）→ 用单位 A_0.01 的换算比还原 A_0.01
                ratio = PR.rain_atten_at_pct(1.0, p_grid, el, la)[0]
                A001_eff = rain["atten_db"][i][j] / max(ratio, 1e-9)
            p_un = PR.unavailability_from_atten(A001_eff, a_tol, el, la)
            a = max(min(100.0 - p_un, 100.0), 0.0)
            row.append(round(a, 4))
            vals.append(a)
        av.append(row)
    n_vis = len(vals)
    stats = dict(n_cells=n_vis,
                 avail_min=round(min(vals), 4) if vals else None,
                 avail_mean=round(sum(vals) / n_vis, 4) if vals else None,
                 pct_cells_ge_995=round(100.0 * sum(1 for v in vals if v >= 99.5)
                                        / n_vis, 1) if vals else None)
    # 波束中心可用度（最近格点）
    bc = cov["beam_center"]
    dlat = lats[1] - lats[0] if len(lats) > 1 else 1.0
    dlon = lons[1] - lons[0] if len(lons) > 1 else 1.0
    i0 = min(max(int(round((bc["lat"] - lats[0]) / dlat)), 0), len(lats) - 1)
    j0 = min(max(int(round((bc["lon"] - lons[0]) / dlon)), 0), len(lons) - 1)
    stats["avail_center"] = av[i0][j0] if av[i0][j0] > floor else None
    # 可用度等值线——复用 marching squares（把可用度百分比当标量场）
    pseudo = dict(lat=lats, lon=lons, eirp_dbw=av, floor=floor)
    contours = {str(lv): contour_segments(pseudo, lv) for lv in (99.0, 99.5, 99.9)}
    return dict(ok=True, avail_pct=av, floor=floor, stats=stats,
                contours=contours, eirp_req_dbw=eirp_req_dbw,
                extra_loss_db=extra_loss_db,
                note=("链路可用度地图：EIRP−雨衰−附加损耗(%.1fdB) 反演（ITU-R P.618），"
                      "波束中心 %.3f%%、最低 %.3f%%、≥99.5%% 格点占比 %s%%"
                      % (extra_loss_db,
                         stats["avail_center"] or 0.0,
                         stats["avail_min"] or 0.0, stats["pct_cells_ge_995"])))


# ================================================================
# 多波束覆盖合成（波束列表 → 逐波束投影 → max 合成 + 同频隔离）
# ================================================================
def multi_beam_coverage(pats, peak_eirps_dbw, h_km, sat_lat=0.0, sat_lon=0.0,
                        n_lat=121, n_lon=161, el_min_deg=0.0,
                        lat_span=None, lon_span=None, labels=None,
                        same_freq_groups=None):
    """多波束合成覆盖：每波束独立 coverage_map（同一 pat 族/各自指向）→
    合成网格取逐点 max（相邻波束交叠区取更强值——SATSOFT 多波束惯例）。

    pats             : 波束方向图列表（各自 scan_theta/scan_phi 已指向波束中心）
    peak_eirps_dbw   : 各波束峰值 EIRP（dBW）
    same_freq_groups : 同频波束分组 [[0,1],[2,3]]（颜色复用）→ 计算组内/组间
                       波束隔离（一波束中心落在另一波束方向图的电平 = C/I 上界）
    返回 dict：合成 eirp 网格、每波束中心/峰值、合成度量、隔离矩阵、note。
    """
    if len(pats) != len(peak_eirps_dbw):
        return dict(ok=False, error="波束数与 EIRP 数不一致")
    n_b = len(pats)
    labels = labels or ["B%d" % (i + 1) for i in range(n_b)]
    covs = [coverage_map(pat, pk, h_km, sat_lat=sat_lat, sat_lon=sat_lon,
                         lat_span=lat_span, lon_span=lon_span,
                         n_lat=n_lat, n_lon=n_lon, el_min_deg=el_min_deg)
            for pat, pk in zip(pats, peak_eirps_dbw)]
    # 公共网格：所有波束窗的并集（各 coverage_map 窗不同 → 用第一波束窗为基，
    # 其余按 lat/lon 最近邻对齐——工程上波束窗交叠率高，误差 <1 格）
    base = covs[0]
    lats, lons = base["lat"], base["lon"]
    floor = base["floor"]
    comp = [[floor] * len(lons) for _ in lats]
    owner = [[-1] * len(lons) for _ in lats]          # 合成值来自哪个波束
    beams = []
    for k, cv in enumerate(covs):
        # 对齐：把 cv 网格重采样到 base 网格（双线性）
        for i, la in enumerate(lats):
            if la < cv["lat"][0] or la > cv["lat"][-1]:
                continue
            fi = (la - cv["lat"][0]) / (cv["lat"][1] - cv["lat"][0])
            i0 = min(int(fi), len(cv["lat"]) - 2)
            wi = fi - i0
            for j, lo in enumerate(lons):
                if lo < cv["lon"][0] or lo > cv["lon"][-1]:
                    continue
                fj = (lo - cv["lon"][0]) / (cv["lon"][1] - cv["lon"][0])
                j0 = min(int(fj), len(cv["lon"]) - 2)
                wj = fj - j0
                v = (cv["eirp_dbw"][i0][j0] * (1 - wi) * (1 - wj) +
                     cv["eirp_dbw"][i0 + 1][j0] * wi * (1 - wj) +
                     cv["eirp_dbw"][i0][j0 + 1] * (1 - wi) * wj +
                     cv["eirp_dbw"][i0 + 1][j0 + 1] * wi * wj)
                if v > floor and v > comp[i][j]:
                    comp[i][j] = round(v, 2)
                    owner[i][j] = k
        beams.append(dict(label=labels[k], beam_center=cv["beam_center"],
                          scan=cv["scan"], peak_eirp_dbw=cv["peak_eirp_dbw"],
                          peak_ground=cv["peak_ground"]))
    comp_cov = dict(lat=lats, lon=lons, eirp_dbw=comp, floor=floor,
                    sat=base["sat"], beam_center=beams[0]["beam_center"],
                    scan=base["scan"], peak_eirp_dbw=max(peak_eirps_dbw),
                    peak_ground=base["peak_ground"], exact=True,
                    n_lat=len(lats), n_lon=len(lons), scan_deg=0.0,
                    peak_gain_dbi=base.get("peak_gain_dbi", 0.0))
    pk = max(v for row in comp for v in row if v > floor) if n_b else 0.0
    levels = [round(pk - x, 1) for x in (3.0, 10.0)]
    metrics = coverage_metrics(comp_cov, levels_dbw=levels)
    # 同频隔离：波束 a 中心方向在波束 b 方向图上的电平（dBr）→ C/I ≈ −电平
    iso = []
    xb, yb, zb = _body_frame(sat_lat, sat_lon)
    p_sat = sat_position(sat_lat, sat_lon, h_km)
    for a in range(n_b):
        for b in range(n_b):
            if a == b:
                continue
            ca = beams[a]["beam_center"]
            p_a = ecef(ca["lat"], ca["lon"], R_EARTH_KM)
            rx, ry, rz = (p_a[0] - p_sat[0], p_a[1] - p_sat[1], p_a[2] - p_sat[2])
            d = math.sqrt(rx * rx + ry * ry + rz * rz) or 1.0
            ga = pats[b].get("_gain_arr")
            if ga is not None:
                # 精确口径：方向单位矢量在体系（x=北,y=东,z=nadir）的分量
                rel = ga((rx * xb[0] + ry * xb[1] + rz * xb[2]) / d,
                         (rx * yb[0] + ry * yb[1] + rz * yb[2]) / d,
                         (rx * zb[0] + ry * zb[1] + rz * zb[2]) / d)
                dbr = 10.0 * math.log10(rel) if rel > 1e-12 else -120.0
            else:
                axis_b, _, _ = beam_axis(sat_lat, sat_lon, h_km,
                                         beams[b]["beam_center"]["lat"],
                                         beams[b]["beam_center"]["lon"])
                v = (rx / d, ry / d, rz / d)
                cos_sep = _dot(axis_b, v)
                th_off = math.degrees(math.acos(max(min(cos_sep, 1.0), -1.0)))
                dbr = gain_dbr_at_offaxis(pats[b], th_off, 0.0)
            iso.append(dict(pair="%s→%s" % (labels[a], labels[b]),
                            level_dbr=round(dbr, 2),
                            ci_db=round(-dbr, 2),
                            same_freq=bool(same_freq_groups and any(
                                a in g and b in g for g in same_freq_groups))))
    worst_same = [x for x in iso if x["same_freq"]]
    return dict(ok=True, n_beams=n_b, lat=lats, lon=lons, eirp_dbw=comp,
                floor=floor, beams=beams, metrics=metrics, levels=levels,
                isolation=iso,
                worst_same_freq_ci=round(min((x["ci_db"] for x in worst_same),
                                             default=0.0), 2),
                coverage=comp_cov,
                note=("多波束合成覆盖（%d 波束，max 合成）：合成峰值 EIRP %.1f dBW，"
                      "−3dB 足迹 Ø %s km；同频波束最差隔离 %s dB"
                      % (n_b, pk,
                         metrics.get(round(levels[0], 1), {}).get("diameter_km"),
                         ("%.1f" % min((x["ci_db"] for x in worst_same), default=0.0))
                         if worst_same else "N/A")))


# ================================================================
# 导出（SATSOFT 交叉核对）
# ================================================================
def export_coverage_csv(cov, path, level_dbw=None):
    """格点表 CSV：lat, lon, eirp_dbw（floor→空）。SATSOFT/Excel 可直接核对。"""
    lines = ["lat_deg,lon_deg,eirp_dbw"]
    floor = cov.get("floor", -200.0)
    for i, la in enumerate(cov["lat"]):
        for j, lo in enumerate(cov["lon"]):
            v = cov["eirp_dbw"][i][j]
            lines.append("%.4f,%.4f,%s" % (la, lo, "" if v <= floor else "%.2f" % v))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, rows=len(cov["lat"]) * len(cov["lon"]))


def export_contours_csv(cov, path, levels_dbw):
    """等值线表 CSV：level_dbw, lat1, lon1, lat2, lon2（线段集）。"""
    lines = ["level_dbw,lat1,lon1,lat2,lon2"]
    for lv in levels_dbw:
        for (a, b) in contour_segments(cov, lv):
            lines.append("%.1f,%.5f,%.5f,%.5f,%.5f" % (lv, a[0], a[1], b[0], b[1]))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return dict(ok=True, path=path, levels=levels_dbw)


# ================================================================
# 自检
# ================================================================
if __name__ == "__main__":
    import os
    import pattern_engine as PE
    print("=== coverage_engine self-test ===")
    # GEO 60°E 定点，2.5m 反射面 @20GHz，指向巴基斯坦（30°N, 70°E）
    # 工作流：pointing_angles 算扫描角 → build 扫描方向图 → coverage_map
    st0, sp0 = pointing_angles(0.0, 60.0, 35786.0, 30.0, 70.0)
    print("pointing → scan_theta=%.3f° scan_phi=%.3f°" % (st0, sp0))
    assert 4.0 < st0 < 7.0, "GEO 60E→巴基斯坦扫描角应≈5~6°，实得 %.2f" % st0
    pat = PE.reflector_pattern(2.5, 20.0, eta=0.65, edge_db=-12.0,
                               scan_theta=st0, scan_phi=sp0,
                               grid_n_theta=91, grid_n_phi=73)
    eirp_pk = 54.0                     # 典型 GEO HTS 点波束峰值 EIRP
    cov = coverage_map(pat, eirp_pk, h_km=35786.0, sat_lat=0.0, sat_lon=60.0,
                       n_lat=121, n_lon=141)
    assert cov["exact"], "反射面应走 _gain_arr 精确查询"
    print("scan_deg =", cov["scan_deg"], " beam_center =", cov["beam_center"])
    assert abs(cov["scan_deg"] - st0) < 1e-3, "coverage_map 扫描角应与 pat 一致"
    assert abs(cov["beam_center"]["lat"] - 30.0) < 0.5 and \
        abs(cov["beam_center"]["lon"] - 70.0) < 0.5, \
        "波束中心应在目标点，实得 %s" % cov["beam_center"]
    pg = cov["peak_ground"]["eirp_dbw"]
    assert abs(pg - eirp_pk) < 1.0, "地面峰值 EIRP 应≈%.1f dBW（扫描损耗<0.1dB），实得 %.2f" % (eirp_pk, pg)
    assert abs(cov["peak_ground"]["lat"] - 30.0) < 0.5 and \
        abs(cov["peak_ground"]["lon"] - 70.0) < 0.5, "地面 EIRP 峰值应落在波束中心"
    m = coverage_metrics(cov, [eirp_pk - 3.0, eirp_pk - 10.0])
    print("metrics:", m)
    d3 = m[round(eirp_pk - 3.0, 1)]["diameter_km"]
    # θ3dB=0.389° @ GEO（斜距 ~37300km）→ 足迹 Ø ≈ 2·(0.194°·π/180)·37300 ≈ 252km（±40%）
    assert d3 and 140.0 < d3 < 450.0, "−3dB 足迹直径应≈250km 量级，实得 %s" % d3
    segs3 = contour_segments(cov, eirp_pk - 3.0)
    print("contour segs(peak−3dB):", len(segs3))
    assert len(segs3) > 20, "−3dB 等值线段应成环（>20 段），实得 %d" % len(segs3)
    # nadir 波束（boresight pat → 波束中心=星下点）
    pat0 = PE.reflector_pattern(2.5, 20.0, eta=0.65, edge_db=-12.0,
                                grid_n_theta=91, grid_n_phi=73)
    cov2 = coverage_map(pat0, eirp_pk, h_km=35786.0, sat_lat=0.0, sat_lon=60.0,
                        n_lat=81, n_lon=101)
    assert cov2["scan_deg"] == 0.0 and abs(cov2["beam_center"]["lon"] - 60.0) < 1e-6 \
        and abs(cov2["beam_center"]["lat"]) < 1e-6, "boresight 波束中心应在星下点"
    assert abs(cov2["peak_ground"]["eirp_dbw"] - eirp_pk) < 1.0, "nadir 峰值 EIRP 应≈54dBW"
    # LEO 550km 广角阵（覆盖窗自动扩展）：θ3≈9.1°（电尺寸同 20GHz 16×16 d=0.5λ）
    # → 星下点足迹 Ø ≈ 2·tan(4.55°)·550 ≈ 88km（LEO 点波束量级）
    pat3 = PE.phased_array_pattern(2.0, 16, 16, d_lam=0.5, grid_n_theta=91, grid_n_phi=73)
    cov3 = coverage_map(pat3, 40.0, h_km=550.0, sat_lat=0.0, sat_lon=105.0,
                        n_lat=81, n_lon=101)
    assert cov3["exact"], "相控阵应走 _gain_arr 精确查询"
    m3 = coverage_metrics(cov3, [40.0 - 3.0])
    d3leo = m3[37.0]["diameter_km"]
    print("LEO −3dB footprint km:", d3leo)
    assert d3leo and 50.0 < d3leo < 200.0, \
        "LEO −3dB 足迹应≈88km（2·tan(θ3/2)·h），实得 %s" % d3leo
    assert abs(cov3["peak_ground"]["eirp_dbw"] - 40.0) < 1.0, "LEO nadir 峰值应≈40dBW"
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out, exist_ok=True)
    r1 = export_coverage_csv(cov, os.path.join(out, "_coverage_test.csv"))
    r2 = export_contours_csv(cov, os.path.join(out, "_coverage_contours.csv"),
                             [eirp_pk - 3.0, eirp_pk - 10.0])
    print("export grid csv:", r1["rows"], "rows; contours:", r2)
    print("note:", cov["note"])

    # ---- 雨衰空间叠加 + 可用度地图（ITU-R）----
    rain = rain_atten_grid(cov, 20.0, p_pct=0.01, pol="V")
    print("rain grid:", rain["note"])
    assert rain["ok"] and rain["A_center_db"] > 0, "波束中心雨衰应为正"
    assert rain["A_center_db"] < 15.0, "巴基斯坦（干旱区）Ka 下行 A_0.01 应 <15dB，实得 %.1f" % rain["A_center_db"]
    # 不可见格点 = floor
    assert rain["atten_db"][0][0] == rain["floor"] or cov["eirp_dbw"][0][0] > cov["floor"]
    # 归一锚定
    rain_n = rain_atten_grid(cov, 20.0, normalize_to=7.0)
    assert abs(rain_n["A_center_db"] - 7.0) < 1e-6, "归一后中心雨衰应=锚定值"
    assert abs(rain_n["scale"] - 7.0 / rain["A_center_db"]) < 1e-3

    av = availability_map(cov, rain, eirp_req_dbw=eirp_pk - 6.0, extra_loss_db=1.5)
    print("availability:", av["note"])
    assert av["ok"] and av["stats"]["avail_center"] is not None
    # 中心余量 = 54−48−1.5 = 4.5dB；巴基斯坦 A_0.01≈5.5dB → p≈0.02~0.05% → 可用度 99.9x%
    assert 99.5 < av["stats"]["avail_center"] <= 100.0, \
        "中心可用度应 >99.5%%，实得 %s" % av["stats"]["avail_center"]
    assert av["stats"]["avail_min"] < av["stats"]["avail_center"], "边缘可用度应低于中心"
    assert 0.0 <= av["stats"]["pct_cells_ge_995"] <= 100.0
    # 可用度等值线（99.5% 应存在——覆盖区大部分高于它，等值线可能为空或成环）
    for lv, segs_ in av["contours"].items():
        assert isinstance(segs_, list)

    # ---- 多波束合成：GEO 三波束（巴基斯坦周边 3 个目标）----
    tgts = [(30.0, 70.0), (33.0, 73.0), (27.0, 68.0)]
    pats, pks = [], []
    for (tla, tlo) in tgts:
        st, sp = pointing_angles(0.0, 60.0, 35786.0, tla, tlo)
        pats.append(PE.reflector_pattern(2.5, 20.0, eta=0.65, edge_db=-12.0,
                                         scan_theta=st, scan_phi=sp,
                                         grid_n_theta=91, grid_n_phi=73))
        pks.append(54.0)
    mb = multi_beam_coverage(pats, pks, 35786.0, sat_lat=0.0, sat_lon=60.0,
                             n_lat=81, n_lon=101,
                             same_freq_groups=[[0, 2]])
    print("multi-beam:", mb["note"])
    assert mb["ok"] and mb["n_beams"] == 3
    for k, bm in enumerate(mb["beams"]):
        assert abs(bm["beam_center"]["lat"] - tgts[k][0]) < 0.6, \
            "波束 %d 中心应在目标点" % k
    # 合成峰值 ≈ 单波束峰值
    assert abs(mb["metrics"][51.0]["diameter_km"] - 250.0) < 150.0
    # 同频隔离：相邻波束（角距 ~3°）间隔离应为负电平（C/I 为正、量级 10~40dB）
    sf = [x for x in mb["isolation"] if x["same_freq"]]
    assert sf and all(x["ci_db"] > 0 for x in sf), "同频 C/I 应为正 dB"
    assert mb["worst_same_freq_ci"] > 5.0, "相邻波束同频隔离应 >5dB，实得 %.1f" % mb["worst_same_freq_ci"]
    print("worst same-freq C/I: %.1f dB" % mb["worst_same_freq_ci"])

    print("=== ALL PASS ===")
