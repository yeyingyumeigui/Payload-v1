"""文生载荷智能体 端到端演示 (demo.py)

覆盖全部载荷类型与流程分支:
  CASE 1  GEO Ka 高通量通信（DTP 柔性体制，多波束）    → 完整方案 + HTML
  CASE 2  GEO Ku 单波束透明转发                        → 反射面天线选型
  CASE 3  LEO L 波段手机直连（缺口检测）               → 定制缺口 L2 告警
  CASE 4  SSO 光学遥感 0.5m                            → 非通信分支
  CASE 5  MEO 导航 / LEO 科学                          → 非通信分支
  CASE 6  需求不完整（"帮我看看遥感载荷"）             → 澄清闸口 need_clarify
  CASE 7  confirm_mode 人工确认流                      → awaiting_confirmation → confirm_design

运行:  python demo.py
产物:  output/*.md + output/*.html
"""

from __future__ import annotations

import datetime
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from payload_agent import PayloadDesignChain, export_html  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

CASES = [
    {
        "name": "GEO Ka 高通量通信（DTP 柔性）",
        "input": "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
                 "48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年",
        "export": True,
    },
    {
        "name": "GEO Ku 单波束透明转发",
        "input": "设计GEO Ku频段透明转发通信载荷，单波束，EIRP>=52dBW，G/T>=5，寿命15年",
        "export": False,
    },
    {
        "name": "LEO L 波段手机直连（缺口检测）",
        "input": "设计LEO L波段手机直连星座通信载荷，12米伞天线，EIRP>=48dBW，寿命7年，要批产",
        "export": False,
    },
    {
        "name": "SSO 光学遥感 0.5m",
        "input": "设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m，幅宽12km",
        "export": True,
    },
    {
        "name": "MEO 导航增强",
        "input": "设计MEO中轨导航载荷，B1C信号体制，寿命12年",
        "export": False,
    },
    {
        "name": "LEO 科学探测",
        "input": "设计LEO低轨科学实验载荷，磁强计，寿命5年",
        "export": False,
    },
    {
        "name": "需求不完整 → 澄清闸口",
        "input": "帮我看看遥感载荷",
        "export": False,
    },
]


def banner(idx: int, name: str):
    print("\n" + "=" * 78)
    print(f"CASE {idx}: {name}")
    print("=" * 78)


def show_events(chain: PayloadDesignChain, sid: str):
    for e in chain.get_events(sid):
        mark = {"info": " ", "warn": "⚠", "error": "✖"}.get(e["level"], " ")
        print(f"  {mark}[{e['seq']:02d}] {e['stage']:<11} {e['message']}")


def main():
    logging.basicConfig(level=logging.WARNING)
    os.makedirs(OUT_DIR, exist_ok=True)
    chain = PayloadDesignChain()
    stamp = datetime.date.today().isoformat()

    print("文生载荷智能体 端到端演示")
    print(f"Skill 数: {len(chain.list_skills())} | 输出目录: {OUT_DIR}")

    passed = 0
    for i, case in enumerate(CASES, 1):
        banner(i, case["name"])
        print(f"需求: {case['input']}")
        r = chain.invoke({"user_input": case["input"]})
        print(f"状态: {r.status}")
        show_events(chain, r.session_id)

        if r.status == "need_clarify":
            print("澄清问题:")
            for c in r.clarifications:
                print(f"  - [{c['level']}] {c['question']}")
            passed += 1
            continue

        if r.status in ("completed", "infeasible"):
            v = r.validation
            print(f"校验: {'通过' if v and v.valid else '未通过'}"
                  f"（错误 {len(v.errors) if v else '-'}，"
                  f"告警 {len(v.warnings) if v else '-'}）")
            if v:
                for e in v.errors:
                    print(f"  ✖ {e}")
                for w in v.warnings[:4]:
                    print(f"  ⚠ {w}")
            print(f"方案文档: {len(r.design_scheme)} 字符"
                  f"（链路回环 {r.link_retry} 次，选型迭代 "
                  f"{r.plan.iteration if r.plan else '-'} 次）")
            passed += 1

            safe = "".join(ch for ch in case["name"]
                           if ch not in r'\/:*?"<>|').replace(" ", "_")
            md_path = os.path.join(OUT_DIR, f"方案_{i}_{safe}_{stamp}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(r.design_scheme)
            print(f"已保存: {md_path}")
            if case.get("export"):
                html_path = md_path.replace(".md", ".html")
                export_html(r.design_scheme, f"CASE{i} {case['name']}", html_path)
                print(f"已导出: {html_path}")

    # CASE 8: 人工确认流
    banner(len(CASES) + 1, "confirm_mode 人工确认流")
    r = chain.invoke({
        "user_input": "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
                      "48个波束相控阵，DTP柔性体制，容量50Gbps",
        "confirm_mode": True})
    print(f"状态: {r.status}")
    if r.status == "awaiting_confirmation":
        p = r.plan
        print(f"待确认选型: 天线={p.antenna['model'] if p.antenna else '-'} | "
              f"平台={p.platform['model'] if p.platform else '-'} | "
              f"运载={p.launcher['name'] if p.launcher else '-'}")
        r2 = chain.confirm_design(r.session_id)
        print(f"确认后状态: {r2.status} | 文档 {len(r2.design_scheme)} 字符")
        show_events(chain, r2.session_id)
        passed += 1

    print("\n" + "=" * 78)
    print(f"演示完成: {passed}/{len(CASES) + 1} 个用例走通")


if __name__ == "__main__":
    main()
