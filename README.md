# 文生载荷（Payload）—— 通信卫星有效载荷智能设计与论证平台

> 一句自然语言任务需求 → 数秒内输出**可审计**的卫星有效载荷方案：框图、链路预算、单机选型清单、平台/运载匹配、A/B/C/D 评级，以及可直接汇报的 Word 论证报告。

本仓库包含两个相互衔接的部分：

| 目录 | 内容 | 版本 |
|---|---|---|
| `PayloadDesign/` | **载荷方案设计器**（Windows 桌面 GUI，13 页签，主交付物） | v5.3 |
| `payload_agent/` + `demo.py` + `test_agent.py` | **文生载荷智能体骨架**（Skill 链路 + 异常分级 + 三级选型闭环，102 用例） | v1 |

---

## 一、载荷方案设计器（PayloadDesign/）

### 1.1 是什么

单机离线的 Windows 桌面工具（pywebview + Edge WebView2，纯 Python 零科学计算依赖）。用户输入一组任务需求（业务 / 轨道 / 覆盖区 / 频段 / 工作模式），软件在数秒内完成**需求解析 → 指标反推 → 天线与单机选型 → 平台/运载匹配 → 链路预算校核 → 方案评价 → 报告导出**的全流程闭环设计。

### 1.2 核心能力（13 页签）

1. **需求输入与一键建议**：仅凭轨道 + 覆盖区即可给出第一性原理正确的完整方案（`suggest_closed_loop`：建议 → 验证 → 按 25 条工程约束自动修正，≤3 轮收敛）
2. **方案总览与评价**：E1~E10 十项准则（6 硬 4 软）→ A/B/C/D 评级 + 可行性结论；地面 EIRP 覆盖热力图
3. **载荷框图与信息流**：业务/数据/控制/供能四类信息流 × 星地/星间/星内三段 × L1~L8 功能级三维层次化渲染
4. **天线与波束**：五维天线选型；次级方向图 grid/cut 双视图、扫描态切换、栅瓣解析+数值双路核查
5. **链路预算**：雨衰（ITU-R P.618/P.838-3/P.837 气候区）、大气、指向、极化、实现损耗同源合成；MODCOD 由 C/N 反推
6. **单机选型**：86 条货架单机库（参考银河航天 / SatNow / Tesat 真实产品），三线编号可追溯
7. **平台与运载匹配** · 8. **频率规划** · 9. **方案对比** · 10. **预设管理** · 11. **接口与协议**（MOSA 风格 ICD 自动生成）
12. **轨道覆盖仿真**（STK 等效）：Kepler + J2 摄动，24h 星下点轨迹、时刻快照覆盖圈、可见窗表、合理性判定，导出 STK `.e` 星历
13. **稳健性分析**：星蚀功率核算、位保 ΔV/推进剂与寿命、蒙特卡洛链路灵敏度（直方图 + 龙卷风图）、雨致交叉极化 XPD、BOM+MTBF 可靠性三 R 口径汇算与冗余整改建议、邻星干扰 C/I（ITU-R S.465-6 / S.580）

### 1.3 内置计算引擎

| 引擎 | 等效工具 | 职责 |
|---|---|---|
| `pattern_engine.py` | GRASP | 相控阵（阵元因子 × 可分离阵因子）/ 反射面（Hankel 变换）次级方向图，导出 `.grd` |
| `coverage_engine.py` | SATSOFT | 波束指向反解 → 逐格点 EIRP 投影 → marching squares 等值线 → 足迹度量 |
| `orbit_engine.py` | STK | 轨道传播、可见窗、星座（Walker）、星蚀历元、位保 ΔV |
| `analysis_engine.py` | — | 蒙特卡洛灵敏度、邻星 C/I、可靠性三 R 口径、冗余整改建议、三工具结果回读 |
| `propagation.py` | — | P.618-12 雨衰与雨致 XPD 全项 |
| `design_engine.py` | — | 五步闭环 + 双回环主链路、25 条工程约束校核、LRU 计算缓存 |
| `report_gen.py` | — | 14 章项目论证报告（SVG 光栅化为 PNG 以兼容 Word/WPS） |

### 1.4 质量保障

- **独立第一性原理交叉验证** `PayloadDesign/tools/_verify_physics.py`：不复用引擎函数，从教科书公式独立重写 P0~P14 共 15 类物理量，10 个场景全部通过
- **回归矩阵**（改动引擎后须全绿）：冻结自检 8/8 场景 grade=A · 物理验证 0 失败 · 冒烟 72 项 · DOM 端到端 88 项 · 报告章节 43 项 · 货架 86 条 · 智能体 102 用例
- 验证过程中曾抓出真实物理缺陷（相控阵接收链 T_sys 漏算 T/R 组件噪声，G/T 乐观约 6 dB）并已修复

### 1.5 运行方式

```bash
# 网页版（实时计算，需 Python 3.13 + pywebview）
cd PayloadDesign/tools
python design_app.py --web      # 浏览器打开 http://127.0.0.1:8642

# 桌面版（离线单文件 exe）
PayloadDesign/tools/dist/载荷方案设计器.exe
```

> 可执行文件与 PyInstaller 中间产物未纳入版本库（见 `.gitignore`），需要 exe 请用 `PayloadDesign/tools/build_exe.bat` 本地重建，或从 Release 获取。
> 打包要求：`pyinstaller design_app.spec`，Windows 自带 .NET Framework 4.8（`PYTHONNET_RUNTIME=netfx`）+ WebView2 Runtime。

想先快速看一眼界面，直接用浏览器打开 `PayloadDesign/output/载荷方案设计器_预览版.html`（内置 8 个预置场景 + 默认配置的预计算结果，页面逻辑与 exe 完全一致）。

### 1.6 文档

- `PayloadDesign/output/载荷方案设计器_软件说明.md` / `.html` —— 软件概述、架构、验证体系、工程口径速查、FAQ
- `PayloadDesign/output/巴基斯坦GEO高通量宽带卫星_载荷方案论证报告_预览.html` —— 报告样例

---

## 二、文生载荷智能体骨架（payload_agent/）

Skill 化的载荷设计主链路，供自然语言驱动：

```
SK-INTENT（意图解析）→ SK-CLARIFY（缺项阻断闸）→ SK-RETRIEVE（知识图谱检索）
→ SK-ANTSEL / SK-EQUIP（天线与单机选型）→ SK-PLAT / SK-LAUNCH（平台与运载）
→ SK-BUDGET（链路预算）→ SK-VALID（质量闸）→ SK-DOC / SK-WORD（文档输出）
```

- **双回环**：内环 = 平台可行性换天线（≤3 迭代）；外环 = 链路余量否决天线重选型（≤2 次）
- **异常分级**：L1 自动降级 / L2 告警放行 / L3 中止转人工（30 条规则）
- **铁律**：禁止擅自假设（缺项即中断）；频段硬约束不回退；MODCOD 由 C/N 反推不预设体制
- 运行：`python demo.py`（8 个用例）· 测试：`python -m unittest test_agent`（102 用例）
- 业务流程梳理：`output/文生载荷业务流程梳理_2026-09-20.html`

---

## 三、目录结构

```
.
├── PayloadDesign/
│   ├── tools/          # 设计器源码（引擎 + 前端 + 打包配置 + 验证脚本）
│   │   ├── design_app.py        # 应用主体（后端 Api + HTTP 路由 + 内嵌前端）
│   │   ├── design_engine.py     # 设计主链路
│   │   ├── design_data.py       # 货架/平台/运载/MODCOD/覆盖区知识库
│   │   ├── pattern_engine.py    # 方向图（GRASP 等效）
│   │   ├── coverage_engine.py   # EIRP 覆盖（SATSOFT 等效）
│   │   ├── orbit_engine.py      # 轨道仿真（STK 等效）
│   │   ├── analysis_engine.py   # 稳健性分析（MC/干扰/可靠性/回读）
│   │   ├── propagation.py       # 电波传播（雨衰/XPD）
│   │   ├── infoflow_engine.py   # 信息流与 25 条工程约束校核
│   │   ├── report_gen.py        # 14 章 Word 论证报告
│   │   ├── protocol_gen.py      # MOSA 风格接口协议 ICD
│   │   ├── grasp_bridge.py      # GRASP 波束桥
│   │   ├── design_app.spec      # PyInstaller 打包配置
│   │   └── _verify_physics.py   # 独立第一性原理交叉验证
│   └── output/         # 知识图谱 JSON、预览版 HTML、软件说明、报告样例
├── payload_agent/      # 智能体骨架（intent/chain/selection/link_budget/docgen…）
├── tools/              # 智能体配套构建与验证脚本
├── output/             # 智能体演示产物与业务流程文档
├── demo.py             # 智能体演示入口（8 用例）
├── test_agent.py       # 智能体测试（102 用例）
└── build_docs.py       # 业务流程文档构建
```

## 四、技术栈

Python 3.13 · pywebview 6.x + Edge WebView2 · 纯标准库计算（无 numpy/scipy/matplotlib，保证冻结体积与离线可用）· PyInstaller 单文件打包 · 原生 SVG / Canvas 前端可视化

---

*本仓库为科研与工程论证用途的方案设计工具，计算结果用于方案论证阶段的快速设计与比选，不构成最终研制依据。*
