"""知识检索 (SK-RETRIEVE)

零依赖确定性检索：按意图从货架目录、选型判据、行业标准、体制模板中
摘取相关条目，装配为压缩上下文，供方案生成引用。

与向量检索的差异：本模块是"规则命中 + 结构化摘要"，结果可复现、可审计，
适合作为骨架的知识底座；接入真实向量库时只需替换 retrieve() 内部实现，
保持 (intent) -> context:str 的契约不变。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .intent import IntentResult
from .catalog import (
    ANTENNA_SELECTION_CRITERIA, NONCOMM_SELECTION_CRITERIA,
    ARCH_TEMPLATES, INDUSTRY_STANDARDS, FREQUENCY_BANDS, ORBIT_TYPES,
    get_catalog_summary,
)

logger = logging.getLogger(__name__)

# 上下文预算（字符），超出按段落截断
CONTEXT_BUDGET = 6000


def _payload_label(intent: IntentResult) -> str:
    return {"communication": "通信", "remote_sensing": "遥感",
            "navigation": "导航", "science": "科学实验"}.get(
        intent.payload_type, "通用")


def retrieve_context(intent: IntentResult, top_k: int = 5) -> str:
    """按意图装配知识上下文（确定性、可复现）"""
    blocks: List[str] = []

    # 1) 任务概述
    blocks.append("## 任务要素\n" + intent.summary())

    # 2) 轨道特性
    orb = ORBIT_TYPES.get(intent.orbit_type)
    if orb:
        alt = orb["alt_km"]
        blocks.append(
            f"## 目标轨道 {intent.orbit_type}\n"
            f"- 高度 {alt[0]}–{alt[1]} km，周期 {orb['period_min'][0]}–{orb['period_min'][1]} min\n"
            f"- {orb['desc']}")

    # 3) 频段特性
    if intent.frequency_bands:
        lines = ["## 工作频段"]
        for b in intent.frequency_bands:
            fb = FREQUENCY_BANDS.get(b)
            if fb:
                lines.append(
                    f"- {b}：上行 {fb['up']:g} GHz / 下行 {fb['down']:g} GHz，"
                    f"典型雨衰 {fb['rain']:g} dB，用途 {fb['use']}")
            else:
                lines.append(f"- {b}")
        blocks.append("\n".join(lines))

    # 4) 选型判据
    if intent.payload_type == "communication":
        lines = ["## 天线五要素选型判据",
                 "| 要素 | 权重 | 计算式 | 设计动作 |",
                 "|------|------|--------|---------|"]
        for c in ANTENNA_SELECTION_CRITERIA:
            lines.append(f"| {c['dim']} | {c['weight']} | {c['formula']} | {c['action']} |")
        blocks.append("\n".join(lines))
    else:
        crit = NONCOMM_SELECTION_CRITERIA.get(intent.payload_type, [])
        if crit:
            lines = [f"## {_payload_label(intent)}载荷选型判据",
                     "| 判据 | 权重 | 设计动作 |", "|------|------|---------|"]
            for c in crit:
                lines.append(f"| {c['dim']} | {c['weight']} | {c['action']} |")
            blocks.append("\n".join(lines))

    # 5) 转发体制（仅通信）
    fm = intent.forwarding_mode
    if fm and fm in ARCH_TEMPLATES:
        a = ARCH_TEMPLATES[fm]
        blocks.append(
            f"## 转发体制：{a['name']}\n{a['desc']}\n"
            f"- 链路：{' → '.join(a['chain'])}\n"
            f"- 优势：{'；'.join(a['pros'])}\n"
            f"- 局限：{'；'.join(a['cons'])}\n"
            f"- 适用：{a['适用']}")

    # 6) 相关行业标准（按频段/体制/链路关键词命中）
    std_keys = _match_standards(intent)
    if std_keys:
        lines = ["## 适用标准与规范"]
        for k in std_keys:
            lines.append(f"- **{k}**：{INDUSTRY_STANDARDS[k]}")
        blocks.append("\n".join(lines))

    # 7) 货架产品库规模
    summ = get_catalog_summary()
    blocks.append(
        "## 货架产品库规模\n"
        f"- 天线 {summ['天线']['count']} 型，单机 {summ['单机']['count']} 型，"
        f"平台 {summ['平台']['count']} 型，运载 {summ['运载']['count']} 型\n"
        f"- 遥感载荷 {summ['遥感载荷']['count']}，导航载荷 {summ['导航载荷']['count']}，"
        f"科学载荷 {summ['科学载荷']['count']}\n"
        f"- 货架水平排序：飞行继承货架 > 飞行继承 > 货架(在研转货架) > 定制")

    context = "\n\n".join(blocks)
    if len(context) > CONTEXT_BUDGET:
        context = context[:CONTEXT_BUDGET] + "\n…（上下文按预算截断）"
    logger.info("知识检索完成：%d 字符，命中标准 %d 项", len(context), len(std_keys))
    return context


def _match_standards(intent: IntentResult) -> List[str]:
    """按意图命中相关标准条目键"""
    hit: List[str] = []
    bands = set(intent.frequency_bands)
    techs = " ".join(intent.key_technologies)

    # 链路预算始终适用（通信/遥感数传）
    if intent.payload_type in ("communication", "remote_sensing"):
        hit.append("链路预算")
    if bands & {"Ka", "Ku", "Q", "V"}:
        hit.append("ITU")
        hit.append("天线")
    if "激光" in bands or "激光通信" in intent.key_technologies:
        hit.append("激光")
    if intent.payload_type == "communication":
        hit.append("CCSDS")
    # 通用工程规范
    hit += ["热控", "电磁兼容", "可靠性", "抗辐射"]
    # 去重保序
    seen, out = set(), []
    for k in hit:
        if k in INDUSTRY_STANDARDS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def fallback_summary() -> str:
    """检索为空时的全量目录摘要兜底"""
    import json
    return "## 货架产品库摘要\n```json\n" + \
        json.dumps(get_catalog_summary(), ensure_ascii=False, indent=2) + "\n```"


if __name__ == "__main__":
    from .intent import KeywordIntentParser
    p = KeywordIntentParser()
    for c in [
        "设计GEO Ka频段高通量通信载荷，相控阵，DTP柔性体制，容量50Gbps",
        "设计SSO太阳同步轨道遥感载荷，分辨率优于0.5m",
    ]:
        it = p.parse(c)
        print("=" * 70)
        print(retrieve_context(it))
        print()
