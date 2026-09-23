# -*- coding: utf-8 -*-
"""通信卫星有效载荷方案设计器 —— 桌面应用（pywebview）。

架构：前端 HTML（配置界面 + 10 个结果页签）经 JS 桥调用真实 Python 设计引擎
design_engine.design_all()，Python 引擎为唯一真源（无 JS 镜像、无一致性风险）。

页签：方案配置 / 载荷组成框图 / 天线链路预算 / 转发器链路预算 / 信息流设计 /
      单机清单与选型 / 方案对比 / 原理介绍 / 约束校验与回环 / 参数面板

运行：python design_app.py          （开发）
打包：pyinstaller design_app.spec   （exe）
"""
import json
import math
import os
import sys
import time
import threading
import datetime
import traceback as _tb

# 关键：必须在任何 clr/webview 导入之前设定 —— pythonnet 用 Windows 自带的
# .NET Framework 4.8（netfx），而非需单独安装的 .NET Desktop Runtime（coreclr）。
# 目标机无 coreclr 时，pywebview edgechromium 平台在 import clr 阶段即崩溃，
# console=False 下无任何提示，表现为"exe 打开没反应"。
os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")

# ---------- 启动诊断日志（排查"exe 打开没反应"） ----------
def _boot_dirs():
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.dirname(sys.executable))
    try:
        cands.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    for k in ("TEMP", "TMP"):
        v = os.environ.get(k)
        if v:
            cands.append(v)
    cands.append(".")
    seen, out = set(), []
    for d in cands:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _bootlog(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    for d in _boot_dirs():
        try:
            with open(os.path.join(d, "payload_designer_boot.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def _fatal(msg):
    _bootlog("FATAL: " + str(msg))
    try:
        import ctypes
        # MB_ICONERROR | MB_TOPMOST，确保弹窗在最前可见
        ctypes.windll.user32.MessageBoxW(0, str(msg), "载荷方案设计器 · 启动错误", 0x10 | 0x40000)
    except Exception:
        pass


def _check_webview2_runtime():
    """检测 Microsoft Edge WebView2 Runtime 注册表，返回 (是否安装, 版本号)。"""
    try:
        import winreg
    except Exception:
        return None, ""
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv != "0.0.0.0":
                    return True, pv
        except Exception:
            continue
    return False, ""


def _check_dotnet():
    """检测 .NET Desktop Runtime 是否可用（pythonnet coreclr 依赖）。"""
    import subprocess
    try:
        r = subprocess.run(["dotnet", "--list-runtimes"], capture_output=True,
                           text=True, timeout=15)
        txt = (r.stdout or "") + (r.stderr or "")
        if "WindowsDesktop" in txt:
            vers = [l.split()[-1] for l in txt.splitlines()
                    if l.startswith("Microsoft.WindowsDesktop.App")]
            return True, (vers[-1] if vers else "ok")
        return False, txt[-300:]
    except Exception:
        return False, "dotnet 命令不可用"


def _collect_diag():
    """收集运行环境诊断信息，写入日志。"""
    _bootlog("--- diagnostics ---")
    ok_wv, ver_wv = _check_webview2_runtime()
    _bootlog("WebView2 Runtime: installed=%s version=%s" % (ok_wv, ver_wv))
    ok_dn, ver_dn = _check_dotnet()
    _bootlog(".NET Desktop Runtime: available=%s version=%s" % (ok_dn, ver_dn))
    return ok_wv, ver_wv, ok_dn, ver_dn


_bootlog("=== module load start | frozen=%s | exe=%s | py=%s ===" % (
    getattr(sys, "frozen", False), sys.executable, sys.version.split()[0]))

# ---------- 资源路径（PyInstaller onefile/onedir 兼容） ----------
def res_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, "frozen", False):
    sys.path.insert(0, res_path("tools"))

try:
    from design_data import (SCENARIOS, DEFAULT_CFG, ORBITS, COVERAGE, SERVICES, MODES,
                             ANT_TYPES, ARRAY_SUBTYPES, SHELF_UNITS, UNIT_PRINCIPLES,
                             PLATFORMS, LAUNCHERS, BAND_FREQ, BAND_RAIN, MODE_HPA,
                             SHELF_LEVELS, SHELF_CATS, ORBIT_KEYS, COVERAGE_KEYS,
                             SERVICE_KEYS, MODE_KEYS, ANT_TYPE_KEYS, ARRAY_SUBTYPE_KEYS,
                             BAND_KEYS)                            # noqa: E402
    import design_engine as DE                                      # noqa: E402
    import grasp_bridge as GB                                       # noqa: E402
    import protocol_gen as PG                                       # noqa: E402
    import report_gen as RG                                         # noqa: E402
    import pattern_engine as PE                                     # noqa: E402
    import coverage_engine as CE                                    # noqa: E402
    import orbit_engine as OE                                       # noqa: E402
    _bootlog("design_data / design_engine / grasp_bridge / protocol_gen / report_gen "
             "/ pattern_engine / coverage_engine / orbit_engine imported OK")
except Exception:
    _fatal("无法导入设计引擎模块（design_data / design_engine / grasp_bridge / protocol_gen / report_gen / pattern_engine / coverage_engine / orbit_engine）：\n" + _tb.format_exc())
    raise

# ---------- 世界陆地轮廓底图（覆盖区示意图用，仅海岸线无政治边界） ----------
_WORLD_LAND = None
def world_land():
    global _WORLD_LAND
    if _WORLD_LAND is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_land.json")
        if not os.path.exists(p):
            p = res_path(os.path.join("tools", "world_land.json"))
        try:
            with open(p, "r", encoding="utf-8") as f:
                _WORLD_LAND = json.load(f)
            _bootlog("world_land.json loaded: %d polys" % _WORLD_LAND.get("n", 0))
        except Exception:
            _WORLD_LAND = {"q": 4.0, "n": 0, "polys": []}
            _bootlog("world_land.json load FAILED:\n" + _tb.format_exc())
    return _WORLD_LAND

_KG_NAME = os.path.join("output", "通信有效载荷知识图谱_2026-09-20.json")
KG_PATH = res_path(_KG_NAME)
_bootlog("KG primary path=%s exists=%s" % (KG_PATH, os.path.exists(KG_PATH)))
if not os.path.exists(KG_PATH):
    KG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _KG_NAME)
    _bootlog("KG fallback path=%s exists=%s" % (KG_PATH, os.path.exists(KG_PATH)))
try:
    with open(KG_PATH, "r", encoding="utf-8") as _f:
        KG = json.load(_f)
    _bootlog("KG loaded OK, top-level keys=%d" % len(KG))
except Exception:
    KG = {}
    _fatal("知识图谱 JSON 加载失败（%s）：\n%s\n\n将以空知识图谱继续，方案对比/单机选型可能受限。"
           % (KG_PATH, _tb.format_exc()))


# ---------- JSON 消毒：NaN/Inf → null（JS JSON.parse 不容忍） ----------
def _clean(o):
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    return str(o)


# ================================================================
# 完整报告 / ICD 数据装配（report_gen + protocol_gen 共用）
# ================================================================
def _out_dir():
    """输出目录：开发态=项目 output/；冻结态=exe 同级 output/（可写）。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "output")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        _bootlog("mkdir output failed:\n" + _tb.format_exc())
    return d


def _safe_name(name, ext):
    """Windows 文件名安全化：非法字符替换 + 长度限制。"""
    bad = '<>:"/\\|?*'
    s = "".join(("_" if ch in bad else ch) for ch in str(name or "方案")).strip(" ._")
    if not s:
        s = "方案"
    return s[:60] + "." + ext


def _report_data(cfg):
    """配置 → design_all 结果 + 报告所需元数据（_cov_meta/_orbit_alt_km/_service_meta）。"""
    R = DE.design_all(cfg, KG, skip_compare=True)
    R["_cov_meta"] = COVERAGE.get(cfg.get("coverage"), {}) or {}
    R["_orbit_alt_km"] = (ORBITS.get(cfg.get("orbit", "GEO"), ORBITS["GEO"]) or {}).get("alt_km", 35786)
    R["_service_meta"] = SERVICES.get(cfg.get("service", "高通量宽带"), {}) or {}
    return R


# ================================================================
# Word 兼容 HTML 导出装配器（方案 → 可下载 .doc 的 HTML）
#   前端把已渲染的各页签 innerHTML 传进来，这里套 mso 样式外壳。
#   Word 打开 .doc（实为 HTML）时按 mso 条件注释应用页面设置与中文字体。
# ================================================================
def build_export_html(payload):
    import datetime as _dt
    name = (payload.get("name") or "通信卫星有效载荷方案").strip()
    sections = payload.get("sections") or []      # [{title, html}]
    kpi = payload.get("kpi") or ""
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    body = []
    body.append('<h1 class="doc-title">%s</h1>' % name)
    body.append('<p class="doc-sub">通信卫星有效载荷方案设计器 · payload-design 五步闭环自动生成 · %s</p>' % now)
    if kpi:
        body.append('<p class="doc-kpi">%s</p>' % kpi)
    body.append('<hr/>')
    for i, sec in enumerate(sections, 1):
        t = (sec.get("title") or "").strip()
        htm = sec.get("html") or ""
        body.append('<h2 class="doc-h2">%d. %s</h2>' % (i, t))
        body.append('<div class="doc-sec">%s</div>' % htm)
        body.append('<br style="page-break-before:auto"/>')
    body.append('<hr/><p class="doc-foot">本方案由设计引擎按 25 条工程约束自动校核生成；'
                '单机默认值为工程典型值，仅用于方案级论证，正式设计以详细链路预算为准。</p>')
    content = "\n".join(body)

    css = """
body{font-family:"仿宋","FangSong","宋体",serif;font-size:12pt;line-height:1.7;color:#000}
.doc-title{font-family:"方正小标宋简体","黑体","SimHei",sans-serif;font-size:22pt;text-align:center;margin:18pt 0 6pt}
.doc-sub{text-align:center;font-size:10.5pt;color:#444;margin:0 0 4pt}
.doc-kpi{text-align:center;font-size:10.5pt;color:#1a3;margin:0 0 8pt}
.doc-h2{font-family:"黑体","SimHei",sans-serif;font-size:15pt;margin:16pt 0 6pt;border-bottom:1.5pt solid #0b5cad;padding-bottom:3pt}
.doc-sec{font-size:11pt}
.doc-sec table{border-collapse:collapse;width:100%;font-size:9.5pt;margin:6pt 0}
.doc-sec th,.doc-sec td{border:0.75pt solid #888;padding:3pt 5pt;text-align:left;vertical-align:top}
.doc-sec th{background:#e8eef7;font-weight:bold}
.doc-sec .note,.doc-sec .warnbox,.doc-sec .badbox,.doc-sec .okbox{border:0.75pt solid #aaa;padding:5pt 8pt;margin:6pt 0;font-size:9.5pt}
.doc-sec .kpi,.doc-sec .kpis{font-size:9.5pt}
.doc-sec svg{max-width:100%;height:auto}
.doc-foot{font-size:9pt;color:#555;text-align:center;margin-top:12pt}
.tag{border:0.5pt solid #999;padding:0 4pt;font-size:9pt}
"""
    mso = """
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom>
<w:DoNotOptimizeForBrowser/></w:WordDocument></xml><![endif]-->
<style>@page WordSection1{size:595.3pt 841.9pt;margin:72pt 72pt 72pt 72pt;mso-header-margin:42.55pt;
mso-footer-margin:49.6pt;mso-paper-source:0;}div.WordSection1{page:WordSection1;}</style>
"""
    html = ('<!DOCTYPE html>\n<html xmlns:o="urn:schemas-microsoft-com:office:office" '
            'xmlns:w="urn:schemas-microsoft-com:office:word" '
            'xmlns="http://www.w3.org/TR/REC-html40">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="ProgId" content="Word.Document">\n'
            '<meta name="Generator" content="payload-design">\n'
            '<title>%s</title>\n%s<style>%s</style>\n</head>\n'
            '<body><div class="WordSection1">\n%s\n</div></body>\n</html>'
            % (name, mso, css, content))
    return html


class Api:
    """JS 桥接口。前端：await pywebview.api.<method>(...)"""

    def meta(self):
        return _clean(dict(
            scenarios={k: dict(label=v["label"], desc=v["desc"], cfg=v["cfg"])
                       for k, v in SCENARIOS.items()},
            default_cfg=DEFAULT_CFG,
            orbits=ORBITS, coverage=COVERAGE, services=SERVICES,
            modes=MODES, ant_types=ANT_TYPES, array_subtypes=ARRAY_SUBTYPES,
            platforms=PLATFORMS, launchers=LAUNCHERS,
            shelf=[dict(zip(("id", "cn", "cat", "bands", "level", "mass", "power",
                             "specs", "note"), u)) for u in SHELF_UNITS],
            unit_principles=UNIT_PRINCIPLES,
            band_keys=BAND_KEYS, orbit_keys=ORBIT_KEYS,
            coverage_keys=COVERAGE_KEYS, service_keys=SERVICE_KEYS,
            mode_keys=MODE_KEYS, ant_type_keys=ANT_TYPE_KEYS,
            array_subtype_keys=ARRAY_SUBTYPE_KEYS,
            shelf_levels={str(k): v for k, v in SHELF_LEVELS.items()},
            shelf_cats=SHELF_CATS,
            mode_hpa=MODE_HPA,
            band_freq={k: list(v) for k, v in BAND_FREQ.items()},
            band_rain={k: list(v) for k, v in BAND_RAIN.items()},
            score_w=DE.SCORE_W, score_cn=DE.SCORE_CN,
            kg_meta=KG.get("name", ""),
        ))

    def design(self, cfg, with_compare=True):
        try:
            r = DE.design_all(cfg, KG, skip_compare=not with_compare)
            return _clean(dict(ok=True, result=r))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-1500:])

    def suggest(self, payload):
        """按当前配置给出参数建议值（覆盖区/业务/频段/天线联动）。

        payload 可为 cfg dict（旧通道，行内提示）或 {cfg, closed} 对象：
        closed=True 时走 suggest_closed_loop —— 建议值经 design_all 全流程验证，
        未闭合约束自动修正（≤3 轮），返回 values/notes + closed{grade,feasible,
        conclusion,adjustments,...}，确保「一键建议值」真正满足设计要求。"""
        try:
            if isinstance(payload, dict) and ("cfg" in payload or "closed" in payload):
                cfg = payload.get("cfg") or {}
                closed = bool(payload.get("closed"))
            else:
                cfg, closed = (payload or {}), False
            if closed:
                return _clean(dict(ok=True, result=DE.suggest_closed_loop(cfg, KG)))
            return _clean(dict(ok=True, result=DE.suggest_params(cfg, KG)))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def js_error(self, msg, src="", line=0, col=0):
        _bootlog("JS-ERROR: %s | %s:%s:%s" % (msg, src, line, col))
        return True

    def beam(self, payload):
        """按天线口径/频率计算波束方向图与覆盖性能（一维 + 可选二维）。
        prefer='grasp' 优先调用 TICRA GRASP 实测，失败降级解析口径方向图。
        with_2d=True 时附带 θx–θy 二维方向图网格（Airy 旋转对称 + 扫描 cos^1.5 修正）。"""
        try:
            p = payload or {}
            D = float(p.get("D_ap") or 0)
            f = float(p.get("freq_ghz") or 0)
            eta = float(p.get("eta") or GB.DEFAULT_ETA)
            prefer = p.get("prefer", "grasp")
            # 方向图采样点抽稀（前端 SVG 渲染，401 点足够平滑）
            r = GB.beam_performance(D, f, eta=eta, prefer=prefer,
                                    tag=p.get("tag"))
            if r.get("ok"):
                th, gd = r.get("theta", []), r.get("gain_dbr", [])
                # 抽稀到 ~200 点（SVG 平滑足够），向上取整步长确保 361/401 点也降采样
                step = max(1, -(-len(th) // 200)) if th else 1
                r2d = None
                if p.get("with_2d"):
                    # 二维网格用全精度一维数据反推波束宽度（抽稀前）
                    r2d = RG.pattern_2d_grid(r, D, f, n=41,
                                             scan_deg=float(p.get("scan_deg") or 0))
                r["theta"] = th[::step]
                r["gain_dbr"] = gd[::step]
                if r2d:
                    r["pattern2d"] = r2d
            return _clean(dict(ok=bool(r.get("ok")), result=r))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def worldmap(self):
        """返回简化陆地轮廓（覆盖区示意图底图）。"""
        try:
            return _clean(dict(ok=True, land=world_land()))
        except Exception as e:                          # noqa: BLE001
            return dict(ok=False, error=f"{type(e).__name__}: {e}")

    def export_html(self, payload):
        """完整载荷方案报告（Word 兼容 HTML，mso 样式）。

        payload = {cfg, name}：服务端按 cfg 重算 design_all → protocol_gen 生成 ICD
        → report_gen 装配完整报告（目录/需求/设计流程/总体方案+架构图/天线波束
        1D+2D 方向图/链路预算/单机选型/接口协议 ICD/约束校验/附录 + 三维地球覆盖图），
        **落盘到 output/ 目录**并返回 file_path。

        修复"导出 Word 没反应"：WebView2 桌面态会静默拦截 Blob-URL 的 a.click()
        下载（无文件、无报错）。现在后端直接写盘，前端展示路径并提供
        「打开文件 / 打开所在文件夹」按钮（/api/open_file、/api/reveal_file）。
        兼容：payload 仍带 sections 时走旧版页签拼装（build_export_html）。
        """
        try:
            payload = payload or {}
            # —— 旧通道兼容：前端传 sections（页签 innerHTML）→ 简易装配 ——
            if payload.get("sections"):
                return _clean(dict(ok=True, html=build_export_html(payload)))
            cfg = payload.get("cfg") or {}
            if not cfg:
                return dict(ok=False, error="缺少配置 cfg：请先完成一次「开始设计」再导出")
            name = (payload.get("name") or cfg.get("name") or "通信卫星有效载荷方案").strip()
            R = _report_data(cfg)
            icd = PG.generate_icd(R)
            doc = RG.build_report(R, icd=icd, world_land=world_land(),
                                  name=name, shelf_count=len(SHELF_UNITS))
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            fname = _safe_name("%s_载荷方案报告_%s" % (name, stamp), "doc")
            fpath = os.path.join(_out_dir(), fname)
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write("\ufeff" + doc)
            _bootlog("report exported: %s (%d chars)" % (fpath, len(doc)))
            # 已落盘 → 不再回传完整 html（光栅化后 PNG base64 可达数 MB，
            # JS 桥/HTTP 回传大字符串慢且前端用不到）；仅纯网页兜底通道才需要 html。
            return _clean(dict(ok=True, file_path=fpath, file_name=fname,
                               chars=len(doc)))
        except Exception as e:                          # noqa: BLE001
            import traceback
            _bootlog("export FAILED: " + traceback.format_exc()[-800:])
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    # ================================================================
    # 三引擎集成（#57）：方向图 grid/cut · 地面 EIRP 覆盖 · 轨道仿真
    # ================================================================
    @staticmethod
    def _pat_from_payload(p):
        """前端参数 → pattern_engine.compute_pattern（保留 _gain_arr 闭包，内部用）。"""
        at = str(p.get("antenna_type") or "phased_array")
        freq = float(p.get("freq_ghz") or 20.0)
        scan_theta = float(p.get("scan_theta") or 0.0)
        scan_phi = float(p.get("scan_phi") or 0.0)
        cut_span = float(p.get("cut_span") or 15.0)
        kw = dict(cut_span=cut_span, cut_phi=float(p.get("cut_phi") or 0.0),
                  grid_n_theta=int(p.get("grid_n_theta") or 91),
                  grid_n_phi=int(p.get("grid_n_phi") or 73),
                  cut_n=int(p.get("cut_n") or 301))
        if p.get("peak_gain_dbi") not in (None, ""):
            kw["peak_gain_dbi"] = float(p["peak_gain_dbi"])
        if at in ("phased_array", "array", "相控阵", "AESA"):
            nx = p.get("nx") and int(p["nx"]) or None
            ny = p.get("ny") and int(p["ny"]) or None
            return PE.compute_pattern(antenna_type="phased_array", freq_ghz=freq,
                                      nx=nx, ny=ny, n_el=p.get("n_el"),
                                      d_lam=float(p.get("d_lam") or 0.5),
                                      scan_theta=scan_theta, scan_phi=scan_phi, **kw)
        return PE.compute_pattern(antenna_type="reflector", freq_ghz=freq,
                                  D=float(p.get("D") or 2.5),
                                  scan_theta=scan_theta, scan_phi=scan_phi, **kw)

    @staticmethod
    def _pat_public(pat, grid_step=2):
        """方向图 → 前端安全 dict（剔除 _gain_arr 闭包；grid 抽稀；round 压缩）。"""
        g = pat["grid"]
        th, ph, gd = g["theta"], g["phi"], g["gain_dbr"]
        gs = max(1, grid_step)
        th2, gd2 = th[::gs], [row[::gs] for row in gd]
        out = dict(
            ok=True, antenna_type=pat["antenna_type"], freq_ghz=pat["freq_ghz"],
            lam_m=round(pat["lam_m"], 5),
            scan_theta_deg=pat["scan_theta_deg"], scan_phi_deg=pat["scan_phi_deg"],
            peak_gain_dbi=pat["peak_gain_dbi"],
            beamwidth_3db_deg=pat["beamwidth_3db_deg"],
            first_sidelobe_dbr=pat["first_sidelobe_dbr"],
            has_grating=pat["has_grating"], note=pat.get("note", ""),
            grid=dict(theta=[round(t, 2) for t in th2],
                      phi=[round(x, 2) for x in ph],
                      gain_dbr=[[round(v, 1) for v in row] for row in gd2]),
            cut=dict(theta=pat["cut"]["theta"], gain_dbr=pat["cut"]["gain_dbr"],
                     phi_deg=pat["cut"].get("phi_deg", 0.0),
                     span=pat["cut"].get("span", 15.0),
                     center=pat["cut"].get("center", 0.0)),
            cut_wide=dict(theta=pat["cut_wide"]["theta"],
                          gain_dbr=pat["cut_wide"]["gain_dbr"]),
            grating_lobes=[dict(order=g.get("order"), theta_deg=round(g["theta_deg"], 2),
                                phi_deg=round(g["phi_deg"], 2))
                           for g in pat.get("grating_lobes", [])],
            grating_in_cut=[dict(theta_deg=round(g["theta_deg"], 2),
                                 phi_deg=round(g["phi_deg"], 2))
                            for g in pat.get("grating_in_cut", [])],
        )
        if pat["antenna_type"] == "phased_array":
            out.update(nx=pat["nx"], ny=pat["ny"], n_el=pat["n_el"],
                       d_lam=pat["d_lam"], d_mm=pat["d_mm"], taper=pat["taper"])
        else:
            out.update(D_m=pat["D_m"], eta=pat["eta"], edge_db=pat["edge_db"])
        return out

    def pattern(self, payload):
        """天线次级方向图：grid（θ×φ）+ cut（±15°）+ 栅瓣检查（boresight/扫描双态）。
        payload: {antenna_type, freq_ghz, D|n_el, d_lam, scan_theta, scan_phi, cut_span,
                  export_grd(bool), tag}"""
        try:
            p = payload or {}
            pat = self._pat_from_payload(p)
            pub = self._pat_public(pat)
            if p.get("export_grd"):
                tag = _safe_name(p.get("tag") or "方向图", "").rsplit(".", 1)[0]
                fpath = os.path.join(_out_dir(), tag + ".grd")
                info = PE.export_grd(pat, fpath)
                pub["grd_file"] = dict(path=info["path"], name=os.path.basename(fpath),
                                       n_theta=info["n_theta"], n_phi=info["n_phi"])
                _bootlog(".grd exported: %s (%d×%d)" % (fpath, info["n_theta"], info["n_phi"]))
            return _clean(dict(ok=True, result=pub))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def coverage(self, payload):
        """地面 EIRP 覆盖（SATSOFT 等效内置计算）：方向图 → 星下点/波束指向 → EIRP 网格
        + 等值线段 + 足迹度量。payload 在 pattern 参数基础上加：
        {peak_eirp_dbw, h_km, sat_lat, sat_lon, target_lat, target_lon, el_min_deg,
         point_at_target(bool), export_csv(bool), tag}"""
        try:
            p = dict(payload or {})
            h_km = float(p.get("h_km") or 35786.0)
            sat_lat = float(p.get("sat_lat") or 0.0)
            sat_lon = float(p.get("sat_lon") or 0.0)
            # 波束指向：point_at_target → pointing_angles 由几何反推（θ0,φ0）
            if p.get("point_at_target") and p.get("target_lat") is not None:
                th0, ph0 = CE.pointing_angles(sat_lat, sat_lon, h_km,
                                              float(p["target_lat"]),
                                              float(p["target_lon"]))
                p["scan_theta"], p["scan_phi"] = round(th0, 4), round(ph0, 4)
            pat = self._pat_from_payload(p)
            eirp = float(p.get("peak_eirp_dbw")
                         or (pat.get("peak_gain_dbi", 0.0) + 10.0))
            cov = CE.coverage_map(pat, eirp, h_km, sat_lat=sat_lat, sat_lon=sat_lon,
                                  el_min_deg=float(p.get("el_min_deg") or 0.0),
                                  n_lat=int(p.get("n_lat") or 97),
                                  n_lon=int(p.get("n_lon") or 121))
            pk = cov["peak_eirp_dbw"]
            levels = [round(pk - x, 1) for x in (3.0, 10.0)]
            segs = {str(lv): [[[round(a, 4), round(b, 4)] for a, b in seg]
                              for seg in CE.contour_segments(cov, lv)][:400]
                    for lv in levels}
            met = CE.coverage_metrics(cov, levels_dbw=levels)
            # EIRP 网格抽稀给前端着色（≤61×81 点）
            st_i = max(1, len(cov["lat"]) // 60)
            st_j = max(1, len(cov["lon"]) // 80)
            grid = [[cov["eirp_dbw"][i][j] if cov["eirp_dbw"][i][j] > cov["floor"] else None
                     for j in range(0, len(cov["lon"]), st_j)]
                    for i in range(0, len(cov["lat"]), st_i)]
            pub = dict(ok=True,
                       lat=[round(cov["lat"][i], 3) for i in range(0, len(cov["lat"]), st_i)],
                       lon=[round(cov["lon"][j], 3) for j in range(0, len(cov["lon"]), st_j)],
                       eirp_dbw=grid, peak_ground=cov["peak_ground"],
                       beam_center=cov["beam_center"], scan=cov["scan"],
                       sat=cov["sat"], peak_eirp_dbw=pk,
                       contours=segs, levels=levels, metrics=met,
                       exact=cov["exact"], note=cov["note"])
            if p.get("export_csv"):
                tag = _safe_name(p.get("tag") or "覆盖", "").rsplit(".", 1)[0]
                f1 = os.path.join(_out_dir(), tag + "_EIRP覆盖.csv")
                f2 = os.path.join(_out_dir(), tag + "_EIRP等值线.csv")
                CE.export_coverage_csv(cov, f1)
                CE.export_contours_csv(cov, f2, levels)
                pub["csv_files"] = [dict(path=f1, name=os.path.basename(f1)),
                                    dict(path=f2, name=os.path.basename(f2))]
                _bootlog("coverage CSV exported: %s / %s" % (f1, f2))
            return _clean(pub)
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    @staticmethod
    def _sso_inclination(h_km):
        """太阳同步倾角：Ω̇ = +0.9856°/d → cos i = −2π·Ω̇_sso/(3nJ2(Re/p)²)。"""
        import math as _m
        a = OE.R_EARTH + h_km
        nn = _m.sqrt(OE.MU / a ** 3)
        om = 0.9856 * _m.pi / 180.0 / 86400.0
        cos_i = -2.0 * om / (3.0 * nn * OE.J2 * (OE.R_EARTH / a) ** 2)
        cos_i = max(min(cos_i, 1.0), -1.0)
        return round(_m.degrees(_m.acos(cos_i)), 2)

    def orbit(self, payload):
        """轨道覆盖仿真（STK 等效内置计算）：星下点轨迹 + 覆盖帽 + 目标可见窗
        + 某时刻快照 + 轨道合理性评估 + .e 导出。
        payload: {orbit_key, h_km, incl_deg(None→按轨道默认; SSO→太阳同步),
                  ecc, raan_deg, geo_lon(GEO 定点经度→自动反解 raan),
                  targets[{name,lat,lon}], el_min_deg,
                  t_offset_min(快照时刻,默认=0), dur_h, export_stk(bool), tag}"""
        try:
            import math as _m
            p = payload or {}
            key = str(p.get("orbit_key") or "GEO").upper()
            h_km = float(p.get("h_km") or 35786.0)
            incl = p.get("incl_deg")
            if incl in (None, ""):
                incl = {"GEO": 0.05, "MEO": 45.0, "LEO": 53.0,
                        "SSO": self._sso_inclination(h_km), "HEO": 63.4}.get(key, 53.0)
            incl = float(incl)
            ecc = float(p.get("ecc") or 0.0)
            el_min = float(p.get("el_min_deg") or 10.0)
            dur_h = float(p.get("dur_h") or 24.0)
            targets = p.get("targets") or []
            t0 = OE.J2000_UNIX + 26.0 * 365.25 * 86400.0    # ≈2026 示意历元
            argp = float(p.get("argp_deg") or 0.0)
            raan = p.get("raan_deg")
            if raan in (None, ""):
                gl = p.get("geo_lon")
                if gl not in (None, ""):
                    # GEO 定点：历元星下点经度=geo_lon。数值标定（鲁棒，免解析相位）：
                    # 先以 raan=0 传播量出 sub_lon0，则 raan = geo_lon − sub_lon0
                    # （星下点经度对 raan 线性 +1；自动吸收 n·Δt₀ 绕行相位与 GMST）。
                    probe = OE.elements_from_altitude(h_km, incl, ecc=ecc,
                                                      raan_deg=0.0, argp_deg=argp)
                    _, lon0, _ = OE.sub_satellite(t0, probe)
                    raan = (float(gl) - lon0) % 360.0
                else:
                    raan = 0.0
            el = OE.elements_from_altitude(h_km, incl, ecc=ecc,
                                           raan_deg=float(raan), argp_deg=argp)
            assess = OE.assess_orbit(key, h_km, incl, targets,
                                     el_min_deg=el_min, t_start=t0, ecc=ecc,
                                     raan_deg=float(raan),
                                     argp_deg=float(p.get("argp_deg") or 0.0))
            t_snap = t0 + float(p.get("t_offset_min") or 0.0) * 60.0
            snap = OE.snapshot(t_snap, el, targets=targets, el_min_deg=el_min)
            snap["t_offset_min"] = round(float(p.get("t_offset_min") or 0.0), 1)
            import time as _time
            snap["t_utc"] = _time.strftime("%Y-%m-%d %H:%M:%S UTC",
                                           _time.gmtime(int(t_snap)))
            per = OE.orbital_period_min(el)
            nn, raan_dot, argp_dot = OE.mean_motion(el)
            out = dict(ok=True, orbit=key, h_km=h_km, incl_deg=incl, ecc=el["ecc"],
                       raan_deg=round(float(raan) % 360.0, 3),
                       geo_lon=(round(float(p.get("geo_lon")), 2)
                                if p.get("geo_lon") not in (None, "") else None),
                       period_min=round(per, 2),
                       vel_kms=round(2 * _m.pi * el["a_km"] / (per * 60.0), 3),
                       raan_dot_deg_day=round(_m.degrees(raan_dot) * 86400.0, 4),
                       sso_incl=self._sso_inclination(h_km) if key in ("SSO", "LEO", "MEO") else None,
                       el_min_deg=el_min, t_start=t0,
                       assess=assess, snapshot=snap,
                       track=assess.get("track", []))
            if p.get("export_stk"):
                tag = _safe_name(p.get("tag") or "轨道", "").rsplit(".", 1)[0]
                fpath = os.path.join(_out_dir(), tag + ".e")
                info = OE.export_stk_ephemeris(el, fpath, t0, dur_h=dur_h, step_s=60.0)
                out["stk_file"] = dict(path=info["path"], name=os.path.basename(fpath),
                                       points=info["points"], format=info["format"])
                _bootlog("STK .e exported: %s (%d pts)" % (fpath, info["points"]))
            return _clean(out)
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def export_file(self, payload):
        """标准交换文件落盘：kind=grd(GRASP)/e(STK Ephemeris)/cov_csv(覆盖)。
        参数同 pattern/orbit/coverage；返回 file_path（前端「打开所在文件夹」用）。"""
        try:
            p = dict(payload or {})
            kind = str(p.get("kind") or "grd").lower()
            tag = _safe_name(p.get("tag") or "导出", "").rsplit(".", 1)[0]
            if kind == "grd":
                pat = self._pat_from_payload(p)
                fpath = os.path.join(_out_dir(), tag + ".grd")
                info = PE.export_grd(pat, fpath)
                return _clean(dict(ok=True, file_path=fpath,
                                   file_name=os.path.basename(fpath),
                                   detail="%d×%d θ×φ 球面网格（GRASP ASCII）"
                                          % (info["n_theta"], info["n_phi"])))
            if kind == "e":
                return self.orbit(dict(p, export_stk=True))
            if kind == "cov_csv":
                return self.coverage(dict(p, export_csv=True))
            return dict(ok=False, error="未知导出类型：" + kind)
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def protocol(self, payload):
        """接口与协议自动生成（MOSA 标准化 ICD）：方案设定 → 单机选型 →
        接口推导 → 标准协议（CCSDS/ECSS/MIL）→ 软件 ICD。"""
        try:
            cfg = (payload or {}).get("cfg") or {}
            if not cfg:
                return dict(ok=False, error="缺少配置 cfg")
            R = _report_data(cfg)
            icd = PG.generate_icd(R)
            return _clean(dict(ok=True, result=icd))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def open_file(self, payload):
        """用系统默认程序（Word/WPS）打开导出文件 —— 仅限 output/ 目录内。"""
        try:
            p = os.path.realpath((payload or {}).get("path") or "")
            base = os.path.realpath(_out_dir())
            if not p.startswith(base):
                return dict(ok=False, error="安全限制：仅允许打开输出目录内的文件")
            if not os.path.exists(p):
                return dict(ok=False, error="文件不存在：" + p)
            os.startfile(p)                             # noqa: S606
            return dict(ok=True)
        except Exception as e:                          # noqa: BLE001
            return dict(ok=False, error=str(e))

    def reveal_file(self, payload):
        """资源管理器定位导出文件 —— 仅限 output/ 目录内。"""
        try:
            import subprocess
            p = os.path.realpath((payload or {}).get("path") or "")
            base = os.path.realpath(_out_dir())
            if not p.startswith(base):
                return dict(ok=False, error="安全限制：仅允许定位输出目录内的文件")
            if not os.path.exists(p):
                return dict(ok=False, error="文件不存在：" + p)
            subprocess.Popen(["explorer", "/select,", p])
            return dict(ok=True)
        except Exception as e:                          # noqa: BLE001
            return dict(ok=False, error=str(e))

    # JS 桥别名（前端统一用 export/beam 名称，与 HTTP 路由一致）
    def export(self, payload):
        return self.export_html(payload)


# ================================================================
# 内置 HTTP 服务（bottle）：网页版实时计算通道 + 桌面版双通道兜底
#   网页版：python design_app.py --web  → 浏览器打开 http://127.0.0.1:PORT
#   桌面版：exe 启动时自动开服务，webview 直接加载 http://127.0.0.1:PORT/
#   —— 前端统一走 fetch('/api/...')，pywebview JS 桥仅作加速通道（可选）。
# ================================================================
def start_http_server(host="127.0.0.1", port=0):
    """启动内置 HTTP 服务（守护线程，纯标准库 http.server，零第三方依赖）。
    port=0 自动选空闲端口。返回实际端口。"""
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):                     # noqa: ARG002 静默访问日志
            pass

        def _send(self, code, ctype, body):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj):
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False))

        def _body(self):
            try:
                ln = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
            except Exception:
                return {}

        def do_OPTIONS(self):                          # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):                              # noqa: N802
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", FRONT_HTML)
            elif path == "/api/meta":
                self._json(_api_singleton.meta())
            elif path == "/api/worldmap":
                self._json(_api_singleton.worldmap())
            elif path == "/api/health":
                self._json(dict(ok=True, ts=time.time()))
            else:
                self._json(dict(ok=False, error="404 " + path))

        def do_POST(self):                             # noqa: N802
            path = self.path.split("?")[0]
            body = self._body()
            if path == "/api/design":
                self._json(_api_singleton.design(body.get("cfg") or {},
                                                 bool(body.get("with_compare", True))))
            elif path == "/api/suggest":
                self._json(_api_singleton.suggest(body))
            elif path == "/api/beam":
                self._json(_api_singleton.beam(body))
            elif path == "/api/pattern":
                self._json(_api_singleton.pattern(body))
            elif path == "/api/coverage":
                self._json(_api_singleton.coverage(body))
            elif path == "/api/orbit":
                self._json(_api_singleton.orbit(body))
            elif path == "/api/export_file":
                self._json(_api_singleton.export_file(body))
            elif path == "/api/export":
                self._json(_api_singleton.export_html(body))
            elif path == "/api/protocol":
                self._json(_api_singleton.protocol(body))
            elif path == "/api/open_file":
                self._json(_api_singleton.open_file(body))
            elif path == "/api/reveal_file":
                self._json(_api_singleton.reveal_file(body))
            else:
                self._json(dict(ok=False, error="404 " + path))

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    real_port = srv.server_address[1]

    t = threading.Thread(target=srv.serve_forever, daemon=True, name="payload-http")
    t.start()
    # 等服务就绪
    for _ in range(50):
        try:
            c = socket.create_connection((host, real_port), timeout=0.2)
            c.close()
            break
        except OSError:
            time.sleep(0.1)
    _bootlog("HTTP server listening on http://%s:%d" % (host, real_port))
    return real_port


_api_singleton = Api()


def run_web_mode(port=8642):
    """纯网页模式：起 HTTP 服务 + 打开系统默认浏览器。"""
    p = start_http_server("127.0.0.1", port)
    url = "http://127.0.0.1:%d/" % p
    _bootlog("WEB mode: %s" % url)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    print("载荷方案设计器（网页版）已启动：%s" % url)
    print("关闭本窗口即停止服务。按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main():
    _bootlog("main() entered")
    if "--web" in sys.argv:
        run_web_mode()
        return
    # 关键修复：强制 pythonnet 使用 netfx（.NET Framework 4.8，Windows 自带），
    # 而非 coreclr（需要单独安装 .NET Desktop Runtime —— 目标机没有时 import clr
    # 阶段即静默崩溃，表现为"exe 打开没反应"）。
    os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")
    _bootlog("PYTHONNET_RUNTIME=%s" % os.environ.get("PYTHONNET_RUNTIME"))
    ok_wv, ver_wv, ok_dn, ver_dn = _collect_diag()
    if ok_wv is False:
        _fatal("未检测到 Microsoft Edge WebView2 Runtime，GUI 无法启动。\n\n"
               "请安装：https://developer.microsoft.com/microsoft-edge/webview2/\n"
               "（Evergreen 独立安装包，约 2 分钟）")
        return
    try:
        import webview
        _bootlog("webview imported OK")
        import clr                                        # noqa: F401
        _bootlog("import clr OK (PYTHONNET_RUNTIME=%s)" % os.environ.get("PYTHONNET_RUNTIME"))
    except Exception:
        _fatal("无法初始化 GUI 运行库（pywebview / pythonnet / .NET）：\n" + _tb.format_exc())
        return
    # 双通道：内置 HTTP 服务（前端统一 fetch 实时计算）+ pywebview JS 桥（加速通道）。
    # webview 直接加载 http://127.0.0.1:PORT/ —— 即使 JS 桥注入失败，页面仍能经
    # HTTP 正常计算（修复"点进去不能进行操作"：旧版 html= 内联页面完全依赖桥）。
    try:
        port = start_http_server("127.0.0.1", 0)
    except Exception:
        _bootlog("HTTP server start failed, fallback to inline html:\n" + _tb.format_exc())
        port = 0
    url = ("http://127.0.0.1:%d/" % port) if port else None
    try:
        if url:
            win = webview.create_window(
                "通信卫星有效载荷方案设计器 · payload-design",
                url, js_api=_api_singleton,
                width=1520, height=960, min_size=(1180, 760),
                background_color="#f4f6fa",
            )
        else:
            win = webview.create_window(
                "通信卫星有效载荷方案设计器 · payload-design",
                html=FRONT_HTML, js_api=_api_singleton,
                width=1520, height=960, min_size=(1180, 760),
                background_color="#f4f6fa",
            )
        _bootlog("window created (url=%s); calling webview.start(gui=edgechromium)" % url)
        webview.start(gui="edgechromium")
        _bootlog("webview.start returned (window closed normally)")
    except Exception:
        _bootlog("webview.start failed:\n" + _tb.format_exc())
        if url:
            # GUI 失败 → 兜底：打开系统浏览器（HTTP 服务仍在，功能完整）
            try:
                import webbrowser
                webbrowser.open(url)
                _bootlog("fallback: opened system browser at %s" % url)
                while True:
                    time.sleep(3600)
            except Exception:
                pass
        _fatal("启动 WebView2 窗口失败（请确认已安装 Microsoft Edge WebView2 Runtime）：\n"
               + _tb.format_exc())


# ================================================================
# 前端（HTML/CSS/JS 单文件）
# ================================================================
FRONT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>通信卫星有效载荷方案设计器</title>
<style>
:root{
  --bg:#f4f6fa; --panel:#ffffff; --ink:#1c2733; --muted:#5f7183; --line:#dde5ee;
  --accent:#0b5cad; --accent2:#0a7ea4; --ok:#1d8a4e; --okbg:#e5f5ec;
  --warn:#b07514; --warnbg:#fdf3e0; --bad:#c0392b; --badbg:#fdeae8;
  --info:#4a6fa5; --infobg:#eaf1fa; --chip:#eef3f9;
  --rf-up:#b0662c; --rf-dn:#0b5cad; --dig:#7048a8; --opt:#0a7ea4; --if:#5f7183; --ctrl:#8a97a5; --pwr:#c0392b;
  --grad:linear-gradient(135deg,#0a3a6b 0%,#0b5cad 55%,#0a7ea4 100%);
  --shadow:0 2px 10px rgba(16,42,74,.07);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:var(--ink);font-size:13px;
  background:linear-gradient(180deg,#e8eef7 0%,#f4f6fa 260px,#f4f6fa 100%);min-height:100vh}
#app{max-width:1500px;margin:0 auto;padding:14px 18px 30px}
header.top{background:var(--grad);color:#fff;border-radius:16px;padding:16px 22px;margin-bottom:14px;
  display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;
  box-shadow:0 8px 26px rgba(16,42,74,.18);position:relative;overflow:hidden}
header.top::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(620px 130px at 88% -25%,rgba(255,255,255,.20),transparent 70%)}
header.top h1{font-size:22px;color:#fff;letter-spacing:.5px;text-shadow:0 1px 3px rgba(0,0,0,.22)}
header.top .sub{color:rgba(255,255,255,.84);font-size:12px;margin-top:5px;line-height:1.65}
.badge-kg{background:rgba(255,255,255,.16);color:#dce9f7;border:1px solid rgba(255,255,255,.38);
  border-radius:10px;padding:1px 8px;font-size:11px}
.badge-ver{background:#ffd166;color:#5a3d00;border-radius:8px;padding:1px 8px;font-size:11px;font-weight:700}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.kpi-top{font-size:12px;color:rgba(255,255,255,.88);width:100%;text-align:right}
.kpi-top b{color:#ffe3a3;font-size:14px;font-variant-numeric:tabular-nums}
.kpi-top .tag{background:rgba(255,255,255,.16);color:#eaf3fc;border-color:rgba(255,255,255,.3)}
header.top .btn{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.45);color:#fff}
header.top .btn:hover{background:#fff;color:var(--accent);border-color:#fff;transform:translateY(-1px);
  box-shadow:0 4px 12px rgba(0,0,0,.18)}
header.top .btn.solid{background:#fff;color:var(--accent);border-color:#fff;font-weight:700}
header.top .btn.solid:hover{background:#ffd166;color:#5a3d00;border-color:#ffd166}
.btn{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;
  padding:6px 14px;font-size:13px;cursor:pointer;transition:.16s;box-shadow:0 1px 3px rgba(16,42,74,.06)}
.btn:hover{border-color:var(--accent);color:var(--accent);transform:translateY(-1px);
  box-shadow:0 4px 12px rgba(11,92,173,.14)}
.btn:active{transform:translateY(0)}
.btn.solid{background:var(--grad);border-color:var(--accent);color:#fff}
.btn.solid:hover{background:linear-gradient(135deg,#0a4e92,#0b5cad);color:#fff;
  box-shadow:0 5px 16px rgba(11,92,173,.35)}
.btn.ghost{background:transparent;box-shadow:none}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn.sm{padding:4px 10px;font-size:12px;border-radius:7px}
.btn.on{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.on:hover{background:linear-gradient(135deg,#0a4e92,#0b5cad);color:#fff}
.glabel{font-size:11.5px;color:var(--muted)}
nav.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 12px}
nav.tabs button{border:1px solid var(--line);background:#fff;border-radius:10px 10px 0 0;
  padding:9px 15px;font-size:13px;cursor:pointer;color:var(--muted);border-bottom:none;
  transition:.18s;position:relative}
nav.tabs button:hover{color:var(--accent);transform:translateY(-2px);box-shadow:0 4px 12px rgba(11,92,173,.12)}
nav.tabs button.on{background:var(--grad);color:#fff;border-color:transparent;font-weight:700;
  box-shadow:0 4px 14px rgba(11,92,173,.3)}
section.tab{display:none}
section.tab.on{display:block;animation:fadeUp .35s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
  margin-bottom:14px;box-shadow:var(--shadow);transition:box-shadow .2s}
.panel:hover{box-shadow:0 4px 18px rgba(16,42,74,.10)}
.panel h2{font-size:15px;color:var(--accent);margin-bottom:10px;border-left:4px solid var(--accent);padding-left:8px}
.panel h3{font-size:13.5px;color:var(--ink);margin:12px 0 6px}
.grid{display:grid;gap:10px}
.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}.g6{grid-template-columns:repeat(6,1fr)}
.field label{display:block;font-size:11.5px;color:var(--muted);margin-bottom:3px}
.field input,.field select{width:100%;border:1px solid var(--line);border-radius:6px;
  padding:6px 8px;font-size:13px;background:#fff;color:var(--ink)}
.field input:focus,.field select:focus{outline:none;border-color:var(--accent)}
.field .hint{font-size:10.5px;color:#93a3b4;margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--chip);color:var(--ink);font-weight:600;white-space:nowrap}
tr:nth-child(even) td{background:#fafcfe}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;border-radius:9px;padding:1px 8px;font-size:11px;margin:1px 2px}
.tag.ok{background:var(--okbg);color:var(--ok)}
.tag.bad{background:var(--badbg);color:var(--bad)}
.tag.warn{background:var(--warnbg);color:var(--warn)}
.tag.info{background:var(--infobg);color:var(--info)}
.tag.mut{background:#eef1f5;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.kpi{background:linear-gradient(180deg,#fbfdff,#eef5fd);border:1px solid #d6e4f2;
  border-radius:12px;padding:10px 12px;position:relative;overflow:hidden;transition:.2s;
  animation:kpiIn .4s ease backwards}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;
  background:linear-gradient(180deg,var(--accent),var(--accent2))}
.kpi:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(11,92,173,.14);border-color:#bcd3ea}
@keyframes kpiIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.kpi .k{font-size:11px;color:var(--muted)}
.kpi .v{font-size:20px;font-weight:700;color:var(--accent);margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .u{font-size:11px;color:var(--muted);font-weight:400}
.kpi.okv .v{color:var(--ok)}.kpi.okv::before{background:linear-gradient(180deg,#38a56c,#1d8a4e)}
.kpi.badv .v{color:var(--bad)}.kpi.badv::before{background:linear-gradient(180deg,#e05a4a,#c0392b)}
.note{background:var(--infobg);border:1px solid #c9d9ef;border-radius:8px;padding:8px 12px;
  font-size:12px;color:#33507a;margin:8px 0;line-height:1.65}
.warnbox{background:var(--warnbg);border:1px solid #ecd9a8;border-radius:8px;padding:8px 12px;
  font-size:12px;color:#7a5a12;margin:8px 0;line-height:1.6}
.badbox{background:var(--badbg);border:1px solid #eec3bd;border-radius:8px;padding:8px 12px;
  font-size:12px;color:#8c2f22;margin:8px 0;line-height:1.6}
.okbox{background:var(--okbg);border:1px solid #bfe3cd;border-radius:8px;padding:8px 12px;
  font-size:12px;color:#1a6b40;margin:8px 0;line-height:1.6}
.muted{color:var(--muted)}
.small{font-size:11.5px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:14px;padding:3px 11px;
  font-size:12px;cursor:pointer}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.flowcard{border:1px solid var(--line);border-radius:10px;padding:10px 13px;margin-bottom:9px;background:#fff}
.flowcard .fname{font-weight:700;color:var(--accent);font-size:13px;margin-bottom:4px}
.flowcard .fpath{font-size:12px;line-height:1.7;color:#2c3e50;background:#f8fafd;
  border-radius:6px;padding:6px 10px;margin:5px 0;border-left:3px solid var(--accent2)}
.flowcard .frow{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin-top:4px}
.flowcard .frow b{color:var(--ink);font-weight:600}
.fchain{display:flex;flex-wrap:wrap;align-items:center;gap:3px;margin:5px 0}
.fstage{display:inline-flex;align-items:center;gap:4px;background:#f2f7fd;border:1px solid #d5e3f2;
  border-radius:6px;padding:2px 7px;font-size:11px;color:#2c3e50;line-height:1.5}
.fstage i{font-style:normal;font-size:9.5px;font-weight:800;color:#fff;background:#7ba4d0;
  border-radius:4px;padding:0 3.5px;line-height:14px}
.farrow{color:#9db6cf;font-size:11px;padding:0 1px}
.scorebar{display:flex;align-items:center;gap:8px;margin:3px 0}
.scorebar .lb{width:100px;font-size:11.5px;color:var(--muted);text-align:right}
.scorebar .bar{flex:1;height:12px;background:#edf1f6;border-radius:6px;overflow:hidden}
.scorebar .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#3f83c9,#0b5cad)}
.scorebar .fill.cur{background:linear-gradient(90deg,#38a56c,#1d8a4e)}
.scorebar .val{width:36px;font-size:11.5px;font-variant-numeric:tabular-nums}
.diag-wrap{overflow-x:auto;background:#fbfdff;border:1px solid var(--line);border-radius:10px;padding:6px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin:8px 2px}
.legend i{display:inline-block;width:22px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.busy{position:fixed;inset:0;background:rgba(244,246,250,.72);display:none;
  align-items:center;justify-content:center;z-index:99;flex-direction:column;gap:10px}
.busy.on{display:flex}
.modal-mask{position:fixed;inset:0;background:rgba(20,30,45,.45);display:none;
  align-items:flex-start;justify-content:center;z-index:200;overflow-y:auto;padding:40px 16px}
.modal-mask.on{display:flex}
.modal{background:#fff;border-radius:12px;max-width:880px;width:100%;
  box-shadow:0 12px 48px rgba(0,0,0,.25);overflow:hidden}
.modal .mhead{padding:13px 18px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.modal .mhead.bad{background:var(--badbg);border-bottom:2px solid #eec3bd}
.modal .mhead.warn{background:var(--warnbg);border-bottom:2px solid #ecd9a8}
.modal .mhead.ok{background:var(--okbg);border-bottom:2px solid #bfe3cd}
.modal .mhead h3{font-size:15.5px}
.modal .mhead .x{cursor:pointer;font-size:20px;color:var(--muted);background:none;border:none;padding:2px 8px}
.modal .mbody{padding:14px 18px;max-height:66vh;overflow-y:auto}
.issue{border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:10px 13px;margin-bottom:10px}
.issue.bad{border-left-color:var(--bad);background:#fffafa}
.issue.warn{border-left-color:var(--warn);background:#fffdf6}
.issue .it{font-weight:700;font-size:13.5px;margin-bottom:4px}
.issue.bad .it{color:var(--bad)}.issue.warn .it{color:var(--warn)}
.issue .id{font-size:12.5px;line-height:1.7;color:#2c3e50}
.issue .is{font-size:12px;line-height:1.7;color:#1a6b40;background:var(--okbg);
  border-radius:6px;padding:6px 9px;margin-top:6px}
.issue .ip{font-size:11px;color:var(--muted);margin-top:5px}
.issue .ip code{background:#eef1f5;border-radius:4px;padding:1px 6px;color:var(--accent);cursor:pointer}
.issue .ip code:hover{background:var(--accent);color:#fff}
.mfoot{padding:10px 18px;border-top:1px solid var(--line);display:flex;gap:8px;justify-content:flex-end;background:#fbfdff}
.sug-item{display:flex;gap:8px;align-items:baseline;padding:4px 0;border-bottom:1px dashed #e8edf4;font-size:12.5px}
.sug-item .sk{min-width:150px;color:var(--muted);font-size:12px}
.sug-item .sv{font-weight:700;color:var(--accent);min-width:80px;font-variant-numeric:tabular-nums}
.sug-item .sn{color:#5f7183;font-size:11.5px;flex:1;line-height:1.55}
.spinner{width:38px;height:38px;border:4px solid #cfdcec;border-top-color:var(--accent);
  border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
/* ===== 信息流图动效 ===== */
@keyframes ifDash{to{stroke-dashoffset:-260}}
@keyframes ifPulse{0%,100%{opacity:.35;r:4}50%{opacity:1;r:6.5}}
.if-link{fill:none;stroke-width:2.2;stroke-linecap:round}
.if-anim{stroke-dasharray:7 9;animation:ifDash 2.6s linear infinite}
.if-node rect{transition:.2s}
.if-node:hover rect{filter:brightness(.96)}
.if-pkt{animation:ifPulse 1.6s ease-in-out infinite}
@keyframes ifFlow{from{offset-distance:0%}to{offset-distance:100%}}
/* ===== 波束方向图 / 覆盖地图 ===== */
.beamgrid{display:grid;grid-template-columns:1.05fr 1fr;gap:12px}
@media(max-width:1100px){.beamgrid{grid-template-columns:1fr}}
.plotbox{background:#fbfdff;border:1px solid var(--line);border-radius:10px;padding:10px}
.plotbox h4{font-size:12.5px;color:var(--accent);margin-bottom:6px;font-weight:700}
.polarnode{fill:#0b5cad;transform-origin:center;animation:nodeBreath 2.2s ease-in-out infinite}
@keyframes nodeBreath{0%,100%{opacity:.75}50%{opacity:1}}
.satsweep{animation:satSweep 7s ease-in-out infinite alternate}
@keyframes satSweep{from{transform:translateX(-4px)}to{transform:translateX(4px)}}
.covbeam{animation:covPulse 2.8s ease-in-out infinite}
@keyframes covPulse{0%,100%{opacity:.5}50%{opacity:.85}}
.mapwrap{position:relative;background:linear-gradient(180deg,#eef5fb,#f7fbfe);
  border:1px solid var(--line);border-radius:10px;padding:8px;overflow:hidden}
.mapnote{position:absolute;left:10px;bottom:8px;font-size:10.5px;color:#7d8ea1;
  background:rgba(255,255,255,.75);border-radius:6px;padding:2px 8px}
/* ===== 三维覆盖地球（Canvas 正交投影，可拖拽旋转/滚轮缩放） ===== */
.globebar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.globebar .glabel{font-size:11.5px;color:var(--muted)}
.globebar input[type=range]{width:110px;accent-color:var(--accent)}
#globeCv{cursor:grab;display:block;margin:0 auto;touch-action:none;border-radius:10px;
  background:radial-gradient(ellipse at 30% 22%,#f3f8fd 0%,#e6eef7 45%,#d8e4f0 100%)}
#globeCv.drag{cursor:grabbing}
.globelegend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:#5f7183;
  justify-content:center;margin-top:6px}
.globelegend i{display:inline-block;width:14px;height:8px;border-radius:2px;margin-right:4px;
  vertical-align:middle;border:1px solid rgba(0,0,0,.15)}
/* ===== 二维方向图热力图 ===== */
.heat2d{display:block;margin:0 auto;image-rendering:pixelated;border:1px solid var(--line);border-radius:6px}
.beamgrid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;align-items:start}
@media(max-width:1400px){.beamgrid3{grid-template-columns:1fr}}
/* ===== 接口与协议（MOSA ICD） ===== */
.icdflow{display:flex;gap:0;align-items:stretch;flex-wrap:wrap;margin:6px 0 12px}
.icdstep{flex:1 1 150px;min-width:148px;background:#f6f9fd;border:1px solid #d8e4f0;
  border-radius:9px;padding:9px 11px;position:relative;margin-right:20px}
.icdstep:last-child{margin-right:0}
.icdstep:not(:last-child)::after{content:"▶";position:absolute;right:-16px;top:50%;
  transform:translateY(-50%);color:#9db8d4;font-size:12px}
.icdstep .st-n{font-size:10px;color:var(--accent);font-weight:700;letter-spacing:.4px}
.icdstep .st-t{font-size:13px;font-weight:700;color:#1c2733;margin:2px 0}
.icdstep .st-d{font-size:11px;color:#5f7183;line-height:1.5}
.icdstep.done{background:var(--okbg);border-color:#bfe3cd}
.ifcard{border:1px solid var(--line);border-radius:9px;padding:9px 12px;margin-bottom:8px;background:#fff}
.ifcard .ifh{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12.5px}
.ifcard .ifn{font-weight:700;color:var(--accent)}
.ifrow{display:grid;grid-template-columns:104px 1fr;gap:6px;font-size:12px;padding:2.5px 0;
  border-bottom:1px dashed #eef2f7}
.ifrow:last-child{border-bottom:none}
.ifrow .k{color:var(--muted)}
.ifrow .v{color:#2c3e50}
.stack{margin:2px 0 0 16px;padding:0;font-size:11.5px;line-height:1.75;color:#2c3e50}
.framebox{border:1px solid #d8e4f0;border-radius:9px;padding:8px 11px;margin-bottom:9px;background:#fbfdff}
.framebox .fn{font-weight:700;font-size:12.5px;color:#0b3d6e}
.framebox .fs{font-size:11px;color:var(--muted);margin-bottom:4px}
.bitstrip{display:flex;gap:1px;margin:5px 0 3px;flex-wrap:wrap}
.bitf{flex:1 1 auto;min-width:22px;background:#e8eef7;border:1px solid #c8d8ea;border-radius:3px;
  padding:3px 4px;font-size:10px;text-align:center;color:#1c3a5c;line-height:1.3}
.mosaic{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px;margin:8px 0}
.mosaic .mcard{border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:9px 11px;background:#fff}
.mosaic .mcard.ok{border-left-color:#1a7a2e}
.mosaic .mcard.part{border-left-color:#b07514}
.mosaic .mt{font-weight:700;font-size:12.5px;margin-bottom:3px}
.mosaic .md{font-size:11.5px;color:#5f7183;line-height:1.6}
.mosaic .ms{font-size:11px;margin-top:4px}
/* ===== 弹窗动效 ===== */
.modal-mask.on .modal{animation:modalIn .28s cubic-bezier(.2,.9,.3,1.2)}
@keyframes modalIn{from{opacity:0;transform:translateY(-26px) scale(.96)}to{opacity:1;transform:none}}
.modal-mask.on{animation:maskIn .22s ease}
@keyframes maskIn{from{opacity:0}to{opacity:1}}
/* ===== 流程卡动效 ===== */
.flowcard{animation:fadeUp .4s ease backwards;transition:.2s}
.flowcard:hover{border-color:#bcd3ea;box-shadow:0 4px 14px rgba(11,92,173,.10);transform:translateY(-1px)}
.principle{transition:.2s}
.principle:hover{box-shadow:var(--shadow)}
.scorebar .fill{transition:width .8s cubic-bezier(.25,.8,.3,1)}
.busy.on .spinner{box-shadow:0 0 0 6px rgba(11,92,173,.08)}
/* ===== 数字滚动 ===== */
.rollv{display:inline-block}
/* ===== 打印：关动画，全页签 ===== */
@media print{
  nav.tabs,.tools,.busy,.chips,#btnExport{display:none!important}
  section.tab{display:block!important;page-break-after:always}
  .panel{break-inside:avoid;border:none;box-shadow:none}
  body{background:#fff}
  header.top{background:#fff!important;color:#000!important;box-shadow:none;border-bottom:2px solid #0b5cad}
  header.top h1{color:#0b5cad!important;text-shadow:none}
  header.top .sub,header.top .kpi-top{color:#333!important}
  *{animation:none!important;transition:none!important}
}
.principle{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.principle .ph{background:var(--chip);padding:8px 13px;font-weight:700;color:var(--accent);cursor:pointer;
  display:flex;justify-content:space-between;align-items:center}
.principle .pb{padding:10px 14px;font-size:12.5px;line-height:1.85;white-space:pre-wrap;color:#2c3e50}
.compare-cur{background:#f0f9f3!important}
footer{margin-top:18px;padding-top:10px;border-top:1px solid var(--line);
  font-size:11px;color:#93a3b4;line-height:1.7}
</style>
</head>
<body>
<div id="app">
  <header class="top">
    <div>
      <h1>🛰 通信卫星有效载荷方案设计器 <span class="badge-ver">v4</span></h1>
      <div class="sub">payload-design 五步闭环：需求解析 → 架构规划 → 天线五维选型 + 转发器方案 →
        货架单机选型 → 链路校核（C/N 余量 ≥3dB） ｜ <span class="badge-kg" id="kgver">知识图谱</span>
        <span class="badge-kg">GRASP 波束仿真</span></div>
    </div>
    <div class="tools">
      <span class="kpi-top" id="topkpi">EIRP <b>—</b> ｜ G/T <b>—</b> ｜ 余量 <b>—</b> ｜ <span class="tag info">未计算</span></span>
      <button class="btn solid" id="btnSuggest">💡 一键建议值</button>
      <button class="btn" id="btnDiag">🩺 方案诊断</button>
      <button class="btn" id="btnSave">💾 保存方案</button>
      <button class="btn" id="btnLoad">📂 载入方案</button>
      <button class="btn" id="btnExport">📄 导出 Word</button>
      <button class="btn" id="btnPrint">🖨 打印 / PDF</button>
    </div>
  </header>

  <nav class="tabs" id="tabs">
    <button data-tab="tab-cfg" class="on">① 方案配置</button>
    <button data-tab="tab-ov">② 方案总览</button>
    <button data-tab="tab-diag">③ 载荷组成框图</button>
    <button data-tab="tab-ant">④ 天线链路预算</button>
    <button data-tab="tab-trp">⑤ 转发器链路预算</button>
    <button data-tab="tab-flow">⑥ 信息流设计</button>
    <button data-tab="tab-eq">⑦ 单机清单与选型</button>
    <button data-tab="tab-cmp">⑧ 方案对比</button>
    <button data-tab="tab-pri">⑨ 原理介绍</button>
    <button data-tab="tab-cons">⑩ 约束校验与回环</button>
    <button data-tab="tab-icd">⑪ 接口与协议（MOSA）</button>
    <button data-tab="tab-orbit">⑫ 轨道覆盖仿真</button>
    <button data-tab="tab-rob">⑬ 稳健性分析</button>
  </nav>

  <section class="tab on" id="tab-cfg"><div id="cfgui"></div></section>
  <section class="tab" id="tab-ov"><div id="ov"></div></section>
  <section class="tab" id="tab-diag"><div id="diag"></div></section>
  <section class="tab" id="tab-ant"><div id="ant"></div></section>
  <section class="tab" id="tab-trp"><div id="trp"></div></section>
  <section class="tab" id="tab-flow"><div id="flow"></div></section>
  <section class="tab" id="tab-eq"><div id="eq"></div></section>
  <section class="tab" id="tab-cmp"><div id="cmp"></div></section>
  <section class="tab" id="tab-pri"><div id="pri"></div></section>
  <section class="tab" id="tab-cons"><div id="cons"></div></section>
  <section class="tab" id="tab-icd"><div id="icd"></div></section>
  <section class="tab" id="tab-orbit"><div id="orbit"></div></section>
  <section class="tab" id="tab-rob"><div id="rob"></div></section>

  <footer id="foot">
    通信卫星有效载荷方案设计器 · 与 payload-design skill 对齐（三级选型闭环 / 天线五维选型 / 货架单机优先 / 25 条工程约束）·
    计算引擎：design_engine.py（Python 后端直算，前端仅呈现）· 单机默认值为工程典型值，仅用于方案级论证，正式设计以详细链路预算为准
  </footer>
</div>

<div class="busy" id="busy"><div class="spinner"></div><div class="muted" id="busytxt">设计引擎计算中…</div></div>

<!-- 方案诊断弹窗：方案不合适 → 弹出具体问题，便于修改 -->
<div class="modal-mask" id="diagMask">
  <div class="modal">
    <div class="mhead bad" id="diagHead">
      <h3 id="diagTitle">🩺 方案诊断</h3>
      <button class="x" id="diagClose">✕</button>
    </div>
    <div class="mbody" id="diagBody"></div>
    <div class="mfoot">
      <button class="btn" id="diagGoCons">查看约束校验页 →</button>
      <button class="btn solid" id="diagCloseBtn">知道了，返回修改</button>
    </div>
  </div>
</div>

<!-- 参数建议弹窗：一键给出全部参数建议值 + 依据 -->
<div class="modal-mask" id="sugMask">
  <div class="modal">
    <div class="mhead ok">
      <h3>💡 参数建议值（按当前轨道/覆盖区/业务/频段/天线体制联动计算）</h3>
      <button class="x" id="sugClose">✕</button>
    </div>
    <div class="mbody" id="sugBody"></div>
    <div class="mfoot">
      <button class="btn" id="sugCancel">取消</button>
      <button class="btn solid" id="sugApply">✓ 应用全部建议值到配置</button>
    </div>
  </div>
</div>

<!-- 导出结果弹窗：后端落盘成功 → 展示路径 + 打开文件/文件夹；网页态提供下载兜底 -->
<div class="modal-mask" id="expMask">
  <div class="modal">
    <div class="mhead ok">
      <h3 id="expTitle">📄 报告已生成</h3>
      <button class="x" id="expClose">✕</button>
    </div>
    <div class="mbody" id="expBody"></div>
    <div class="mfoot">
      <button class="btn" id="expCloseBtn">关闭</button>
      <button class="btn" id="expReveal">📂 打开所在文件夹</button>
      <button class="btn solid" id="expOpen">📝 用 Word 打开</button>
    </div>
  </div>
</div>

<script>
'use strict';
let META = null, CFG = null, RES = null, CUR = null;

/* ---------- 工具 ---------- */
const el = id => document.getElementById(id);
function h(s){ return String(s===null||s===undefined?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function n(v,nd){ if(v===null||v===undefined||v===""||isNaN(v)) return "—"; nd=nd===undefined?2:nd;
  let s=(+v).toFixed(nd); s=s.replace(/\.?0+$/,""); return s==="-0"?"0":s; }
function busy(on,txt){ el("busy").classList.toggle("on",!!on); if(txt) el("busytxt").textContent=txt; }
function tag(ok,txt){ return '<span class="tag '+(ok?"ok":"bad")+'">'+h(txt)+'</span>'; }
function deep(o){ return JSON.parse(JSON.stringify(o)); }

/* ---------- API 双通道：优先 HTTP fetch（exe/网页版统一），pywebview 桥兜底 ---------- */
async function apiCall(method, payload){
  // 通道1：内置 HTTP 服务（exe 加载 http://127.0.0.1:PORT/，网页版同源）
  try{
    const opt = payload
      ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}
      : {method:"GET"};
    const r = await fetch("/api/"+method, opt);
    if(r.ok) return await r.json();
  }catch(e){/* HTTP 不可用 → 走桥 */}
  // 通道2：pywebview JS 桥（桌面加速通道）
  if(window.pywebview && pywebview.api && typeof pywebview.api[method]==="function"){
    if(method==="design") return await pywebview.api.design(payload.cfg, payload.with_compare);
    if(method==="suggest") return await pywebview.api.suggest(payload);
    if(method==="beam"||method==="pattern"||method==="coverage"||method==="orbit"||method==="export_file"||method==="export"||method==="protocol"||method==="open_file"||method==="reveal_file") return await pywebview.api[method](payload);
    return await pywebview.api[method]();
  }
  throw new Error("无法连接设计引擎（HTTP 与 JS 桥均不可用）");
}

/* ---------- 配置界面 ---------- */
function cfgField(key,label,type,opts,hint){
  const v = CFG[key]===undefined||CFG[key]===null?"":CFG[key];
  let inp;
  if(type==="select"){
    inp='<select data-k="'+key+'">'+opts.map(o=>{
      const val=o[0],tx=o[1];
      return '<option value="'+h(val)+'"'+(String(v)===String(val)?" selected":"")+'>'+h(tx)+'</option>';
    }).join("")+'</select>';
  }else if(type==="check"){
    inp='<label style="display:flex;align-items:center;gap:6px;font-size:13px">'+
        '<input type="checkbox" data-k="'+key+'"'+(v?" checked":"")+' style="width:auto">'+h(label)+'</label>';
    label="";
  }else{
    inp='<input type="'+(type||"text")+'" data-k="'+key+'" value="'+h(v)+'" step="any">';
  }
  return '<div class="field">'+(label?'<label>'+h(label)+'</label>':'')+inp+
         '<div class="hint" id="hint_'+h(key)+'" data-base="'+h(hint||"")+'">'+h(hint||"")+'</div></div>';
}
function optsOf(obj,keys){ return keys.map(k=>[k,obj[k].cn||k]); }
function bandOpts(){ return META.band_keys.map(b=>[b,b]); }
/* 覆盖区下拉：基础覆盖 + 全球国家（按区域分组 optgroup） */
function covSelectHTML(v){
  const base=[],groups={};
  META.coverage_keys.forEach(k=>{
    const c=META.coverage[k]; if(!c) return;
    if(c.country){ const r=c.region||"其他"; (groups[r]=groups[r]||[]).push(k); }
    else base.push(k);
  });
  let html='<select data-k="coverage">';
  html+='<optgroup label="—— 基础覆盖类型 ——">'+base.map(k=>
    '<option value="'+h(k)+'"'+(String(v)===String(k)?" selected":"")+'>'+h(META.coverage[k].cn||k)+'</option>').join("")+'</optgroup>';
  Object.keys(groups).forEach(r=>{
    html+='<optgroup label="—— '+h(r)+' ——">'+groups[r].map(k=>{
      const c=META.coverage[k];
      const tx=(c.cn||k)+"（"+(c.geo_lon!==undefined?"GEO "+c.geo_lon+"°":"")+(c.rain?" · "+c.rain:"")+"）";
      return '<option value="'+h(k)+'"'+(String(v)===String(k)?" selected":"")+'>'+h(tx)+'</option>';
    }).join("")+'</optgroup>';
  });
  return html+'</select>';
}

function renderCfgUI(){
  const orbOpts=optsOf(META.orbits,META.orbit_keys);
  const svcOpts=optsOf(META.services,META.service_keys);
  const modeOpts=optsOf(META.modes,META.mode_keys);
  const antOpts=optsOf(META.ant_types,META.ant_type_keys);
  const subOpts=[["","（不适用）"]].concat(optsOf(META.array_subtypes,META.array_subtype_keys));
  const ampOpts=[["","自动（按体制推荐）"],["TWTA","TWTA 行波管"],["SSPA","SSPA 固态(GaN)"],["MPA","MPA 功率池矩阵"]];
  const modeCapOpts=[["全球覆盖","全球覆盖（宽波束/赋形）"],["区域赋形","区域赋形（赋形波束）"],["点波束","点波束（固定多波束）"],
    ["单波束","单波束"],["多波束","多波束（频率复用）"],["波束跳变","波束跳变（时分捷变）"],
    ["相控扫描","相控扫描（电扫捷变）"],["在轨重构","在轨重构（波束/子带/功率/路由）"]];
  const platOpts=[["自动","自动选型"]].concat(META.platforms.map(p=>[p.id,p.cn]));
  const islOpts=[["","不配置"],["激光","激光星间链路"],["微波","微波星间链路"]];

  el("cfgui").innerHTML =
  '<div class="panel"><h2>场景预设（8 个典型场景一键载入，可再修改）</h2>'+
    '<div class="chips" id="scenChips">'+
    Object.keys(META.scenarios).map(k=>'<span class="chip" data-sc="'+k+'">'+h(META.scenarios[k].label)+'</span>').join("")+
    '<span class="chip" data-sc="__default">空白新方案</span></div>'+
    '<div class="note" id="scenDesc">选择场景后自动填充下方全部配置项；所有项均可修改，点击「开始设计」重算。</div></div>'+

  '<div class="panel"><h2>需求与轨道（步骤 1~2：需求解析 / 架构规划）</h2>'+
    '<div class="grid g4">'+
      cfgField("name","方案名称","text",null,"用于保存/导出")+
      cfgField("service","业务类型","select",svcOpts,"决定容量/终端能力/可用性设计点")+
      cfgField("orbit","轨道","select",orbOpts,"GEO/MEO/LEO/SSO/HEO")+
      '<div class="field"><label>覆盖区（含全球国家）</label>'+covSelectHTML(CFG.coverage||"")+
        '<div class="hint">选择国家自动带出 GEO 定点/仰角/雨衰区；决定波束密度与链路余量附加</div></div>'+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("band","用户链路频段","select",bandOpts(),"天线选型频段硬过滤")+
      cfgField("feeder_band","馈电链路频段","select",bandOpts(),"可与用户链路异频")+
      cfgField("el_deg","最低用户仰角 (°)","number",null,"决定最差斜距与雨衰")+
      cfgField("A_avail","链路可用性 (%)","number",null,"雨衰按 A(p)∝p^-0.6 折算")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      '<div class="field" style="grid-column:1/-1"><label>多覆盖区（可选，逗号分隔；链路自动按最差区闭合）</label>'+
        '<input type="text" data-k="coverage_list" value="'+h(CFG.coverage_list||"")+'" '+
        'placeholder="如：巴基斯坦,沙特阿拉伯,印度尼西亚（含全球国家库任意组合）">'+
        '<div class="hint" id="hint_coverage_list">填写 ≥2 个覆盖区即启用多区合成：各区独立几何推导（仰角/斜距/雨衰），'+
        '链路按最差区（雨衰+斜距严重度最高）闭合，波束总数=Σ各区密铺；一键建议值同步按合成包络给出</div></div>'+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("C_req_ovr","容量需求覆盖 (Gbps)","number",null,"留空取业务库默认")+
      cfgField("GT_term","用户终端 G/T (dB/K)","number",null,"留空取业务库默认")+
      cfgField("EIRP_term","用户终端 EIRP (dBW)","number",null,"留空取业务库默认；馈电关口站 EIRP_gs 在高级项")+
      cfgField("M_target","余量门限 (dB)","number",null,"skill 规范 ≥3dB")+
    '</div><div class="note small" id="reqNote"></div></div>'+

  '<div class="panel"><h2>载荷体制与天线（步骤 3：五维选型对象）</h2>'+
    '<div class="grid g4">'+
      cfgField("mode","转发体制","select",modeOpts,"透明 / 数字透明 DTP / 再生处理")+
      cfgField("ant_type","天线类型","select",antOpts,"固面 / 相控阵 / 伞状可展开")+
      cfgField("array_subtype","相控阵子体制","select",subOpts,"直射阵/反射阵/数字模拟混合/纯数字/模拟拼接")+
      cfgField("Mode","工作模式需求","select",modeCapOpts,"天线五维选型第⑤维")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("D_ap","反射面/阵面口径 D (m)","number",null,"固面/伞状用；相控阵为阵面等效口径。手动修改后自动锁定（不被货架替代）")+
      cfgField("N_el","阵元数 N_el","number",null,"相控阵用；G=10lg(N_el·η)+G_el−扫描损耗。手动修改后自动锁定")+
      cfgField("θ_scan","扫描角 (°)","number",null,"相控阵 cos^1.5θ 扫描损耗")+
      cfgField("η_ill","口径效率/照射效率 (%)","number",null,"留空按类型/子体制典型值")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("force_custom_ant","锁定用户天线电气参数","check",null,
        "勾选后天线严格按上方 D/N_el/η/θ_scan 计算（定制路径，货架产品仅列参考）；不勾选则货架选型可替代口径。手动修改口径/阵元数会自动勾选")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("N_beam","波束数 N_beam","number",null,"留空按覆盖几何 1.209(r_cov/r_beam)² 建议")+
      cfgField("B_beam","单波束带宽 (MHz)","number",null,"频率规划 c-13：N_beam×B_beam ≤ B_total×k")+
      cfgField("B_carrier","单载波带宽 (MHz)","number",null,"链路预算噪声带宽")+
      cfgField("k_reuse","频率复用色数 k","number",null,"留空按覆盖区典型值（区域 4 / 热点 7）")+
      cfgField("n_pol","极化复用 n_pol","number",null,"系统容量 c-12：C_sys=N_beam×B_beam×η×n_pol；双极化=2（默认）")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("amp_type","功放类型","select",ampOpts,"透明→TWTA / DTP→MPA / 再生→SSPA")+
      cfgField("P_out","功放功率覆盖 (W)","number",null,"留空由 EIRP 需求反推（skill 五维①核心）")+
      cfgField("EIRP_gs","关口站 EIRP (dBW)","number",null,"馈电上行驱动")+
      cfgField("life_yr","设计寿命 (年)","number",null,"平台/火箭校核参考")+
    '</div></div>'+

  '<div class="panel"><h2>星间链路·星座组网与选型偏好</h2>'+
    '<div class="grid g4">'+
      cfgField("isl_type","星间链路","select",islOpts,"LEO/MEO 组网建议激光")+
      cfgField("isl_r_gbps","星间速率 (Gbps)","number",null,"激光终端货架：5/10/20Gbps")+
      cfgField("N_sat","星座卫星数 N_sat","number",null,"≥2 启用组网指标（Walker 数值覆盖仿真）；留空由一键建议值反推")+
      cfgField("N_plane","轨道面数 P","number",null,"Walker N/P/F；留空取 √N_sat")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("incl_deg","轨道倾角 (°)","number",null,"全球宽带 53°主壳层；区域=纬度+15°；留空 53°")+
      cfgField("phase_f","相位因子 F","number",null,"Walker 相位因子（相邻面同序号星错开 360F/N），典型 1")+
      cfgField("platform_pref","平台偏好","select",platOpts,"默认自动：最小可行平台优先")+
      cfgField("cov_r_km","覆盖半径覆盖 (km)","number",null,"留空取覆盖区库默认")+
    '</div><div class="grid g4" style="margin-top:10px">'+
      cfgField("beam_r_km","波束覆盖半径 (km)","number",null,"决定几何建议波束数")+
      '<div class="field" style="display:flex;align-items:flex-end">'+
        '<button class="btn solid" id="btnRun" style="width:100%;padding:9px">🚀 开始设计（全流程计算 + 方案对比）</button></div>'+
      '<div class="field" style="display:flex;align-items:flex-end">'+
        '<button class="btn" id="btnRunFast" style="width:100%;padding:9px">⚡ 快速重算（跳过方案对比）</button></div>'+
    '</div>'+
    '<div class="note small">「开始设计」跑当前方案 + 体制替代（透明/DTP/再生）+ 天线替代（同频段可行的固面/相控阵/伞状）共至多 6 个方案的全流程与六维评分对比；「快速重算」仅算当前方案。</div></div>';

  bindCfgEvents();
  refreshReqNote();
}

function bindCfgEvents(){
  document.querySelectorAll("#cfgui [data-k]").forEach(inp=>{
    const ev = inp.type==="checkbox" ? "change" : (inp.tagName==="SELECT"?"change":"input");
    inp.addEventListener(ev,e=>{
      const k=e.target.dataset.k;
      CFG[k] = e.target.type==="checkbox" ? e.target.checked : e.target.value;
      // 用户手动改口径/阵元数 → 自动锁定电气参数（货架不再替代，保证"输入5m就按5m算"）
      if((k==="D_ap"||k==="N_el") && String(CFG[k]).trim()!=="" && !CFG.force_custom_ant){
        CFG.force_custom_ant=true;
        const cb=document.querySelector('#cfgui [data-k="force_custom_ant"]');
        if(cb) cb.checked=true;
      }
      refreshReqNote();
      // 关键选择项变化 → 防抖刷新建议值提示
      if(["service","orbit","coverage","coverage_list","band","ant_type","array_subtype","mode","N_sat"].includes(k))
        scheduleHintSuggest();
    });
  });
  document.querySelectorAll("#scenChips .chip").forEach(c=>{
    c.addEventListener("click",()=>{
      document.querySelectorAll("#scenChips .chip").forEach(x=>x.classList.remove("on"));
      c.classList.add("on");
      const sc=c.dataset.sc;
      if(sc==="__default"){ CFG=deep(META.default_cfg); el("scenDesc").textContent="空白新方案：从默认配置起步，逐项修改。"; }
      else{ const s=META.scenarios[sc];
        CFG=Object.assign(deep(META.default_cfg),deep(s.cfg),{name:s.label,isl_on:!!s.cfg.isl_on});
        el("scenDesc").textContent=s.desc; }
      renderCfgUI();
      document.querySelectorAll("#scenChips .chip").forEach(x=>{
        if(x.dataset.sc===sc) x.classList.add("on");
      });
    });
  });
  el("btnRun").addEventListener("click",()=>runDesign(true));
  el("btnRunFast").addEventListener("click",()=>runDesign(false));
}

/* ---------- 行内建议提示：关键选择项变化后静默拉取建议值，显示在字段 hint 上 ---------- */
let _sugTimer=null, _sugSeq=0;
function scheduleHintSuggest(){
  clearTimeout(_sugTimer);
  _sugTimer=setTimeout(fetchHintSuggest,500);
}
async function fetchHintSuggest(){
  const seq=++_sugSeq;
  try{
    const cfgOut=deep(CFG); cfgOut.isl_on=!!cfgOut.isl_type;
    const r=await apiCall("suggest",{cfg:cfgOut});
    if(seq!==_sugSeq||!r.ok) return;   // 过期响应丢弃
    const S=r.result;
    Object.keys(S.values||{}).forEach(k=>{
      const hintEl=el("hint_"+k);
      if(!hintEl) return;
      const v=S.values[k], note=S.notes[k]||"";
      const cur=CFG[k];
      const diff=(cur!==undefined&&cur!==null&&String(cur)!==""&&String(cur)!==String(v));
      hintEl.innerHTML=(diff?'<span style="color:#b07514">💡 建议 <b>'+h(v===""?"（留空取库默认）":v)+'</b></span> · ':'<span style="color:#1d8a4e">💡 建议 <b>'+h(v===""?"（留空取库默认）":v)+'</b></span> · ')+
        '<span style="cursor:pointer;color:#0b5cad" data-fill="'+h(k)+'" data-v="'+h(v)+'">采用</span> ｜ '+h(note);
      const a=hintEl.querySelector("[data-fill]");
      if(a) a.addEventListener("click",()=>{
        CFG[k]=a.dataset.v;
        const inp=document.querySelector('#cfgui [data-k="'+k+'"]');
        if(inp){ if(inp.tagName==="SELECT") inp.value=a.dataset.v; else inp.value=a.dataset.v; }
        hintEl.textContent=hintEl.dataset.base||"";
        refreshReqNote();
      });
    });
  }catch(e){/* 静默失败，不打扰 */}
}

function refreshReqNote(){
  const svc=META.services[CFG.service]||{};
  const orb=META.orbits[CFG.orbit]||{};
  const cov=META.coverage[CFG.coverage]||{};
  const mode=META.modes[CFG.mode]||{};
  const ant=META.ant_types[CFG.ant_type]||{};
  el("reqNote").innerHTML=
    "<b>需求解析（业务库默认）：</b>容量 "+n(svc.C_gbps,2)+" Gbps ｜ 终端 G/T "+n(svc.GT_term,1)+" dB/K ｜ 终端 EIRP "+n(svc.EIRP_term,0)+
    " dBW ｜ 可用性 "+n(svc.avail,2)+"% ｜ 设计点 (C/N) "+n(svc.design_cn,0)+" dB<br>"+
    "<b>轨道：</b>"+h(orb.cn||"")+"（高度 "+n(orb.alt_km,0)+" km，"+h(orb.note||"")+"）<br>"+
    "<b>覆盖区：</b>"+h(cov.cn||"")+"（波束密度 k="+n(cov.k_typ,0)+"，动态余量附加 +"+n(cov.margin_add_db,1)+" dB）"+
    " ｜ <b>体制：</b>"+h(mode.cn||"")+"（星上时延 "+h(mode.delay||"")+"）"+
    " ｜ <b>天线：</b>"+h(ant.cn||"")+(CFG.array_subtype&&META.array_subtypes[CFG.array_subtype]?"（"+h(META.array_subtypes[CFG.array_subtype].cn)+"）":"")+
    "<br><b>"+h(svc.note||"")+"</b>";
}

/* ---------- 计算 ---------- */
async function runDesign(withCompare, silentDiag){
  busy(true, withCompare?"设计引擎全流程计算（含多方案对比）…":"设计引擎计算中…");
  try{
    const cfgOut=deep(CFG);
    cfgOut.isl_on = !!cfgOut.isl_type;
    const r=await apiCall("design",{cfg:cfgOut, with_compare:!!withCompare});
    if(!r.ok){ alert("设计引擎错误：\n"+r.error+"\n\n"+(r.trace||"").slice(-600)); return; }
    RES=r.result; CUR=RES;
    renderAll();
    showTab("tab-ov");
    // 方案不合适 → 自动弹出具体问题清单（便于修改）
    const dg=RES.diagnosis;
    if(!silentDiag && dg && dg.level!=="ok") showDiagnosis(dg);
  }catch(e){ alert("调用失败："+e); }
  finally{ busy(false); }
}

/* ---------- 诊断弹窗：方案不合适 → 弹出具体问题 ---------- */
function showDiagnosis(dg){
  const head=el("diagHead");
  head.className="mhead "+(dg.level==="bad"?"bad":"warn");
  const nBad=dg.issues.filter(i=>i.sev==="bad").length;
  const nWarn=dg.issues.filter(i=>i.sev==="warn").length;
  el("diagTitle").innerHTML=(dg.level==="bad"
    ? "⛔ 方案不合适 —— 发现 "+nBad+" 项硬性问题"+(nWarn?"、"+nWarn+" 项警告":"")+"（判据 "+h(dg.judge||"")+"）"
    : "⚠️ 方案可行但有 "+nWarn+" 项警告（判据 "+h(dg.judge||"")+"）");
  el("diagBody").innerHTML=dg.issues.map((it,idx)=>
    '<div class="issue '+it.sev+'">'+
      '<div class="it">'+(it.sev==="bad"?"⛔":"⚠️")+' ['+h(it.id)+'] '+h(it.title)+'</div>'+
      '<div class="id">'+h(it.detail||"")+'</div>'+
      (it.suggestion?'<div class="is">🔧 修改建议：'+h(it.suggestion)+'</div>':"")+
      (it.param?'<div class="ip">涉及参数：'+String(it.param).split("/").map(s=>s.trim()).filter(Boolean)
        .map(s=>'<code data-p="'+h(s)+'">'+h(s)+'</code>').join(" ")
        +' <span class="muted">（点击参数名跳回配置页定位）</span></div>':"")+
    '</div>').join("") || '<div class="okbox">全部约束闭合，方案可行。</div>';
  el("diagMask").classList.add("on");
  // 参数名点击 → 关闭弹窗、跳配置页并高亮对应输入框
  el("diagBody").querySelectorAll("code[data-p]").forEach(c=>{
    c.addEventListener("click",()=>{
      el("diagMask").classList.remove("on");
      showTab("tab-cfg");
      const key=c.dataset.p.split(" ")[0];
      const inp=document.querySelector('#cfgui [data-k="'+key+'"]');
      if(inp){ inp.focus(); inp.scrollIntoView({behavior:"smooth",block:"center"});
        inp.style.boxShadow="0 0 0 3px rgba(11,92,173,.35)";
        setTimeout(()=>{inp.style.boxShadow="";},2500); }
    });
  });
}

/* ---------- 参数建议弹窗：一键建议值（闭环：建议→全流程验证→自动修正→评级） ---------- */
let SUG=null;
async function showSuggest(){
  busy(true,"一键建议值闭环：建议 → design_all 全流程验证 → 自动修正 → 评级（≤3 轮）…");
  try{
    const cfgOut=deep(CFG); cfgOut.isl_on=!!cfgOut.isl_type;
    const r=await apiCall("suggest",{cfg:cfgOut,closed:true});
    if(!r.ok){ alert("建议值计算失败：\n"+r.error); return; }
    SUG=r.result;
    const cl=SUG.closed||{};
    const order=["band","user_band","feeder_band","ant_type","array_subtype","mode","isl_type",
      "el_deg","A_avail","M_target","life_yr","cov_r_km","beam_r_km","N_beam","B_beam",
      "k_reuse","n_pol","B_carrier","C_req_ovr","GT_term","EIRP_term","EIRP_gs","D_ap","N_el",
      "θ_scan","η_ill","amp_type","P_out","Mode","isl_r_gbps","N_sat","N_plane","incl_deg","phase_f"];
    const cn={el_deg:"最低用户仰角(°)",A_avail:"可用性(%)",M_target:"余量门限(dB)",life_yr:"设计寿命(年)",
      cov_r_km:"覆盖半径(km)",beam_r_km:"波束半径(km)",N_beam:"波束数",B_beam:"单波束带宽(MHz)",
      k_reuse:"复用色数k",n_pol:"极化复用",B_carrier:"单载波带宽(MHz)",C_req_ovr:"容量需求(Gbps)",
      GT_term:"终端G/T(dB/K)",EIRP_term:"终端EIRP(dBW)",EIRP_gs:"关口站EIRP(dBW)",D_ap:"天线口径D(m)",
      N_el:"阵元数N_el","θ_scan":"扫描角(°)","η_ill":"口径效率(%)",amp_type:"功放类型",
      P_out:"功放功率(W)",Mode:"工作模式需求",isl_r_gbps:"星间速率(Gbps)",
      band:"用户链路频段",user_band:"用户频段",feeder_band:"馈电频段",ant_type:"天线类型",
      array_subtype:"相控阵子体制",mode:"转发体制",isl_type:"星间链路",
      N_sat:"星座卫星数",N_plane:"轨道面数P",incl_deg:"轨道倾角(°)",phase_f:"相位因子F"};
    const rows=order.filter(k=>k in SUG.values).map(k=>{
      const v=SUG.values[k];
      const cur=CFG[k];
      const chg=(cur!==undefined&&cur!==null&&String(cur)!==String(v))?"style='background:#fffbe8'":"";
      return '<div class="sug-item" '+chg+'><span class="sk">'+h(cn[k]||k)+
        '</span><span class="sv">'+h(v===""?"（留空取库默认）":v)+
        '</span><span class="sn">'+h(SUG.notes[k]||"")+'</span></div>';
    }).join("");
    // 闭环结论横幅
    let banner="";
    if(cl && cl.grade){
      const gc={A:"#1a7a2e",B:"#0b5cad",C:"#b8860b",D:"#c0392b"}[cl.grade]||"#444";
      const okc=cl.feasible;
      banner='<div style="border:2px solid '+gc+';border-radius:8px;padding:10px 14px;margin:6px 0 10px;background:'+
        (okc?"#f3fbf5":"#fdf4f3")+'">'+
        '<div style="font-size:15px;font-weight:bold;color:'+gc+'">'+
        (okc?"✓ ":"⚠ ")+'闭环验证结论：评级 '+h(cl.grade)+'（迭代 '+n(cl.iters,0)+' 轮 · 硬准则 '+h(cl.pass_hard||"—")+
        ' · 软准则 '+h(cl.pass_soft||"—")+' · 六维 '+n(cl.score_total,2)+'/10）</div>'+
        '<div style="font-size:12.5px;margin-top:5px;color:#222">'+h(cl.conclusion||"")+'</div>'+
        ((cl.adjustments&&cl.adjustments.length)?
          '<div style="font-size:12px;margin-top:6px;color:#8a3b12"><b>自动修正：</b><ul style="margin:3px 0 0 18px">'+
          cl.adjustments.map(a=>'<li>'+h(a)+'</li>').join("")+'</ul></div>':"")+
        ((cl.advice&&cl.advice.length&&!okc)?
          '<div style="font-size:12px;margin-top:6px;color:#c0392b"><b>未闭合（需人工决策）：</b><ul style="margin:3px 0 0 18px">'+
          cl.advice.slice(0,5).map(a=>'<li>'+h(a)+'</li>').join("")+'</ul></div>':"")+
        '</div>';
    }
    // 体制第一性原理推断依据（业务+轨道+覆盖 → 频段/天线/体制/ISL）
    let archBox="";
    const A=SUG.arch;
    if(A && (A.reasons||[]).length){
      archBox='<div style="border:1px solid #cfe0f2;border-radius:8px;padding:10px 14px;margin:6px 0 10px;background:#f6fafd">'+
        '<div style="font-size:13.5px;font-weight:bold;color:#0b5cad;margin-bottom:4px">🧭 体制第一性原理推断'+
        ((A.changed&&Object.keys(A.changed).length)?'（<span style="color:#b07514">黄色高亮项为推断覆盖</span>）':'（与当前配置一致）')+'</div>'+
        '<ul style="margin:2px 0 0 18px;font-size:12.5px;line-height:1.7;color:#222">'+
        A.reasons.map(r=>'<li>'+h(r)+'</li>').join("")+'</ul></div>';
    }
    // 星座组网建议（Walker 构型 + 数值覆盖仿真）
    let csBox="";
    const CS=SUG.constellation;
    if(CS){
      csBox='<div style="border:1px solid #cfe8d6;border-radius:8px;padding:10px 14px;margin:6px 0 10px;background:#f5fbf7">'+
        '<div style="font-size:13.5px;font-weight:bold;color:#1a7a2e;margin-bottom:4px">🛰️ 星座组网建议（'+
        (CS.continuous?"数值仿真验证连续覆盖":"存在覆盖间隙，建议调整")+'）</div>'+
        '<div style="font-size:12.5px;line-height:1.7;color:#222">'+h(CS.note||"")+'</div></div>';
    }
    // 多覆盖区合成（最差区闭合）
    let mcBox="";
    const MC=SUG.multi_coverage;
    if(MC && (MC.regions||[]).length){
      mcBox='<div style="border:1px solid #f0dfc0;border-radius:8px;padding:10px 14px;margin:6px 0 10px;background:#fdfaf4">'+
        '<div style="font-size:13.5px;font-weight:bold;color:#8a5b12;margin-bottom:4px">🌏 多覆盖区合成（'+MC.regions.length+' 区）</div>'+
        '<table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="background:#f6efe0">'+
        '<th style="padding:3px 6px;border:1px solid #e5d8bc;text-align:left">覆盖区</th>'+
        '<th style="padding:3px 6px;border:1px solid #e5d8bc">最低仰角</th>'+
        '<th style="padding:3px 6px;border:1px solid #e5d8bc">斜距(km)</th>'+
        '<th style="padding:3px 6px;border:1px solid #e5d8bc">雨衰附加(dB)</th>'+
        '<th style="padding:3px 6px;border:1px solid #e5d8bc">波束数(密铺)</th></tr>'+
        MC.regions.map(r=>'<tr'+(MC.worst&&r.key===MC.worst.key?' style="background:#fbeee0;font-weight:bold"':'')+'>'+
          '<td style="padding:3px 6px;border:1px solid #e5d8bc">'+h(r.cn)+(MC.worst&&r.key===MC.worst.key?" ⬅ 最差区":"")+'</td>'+
          '<td style="padding:3px 6px;border:1px solid #e5d8bc;text-align:center">'+n(r.el_min,0)+'°</td>'+
          '<td style="padding:3px 6px;border:1px solid #e5d8bc;text-align:center">'+n(r.d_slant,0)+'</td>'+
          '<td style="padding:3px 6px;border:1px solid #e5d8bc;text-align:center">+'+n(r.A_dyn,1)+'</td>'+
          '<td style="padding:3px 6px;border:1px solid #e5d8bc;text-align:center">'+n(r.N_beam_geo,0)+'</td></tr>').join("")+
        '</table><div style="font-size:12px;margin-top:5px;color:#5f4a20">链路按最差区（雨衰+斜距严重度最高）闭合；'+
        '波束总数=Σ各区密铺='+MC.n_beam_total+'</div></div>';
    }
    el("sugBody").innerHTML=banner+archBox+csBox+mcBox+
      '<div class="note small">黄色底＝与当前配置不同。以下建议值已通过 design_all 全流程闭环验证'+
      (cl&&cl.feasible?"（方案可行，可直接应用）":"")+'；应用后仅覆盖下表参数，其余配置保持不变；应用后自动快速重算。</div>'+rows;
    el("sugMask").classList.add("on");
  }catch(e){ alert("建议值调用失败："+e); }
  finally{ busy(false); }
}
function applySuggest(){
  if(!SUG) return;
  Object.keys(SUG.values).forEach(k=>{ CFG[k]=SUG.values[k]; });
  el("sugMask").classList.remove("on");
  renderCfgUI();
  runDesign(false,true);
}

function renderAll(){
  renderTop(); renderOv(); renderDiag(); renderAnt(); renderTrp();
  renderFlow(); renderEq(); renderCmp(); renderPri(); renderCons();
  // 稳健性分析（robust 随 design_all 同步返回，无需懒加载）
  try{ renderRobust(); }catch(e){ console.warn("renderRobust:",e); }
  // 接口与协议：方案变更后失效缓存；仅当页签正显示时立即重算（否则切入时懒加载）
  ICD=null;
  if(document.querySelector("#tab-icd.on")) renderIcd();
  // 轨道覆盖仿真：同样失效缓存 + 懒加载
  ORBSIM=null;
  if(document.querySelector("#tab-orbit.on")) renderOrbit();
  animateKpis();
}

/* ---------- 顶栏 KPI ---------- */
function renderTop(){
  const s=RES.res.summary;
  const pass=s.fail.length===0;
  el("topkpi").innerHTML="EIRP <b>"+n(s.EIRP,1)+"</b> dBW ｜ G/T <b>"+n(s.GT,1)+"</b> dB/K ｜ 余量 上<b>"+
    n(s.M_up,1)+"</b>/下<b>"+n(s.M_dn,1)+"</b> dB ｜ "+
    '<span class="tag '+(pass?"ok":"bad")+'">判据 '+s.judge_pass+"/"+s.judge_total+(pass?"":" · 未闭合 "+s.fail.join(","))+"</span>";
  el("kgver").textContent=h(META.kg_meta||"");
}

/* ---------- ② 方案总览 ---------- */
function kpi(k,v,u,cls){
  const isNum=typeof v!=="string"&&v!==null&&v!==undefined&&!isNaN(v);
  const vHtml=isNum
    ? '<span class="rollv" data-v="'+(+v)+'">'+n(v,2)+'</span>'
    : h(v);
  return '<div class="kpi '+(cls||"")+'"><div class="k">'+h(k)+'</div><div class="v">'+
    vHtml+' <span class="u">'+h(u||"")+'</span></div></div>';
}
/* KPI 数字滚动：从 0 缓动到目标值（0.6s），打印/减弱动画偏好时直接终值 */
function animateKpis(root){
  if(window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const nodes=(root||document).querySelectorAll(".rollv");
  nodes.forEach(sp=>{
    if(sp.dataset.done) return; sp.dataset.done="1";
    const target=parseFloat(sp.dataset.v); if(isNaN(target)) return;
    const t0=performance.now(), dur=600;
    const tick=t=>{
      const p=Math.min((t-t0)/dur,1), e=1-Math.pow(1-p,3);
      sp.textContent=n(target*e,2);
      if(p<1) requestAnimationFrame(tick); else sp.textContent=n(target,2);
    };
    requestAnimationFrame(tick);
  });
}
function renderOv(){
  const R=RES, s=R.res.summary, g=R.geo, req=R.req, t=R.totals, der=R.params._derived;
  const sc=R.score, cmps=(R.compare||[]);
  const best=cmps.length?cmps.slice().sort((a,b)=>(b.score?b.score.total:-1)-(a.score?a.score.total:-1))[0]:null;
  let html='<div class="panel"><h2>方案总览 · '+h(R.cfg.name||"未命名方案")+'</h2>'+
  '<div class="chips">'+
    '<span class="tag info">'+h(req.orbit_cn)+" · "+h(req.coverage_cn)+" · "+h(req.band)+' 频段</span>'+
    '<span class="tag info">'+h(req.service_cn)+'</span>'+
    '<span class="tag info">'+h(R.mode_info.cn||req.mode_cn)+'</span>'+
    '<span class="tag info">'+h(R.ant_info.cn||"")+(R.sub_info&&R.sub_info.cn?"（"+h(R.sub_info.cn)+"）":"")+'</span>'+
    (R.is_custom_ant?'<span class="tag warn">天线转定制（N_gap+1）</span>':'<span class="tag ok">货架天线</span>')+
    '<span class="tag '+(s.fail.length?"bad":"ok")+'">判据 '+s.judge_pass+"/"+s.judge_total+'</span>'+
  '</div>';

  // 方案评价标准（E1~E10 → 评级/可行性结论），design_all 注入 R.eval
  const ev=R.eval;
  if(ev&&ev.grade){
    const gc={A:"#1a7a2e",B:"#0b5cad",C:"#b8860b",D:"#c0392b"}[ev.grade]||"#444";
    const gbg={A:"#f3fbf5",B:"#f2f7fd",C:"#fdf9ee",D:"#fdf4f3"}[ev.grade]||"#f5f5f5";
    html+='<h3>方案评价标准（E1~E10 十项准则）</h3>'+
      '<div class="panel" style="margin:0;border:2px solid '+gc+';background:'+gbg+';display:flex;gap:18px;align-items:center;flex-wrap:wrap">'+
      '<div style="width:96px;height:96px;border:4px solid '+gc+';border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;flex:none;background:#fff">'+
        '<div style="font-size:40px;font-weight:800;color:'+gc+';line-height:1">'+h(ev.grade)+'</div>'+
        '<div style="font-size:11px;color:'+gc+';font-weight:700;margin-top:2px">'+h({A:"合理可行",B:"基本可行",C:"有条件可行",D:"不可行"}[ev.grade]||"—")+'</div>'+
      '</div>'+
      '<div style="flex:1;min-width:280px">'+
        '<div style="font-size:14px;font-weight:700;color:'+gc+';margin-bottom:6px">'+h(ev.conclusion||"")+'</div>'+
        '<div class="chips" style="margin:0 0 8px">'+
          '<span class="tag '+(ev.feasible?"ok":"bad")+'">硬准则 '+h(ev.pass_hard||"—")+'</span>'+
          '<span class="tag info">软准则 '+h(ev.pass_soft||"—")+'</span>'+
          '<span class="tag info">六维 '+n(ev.score_total,2)+'/10</span>'+
        '</div>'+
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:4px 10px">'+
        (ev.criteria||[]).map(c=>'<div style="font-size:12px;line-height:1.45">'+
          '<span style="color:'+(c.ok?"#1a7a2e":"#c0392b")+';font-weight:700">'+(c.ok?"✓":"✗")+'</span> '+
          '<b style="color:'+((c.kind==="hard")?"#c0392b":"#0b5cad")+'">'+h(c.id)+'</b> '+h(c.name)+
          (c.ok?"":'<div style="color:#8a3b12;margin-left:18px">'+h(c.got)+'（需 '+h(c.need)+'）</div>')+'</div>').join("")+
        '</div>'+
        ((ev.advice&&ev.advice.length)?'<div class="note small" style="margin-top:8px"><b>修正建议：</b>'+ev.advice.slice(0,4).map(h).join("；")+'</div>':"")+
      '</div></div>';
  }

  // 几何与需求
  html+='<h3>轨道几何与需求推导（步骤 1~2）</h3><div class="kpis">'+
    kpi("最差斜距",g.d_slant,"km")+kpi("覆盖地心角",g.psi_cov_deg,"°")+
    kpi("单星视域半径",g.cov_r_cap_km,"km")+kpi("几何建议波束数",g.N_beam_geo,"个")+
    kpi("波束地心张角",g["θ_beam_deg"],"°")+kpi("波束数(配置)",der.N_beam,"个")+
    kpi("EIRP 需求",der.EIRP_req,"dBW")+kpi("G/T 需求",der.GT_req,"dB/K")+
    kpi("上行 ΣL",der["ΣL_up"],"dB")+kpi("下行 ΣL",der["ΣL_dn"],"dB")+
    kpi("设计点 (C/N)",der.CN_des,"dB")+kpi("频率规划",der.freq_ok?"闭合":"超限","")+
  '</div>';
  if(g.warns&&g.warns.length) html+='<div class="warnbox"><b>几何提示：</b><br>'+g.warns.map(h).join("<br>")+'</div>';
  html+='<div class="note small"><b>功放反推（五维①核心）：</b>'+h(der.p_out_source||"")+
    ' → P_out = '+n(der.P_out_w,1)+' W/波束'+(R.transponder.distributed?"（相控阵分布式 T/R，每阵元 "+n(der.P_out_w*der.N_beam/Math.max(toF(CFG.N_el,1024),1),2)+"W）":"")+'</div>';

  // 多覆盖区合成（各区独立几何 → 最差区闭合）
  const MC=R.multi_coverage;
  if(MC && (MC.regions||[]).length){
    html+='<h3>🌏 多覆盖区合成（'+MC.regions.length+' 区 · 按最差区闭合）</h3>'+
      '<table style="width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:6px">'+
      '<tr style="background:#f0f4f8"><th style="padding:5px 8px;border:1px solid #dbe3ec;text-align:left">覆盖区</th>'+
      '<th style="padding:5px 8px;border:1px solid #dbe3ec">最低仰角</th><th style="padding:5px 8px;border:1px solid #dbe3ec">斜距(km)</th>'+
      '<th style="padding:5px 8px;border:1px solid #dbe3ec">雨衰附加(dB)</th><th style="padding:5px 8px;border:1px solid #dbe3ec">链路严重度(dB)</th>'+
      '<th style="padding:5px 8px;border:1px solid #dbe3ec">波束数(密铺)</th></tr>'+
      MC.regions.map(r=>'<tr'+(MC.worst&&r.key===MC.worst.key?' style="background:#fff4e6;font-weight:bold"':'')+'>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec">'+h(r.cn)+(MC.worst&&r.key===MC.worst.key?" ⬅ 最差区（链路按此闭合）":"")+'</td>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec;text-align:center">'+n(r.el_min,0)+'°</td>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec;text-align:center">'+n(r.d_slant,0)+'</td>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec;text-align:center">+'+n(r.A_dyn,1)+'</td>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec;text-align:center">'+n(r.sev_db,2)+'</td>'+
        '<td style="padding:5px 8px;border:1px solid #dbe3ec;text-align:center">'+n(r.N_beam_geo,0)+'</td></tr>').join("")+
      '</table>'+
      '<div class="note small">'+h((MC.composite||{}).note||"")+'；波束总数 = Σ各区密铺 = '+MC.n_beam_total+
      '。严重度 = 雨衰附加 + 20lg(斜距/37500)，Ka 频段雨衰差主导（同仰角差的 FSPL 差仅 0.02dB 量级）。</div>';
  }
  // 星座组网指标（Walker 数值覆盖仿真）
  const CS=R.constellation;
  if(CS){
    html+='<h3>🛰️ 星座组网（Walker '+h(CS.walker)+' · 数值覆盖仿真）</h3><div class="kpis">'+
      kpi("卫星总数",CS.N_sat,"颗")+kpi("轨道面数P",CS.N_plane,"面")+
      kpi("轨道倾角",CS.incl_deg,"°")+kpi("轨道高度",CS.h_km,"km")+
      kpi("最小覆盖重数",CS.mult_min,"重")+kpi("平均覆盖重数",CS.mult_mean,"重")+
      kpi("同轨星间距离",CS.d_intra_km,"km")+kpi("异轨星间距离",CS.d_cross_km,"km")+
      kpi("单跳时延",CS.hop_ms,"ms")+kpi("激光终端数/星",CS.n_lct,"台")+
      (CS.c_sys_total?kpi("系统总容量",CS.c_sys_total,"Gbps"):"")+
      kpi("服务纬度带",("±"+n(CS.lat_cap,0)),"°")+
    '</div>'+
    '<div class="'+(CS.continuous?"okbox":"warnbox")+'">'+h(CS.note||"")+'</div>';
  }

  // 链路 KPI
  html+='<h3>链路校核结果（步骤 5）</h3><div class="kpis">'+
    kpi("星上 EIRP",s.EIRP,"dBW",s.EIRP>=der.EIRP_req-0.05?"okv":"badv")+
    kpi("星上 G/T",s.GT,"dB/K",s.GT>=der.GT_req-0.05?"okv":"badv")+
    kpi("上行余量 M",s.M_up,"dB",s.M_up>=toF(CFG.M_target,3)?"okv":"badv")+
    kpi("下行余量 M",s.M_dn,"dB",s.M_dn>=toF(CFG.M_target,3)?"okv":"badv")+
    kpi("端到端余量",s.M_e2e,"dB")+kpi("下行 MODCOD",s.modcod,"")+
    kpi("单波束容量",s.C_link,"Gbps")+kpi("整星容量 C_sys",s.C_sys,"Gbps")+
  '</div>';

  // 单机/平台/火箭
  const plat=R.platform?R.platform[1]:null, lau=R.launcher?R.launcher[1]:null;
  html+='<h3>货架单机与平台/运载（步骤 4 + 三级闭环）</h3><div class="kpis">'+
    kpi("单机种类",t.n_rows,"种")+kpi("单机总数",t.n_items,"件")+
    kpi("载荷质量(含20%裕度)",t.m_pay,"kg")+kpi("载荷功耗(含20%裕度)",t.p_pay,"W")+
    kpi("货架水平 H",t.H_scheme,"(1~4) 4=货架飞行继承")+kpi("定制缺口 N_gap",t.n_custom,"项")+
    kpi("推荐平台",plat?plat.cn:"—","") + kpi("平台承载",plat?plat.m_pay+"kg/"+plat.p_pay+"W":"—","")+
    kpi("推荐运载",lau?lau.cn:"—","")+kpi("综合评分",sc.total,"/10（六维加权）")+
  '</div>';
  if(!R.platform) html+='<div class="badbox">无可行平台：承载/供电不足 → 回环建议见「约束校验」页</div>';

  // 天线推荐
  const arec=R.ant_rec;
  html+='<h3>天线五维选型推荐</h3>'+
    '<div class="note"><b>'+h(arec[1].id)+" · "+h(arec[1].cn)+'</b>（评分 '+n(arec[0],2)+'/11'+
    (R.is_custom_ant?'，<span class="tag warn">货架不满足 → 转定制</span>':'，<span class="tag ok">货架产品</span>')+'）<br>'+
    arec[2].map(h).join("<br>")+'</div>';

  // 六维评分
  html+='<h3>六维评分（性能 30% / 成本 15% / 灵活 15% / 风险 20% / 质量 10% / 功耗 10%）</h3><div class="panel" style="margin:0;border:none;padding:0">'+
    Object.keys(sc.dims).map(k=>'<div class="scorebar"><div class="lb">'+h(sc.cn[k])+' ('+(sc.weights[k]*100)+'%)</div>'+
      '<div class="bar"><div class="fill cur" style="width:'+(sc.dims[k]*10)+'%"></div></div><div class="val">'+n(sc.dims[k],1)+'</div></div>').join("")+
    '<div class="scorebar"><div class="lb"><b>加权总分</b></div><div class="bar"><div class="fill cur" style="width:'+(sc.total*10)+'%"></div></div><div class="val"><b>'+n(sc.total,2)+'</b></div></div>'+
  '</div>';
  if(best&&R.compare&&R.compare.length>1)
    html+='<div class="'+(best.label==="当前方案"?"okbox":"warnbox")+'">对比结论：最优方案为 <b>'+h(best.label)+"（"+h(best.antenna_cn||best.antenna||"")+"）</b>，总分 "+
      n(best.score?best.score.total:0,2)+"；详见「方案对比」页。</div>";
  html+='</div>';
  // 覆盖区示意图（世界陆地轮廓 + 星下点 + 波束网格），异步加载
  html+='<div class="panel" id="covPanel"><h2>覆盖区示意图（星下点 / 单星视域 / 多波束栅格 · 频率复用色数 k='+n(toF(R.cfg.k_reuse,R.geo.k_typ||4),0)+'）</h2>'+
    '<div id="covBody"><div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> 加载陆地轮廓底图…</div></div></div>';
  // 地面 EIRP 覆盖（coverage_engine：方向图 → 地面投影，SATSOFT 等效内置计算 + CSV 导出）
  html+='<div class="panel" id="eirpPanel"><h2>地面 EIRP 覆盖（方向图地面投影 · 等值线 · SATSOFT 等效内置计算 + CSV 导出）</h2>'+
    '<div id="eirpBody"><div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> EIRP 覆盖计算中（次级方向图 → 地面投影）…</div></div></div>';
  el("ov").innerHTML=html;
  loadCoverageMap();
  loadEirpPanel();
}

/* ---------- ②b 覆盖区示意图：等距圆柱投影世界陆地轮廓 + 星下点 + 波束栅格 ---------- */
let _covSeq=0, _worldLand=null;
async function loadCoverageMap(){
  const seq=++_covSeq;
  try{
    if(!_worldLand){
      const w=await apiCall("worldmap");
      if(w&&w.ok) _worldLand=w.land; else _worldLand={polys:[],q:4,n:0};
    }
    if(seq!==_covSeq) return;
    const box=el("covBody"); if(!box) return;
    box.innerHTML=coverageMapHTML();
    initGlobe3D();
  }catch(e){
    if(seq!==_covSeq) return;
    const box=el("covBody");
    if(box) box.innerHTML='<div class="warnbox">覆盖示意图加载失败：'+h(e)+'</div>';
  }
}
/* ---------- 三维覆盖示意图：Canvas 正交投影地球（拖拽旋转 / 滚轮缩放 / 自动旋转） ---------- */
function coverageMeta(){
  const R=RES, cov=META.coverage[R.cfg.coverage]||{};
  const lon0=toF(cov.lon!==undefined&&cov.lon!==null?cov.lon:(cov.geo_lon||0),0);
  const lat0=toF(cov.lat||0,0);
  const g=R.geo, R_e=6371;
  return {cov:cov,lon0:lon0,lat0:lat0,g:g,R_e:R_e,
    k:Math.max(1,Math.round(toF(R.cfg.k_reuse,g.k_typ||4))),
    psi:toF(g.psi_cov_deg,17.3),
    alt:toF((META.orbits[R.cfg.orbit]||{}).alt_km,35786),
    covDeg:toF(cov.r_km||R.cfg.cov_r_km||g.cov_r_km||1500,1500)/R_e*(180/Math.PI),
    beamDeg:toF(cov.beam_r_km||R.cfg.beam_r_km||g.beam_r_km||250,250)/R_e*(180/Math.PI),
    Nb:toF((R.transponder||{}).N_beam,1)};
}
const GPALETTE=["#0b5cad","#c0392b","#1d8a4e","#b07514","#7048a8","#0a7ea4","#d1568c"];
function coverageMapHTML(){
  const M=coverageMeta(), R=RES;
  let s='<div class="globebar">'+
    '<button class="btn sm" id="gReset">🌍 复位视角（覆盖区中心）</button>'+
    '<button class="btn sm" id="gSpin">▶ 自动旋转</button>'+
    '<label class="glabel">缩放 <input type="range" id="gZoom" min="55" max="230" value="100" style="vertical-align:middle"></label>'+
    '<button class="btn sm" id="g2d">🗺 切换二维平面图</button>'+
    '<span class="glabel" id="gHint">🖱 拖拽旋转 · 滚轮缩放 · 默认视角=覆盖区中心</span>'+
  '</div>'+
  '<div class="mapwrap" id="globeWrap"><canvas id="globeCv"></canvas>'+
  '<div class="globelegend">'+
    '<span><i style="background:#cfe0d2"></i>陆地（海岸线）</span>'+
    '<span><i style="background:#0b5cad"></i>单星视域（虚线大圆）</span>'+
    '<span><i style="background:#c0392b"></i>目标覆盖区</span>'+
    '<span><i style="background:linear-gradient(90deg,'+GPALETTE.slice(0,Math.min(M.k,7)).join(",")+')"></i>波束栅格（k='+M.k+' 色复用）</span>'+
    '<span>🛰 卫星位置为示意（实际 h='+n(M.alt,0)+' km）</span>'+
  '</div>'+
  '<div class="mapnote">三维示意图 · 正交投影 · 仅海岸线无政治边界 · 波束栅格为频率复用示意，非实际赋形</div></div>'+
  '<div id="cov2d" style="display:none">'+coverageMap2DHTML()+'</div>';
  s+='<div class="note small"><b>几何自洽：</b>星下点 '+n(M.lon0,1)+'°'+(M.lon0>=0?"E":"W")+' ｜ 单星视域地心角 ±'+n(M.psi,2)+'°（Ø'+n((M.g.cov_r_cap_km||0)*2,0)+'km）｜ '+
    '目标覆盖 R='+n(toF(M.cov.r_km||R.cfg.cov_r_km,0),0)+'km ｜ 单波束 R='+n(toF(M.cov.beam_r_km||R.cfg.beam_r_km,0),0)+'km（张角 '+n(M.g["θ_beam_deg"],2)+'°）｜ '+
    '几何建议波束数 '+n(M.g.N_beam_geo,0)+' → 采用 '+n(M.Nb,0)+' 个（k='+M.k+' 色复用）。'+
    (M.g.need_constellation?'<span class="tag warn">需多星组网</span>':'<span class="tag ok">单星可覆盖</span>')+'</div>';
  return s;
}
/* 大圆上的点（球面几何，与 report_gen._circle_points 同源） */
function circlePts(lat1,lon1,rDeg,npts){
  const la1=lat1*Math.PI/180, lo1=lon1*Math.PI/180, r=rDeg*Math.PI/180, pts=[];
  for(let i=0;i<=npts;i++){
    const br=2*Math.PI*i/npts;
    const la2=Math.asin(Math.sin(la1)*Math.cos(r)+Math.cos(la1)*Math.sin(r)*Math.cos(br));
    const lo2=lo1+Math.atan2(Math.sin(br)*Math.sin(r)*Math.cos(la1),Math.cos(r)-Math.sin(la1)*Math.sin(la2));
    pts.push([la2*180/Math.PI, lo2*180/Math.PI]);
  }
  return pts;
}
let _globeSt=null;
function initGlobe3D(){
  const cv=el("globeCv"); if(!cv||!_worldLand) return;
  const ctx=(typeof cv.getContext==="function")?cv.getContext("2d"):null;
  if(!ctx){
    // 无 Canvas 环境（老内核/测试桩）→ 直接展示二维平面图
    const w=el("globeWrap"), d=el("cov2d");
    if(w&&d){ w.style.display="none"; d.style.display="block"; }
    const b=el("g2d"); if(b) b.style.display="none";
    return;
  }
  const M=coverageMeta();
  const GW=980, GH=620;
  const dpr=Math.min(window.devicePixelRatio||1,2);
  cv.width=GW*dpr; cv.height=GH*dpr; cv.style.width="100%"; cv.style.maxWidth=GW+"px"; cv.style.height="auto";
  ctx.setTransform(dpr,0,0,dpr,0,0);
  // 视角状态：中心=覆盖区（纬度稍抬便于观察球面），zoom 相对基准
  const st=_globeSt||{cLat:Math.max(Math.min(M.lat0*0.6,60),-60),cLon:M.lon0,zoom:1,spin:false};
  _globeSt=st;
  const cx=GW/2, cy=GH/2+16, Rbase=Math.min(GW,GH)*0.35;
  const D2R=Math.PI/180;
  // roundRect 兼容（老内核降级为直角矩形）
  function rrect(x,y,w,ht,r){
    ctx.beginPath();
    if(ctx.roundRect){ ctx.roundRect(x,y,w,ht,r); return; }
    ctx.rect(x,y,w,ht);
  }
  function P(lat,lon,R){
    const la=lat*D2R, lo=lon*D2R, cl=st.cLat*D2R, cl0=st.cLon*D2R;
    const cosc=Math.sin(cl)*Math.sin(la)+Math.cos(cl)*Math.cos(la)*Math.cos(lo-cl0);
    return [cx+R*Math.cos(la)*Math.sin(lo-cl0),
            cy-R*(Math.cos(cl)*Math.sin(la)-Math.sin(cl)*Math.cos(la)*Math.cos(lo-cl0)),
            cosc>0, cosc];
  }
  function ringPath(pts,R){
    // 可见段拆分为多条子路径
    const segs=[]; let cur=null;
    pts.forEach(p=>{
      const q=P(p[0],p[1],R);
      if(q[2]){ if(!cur){cur=[];segs.push(cur);} cur.push(q); }
      else cur=null;
    });
    return segs;
  }
  function strokeSegs(segs,color,w,dash){
    ctx.save(); ctx.strokeStyle=color; ctx.lineWidth=w; ctx.setLineDash(dash||[]);
    segs.forEach(sg=>{ if(sg.length<2) return; ctx.beginPath(); ctx.moveTo(sg[0][0],sg[0][1]);
      for(let i=1;i<sg.length;i++) ctx.lineTo(sg[i][0],sg[i][1]); ctx.stroke(); });
    ctx.restore();
  }
  function draw(){
    const R=Rbase*st.zoom;
    ctx.clearRect(0,0,GW,GH);
    // 球体（渐变高光）
    const grd=ctx.createRadialGradient(cx-R*0.32,cy-R*0.36,R*0.08,cx,cy,R*1.02);
    grd.addColorStop(0,"#eaf4ff"); grd.addColorStop(0.55,"#bcd8f2"); grd.addColorStop(1,"#6f9fc9");
    ctx.beginPath(); ctx.arc(cx,cy,R,0,2*Math.PI); ctx.fillStyle=grd; ctx.fill();
    ctx.strokeStyle="#4a6fa5"; ctx.lineWidth=1.4; ctx.stroke();
    ctx.save(); ctx.beginPath(); ctx.arc(cx,cy,R,0,2*Math.PI); ctx.clip();
    // 经纬网
    for(let lon=-180;lon<180;lon+=30){
      const pts=[]; for(let la=-90;la<=90;la+=3) pts.push([la,lon]);
      strokeSegs(ringPath(pts,R),"rgba(255,255,255,.55)",.6);
    }
    for(let lat=-60;lat<=60;lat+=30){
      const pts=[]; for(let lo=-180;lo<=180;lo+=3) pts.push([lat,lo]);
      strokeSegs(ringPath(pts,R),"rgba(255,255,255,.55)",.6);
    }
    // 海岸线（仅海岸线，无政治边界 —— 地图合规）
    const q=toF(_worldLand.q,4), polys=_worldLand.polys||[];
    ctx.lineWidth=.7;
    polys.forEach(poly=>{
      const pts=[];
      for(let i=0;i+1<poly.length;i+=2) pts.push([poly[i+1]/q, poly[i]/q]);
      const segs=ringPath(pts,R);
      segs.forEach(sg=>{ if(sg.length<3) return;
        ctx.beginPath(); ctx.moveTo(sg[0][0],sg[0][1]);
        for(let i=1;i<sg.length;i++) ctx.lineTo(sg[i][0],sg[i][1]);
        ctx.closePath(); ctx.fillStyle="rgba(207,224,210,.92)"; ctx.fill();
        ctx.strokeStyle="#7fa887"; ctx.stroke(); });
    });
    // 覆盖中心 / 星下点
    const cLatC=M.lat0, cLonC=M.lon0;           // 覆盖区中心
    const sLat=0, sLon=M.lon0;                  // GEO 定点星下点（赤道）
    // 单星视域大圆（蓝虚线）
    strokeSegs(ringPath(circlePts(sLat,sLon,M.psi,120),R),"#0b5cad",1.6,[6,4]);
    // 覆盖区圈（红实线 + 渐变填充）
    const covSegs=ringPath(circlePts(cLatC,cLonC,M.covDeg,120),R);
    const cc=P(cLatC,cLonC,R);
    if(cc[2]){
      const rg=ctx.createRadialGradient(cc[0],cc[1],1,cc[0],cc[1],Math.max(R*Math.sin(M.covDeg*D2R),6));
      rg.addColorStop(0,"rgba(192,57,43,.34)"); rg.addColorStop(.8,"rgba(192,57,43,.16)"); rg.addColorStop(1,"rgba(192,57,43,0)");
      ctx.beginPath(); ctx.arc(cc[0],cc[1],R*Math.sin(M.covDeg*D2R),0,2*Math.PI);
      ctx.fillStyle=rg; ctx.fill();
    }
    strokeSegs(covSegs,"#c0392b",2.0);
    // 波束栅格（中心 + 一环 6 示意）
    if(M.Nb>1&&M.beamDeg>0.05){
      const centers=[[cLatC,cLonC]].concat(circlePts(cLatC,cLonC,M.beamDeg*1.78,6).slice(0,6));
      centers.forEach((c,i)=>{
        const col=GPALETTE[i%M.k];
        const segs2=ringPath(circlePts(c[0],c[1],M.beamDeg,36),R);
        segs2.forEach(sg=>{ if(sg.length<3) return;
          ctx.beginPath(); ctx.moveTo(sg[0][0],sg[0][1]);
          for(let j=1;j<sg.length;j++) ctx.lineTo(sg[j][0],sg[j][1]);
          ctx.closePath(); ctx.fillStyle=col; ctx.globalAlpha=.3; ctx.fill();
          ctx.globalAlpha=.9; ctx.strokeStyle=col; ctx.lineWidth=.9; ctx.stroke(); ctx.globalAlpha=1; });
      });
      const lab=P(cLatC,cLonC,R);
      if(lab[2]){ ctx.font="700 10.5px 'Microsoft YaHei'"; ctx.fillStyle="#083a6b"; ctx.textAlign="center";
        ctx.fillText(M.Nb+" 波束（示意7，k="+M.k+"）",lab[0],lab[1]+4); }
    }
    // 星下点十字
    const sp=P(sLat,sLon,R);
    if(sp[2]){
      ctx.strokeStyle="#c0392b"; ctx.lineWidth=1.8;
      ctx.beginPath(); ctx.moveTo(sp[0]-8,sp[1]); ctx.lineTo(sp[0]+8,sp[1]);
      ctx.moveTo(sp[0],sp[1]-8); ctx.lineTo(sp[0],sp[1]+8); ctx.stroke();
      ctx.beginPath(); ctx.arc(sp[0],sp[1],3.2,0,2*Math.PI); ctx.fillStyle="#c0392b"; ctx.fill();
    }
    ctx.restore(); // 解除球体 clip
    // 卫星（沿星下点视线方向抬升，位置示意）+ 波束锥
    if(sp[2]){
      const ang=Math.atan2(sp[1]-cy,sp[0]-cx);
      const dx=Math.cos(ang), dy=Math.sin(ang);
      // 拉远卫星便于观察：目标 1.85R，但夹取在画布内（留 46px 边距）
      const marg=46; let tmax=1e9;
      if(dx>1e-6) tmax=Math.min(tmax,(GW-marg-cx)/dx);
      if(dx<-1e-6) tmax=Math.min(tmax,(marg-cx)/dx);
      if(dy>1e-6) tmax=Math.min(tmax,(GH-marg-cy)/dy);
      if(dy<-1e-6) tmax=Math.min(tmax,(marg-cy)/dy);
      const rs=Math.max(R*1.3, Math.min(R*1.85, tmax));
      const bx=cx+rs*dx, by=cy+rs*dy;
      // 星地连线（星下点方向）
      ctx.save(); ctx.strokeStyle="#0b5cad"; ctx.lineWidth=.9; ctx.setLineDash([2,3]); ctx.globalAlpha=.55;
      ctx.beginPath(); ctx.moveTo(bx,by); ctx.lineTo(sp[0],sp[1]); ctx.stroke(); ctx.restore();
      // 波束锥（卫星 → 覆盖圈 4 边缘点）
      ctx.save(); ctx.strokeStyle="#b07514"; ctx.lineWidth=1; ctx.setLineDash([3,3]); ctx.globalAlpha=.85;
      circlePts(cLatC,cLonC,M.covDeg,4).slice(0,4).forEach(ep=>{
        const q2=P(ep[0],ep[1],R);
        if(q2[2]){ ctx.beginPath(); ctx.moveTo(bx,by); ctx.lineTo(q2[0],q2[1]); ctx.stroke(); }
      });
      ctx.restore();
      ctx.save(); ctx.translate(bx,by); ctx.rotate(ang+Math.PI/2);
      ctx.fillStyle="#0b5cad"; ctx.strokeStyle="#083a6b"; ctx.lineWidth=1;
      rrect(-13,-6,26,12,3); ctx.fill(); ctx.stroke();
      ctx.fillStyle="#0a7ea4";
      rrect(-34,-4,18,8,1.5); ctx.fill(); ctx.stroke();
      rrect(16,-4,18,8,1.5); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.arc(0,8,2.6,0,2*Math.PI); ctx.fillStyle="#b0662c"; ctx.fill();
      ctx.restore();
      ctx.font="700 11px 'Microsoft YaHei'"; ctx.fillStyle="#1c2733"; ctx.textAlign="center";
      ctx.fillText("🛰 "+(R0cfg().orbit||"GEO")+" · h="+n(M.alt,0)+"km",bx,by-22);
    }
    // 视角信息
    ctx.font="10.5px 'Microsoft YaHei'"; ctx.fillStyle="#5f7183"; ctx.textAlign="left";
    ctx.fillText("视角中心 "+n(st.cLat,1)+"°N "+n(((st.cLon+540)%360)-180,1)+"°E ｜ 缩放 "+n(st.zoom*100,0)+"%",10,GH-10);
  }
  function R0cfg(){ return RES.cfg; }
  // 交互：拖拽旋转
  let drag=null;
  cv.addEventListener("pointerdown",ev=>{ drag={x:ev.clientX,y:ev.clientY}; cv.classList.add("drag"); cv.setPointerCapture(ev.pointerId); });
  cv.addEventListener("pointermove",ev=>{
    if(!drag) return;
    const R=Rbase*st.zoom;
    st.cLon-= (ev.clientX-drag.x)/R*57.3*1.05;
    st.cLat=Math.max(-89,Math.min(89,st.cLat+(ev.clientY-drag.y)/R*57.3*1.05));
    drag={x:ev.clientX,y:ev.clientY}; draw();
  });
  cv.addEventListener("pointerup",()=>{ drag=null; cv.classList.remove("drag"); });
  cv.addEventListener("pointercancel",()=>{ drag=null; cv.classList.remove("drag"); });
  cv.addEventListener("wheel",ev=>{
    ev.preventDefault();
    st.zoom=Math.max(.55,Math.min(2.3,st.zoom*(ev.deltaY>0?0.92:1.08)));
    const z=el("gZoom"); if(z) z.value=Math.round(st.zoom*100);
    draw();
  },{passive:false});
  // 工具条
  el("gReset").addEventListener("click",()=>{ st.cLat=Math.max(Math.min(M.lat0*0.6,60),-60); st.cLon=M.lon0; st.zoom=1;
    const z=el("gZoom"); if(z) z.value=100; draw(); });
  el("gSpin").addEventListener("click",function(){ st.spin=!st.spin; this.textContent=st.spin?"⏸ 停止旋转":"▶ 自动旋转";
    this.classList.toggle("solid",st.spin); if(st.spin) spinLoop(); });
  el("gZoom").addEventListener("input",function(){ st.zoom=toF(this.value,100)/100; draw(); });
  el("g2d").addEventListener("click",function(){
    const w=el("globeWrap"), d=el("cov2d");
    const flat=d.style.display!=="none";
    d.style.display=flat?"none":"block"; w.style.display=flat?"block":"none";
    this.textContent=flat?"🗺 切换二维平面图":"🌍 切换三维地球";
  });
  let spinRaf=0;
  function spinLoop(){
    if(!st.spin||!document.getElementById("globeCv")){ return; }
    st.cLon+=0.22; draw();
    spinRaf=requestAnimationFrame(spinLoop);
  }
  draw();
}
/* 等距圆柱投影二维平面图（对照视图）：lon/lat → x/y；中心以覆盖区中心经度为准，避免跨 180° 断裂 */
function coverageMap2DHTML(){
  const R=RES, g=R.geo, cov=META.coverage[R.cfg.coverage]||{};
  const lon0=toF(cov.lon!==undefined&&cov.lon!==null?cov.lon:(cov.geo_lon||0),0);
  const lat0=toF(cov.lat||0,0);
  const W=1000,H=500,PL=10,PT=10;
  const mapW=W-2*PL, mapH=H-2*PT;
  // 投影中心 = 覆盖区中心经度；经度归一到 [lon0-180, lon0+180]
  const X=lon=>{ let d=((lon-lon0+540)%360)-180; return PL+(d+180)/360*mapW; };
  const Y=lat=>PT+(90-Math.min(Math.max(lat,-85.5),85.5))/180*mapH;
  // 复用色（k 色频率复用）
  const k=Math.max(1,Math.round(toF(R.cfg.k_reuse,g.k_typ||4)));
  const PALETTE=["#0b5cad","#c0392b","#1d8a4e","#b07514","#7048a8","#0a7ea4","#d1568c"];
  let s='<div class="mapwrap"><svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto;display:block;margin:0 auto">';
  s+='<defs><radialGradient id="covg" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#0b5cad" stop-opacity=".34"/><stop offset="0.72" stop-color="#0b5cad" stop-opacity=".16"/><stop offset="1" stop-color="#0b5cad" stop-opacity="0"/></radialGradient></defs>';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+mapW+'" height="'+mapH+'" fill="#eef5fb" stroke="#d3e0ee"/>';
  // 经纬网格
  for(let lon=-180;lon<=180;lon+=30){ s+='<line x1="'+X(lon)+'" y1="'+PT+'" x2="'+X(lon)+'" y2="'+(PT+mapH)+'" stroke="#dfe9f3" stroke-width=".6"/>'; }
  for(let lat=-60;lat<=60;lat+=30){ s+='<line x1="'+PL+'" y1="'+Y(lat)+'" x2="'+(PL+mapW)+'" y2="'+Y(lat)+'" stroke="#dfe9f3" stroke-width=".6"/>'; }
  s+='<line x1="'+PL+'" y1="'+Y(0)+'" x2="'+(PL+mapW)+'" y2="'+Y(0)+'" stroke="#c3d4e6" stroke-width="1"/>';
  // 陆地轮廓（仅海岸线，无政治边界 —— 地图合规）
  const q=(_worldLand&&_worldLand.q)||4, polys=(_worldLand&&_worldLand.polys)||[];
  let landPaths=0;
  polys.forEach(poly=>{
    let d="",first=true;
    for(let i=0;i+1<poly.length;i+=2){
      const lon=poly[i]/q, lat=poly[i+1]/q;
      const px=X(lon),py=Y(lat);
      if(first){ d+="M"+px.toFixed(1)+","+py.toFixed(1); first=false; }
      else d+="L"+px.toFixed(1)+","+py.toFixed(1);
    }
    if(d){ s+='<path d="'+d+'Z" fill="#cfe0d2" stroke="#9db9a3" stroke-width=".5" stroke-linejoin="round"/>'; landPaths++; }
  });
  // 星下点（GEO 定点 = 覆盖区中心经度，纬度 0）
  const sx=X(lon0), sy=Y(0);
  const alt=toF((META.orbits[R.cfg.orbit]||{}).alt_km,35786), R_e=6371;
  // 单星视域地心半角 → 投影纬度跨度（等距圆柱近似：Δlat_deg = psi_cov）
  const psi=g.psi_cov_deg||17.3;
  const covRlat=psi; // 视域半径对应的纬度跨度（度）
  // 视域圈（椭圆近似，覆盖地心角 psi）
  const rxKm=g.cov_r_cap_km||0;
  // 覆盖区半径 r_km → 纬度跨度
  const covLatSpan=(toF(cov.r_km||R.cfg.cov_r_km||g.cov_r_km||1500,1500)/R_e)*(180/Math.PI);
  const beamLatSpan=(toF(cov.beam_r_km||R.cfg.beam_r_km||g.beam_r_km||250,250)/R_e)*(180/Math.PI);
  // 单星视域大圈
  s+='<ellipse cx="'+sx+'" cy="'+sy+'" rx="'+(X(lon0+psi)-sx)+'" ry="'+(sy-Y(psi))+'" fill="none" stroke="#0b5cad" stroke-width="1.6" stroke-dasharray="6 4" opacity=".7"/>';
  s+='<text x="'+sx+'" y="'+(sy-(sy-Y(psi))-6)+'" text-anchor="middle" font-size="10.5" fill="#0b5cad">单星视域 Ø'+n(rxKm*2,0)+'km</text>';
  // 覆盖区圈（目标覆盖）
  s+='<circle cx="'+sx+'" cy="'+sy+'" r="'+Math.max(sy-Y(covLatSpan),3)+'" fill="url(#covg)" stroke="#0a7ea4" stroke-width="1.8" class="covbeam"/>';
  s+='<text x="'+sx+'" y="'+(sy+Math.max(sy-Y(covLatSpan),3)+14)+'" text-anchor="middle" font-size="10.5" fill="#0a7ea4">覆盖区 '+h(cov.cn||R.cfg.coverage)+' R='+n(toF(cov.r_km||R.cfg.cov_r_km,0),0)+'km</text>';
  // 多波束栅格：在覆盖圆内铺 hex 波束（半径 = beamLatSpan）
  const br=Math.max(sy-Y(beamLatSpan),4);
  if(R.transponder&&R.transponder.N_beam>1&&br>3){
    const Nbeam=R.transponder.N_beam;
    // 用同心环近似铺 N_beam 个波束（hex 排布），最多画 61 个（示意）
    const shown=Math.min(Nbeam,61);
    let cnt=0, ring=0;
    const hexR=br*0.92;
    const drawBeam=(cx,cy,idx)=>{
      const col=PALETTE[idx%k];
      // 六边形波束
      let pts="";
      for(let a=0;a<6;a++){ const ang=Math.PI/6+a*Math.PI/3; pts+=(cx+hexR*Math.cos(ang)).toFixed(1)+","+(cy+hexR*Math.sin(ang)*0.9).toFixed(1)+" "; }
      s+='<polygon points="'+pts+'" fill="'+col+'" fill-opacity=".30" stroke="'+col+'" stroke-width=".9" stroke-opacity=".8"><title>波束 '+(idx+1)+' · 色 '+(idx%k+1)+'</title></polygon>';
    };
    drawBeam(sx,sy,cnt++);
    for(let r=1;r<=3&&cnt<shown;r++){
      const ringN=r*6;
      for(let j=0;j<ringN&&cnt<shown;j++){
        const ang=j/ringN*2*Math.PI;
        const rr=r*hexR*1.72;
        const cx=sx+rr*Math.cos(ang), cy=sy+rr*Math.sin(ang)*0.9;
        if(Math.hypot(cx-sx,(cy-sy)/0.9)>Math.max(sy-Y(covLatSpan),br)) continue;
        drawBeam(cx,cy,cnt++);
      }
      ring=r;
    }
    s+='<text x="'+sx+'" y="'+(sy+4)+'" text-anchor="middle" font-size="9" fill="#083a6b" font-weight="700">'+Nbeam+' 波束（示意'+cnt+'）</text>';
  }else{
    // 单波束
    s+='<circle cx="'+sx+'" cy="'+sy+'" r="'+br+'" fill="#0b5cad" fill-opacity=".28" stroke="#0b5cad" stroke-width="1.4"/>';
  }
  // 星下点十字 + 卫星图标
  s+='<g><line x1="'+(sx-7)+'" y1="'+sy+'" x2="'+(sx+7)+'" y2="'+sy+'" stroke="#c0392b" stroke-width="1.6"/>'+
     '<line x1="'+sx+'" y1="'+(sy-7)+'" x2="'+sx+'" y2="'+(sy+7)+'" stroke="#c0392b" stroke-width="1.6"/>'+
     '<circle cx="'+sx+'" cy="'+sy+'" r="3" fill="#c0392b"><animate attributeName="r" values="3;6;3" dur="2s" repeatCount="indefinite"/><animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/></circle></g>';
  s+='<text x="'+(sx+10)+'" y="'+(sy-8)+'" font-size="10.5" fill="#c0392b" font-weight="700">星下点 '+n(lon0,1)+'°'+(lon0>=0?"E":"W")+'</text>';
  // 图例
  let ly=PT+14;
  s+='<rect x="'+(PL+mapW-150)+'" y="'+(PT+6)+'" width="144" height="'+(56+(k>4?14:0))+'" rx="8" fill="#fff" fill-opacity=".88" stroke="#dde5ee"/>';
  s+='<text x="'+(PL+mapW-142)+'" y="'+(ly+8)+'" font-size="10.5" font-weight="700" fill="#1c2733">图例</text>';
  s+='<line x1="'+(PL+mapW-142)+'" y1="'+(ly+22)+'" x2="'+(PL+mapW-120)+'" y2="'+(ly+22)+'" stroke="#0b5cad" stroke-width="1.6" stroke-dasharray="5 3"/><text x="'+(PL+mapW-116)+'" y="'+(ly+25)+'" font-size="9.5" fill="#5f7183">单星视域</text>';
  s+='<circle cx="'+(PL+mapW-131)+'" cy="'+(ly+38)+'" r="6" fill="url(#covg)" stroke="#0a7ea4"/><text x="'+(PL+mapW-116)+'" y="'+(ly+41)+'" font-size="9.5" fill="#5f7183">目标覆盖区</text>';
  let lgx=PL+mapW-142;
  for(let c=0;c<Math.min(k,7);c++){ s+='<rect x="'+(lgx+c*18)+'" y="'+(ly+50)+'" width="14" height="10" rx="2" fill="'+PALETTE[c]+'" fill-opacity=".5" stroke="'+PALETTE[c]+'"/>'; }
  s+='<text x="'+(lgx+Math.min(k,7)*18+4)+'" y="'+(ly+59)+'" font-size="9.5" fill="#5f7183">复用色(k='+k+')</text>';
  s+='</svg><div class="mapnote">示意图 · 等距圆柱投影 · 仅海岸线无政治边界 · 波束栅格为频率复用示意，非实际赋形</div></div>';
  const geo=g;
  s+='<div class="note small"><b>几何自洽：</b>星下点 '+n(lon0,1)+'°'+(lon0>=0?"E":"W")+' ｜ 单星视域地心角 ±'+n(psi,2)+'°（Ø'+n((geo.cov_r_cap_km||0)*2,0)+'km）｜ '+
    '目标覆盖 R='+n(toF(cov.r_km||R.cfg.cov_r_km,0),0)+'km ｜ 单波束 R='+n(toF(cov.beam_r_km||R.cfg.beam_r_km,0),0)+'km（张角 '+n(geo["θ_beam_deg"],2)+'°）｜ '+
    '几何建议波束数 '+n(geo.N_beam_geo,0)+' → 采用 '+n(R.transponder.N_beam,0)+' 个（k='+k+' 色复用）。'+
    (geo.need_constellation?'<span class="tag warn">需多星组网</span>':'<span class="tag ok">单星可覆盖</span>')+'</div>';
  return s;
}
function toF(v,d){ v=parseFloat(v); return isNaN(v)?(d===undefined?0:d):v; }

/* ---------- ②c 地面 EIRP 覆盖（coverage_engine：次级方向图 → 地面投影，SATSOFT 等效） ---------- */
let _eirpSeq=0;
const _eirpState={csv:null};
function satAnchor(){
  /* 星下点：GEO=覆盖区推荐星位；LEO 等非 GEO=覆盖区中心经度上方（瞬时星下点示意） */
  const cov=META.coverage[RES.cfg.coverage]||{};
  const isGeo=RES.cfg.orbit==="GEO";
  const lon=toF(cov.geo_lon!==undefined&&cov.geo_lon!==null?cov.geo_lon:(cov.lon||0),0);
  const lat=isGeo?0:toF(cov.lat||0,0);
  return {lat:lat,lon:lon,isGeo:isGeo};
}
function eirpPayload(withCsv){
  const ant=RES.res.antenna, lk=RES.res.downlink||{};
  const f=lk.f_ghz||((META.band_freq[RES.cfg.band]||[20])[1]);
  const isArr=String(ant.ant_type||"").indexOf("相控阵")>=0;
  const cov=META.coverage[RES.cfg.coverage]||{};
  const sa=satAnchor();
  const h=(META.orbits[RES.cfg.orbit]||{}).alt_km||35786;
  const eirpPk=toF((RES.res.eirp||{}).EIRP,ant.G_ant+10);
  const p={antenna_type:isArr?"phased_array":"reflector",freq_ghz:f,
    peak_gain_dbi:ant.G_ant||null,
    peak_eirp_dbw:eirpPk,h_km:h,
    sat_lat:sa.lat,sat_lon:sa.lon,
    target_lat:toF(cov.lat,sa.lat),target_lon:toF(cov.lon!==undefined&&cov.lon!==null?cov.lon:(cov.geo_lon||0),sa.lon),
    point_at_target:true,
    el_min_deg:toF(cov.el_min!==undefined?cov.el_min:10,10),
    n_lat:97,n_lon:121,
    tag:_safeTag("EIRP覆盖_"+RES.cfg.band)};
  if(isArr){ p.n_el=Math.max(4,Math.round(toF(RES.params.N_el,toF(CFG.N_el,1024)))); p.d_lam=_patState.dlam; }
  else p.D=ant.D_m||beamAperture();
  if(withCsv) p.export_csv=true;
  return p;
}
async function loadEirpPanel(withCsv){
  const seq=++_eirpSeq;
  const box=el("eirpBody"); if(!box) return;
  if(!RES||!RES.res){ box.innerHTML='<div class="muted">请先完成一次设计。</div>'; return; }
  box.innerHTML='<div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> EIRP 覆盖计算中（次级方向图 → 地面投影）…</div>';
  try{
    const r=await apiCall("coverage",eirpPayload(!!withCsv));
    if(seq!==_eirpSeq) return;
    const b2=el("eirpBody"); if(!b2) return;
    if(!r.ok){ b2.innerHTML='<div class="warnbox">EIRP 覆盖计算失败：'+h(r.error||"未知错误")+'</div>'; return; }
    if(r.csv_files) _eirpState.csv=r.csv_files;
    b2.innerHTML=eirpPanelHTML(r);
    bindEirpPanel();
  }catch(e){
    if(seq!==_eirpSeq) return;
    const b2=el("eirpBody");
    if(b2) b2.innerHTML='<div class="warnbox">EIRP 覆盖通道不可用：'+h(e)+'</div>';
  }
}
function bindEirpPanel(){
  const ex=el("eirpExportCsv");
  if(ex) ex.addEventListener("click",()=>loadEirpPanel(true));
  const op=el("eirpOpenCsv"), rv=el("eirpRevealCsv");
  if(op&&_eirpState.csv&&_eirpState.csv[0]) op.addEventListener("click",()=>apiCall("open_file",{path:_eirpState.csv[0].path}));
  if(rv&&_eirpState.csv&&_eirpState.csv[0]) rv.addEventListener("click",()=>apiCall("reveal_file",{path:_eirpState.csv[0].path}));
}
/* EIRP 覆盖图：等距圆柱局部投影（窗=覆盖网格范围），海岸线底图 + EIRP 色块 + 等值线 */
function eirpMapSvg(C){
  const lats=C.lat, lons=C.lon, grid=C.eirp_dbw;
  if(!lats||!lons||!grid||!grid.length) return "";
  const la0=lats[0],la1=lats[lats.length-1],lo0=lons[0],lo1=lons[lons.length-1];
  const W=760,PL=42,PT=14,PB=38,PR=64;
  const ar=Math.max(0.35,Math.min(2.6,(la1-la0)/Math.max((lo1-lo0)*Math.cos((la0+la1)/2*Math.PI/180),1e-6)));
  const MW=W-PL-PR, MH=Math.max(240,Math.min(460,MW*ar));
  const H=MH+PT+PB;
  const X=lo=>PL+(lo-lo0)/Math.max(lo1-lo0,1e-9)*MW;
  const Y=la=>PT+(la1-la)/Math.max(la1-la0,1e-9)*MH;
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+MW+'" height="'+MH+'" fill="#eef5fb" stroke="#d3e0ee"/>';
  // 海岸线（裁剪到窗内；_worldLand 由覆盖示意图通道预取）
  const q=(_worldLand&&_worldLand.q)||4, polys=(_worldLand&&_worldLand.polys)||[];
  polys.forEach(poly=>{
    let d="",first=true,any=false;
    for(let i=0;i+1<poly.length;i+=2){
      const lon=poly[i]/q, lat=poly[i+1]/q;
      if(lon<lo0-2||lon>lo1+2||lat<la0-2||lat>la1+2){ first=true; continue; }
      any=true;
      const px=X(lon),py=Y(lat);
      if(first){ d+="M"+px.toFixed(1)+","+py.toFixed(1); first=false; }
      else d+="L"+px.toFixed(1)+","+py.toFixed(1);
    }
    if(any&&d) s+='<path d="'+d+'" fill="none" stroke="#8fae94" stroke-width=".8" stroke-linejoin="round" opacity=".9"/>';
  });
  // EIRP 色块：Canvas 光栅化（97×121 格元若逐个 <rect> 内联会产生 ~1MB SVG，渲染卡顿）
  function ec(v){
    const pk=C.peak_eirp_dbw;
    const t=Math.min(Math.max((v-(pk-30))/30,0),1);   // pk−30 .. pk
    const st=[[0,[238,245,251]],[0.35,[147,196,232]],[0.6,[64,140,198]],[0.8,[23,96,160]],[1,[10,50,110]]];
    for(let i=0;i<st.length-1;i++){
      const a=st[i],b=st[i+1];
      if(t>=a[0]&&t<=b[0]){ const k=b[0]>a[0]?(t-a[0])/(b[0]-a[0]):0;
        return [Math.round(a[1][0]+k*(b[1][0]-a[1][0])),Math.round(a[1][1]+k*(b[1][1]-a[1][1])),Math.round(a[1][2]+k*(b[1][2]-a[1][2]))]; }
    }
    return st[st.length-1][1];
  }
  const dLat=lats.length>1?(lats[1]-lats[0]):1, dLon=lons.length>1?(lons[1]-lons[0]):1;
  const cvE=document.createElement("canvas"); cvE.width=lons.length; cvE.height=lats.length;
  const cxE=(typeof cvE.getContext==="function")?cvE.getContext("2d"):null;
  if(cxE){
    // 像素行 iy=0 = 最高纬度（canvas y 向下，grid 行序=lats 升序 → gi=n-1-iy）
    for(let iy=0;iy<lats.length;iy++){
      const gi=lats.length-1-iy;
      for(let jx=0;jx<lons.length;jx++){
        const v=grid[gi][jx];
        if(v===null||v===undefined) continue;
        const c=ec(v);
        cxE.fillStyle="rgba("+c[0]+","+c[1]+","+c[2]+",0.55)";
        cxE.fillRect(jx,iy,1,1);
      }
    }
    const urlE=cvE.toDataURL("image/png");
    const ix0=X(lons[0]-dLon/2), iy0=Y(lats[lats.length-1]+dLat/2);
    const iw=Math.max(X(lons[lons.length-1]+dLon/2)-ix0,1), ih=Math.max(Y(lats[0]-dLat/2)-iy0,1);
    s+='<image href="'+urlE+'" x="'+ix0.toFixed(1)+'" y="'+iy0.toFixed(1)+'" width="'+iw.toFixed(1)+'" height="'+ih.toFixed(1)+'" style="image-rendering:pixelated"/>';
  }else{
    // 无 Canvas（老内核/测试桩）→ 抽稀矩形矢量兜底（≤40×40 单元）
    const sI=Math.max(1,Math.ceil(lats.length/40)), sJ=Math.max(1,Math.ceil(lons.length/40));
    for(let i=0;i<lats.length;i+=sI) for(let j=0;j<lons.length;j+=sJ){
      const v=grid[i][j];
      if(v===null||v===undefined) continue;
      const c=ec(v);
      const px=X(lons[j]-dLon*sJ/2), py=Y(lats[i]+dLat*sI/2);
      s+='<rect x="'+px.toFixed(1)+'" y="'+py.toFixed(1)+'" width="'+Math.ceil((X(lons[j]+dLon*sJ/2)-px)+0.6)+'" height="'+Math.ceil((py-Y(lats[i]-dLat*sI/2))+0.6)+'" fill="rgb('+c[0]+','+c[1]+','+c[2]+')" opacity=".55"/>';
    }
  }
  // 等值线（−3dB 红 / −10dB 橙）
  const cols={"0":"#d6452d","1":"#e08214"};
  (C.levels||[]).forEach((lv,k)=>{
    const segs=(C.contours||{})[String(lv)]||[];
    const col=k===0?"#d6452d":"#e08214";
    segs.forEach(sg=>{
      if(!sg||sg.length<2) return;
      s+='<line x1="'+X(sg[0][1]).toFixed(1)+'" y1="'+Y(sg[0][0]).toFixed(1)+'" x2="'+X(sg[1][1]).toFixed(1)+'" y2="'+Y(sg[1][0]).toFixed(1)+'" stroke="'+col+'" stroke-width="'+(k===0?1.8:1.3)+'" opacity=".95"/>';
    });
  });
  // 波束中心 + 星下点 + 峰值点
  const bc=C.beam_center||{}, pg=C.peak_ground||{}, sat=C.sat||{};
  if(bc.lat!==undefined){
    s+='<g><circle cx="'+X(bc.lon)+'" cy="'+Y(bc.lat)+'" r="4.5" fill="none" stroke="#d6452d" stroke-width="1.6"/>'+
       '<circle cx="'+X(bc.lon)+'" cy="'+Y(bc.lat)+'" r="1.6" fill="#d6452d"/></g>'+
       '<text x="'+(X(bc.lon)+8)+'" y="'+(Y(bc.lat)-6)+'" font-size="10" fill="#d6452d" font-weight="700">波束中心 ('+n(bc.lat,2)+'°, '+n(bc.lon,2)+'°)</text>';
  }
  if(sat.lat!==undefined&&sat.lon>=lo0&&sat.lon<=lo1&&sat.lat>=la0&&sat.lat<=la1){
    s+='<g><line x1="'+(X(sat.lon)-6)+'" y1="'+Y(sat.lat)+'" x2="'+(X(sat.lon)+6)+'" y2="'+Y(sat.lat)+'" stroke="#c0392b" stroke-width="1.5"/>'+
       '<line x1="'+X(sat.lon)+'" y1="'+(Y(sat.lat)-6)+'" x2="'+X(sat.lon)+'" y2="'+(Y(sat.lat)+6)+'" stroke="#c0392b" stroke-width="1.5"/></g>'+
       '<text x="'+(X(sat.lon)+8)+'" y="'+(Y(sat.lat)+14)+'" font-size="9.5" fill="#c0392b">星下点</text>';
  }
  // 刻度
  const loStep=Math.max(1,Math.round((lo1-lo0)/8)), laStep=Math.max(1,Math.round((la1-la0)/6));
  for(let lo=Math.ceil(lo0/loStep)*loStep;lo<=lo1;lo+=loStep)
    s+='<text x="'+X(lo)+'" y="'+(H-PB+15)+'" text-anchor="middle" font-size="9.5" fill="#5f7183">'+lo+'°</text>';
  for(let la=Math.ceil(la0/laStep)*laStep;la<=la1;la+=laStep)
    s+='<text x="'+(PL-5)+'" y="'+(Y(la)+3)+'" text-anchor="end" font-size="9.5" fill="#5f7183">'+la+'°</text>';
  s+='<text x="'+(PL+MW/2)+'" y="'+(H-5)+'" text-anchor="middle" font-size="10.5" fill="#5f7183">经度 (°)</text>';
  // 色标（pk−30..pk）
  const lx=W-46, pk=C.peak_eirp_dbw;
  s+='<defs><linearGradient id="eirpg" x1="0" y1="1" x2="0" y2="0">'+
     '<stop offset="0" stop-color="rgb(238,245,251)"/><stop offset=".35" stop-color="rgb(147,196,232)"/>'+
     '<stop offset=".6" stop-color="rgb(64,140,198)"/><stop offset=".8" stop-color="rgb(23,96,160)"/>'+
     '<stop offset="1" stop-color="rgb(10,50,110)"/></linearGradient></defs>';
  s+='<rect x="'+lx+'" y="'+PT+'" width="14" height="'+MH+'" fill="url(#eirpg)" stroke="#93a3b4"/>';
  [0,-10,-20,-30].forEach(gv=>{
    const gy=PT+(-gv)/30*MH;
    s+='<text x="'+(lx+18)+'" y="'+(gy+3)+'" font-size="9.5" fill="#5f7183">'+n(pk+gv,0)+'</text>';
  });
  s+='<text x="'+(lx+7)+'" y="'+(PT-3)+'" text-anchor="middle" font-size="9" fill="#5f7183">dBW</text>';
  s+='</svg>';
  return s;
}
function eirpPanelHTML(C){
  const lv=C.levels||[], met=C.metrics||{};
  const m3=met[String(lv[0])]||met[lv[0]]||{}, m10=met[String(lv[1])]||met[lv[1]]||{};
  const sa=satAnchor();
  let kpis='<div class="kpis">'+
    kpi("波束峰值 EIRP",C.peak_eirp_dbw,"dBW")+
    kpi("−3dB 足迹直径",(m3.diameter_km),"km")+
    kpi("−10dB 足迹直径",(m10.diameter_km),"km")+
    kpi("−3dB 覆盖面积",(m3.area_km2),"km²")+
    kpi("波束中心","("+n((C.beam_center||{}).lat,2)+", "+n((C.beam_center||{}).lon,2)+")","°N,°E")+
    kpi("扫描角","("+n((C.scan||{}).theta_deg,2)+", "+n((C.scan||{}).phi_deg,1)+")","° (θ₀,φ₀)")+
  '</div>';
  const csvBox=_eirpState.csv?('<div class="okbox small">✅ 覆盖数据已导出：<code>'+h(_eirpState.csv[0].path)+'</code> ＋ <code>'+h(_eirpState.csv[1].path)+
    '</code>（格点表+等值线表，SATSOFT/Excel 可直接核对）。 <button class="btn sm" id="eirpOpenCsv">打开文件</button> <button class="btn sm" id="eirpRevealCsv">所在文件夹</button></div>'):
    '<div class="note small">导出 CSV（格点表 lat,lon,EIRP + 等值线表）后可带入 SATSOFT 交叉核对；.grd 方向图文件在「④ 天线链路预算 → 标准远场方向图」面板导出（GRASP ASCII 球面网格）。</div>';
  let metTab='<table><tr><th>等值线电平</th><th class="num">足迹直径 (km)</th><th class="num">覆盖面积 (km²)</th><th class="num">有效射线</th></tr>';
  lv.forEach(x=>{
    const m=met[String(x)]||met[x]||{};
    metTab+='<tr><td>'+n(x,1)+' dBW（峰值'+(x===lv[0]?"−3dB":"−10dB")+'）</td><td class="num">'+n(m.diameter_km,0)+'</td><td class="num">'+n(m.area_km2,0)+'</td><td class="num">'+(m.n_rays||0)+'/8</td></tr>';
  });
  metTab+='</table>';
  return '<div class="chips"><span class="tag info">星位 '+n(sa.lon,1)+'°'+(sa.lon>=0?"E":"W")+(sa.isGeo?"（GEO 定点）":"（瞬时星下点）")+'</span>'+
    '<span class="tag mut">计算窗 '+n(lats0(C),2)+'°~'+n(lats1(C),2)+'°N · '+n(lons0(C),2)+'°~'+n(lons1(C),2)+'°E</span>'+
    '<span class="tag '+(C.exact?"ok":"warn")+'">'+(C.exact?"精确方向图逐点投影":"grid 插值")+'</span>'+
    '<span style="flex:1"></span><button class="btn sm" id="eirpExportCsv">⬇ 导出覆盖 CSV</button></div>'+
    kpis+'<div class="plotbox"><h4>地面 EIRP 覆盖（'+n(lv[0],1)+' dBW 红 / '+n(lv[1],1)+' dBW 橙 等值线 · 海岸线仅示意无政治边界）</h4>'+eirpMapSvg(C)+'</div>'+
    '<h4>覆盖度量（8 方位射线平均）</h4>'+metTab+csvBox+
    '<div class="note small"><b>计算说明：</b>'+h(C.note||"")+'</div>';
}
function lats0(C){return C.lat&&C.lat.length?C.lat[0]:0}
function lats1(C){return C.lat&&C.lat.length?C.lat[C.lat.length-1]:0}
function lons0(C){return C.lon&&C.lon.length?C.lon[0]:0}
function lons1(C){return C.lon&&C.lon.length?C.lon[C.lon.length-1]:0}

/* ---------- ③ 载荷组成框图 ---------- */
const EDGE_COLOR={rf_up:"#b0662c",rf_dn:"#0b5cad",dig:"#7048a8",opt:"#0a7ea4",if_:"#5f7183","if":"#5f7183",ctrl:"#8a97a5"};
const NODE_FILL={ant:"#eaf1fa",rf:"#f3f7fb",amp:"#fdf3e0",dig:"#f3eefb",opt:"#e6f5f8",ctrl:"#f1f4f7"};
const NODE_STROKE={ant:"#7ea3d0",rf:"#a8bdd4",amp:"#d9b06a",dig:"#b394dd",opt:"#79c2d0",ctrl:"#b0bcc9"};
function renderDiag(){
  const D=RES.diagram;
  const COLW=252, NODEW=228, NODEH0=52, GAPY=14, TOP=54;
  // 布局：每列节点纵向排布
  const byCol={};
  D.nodes.forEach(nd=>{ (byCol[nd.col]=byCol[nd.col]||[]).push(nd); });
  const pos={}; let maxRows=0;
  D.cols.forEach(c=>{
    const list=byCol[c.id]||[]; maxRows=Math.max(maxRows,list.length);
    let y=TOP;
    list.forEach((nd,i)=>{
      const lines=String(nd.cn).split("\n").length;
      const hh=NODEH0+(lines-1)*15+(nd.note?14:0);
      pos[nd.id]={x:c.x*COLW+12,y:y,w:NODEW,h:hh,col:c.x};
      y+=hh+GAPY;
    });
  });
  const W=D.cols.length*COLW, H=TOP+maxRows*(NODEH0+GAPY)+90;
  let svg='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+" "+H+'" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,sans-serif">';
  svg+='<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="#5f7183"/></marker>'+
    Object.keys(EDGE_COLOR).filter(k=>k!=="if_").map(k=>'<marker id="arr_'+k+'" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="'+EDGE_COLOR[k]+'"/></marker>').join("")+
  '</defs>';
  // 列标题
  D.cols.forEach(c=>{
    svg+='<text x="'+(c.x*COLW+12+NODEW/2)+'" y="30" text-anchor="middle" font-size="14" font-weight="bold" fill="#0b5cad">'+h(c.cn)+'</text>'+
         '<rect x="'+(c.x*COLW+8)+'" y="40" width="'+(NODEW+8)+'" height="'+(H-52)+'" rx="10" fill="none" stroke="#dde5ee" stroke-dasharray="4 3"/>';
  });
  // 节点
  D.nodes.forEach(nd=>{
    const p=pos[nd.id]; if(!p) return;
    const fill=NODE_FILL[nd.kind]||NODE_FILL.rf, st=NODE_STROKE[nd.kind]||NODE_STROKE.rf;
    svg+='<rect x="'+p.x+'" y="'+p.y+'" width="'+p.w+'" height="'+p.h+'" rx="8" fill="'+fill+'" stroke="'+st+'" stroke-width="1.4"/>';
    const lines=String(nd.cn).split("\n");
    lines.forEach((ln,i)=>{
      svg+='<text x="'+(p.x+10)+'" y="'+(p.y+19+i*15)+'" font-size="12" font-weight="'+(i===0?700:400)+'" fill="#1c2733">'+h(ln)+'</text>';
    });
    let yy=p.y+19+lines.length*15;
    if(nd.qty&&nd.qty>1){ svg+='<text x="'+(p.x+p.w-10)+'" y="'+(p.y+19)+'" text-anchor="end" font-size="11" fill="#0b5cad">×'+nd.qty+'</text>'; }
    if(nd.note){ svg+='<text x="'+(p.x+10)+'" y="'+(yy)+'" font-size="10" fill="#5f7183">'+h(String(nd.note).slice(0,40))+(nd.note.length>40?"…":"")+'</text>'; }
  });
  // 边
  D.edges.forEach(e=>{
    const a=pos[e.f], b=pos[e.t]; if(!a||!b) return;
    const col=EDGE_COLOR[e.kind]||EDGE_COLOR["if"];
    const sameCol=a.col===b.col;
    let x1,y1,x2,y2,path;
    if(b.col>a.col){ x1=a.x+a.w; y1=a.y+a.h/2; x2=b.x; y2=b.y+b.h/2; }
    else if(b.col<a.col){ x1=a.x; y1=a.y+a.h/2; x2=b.x+b.w; y2=b.y+b.h/2; }
    else { x1=a.x+a.w/2; y1=a.y+a.h; x2=b.x+b.w/2; y2=b.y; }
    const mx=(x1+x2)/2;
    path='M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2;
    svg+='<path d="'+path+'" fill="none" stroke="'+col+'" stroke-width="1.8" marker-end="url(#arr_'+e.kind+')"/>';
    if(e.label){
      const lx=(x1+x2)/2, ly=(y1+y2)/2-5;
      svg+='<text x="'+lx+'" y="'+ly+'" text-anchor="middle" font-size="10" fill="'+col+'">'+h(e.label)+'</text>';
    }
  });
  svg+='</svg>';
  el("diag").innerHTML='<div class="panel"><h2>载荷组成框图（'+h(RES.cfg.mode)+' 体制 · '+h(RES.cfg.band)+' 用户频段'+
    (RES.cfg.feeder_band!==RES.cfg.band?" / "+h(RES.cfg.feeder_band)+" 馈电":"")+'）</h2>'+
    '<div class="legend">'+
      '<span><i style="background:'+EDGE_COLOR.rf_up+'"></i>上行射频</span>'+
      '<span><i style="background:'+EDGE_COLOR.rf_dn+'"></i>下行射频</span>'+
      '<span><i style="background:'+EDGE_COLOR.dig+'"></i>数字域</span>'+
      '<span><i style="background:'+EDGE_COLOR.opt+'"></i>激光/光域</span>'+
      '<span><i style="background:'+EDGE_COLOR["if"]+'"></i>中频</span>'+
      '<span><i style="background:'+EDGE_COLOR.ctrl+'"></i>控制/重构</span>'+
    '</div><div class="diag-wrap">'+svg+'</div>'+
    '<div class="note small">框图由 design_engine.block_diagram() 按「体制 + 天线类型 + 频段规划」自动生成：节点=单机/功能模块（×数量为货架清单件数），连线=信号/控制流向。'+
    '处理列随体制变化：透明→IMUX/均衡/开关矩阵；DTP→ADC/交换矩阵/DAC；再生→解调/译码/路由/调制。相控阵体制下功放为分布式 T/R 阵列。</div></div>'+
    renderInfoFlowDiagram("dg");
}

/* ---------- ③b 可视化信息流图（泳道分层：类别泳道 × 功能层列 · 正交连线无交叉） ---------- */
const IF_COLOR={rf:"#b0662c",rf2:"#0b5cad",dig:"#7048a8",opt:"#0a7ea4",bus:"#5f7183",pwr:"#c0392b"};
function ifColorOf(f){
  // 层次化配色：优先按信息流类别（业务/数据/控制/能量）着色，与⑥页分组一致
  const TO=(typeof RES!=="undefined"&&RES&&RES.flows&&RES.flows.tier_of)||{};
  if(f&&f.tier&&TO[f.tier]&&TO[f.tier].color) return TO[f.tier].color;
  const m=(f.medium||"")+" "+(f.name||"");
  if(/激光|光域|光路/.test(m)) return IF_COLOR.opt;
  if(/电力|供能|功率流/.test(m)) return IF_COLOR.pwr;
  if(/1553|CAN|总线|指令/.test(m)) return IF_COLOR.bus;
  if(/FC-AE|数据/.test(m)) return IF_COLOR.dig;
  if(/下行|落地|回传/.test(f.name||"")) return IF_COLOR.rf2;
  return IF_COLOR.rf;
}
function ifBidir(f){ return /⇄|↔/.test(String(f.path||"")); }
/* 中文断行：max 字/行，最多 2 行（超出加省略号） */
function ifWrap2(s,max){
  s=String(s||"");
  if(s.length<=max) return [s];
  return [s.slice(0,max),s.slice(max,max*2-1)+(s.length>max*2?"…":s.slice(max*2-1)?"…":"")];
}
/* 一条信息流行（泳道内）：身份列（名称/段/速率）+ 功能层列节点盒 + 水平正交连线（同层合并，无交叉） */
function ifFlowRow(f,gIdx,uid,y,G){
  const col=ifColorOf(f), ym=y+G.ROWH/2+1;
  let s='<g class="if-node">';
  // ---- 身份列 ----
  const nm=ifWrap2(f.name,13);
  s+='<text x="'+(G.LANE_L+6)+'" y="'+(y+16)+'" font-size="11" font-weight="700" fill="#1c2733">'+h(nm[0])+'</text>';
  if(nm[1]) s+='<text x="'+(G.LANE_L+6)+'" y="'+(y+29)+'" font-size="11" font-weight="700" fill="#1c2733">'+h(nm[1])+'</text>';
  s+='<rect x="'+(G.LANE_L+6)+'" y="'+(y+33)+'" width="64" height="15" rx="7.5" fill="'+col+'" fill-opacity=".12" stroke="'+col+'" stroke-opacity=".4"/>'+
     '<text x="'+(G.LANE_L+38)+'" y="'+(y+44)+'" text-anchor="middle" font-size="9" font-weight="700" fill="'+col+'">'+h(G.lvCN[f.level]||"")+'</text>';
  const rt=String(f.rate||"");
  s+='<text x="'+(G.LANE_L+76)+'" y="'+(y+44)+'" font-size="8.5" fill="#5f7183">'+h(rt.length>22?rt.slice(0,21)+"…":rt)+'</text>';
  // ---- 功能层节点盒（同层合并；列对齐 → 连线全水平，零交叉）----
  const byL={};
  (f.stages||[]).forEach(st=>{(byL[st.layer]=byL[st.layer]||[]).push(st.node);});
  const ks=G.order.filter(k=>byL[k]&&byL[k].length);
  const bid=ifBidir(f);
  const pts=[];
  ks.forEach(k=>{
    const gi=G.layerIdx[k]; if(gi===undefined) return;
    const x=G.colX(gi), bw=G.COLW-18;
    const txt=byL[k].join("/");
    s+='<rect x="'+x+'" y="'+(ym-16)+'" width="'+bw+'" height="32" rx="8" fill="#fff" stroke="'+col+'" stroke-opacity=".6"/>'+
       '<rect x="'+x+'" y="'+(ym-16)+'" width="4" height="32" rx="2" fill="'+col+'"/>';
    s+='<text x="'+(x+bw/2+2)+'" y="'+(ym-2)+'" text-anchor="middle" font-size="9.8" fill="#1c2733">'+h(txt.length>14?txt.slice(0,13)+"…":txt)+'</text>';
    s+='<text x="'+(x+bw/2+2)+'" y="'+(ym+11)+'" text-anchor="middle" font-size="8" fill="'+col+'" opacity=".8">'+h(k)+'</text>';
    pts.push([x,x+bw]);
  });
  // ---- 连线 + 流动包 ----
  if(pts.length>=2){
    const dly=parseFloat(String(f.delay||"").match(/[\d.]+/));
    let dur=isNaN(dly)?2.6:Math.max(1.2,Math.min(3.6,1.0+dly*0.5));
    if(/电力|供能/.test(f.medium||"")) dur=4.2;
    const pid="ifp_"+uid+"_"+gIdx;
    let d="M"+pts[0][1]+","+ym;
    for(let i=1;i<pts.length;i++) d+=" L"+pts[i][0]+","+ym;
    s+='<path id="'+pid+'" class="if-link" d="'+d+'" stroke="'+col+'" opacity=".3"/>';
    s+='<path class="if-link if-anim" d="'+d+'" stroke="'+col+'" marker-end="url(#ifar_'+uid+')"/>';
    if(bid) s+='<path class="if-link" d="M'+pts[pts.length-1][0]+','+(ym+11)+' L'+pts[0][1]+','+(ym+11)+'" stroke="'+col+'" opacity=".4" stroke-dasharray="3 4" marker-end="url(#ifar_'+uid+')"/>';
    for(let k=0;k<2;k++){
      s+='<circle r="3.6" fill="'+col+'" class="if-pkt"><animateMotion dur="'+dur.toFixed(2)+'s" begin="'+(k*dur/2).toFixed(2)+'s" repeatCount="indefinite"><mpath href="#'+pid+'"/></animateMotion></circle>';
    }
  }
  return s+'</g>';
}
function renderInfoFlowDiagram(uid){
  const F=RES.flows, dn=F.delay_note;
  const tiers=F.tiers||[], levels=F.levels||[];
  const stagesDef=F.stages_def||[];
  const all=F.all||[].concat(F.sg||[],F.si||[],F.sn||[]);
  // ---- 泳道几何：行=类别泳道（内按 星地→星间→星内 分段），列=功能层 L1..L8 ----
  const W=1460,LANE_L=146,IDW=172,ROWH=54,HDR=96;
  const COLW=Math.floor((W-LANE_L-IDW-24)/Math.max(stagesDef.length,8));
  const colX=gi=>LANE_L+IDW+gi*COLW+9;
  const order=stagesDef.map(s=>s[0]);
  const layerIdx={}; order.forEach((k,i)=>layerIdx[k]=i);
  const G={W:W,LANE_L:LANE_L,IDW:IDW,COLW:COLW,ROWH:ROWH,colX:colX,order:order,layerIdx:layerIdx,
           lvCN:{sg:"星地信息流",si:"星间信息流",sn:"星内信息流"}};
  // 泳道数据：tier → level 分组（保序）
  const lanes=[];
  tiers.forEach(t=>{
    const gs=levels.map(l=>({lv:l,list:all.filter(f=>f.tier===t.key&&f.level===l.key)})).filter(g=>g.list.length);
    if(gs.length) lanes.push({tier:t,gs:gs,n:gs.reduce((a,g)=>a+g.list.length,0)});
  });
  let H=HDR;
  const laneY=[];
  lanes.forEach(l=>{laneY.push(H);H+=32+l.n*ROWH+10;});
  H+=84;
  let svg='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  svg+='<defs><marker id="ifar_'+uid+'" markerWidth="9" markerHeight="9" refX="8" refY="3.2" orient="auto"><path d="M0,0 L8,3.2 L0,6.4 z" fill="#5f7183"/></marker>'+
    '<linearGradient id="ifhg_'+uid+'" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0a3a6b"/><stop offset="1" stop-color="#0a7ea4"/></linearGradient></defs>';
  // 顶部：卫星平台总标注
  svg+='<rect x="14" y="6" width="'+(W-28)+'" height="26" rx="8" fill="url(#ifhg_'+uid+')" />'+
    '<text x="'+(W/2)+'" y="23" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">🛰 '+h(RES.cfg.name||"卫星方案")+' · '+h(RES.req.orbit_cn)+' · '+h(RES.mode_info.cn||"")+'体制 ｜ 单跳时延 '+n(dn.total_ms,2)+' ms（传播 '+n(dn.prop_ms,2)+' + 星上 '+n(dn.onboard_ms,2)+'）</text>';
  // 列头：功能层 L1..L8（泳道列 = 真实信号链层次，节点按层落列 → 连线只向右，零交叉）
  svg+='<rect x="'+LANE_L+'" y="40" width="'+IDW+'" height="44" rx="8" fill="#eef1f5" stroke="#dde5ee"/>'+
    '<text x="'+(LANE_L+IDW/2)+'" y="58" text-anchor="middle" font-size="11" font-weight="700" fill="#2c3e50">信息流（类别泳道）</text>'+
    '<text x="'+(LANE_L+IDW/2)+'" y="74" text-anchor="middle" font-size="9" fill="#5f7183">名称 / 空间段 / 速率</text>';
  stagesDef.forEach((sd,i)=>{
    const x=colX(i), bw=COLW-18;
    svg+='<rect x="'+x+'" y="40" width="'+bw+'" height="44" rx="8" fill="#eaf1fa" stroke="#c9daee"/>'+
      '<text x="'+(x+bw/2)+'" y="57" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0b5cad">'+h(sd[0])+'</text>'+
      '<text x="'+(x+bw/2)+'" y="72" text-anchor="middle" font-size="9" fill="#2c3e50">'+h(String(sd[1]).replace(/\/.*$/,""))+'</text>';
  });
  let gIdx=0;
  lanes.forEach((ln,li)=>{
    const by=laneY[li], t=ln.tier;
    const bh=26+ln.n*ROWH+8;
    // 泳道背景 + 左侧标签（跨行竖排色条）
    svg+='<rect x="8" y="'+by+'" width="'+(W-16)+'" height="'+bh+'" rx="12" fill="'+h(t.color)+'" fill-opacity=".045" stroke="'+h(t.color)+'" stroke-opacity=".3"/>';
    svg+='<rect x="8" y="'+by+'" width="6" height="'+bh+'" rx="3" fill="'+h(t.color)+'"/>';
    svg+='<rect x="20" y="'+(by+5)+'" width="120" height="20" rx="10" fill="'+h(t.color)+'"/>'+
      '<text x="80" y="'+(by+19)+'" text-anchor="middle" font-size="11.5" font-weight="700" fill="#fff">'+h(t.cn)+' ×'+ln.n+'</text>';
    let ry=by+30;
    ln.gs.forEach((g,gi)=>{
      if(gi>0){ svg+='<line x1="'+(LANE_L-4)+'" y1="'+(ry-4)+'" x2="'+(W-20)+'" y2="'+(ry-4)+'" stroke="'+h(t.color)+'" stroke-opacity=".18" stroke-dasharray="4 4"/>'; }
      g.list.forEach(f=>{ svg+=ifFlowRow(f,gIdx,uid,ry,G); ry+=ROWH; gIdx++; });
    });
  });
  // 底部：体制演进趋势标注（参考行业公开资料，按当前体制高亮）
  const trends=[
    {t:"透明转发 → 数字透明(DTP) → 再生处理",on:/再生/.test(dn.mode||"")?2:(/数字/.test(dn.mode||"")?1:0)},
    {t:"星间激光组网 · 共享关口站（减少落地双跳）",on:RES.cfg.isl_type?1:0},
    {t:"星上存储转发 + 在轨重构（波束/子带/功率/路由）",on:/重构|跳变/.test(RES.cfg.Mode||"")?1:0}
  ];
  let tx=20;
  svg+='<text x="14" y="'+(H-52)+'" font-size="11.5" font-weight="700" fill="#0b5cad">体制演进趋势（本方案所处位置）：</text>';
  trends.forEach((tr,i)=>{
    const w=16+tr.t.length*11.6;
    svg+='<rect x="'+tx+'" y="'+(H-42)+'" width="'+w+'" height="24" rx="12" fill="'+(tr.on?"#e5f5ec":"#eef1f5")+'" stroke="'+(tr.on?"#1d8a4e":"#dde5ee")+'"/>'+
      '<text x="'+(tx+10)+'" y="'+(H-26)+'" font-size="11" fill="'+(tr.on?"#1a6b40":"#5f7183")+'">'+(tr.on?"✓ ":"○ ")+h(tr.t)+'</text>';
    tx+=w+12;
  });
  svg+='</svg>';
  return '<div class="panel"><h2>可视化信息流图（泳道分层：四类信息流泳道 × 八功能层列 · 连线只向右零交叉）</h2>'+
    '<div class="legend">'+
      tiers.map(t=>'<span><i style="background:'+h(t.color)+'"></i>'+h(t.cn)+'</span>').join("")+
      '<span style="color:#8a99a8">｜ 列 = 功能层（'+h(order.join(" → "))+'），每条流按路径落列、同层合并</span>'+
    '</div><div class="diag-wrap">'+svg+'</div>'+
    '<div class="note small">泳道分层布局（整治「太乱」）：<b>行=信息流类别泳道</b>（业务/载荷数据/控制/能量，色带分组），'+
    '<b>列=功能层 L1 接入→L8 供能</b>（与真实载荷信号链一致），每条流一行、节点按功能层落列、同层节点合并——'+
    '连线全部水平向右，<b>无交叉</b>；空间段（星地信息流/星间信息流/星内信息流）以行内徽标标注、泳道内虚线分段。'+
    '双向流（⇄）附虚线回程。流动包点速率按时延相对映射，仅为可视化示意；每条流与「⑥ 信息流设计」页卡片一一对应。</div></div>';
}

/* ---------- ④ 天线链路预算 ---------- */
function renderAnt(){
  const R=RES, ant=R.res.antenna, e=R.res.eirp, g=R.res.gt, der=R.params._derived;
  const up=R.res.uplink, dn=R.res.downlink;
  const stageRows=(stages,mode)=>{
    if(!stages||!stages.length) return '<tr><td colspan="6" class="muted">无</td></tr>';
    return stages.map((s,i)=>'<tr><td class="num">'+(i+1)+'</td><td>'+h(s.cn||s.id)+'</td><td>'+h(s.kind||"")+'</td>'+
      '<td class="num">'+n(s.g_db,2)+'</td><td class="num">'+n(s.p_in_dbw,2)+'</td><td class="num">'+n(s.p_out_dbw,2)+'</td></tr>'+(
        s.note?'<tr><td></td><td colspan="5" class="muted small">'+h(s.note)+'</td></tr>':"")).join("");
  };
  const txf=(R.res.flows||{}).ant_tx_path||{stages:[]};
  const rxfId=g.rx_chain_id; const rxfRaw=(R.res.flows||{})[rxfId]||{};
  const rxf=rxfRaw.rx||rxfRaw;

  let html='<div class="panel"><h2>天线电气与 EIRP / G/T（c-1 ~ c-6）</h2><div class="kpis">'+
    kpi("天线类型",ant.ant_type,"")+kpi("增益 G_ant",ant.G_ant,"dBi（"+h(ant.G_source||"")+"）")+
    kpi("波束宽度 θ3dB",ant["θ_3dB"],"°")+kpi("工作波长 λ",ant.lam_mm,"mm")+
    kpi("EIRP（发射）",e.EIRP,"dBW")+kpi("G/T（接收）",g.GT,"dB/K")+
    kpi("T_sys",g.T_sys,"K（"+h(g.source||"")+"）")+kpi("功放 P_out",e.P_out_w,"W（η="+n(e["η_pa_pct"],0)+"%）")+
  '</div>';

  html+='<h3>发射 EIRP 预算（c-1：EIRP = P_out + G_ant − L_feed − L_tx）</h3><table>'+
    '<tr><th>项</th><th class="num">值 (dB/dBW)</th><th>说明</th></tr>'+
    '<tr><td>P_out 功放饱和输出</td><td class="num">'+n(e.P_out_dbw,2)+' dBW（'+n(e.P_out_w,1)+'W）</td><td>'+h(der.p_out_source||"")+'</td></tr>'+
    '<tr><td>G_ant 天线增益</td><td class="num">'+n(e.G_ant,2)+' dBi</td><td>'+(ant.formula==="c-3"?"相控阵 10lg(N_el·η)+G_el−扫描损耗":"反射面 10lg(η(πD/λ)²)")+'</td></tr>'+
    '<tr><td>L_feed 馈线损耗</td><td class="num">−'+n(e.L_feed,2)+' dB</td><td>馈源/波导/旋转关节</td></tr>'+
    '<tr><td>L_tx 发射链损耗</td><td class="num">−'+n(e.L_tx,2)+' dB</td><td>'+h(e.L_tx_source||"")+'（OMUX/滤波/隔离器）</td></tr>'+
    '<tr><td><b>EIRP</b></td><td class="num"><b>'+n(e.EIRP,2)+' dBW</b></td><td>需求 '+n(der.EIRP_req,2)+' dBW → '+tag(e.EIRP>=der.EIRP_req-0.05,"满足/缺口 "+n(e.EIRP-der.EIRP_req,2)+"dB")+'</td></tr>'+
  '</table>';

  html+='<h3>发射链逐级电平（ant_tx_path 信息流）</h3><table><tr><th>#</th><th>单机</th><th>类型</th><th class="num">增益/损耗 dB</th><th class="num">入口 dBW</th><th class="num">出口 dBW</th></tr>'+
    stageRows(txf.stages)+'</table>';

  html+='<h3>接收 G/T 预算（c-2：G/T = G_ant − 10lg(T_sys)，Friis 级联）</h3><table>'+
    '<tr><th>项</th><th class="num">值</th><th>说明</th></tr>'+
    '<tr><td>G_ant</td><td class="num">'+n(g.G_ant,2)+' dBi</td><td>接收链 '+h(g.rx_chain_name||rxfId||"")+'</td></tr>'+
    '<tr><td>T_ant 天线噪声</td><td class="num">'+n(g.T_ant,1)+' K</td><td>天空噪声+馈线</td></tr>'+
    '<tr><td>T_rx 接收机噪声</td><td class="num">'+n(g.T_rx,1)+' K</td><td>LNA/T-R 组件 NF 级联</td></tr>'+
    '<tr><td>T_sys</td><td class="num">'+n(g.T_sys,1)+' K</td><td>NF_total = '+n(g.NF_total_db,2)+' dB</td></tr>'+
    '<tr><td><b>G/T</b></td><td class="num"><b>'+n(g.GT,2)+' dB/K</b></td><td>需求 '+n(der.GT_req,2)+' dB/K → '+tag(g.GT>=der.GT_req-0.05,"满足/缺口 "+n(g.GT-der.GT_req,2)+"dB")+'</td></tr>'+
  '</table>';
  if(rxf&&rxf.stages){
    html+='<h3>接收链逐级噪声（'+h((rxf.meta&&rxf.meta.name)||rxfId)+'）</h3><table><tr><th>#</th><th>单机</th><th class="num">增益 dB</th><th class="num">NF dB</th><th class="num">累计增益 dB</th><th class="num">本级噪声贡献 K</th></tr>'+
      rxf.stages.map((s,i)=>'<tr><td class="num">'+(i+1)+'</td><td>'+h(s.cn||s.id)+'</td><td class="num">'+n(s.g_db,2)+'</td><td class="num">'+n(s.nf_db,2)+'</td>'+
        '<td class="num">'+n(s.cum_g_db,2)+'</td><td class="num">'+n(s.T_contrib,2)+'</td></tr>').join("")+'</table>';
  }
  html+='</div>';

  // 用户/馈电上下行
  html+='<div class="panel"><h2>用户链路与馈电链路预算（c-7 ~ c-11）</h2>';
  [["上行（馈电/用户→星）",up],["下行（星→用户/关口站）",dn]].forEach(pair=>{
    const nm=pair[0], lk=pair[1];
    html+='<h3>'+h(nm)+' · '+n(lk.f_ghz,3)+' GHz · 斜距 '+n(lk.d_km,0)+' km</h3><table>'+
    '<tr><th>步骤</th><th class="num">值</th><th>公式/说明</th></tr>'+
    '<tr><td>EIRP（'+h(lk.gt_sym==="GT_ant"?"关口站/终端":"星上，按载波折算")+'）</td><td class="num">'+n(lk.EIRP,2)+' dBW</td><td>总 '+n(lk.EIRP_total,2)+' dBW'+(lk.share_db>0?" − 载波分摊 "+n(lk.share_db,2)+"dB（"+n(lk.N_carrier,1)+" 载波）":"")+'</td></tr>'+
    '<tr><td>L_fs 自由空间损耗</td><td class="num">'+n(lk.L_fs,2)+' dB</td><td>20lg(d)+20lg(f)−147.55</td></tr>'+
    '<tr><td>ΣL 其它损耗</td><td class="num">'+n(lk.sum_L,2)+' dB</td><td>雨衰 '+n(lk.A_rain,2)+'（可用性 '+n(lk.avail,1)+'%，仰角 '+n(lk.el,0)+'°）+ 大气 '+n(lk.A_atm,2)+' + 指向 '+n(lk.L_pnt,2)+' + 极化 '+n(lk.L_pol,2)+' + 实现 '+n(lk.L_impl,2)+'</td></tr>'+
    '<tr><td>G/T（'+h(lk.gt_sym==="GT_ant"?"星上":"关口站")+'）</td><td class="num">'+n(lk.GT,2)+' dB/K</td><td></td></tr>'+
    '<tr><td>C/N0</td><td class="num">'+n(lk.CN0,2)+' dBHz</td><td>EIRP − L_fs − ΣL + G/T − k</td></tr>'+
    '<tr><td>C/N（B='+n(lk.B_mhz,2)+'MHz）</td><td class="num">'+n(lk.CN,2)+' dB</td><td>C/N0 − 10lg(B)</td></tr>'+
    '<tr><td>MODCOD</td><td class="num">'+h(lk.modcod)+'</td><td>η='+n(lk.eta,3)+' bps/Hz，(C/N)req='+n(lk.CN_req,2)+' dB</td></tr>'+
    '<tr><td><b>余量 M</b></td><td class="num"><b>'+n(lk.M,2)+' dB</b></td><td>'+tag(lk.M>=toF(CFG.M_target,3),"≥/< 门限 "+n(toF(CFG.M_target,3),1)+"dB")+'</td></tr>'+
    '<tr><td>链路容量 C_link</td><td class="num">'+n(lk.C_link_gbps,3)+' Gbps</td><td>B×η；波束容量 '+n(lk.C_beam_gbps,3)+' Gbps</td></tr>'+
    '</table>';
  });
  const e2e=R.res.e2e;
  html+='<h3>端到端（'+h(e2e.arch)+'）</h3><table><tr><th>项</th><th class="num">值</th></tr>'+
    '<tr><td>C/N 上 / 下 / 总</td><td class="num">'+n(e2e.CN_up,2)+' / '+n(e2e.CN_dn,2)+' / '+n(e2e.CN_total,2)+' dB</td></tr>'+
    '<tr><td>MODCOD / η</td><td class="num">'+h(e2e.modcod)+' / '+n(e2e.eta,3)+'</td></tr>'+
    '<tr><td>再生增益 ΔM_reg</td><td class="num">'+n(e2e.regen_bonus,1)+' dB</td></tr>'+
    '<tr><td><b>端到端余量 M</b></td><td class="num"><b>'+n(e2e.M,2)+' dB</b></td></tr></table></div>';
  // 波束覆盖性能（GRASP 仿真 / 解析方向图）——异步加载
  html+='<div class="panel" id="beamPanel"><h2>波束覆盖性能（TICRA GRASP 物理光学仿真 · 失败自动降级解析口径方向图）</h2>'+
    '<div id="beamBody"><div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> GRASP 求解中（偏置抛物面 PO 法，约 1~5 s）…</div></div></div>';
  // 标准方向图（grid + cut，内置第一性原理计算 + 导出 GRASP .grd）——异步加载
  html+='<div class="panel" id="patPanel"><h2>标准远场方向图（grid θ×φ + cut ±15° · 栅瓣检查 · 内置计算 + 导出 GRASP .grd）</h2>'+
    '<div id="patBody"><div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> 方向图求解中（次级方向图 grid + cut）…</div></div></div>';
  el("ant").innerHTML=html;
  loadBeamPanel();
  loadPatternPanel();
}

/* ---------- ④b 波束覆盖：GRASP/解析方向图 + 地面覆盖足迹 ---------- */
let _beamSeq=0;
function beamAperture(){
  const ant=RES.res.antenna;
  if(ant.D_m) return ant.D_m;
  // 相控阵：由整阵增益反推等效口径 D = λ/π·√(G_lin/η)
  const Glin=Math.pow(10,(ant.G_ant||0)/10);
  const eta=(toF(CFG["η_ill"],65)/100)||0.65;
  return (ant.lam_m||0.02)/Math.PI*Math.sqrt(Glin/eta);
}
async function loadBeamPanel(){
  const seq=++_beamSeq;
  const D=beamAperture(), lk=RES.res.downlink||{};
  const f=lk.f_ghz||((META.band_freq[RES.cfg.band]||[20])[1]);
  const scan=toF(CFG["θ_scan"],0);
  try{
    const r=await apiCall("beam",{D_ap:D,freq_ghz:f,prefer:"grasp",tag:"ui_"+RES.cfg.band,
      with_2d:true,scan_deg:scan});
    if(seq!==_beamSeq) return;
    const box=el("beamBody"); if(!box) return;
    if(!r.ok||!r.result||!r.result.ok){
      box.innerHTML='<div class="warnbox">波束方向图计算失败：'+h((r.result&&r.result.error)||r.error||"未知错误")+'</div>';
      return;
    }
    box.innerHTML=beamPanelHTML(r.result,D,f);
  }catch(e){
    if(seq!==_beamSeq) return;
    const box=el("beamBody");
    if(box) box.innerHTML='<div class="warnbox">波束计算通道不可用：'+h(e)+'</div>';
  }
}
/* 二维方向图热力图（θx–θy 平面 dBr，Canvas→dataURL；数据来自后端 pattern_2d_grid） */
function heat2dSvg(P){
  if(!P||!P.grid||!P.grid.length) return "";
  // 注意：局部变量切勿命名为 n —— 会遮蔽全局数字格式化函数 n(v,nd)，
  // 导致下方刻度 n(t,0) 抛 "n is not a function"（网格尺寸统一用 gn）
  const gn=P.grid.length, CW=430, PL=46, PT=30, PB=44, PR=64;
  const W=PL+CW+PR, H=PT+CW+PB;
  const cv=document.createElement("canvas"); cv.width=gn; cv.height=gn;
  const cx2=(typeof cv.getContext==="function")?cv.getContext("2d"):null;
  if(!cx2) return "";   // 无 Canvas 环境（老内核/测试桩）→ 跳过二维图
  const img=cx2.createImageData(gn,gn);
  function heatc(v){
    const t=Math.min(Math.max((v+40)/40,0),1);
    const stops=[[0,[13,30,74]],[0.30,[11,92,173]],[0.55,[10,126,164]],[0.75,[29,138,78]],[0.90,[230,190,40]],[1,[214,69,45]]];
    for(let i=0;i<stops.length-1;i++){
      const [t0,c0]=stops[i],[t1,c1]=stops[i+1];
      if(t>=t0&&t<=t1){ const k=t1>t0?(t-t0)/(t1-t0):0;
        return [Math.round(c0[0]+k*(c1[0]-c0[0])),Math.round(c0[1]+k*(c1[1]-c0[1])),Math.round(c0[2]+k*(c1[2]-c0[2]))]; }
    }
    return stops[stops.length-1][1];
  }
  for(let iy=0;iy<gn;iy++) for(let ix=0;ix<gn;ix++){
    const c=heatc(P.grid[gn-1-iy][ix]);   // y 轴翻转：theta_y 向上为正
    const o=(iy*gn+ix)*4; img.data[o]=c[0]; img.data[o+1]=c[1]; img.data[o+2]=c[2]; img.data[o+3]=255;
  }
  cx2.putImageData(img,0,0);
  const url=cv.toDataURL("image/png");
  const span=P.span, th3=P.th3;
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<image href="'+url+'" x="'+PL+'" y="'+PT+'" width="'+CW+'" height="'+CW+'" style="image-rendering:pixelated"/>';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+CW+'" height="'+CW+'" fill="none" stroke="#93a3b4"/>';
  // −3dB 等值圈（白虚线圆）
  const r3=th3/2/span*(CW/2);
  s+='<circle cx="'+(PL+CW/2)+'" cy="'+(PT+CW/2)+'" r="'+r3.toFixed(1)+'" fill="none" stroke="#fff" stroke-width="1.4" stroke-dasharray="4 3"/>'+
     '<text x="'+(PL+CW/2+r3*0.72)+'" y="'+(PT+CW/2-r3*0.72)+'" font-size="9.5" fill="#fff">−3dB</text>';
  // 刻度
  const tstep=span<=6?1:(span<=20?5:10);
  for(let t=-Math.floor(span/tstep)*tstep;t<=span+1e-9;t+=tstep){
    const px=PL+(t+span)/(2*span)*CW, py=PT+(span-t)/(2*span)*CW;
    s+='<text x="'+px.toFixed(1)+'" y="'+(H-PB+16)+'" text-anchor="middle" font-size="9.5" fill="#5f7183">'+n(t,0)+'</text>';
    s+='<text x="'+(PL-5)+'" y="'+(py+3).toFixed(1)+'" text-anchor="end" font-size="9.5" fill="#5f7183">'+n(t,0)+'</text>';
  }
  s+='<text x="'+(PL+CW/2)+'" y="'+(H-8)+'" text-anchor="middle" font-size="11" fill="#5f7183">θx (°)</text>';
  s+='<text x="14" y="'+(PT+CW/2)+'" text-anchor="middle" font-size="11" fill="#5f7183" transform="rotate(-90 14 '+(PT+CW/2)+')">θy (°)</text>';
  // 色标
  const lx=W-46;
  const gradId="hg2d";
  s+='<defs><linearGradient id="'+gradId+'" x1="0" y1="1" x2="0" y2="0">'+
     '<stop offset="0" stop-color="rgb(13,30,74)"/><stop offset=".3" stop-color="rgb(11,92,173)"/>'+
     '<stop offset=".55" stop-color="rgb(10,126,164)"/><stop offset=".75" stop-color="rgb(29,138,78)"/>'+
     '<stop offset=".9" stop-color="rgb(230,190,40)"/><stop offset="1" stop-color="rgb(214,69,45)"/></linearGradient></defs>';
  s+='<rect x="'+lx+'" y="'+PT+'" width="15" height="'+CW+'" fill="url(#'+gradId+')" stroke="#93a3b4"/>';
  [0,-10,-20,-30,-40].forEach(gv=>{
    const gy=PT+(-gv)/40*CW;
    s+='<text x="'+(lx+19)+'" y="'+(gy+3)+'" font-size="9.5" fill="#5f7183">'+gv+'</text>';
  });
  s+='<text x="'+(lx+7)+'" y="'+(PT-8)+'" text-anchor="middle" font-size="9.5" fill="#5f7183">dBr</text>';
  s+='</svg>';
  return s;
}
function beamPanelHTML(B,D,f){
  const th=B.theta||[], gd=B.gain_dbr||[];
  const span=th.length?Math.max(Math.abs(th[0]),Math.abs(th[th.length-1])):3;
  const G0=B.peak_gain_dbi||0, th3=B.beamwidth_3db_deg||0, edge=B.coverage_edge_dbr;
  const srcTag=B.source==="grasp"?'<span class="tag ok">GRASP 物理光学实测</span>':'<span class="tag warn">解析口径方向图（Airy）</span>';
  // 地面足迹：ψ=θ/2（小角近似），弧长 r = R_e·ψ_rad；星高取轨道高度
  const alt=toF((META.orbits[RES.cfg.orbit]||{}).alt_km,35786), R_e=6371;
  const foot3=(th3/2)*(Math.PI/180)*R_e;
  // -edge dB 覆盖角（从方向图找交叉点）
  let thEdge=null;
  if(edge!==null&&edge!==undefined){
    for(let i=1;i<th.length;i++){
      if(gd[i-1]>=edge&&gd[i]<edge){
        const t0=th[i-1],t1=th[i],g0=gd[i-1],g1=gd[i];
        thEdge=t0+(edge-g0)*(t1-t0)/(g1-g0||1e-9); break;
      }
    }
  }
  const footE=thEdge!==null?(thEdge/2)*(Math.PI/180)*R_e:null;
  let kpis='<div class="kpis">'+
    kpi("峰值增益 G0",G0,"dBi")+kpi("−3dB 波束宽度",th3,"°")+
    kpi("3dB 地面足迹直径",foot3*2,"km")+
    (footE!==null?kpi("−"+n(-edge,0)+"dB 覆盖直径",footE*2,"km"):kpi("覆盖边缘电平",edge,"dBr"))+
    kpi("等效口径 D",D,"m @ "+n(f,2)+"GHz")+
  '</div>';
  /* --- 直角坐标方向图（窄波束标准画法）：θ∈[-span,span]，G∈[-40,0] dBr --- */
  const PW=560,PH=330,PL=52,PR=16,PT=18,PB=42;
  const X=t=>PL+(t+span)/(2*span)*(PW-PL-PR);
  const Yq=g=>PT+(1-(Math.min(Math.max(g,-40),0)+40)/40)*(PH-PT-PB);
  let pts=[];
  for(let i=0;i<th.length;i++) pts.push(X(th[i]).toFixed(1)+","+Yq(gd[i]).toFixed(1));
  let p='<svg width="'+PW+'" height="'+PH+'" viewBox="0 0 '+PW+' '+PH+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  p+='<rect x="'+PL+'" y="'+PT+'" width="'+(PW-PL-PR)+'" height="'+(PH-PT-PB)+'" fill="#fbfdff" stroke="#dde5ee"/>';
  for(let g=0;g>=-40;g-=10){
    p+='<line x1="'+PL+'" y1="'+Yq(g)+'" x2="'+(PW-PR)+'" y2="'+Yq(g)+'" stroke="'+(g===0?"#b8c6d6":"#e8eef5")+'"/>'+
       '<text x="'+(PL-6)+'" y="'+(Yq(g)+4)+'" text-anchor="end" font-size="10" fill="#5f7183">'+g+'</text>';
  }
  const tstep=span>6?2:(span>2?1:0.5);
  for(let t=-span;t<=span+1e-9;t+=tstep){
    p+='<line x1="'+X(t)+'" y1="'+PT+'" x2="'+X(t)+'" y2="'+(PH-PB)+'" stroke="#eef2f7"/>'+
       '<text x="'+X(t)+'" y="'+(PH-PB+15)+'" text-anchor="middle" font-size="10" fill="#5f7183">'+n(t,1)+'</text>';
  }
  // −3dB 参考线
  p+='<line x1="'+PL+'" y1="'+Yq(-3)+'" x2="'+(PW-PR)+'" y2="'+Yq(-3)+'" stroke="#c0392b" stroke-dasharray="5 4" stroke-width="1.2"/>'+
     '<text x="'+(PW-PR-4)+'" y="'+(Yq(-3)-4)+'" text-anchor="end" font-size="10" fill="#c0392b">−3dB</text>';
  if(edge!==null&&edge!==undefined&&edge>-40){
    p+='<line x1="'+PL+'" y1="'+Yq(edge)+'" x2="'+(PW-PR)+'" y2="'+Yq(edge)+'" stroke="#b07514" stroke-dasharray="3 3" stroke-width="1.2"/>'+
       '<text x="'+(PW-PR-4)+'" y="'+(Yq(edge)-4)+'" text-anchor="end" font-size="10" fill="#b07514">覆盖边缘 '+n(edge,1)+'dBr</text>';
  }
  p+='<polyline points="'+pts.join(" ")+'" fill="none" stroke="#0b5cad" stroke-width="2"/>';
  // 扫描动画线（示意波束扫描范围）
  p+='<line x1="'+PL+'" y1="'+PT+'" x2="'+PL+'" y2="'+(PH-PB)+'" stroke="#0a7ea4" stroke-width="1" opacity=".55">'+
     '<animate attributeName="x1" values="'+PL+";"+(PW-PR)+";"+PL+'" dur="6s" repeatCount="indefinite"/>'+
     '<animate attributeName="x2" values="'+PL+";"+(PW-PR)+";"+PL+'" dur="6s" repeatCount="indefinite"/></line>';
  p+='<text x="'+(PW/2)+'" y="'+(PH-6)+'" text-anchor="middle" font-size="11" fill="#5f7183">离轴角 θ (°) —— 竖线往复为波束扫描示意</text>';
  p+='<text x="14" y="'+(PT-5)+'" font-size="11" fill="#5f7183">G (dBr)</text></svg>';
  /* --- 星地覆盖足迹剖面（几何示意，锥角放大） --- */
  const FW=520,FH=330,exag=Math.min(60,Math.max(8,14/Math.max(th3,0.05)));
  const fx=FW/2, fsy=34, fey=FH-6;
  const halfCone=(th3/2)*exag*(Math.PI/180);
  let q='<svg width="'+FW+'" height="'+FH+'" viewBox="0 0 '+FW+' '+FH+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  // 地球弧
  q+='<path d="M'+(fx-240)+','+(fey+58)+' Q'+fx+','+(fey-46)+' '+(fx+240)+','+(fey+58)+' L'+(fx+240)+','+FH+' L'+(fx-240)+','+FH+' Z" fill="#dcebf7" stroke="#7ea3d0"/>';
  q+='<text x="'+(fx+170)+'" y="'+(fey+34)+'" font-size="11" fill="#4a6fa5">地球（R=6371km）</text>';
  // 卫星
  q+='<g class="satsweep"><rect x="'+(fx-16)+'" y="'+(fsy-9)+'" width="32" height="18" rx="4" fill="#0b5cad"/>'+
     '<rect x="'+(fx-40)+'" y="'+(fsy-5)+'" width="20" height="10" rx="2" fill="#0a7ea4"/><rect x="'+(fx+20)+'" y="'+(fsy-5)+'" width="20" height="10" rx="2" fill="#0a7ea4"/>'+
     '<circle cx="'+fx+'" cy="'+(fsy+16)+'" r="3" fill="#b0662c"/></g>';
  q+='<text x="'+(fx+52)+'" y="'+(fsy+4)+'" font-size="11" fill="#1c2733">🛰 '+h(RES.cfg.orbit)+' · h='+n(alt,0)+'km</text>';
  // 波束锥（θ3dB 实线 + 覆盖边缘虚线），锥角放大 exag 倍便于观察
  const coneY=fey-16;
  const dx3=Math.tan(halfCone)*(coneY-fsy);
  const dxE=thEdge!==null?Math.tan((thEdge/2)*exag*(Math.PI/180))*(coneY-fsy):dx3*1.5;
  q+='<path d="M'+fx+','+(fsy+14)+' L'+(fx-dx3)+','+coneY+' M'+fx+','+(fsy+14)+' L'+(fx+dx3)+','+coneY+'" stroke="#0b5cad" stroke-width="1.8" fill="none"/>';
  q+='<path d="M'+fx+','+(fsy+14)+' L'+(fx-dxE)+','+coneY+' M'+fx+','+(fsy+14)+' L'+(fx+dxE)+','+coneY+'" stroke="#b07514" stroke-width="1.2" stroke-dasharray="4 3" fill="none"/>';
  q+='<path d="M'+(fx-dxE)+','+coneY+' L'+fx+','+(fsy+14)+' L'+(fx+dxE)+','+coneY+' Z" fill="#0b5cad" opacity=".07" class="covbeam"/>';
  // 足迹标记
  q+='<line x1="'+(fx-dx3)+'" y1="'+coneY+'" x2="'+(fx+dx3)+'" y2="'+coneY+'" stroke="#0b5cad" stroke-width="3"/>'+
     '<text x="'+fx+'" y="'+(coneY+16)+'" text-anchor="middle" font-size="10.5" fill="#0b5cad">−3dB 足迹 Ø'+n(foot3*2,0)+' km</text>';
  if(footE!==null) q+='<text x="'+fx+'" y="'+(coneY+30)+'" text-anchor="middle" font-size="10.5" fill="#b07514">覆盖边缘 Ø'+n(footE*2,0)+' km</text>';
  q+='<text x="10" y="'+(FH-8)+'" font-size="10" fill="#93a3b4">⚠ 锥角放大 '+n(exag,0)+'× 便于观察（实际 θ3dB='+n(th3,3)+'°）</text></svg>';
  // 二维方向图热力图（θx–θy 平面；后端 pattern_2d_grid 数据 → Canvas 光栅化）
  const p2=B.pattern2d?heat2dSvg(B.pattern2d):"";
  const scanDeg=toF(CFG["θ_scan"],0);
  const p2head=p2?('<div class="plotbox"><h4>二维方向图（θx–θy 平面 · dBr）'+
    (scanDeg?'（扫描 '+n(scanDeg,0)+'° · cos^1.5 修正）':'（口径旋转对称）')+'</h4>'+p2+'</div>'):"";
  const note=B.note?'<div class="note small"><b>计算说明：</b>'+h(B.note)+(B.grasp_error?"<br><span class='muted'>GRASP 信息："+h(String(B.grasp_error).slice(0,160))+"</span>":"")+'</div>':"";
  return '<div class="chips">'+srcTag+'<span class="tag info">D='+n(D,2)+' m @ '+n(f,3)+' GHz（'+h(RES.cfg.band)+' 下行）</span>'+
    '<span class="tag mut">偏置抛物面 PO / η='+n(toF(CFG["η_ill"],65),0)+'%</span></div>'+kpis+
    (p2?('<div class="beamgrid3"><div class="plotbox"><h4>一维远场方向图（主瓣切面 · 相对增益 dBr）</h4>'+p+'</div>'+p2head+
      '<div class="plotbox"><h4>星地覆盖足迹剖面（几何示意）</h4>'+q+'</div></div>')
     :('<div class="beamgrid"><div class="plotbox"><h4>远场方向图（主瓣切面 · 相对增益 dBr）</h4>'+p+'</div>'+
      '<div class="plotbox"><h4>星地覆盖足迹剖面（几何示意）</h4>'+q+'</div></div>'))+note+
    '<div class="note small">一维方向图来自 TICRA GRASP（物理光学法，偏置抛物面 F/D=1.31 + 高斯馈源 −12dB 边缘照射）实时求解；'+
    'GRASP 不可用时自动降级为口径 Airy 解析方向图 G(θ)=G0·[2J1(u)/u]²。'+
    '二维方向图为 θx–θy 平面相对增益热力图（口径 Airy 旋转对称'+(scanDeg?'，相控阵扫描按 cos^1.5(θ) 单元因子修正':'')+'），'+
    '白色虚线为 −3dB 等值圈。地面足迹 r=R_e·θ/2（小角近似），'+
    '与「② 方案总览」几何推导（波束地心张角 '+n(RES.geo["θ_beam_deg"],2)+'°）同源自洽。多波束整星覆盖见总览页覆盖示意图。</div>';
}

/* ---------- ④c 标准远场方向图（grid θ×φ + cut ±15° · 栅瓣检查 · 导出 GRASP .grd） ---------- */
let _patSeq=0;
const _patState={scanned:false,view:"cut",scanTheta:null,dlam:0.5,grd:null};
function patPayload(withGrd){
  const ant=RES.res.antenna, lk=RES.res.downlink||{};
  const f=lk.f_ghz||((META.band_freq[RES.cfg.band]||[20])[1]);
  const isArr=String(ant.ant_type||"").indexOf("相控阵")>=0;
  const scanOn=_patState.scanned;
  const thScan=scanOn?(_patState.scanTheta!==null?_patState.scanTheta:toF(CFG["θ_scan"],10)):0;
  const p={antenna_type:isArr?"phased_array":"reflector",freq_ghz:f,
    scan_theta:thScan,scan_phi:0,cut_span:15,cut_n:301,
    grid_n_theta:91,grid_n_phi:73,
    peak_gain_dbi:ant.G_ant||null,
    tag:_safeTag("方向图_"+RES.cfg.band+(scanOn?"_扫描":"_boresight"))};
  if(isArr){
    p.n_el=Math.max(4,Math.round(toF(RES.params.N_el,toF(CFG.N_el,1024))));
    p.d_lam=_patState.dlam;
  }else{
    p.D=ant.D_m||beamAperture();
  }
  if(withGrd){ p.export_grd=true; }
  return p;
}
function _safeTag(s){ return String(s).replace(/[<>:"/\\|?*]/g,"_").slice(0,50); }
async function loadPatternPanel(withGrd){
  const seq=++_patSeq;
  const box=el("patBody"); if(!box) return;
  if(!RES||!RES.res){ box.innerHTML='<div class="muted">请先完成一次设计。</div>'; return; }
  box.innerHTML='<div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> 次级方向图求解中（grid θ×φ + cut ±15°）…</div>';
  try{
    const r=await apiCall("pattern",patPayload(!!withGrd));
    if(seq!==_patSeq) return;
    const b2=el("patBody"); if(!b2) return;
    if(!r.ok||!r.result){ b2.innerHTML='<div class="warnbox">方向图计算失败：'+h(r.error||"未知错误")+'</div>'; return; }
    if(r.result.grd_file){ _patState.grd=r.result.grd_file; }
    b2.innerHTML=patternPanelHTML(r.result);
    bindPatternPanel();
  }catch(e){
    if(seq!==_patSeq) return;
    const b2=el("patBody");
    if(b2) b2.innerHTML='<div class="warnbox">方向图通道不可用：'+h(e)+'</div>';
  }
}
function bindPatternPanel(){
  const bs=el("patScanBtn"), bb=el("patBoreBtn");
  if(bb) bb.addEventListener("click",()=>{ _patState.scanned=false; loadPatternPanel(); });
  if(bs) bs.addEventListener("click",()=>{
    const inp=el("patScanInp");
    _patState.scanTheta=Math.max(0,Math.min(60,toF(inp&&inp.value,10)));
    _patState.scanned=true; loadPatternPanel();
  });
  const di=el("patDlamInp");
  if(di) di.addEventListener("change",()=>{
    _patState.dlam=Math.max(0.3,Math.min(1.2,toF(di.value,0.5)));
    if(_patState.scanned||true) loadPatternPanel();
  });
  document.querySelectorAll("#patBody .patview").forEach(b=>b.addEventListener("click",()=>{
    _patState.view=b.dataset.v; 
    document.querySelectorAll("#patBody .patview").forEach(x=>x.classList.remove("on"));
    b.classList.add("on");
    const sec={cut:"patSecCut",wide:"patSecWide",grid:"patSecGrid"};
    ["patSecCut","patSecWide","patSecGrid"].forEach(id=>{
      const e2=el(id); if(e2) e2.style.display=(id===sec[_patState.view])?"block":"none";
    });
  }));
  const ex=el("patExportGrd");
  if(ex) ex.addEventListener("click",()=>loadPatternPanel(true));
  const op=el("patOpenGrd"), rv=el("patRevealGrd");
  if(op&&_patState.grd) op.addEventListener("click",()=>apiCall("open_file",{path:_patState.grd.path}));
  if(rv&&_patState.grd) rv.addEventListener("click",()=>apiCall("reveal_file",{path:_patState.grd.path}));
}
/* grid 热力图：x=φ(0..360)、y=θ(0..90 自上而下)，Canvas 光栅化 + 栅瓣十字标记 */
function patGridSvg(P){
  const g=P.grid; if(!g||!g.gain_dbr||!g.gain_dbr.length) return "";
  const nTh=g.gain_dbr.length, nPh=g.gain_dbr[0].length;
  const CW=560,CH=300,PL=44,PT=16,PB=40,PR=62;
  const W=PL+CW+PR,H=PT+CH+PB;
  const cv=document.createElement("canvas"); cv.width=nPh; cv.height=nTh;
  const c2=(typeof cv.getContext==="function")?cv.getContext("2d"):null;
  if(!c2) return "";
  const img=c2.createImageData(nPh,nTh);
  function hc(v){
    const t=Math.min(Math.max((v+40)/40,0),1);
    const st=[[0,[13,30,74]],[0.30,[11,92,173]],[0.55,[10,126,164]],[0.75,[29,138,78]],[0.90,[230,190,40]],[1,[214,69,45]]];
    for(let i=0;i<st.length-1;i++){
      const a=st[i],b=st[i+1];
      if(t>=a[0]&&t<=b[0]){ const k=b[0]>a[0]?(t-a[0])/(b[0]-a[0]):0;
        return [Math.round(a[1][0]+k*(b[1][0]-a[1][0])),Math.round(a[1][1]+k*(b[1][1]-a[1][1])),Math.round(a[1][2]+k*(b[1][2]-a[1][2]))]; }
    }
    return st[st.length-1][1];
  }
  for(let ith=0;ith<nTh;ith++) for(let iph=0;iph<nPh;iph++){
    const c=hc(g.gain_dbr[ith][iph]);
    const o=(ith*nPh+iph)*4; img.data[o]=c[0]; img.data[o+1]=c[1]; img.data[o+2]=c[2]; img.data[o+3]=255;
  }
  c2.putImageData(img,0,0);
  const url=cv.toDataURL("image/png");
  const PX=ph=>PL+(ph/360)*CW, PY=th=>PT+(th/90)*CH;
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<image href="'+url+'" x="'+PL+'" y="'+PT+'" width="'+CW+'" height="'+CH+'" style="image-rendering:pixelated"/>';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+CW+'" height="'+CH+'" fill="none" stroke="#93a3b4"/>';
  // 栅瓣标记（白十字 + 标签）
  (P.grating_lobes||[]).forEach(gl=>{
    const gx=PX(((gl.phi_deg%360)+360)%360), gy=PY(Math.min(gl.theta_deg,90));
    s+='<g stroke="#fff" stroke-width="1.6"><line x1="'+(gx-6)+'" y1="'+gy+'" x2="'+(gx+6)+'" y2="'+gy+'"/>'+
       '<line x1="'+gx+'" y1="'+(gy-6)+'" x2="'+gx+'" y2="'+(gy+6)+'"/></g>'+
       '<circle cx="'+gx+'" cy="'+gy+'" r="8" fill="none" stroke="#fff" stroke-width="1.2" stroke-dasharray="2 2"/>'+
       '<text x="'+(gx+10)+'" y="'+(gy-6)+'" font-size="9" fill="#fff">GL'+(gl.order?("("+gl.order+")"):"")+'</text>';
  });
  // 主瓣指向十字（黄）
  const bx=PX(((P.scan_phi_deg%360)+360)%360), by=PY(Math.min(P.scan_theta_deg,90));
  s+='<g stroke="#ffd166" stroke-width="1.8"><line x1="'+(bx-7)+'" y1="'+by+'" x2="'+(bx+7)+'" y2="'+by+'"/><line x1="'+bx+'" y1="'+(by-7)+'" x2="'+bx+'" y2="'+(by+7)+'"/></g>';
  // 刻度
  for(let ph=0;ph<=360;ph+=45){
    s+='<text x="'+PX(ph)+'" y="'+(H-PB+15)+'" text-anchor="middle" font-size="9.5" fill="#5f7183">'+ph+'°</text>';
  }
  for(let th=0;th<=90;th+=15){
    s+='<text x="'+(PL-5)+'" y="'+(PY(th)+3)+'" text-anchor="end" font-size="9.5" fill="#5f7183">'+th+'°</text>';
  }
  s+='<text x="'+(PL+CW/2)+'" y="'+(H-6)+'" text-anchor="middle" font-size="11" fill="#5f7183">φ (°) —— grid 全空域（θ 0~90° 自上而下）</text>';
  s+='<text x="12" y="'+(PT+CH/2)+'" text-anchor="middle" font-size="11" fill="#5f7183" transform="rotate(-90 12 '+(PT+CH/2)+')">θ (°)</text>';
  // 色标
  const lx=W-46;
  s+='<defs><linearGradient id="pgrd" x1="0" y1="1" x2="0" y2="0">'+
     '<stop offset="0" stop-color="rgb(13,30,74)"/><stop offset=".3" stop-color="rgb(11,92,173)"/>'+
     '<stop offset=".55" stop-color="rgb(10,126,164)"/><stop offset=".75" stop-color="rgb(29,138,78)"/>'+
     '<stop offset=".9" stop-color="rgb(230,190,40)"/><stop offset="1" stop-color="rgb(214,69,45)"/></linearGradient></defs>';
  s+='<rect x="'+lx+'" y="'+PT+'" width="14" height="'+CH+'" fill="url(#pgrd)" stroke="#93a3b4"/>';
  [0,-10,-20,-30,-40].forEach(gv=>{
    const gy2=PT+(-gv)/40*CH;
    s+='<text x="'+(lx+18)+'" y="'+(gy2+3)+'" font-size="9.5" fill="#5f7183">'+gv+'</text>';
  });
  s+='<text x="'+(lx+7)+'" y="'+(PT-4)+'" text-anchor="middle" font-size="9" fill="#5f7183">dBr</text>';
  s+='</svg>';
  return s;
}
/* cut 剖面：签名 θ（宽 cut −90..+90 / 主 cut 中心±15°），栅瓣竖线标注 */
function patCutSvg(P,wide){
  const c=wide?P.cut_wide:P.cut;
  if(!c||!c.theta||!c.theta.length) return "";
  const th=c.theta, gv=c.gain_dbr;
  const tMin=th[0], tMax=th[th.length-1];
  const PW=640,PH=300,PL=48,PR=14,PT=16,PB=40;
  const X=t=>PL+(t-tMin)/(tMax-tMin)*(PW-PL-PR);
  const Y=g=>PT+(1-(Math.min(Math.max(g,-40),0)+40)/40)*(PH-PT-PB);
  let s='<svg width="'+PW+'" height="'+PH+'" viewBox="0 0 '+PW+' '+PH+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+(PW-PL-PR)+'" height="'+(PH-PT-PB)+'" fill="#fbfdff" stroke="#dde5ee"/>';
  for(let g=0;g>=-40;g-=10){
    s+='<line x1="'+PL+'" y1="'+Y(g)+'" x2="'+(PW-PR)+'" y2="'+Y(g)+'" stroke="'+(g===0?"#b8c6d6":"#e8eef5")+'"/>'+
       '<text x="'+(PL-5)+'" y="'+(Y(g)+4)+'" text-anchor="end" font-size="10" fill="#5f7183">'+g+'</text>';
  }
  const tstep=wide?15:5;
  for(let t=Math.ceil(tMin/tstep)*tstep;t<=tMax+1e-9;t+=tstep){
    s+='<line x1="'+X(t)+'" y1="'+PT+'" x2="'+X(t)+'" y2="'+(PH-PB)+'" stroke="#eef2f7"/>'+
       '<text x="'+X(t)+'" y="'+(PH-PB+15)+'" text-anchor="middle" font-size="10" fill="#5f7183">'+n(t,0)+'</text>';
  }
  // −3dB 参考线
  s+='<line x1="'+PL+'" y1="'+Y(-3)+'" x2="'+(PW-PR)+'" y2="'+Y(-3)+'" stroke="#c0392b" stroke-dasharray="5 4" stroke-width="1.1"/>'+
     '<text x="'+(PW-PR-4)+'" y="'+(Y(-3)-4)+'" text-anchor="end" font-size="10" fill="#c0392b">−3dB</text>';
  // ±15° 窗口边界（宽 cut 上画主 cut 窗）
  if(wide){
    const cspan=(P.cut&&P.cut.span)||15, ctr=(P.cut&&P.cut.center)||0;
    [ctr-cspan,ctr+cspan].forEach(tb=>{
      if(tb>=tMin&&tb<=tMax)
        s+='<line x1="'+X(tb)+'" y1="'+PT+'" x2="'+X(tb)+'" y2="'+(PH-PB)+'" stroke="#0a7ea4" stroke-dasharray="3 3" stroke-width="1" opacity=".7"/>';
    });
    s+='<text x="'+X(Math.min(Math.max(ctr+cspan,tMin),tMax))+'" y="'+(PT+12)+'" text-anchor="end" font-size="9.5" fill="#0a7ea4">±'+n(cspan,0)+'° cut 窗</text>';
  }
  // 栅瓣竖线（签名 θ：GL φ 与 cut 平面同侧→+θ，反侧→−θ）
  const cutPhi=(P.cut&&P.cut.phi_deg)||0;
  let glMarks=0;
  (P.grating_lobes||[]).forEach(gl=>{
    let dphi=((gl.phi_deg-cutPhi)%360+360)%360;
    let st=null;
    if(dphi<=5) st=gl.theta_deg;
    else if(Math.abs(dphi-180)<=5) st=-gl.theta_deg;
    if(st===null||st<tMin||st>tMax) return;
    glMarks++;
    s+='<line x1="'+X(st)+'" y1="'+PT+'" x2="'+X(st)+'" y2="'+(PH-PB)+'" stroke="#d6452d" stroke-width="1.4" stroke-dasharray="6 3"/>'+
       '<text x="'+X(st)+'" y="'+(PT+11)+'" text-anchor="middle" font-size="9.5" fill="#d6452d" font-weight="700">栅瓣</text>';
  });
  // 主瓣中心竖线
  const ctr2=(P.cut&&P.cut.center)||0;
  if(!wide&&ctr2>tMin&&ctr2<tMax)
    s+='<line x1="'+X(ctr2)+'" y1="'+PT+'" x2="'+X(ctr2)+'" y2="'+(PH-PB)+'" stroke="#0b5cad" stroke-width="1" opacity=".45"/>';
  let pts=[];
  for(let i=0;i<th.length;i++) pts.push(X(th[i]).toFixed(1)+","+Y(gv[i]).toFixed(1));
  s+='<polyline points="'+pts.join(" ")+'" fill="none" stroke="#0b5cad" stroke-width="1.8"/>';
  s+='<text x="'+(PW/2)+'" y="'+(PH-6)+'" text-anchor="middle" font-size="11" fill="#5f7183">'+
     (wide?"签名 θ (°) —— 负 θ = φ+180° 反侧（GRASP 惯例），栅瓣常出现在主瓣远侧":"θ (°) —— 主瓣中心 ±15° cut（φ="+n(cutPhi,0)+"° 剖面）")+'</text>';
  s+='<text x="12" y="'+(PT-4)+'" font-size="10.5" fill="#5f7183">G (dBr)</text></svg>';
  return s;
}
function patternPanelHTML(P){
  const isArr=P.antenna_type==="phased_array";
  const scanOn=_patState.scanned;
  const deflScan=_patState.scanTheta!==null?_patState.scanTheta:Math.max(toF(CFG["θ_scan"],10),5);
  let ctrl='<div class="chips" style="flex-wrap:wrap;gap:8px">'+
    '<button class="btn sm'+(scanOn?"":" solid")+'" id="patBoreBtn">boresight（不扫描）</button>'+
    '<button class="btn sm'+(scanOn?" solid":"")+'" id="patScanBtn">扫描到</button>'+
    '<input id="patScanInp" type="number" min="0" max="60" step="1" value="'+n(deflScan,0)+'" style="width:64px" title="扫描角 θ₀ (°)">°'+
    (isArr?('<span class="glabel">阵元间距 d/λ <input id="patDlamInp" type="number" min="0.3" max="1.2" step="0.05" value="'+n(_patState.dlam,2)+'" style="width:64px"></span>'):"")+
    '<span style="flex:1"></span>'+
    '<button class="btn sm patview'+(_patState.view==="cut"?" on":"")+'" data-v="cut">cut ±15°</button>'+
    '<button class="btn sm patview'+(_patState.view==="wide"?" on":"")+'" data-v="wide">宽 cut ±90°</button>'+
    '<button class="btn sm patview'+(_patState.view==="grid"?" on":"")+'" data-v="grid">grid θ×φ</button>'+
    '<button class="btn sm" id="patExportGrd">⬇ 导出 GRASP .grd</button>'+
  '</div>';
  const glN=(P.grating_lobes||[]).length, glC=(P.grating_in_cut||[]).length;
  const glTag=(!isArr)?'<span class="tag ok">连续口径 · 无栅瓣</span>':
    (glN===0?'<span class="tag ok">无栅瓣（d='+n(P.d_lam,2)+'λ 扫描 '+n(P.scan_theta_deg,0)+'° 安全）</span>':
     (glC>0?'<span class="tag bad">栅瓣 ×'+glN+'，其中 '+glC+' 个进入 ±15° cut 窗！</span>':
      '<span class="tag warn">栅瓣 ×'+glN+'（均在 ±15° cut 窗外）</span>'));
  let kpis='<div class="kpis">'+
    kpi("峰值增益 G0",P.peak_gain_dbi,"dBi")+
    kpi("θ3dB",P.beamwidth_3db_deg,"°")+
    kpi("首旁瓣",P.first_sidelobe_dbr,"dBr")+
    kpi("扫描角 (θ₀,φ₀)","("+n(P.scan_theta_deg,1)+", "+n(P.scan_phi_deg,0)+")","°")+
    (isArr?kpi("阵规模",P.nx+"×"+P.ny,"= "+P.n_el+" 元 · d="+n(P.d_lam,2)+"λ（"+n(P.d_mm,1)+"mm）"):
           kpi("口径 D",P.D_m,"m · η="+n(P.eta*100,0)+"%"))+
  '</div>';
  let glTab="";
  if(isArr&&glN>0){
    glTab='<h4>栅瓣清单（解析判据 sinθ_gl·cosφ = sinθ₀ + nₓλ/d）</h4>'+
      '<table><tr><th>阶</th><th class="num">θ_gl (°)</th><th class="num">φ_gl (°)</th><th>在 ±15° cut 内？</th></tr>'+
      (P.grating_lobes||[]).map(gl=>{
        const inCut=(P.grating_in_cut||[]).some(x=>Math.abs(x.theta_deg-gl.theta_deg)<0.01);
        return '<tr><td>'+h(String(gl.order))+'</td><td class="num">'+n(gl.theta_deg,2)+'</td><td class="num">'+n(gl.phi_deg,1)+'</td><td>'+tag(!inCut,inCut?"是 ⚠":"否")+'</td></tr>';
      }).join("")+'</table>';
  }
  const grd=_patState.grd?('<div class="okbox small">✅ GRASP .grd 已导出：<code>'+h(_patState.grd.path)+
    '</code>（'+_patState.grd.n_theta+'×'+_patState.grd.n_phi+' θ×φ 球面网格）——可带入 GRASP/SATSOFT 复核。'+
    ' <button class="btn sm" id="patOpenGrd">打开文件</button> <button class="btn sm" id="patRevealGrd">所在文件夹</button></div>'):
    '<div class="note small">导出 .grd（GRASP ASCII 球面网格：θ_start θ_step n_θ φ_start n_φ + E_co/E_x 四列）后可带入 SATSOFT/GRASP 做覆盖复核；覆盖区内置计算见「② 方案总览」EIRP 覆盖面板。</div>';
  const secCut='<div id="patSecCut" style="'+(_patState.view==="cut"?"":"display:none")+'"><div class="plotbox"><h4>主 cut（中心 ±15° · φ='+n((P.cut&&P.cut.phi_deg)||0,0)+'° 剖面 · 次级方向图含次瓣）</h4>'+patCutSvg(P,false)+'</div></div>';
  const secWide='<div id="patSecWide" style="'+(_patState.view==="wide"?"":"display:none")+'"><div class="plotbox"><h4>宽 cut（签名 θ −90°~+90° · 检查栅瓣/远区次瓣）</h4>'+patCutSvg(P,true)+'</div></div>';
  const secGrid='<div id="patSecGrid" style="'+(_patState.view==="grid"?"":"display:none")+'"><div class="plotbox"><h4>grid（θ×φ 全空域 · dBr · 白十字=栅瓣 · 黄十字=波束指向）</h4>'+patGridSvg(P)+'</div></div>';
  return ctrl+'<div class="chips">'+glTag+'<span class="tag info">'+
    (isArr?("相控阵 "+P.n_el+" 元 · element×AF 可分离积"):("反射面 D="+n(P.D_m,2)+"m · 口径 Hankel 变换"))+
    ' · '+n(P.freq_ghz,2)+' GHz</span></div>'+kpis+secCut+secWide+secGrid+glTab+grd+
    '<div class="note small"><b>计算说明：</b>'+h(P.note||"")+'</div>';
}

/* ---------- ⑤ 转发器链路预算 ---------- */
function renderTrp(){
  const T=RES.transponder, p=RES.params, m=RES.mode_info;
  let html='<div class="panel"><h2>转发器方案（'+h(T.mode_cn)+'）</h2>'+
  '<div class="note"><b>体制链路：</b><code>'+h(T.chain)+'</code><br><b>噪声特性：</b>'+h(T.noise)+
  '<br><b>柔性：</b>'+h(T.flex)+'<br><b>星上时延：</b>'+n(T.delay_ms,3)+' ms ｜ <b>再生增益：</b>'+n(T.regen_bonus,1)+' dB</div>';
  html+='<div class="kpis">'+
    kpi("波束数 N_beam",T.N_beam,"")+kpi("单波束带宽",T.B_beam,"MHz")+
    kpi("转发器总带宽",T.B_trp,"MHz")+kpi("信道数 N_ch",T.N_ch,"")+
    kpi("子带粒度 B_sub",T.B_sub,"MHz")+kpi("交换容量 C_sw",T.C_sw,"Gbps")+
    kpi("转发通道数",T.n_trp_chan,"（N_beam/k 复用）")+kpi("单波束功放",T.P_out_w,"W/波束")+
  '</div>';
  html+='<h3>功放（HPA）方案 —— EIRP 需求反推 + 货架就近选型</h3>'+
    '<table><tr><th>项</th><th>内容</th></tr>'+
    '<tr><td>反推来源</td><td>'+h(T.P_out_source||"")+'</td></tr>'+
    '<tr><td>体制/架构</td><td>'+(T.distributed?"分布式（相控阵 T/R 阵列集成）":"集中式（"+h(T.amp)+" ×"+T.n_hpa+" 台，环备份 1/8）")+'</td></tr>'+
    '<tr><td>选定 HPA</td><td><b>'+h(T.hpa?T.hpa.id+" · "+T.hpa.cn:"—")+'</b>'+(T.hpa&&T.hpa.specs?"（货架 level "+T.hpa.level+"）":"")+'</td></tr>'+
    '<tr><td>直流功耗</td><td>'+n(T.p_hpa_dc,0)+' W'+(T.distributed&&T.p_hpa_dc===0?"（已计入货架天线产品功耗，不重复计）":"")+'</td></tr>'+
    '<tr><td>选型说明</td><td>'+h(T.hpa_note||"")+'</td></tr></table>';

  // 频率规划
  const der=RES.params._derived;
  html+='<h3>频率规划校核（c-12/c-13/c-14）</h3><table><tr><th>项</th><th class="num">值</th><th>判据</th></tr>'+
    '<tr><td>N_beam × B_beam</td><td class="num">'+n(T.N_beam*T.B_beam,0)+' MHz</td><td rowspan="2">≤ B_total × k = '+n(toF(p.B_total,500)*toF(p.k_reuse,4),0)+' MHz → '+tag(der.freq_ok,"闭合/超限")+'</td></tr>'+
    '<tr><td>B_total（'+h(RES.cfg.band)+' 指配）× 复用色数 k</td><td class="num">'+n(p.B_total,0)+' × '+n(p.k_reuse,0)+'</td></tr>'+
    '<tr><td>转发器通道带宽（36MHz 栅格取整）</td><td class="num">'+n(T.B_trp,0)+' MHz</td><td>B_trp = ceil(N_beam×B_beam/k/36)×36</td></tr>'+
    '<tr><td>DTP 信道化</td><td class="num">'+T.N_ch+' 信道 × '+n(T.B_sub,0)+' MHz</td><td>交换容量 C_sw ≥ N_beam×B_beam×2.5/1000 = '+n(T.N_beam*T.B_beam*2.5/1000,1)+' Gbps → 取 '+n(T.C_sw,0)+' Gbps</td></tr>'+
  '</table>';

  // 体制对比说明
  html+='<h3>本方案体制特点（'+h(m.cn||"")+'）</h3><div class="grid g2">'+
    '<div><b>优点</b><ul style="margin:4px 0 0 18px;line-height:1.8">'+(m.pros||[]).map(x=>'<li>'+h(x)+'</li>').join("")+'</ul></div>'+
    '<div><b>代价</b><ul style="margin:4px 0 0 18px;line-height:1.8">'+(m.cons||[]).map(x=>'<li>'+h(x)+'</li>').join("")+'</ul></div>'+
  '</div><div class="note small"><b>适用场景：</b>'+h((m.apps||[]).join("；"))+'<br><b>功放偏好：</b>'+h(m.hpa_pref||"")+'</div></div>';

  // 功耗/质量分解
  const t=RES.totals;
  html+='<div class="panel"><h2>转发器分系统功耗/质量分解</h2><div class="kpis">'+
    kpi("天线分系统质量",t.sub_m.m_ant,"kg")+kpi("转发器质量",t.sub_m.m_trp,"kg")+
    kpi("激光终端质量",t.sub_m.m_laser,"kg")+kpi("星务质量",t.sub_m.m_ipu,"kg")+
    kpi("天线功耗",t.sub_p.P_ant,"W")+kpi("转发器功耗",t.sub_p.P_trp,"W")+
    kpi("激光功耗",t.sub_p.P_laser,"W")+kpi("星务功耗",t.sub_p.P_ipu,"W")+
  '</div><div class="note small">合计（含 20% 系统裕度）：质量 '+n(t.m_pay,1)+' kg ｜ 功耗 '+n(t.p_pay,0)+' W。'+
  '功放直流功耗 P_dc = P_out/η（c-16），结温 T_j ≤125℃ 决定寿命；转发器功耗占比 '+
  n(100*t.sub_p.P_trp/Math.max(t.p_est,1),0)+'%。</div></div>';
  el("trp").innerHTML=html;
}

/* ---------- ⑥ 信息流设计（层次化：三类信息流 × 三段空间层次 × 功能层链） ---------- */
function flowStagesHTML(f){
  const st=f.stages||[];
  if(!st.length) return "";
  // 分层节点链：L1 接入 → L2 天线 → …（同层节点合并显示）
  let out='<div class="fchain">';
  st.forEach((s,i)=>{
    if(i>0) out+='<span class="farrow">→</span>';
    out+='<span class="fstage" title="'+h(s.layer+" "+s.layer_cn)+'"><i>'+h(s.layer)+'</i>'+h(s.node)+'</span>';
  });
  return out+'</div>';
}
function flowCards(list,FL){
  const tierOf=(FL&&FL.tier_of)||{}, lvOf={};
  ((FL&&FL.levels)||[]).forEach(l=>lvOf[l.key]=l);
  return list.map(f=>{
    const tc=tierOf[f.tier]||{};
    return '<div class="flowcard" style="border-left:4px solid '+h(tc.color||"#93a3b4")+'">'+
    '<div class="fname">'+h(f.name)+
      '<span class="tag mut" style="margin-left:8px">'+h(tc.cn||"")+'</span>'+
      '<span class="tag mut">'+h((lvOf[f.level]||{}).cn||"")+'</span></div>'+
    flowStagesHTML(f)+
    '<div class="fpath">'+h(f.path)+'</div>'+
    '<div class="frow"><span>介质：<b>'+h(f.medium)+'</b></span><span>速率：<b>'+h(f.rate)+'</b></span>'+
    '<span>时延：<b>'+h(f.delay)+'</b></span></div>'+
    '<div class="frow"><span>关键点：<b>'+h(f.key)+'</b></span></div></div>';
  }).join("");
}
function renderFlow(){
  const F=RES.flows, dn=F.delay_note;
  const all=F.all||[].concat(F.sg||[],F.si||[],F.sn||[]);
  const tiers=F.tiers||[], levels=F.levels||[];
  let html='<div class="panel"><h2>信息流设计（层次化：三类信息流 × 三段空间层次）</h2>'+
  '<div class="note">单跳时延模型：传播 '+n(dn.prop_ms,3)+' ms（斜距/光速）+ 星上处理 '+n(dn.onboard_ms,3)+' ms（'+h(dn.mode)+' 体制）= <b>'+n(dn.total_ms,3)+' ms</b>；'+
  '轨道 '+h(dn.orbit)+'。再生体制星上处理含解调/译码/路由（≈40ms）；DTP 数字信道化 ≈3ms；透明体制仅群时延 ≈0.2μs。</div>'+
  // 层次矩阵总览：行=信息流类别（业务/数据/控制/能量），列=空间段（星地/星间/星内）
  '<h3>层次矩阵（类别 × 空间段 → 流条数）</h3><table><tr><th>信息流类别</th>'+
    levels.map(l=>'<th>'+h(l.cn)+'<br><span class="muted small">'+h(l.desc)+'</span></th>').join("")+'<th>小计</th></tr>'+
    tiers.map(t=>{
      const cells=levels.map(l=>{
        const list=((F.matrix||{})[t.key]||{})[l.key]||[];
        return '<td style="text-align:center">'+(list.length?
          '<b style="color:'+h(t.color)+'">'+list.length+'</b><br><span class="small muted">'+list.map(h).join("、").slice(0,60)+'</span>':'<span class="muted">—</span>')+'</td>';
      }).join("");
      const tot=levels.reduce((a,l)=>a+((((F.matrix||{})[t.key]||{})[l.key]||[]).length),0);
      return '<tr><td><b style="color:'+h(t.color)+'">■</b> '+h(t.cn)+'<br><span class="small muted">'+h(t.desc)+'</span></td>'+cells+
        '<td style="text-align:center"><b>'+tot+'</b></td></tr>';
    }).join("")+
  '</table>'+
  '<div class="note small">分层依据（真实载荷架构）：<b>业务流</b>（射频承载的用户/馈电业务，链路预算主体）、'+
  '<b>载荷数据流</b>（星内 FC-AE 数字域，可缓存非实时）、<b>控制流</b>（TT&C/在轨重构/FDIR，1553B/CAN，kbps 级高可靠）、'+
  '<b>能量流</b>（EPC 母线功率分配，为前三类供能）。每条流按功能层展开：'+
  (F.stages_def||[]).map(s=>'<b>'+h(s[0])+'</b> '+h(s[1])).join(" → ")+'。</div>';
  // 按三类信息流分组渲染（层次化结构），每类内按 星地→星间→星内 排序
  const order={sg:0,si:1,sn:2};
  tiers.forEach(t=>{
    const list=all.filter(f=>f.tier===t.key).sort((a,b)=>(order[a.level]||9)-(order[b.level]||9));
    if(!list.length) return;
    html+='<h3 style="color:'+h(t.color)+'">■ '+h(t.cn)+'（'+list.length+' 条 · '+h(t.desc)+'）</h3>'+flowCards(list,F);
  });

  // 激光链路细节
  const li=RES.res.laser_isl;
  if(li){
    html+='<h3>激光星间链路预算（c-18/c-19）</h3><table><tr><th>项</th><th class="num">值</th></tr>'+
    '<tr><td>发射功率 P_tx / EDFA 增益</td><td class="num">'+n(li.P_tx_w,2)+' W / '+n(li.G_edfa_eff,1)+' dB</td></tr>'+
    '<tr><td>光学天线增益 G_opt（Φ'+n(li.D_mm,0)+'mm @'+n(li.lam_nm,0)+'nm）</td><td class="num">'+n(li.G_opt,1)+' dBi</td></tr>'+
    '<tr><td>光路损耗 L_fs（d='+n(li.d_km,0)+'km）</td><td class="num">'+n(li.L_fs_opt,1)+' dB</td></tr>'+
    '<tr><td>指向损耗 L_point（σ_jit='+n(li.sig_jit,1)+'μrad / θ_div='+n(li.th_div,0)+'μrad）</td><td class="num">'+n(li.L_point,2)+' dB</td></tr>'+
    '<tr><td>接收功率 P_rx</td><td class="num">'+n(li.P_rx_dbm,1)+' dBm</td></tr>'+
    '<tr><td>灵敏度门限 P_req（'+n(li.R,1)+'Gbps DPSK）</td><td class="num">'+n(li.P_req_dbm,1)+' dBm</td></tr>'+
    '<tr><td><b>链路余量 M</b></td><td class="num"><b>'+n(li.M_db,2)+' dB</b></td></tr></table>';
  }
  // 15 条链路信息流索引
  const flows=RES.res.flows||{};
  const ids=Object.keys(flows);
  html+='<h3>全链路信息流索引（'+ids.length+' 条本体链路 · 逐级电平/噪声见知识图谱计算器）</h3><div class="chips">'+
    ids.map(id=>{const f=flows[id];const nm=(f.meta&&f.meta.name)||id;
      return '<span class="tag info" title="'+h(id)+'">'+h(nm)+'</span>';}).join("")+'</div></div>';
  el("flow").innerHTML=html;
}

/* ---------- ⑦ 单机清单与选型 ---------- */
function renderEq(){
  const rows=RES.equipment, t=RES.totals, R=RES;
  const lvTag=l=>'<span class="tag '+(l>=4?"ok":(l===3?"info":(l===2?"warn":"bad")))+'">'+h(META.shelf_levels[String(l)]||("L"+l))+'</span>';
  let html='<div class="panel"><h2>货架单机清单（步骤 4：货架优先，三线编号）</h2>'+
  '<div class="kpis">'+kpi("单机种类",t.n_rows,"种")+kpi("单机总数",t.n_items,"件")+
    kpi("载荷质量",t.m_pay,"kg（含20%裕度）")+kpi("载荷功耗",t.p_pay,"W（含20%裕度）")+
    kpi("货架水平 H_scheme",t.H_scheme,"(c-21) 4=货架飞行继承")+kpi("定制缺口 N_gap",t.n_custom,"项")+'</div>'+
  '<table><tr><th>#</th><th>编号</th><th>单机名称</th><th>类别</th><th>频段</th><th class="num">数量</th><th class="num">质量 kg</th><th class="num">功耗 W</th><th>货架水平</th><th>选型依据（链路预算反推）</th></tr>'+
  rows.map((r,i)=>'<tr><td class="num">'+(i+1)+'</td><td><code>'+h(r.id)+'</code></td><td>'+h(r.cn)+'</td><td>'+h(r.cat)+'</td><td>'+h(r.band)+'</td>'+
    '<td class="num">'+r.qty+'</td><td class="num">'+n(r.mass,2)+'</td><td class="num">'+n(r.power,1)+'</td><td>'+lvTag(r.level)+'</td>'+
    '<td class="small">'+h(r.why||"")+(r.note?"<br><span class='muted'>"+h(r.note)+"</span>":"")+'</td></tr>').join("")+
  '<tr><th colspan="6">合计（×1.2 系统裕度 → '+n(t.m_pay,1)+' kg / '+n(t.p_pay,0)+' W）</th><th class="num">'+n(t.m_est,1)+'</th><th class="num">'+n(t.p_est,0)+'</th><th colspan="2"></th></tr>'+
  '</table>';
  // 天线候选
  html+='<h3>天线五维选型候选（频段硬过滤：'+h(R.cfg.band)+'）</h3><table><tr><th>评分</th><th>编号</th><th>名称</th><th class="num">EIRP①</th><th class="num">G/T②</th><th class="num">质量③</th><th class="num">功耗④</th><th class="num">模式⑤</th><th>五维分析</th></tr>'+
  R.ant_cands.slice(0,8).map(c=>{
    const rec=R.ant_rec&&c[1].id===R.ant_rec[1].id;
    return '<tr'+(rec?' class="compare-cur"':'')+'><td class="num"><b>'+n(c[0],2)+'</b></td><td><code>'+h(c[1].id)+'</code></td><td>'+h(c[1].cn)+(rec?' <span class="tag ok">推荐</span>':'')+'</td>'+
    '<td class="num">'+n(c[3].EIRP,1)+'</td><td class="num">'+n(c[3].GT,1)+'</td><td class="num">'+n(c[3].mass,1)+'</td><td class="num">'+n(c[3].power,1)+'</td><td class="num">'+n(c[3].mode,1)+'</td>'+
    '<td class="small">'+c[2].map(h).join("<br>")+'</td></tr>';
  }).join("")+'</table>';
  // 平台/火箭
  const plat=R.platform?R.platform[1]:null;
  html+='<h3>平台选型（三级闭环第二级）</h3><table><tr><th>评分</th><th>平台</th><th class="num">承载 kg</th><th class="num">供电 W</th><th class="num">整星 kg</th><th class="num">寿命 yr</th><th>继承</th><th>校核</th></tr>'+
  R.platforms.slice(0,6).map(c=>'<tr'+(plat&&c[1].id===plat.id?' class="compare-cur"':'')+'><td class="num">'+n(c[0],2)+'</td><td>'+h(c[1].cn)+(plat&&c[1].id===plat.id?' <span class="tag ok">推荐</span>':'')+'</td>'+
    '<td class="num">'+c[1].m_pay+'</td><td class="num">'+c[1].p_pay+'</td><td class="num">'+c[1].m_sat+'</td><td class="num">'+c[1].life+'</td><td class="small">'+h(c[1].heritage)+'</td><td class="small">'+h(c[3])+'</td></tr>').join("")+'</table>';
  const lau=R.launcher?R.launcher[1]:null;
  html+='<h3>运载选型（三级闭环第三级）</h3><table><tr><th>评分</th><th>火箭</th><th class="num">LEO t</th><th class="num">GTO t</th><th>整流罩</th><th>成本</th><th>校核</th></tr>'+
  R.launchers.slice(0,6).map(c=>'<tr'+(lau&&c[1].id===lau.id?' class="compare-cur"':'')+'><td class="num">'+n(c[0],2)+'</td><td>'+h(c[1].cn)+(lau&&c[1].id===lau.id?' <span class="tag ok">推荐</span>':'')+'</td>'+
    '<td class="num">'+n(c[1].leo_t/1000,2)+'</td><td class="num">'+(c[1].gto_t?n(c[1].gto_t/1000,2):"—")+'</td><td>'+h(c[1].fairing)+'</td><td>'+h(c[1].cost)+'</td><td class="small">'+h(c[3])+'</td></tr>').join("")+'</table></div>';
  el("eq").innerHTML=html;
}

/* ---------- ⑧ 方案对比 ---------- */
function renderCmp(){
  const C=RES.compare;
  if(!C||!C.length){ el("cmp").innerHTML='<div class="panel"><h2>方案对比</h2><div class="warnbox">本次为快速重算（未含方案对比）。请在「方案配置」页点击「开始设计」生成体制替代 + 天线替代方案的六维评分对比。</div></div>'; return; }
  const dims=Object.keys(RES.score.weights);
  const rows=C.filter(c=>!c.error);
  const bestScore=Math.max.apply(null,rows.map(r=>r.score?r.score.total:-1));
  let html='<div class="panel"><h2>方案对比（当前 + 体制替代 + 天线替代 · 六维评分）</h2>'+
  '<table><tr><th>方案</th><th>体制</th><th>天线</th><th class="num">总分</th><th class="num">性能</th><th class="num">质量</th><th class="num">功耗</th><th class="num">成本</th><th class="num">灵活</th><th class="num">风险</th>'+
  '<th class="num">EIRP dBW</th><th class="num">G/T dB/K</th><th class="num">M上/M下 dB</th><th class="num">C_sys Gbps</th><th class="num">质量 kg</th><th class="num">功耗 W</th><th class="num">单机 种/件/定制</th><th>平台/运载</th><th>判据</th></tr>'+
  C.map(c=>{
    if(c.error) return '<tr><td>'+h(c.label)+'</td><td colspan="18" class="badbox">'+h(c.error)+'</td></tr>';
    const cur=c.label==="当前方案";
    const s=c.score;
    return '<tr'+(cur?' class="compare-cur"':'')+'><td><b>'+h(c.label)+'</b><br><span class="small muted">'+h(c.note||"")+'</span></td>'+
      '<td>'+h(META.modes[c.mode]?META.modes[c.mode].cn:c.mode)+'</td>'+
      '<td>'+h(c.antenna_cn||c.antenna||"")+'</td>'+
      '<td class="num"><b>'+n(s.total,2)+'</b>'+(s.total>=bestScore-1e-9?' <span class="tag ok">最优</span>':'')+'</td>'+
      dims.map(k=>'<td class="num">'+n(s.dims[k],1)+'</td>').join("")+
      '<td class="num">'+n(c.EIRP,1)+'</td><td class="num">'+n(c.GT,1)+'</td><td class="num">'+n(c.M_up,1)+'/'+n(c.M_dn,1)+'</td>'+
      '<td class="num">'+n(c.C_sys,2)+'</td><td class="num">'+n(c.m,0)+'</td><td class="num">'+n(c.pw,0)+'</td>'+
      '<td class="num">'+c.n_rows+'/'+c.n_items+'/'+c.n_custom+'</td>'+
      '<td class="small">'+h(c.platform)+'<br>'+h(c.launcher)+'</td>'+
      '<td>'+tag(c.fail.length===0,c.judge)+(c.fail.length?'<br><span class="small bad">'+c.fail.join(",")+'</span>':'')+'</td></tr>';
  }).join("")+'</table>';
  // 评分条对比
  html+='<h3>总分对比</h3>'+rows.map(r=>'<div class="scorebar"><div class="lb" style="width:220px">'+h(r.label)+'</div>'+
    '<div class="bar"><div class="fill'+(r.label==="当前方案"?" cur":"")+'" style="width:'+(r.score.total*10)+'%"></div></div><div class="val">'+n(r.score.total,2)+'</div></div>').join("");
  // 六维雷达（简化为条形对比）
  html+='<h3>六维分项对比（当前方案 vs 最优替代）</h3>';
  const alt=rows.filter(r=>r.label!=="当前方案").sort((a,b)=>b.score.total-a.score.total)[0];
  if(alt){
    html+='<table><tr><th>维度（权重）</th><th class="num">当前方案</th><th class="num">'+h(alt.label)+'</th><th>差异</th></tr>'+
    dims.map(k=>{const a=RES.score.dims[k],b=alt.score.dims[k];
      return '<tr><td>'+h(RES.score.cn[k])+'（'+(RES.score.weights[k]*100)+'%）</td><td class="num">'+n(a,1)+'</td><td class="num">'+n(b,1)+'</td>'+
      '<td>'+(b>a+0.05?'<span class="tag bad">−'+n(b-a,1)+'</span>':(a>b+0.05?'<span class="tag ok">+'+n(a-b,1)+'</span>':'<span class="tag mut">≈</span>'))+'</td></tr>';}).join("")+'</table>';
    html+='<div class="note"><b>对比结论：</b>'+h(RES.score.total>=alt.score.total?
      "当前方案总分领先，维持当前体制/天线组合。":
      "替代方案「"+alt.label+"」总分更高（"+n(alt.score.total,2)+" vs "+n(RES.score.total,2)+"），建议评估切换；切换影响："+ (alt.note||""))+'</div>';
  }
  html+='</div>';
  el("cmp").innerHTML=html;
}

/* ---------- ⑨ 原理介绍 ---------- */
function renderPri(){
  const P=RES.principles||[];
  let html='<div class="panel"><h2>载荷功能/单机原理介绍（当前方案涉及的 '+P.length+' 个子系统）</h2>';
  P.forEach((p,i)=>{
    html+='<div class="principle"><div class="ph" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">'+
      '<span>'+h(p.cn)+'</span><span class="muted small">点击折叠/展开</span></div>'+
      '<div class="pb">'+h(p.principle)+'</div></div>';
  });
  // 天线类型/子体制库
  html+='<h3>天线类型库（三类对比）</h3><table><tr><th>类型</th><th>增益公式</th><th>扫描/波束</th><th>适用频段</th><th>成本系数</th><th>优点</th><th>代价</th></tr>'+
  META.ant_type_keys.map(k=>{const a=META.ant_types[k];
    return '<tr><td><b>'+h(a.cn)+'</b></td><td class="small">'+h(a.gain_formula)+'</td><td class="small">'+h(a.scan)+'<br>'+h(a.beam)+'</td><td>'+h(a.bands.join("/"))+'</td><td class="num">×'+n(a.cost_mult,2)+'</td>'+
    '<td class="small">'+(a.pros||[]).map(h).join("<br>")+'</td><td class="small">'+(a.cons||[]).map(h).join("<br>")+'</td></tr>';}).join("")+'</table>';
  html+='<h3>相控阵子体制库（五选一）</h3><table><tr><th>子体制</th><th>原理</th><th class="num">η</th><th class="num">P_tr W/元</th><th class="num">扫描上限</th><th>成本</th><th>适用</th></tr>'+
  META.array_subtype_keys.map(k=>{const a=META.array_subtypes[k];
    return '<tr><td><b>'+h(a.cn)+'</b></td><td class="small">'+h(a.principle)+'</td><td class="num">'+n(a.eta,2)+'</td><td class="num">'+n(a.p_tr_w,1)+'</td><td class="num">±'+a.scan_max+'°</td><td class="num">×'+n(a.cost_mult,2)+'</td><td class="small">'+h((a.apps||[]).join("；"))+'</td></tr>';}).join("")+'</table>';
  html+='<h3>转发体制库（三选一）</h3><table><tr><th>体制</th><th>链路</th><th>噪声</th><th>柔性</th><th class="num">成本</th><th class="num">质量</th><th class="num">功耗</th><th>时延</th></tr>'+
  META.mode_keys.map(k=>{const m=META.modes[k];
    return '<tr><td><b>'+h(m.cn)+'</b></td><td class="small"><code>'+h(m.chain)+'</code></td><td class="small">'+h(m.noise)+'</td><td class="small">'+h(m.flex)+'</td>'+
    '<td class="num">×'+n(m.cost_mult,2)+'</td><td class="num">×'+n(m.mass_mult,2)+'</td><td class="num">×'+n(m.power_mult,2)+'</td><td class="small">'+h(m.delay)+'</td></tr>';}).join("")+'</table></div>';
  el("pri").innerHTML=html;
}

/* ---------- ⑩ 约束校验与回环 ---------- */
function renderCons(){
  const cs=RES.res.constraints||[], loop=RES.res.loop||{}, s=RES.res.summary;
  const sevCls=c=>c.ok?"ok":(c.sev==="warning"?"warn":"bad");
  let html='<div class="panel"><h2>25 条工程约束校验（c-1 ~ c-25）</h2>'+
  '<div class="chips"><span class="tag ok">通过 '+s.pass_count+'</span><span class="tag mut">信息/校验共 '+s.total_count+' 项</span>'+
  '<span class="tag '+(s.judge_pass===s.judge_total?"ok":"bad")+'">硬判据 '+s.judge_pass+'/'+s.judge_total+'</span>'+
  (s.fail.length?'<span class="tag bad">未闭合 '+s.fail.join(", ")+'</span>':'<span class="tag ok">全部闭合</span>')+
  (s.warn&&s.warn.length?'<span class="tag warn">警告 '+s.warn.join(", ")+'</span>':'')+'</div>';
  html+='<table><tr><th>编号</th><th>公式/判据</th><th>逐项数值</th><th>结论</th><th>状态</th></tr>'+
  cs.map(c=>'<tr><td><b>'+h(c.id)+'</b>'+(c.tag?'<br><span class="tag mut">'+h(c.tag)+'</span>':'')+'</td>'+
    '<td class="small">'+h(c.formula||"")+'</td>'+
    '<td class="small">'+((c.items||[]).map(it=>h(it[0])+" = <b>"+n(it[1],typeof it[1]==="number"?2:0)+"</b> "+h(it[2]||"")).join(" ｜ "))+'</td>'+
    '<td class="small">'+h(c.note||"")+'</td>'+
    '<td><span class="tag '+sevCls(c)+'">'+(c.ok?"通过":(c.sev==="warning"?"警告":"未过"))+'</span></td></tr>').join("")+'</table>';
  // 回环
  html+='<h3>回环建议（外环：链路不闭合时的架构调整）</h3>';
  if(!loop.need) html+='<div class="okbox">'+h(loop.note||"全部链路余量达标，无需回环")+'</div>';
  else{
    html+='<div class="warnbox">'+h(loop.note)+'（最差 '+n(loop.worst_M,2)+' dB vs 目标 '+n(loop.target,1)+' dB，缺口 '+n(loop.deficit,2)+' dB）</div>'+
    '<table><tr><th>调整步骤</th><th>动作</th><th class="num">增益 dB</th><th>代价</th><th>是否足够</th></tr>'+
    (loop.advice||[]).map(a=>'<tr><td>'+h(a.step)+'</td><td>'+h(a.action)+'</td><td class="num">'+(a.gain_db===null||a.gain_db===undefined?"—":n(a.gain_db,2))+'</td><td class="small">'+h(a.cost)+'</td>'+
    '<td>'+(a.enough?'<span class="tag ok">足够</span>':'<span class="tag mut">不足/需组合</span>')+'</td></tr>').join("")+'</table>';
  }
  html+='</div>';
  el("cons").innerHTML=html;
}

/* ---------- ⑬ 稳健性分析（design_engine._robustness_analyses：星蚀/位保/MC/XPD/可靠性/邻星） ---------- */
function robTag(ok,txtGood,txtBad){ return '<span class="tag '+(ok?"ok":"bad")+'">'+h(ok?(txtGood||"满足"):(txtBad||"不满足"))+'</span>'; }
function robSection(title,inner,note){
  return '<h3>'+h(title)+'</h3>'+inner+(note?'<div class="note small">'+note+'</div>':'');
}
/* MC 直方图（M 分布 + 目标余量竖线） */
function robMcHistSvg(mc){
  const hs=mc.hist||{}; const cts=hs.counts||[];
  if(!cts.length) return "";
  const W=560,H=210,PL=44,PR=14,PT=16,PB=34;
  const cmax=Math.max.apply(null,cts)||1;
  const lo=hs.lo,hi=hs.hi,step=hs.step||((hi-lo)/Math.max(cts.length,1));
  const xOf=v=>PL+(v-lo)/Math.max(hi-lo,1e-9)*(W-PL-PR);
  const yOf=c=>PT+(1-c/cmax)*(H-PT-PB);
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fbfdff" stroke="#d3e0ee" rx="8"/>';
  for(let i=0;i<=4;i++){ const cv=cmax*i/4, yy=yOf(cv);
    s+='<line x1="'+PL+'" y1="'+yy+'" x2="'+(W-PR)+'" y2="'+yy+'" stroke="#e5eef7" stroke-width=".7"/>'+
       '<text x="'+(PL-5)+'" y="'+(yy+4)+'" font-size="10" fill="#7186a0" text-anchor="end">'+Math.round(cv)+'</text>'; }
  cts.forEach((c,i)=>{ const x0=xOf(lo+i*step),x1=xOf(lo+(i+1)*step);
    s+='<rect x="'+x0.toFixed(1)+'" y="'+yOf(c).toFixed(1)+'" width="'+Math.max(x1-x0-1,1).toFixed(1)+'" height="'+(yOf(0)-yOf(c)).toFixed(1)+'" fill="#4d8fd1" opacity=".8"/>'; });
  const tm=toF(mc.m_target_db,3);
  if(tm>=lo&&tm<=hi){ const tx=xOf(tm);
    s+='<line x1="'+tx+'" y1="'+PT+'" x2="'+tx+'" y2="'+(H-PB)+'" stroke="#d43a3a" stroke-width="1.6" stroke-dasharray="5,3"/>'+
       '<text x="'+(tx+4)+'" y="'+(PT+11)+'" font-size="10.5" fill="#d43a3a">目标 M='+n(tm,1)+'dB</text>'; }
  for(let i=0;i<=4;i++){ const vv=lo+(hi-lo)*i/4;
    s+='<text x="'+xOf(vv).toFixed(1)+'" y="'+(H-PB+15)+'" font-size="10" fill="#7186a0" text-anchor="middle">'+n(vv,1)+'</text>'; }
  s+='<text x="'+(W/2)+'" y="'+(H-4)+'" font-size="10.5" fill="#5a6b80" text-anchor="middle">链路余量 M（dB）· n='+h(mc.n||"")+'</text>';
  return s+'</svg>';
}
/* 龙卷风图（各不确定项 ±2σ 对 M 的摆动） */
function robTornadoSvg(mc){
  const tor=mc.tornado||[];
  if(!tor.length) return "";
  const rowH=26,W=560,PL=170,PR=16,PT=24,PB=26;
  const H=PT+PB+tor.length*rowH;
  const mean=toF((mc.M||{}).mean,0);
  const spans=tor.map(t=>Math.max(t.m_high,t.span_db||0)-Math.min(t.m_low,0));
  let smax=0; tor.forEach(t=>{ smax=Math.max(smax,Math.abs(t.m_high-mean),Math.abs(t.m_low-mean)); });
  smax=Math.max(smax,0.5);
  const xOf=v=>PL+(v-mean+smax)/(2*smax)*(W-PL-PR);
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fbfdff" stroke="#d3e0ee" rx="8"/>';
  s+='<line x1="'+xOf(mean)+'" y1="'+PT+'" x2="'+xOf(mean)+'" y2="'+(H-PB)+'" stroke="#93a9c2" stroke-width="1"/>';
  tor.forEach((t,i)=>{ const yy=PT+i*rowH+4;
    const xa=xOf(t.m_low),xb=xOf(t.m_high);
    s+='<rect x="'+Math.min(xa,xb)+'" y="'+yy+'" width="'+Math.max(Math.abs(xb-xa),2)+'" height="'+(rowH-10)+'" rx="3" fill="#e08b4c" opacity=".85"/>'+
       '<text x="'+(PL-8)+'" y="'+(yy+12)+'" font-size="10.5" fill="#33475e" text-anchor="end">'+h(t.cn||t.param)+' ±2σ</text>'+
       '<text x="'+(Math.max(xa,xb)+6)+'" y="'+(yy+12)+'" font-size="10" fill="#8a5a2b">'+n(t.span_db,2)+'dB</text>'; });
  s+='<text x="'+xOf(mean)+'" y="'+(PT-8)+'" font-size="10" fill="#5a6b80" text-anchor="middle">均值 '+n(mean,2)+'dB</text>';
  return s+'</svg>';
}
/* 可靠性三 R 口径条 */
function robRelBarSvg(rel){
  const W=560,H=128,PL=150,PR=52,PT=14;
  const rows=[["单串基线（无冗余）",rel.r_serial_pct,"#c05656"],
              ["按 BOM 冗余标注",rel.r_asbuilt_pct,"#d99b3c"],
              ["标准 1:1 冗余设计",rel.r_designed_pct,"#4a9a5f"]];
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fbfdff" stroke="#d3e0ee" rx="8"/>';
  rows.forEach((r,i)=>{ const yy=PT+i*36;
    const wv=Math.max(toF(r[1],0),0)/100*(W-PL-PR);
    s+='<text x="'+(PL-8)+'" y="'+(yy+16)+'" font-size="11" fill="#33475e" text-anchor="end">'+h(r[0])+'</text>'+
       '<rect x="'+PL+'" y="'+(yy+3)+'" width="'+(W-PL-PR)+'" height="18" fill="#eef3f9" stroke="#dce6f0" rx="3"/>'+
       '<rect x="'+PL+'" y="'+(yy+3)+'" width="'+wv.toFixed(1)+'" height="18" fill="'+r[2]+'" opacity=".85" rx="3"/>'+
       '<text x="'+(PL+wv+6)+'" y="'+(yy+16)+'" font-size="11" fill="#33475e" font-weight="700">'+n(toF(r[1],0),1)+'%</text>'; });
  const xg=PL+0.9*(W-PL-PR);
  s+='<line x1="'+xg+'" y1="'+(PT-2)+'" x2="'+xg+'" y2="'+(PT+3*36-16)+'" stroke="#d43a3a" stroke-width="1.4" stroke-dasharray="4,3"/>'+
     '<text x="'+(xg+4)+'" y="'+(PT+10)+'" font-size="10" fill="#d43a3a">90% 良好线</text>';
  return s+'</svg>';
}
function renderRobust(){
  const box=el("rob"); if(!box) return;
  if(!RES||!RES.robust){ box.innerHTML='<div class="panel"><div class="muted">请先完成一次设计。</div></div>'; return; }
  const rb=RES.robust;
  let html='<div class="panel"><h2>方案级稳健性分析（星蚀供电 · 位保寿命 · 链路灵敏度 · 去极化 · 可靠性 · 邻星干扰）</h2>';
  html+='<div class="'+(rb.ok===false?"warnbox":"okbox")+'"><b>综合结论：</b>'+h(rb.verdict||"")+'</div>';

  /* --- 星蚀供电 --- */
  const ec=rb.eclipse||{};
  if(ec.error) html+=robSection("1. 星蚀（地影）供电分析",'<div class="warnbox">计算失败：'+h(ec.error)+'</div>');
  else{
    const pw=ec.power||{};
    html+=robSection("1. 星蚀（地影）供电分析",
      '<div class="chips"><span class="tag info">'+(ec.is_geo?"GEO（分点季最恶劣历元锚定）":h(ec.orbit||"LEO/MEO"))+'</span>'+
      '<span class="tag info">星蚀段数 '+h(ec.n_eclipses||0)+'</span>'+
      '<span class="tag info">最长 '+n(ec.t_max_min,0)+' min（'+h(ec.t_max_source||"")+'）</span>'+
      robTag(pw.batt_ok!==false,"电池满足","电池不足")+'</div>'+
      '<table><tr><th>载荷功耗 P_load</th><th>最长星蚀</th><th>电池需求 E_req（DoD≤80%）</th><th>平台电池</th><th>结论</th></tr>'+
      '<tr><td class="num">'+n(pw.p_load_w||0,0)+' W</td><td class="num">'+n(ec.t_max_min,0)+' min</td>'+
      '<td class="num"><b>'+n(pw.e_req_kwh,2)+' kWh</b></td><td class="num">'+n(pw.batt_kwh,2)+' kWh</td>'+
      '<td>'+robTag(pw.batt_ok!==false)+'</td></tr></table>',
      h(ec.verdict||""));
  }
  /* --- 位保 ΔV/寿命 --- */
  const sk=rb.station_keeping||{}, ske=rb.station_keeping_ep||{};
  if(sk.error) html+=robSection("2. 位置保持 ΔV 与寿命",'<div class="warnbox">计算失败：'+h(sk.error)+'</div>');
  else{
    html+=robSection("2. 位置保持 ΔV 与推进剂寿命",
      '<table><tr><th>推进方式</th><th class="num">ΔV/年 (m/s)</th><th class="num">寿命期 ΔV (m/s)</th><th class="num">Isp (s)</th><th class="num">推进剂 (kg)</th><th class="num">湿重 (kg)</th><th class="num">占比 (%)</th><th>判定</th></tr>'+
      '<tr><td><b>化学推进</b>（基准）</td><td class="num">'+n(sk.dv_per_yr,1)+'</td><td class="num">'+n(sk.dv_total_ms,0)+'</td>'+
      '<td class="num">'+n(sk.isp_s,0)+'</td><td class="num"><b>'+n(sk.m_prop_kg,0)+'</b></td><td class="num">'+n(sk.m_wet_kg,0)+'</td>'+
      '<td class="num">'+n(sk.prop_frac_pct,1)+'</td><td>'+robTag(sk.ok!==false,"合理(<15%)","偏高")+'</td></tr>'+
      (ske.dv_total_ms!==undefined?'<tr><td><b>电推对照</b>（Isp 1800s）</td><td class="num">'+n(ske.dv_per_yr,1)+'</td><td class="num">'+n(ske.dv_total_ms,0)+'</td>'+
      '<td class="num">1800</td><td class="num"><b>'+n(ske.m_prop_kg,0)+'</b></td><td class="num">'+n(ske.m_wet_kg,0)+'</td>'+
      '<td class="num">'+n(ske.prop_frac_pct,1)+'</td><td>'+robTag(ske.ok!==false)+'</td></tr>':'')+'</table>',
      h(sk.source||"")+"。"+h(sk.verdict||""));
  }
  /* --- MC 灵敏度 --- */
  const mc=rb.monte_carlo||{};
  if(mc.ok===false) html+=robSection("3. 链路灵敏度蒙特卡洛",'<div class="warnbox">'+h(mc.error||mc.note||"未计算")+'</div>');
  else{
    const M=mc.M||{};
    html+=robSection("3. 链路灵敏度蒙特卡洛（下行 · dB 域精确叠加）",
      '<div class="chips"><span class="tag info">n='+h(mc.n||0)+'</span>'+
      '<span class="tag info">M 均值 '+n(M.mean,2)+' dB（σ='+n(M.std,2)+'）</span>'+
      '<span class="tag info">P10='+n(M.p10,2)+' dB / P90='+n(M.p90,2)+' dB</span>'+
      robTag(toF(mc.p_close_pct,0)>=95,"闭合概率 "+n(mc.p_close_pct,1)+"%","闭合概率仅 "+n(mc.p_close_pct,1)+"%")+'</div>'+
      '<div style="display:flex;gap:14px;flex-wrap:wrap">'+robMcHistSvg(mc)+robTornadoSvg(mc)+'</div>'+
      '<table><tr><th>ACM 期望容量 (Gbps)</th><th>定档名义容量 (Gbps)</th><th>MODCOD 驻留分布（TOP6）</th></tr><tr>'+
      '<td class="num"><b>'+n((mc.acm_capacity_gbps||{}).mean,2)+'</b></td>'+
      '<td class="num">'+n((mc.acm_capacity_gbps||{}).fixed_nominal_gbps,2)+'</td>'+
      '<td class="small">'+Object.keys(mc.modcod_hist||{}).slice(0,6).map(k=>h(k)+"×"+h(mc.modcod_hist[k])).join(" ｜ ")+'</td></tr></table>',
      "扰动口径：EIRP/GT σ=0.5dB、雨衰对数正态 σ=25%、指向 0.25dB、极化 0.15dB、实现 0.2dB（dB 域线性叠加=链路方程精确解）。龙卷风图给出各不确定项 ±2σ 对余量的摆动幅度，用于确定加固优先级。");
  }
  /* --- XPD --- */
  const xp=rb.xpd||{}, iso=xp.isolation||{}, xpdD=iso.xpd||{};
  html+=robSection("4. 雨致去极化（XPD）与频率复用",
    (xp.error?'<div class="warnbox">计算失败：'+h(xp.error)+'</div>':
     (xpdD.XPD_p===undefined?
      '<div class="okbox">'+h(xp.verdict||xp.note||"")+'</div>':
      '<div class="chips"><span class="tag info">雨致 XPD='+n(xpdD.XPD_rain,1)+' dB（P 极化 '+n(xpdD.XPD_p,1)+' dB）</span>'+
      '<span class="tag info">天线交极隔离='+n(iso.reuse_xpol_db,30)+' dB</span>'+
      '<span class="tag info">有效隔离='+n(iso.eff_iso_db,1)+' dB（要求 '+n(iso.xpd_spec_db,30)+' dB）</span>'+
      '<span class="tag info">裕度 '+n(iso.margin_db,1)+' dB</span>'+
      robTag(iso.ok!==false,"满足复用要求","超出隔离能力")+'</div>')),
    h(xp.verdict||"")||"ITU-R P.618-12 §4.1 雨致去极化模型（C_f/C_A/C_τ/C_θ/C_σ 全项），与同波束双极化复用要求对比。");
  /* --- 可靠性 --- */
  const rel=rb.reliability||{}, adv=rb.redundancy||{};
  if(rel.error) html+=robSection("5. 载荷可靠性（BOM+MTBF 汇总）",'<div class="warnbox">计算失败：'+h(rel.error)+'</div>');
  else{
    const kindCn={series:"单串",pair:"1+1 冷备",triple:"三模表决",channel:"通道化降级",array:"阵面降级"};
    html+=robSection("5. 载荷可靠性汇总（寿命 "+n(toF(rb.life_yr,15),0)+" 年）",
      '<div class="chips"><span class="tag info">单机 '+h(rel.n_units||0)+' 台 / '+h((rel.items||[]).length)+' 行</span>'+
      '<span class="tag mut">单串 '+h(rel.n_series||0)+' 项</span><span class="tag mut">已冗余 '+h(rel.n_redundant||0)+' 项</span>'+
      '<span class="tag mut">优雅降级 '+h(rel.n_graceful||0)+' 项</span>'+
      robTag(rel.pass_90===true,"R≥90% 良好","R<90% 需整改")+'</div>'+
      robRelBarSvg(rel)+
      '<table><tr><th>单机（TOP10 按 q 降序）</th><th>结构</th><th class="num">数量</th><th class="num">MTBF (h)</th><th class="num">q 寿命期 (%)</th><th class="num">q 设计口径 (%)</th><th class="num">贡献 (%)</th></tr>'+
      (rel.items||[]).slice(0,10).map(it=>'<tr><td>'+h(it.cn)+'</td><td><span class="tag mut">'+h(kindCn[it.kind]||it.kind)+'</span></td>'+
        '<td class="num">'+h(it.qty)+'</td><td class="num">'+h(Math.round(toF(it.mtbf_h,0)).toExponential(0))+'</td>'+
        '<td class="num">'+n(it.q_life_pct,2)+'</td><td class="num">'+n(it.q_designed_pct,2)+'</td><td class="num">'+n(it.contrib_pct,1)+'</td></tr>').join("")+'</table>'+
      '<h4 style="margin:12px 0 6px">整改建议（目标 R≥'+n(toF(adv.target_r,0.95)*100,0)+'%）</h4>'+
      '<div class="'+(adv.pass_target?"okbox":"warnbox")+'">'+h(adv.note||"")+'</div>'+
      ((adv.plan||[]).length?'<table><tr><th>单机</th><th>结构</th><th>措施</th><th class="num">q 前 (%)</th><th class="num">q 后 (%)</th><th class="num">R 后 (%)</th><th class="num">ΔR (pp)</th></tr>'+
       adv.plan.map(p=>'<tr><td>'+h(p.cn)+'</td><td><span class="tag mut">'+h(kindCn[p.kind]||p.kind)+'</span></td>'+
        '<td class="small">'+h(p.action||p.kind)+'</td><td class="num">'+n(p.q_before_pct,2)+'</td><td class="num">'+n(p.q_after_pct,3)+'</td>'+
        '<td class="num"><b>'+n(p.r_after*100,1)+'</b></td><td class="num">+'+n(p.delta_pct,1)+'</td></tr>').join("")+'</table>':''),
      "模型：series q=1−exp(−nλt)；pair 逐件冷备 q=1−(1−q_u²)^n；triple 2/3 表决；channel/array k-out-of-n（Poisson）。MTBF 为分类工程保守值，详细设计阶段以零件应力分析（GJB 299C / MIL-HDBK-217）替代。");
  }
  /* --- 邻星干扰 --- */
  const inf=rb.interference||{};
  if(inf.note&&!inf.ci_dn_db) html+=robSection("6. 邻星干扰 C/I（GSO 弧段协调）",'<div class="okbox">'+h(inf.verdict||inf.note)+'</div>');
  else if(inf.error) html+=robSection("6. 邻星干扰 C/I",'<div class="warnbox">计算失败：'+h(inf.error)+'</div>');
  else{
    const se=inf.single_entry_ok||{};
    html+=robSection("6. 邻星干扰 C/I（GSO 弧段协调）",
      '<div class="chips"><span class="tag info">轨位间隔 '+n(inf.phi_sep_deg,2)+'°</span>'+
      '<span class="tag info">下行 C/I='+n(inf.ci_dn_db,1)+' dB</span>'+
      '<span class="tag info">上行 C/I='+n(inf.ci_up_db,1)+' dB</span>'+
      robTag(se.down!==false,"下行满足单入境判据","下行超出")+' '+robTag(se.up!==false,"上行满足","上行超出")+'</div>',
      h(inf.verdict||"")+"。地面站旁瓣按 ITU-R S.465-6 包络（32−25log₁₀φ），卫星旁瓣按 S.580/S.1428 工程近似。");
  }
  html+='<div class="note small">本页数据与 Word 报告「稳健性分析」章同源（design_all → R.robust，随「开始设计」自动刷新）；星蚀分析对 GEO 锚定分点最恶劣历元（±22 天窗口），避免任意历元得出 0 星蚀的非保守结论。</div></div>';
  box.innerHTML=html;
}

/* ---------- ⑫ 轨道覆盖仿真（orbit_engine：轨迹 + 覆盖圈 + 快照 + 可见窗 + STK .e 导出） ---------- */
let ORBSIM=null, _orbSeq=0;
const _orbState={tOff:0,stk:null};
function orbitPayload(withStk){
  const cov=META.coverage[RES.cfg.coverage]||{};
  const orb=META.orbits[RES.cfg.orbit]||{};
  const isGeo=RES.cfg.orbit==="GEO";
  const sa=satAnchor();
  const p={orbit_key:RES.cfg.orbit,h_km:orb.alt_km||35786,
    incl_deg:(isGeo?0.05:null),
    targets:[{name:String(cov.cn||RES.cfg.coverage),lat:toF(cov.lat,sa.lat),
              lon:toF(cov.lon!==undefined&&cov.lon!==null?cov.lon:(cov.geo_lon||0),sa.lon)}],
    el_min_deg:toF(cov.el_min!==undefined?cov.el_min:10,10),
    t_offset_min:_orbState.tOff,dur_h:24,
    tag:_safeTag("轨道_"+RES.cfg.orbit)};
  if(isGeo) p.geo_lon=sa.lon;
  if(withStk) p.export_stk=true;
  return p;
}
async function renderOrbit(withStk){
  const seq=++_orbSeq;
  const box=el("orbit"); if(!box) return;
  if(!RES||!RES.res){ box.innerHTML='<div class="panel"><div class="muted">请先完成一次设计。</div></div>'; return; }
  if(ORBSIM&&!withStk){ box.innerHTML=orbitHTML(ORBSIM); bindOrbitPanel(); return; }
  box.innerHTML='<div class="panel"><h2>轨道覆盖仿真（STK 等效内置计算）</h2>'+
    '<div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> '+
    '轨道传播 + 覆盖分析中（二体 Kepler + J2 摄动 · 24h 可见窗扫描）…</div></div>';
  try{
    const r=await apiCall("orbit",orbitPayload(!!withStk));
    if(seq!==_orbSeq) return;
    const b2=el("orbit"); if(!b2) return;
    if(!r.ok){ b2.innerHTML='<div class="panel"><div class="warnbox">轨道仿真失败：'+h(r.error||"未知错误")+'</div></div>'; return; }
    if(r.stk_file) _orbState.stk=r.stk_file;
    ORBSIM=r;
    b2.innerHTML=orbitHTML(r);
    bindOrbitPanel();
  }catch(e){
    if(seq!==_orbSeq) return;
    const b2=el("orbit");
    if(b2) b2.innerHTML='<div class="panel"><div class="warnbox">轨道仿真通道不可用：'+h(e)+'</div></div>';
  }
}
function bindOrbitPanel(){
  const sl=el("orbTimeSlider"), lb=el("orbTimeLbl");
  if(sl) sl.addEventListener("input",()=>{ if(lb) lb.textContent=n(toF(sl.value,0),0)+" min"; });
  if(sl) sl.addEventListener("change",()=>{ _orbState.tOff=toF(sl.value,0); ORBSIM=null; renderOrbit(); });
  const ex=el("orbExportStk");
  if(ex) ex.addEventListener("click",()=>renderOrbit(true));
  const op=el("orbOpenStk"), rv=el("orbRevealStk");
  if(op&&_orbState.stk) op.addEventListener("click",()=>apiCall("open_file",{path:_orbState.stk.path}));
  if(rv&&_orbState.stk) rv.addEventListener("click",()=>apiCall("reveal_file",{path:_orbState.stk.path}));
}
/* 轨迹 + 覆盖圈地图（等距圆柱全球投影；跨 180° 经线分段） */
function orbitTrackSvg(O){
  const W=980,H=520,PL=12,PT=12,PB=34;
  const MW=W-2*PL, MH=H-PT-PB;
  const X=lo=>PL+((lo+180)%360)/360*MW, Y=la=>PT+(90-Math.min(Math.max(la,-89),89))/180*MH;
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" font-family="Microsoft YaHei,sans-serif" style="max-width:100%;height:auto">';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+MW+'" height="'+MH+'" fill="#eef5fb" stroke="#d3e0ee"/>';
  for(let lo=-180;lo<=180;lo+=30) s+='<line x1="'+X(lo)+'" y1="'+PT+'" x2="'+X(lo)+'" y2="'+(PT+MH)+'" stroke="#dfe9f3" stroke-width=".6"/>';
  for(let la=-60;la<=60;la+=30) s+='<line x1="'+PL+'" y1="'+Y(la)+'" x2="'+(PL+MW)+'" y2="'+Y(la)+'" stroke="#dfe9f3" stroke-width=".6"/>';
  s+='<line x1="'+PL+'" y1="'+Y(0)+'" x2="'+(PL+MW)+'" y2="'+Y(0)+'" stroke="#c3d4e6" stroke-width="1"/>';
  const q=(_worldLand&&_worldLand.q)||4, polys=(_worldLand&&_worldLand.polys)||[];
  polys.forEach(poly=>{
    let d="",first=true;
    let prevLon=null;
    for(let i=0;i+1<poly.length;i+=2){
      const lon=poly[i]/q, lat=poly[i+1]/q;
      if(prevLon!==null&&Math.abs(lon-prevLon)>180) first=true;   // 跨日界线分段
      prevLon=lon;
      const px=X(lon),py=Y(lat);
      if(first){ d+="M"+px.toFixed(1)+","+py.toFixed(1); first=false; }
      else d+="L"+px.toFixed(1)+","+py.toFixed(1);
    }
    if(d) s+='<path d="'+d+'" fill="#cfe0d2" stroke="#9db9a3" stroke-width=".5" stroke-linejoin="round"/>';
  });
  // 24h 星下点轨迹（分段防跨日界线飞线；渐变色区分时间先后）
  const tr=O.track||[];
  if(tr.length>1){
    let seg=[[tr[0]]];
    for(let i=1;i<tr.length;i++){
      if(Math.abs(tr[i][2]-tr[i-1][2])>180) seg.push([tr[i]]);
      else seg[seg.length-1].push(tr[i]);
    }
    seg.forEach((sg,si)=>{
      if(sg.length<2) return;
      const d=sg.map((p,i)=>(i===0?"M":"L")+X(p[2]).toFixed(1)+","+Y(p[1]).toFixed(1)).join("");
      s+='<path d="'+d+'" fill="none" stroke="#0b5cad" stroke-width="1.6" opacity="'+(0.45+0.55*si/Math.max(seg.length-1,1)).toFixed(2)+'"/>';
    });
  }
  // 快照时刻：覆盖圈（填充）+ 星下点
  const sn=O.snapshot||{};
  const cir=sn.circle||[];
  if(cir.length>2){
    let d="",first=true,prevLon=null;
    for(let i=0;i<cir.length;i++){
      const la=cir[i][0], lo=((cir[i][1]+180)%360)-180;
      if(prevLon!==null&&Math.abs(lo-prevLon)>180) first=true;
      prevLon=lo;
      if(first){ d+="M"+X(lo).toFixed(1)+","+Y(la).toFixed(1); first=false; }
      else d+="L"+X(lo).toFixed(1)+","+Y(la).toFixed(1);
    }
    if(d) s+='<path d="'+d+'" fill="#0b5cad" fill-opacity=".13" stroke="#0b5cad" stroke-width="1.8" stroke-dasharray="7 4"/>';
  }
  if(sn.sub_lat!==undefined){
    const sx=X(sn.sub_lon), sy=Y(sn.sub_lat);
    s+='<g><line x1="'+(sx-8)+'" y1="'+sy+'" x2="'+(sx+8)+'" y2="'+sy+'" stroke="#c0392b" stroke-width="1.8"/>'+
       '<line x1="'+sx+'" y1="'+(sy-8)+'" x2="'+sx+'" y2="'+(sy+8)+'" stroke="#c0392b" stroke-width="1.8"/>'+
       '<circle cx="'+sx+'" cy="'+sy+'" r="3.4" fill="#c0392b"><animate attributeName="r" values="3.4;6.5;3.4" dur="2s" repeatCount="indefinite"/><animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/></circle></g>'+
       '<text x="'+(sx+11)+'" y="'+(sy-9)+'" font-size="10.5" fill="#c0392b" font-weight="700">🛰 t='+n(sn.t_offset_min,0)+'min ('+n(sn.sub_lat,1)+'°, '+n(sn.sub_lon,1)+'°)</text>';
  }
  // 目标点（黄星）
  (sn.targets||[]).forEach(t=>{
    const tx=X(t.lon), ty=Y(t.lat);
    s+='<g><circle cx="'+tx+'" cy="'+ty+'" r="4" fill="'+(t.visible?"#e6b422":"#8a94a0")+'" stroke="#5a3d00" stroke-width=".8"/>'+
       '<text x="'+(tx+7)+'" y="'+(ty+4)+'" font-size="10" fill="#5a3d00" font-weight="700">'+h(t.name)+' el='+n(t.el_deg,1)+'°'+(t.visible?"":"（不可见）")+'</text></g>';
  });
  for(let lo=-180;lo<=180;lo+=30) s+='<text x="'+X(lo)+'" y="'+(H-PB+16)+'" text-anchor="middle" font-size="9.5" fill="#5f7183">'+lo+'°</text>';
  s+='<text x="'+(PL+MW/2)+'" y="'+(H-4)+'" text-anchor="middle" font-size="10.5" fill="#5f7183">经度 (°) —— 蓝线=24h 星下点轨迹（渐深=时间先后） · 蓝虚线圈=快照时刻覆盖圈（仰角≥'+n(O.el_min_deg,0)+'°） · 仅海岸线无政治边界</text>';
  s+='</svg>';
  return s;
}
function orbitHTML(O){
  const sn=O.snapshot||{}, as=O.assess||{};
  let html='<div class="panel"><h2>轨道覆盖仿真（STK 等效内置计算 · 二体 Kepler + J2 摄动）</h2>';
  html+='<div class="chips" style="flex-wrap:wrap;gap:8px">'+
    '<span class="tag info">'+h(O.orbit)+' · h='+n(O.h_km,0)+' km · i='+n(O.incl_deg,2)+'°'+(O.ecc?(' · e='+n(O.ecc,3)):"")+'</span>'+
    '<span class="tag mut">T='+n(O.period_min,1)+' min · v='+n(O.vel_kms,2)+' km/s · Ω̇='+n(O.raan_dot_deg_day,3)+'°/d'+
      (O.orbit==="SSO"&&O.sso_incl?('（太阳同步 i≈'+n(O.sso_incl,1)+'°✓）'):"")+'</span>'+
    (O.geo_lon!==null&&O.geo_lon!==undefined?'<span class="tag ok">GEO 定点 '+n(O.geo_lon,1)+'°E</span>':"")+
    '<span style="flex:1"></span>'+
    '<button class="btn sm" id="orbExportStk">⬇ 导出 STK Ephemeris (.e)</button>'+
  '</div>';
  // 某时刻快照控制条
  html+='<div class="globebar" style="margin-top:8px"><span class="glabel">⏱ 仿真时刻（历元起）</span>'+
    '<input type="range" id="orbTimeSlider" min="0" max="1440" step="5" value="'+n(sn.t_offset_min||0,0)+'" style="flex:1;max-width:420px">'+
    '<span class="glabel" id="orbTimeLbl">'+n(sn.t_offset_min||0,0)+' min</span>'+
    '<span class="glabel">'+h(sn.t_utc||"")+'</span></div>';
  // 快照 KPI
  html+='<div class="kpis">'+
    kpi("星下点","("+n(sn.sub_lat,2)+", "+n(sn.sub_lon,2)+")","°N, °E")+
    kpi("轨道高度",sn.alt_km,"km")+
    kpi("覆盖帽 σ",sn.sigma_deg,"°（仰角≥"+n(O.el_min_deg,0)+"°）")+
    kpi("覆盖半径",sn.cov_radius_km,"km")+
    kpi("卫星速度",sn.vel_kms,"km/s")+
  '</div>';
  html+='<div class="plotbox"><h4>星下点轨迹 + 快照时刻覆盖（某一时刻覆盖情况）</h4>'+orbitTrackSvg(O)+'</div>';
  // 目标可见性（快照时刻）
  if(sn.targets&&sn.targets.length){
    html+='<h4>快照时刻目标可见性</h4><table><tr><th>目标</th><th class="num">纬度 (°)</th><th class="num">经度 (°)</th><th class="num">仰角 (°)</th><th class="num">斜距 (km)</th><th>可见（≥'+n(O.el_min_deg,0)+'°）</th></tr>';
    sn.targets.forEach(t=>{
      html+='<tr><td><b>'+h(t.name)+'</b></td><td class="num">'+n(t.lat,2)+'</td><td class="num">'+n(t.lon,2)+'</td><td class="num">'+n(t.el_deg,1)+'</td><td class="num">'+n(t.slant_km,0)+'</td><td>'+tag(t.visible,t.visible?"可见":"不可见")+'</td></tr>';
    });
    html+='</table>';
  }
  // 24h 可见窗
  const rs=as.results||[];
  if(rs.length){
    html+='<h4>24h 可见时间窗（AOS/LOS · 最大仰角 · 覆盖率 · 重访）</h4>';
    rs.forEach(r=>{
      html+='<div class="note small" style="margin:6px 0"><b>'+h(r.target)+'</b>：'+r.n_win+' 个窗口 · 覆盖率 <b>'+n(r.cov_pct,1)+'%</b> · 最大仰角 '+n(r.el_max,1)+'° · 最长重访间隔 '+n(r.revisit_h,2)+' h</div>';
      if(r.windows&&r.windows.length){
        html+='<table><tr><th>#</th><th class="num">AOS (h)</th><th class="num">LOS (h)</th><th class="num">时长 (min)</th><th class="num">最大仰角 (°)</th></tr>';
        r.windows.forEach((w,i)=>{
          html+='<tr><td>'+(i+1)+'</td><td class="num">'+n(w.aos_h,2)+'</td><td class="num">'+n(w.los_h,2)+'</td><td class="num">'+n(w.dur_min,1)+'</td><td class="num">'+n(w.el_max,1)+'</td></tr>';
        });
        html+='</table>';
        if(r.n_win>r.windows.length) html+='<div class="muted small">（仅列前 '+r.windows.length+' 窗，共 '+r.n_win+' 窗）</div>';
      }
    });
  }
  // 轨道合理性结论
  if(as.verdict)
    html+='<div class="'+(as.ok?"okbox":"badbox")+'"><b>轨道覆盖合理性判定：</b>'+h(as.verdict)+'</div>';
  // STK .e 导出结果
  if(_orbState.stk)
    html+='<div class="okbox small">✅ STK Ephemeris 已导出：<code>'+h(_orbState.stk.path)+'</code>（'+_orbState.stk.points+' 点 · '+h(_orbState.stk.format||"")+'）——STK 中 Insert → Satellite → From Ephemeris File 导入即可复核轨道与覆盖。'+
      ' <button class="btn sm" id="orbOpenStk">打开文件</button> <button class="btn sm" id="orbRevealStk">所在文件夹</button></div>';
  else
    html+='<div class="note small">导出 .e（STK Ephemeris：stk.v.12 · J2000 ECI · 位置+速度，60s 步长）后可带入 STK 做高精度复核（HPOP 轨道 + Access 分析 + 覆盖重数图）。</div>';
  html+='<div class="note small"><b>模型说明：</b>二体 Kepler 传播 + J2 长期摄动（交点退行 Ω̇/近地点旋转 ω̇），ECI(J2000)→ECEF(IAU1982 GMST)→星下点；'+
    'LEO 一天量级内与 STK HPOP 偏差 &lt;0.5°。GEO 定点经度按覆盖区推荐星位（数值标定 raan）。历元为示意（2026-01-01）。</div>';
  html+='</div>';
  return html;
}

/* ---------- ⑪ 接口与协议（MOSA 标准化 ICD 自动生成） ---------- */
let ICD=null, _icdSeq=0;
async function renderIcd(){
  const seq=++_icdSeq;
  const box=el("icd"); if(!box) return;
  if(ICD){ box.innerHTML=icdHTML(ICD); return; }
  box.innerHTML='<div class="panel"><h2>接口与协议（MOSA 标准化 ICD）</h2>'+
    '<div class="muted"><span class="spinner" style="width:18px;height:18px;border-width:3px;display:inline-block;vertical-align:middle"></span> '+
    '按当前方案自动推导接口矩阵与标准协议（方案设定 → 单机选型 → 接口 → 标准协议 → 软件 ICD）…</div></div>';
  try{
    const cfgOut=deep(CFG); cfgOut.isl_on=!!cfgOut.isl_type;
    const r=await apiCall("protocol",{cfg:cfgOut});
    if(seq!==_icdSeq) return;
    if(!r.ok||!r.result){
      box.innerHTML='<div class="panel"><div class="warnbox">接口协议生成失败：'+h((r&&r.error)||"引擎未返回")+'</div></div>'; return;
    }
    ICD=r.result;
    box.innerHTML=icdHTML(ICD);
  }catch(e){
    if(seq!==_icdSeq) return;
    box.innerHTML='<div class="panel"><div class="warnbox">接口协议通道不可用：'+h(e)+'</div></div>';
  }
}
function icdHTML(icd){
  const st=icd.stats||{};
  let html='<div class="panel"><h2>接口与协议 · MOSA 标准化 ICD（自动生成）</h2>'+
  '<div class="note"><b>生成链路：</b>方案设定 → 单机选型（货架优先三级选型）→ 接口自动推导（ICD 矩阵）→ '+
  '标准协议规格（CCSDS / ECSS / MIL-STD-1553B / FC-AE）→ 单机软件协议栈（供软件开发）。'+
  '标准化参考 <b>MOSA</b>（模块化开放系统方法）与 <b>FACE</b> 五层软件参考架构。</div>'+
  '<div class="icdflow">'+
    '<div class="icdstep done"><div class="st-n">STEP 1</div><div class="st-t">方案设定</div><div class="st-d">'+h(RES.req.orbit_cn)+' · '+h(RES.req.coverage_cn)+' · '+h(RES.req.band)+' · '+h(RES.req.mode_cn)+'</div></div>'+
    '<div class="icdstep done"><div class="st-n">STEP 2</div><div class="st-t">单机选型</div><div class="st-d">'+st.n_if+' 接口节点 ｜ 货架单机 '+h(RES.totals.n_rows)+' 种</div></div>'+
    '<div class="icdstep done"><div class="st-n">STEP 3</div><div class="st-t">接口推导</div><div class="st-d">射频 '+st.n_rf+' / 中频 '+st.n_ifmid+' / 数据 '+st.n_dig+' / 控制 '+st.n_ctrl+' / 光 '+st.n_opt+' / 电源 '+st.n_power+'</div></div>'+
    '<div class="icdstep done"><div class="st-n">STEP 4</div><div class="st-t">标准协议</div><div class="st-d">CCSDS 帧格式 '+(icd.frames||[]).length+' 种 ｜ APID '+st.n_apid+' / VCID '+st.n_vc+'</div></div>'+
    '<div class="icdstep done"><div class="st-n">STEP 5</div><div class="st-t">软件 ICD</div><div class="st-d">'+(icd.sw_icd||[]).length+' 台处理类单机协议栈（MOSA 分层落地）</div></div>'+
  '</div>';

  // 1 接口矩阵
  html+='<h3>1. 接口矩阵（ICD 核心表 · 由载荷框图自动推导）</h3>'+
  '<table><tr><th>#</th><th>接口（源→宿）</th><th>类型</th><th>传输介质 / 连接器</th><th>关键参数</th><th>遵循标准</th></tr>'+
  (icd.interfaces||[]).map(i=>'<tr><td class="num">'+i.idx+'</td>'+
    '<td><b>'+h(i.src_cn)+'</b> → <b>'+h(i.dst_cn)+'</b><br><span class="muted small">'+h(i.src_id)+'→'+h(i.dst_id)+' ｜ '+h(i.label||"")+'</span></td>'+
    '<td><span class="tag '+(i.itype==="射频接口"?"info":(i.itype==="数据接口"?"ok":"mut"))+'">'+h(i.itype)+'</span><br><span class="small">'+h(i.subtype||"")+'</span></td>'+
    '<td class="small">'+h(i.media)+'<br><span class="muted">'+h(i.conn)+'</span></td>'+
    '<td class="small">'+h(i.param)+'</td>'+
    '<td class="small">'+h(i.std)+'</td></tr>').join("")+'</table>';

  // 2 电气特性
  html+='<h3>2. 接口电气/性能特性</h3>'+
  '<table><tr><th>#</th><th>接口</th><th>电气/性能特性</th><th>工程备注</th></tr>'+
  (icd.interfaces||[]).map(i=>'<tr><td class="num">'+i.idx+'</td><td class="small">'+h(i.src_id)+'→'+h(i.dst_id)+'</td>'+
    '<td class="small">'+h(i.electrical)+'</td><td class="small muted">'+h(i.note||"")+'</td></tr>').join("")+'</table>';

  // 3 数据总线标准库
  html+='<h3>3. 数据总线开放标准库（按速率自动选型）</h3>'+
  '<table><tr><th>总线</th><th>标准</th><th>速率能力</th><th>介质/电气</th><th>连接器</th><th>适用</th></tr>'+
  (icd.bus_standards||[]).map(b=>'<tr><td><b>'+h(b.bus)+'</b></td><td class="small">'+h(b.std)+'</td>'+
    '<td class="num small">≤'+n(b.cap_mbps,0)+' Mbps</td><td class="small">'+h(b.media)+'</td>'+
    '<td class="small">'+h(b.conn)+'</td><td class="small">'+h(b.note)+'</td></tr>').join("")+'</table>';
  html+='<div class="note small"><b>选型规则（MOSA 优先公开标准）：</b>速率需求就近向上匹配开放标准总线；'+
  '控制面独立走 '+((icd.ctrl_buses||[]).map(c=>h(c.bus)).join(" / "))+'（控制面与数据面物理隔离）。</div>';

  // 4 CCSDS 帧格式（字段级位条带）
  html+='<h3>4. CCSDS 协议帧格式（字段级 · 供软件协议栈开发）</h3>';
  (icd.frames||[]).forEach(fr=>{
    html+='<div class="framebox"><div class="fn">'+h(fr.name)+'</div><div class="fs">'+h(fr.std)+' ｜ 帧头 '+h(fr.size)+'</div>'+
      '<div class="bitstrip">'+fr.fields.map(fd=>'<div class="bitf" style="flex:'+
        (typeof fd[1]==="number"?Math.max(fd[1],2):3)+' 1 auto"><b>'+h(fd[0])+'</b><br>'+h(fd[1])+' bit</div>').join("")+'</div>'+
      '<table><tr><th>字段</th><th class="num">位长</th><th>说明</th></tr>'+
      fr.fields.map(fd=>'<tr><td>'+h(fd[0])+'</td><td class="num">'+h(fd[1])+'</td><td class="small">'+h(fd[2])+'</td></tr>').join("")+'</table></div>';
  });

  // 5 APID / VCID
  html+='<h3>5. APID / 虚拟信道（VCID）自动分配</h3><div class="grid g2"><div>'+
  '<table><tr><th>APID</th><th>单机/用途</th><th>服务说明</th></tr>'+
  (icd.apids||[]).map(a=>'<tr><td class="num"><b>'+a.apid+'</b></td><td>'+h(a.unit)+' · '+h(a.cn)+'</td><td class="small">'+h(a.svc)+'</td></tr>').join("")+'</table></div><div>'+
  '<table><tr><th>VCID</th><th>业务</th><th>速率档</th><th>承载标准</th></tr>'+
  (icd.vcids||[]).map(v=>'<tr><td class="num"><b>'+v.vcid+'</b></td><td>'+h(v.svc)+'</td><td>'+h(v.rate)+'</td><td class="small">'+h(v.std)+'</td></tr>').join("")+'</table></div></div>';

  // 6 电源接口
  html+='<h3>6. 电源接口（ECSS 电源特性标准）</h3>'+
  '<table><tr><th>单机</th><th>名称</th><th class="num">数量</th><th>供电母线</th><th>标准</th><th>备注</th></tr>'+
  (icd.power||[]).slice(0,40).map(pw=>'<tr><td>'+h(pw.unit)+'</td><td>'+h(pw.cn)+'</td><td class="num">'+h(pw.qty)+'</td>'+
    '<td class="small">'+h(pw.bus)+'</td><td class="small">'+h(pw.std)+'</td><td class="small muted">'+h(pw.note||"")+'</td></tr>').join("")+'</table>';

  // 7 MOSA/FACE 分层
  html+='<h3>7. MOSA / FACE 软件分层参考</h3>'+
  '<table><tr><th>FACE 层</th><th>开放标准</th><th>内容</th><th>MOSA 意义</th></tr>'+
  (icd.layers||[]).map(l=>'<tr><td><b>'+h(l.layer)+'</b></td><td class="small">'+h(l.std)+'</td>'+
    '<td class="small">'+h(l.content)+'</td><td class="small">'+h(l.mosa)+'</td></tr>').join("")+'</table>';

  // 8 MOSA 符合性
  html+='<h3>8. MOSA 符合性检查（开放架构五要素）</h3><div class="mosaic">'+
  (icd.mosa||[]).map(m=>'<div class="mcard '+(m.score==="满足"?"ok":"part")+'">'+
    '<div class="mt">'+h(m.item)+'</div><div class="md">'+h(m.eval)+'</div>'+
    '<div class="ms"><span class="tag '+(m.score==="满足"?"ok":"warn")+'">'+h(m.score)+'</span> <span class="muted small">'+h(m.note)+'</span></div></div>').join("")+'</div>';

  // 9 单机软件协议栈
  html+='<h3>9. 单机软件协议栈（软件 ICD · 供后续软件开发）</h3>';
  (icd.sw_icd||[]).forEach(u=>{
    html+='<div class="ifcard"><div class="ifh"><span class="ifn">'+h(u.unit)+' · '+h(u.cn)+'</span>'+
      '<span class="tag mut">×'+h(u.qty)+'</span></div><ul class="stack">'+
      u.stack.map(x=>'<li>'+h(x)+'</li>').join("")+'</ul></div>';
  });
  html+='<div class="note small">本 ICD 由 <b>protocol_gen</b> 引擎自动生成（与「单机清单」「载荷框图」同源）：'+
  '接口条目直接由 block_diagram 边表推导，速率/频段/功率取链路预算与频率规划结果；'+
  '修改方案配置后点击「开始设计」即自动刷新。导出 Word 报告第 7 章包含完整 ICD。'+
  '正式工程 ICD 需经双方签署确认，本文档为方案级自动生成基线。</div></div>';
  return html;
}

/* ---------- 页签/保存/打印 ---------- */
function showTab(id){
  document.querySelectorAll("section.tab").forEach(s=>s.classList.toggle("on",s.id===id));
  document.querySelectorAll("nav.tabs button").forEach(b=>b.classList.toggle("on",b.dataset.tab===id));
  // 接口与协议页：懒加载（首次切入或方案变更后自动计算）
  if(id==="tab-icd"&&RES&&!ICD) renderIcd();
  // 轨道覆盖仿真页：懒加载
  if(id==="tab-orbit"&&RES&&!ORBSIM) renderOrbit();
}
function saveScheme(){
  const name=(CFG.name||"方案")+"_"+new Date().toISOString().slice(0,16).replace(/[:T]/g,"-");
  const store=JSON.parse(localStorage.getItem("payload_schemes")||"{}");
  store[name]={cfg:deep(CFG),ts:Date.now()};
  localStorage.setItem("payload_schemes",JSON.stringify(store));
  alert("已保存到本地：\n"+name+"\n（浏览器 localStorage，可通过「载入方案」恢复）");
}
function loadScheme(){
  const store=JSON.parse(localStorage.getItem("payload_schemes")||"{}");
  const keys=Object.keys(store);
  if(!keys.length){ alert("暂无已保存方案。"); return; }
  keys.sort((a,b)=>store[b].ts-store[a].ts);
  const pick=prompt("载入哪个方案？输入编号：\n"+keys.map((k,i)=>(i+1)+". "+k).join("\n"),"1");
  const idx=parseInt(pick,10)-1;
  if(idx>=0&&idx<keys.length){ CFG=deep(store[keys[idx]].cfg); renderCfgUI(); alert("已载入 "+keys[idx]+"，点击「开始设计」重算。"); }
}
function printPdf(){
  document.querySelectorAll("section.tab").forEach(s=>s.style.display="block");
  window.print();
  document.querySelectorAll("section.tab").forEach(s=>s.style.display="");
}
/* ---------- 导出 Word（项目论证报告 · 后端落盘双通道） ----------
   修复"导出 Word 没反应"：WebView2 桌面态静默拦截 Blob-URL 的 a.click() 下载。
   现在：后端按 cfg 重算 → 生成项目论证报告（封面/摘要/目录/14章正文：需求分析、
   设计原理与方法论、总体方案+框架图、天线波束、链路预算、单机选型、接口协议 ICD、
   约束校验、方案评价、星座组网多覆盖区、EIRP 覆盖、轨道仿真、稳健性分析、附录；
   图表带编号题注+每章导语）→ 写盘 output/ →
   弹窗展示路径 +「用 Word 打开 / 打开所在文件夹」；网页态仍走 Blob 下载兜底。 */
let _expFile=null;
async function exportWord(){
  if(!RES){ alert("请先点击「开始设计」完成一次计算，再导出方案。"); return; }
  busy(true,"生成完整方案报告（含流程图/架构图/波束方向图/三维覆盖/接口协议 ICD）…");
  try{
    const cfgOut=deep(CFG); cfgOut.isl_on=!!cfgOut.isl_type;
    const r=await apiCall("export",{cfg:cfgOut,name:(CFG.name||"通信卫星有效载荷方案")});
    if(!r.ok||(!r.html&&!r.file_path)){ alert("导出失败："+(r.error||"引擎未返回文档")+"\n"+(r.trace||"").slice(-300)); return; }
    if(r.file_path){
      // 桌面/后端可写：已落盘 → 弹窗展示路径 + 打开按钮
      _expFile=r.file_path;
      el("expTitle").innerHTML="📄 完整方案报告已生成（"+n((r.chars||0)/1000,0)+"K 字符）";
      el("expBody").innerHTML=
        '<div class="okbox"><b>✓ 已保存到：</b><br><code style="word-break:break-all">'+h(r.file_path)+'</code></div>'+
        '<div class="note small">项目论证报告版式：封面 / 摘要（结论先行）/ 目录 / 14 章正文——'+
        '1 项目概述与需求分析 / 2 设计原理与方法论（第一性原理公式+skill 主链路+双回环+信息流框架图+单机原理）/ '+
        '3 总体方案（架构图+功能框架图+链路原理图+频率规划图+三维覆盖图）/ '+
        '4 天线与波束性能（GRASP 一维+二维方向图+次级方向图/栅瓣核查）/ 5 链路预算与转发器 / 6 单机选型与货架清单 / '+
        '7 接口与协议（MOSA ICD）/ 8 约束校验与回环 / 9 方案评价标准（E1~E10 评级+雷达图+修正建议）/ '+
        '10 星座组网与多覆盖区 / 11 地面 EIRP 覆盖分析（SATSOFT 等效）/ 12 轨道覆盖仿真（STK 等效）/ '+
        '13 方案级稳健性分析（星蚀供电/位保ΔV/链路灵敏度蒙特卡洛/雨致去极化XPD/可靠性三口径+整改建议/邻星干扰C/I）/ '+
        '14 附录；全部图表带编号题注、每章有导语。<br>'+
        '文件为 Word 兼容格式（.doc），全部插图已光栅化为位图（Word/WPS 直接显示），双击打开即可编辑、另存为 .docx 或打印 PDF。</div>';
      el("expMask").classList.add("on");
      return;
    }
    // 兜底（纯网页无后端落盘路径）：Blob 下载
    const blob=new Blob(["\ufeff",r.html],{type:"application/msword;charset=utf-8"});
    const a=document.createElement("a");
    a.href=URL.createObjectURL(blob);
    a.download=(CFG.name||"载荷方案")+"_"+new Date().toISOString().slice(0,10)+".doc";
    document.body.appendChild(a); a.click();
    setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); },1500);
  }catch(e){ alert("导出失败："+e); }
  finally{ busy(false); }
}

/* ---------- 启动 ---------- */
window.addEventListener("error",ev=>{ try{ if(window.pywebview&&pywebview.api) pywebview.api.js_error(String(ev.message),String(ev.filename||""),ev.lineno||0,ev.colno||0); }catch(_){} });
window.addEventListener("unhandledrejection",ev=>{ try{ if(window.pywebview&&pywebview.api) pywebview.api.js_error("unhandledrejection: "+String(ev.reason),"",0,0); }catch(_){} });
function bindModal(){
  const close=(id)=>el(id).addEventListener("click",()=>{
    el("diagMask").classList.remove("on"); el("sugMask").classList.remove("on"); });
  close("diagClose"); close("diagCloseBtn"); close("sugClose"); close("sugCancel");
  el("diagGoCons").addEventListener("click",()=>{
    el("diagMask").classList.remove("on"); showTab("tab-cons"); });
  el("sugApply").addEventListener("click",applySuggest);
  el("btnSuggest").addEventListener("click",showSuggest);
  el("btnDiag").addEventListener("click",()=>{
    if(RES&&RES.diagnosis) showDiagnosis(RES.diagnosis);
    else alert("请先点击「开始设计」完成一次计算，再进行方案诊断。"); });
  // 导出结果弹窗
  const closeExp=()=>el("expMask").classList.remove("on");
  el("expClose").addEventListener("click",closeExp);
  el("expCloseBtn").addEventListener("click",closeExp);
  el("expOpen").addEventListener("click",async()=>{
    if(!_expFile) return;
    try{
      const r=await apiCall("open_file",{path:_expFile});
      if(!r.ok) alert("打开失败："+(r.error||"")+"\n\n可手动到输出目录打开该 .doc 文件。");
    }catch(e){ alert("打开失败："+e); }
  });
  el("expReveal").addEventListener("click",async()=>{
    if(!_expFile) return;
    try{
      const r=await apiCall("reveal_file",{path:_expFile});
      if(!r.ok) alert("定位失败："+(r.error||""));
    }catch(e){ alert("定位失败："+e); }
  });
  // 点遮罩空白处关闭
  ["diagMask","sugMask","expMask"].forEach(id=>el(id).addEventListener("click",e=>{
    if(e.target===el(id)) el(id).classList.remove("on"); }));
}
async function boot(){
  busy(true,"加载设计数据库…");
  try{
    META=await apiCall("meta");
    CFG=deep(META.default_cfg);
    // 默认载入首个场景
    const firstKey=Object.keys(META.scenarios)[0];
    if(firstKey){ const s=META.scenarios[firstKey];
      CFG=Object.assign(CFG,deep(s.cfg),{name:s.label,isl_on:!!s.cfg.isl_on}); }
    renderCfgUI();
    bindModal();
    el("scenDesc").textContent=(META.scenarios[firstKey]||{}).desc||"";
    const chips=document.querySelectorAll("#scenChips .chip");
    if(chips.length) chips[0].classList.add("on");
    document.querySelectorAll("nav.tabs button").forEach(b=>b.addEventListener("click",()=>showTab(b.dataset.tab)));
    el("btnSave").addEventListener("click",saveScheme);
    el("btnLoad").addEventListener("click",loadScheme);
    el("btnExport").addEventListener("click",exportWord);
    el("btnPrint").addEventListener("click",printPdf);
    busy(false);
    // 自动首算：快速模式（不含多方案对比），避免首屏长时间忙碌遮罩阻塞操作
    runDesign(false,true);
  }catch(e){ busy(false); alert("初始化失败："+e); }
}
// 双入口：pywebview 桥就绪事件 或 直接启动（HTTP 模式下无需等桥）
document.addEventListener("pywebviewready",()=>{ if(!META) boot(); });
setTimeout(()=>{ if(!META) boot(); },300);
</script>
</body>
</html>
"""

def selftest():
    """无界面自检：验证冻结 exe 内 Python 引擎可正常导入并完成全部场景计算。
    运行：载荷方案设计器.exe --selftest   →   写 payload_designer_selftest.txt"""
    import time
    _bootlog("=== SELFTEST mode (no GUI) ===")
    t0 = time.time()
    lines = ["SELFTEST start py=%s frozen=%s" % (sys.version.split()[0], getattr(sys, "frozen", False))]
    n_ok = 0
    try:
        api = Api()
        m = api.meta()
        lines.append("meta OK keys=%d" % len(m))
        for key, sc in SCENARIOS.items():
            r = api.design(sc["cfg"], with_compare=False)
            ok = bool(r.get("ok"))
            if ok:
                n_ok += 1
                res = r["result"]
                lb = res.get("res", {})
                s = lb.get("summary", {})
                tot = res.get("totals", {})
                lines.append("[%s] OK EIRP=%.2f GT=%.2f M_up=%.2f M_dn=%.2f M_e2e=%.2f "
                             "judge=%s/%s fail=%s warn=%s mass=%.0fkg P=%.0fW plat=%s"
                             % (key, s.get("EIRP", float("nan")), s.get("GT", float("nan")),
                                s.get("M_up", float("nan")), s.get("M_dn", float("nan")),
                                s.get("M_e2e", float("nan")),
                                s.get("judge_pass", "?"), s.get("judge_total", "?"),
                                s.get("fail", []), s.get("warn", []),
                                tot.get("m_pay", 0), tot.get("p_pay", 0),
                                (res.get("platform") or ["", {}])[1].get("id", "?")
                                if isinstance(res.get("platform"), list) else "?"))
            else:
                lines.append("[%s] FAIL %s" % (key, r.get("error", "")[:300]))
        # ---- v5 新增自检：评价标准 / 闭环建议 / 报告光栅化导出 ----
        try:
            import design_engine as DE
            skey = list(SCENARIOS.keys())[0]
            scfg = dict(SCENARIOS[skey]["cfg"])
            R0 = DE.design_all(scfg, KG, skip_compare=True)
            ev0 = R0.get("eval") or {}
            lines.append("eval OK grade=%s feasible=%s pass_hard=%s pass_soft=%s"
                         % (ev0.get("grade"), ev0.get("feasible"),
                            ev0.get("pass_hard"), ev0.get("pass_soft")))
            sg = DE.suggest_closed_loop(scfg, KG, max_iter=3)
            cl = sg.get("closed") or {}
            lines.append("suggest_closed_loop OK grade=%s iters=%s feasible=%s adjustments=%d"
                         % (cl.get("grade"), cl.get("iters"), cl.get("feasible"),
                            len(cl.get("adjustments") or [])))
            er = api.export_html({"cfg": scfg, "name": "selftest报告"})
            if er.get("ok") and er.get("file_path"):
                import io as _io
                doc = _io.open(er["file_path"], encoding="utf-8").read()
                n_png = doc.count("data:image/png")
                n_svg = doc.count("<svg")
                lines.append("export OK chars=%d png=%d svg_left=%d %s"
                             % (len(doc), n_png, n_svg,
                                "RASTERIZED" if n_svg == 0 and n_png > 0 else "SVG-FALLBACK"))
                try:
                    os.remove(er["file_path"])
                except Exception:
                    pass
            else:
                lines.append("export FAIL %s" % str(er.get("error"))[:200])
        except Exception:
            lines.append("V5-CHECK FATAL\n" + _tb.format_exc())
    except Exception:
        lines.append("SELFTEST FATAL\n" + _tb.format_exc())
    dt = time.time() - t0
    head = "SELFTEST %s %d/%d scenarios in %.2fs" % (
        "OK" if n_ok == len(SCENARIOS) else "PARTIAL", n_ok, len(SCENARIOS), dt)
    lines.insert(0, head)
    txt = "\n".join(lines)
    for d in _boot_dirs():
        try:
            with open(os.path.join(d, "payload_designer_selftest.txt"), "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            break
        except Exception:
            pass
    _bootlog(head)
    print(txt)


def guicheck():
    """冻结环境 GUI 依赖自检（不开窗）：完整复现 pywebview edgechromium 平台的
    CLR/.NET 加载链，定位"exe 打开没反应"的真正症结。
    运行：载荷方案设计器.exe --guicheck → 写 payload_designer_guicheck.txt"""
    _bootlog("=== GUICHECK mode (no window) ===")
    lines = ["GUICHECK start frozen=%s PYTHONNET_RUNTIME=%s"
             % (getattr(sys, "frozen", False), os.environ.get("PYTHONNET_RUNTIME"))]

    def step(name, fn):
        try:
            v = fn()
            lines.append("OK   %-38s %s" % (name, v if v is not None else ""))
            return True
        except Exception:
            lines.append("FAIL %-38s\n%s" % (name, _tb.format_exc()))
            return False

    ok = True
    ok &= step("WebView2 Runtime 注册表", lambda: _check_webview2_runtime())
    ok &= step("import clr", lambda: __import__("clr") and "clr imported")

    def _addref():
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Collections")
        clr.AddReference("System.Threading")
        return "WinForms/Collections/Threading"
    ok &= step("clr.AddReference(WinForms...)", _addref)

    def _wf():
        import System.Windows.Forms as WinForms
        from System import String
        return "Application=%s String=%s" % (bool(WinForms.Application), String("x"))
    ok &= step("import System.Windows.Forms", _wf)

    def _interop():
        import clr
        from webview.util import interop_dll_path
        p1 = interop_dll_path("Microsoft.Web.WebView2.Core.dll")
        p2 = interop_dll_path("Microsoft.Web.WebView2.WinForms.dll")
        if not (os.path.exists(p1) and os.path.exists(p2)):
            raise RuntimeError("interop dll 缺失: %s | %s" % (p1, p2))
        clr.AddReference(p1)
        clr.AddReference(p2)
        return "Core+WinForms interop loaded"
    ok &= step("AddReference(WebView2 interop)", _interop)

    def _wv2():
        from Microsoft.Web.WebView2.WinForms import WebView2
        return "WebView2=%s" % bool(WebView2)
    ok &= step("import WebView2 type", _wv2)

    def _platform():
        import webview.platforms.edgechromium as ec
        return "edgechromium module imported"
    ok &= step("import webview edgechromium platform", _platform)

    head = "GUICHECK %s" % ("OK — GUI 依赖完整" if ok else "FAILED — 见上方 FAIL 项")
    lines.insert(0, head)
    txt = "\n".join(lines)
    for d in _boot_dirs():
        try:
            with open(os.path.join(d, "payload_designer_guicheck.txt"), "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            break
        except Exception:
            pass
    _bootlog(head)
    print(txt)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--guicheck" in sys.argv:
        guicheck()
    else:
        main()
