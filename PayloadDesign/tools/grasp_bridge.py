# -*- coding: utf-8 -*-
"""GRASP 天线仿真桥 —— 按天线选型调用 TICRA GRASP 产生远场方向图与性能指标。

调用链（对齐 D:\\ZWL\\Traework\\AI_Grasp\\mcp_interface 约定）：
  1. find_grasp()      读 grasp_config.json 定位 ticra-tools.exe（解析 {grasp_root} 占位符）
  2. build_model()     按口径 D/频率/焦距生成 .tor(对象)+.tci(命令,CRLF)+.gxp(batch入口)
                       —— 偏馈抛物面 + 焦点高斯馈源 + PO 法（验证过的 2.4m@14GHz 几何按比例缩放）
  3. run_grasp()       干净子目录 subprocess 求解，解析 .cut 远场
  4. beam_performance()编排：优先 GRASP 实测，失败/不可用→口径天线解析方向图（Airy）降级，标注来源

科学口径：
  · 峰值增益 G0 = η·(πD/λ)²（口径天线基本公式）
  · θ3dB 由方向图 -3dB 交点实测/实算，不套近似公式（保证自洽）
  · 偏馈几何 F/D=1.31、offset=0.759D、馈源在焦点（与 AI_Grasp 验证案例同构）
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import time

# ---------------- 配置 ----------------
GRASP_CFG_CANDIDATES = [
    r"D:\ZWL\Traework\AI_Grasp\AI_Grasp\mcp_interface\grasp_config.json",
    r"D:\ZWL\Traework\AI_Grasp\mcp_interface\grasp_config.json",
]
SOLVER_FALLBACKS = [
    r"D:\Program Files\TICRA\TICRA-Tools-19.0\bin\ticra-tools.exe",
    r"C:\Program Files\TICRA\TICRA-Tools-19.0\bin\ticra-tools.exe",
]
F_OVER_D = 1.31          # 母抛物面焦距比（验证案例 3.144/2.4）
OFFSET_RATIO = 0.759     # 反射面偏置比 h/D（验证案例 1.82131/2.4）
EDGE_TAPER_DB = -12.0    # 馈源边缘照射电平
DEFAULT_ETA = 0.65       # 口径效率（解析降级用）
C_M_S = 299792458.0


# ---------------- Bessel J1（Abramowitz-Stegun 9.4.4，无第三方依赖） ----------------
def _j1(x):
    ax = abs(x)
    if ax < 8.0:
        y = x * x
        ans1 = x * (72362614232.0 + y * (-7895059235.0 + y * (242396853.1
              + y * (-2972611.439 + y * (15704.48260 + y * (-30.16036606))))))
        ans2 = 144725228442.0 + y * (2300535178.0 + y * (18583304.74
              + y * (99447.43394 + y * (376.9991397 + y * 1.0))))
        ans = ans1 / ans2
    else:
        z = 8.0 / ax
        y = z * z
        xx = ax - 2.356194491
        ans1 = 1.0 + y * (0.183105e-2 + y * (-0.3516396496e-4
              + y * (0.2457520174e-5 + y * (-0.240337019e-6))))
        ans2 = 0.04166666667 + y * (-0.1098628627e-2 + y * (0.2734510407e-4
              + y * (-0.2073370639e-5 + y * 0.2093887211e-6)))
        ans = math.sqrt(0.636619772 / ax) * (math.cos(xx) * ans1 - z * math.sin(xx) * ans2)
    return ans if x >= 0 else -ans


def _airy_db(u):
    """均匀圆口径归一化功率方向图 20log10|2J1(u)/u|（u=0→0dB）。"""
    if abs(u) < 1e-9:
        return 0.0
    f = 2.0 * _j1(u) / u
    if abs(f) < 1e-12:
        return -120.0
    return 20.0 * math.log10(abs(f))


# ---------------- 定位 GRASP ----------------
def find_grasp():
    """返回 (solver_path 或 None, 诊断信息 dict)。"""
    info = {"config": None, "grasp_root": None, "solver": None, "exists": False}
    root = None
    for c in GRASP_CFG_CANDIDATES:
        if os.path.exists(c):
            info["config"] = c
            try:
                with open(c, "r", encoding="utf-8") as f:
                    cfgj = json.load(f)
                root = cfgj.get("grasp_root")
                info["grasp_root"] = root
                solver = (cfgj.get("solver") or "{grasp_root}/bin/ticra-tools.exe")
                solver = solver.replace("{grasp_root}", root or "").replace("/", os.sep)
                if os.path.exists(solver):
                    info["solver"] = solver
                    info["exists"] = True
                    return solver, info
            except Exception as e:                     # noqa: BLE001
                info["error"] = repr(e)
            break
    for s in SOLVER_FALLBACKS:
        if os.path.exists(s):
            info["solver"] = s
            info["exists"] = True
            return s, info
    return None, info


# ---------------- 几何（偏馈抛物面，按比例缩放验证案例） ----------------
def _geometry(D, freq_ghz):
    f = F_OVER_D * D                 # 母抛物面焦距
    h = OFFSET_RATIO * D             # 反射面偏置
    z_c = h ** 2 / (4 * f)           # 边缘中心在抛物面上的高度
    center = (h, 0.0, z_c)
    focus = (0.0, 0.0, f)
    dx = center[0] - focus[0]
    dz = center[2] - focus[2]
    dist = math.sqrt(dx ** 2 + dz ** 2)
    zx, zz = dx / dist, dz / dist
    x_axis = (-zz, 0.0, zx)
    taper = math.degrees(math.atan((D / 2) / dist))
    return dict(f=f, h=h, z_c=z_c, focus=focus, center=center,
                dist=dist, zx=zx, zz=zz, x_axis=x_axis, taper=taper)


def lam_m(freq_ghz):
    return C_M_S / (freq_ghz * 1e9)


def peak_gain_dbi(D, freq_ghz, eta=DEFAULT_ETA):
    lam = lam_m(freq_ghz)
    return 10.0 * math.log10(eta * (math.pi * D / lam) ** 2)


# ---------------- 解析方向图（降级路径） ----------------
def analytic_pattern(D, freq_ghz, eta=DEFAULT_ETA, span_deg=None, np_theta=361):
    lam = lam_m(freq_ghz)
    kD = math.pi * D / lam
    th3_est = math.degrees(1.02 * lam / D)            # 均匀口径 -3dB 近似（仅用于定标度范围）
    if span_deg is None:
        span_deg = max(6.0 * th3_est, 2.0)
        span_deg = min(span_deg, 30.0)
    thetas = [(-span_deg + 2 * span_deg * i / (np_theta - 1)) for i in range(np_theta)]
    gain_dbr = []
    for th in thetas:
        u = kD * math.sin(math.radians(th))
        gain_dbr.append(_airy_db(u))
    g0 = peak_gain_dbi(D, freq_ghz, eta)
    th3 = _beamwidth_from(thetas, gain_dbr, 3.0)
    edge = _edge_level(thetas, gain_dbr, th3)
    return dict(source="analytic", ok=True,
                peak_gain_dbi=round(g0, 2), beamwidth_3db_deg=round(th3, 3),
                coverage_edge_dbr=round(edge, 2), theta=thetas, gain_dbr=gain_dbr,
                freq_ghz=freq_ghz, D_m=D, eta=eta,
                note=f"解析口径方向图（Airy，η={eta}）：G0=η(πD/λ)²={g0:.1f}dBi；GRASP 不可用时的工程估算")


def _beamwidth_from(thetas, dbr, level=3.0):
    """从方向图找主瓣 -level dB 全宽（度）。"""
    ipk = max(range(len(dbr)), key=lambda i: dbr[i])
    # 向左
    li = ipk
    while li > 0 and dbr[li] > -level:
        li -= 1
    ri = ipk
    while ri < len(dbr) - 1 and dbr[ri] > -level:
        ri += 1

    def cross(i0, i1):
        # 线性插值找 -level 交点
        y0, y1 = dbr[i0], dbr[i1]
        x0, x1 = thetas[i0], thetas[i1]
        if y1 == y0:
            return x1
        return x0 + (-level - y0) * (x1 - x0) / (y1 - y0)

    left = cross(li, li + 1) if li < ipk else thetas[li]
    right = cross(ri - 1, ri) if ri > ipk else thetas[ri]
    return abs(right - left)


def _edge_level(thetas, dbr, th3, cov_factor=1.75):
    """覆盖边缘电平：θ=cov_factor×(θ3dB/2) 处的相对电平（波束覆盖区边缘典型取值）。"""
    th_edge = cov_factor * th3 / 2.0
    best = min(range(len(thetas)), key=lambda i: abs(thetas[i] - th_edge))
    return dbr[best]


# ---------------- GRASP 模型生成 ----------------
def build_model(workdir, D, freq_ghz, tag="beam", span_deg=None, np_theta=401):
    g = _geometry(D, freq_ghz)
    lam = lam_m(freq_ghz)
    th3_est = math.degrees(1.02 * lam / D)
    if span_deg is None:
        span_deg = min(max(5.0 * th3_est, 2.0), 30.0)
    tor_name = f"ant_{tag}.tor"
    tci_name = f"ant_{tag}.tci"
    gxp_name = f"batch_{tag}.gxp"
    cut_name = f"far_field_{tag}.cut"

    L = []
    L.append(f"// PayloadDesign auto-model: offset reflector D={D}m @ {freq_ghz}GHz")
    L.append(f"// F/D={F_OVER_D}, offset h={g['h']:.4f}m, feed at focus, taper {EDGE_TAPER_DB}dB")
    L.append("global_coor  coor_sys")
    L.append("(")
    L.append(")")
    L.append("")
    L.append("freq  frequency")
    L.append("(")
    L.append(f"  frequency_list : sequence({freq_ghz} GHz)")
    L.append(")")
    L.append("")
    L.append("reflector_surface  paraboloid")
    L.append("(")
    L.append(f"  focal_length : {g['f']:.4f} m")
    L.append(")")
    L.append("")
    L.append("reflector_rim  elliptical_rim")
    L.append("(")
    L.append(f"  centre : struct(x: {g['h']:.5f} m, y: 0.0 m),")
    L.append(f"  half_axis : struct(x: {D/2:.3f} m, y: {D/2:.3f} m)")
    L.append(")")
    L.append("")
    L.append("reflector  reflector")
    L.append("(")
    L.append("  coor_sys : ref(global_coor),")
    L.append("  surfaces : sequence(ref(reflector_surface)),")
    L.append("  rim : ref(reflector_rim),")
    L.append("  centre_hole_radius : 0.0 m")
    L.append(")")
    L.append("")
    L.append("feed_coor_1  coor_sys")
    L.append("(")
    L.append(f"  origin : struct(x: {g['focus'][0]:.8f} m, y: {g['focus'][1]:.8f} m, z: {g['focus'][2]:.8f} m),")
    L.append(f"  x_axis : struct(x: {g['x_axis'][0]:.6f}, y: {g['x_axis'][1]:.6f}, z: {g['x_axis'][2]:.6f}),")
    L.append("  y_axis : struct(x: 0.0, y: -1.0, z: 0.0),")
    L.append("  base : ref(global_coor)")
    L.append(")")
    L.append("")
    L.append("feed_1  gaussian_beam_pattern")
    L.append("(")
    L.append("  frequency : ref(freq),")
    L.append("  coor_sys : ref(feed_coor_1),")
    L.append(f"  taper_angle : {g['taper']:.3f},")
    L.append(f"  taper : {EDGE_TAPER_DB},")
    L.append("  factor : struct(db : 0.0, deg : 0.0)")
    L.append(")")
    L.append("")
    L.append("PO_reflector  po_single_face_scatterer")
    L.append("(")
    L.append("  frequency : ref(freq),")
    L.append("  scatterer : ref(reflector),")
    L.append("  method : po,")
    L.append("  spill_over : on,")
    L.append("  coor_sys : ref(global_coor),")
    L.append('  file_name : " "')
    L.append(")")
    L.append("")
    L.append("cut_coor  coor_sys")
    L.append("(")
    L.append("  origin : struct(x: 0.0 m, y: 0.0 m, z: 0.0 m),")
    L.append(f"  x_axis : struct(x: {g['zx']:.6f}, y: 0.0, z: {g['zz']:.6f}),")
    L.append("  y_axis : struct(x: 0.0, y: 1.0, z: 0.0),")
    L.append("  base : ref(global_coor)")
    L.append(")")
    L.append("")
    L.append("far_field_cut  spherical_cut")
    L.append("(")
    L.append("  coor_sys : ref(cut_coor),")
    L.append(f"  theta_range : struct(start: {-span_deg:.3f}, end: {span_deg:.3f}, np: {np_theta}),")
    L.append("  phi_range : struct(start: 0.0, end: 0.0, np: 1),")
    L.append(f"  file_name : {cut_name},")
    L.append("  frequency : ref(freq)")
    L.append(")")
    with open(os.path.join(workdir, tor_name), "w", encoding="ascii") as f:
        f.write("\n".join(L))

    tci = [
        "COMMAND OBJECT PO_reflector get_currents ( source : sequence(ref(feed_1)), "
        "auto_convergence_of_po : on, convergence_on_output_grid : sequence(ref(far_field_cut)) )",
        "COMMAND OBJECT far_field_cut get_field ( source : sequence(ref(PO_reflector), ref(feed_1)) )",
        "QUIT",
        "",
    ]
    with open(os.path.join(workdir, tci_name), "wb") as f:      # CRLF 二进制（陷阱#3）
        f.write("\r\n".join(tci).encode("ascii"))

    gxp = (f"[Comment]\nPayloadDesign auto: D={D}m {freq_ghz}GHz offset reflector\n"
           f"[TOR file]\n{tor_name}\n[TCI file]\n{tci_name}\n[Default units]\nGHz m S/m 1\n")
    with open(os.path.join(workdir, gxp_name), "w", encoding="ascii") as f:
        f.write(gxp)
    return dict(gxp=gxp_name, cut=cut_name, span_deg=span_deg, np_theta=np_theta, tor=tor_name)


# ---------------- .cut 解析 ----------------
def parse_cut(path):
    """GRASP spherical_cut 格式（本桥固定 np_phi=1 主切面）：
      行1 'Field data in cuts'（标题，4 词）
      行2 全局头 7 字段：theta_start theta_step np_theta phi n_phi freq_idx comp
      其后 np_theta 行数据，每行 4 字段：E_co_re E_co_im E_x_re E_x_im
    解析策略：读全局头取 theta 轴，再顺序收集其后的 4 字段数值行（取前 np_theta 行），
    兼容无分块头（np_phi=1）与有分块头（多 phi，块头为 7 字段自动跳过）。"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().strip().split("\n")
    if len(lines) < 3:
        raise ValueError("cut 文件过短")
    parts = lines[1].split()
    if len(parts) < 3:
        raise ValueError("cut 全局头异常")
    theta_start = float(parts[0]); theta_step = float(parts[1]); np_theta = int(float(parts[2]))
    mag = []
    for ln in lines[2:]:
        row = ln.split()
        if len(row) == 4:                       # 数据行（块头为 7 字段，自动跳过）
            try:
                mag.append(math.sqrt(float(row[0]) ** 2 + float(row[1]) ** 2))
            except ValueError:
                continue
            if len(mag) >= np_theta:
                break
    if len(mag) < np_theta:
        raise ValueError("cut 数据行不足（%d/%d）" % (len(mag), np_theta))
    peak = max(mag) if max(mag) > 0 else 1.0
    thetas = [theta_start + k * theta_step for k in range(np_theta)]
    dbr = [20 * math.log10(v / peak) if v > 0 else -120.0 for v in mag]
    return thetas, dbr


# ---------------- GRASP 求解 ----------------
def run_grasp(solver, workdir, D, freq_ghz, tag="beam", timeout=240):
    m = build_model(workdir, D, freq_ghz, tag=tag)
    t0 = time.time()
    try:
        proc = subprocess.run([solver, m["gxp"]], cwd=workdir,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return dict(ok=False, error=f"GRASP 求解超时（>{timeout}s）", model=m)
    except Exception as e:                                   # noqa: BLE001
        return dict(ok=False, error=f"GRASP 启动失败：{e!r}", model=m)
    dt = time.time() - t0
    cut_path = os.path.join(workdir, m["cut"])
    screen = ""
    sp = os.path.join(workdir, "screenoutput.txt")
    if os.path.exists(sp):
        try:
            screen = open(sp, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            pass
    if not os.path.exists(cut_path):
        err = (screen[-600:] or (proc.stderr or "")[-600:] or "无 .cut 输出")
        return dict(ok=False, error="GRASP 未生成远场：" + err, model=m,
                    exit=proc.returncode, secs=dt)
    try:
        thetas, dbr = parse_cut(cut_path)
    except Exception as e:                                   # noqa: BLE001
        return dict(ok=False, error=f".cut 解析失败：{e!r}", model=m, secs=dt)
    g0 = peak_gain_dbi(D, freq_ghz, DEFAULT_ETA)
    th3 = _beamwidth_from(thetas, dbr, 3.0)
    edge = _edge_level(thetas, dbr, th3)
    return dict(source="grasp", ok=True, model=m, secs=round(dt, 1),
                peak_gain_dbi=round(g0, 2), beamwidth_3db_deg=round(th3, 3),
                coverage_edge_dbr=round(edge, 2), theta=thetas, gain_dbr=dbr,
                freq_ghz=freq_ghz, D_m=D, eta=DEFAULT_ETA,
                screen_tail=screen[-400:],
                note=f"GRASP PO 实测远场（ticra-tools.exe，{dt:.0f}s）：G0(η={DEFAULT_ETA})≈{g0:.1f}dBi")


# ---------------- 编排入口 ----------------
def beam_performance(D_ap, freq_ghz, eta=DEFAULT_ETA, prefer="grasp", tag=None, timeout=240):
    """返回波束性能 dict。prefer='grasp' 优先实测，失败降级解析；prefer='analytic' 直接解析。"""
    D_ap = float(D_ap or 0)
    freq_ghz = float(freq_ghz or 0)
    if D_ap <= 0 or freq_ghz <= 0:
        return dict(ok=False, source="none", error="口径或频率无效（D_ap/freq_ghz 需 >0）")
    tag = tag or ("d%dm_f%gghz" % (round(D_ap * 100), round(freq_ghz)))
    if prefer == "grasp":
        solver, info = find_grasp()
        if solver:
            workdir = tempfile.mkdtemp(prefix="grasp_pd_")
            try:
                r = run_grasp(solver, workdir, D_ap, freq_ghz, tag=tag, timeout=timeout)
                if r.get("ok"):
                    return r
                # 实测失败 → 记录原因并降级
                ana = analytic_pattern(D_ap, freq_ghz, eta)
                ana["grasp_error"] = r.get("error", "")
                ana["note"] = "GRASP 求解失败，已降级解析估算：" + ana["note"]
                return ana
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        else:
            ana = analytic_pattern(D_ap, freq_ghz, eta)
            ana["note"] = "未找到 GRASP（ticra-tools.exe），已降级解析估算：" + ana["note"]
            return ana
    return analytic_pattern(D_ap, freq_ghz, eta)


if __name__ == "__main__":
    import sys
    D = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4
    fr = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
    pref = sys.argv[3] if len(sys.argv) > 3 else "grasp"
    solver, info = find_grasp()
    print("solver:", solver)
    print("info:", info)
    r = beam_performance(D, fr, prefer=pref)
    print("source:", r.get("source"), "ok:", r.get("ok"))
    print("peak_dBi:", r.get("peak_gain_dbi"), "th3dB:", r.get("beamwidth_3db_deg"),
          "edge_dBr:", r.get("coverage_edge_dbr"))
    if r.get("grasp_error"):
        print("grasp_error:", r["grasp_error"][:300])
    print("note:", r.get("note"))
    print("n_theta:", len(r.get("theta", [])))
