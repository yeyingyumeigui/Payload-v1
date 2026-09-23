# -*- coding: utf-8 -*-
"""生成 Markdown 版计划文档（与 HTML/CSV 同源数据）。"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pingcode_plan as P

OUT = P.OUT
s = P.stats
N_SP = len(P.sprints)

STAGES = [
    ("需求分析", "E1", "任务场景→需求澄清闸口→顶层指标预算→频率规划", "G0 需求基线"),
    ("总体方案与体制选择", "E2", "转发体制(透明/再生/DTP)→天线体制五要素→波束覆盖→货架选型", "G1 总体方案 SRR"),
    ("分系统详细设计", "E3", "天线/转发器/激光/智能处理四分系统并行 + EMC-热控-供电协同", "—"),
    ("指标校核与闭环", "E4", "链路预算→余量≥3dB→双回环迭代→三重校验→异常分级", "G2 指标校核 PDR"),
    ("平台/运载适配与集成验证", "E5", "平台承载/姿态耦合→运载约束→ICD→试验大纲与仿真", "G3 集成验证 CDR"),
    ("评审交付与知识沉淀", "E6", "方案文档→交付归档→知识图谱/货架库/规则库更新→复盘", "G4 交付验收 FRR"),
]

L = []
L.append("# 通信有效载荷设计流程 · 六个月敏捷研制计划\n")
L.append("> PingCode 工作项导入包 | 敏捷提效 · 质量门禁双保障\n")
L.append(f"> 编制日期 2026-09-20 · 项目周期 {s['项目周期']} · {s['迭代数']}\n")

L.append("\n## 一句话概要\n")
L.append("以「六阶段载荷工程设计流程」为主轴，用 **12 个固定两周迭代**把需求分析→总体方案→分系统设计→指标校核→平台适配→评审交付串成可度量、可回溯的敏捷流水线；"
         "通过 **DoR/DoD + WIP 限制 + 五道质量门禁(G0–G4) + 自动化三重校验 + 每迭代≥10% 技术债偿还**，实现「效率提升不以质量妥协为代价」。"
         f"本计划已展平为 **{s['工作项总数']} 个 PingCode 工作项**（{s['史诗']} 史诗 / {s['特性']} 特性 / {s['用户故事']} 故事 / {s['任务']} 任务），随附 8 个 CSV 可直接导入。\n")

L.append("\n## 一、执行摘要\n")
L.append(f"| 指标 | 数值 |\n|---|---|")
L.append(f"| 项目周期 | {s['项目周期']} |")
L.append(f"| 迭代结构 | {s['迭代数']} |")
L.append(f"| 工作项总数 | {s['工作项总数']}（{s['史诗']} 史诗 / {s['特性']} 特性 / {s['用户故事']} 故事 / {s['任务']} 任务） |")
L.append(f"| 故事点合计 | {s['故事点合计']} |")
L.append(f"| 预估工时 | {s['预估工时合计']} |")
L.append(f"| 质量门禁 | {s['质量门禁']} 道（G0–G4） |")
L.append(f"| 风险登记项 | {s['风险项']} 项 |")
L.append("")

L.append("\n## 二、六阶段设计流程与质量门禁\n")
L.append("| 阶段 | 史诗 | 主要活动 | 门禁 |")
L.append("|---|---|---|---|")
for name, eid, desc, gate in STAGES:
    L.append(f"| {name} | {eid} | {desc} | {gate} |")
L.append("")
L.append("\n### 质量门禁定义（G0–G4）\n")
L.append("| 门禁 | 名称 | 所在迭代 | 通过准则 | 阻断规则 |")
L.append("|---|---|---|---|---|")
for g in P.GATES:
    L.append(f"| {g['门禁编号']} | {g['门禁名称']} | {g['所在迭代']} | {g['通过准则']} | {g['阻断规则']} |")
L.append("")

L.append("\n## 三、敏捷机制：效率与质量的双引擎\n")
L.append("### 3.1 迭代节奏与四类仪式\n")
L.append("| 仪式 | 频率/时间盒 | 产出物 | 效率作用 |")
L.append("|---|---|---|---|")
L.append("| Sprint 计划会 | 每迭代首日 2h | 迭代目标、容量核算、任务认领 | 聚焦高优先级，限制在制品 |")
L.append("| 每日站会 | 每日 15min | 任务板更新、阻塞项、当日承诺 | 快速暴露阻塞，减少等待 |")
L.append("| 迭代评审会 | 每迭代末日 1.5h | 交付物演示、指标核验、门禁判定 | 增量可见，及时反馈 |")
L.append("| 迭代回顾会 | 每迭代末日 1h | 改进项清单（责任人+期限） | 持续改进，沉淀最佳实践 |")
L.append("| Backlog 梳理会 | 每迭代中期 2h | 故事细化、DoR 检查、估算 | 保证下迭代就绪，减少返工 |")
L.append("\n> 仪式执行率要求：连续 2 个迭代四类仪式执行率 100%。\n")
L.append("### 3.2 DoR / DoD\n")
L.append("- **DoR 就绪定义**：① 验收标准明确可测试；② 依赖项就绪；③ 可估算、粒度 0.5–2 人日。")
L.append("- **DoD 完成定义**：① 设计/实现完成；② 三重校验（语法/语义/合规）通过；③ 文档归档版本受控；④ 评审/门禁通过。")
L.append("### 3.3 WIP 限制与技术债\n")
L.append("- WIP：人均并行 ≤ 2，看板每列在制 ≤ 5。")
L.append("- 技术债：每迭代预留 ≥ 10% 容量偿还。")
L.append("- 关键计算（链路预算/指标分配）双人交叉复核并签署。")
L.append("### 3.4 自动化三重校验\n")
L.append("| 校验层 | 内容 | 规则来源 |")
L.append("|---|---|---|")
L.append("| 语法校验 | 文档要素完整性（章节/表格/单位） | 文档模板规则 |")
L.append("| 语义校验 | 指标一致性（EIRP/G-T/质量功耗/模式匹配） | 25 条工程约束 |")
L.append("| 合规校验 | 余量≥3dB、频段-产品匹配、货架优先 | 25 条工程约束 + 合规库 |")
L.append("| 异常分级 | L1 自动降级(8)/L2 告警放行(16)/L3 中止转人工(6) | 30 条异常规则，覆盖 11 环节 |")
L.append("### 3.5 双回环迭代优化\n")
L.append("| 回环 | 触发条件 | 调整手段（优先级） | 上限 |")
L.append("|---|---|---|---|")
L.append("| 内环（平台可行性） | 质量/功耗超承载 | 换天线/换方案 → 升级平台 | ≤ 3 次 |")
L.append("| 外环（链路余量） | 余量 M < 3dB | 降阶调制 → 增 EIRP → 减带宽 → 放宽可用性 → 换天线重选 | ≤ 2 次 |")
L.append("\n> 回环耗尽转 L3 人工决策，确保问题不被掩盖。\n")

L.append("\n## 四、迭代日历与目标\n")
L.append("| 迭代 | 开始 | 结束 | 容量(点) | 迭代目标 |")
L.append("|---|---|---|---|---|")
for sp in P.sprints:
    L.append(f"| {sp['名称']} | {sp['开始日期']} | {sp['结束日期']} | {sp.get('容量故事点','')} | {sp['迭代目标']} |")
L.append("")

L.append("\n## 五、WBS 工作分解结构\n")
for ep in P.PLAN:
    ep_pts = sum(st["p"] for f in ep["features"] for st in f["stories"])
    ep_hours = sum(tk[1] for f in ep["features"] for st in f["stories"] for tk in st["tasks"])
    L.append(f"\n### {ep['id']} · {ep['name']}\n")
    L.append(f"*{ep['desc']}*\n")
    L.append(f"> {ep_pts} 故事点 / {ep_hours}h / 起始 {ep['sprint']} / 优先级 {ep['pri']}\n")
    for f in ep["features"]:
        L.append(f"\n**{f['id']} {f['name']}** （{f['sprint']}，优先级 {f['pri']}）\n")
        for si, st in enumerate(f["stories"], 1):
            sid = f"{f['id']}-S{si}"
            L.append(f"\n- `{sid}` **{st['t']}** — {st['p']} 点 / {st['s']}")
            L.append(f"  - 验收标准：{st['ac']}")
            for ti, tk in enumerate(st["tasks"], 1):
                t_title, hours, t_sprint, role, tag = tk
                L.append(f"  - [ ] {t_title}（{hours}h · {role} · {t_sprint} · #{tag}）")
L.append("")

L.append("\n## 六、风险登记册\n")
L.append("| 编号 | 风险描述 | 概率 | 影响 | 缓解措施 | 责任人 | 关注迭代 | 触发阈值 |")
L.append("|---|---|---|---|---|---|---|---|")
for r in P.RISK_ROWS:
    L.append(f"| {r['风险编号']} | {r['风险描述']} | {r['概率']} | {r['影响']} | {r['缓解措施']} | {r['责任人']} | {r['关注迭代']} | {r['触发阈值']} |")
L.append("")

L.append("\n## 七、PingCode 导入操作指引\n")
L.append("随附 8 个 CSV（UTF-8 带 BOM），位于 `output/pingcode/`。PingCode 无开放 API 连接器，按以下步骤手动导入：\n")
L.append("### 7.1 文件清单\n")
L.append("| 文件 | 内容 | 行数 | 用途 |")
L.append("|---|---|---|---|")
L.append(f"| `00_迭代.csv` | 迭代名称/起止/目标/容量 | {N_SP} | 先建迭代日历 |")
L.append(f"| `01_史诗.csv` | 7 个 Epic | {len(P.EPICS)} | 第一层 |")
L.append(f"| `02_特性.csv` | 20 个 Feature | {len(P.FEATURES)} | 第二层（父级=Epic） |")
L.append(f"| `03_用户故事.csv` | 44 个 Story | {len(P.STORIES)} | 第三层（父级=Feature） |")
L.append(f"| `04_任务.csv` | 203 个 Task | {len(P.TASKS)} | 第四层（父级=Story） |")
L.append(f"| `05_全量工作项_一次导入.csv` | 四层合一 | {s['工作项总数']} | **推荐：单次导入** |")
L.append(f"| `06_质量门禁.csv` | G0–G4 门禁准则 | {len(P.GATES)} | 配置审批流参考 |")
L.append(f"| `07_风险登记册.csv` | 12 项风险 | {len(P.RISK_ROWS)} | 风险库导入参考 |")
L.append("\n### 7.2 导入步骤\n")
L.append("1. **建项目空间**：PingCode → 敏捷研发 → 新建 Scrum 项目「通信有效载荷研制」。")
L.append("2. **建迭代**：项目设置 → 迭代 → 按 `00_迭代.csv` 录入 14 个迭代的起止日期与目标。")
L.append("3. **导入工作项（推荐一次性）**：Backlog → 导入 → 选择 `05_全量工作项_一次导入.csv`，在字段映射向导中映射：")
L.append("   - `工作项类型→类型`、`标题→标题`、`描述→描述`、`父级工作项→父级(按标题匹配)`、`优先级→优先级`、`迭代→迭代(按名称匹配)`、`故事点→故事点`、`预估工时→预估工时`、`负责人→负责人(按角色映射成员)`、`开始/截止日期→对应日期`、`标签→标签`、`验收标准→验收标准/自定义字段`。")
L.append("   - 若向导不支持父级按标题匹配，改为分层导入：`01_史诗`→`02_特性`→`03_用户故事`→`04_任务`，逐层建立父子关系。")
L.append("4. **配置质量门禁**：按 `06_质量门禁.csv`，为 G0–G4 对应阶段设置「关闭需审批」，审批人=技术负责人。")
L.append("5. **配置 DoR/DoD 校验**：DoR 三条件设为创建必填校验，DoD 四条件设为状态流转前置检查项。")
L.append("6. **配置 WIP 限制**：看板每列在制品上限 5；报表监控人均在制 ≤ 2。")
L.append("7. **导入风险库**：按 `07_风险登记册.csv` 录入 12 项风险。")
L.append(f"8. **校验**：核对工作项总数 = {s['工作项总数']}、故事点合计 = {s['故事点合计']}、各迭代任务分布与迭代日历一致。")
L.append("\n> 负责人字段当前为角色名（如「链路工程师」「天线设计师」），导入后请在 PingCode 中按实际成员批量替换。\n")

L.append("\n## 八、交付物与验收\n")
L.append("- **阶段交付物**：需求基线 → 总体方案(SRR) → 分系统设计包 → 指标校核报告(PDR) → 集成验证大纲(CDR) → 方案文档与交付归档(FRR)。")
L.append("- **知识资产**：通信有效载荷知识图谱、货架产品库、25 条工程约束库、30 条异常规则库随项目迭代更新。")
L.append("- **验收标准**：五道门禁全部通过、链路余量 100% 达标、三重校验阻断项清零、度量指标达成、复盘改进项入库。")
L.append("- **复用目标**：设计工具固化，下一型号复用率 ≥ 60%。")
L.append("\n---\n*生成于 2026-09-20 · 数据源：build_pingcode_plan.py*\n")

md_path = os.path.join(OUT, "载荷设计流程6个月敏捷计划.md")
with open(md_path, "w", encoding="utf-8") as f:
    f.write("\n".join(L))

content = "\n".join(L)
checks = [
    ("MD 非空", len(content) > 3000),
    ("含 7 Epic", all(e["name"] in content for e in P.PLAN)),
    ("含 5 门禁", all(g["门禁编号"] in content for g in P.GATES)),
    ("含 12 风险", all(r["风险编号"] in content for r in P.RISK_ROWS)),
    ("含导入指引", "PingCode 导入操作指引" in content),
    ("任务勾选框数≈203", content.count("- [ ]") >= len(P.TASKS) * 0.9),
]
rep = [f"MD 路径: {md_path}", f"大小: {len(content)} 字符", ""]
ok = True
for n, o in checks:
    rep.append(f"  [{'PASS' if o else 'FAIL'}] {n}")
    ok = ok and o
rep.append("结论: " + ("全部通过" if ok else "存在失败项"))
with open(os.path.join(OUT, "_md_verify.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(rep))
print("\n".join(rep))
