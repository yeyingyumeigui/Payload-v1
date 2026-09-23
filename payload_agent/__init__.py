"""文生有效载荷智能体 (Payload Design Agent)

零依赖可运行的载荷方案设计智能体骨架。

主链路:
  需求 → SK-INTENT 意图解析 → SK-CLARIFY 澄清闸口 → SK-RETRIEVE 知识检索
       → SK-ANTSEL/SK-EQUIP 载荷选型 → SK-PLAT/SK-LAUNCH 平台运载
       → SK-BUDGET 链路预算 → SK-VALID 三重校验（双回环）
       → SK-DOC 方案生成 → SK-WORD 导出

用法:
  from payload_agent import PayloadDesignChain
  chain = PayloadDesignChain()
  r = chain.invoke({"user_input": "设计GEO Ka频段高通量通信载荷…"})
  print(r.status, r.design_scheme[:200])
"""

from .intent import (
    IntentResult, IntentChain, KeywordIntentParser, LLMIntentParser,
    extract_metrics, parse_frequency_bands, build_clarifications,
)
from .selection import (
    SelectionEngine, SelectionPlan, SelectionRequirement,
    AntennaSelector, EquipmentSelector, NonCommSelector,
    PlatformSelector, LauncherSelector,
)
from .link_budget import (
    LinkBudget, ValidationResult, build_link_budgets, validate_scheme,
    link_budget_markdown, select_modcod, free_space_loss_db,
    rain_attenuation_db, orbit_distance_km, antenna_gain_db, array_gain_db,
    capacity_gbps, MODCOD_LADDER, MARGIN_THRESHOLD_DB,
)
from .knowledge import retrieve_context
from .skill_registry import (
    SkillRegistry, SkillDef, AnomalyLevel, AnomalyRule, get_skill_registry,
)
from .chain import (
    PayloadDesignChain, DesignResult, ChainInterrupted, SessionState,
)
from .docgen import generate_scheme, export_html, markdown_to_html_body, build_toc
from .catalog import get_catalog_summary

__all__ = [
    # 意图
    "IntentResult", "IntentChain", "KeywordIntentParser", "LLMIntentParser",
    "extract_metrics", "parse_frequency_bands", "build_clarifications",
    # 选型
    "SelectionEngine", "SelectionPlan", "SelectionRequirement",
    "AntennaSelector", "EquipmentSelector", "NonCommSelector",
    "PlatformSelector", "LauncherSelector",
    # 链路/校验
    "LinkBudget", "ValidationResult", "build_link_budgets",
    "validate_scheme", "link_budget_markdown", "select_modcod",
    "free_space_loss_db", "rain_attenuation_db", "orbit_distance_km",
    "antenna_gain_db", "array_gain_db", "capacity_gbps",
    "MODCOD_LADDER", "MARGIN_THRESHOLD_DB",
    # 知识
    "retrieve_context",
    # Skill
    "SkillRegistry", "SkillDef", "AnomalyLevel", "AnomalyRule",
    "get_skill_registry",
    # 主链
    "PayloadDesignChain", "DesignResult", "ChainInterrupted", "SessionState",
    # 文档
    "generate_scheme", "export_html", "markdown_to_html_body", "build_toc",
    # 目录
    "get_catalog_summary",
]

__version__ = "0.2.0"
