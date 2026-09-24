# -*- coding: utf-8 -*-
"""偏置反射面天线设计引擎（纯 Python 第一性原理，零第三方依赖，冻结 exe 可用）。

输入用户可配置的四项几何参数：
  · D_r    反射器口径 (m)                    —— 反射面边缘投影直径
  · f      反射器焦距 (m)                    —— 母抛物面焦距（顶点到焦点）
  · h      发射器(馈源相位中心)中心偏置 (m)   —— 母面轴线到反射面几何中心的横向偏置
  · d_feed 馈源口径 (m)                      —— 馈源喇叭物理口径（留空由照射角反推）

输出：
  · 几何：F/D、h/D、馈源轴倾斜角 ψ0、近/远边照射角 ψ_near/ψ_far、半张角 Δψ、
          焦点-反射面中心距 r_c、近边到母轴间隙
  · 照射：所需馈源 θ3dB、推荐 d_feed、实际边缘锥削、溢散效率 η_spill
  · 效率：口径照射效率 η_ill（严格 2D 数值积分）、总口径效率 η_ap、增益 G、θ3dB
  · 方向图：真实照射分布的口径远场（主面 E / 正交面 H 双 cut）+ θ3dB + 首旁瓣
  · 约束校验：F/D 区间、偏置间隙、馈源覆盖、锥削区间、η_spill、η_ill、Ruze
  · 反解设计：给定 D_r + 目标 θ3dB + 锥削 → 求 f / h / d_feed

════════ 物理口径（可追溯）════════
母抛物面 z = ρ²/(4f)，焦点 F=(0,0,f)，顶点在原点，轴线 = +z。
反射面为椭圆 rim，正投影到口径面 (z=0) 是圆盘 (x−h)² + y² ≤ (D_r/2)²。

**抛物面张角性质（严格）**：焦点到母面上径向坐标 ρ 处一点的连线，与母轴
的夹角 ψ 满足  ψ = 2·atan(ρ / 2f)。
  证明：焦半径 |FP| = f + ρ²/(4f)（抛物线定义），P=(ρ,0,ρ²/4f)，
        cos ψ = (f − ρ²/4f)/(f + ρ²/4f) = (1−t²)/(1+t²)，t=ρ/(2f)
        而 cos ψ = (1−tan²(ψ/2))/(1+tan²(ψ/2)) → tan(ψ/2) = ρ/(2f)。∎
故**馈源轴倾斜角 ψ0 = 2·atan(h/2f)**（指向反射面几何中心），不是 atan(h/2f)。

**馈源照射角 ψ′（关键）**：馈源方向图 F(ψ′) 的自变量是「离馈源轴」的角，
不是离母轴角。馈源轴 â = 单位向量 F→C（C=反射面中心）。口径面上一点 Q：
    d̂ = 单位向量 F→Q，   cos ψ′ = d̂ · â
用向量点积直接算，避免球面三角近似（偏置面 ψ′ 在方位上非对称）。

**口径场（物理光学 PO，反射后相位均匀）**：
    E_a(Q) = F(ψ′) · (f/r)^{3/4}，  r = |FP| = f + ρ²/(4f)
推导：馈源在 P 点产生 E_inc = E_0 F(ψ′)/r；反射面元 dS 与口径面元 dA 的关系
dA = dS·cosα，α 为面法线与口径面法线(+z)夹角。抛物面性质 tanα = dz/dρ = ρ/(2f)
= tan(ψ/2) → α = ψ/2，且 cos(ψ/2) = 2f/sqrt(4f²+ρ²) = sqrt(f/r)。
功率守恒 S_a·dA = S_inc·dS → E_a = E_inc/sqrt(cosα) = E_0 F/(r·(f/r)^{1/4})
= E_0 F f^{-1/4} r^{-3/4} ∝ F(ψ′)·(f/r)^{3/4}。（归一化效率比值与常数无关。）

**立体角元（溢散效率用）**：
    dΩ = dS·cos(入射角)/r² = (dA/cosα)·cos(ψ/2)/r² = dA/r²
（入射角 = ψ/2 = α，二者恰好抵消 → 形式极简，数值稳定。）

**效率**：
    η_ill   = |∫E_a dA|² / (A ∫|E_a|² dA)，A = π(D_r/2)²（投影口径面积）
    η_spill = ∫_reflector |F(ψ′)|² dΩ / ∫_4π |F(ψ′)|² dΩ，dΩ = dA/r²
    η_ap    = η_ill · η_spill     （偏置面无副面/馈源遮挡，不计 blockage）
    G       = 10lg[ η_ap · (π D_r/λ)² ] · 10^(−L_Ruze/10)
    L_Ruze  = 10lg exp[(4πσ_ε/λ)²]

**馈源模型**：cos^q（q 由边缘锥削 Te 与半张角 Δψ 反解：cos^q(Δψ)=10^(Te/20)）
或 gaussian（exp(−c·sin²ψ′)）。馈源物理口径 ↔ θ3dB：θ3dB ≈ k_h·λ/d_feed，
k_h 取 1.27（喇叭/波纹喇叭工程经验 1.1~1.5）。
"""
from __future__ import annotations

import math

C_M_S = 299792458.0
DEG = math.pi / 180.0
K_HORN = 1.27          # 馈源口径-波束宽度经验系数 θ3dB ≈ k·λ/d

# 工程约束默认值（可被调用方覆盖）
CONSTRAINTS = dict(
    f_over_d=(0.5, 2.0),     # F/D 合理区间
    h_min_gap_m=0.02,        # 反射面近边到母轴最小间隙（避免馈源/支杆遮挡主面）
    edge_taper_range=(-18.0, -6.0),   # 实际边缘锥削合理区间 (dB)
    eta_spill_min=0.85,      # 溢散效率下限
    eta_ill_min=0.70,        # 口径照射效率下限
    ruze_max_db=1.0,         # 面精度损耗上限
)


# ================================================================
# 0 通用工具
# ================================================================
def lam_m(freq_ghz):
    """波长 (m)。"""
    return C_M_S / (to_f(freq_ghz, 20.0) * 1e9)


def to_f(v, d=0.0):
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else d
    except (TypeError, ValueError):
        return d


def fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    f = to_f(v, None)
    if f is None:
        return dash
    return ("%%.%df" % nd) % f


# ================================================================
# 1 馈源方向图模型
# ================================================================
def feed_q_from_taper(taper_db, psi_half_deg):
    """由边缘锥削 Te(dB) 与半张角 Δψ 反解 cos^q 的 q：cos^q(Δψ)=10^(Te/20)。"""
    c = math.cos(math.radians(max(to_f(psi_half_deg), 1e-6)))
    if c <= 1e-9 or c >= 1.0 - 1e-12:
        return 0.0
    return to_f(taper_db, -12.0) / (20.0 * math.log10(c))


def feed_theta3db_cosq(q):
    """cos^q 馈源 −3dB 全宽 (deg)：2·acos(0.5^(1/q))。"""
    q = to_f(q, 0.0)
    if q <= 0:
        return 180.0
    return 2.0 * math.degrees(math.acos(min(0.5 ** (1.0 / q), 1.0)))


def feed_theta3db_gauss(c):
    """gaussian 馈源 exp(−c sin²ψ) 的 −3dB 全宽 (deg)。"""
    c = to_f(c, 0.0)
    if c <= 0:
        return 180.0
    s = min(1.0, math.sqrt(math.log(2.0) / c))
    return 2.0 * math.degrees(math.asin(s))


def gauss_c_from_taper(taper_db, psi_half_deg):
    """由边缘锥削与半张角反解高斯 c：exp(−c sin²Δψ)=10^(Te/20)。"""
    s = math.sin(math.radians(max(to_f(psi_half_deg), 1e-6)))
    if s <= 1e-9:
        return 0.0
    return -to_f(taper_db, -12.0) * math.log(10.0) / 20.0 / (s * s)


def feed_q_from_theta3(theta3_deg):
    """由馈源自身 θ3dB 定 cos^q 的 q：cos^q(θ3dB/2)=0.5 → q=ln0.5/ln cos(θ3dB/2)。

    用于**用户给定馈源口径**的情形——此时馈源方向图由其物理口径决定，
    反射面边缘的实际锥削是结果而非约束（不可反过来强设锥削）。
    """
    th = to_f(theta3_deg, 0.0)
    if th <= 0:
        return 60.0
    c = math.cos(math.radians(min(th / 2.0, 89.9)))
    if c <= 1e-9 or c >= 1.0 - 1e-12:
        return 0.0
    return max(min(math.log(0.5) / math.log(c), 60.0), 0.05)


def feed_c_from_theta3(theta3_deg):
    """由馈源自身 θ3dB 定高斯 c：exp(−c sin²(θ3dB/2))=0.5 → c=ln2/sin²(θ3dB/2)。"""
    th = to_f(theta3_deg, 0.0)
    if th <= 0:
        return 1e6
    s = math.sin(math.radians(min(th / 2.0, 89.9)))
    if s <= 1e-9:
        return 1e6
    return math.log(2.0) / (s * s)


def feed_amp(model, psi_deg, q=None, c=None):
    """馈源方向图幅值（线性，轴向峰值=1）。psi = 离馈源轴角 ψ′。"""
    psi = math.radians(max(to_f(psi_deg), 0.0))
    if model == "gaussian":
        return math.exp(-to_f(c, 1.0) * math.sin(psi) ** 2)
    return max(math.cos(psi), 0.0) ** max(to_f(q, 1.0), 0.0)


def feed_diam_from_theta3(theta3_deg, freq_ghz, k=K_HORN):
    """由馈源 θ3dB 反推物理口径 (m)：d = k·λ/θ3dB(rad)。"""
    th = max(to_f(theta3_deg), 1e-3)
    return to_f(k, K_HORN) * lam_m(freq_ghz) / (th * DEG)


def theta3_from_diam(d_m, freq_ghz, k=K_HORN):
    """由馈源口径 → θ3dB (deg)（上一函数逆运算）。"""
    d = max(to_f(d_m), 1e-6)
    return to_f(k, K_HORN) * lam_m(freq_ghz) / d / DEG


# ================================================================
# 2 几何：偏置抛物面（第一性原理）
# ================================================================
def geometry(D_r, f, h):
    """偏置抛物面几何。

    返回 F/D、h/D、馈源轴倾斜角 ψ0、近/远边照射角、半张角 Δψ、
    焦点-反射面中心距 r_c、近边到母轴间隙、馈源轴单位向量。
    """
    D_r, f, h = to_f(D_r), to_f(f), to_f(h)
    if D_r <= 0 or f <= 0:
        return dict(ok=False, error="D_r 与 f 必须为正")
    h = max(h, 0.0)
    a = D_r / 2.0
    # 反射面中心 C=(h, 0, h²/(4f))；焦点 F=(0,0,f)
    z_c = h * h / (4.0 * f)
    dx, dz = h - 0.0, z_c - f
    r_c = math.sqrt(dx * dx + dz * dz)               # |FC| 焦点到反射面中心距
    # 抛物面张角性质 ψ = 2 atan(ρ/2f)（见文件头证明）
    psi0 = 2.0 * math.degrees(math.atan(h / (2.0 * f)))      # 馈源轴倾斜角
    rho_near = max(h - a, 0.0)                               # 圆盘含母轴时取 0
    rho_far = h + a
    psi_near = 2.0 * math.degrees(math.atan(rho_near / (2.0 * f)))
    psi_far = 2.0 * math.degrees(math.atan(rho_far / (2.0 * f)))
    d_psi = (psi_far - psi_near) / 2.0                       # 半张角算术平均（仅参考）
    psi_c = (psi_far + psi_near) / 2.0                       # 照射角算术中心
    # **偏置面照射角关于馈源轴不对称**（ψ 对 ρ 非线性）：近边张角 ψ0−ψ_near
    # 通常大于远边 ψ_far−ψ0。馈源覆盖约束取**较大半张角**，否则近边照射不足。
    span_near = psi0 - psi_near
    span_far = psi_far - psi0
    psi_span = max(span_near, span_far)                      # 绑定约束（馈源须覆盖 ±ψ_span）
    # 馈源轴严格指向反射面几何中心 → 中心点 ψ′ 必为 0（自洽性由 _psi_prime 保证，
    # 此处用 ψ_c 与 ψ0 之差刻画「照射角非对称度」，非判定依据，仅供诊断输出）
    psi_c_off = psi_c - psi0
    # 馈源轴单位向量 â = F→C（指向 +x 偏置方向、−z 前方）
    ax = (dx / r_c, 0.0, dz / r_c) if r_c > 0 else (0.0, 0.0, -1.0)
    return dict(ok=True, D_r=D_r, f=f, h=h, a=a, z_c=z_c, r_c=r_c,
                f_over_d=f / D_r, h_over_d=h / D_r,
                psi0_deg=psi0, psi_near_deg=psi_near, psi_far_deg=psi_far,
                psi_c_deg=psi_c, d_psi_deg=d_psi,
                psi_span_deg=psi_span, span_near_deg=span_near,
                span_far_deg=span_far, asym_deg=round(span_near - span_far, 4),
                rho_near=rho_near, rho_far=rho_far, h_near_m=rho_near,
                feed_axis=ax, crosses_axis=bool(h < a), psi_c_off_deg=psi_c_off,
                note=("偏置抛物面 D_r=%.4gm f=%.4gm h=%.4gm：F/D=%.3f、h/D=%.3f、"
                      "馈源轴倾斜 ψ0=%.3f°（=2atan(h/2f)）、照射角 %.3f~%.3f°"
                      "（近边张角 %.3f° / 远边 %.3f° → 绑定 ±%.3f°）、"
                      "焦点-中心距 r_c=%.4gm%s")
                % (D_r, f, h, f / D_r, h / D_r, psi0, psi_near, psi_far,
                   span_near, span_far, psi_span, r_c,
                   "；反射面跨母轴（h<D_r/2）→ 馈源遮挡风险" if h < a else ""))


def _psi_prime(h, u, v, f, axis):
    """口径面点 (h+u, v) 对应的**真实反射面点** P 相对馈源轴的离轴角 ψ′(deg) 与 r=|FP|。

    P = (ρcosφ, ρsinφ, ρ²/4f)，ρ=sqrt((h+u)²+v²)（P 在母面抛物面上，不是 z=0 投影点）。
    cos ψ′ = d̂·â，d̂=(F→P)/r；抛物面性质 r = f + ρ²/(4f)（焦半径）。
    共面退化校核：φ=0 时 ψ′ = 2atan(ρ/2f) − 2atan(h/2f) = ψ_P − ψ0。
    """
    rho = math.sqrt((h + u) ** 2 + v * v)
    r = f + rho * rho / (4.0 * f)                       # 焦半径（严格）
    if r <= 0:
        return 0.0, 0.0
    # F→P = P − F，F=(0,0,f)；P_z − f = ρ²/(4f) − f
    dz = rho * rho / (4.0 * f) - f
    c = ((h + u) * axis[0] + v * axis[1] + dz * axis[2]) / r
    return math.degrees(math.acos(max(min(c, 1.0), -1.0))), r


# ================================================================
# 3 口径照射分布与效率（严格 2D 数值积分）
# ================================================================
def _aperture_field(geom, freq_ghz, model, q=None, c=None, n=65,
                    scan_theta=0.0, scan_phi=0.0):
    """口径面圆盘 (x−h)²+y²≤a² 上的场分布（PO，反射后相位均匀）。

    E(Q) = F(ψ′) · (f/r)^{3/4}   （见文件头推导：能量守恒 dA=dS·cosα，α=ψ/2）
    返回扁平数组 (xs_abs, ys_abs, vals, dq, a)，只含圆盘内点（加速远场积分）。
    """
    h, f, a = geom["h"], geom["f"], geom["a"]
    axis = geom["feed_axis"]
    n = max(int(n) | 1, 15)
    dq = 2.0 * a / (n - 1)
    xs, ys, vals = [], [], []
    k = 2.0 * math.pi / lam_m(freq_ghz)
    st = math.sin(to_f(scan_theta) * DEG)
    ux0, uy0 = st * math.cos(to_f(scan_phi) * DEG), st * math.sin(to_f(scan_phi) * DEG)
    for i in range(n):
        v = -a + dq * i                                   # y
        for j in range(n):
            u = -a + dq * j                               # x − h
            if (u * u + v * v) > a * a:
                continue
            psi_p, r = _psi_prime(h, u, v, f, axis)
            amp = feed_amp(model, psi_p, q, c)
            if amp <= 0.0:
                continue
            val = amp * (f / r) ** 0.75                   # 口径场（PO，相位均匀）
            x_abs = h + u
            # 波束扫描：口径场加线性相位斜坡（峰值移到 scan_theta）
            if st != 0.0:
                ph = -k * (x_abs * ux0 + v * uy0)
                vals.append(complex(val * math.cos(ph), val * math.sin(ph)))
            else:
                vals.append(val)
            xs.append(x_abs)
            ys.append(v)
    return xs, ys, vals, dq, a


def illumination_efficiency(D_r, f, h, freq_ghz=20.0, model="cosq", q=None,
                            c=None, n=65):
    """口径照射效率 η_ill = |∫E dA|² / (A ∫|E|² dA)（严格 2D 数值积分）。

    返回 (eta, E_sum, E2_sum, A, peak_rel, n_pts)。
    """
    g = geometry(D_r, f, h)
    if not g.get("ok"):
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0
    xs, ys, vals, dq, a = _aperture_field(g, freq_ghz, model, q, c, n=n)
    s_re = s_im = s2 = 0.0
    peak = 0.0
    for v in vals:
        if isinstance(v, complex):
            s_re += v.real
            s_im += v.imag
            mag = abs(v)
        else:
            s_re += v
            mag = abs(v)
        s2 += mag * mag
        if mag > peak:
            peak = mag
    dA = dq * dq
    E_sum = math.sqrt(s_re * s_re + s_im * s_im) * dA      # |∫E dA|（含相位合成）
    E2_sum = s2 * dA
    A = math.pi * a * a
    eta = (E_sum * E_sum) / (A * E2_sum) if E2_sum > 0 else 0.0
    return min(eta, 1.0), E_sum, E2_sum, A, (peak / (E_sum / max(A, 1e-12)) if E_sum > 0 else 0.0), len(vals)


def spillover_efficiency(D_r, f, h, model="cosq", q=None, c=None, n=61,
                         n_total=721):
    """溢散（截获）效率 η_spill = ∫_reflector|F(ψ′)|²dΩ / ∫_4π|F(ψ′)|²dΩ。

    截获项：dΩ = dS·cos(ψ/2)/r²，而 dA = dS·cos(ψ/2) → **dΩ = dA/r²**
    （入射角=ψ/2 与投影角恰好抵消，见文件头推导）。r = f + ρ²/(4f)。
    全空间：∫₀^π |F|²·2π sinψ dψ（馈源旋转对称）。
    """
    g = geometry(D_r, f, h)
    if not g.get("ok"):
        return 0.0
    a, f_, h_, axis = g["a"], g["f"], g["h"], g["feed_axis"]
    n = max(int(n) | 1, 21)
    dq = 2.0 * a / (n - 1)
    captured = 0.0
    for i in range(n):
        v = -a + dq * i
        for j in range(n):
            u = -a + dq * j
            if (u * u + v * v) > a * a:
                continue
            psi_p, r = _psi_prime(h_, u, v, f_, axis)
            amp = feed_amp(model, psi_p, q, c)
            r2 = r * r
            if r2 <= 0:
                continue
            captured += amp * amp * (dq * dq) / r2        # |F|²·dΩ，dΩ=dA/r²
    m = max(int(n_total), 61)
    dpsi = math.pi / (m - 1)
    total = 0.0
    for i in range(m):
        psi = dpsi * i
        w = 0.5 if (i == 0 or i == m - 1) else 1.0
        amp = feed_amp(model, math.degrees(psi), q, c)
        total += w * amp * amp * math.sin(psi) * dpsi
    total *= 2.0 * math.pi
    return min(max(captured / total, 0.0), 1.0) if total > 0 else 0.0


def edge_taper_actual(D_r, f, h, model="cosq", q=None, c=None):
    """实际边缘锥削 (dB)：反射面 rim 上最差（最深）的馈源电平。

    沿 rim 采样（含方位变化，偏置面 rim 上 ψ′ 非恒定），取最小值。
    """
    g = geometry(D_r, f, h)
    if not g.get("ok"):
        return 0.0
    a, f_, h_, axis = g["a"], g["f"], g["h"], g["feed_axis"]
    worst = 1.0
    for i in range(181):
        phi = 2.0 * math.pi * i / 180.0
        u = a * math.cos(phi)
        v = a * math.sin(phi)
        psi_p, _r = _psi_prime(h_, u, v, f_, axis)
        amp = feed_amp(model, psi_p, q, c)
        if amp < worst:
            worst = amp
    return 20.0 * math.log10(max(worst, 1e-12))


# ================================================================
# 4 远场方向图（真实照射分布的口径变换，主面/正交面双 cut）
# ================================================================
def _cut_from_field(xs, ys, vals, dq, k, phi_deg, cut_thetas):
    """沿方位 φ 的 cut：E(θ)=Σ E_i·exp(jk·r_i·sinθ·cos(φ_i−φ))·dA。"""
    re, im = [], []
    for th in cut_thetas:
        su = math.sin(th * DEG)
        sr = ir = 0.0
        for x, y, v in zip(xs, ys, vals):
            if su == 0.0:
                sr += v.real if isinstance(v, complex) else v
                ir += v.imag if isinstance(v, complex) else 0.0
                continue
            ph = k * su * (x * math.cos(phi_deg * DEG) + y * math.sin(phi_deg * DEG))
            cp, sp = math.cos(ph), math.sin(ph)
            if isinstance(v, complex):
                sr += v.real * cp - v.imag * sp
                ir += v.real * sp + v.imag * cp
            else:
                sr += v * cp
                ir += v * sp
        re.append(sr * dq * dq)
        im.append(ir * dq * dq)
    mag = [math.sqrt(a * a + b * b) for a, b in zip(re, im)]
    peak = max(mag) if mag else 1.0
    dbr = [20.0 * math.log10(max(v / peak, 1e-12)) for v in mag]
    return cut_thetas, dbr, peak


def _theta3_and_fsl(thetas, dbr, level=3.0):
    """由 cut 找主瓣 −level dB 全宽与首旁瓣电平。

    首旁瓣须**先定位第一零点再在其后找极大**——否则会把主瓣肩部误当旁瓣
    （圆口径第一零点在 1.22λ/D ≈ 1.2θ3dB，远大于 0.8θ3dB）。
    """
    if not dbr:
        return None, None
    ip = max(range(len(dbr)), key=lambda i: dbr[i])
    lo = hi = None
    for i in range(ip, 0, -1):                       # 向左找 −level dB
        if dbr[i] >= -level > dbr[i - 1]:
            d0, d1 = dbr[i], dbr[i - 1]
            fr = (d0 + level) / max(d0 - d1, 1e-12)
            lo = thetas[i] + fr * (thetas[i - 1] - thetas[i])
            break
    for i in range(ip, len(dbr) - 1):                # 向右找 −level dB
        if dbr[i] >= -level > dbr[i + 1]:
            d0, d1 = dbr[i], dbr[i + 1]
            fr = (d0 + level) / max(d0 - d1, 1e-12)
            hi = thetas[i] + fr * (thetas[i + 1] - thetas[i])
            break
    th3 = (hi - lo) if (lo is not None and hi is not None) else None
    ctr = thetas[ip]

    # 第一零点：主瓣外第一个局部极小（且低于 −level）
    fsl = None
    if th3:
        half = th3 / 2.0
        null_idx = None
        for i in range(ip + 1, len(dbr) - 1):
            if abs(thetas[i] - ctr) < half:
                continue
            if dbr[i] <= dbr[i - 1] and dbr[i] <= dbr[i + 1] and dbr[i] < -level:
                null_idx = i
                break
        for i in range(ip - 1, 0, -1):               # 对称侧同样找
            if abs(thetas[i] - ctr) < half:
                continue
            if dbr[i] <= dbr[i - 1] and dbr[i] <= dbr[i + 1] and dbr[i] < -level:
                null_idx = i if null_idx is None else null_idx
                break
        # 在零点之后找极大（首旁瓣峰）
        cands = []
        if null_idx is not None:
            for i in range(null_idx + 1, len(dbr) - 1):
                if dbr[i] >= dbr[i - 1] and dbr[i] >= dbr[i + 1]:
                    cands.append(dbr[i])
                    break
        for i in range((null_idx or ip) - 1, 0, -1):
            if dbr[i] >= dbr[i - 1] and dbr[i] >= dbr[i + 1] and abs(thetas[i] - ctr) > half:
                cands.append(dbr[i])
                break
        if cands:
            fsl = max(cands)
    return th3, fsl


def far_field(D_r, f, h, freq_ghz, model="cosq", q=None, c=None, n=45,
              cut_n=241, cut_span=6.0, scan_theta=0.0, scan_phi=0.0):
    """口径积分远场（含真实照射分布）。返回主面(φ=0)/正交面(φ=90°)双 cut。"""
    g = geometry(D_r, f, h)
    if not g.get("ok"):
        return dict(ok=False, error=g.get("error"))
    xs, ys, vals, dq, a = _aperture_field(g, freq_ghz, model, q, c, n=n,
                                          scan_theta=scan_theta,
                                          scan_phi=scan_phi)
    if not vals:
        return dict(ok=False, error="口径场为空")
    k = 2.0 * math.pi / lam_m(freq_ghz)
    ctr = to_f(scan_theta)
    ths = [(ctr - cut_span + 2 * cut_span * i / (cut_n - 1)) for i in range(cut_n)]
    te, de, pk_e = _cut_from_field(xs, ys, vals, dq, k, 0.0, ths)
    th_h, dh, pk_h = _cut_from_field(xs, ys, vals, dq, k, 90.0, ths)
    th3_e, fsl_e = _theta3_and_fsl(te, de)
    th3_h, fsl_h = _theta3_and_fsl(th_h, dh)
    th3 = min([x for x in (th3_e, th3_h) if x] or [0.0])
    return dict(ok=True, cut_theta=[round(t, 4) for t in ths],
                cut_e_dbr=[round(v, 3) for v in de],
                cut_h_dbr=[round(v, 3) for v in dh],
                theta3db_e_deg=th3_e, theta3db_h_deg=th3_h,
                theta3db_deg=th3,
                first_sidelobe_e_dbr=fsl_e, first_sidelobe_h_dbr=fsl_h,
                first_sidelobe_dbr=max([x for x in (fsl_e, fsl_h)
                                        if x is not None] or [-99.0]),
                cut_span=cut_span, scan_theta_deg=ctr, scan_phi_deg=scan_phi,
                n_points=len(vals),
                note=("口径积分远场（%d 点口径网格，真实照射分布非参数化 taper）："
                      "主面 θ3dB=%s°、正交面 θ3dB=%s°（偏置面两切面不等宽）")
                % (len(vals), fmt(th3_e, 4), fmt(th3_h, 4)))


# ================================================================
# 5 Ruze 面精度损耗
# ================================================================
def ruze_loss_db(surface_rms_mm, freq_ghz):
    """Ruze：L(dB) = 10lg exp[(4πσ_ε/λ)²] = 4.343·(4πσ_ε/λ)²。"""
    s = to_f(surface_rms_mm, None)
    if s is None or s <= 0:
        return 0.0
    lam = lam_m(freq_ghz)
    return 4.3429448 * (4.0 * math.pi * (s / 1000.0) / lam) ** 2


# ================================================================
# 6 主入口：正向设计/校核
# ================================================================
def design(D_r, f, h, freq_ghz, d_feed=None, edge_taper_db=-12.0,
           feed_model="cosq", n_ap=65, n_spill=61, surface_rms_mm=None,
           want_pattern=True, cut_span=0.0, scan_theta=0.0, scan_phi=0.0,
           n_ff=45):
    """偏置反射面正向设计：几何 → 馈源 → 效率 → 增益 → 方向图 → 约束校核。

    d_feed=None → 由所需照射角反推推荐值；给定时按物理口径算实际馈源 θ3dB
    并校核是否覆盖反射面（照射不足/溢散过大）。
    """
    D_r, f, freq_ghz = to_f(D_r), to_f(f), to_f(freq_ghz, 20.0)
    if D_r <= 0 or f <= 0:
        return dict(ok=False, error="D_r 与 f 必须为正")
    h = max(to_f(h), 0.0)
    lam = lam_m(freq_ghz)
    g = geometry(D_r, f, h)
    d_psi = g["d_psi_deg"]
    # 锥削/馈源覆盖以**绑定半张角**（近边、远边中较大者）为设计点：
    # 偏置面照射角关于馈源轴不对称，按算术平均 Δψ 设计会使近边照射不足。
    psi_span = g["psi_span_deg"]

    # ---- 馈源模型参数 ----
    model = "gaussian" if str(feed_model).lower().startswith("gauss") else "cosq"
    d_feed_in = to_f(d_feed, None)
    if model == "gaussian":
        c = gauss_c_from_taper(edge_taper_db, psi_span)
        q = None
        th3_design = feed_theta3db_gauss(c)
    else:
        q = max(min(feed_q_from_taper(edge_taper_db, psi_span), 60.0), 0.05)
        c = None
        th3_design = feed_theta3db_cosq(q)

    # 馈源推荐口径：使其 −3dB 点落在反射面张角附近（θ3dB ≈ 2ψ_span 为宽松上限，
    # 工程上取 θ3dB 略大于 ψ_span，使边缘锥削落在 −10~−15dB）
    d_feed_rec = feed_diam_from_theta3(th3_design, freq_ghz)
    if d_feed_in is None or d_feed_in <= 0:
        d_feed = d_feed_rec
        feed_src = "反推（按目标锥削 %.0fdB @ ψ_span=%.2f°）" % (
            to_f(edge_taper_db, -12.0), psi_span)
        q_used, c_used = q, c
        th3_feed = th3_design
    else:
        d_feed = d_feed_in
        feed_src = "用户给定"
        # 用户口径 → 馈源实际 θ3dB → **由馈源自身 θ3dB 定 q/c**（此时边缘锥削是
        # 计算结果而非设计约束；不可反过来强设锥削，否则伪造馈源方向图）
        th3_feed = theta3_from_diam(d_feed, freq_ghz)
        if model == "gaussian":
            c_used = feed_c_from_theta3(th3_feed)
            q_used = None
        else:
            q_used = feed_q_from_theta3(th3_feed)
            c_used = None

    # ---- 效率（严格 2D 数值积分）----
    eta_ill, E_sum, E2_sum, A, peak_rel, n_pts = illumination_efficiency(
        D_r, f, h, freq_ghz, model, q_used, c_used, n=n_ap)
    eta_spill = spillover_efficiency(D_r, f, h, model, q_used, c_used,
                                     n=n_spill)
    eta_ap = eta_ill * eta_spill
    L_ruze = ruze_loss_db(surface_rms_mm, freq_ghz)
    eta_ap_r = eta_ap * (10.0 ** (-L_ruze / 10.0))

    # ---- 增益与波束宽度 ----
    G_dbi = 10.0 * math.log10(max(eta_ap_r * (math.pi * D_r / lam) ** 2, 1e-12))
    # θ3dB ≈ 70λ/D（度）——系数 70 ≈ (180/π)×1.22 已含弧度→度换算，勿再乘 180/π
    th3_classic = 70.0 * lam / D_r
    taper_act = edge_taper_actual(D_r, f, h, model, q_used, c_used)

    # ---- 方向图（真实照射分布）----
    ff = None
    th3_final = th3_classic
    if want_pattern:
        # cut 跨度自适应：大口径 θ3dB 很小，固定 ±6° 采样不足以分辨主瓣
        span = to_f(cut_span, 0.0)
        if span <= 0:
            span = max(3.0 * th3_classic, 0.2)
        try:
            ff = far_field(D_r, f, h, freq_ghz, model, q_used, c_used,
                           n=n_ff, cut_span=span, scan_theta=scan_theta,
                           scan_phi=scan_phi)
            if ff.get("ok") and ff.get("theta3db_deg"):
                th3_final = ff["theta3db_deg"]
        except Exception as e:                                          # noqa: BLE001
            ff = dict(ok=False, error=str(e))

    # ---- 交叉极化（偏置面特征，工程界）----
    # 理想照射偏置抛物面，轴上交叉极化鉴别率 XPD ≈ 20lg(4f/D_r)（Ludwig-3 口径积分界）
    xpd = 20.0 * math.log10(max(4.0 * f / D_r, 1e-6))

    # ---- 约束校验 ----
    checks = []

    def chk(name, ok, got, need, note):
        checks.append(dict(name=name, ok=bool(ok), got=str(got), need=str(need),
                           note=note))

    K = CONSTRAINTS
    fd_lo, fd_hi = K["f_over_d"]
    te_lo, te_hi = K["edge_taper_range"]
    chk("F/D 在工程区间", fd_lo <= g["f_over_d"] <= fd_hi,
        fmt(g["f_over_d"], 3), "%.1f~%.1f" % (fd_lo, fd_hi),
        "F/D<%.1f 馈源难做/像差大；>%.1f 结构笨重、溢散增" % (fd_lo, fd_hi))
    chk("偏置间隙（反射面不跨母轴）", g["h_near_m"] >= K["h_min_gap_m"],
        fmt(g["h_near_m"] * 1000, 1) + " mm",
        "≥ %.0f mm" % (K["h_min_gap_m"] * 1000),
        "h<D_r/2 时反射面跨母轴 → 馈源/支杆遮挡主面（偏置面优势丧失）")
    # 锥削设计比 ratio = ψ_span / (θ3dB/2)：rim 落在馈源 −3dB 半角的几倍处
    #   ratio≈1.5 → 边缘锥削 ≈−12dB（工程最佳）；<1 → 波束过宽溢散大；>2.5 → 锥削过深 η_ill 低
    # 注意量纲：θ3dB 是**全宽**、ψ_span 是**半角**，必须除以 2 才是同一口径。
    ratio = psi_span / max(th3_feed / 2.0, 1e-9)
    chk("锥削设计比 ψ_span/(θ3dB/2) 在工程区间", 0.95 <= ratio <= 2.5,
        fmt(ratio, 3), "0.95~2.50（≈1.5 对应 −12dB）",
        "rim 张角 ψ_span=%.2f°（半角）vs 馈源 −3dB 半角 %.2f°；比值决定边缘锥削深度"
        % (psi_span, th3_feed / 2.0))
    chk("边缘锥削在合理区间", te_lo <= taper_act <= te_hi,
        fmt(taper_act, 1) + " dB", "%.0f~%.0f dB" % (te_lo, te_hi),
        "锥削过浅(>%.0fdB)溢散大；过深(<%.0fdB)口径利用低" % (te_hi, te_lo))
    chk("溢散效率 η_spill", eta_spill >= K["eta_spill_min"],
        fmt(eta_spill * 100, 1) + " %", "≥ %.0f %%" % (K["eta_spill_min"] * 100),
        "η_spill 低 → 增大馈源照射角或减小 F/D")
    chk("口径照射效率 η_ill", eta_ill >= K["eta_ill_min"],
        fmt(eta_ill * 100, 1) + " %", "≥ %.0f %%" % (K["eta_ill_min"] * 100),
        "η_ill 低 → 锥削过深，减小边缘锥削或加大馈源照射角")
    if surface_rms_mm:
        chk("面精度损耗（Ruze）", L_ruze <= K["ruze_max_db"],
            fmt(L_ruze, 2) + " dB", "≤ %.1f dB" % K["ruze_max_db"],
            "σ_ε=%.2fmm @ %.1fGHz（λ=%.2fmm）"
            % (surface_rms_mm, freq_ghz, lam * 1000))
    n_fail = sum(1 for c_ in checks if not c_["ok"])

    advice = []
    # 馈源物理方向：d_feed↑ → θ3dB↓（波束变窄）→ rim 处锥削变深 → η_ill↓、η_spill↑
    # d_feed_rec = 按目标锥削（默认 −12dB）在 rim 张角 ψ_span 处反推的推荐口径。
    if ratio < 0.95:
        advice.append("馈源波束过宽（锥削设计比 %.2f<0.95）→ rim 落在 −3dB 内、能量溢出，"
                      "η_spill=%.1f%%；增大 d_feed 收窄波束到约 %.4fm（θ3dB→%.1f°）"
                      % (ratio, eta_spill * 100, d_feed_rec, th3_design))
    elif ratio > 2.5:
        advice.append("馈源波束过窄（锥削设计比 %.2f>2.5）→ rim 锥削 %.1fdB 过深、"
                      "η_ill=%.1f%%；减小 d_feed 展宽波束到约 %.4fm（θ3dB→%.1f°）"
                      % (ratio, taper_act, eta_ill * 100, d_feed_rec, th3_design))
    if eta_spill < K["eta_spill_min"] and ratio >= 0.95:
        advice.append("溢散效率 %.1f%% 偏低 → 减小 F/D（当前 %.2f，缩到 %.2f 使 rim 张角变小）"
                      % (eta_spill * 100, g["f_over_d"], g["f_over_d"] * 0.85))
    if eta_ill < K["eta_ill_min"] and ratio <= 2.5:
        advice.append("口径照射效率 %.1f%% 偏低（边缘锥削 %.1fdB）→ 减浅锥削到 −10dB"
                      % (eta_ill * 100, taper_act))
    if taper_act > te_hi:
        advice.append("边缘锥削 %.1fdB 过浅（>%.0fdB）→ 溢散增大；增大 d_feed 收窄波束"
                      % (taper_act, te_hi))
    if g["h_near_m"] < K["h_min_gap_m"]:
        advice.append("偏置不足：h=%.4fm < D_r/2=%.4fm → 反射面跨母轴，"
                      "建议 h≥%.4fm（保留 %.0fmm 间隙）"
                      % (h, g["a"], g["a"] + K["h_min_gap_m"],
                         K["h_min_gap_m"] * 1000))

    res = dict(
        ok=True,
        inputs=dict(D_r=D_r, f=f, h=h, d_feed=d_feed, freq_ghz=freq_ghz,
                    edge_taper_db=edge_taper_db, feed_model=model,
                    surface_rms_mm=surface_rms_mm,
                    scan_theta_deg=scan_theta, scan_phi_deg=scan_phi),
        geom=g, lam_m=lam,
        feed=dict(model=model,
                  q=round(q_used, 3) if q_used is not None else None,
                  c_gauss=round(c_used, 4) if c_used is not None else None,
                  theta3db_deg=round(th3_feed, 3),
                  theta3db_design_deg=round(th3_design, 3),
                  psi_span_deg=round(psi_span, 3),
                  span_near_deg=round(g["span_near_deg"], 3),
                  span_far_deg=round(g["span_far_deg"], 3),
                  d_feed_m=round(d_feed, 5), d_feed_rec_m=round(d_feed_rec, 5),
                  source=feed_src, tilt_deg=round(g["psi0_deg"], 3),
                  edge_taper_actual_db=round(taper_act, 2),
                  d_psi_deg=round(d_psi, 3)),
        eff=dict(eta_ill=round(eta_ill, 4), eta_spill=round(eta_spill, 4),
                 eta_ap=round(eta_ap, 4), ruze_db=round(L_ruze, 3),
                 eta_ap_with_ruze=round(eta_ap_r, 4), A_m2=round(A, 4),
                 peak_rel=round(peak_rel, 5), n_points=n_pts,
                 formula=("η_ill=|∫E dA|²/(A∫|E|²dA)；η_spill=∫_ref|F|²dΩ/∫_4π|F|²dΩ；"
                          "η_ap=η_ill·η_spill（偏置面无遮挡）")),
        perf=dict(G_dbi=round(G_dbi, 2), theta3db_deg=round(th3_final, 4),
                  theta3db_classic_deg=round(th3_classic, 4),
                  xpd_dB=round(xpd, 1),
                  G_formula="G=10lg[η_ap·(πD_r/λ)²]−L_Ruze",
                  th3_formula="θ3dB=70λ/D_r（口径积分实测优先）",
                  xpd_formula="XPD≈20lg(4f/D_r)（偏置面轴上交叉极化界）"),
        checks=checks, n_fail=n_fail, feasible=(n_fail == 0),
        advice=advice,
        verdict=("偏置反射面设计可行：D_r=%.4gm、f=%.4gm、h=%.4gm（F/D=%.2f、"
                 "ψ0=%.2f°）、馈源 φ%.4gm（θ3dB=%.2f°，%s），η_ap=%.1f%%"
                 "（照射 %.1f%%×溢散 %.1f%%），G=%.2fdBi、θ3dB=%.3f°、XPD≈%.0fdB"
                 % (D_r, f, h, g["f_over_d"], g["psi0_deg"], d_feed, th3_feed,
                    feed_src, eta_ap * 100, eta_ill * 100, eta_spill * 100,
                    G_dbi, th3_final, xpd)
                 if n_fail == 0 else
                 "偏置反射面设计有 %d 项约束未满足：%s"
                 % (n_fail, "；".join(c_["name"] for c_ in checks if not c_["ok"]))),
    )
    if ff:
        res["pattern"] = ff
    return res


# ================================================================
# 7 反解设计：口径 + 目标波束宽度 + 锥削 → f / h / d_feed
# ================================================================
def synthesize(D_r=None, theta3db_target_deg=None, freq_ghz=20.0,
               edge_taper_db=-12.0, f_over_d=1.0, h_over_d=0.55,
               feed_model="cosq", n_ap=55, surface_rms_mm=None):
    """由目标波束宽度反推反射面几何与馈源（D_r 或 θ3dB 至少给一个）。

    · θ3dB ≈ 70λ/D_r → 反解所需口径 D_need
    · F/D 取 f_over_d（偏置面常用 0.8~1.3，默认 1.0）
    · h/D 取 h_over_d（默认 0.55 → 近边留 5%·D_r 间隙，避免跨母轴）
    · 馈源口径由照射角 2Δψ 反推
    给出 D_r 时校核能否达成目标；未给 D_r 时按 D_need 直接定口径。
    """
    freq_ghz = to_f(freq_ghz, 20.0)
    lam = lam_m(freq_ghz)
    th3_t = to_f(theta3db_target_deg, None)
    D_in = to_f(D_r, None)
    if th3_t and th3_t > 0:
        D_need = 70.0 * lam / th3_t          # θ3dB≈70λ/D（度）→ D=70λ/θ3dB
    elif D_in:
        D_need = D_in
        th3_t = 70.0 * lam / D_in
    else:
        return dict(ok=False, error="D_r 与 theta3db_target_deg 至少给一个")
    D_use = D_in if (D_in and D_in > 0) else D_need
    d_ok = (D_use >= D_need * 0.98) if th3_t else True
    fd = to_f(f_over_d, 1.0)
    hd = to_f(h_over_d, 0.55)
    f = fd * D_use
    h = hd * D_use
    r = design(D_use, f, h, freq_ghz, None, edge_taper_db, feed_model,
               n_ap=n_ap, surface_rms_mm=surface_rms_mm)
    if not r.get("ok"):
        return r
    r["synth"] = dict(
        theta3db_target_deg=th3_t, D_need_m=round(D_need, 4),
        D_r_used_m=round(D_use, 4), D_r_ok=bool(d_ok),
        f_over_d_used=fd, h_over_d_used=hd,
        f_m=round(f, 4), h_m=round(h, 4),
        d_feed_m=r["feed"]["d_feed_m"],
        note=("目标 θ3dB=%s° → 需口径 D_r≥%.4fm（70λ/D 准则，λ=%.4fmm）；"
              "取 F/D=%.2f → f=%.4fm；取 h/D=%.2f → h=%.4fm（近边间隙 %.1fmm，"
              "不跨母轴）；馈源 φ%.4fm（θ3dB=%.2f° 覆盖绑定照射角 ψ_span=%.2f°）%s")
        % (fmt(th3_t, 3), D_need, lam * 1000, fd, f, hd, h,
           max(h - D_use / 2, 0) * 1000, r["feed"]["d_feed_m"],
           r["feed"]["theta3db_deg"], r["feed"]["psi_span_deg"],
           "" if d_ok else "；给定 D_r=%.4fm 不足 → 实际波束宽度将大于目标"
           % D_use))
    return r


# ================================================================
# 8 自检（含解析对照，验证数值积分正确性）
# ================================================================
def _selftest():
    print("=== reflector_engine selftest ===")
    ok = fail = 0

    def chk(name, cond, info=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print("  PASS %s %s" % (name, info))
        else:
            fail += 1
            print("  FAIL %s %s" % (name, info))

    lam = lam_m(20.0)
    chk("波长 λ(20GHz)=15mm", abs(lam - 0.014989623) < 1e-6, "λ=%.6f m" % lam)

    # --- 几何：抛物面张角性质 ψ=2atan(ρ/2f) ---
    g = geometry(2.5, 3.275, 1.8975)          # F/D=1.31, h/D=0.759（GRASP 验证案例比例）
    chk("F/D=1.31", abs(g["f_over_d"] - 1.31) < 1e-6, "%.4f" % g["f_over_d"])
    chk("h/D=0.759", abs(g["h_over_d"] - 0.759) < 1e-6, "%.4f" % g["h_over_d"])
    # ψ0 = 2atan(h/2f) = 2atan(1.8975/6.55)
    psi0_ref = 2.0 * math.degrees(math.atan(1.8975 / 6.55))
    chk("馈源轴倾斜 ψ0=2atan(h/2f)", abs(g["psi0_deg"] - psi0_ref) < 1e-9,
        "ψ0=%.4f° (ref %.4f°)" % (g["psi0_deg"], psi0_ref))
    # 严格自洽：馈源轴指向反射面几何中心 → 中心点 ψ′ 必为 0
    psi_ctr, r_ctr = _psi_prime(g["h"], 0.0, 0.0, g["f"], g["feed_axis"])
    chk("馈源轴过反射面中心（ψ′_center≈0）", psi_ctr < 1e-4,
        "ψ′(center)=%.2e°（acos 浮点极限）" % psi_ctr)
    chk("中心点 r = r_c（焦半径）", abs(r_ctr - g["r_c"]) < 1e-9,
        "r=%.6f r_c=%.6f" % (r_ctr, g["r_c"]))
    # 偏置面照射角非对称（近边张角 > 远边张角）
    chk("照射角非对称性（近边张角>远边）",
        g["span_near_deg"] > g["span_far_deg"],
        "近边 %.3f° / 远边 %.3f° → 绑定 ψ_span=%.3f°"
        % (g["span_near_deg"], g["span_far_deg"], g["psi_span_deg"]))
    chk("绑定半张角 ψ_span=|ψ0−ψ_near|",
        abs(g["psi_span_deg"] - abs(g["psi0_deg"] - g["psi_near_deg"])) < 1e-9,
        "ψ_span=%.4f°" % g["psi_span_deg"])
    # 焦点到反射面中心距 = f + h²/(4f)（抛物线焦半径性质）
    r_c_ref = 3.275 + 1.8975 ** 2 / (4 * 3.275)
    chk("焦半径 r_c=f+ρ²/4f", abs(g["r_c"] - r_c_ref) < 1e-9,
        "r_c=%.5f (ref %.5f)" % (g["r_c"], r_c_ref))
    chk("照射角 ψ_near=2atan(ρ_near/2f)",
        abs(g["psi_near_deg"] - 2 * math.degrees(math.atan(0.6475 / 6.55))) < 1e-9,
        "%.4f°" % g["psi_near_deg"])

    # --- 馈源模型 ---
    q = feed_q_from_taper(-12.0, 20.0)
    chk("cos^q 反解：Δψ=20°/Te=−12dB → q", abs(feed_amp("cosq", 20.0, q) ** 2 - 1) < 1e-9
        or abs(20 * math.log10(feed_amp("cosq", 20.0, q)) + 12.0) < 1e-6,
        "q=%.4f，20lg F(20°)=%.4f dB" % (q, 20 * math.log10(feed_amp("cosq", 20.0, q))))
    th3f = feed_theta3db_cosq(q)
    chk("cos^q θ3dB=2acos(0.5^(1/q))", abs(th3f - 2 * math.degrees(math.acos(0.5 ** (1 / q)))) < 1e-9,
        "θ3dB=%.4f°" % th3f)
    d_rec = feed_diam_from_theta3(th3f, 20.0)
    chk("馈源口径↔θ3dB 互逆", abs(theta3_from_diam(d_rec, 20.0) - th3f) < 1e-9,
        "d=%.5fm → θ3dB=%.4f°" % (d_rec, theta3_from_diam(d_rec, 20.0)))

    # --- 效率：正馈极限对照（h→0 退化为正馈，η_ill 应接近 cos^q 圆口径解析值）---
    # 正馈对称照射 cos^q(ψ) 在抛物面上，η_ill 解析 = [∫₀^A t(ρ)ρdρ]²/(A²/2·∫t²ρdρ)
    # 这里做「数值 vs 更细网格」收敛性检验（自洽性）
    e1, *_ = illumination_efficiency(2.5, 3.275, 1.8975, 20.0, "cosq", q, None, n=41)
    e2, *_ = illumination_efficiency(2.5, 3.275, 1.8975, 20.0, "cosq", q, None, n=81)
    chk("η_ill 网格收敛（41 vs 81）", abs(e1 - e2) < 0.01,
        "η(41)=%.4f η(81)=%.4f Δ=%.4f" % (e1, e2, abs(e1 - e2)))
    chk("η_ill 在物理区间 (0.5,1]", 0.5 < e2 <= 1.0, "η_ill=%.4f" % e2)

    s1 = spillover_efficiency(2.5, 3.275, 1.8975, "cosq", q, None, n=41)
    s2 = spillover_efficiency(2.5, 3.275, 1.8975, "cosq", q, None, n=101)
    chk("η_spill 网格收敛（41 vs 101）", abs(s1 - s2) < 0.02,
        "η(41)=%.4f η(101)=%.4f Δ=%.4f" % (s1, s2, abs(s1 - s2)))
    chk("η_spill 在物理区间 (0.5,1]", 0.5 < s2 <= 1.0, "η_spill=%.4f" % s2)

    # --- η_spill 解析对照：馈源旋转对称时 ∫_4π|F|²dΩ = 2π∫cos^2q(ψ)sinψ dψ = 2π/(2q+1)
    m = 200001
    dpsi = math.pi / (m - 1)
    # 注：馈源 cos^q 在 ψ>90°（背向）时 cos<0，非整数幂会出复数 → 物理上背向幅值为 0，须钳制
    tot = 0.0
    for i in range(0, m, 20):                     # 粗采样对照（够验量级）
        psi = dpsi * i
        w = 0.5 if (i == 0 or i >= m - 20) else 1.0
        tot += w * (max(math.cos(psi), 0.0) ** (2 * q)) * math.sin(psi) * dpsi * 20
    tot *= 2 * math.pi
    tot_ref = 2 * math.pi / (2 * q + 1)
    chk("全空间积分 ∫|F|²dΩ = 2π/(2q+1) 解析对照",
        abs(tot - tot_ref) / tot_ref < 0.05,
        "数值=%.5f 解析=%.5f 偏差=%.2f%%" % (tot, tot_ref, 100 * abs(tot - tot_ref) / tot_ref))

    # --- 完整设计（GRASP 验证案例比例，−12dB 锥削）---
    r = design(2.5, 3.275, 1.8975, 20.0, None, -12.0, "cosq", n_ap=81, n_spill=101)
    print("  [case A] D_r=2.5m f=3.275m h=1.8975m @20GHz Te=−12dB")
    print("    ψ0=%.3f° 照射 %.3f~%.3f° 绑定ψ_span=%.3f°（近%.3f/远%.3f）" %
          (r["geom"]["psi0_deg"], r["geom"]["psi_near_deg"],
           r["geom"]["psi_far_deg"], r["geom"]["psi_span_deg"],
           r["geom"]["span_near_deg"], r["geom"]["span_far_deg"]))
    print("    馈源 q=%s θ3dB=%.3f°（绑定ψ_span=%.3f°）d_feed=%.5fm" %
          (r["feed"]["q"], r["feed"]["theta3db_deg"],
           r["feed"]["psi_span_deg"], r["feed"]["d_feed_m"]))
    print("    η_ill=%.4f η_spill=%.4f η_ap=%.4f" %
          (r["eff"]["eta_ill"], r["eff"]["eta_spill"], r["eff"]["eta_ap"]))
    print("    G=%.2fdBi θ3dB=%.4f°（经典 %.4f°）XPD=%.1fdB" %
          (r["perf"]["G_dbi"], r["perf"]["theta3db_deg"],
           r["perf"]["theta3db_classic_deg"], r["perf"]["xpd_dB"]))
    print("    实际边缘锥削=%.2fdB  约束 fail=%d" %
          (r["feed"]["edge_taper_actual_db"], r["n_fail"]))
    chk("η_ap = η_ill × η_spill（未舍入口径）",
        abs(r["eff"]["eta_ap_with_ruze"] - r["eff"]["eta_ap"]) < 1e-9
        and abs(r["eff"]["eta_ap"] - round(r["eff"]["eta_ill"] * r["eff"]["eta_spill"], 4)) < 2e-4,
        "η_ap=%.4f = %.4f×%.4f" % (r["eff"]["eta_ap"], r["eff"]["eta_ill"],
                                    r["eff"]["eta_spill"]))
    chk("增益量级合理（2.5m@20GHz，G>45dBi）", r["perf"]["G_dbi"] > 45,
        "G=%.2fdBi" % r["perf"]["G_dbi"])
    chk("增益不超过理想上限 η=1", r["perf"]["G_dbi"] <
        10 * math.log10((math.pi * 2.5 / lam) ** 2),
        "G=%.2f < 理想 %.2f" % (r["perf"]["G_dbi"],
                                10 * math.log10((math.pi * 2.5 / lam) ** 2)))
    chk("θ3dB 与经典 70λ/D 同量级（±30%）",
        0.7 * r["perf"]["theta3db_classic_deg"] < r["perf"]["theta3db_deg"]
        < 1.3 * r["perf"]["theta3db_classic_deg"],
        "实测 %.4f° vs 经典 %.4f°" % (r["perf"]["theta3db_deg"],
                                      r["perf"]["theta3db_classic_deg"]))
    chk("实际边缘锥削≈目标（rim 最差 −12~−16dB）",
        -20.0 <= r["feed"]["edge_taper_actual_db"] <= -8.0,
        "%.2f dB" % r["feed"]["edge_taper_actual_db"])
    chk("η_ill 物理合理（≥0.70）", r["eff"]["eta_ill"] >= 0.70,
        "%.4f" % r["eff"]["eta_ill"])
    chk("η_spill 物理合理（≥0.85）", r["eff"]["eta_spill"] >= 0.85,
        "%.4f" % r["eff"]["eta_spill"])

    # --- 方向图 ---
    ff = r.get("pattern")
    chk("方向图已生成", bool(ff) and ff.get("ok", False),
        "" if not ff else "点数=%d" % ff.get("n_points", 0))
    if ff and ff.get("ok"):
        chk("方向图峰值归一 0dB", abs(max(ff["cut_e_dbr"])) < 1e-6,
            "max=%.6f" % max(ff["cut_e_dbr"]))
        chk("主瓣在 boresight（|θ_peak|<0.5°）",
            abs(ff["cut_theta"][max(range(len(ff["cut_e_dbr"])),
                                    key=lambda i: ff["cut_e_dbr"][i])]) < 0.5,
            "")
        chk("θ3dB(E面) 为正且 <1°", 0 < (ff["theta3db_e_deg"] or 0) < 1.0,
            "E面 %.4f° / H面 %.4f°" % (ff["theta3db_e_deg"] or 0,
                                        ff["theta3db_h_deg"] or 0))
        chk("首旁瓣 < −10dBr", (ff["first_sidelobe_dbr"] or 0) < -10.0,
            "%.2f dBr" % (ff["first_sidelobe_dbr"] or 0))

    # --- 反解设计 ---
    s = synthesize(D_r=2.5, theta3db_target_deg=0.3, freq_ghz=20.0)
    print("  [case B] 反解：D_r=2.5m 目标 θ3dB=0.3° @20GHz")
    print("    %s" % s["synth"]["note"])
    print("    G=%.2fdBi θ3dB=%.4f° η_ap=%.4f fail=%d" %
          (s["perf"]["G_dbi"], s["perf"]["theta3db_deg"],
           s["eff"]["eta_ap"], s["n_fail"]))
    chk("反解 D_need 与 70λ/θ3dB 一致",
        abs(s["synth"]["D_need_m"] - 70 * lam / 0.3) < 1e-3,
        "D_need=%.4fm" % s["synth"]["D_need_m"])
    chk("反解口径不足被如实标记", s["synth"]["D_r_ok"] is False,
        "D_r=2.5 < D_need=%.3f → ok=%s" % (s["synth"]["D_need_m"],
                                            s["synth"]["D_r_ok"]))
    chk("反解 F/D 生效", abs(s["geom"]["f_over_d"] - 1.0) < 1e-6,
        "F/D=%.3f" % s["geom"]["f_over_d"])
    chk("反解 h 不跨母轴", s["geom"]["h_near_m"] >= 0.02,
        "h_near=%.1fmm" % (s["geom"]["h_near_m"] * 1000))

    # --- 由 θ3dB 直接定口径（不给 D_r）---
    s2 = synthesize(theta3db_target_deg=0.3, freq_ghz=20.0, f_over_d=1.0)
    chk("无 D_r 时按 D_need 定口径",
        abs(s2["inputs"]["D_r"] - s2["synth"]["D_need_m"]) < 1e-3,
        "D_r=%.4fm vs D_need=%.4fm" % (s2["inputs"]["D_r"],
                                        s2["synth"]["D_need_m"]))
    chk("定口径后波束宽度≈目标（±20%）",
        0.8 * 0.3 <= s2["perf"]["theta3db_deg"] <= 1.2 * 0.3,
        "θ3dB=%.4f° (目标 0.3°)" % s2["perf"]["theta3db_deg"])

    # --- Ruze ---
    chk("Ruze 损耗 σ=0.5mm@20GHz", abs(ruze_loss_db(0.5, 20.0) -
        4.3429448 * (4 * math.pi * 0.0005 / lam) ** 2) < 1e-9,
        "%.4f dB" % ruze_loss_db(0.5, 20.0))
    chk("Ruze 无面精度=0dB", ruze_loss_db(None, 20.0) == 0.0, "")

    # --- 约束检出能力（坏几何必须报警）---
    bad = design(2.5, 3.275, 0.5, 20.0, None, -12.0, "cosq", n_ap=41,
                 want_pattern=False)      # h=0.5 < a=1.25 → 跨母轴
    chk("跨母轴偏置被检出", any("偏置间隙" in c["name"] and not c["ok"]
                                for c in bad["checks"]),
        "h=0.5m, h_near=%.1fmm" % (bad["geom"]["h_near_m"] * 1000))
    bad2 = design(2.5, 6.0, 1.9, 20.0, 0.005, -12.0, "cosq", n_ap=41,
                  want_pattern=False)     # 馈源口径 5mm 太小
    chk("馈源口径过小被检出", bad2["n_fail"] > 0,
        "fail=%d: %s" % (bad2["n_fail"],
                         "；".join(c["name"] for c in bad2["checks"] if not c["ok"])))

    # --- 高斯馈源路径 ---
    rg = design(2.5, 3.275, 1.8975, 20.0, None, -12.0, "gaussian", n_ap=61,
                n_spill=81, want_pattern=False)
    chk("高斯馈源路径可算且 η_ap 合理",
        0.3 < rg["eff"]["eta_ap"] <= 1.0,
        "η_ap=%.4f (ill=%.4f spill=%.4f)" % (rg["eff"]["eta_ap"],
                                              rg["eff"]["eta_ill"],
                                              rg["eff"]["eta_spill"]))

    print("\nRESULT: PASS ok=%d fail=%d" % (ok, fail))
    print("reflector_engine selftest: %s" % ("ALL PASS" if fail == 0 else "HAS FAILURES"))
    return fail == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
