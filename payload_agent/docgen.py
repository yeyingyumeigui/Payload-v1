"""方案文档生成与导出 (SK-DOC / SK-WORD)

SK-DOC : 将选型、链路预算、校验结果装配为完整 Markdown 方案文档（确定性模板，
         不依赖 LLM，可复现可审计；LLM 润色为可选增强）。
SK-WORD: Markdown → HTML（中文排版 + 目录 + DOC 下载 + 打印/PDF）。

零依赖：内置极简 Markdown 渲染器（标题/表格/代码块/列表/引用/details/粗体/行内码）。
"""

from __future__ import annotations

import datetime
import html as html_mod
import logging
import re
from typing import List, Optional

from .intent import IntentResult
from .selection import SelectionPlan
from .link_budget import LinkBudget, ValidationResult, link_budget_markdown

logger = logging.getLogger(__name__)


# ============================================================
# SK-DOC: Markdown 方案装配
# ============================================================

def generate_scheme(intent: IntentResult, plan: SelectionPlan,
                    budgets: Optional[List[LinkBudget]] = None,
                    validation: Optional[ValidationResult] = None,
                    user_input: str = "") -> str:
    """装配完整 Markdown 方案文档"""
    today = datetime.date.today().isoformat()
    label = {"communication": "通信", "remote_sensing": "遥感",
             "navigation": "导航", "science": "科学实验"}.get(
        intent.payload_type, "通用")
    title = (f"{intent.orbit_type} {label}卫星有效载荷方案"
             if intent.orbit_type not in ("unknown", "") else f"{label}卫星有效载荷方案")

    sec: List[str] = []
    sec.append(f"# {title}")
    sec.append(f"> 文生载荷智能体自动生成 | {today} | 版本 V0.1（骨架）\n>\n"
               f"> 原始需求：{user_input or intent.raw_input}")

    # 1 需求分析
    sec.append("## 一、需求分析")
    sec.append(intent.summary().replace(" | ", "\n- "), )
    sec[-1] = "- " + sec[-1]
    if intent.ambiguity:
        sec.append(f"\n**歧义提示**：{intent.ambiguity}")
    if intent.special_requirements:
        sec.append(f"\n**特殊需求**：{'、'.join(intent.special_requirements)}")

    # 2 选型需求（五要素/判据）
    sec.append("## 二、选型需求与判据")
    sec.append(plan.requirement_markdown())

    # 3 载荷方案
    sec.append("## 三、载荷方案")
    if plan.is_comm:
        if plan.architecture:
            sec.append(plan.architecture_markdown())
        sec.append(plan.antenna_markdown())
        sec.append(plan.equipment_markdown())
    else:
        sec.append(plan.noncomm_markdown())

    # 4 平台
    sec.append("## 四、平台方案")
    sec.append(plan.platform_markdown())

    # 5 运载
    sec.append("## 五、发射方案")
    sec.append(plan.launcher_markdown())

    # 6 指标汇总与校核
    sec.append("## 六、指标汇总与平台校核")
    sec.append(plan.summary_markdown())

    # 7 链路预算
    sec.append("## 七、链路预算与余量校核")
    sec.append(link_budget_markdown(budgets or []))

    # 8 三重校验
    if validation is not None:
        sec.append("## 八、方案三重校验")
        sec.append(validation.markdown())

    # 9 风险与异常处置
    sec.append("## 九、风险与异常处置")
    sec.append(_risk_markdown(plan, validation))

    # 10 结论
    sec.append("## 十、结论")
    sec.append(_conclusion_markdown(plan, validation))

    return "\n\n".join(sec) + "\n"


def _requirement_analysis_md(intent: IntentResult) -> str:
    """需求分析要素表（中文标签）"""
    pl = {"communication": "通信载荷", "remote_sensing": "遥感载荷",
          "navigation": "导航载荷", "science": "科学实验载荷"}.get(
        intent.payload_type, "未识别")
    rows = [("载荷类型", pl), ("目标轨道", intent.orbit_type)]
    if intent.frequency_bands:
        rows.append(("工作频段", " / ".join(intent.frequency_bands)))
    if intent.key_technologies:
        rows.append(("关键技术", "、".join(intent.key_technologies)))
    if intent.antenna_types:
        rows.append(("天线形态", "、".join(intent.antenna_types)))
    if intent.forwarding_mode:
        fm = {"transparent": "透明转发", "regenerative": "处理转发（星上再生）",
              "dtp": "柔性载荷（DTP）"}.get(intent.forwarding_mode,
                                           intent.forwarding_mode)
        rows.append(("转发体制", fm))
    if intent.rs_subtype:
        rows.append(("遥感细分", intent.rs_subtype))
    unit = {"eirp_dbw": ("EIRP", " dBW"), "gt_dbk": ("G/T", " dB/K"),
            "mass_kg": ("载荷质量约束", " kg"), "power_w": ("载荷功耗约束", " W"),
            "life_years": ("任务寿命", " 年"), "capacity_gbps": ("容量需求", " Gbps"),
            "beam_num": ("波束数", " 个"), "bandwidth_mhz": ("带宽", " MHz"),
            "resolution_m": ("空间分辨率", " m"), "swath_km": ("幅宽", " km")}
    for k, v in intent.metrics.items():
        if k in unit:
            name, u = unit[k]
            rows.append((name, f"{v:g}{u}"))
    out = ["| 要素 | 取值 |", "|------|------|"]
    out += [f"| {a} | {b} |" for a, b in rows]
    return "\n".join(out)


def _risk_markdown(plan: SelectionPlan,
                   validation: Optional[ValidationResult]) -> str:
    out = ["| 风险项 | 等级 | 影响 | 处置措施 |", "|--------|------|------|---------|"]
    if not plan.feasible:
        out.append("| 平台不可行 | **L3** | 方案中止 | 拆分载荷多星部署 / 改换轨道 / 定制大平台（人工决策） |")
    if plan.gaps:
        names = "、".join(g["need"] for g in plan.gaps)
        out.append(f"| 定制缺口 {len(plan.gaps)} 项 | L2 | 研制周期与成本上升 | 立项定制：{names} |")
    if plan.warnings:
        for w in plan.warnings[:3]:
            out.append(f"| {w[:40]} | L2 | 指标裕度 | 见选型告警详情 |")
    if validation and validation.errors:
        for e in validation.errors[:3]:
            out.append(f"| {e[:50]} | L2 | 校验不通过 | 回环调整选型或链路参数 |")
    if validation and validation.warnings:
        for w in validation.warnings[:3]:
            out.append(f"| {w[:50]} | L1 | 告警 | 跟踪观察 |")
    if len(out) == 2:
        out.append("| 无重大风险 | — | — | 按流程推进 |")
    return "\n".join(out)


def _conclusion_markdown(plan: SelectionPlan,
                         validation: Optional[ValidationResult]) -> str:
    ok = plan.feasible and (validation.valid if validation else True)
    head = "**方案可行，可进入详细设计阶段。**" if ok else \
        "**方案存在阻断项，须回环调整或人工决策后再放行。**"
    lines = [head, ""]
    if plan.is_comm and plan.antenna:
        lines.append(f"- 载荷：{plan.antenna['model']}（{plan.antenna['name']}）"
                     f" + 货架单机 {len(plan.equipment)} 台")
    elif plan.noncomm_top:
        lines.append(f"- 载荷：{plan.noncomm_top['model']}（{plan.noncomm_top['name']}）")
    if plan.platform:
        lines.append(f"- 平台：{plan.platform['model']}（{plan.platform['name']}），"
                     f"整星约 {plan.sat_mass_est:.0f} kg")
    if plan.launcher:
        lines.append(f"- 发射：{plan.launcher['name']}（{plan.launcher['country']}）")
    if plan.gaps:
        lines.append(f"- 定制缺口 {len(plan.gaps)} 项，需专项立项")
    lines.append(f"- 校核回环迭代 {plan.iteration} 次，"
                 f"可行性{'通过' if plan.feasible else '未通过'}")
    return "\n".join(lines)


# ============================================================
# 极简 Markdown → HTML 渲染器（零依赖）
# ============================================================

def _inline(text: str) -> str:
    """行内元素：转义 → 粗体 → 行内码"""
    t = html_mod.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


_RAW_BLOCK_RE = re.compile(
    r"^\s*<(svg|div|figure|table|img|iframe|details)\b", re.I)


def markdown_to_html_body(md: str) -> str:
    """将 Markdown 渲染为 HTML 主体

    支持：标题 / 表格 / 代码块 / 列表 / 引用 / details / 原生 HTML 块（SVG 流程图）。
    原生 HTML 块按原样透传（不做转义），用于内嵌 SVG 流程图；
    其余文本一律转义，避免注入。
    """
    lines = md.split("\n")
    out: List[str] = []
    i, n = 0, len(lines)
    in_code = False
    in_ul = False
    in_tbl = False
    in_raw = False
    raw_tag = ""
    tbl_rows: List[str] = []

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def flush_table():
        nonlocal in_tbl, tbl_rows
        if not in_tbl:
            return
        out.append('<table>')
        for ri, row in enumerate(tbl_rows):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if ri == 0:
                out.append("<thead><tr>" +
                           "".join(f"<th>{_inline(c)}</th>" for c in cells) +
                           "</tr></thead><tbody>")
            else:
                out.append("<tr>" +
                           "".join(f"<td>{_inline(c)}</td>" for c in cells) +
                           "</tr>")
        out.append("</tbody></table>")
        in_tbl, tbl_rows = False, []

    while i < n:
        line = lines[i]

        # 原生 HTML 块（SVG 等）：整段透传至闭合标签
        if not in_code and not in_raw and _RAW_BLOCK_RE.match(line):
            close_ul()
            flush_table()
            raw_tag = _RAW_BLOCK_RE.match(line).group(1).lower()
            in_raw = True
            out.append(line)
            if re.search(rf"</{raw_tag}\s*>", line, re.I):
                in_raw = False
            i += 1
            continue
        if in_raw:
            out.append(line)
            if re.search(rf"</{raw_tag}\s*>", line, re.I):
                in_raw = False
            i += 1
            continue

        # 代码块
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                close_ul()
                flush_table()
                out.append("<pre><code>")
                in_code = True
            i += 1
            continue
        if in_code:
            out.append(html_mod.escape(line))
            i += 1
            continue

        # details / summary（Markdown 内联写法）
        m = re.match(r"^<details><summary>(.*)</summary>\s*$", line.strip())
        if m:
            close_ul()
            out.append(f"<details><summary>{_inline(m.group(1))}</summary>")
            i += 1
            continue
        if line.strip() == "</details>":
            out.append("</details>")
            i += 1
            continue

        # 表格
        if line.strip().startswith("|"):
            if re.match(r"^\s*\|[\s:|-]+\|\s*$", line):   # 分隔行
                i += 1
                continue
            close_ul()
            if not in_tbl:
                in_tbl = True
            tbl_rows.append(line)
            i += 1
            continue
        flush_table()

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_ul()
            lvl = len(m.group(1))
            txt = m.group(2)
            anchor = re.sub(r"[^\w\u4e00-\u9fff]+", "-", txt).strip("-")
            out.append(f'<h{lvl} id="{anchor}">{_inline(txt)}</h{lvl}>')
            i += 1
            continue

        # 引用
        if line.startswith(">"):
            close_ul()
            out.append(f"<blockquote>{_inline(line.lstrip('> ').rstrip())}</blockquote>")
            i += 1
            continue

        # 列表
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        m = re.match(r"^\s*(\d+)[.)]\s+(.*)$", line)
        if m:
            close_ul()
            out.append(f'<p class="num">{m.group(1)}. {_inline(m.group(2))}</p>')
            i += 1
            continue
        close_ul()

        # 空行 / 段落
        if not line.strip():
            i += 1
            continue
        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    close_ul()
    flush_table()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def build_toc(md: str) -> str:
    """从 Markdown 提取 h2/h3 生成目录"""
    items = []
    for line in md.split("\n"):
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            txt = m.group(2)
            anchor = re.sub(r"[^\w\u4e00-\u9fff]+", "-", txt).strip("-")
            items.append((lvl, anchor, txt))
    if not items:
        return ""
    out = ['<nav class="toc"><div class="toc-title">目 录</div><ul>']
    for lvl, anchor, txt in items:
        cls = "toc-2" if lvl == 2 else "toc-3"
        out.append(f'<li class="{cls}"><a href="#{anchor}">{html_mod.escape(txt)}</a></li>')
    out.append("</ul></nav>")
    return "\n".join(out)


# ============================================================
# SK-WORD: HTML 页面装配（DOC 下载 + 打印/PDF）
# ============================================================

PAGE_CSS = """
:root { --ink:#1a2233; --muted:#5a6a85; --line:#dde5f0; --accent:#1f5eff;
        --bg:#f5f7fb; --card:#ffffff; --ok:#1a7f4b; --bad:#c2372c; --warn:#b07a1f; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font-family:"Source Han Serif SC","Noto Serif CJK SC","SimSun","宋体",serif;
       font-size:15px; line-height:1.85; }
.toolbar { position:sticky; top:0; z-index:50; display:flex; gap:10px; align-items:center;
           padding:10px 24px; background:#0f1c3f; color:#fff; }
.toolbar .title { font-weight:700; margin-right:auto; font-size:15px;
                  font-family:"Source Han Sans SC","Microsoft YaHei",sans-serif; }
.toolbar button { border:1px solid rgba(255,255,255,.45); background:transparent;
           color:#fff; padding:6px 16px; border-radius:6px; cursor:pointer; font-size:13px;
           font-family:"Source Han Sans SC","Microsoft YaHei",sans-serif; }
.toolbar button:hover { background:rgba(255,255,255,.15); }
.page { max-width:920px; margin:24px auto 64px; background:var(--card);
        padding:56px 64px; border:1px solid var(--line); border-radius:8px;
        box-shadow:0 2px 14px rgba(15,28,63,.06); }
h1 { text-align:center; font-size:26px; line-height:1.5; margin:.2em 0 .8em;
     font-family:"Source Han Serif SC","SimSun",serif; }
h2 { font-size:19px; margin:1.8em 0 .6em; padding-left:10px;
     border-left:4px solid var(--accent); }
h3 { font-size:16px; margin:1.4em 0 .5em; }
p { margin:.5em 0; text-align:justify; }
blockquote { margin:.8em 0; padding:8px 14px; background:#f0f4fb;
             border-left:3px solid var(--accent); color:var(--muted); font-size:14px; }
table { border-collapse:collapse; width:100%; margin:.8em 0; font-size:13.5px; }
th,td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }
th { background:#eef2f9; font-weight:700; white-space:nowrap; }
tr:nth-child(even) td { background:#fafbfe; }
pre { background:#0f1c3f; color:#dfe7f5; padding:14px 16px; border-radius:6px;
      overflow-x:auto; font-size:12.5px; line-height:1.6; }
code { font-family:"Cascadia Code",Consolas,monospace; }
p code, li code, td code { background:#eef2f9; color:#27408b; padding:1px 5px;
      border-radius:4px; font-size:13px; }
ul { margin:.4em 0 .8em; padding-left:1.6em; }
li { margin:.25em 0; }
details { margin:.6em 0; border:1px solid var(--line); border-radius:6px; padding:8px 12px; }
summary { cursor:pointer; color:var(--accent); font-weight:600; }
svg { max-width:100%; height:auto; display:block; margin:12px auto; }
.toc { background:#f7f9fd; border:1px solid var(--line); border-radius:8px;
       padding:16px 28px; margin:0 0 28px; }
.toc-title { text-align:center; font-weight:700; font-size:17px; margin-bottom:8px;
       letter-spacing:.5em; text-indent:.5em; }
.toc ul { list-style:none; padding:0; margin:0; }
.toc li { margin:3px 0; }
.toc-3 { padding-left:1.6em; }
.toc a { color:var(--ink); text-decoration:none; }
.toc a:hover { color:var(--accent); }
.meta { text-align:center; color:var(--muted); font-size:13px; margin-bottom:28px; }

/* 公文风格变体：标题三号小标宋居中，正文小四仿宋/宋体，首行缩进两字符 */
body.gongwen { font-size:12pt; }
body.gongwen .page { max-width:800px; padding:64px 72px; }
body.gongwen h1 { font-family:"STZhongsong","华文中宋","SimSun",serif;
       font-size:16pt; /* 三号 */ font-weight:700; text-align:center; }
body.gongwen h2 { font-family:"SimHei","黑体",sans-serif; font-size:14pt;
       border-left:none; padding-left:0; }
body.gongwen h3 { font-family:"KaiTi","楷体",serif; font-size:12pt; font-weight:700; }
body.gongwen p { font-family:"FangSong","仿宋","SimSun",serif; font-size:12pt; /* 小四 */
       text-indent:2em; line-height:1.9; }
body.gongwen p.num { text-indent:0; }
body.gongwen blockquote p, body.gongwen td p, body.gongwen th p { text-indent:0; }
body.gongwen table { font-size:10.5pt; }
body.gongwen .toc p { text-indent:0; }

@media print {
  .toolbar { display:none; }
  body { background:#fff; }
  .page { box-shadow:none; border:none; margin:0; max-width:none; padding:10mm 6mm; }
  h2 { break-after:avoid; }
  table, pre, blockquote, svg { break-inside:avoid; }
}
"""

# Word 打开 HTML 所需的命名空间声明
DOC_DOWNLOAD_JS = """
function downloadDoc() {
  var page = document.querySelector('.page');
  var css = document.querySelector('#page-style').textContent;
  var head = '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
    + 'xmlns:w="urn:schemas-microsoft-com:office:word" '
    + 'xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8">'
    + '<title>' + (document.title || 'scheme') + '</title>'
    + '<style>' + css + ' body{font-family:SimSun,serif;} .toolbar{display:none;}'
    + ' .page{border:none;box-shadow:none;margin:0;padding:0;max-width:none;}</style>'
    + '</head><body>';
  var src = head + page.outerHTML + '</body></html>';
  var blob = new Blob(['\\ufeff', src], {type: 'application/msword'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = (document.title || 'scheme') + '.doc';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(url); }, 2000);
}
"""


def export_html(markdown: str, title: str, out_path: str,
                extra_head: str = "", gongwen: bool = False) -> str:
    """Markdown → 独立 HTML 文件（含目录、DOC 下载、打印/PDF 按钮）

    gongwen=True 时启用中文公文排版（标题小标宋居中、正文仿宋小四、首行缩进两字符）。
    """
    toc = build_toc(markdown)
    body = markdown_to_html_body(markdown)
    # 去掉正文里的 h1（页面已用 title 呈现）
    body = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", body, count=1, flags=re.S)
    body_cls = ' class="gongwen"' if gongwen else ""
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(title)}</title>
<style id="page-style">{PAGE_CSS}</style>
{extra_head}
</head>
<body{body_cls}>
<div class="toolbar">
  <span class="title">{html_mod.escape(title)}</span>
  <button onclick="downloadDoc()">下载 DOC</button>
  <button onclick="window.print()">打印 / 存 PDF</button>
</div>
<div class="page">
{toc}
{body}
</div>
<script>{DOC_DOWNLOAD_JS}</script>
</body>
</html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    logger.info("HTML 导出: %s (%d 字符)", out_path, len(page))
    return out_path


if __name__ == "__main__":
    from .intent import KeywordIntentParser, build_clarifications
    from .selection import SelectionEngine
    from .link_budget import build_link_budgets, validate_scheme
    p = KeywordIntentParser()
    e = SelectionEngine()
    c = "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年"
    it = p.parse(c)
    pl = e.run(it)
    bs = build_link_budgets(pl, it)
    v = validate_scheme(pl, bs, it)
    md = generate_scheme(it, pl, bs, v, user_input=c)
    print(md[:2500])
    print(f"\n… 全文 {len(md)} 字符")
