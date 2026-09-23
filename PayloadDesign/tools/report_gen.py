# -*- coding: utf-8 -*-
"""完整载荷方案报告生成器 —— 把 design_all 结果 + 接口协议 ICD + 波束方向图
装配为结构化 Word 兼容 HTML 报告（目录/需求/流程/方案/天线链路/转发器/单机选型/接口协议/校验/附录）。

图形全部服务端生成 SVG（Word 2013+ 直接显示）：
  · 载荷架构图（block_diagram 数据 → 列式框图，与前端 renderDiag 同构）
  · 收发链原理图（信息流 stages → 逐级电平/噪声链）
  · GRASP/解析一维方向图 + 二维方向图热力图（Airy 旋转对称/扫描修正）
  · 三维地球覆盖示意图（正交投影 + 海岸线 + 覆盖圈 + 波束栅格 + 卫星）
  · 设计流程图（skill 主链路 SK-INTENT→…→SK-WORD）
"""
from __future__ import annotations

import base64
import datetime
import html as _html
import math
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import grasp_bridge as GB
import protocol_gen as PG
import pattern_engine as PE
import coverage_engine as CE
import orbit_engine as OE


# ================================================================
# SVG → PNG 光栅化（Word 的 HTML 导入滤镜不渲染内嵌 <svg>，必须转位图）
#   用系统自带 Edge headless 截图（WebView2 同内核，目标机必然存在）。
#   失败时回退保留内嵌 SVG（现代 Word/365 部分支持）。
# ================================================================
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_EDGE_CACHE = {"path": None, "probed": False}


def _find_edge():
    if _EDGE_CACHE["probed"]:
        return _EDGE_CACHE["path"]
    _EDGE_CACHE["probed"] = True
    for p in _EDGE_CANDIDATES:
        if os.path.exists(p):
            _EDGE_CACHE["path"] = p
            return p
    # 兜底：PATH 中的 msedge / chrome
    for name in ("msedge.exe", "chrome.exe"):
        w = _which(name)
        if w:
            _EDGE_CACHE["path"] = w
            return w
    return None


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        fp = os.path.join(d, name)
        if os.path.exists(fp):
            return fp
    return None


def _svg_size(svg):
    m = re.search(r'width="(\d+(?:\.\d+)?)"', svg)
    n = re.search(r'height="(\d+(?:\.\d+)?)"', svg)
    w = int(float(m.group(1))) if m else 800
    h = int(float(n.group(1))) if n else 600
    return max(w, 1), max(h, 1)


def svg_to_png_b64(svg, edge=None, scale=2, timeout=40):
    """单张 SVG → PNG base64 data URI；失败返回 None。"""
    edge = edge or _find_edge()
    if not edge:
        return None
    w, h = _svg_size(svg)
    # 限制超大图（架构图可能很宽），等比缩到 ≤1600px 宽再 2x
    wpx = min(w, 1600)
    hpx = int(h * wpx / w) if w else h
    html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            'html,body{margin:0;padding:0;background:#fff;overflow:hidden}'
            'svg{display:block}</style></head><body>' + svg + '</body></html>')
    tmpd = tempfile.mkdtemp(prefix="rpt_svg_")
    tmp_html = os.path.join(tmpd, "s.html")
    out_png = os.path.join(tmpd, "s.png")
    try:
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
               "--hide-scrollbars", "--force-color-profile=srgb",
               "--force-device-scale-factor=%d" % scale,
               "--default-background-color=FFFFFFFF",
               "--window-size=%d,%d" % (wpx, hpx),
               "--screenshot=" + out_png,
               "file:///" + tmp_html.replace("\\", "/")]
        subprocess.run(cmd, capture_output=True, timeout=timeout)
        if os.path.exists(out_png) and os.path.getsize(out_png) > 800:
            with open(out_png, "rb") as f:
                b = base64.b64encode(f.read()).decode("ascii")
            return "data:image/png;base64," + b
    except Exception:                                     # noqa: BLE001
        return None
    finally:
        for p in (tmp_html, out_png):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpd)
        except OSError:
            pass
    return None


_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)


def rasterize_svgs(html, edge=None, max_workers=4, scale=2):
    """把 HTML 中所有 <svg>…</svg> 并行光栅化为 <img src=data:image/png>。
    保留原始宽高（style 限 max-width:100%）。Edge 不可用或全部失败时原样返回。"""
    edge = edge or _find_edge()
    if not edge:
        return html
    blocks = _SVG_RE.findall(html)
    if not blocks:
        return html
    # 去重（相同 SVG 只渲染一次）
    uniq = list(dict.fromkeys(blocks))

    def work(sv):
        uri = svg_to_png_b64(sv, edge=edge, scale=scale)
        return sv, uri

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sv, uri in ex.map(work, uniq):
            if uri:
                results[sv] = uri
    if not results:
        return html

    def repl(m):
        sv = m.group(0)
        uri = results.get(sv)
        if not uri:
            return sv
        w, h = _svg_size(sv)
        return ('<img src="%s" width="%d" height="%d" '
                'style="max-width:100%%;height:auto" alt="diagram"/>' % (uri, w, h))

    return _SVG_RE.sub(repl, html)


# ---------------- 设计流程（与主项目 payload_agent skill 主链路同源） ----------------
SKILL_CHAIN = [
    ("SK-INTENT", "意图解析", "需求理解", "解析一句话/结构化需求 → 轨道/频段/覆盖/业务/体制"),
    ("SK-CLARIFY", "需求澄清", "需求理解", "阻断闸：blocking 缺项必须澄清，禁止擅自假设"),
    ("SK-RETRIEVE", "知识检索", "知识支撑", "从知识图谱取频段规划/平台包络/货架单机/链路公式"),
    ("SK-ANTSEL", "天线选型", "载荷方案", "频段硬过滤 + 五维评分（EIRP/G/T/质量/功耗/模式）"),
    ("SK-EQUIP", "单机选型", "载荷方案", "货架优先三级选型；无货架记缺口 N_gap（不回退错误频段）"),
    ("SK-BUDGET", "链路预算", "指标校核", "上下行/端到端 C/N、MODCOD 反推、余量校核"),
    ("SK-PLAT", "平台选型", "平台运载", "承载/供电/容积匹配（内环：不可行换天线 ≤3 迭代）"),
    ("SK-LAUNCH", "运载选型", "平台运载", "入轨能力/整流罩包络/发射场匹配"),
    ("SK-VALID", "方案校验", "指标校核", "25 条工程约束质量闸（外环：余量否决重选型 ≤2 次）"),
    ("SK-DOC", "方案生成", "成果输出", "结构化方案装配（本报告即 SK-DOC 产物）"),
    ("SK-WORD", "文档导出", "成果输出", "Word/PDF 导出（mso 兼容 HTML）"),
]

EDGE_COLOR = {"rf_up": "#b0662c", "rf_dn": "#0b5cad", "dig": "#7048a8",
              "opt": "#0a7ea4", "if": "#5f7183", "if_": "#5f7183", "ctrl": "#8a97a5"}
NODE_FILL = {"ant": "#eaf1fa", "rf": "#f3f7fb", "amp": "#fdf3e0",
             "dig": "#f3eefb", "opt": "#e6f5f8", "ctrl": "#f1f4f7"}
NODE_STROKE = {"ant": "#7ea3d0", "rf": "#a8bdd4", "amp": "#d9b06a",
               "dig": "#b394dd", "opt": "#79c2d0", "ctrl": "#b0bcc9"}


def e(s):
    return _html.escape(str(s if s is not None else ""))


def f(v, nd=2, d="—"):
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return d
        return ("%%.%df" % nd) % x
    except (TypeError, ValueError):
        return d


def to_f(v, default=0.0):
    """安全转 float（None/空串/NaN/Inf/非数 → default）。"""
    try:
        if v is None or v == "":
            return float(default)
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return float(default)
        return x
    except (TypeError, ValueError):
        return float(default)


# ================================================================
# SVG 1：设计流程图（skill 主链路）
# ================================================================
def svg_flow_chain(active_stage=None):
    W, H = 980, 300
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<defs><marker id="fcarr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
             '<path d="M0,0 L7,3 L0,6 z" fill="#5f7183"/></marker></defs>')
    stages = ["需求理解", "知识支撑", "载荷方案", "指标校核", "平台运载", "成果输出"]
    order = {st: i for i, st in enumerate(stages)}
    # 按阶段分列
    cols = {st: [] for st in stages}
    for sk in SKILL_CHAIN:
        cols[sk[2]].append(sk)
    col_x = {st: 20 + i * 160 for i, st in enumerate(stages)}
    pos = {}
    for st in stages:
        x = col_x[st]
        y = 56
        s.append('<text x="%d" y="30" text-anchor="middle" font-size="13" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (x + 70, e(st)))
        s.append('<rect x="%d" y="40" width="140" height="240" rx="10" fill="none" '
                 'stroke="#dde5ee" stroke-dasharray="4 3"/>' % (x - 4))
        for sk in cols[st]:
            hot = (active_stage == st)
            fill = "#e8f2ff" if hot else NODE_FILL.get("ctrl", "#f1f4f7")
            s.append('<rect x="%d" y="%d" width="132" height="62" rx="8" fill="%s" '
                     'stroke="%s" stroke-width="1.4"/>' % (x, y, fill, "#7ea3d0" if hot else "#b0bcc9"))
            s.append('<text x="%d" y="%d" font-size="10.5" fill="#5f7183" font-weight="bold">%s</text>'
                     % (x + 8, y + 16, e(sk[0])))
            s.append('<text x="%d" y="%d" font-size="12.5" fill="#1c2733" font-weight="700">%s</text>'
                     % (x + 8, y + 34, e(sk[1])))
            note = sk[3]
            # 截断到两行
            l1 = note[:17]
            l2 = note[17:34]
            s.append('<text x="%d" y="%d" font-size="9" fill="#5f7183">%s%s</text>'
                     % (x + 8, y + 50, e(l1), e("…" if len(note) > 34 else "")))
            if l2:
                s.append('<text x="%d" y="%d" font-size="9" fill="#5f7183">%s</text>'
                         % (x + 8, y + 60, e(l2)))
            pos[sk[0]] = (x, y)
            y += 76
    # 主链路箭头
    seq = [sk[0] for sk in SKILL_CHAIN]
    for a, b in zip(seq[:-1], seq[1:]):
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        ax, ay = x1 + 132, y1 + 31
        bx, by = x2, y2 + 31
        mx = (ax + bx) / 2
        s.append('<path d="M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="none" '
                 'stroke="#5f7183" stroke-width="1.6" marker-end="url(#fcarr)"/>'
                 % (ax, ay, mx, ay, mx, by, bx, by))
    # 回环虚线（内环/外环）
    x1, y1 = pos["SK-PLAT"]
    x2, y2 = pos["SK-ANTSEL"]
    s.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="#c0392b" stroke-width="1.3" '
             'stroke-dasharray="5 4" marker-end="url(#fcarr)"/>'
             % (x1 + 66, y1, x1 + 66, y1 - 40, x2 + 66, y2 + 100, x2 + 66, y2 + 62))
    s.append('<text x="%d" y="%d" font-size="9.5" fill="#c0392b" text-anchor="middle">内环：平台不可行→换天线（≤3 迭代）</text>'
             % ((x1 + x2) // 2 + 66, y1 - 44))
    x1, y1 = pos["SK-VALID"]
    x2, y2 = pos["SK-ANTSEL"]
    s.append('<text x="%d" y="%d" font-size="9.5" fill="#b07514" text-anchor="middle">外环：链路余量否决→天线重选型（≤2 次）</text>'
             % (x1 + 70, 292))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 2：载荷架构图（block_diagram 数据，与前端 renderDiag 同构）
# ================================================================
def svg_architecture(diagram):
    D = diagram or {}
    cols = D.get("cols") or []
    nodes = D.get("nodes") or []
    edges = D.get("edges") or []
    COLW, NODEW, NODEH0, GAPY, TOP = 236, 214, 50, 13, 54
    by_col = {}
    for nd in nodes:
        by_col.setdefault(nd["col"], []).append(nd)
    pos, max_rows = {}, 0
    for c in cols:
        lst = by_col.get(c["id"], [])
        max_rows = max(max_rows, len(lst))
        y = TOP
        for nd in lst:
            lines = str(nd.get("cn", "")).split("\n")
            hh = NODEH0 + (len(lines) - 1) * 15 + (14 if nd.get("note") else 0)
            pos[nd["id"]] = dict(x=c["x"] * COLW + 12, y=y, w=NODEW, h=hh, col=c["x"])
            y += hh + GAPY
    W = max(len(cols), 1) * COLW
    H = TOP + max_rows * (NODEH0 + GAPY) + 90
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    mk = "".join('<marker id="ar_%s" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
                 '<path d="M0,0 L7,3 L0,6 z" fill="%s"/></marker>' % (k, v)
                 for k, v in EDGE_COLOR.items() if k != "if_")
    s.append('<defs><marker id="ar_def" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
             '<path d="M0,0 L7,3 L0,6 z" fill="#5f7183"/></marker>%s</defs>' % mk)
    for c in cols:
        s.append('<text x="%d" y="30" text-anchor="middle" font-size="13.5" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (c["x"] * COLW + 12 + NODEW // 2, e(c["cn"])))
        s.append('<rect x="%d" y="40" width="%d" height="%d" rx="10" fill="none" '
                 'stroke="#dde5ee" stroke-dasharray="4 3"/>' % (c["x"] * COLW + 8, NODEW + 8, H - 52))
    for nd in nodes:
        p = pos.get(nd["id"])
        if not p:
            continue
        fill = NODE_FILL.get(nd.get("kind"), NODE_FILL["rf"])
        st = NODE_STROKE.get(nd.get("kind"), NODE_STROKE["rf"])
        s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" stroke="%s" '
                 'stroke-width="1.4"/>' % (p["x"], p["y"], p["w"], p["h"], fill, st))
        lines = str(nd.get("cn", "")).split("\n")
        for i, ln in enumerate(lines):
            s.append('<text x="%d" y="%d" font-size="11.5" font-weight="%s" fill="#1c2733">%s</text>'
                     % (p["x"] + 9, p["y"] + 18 + i * 15, 700 if i == 0 else 400, e(ln[:24])))
        yy = p["y"] + 18 + len(lines) * 15
        if nd.get("qty") and int(nd["qty"]) > 1:
            s.append('<text x="%d" y="%d" text-anchor="end" font-size="10.5" fill="#0b5cad">×%s</text>'
                     % (p["x"] + p["w"] - 9, p["y"] + 18, nd["qty"]))
        if nd.get("note"):
            s.append('<text x="%d" y="%d" font-size="9.5" fill="#5f7183">%s</text>'
                     % (p["x"] + 9, yy, e(str(nd["note"])[:36])))
    for ed in edges:
        a, b = pos.get(ed["f"]), pos.get(ed["t"])
        if not a or not b:
            continue
        col = EDGE_COLOR.get(ed.get("kind"), EDGE_COLOR["if"])
        if b["col"] > a["col"]:
            x1, y1, x2, y2 = a["x"] + a["w"], a["y"] + a["h"] / 2, b["x"], b["y"] + b["h"] / 2
        elif b["col"] < a["col"]:
            x1, y1, x2, y2 = a["x"], a["y"] + a["h"] / 2, b["x"] + b["w"], b["y"] + b["h"] / 2
        else:
            x1, y1, x2, y2 = a["x"] + a["w"] / 2, a["y"] + a["h"], b["x"] + b["w"] / 2, b["y"]
        mx = (x1 + x2) / 2
        s.append('<path d="M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="none" stroke="%s" '
                 'stroke-width="1.7" marker-end="url(#ar_%s)"/>'
                 % (x1, y1, mx, y1, mx, y2, x2, y2, col,
                    ed.get("kind") if ed.get("kind") in EDGE_COLOR and ed.get("kind") != "if_" else "def"))
        if ed.get("label"):
            s.append('<text x="%.0f" y="%.0f" text-anchor="middle" font-size="9.5" fill="%s">%s</text>'
                     % ((x1 + x2) / 2, (y1 + y2) / 2 - 5, col, e(str(ed["label"])[:26])))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 3：收发链原理图（信息流 stages）
# ================================================================
def svg_rx_chain(stages, title, direction="rx"):
    """stages: [{cn,g_db,nf_db,p_in_dbw,p_out_dbw,...}]"""
    if not stages:
        return ""
    BW, BH, GAP = 128, 66, 34
    W = len(stages) * (BW + GAP) + 40
    H = BH + 118
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<defs><marker id="charr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
             '<path d="M0,0 L7,3 L0,6 z" fill="#5f7183"/></marker></defs>')
    s.append('<text x="20" y="24" font-size="13" font-weight="bold" fill="#0b5cad">%s</text>' % e(title))
    cum = 0.0
    for i, st in enumerate(stages):
        x = 20 + i * (BW + GAP)
        y = 44
        g = st.get("g_db")
        try:
            cum += float(g or 0)
        except (TypeError, ValueError):
            pass
        fill = "#fdf3e0" if st.get("kind") == "amp" else ("#eaf1fa" if st.get("kind") == "ant" else "#f3f7fb")
        stroke = "#d9b06a" if st.get("kind") == "amp" else ("#7ea3d0" if st.get("kind") == "ant" else "#a8bdd4")
        s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="7" fill="%s" stroke="%s" stroke-width="1.3"/>'
                 % (x, y, BW, BH, fill, stroke))
        nm = str(st.get("cn") or st.get("id") or "")[:11]
        s.append('<text x="%d" y="%d" font-size="11" font-weight="700" fill="#1c2733" text-anchor="middle">%s</text>'
                 % (x + BW // 2, y + 20, e(nm)))
        if g is not None:
            s.append('<text x="%d" y="%d" font-size="10" fill="#5f7183" text-anchor="middle">G %s dB</text>'
                     % (x + BW // 2, y + 38, f(g, 1)))
        if st.get("nf_db") is not None and direction == "rx":
            s.append('<text x="%d" y="%d" font-size="10" fill="#5f7183" text-anchor="middle">NF %s dB</text>'
                     % (x + BW // 2, y + 54, f(st.get("nf_db"), 1)))
        # 级间电平
        if i < len(stages) - 1:
            x2 = x + BW
            s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#5f7183" stroke-width="1.6" '
                     'marker-end="url(#charr)"/>' % (x2, y + BH // 2, x2 + GAP - 4, y + BH // 2))
        pout = st.get("p_out_dbw")
        if pout is not None:
            s.append('<text x="%d" y="%d" font-size="9.5" fill="#0b5cad" text-anchor="middle">%s dBW</text>'
                     % (x + BW // 2, y + BH + 16, f(pout, 1)))
        if direction == "rx" and st.get("T_contrib") is not None:
            s.append('<text x="%d" y="%d" font-size="9.5" fill="#b07514" text-anchor="middle">+T %s K</text>'
                     % (x + BW // 2, y + BH + 30, f(st.get("T_contrib"), 0)))
        if st.get("cum_g_db") is not None:
            s.append('<text x="%d" y="%d" font-size="9.5" fill="#7048a8" text-anchor="middle">ΣG %s dB</text>'
                     % (x + BW // 2, y + BH + (44 if direction == "rx" else 30), f(st.get("cum_g_db"), 1)))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 4：一维方向图（GRASP/解析数据）
# ================================================================
def svg_pattern_1d(B, W=620, H=340):
    th = B.get("theta") or []
    gd = B.get("gain_dbr") or []
    if not th or not gd:
        return ""
    span = max(abs(th[0]), abs(th[-1]), 0.1)
    PL, PR, PT, PB = 52, 16, 18, 42
    X = lambda t: PL + (t + span) / (2 * span) * (W - PL - PR)          # noqa: E731
    Yq = lambda g: PT + (1 - (min(max(g, -40), 0) + 40) / 40) * (H - PT - PB)   # noqa: E731
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#fbfdff" stroke="#dde5ee"/>'
             % (PL, PT, W - PL - PR, H - PT - PB))
    g = 0
    while g >= -40:
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (PL, Yq(g), W - PR, Yq(g), "#b8c6d6" if g == 0 else "#e8eef5"))
        s.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" fill="#5f7183">%d</text>'
                 % (PL - 6, Yq(g) + 4, g))
        g -= 10
    tstep = 2 if span > 6 else (1 if span > 2 else 0.5)
    t = -span
    while t <= span + 1e-9:
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#eef2f7"/>' % (X(t), PT, X(t), H - PB))
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="10" fill="#5f7183">%s</text>'
                 % (X(t), H - PB + 15, f(t, 1)))
        t += tstep
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#c0392b" stroke-dasharray="5 4" '
             'stroke-width="1.2"/><text x="%d" y="%.1f" text-anchor="end" font-size="10" '
             'fill="#c0392b">−3dB</text>' % (PL, Yq(-3), W - PR, Yq(-3), W - PR - 4, Yq(-3) - 4))
    edge = B.get("coverage_edge_dbr")
    if edge is not None and -40 < float(edge) < 0:
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#b07514" stroke-dasharray="3 3" '
                 'stroke-width="1.2"/><text x="%d" y="%.1f" text-anchor="end" font-size="10" '
                 'fill="#b07514">覆盖边缘 %sdBr</text>'
                 % (PL, Yq(float(edge)), W - PR, Yq(float(edge)), W - PR - 4, Yq(float(edge)) - 4,
                    f(edge, 1)))
    pts = " ".join("%.1f,%.1f" % (X(th[i]), Yq(gd[i])) for i in range(len(th)))
    s.append('<polyline points="%s" fill="none" stroke="#0b5cad" stroke-width="2"/>' % pts)
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="11" fill="#5f7183">离轴角 θ (°)</text>'
             % (W // 2, H - 6))
    s.append('<text x="14" y="%d" font-size="11" fill="#5f7183">G (dBr)</text>' % (PT - 5))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 5：二维方向图（θx-θy 平面热力图 + −3dB 等值圈）
# ================================================================
def _airy(u):
    if abs(u) < 1e-9:
        return 0.0
    v = 2.0 * GB._j1(u) / u
    return 20.0 * math.log10(abs(v)) if abs(v) > 1e-12 else -120.0


def pattern_2d_grid(B, D, freq_ghz, n=61, scan_deg=0.0, scan_phi_deg=0.0):
    """二维方向图网格（dBr）：口径 Airy 旋转对称 + 相控阵扫描 cos^1.5 单元因子修正。
    返回 dict(theta_x[], theta_y[], grid[[dBr]], th3, span)。"""
    lam = GB.lam_m(freq_ghz)
    kD = math.pi * D / lam
    th3 = float(B.get("beamwidth_3db_deg") or max(0.2, math.degrees(1.02 * lam / D)))
    span = min(max(th3 * 3.2, 1.0), 40.0)
    step = 2 * span / (n - 1)
    txs = [-span + i * step for i in range(n)]
    tys = [-span + i * step for i in range(n)]
    sx = math.sin(math.radians(scan_deg)) * math.cos(math.radians(scan_phi_deg))
    sy = math.sin(math.radians(scan_deg)) * math.sin(math.radians(scan_phi_deg))
    grid = []
    for ty in tys:
        row = []
        for tx in txs:
            # 离轴角（含扫描偏置）：sinθ 分量合成
            ux = math.sin(math.radians(tx)) - sx
            uy = math.sin(math.radians(ty)) - sy
            u = kD * math.sqrt(ux * ux + uy * uy)
            g = _airy(u)
            if scan_deg:
                # 单元方向图扫描损耗近似 cos^1.5(θ_off)
                cos_t = math.cos(math.radians(tx)) * math.cos(math.radians(ty))
                g += 15.0 * math.log10(max(cos_t, 0.05))
            row.append(max(g, -40.0))
        grid.append(row)
    return dict(theta_x=[round(t, 3) for t in txs], theta_y=[round(t, 3) for t in tys],
                grid=[[round(v, 2) for v in row] for row in grid],
                th3=round(th3, 3), span=round(span, 2))


def _heat(v):
    """dBr → 热力色（蓝→青→绿→黄→红），-40..0。"""
    t = min(max((v + 40.0) / 40.0, 0.0), 1.0)
    stops = [(0.0, (13, 30, 74)), (0.30, (11, 92, 173)), (0.55, (10, 126, 164)),
             (0.75, (29, 138, 78)), (0.90, (230, 190, 40)), (1.0, (214, 69, 45))]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return "#%02x%02x%02x" % tuple(int(c0[j] + k * (c1[j] - c0[j])) for j in range(3))
    return "#%02x%02x%02x" % stops[-1][1]


def svg_pattern_2d(B, D, freq_ghz, scan_deg=0.0, W=560, H=430, n=61):
    p2 = pattern_2d_grid(B, D, freq_ghz, n=n, scan_deg=scan_deg)
    txs, tys, grid = p2["theta_x"], p2["theta_y"], p2["grid"]
    PL, PT = 62, 46
    cw = (W - PL - 90) / n
    ch = (H - PT - 60) / n
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<text x="%d" y="24" text-anchor="middle" font-size="12.5" font-weight="bold" '
             'fill="#0b5cad">二维远场方向图（θx–θy 平面 · dBr）%s</text>'
             % (W // 2 - 20, "（扫描 %s°）" % f(scan_deg, 0) if scan_deg else ""))
    for iy in range(n):
        for ix in range(n):
            x = PL + ix * cw
            y = PT + (n - 1 - iy) * ch
            s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="none"/>'
                     % (x, y, cw + 0.6, ch + 0.6, _heat(grid[iy][ix])))
    # 坐标轴刻度
    span = p2["span"]
    tstep = 1 if span <= 6 else (5 if span <= 20 else 10)
    t = -int(span // tstep) * tstep
    while t <= span + 1e-9:
        px = PL + (t + span) / (2 * span) * n * cw
        py = PT + (span - t) / (2 * span) * n * ch
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="9.5" fill="#5f7183">%s</text>'
                 % (px, H - 36, f(t, 0)))
        s.append('<text x="%d" y="%.1f" text-anchor="end" font-size="9.5" fill="#5f7183">%s</text>'
                 % (PL - 6, py + 3, f(t, 0)))
        t += tstep
    s.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="#93a3b4"/>'
             % (PL, PT, n * cw, n * ch))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="11" fill="#5f7183">θx (°)</text>'
             % (PL + n * cw / 2, H - 20))
    s.append('<text x="18" y="%d" text-anchor="middle" font-size="11" fill="#5f7183" '
             'transform="rotate(-90 18 %d)">θy (°)</text>' % (PT + n * ch / 2, PT + n * ch / 2))
    # −3dB 等值圈（椭圆近似：圆口径旋转对称 → 圆）
    r3 = p2["th3"] / 2
    px3 = PL + n * cw / 2 + (0 if not scan_deg else (math.sin(math.radians(scan_deg)) * n * cw / 2
                                                      / math.sin(math.radians(span)) if span > 0 else 0))
    s.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#fff" stroke-width="1.4" '
             'stroke-dasharray="4 3"/><text x="%.1f" y="%.1f" font-size="9.5" fill="#fff">−3dB</text>'
             % (px3, PT + n * ch / 2, r3 / span * n * cw / 2, px3 + 4, PT + n * ch / 2 - r3 / span * n * ch / 2 - 4))
    # 色标
    lx = W - 64
    for i in range(40):
        v = -40 + i
        s.append('<rect x="%d" y="%.1f" width="16" height="%.1f" fill="%s"/>'
                 % (lx, PT + (39 - i) * (n * ch / 40), n * ch / 40 + 0.5, _heat(v)))
    s.append('<rect x="%d" y="%d" width="16" height="%d" fill="none" stroke="#93a3b4"/>'
             % (lx, PT, int(n * ch)))
    for gv in (0, -10, -20, -30, -40):
        gy = PT + (-gv) / 40.0 * n * ch
        s.append('<text x="%d" y="%.1f" font-size="9.5" fill="#5f7183">%d</text>' % (lx + 20, gy + 3, gv))
    s.append('</svg>')
    return "".join(s), p2


# ================================================================
# SVG 6：三维地球覆盖示意图（正交投影，静态默认视角；前端另有可交互版）
# ================================================================
def _ortho(lat, lon, lat0, lon0, R_px, cx, cy):
    """正交投影：返回 (x, y, visible)。"""
    la, lo = math.radians(lat), math.radians(lon)
    la0, lo0 = math.radians(lat0), math.radians(lon0)
    cosc = math.sin(la0) * math.sin(la) + math.cos(la0) * math.cos(la) * math.cos(lo - lo0)
    x = cx + R_px * math.cos(la) * math.sin(lo - lo0)
    y = cy - R_px * (math.cos(la0) * math.sin(la) - math.sin(la0) * math.cos(la) * math.cos(lo - lo0))
    return x, y, cosc > 0


def _circle_points(lat1, lon1, r_deg, n=90):
    la1, lo1, r = math.radians(lat1), math.radians(lon1), math.radians(r_deg)
    pts = []
    for i in range(n + 1):
        br = 2 * math.pi * i / n
        la2 = math.asin(math.sin(la1) * math.cos(r) + math.cos(la1) * math.sin(r) * math.cos(br))
        lo2 = lo1 + math.atan2(math.sin(br) * math.sin(r) * math.cos(la1),
                               math.cos(r) - math.sin(la1) * math.sin(la2))
        pts.append((math.degrees(la2), math.degrees(lo2)))
    return pts


def svg_globe_3d(R, world_land=None, W=680, H=620, lat0=None, lon0=None):
    """静态三维地球（正交投影）：海岸线 + 经纬网 + 覆盖圈 + 波束栅格 + 卫星。"""
    cfg = R.get("cfg") or {}
    geo = R.get("geo") or {}
    cov = (R.get("_cov_meta") or {})
    lat0 = lat0 if lat0 is not None else float(cov.get("lat") or 0)
    lon0 = lon0 if lon0 is not None else float(
        cov.get("lon", cov.get("geo_lon", 0)) or 0)
    alt = float((R.get("_orbit_alt_km") or 35786))
    R_e = 6371.0
    cx, cy, Rg = W / 2, H / 2 + 30, min(W, H) * 0.36
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<defs><radialGradient id="g3d" cx="38%" cy="34%" r="75%">'
             '<stop offset="0" stop-color="#eaf4ff"/><stop offset="0.55" stop-color="#bcd8f2"/>'
             '<stop offset="1" stop-color="#6f9fc9"/></radialGradient>'
             '<radialGradient id="covg3" cx="50%" cy="50%" r="50%">'
             '<stop offset="0" stop-color="#0b5cad" stop-opacity=".45"/>'
             '<stop offset="0.8" stop-color="#0b5cad" stop-opacity=".22"/>'
             '<stop offset="1" stop-color="#0b5cad" stop-opacity="0"/></radialGradient></defs>')
    # 球体
    s.append('<circle cx="%.0f" cy="%.0f" r="%.0f" fill="url(#g3d)" stroke="#4a6fa5" stroke-width="1.4"/>'
             % (cx, cy, Rg))
    # 经纬网
    for lon in range(-180, 180, 30):
        pts = []
        for la in range(-90, 91, 3):
            x, y, vis = _ortho(la, lon, lat0, lon0, Rg, cx, cy)
            pts.append((x, y, vis))
        d, drawing = "", False
        for x, y, vis in pts:
            if vis:
                d += ("M%.1f,%.1f" % (x, y)) if not drawing else ("L%.1f,%.1f" % (x, y))
                drawing = True
            else:
                drawing = False
        if d:
            s.append('<path d="%s" fill="none" stroke="#ffffff" stroke-width=".55" opacity=".55"/>' % d)
    for lat in range(-60, 90, 30):
        pts = []
        for lo in range(-180, 181, 3):
            x, y, vis = _ortho(lat, lo, lat0, lon0, Rg, cx, cy)
            pts.append((x, y, vis))
        d, drawing = "", False
        for x, y, vis in pts:
            if vis:
                d += ("M%.1f,%.1f" % (x, y)) if not drawing else ("L%.1f,%.1f" % (x, y))
                drawing = True
            else:
                drawing = False
        if d:
            s.append('<path d="%s" fill="none" stroke="#ffffff" stroke-width=".55" opacity=".55"/>' % d)
    # 海岸线（仅海岸线，无政治边界 —— 地图合规）
    q = float((world_land or {}).get("q") or 4)
    for poly in (world_land or {}).get("polys") or []:
        d, drawing = "", False
        for i in range(0, len(poly) - 1, 2):
            lon, lat = poly[i] / q, poly[i + 1] / q
            x, y, vis = _ortho(lat, lon, lat0, lon0, Rg, cx, cy)
            if vis:
                d += ("M%.1f,%.1f" % (x, y)) if not drawing else ("L%.1f,%.1f" % (x, y))
                drawing = True
            else:
                drawing = False
        if d:
            s.append('<path d="%s" fill="#cfe0d2" fill-opacity=".9" stroke="#7fa887" '
                     'stroke-width=".5" stroke-linejoin="round"/>' % d)
    # 单星视域圈（大圆 psi）
    psi = float(geo.get("psi_cov_deg") or 17.3)
    for label, rdeg, color, dash, wid in (
            ("单星视域", psi, "#0b5cad", "6 4", 1.6),
            ("覆盖区", float(cov.get("r_km") or 1500) / R_e * (180 / math.pi), "#c0392b", "", 2.0)):
        pts = _circle_points(lat0 if abs(lat0) > 0.01 else 0.0, lon0, rdeg)
        d, drawing = "", False
        any_vis = False
        for la, lo in pts:
            x, y, vis = _ortho(la, lo, lat0, lon0, Rg, cx, cy)
            any_vis = any_vis or vis
            if vis:
                d += ("M%.1f,%.1f" % (x, y)) if not drawing else ("L%.1f,%.1f" % (x, y))
                drawing = True
            else:
                drawing = False
        if d:
            s.append('<path d="%s" fill="none" stroke="%s" stroke-width="%.1f"%s opacity=".85"/>'
                     % (d, color, wid, ' stroke-dasharray="%s"' % dash if dash else ""))
    # 覆盖区填充（中心区渐变圆近似：投影后为椭圆，用视域内小圆）
    sx, sy, _ = _ortho(0.0 if abs(lat0) < 0.01 else lat0, lon0, lat0, lon0, Rg, cx, cy)
    cov_r_deg = float(cov.get("r_km") or 1500) / R_e * (180 / math.pi)
    r_px = math.sin(math.radians(cov_r_deg)) / max(math.sin(math.radians(90)), 1e-9) * Rg
    s.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="url(#covg3)"/>' % (sx, sy, max(r_px, 4)))
    # 波束栅格（中心波束 + 一环示意，k 色复用）
    trp = R.get("transponder") or {}
    Nb = int(trp.get("N_beam") or 1)
    if Nb > 1:
        k = max(1, int(R.get("cfg", {}).get("k_reuse") or 4))
        PALETTE = ["#0b5cad", "#c0392b", "#1d8a4e", "#b07514", "#7048a8", "#0a7ea4", "#d1568c"]
        br_deg = float(cov.get("beam_r_km") or 250) / R_e * (180 / math.pi)
        beam_pts = [(lat0 if abs(lat0) > 0.01 else 0.0, lon0)]
        ring6 = _circle_points(lat0 if abs(lat0) > 0.01 else 0.0, lon0, br_deg * 1.75, 6)
        for j in range(6):
            beam_pts.append(ring6[j])
        for i, (bla, blo) in enumerate(beam_pts[:7]):
            pts = _circle_points(bla, blo, br_deg, 24)
            d, drawing, any_vis = "", False, False
            for la, lo in pts:
                x, y, vis = _ortho(la, lo, lat0, lon0, Rg, cx, cy)
                any_vis = any_vis or vis
                if vis:
                    d += ("M%.1f,%.1f" % (x, y)) if not drawing else ("L%.1f,%.1f" % (x, y))
                    drawing = True
                else:
                    drawing = False
            if d:
                col = PALETTE[i % k]
                s.append('<path d="%sZ" fill="%s" fill-opacity=".30" stroke="%s" stroke-width=".9"/>'
                         % (d, col, col))
        s.append('<text x="%.0f" y="%.0f" text-anchor="middle" font-size="10.5" fill="#083a6b" '
                 'font-weight="700">%d 波束（示意 7，k=%d 色复用）</text>' % (sx, sy + 4, Nb, k))
    # 星下点
    s.append('<g><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c0392b" stroke-width="1.8"/>'
             '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c0392b" stroke-width="1.8"/>'
             '<circle cx="%.1f" cy="%.1f" r="3.2" fill="#c0392b"/></g>'
             % (sx - 8, sy, sx + 8, sy, sx, sy - 8, sx, sy + 8, sx, sy))
    # 卫星（沿星下点方向抬升）—— 显示距离与地球拉开，便于观察波束锥
    # 真实 GEO 比例 6.6Re 会把卫星画到画布外；改为「地表 + 观察间隙」并夹取在画布内。
    r_true = Rg * (R_e + alt) / R_e
    gap = Rg * 0.55                       # 地表到卫星的最小可视间隙（0.55×地球半径）
    r_disp = min(max(r_true * 0.42, Rg + gap), min(W, H) * 0.485)
    la_s = 0.0 if abs(lat0) < 0.01 else lat0
    x3, y3, vis3 = _ortho(la_s, lon0, lat0, lon0, r_disp, cx, cy)
    if vis3:
        ang = math.atan2(y3 - cy, x3 - cx)
        bx, by = cx + r_disp * math.cos(ang), cy + r_disp * math.sin(ang)
        s.append('<g transform="translate(%.1f,%.1f) rotate(%.1f)">'
                 '<rect x="-13" y="-6" width="26" height="12" rx="3" fill="#0b5cad" stroke="#083a6b"/>'
                 '<rect x="-34" y="-4" width="18" height="8" rx="1.5" fill="#0a7ea4" stroke="#083a6b"/>'
                 '<rect x="16" y="-4" width="18" height="8" rx="1.5" fill="#0a7ea4" stroke="#083a6b"/>'
                 '<circle cx="0" cy="8" r="2.6" fill="#b0662c"/></g>' % (bx, by, math.degrees(ang) + 90))
        # 星下点连线（星地链路示意）
        s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#0b5cad" '
                 'stroke-width=".9" stroke-dasharray="2 3" opacity=".6"/>' % (bx, by, sx, sy))
        # 波束锥（卫星 → 覆盖圈边缘 4 点）
        ring4 = _circle_points(la_s, lon0, cov_r_deg, 4)
        for j in range(4):
            la_e, lo_e = ring4[j]
            ex, ey, evis = _ortho(la_e, lo_e, lat0, lon0, Rg, cx, cy)
            if evis:
                s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#b07514" '
                         'stroke-width="1" stroke-dasharray="3 3" opacity=".8"/>' % (bx, by, ex, ey))
        s.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="11" fill="#1c2733" '
                 'font-weight="700">🛰 %s · h=%skm</text>' % (bx, by - 22, e(cfg.get("orbit", "GEO")),
                                                              f(alt, 0)))
    # 标题/图例
    s.append('<text x="%d" y="24" text-anchor="middle" font-size="13.5" font-weight="bold" '
             'fill="#0b5cad">三维覆盖示意图（正交投影 · 视角中心 %s°/%s°）</text>'
             % (W // 2, f(lat0, 1), f(lon0, 1)))
    ly = H - 62
    s.append('<rect x="16" y="%d" width="%d" height="52" rx="8" fill="#fff" fill-opacity=".9" '
             'stroke="#dde5ee"/>' % (ly, W - 32))
    s.append('<line x1="28" y1="%d" x2="52" y2="%d" stroke="#0b5cad" stroke-width="1.6" '
             'stroke-dasharray="5 3"/><text x="58" y="%d" font-size="10" fill="#5f7183">单星视域（±%s°）</text>'
             % (ly + 16, ly + 16, ly + 19, f(psi, 2)))
    s.append('<line x1="28" y1="%d" x2="52" y2="%d" stroke="#c0392b" stroke-width="2"/>'
             '<text x="58" y="%d" font-size="10" fill="#5f7183">目标覆盖区 R=%skm</text>'
             % (ly + 34, ly + 34, ly + 37, f(cov.get("r_km") or 0, 0)))
    s.append('<circle cx="%.0f" cy="%d" r="6" fill="url(#covg3)" stroke="#0a7ea4"/>'
             '<text x="%.0f" y="%d" font-size="10" fill="#5f7183">波束栅格（k 色频率复用示意）· '
             '示意图：仅海岸线，无政治边界</text>' % (W - 420, ly + 16, W - 408, ly + 19))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 7：信息流框架图（泳道分层：类别泳道 × 功能层列，服务端复刻前端 renderInfoFlowDiagram）
# ================================================================


def svg_info_flow(flows, cfg=None):
    """信息流框架图（泳道分层，与前端 renderInfoFlowDiagram 同构）：
    行=信息流类别泳道（业务/数据/控制/能量），列=功能层 L1..L8（stages_def），
    每条流一行、节点按功能层落列、同层合并 → 连线全部水平向右，无交叉。
    空间段（星地/星间/星内）以行内徽标标注。Word 报告静态版（无动画）。"""
    flows = flows or {}
    cfg = cfg or {}
    tiers = flows.get("tiers") or []
    levels = flows.get("levels") or []
    stages_def = flows.get("stages_def") or []
    allf = flows.get("all") or list(flows.get("sg") or []) + \
        list(flows.get("si") or []) + list(flows.get("sn") or [])
    tier_of = flows.get("tier_of") or {}
    LV_CN = {"sg": "星地", "si": "星间", "sn": "星内"}
    ROWH, HDR, LANE_L, IDW = 46, 92, 128, 150
    W = 1080
    n_cols = max(len(stages_def), 8)
    COLW = (W - LANE_L - IDW - 20) // n_cols
    order = [sd[0] for sd in stages_def]
    layer_idx = {k: i for i, k in enumerate(order)}

    def col_x(gi):
        return LANE_L + IDW + gi * COLW + 6

    # 泳道数据
    lanes = []
    for t in tiers:
        gs = [dict(lv=l, lst=[f for f in allf if f.get("tier") == t["key"] and f.get("level") == l["key"]])
              for l in levels]
        gs = [g for g in gs if g["lst"]]
        if gs:
            lanes.append(dict(tier=t, gs=gs, n=sum(len(g["lst"]) for g in gs)))
    H = HDR + sum(28 + ln["n"] * ROWH + 8 for ln in lanes) + 22
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<defs><marker id="ifarr" markerWidth="9" markerHeight="9" refX="8" refY="3.2" orient="auto">'
             '<path d="M0,0 L8,3.2 L0,6.4 z" fill="#5f7183"/></marker>'
             '<linearGradient id="ifhdr" x1="0" y1="0" x2="1" y2="0">'
             '<stop offset="0" stop-color="#0a3a6b"/><stop offset="1" stop-color="#0a7ea4"/></linearGradient></defs>')
    dn = (flows.get("delay_note") or {})
    s.append('<rect x="14" y="6" width="%d" height="26" rx="8" fill="url(#ifhdr)"/>' % (W - 28))
    s.append('<text x="%d" y="23" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">'
             '🛰 %s · %s体制 ｜ 单跳时延 %s ms（传播 %s + 星上 %s）</text>'
             % (W // 2, e(cfg.get("name") or "卫星方案"), e(dn.get("mode") or ""),
                f(dn.get("total_ms"), 2), f(dn.get("prop_ms"), 2), f(dn.get("onboard_ms"), 2)))
    # 列头（功能层）
    s.append('<rect x="%d" y="40" width="%d" height="40" rx="8" fill="#eef1f5" stroke="#dde5ee"/>'
             '<text x="%d" y="56" text-anchor="middle" font-size="10.5" font-weight="700" fill="#2c3e50">信息流（泳道）</text>'
             '<text x="%d" y="71" text-anchor="middle" font-size="8.5" fill="#5f7183">名称 / 空间段</text>'
             % (LANE_L, IDW, LANE_L + IDW // 2, LANE_L + IDW // 2))
    for i, sd in enumerate(stages_def):
        x = col_x(i)
        bw = COLW - 12
        s.append('<rect x="%d" y="40" width="%d" height="40" rx="8" fill="#eaf1fa" stroke="#c9daee"/>'
                 '<text x="%d" y="56" text-anchor="middle" font-size="10" font-weight="700" fill="#0b5cad">%s</text>'
                 '<text x="%d" y="71" text-anchor="middle" font-size="8.5" fill="#2c3e50">%s</text>'
                 % (x, bw, x + bw // 2, e(sd[0]), x + bw // 2, e(str(sd[1]).split("/")[0])))
    # 泳道
    y = HDR
    for ln in lanes:
        t = ln["tier"]
        col = t.get("color", "#5f7183")
        bh = 24 + ln["n"] * ROWH + 6
        s.append('<rect x="8" y="%d" width="%d" height="%d" rx="12" fill="%s" fill-opacity=".05" '
                 'stroke="%s" stroke-opacity=".3"/>' % (y, W - 16, bh, col, col))
        s.append('<rect x="8" y="%d" width="6" height="%d" rx="3" fill="%s"/>' % (y, bh, col))
        s.append('<rect x="18" y="%d" width="%d" height="18" rx="9" fill="%s"/>'
                 '<text x="%d" y="%d" text-anchor="middle" font-size="10.5" font-weight="700" fill="#fff">%s ×%d</text>'
                 % (y + 4, 116, col, 18 + 58, y + 17, e(t.get("cn", "")), ln["n"]))
        ry = y + 26
        for gi, g in enumerate(ln["gs"]):
            if gi > 0:
                s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-opacity=".2" '
                         'stroke-dasharray="4 4"/>' % (LANE_L - 4, ry - 3, W - 16, ry - 3, col))
            for fl in g["lst"]:
                ym = ry + ROWH // 2
                nm = str(fl.get("name") or "—")[:13]
                lv = LV_CN.get(fl.get("level"), "")
                rt = str(fl.get("rate") or "")[:20]
                s.append('<text x="%d" y="%d" font-size="10" font-weight="700" fill="#1c2733">%s</text>'
                         % (LANE_L + 4, ym - 4, e(nm)))
                s.append('<rect x="%d" y="%d" width="42" height="14" rx="7" fill="%s" fill-opacity=".14" '
                         'stroke="%s" stroke-opacity=".45"/><text x="%d" y="%d" text-anchor="middle" '
                         'font-size="8.5" font-weight="700" fill="%s">%s</text>'
                         % (LANE_L + 4, ym + 1, col, col, LANE_L + 25, ym + 11, col, e(lv)))
                s.append('<text x="%d" y="%d" font-size="8" fill="#5f7183">%s</text>'
                         % (LANE_L + 52, ym + 11, e(rt)))
                # 节点按层落列（同层合并）
                by_l = {}
                for st in (fl.get("stages") or []):
                    by_l.setdefault(st.get("layer"), []).append(st.get("node", ""))
                pts = []
                for k in order:
                    if k not in by_l or k not in layer_idx:
                        continue
                    x = col_x(layer_idx[k])
                    bw = COLW - 12
                    txt = "/".join(by_l[k])
                    s.append('<rect x="%d" y="%d" width="%d" height="26" rx="7" fill="#fff" '
                             'stroke="%s" stroke-opacity=".6"/>' % (x, ym - 13, bw, col))
                    s.append('<rect x="%d" y="%d" width="3.5" height="26" rx="1.8" fill="%s"/>' % (x, ym - 13, col))
                    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="8.5" fill="#1c2733">%s</text>'
                             % (x + bw // 2 + 2, ym - 1, e(txt[:13])))
                    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="7.5" fill="%s" opacity=".85">%s</text>'
                             % (x + bw // 2 + 2, ym + 9, col, e(k)))
                    pts.append((x, x + bw))
                if len(pts) >= 2:
                    d = "M%d,%d" % (pts[0][1], ym)
                    for px in pts[1:]:
                        d += " L%d,%d" % (px[0], ym)
                    s.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" opacity=".3"/>' % (d, col))
                    s.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" stroke-dasharray="6 7" '
                             'marker-end="url(#ifarr)"/>' % (d, col))
                ry += ROWH
        y += bh + 6
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 8：载荷功能框架图（分系统层级框图，与单机清单/架构图互补）
# ================================================================
def svg_payload_framework(R):
    """载荷功能框架图：天线子系统 / 转发器子系统 / 数字处理 / 测控 / 星务 / 供配电 六大功能域，
    每域列出本方案实际选用的单机（来自 equipment），体现「功能分解 → 单机映射」。"""
    rows = R.get("equipment") or []
    totals = R.get("totals") or {}
    cfg = R.get("cfg") or {}
    # 功能域归类（按单机 cat）
    dom = [
        ("天线与波束", "#eaf1fa", "#7ea3d0", {"天线", "机构", "相控阵组件"}),
        ("射频转发", "#f3f7fb", "#a8bdd4", {"LNA", "变频", "多工器", "功放", "开关"}),
        ("数字处理", "#f3eefb", "#b394dd", {"数字处理", "再生基带"}),
        ("测控与星务", "#f1f4f7", "#b0bcc9", {"测控信标", "星务"}),
        ("星间激光", "#e6f5f8", "#79c2d0", {"激光"}),
    ]
    bycat = {}
    for r in rows:
        bycat.setdefault(r.get("cat"), []).append(r)
    W, COLW, TOP = 1080, 200, 92
    # 每列高度 = 标题 + 单机条目
    max_items = 1
    coldata = []
    for nm, fill, stroke, cats in dom:
        items = []
        for c in cats:
            items.extend(bycat.get(c, []))
        coldata.append((nm, fill, stroke, items))
        max_items = max(max_items, len(items))
    H = TOP + max_items * 46 + 60
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<text x="%d" y="26" text-anchor="middle" font-size="14" font-weight="bold" '
             'fill="#0b5cad">载荷功能框架图（功能分解 → 单机映射）</text>' % (W // 2))
    s.append('<text x="%d" y="46" text-anchor="middle" font-size="10.5" fill="#5f7183">'
             '%s · %s体制 · 单机 %s 种 / %s 件 · 载荷 %s kg / %s W · 货架水平 H=%s · 定制缺口 %s 项</text>'
             % (W // 2, e(cfg.get("name") or "方案"), e((R.get("mode_info") or {}).get("cn") or ""),
                f(totals.get("n_rows"), 0), f(totals.get("n_items"), 0),
                f(totals.get("m_pay"), 0), f(totals.get("p_pay"), 0),
                f(totals.get("H_scheme"), 2), f(totals.get("n_custom"), 0)))
    # 顶层载荷框
    s.append('<rect x="%d" y="58" width="%d" height="24" rx="6" fill="#0b5cad"/>'
             '<text x="%d" y="74" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">'
             '通信有效载荷（Payload）</text>' % (W // 2 - 130, 260, W // 2))
    x = 14
    for nm, fill, stroke, items in coldata:
        # 连线到顶层
        s.append('<line x1="%d" y1="82" x2="%d" y2="%d" stroke="#b0bcc9" stroke-width="1.2"/>'
                 % (W // 2, x + COLW // 2 - 6, TOP))
        s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="9" fill="%s" stroke="%s" '
                 'stroke-width="1.4"/>' % (x - 6, TOP, COLW - 8, H - TOP - 16, fill, stroke))
        s.append('<rect x="%d" y="%d" width="%d" height="24" rx="6" fill="%s"/>'
                 '<text x="%d" y="%d" text-anchor="middle" font-size="11.5" font-weight="700" '
                 'fill="#fff">%s</text>' % (x - 2, TOP + 4, COLW - 16, stroke,
                                             x + COLW // 2 - 10, TOP + 20, e(nm)))
        iy = TOP + 36
        if not items:
            s.append('<text x="%d" y="%d" font-size="9.5" fill="#93a3b4">（本方案未配置）</text>'
                     % (x + 2, iy + 12))
        for it in items[:9]:
            iid = str(it.get("id") or "")
            icn = str(it.get("cn") or "")[:13]
            qty = it.get("qty")
            lv = it.get("level")
            lcol = {4: "#1a7a2e", 3: "#2e8b57", 2: "#b07514", 1: "#c0392b"}.get(lv, "#5f7183")
            s.append('<rect x="%d" y="%d" width="%d" height="38" rx="5" fill="#fff" '
                     'fill-opacity=".82" stroke="%s" stroke-opacity=".5"/>'
                     % (x, iy, COLW - 20, stroke))
            s.append('<text x="%d" y="%d" font-size="10" font-weight="700" fill="#1c2733">%s</text>'
                     % (x + 7, iy + 14, e(icn)))
            s.append('<text x="%d" y="%d" font-size="8.5" fill="#5f7183">%s%s</text>'
                     % (x + 7, iy + 27, e(iid), (" ×%s" % qty) if qty and int(qty) > 1 else ""))
            s.append('<circle cx="%d" cy="%d" r="4" fill="%s"><title>货架水平 L%s</title></circle>'
                     % (x + COLW - 28, iy + 26, lcol, lv))
            iy += 46
        x += COLW
    s.append('<text x="14" y="%d" font-size="9" fill="#93a3b4">圆点色＝货架水平：'
             '绿=L4 货架(飞行继承) / 浅绿=L3 飞行继承 / 橙=L2 在研转货架 / 红=L1 定制</text>' % (H - 6))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 9：端到端链路原理图（用户→上行→星上→下行→用户 全链路电平/噪声）
# ================================================================
def svg_link_chain(R):
    """端到端链路原理图：地面用户/关口站 → 上行 → 星上转发（收发链）→ 下行 → 用户，
    标注 EIRP/G/T/C/N/余量/MODCOD，体现完整链路闭合。"""
    res = R.get("res") or {}
    up, dn, e2e = res.get("uplink") or {}, res.get("downlink") or {}, res.get("e2e") or {}
    eirp, gt = res.get("eirp") or {}, res.get("gt") or {}
    s_ = res.get("summary") or {}
    W, H = 1080, 430
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<defs><marker id="lcarr" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">'
             '<path d="M0,0 L8,3 L0,6 z" fill="#0b5cad"/></marker>'
             '<marker id="lcarr2" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">'
             '<path d="M0,0 L8,3 L0,6 z" fill="#b0662c"/></marker></defs>')
    s.append('<text x="%d" y="24" text-anchor="middle" font-size="14" font-weight="bold" '
             'fill="#0b5cad">端到端链路原理图（用户 ↔ 关口站 ↔ 卫星转发器）</text>' % (W // 2))

    def box(x, y, w, h, title, lines, fill, stroke, tcol="#1c2733"):
        s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" stroke="%s" '
                 'stroke-width="1.5"/>' % (x, y, w, h, fill, stroke))
        s.append('<text x="%d" y="%d" text-anchor="middle" font-size="11.5" font-weight="700" '
                 'fill="%s">%s</text>' % (x + w // 2, y + 18, tcol, e(title)))
        yy = y + 36
        for ln in lines:
            s.append('<text x="%d" y="%d" font-size="9.8" fill="#2c3e50">%s</text>'
                     % (x + 10, yy, e(ln)))
            yy += 15

    # 上行（左→中）
    box(20, 70, 200, 120, "① 地面用户/关口站", [
        "EIRP_gs %s dBW" % f(up.get("EIRP_gs"), 1),
        "上行频率 %s GHz" % f(up.get("f_ghz"), 2),
        "斜距 %s km" % f(up.get("d_km"), 0),
        "雨衰 %s dB" % f(up.get("A_rain"), 1),
    ], "#fdf3e0", "#d9b06a")
    box(270, 70, 230, 120, "② 上行链路", [
        "L_fs %s dB" % f(up.get("L_fs"), 1),
        "ΣL %s dB" % f(up.get("sum_L"), 1),
        "C/N %s dB" % f(up.get("CN"), 2),
        "余量 M %s dB" % f(up.get("M"), 2),
    ], "#eaf1fa", "#7ea3d0")
    # 星上（中）
    box(550, 56, 250, 150, "③ 星上转发器（%s）" % (e2e.get("arch") or ""), [
        "接收 G/T %s dB/K" % f(gt.get("GT"), 1),
        "T_sys %s K" % f(gt.get("T_sys"), 1),
        "发射 EIRP %s dBW" % f(eirp.get("EIRP"), 1),
        "P_out %s W（%s）" % (f(eirp.get("P_out_w"), 1), eirp.get("amp") or ""),
        "再生增益 ΔM %s dB" % f(e2e.get("regen_bonus"), 1),
        "星上时延 %s ms" % f((R.get("flows") or {}).get("delay_note", {}).get("onboard_ms"), 3),
    ], "#f3eefb", "#b394dd")
    # 下行（中→右）
    box(550, 240, 230, 120, "④ 下行链路", [
        "下行 %s GHz" % f(dn.get("f_ghz"), 2),
        "L_fs %s dB" % f(dn.get("L_fs"), 1),
        "C/N %s dB" % f(dn.get("CN"), 2),
        "余量 M %s dB" % f(dn.get("M"), 2),
    ], "#eaf1fa", "#7ea3d0")
    box(830, 240, 220, 120, "⑤ 地面用户终端", [
        "G/T %s dB/K" % f(dn.get("GT"), 1),
        "MODCOD %s" % (dn.get("modcod") or "—"),
        "η %s bps/Hz" % f(dn.get("eta"), 3),
        "单波束 %s Gbps" % f(dn.get("C_beam_gbps"), 2),
    ], "#e6f5f8", "#79c2d0")
    # 端到端汇总框
    box(270, 240, 230, 120, "⑥ 端到端校核", [
        "C/N 上/下/总",
        "%s/%s/%s dB" % (f(e2e.get("CN_up")), f(e2e.get("CN_dn")), f(e2e.get("CN_total"))),
        "端到端余量 %s dB" % f(e2e.get("M")),
        "整星容量 %s Gbps" % f(s_.get("C_sys"), 1),
    ], "#e8f2ff", "#0b5cad")
    # 箭头
    s.append('<line x1="220" y1="130" x2="266" y2="130" stroke="#b0662c" stroke-width="2" '
             'marker-end="url(#lcarr2)"/>')
    s.append('<line x1="500" y1="130" x2="546" y2="130" stroke="#b0662c" stroke-width="2" '
             'marker-end="url(#lcarr2)"/>')
    s.append('<path d="M675,206 L675,236" stroke="#0b5cad" stroke-width="2" fill="none" '
             'marker-end="url(#lcarr)"/>')
    s.append('<line x1="780" y1="300" x2="826" y2="300" stroke="#0b5cad" stroke-width="2" '
             'marker-end="url(#lcarr)"/>')
    s.append('<line x1="546" y1="300" x2="504" y2="300" stroke="#0b5cad" stroke-width="2" '
             'marker-end="url(#lcarr)"/>')
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="9.5" fill="#5f7183">'
             '上行（馈电）→ 星上转发 → 下行（用户）；C/N 逐级校核，MODCOD 由 C/N 反推（不预设体制）</text>'
             % (W // 2, H - 12))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 10：频率规划示意图（频谱占用 + k 色复用 + 极化）
# ================================================================
def svg_freq_plan(R):
    """频率规划图：B_total 频谱条 → N_beam 波束按 k 色复用分配 → 双极化，体现 c-13 频谱闭合。"""
    p = R.get("params") or {}
    der = p.get("_derived") or {}
    cfg = R.get("cfg") or {}
    trp = R.get("transponder") or {}
    from infoflow_data import BANDS
    from design_engine import B_TOTAL_OVR
    band = cfg.get("band", "Ka")
    B_total = B_TOTAL_OVR.get(band, BANDS.get(band, {}).get("B_total", 2500))
    Nb = int(to_f(p.get("N_beam"), to_f(der.get("N_beam"), 16)) or 16)
    Bb = to_f(p.get("B_beam"), to_f(trp.get("B_beam"), 125))
    k = int(to_f(p.get("k_reuse"), to_f(cfg.get("k_reuse"), 4)) or 4)
    npol = int(to_f(p.get("n_pol"), 2) or 2)
    W, H = 1000, 340
    PALETTE = ["#0b5cad", "#c0392b", "#1d8a4e", "#b07514", "#7048a8", "#0a7ea4", "#d1568c"]
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<text x="%d" y="24" text-anchor="middle" font-size="14" font-weight="bold" '
             'fill="#0b5cad">频率规划与复用示意图（%s 频段 · c-13 频谱闭合）</text>' % (W // 2, e(band)))
    occ = Nb * Bb
    cap = B_total * k
    ok = occ <= cap + 1e-6
    s.append('<text x="%d" y="44" text-anchor="middle" font-size="10.5" fill="%s">'
             'N_beam×B_beam = %s×%s = %s MHz %s B_total×k = %s×%s = %s MHz → %s</text>'
             % (W // 2, "#1a7a2e" if ok else "#c0392b", f(Nb, 0), f(Bb, 0), f(occ, 0),
                "≤" if ok else "＞", f(B_total, 0), f(k, 0), f(cap, 0),
                "频谱闭合" if ok else "超限！"))
    # 频谱条（B_total）
    bx, by, bw, bh = 60, 70, W - 120, 34
    s.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#eef5fb" stroke="#7ea3d0"/>'
             % (bx, by, bw, bh))
    s.append('<text x="%d" y="%d" font-size="10" fill="#5f7183">%s 可用频谱 B_total=%s MHz</text>'
             % (bx, by - 6, e(band), f(B_total, 0)))
    # 按 k 色把波束分组，每组占 B_total 内一段
    per_color = max(1, Nb // k)
    seg_w = bw / k
    for ci in range(k):
        col = PALETTE[ci % len(PALETTE)]
        x0 = bx + ci * seg_w
        s.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s" fill-opacity=".75" '
                 'stroke="#fff"/>' % (x0, by, seg_w - 2, bh, col))
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="9.5" fill="#fff" '
                 'font-weight="700">色%d</text>' % (x0 + seg_w / 2, by + 14, ci + 1))
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="9" fill="#fff">%s波束</text>'
                 % (x0 + seg_w / 2, by + 28, f(per_color if ci < k - 1 else Nb - per_color * (k - 1), 0)))
    # 单波束带宽放大示意
    zy = 150
    s.append('<text x="%d" y="%d" font-size="11" font-weight="700" fill="#0b5cad">'
             '单波束频谱（B_beam=%s MHz）× 双极化复用（n_pol=%d）</text>' % (bx, zy, f(Bb, 0), npol))
    bwid = min(bw * 0.42, 380)
    for pi in range(npol):
        yy = zy + 14 + pi * 40
        col = "#0b5cad" if pi == 0 else "#c0392b"
        s.append('<rect x="%d" y="%d" width="%.1f" height="30" rx="4" fill="%s" fill-opacity=".2" '
                 'stroke="%s"/>' % (bx, yy, bwid, col, col))
        s.append('<text x="%d" y="%d" font-size="10" fill="%s" font-weight="700">%s极化 · %s MHz</text>'
                 % (bx + 8, yy + 19, col, "水平(H)" if pi == 0 else "垂直(V)", f(Bb, 0)))
        # 载波划分
        ncar = max(1, int(Bb / max(to_f(p.get("B_carrier"), Bb / 4), 1)))
        cw = bwid / min(ncar, 16)
        for cci in range(min(ncar, 16)):
            s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-opacity=".4"/>'
                     % (bx + cci * cw, yy, bx + cci * cw, yy + 30, col))
    s.append('<text x="%d" y="%d" font-size="9.5" fill="#5f7183">单载波 B_carrier=%s MHz（SCPC，'
             '噪声带宽最优）；双极化使同频段容量 ×2（c-12）</text>'
             % (bx, H - 40, f(p.get("B_carrier"), 1)))
    s.append('<text x="%d" y="%d" font-size="9.5" fill="#5f7183">转发通道数 %s（N_beam/k 复用）· '
             '转发器总带宽 %s MHz</text>'
             % (bx, H - 22, f(trp.get("n_trp_chan"), 0), f(trp.get("B_trp"), 0)))
    s.append('</svg>')
    return "".join(s)


# ================================================================
# SVG 11：评价准则雷达图（六维评分 + 硬/软准则通过率）
# ================================================================
def svg_eval_radar(ev, score):
    """评价雷达图：六维评分（性能/质量/功耗/成本/灵活/风险）蛛网图 + 中心综合分。"""
    dims = (score or {}).get("dims") or {}
    cn = (score or {}).get("cn") or {}
    order = ["perf", "mass", "power", "cost", "flex", "risk"]
    order = [k for k in order if k in dims] or list(dims.keys())
    W, H = 560, 420
    cx, cy, Rr = W // 2, H // 2 + 6, 150
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    s.append('<text x="%d" y="22" text-anchor="middle" font-size="13" font-weight="bold" '
             'fill="#0b5cad">六维评分雷达图（综合 %s/10 · 评级 %s）</text>'
             % (W // 2, f((score or {}).get("total"), 2), e((ev or {}).get("grade", "—"))))
    n = max(len(order), 3)
    import math as _m
    # 网格环
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(n):
            a = -_m.pi / 2 + 2 * _m.pi * i / n
            pts.append("%.1f,%.1f" % (cx + Rr * ring * _m.cos(a), cy + Rr * ring * _m.sin(a)))
        s.append('<polygon points="%s" fill="none" stroke="#dde5ee" stroke-width=".8"/>'
                 % " ".join(pts))
    # 轴线 + 标签
    for i, k in enumerate(order):
        a = -_m.pi / 2 + 2 * _m.pi * i / n
        ex, ey = cx + Rr * _m.cos(a), cy + Rr * _m.sin(a)
        s.append('<line x1="%d" y1="%d" x2="%.1f" y2="%.1f" stroke="#cdd8e4" stroke-width=".8"/>'
                 % (cx, cy, ex, ey))
        lx, ly = cx + (Rr + 26) * _m.cos(a), cy + (Rr + 22) * _m.sin(a)
        anchor = "middle" if abs(_m.cos(a)) < 0.3 else ("start" if _m.cos(a) > 0 else "end")
        s.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="10.5" fill="#1c2733">%s</text>'
                 % (lx, ly + 4, anchor, e(cn.get(k, k))))
        s.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="9.5" fill="#0b5cad">%s</text>'
                 % (lx, ly + 17, anchor, f(dims.get(k), 1)))
    # 数据多边形
    pts = []
    for i, k in enumerate(order):
        a = -_m.pi / 2 + 2 * _m.pi * i / n
        v = min(max(to_f(dims.get(k), 0) / 10.0, 0), 1)
        pts.append("%.1f,%.1f" % (cx + Rr * v * _m.cos(a), cy + Rr * v * _m.sin(a)))
    s.append('<polygon points="%s" fill="#0b5cad" fill-opacity=".22" stroke="#0b5cad" '
             'stroke-width="2"/>' % " ".join(pts))
    for pt in pts:
        px, py = pt.split(",")
        s.append('<circle cx="%s" cy="%s" r="3.4" fill="#0b5cad"/>' % (px, py))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="22" font-weight="bold" '
             'fill="#0b5cad">%s</text>' % (cx, cy + 8, f((score or {}).get("total"), 1)))
    s.append('</svg>')
    return "".join(s)


# ================================================================
def table(headers, rows, cls=""):
    out = ['<table class="%s">' % cls] if cls else ["<table>"]
    out.append("<tr>" + "".join("<th>%s</th>" % e(hh) for hh in headers) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % (c if isinstance(c, str) and c.startswith("<")
                                                     else e(c)) for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _req_chapter(R):
    cfg, req, geo, der = R["cfg"], R["req"], R["geo"], R["params"]["_derived"]
    svc = (R.get("_service_meta") or {})
    lead_txt = ('本章汇总任务需求基线与覆盖几何推导结果：由轨道高度、最小仰角与覆盖区半径，'
                '按球面三角解出斜距、覆盖地心角与波束张角，进而反推 EIRP / G/T 指标需求——'
                '这是后续所有分系统设计的输入基线（对应 SK-INTENT / SK-RETRIEVE 环节）。')
    rows = [
        ["任务名称", cfg.get("name") or "—", "业务类型", req.get("service_cn") or cfg.get("service")],
        ["轨道类型", req.get("orbit_cn") or cfg.get("orbit"), "轨道高度", "%s km" % f(R.get("_orbit_alt_km"), 0)],
        ["用户频段", req.get("band") or cfg.get("band"), "馈电频段", cfg.get("feeder_band") or "同用户频段"],
        ["覆盖区", req.get("coverage_cn") or cfg.get("coverage"), "覆盖半径", "%s km" % f(cfg.get("cov_r_km") or geo.get("cov_r_km"), 0)],
        ["单波束半径", "%s km" % f(cfg.get("beam_r_km") or geo.get("beam_r_km"), 0), "设计寿命", "%s 年" % f(cfg.get("life_yr"), 0)],
        ["转发体制", (R.get("mode_info") or {}).get("cn") or cfg.get("mode"), "工作模式", cfg.get("Mode") or "多波束"],
        ["天线体制", (R.get("ant_info") or {}).get("cn") or cfg.get("ant_type"),
         "阵面子体制", (R.get("sub_info") or {}).get("cn") or cfg.get("array_subtype") or "—"],
        ["星间链路", ("激光 %s Gbps" % f(cfg.get("isl_r_gbps"), 0)) if cfg.get("isl_on") else "不配置",
         "系统容量需求", "%s Gbps（业务库典型值）" % f(svc.get("C_gbps"), 1) if svc.get("C_gbps") else "—"],
    ]
    t1 = table(["项目", "取值", "项目", "取值"], rows)
    rows2 = [
        ["最差斜距 d", "%s km" % f(geo.get("d_slant"), 0), "几何：由轨道高度+最小仰角解球面三角"],
        ["覆盖地心角 ψ_cov", "%s°" % f(geo.get("psi_cov_deg"), 2), "单星可视范围地心半角"],
        ["单星视域半径", "%s km" % f(geo.get("cov_r_cap_km"), 0), "R_e·ψ_cov（弧长）"],
        ["波束地心张角 θ_beam", "%s°" % f(geo.get("θ_beam_deg"), 2), "由单波束覆盖半径反推"],
        ["几何建议波束数 N_beam_geo", f(geo.get("N_beam_geo"), 0), "覆盖区面积/单波束面积（六边形密铺）"],
        ["EIRP 需求", "%s dBW" % f(der.get("EIRP_req"), 1), "由链路预算+雨衰可用性反推（c-22）"],
        ["G/T 需求", "%s dB/K" % f(der.get("GT_req"), 1), "上行 C/N 门限反推"],
        ["设计波束数（采用）", f(der.get("N_beam"), 0), "频率复用 k=%s" % f(cfg.get("k_reuse") or geo.get("k_typ"), 0)],
    ]
    t2 = table(["需求推导项", "数值", "说明"], rows2)
    return (lead(lead_txt)
            + '<h3 class="doc-h3">1.1 任务需求汇总</h3>'
            + tabcap("1-1", "任务需求基线") + t1
            + '<h3 class="doc-h3">1.2 覆盖几何与指标需求推导（SK-INTENT/SK-RETRIEVE）</h3>'
            + tabcap("1-2", "覆盖几何与指标需求推导") + t2
            + '<p class="doc-p"><b>需求闭环判据：</b>下行 MODCOD 由 C/N 反推（不预设体制）；'
            '频段为硬约束（无货架产品记缺口 N_gap，不回退错误频段；测控/信标豁免 S 波段）；'
            '链路余量目标 M ≥ %s dB。</p>' % f(cfg.get("M_target"), 1))


def _principle_chapter(R):
    """第 2 章：设计原理与方法论（第一性原理公式 + skill 主链路 + 双回环 + 信息流框架 + 单机原理）。"""
    cfg = R.get("cfg") or {}
    ant = R.get("res", {}).get("antenna") or {}
    # ---- 2.1 第一性原理 ----
    fml = table(["物理量", "公式", "本报告应用"], [
        ["自由空间损耗", "L_fs = 20lg(d) + 20lg(f) + 32.44　(dB, km/GHz)", "第 5 章上/下行 L_fs 逐项闭合"],
        ["等效全向辐射功率", "EIRP = P_out + G_ant − L_feed − L_tx　(dBW)", "第 4.1 节发射预算（c-1）"],
        ["接收品质因数", "G/T = G_ant − 10lg(T_sys)；T_sys = T_ant + T_rx（Friis 级联）", "第 4.2 节接收预算（c-2）"],
        ["载噪比密度", "C/N0 = EIRP − L_fs − ΣL + G/T + 228.6　(dBHz)", "第 5 章链路预算"],
        ["调制编码", "MODCOD 由 C/N 反推（不预设体制），C = B·η·(1−M回退)", "第 5.2 节端到端校核"],
        ["覆盖几何", "cosψ = R·cos(el)/(R+h)；σ = ψ − el", "第 1.2 节几何推导 / 第 10 章组网"],
        ["反射面增益", "G = η·(πD/λ)²", "第 4 章天线增益"],
        ["相控阵增益", "G = 10lg(N_el·η) + G_el − L_scan(cos^1.5θ)", "第 4 章 / 二维方向图扫描修正"],
        ["功率墙", "P_阵 = N_el × P_偏置（T/R 或 MPD）vs 平台供电能力", "体制判别：相控阵 vs 反射面"],
    ])
    p1 = ('<h3 class="doc-h3">2.1 设计方法论与第一性原理</h3>'
          '<p class="doc-p">本方案论证不依赖经验模板，全部指标自物理定律出发逐级闭合：'
          '由业务需求与覆盖几何解出斜距与损耗 → 由可用性（雨衰）与 MODCOD 门限反推 EIRP/G/T 需求 → '
          '由增益/噪声需求分解到天线口径、阵元数、功放功率与接收链噪声系数 → '
          '折算质量/功耗后与平台承载能力闭环校核。核心公式如下：</p>'
          + tabcap("2-1", "第一性原理公式体系") + fml +
          '<p class="doc-p small">注：MODCOD 一律由链路 C/N 反推而非预设；频段为硬约束，'
          '无货架产品时记录定制缺口 N_gap 而不回退到错误频段（测控/信标按惯例豁免 S 波段）。</p>')
    # ---- 2.2 设计主链路 ----
    rows = []
    for i, (sid, nm, stage, note) in enumerate(SKILL_CHAIN, 1):
        rows.append([i, sid, nm, stage, note])
    t = table(["#", "Skill 编号", "名称", "阶段", "职责说明"], rows)
    dg = R.get("diagnosis") or {}
    lvl = {"ok": "通过", "warn": "告警放行", "bad": "中止转人工"}.get(dg.get("level"), "—")
    p2 = ('<h3 class="doc-h3">2.2 设计主链路（skill 流程）</h3>'
          + svg_flow_chain() + figcap("2-1", "设计主链路流程图（需求理解 → 知识支撑 → 载荷方案 → 指标校核 → 平台运载 → 成果输出）")
          + tabcap("2-2", "skill 主链路职责表") + t)
    # ---- 2.3 双回环 ----
    p3 = ('<h3 class="doc-h3">2.3 双回环机制与异常分级</h3>'
          '<p class="doc-p">· <b>内环</b>（平台可行性）：单机清单 → 平台承载校核，不满足时更换天线方案重算（≤3 次迭代）；<br/>'
          '· <b>外环</b>（链路余量）：SK-VALID 判定余量不足 → 否决当前天线、带 exclude_models 重新五维选型（≤2 次）；<br/>'
          '· <b>异常分级</b>：L1 自动降级 / L2 告警放行 / L3 中止转人工。本方案质量闸判定：<b>%s</b>。</p>'
          % lvl)
    issues = "".join('<p class="doc-p" style="color:#8a3b12">诊断问题 [%s][%s] %s：%s</p>'
                     % (e(i.get("sev")), e(i.get("id")), e(i.get("title")), e(str(i.get("detail"))[:220]))
                     for i in (dg.get("issues") or [])[:8])
    # ---- 2.4 信息流框架 ----
    flows = R.get("flows") or {}
    tiers = flows.get("tiers") or []
    tier_note = ""
    if tiers:
        tier_note = ('<p class="doc-p small">信息流按「层次 × 类别 × 功能级」三维组织：'
                     '层次分 %s；每类流再按星地段（sg）/星间段（si）/星内段（sn）展开，'
                     '并标注 L1 接入 → L8 供能的功能级链路（与前端「⑥ 信息流设计」页同源）。</p>'
                     % "、".join(e(t.get("cn") or t.get("id")) for t in tiers))
    iflow = ('<h3 class="doc-h3">2.4 载荷信息流框架图（泳道分层：类别泳道 × 功能层列）</h3>'
             + tier_note
             + svg_info_flow(R.get("flows"), R.get("cfg"))
             + figcap("2-2", "载荷信息流框架图（行=业务/数据/控制/供能泳道，列=L1 接入→L8 供能功能层，"
                             "节点按功能层落列、连线水平无交叉）")
             + '<p class="doc-p small">信息流框架图由 info_flows() 按体制/轨道/星间配置自动生成：'
             '每条流一行、路径节点按功能层（L1 接入→L8 供能）落列、同层合并，空间段（星地/星间/星内）'
             '以行内徽标标注；每条流的介质、速率、时延与关键判据见「信息流设计」章节卡片。'
             '供能流（功率流）按 EPC 高压母线→功放路径绘制。</p>')
    # ---- 2.5 单机工作原理 ----
    princ = R.get("principles") or []
    ps = []
    for pr in princ[:12]:
        body_txt = str(pr.get("principle") or "").replace("\n", "<br/>")
        ps.append('<p class="doc-p"><b>%s（%s）</b><br/><span class="small">%s</span></p>'
                  % (e(pr.get("key")), e(pr.get("cn")), body_txt))
    p5 = ('<h3 class="doc-h3">2.5 本方案涉及单机工作原理</h3>'
          + "".join(ps)) if ps else ""
    return p1 + p2 + p3 + issues + iflow + p5


def _scheme_chapter(R):
    s, t = R["res"]["summary"], R["totals"]
    plat = (R.get("platform") or [None, {}])[1]
    lau = (R.get("launcher") or [None, {}])[1]
    sc = R.get("score") or {}
    kpi_rows = [
        ["星上 EIRP", "%s dBW" % f(s.get("EIRP"), 1), "星上 G/T", "%s dB/K" % f(s.get("GT"), 1)],
        ["上行余量 M_up", "%s dB" % f(s.get("M_up"), 2), "下行余量 M_dn", "%s dB" % f(s.get("M_dn"), 2)],
        ["端到端余量", "%s dB" % f(s.get("M_e2e"), 2), "下行 MODCOD", s.get("modcod") or "—"],
        ["单波束容量", "%s Gbps" % f(s.get("C_link"), 2), "整星容量 C_sys", "%s Gbps" % f(s.get("C_sys"), 1)],
        ["载荷质量（含20%裕度）", "%s kg" % f(t.get("m_pay"), 0), "载荷功耗（含20%裕度）", "%s W" % f(t.get("p_pay"), 0)],
        ["货架水平 H_scheme", t.get("H_scheme"), "定制缺口 N_gap", "%s 项" % t.get("n_custom")],
        ["推荐平台", "%s（%skg/%sW）" % (plat.get("cn", "—"), plat.get("m_pay", ""), plat.get("p_pay", "")),
         "推荐运载", lau.get("cn") or "—"],
        ["约束判据", "%s/%s 通过" % (s.get("judge_pass"), s.get("judge_total")),
         "六维综合评分", "%s /10" % f(sc.get("total"), 2)],
    ]
    kt = table(["项目", "数值", "项目", "数值"], kpi_rows)
    arch = svg_architecture(R.get("diagram"))
    frame = svg_payload_framework(R)
    link = svg_link_chain(R)
    freq = svg_freq_plan(R)
    dims = sc.get("dims") or {}
    cn = sc.get("cn") or {}
    wts = sc.get("weights") or {}
    st = table(["维度", "权重", "得分(0~10)"],
               [[cn.get(k, k), "%s%%" % round(wts.get(k, 0) * 100), f(dims.get(k), 1)]
                for k in dims])
    return (lead('本章给出经链路校核闭合的总体方案：先以总体指标表呈现校核结果，'
                 '再依次以架构图（信号级连接）、功能框架图（功能分解→单机映射）、'
                 '端到端链路原理图、频率规划图四张框架图，从「连接—功能—链路—频谱」'
                 '四个维度刻画载荷总体构成。')
            + '<h3 class="doc-h3">3.1 总体指标（链路校核结果）</h3>'
            + tabcap("3-1", "总体指标汇总表") + kt
            + '<h3 class="doc-h3">3.2 载荷组成架构图（信号级框图）</h3>'
            + arch + figcap("3-1", "载荷组成架构图（信号级连接关系）")
            + '<p class="doc-p small">架构图由 block_diagram() 按「体制+天线类型+频段规划」自动生成；'
              '连线颜色：棕=上行射频，蓝=下行射频，紫=数字域，青=光域，灰=中频/控制。</p>'
            + '<h3 class="doc-h3">3.3 载荷功能框架图（功能分解 → 单机映射）</h3>'
            + frame + figcap("3-2", "载荷功能框架图（六大功能域→货架单机映射）")
            + '<p class="doc-p small">功能框架图按六大功能域（天线与波束/射频转发/数字处理/测控与星务/星间激光）'
              '归并本方案实际选用的货架单机，圆点色表示货架水平（绿=飞行继承级）。</p>'
            + '<h3 class="doc-h3">3.4 端到端链路原理图</h3>'
            + link + figcap("3-3", "端到端链路原理图（逐级电平/噪声）")
            + '<p class="doc-p small">完整链路：地面用户/关口站 → 上行 → 星上转发（接收 G/T + 发射 EIRP）→ '
              '下行 → 用户终端；C/N 逐级校核，MODCOD 由 C/N 反推。</p>'
            + '<h3 class="doc-h3">3.5 频率规划与复用示意图</h3>'
            + freq + figcap("3-4", "频率规划与 k 色复用示意图")
            + '<h3 class="doc-h3">3.6 六维评分</h3>'
            + tabcap("3-2", "六维加权评分") + st)


def _ant_chapter(R, beam1d, beam2d_svg, p2info, scan_note=""):
    ant = R["res"]["antenna"]
    eirp, gt = R["res"]["eirp"], R["res"]["gt"]
    der = R["params"]["_derived"]
    t1 = table(["项", "值 (dB/dBW)", "说明"], [
        ["P_out 功放饱和输出", "%s dBW（%s W）" % (f(eirp.get("P_out_dbw")), f(eirp.get("P_out_w"), 1)),
         der.get("p_out_source") or "EIRP 需求反推"],
        ["G_ant 天线增益", "%s dBi" % f(eirp.get("G_ant")),
         "相控阵 10lg(N_el·η)+G_el−扫描损耗" if ant.get("formula") == "c-3" else "反射面 10lg(η(πD/λ)²)"],
        ["L_feed 馈线损耗", "−%s dB" % f(eirp.get("L_feed")), "馈源/波导/旋转关节"],
        ["L_tx 发射链损耗", "−%s dB" % f(eirp.get("L_tx")), (eirp.get("L_tx_source") or "") + "（OMUX/滤波/隔离器）"],
        ["<b>EIRP</b>", "<b>%s dBW</b>" % f(eirp.get("EIRP")),
         "需求 %s dBW → %s" % (f(der.get("EIRP_req"), 1),
                               "满足" if (eirp.get("EIRP") or 0) >= (der.get("EIRP_req") or 0) - 0.05
                               else "缺口 %sdB" % f((eirp.get("EIRP") or 0) - (der.get("EIRP_req") or 0)))],
    ])
    t2 = table(["项", "值", "说明"], [
        ["G_ant", "%s dBi" % f(gt.get("G_ant")), gt.get("rx_chain_name") or "接收链"],
        ["T_ant 天线噪声", "%s K" % f(gt.get("T_ant"), 1), "天空噪声+馈线"],
        ["T_rx 接收机噪声", "%s K" % f(gt.get("T_rx"), 1), "LNA/T-R 组件 NF 级联（Friis）"],
        ["T_sys", "%s K" % f(gt.get("T_sys"), 1), "NF_total %s dB" % f(gt.get("NF_total_db"))],
        ["<b>G/T</b>", "<b>%s dB/K</b>" % f(gt.get("GT")),
         "需求 %s dB/K" % f(der.get("GT_req"), 1)],
    ])
    # 接收链原理图
    rx_svg = ""
    flows = R["res"].get("flows") or {}
    rxf = (flows.get(gt.get("rx_chain_id")) or {}).get("rx") or flows.get(gt.get("rx_chain_id")) or {}
    if rxf.get("stages"):
        rx_svg = svg_rx_chain(rxf["stages"], "接收链原理图（逐级增益/噪声 → T_sys Friis 级联）", "rx")
    txf = flows.get("ant_tx_path") or {}
    tx_svg = svg_rx_chain(txf.get("stages") or [], "发射链原理图（逐级电平 → EIRP）", "tx")
    B = beam1d or {}
    src = "GRASP 物理光学实测" if B.get("source") == "grasp" else "解析口径方向图（Airy，GRASP 不可用时降级）"
    pat = ""
    if B.get("theta"):
        pat = ('<h3 class="doc-h3">4.3 波束方向图（%s）</h3>'
               '<table class="nob"><tr><td class="nob">%s</td><td class="nob">%s</td></tr></table>'
               '<p class="figcap"><b>图 4-1</b>　左：一维主瓣切面；右：二维 θx–θy 平面热力图（含 −3dB 等值圈）</p>'
               '<p class="doc-p small">一维主瓣切面：峰值增益 %s dBi，−3dB 波束宽度 %s°，覆盖边缘电平 %s dBr。'
               '二维方向图为 θx–θy 平面热力图（%s）；'
               '地面足迹：−3dB 直径 ≈ %s km（r=R_e·θ/2 小角近似）。%s</p>'
               % (src, svg_pattern_1d(B), beam2d_svg,
                  f(B.get("peak_gain_dbi"), 1), f(B.get("beamwidth_3db_deg"), 3),
                  f(B.get("coverage_edge_dbr"), 1),
                  "含相控阵扫描 cos^1.5 单元因子修正" if "扫描" in scan_note else "口径旋转对称",
                  f((B.get("beamwidth_3db_deg") or 0) / 2 * math.pi / 180 * 6371 * 2, 0),
                  scan_note))
    return ('<h3 class="doc-h3">4.1 发射 EIRP 预算（c-1）</h3>%s%s'
            '<h3 class="doc-h3">4.2 接收 G/T 预算（c-2，Friis 级联）</h3>%s%s%s'
            % (tabcap("4-1", "发射 EIRP 预算表") + t1, tx_svg, tabcap("4-2", "接收 G/T 预算表") + t2,
               rx_svg, pat))


def _link_chapter(R):
    up, dn, e2e = R["res"]["uplink"], R["res"]["downlink"], R["res"]["e2e"]
    rows = []
    for nm, lk in (("上行", up), ("下行", dn)):
        rows += [
            ["%s · 频率" % nm, "%s GHz" % f(lk.get("f_ghz"), 3), "%s · 斜距" % nm, "%s km" % f(lk.get("d_km"), 0)],
            ["%s · EIRP" % nm, "%s dBW" % f(lk.get("EIRP")), "%s · L_fs" % nm, "%s dB" % f(lk.get("L_fs"))],
            ["%s · ΣL 其它损耗" % nm, "%s dB（雨衰 %s + 大气 %s + 指向 %s + 极化 %s + 实现 %s）"
             % (f(lk.get("sum_L")), f(lk.get("A_rain")), f(lk.get("A_atm")), f(lk.get("L_pnt")),
                f(lk.get("L_pol")), f(lk.get("L_impl"))),
             "%s · G/T" % nm, "%s dB/K" % f(lk.get("GT"))],
            ["%s · C/N0" % nm, "%s dBHz" % f(lk.get("CN0")), "%s · C/N（B=%sMHz）" % (nm, f(lk.get("B_mhz"), 1)),
             "%s dB" % f(lk.get("CN"))],
            ["%s · MODCOD" % nm, "%s（η=%s bps/Hz，(C/N)req=%s dB）"
             % (lk.get("modcod"), f(lk.get("eta"), 3), f(lk.get("CN_req"))),
             "%s · 余量 M" % nm, "<b>%s dB</b>" % f(lk.get("M"))],
            ["%s · 链路容量" % nm, "%s Gbps" % f(lk.get("C_link_gbps"), 3),
             "%s · 波束容量" % nm, "%s Gbps" % f(lk.get("C_beam_gbps"), 3)],
        ]
    t = table(["项目", "数值", "项目", "数值"], rows)
    te = table(["端到端项", "数值"], [
        ["体制架构", e2e.get("arch") or "—"],
        ["C/N 上/下/总", "%s / %s / %s dB" % (f(e2e.get("CN_up")), f(e2e.get("CN_dn")), f(e2e.get("CN_total")))],
        ["MODCOD / η", "%s / %s bps/Hz" % (e2e.get("modcod"), f(e2e.get("eta"), 3))],
        ["再生增益 ΔM", "%s dB" % f(e2e.get("regen_bonus"), 1)],
        ["端到端余量 M", "%s dB" % f(e2e.get("M"))],
    ])
    trp = R.get("transponder") or {}
    tt = table(["转发器参数", "取值"], [
        ["波束数 N_beam", trp.get("N_beam")],
        ["转发通道数", trp.get("n_trp_chan")],
        ["单波束带宽", "%s MHz" % f(R["cfg"].get("B_beam") or trp.get("B_beam"), 0)],
        ["功放体制", trp.get("amp") or "—"],
        ["单波束功率", "%s W" % f(trp.get("P_out_w"), 1)],
        ["功放台数（含环备份）", trp.get("n_hpa")],
        ["功放直流总功耗", "%s W" % f(trp.get("p_hpa_dc"), 0)],
        ["分布式 T/R（相控阵）", "是" if trp.get("distributed") else "否"],
        ["频率规划", "闭合（N×B ≤ k×B_total）" if R["params"]["_derived"].get("freq_ok") else "超限"],
    ])
    return (lead('链路预算是方案可行性的定量核心：上行、下行分别按 Friis 公式闭合 C/N0 与 C/N，'
                 'MODCOD 由实际 C/N 反推（不预设体制），端到端按再生/透明体制合成，'
                 '最终校核余量 M ≥ 目标值。转发器方案（波束数/带宽/功放体制/台数）随链路闭合结果一并给出。')
            + '<h3 class="doc-h3">5.1 上/下行链路预算表</h3>' + tabcap("5-1", "上/下行链路预算") + t
            + '<h3 class="doc-h3">5.2 端到端校核</h3>' + tabcap("5-2", "端到端校核") + te
            + '<h3 class="doc-h3">5.3 转发器方案</h3>' + tabcap("5-3", "转发器参数") + tt)


def _equip_chapter(R):
    rows = R.get("equipment") or []
    lvmap = {4: "货架(飞行继承)", 3: "飞行继承", 2: "在研转货架", 1: "定制"}
    body = []
    for i, r in enumerate(rows, 1):
        body.append([i, r.get("id"), r.get("cn"), r.get("cat"), r.get("band"),
                     r.get("qty"), f(r.get("mass"), 1), f(r.get("power"), 1),
                     lvmap.get(r.get("level"), r.get("level")),
                     (str(r.get("why") or "")[:90])])
    t = table(["#", "编号", "单机名称", "类别", "频段", "数量", "质量kg", "功耗W", "货架水平", "选型依据"], body)
    tsum = table(["汇总项", "数值"], [
        ["单机种类", R["totals"].get("n_rows")],
        ["单机总数", "%s 件" % R["totals"].get("n_items")],
        ["载荷质量（含20%裕度）", "%s kg" % f(R["totals"].get("m_pay"), 0)],
        ["载荷功耗（含20%裕度）", "%s W" % f(R["totals"].get("p_pay"), 0)],
        ["货架水平 H_scheme", R["totals"].get("H_scheme")],
        ["定制缺口 N_gap", "%s 项" % R["totals"].get("n_custom")],
    ])
    # 天线五维选型
    cands = R.get("ant_cands") or []
    crec = (R.get("ant_rec") or [None, {}])
    rec_id = (crec[1] or {}).get("id")
    crows = []
    for c in cands[:8]:
        cid = c[1].get("id")
        d = c[3]
        crows.append([("<b>%s</b>" % f(c[0])) if cid == rec_id else f(c[0]),
                      cid + ("（推荐）" if cid == rec_id else ""),
                      f(d.get("EIRP"), 1), f(d.get("GT"), 1), f(d.get("mass"), 1),
                      f(d.get("power"), 1), f(d.get("mode"), 1), d.get("fam")])
    tcand = table(["评分", "编号", "①EIRP", "②G/T", "③质量", "④功耗", "⑤模式", "体制"], crows)
    reasons = "".join("<li>%s</li>" % e(x) for x in (crec[2] if len(crec) > 2 else []) or [])
    return (lead('单机选型遵循「频段硬过滤 → 五维评分 → 货架优先三级选型」流程：'
                 '天线按 EIRP/G/T/质量/功耗/工作模式五维加权评分择优；其余单机在通过频段过滤后'
                 '按货架水平（4=货架产品(飞行继承) → 3=飞行继承 → 2=在研转货架 → 1=定制）逐级选取，'
                 '无货架可用时记录定制缺口 N_gap 而不回退错误频段。')
            + '<h3 class="doc-h3">6.1 天线五维选型（频段硬过滤 + EIRP/G/T/质量/功耗/模式评分）</h3>'
            + tabcap("6-1", "天线候选五维评分") + tcand
            + '<p class="doc-p"><b>推荐：%s · %s</b></p><ul class="doc-ul">%s</ul>'
            % (e((crec[1] or {}).get("id")), e((crec[1] or {}).get("cn")), reasons)
            + '<h3 class="doc-h3">6.2 货架单机清单（三线编号，货架优先）</h3>'
            + tabcap("6-2", "货架单机清单") + t
            + '<h3 class="doc-h3">6.3 清单汇总</h3>'
            + tabcap("6-3", "清单汇总") + tsum)


def _icd_chapter(icd):
    if not icd:
        return "<p class='doc-p'>接口与协议数据不可用。</p>"
    st = icd["stats"]
    intro = ('<p class="doc-p">接口控制文件（ICD）由 <b>protocol_gen</b> 自动生成：方案设定 → 单机选型 → '
             '接口自动推导 → 标准协议规格。标准化体系参考 <b>MOSA</b>（模块化开放系统方法）/'
             'FACE 五层软件参考、<b>CCSDS</b> 空间数据系统标准、<b>ECSS</b> 总线与电源标准、'
             'MIL-STD-1553B。共推导接口 <b>%d</b> 条（射频 %d / 中频 %d / 数据 %d / 控制 %d / 光 %d）、'
             '电源接口 %d 项、APID %d 个、虚拟信道 %d 条。</p>'
             % (st["n_if"], st["n_rf"], st["n_ifmid"], st["n_dig"], st["n_ctrl"], st["n_opt"],
                st["n_power"], st["n_apid"], st["n_vc"]))
    # 接口矩阵
    irows = [[i["idx"], "%s→%s" % (i["src_id"], i["dst_id"]), i["itype"], i["subtype"],
              i["media"], i["conn"], i["param"], i["std"]]
             for i in icd["interfaces"]]
    ti = table(["#", "接口（源→宿）", "类型", "子类", "传输介质", "连接器", "关键参数", "遵循标准"], irows)
    # 电气特性补充表
    erows = [[i["idx"], "%s→%s" % (i["src_id"], i["dst_id"]), i["electrical"]]
             for i in icd["interfaces"]]
    te = table(["#", "接口", "电气/性能特性"], erows)
    # 数据总线标准库
    tb = table(["总线", "标准", "速率能力", "介质/电气", "连接器", "适用"],
               [[b["bus"], b["std"], "≤%s Mbps" % b["cap_mbps"], b["media"], b["conn"], b["note"]]
                for b in icd["bus_standards"]])
    # CCSDS 帧格式
    frames_html = []
    for fr in icd["frames"]:
        frows = [[fn, bs, note] for fn, bs, note in fr["fields"]]
        frames_html.append('<p class="doc-p"><b>%s</b>（%s，%s）</p>%s'
                           % (e(fr["name"]), e(fr["std"]), e(fr["size"]),
                              table(["字段", "位长", "说明"], frows)))
    # APID/VCID
    ta = table(["APID", "单机/用途", "名称", "服务说明"],
               [[a["apid"], a["unit"], a["cn"], a["svc"]] for a in icd["apids"]])
    tv = table(["VCID", "业务", "速率档", "承载标准"],
               [[v["vcid"], v["svc"], v["rate"], v["std"]] for v in icd["vcids"]])
    # 电源
    tp = table(["单机", "名称", "数量", "供电母线", "标准", "备注"],
               [[pw["unit"], pw["cn"], pw["qty"], pw["bus"], pw["std"], pw["note"]]
                for pw in icd["power"]])
    # MOSA 分层 + 检查表
    tl = table(["FACE 层", "开放标准", "内容", "MOSA 意义"],
               [[l["layer"], l["std"], l["content"], l["mosa"]] for l in icd["layers"]])
    tm = table(["MOSA 要素", "本方案评估", "判定", "说明"],
               [[m["item"], m["eval"], m["score"], m["note"]] for m in icd["mosa"]])
    # 软件 ICD
    sw = []
    for u in icd["sw_icd"]:
        sw.append('<p class="doc-p"><b>%s · %s</b>（×%s）</p><ul class="doc-ul">%s</ul>'
                  % (e(u["unit"]), e(u["cn"]), u["qty"],
                     "".join("<li>%s</li>" % e(x) for x in u["stack"])))
    return (intro +
            '<h3 class="doc-h3">7.1 接口矩阵（ICD 核心表）</h3>' + tabcap("7-1", "接口矩阵") + ti +
            '<h3 class="doc-h3">7.2 接口电气/性能特性</h3>' + tabcap("7-2", "接口电气特性") + te +
            '<h3 class="doc-h3">7.3 数据总线开放标准库（按速率选型）</h3>' + tabcap("7-3", "数据总线标准库") + tb +
            '<h3 class="doc-h3">7.4 CCSDS 协议帧格式（字段级）</h3>' + "".join(frames_html) +
            '<h3 class="doc-h3">7.5 APID / 虚拟信道分配</h3>' + tabcap("7-4", "APID 分配") + ta +
            tabcap("7-5", "虚拟信道分配") + tv +
            '<h3 class="doc-h3">7.6 电源接口</h3>' + tabcap("7-6", "电源接口") + tp +
            '<h3 class="doc-h3">7.7 MOSA/FACE 软件分层参考</h3>' + tabcap("7-7", "MOSA/FACE 分层") + tl +
            '<h3 class="doc-h3">7.8 MOSA 符合性检查</h3>' + tabcap("7-8", "MOSA 符合性") + tm +
            '<h3 class="doc-h3">7.9 单机软件协议栈（软件开发 ICD）</h3>' + "".join(sw))


def _eval_chapter(R):
    """方案评价标准（E1~E10 十项准则 → 评级 + 可行性结论 + 雷达图 + 修正建议）。"""
    ev = R.get("eval") or {}
    crit = ev.get("criteria") or []
    grade = ev.get("grade", "—")
    gc = {"A": "#1a7a2e", "B": "#0b5cad", "C": "#b8860b", "D": "#c0392b"}.get(grade, "#444")
    gtxt = {"A": "合理可行", "B": "基本可行", "C": "有条件可行", "D": "不可行"}.get(grade, "—")
    badge = ('<table class="nob" style="width:100%%;border:none;margin:6pt 0"><tr>'
             '<td class="nob" style="width:150pt;border:none;vertical-align:middle;text-align:center">'
             '<div style="width:120pt;height:120pt;border:4pt solid %s;border-radius:60pt;'
             'line-height:112pt;font-size:48pt;font-weight:bold;color:%s;text-align:center">%s</div>'
             '<div style="font-size:11pt;color:%s;font-weight:bold;margin-top:4pt">%s</div></td>'
             '<td class="nob" style="border:none;vertical-align:middle;padding-left:14pt">'
             '<p style="font-size:12.5pt;margin:0 0 6pt"><b>可行性结论：</b>%s</p>'
             '<p style="font-size:10.5pt;margin:2pt 0">硬准则 %s ｜ 软准则 %s ｜ 六维评分 %s/10 ｜ 诊断 %s</p>'
             '<p style="font-size:9.5pt;color:#555;margin:4pt 0 0">评级规则：硬准则（E1~E5/E10）全过 → '
             'A（软≥4）/ B（软2~3）/ C（软&lt;2）；任一硬准则失败 → D（不可行）。</p></td></tr></table>'
             % (gc, gc, e(grade), gc, e(gtxt), e(ev.get("conclusion", "—")),
                e(ev.get("pass_hard", "—")), e(ev.get("pass_soft", "—")),
                f(ev.get("score_total"), 2), e(ev.get("level", "—"))))
    rows = []
    for c in crit:
        ok = bool(c.get("ok"))
        kind = c.get("kind") == "hard"
        rows.append([
            e(c.get("id")), e(c.get("name")),
            '<span style="color:%s;font-weight:bold">%s</span>' % ("#c0392b" if kind else "#0b5cad",
                                                                   "硬" if kind else "软"),
            '<span style="color:%s;font-weight:bold">%s</span>' % ("#1a7a2e" if ok else "#c0392b",
                                                                   "通过" if ok else "不通过"),
            e(c.get("got")), e(c.get("need")), e(c.get("note"))])
    t = table(["准则", "评价项", "性质", "判定", "实际值", "要求值", "说明"], rows)
    radar = svg_eval_radar(ev, R.get("score"))
    adv = ev.get("advice") or []
    adv_html = ""
    if adv:
        adv_html = ('<h3 class="doc-h3">9.4 修正建议</h3><ul class="doc-ul">'
                    + "".join('<li style="color:#8a3b12">%s</li>' % e(a) for a in adv)
                    + '</ul>')
    else:
        adv_html = ('<h3 class="doc-h3">9.4 修正建议</h3>'
                    '<p class="doc-p">十项准则全部达标，无需修正 —— 方案可直接转入详细设计阶段。</p>')
    return (lead('方案评价采用「硬准则一票否决 + 软准则加权评级」双层判据：'
                 'E1~E5/E10 为硬准则（链路余量、频段合规、平台承载、频率闭合等），任一不过即判 D（不可行）；'
                 '软准则通过数量决定 A/B/C 等级。雷达图与六维评分同源，综合反映方案在多目标下的均衡性。')
            + '<h3 class="doc-h3">9.1 方案评级与可行性结论</h3>' + badge +
            '<h3 class="doc-h3">9.2 十项评价准则逐项判定（E1~E10）</h3>' + tabcap("9-1", "十项评价准则判定") + t +
            '<h3 class="doc-h3">9.3 六维评分雷达图</h3>' + radar +
            figcap("9-1", "六维加权评分雷达图") +
            '<p class="doc-p small">雷达图为六维加权评分（性能30%/成本15%/灵活15%/风险20%/'
            '质量10%/功耗10%），与第 3 章「六维评分」同源；中心数字为综合分（0~10）。</p>' +
            adv_html)


def _valid_chapter(R):
    cons = R["res"].get("constraints") or []
    rows = []
    for c in cons:
        items = "；".join("%s=%s%s" % (it[0], f(it[1], 2) if isinstance(it[1], (int, float)) else e(it[1]),
                                       e(it[2]) if len(it) > 2 else "")
                          for it in (c.get("items") or [])[:4])
        rows.append([c.get("id"), c.get("formula"),
                     '<span style="color:%s">%s</span>' % ("#1a7a2e" if c.get("ok") else "#c0392b",
                                                           "通过" if c.get("ok") else "不通过"),
                     items, str(c.get("note") or "")[:120]])
    t = table(["约束", "判据公式", "判定", "关键量", "说明"], rows)
    loop = R["res"].get("loop") or {}
    lp = ""
    if loop.get("need"):
        lrows = [[a.get("step"), a.get("action"), f(a.get("gain_db")), a.get("cost"),
                  "足够" if a.get("enough") else "不足/需组合"] for a in loop.get("advice") or []]
        lp = ('<p class="doc-p"><b>回环建议</b>（最差余量 %s dB vs 目标 %s dB，缺口 %s dB）：</p>%s'
              % (f(loop.get("worst_M")), f(loop.get("target"), 1), f(loop.get("deficit")),
                 table(["步骤", "动作", "增益dB", "代价", "是否足够"], lrows)))
    else:
        lp = '<p class="doc-p">全部链路余量达标，无需回环调整。</p>'
    return (lead('方案质量由双重闸门把关：25 条工程约束逐项校核（判据公式、关键量、通过状态全部留痕，'
                 '构成可追溯的论证证据链）；余量不足时给出回环建议（外环否决重选型的量化依据）。')
            + '<h3 class="doc-h3">8.1 25 条工程约束逐项校核</h3>'
            + tabcap("8-1", "工程约束校核表") + t
            + '<h3 class="doc-h3">8.2 余量回环</h3>' + lp)


def _constellation_chapter(R):
    """第 10 章：星座组网与多覆盖区（无相关配置时给出说明性占位，不留空章）。"""
    cfg = R.get("cfg") or {}
    cs = R.get("constellation") or {}
    mc = R.get("multi_coverage") or {}
    parts = []
    if mc:
        w = mc.get("worst") or {}
        rows = []
        for r in mc.get("regions") or []:
            is_w = (r.get("key") == w.get("key"))
            mark = "<b>%s</b>" if is_w else "%s"
            rows.append([mark % e(r.get("cn")), f(r.get("el_min"), 1), f(r.get("d_slant"), 0),
                         "+" + f(r.get("A_dyn"), 1), mark % f(r.get("sev_db"), 2),
                         f(r.get("N_beam_geo"), 0), e(r.get("rain") or "—"),
                         ("链路闭合区（最差）" if is_w else "按包络校核")])
        parts.append('<h3 class="doc-h3">10.1 多覆盖区合成分析</h3>'
                     '<p class="doc-p">多个覆盖区按「各区独立几何 → 最差包络合成」原则处理：'
                     '链路严重度 sev = A_rain + 20lg(d/37500)（雨衰主导，同仰角下 FSPL 差异仅 0.02dB 量级），'
                     '链路预算按严重度最高区闭合；波束总数取各区六边形密铺之和（多区覆盖的物理下限）。'
                     '本方案共 %d 个覆盖区，合成波束数 <b>%s</b>，最差区 <b>%s</b>。</p>'
                     % (len(mc.get("regions") or []), f(mc.get("n_beam_total"), 0), e(w.get("cn"))
                        ) + tabcap("10-1", "多覆盖区逐区几何与链路严重度")
                     + table(["覆盖区", "最小仰角°", "斜距km", "雨衰dB", "严重度dB", "密铺波束数", "雨区", "处理"], rows))
    if cs:
        parts.append('<h3 class="doc-h3">%s 星座组网指标（Walker 构型）</h3>'
                     % ("10.2" if parts else "10.1")
                     + '<p class="doc-p">星座按 Walker N/P/F 标准构型描述，覆盖连续性不用经验公式近似，'
                     '直接对全球网格（纬向 5° × 经向 10°）× 多轨道相位快照逐点数值仿真，'
                     '以「仰角 ≥ 最小仰角 ⟺ 星下点角距 ψ ≤ 覆盖帽半角 σ」为判据统计覆盖重数。'
                     '服务纬度带 |lat| ≤ %s°（倾角与 σ 决定，壳层外为间歇覆盖区）。</p>'
                     % f(cs.get("lat_cap"), 0)
                     + tabcap("10-2" if parts else "10-1", "星座构型与覆盖仿真结果")
                     + table(["构型项", "数值", "构型项", "数值"], [
                         ["Walker 构型 N/P/F", e(cs.get("walker")), "轨道倾角", "%s°" % f(cs.get("incl_deg"), 1)],
                         ["轨道高度", "%s km" % f(cs.get("h_km"), 0), "覆盖帽半角 σ", "%s°" % f(cs.get("sigma_deg"), 2)],
                         ["服务纬度带", "|lat| ≤ %s°" % f(cs.get("lat_cap"), 0), "最小覆盖重数",
                          "%s（%s）" % (f(cs.get("mult_min"), 0),
                                       "连续覆盖" if cs.get("continuous") else "存在间隙")],
                         ["平均覆盖重数", f(cs.get("mult_mean"), 2), "激光终端/星", "%s 台" % f(cs.get("n_lct"), 0)],
                         ["同轨星间距离", "%s km" % f(cs.get("d_intra_km"), 0), "异轨星间距离",
                          "%s km" % f(cs.get("d_cross_km"), 0)],
                         ["单跳时延", "%s ms" % f(cs.get("hop_ms"), 2), "星座总容量",
                          ("%s Gbps（单星 %s Gbps × %s 星）"
                           % (f(cs.get("c_sys_total"), 1),
                              f((cs.get("c_sys_total") or 0) / max(to_f(cs.get("N_sat"), 1), 1), 1),
                              f(cs.get("N_sat"), 0))) if cs.get("c_sys_total") else "—"],
                     ])
                     + '<p class="doc-p small">%s</p>' % e(cs.get("note") or ""))
    if not parts:
        n_sat = to_f(cfg.get("N_sat"), 1)
        parts.append('<p class="doc-p">本方案为<b>单星任务</b>（N_sat = %s）且单覆盖区，'
                     '未启用星座组网与多覆盖区合成分析。如任务扩展为组网或多区覆盖，'
                     '可在配置页设置「覆盖区列表」与「N_sat / N_plane / 倾角 / 相位因子」后重新设计：'
                     '引擎将按第 2.1 节覆盖几何公式自动完成 Walker 构型反推、'
                     '全球网格数值覆盖仿真（最小重数 ≥ 1 判连续）与多区最差包络合成，'
                     '激光终端按 2 同轨 + 2 异轨标准拓扑配置。</p>' % f(n_sat, 0))
    return "".join(parts)


# ================================================================
# 三引擎章节：次级方向图 grid/cut + 栅瓣 / 地面 EIRP 覆盖 / 轨道覆盖仿真
#   pattern_engine / coverage_engine / orbit_engine（与前端页签同源计算）
# ================================================================
_BAND_FREQ = {"Ka": 20.0, "Ku": 12.5, "C": 6.0, "Q/V": 45.0, "X": 8.0,
              "S": 2.5, "L": 1.6, "UHF": 0.4}


def _ant_is_array(R):
    ant = (R.get("res") or {}).get("antenna") or {}
    return "相控阵" in str(ant.get("ant_type") or "")


def _pat_freq(R):
    dn = (R.get("res") or {}).get("downlink") or {}
    cfg = R.get("cfg") or {}
    f = dn.get("f_ghz")
    if not f:
        f = _BAND_FREQ.get(str(cfg.get("band") or "Ka"), 20.0)
    return float(f)


def _sso_inclination(h_km):
    """太阳同步倾角：Ω̇=+0.9856°/d → cos i = −2π·Ω̇/(3n·J2·(Re/p)²)。"""
    a = OE.R_EARTH + float(h_km)
    nn = math.sqrt(OE.MU / a ** 3)
    om = 0.9856 * math.pi / 180.0 / 86400.0
    cos_i = -2.0 * om / (3.0 * nn * OE.J2 * (OE.R_EARTH / a) ** 2)
    cos_i = max(min(cos_i, 1.0), -1.0)
    return round(math.degrees(math.acos(cos_i)), 2)


def _compute_pattern(R, scan_theta=0.0, scan_phi=0.0, cut_span=15.0, D_m=None):
    """方案结果 → pattern_engine 次级方向图（与前端 patPayload 同源）。
    返回 (pat, meta)；meta={is_arr,f_ghz,nx,ny,d_lam,D_m,n_el}。"""
    cfg = R.get("cfg") or {}
    params = R.get("params") or {}
    ant = (R.get("res") or {}).get("antenna") or {}
    f_ghz = _pat_freq(R)
    is_arr = _ant_is_array(R)
    kw = dict(freq_ghz=f_ghz, scan_theta=float(scan_theta), scan_phi=float(scan_phi),
              cut_span=float(cut_span), cut_n=301, grid_n_theta=91, grid_n_phi=73)
    g_ant = ant.get("G_ant")
    if g_ant:
        kw["peak_gain_dbi"] = float(g_ant)
    meta = dict(is_arr=is_arr, f_ghz=f_ghz)
    if is_arr:
        n_el = int(to_f(params.get("N_el"), to_f(cfg.get("N_el"), 1024)))
        n_el = max(4, n_el)
        side = max(int(round(math.sqrt(n_el))), 2)
        d_lam = float(cfg.get("d_lam") or params.get("d_lam") or 0.5)
        pat = PE.compute_pattern("phased_array", nx=side, ny=side, d_lam=d_lam, **kw)
        meta.update(nx=side, ny=side, n_el=side * side, d_lam=d_lam)
    else:
        if not D_m:
            D_m = ant.get("D_m")
        if not D_m:
            Glin = 10 ** ((g_ant or 0) / 10)
            eta = float(cfg.get("η_ill") or 65) / 100 or 0.65
            lam = GB.lam_m(f_ghz)
            D_m = lam / math.pi * math.sqrt(max(Glin, 1) / eta)
        pat = PE.compute_pattern("reflector", D=float(D_m), **kw)
        meta.update(D_m=float(D_m), eta=pat.get("eta"), edge_db=pat.get("edge_db"))
    return pat, meta


def _compute_coverage(R):
    """方案结果 → 地面 EIRP 覆盖（coverage_engine，SATSOFT 等效内置计算）。"""
    cfg = R.get("cfg") or {}
    cm = R.get("_cov_meta") or {}
    h_km = float(R.get("_orbit_alt_km") or 35786)
    is_geo = str(cfg.get("orbit") or "GEO").upper() == "GEO"
    tlat = float(cm.get("lat") or 0)
    tlon = float(cm.get("lon", cm.get("geo_lon", 0)) or 0)
    if is_geo:
        sat_lat = 0.0
        sat_lon = float(cm.get("geo_lon", cm.get("lon", 0)) or 0)
    else:
        sat_lat, sat_lon = tlat, tlon
    el_min = float(cm.get("el_min") or 10)
    th0, ph0 = CE.pointing_angles(sat_lat, sat_lon, h_km, tlat, tlon)
    pat, meta = _compute_pattern(R, scan_theta=round(th0, 4), scan_phi=round(ph0, 4))
    eirp_pk = float(((R.get("res") or {}).get("eirp") or {}).get("EIRP")
                    or (pat.get("peak_gain_dbi", 0.0) + 10.0))
    cov = CE.coverage_map(pat, eirp_pk, h_km, sat_lat=sat_lat, sat_lon=sat_lon,
                          el_min_deg=el_min, n_lat=97, n_lon=121)
    pk = cov["peak_eirp_dbw"]
    levels = [round(pk - x, 1) for x in (3.0, 10.0)]
    segs = {str(lv): CE.contour_segments(cov, lv) for lv in levels}
    metrics = CE.coverage_metrics(cov, levels_dbw=levels)
    return dict(cov=cov, segs=segs, metrics=metrics, levels=levels, pat=pat, meta=meta,
                target=dict(lat=tlat, lon=tlon, name=cm.get("cn") or cfg.get("coverage") or "覆盖区"),
                sat=dict(lat=sat_lat, lon=sat_lon, h_km=h_km),
                is_geo=is_geo, el_min=el_min, point=dict(theta=round(th0, 3), phi=round(ph0, 3)))


def _compute_orbit(R):
    """方案结果 → 轨道覆盖仿真（orbit_engine，STK 等效内置计算）。"""
    cfg = R.get("cfg") or {}
    cm = R.get("_cov_meta") or {}
    key = str(cfg.get("orbit") or "GEO").upper()
    h_km = float(R.get("_orbit_alt_km") or 35786)
    el_min = float(cm.get("el_min") or 10)
    tlat = float(cm.get("lat") or 0)
    tlon = float(cm.get("lon", cm.get("geo_lon", 0)) or 0)
    targets = [dict(name=cm.get("cn") or cfg.get("coverage") or "覆盖区", lat=tlat, lon=tlon)]
    is_geo = key == "GEO"
    if is_geo:
        incl = 0.05
    elif key == "SSO":
        incl = _sso_inclination(h_km)
    else:
        incl = {"MEO": 45.0, "LEO": 53.0, "HEO": 63.4}.get(key, 53.0)
    t0 = OE.J2000_UNIX + 26.0 * 365.25 * 86400.0
    raan, argp, ecc = 0.0, 0.0, 0.0
    if is_geo:
        gl = float(cm.get("geo_lon", cm.get("lon", 0)) or 0)
        probe = OE.elements_from_altitude(h_km, incl, raan_deg=0.0, argp_deg=0.0)
        _, lon0, _ = OE.sub_satellite(t0, probe)
        raan = (gl - lon0) % 360.0
    el = OE.elements_from_altitude(h_km, incl, ecc=ecc, raan_deg=raan, argp_deg=argp)
    assess = OE.assess_orbit(key, h_km, incl, targets, el_min_deg=el_min, t_start=t0,
                             ecc=ecc, raan_deg=raan, argp_deg=argp)
    snap = OE.snapshot(t0, el, targets=targets, el_min_deg=el_min)
    import time as _time
    snap["t_utc"] = _time.strftime("%Y-%m-%d %H:%M:%S UTC", _time.gmtime(int(t0)))
    nn, raan_dot, argp_dot = OE.mean_motion(el)
    return dict(assess=assess, snap=snap, el=el, key=key, h_km=h_km, incl=incl,
                period_min=OE.orbital_period_min(el), targets=targets, is_geo=is_geo,
                el_min=el_min, raan=raan, ecc=el["ecc"],
                raan_dot_deg_day=round(math.degrees(raan_dot) * 86400.0, 4),
                sso_incl=(_sso_inclination(h_km) if key in ("SSO", "LEO", "MEO") else None))


# ---------- SVG：方向图 grid（θ×φ 热力图 + 栅瓣白圈） ----------
def svg_pat_grid(pat, W=440, H=430, title=""):
    g = pat.get("grid") or {}
    th, ph, gd = g.get("theta") or [], g.get("phi") or [], g.get("gain_dbr") or []
    if not th or not ph or not gd:
        return ""
    nt, np_ = len(th), len(ph)
    th_max = max(th[-1], 1e-6)
    PL, PT, PR, PB = 48, 38, 80, 44
    MW, MH = W - PL - PR, H - PT - PB
    cw, chh = MW / np_, MH / nt
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    if title:
        s.append('<text x="%d" y="22" text-anchor="middle" font-size="12.5" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (PL + MW // 2, e(title)))
    for i in range(nt):
        y = PT + i * chh
        row = gd[i]
        for j in range(np_):
            s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                     % (PL + j * cw, y, cw + 0.6, chh + 0.6, _heat(row[j])))
    s.append('<rect x="%d" y="%d" width="%.1f" height="%.1f" fill="none" stroke="#93a3b4"/>'
             % (PL, PT, MW, MH))
    for tv in range(0, int(th_max) + 1, 30):
        y = PT + tv / th_max * MH
        s.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ffffff" stroke-opacity=".22"/>'
                 % (PL, y, PL + MW, y))
        s.append('<text x="%d" y="%.1f" text-anchor="end" font-size="9" fill="#5f7183">%d°</text>'
                 % (PL - 5, y + 3, tv))
    for pv in range(0, 361, 90):
        x = PL + pv / 360.0 * MW
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="9" fill="#5f7183">%d°</text>'
                 % (x, H - PB + 14, pv))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="10" fill="#5f7183">方位 φ (°)</text>'
             % (PL + MW // 2, H - 6))
    s.append('<text x="14" y="%d" text-anchor="middle" font-size="10" fill="#5f7183" '
             'transform="rotate(-90 14 %d)">离轴 θ (°)</text>' % (PT + MH // 2, PT + MH // 2))
    for gl in pat.get("grating_lobes") or []:
        gx = PL + (gl["phi_deg"] % 360) / 360.0 * MW
        gy = PT + gl["theta_deg"] / th_max * MH
        s.append('<circle cx="%.1f" cy="%.1f" r="7.5" fill="none" stroke="#fff" stroke-width="1.6"/>'
                 '<circle cx="%.1f" cy="%.1f" r="7.5" fill="none" stroke="#d6452d" '
                 'stroke-width="0.9" stroke-dasharray="2 2"/>' % (gx, gy, gx, gy))
    lx = W - 58
    for i2 in range(40):
        v = -40 + i2
        s.append('<rect x="%d" y="%.1f" width="15" height="%.1f" fill="%s"/>'
                 % (lx, PT + (39 - i2) * (MH / 40), MH / 40 + 0.5, _heat(v)))
    s.append('<rect x="%d" y="%d" width="15" height="%.1f" fill="none" stroke="#93a3b4"/>' % (lx, PT, MH))
    for gv in (0, -10, -20, -30, -40):
        gy = PT + (-gv) / 40.0 * MH
        s.append('<text x="%d" y="%.1f" font-size="8.5" fill="#5f7183">%d</text>' % (lx + 18, gy + 3, gv))
    s.append('</svg>')
    return "".join(s)


# ---------- SVG：方向图 cut（主瓣 ±15° + 宽角签名 −90~+90，栅瓣竖线） ----------
def svg_pat_cut(pat, W=440, H=470, title=""):
    cut = pat.get("cut") or {}
    wide = pat.get("cut_wide") or {}
    ct, cd = cut.get("theta") or [], cut.get("gain_dbr") or []
    wt, wd = wide.get("theta") or [], wide.get("gain_dbr") or []
    if not ct or not wt:
        return ""
    cut_phi = float(cut.get("phi_deg", 0.0))
    center = float(cut.get("center", 0.0))
    span = float(cut.get("span", 15.0))
    gl_signed = []
    for gl in pat.get("grating_lobes") or []:
        st = PE._gl_signed_theta(gl, cut_phi)
        if st is not None:
            gl_signed.append(st)
    PL, PR, PT = 48, 18, 40
    panelH = (H - PT - 34) / 2 - 14
    MW = W - PL - PR
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    if title:
        s.append('<text x="%d" y="22" text-anchor="middle" font-size="12.5" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (W // 2, e(title)))
    panels = [
        (ct, cd, center - span, center + span, PT,
         "主瓣切面 φ=%.0f°（±%.0f°）" % (cut_phi, span),
         [x for x in gl_signed if center - span <= x <= center + span]),
        (wt, wd, -90.0, 90.0, PT + panelH + 28,
         "宽角签名切面（−90°~+90°，负 θ = 反侧）", gl_signed),
    ]
    for (tt, dd, xmin, xmax, y0, lab, gll) in panels:
        Xf = lambda v: PL + (v - xmin) / max(xmax - xmin, 1e-9) * MW          # noqa: E731
        Yf = lambda gg: y0 + (1 - (min(max(gg, -40), 0) + 40) / 40.0) * panelH  # noqa: E731
        s.append('<rect x="%d" y="%.1f" width="%.1f" height="%.1f" fill="#fbfdff" stroke="#dde5ee"/>'
                 % (PL, y0, MW, panelH))
        for gv in (0, -10, -20, -30, -40):
            s.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                     % (PL, Yf(gv), PL + MW, Yf(gv), "#b8c6d6" if gv == 0 else "#eef2f7"))
            s.append('<text x="%d" y="%.1f" text-anchor="end" font-size="8.5" fill="#5f7183">%d</text>'
                     % (PL - 4, Yf(gv) + 3, gv))
        s.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c0392b" '
                 'stroke-dasharray="4 3" stroke-width="1"/>' % (PL, Yf(-3), PL + MW, Yf(-3)))
        xstep = 5 if (xmax - xmin) <= 40 else 30
        xv = math.ceil(xmin / xstep) * xstep
        while xv <= xmax + 1e-9:
            s.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="8" fill="#5f7183">%d</text>'
                     % (Xf(xv), y0 + panelH + 11, xv))
            xv += xstep
        for gth in gll:
            if xmin <= gth <= xmax:
                s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d6452d" '
                         'stroke-width="1.2" stroke-dasharray="3 2"/>' % (Xf(gth), y0, Xf(gth), y0 + panelH))
                s.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="7.5" fill="#d6452d">栅瓣</text>'
                         % (Xf(gth), y0 + 9))
        pts = " ".join("%.1f,%.1f" % (Xf(tt[i]), Yf(dd[i])) for i in range(len(tt)))
        s.append('<polyline points="%s" fill="none" stroke="#0b5cad" stroke-width="1.8"/>' % pts)
        s.append('<text x="%d" y="%.1f" font-size="9" fill="#33475b">%s</text>' % (PL + 2, y0 - 3, e(lab)))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="10" fill="#5f7183">θ (°)</text>'
             % (W // 2, H - 4))
    s.append('</svg>')
    return "".join(s)


# ---------- SVG：地面 EIRP 覆盖（局部窗等距圆柱 + 海岸线 + 色块 + 等值线） ----------
def svg_eirp_coverage(C, world_land=None, W=720, H=480, title=""):
    cov = C["cov"]
    lats, lons, vals = cov["lat"], cov["lon"], cov["eirp_dbw"]
    floor = cov.get("floor", -200.0)
    la0, la1 = lats[0], lats[-1]
    lo0, lo1 = lons[0], lons[-1]
    pk = (cov.get("peak_ground") or {}).get("eirp_dbw") or cov.get("peak_eirp_dbw") or 0
    PL, PT, PR, PB = 48, 38, 82, 44
    MW, MH = W - PL - PR, H - PT - PB
    Xf = lambda lo: PL + (lo - lo0) / max(lo1 - lo0, 1e-9) * MW              # noqa: E731
    Yf = lambda la: PT + (la1 - la) / max(la1 - la0, 1e-9) * MH              # noqa: E731
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    if title:
        s.append('<text x="%d" y="22" text-anchor="middle" font-size="12.5" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (W // 2, e(title)))
    s.append('<rect x="%d" y="%d" width="%.1f" height="%.1f" fill="#eef5fb" stroke="#d3e0ee"/>'
             % (PL, PT, MW, MH))
    # EIRP 色块（抽稀 ≤48×60；相对峰值着色）
    ni, nj = len(lats), len(lons)
    si = max(1, ni // 48)
    sj = max(1, nj // 60)
    for i in range(0, ni - 1, si):
        for j in range(0, nj - 1, sj):
            v = vals[i][j]
            if v <= floor:
                continue
            i2 = min(i + si, ni - 1)
            j2 = min(j + sj, nj - 1)
            x, y = Xf(lons[j]), Yf(lats[i2])
            w, h = Xf(lons[j2]) - x, Yf(lats[i]) - y
            s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity=".82"/>'
                     % (x, y, max(w, 0.6), max(h, 0.6), _heat(min(max(v - pk, -40.0), 0.0))))
    # 海岸线（仅窗内段；地图合规：只海岸线无政界）
    q = float((world_land or {}).get("q") or 4)
    for poly in (world_land or {}).get("polys") or []:
        d, drawing = "", False
        for k in range(0, len(poly) - 3, 2):
            lon_a, lat_a = poly[k] / q, poly[k + 1] / q
            lon_b, lat_b = poly[k + 2] / q, poly[k + 3] / q
            in_a = lo0 <= lon_a <= lo1 and la0 <= lat_a <= la1
            in_b = lo0 <= lon_b <= lo1 and la0 <= lat_b <= la1
            if in_a and in_b:
                d += ("M%.1f,%.1f" % (Xf(lon_a), Yf(lat_a))) if not drawing else ("L%.1f,%.1f" % (Xf(lon_b), Yf(lat_b)))
                drawing = True
            else:
                drawing = False
        if d:
            s.append('<path d="%s" fill="none" stroke="#5c7a5f" stroke-width=".7" opacity=".85"/>' % d)
    # 等值线（-3dB 红 / -10dB 橙）
    for lv in C["levels"]:
        col = "#d6452d" if abs(lv - (pk - 3)) < 0.6 else "#e08214"
        for seg in C["segs"].get(str(lv)) or []:
            (lat_a, lon_a), (lat_b, lon_b) = seg[0], seg[1]
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
                     % (Xf(lon_a), Yf(lat_a), Xf(lon_b), Yf(lat_b), col))
    # 标记：波束中心 / 星下点 / 目标
    bc = cov.get("beam_center") or {}
    sat = C.get("sat") or {}
    tgt = C.get("target") or {}
    for (la, lo, col, lab) in ((bc.get("lat"), bc.get("lon"), "#0b5cad", "波束中心"),
                               (sat.get("lat"), sat.get("lon"), "#1a7a2e", "星下点"),
                               (tgt.get("lat"), tgt.get("lon"), "#c0392b", "目标")):
        if la is None or lo is None or not (lo0 <= lo <= lo1 and la0 <= la <= la1):
            continue
        x, y = Xf(lo), Yf(la)
        s.append('<circle cx="%.1f" cy="%.1f" r="3.4" fill="%s" stroke="#fff" stroke-width="1"/>'
                 '<text x="%.1f" y="%.1f" font-size="8.5" fill="%s">%s</text>'
                 % (x, y, col, x + 5, y - 4, col, e(lab)))
    s.append('<rect x="%d" y="%d" width="%.1f" height="%.1f" fill="none" stroke="#93a3b4"/>'
             % (PL, PT, MW, MH))
    # 经纬刻度
    for k in range(5):
        la = la0 + (la1 - la0) * k / 4
        s.append('<text x="%d" y="%.1f" text-anchor="end" font-size="8.5" fill="#5f7183">%.0f°</text>'
                 % (PL - 4, Yf(la) + 3, la))
        lo = lo0 + (lo1 - lo0) * k / 4
        s.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="8.5" fill="#5f7183">%.0f°</text>'
                 % (Xf(lo), H - PB + 14, lo))
    # 色标（相对峰值 dBr）
    lx = W - 58
    for i2 in range(40):
        v = -40 + i2
        s.append('<rect x="%d" y="%.1f" width="15" height="%.1f" fill="%s"/>'
                 % (lx, PT + (39 - i2) * (MH / 40), MH / 40 + 0.5, _heat(v)))
    s.append('<rect x="%d" y="%d" width="15" height="%.1f" fill="none" stroke="#93a3b4"/>' % (lx, PT, MH))
    for gv in (0, -10, -20, -30, -40):
        gy = PT + (-gv) / 40.0 * MH
        s.append('<text x="%d" y="%.1f" font-size="8.5" fill="#5f7183">%d</text>'
                 % (lx + 18, gy + 3, gv + int(round(pk))))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-size="9" fill="#5f7183">EIRP dBW</text>'
             % (lx + 8, PT - 8))
    s.append('</svg>')
    return "".join(s)


# ---------- SVG：轨道星下点轨迹 + 覆盖圆 + 目标（全球等距圆柱） ----------
def _seg_polyline(pts, Xf, Yf, split_lon=True):
    """[(lat,lon),...] → 分段 path d（跨 ±180° 经线断开）。"""
    d, drawing, prev_lo = "", False, None
    for la, lo in pts:
        if split_lon and prev_lo is not None and abs(lo - prev_lo) > 180:
            drawing = False
        d += ("M%.1f,%.1f" % (Xf(lo), Yf(la))) if not drawing else ("L%.1f,%.1f" % (Xf(lo), Yf(la)))
        drawing = True
        prev_lo = lo
    return d


def svg_orbit_track(O, world_land=None, W=760, H=430, title=""):
    assess = O.get("assess") or {}
    snap = O.get("snap") or {}
    track = assess.get("track") or []
    PL, PT, PR, PB = 12, 34, 12, 30
    MW, MH = W - PL - PR, H - PT - PB
    Xf = lambda lo: PL + ((lo + 180) % 360) / 360.0 * MW                     # noqa: E731
    Yf = lambda la: PT + (90 - min(max(la, -89), 89)) / 180.0 * MH           # noqa: E731
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
         'font-family="Microsoft YaHei,sans-serif">' % (W, H, W, H)]
    if title:
        s.append('<text x="%d" y="20" text-anchor="middle" font-size="12.5" font-weight="bold" '
                 'fill="#0b5cad">%s</text>' % (W // 2, e(title)))
    s.append('<rect x="%d" y="%d" width="%.1f" height="%.1f" fill="#eef5fb" stroke="#cddcec"/>'
             % (PL, PT, MW, MH))
    # 经纬网
    for lo in range(-180, 181, 30):
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#dbe6f1" stroke-width=".6"/>'
                 % (Xf(lo), PT, Xf(lo), PT + MH))
    for la in range(-60, 90, 30):
        s.append('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#dbe6f1" stroke-width=".6"/>'
                 % (PL, Yf(la), PL + MW, Yf(la)))
    # 海岸线
    q = float((world_land or {}).get("q") or 4)
    for poly in (world_land or {}).get("polys") or []:
        d, drawing = "", False
        for k in range(0, len(poly) - 3, 2):
            lon_a, lat_a = poly[k] / q, poly[k + 1] / q
            lon_b, lat_b = poly[k + 2] / q, poly[k + 3] / q
            if abs(lon_b - lon_a) > 180:
                drawing = False
                continue
            d += ("M%.1f,%.1f" % (Xf(lon_a), Yf(lat_a))) if not drawing else ("L%.1f,%.1f" % (Xf(lon_b), Yf(lat_b)))
            drawing = True
        if d:
            s.append('<path d="%s" fill="#cfe0d2" fill-opacity=".9" stroke="#7fa887" '
                     'stroke-width=".5" stroke-linejoin="round"/>' % d)
    # 24h 星下点轨迹
    if track:
        pts = [(p[1], p[2]) for p in track]
        d = _seg_polyline(pts, Xf, Yf)
        if d:
            s.append('<path d="%s" fill="none" stroke="#0b5cad" stroke-width="1.6" '
                     'stroke-dasharray="5 3" opacity=".9"/>' % d)
    # 快照覆盖圆
    circ = snap.get("circle") or []
    if circ:
        d = _seg_polyline([(c[0], c[1]) for c in circ], Xf, Yf)
        if d:
            s.append('<path d="%s" fill="#0b5cad" fill-opacity=".10" stroke="#0b5cad" '
                     'stroke-width="1.5"/>' % d)
    # 目标点
    for tg in snap.get("targets") or []:
        x, y = Xf(tg["lon"]), Yf(tg["lat"])
        col = "#c0392b" if tg.get("visible") else "#8a8f98"
        s.append('<circle cx="%.1f" cy="%.1f" r="3.6" fill="%s" stroke="#fff" stroke-width="1"/>'
                 '<text x="%.1f" y="%.1f" font-size="8.5" fill="%s">%s(%s°)</text>'
                 % (x, y, col, x + 5, y - 4, col, e(tg.get("name", "")), f(tg.get("el_deg"), 0)))
    # 星下点
    if snap.get("sub_lat") is not None:
        x, y = Xf(snap["sub_lon"]), Yf(snap["sub_lat"])
        s.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="#1a7a2e" stroke="#fff" stroke-width="1.2"/>'
                 '<text x="%.1f" y="%.1f" font-size="8.5" fill="#1a7a2e">星下点</text>'
                 % (x, y, x + 6, y + 12))
    s.append('<rect x="%d" y="%d" width="%.1f" height="%.1f" fill="none" stroke="#93a3b4"/>'
             % (PL, PT, MW, MH))
    s.append('</svg>')
    return "".join(s)


# ---------- 章节：4.4/4.5 次级方向图 grid/cut + 栅瓣 ----------
def _pattern_section(pat_bore, pat_scan, meta, D_m=None):
    """追加到第 4 章：次级方向图（grid + cut，boresight/扫描双态）+ 栅瓣分析。"""
    if not pat_bore:
        return ""
    is_arr = meta.get("is_arr")
    f_ghz = meta.get("f_ghz")
    lam = GB.lam_m(f_ghz) * 1000
    rows = []
    if is_arr:
        d_mm = float(meta.get("d_lam") or 0.5) * GB.lam_m(f_ghz) * 1000
        rows = [["天线体制", "平面相控阵（阵元因子 cos^1.5 × 可分离阵列因子）"],
                ["阵规模 N_el", "%s（%s×%s）" % (f(meta.get("n_el"), 0), f(meta.get("nx"), 0), f(meta.get("ny"), 0))],
                ["阵元间距 d", "%s λ（%s mm）" % (f(meta.get("d_lam"), 2), f(d_mm, 1))]]
    else:
        rows = [["天线体制", "反射面（圆口径 Hankel 变换，旋转对称）"],
                ["口径 D", "%s m（η=%s，边缘锥削 %sdB）" % (f(meta.get("D_m"), 2), f(meta.get("eta"), 2),
                                                        f(meta.get("edge_db"), 0))],
                ["栅瓣", "连续口径无栅瓣"]]
    rows += [["工作频率 / 波长", "%s GHz（λ=%s mm）" % (f(f_ghz, 1), f(lam, 1))],
             ["峰值增益 G₀", "%s dBi" % f(pat_bore.get("peak_gain_dbi"), 2)],
             ["−3dB 波束宽度", "%s°" % f(pat_bore.get("beamwidth_3db_deg"), 3)],
             ["首旁瓣电平", "%s dBr" % f(pat_bore.get("first_sidelobe_dbr"), 1)]]
    parts = ['<h3 class="doc-h3">4.4 天线次级方向图（grid θ×φ + cut ±15°）</h3>',
             lead("次级方向图由 pattern_engine 按第一性原理求解：相控阵 = 阵元因子 cos^1.5(θ) × 可分离阵列因子"
                  "（扫描即施加相位梯度 u₀=sinθ₀·cosφ₀）；反射面 = 圆口径场 Hankel 变换 E(u)=∫t(ρ)J₀(kρu)ρdρ"
                  "（关于扫描轴旋转对称，连续口径无栅瓣）。grid 为 θ×φ 全空间功率方向图（用于捕获栅瓣），"
                  "cut 为主瓣 ±15° 切面与 −90°~+90° 宽角签名切面（核查栅瓣是否落入/污染主瓣窗）。"),
             tabcap("4-3", "次级方向图求解参数与结果"),
             table(["项", "值"], rows)]
    # boresight：grid + cut 并排
    gb = svg_pat_grid(pat_bore, title="grid（boresight 不扫描）")
    cb = svg_pat_cut(pat_bore, title="cut（boresight）")
    parts.append('<table class="nob"><tr><td class="nob">%s</td><td class="nob">%s</td></tr></table>'
                 % (gb, cb))
    parts.append(figcap("4-2", "boresight（不扫描）次级方向图：左 grid θ×φ 热力图，右 cut 主瓣±15°与宽角签名切面"))
    # 扫描态
    if pat_scan:
        sd = pat_scan.get("scan_theta_deg")
        gs = svg_pat_grid(pat_scan, title="grid（扫描 %s°）" % f(sd, 0))
        cs = svg_pat_cut(pat_scan, title="cut（扫描 %s°）" % f(sd, 0))
        parts.append('<h3 class="doc-h3">4.5 扫描态方向图与栅瓣分析</h3>')
        parts.append('<table class="nob"><tr><td class="nob">%s</td><td class="nob">%s</td></tr></table>'
                     % (gs, cs))
        parts.append(figcap("4-3", "扫描 %s° 次级方向图：栅瓣随扫描移出可见区（白圈/红虚线标注）" % f(sd, 0)))
    # 栅瓣表
    gl = (pat_scan or pat_bore).get("grating_lobes") or []
    gl_in = (pat_scan or pat_bore).get("grating_in_cut") or []
    parts.append('<h3 class="doc-h3">%s 栅瓣核查</h3>' % ("4.6" if pat_scan else "4.5"))
    if gl:
        grows = [["(%d,%d)" % (g["order"][0], g["order"][1]), f(g["theta_deg"], 1), f(g["phi_deg"], 1),
                  ("是" if any(abs(g["theta_deg"] - x["theta_deg"]) < 0.5 for x in gl_in) else "否"),
                  ("⚠ 污染覆盖区，需减小 d 或限制扫描角"
                   if any(abs(g["theta_deg"] - x["theta_deg"]) < 0.5 for x in gl_in)
                   else "在 ±15° cut 外，覆盖区未受污染")] for g in gl[:8]]
        parts.append(tabcap("4-4", "解析栅瓣（可见区实根）")
                     + table(["栅瓣阶次 (nₓ,ny)", "θ (°)", "φ (°)", "落入 ±15° cut", "判定"], grows))
    else:
        parts.append('<p class="doc-p">本状态可见区内<b>无栅瓣</b>。%s</p>'
                     % e((pat_scan or pat_bore).get("note") or ""))
    parts.append('<p class="doc-p small">方向图数据可导出 GRASP <code>.grd</code> 球面网格文件'
                 '（θ×φ ASCII，幅度由 dBr 反推、相位置 0），供 GRASP/SATSOFT 交叉核对；'
                 '地面覆盖投影见第 11 章。</p>')
    return "".join(parts)


# ---------- 章节：11 地面 EIRP 覆盖 ----------
def _coverage_chapter(C, world_land=None):
    parts = ['<h3 class="doc-h3">11.1 地面 EIRP 覆盖投影</h3>',
             lead("地面覆盖由 coverage_engine 内置计算（SATSOFT 等效）：以天线体坐标系"
                  "（z=天底、x=北、y=东）将次级方向图逐地面点投影——先由 pointing_angles 反解波束指向"
                  "（θ₀,φ₀）使峰值精确落在目标，再对每个格点求离轴角 → 精确方向图查询（不经 grid 插值）"
                  "→ 叠加自由空间损耗与可见性判据（仰角≥门限）→ 地面 EIRP 网格，提取 −3dB/−10dB 等值线。")]
    if not C or not C.get("cov"):
        parts.append('<p class="doc-p">覆盖计算不可用（引擎未返回有效网格）。</p>')
        return "".join(parts)
    cov = C["cov"]
    metrics = C.get("metrics") or {}
    levels = C.get("levels") or []
    tgt = C.get("target") or {}
    sat = C.get("sat") or {}
    pt = C.get("point") or {}
    parts.append(svg_eirp_coverage(C, world_land,
                                   title="地面 EIRP 覆盖（%s，波束指向 %.1f°/%.1f°）"
                                         % ("GEO 定点" if C.get("is_geo") else "瞬时星下点",
                                            pt.get("theta", 0), pt.get("phi", 0))))
    parts.append(figcap("11-1", "地面 EIRP 覆盖等值线图（色块=相对峰值 EIRP，红=−3dB、橙=−10dB 等值线；"
                                "含海岸线/波束中心/星下点/目标）"))
    pg = cov.get("peak_ground") or {}
    mrows = []
    for lv in levels:
        m = metrics.get(round(lv, 1)) or metrics.get(lv) or {}
        mrows.append(["%s dBW（峰值−%s dB）" % (f(lv, 1), f(pg.get("eirp_dbw", 0) - lv, 0)),
                      f(m.get("diameter_km"), 0), f(m.get("area_km2"), 0), f(m.get("n_rays"), 0)])
    parts.append('<h3 class="doc-h3">11.2 覆盖足迹度量</h3>')
    parts.append(tabcap("11-1", "EIRP 等值线足迹度量（多方位射线平均直径 + 格点计数面积）")
                 + table(["等值线电平", "足迹直径 (km)", "覆盖面积 (km²)", "有效射线数"], mrows))
    parts.append('<p class="doc-p">目标 <b>%s</b>（%.2f°N, %.2f°E）；星下点/星位 '
                 '(%.2f°, %.2f°E, h=%s km)；地面峰值 EIRP <b>%s dBW</b> 位于 '
                 '(%.2f°N, %.2f°E)；最小工作仰角 %s°。%s</p>'
                 % (e(tgt.get("name", "")), tgt.get("lat", 0), tgt.get("lon", 0),
                    sat.get("lat", 0), sat.get("lon", 0), f(sat.get("h_km"), 0),
                    f(pg.get("eirp_dbw"), 1), pg.get("lat", 0), pg.get("lon", 0),
                    f(C.get("el_min"), 0), e(cov.get("note") or "")))
    parts.append('<p class="doc-p small">覆盖格点表与等值线线段可导出 CSV（lat,lon,eirp_dbw / '
                 'level,lat1,lon1,lat2,lon2），供 SATSOFT/Excel 交叉核对。</p>')
    return "".join(parts)


# ---------- 章节：12 轨道覆盖仿真 ----------
def _orbit_chapter(O, world_land=None):
    parts = ['<h3 class="doc-h3">12.1 星下点轨迹与瞬时覆盖</h3>',
             lead("轨道覆盖由 orbit_engine 内置仿真（STK 等效）：二体 Kepler + J2 长期摄动"
                  "（Ω̇、ω̇ 解析项）传播，ECI→ECEF 经 GMST（IAU1982）旋转；对每个目标点以固定步长扫描"
                  "仰角≥门限求可见窗（AOS/LOS/最大仰角/重访间隔），并按「星下点角距 ψ ≤ 覆盖帽半角 σ」"
                  "判定连续性。GEO 定点经度由数值标定升交点赤经（历元星下点经度=定点经度）实现。")]
    if not O or not O.get("assess"):
        parts.append('<p class="doc-p">轨道仿真不可用。</p>')
        return "".join(parts)
    assess = O["assess"]
    snap = O["snap"]
    parts.append(svg_orbit_track(O, world_land,
                                 title="%s 轨道 24h 星下点轨迹与快照覆盖（σ=%s°）"
                                       % (O.get("key"), f(snap.get("sigma_deg"), 1))))
    parts.append(figcap("12-1", "星下点轨迹（蓝虚线，跨 180° 经线自动分段）+ 快照覆盖帽（σ）+ 目标可见性"))
    parts.append(tabcap("12-1", "轨道要素与传播结果")
                 + table(["项", "值", "项", "值"], [
                     ["轨道类型", e(O.get("key")), "轨道高度", "%s km" % f(O.get("h_km"), 0)],
                     ["倾角 i", "%s°%s" % (f(O.get("incl"), 2),
                                          ("（太阳同步）" if O.get("sso_incl") else "")),
                      "偏心率 e", f(O.get("ecc"), 4)],
                     ["升交点赤经 Ω", "%s°" % f(O.get("raan"), 2), "轨道周期", "%s min" % f(O.get("period_min"), 1)],
                     ["Ω̇（J2）", "%s °/d" % f(O.get("raan_dot_deg_day"), 3), "最小仰角门限", "%s°" % f(O.get("el_min"), 0)],
                 ]))
    # 快照
    parts.append('<h3 class="doc-h3">12.2 指定时刻覆盖快照</h3>')
    parts.append('<p class="doc-p">历元 %s：星下点 (%.2f°N, %.2f°E)，高度 %s km，速度 %s km/s；'
                 '覆盖帽半角 σ=%s°（覆盖半径 ≈ %s km）。</p>'
                 % (e(snap.get("t_utc", "")), snap.get("sub_lat", 0), snap.get("sub_lon", 0),
                    f(snap.get("alt_km"), 1), f(snap.get("vel_kms"), 3),
                    f(snap.get("sigma_deg"), 2), f(snap.get("cov_radius_km"), 0)))
    trows = []
    for tg in snap.get("targets") or []:
        trows.append([e(tg.get("name", "")), "%.2f°N, %.2f°E" % (tg.get("lat", 0), tg.get("lon", 0)),
                      f(tg.get("el_deg"), 2), f(tg.get("slant_km"), 0),
                      ("可见 ✓" if tg.get("visible") else "不可见 ✗")])
    parts.append(tabcap("12-2", "快照时刻目标可见性")
                 + table(["目标", "位置", "仰角 (°)", "斜距 (km)", "可见性（仰角≥%s°）" % f(O.get("el_min"), 0)], trows))
    # 可见窗 + 评估
    parts.append('<h3 class="doc-h3">12.3 24h 可见窗与轨道合理性评估</h3>')
    wrows = []
    for r in assess.get("results") or []:
        wrows.append([e(r.get("target", "")), f(r.get("n_win"), 0), "%s%%" % f(r.get("cov_pct"), 1),
                      f(r.get("dur_max_min"), 1), f(r.get("el_max"), 1), f(r.get("revisit_h"), 2)])
    parts.append(tabcap("12-3", "目标 24h 可见窗统计")
                 + table(["目标", "窗口数", "覆盖率", "最长单窗 (min)", "最大仰角 (°)", "最长重访 (h)"], wrows))
    ok = assess.get("ok")
    badge = ('<span style="color:#1a7a2e;font-weight:bold">合理 ✓</span>' if ok
             else '<span style="color:#c0392b;font-weight:bold">需复核 ✗</span>')
    parts.append('<p class="doc-p"><b>轨道覆盖合理性判定：%s</b><br/>%s</p>'
                 % (badge, e(assess.get("verdict") or "")))
    parts.append('<p class="doc-p small">轨道历元状态可导出 STK Ephemeris <code>.e</code> 文件'
                 '（stk.v.12 · J2000 ECI · 位置+速度），供 STK 交叉核对覆盖与访问窗。</p>')
    return "".join(parts)


def svg_mc_hist(mc, W=620, H=260):
    """MC 余量分布直方图（目标余量红线）。"""
    hs = mc.get("hist") or {}
    cts = hs.get("counts") or []
    if not cts:
        return ""
    lo, hi = hs.get("lo", 0.0), hs.get("hi", 1.0)
    step = hs.get("step") or ((hi - lo) / max(len(cts), 1))
    cmax = max(cts) or 1
    PL, PR, PT, PB = 46, 16, 18, 40
    def X(v): return PL + (v - lo) / max(hi - lo, 1e-9) * (W - PL - PR)
    def Y(c): return PT + (1 - c / cmax) * (H - PT - PB)
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" font-family="SimSun,serif">' % (W, H, W, H)]
    s.append('<rect x="0" y="0" width="%d" height="%d" fill="#fbfdff" stroke="#9ab" rx="6"/>' % (W, H))
    for i in range(5):
        cv = cmax * i / 4.0
        yy = Y(cv)
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#dde6f0" stroke-width="0.7"/>' % (PL, yy, W - PR, yy))
        s.append('<text x="%d" y="%.1f" font-size="9" fill="#556" text-anchor="end">%d</text>' % (PL - 4, yy + 3, int(cv)))
    for i, c in enumerate(cts):
        x0, x1 = X(lo + i * step), X(lo + (i + 1) * step)
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#4d8fd1" opacity="0.82"/>'
                 % (x0, Y(c), max(x1 - x0 - 1, 1), Y(0) - Y(c)))
    tm = mc.get("m_target_db")
    if tm is not None and lo <= tm <= hi:
        tx = X(tm)
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#c0392b" stroke-width="1.6" stroke-dasharray="5,3"/>'
                 % (tx, PT, tx, H - PB))
        s.append('<text x="%.1f" y="%d" font-size="10" fill="#c0392b">目标 M=%s dB</text>' % (tx + 4, PT + 11, f(tm, 1)))
    for i in range(5):
        vv = lo + (hi - lo) * i / 4.0
        s.append('<text x="%.1f" y="%d" font-size="9" fill="#556" text-anchor="middle">%s</text>' % (X(vv), H - PB + 14, f(vv, 1)))
    s.append('<text x="%d" y="%d" font-size="10" fill="#345" text-anchor="middle">链路余量 M（dB）· n=%d · σ=%s dB</text>'
             % (W // 2, H - 6, mc.get("n", 0), f((mc.get("M") or {}).get("std"), 2)))
    s.append("</svg>")
    return "".join(s)


def svg_tornado(mc, W=620, H=None):
    """龙卷风图：各不确定项 ±2σ 对 M 的摆动。"""
    tor = mc.get("tornado") or []
    if not tor:
        return ""
    rowH = 26
    PL, PR, PT, PB = 180, 20, 26, 30
    H = H or (PT + PB + len(tor) * rowH)
    mean = (mc.get("M") or {}).get("mean") or 0.0
    smax = 0.5
    for t in tor:
        smax = max(smax, abs(t.get("m_high", mean) - mean), abs(t.get("m_low", mean) - mean))
    def X(v): return PL + (v - mean + smax) / (2 * smax) * (W - PL - PR)
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" font-family="SimSun,serif">' % (W, H, W, H)]
    s.append('<rect x="0" y="0" width="%d" height="%d" fill="#fbfdff" stroke="#9ab" rx="6"/>' % (W, H))
    s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#67809c" stroke-width="1"/>' % (X(mean), PT, X(mean), H - PB))
    for i, t in enumerate(tor):
        yy = PT + i * rowH + 4
        xa, xb = X(t.get("m_low", mean)), X(t.get("m_high", mean))
        s.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="3" fill="#e08b4c" opacity="0.85"/>'
                 % (min(xa, xb), yy, max(abs(xb - xa), 2), rowH - 12))
        s.append('<text x="%d" y="%d" font-size="10" fill="#234" text-anchor="end">%s ±2σ</text>'
                 % (PL - 8, yy + 12, e(t.get("cn") or t.get("param"))))
        s.append('<text x="%.1f" y="%d" font-size="9" fill="#8a5a2b">%s dB</text>'
                 % (max(xa, xb) + 5, yy + 12, f(t.get("span_db"), 2)))
    s.append('<text x="%.1f" y="%d" font-size="10" fill="#456" text-anchor="middle">M 均值 %s dB</text>' % (X(mean), PT - 9, f(mean, 2)))
    s.append('<text x="%d" y="%d" font-size="10" fill="#345" text-anchor="middle">单参数摆动（±2σ，其余名义）→ 加固优先级排序</text>' % (W // 2, H - 8))
    s.append("</svg>")
    return "".join(s)


def svg_rel_bars(rel, W=620, H=140):
    """可靠性三 R 口径水平条（单串基线/按 BOM 标注/标准 1:1 冗余设计）。"""
    PL, PR, PT = 160, 56, 16
    rows = [("单串基线（无冗余）", rel.get("r_serial_pct"), "#c05656"),
            ("按 BOM 冗余标注", rel.get("r_asbuilt_pct"), "#d99b3c"),
            ("标准 1:1 冗余设计", rel.get("r_designed_pct"), "#4a9a5f")]
    s = ['<svg width="%d" height="%d" viewBox="0 0 %d %d" font-family="SimSun,serif">' % (W, H, W, H)]
    s.append('<rect x="0" y="0" width="%d" height="%d" fill="#fbfdff" stroke="#9ab" rx="6"/>' % (W, H))
    for i, (lab, v, col) in enumerate(rows):
        yy = PT + i * 36
        vv = max(float(v or 0.0), 0.0)
        wv = vv / 100.0 * (W - PL - PR)
        s.append('<text x="%d" y="%d" font-size="10.5" fill="#234" text-anchor="end">%s</text>' % (PL - 8, yy + 15, e(lab)))
        s.append('<rect x="%d" y="%d" width="%d" height="17" fill="#eef3f9" stroke="#c9d8e8" rx="3"/>' % (PL, yy + 2, W - PL - PR))
        s.append('<rect x="%d" y="%d" width="%.1f" height="17" fill="%s" opacity="0.85" rx="3"/>' % (PL, yy + 2, wv, col))
        s.append('<text x="%.1f" y="%d" font-size="10.5" font-weight="bold" fill="#234">%s%%</text>' % (PL + wv + 5, yy + 15, f(vv, 1)))
    xg = PL + 0.9 * (W - PL - PR)
    s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#c0392b" stroke-width="1.3" stroke-dasharray="4,3"/>' % (xg, PT - 2, xg, PT + 96))
    s.append('<text x="%.1f" y="%d" font-size="9.5" fill="#c0392b">90%% 良好线</text>' % (xg + 3, PT + 9))
    s.append("</svg>")
    return "".join(s)


def _robust_chapter(R):
    """第 13 章：方案级稳健性分析（星蚀/位保/MC/XPD/可靠性/邻星，与前端⑬页同源）。"""
    rb = R.get("robust") or {}
    if not rb or rb.get("ok") is False and not any(
            rb.get(k) for k in ("eclipse", "station_keeping", "reliability")):
        return '<p class="doc-p">稳健性分析不可用（引擎未返回 robust 数据，见前端⑬页）。</p>'
    parts = ['<div class="lead">本章从六个维度核查方案在不确定性与寿命期约束下的稳健程度：'
             '星蚀供电（GEO 锚定分点最恶劣历元）、位置保持 ΔV 与推进剂寿命（齐奥尔科夫斯基）、'
             '链路灵敏度蒙特卡洛（dB 域精确叠加）、雨致去极化 XPD（ITU-R P.618-12 §4.1）、'
             'BOM+MTBF 可靠性三口径汇总与整改建议、邻星干扰 C/I（ITU-R S.465-6 旁瓣包络）。'
             '与前端第⑬页「稳健性分析」同源（design_all → R.robust）。</div>']
    parts.append('<p class="doc-p"><b>综合结论：</b>%s</p>' % e(rb.get("verdict") or ""))
    kind_cn = {"series": "单串", "pair": "1+1 冷备", "triple": "三模表决",
               "channel": "通道化降级", "array": "阵面降级"}
    ok_bad = lambda ok, t="满足", b="不满足": (
        '<span style="color:%s;font-weight:bold">%s</span>' % ("#1a7a2e" if ok else "#c0392b", t if ok else b))

    # ---- 13.1 星蚀供电 ----
    ec = rb.get("eclipse") or {}
    pw = ec.get("power") or {}
    parts.append('<h3 class="doc-h3">13.1 星蚀（地影）供电分析</h3>')
    if ec.get("error"):
        parts.append('<p class="doc-p">星蚀分析失败：%s</p>' % e(ec["error"]))
    else:
        parts.append(tabcap("13-1", "星蚀窗口与电池核算") + table(
            ["轨道", "星蚀段数（扫描窗）", "最长单段 (min)", "时长来源", "载荷功耗 (W)",
             "电池需求 (kWh, DoD≤80%)", "平台电池 (kWh)", "判定"],
            [["GEO（分点季锚定）" if ec.get("is_geo") else "LEO/MEO",
              str(ec.get("n_eclipses", 0)), f(ec.get("t_max_min"), 0), e(ec.get("t_max_source") or ""),
              f(pw.get("p_load_w"), 0), f(pw.get("e_req_kwh"), 2), f(pw.get("batt_kwh"), 2),
              ok_bad(pw.get("batt_ok") is not False)]]))
        parts.append('<p class="doc-p small">%s</p>' % e(ec.get("verdict") or ""))
        parts.append('<p class="doc-p small">GEO 星蚀只在春/秋分 ±22 天窗口出现（太阳赤纬 |δ|&lt;0.264°），'
                     '分析锚定最恶劣历元（worst_eclipse_epoch 扫描 ±400 天），避免任意历元得出「0 星蚀」'
                     '的非保守结论；数值扫描未捕获影段时以解析上限 72 min 兜底。</p>')

    # ---- 13.2 位保 ----
    sk = rb.get("station_keeping") or {}
    ske = rb.get("station_keeping_ep") or {}
    parts.append('<h3 class="doc-h3">13.2 位置保持 ΔV 与推进剂寿命</h3>')
    if sk.get("error"):
        parts.append('<p class="doc-p">位保分析失败：%s</p>' % e(sk["error"]))
    else:
        srows = [["化学推进（基准，Isp %s s）" % f(sk.get("isp_s"), 0),
                  f(sk.get("dv_per_yr"), 1), f(sk.get("dv_total_ms"), 0),
                  f(sk.get("m_prop_kg"), 0), f(sk.get("m_wet_kg"), 0),
                  f(sk.get("prop_frac_pct"), 1), ok_bad(sk.get("ok") is not False, "合理(<15%)", "偏高")]]
        if ske.get("dv_total_ms") is not None:
            srows.append(["电推对照（Isp 1800 s）", f(ske.get("dv_per_yr"), 1), f(ske.get("dv_total_ms"), 0),
                          f(ske.get("m_prop_kg"), 0), "—", "—",
                          ok_bad(ske.get("ok") is not False, "合理", "偏高")])
        parts.append(tabcap("13-2", "位保 ΔV 预算（齐奥尔科夫斯基）") + table(
            ["推进方式", "ΔV/年 (m/s)", "寿命期 ΔV (m/s)", "推进剂 (kg)", "湿重 (kg)", "占比 (%)", "判定"], srows))
        parts.append('<p class="doc-p small">%s</p>' % e(sk.get("verdict") or ""))

    # ---- 13.3 MC ----
    mc = rb.get("monte_carlo") or {}
    parts.append('<h3 class="doc-h3">13.3 链路灵敏度蒙特卡洛（下行）</h3>')
    if mc.get("ok") is False:
        parts.append('<p class="doc-p">%s</p>' % e(mc.get("error") or mc.get("note") or "未计算"))
    else:
        M = mc.get("M") or {}
        parts.append(tabcap("13-3", "余量分布统计") + table(
            ["n", "M 均值 (dB)", "σ (dB)", "P1", "P5", "P10", "P50", "P90",
             "P(M≥%s dB)" % f(mc.get("m_target_db"), 1), "ACM 期望容量 (Gbps)"],
            [[str(mc.get("n", 0)), f(M.get("mean")), f(M.get("std")), f(M.get("p1")), f(M.get("p5")),
              f(M.get("p10")), f(M.get("p50")), f(M.get("p90")),
              ok_bad((mc.get("p_close_pct") or 0) >= 95.0, "%s%%" % f(mc.get("p_close_pct"), 1),
                     "%s%%（偏低）" % f(mc.get("p_close_pct"), 1)),
              f((mc.get("acm_capacity_gbps") or {}).get("mean"))]]))
        hsvg = svg_mc_hist(mc)
        tsvg = svg_tornado(mc)
        if hsvg:
            parts.append(hsvg + figcap("13-1", "链路余量 M 蒙特卡洛分布（红虚线=目标余量）"))
        if tsvg:
            parts.append(tsvg + figcap("13-2", "龙卷风图：各不确定项 ±2σ 对余量的摆动（加固优先级）"))
        mh = mc.get("modcod_hist") or {}
        if mh:
            parts.append(tabcap("13-4", "ACM MODCOD 驻留分布") + table(
                ["MODCOD 档位", "驻留次数", "占比 (%)"],
                [[e(k), str(v), f(100.0 * v / max(mc.get("n", 1), 1), 1)]
                 for k, v in list(mh.items())[:8]]))
        parts.append('<p class="doc-p small">扰动口径：EIRP/G/T σ=0.5 dB、雨衰对数正态 σ=25%（P.618 模型自身不确定度）、'
                     '指向 0.25 dB、极化 0.15 dB、实现 0.2 dB。链路方程在 dB 域线性，蒙特卡洛叠加即精确解'
                     '（无小信号近似误差）。</p>')

    # ---- 13.4 XPD ----
    xp = rb.get("xpd") or {}
    iso = xp.get("isolation") or {}
    xd = iso.get("xpd") or {}
    parts.append('<h3 class="doc-h3">13.4 雨致去极化（XPD）与双极化复用</h3>')
    if xp.get("error"):
        parts.append('<p class="doc-p">XPD 分析失败：%s</p>' % e(xp["error"]))
    elif xd.get("XPD_p") is None:
        parts.append('<p class="doc-p">%s</p>' % e(xp.get("verdict") or xp.get("note") or ""))
    else:
        parts.append(tabcap("13-5", "XPD 预测（ITU-R P.618-12 §4.1）") + table(
            ["频率 (GHz)", "雨衰 A_p (dB)", "V(f)", "C_f", "C_A", "C_τ", "C_θ", "C_σ",
             "XPD_雨 (dB)", "冰晶 C_ice", "XPD_p (dB)", "天线交极隔离 (dB)", "有效隔离 (dB)",
             "复用要求 (dB)", "裕度 (dB)", "判定"],
            [[f(xd.get("f_ghz"), 1), f(xd.get("A_p_db")), f(xd.get("V"), 1), f(xd.get("C_f"), 1),
              f(xd.get("C_A"), 1), f(xd.get("C_tau"), 1), f(xd.get("C_theta"), 1), f(xd.get("C_sigma"), 1),
              f(xd.get("XPD_rain"), 1), f(xd.get("C_ice"), 1), f(xd.get("XPD_p"), 1),
              f(iso.get("reuse_xpol_db"), 0), f(iso.get("eff_iso_db"), 1),
              f(iso.get("xpd_spec_db"), 0), f(iso.get("margin_db"), 1),
              ok_bad(iso.get("ok") is not False, "满足", "需 XPIC/降复用")]]))
        parts.append('<p class="doc-p small">%s</p>' % e(xp.get("verdict") or ""))

    # ---- 13.5 可靠性 ----
    rel = rb.get("reliability") or {}
    adv = rb.get("redundancy") or {}
    parts.append('<h3 class="doc-h3">13.5 载荷可靠性汇总（BOM + MTBF，%s 年寿命）</h3>'
                 % f(rb.get("life_yr"), 0))
    if rel.get("error"):
        parts.append('<p class="doc-p">可靠性分析失败：%s</p>' % e(rel["error"]))
    else:
        parts.append('<p class="doc-p">结构统计：单机 %s 台 / %d 行；单串 %s 项、已冗余 %s 项、优雅降级 %s 项。'
                     '等效 MTBF ≈ %s h。三口径：%s</p>'
                     % (str(rel.get("n_units", 0)), len(rel.get("items") or []),
                        str(rel.get("n_series", 0)), str(rel.get("n_redundant", 0)),
                        str(rel.get("n_graceful", 0)),
                        ("%.0f 年" % (rel.get("mtbf_sys_h", 0) / 8760.0)) if rel.get("mtbf_sys_h") else "—",
                        e(rel.get("verdict") or "")))
        bsvg = svg_rel_bars(rel)
        if bsvg:
            parts.append(bsvg + figcap("13-3", "可靠性三口径对比（单串基线 → 按 BOM 标注 → 标准 1:1 冗余设计）"))
        parts.append(tabcap("13-6", "单机可靠性贡献（TOP10，按寿命期失效概率 q 降序）") + table(
            ["单机", "类别", "结构", "数量", "MTBF (h)", "q 寿命期 (%)", "q 设计口径 (%)", "贡献 (%)", "模型"],
            [[e(it.get("cn")), e(it.get("cat")), e(kind_cn.get(it.get("kind"), it.get("kind"))),
              str(it.get("qty")), "%.0e" % (it.get("mtbf_h") or 0), f(it.get("q_life_pct"), 3),
              f(it.get("q_designed_pct"), 3), f(it.get("contrib_pct"), 1), e((it.get("model") or "")[:40])]
             for it in (rel.get("items") or [])[:10]]))
        parts.append('<h4 class="doc-h4">13.5.1 整改建议（目标 R ≥ %s%%）</h4>' % f((adv.get("target_r") or 0.95) * 100, 0))
        parts.append('<p class="doc-p"><b>%s</b></p>' % e(adv.get("note") or ""))
        plan = adv.get("plan") or []
        if plan:
            parts.append(tabcap("13-7", "逐项整改措施与 R 演进") + table(
                ["单机", "结构", "措施", "q 前 (%)", "q 后 (%)", "R 后 (%)", "ΔR (pp)"],
                [[e(p.get("cn")), e(kind_cn.get(p.get("kind"), p.get("kind"))), e(p.get("action") or ""),
                  f(p.get("q_before_pct"), 2), f(p.get("q_after_pct"), 3),
                  f((p.get("r_after") or 0) * 100, 1), f(p.get("delta_pct"), 1)] for p in plan]))
        parts.append('<p class="doc-p small">模型：series q=1−exp(−nλt)；pair 逐件冷备 q=1−(1−q_u²)^n；'
                     'triple 2/3 表决 q=3q²−2q³；channel/array k-out-of-n（Poisson 近似，容差 10%/15%）。'
                     'MTBF 为分类工程保守估计，详细设计阶段以零件应力分析（GJB 299C / MIL-HDBK-217FN2 / ECSS-Q-30）'
                     '+ 降额系数替代。</p>')

    # ---- 13.6 邻星干扰 ----
    inf = rb.get("interference") or {}
    parts.append('<h3 class="doc-h3">13.6 邻星干扰 C/I（GSO 弧段协调）</h3>')
    if inf.get("error"):
        parts.append('<p class="doc-p">干扰分析失败：%s</p>' % e(inf["error"]))
    elif not inf.get("ci_dn_db") and inf.get("note"):
        parts.append('<p class="doc-p">%s</p>' % e(inf.get("verdict") or inf.get("note")))
    else:
        se = inf.get("single_entry_ok") or {}
        ges = inf.get("g_es") or {}
        me = inf.get("multi_entry") or {}
        parts.append(tabcap("13-8", "邻星干扰核算（ITU-R S.465-6 地面站旁瓣包络）") + table(
            ["轨位间隔 (°)", "站旁瓣包络 G(φ) (dBi)", "干扰星旁瓣 (dBi)",
             "下行 C/I (dB)", "下行 I/N (dB)", "上行 C/I (dB)",
             "单入境判定（ΔT/T≤20%）", "多入境 I/N (dB)"],
            [[f(inf.get("phi_sep_deg"), 2), f(ges.get("off_dbi"), 1),
              f(inf.get("g_sat_int_off_dbi"), 1),
              f(inf.get("ci_dn_db"), 1), f(inf.get("in_dn_db"), 1),
              f(inf.get("ci_up_db"), 1),
              ("下行%s/上行%s" % ("✓" if se.get("down") else "✗", "✓" if se.get("up") else "✗")),
              f(me.get("in_dn_db"), 1)]]))
        parts.append('<p class="doc-p small">%s</p>' % e(inf.get("verdict") or ""))
        parts.append('<p class="doc-p small">单入境判据：I/N ≤ −12.2 dB（ΔT/T ≤ 20%%）；'
                     '多入境判据：I/N_total ≤ −10 dB（ΔT/T ≤ 10%%）。C/(N+I) 恶化 %s dB。</p>'
                     % f(inf.get("degrade_dn_db"), 2))
    return "".join(parts)


def _appendix(R, meta_shelf_count=86):
    princ = R.get("principles") or []
    ps = []
    for pr in princ[:12]:
        body = str(pr.get("principle") or "").replace("\n", "<br/>")
        ps.append('<p class="doc-p"><b>%s（%s）</b><br/><span class="small">%s</span></p>'
                  % (e(pr.get("key")), e(pr.get("cn")), body))
    return ('<h3 class="doc-h3">附录A 单机工作原理（本方案涉及子系统）</h3>%s'
            '<h3 class="doc-h3">附录B 货架产品库说明</h3>'
            '<p class="doc-p">货架库共 %d 条单机产品（三线编号，水平分级：4=货架产品(飞行继承)、'
            '3=飞行继承产品、2=货架产品(在研转货架)、1=定制），覆盖 13 个类别：天线/LNA/变频/多工器/功放/'
            '相控阵组件/数字处理/再生基带/开关/激光/测控信标/机构/星务；含银河航天批产货架'
            '（Q/V 平板天线、Ka 8 波束 AiP、单片 8 波束赋形芯片、芯片化 DBF、5G NTN 星载基站）与'
            '国际参考产品（Tesat 激光终端族、SatNow 目录 SDR/OBC/测控转发器等）。</p>'
            % ("".join(ps), meta_shelf_count))


# ================================================================
# 项目论证报告排版辅助（封面 / 摘要 / 图题注 / 章导语）
# ================================================================
def _cover(R, name, now):
    """封面页：报告名称 + 方案要素表 + 版本信息（独占一页）。"""
    cfg, req = R.get("cfg") or {}, R.get("req") or {}
    ev = R.get("eval") or {}
    grade = ev.get("grade", "—")
    gc = {"A": "#1a7a2e", "B": "#0b5cad", "C": "#b8860b", "D": "#c0392b"}.get(grade, "#444")
    gtxt = {"A": "合理可行", "B": "基本可行", "C": "有条件可行", "D": "不可行"}.get(grade, "—")
    rows = [
        ["任务名称", cfg.get("name") or "—", "业务类型", req.get("service_cn") or cfg.get("service")],
        ["轨道类型", req.get("orbit_cn") or cfg.get("orbit"), "用户频段", req.get("band") or cfg.get("band")],
        ["覆盖区域", req.get("coverage_cn") or cfg.get("coverage"), "天线体制",
         (R.get("ant_info") or {}).get("cn") or cfg.get("ant_type")],
        ["转发体制", (R.get("mode_info") or {}).get("cn") or cfg.get("mode"), "系统容量",
         "%s Gbps" % f(R["res"]["summary"].get("C_sys"), 1)],
    ]
    t = table(["项目", "内容", "项目", "内容"], rows)
    return ('<div class="cover">'
            '<div class="cover-band">方案论证报告</div>'
            '<h1 class="cover-title">%s</h1>'
            '<p class="cover-sub">通信卫星有效载荷方案论证报告</p>'
            '<div class="cover-grade" style="border-color:%s;color:%s">'
            '方案评级 %s · %s</div>'
            '<div class="cover-tbl">%s</div>'
            '<p class="cover-meta">编制工具：载荷方案设计器（五步闭环 · 第一性原理）<br/>'
            '生成时间：%s　｜　文档状态：方案级论证稿<br/>'
            '校核依据：25 条工程约束 · 10 项评价准则（E1~E10）</p>'
            '</div>' % (e(name), gc, gc, e(grade), e(gtxt), t, now))


def _abstract(R):
    """摘要页（结论先行）：一段综述 + 关键指标速览 + 可行性结论。"""
    s, t = R["res"]["summary"], R["totals"]
    cfg, req = R.get("cfg") or {}, R.get("req") or {}
    ev = R.get("eval") or {}
    sc = R.get("score") or {}
    plat = (R.get("platform") or [None, {}])[1]
    lau = (R.get("launcher") or [None, {}])[1]
    grade = ev.get("grade", "—")
    gc = {"A": "#1a7a2e", "B": "#0b5cad", "C": "#b8860b", "D": "#c0392b"}.get(grade, "#444")
    concl = ev.get("conclusion") or "—"
    n_gap = t.get("n_custom")
    summary_txt = (
        "本报告针对<b>%s</b>业务需求，在 <b>%s</b> 轨道对 <b>%s</b> 覆盖区开展有效载荷方案论证。"
        "方案采用 <b>%s</b> 天线体制、<b>%s</b> 转发体制，工作于 <b>%s</b> 频段；"
        "经第一性原理链路预算闭合与 25 条工程约束逐项校核，"
        "下行 MODCOD 达 <b>%s</b>，端到端余量 <b>%s dB</b>，整星容量 <b>%s Gbps</b>；"
        "载荷质量 <b>%s kg</b>、功耗 <b>%s W</b>，货架水平 <b>%s</b>，定制缺口 <b>%s 项</b>。"
        % (e(req.get("service_cn") or cfg.get("service")), e(req.get("orbit_cn") or cfg.get("orbit")),
           e(req.get("coverage_cn") or cfg.get("coverage")),
           e((R.get("ant_info") or {}).get("cn") or cfg.get("ant_type")),
           e((R.get("mode_info") or {}).get("cn") or cfg.get("mode")),
           e(req.get("band") or cfg.get("band")),
           e(s.get("modcod") or "—"), f(s.get("M_e2e"), 2), f(s.get("C_sys"), 1),
           f(t.get("m_pay"), 0), f(t.get("p_pay"), 0), e(t.get("H_scheme")), e(n_gap)))
    kpi = table(["关键指标", "数值", "关键指标", "数值"], [
        ["星上 EIRP", "%s dBW" % f(s.get("EIRP"), 1), "星上 G/T", "%s dB/K" % f(s.get("GT"), 1)],
        ["上行余量", "%s dB" % f(s.get("M_up"), 2), "下行余量", "%s dB" % f(s.get("M_dn"), 2)],
        ["端到端余量", "%s dB" % f(s.get("M_e2e"), 2), "下行 MODCOD", s.get("modcod") or "—"],
        ["整星容量", "%s Gbps" % f(s.get("C_sys"), 1), "六维综合评分", "%s /10" % f(sc.get("total"), 2)],
        ["载荷质量", "%s kg" % f(t.get("m_pay"), 0), "载荷功耗", "%s W" % f(t.get("p_pay"), 0)],
        ["推荐平台", plat.get("cn", "—"), "推荐运载", lau.get("cn") or "—"],
    ])
    return ('<div class="abs">'
            '<h2 class="doc-h2 abs-h">摘&nbsp;&nbsp;要</h2>'
            '<p class="abs-lead">%s</p>'
            '<div class="abs-kpi">%s</div>'
            '<div class="abs-concl" style="border-left-color:%s">'
            '<b style="color:%s">可行性结论（评级 %s）：</b>%s</div>'
            '<p class="small abs-note">判据通过 %s/%s ｜ 硬准则 %s ｜ 软准则 %s ｜ '
            '诊断：%s。本报告用于方案级论证，正式设计以详细链路预算与正式 ICD 为准。</p>'
            '</div>'
            % (summary_txt, kpi, gc, gc, e(grade), e(concl),
               s.get("judge_pass"), s.get("judge_total"),
               e(ev.get("pass_hard", "—")), e(ev.get("pass_soft", "—")), e(ev.get("level", "—"))))


def figcap(no, text):
    """图题注（居中，图号加粗）。"""
    return '<p class="figcap"><b>图 %s</b>　%s</p>' % (e(no), e(text))


def tabcap(no, text):
    """表题注（左对齐，表号加粗，置于表上方）。"""
    return '<p class="tabcap"><b>表 %s</b>　%s</p>' % (e(no), e(text))


def lead(text):
    """章节导语（灰底左边框，导读用）。"""
    return '<p class="lead">%s</p>' % text


# ================================================================
# 报告总装
# ================================================================
def build_report(R, icd=None, beam=None, world_land=None, name=None,
                 shelf_count=86, rasterize=True):
    """R = design_all 结果；beam = 一维方向图数据（可空→服务端解析补算）。
    返回完整 Word 兼容 HTML 字符串（项目论证报告版式：封面 / 摘要 / 目录 / 正文 / 附录）。
    rasterize=True 时把所有内嵌 <svg> 光栅化为 PNG（Edge headless）——
    Word 的 HTML 导入滤镜不渲染内嵌 SVG（GRASP 方向图/架构图打不开的根因），
    转 <img data:image/png> 后 Word/WPS 均可直接显示；Edge 不可用时自动回退保留 SVG。"""
    cfg = R.get("cfg") or {}
    name = (name or cfg.get("name") or "通信卫星有效载荷方案").strip()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    s = R["res"]["summary"]

    # ---- 服务端补算：波束方向图（1D + 2D）----
    ant = R["res"]["antenna"]
    D_m = ant.get("D_m")
    if not D_m:
        Glin = 10 ** ((ant.get("G_ant") or 0) / 10)
        eta = float(cfg.get("η_ill") or 65) / 100 or 0.65
        D_m = (ant.get("lam_m") or 0.02) / math.pi * math.sqrt(max(Glin, 1) / eta)
    dn = R["res"].get("downlink") or {}
    f_ghz = dn.get("f_ghz") or 20.0
    if not beam or not beam.get("ok"):
        beam = GB.beam_performance(D_m, f_ghz, prefer="grasp", tag="rpt")
    scan_deg = float(cfg.get("θ_scan") or 0)
    beam2d_svg, p2 = svg_pattern_2d(beam, D_m, f_ghz, scan_deg=scan_deg, n=51)
    scan_note = ("相控阵扫描角 %s°（扫描损耗按 cos^1.5 计入二维图）" % f(scan_deg, 0)) if scan_deg else ""

    # ---- 三引擎补算：次级方向图（boresight/扫描）+ 地面 EIRP 覆盖 + 轨道仿真 ----
    pat_sec_html = cov_html = orb_html = ""
    try:
        pat_bore, pmeta = _compute_pattern(R)
        th_scan = float(cfg.get("θ_scan") or 0)
        pat_scan = None
        if pmeta["is_arr"] and th_scan > 0.5:
            pat_scan, _ = _compute_pattern(R, scan_theta=th_scan)
        pat_sec_html = _pattern_section(pat_bore, pat_scan, pmeta)
    except Exception:
        pass
    try:
        COV = _compute_coverage(R)
        cov_html = _coverage_chapter(COV, world_land)
    except Exception:
        cov_html = '<p class="doc-p">地面 EIRP 覆盖计算不可用（引擎异常，见前端②总览页）。</p>'
    try:
        ORB = _compute_orbit(R)
        orb_html = _orbit_chapter(ORB, world_land)
    except Exception:
        orb_html = '<p class="doc-p">轨道覆盖仿真不可用（引擎异常，见前端⑫轨道页）。</p>'

    chapters = [
        ("项目概述与需求分析", _req_chapter(R)),
        ("设计原理与方法论", _principle_chapter(R)),
        ("总体方案", _scheme_chapter(R)),
        ("天线与波束性能", _ant_chapter(R, beam, beam2d_svg, p2, scan_note) + pat_sec_html),
        ("链路预算与转发器方案", _link_chapter(R)),
        ("单机选型与货架清单", _equip_chapter(R)),
        ("接口与协议（MOSA 标准化 ICD）", _icd_chapter(icd)),
        ("约束校验与回环", _valid_chapter(R)),
        ("方案评价标准与可行性结论（E1~E10）", _eval_chapter(R)),
        ("星座组网与多覆盖区", _constellation_chapter(R)),
        ("地面 EIRP 覆盖分析（SATSOFT 等效）", cov_html),
        ("轨道覆盖仿真（STK 等效）", orb_html),
        ("方案级稳健性分析", _robust_chapter(R)),
        ("附录", _appendix(R, shelf_count)),
    ]
    # 覆盖 3D 图插入第 3 章末
    globe = svg_globe_3d(R, world_land)
    chapters[2] = (chapters[2][0],
                   chapters[2][1] + '<h3 class="doc-h3">3.7 三维覆盖示意图</h3>'
                   + globe + figcap("3-5", "三维覆盖示意图（正交投影，含海岸线/覆盖圈/波束栅格/星下点）"))

    body = []
    # 封面 + 摘要（各自独占一页）
    body.append(_cover(R, name, now))
    body.append('<br style="page-break-after:always"/>')
    body.append(_abstract(R))
    body.append('<br style="page-break-after:always"/>')
    # 目录
    body.append('<h2 class="doc-h2 toc-h">目&nbsp;&nbsp;录</h2><table class="toc">')
    for i, (t, _) in enumerate(chapters, 1):
        body.append('<tr><td class="toc-n">%d</td><td class="toc-t">%s</td></tr>' % (i, e(t)))
    body.append('</table>')
    body.append('<br style="page-break-after:always"/>')
    for i, (t, htm) in enumerate(chapters, 1):
        body.append('<h2 class="doc-h2">%d　%s</h2>' % (i, e(t)))
        body.append('<div class="doc-sec">%s</div>' % htm)
        body.append('<br style="page-break-before:always"/>')
    body.append('<p class="doc-foot">本报告由载荷方案设计器按 %d 条工程约束自动校核生成；'
                '单机默认值为工程典型值，仅用于方案级论证，正式设计以详细链路预算与正式 ICD 为准。<br/>'
                '标准化参考：MOSA / FACE / CCSDS / ECSS / MIL-STD-1553B。</p>' % 25)
    content = "\n".join(body)

    css = """
body{font-family:"仿宋","FangSong","宋体",serif;font-size:12pt;line-height:1.85;color:#000}
/* ---- 封面 ---- */
.cover{text-align:center;padding-top:36pt}
.cover-band{display:inline-block;font-family:"黑体","SimHei",sans-serif;font-size:11pt;
  letter-spacing:6pt;color:#0b5cad;border:1.2pt solid #0b5cad;padding:3pt 16pt;margin-bottom:30pt}
.cover-title{font-family:"方正小标宋简体","黑体","SimHei",sans-serif;font-size:26pt;line-height:1.4;
  margin:0 0 10pt;color:#0b3d6e}
.cover-sub{font-family:"黑体","SimHei",sans-serif;font-size:15pt;color:#222;margin:0 0 20pt}
.cover-grade{display:inline-block;font-size:13pt;font-weight:bold;border:2pt solid;
  border-radius:4pt;padding:5pt 20pt;margin:6pt 0 24pt}
.cover-tbl{width:86%;margin:0 auto}
.cover-tbl table{border-collapse:collapse;width:100%;font-size:11pt}
.cover-tbl th,.cover-tbl td{border:0.75pt solid #9ab;padding:5pt 8pt;text-align:left}
.cover-tbl th{background:#eef3fa;font-family:"黑体","SimHei",sans-serif;font-weight:normal;width:16%}
.cover-meta{font-size:10.5pt;color:#444;margin-top:34pt;line-height:2.0}
/* ---- 摘要 ---- */
.abs-h{border-bottom:2pt solid #0b5cad}
.abs-lead{font-size:11.5pt;text-align:justify;text-indent:2em;margin:8pt 0 12pt;line-height:1.95}
.abs-kpi table{border-collapse:collapse;width:100%;font-size:10pt;margin:6pt 0}
.abs-kpi th,.abs-kpi td{border:0.75pt solid #9ab;padding:4pt 7pt}
.abs-kpi th{background:#eef3fa;font-family:"黑体","SimHei",sans-serif;font-weight:normal}
.abs-concl{font-size:11.5pt;border-left:4pt solid #0b5cad;background:#f6f9fd;
  padding:8pt 12pt;margin:12pt 0;text-align:justify;line-height:1.8}
.abs-note{margin-top:10pt;text-align:justify}
/* ---- 标题层级 ---- */
.doc-h2{font-family:"黑体","SimHei",sans-serif;font-size:16pt;margin:0 0 10pt;
  padding:0 0 5pt;border-bottom:2pt solid #0b5cad;color:#0b3d6e;page-break-after:avoid}
.toc-h{border-bottom:2pt solid #0b5cad}
.doc-h3{font-family:"黑体","SimHei",sans-serif;font-size:13pt;margin:16pt 0 6pt;
  color:#0b3d6e;page-break-after:avoid}
.doc-h4{font-family:"黑体","SimHei",sans-serif;font-size:11.5pt;margin:11pt 0 4pt;
  color:#333;page-break-after:avoid}
/* ---- 正文 ---- */
.doc-p{font-size:11pt;margin:6pt 0;text-align:justify}
.doc-ul{font-size:10.5pt;margin:4pt 0 8pt 20pt;line-height:1.8}
.doc-sec{font-size:11pt}
.lead{font-size:10.5pt;color:#3a4a5a;background:#f4f7fb;border-left:3.5pt solid #7ea3d0;
  padding:7pt 12pt;margin:6pt 0 12pt;text-align:justify;line-height:1.8}
/* ---- 表格 ---- */
.doc-sec table{border-collapse:collapse;width:100%;font-size:9.5pt;margin:5pt 0 10pt}
.doc-sec th,.doc-sec td{border:0.75pt solid #9ab;padding:4pt 6pt;text-align:left;vertical-align:top}
.doc-sec th{background:#dce6f4;font-family:"黑体","SimHei",sans-serif;font-weight:normal;color:#0b3d6e}
.doc-sec tr:nth-child(even) td{background:#f7f9fc}
/* ---- 图表题注 ---- */
.figcap{text-align:center;font-size:9.5pt;color:#333;margin:3pt 0 14pt;page-break-before:avoid}
.tabcap{font-size:9.5pt;color:#0b3d6e;margin:10pt 0 2pt;page-break-after:avoid}
.doc-sec img{display:block;margin:6pt auto;max-width:100%;height:auto}
.doc-sec svg{display:block;margin:6pt auto;max-width:100%;height:auto}
/* ---- 目录 / 其它 ---- */
table.toc{border:none;width:78%;margin-top:8pt}
table.toc td{border:none;font-size:12pt;padding:3.5pt 6pt}
.toc-n{width:40pt;text-align:right;color:#0b5cad;font-weight:bold;font-family:"黑体","SimHei",sans-serif}
table.nob,td.nob{border:none!important;background:transparent}
.doc-foot{font-size:9pt;color:#555;text-align:center;margin-top:12pt;border-top:0.75pt solid #ccc;padding-top:8pt}
.small{font-size:9.5pt;color:#444}
"""
    mso = """
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom>
<w:DoNotOptimizeForBrowser/></w:WordDocument></xml><![endif]-->
<style>@page WordSection1{size:595.3pt 841.9pt;margin:72pt 60pt 72pt 60pt;mso-header-margin:42.55pt;
mso-footer-margin:49.6pt;mso-paper-source:0;}div.WordSection1{page:WordSection1;}</style>
"""
    doc = ('<!DOCTYPE html>\n<html xmlns:o="urn:schemas-microsoft-com:office:office" '
           'xmlns:w="urn:schemas-microsoft-com:office:word" '
           'xmlns="http://www.w3.org/TR/REC-html40">\n<head>\n'
           '<meta charset="utf-8">\n'
           '<meta name="ProgId" content="Word.Document">\n'
           '<meta name="Generator" content="payload-design report_gen">\n'
           '<title>%s</title>\n%s<style>%s</style>\n</head>\n'
           '<body><div class="WordSection1">\n%s\n</div></body>\n</html>'
           % (e(name), mso, css, content))
    if rasterize:
        try:
            doc = rasterize_svgs(doc)
        except Exception:
            pass                      # 光栅化失败 → 保留内嵌 SVG（HTML 预览仍可看）
    return doc


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
    import design_data as DD
    import design_engine as DE
    import design_app as DA
    cfg = dict(DD.DEFAULT_CFG, name="报告自检", service="高通量宽带", orbit="GEO",
               coverage="巴基斯坦", band="Ka", feeder_band="Ka", mode="数字透明",
               ant_type="固面")
    # 一键建议值闭环（建议→验证→自动修正→评级），用闭环后的可行参数出报告
    sg = DE.suggest_closed_loop(cfg, DA.KG)
    cl = sg.get("closed") or {}
    for k, v in (sg.get("values") or {}).items():
        if v != "":
            cfg[k] = v
    print("closed-loop: grade=%s iters=%s feasible=%s" %
          (cl.get("grade"), cl.get("iters"), cl.get("feasible")))
    R = DE.design_all(cfg, DA.KG, skip_compare=True)
    R["_cov_meta"] = DD.COVERAGE.get("巴基斯坦", {})
    R["_orbit_alt_km"] = DD.ORBITS["GEO"]["alt_km"]
    icd = PG.generate_icd(R)
    doc = build_report(R, icd=icd, world_land=DA.world_land())
    out = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\_report_selftest.doc"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\ufeff" + doc)
    print("OK", len(doc), "chars ->", out)
