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
    _bootlog("design_data / design_engine imported OK")
except Exception:
    _fatal("无法导入设计引擎模块（design_data / design_engine）：\n" + _tb.format_exc())
    raise

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

    def suggest(self, cfg):
        """按当前配置给出参数建议值（覆盖区/业务/频段/天线联动）。"""
        try:
            return _clean(dict(ok=True, result=DE.suggest_params(cfg, KG)))
        except Exception as e:                          # noqa: BLE001
            import traceback
            return dict(ok=False, error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc()[-800:])

    def js_error(self, msg, src="", line=0, col=0):
        _bootlog("JS-ERROR: %s | %s:%s:%s" % (msg, src, line, col))
        return True


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
                self._json(_api_singleton.suggest(body.get("cfg") or {}))
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
  --rf-up:#b0662c; --rf-dn:#0b5cad; --dig:#7048a8; --opt:#0a7ea4; --if:#5f7183; --ctrl:#8a97a5;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:var(--bg);color:var(--ink);font-size:13px}
#app{max-width:1500px;margin:0 auto;padding:14px 18px 30px}
header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
  border-bottom:3px solid var(--accent);padding-bottom:10px;margin-bottom:12px;flex-wrap:wrap}
header.top h1{font-size:21px;color:var(--accent)}
header.top .sub{color:var(--muted);font-size:12px;margin-top:4px}
.badge-kg{background:var(--infobg);color:var(--info);border:1px solid #c3d4ec;border-radius:10px;
  padding:1px 8px;font-size:11px}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kpi-top{font-size:12px;color:var(--muted)}
.kpi-top b{color:var(--ink);font-size:14px}
.btn{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:6px;
  padding:6px 14px;font-size:13px;cursor:pointer;transition:.15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.solid{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.solid:hover{background:#0a4e92;color:#fff}
.btn.ghost{background:transparent}
.btn:disabled{opacity:.5;cursor:not-allowed}
nav.tabs{display:flex;gap:4px;flex-wrap:wrap;margin:10px 0 12px}
nav.tabs button{border:1px solid var(--line);background:#fff;border-radius:8px 8px 0 0;
  padding:8px 14px;font-size:13px;cursor:pointer;color:var(--muted);border-bottom:none}
nav.tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
section.tab{display:none}
section.tab.on{display:block}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
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
.kpi{background:linear-gradient(180deg,#fbfdff,#f2f7fd);border:1px solid var(--line);
  border-radius:10px;padding:10px 12px}
.kpi .k{font-size:11px;color:var(--muted)}
.kpi .v{font-size:19px;font-weight:700;color:var(--accent);margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .u{font-size:11px;color:var(--muted);font-weight:400}
.kpi.okv .v{color:var(--ok)}.kpi.badv .v{color:var(--bad)}
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
.principle{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.principle .ph{background:var(--chip);padding:8px 13px;font-weight:700;color:var(--accent);cursor:pointer;
  display:flex;justify-content:space-between;align-items:center}
.principle .pb{padding:10px 14px;font-size:12.5px;line-height:1.85;white-space:pre-wrap;color:#2c3e50}
.compare-cur{background:#f0f9f3!important}
footer{margin-top:18px;padding-top:10px;border-top:1px solid var(--line);
  font-size:11px;color:#93a3b4;line-height:1.7}
@media print{
  nav.tabs,.tools,.busy,.chips{display:none!important}
  section.tab{display:block!important;page-break-after:always}
  .panel{break-inside:avoid;border:none}
  body{background:#fff}
}
</style>
</head>
<body>
<div id="app">
  <header class="top">
    <div>
      <h1>通信卫星有效载荷方案设计器</h1>
      <div class="sub">payload-design 五步闭环：需求解析 → 架构规划 → 天线五维选型 + 转发器方案 →
        货架单机选型 → 链路校核（C/N 余量 ≥3dB） ｜ <span class="badge-kg" id="kgver">知识图谱</span></div>
    </div>
    <div class="tools">
      <span class="kpi-top" id="topkpi">EIRP <b>—</b> ｜ G/T <b>—</b> ｜ 余量 <b>—</b> ｜ <span class="tag info">未计算</span></span>
      <button class="btn solid" id="btnSuggest">💡 一键建议值</button>
      <button class="btn" id="btnDiag">🩺 方案诊断</button>
      <button class="btn" id="btnSave">💾 保存方案</button>
      <button class="btn" id="btnLoad">📂 载入方案</button>
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
    if(method==="suggest") return await pywebview.api.suggest(payload.cfg);
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
  const modeCapOpts=[["单波束","单波束"],["多波束","多波束"],["波束跳变","波束跳变"],["在轨重构","在轨重构"]];
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
      cfgField("D_ap","反射面/阵面口径 D (m)","number",null,"固面/伞状用；相控阵为阵面等效口径")+
      cfgField("N_el","阵元数 N_el","number",null,"相控阵用；G=10lg(N_el·η)+G_el−扫描损耗")+
      cfgField("θ_scan","扫描角 (°)","number",null,"相控阵 cos^1.5θ 扫描损耗")+
      cfgField("η_ill","口径效率/照射效率 (%)","number",null,"留空按类型/子体制典型值")+
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

  '<div class="panel"><h2>星间链路与选型偏好</h2>'+
    '<div class="grid g4">'+
      cfgField("isl_type","星间链路","select",islOpts,"LEO/MEO 组网建议激光")+
      cfgField("isl_r_gbps","星间速率 (Gbps)","number",null,"激光终端货架：5/10/20Gbps")+
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
      refreshReqNote();
      // 关键选择项变化 → 防抖刷新建议值提示
      if(["service","orbit","coverage","band","ant_type","array_subtype","mode"].includes(k))
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

/* ---------- 参数建议弹窗：一键建议值 ---------- */
let SUG=null;
async function showSuggest(){
  busy(true,"按当前配置计算建议值…");
  try{
    const cfgOut=deep(CFG); cfgOut.isl_on=!!cfgOut.isl_type;
    const r=await apiCall("suggest",{cfg:cfgOut});
    if(!r.ok){ alert("建议值计算失败：\n"+r.error); return; }
    SUG=r.result;
    const order=["el_deg","A_avail","M_target","life_yr","cov_r_km","beam_r_km","N_beam","B_beam",
      "k_reuse","n_pol","B_carrier","C_req_ovr","GT_term","EIRP_term","EIRP_gs","D_ap","N_el",
      "θ_scan","η_ill","amp_type","P_out","Mode","isl_r_gbps"];
    const cn={el_deg:"最低用户仰角(°)",A_avail:"可用性(%)",M_target:"余量门限(dB)",life_yr:"设计寿命(年)",
      cov_r_km:"覆盖半径(km)",beam_r_km:"波束半径(km)",N_beam:"波束数",B_beam:"单波束带宽(MHz)",
      k_reuse:"复用色数k",n_pol:"极化复用",B_carrier:"单载波带宽(MHz)",C_req_ovr:"容量需求(Gbps)",
      GT_term:"终端G/T(dB/K)",EIRP_term:"终端EIRP(dBW)",EIRP_gs:"关口站EIRP(dBW)",D_ap:"天线口径D(m)",
      N_el:"阵元数N_el","θ_scan":"扫描角(°)","η_ill":"口径效率(%)",amp_type:"功放类型",
      P_out:"功放功率(W)",Mode:"工作模式需求",isl_r_gbps:"星间速率(Gbps)"};
    const rows=order.filter(k=>k in SUG.values).map(k=>{
      const v=SUG.values[k];
      const cur=CFG[k];
      const chg=(cur!==undefined&&cur!==null&&String(cur)!==String(v))?"style='background:#fffbe8'":"";
      return '<div class="sug-item" '+chg+'><span class="sk">'+h(cn[k]||k)+
        '</span><span class="sv">'+h(v===""?"（留空取库默认）":v)+
        '</span><span class="sn">'+h(SUG.notes[k]||"")+'</span></div>';
    }).join("");
    el("sugBody").innerHTML=
      '<div class="note small">黄色底＝与当前配置不同。应用后仅覆盖下表参数，其余配置保持不变；应用后自动快速重算。</div>'+rows;
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
function kpi(k,v,u,cls){ return '<div class="kpi '+(cls||"")+'"><div class="k">'+h(k)+'</div><div class="v">'+
  (typeof v==="string"?h(v):n(v,2))+' <span class="u">'+h(u||"")+'</span></div></div>'; }
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
  el("ov").innerHTML=html;
}
function toF(v,d){ v=parseFloat(v); return isNaN(v)?(d===undefined?0:d):v; }

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
    '处理列随体制变化：透明→IMUX/均衡/开关矩阵；DTP→ADC/交换矩阵/DAC；再生→解调/译码/路由/调制。相控阵体制下功放为分布式 T/R 阵列。</div></div>';
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
  el("ant").innerHTML=html;
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

/* ---------- ⑥ 信息流设计 ---------- */
function flowCards(list){
  return list.map(f=>'<div class="flowcard"><div class="fname">'+h(f.name)+'</div>'+
    '<div class="fpath">'+h(f.path)+'</div>'+
    '<div class="frow"><span>介质：<b>'+h(f.medium)+'</b></span><span>速率：<b>'+h(f.rate)+'</b></span>'+
    '<span>时延：<b>'+h(f.delay)+'</b></span></div>'+
    '<div class="frow"><span>关键点：<b>'+h(f.key)+'</b></span></div></div>').join("");
}
function renderFlow(){
  const F=RES.flows, dn=F.delay_note;
  let html='<div class="panel"><h2>信息流设计（星地 / 星间 / 星内）</h2>'+
  '<div class="note">单跳时延模型：传播 '+n(dn.prop_ms,3)+' ms（斜距/光速）+ 星上处理 '+n(dn.onboard_ms,3)+' ms（'+h(dn.mode)+' 体制）= <b>'+n(dn.total_ms,3)+' ms</b>；'+
  '轨道 '+h(dn.orbit)+'。再生体制星上处理含解调/译码/路由（≈40ms）；DTP 数字信道化 ≈3ms；透明体制仅群时延 ≈0.2μs。</div>';
  html+='<h3>星地信息流（'+F.sg.length+' 条：用户链路 / 馈电链路 / 测控）</h3>'+flowCards(F.sg);
  html+='<h3>星间信息流（'+F.si.length+' 条）</h3>'+flowCards(F.si);
  html+='<h3>星内信息流（'+F.sn.length+' 条：射频 / 数据 / 控制 / 供能）</h3>'+flowCards(F.sn);

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

/* ---------- 页签/保存/打印 ---------- */
function showTab(id){
  document.querySelectorAll("section.tab").forEach(s=>s.classList.toggle("on",s.id===id));
  document.querySelectorAll("nav.tabs button").forEach(b=>b.classList.toggle("on",b.dataset.tab===id));
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
  // 点遮罩空白处关闭
  ["diagMask","sugMask"].forEach(id=>el(id).addEventListener("click",e=>{
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
