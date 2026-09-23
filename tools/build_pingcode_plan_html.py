# -*- coding: utf-8 -*-
"""读取 build_pingcode_plan 的数据源，渲染可视化计划文档 HTML。

产出：output/pingcode/载荷设计流程6个月敏捷计划.html
  - 执行摘要 KPI 卡片
  - 六阶段流程 + 5 道质量门禁
  - 敏捷机制（DoR/DoD/WIP/仪式/技术债/自动化校核/度量）
  - 14 迭代甘特图
  - WBS 树状表（Epic→Feature→Story→Task）
  - 迭代日历 / 质量门禁 / 风险登记册
  - PingCode 导入操作指引（字段映射）
  - DOC 下载 + 打印/PDF（中文公文格式）
"""
from __future__ import annotations
import os, sys, html, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pingcode_plan as P  # 复用数据源（导入即执行生成 CSV，幂等）

OUT = P.OUT
esc = lambda s: html.escape(str(s), quote=True)

# ---- 六阶段流程与门禁映射 ----
STAGES = [
    ("需求分析", "E1", "任务场景→需求澄清闸口→顶层指标预算→频率规划", "G0 需求基线"),
    ("总体方案与体制选择", "E2", "转发体制(透明/再生/DTP)→天线体制五要素→波束覆盖→货架选型", "G1 总体方案 SRR"),
    ("分系统详细设计", "E3", "天线/转发器/激光/智能处理四分系统并行 + EMC-热控-供电协同", "—"),
    ("指标校核与闭环", "E4", "链路预算→余量≥3dB→双回环迭代→三重校验→异常分级", "G2 指标校核 PDR"),
    ("平台/运载适配与集成验证", "E5", "平台承载/姿态耦合→运载约束→ICD→试验大纲与仿真", "G3 集成验证 CDR"),
    ("评审交付与知识沉淀", "E6", "方案文档→交付归档→知识图谱/货架库/规则库更新→复盘", "G4 交付验收 FRR"),
]

# ---- 甘特：Epic 跨迭代条 ----
# 计算每个 Epic 的起止迭代索引（基于其下 story/task 的迭代）
sp_names = [s["名称"] for s in P.sprints]
sp_index = {n: i for i, n in enumerate(sp_names)}

def epic_span(ep):
    its = set()
    its.add(ep["sprint"])
    for f in ep["features"]:
        its.add(f["sprint"])
        for st in f["stories"]:
            its.add(st["s"])
            for tk in st["tasks"]:
                its.add(tk[4 - 2])  # tk = (标题,工时,迭代,角色,标签) → 迭代在 idx2
    idxs = [sp_index[i] for i in its if i in sp_index]
    return (min(idxs), max(idxs)) if idxs else (0, 0)

# 修正：task 元组第 3 位是迭代
def epic_span2(ep):
    its = {ep["sprint"]}
    for f in ep["features"]:
        its.add(f["sprint"])
        for st in f["stories"]:
            its.add(st["s"])
            for tk in st["tasks"]:
                its.add(tk[2])
    idxs = [sp_index[i] for i in its if i in sp_index]
    return (min(idxs), max(idxs)) if idxs else (0, 0)

EPIC_COLORS = {
    "E0": "#8b5cf6", "E1": "#2563eb", "E2": "#0891b2",
    "E3": "#059669", "E4": "#d97706", "E5": "#dc2626", "E6": "#7c3aed",
}

s = P.stats
N_SP = len(P.sprints)

# ---------------- 组装 HTML ----------------
parts = []
parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>载荷设计流程 6 个月敏捷计划 · PingCode 导入包</title>
<style>
:root {{
  --ink:#1a1a1a; --sub:#555; --line:#d8d8d8; --bg:#f5f6f8; --card:#fff;
  --accent:#1f4e79; --accent2:#2e75b6; --ok:#059669; --warn:#d97706; --risk:#dc2626;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:"Songti SC","SimSun","宋体",serif; line-height:1.75; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 22px 80px; }}
.toolbar {{ position:sticky; top:0; z-index:50; background:rgba(245,246,248,.96);
  backdrop-filter:blur(6px); border-bottom:1px solid var(--line);
  padding:10px 0; margin-bottom:22px; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
.btn {{ border:1px solid var(--accent); background:var(--accent); color:#fff;
  padding:7px 16px; border-radius:6px; cursor:pointer; font-size:14px;
  font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}
.btn.ghost {{ background:#fff; color:var(--accent); }}
.btn:hover {{ opacity:.9; }}
h1 {{ font-family:"STZhongsong","SimSun",serif; font-size:26px; text-align:center;
  font-weight:700; margin:6px 0 4px; letter-spacing:1px; }}
.subtitle {{ text-align:center; color:var(--sub); font-size:14px; margin-bottom:4px;
  font-family:"Microsoft YaHei",sans-serif; }}
.meta {{ text-align:center; color:#888; font-size:12.5px; margin-bottom:24px;
  font-family:"Microsoft YaHei",sans-serif; }}
h2 {{ font-family:"STZhongsong","SimSun",serif; font-size:19px; color:var(--accent);
  border-left:5px solid var(--accent2); padding-left:12px; margin:34px 0 14px; }}
h3 {{ font-size:16px; color:#243; margin:20px 0 8px; font-family:"Microsoft YaHei",sans-serif; }}
p {{ text-indent:2em; margin:8px 0; font-size:15px; }}
p.noindent {{ text-indent:0; }}
.lead {{ background:#eef4fb; border:1px solid #cfe0f2; border-radius:8px;
  padding:14px 18px; font-size:15.5px; text-indent:0; }}
.lead b {{ color:var(--accent); }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px; margin:16px 0; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 12px; text-align:center; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
.kpi .n {{ font-size:26px; font-weight:700; color:var(--accent);
  font-family:"Microsoft YaHei",sans-serif; }}
.kpi .l {{ font-size:12.5px; color:var(--sub); margin-top:2px;
  font-family:"Microsoft YaHei",sans-serif; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:13.5px;
  background:var(--card); font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}
th,td {{ border:1px solid var(--line); padding:7px 9px; text-align:left; vertical-align:top; }}
th {{ background:#e8eef6; color:#1f3a5f; font-weight:600; white-space:nowrap; }}
tr:nth-child(even) td {{ background:#fafbfc; }}
.tag {{ display:inline-block; background:#eef2f7; border:1px solid #d5dde8;
  border-radius:4px; padding:1px 7px; font-size:12px; margin:1px 2px; color:#3a4a5f; }}
.gate {{ background:#fff7ed; border-left:4px solid var(--warn); }}
.pri-紧急 {{ color:var(--risk); font-weight:600; }}
.pri-高 {{ color:var(--warn); }}
.pri-中 {{ color:#2563eb; }}
/* 流程图 */
.flow {{ display:flex; flex-wrap:wrap; gap:0; align-items:stretch; margin:16px 0; }}
.fstage {{ flex:1 1 150px; min-width:150px; background:var(--card); border:1px solid var(--line);
  border-radius:8px; padding:10px; position:relative; margin-right:26px; }}
.fstage:last-child {{ margin-right:0; }}
.fstage:not(:last-child)::after {{ content:"▶"; position:absolute; right:-20px; top:50%;
  transform:translateY(-50%); color:var(--accent2); font-size:14px; }}
.fstage .ft {{ font-weight:700; color:var(--accent); font-size:14px;
  font-family:"Microsoft YaHei",sans-serif; }}
.fstage .fe {{ font-size:11.5px; color:#888; margin:2px 0; }}
.fstage .fd {{ font-size:12px; color:var(--sub); line-height:1.5; }}
.fstage .fg {{ margin-top:6px; font-size:11.5px; background:#fff7ed; border:1px solid #fcd9a8;
  color:#92400e; border-radius:4px; padding:2px 6px; display:inline-block; }}
/* 甘特 */
.gantt {{ overflow-x:auto; background:var(--card); border:1px solid var(--line);
  border-radius:8px; padding:10px; }}
.gantt table {{ font-size:12px; }}
.gantt th {{ text-align:center; padding:4px 2px; font-size:11px; }}
.gantt td {{ padding:3px 2px; text-align:center; }}
.gantt td.lab {{ text-align:left; white-space:nowrap; font-weight:600; padding-left:6px; }}
.cell {{ height:16px; border-radius:3px; }}
/* WBS */
.wbs {{ font-size:13px; }}
.wbs .ep {{ background:#e8eef6; font-weight:700; }}
.wbs .ft {{ background:#f2f6fb; }}
.wbs .st {{ }}
.wbs .tk {{ color:#555; font-size:12.5px; }}
details {{ margin:4px 0; }}
summary {{ cursor:pointer; font-weight:600; color:var(--accent); padding:3px 0;
  font-family:"Microsoft YaHei",sans-serif; }}
.note {{ background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:12px 16px;
  font-size:13.5px; text-indent:0; }}
.warn {{ background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:12px 16px;
  font-size:13.5px; text-indent:0; }}
ol,ul {{ margin:8px 0 8px 1.4em; }}
li {{ font-size:14px; margin:4px 0; }}
code {{ background:#eef2f7; padding:1px 5px; border-radius:3px; font-size:12.5px;
  font-family:Consolas,monospace; }}
.foot {{ margin-top:40px; padding-top:14px; border-top:1px solid var(--line);
  color:#999; font-size:12px; text-align:center; font-family:"Microsoft YaHei",sans-serif; }}
@media print {{
  body {{ background:#fff; }}
  .toolbar {{ display:none; }}
  .wrap {{ max-width:100%; padding:0; }}
  h2 {{ page-break-after:avoid; }}
  table,.gantt,.flow {{ page-break-inside:avoid; }}
  .kpi {{ box-shadow:none; }}
}}
</style>
</head>
<body>
<div class="wrap">
<div class="toolbar">
  <button class="btn" onclick="downloadDOC()">⬇ 下载 DOC</button>
  <button class="btn ghost" onclick="window.print()">🖨 打印 / 导出 PDF</button>
  <span style="color:#888;font-size:12.5px;font-family:'Microsoft YaHei',sans-serif;">
    共 {s['工作项总数']} 个工作项 · {s['故事点合计']} 故事点 · {s['预估工时合计']}</span>
</div>

<h1>通信有效载荷设计流程 · 六个月敏捷研制计划</h1>
<div class="subtitle">PingCode 工作项导入包 &nbsp;|&nbsp; 敏捷提效 · 质量门禁双保障</div>
<div class="meta">编制日期 2026-09-20 &nbsp;·&nbsp; 项目周期 {esc(s['项目周期'])} &nbsp;·&nbsp; {esc(s['迭代数'])}</div>

<div class="lead">
<b>一句话概要：</b>以「六阶段载荷工程设计流程」为主轴，用 <b>12 个固定两周迭代</b>把需求分析→总体方案→分系统设计→指标校核→平台适配→评审交付串成可度量、可回溯的敏捷流水线；
通过 <b>DoR/DoD + WIP 限制 + 五道质量门禁(G0–G4) + 自动化三重校验 + 每迭代≥10% 技术债偿还</b>，实现「效率提升不以质量妥协为代价」。
本计划已展平为 <b>{s['工作项总数']} 个 PingCode 工作项</b>（{s['史诗']} 史诗 / {s['特性']} 特性 / {s['用户故事']} 故事 / {s['任务']} 任务），随附 8 个 CSV 可直接导入。
</div>

<h2>一、执行摘要</h2>
<div class="kpis">
  <div class="kpi"><div class="n">{s['工作项总数']}</div><div class="l">工作项总数</div></div>
  <div class="kpi"><div class="n">{s['史诗']}</div><div class="l">史诗 Epic</div></div>
  <div class="kpi"><div class="n">{s['特性']}</div><div class="l">特性 Feature</div></div>
  <div class="kpi"><div class="n">{s['用户故事']}</div><div class="l">用户故事 Story</div></div>
  <div class="kpi"><div class="n">{s['任务']}</div><div class="l">任务 Task</div></div>
  <div class="kpi"><div class="n">{s['故事点合计']}</div><div class="l">故事点合计</div></div>
  <div class="kpi"><div class="n">{int(s['预估工时合计'].split(' ')[0])}</div><div class="l">预估工时 (h)</div></div>
  <div class="kpi"><div class="n">{s['质量门禁']}</div><div class="l">质量门禁 G0–G4</div></div>
  <div class="kpi"><div class="n">{s['风险项']}</div><div class="l">风险登记项</div></div>
</div>
<p>项目自 2026-09-21 启动，含 1 个启动周（Sprint 0 敏捷机制落地）、12 个两周迭代（Sprint 1–12 覆盖六阶段研制）与 1 个发布收尾周，至 2027-03-21 交付，历时约 6 个月。
全部工作项按「史诗→特性→用户故事→任务」四层 WBS 组织，故事点采用斐波那契估算（1/2/3/5/8/13），任务粒度控制在 0.5–2 人日，预估总工时 {s['预估工时合计']}。</p>

<h2>二、六阶段设计流程与质量门禁</h2>
<p class="noindent">载荷工程设计遵循六阶段串行推进、门禁阻断的瀑布骨架，每个阶段内部以敏捷迭代方式并行展开。门禁未通过禁止进入下一阶段（PingCode 状态流转强制审批）。</p>
<div class="flow">
""")

for name, eid, desc, gate in STAGES:
    parts.append(f"""  <div class="fstage">
    <div class="ft">{esc(name)}</div>
    <div class="fe">{esc(eid)}</div>
    <div class="fd">{esc(desc)}</div>
    <div class="fg">{esc(gate)}</div>
  </div>""")
parts.append("</div>")

# 门禁表
parts.append("""
<h3>质量门禁定义（G0–G4）</h3>
<table>
<tr><th>门禁</th><th>名称</th><th>所在迭代</th><th>通过准则</th><th>阻断规则</th></tr>""")
for g in P.GATES:
    parts.append(f"""<tr class="gate"><td><b>{esc(g['门禁编号'])}</b></td><td>{esc(g['门禁名称'])}</td>
<td>{esc(g['所在迭代'])}</td><td>{esc(g['通过准则'])}</td><td>{esc(g['阻断规则'])}</td></tr>""")
parts.append("</table>")

# ---------------- 敏捷机制 ----------------
parts.append("""
<h2>三、敏捷机制：效率与质量的双引擎</h2>
<h3>3.1 迭代节奏与四类仪式</h3>
<table>
<tr><th>仪式</th><th>频率/时间盒</th><th>产出物</th><th>效率作用</th></tr>
<tr><td>Sprint 计划会</td><td>每迭代首日 2h</td><td>迭代目标、容量核算、任务认领</td><td>聚焦高优先级，限制在制品</td></tr>
<tr><td>每日站会</td><td>每日 15min</td><td>任务板更新、阻塞项、当日承诺</td><td>快速暴露阻塞，减少等待</td></tr>
<tr><td>迭代评审会</td><td>每迭代末日 1.5h</td><td>交付物演示、指标核验、门禁判定</td><td>增量可见，及时反馈</td></tr>
<tr><td>迭代回顾会</td><td>每迭代末日 1h</td><td>改进项清单（责任人+期限）</td><td>持续改进，沉淀最佳实践</td></tr>
<tr><td>Backlog 梳理会</td><td>每迭代中期 2h</td><td>故事细化、DoR 检查、估算</td><td>保证下迭代就绪，减少返工</td></tr>
</table>
<p class="note"><b>仪式执行率要求：</b>连续 2 个迭代四类仪式执行率 100%，作为敏捷成熟度基线度量项。</p>

<h3>3.2 就绪定义 DoR 与完成定义 DoD</h3>
<table>
<tr><th>类别</th><th>条目</th><th>PingCode 落地方式</th></tr>
<tr><td rowspan="3"><b>DoR<br>就绪定义</b></td><td>① 验收标准明确、可测试</td><td>创建校验：验收标准为必填</td></tr>
<tr><td>② 依赖项（上游输入/接口/资源）就绪</td><td>依赖关系字段 + 阻塞标记</td></tr>
<tr><td>③ 可估算、粒度 0.5–2 人日</td><td>故事点/预估工时必填</td></tr>
<tr><td rowspan="4"><b>DoD<br>完成定义</b></td><td>① 设计/实现完成</td><td>状态流转至「已完成」前置</td></tr>
<tr><td>② 三重校验（语法/语义/合规）通过</td><td>DoD 检查项，自动校核</td></tr>
<tr><td>③ 文档归档、版本受控</td><td>关联交付物附件</td></tr>
<tr><td>④ 评审/门禁通过</td><td>阶段关闭强制审批</td></tr>
</table>

<h3>3.3 WIP 限制与技术债</h3>
<ul>
<li><b>WIP 限制：</b>人均并行在制任务 ≤ 2，看板每列在制品 ≤ 5，避免多任务切换损耗，缩短周期时间。</li>
<li><b>技术债偿还：</b>每迭代预留 ≥ 10% 容量用于偿还技术债（工具固化、模型修正、文档补全），防止债务累积拖垮后期效率。</li>
<li><b>关键计算双人交叉复核：</b>链路预算、指标分配等关键计算实行双人复核并签署，杜绝单点错误。</li>
</ul>

<h3>3.4 自动化校核替代人工检查</h3>
<p>将既有工程知识固化为自动校核规则，作为 DoD 必过项，人工检查项减少 ≥ 50%，校核可复现、可审计：</p>
<table>
<tr><th>校验层</th><th>内容</th><th>规则来源</th></tr>
<tr><td>语法校验</td><td>文档要素完整性（章节/表格/单位）</td><td>文档模板规则</td></tr>
<tr><td>语义校验</td><td>指标一致性（EIRP/G-T 满足需求、质量功耗在平台内、工作模式匹配）</td><td>25 条工程约束</td></tr>
<tr><td>合规校验</td><td>余量≥3dB、频段-产品匹配无错配、货架优先</td><td>25 条工程约束 + 合规库</td></tr>
<tr><td>异常分级</td><td>L1 自动降级(8) / L2 告警放行(16) / L3 中止转人工(6)</td><td>30 条异常规则，覆盖 11 环节</td></tr>
</table>

<h3>3.5 双回环迭代优化</h3>
<table>
<tr><th>回环</th><th>触发条件</th><th>调整手段（优先级）</th><th>迭代上限</th></tr>
<tr><td>内环（平台可行性）</td><td>质量/功耗超平台承载</td><td>换天线/换分系统方案 → 升级平台</td><td>≤ 3 次</td></tr>
<tr><td>外环（链路余量）</td><td>余量 M &lt; 3dB</td><td>降阶调制 → 增 EIRP → 减带宽 → 放宽可用性 → 换天线重选</td><td>≤ 2 次</td></tr>
</table>
<p class="warn"><b>回环耗尽处置：</b>内/外环迭代达上限仍未收敛，转 L3 人工决策（中止并生成人工决策任务），确保问题不被掩盖。</p>

<h3>3.6 度量指标（敏捷 + 质量）</h3>
<table>
<tr><th>维度</th><th>指标</th><th>目标</th></tr>
<tr><td rowspan="3">效率</td><td>迭代速率（故事点/迭代）</td><td>稳定在容量 ±15%</td></tr>
<tr><td>周期时间（故事创建→完成）</td><td>逐迭代下降</td></tr>
<tr><td>仪式执行率</td><td>连续 2 迭代 100%</td></tr>
<tr><td rowspan="4">质量</td><td>质量门禁一次通过率</td><td>≥ 90%</td></tr>
<tr><td>缺陷密度 / 返工率</td><td>逐迭代下降</td></tr>
<tr><td>链路余量达标率（M≥3dB）</td><td>100%</td></tr>
<tr><td>三重校验阻断项清零率</td><td>阶段关闭前 100%</td></tr>
</table>
""")

# ---------------- 甘特 ----------------
parts.append('<h2>四、迭代甘特图</h2><div class="gantt"><table><tr><th style="text-align:left">史诗 \\ 迭代</th>')
for i, sp in enumerate(P.sprints):
    short = sp["名称"].replace("Sprint ", "S").replace(" · 启动准备", "0").replace("发布与收尾", "发布")
    parts.append(f'<th>{esc(short)}</th>')
parts.append("</tr>")
for ep in P.PLAN:
    a, b = epic_span2(ep)
    color = EPIC_COLORS.get(ep["id"], "#888")
    parts.append(f'<tr><td class="lab">{esc(ep["id"])} {esc(ep["name"].split(" ",1)[-1][:10])}</td>')
    for i in range(N_SP):
        if a <= i <= b:
            parts.append(f'<td><div class="cell" style="background:{color}"></div></td>')
        else:
            parts.append('<td></td>')
    parts.append("</tr>")
# 门禁行
parts.append('<tr><td class="lab" style="color:#92400e">质量门禁</td>')
gate_sp = {g["所在迭代"]: g["门禁编号"] for g in P.GATES}
for i, sp in enumerate(P.sprints):
    if sp["名称"] in gate_sp:
        parts.append(f'<td><div class="cell" style="background:#f59e0b" title="{esc(gate_sp[sp["名称"]])}"></div></td>')
    else:
        parts.append('<td></td>')
parts.append("</tr></table></div>")
parts.append('<p class="noindent" style="font-size:12.5px;color:#888">色条=史诗跨迭代区间；橙色=质量门禁所在迭代。S0=启动周，S1–S12=两周迭代，发布=收尾周。</p>')

# ---------------- 迭代日历 ----------------
parts.append('<h2>五、迭代日历与目标</h2><table><tr><th>迭代</th><th>开始</th><th>结束</th><th>容量(点)</th><th>迭代目标</th></tr>')
for sp in P.sprints:
    parts.append(f"""<tr><td><b>{esc(sp['名称'])}</b></td><td>{esc(sp['开始日期'])}</td><td>{esc(sp['结束日期'])}</td>
<td style="text-align:center">{sp.get('容量故事点','')}</td><td>{esc(sp['迭代目标'])}</td></tr>""")
parts.append("</table>")

# ---------------- WBS ----------------
parts.append('<h2>六、WBS 工作分解结构</h2>')
parts.append('<p class="noindent">点击展开各史诗查看「特性→故事→任务」四层分解。故事含故事点与验收标准，任务含预估工时、负责角色与迭代。</p>')
parts.append('<div class="wbs">')
for ep in P.PLAN:
    ep_pts = sum(st["p"] for f in ep["features"] for st in f["stories"])
    ep_hours = sum(tk[1] for f in ep["features"] for st in f["stories"] for tk in st["tasks"])
    color = EPIC_COLORS.get(ep["id"], "#888")
    parts.append(f"""<details {'open' if ep['id']=='E0' else ''}>
<summary style="border-left:5px solid {color};padding-left:10px">
{esc(ep['id'])} · {esc(ep['name'])}
<span style="color:#888;font-weight:400;font-size:12px">（{ep_pts} 点 / {ep_hours}h / {esc(ep['sprint'])} 起 / 优先级 <span class="pri-{esc(ep['pri'])}">{esc(ep['pri'])}</span>）</span></summary>
<p style="text-indent:0;font-size:13px;color:#555;margin:6px 0 6px 14px">{esc(ep['desc'])}</p>
<table><tr><th>层级</th><th>标题</th><th>迭代</th><th>点/工时</th><th>负责</th><th>验收标准 / 标签</th></tr>""")
    for f in ep["features"]:
        parts.append(f"""<tr class="ft"><td>特性</td><td><b>{esc(f['id'])} {esc(f['name'])}</b></td>
<td>{esc(f['sprint'])}</td><td>—</td><td>—</td><td><span class="pri-{esc(f['pri'])}">{esc(f['pri'])}</span></td></tr>""")
        for si, st in enumerate(f["stories"], 1):
            sid = f"{f['id']}-S{si}"
            parts.append(f"""<tr class="st"><td>故事</td><td>{esc(sid)} {esc(st['t'])}</td>
<td>{esc(st['s'])}</td><td style="text-align:center">{st['p']}</td><td>—</td>
<td style="font-size:12px">{esc(st['ac'])}</td></tr>""")
            for ti, tk in enumerate(st["tasks"], 1):
                t_title, hours, t_sprint, role, tag = tk
                parts.append(f"""<tr class="tk"><td>任务</td><td style="padding-left:22px">└ {esc(t_title)}</td>
<td>{esc(t_sprint)}</td><td style="text-align:center">{hours}h</td><td>{esc(role)}</td>
<td><span class="tag">{esc(tag)}</span></td></tr>""")
    parts.append("</table></details>")
parts.append("</div>")

# ---------------- 风险登记册 ----------------
parts.append('<h2>七、风险登记册</h2><table><tr><th>编号</th><th>风险描述</th><th>概率</th><th>影响</th><th>缓解措施</th><th>责任人</th><th>关注迭代</th><th>触发阈值</th></tr>')
for r in P.RISK_ROWS:
    pc = "pri-紧急" if r["概率"]=="高" else ("pri-高" if r["概率"]=="中" else "")
    ic = "pri-紧急" if r["影响"]=="高" else ("pri-高" if r["影响"]=="中" else "")
    parts.append(f"""<tr><td><b>{esc(r['风险编号'])}</b></td><td>{esc(r['风险描述'])}</td>
<td class="{pc}">{esc(r['概率'])}</td><td class="{ic}">{esc(r['影响'])}</td>
<td style="font-size:12.5px">{esc(r['缓解措施'])}</td><td>{esc(r['责任人'])}</td>
<td>{esc(r['关注迭代'])}</td><td style="font-size:12px">{esc(r['触发阈值'])}</td></tr>""")
parts.append("</table>")

# ---------------- 导入指引 ----------------
parts.append(f"""
<h2>八、PingCode 导入操作指引</h2>
<p class="noindent">本计划随附 8 个 CSV 文件（UTF-8 带 BOM，Excel 与 PingCode 导入向导均可正确识别中文），位于 <code>output/pingcode/</code>。PingCode 无开放 API 连接器，按以下步骤手动导入：</p>
<h3>8.1 文件清单</h3>
<table>
<tr><th>文件</th><th>内容</th><th>行数</th><th>用途</th></tr>
<tr><td><code>00_迭代.csv</code></td><td>迭代名称/起止/目标/容量</td><td>{N_SP}</td><td>先建迭代日历</td></tr>
<tr><td><code>01_史诗.csv</code></td><td>7 个 Epic</td><td>{len(P.EPICS)}</td><td>第一层</td></tr>
<tr><td><code>02_特性.csv</code></td><td>20 个 Feature</td><td>{len(P.FEATURES)}</td><td>第二层（父级=Epic）</td></tr>
<tr><td><code>03_用户故事.csv</code></td><td>44 个 Story（含故事点/验收标准）</td><td>{len(P.STORIES)}</td><td>第三层（父级=Feature）</td></tr>
<tr><td><code>04_任务.csv</code></td><td>203 个 Task（含工时/角色/标签）</td><td>{len(P.TASKS)}</td><td>第四层（父级=Story）</td></tr>
<tr><td><code>05_全量工作项_一次导入.csv</code></td><td>四层合一</td><td>{s['工作项总数']}</td><td><b>推荐：单次导入</b></td></tr>
<tr><td><code>06_质量门禁.csv</code></td><td>G0–G4 门禁准则</td><td>{len(P.GATES)}</td><td>配置审批流参考</td></tr>
<tr><td><code>07_风险登记册.csv</code></td><td>12 项风险</td><td>{len(P.RISK_ROWS)}</td><td>风险库导入参考</td></tr>
</table>

<h3>8.2 导入步骤</h3>
<ol>
<li><b>建项目空间：</b>PingCode → 敏捷研发 → 新建 Scrum 项目「通信有效载荷研制」。</li>
<li><b>建迭代：</b>项目设置 → 迭代 → 按 <code>00_迭代.csv</code> 录入 14 个迭代（S0 启动周 + S1–S12 两周 + 发布周）的起止日期与目标。</li>
<li><b>导入工作项（推荐一次性）：</b>Backlog → 导入 → 选择 <code>05_全量工作项_一次导入.csv</code>。
  <ul>
  <li>在字段映射向导中，将 CSV 列映射到 PingCode 字段：<br>
  <code>工作项类型→类型</code>、<code>标题→标题</code>、<code>描述→描述</code>、<code>父级工作项→父级(按标题匹配)</code>、
  <code>优先级→优先级</code>、<code>迭代→迭代(按名称匹配)</code>、<code>故事点→故事点</code>、
  <code>预估工时→预估工时</code>、<code>负责人→负责人(按角色映射成员)</code>、<code>开始/截止日期→对应日期</code>、
  <code>标签→标签</code>、<code>验收标准→验收标准/自定义字段</code>。</li>
  <li>若向导不支持「父级按标题匹配」，改为分层导入：先 <code>01_史诗</code> → 再 <code>02_特性</code>（父级填史诗标题）→ <code>03_用户故事</code> → <code>04_任务</code>，逐层建立父子关系。</li>
  </ul>
</li>
<li><b>配置质量门禁：</b>按 <code>06_质量门禁.csv</code>，在工作流中为 G0–G4 对应阶段设置「关闭需审批」，审批人=技术负责人，通过准则写入阶段说明。</li>
<li><b>配置 DoR/DoD 校验：</b>将 DoR 三条件设为创建必填校验，DoD 四条件设为状态流转前置检查项。</li>
<li><b>配置 WIP 限制：</b>看板每列在制品上限 5；通过报表监控人均在制 ≤ 2。</li>
<li><b>导入风险库：</b>按 <code>07_风险登记册.csv</code> 录入 12 项风险（概率×影响、缓解措施、责任人、触发阈值）。</li>
<li><b>校验：</b>导入后核对工作项总数 = {s['工作项总数']}、故事点合计 = {s['故事点合计']}、各迭代任务分布与「五、迭代日历」一致。</li>
</ol>
<p class="note"><b>提示：</b>负责人字段当前为角色名（如「链路工程师」「天线设计师」），导入后请在 PingCode 中按实际成员批量替换；标签字段可用于看板筛选与度量分组。</p>

<h2>九、交付物与验收</h2>
<ul>
<li><b>阶段交付物：</b>需求基线 → 总体方案(SRR) → 分系统设计包 → 指标校核报告(PDR) → 集成验证大纲(CDR) → 方案文档与交付归档(FRR)。</li>
<li><b>知识资产：</b>通信有效载荷知识图谱、货架产品库、25 条工程约束库、30 条异常规则库随项目迭代更新。</li>
<li><b>验收标准：</b>五道门禁全部通过、链路余量 100% 达标、三重校验阻断项清零、度量指标达成、复盘改进项入库。</li>
<li><b>复用目标：</b>设计工具（选型引擎/链路预算/三重校验/文档自动生成）固化，下一型号复用率 ≥ 60%。</li>
</ul>

<div class="foot">通信有效载荷设计流程 · 六个月敏捷研制计划 &nbsp;|&nbsp; 生成于 2026-09-20 &nbsp;|&nbsp; 数据源：build_pingcode_plan.py（{s['工作项总数']} 工作项）</div>
</div>

<script>
function downloadDOC() {{
  var html = document.documentElement.outerHTML;
  var blob = new Blob(['\\ufeff', html], {{type:'application/msword'}});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = '载荷设计流程6个月敏捷计划.doc';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}}
</script>
</body></html>""")

html_path = os.path.join(OUT, "载荷设计流程6个月敏捷计划.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write("".join(parts))

# 自检
checks = []
content = "".join(parts)
checks.append(("HTML 非空", len(content) > 5000))
checks.append(("含 DOCTYPE", content.startswith("<!DOCTYPE")))
checks.append(("含全部 7 Epic", all(e["name"] in content for e in P.PLAN)))
checks.append(("含 5 门禁", all(g["门禁编号"] in content for g in P.GATES)))
checks.append(("含 12 风险", all(r["风险编号"] in content for r in P.RISK_ROWS)))
checks.append(("含导入指引", "PingCode 导入操作指引" in content))
checks.append(("含甘特", "迭代甘特图" in content))
checks.append(("含 DOC 下载", "downloadDOC" in content))
checks.append(("标签闭合 html", content.rstrip().endswith("</html>")))
n_tasks_in_wbs = content.count("└")
checks.append((f"WBS 任务行数={n_tasks_in_wbs} (应≈{len(P.TASKS)})", n_tasks_in_wbs >= len(P.TASKS) * 0.9))

report = ["HTML 计划文档自检：", f"路径: {html_path}", f"大小: {len(content)} 字符", ""]
allok = True
for name, ok in checks:
    report.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok: allok = False
report.append("")
report.append("结论: " + ("全部通过" if allok else "存在失败项"))
with open(os.path.join(OUT, "_html_verify.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("\n".join(report))
