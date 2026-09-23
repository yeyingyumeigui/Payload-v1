"""意图解析 (SK-INTENT)

从用户自然语言需求中提取结构化设计要素。
零依赖关键词后端为主，可选 LLM 后端增强；LLM 不可用时自动降级。

关键陷阱规避:
  数值频段关键词 (12/14/20/30 等) 必须带 GHz 上下文才判为频段，
  避免 "12m 伞天线 / 300kg / 30 人" 被误判为频段。
  L 波段用特征频点 (1525/1559/1626/1660 MHz) 识别。
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 关键词表（可按需扩充）
# ============================================================

PAYLOAD_KEYWORDS: Dict[str, List[str]] = {
    "communication": ["通信", "转发", "信标", "5g", "6g", "基站", "宽带", "高通量",
                      "hts", "vsat", "直播", "数传", "手机直连", "物联网", "中继"],
    "remote_sensing": ["遥感", "成像", "相机", "sar", "光谱", "多光谱", "高光谱",
                       "分辨率", "对地观测", "测绘"],
    "navigation": ["导航", "定位", "授时", "gnss", "北斗", "gps", "增强"],
    "science": ["科学实验", "探测", "天文", "观测", "重力场", "掩星", "载荷试验"],
}

ORBIT_KEYWORDS: Dict[str, List[str]] = {
    "GEO": ["geo", "同步轨道", "地球静止", "静止轨道", "对地静止", "geostationary"],
    "LEO": ["leo", "低轨", "低地球", "星座", "巨星座", "leo星座"],
    "MEO": ["meo", "中轨", "中地球"],
    "SSO": ["sso", "太阳同步", "sun-synchronous"],
    "HEO": ["heo", "大椭圆", "莫尼亚", "闪电轨道"],
}

# 文本频段（字母型）
FREQ_KEYWORDS: Dict[str, List[str]] = {
    "L": ["l波段", "l频段", "l-band", "l band"],
    "S": ["s波段", "s频段", "s-band"],
    "C": ["c波段", "c频段", "c-band"],
    "X": ["x波段", "x频段", "x-band"],
    "Ku": ["ku波段", "ku频段", "ku-band", "ku band"],
    "Ka": ["ka波段", "ka频段", "ka-band", "ka band"],
    "Q": ["q波段", "q频段", "q/v"],
    "V": ["v波段", "v频段"],
    "激光": ["激光", "光通信", "星间链路", "isl", "optical", "lct"],
}

# 数值频段（必须带 GHz 上下文）→ 归一化到字母频段
FREQ_NUMERIC_GHZ: List[tuple] = [
    (1.2, 1.7, "L"), (1.9, 2.4, "S"), (3.4, 4.2, "C"), (4.4, 5.0, "C"),
    (5.85, 7.075, "C"), (7.0, 8.4, "X"), (10.7, 12.75, "Ku"), (12.75, 14.8, "Ku"),
    (17.3, 21.2, "Ka"), (27.0, 31.0, "Ka"), (37.5, 42.5, "Q"), (42.5, 52.0, "V"),
]

# L 波段特征频点 (MHz)
FREQ_L_MARKERS_MHZ = [1525, 1559, 1626, 1660, 1610, 2483]

TECH_KEYWORDS: Dict[str, List[str]] = {
    "相控阵天线": ["相控阵", "aesa", "pesa", "平面阵", "阵列天线", "t/r", "dbf",
                 "波束赋形", "波束成形"],
    "反射面天线": ["反射面", "抛物面", "固定口径", "卡塞格林", "格雷高里"],
    "伞天线": ["伞天线", "伞状", "可展开", "展开式", "网状天线", "astromesh", "桁架"],
    "反射阵天线": ["反射阵", "反射式阵", "raa"],
    "激光通信": ["激光", "光通信", "星间链路", "atp", "dpsk"],
    "数字透明处理": ["dtp", "数字透明", "柔性载荷", "软件定义", "sdr", "在轨重构",
                   "可重构", "灵活载荷", "信道化"],
    "星上处理": ["星上处理", "再生转发", "处理转发", "星上路由", "星上交换", "星上组网"],
    "多波束": ["多波束", "点波束", "波束跳变", "波束跳速", "频率复用"],
    "5G核心网": ["5g核心网", "核心网", "upf", "amf"],
}

ANTENNA_KEYWORDS: Dict[str, List[str]] = {
    "相控阵": ["相控阵", "aesa", "平面阵", "阵列"],
    "反射面": ["反射面", "抛物面", "伞天线", "伞状", "展开式", "反射阵"],
    "喇叭": ["喇叭", "全向天线", "omni"],
    "螺旋": ["螺旋", "测控天线"],
    "光学": ["光学天线", "激光终端", "光天线"],
}

FORWARDING_KEYWORDS: Dict[str, List[str]] = {
    "transparent": ["透明转发", "bent-pipe", "弯管", "透明弯管", "直接转发"],
    "regenerative": ["处理转发", "再生转发", "星上再生", "再生"],
    "dtp": ["dtp", "数字透明", "柔性", "软件定义", "在轨重构", "灵活载荷"],
}

SPECIAL_KEYWORDS: Dict[str, List[str]] = {
    "协议": ["协议", "icd", "接口协议", "接口控制"],
    "批产": ["批产", "量产", "批量生产", "规模化"],
    "抗干扰": ["抗干扰", "抗截获", "低截获", "电子对抗", "军用"],
    "星间组网": ["星间组网", "星座组网", "组网"],
    "手机直连": ["手机直连", "直连手机", "d2d", "direct-to-device"],
}

# 遥感载荷细分类型（决定选型判据与货架目录）
RS_SUBTYPE_KEYWORDS: Dict[str, List[str]] = {
    "SAR": ["sar", "合成孔径", "雷达", "微波遥感"],
    "高光谱": ["高光谱", "hyperspectral", "光谱仪"],
    "多光谱": ["多光谱", "multispectral", "msi"],
    "全色": ["全色", "pan", "panchromatic", "高分辨率成像"],
}


# ============================================================
# 结构化意图
# ============================================================

@dataclass
class IntentResult:
    """意图解析结果"""
    payload_type: str = "unknown"
    orbit_type: str = "unknown"
    frequency_bands: List[str] = field(default_factory=list)
    key_technologies: List[str] = field(default_factory=list)
    antenna_types: List[str] = field(default_factory=list)
    forwarding_mode: Optional[str] = None
    special_requirements: List[str] = field(default_factory=list)
    rs_subtype: Optional[str] = None   # 遥感细分: SAR/高光谱/多光谱/全色
    # 数值指标（从原文抽取）
    metrics: Dict[str, float] = field(default_factory=dict)
    ambiguity: Optional[str] = None
    backend: str = "keyword"
    raw_input: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        parts = [f"载荷类型={self.payload_type}", f"轨道={self.orbit_type}"]
        if self.frequency_bands:
            parts.append(f"频段={'/'.join(self.frequency_bands)}")
        if self.key_technologies:
            parts.append(f"关键技术={'、'.join(self.key_technologies[:4])}")
        if self.forwarding_mode:
            parts.append(f"转发体制={self.forwarding_mode}")
        if self.antenna_types:
            parts.append(f"天线形态={'、'.join(self.antenna_types)}")
        if self.special_requirements:
            parts.append(f"特殊需求={'、'.join(self.special_requirements)}")
        if self.rs_subtype:
            parts.append(f"遥感细分={self.rs_subtype}")
        if self.metrics:
            m = "、".join(f"{k}={v:g}" for k, v in self.metrics.items())
            parts.append(f"指标[{m}]")
        return " | ".join(parts)


# ============================================================
# 数值指标提取
# ============================================================

_CMP = (r"(?:≥|≤|>=|<=|>|<|不大于|不超过|不低于|不小于|优于|好于|高于|低于"
        r"|大于|小于|等于|约|为|:|：|\s)*")


def extract_metrics(text: str) -> Dict[str, float]:
    """从需求原文抽取数值指标: EIRP / G/T / 质量 / 功耗 / 寿命 / 容量 / 波束数"""
    low = text.lower()
    m: Dict[str, float] = {}

    def grab(pattern: str, key: str, scale: float = 1.0):
        r = re.search(pattern, low)
        if r:
            try:
                m[key] = float(r.group(1)) * scale
            except (ValueError, IndexError):
                pass

    grab(r"eirp\s*" + _CMP + r"\s*(-?\d+(?:\.\d+)?)\s*db\s*w?", "eirp_dbw")
    grab(r"g\s*/\s*t\s*" + _CMP + r"\s*(-?\d+(?:\.\d+)?)\s*(?:db\s*/?\s*k)?", "gt_dbk")
    grab(r"(?:载荷)?(?:质量|重量)\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)", "mass_kg")
    grab(r"功耗\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(kw|mw|w)", "power_w")
    if "power_w" in m:
        pm = re.search(r"功耗\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(kw|w)", low)
        if pm and pm.group(2) == "kw":
            m["power_w"] *= 1000.0
    grab(r"(?:设计|任务)?寿命\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*年", "life_years")
    grab(r"(?:总)?容量\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(gbps|mbps)", "capacity_gbps")
    if "capacity_gbps" in m:
        cm = re.search(r"(?:总)?容量\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(gbps|mbps)", low)
        if cm and cm.group(2) == "mbps":
            m["capacity_gbps"] /= 1000.0
    grab(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*波束", "beam_num")
    grab(r"带宽\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(ghz|mhz)", "bandwidth_mhz")
    if "bandwidth_mhz" in m:
        bm = re.search(r"带宽\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(ghz|mhz)", low)
        if bm and bm.group(2) == "ghz":
            m["bandwidth_mhz"] *= 1000.0
    # 遥感: 空间分辨率 / 幅宽
    grab(r"(?:空间)?分辨率\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(?:m|米)", "resolution_m")
    grab(r"幅宽\s*" + _CMP + r"\s*(\d+(?:\.\d+)?)\s*(?:km|公里)", "swath_km")
    # 遥感载荷类型细分
    return m


def parse_frequency_bands(text: str) -> List[str]:
    """频段识别: 字母频段 + 带 GHz 上下文的数值频段 + L 波段特征频点"""
    low = text.lower()
    bands: List[str] = []

    for band, kws in FREQ_KEYWORDS.items():
        if any(k in low for k in kws):
            if band not in bands:
                bands.append(band)

    # 数值频段: 必须有 GHz 上下文
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:ghz|g赫兹)", low):
        try:
            f = float(m.group(1))
        except ValueError:
            continue
        for lo, hi, band in FREQ_NUMERIC_GHZ:
            if lo <= f <= hi and band not in bands:
                bands.append(band)
                break

    # L 波段特征频点 (MHz)
    for marker in FREQ_L_MARKERS_MHZ:
        if str(marker) in low and "L" not in bands:
            bands.append("L")
            break

    # 激光独立成项（已在 FREQ_KEYWORDS）
    return bands


# ============================================================
# 关键词后端
# ============================================================

class KeywordIntentParser:
    """零依赖关键词意图解析器"""
    backend = "keyword"

    def parse(self, text: str) -> IntentResult:
        low = text.lower()
        r = IntentResult(raw_input=text, backend="keyword")

        # 载荷类型（取命中关键词最多者）
        best, best_hit = "unknown", 0
        for ptype, kws in PAYLOAD_KEYWORDS.items():
            hit = sum(1 for k in kws if k in low)
            if hit > best_hit:
                best, best_hit = ptype, hit
        r.payload_type = best

        # 轨道
        best_o, best_oh = "unknown", 0
        for orbit, kws in ORBIT_KEYWORDS.items():
            hit = sum(1 for k in kws if k in low)
            if hit > best_oh:
                best_o, best_oh = orbit, hit
        r.orbit_type = best_o

        r.frequency_bands = parse_frequency_bands(text)

        for tech, kws in TECH_KEYWORDS.items():
            if any(k in low for k in kws):
                r.key_technologies.append(tech)

        for atype, kws in ANTENNA_KEYWORDS.items():
            if any(k in low for k in kws) and atype not in r.antenna_types:
                r.antenna_types.append(atype)

        for mode, kws in FORWARDING_KEYWORDS.items():
            if any(k in low for k in kws):
                r.forwarding_mode = mode
                break

        for sp, kws in SPECIAL_KEYWORDS.items():
            if any(k in low for k in kws):
                r.special_requirements.append(sp)

        # 遥感细分类型（仅遥感载荷有效）
        if r.payload_type == "remote_sensing":
            for sub, kws in RS_SUBTYPE_KEYWORDS.items():
                if any(k in low for k in kws):
                    r.rs_subtype = sub
                    break

        r.metrics = extract_metrics(text)
        r.ambiguity = self._detect_ambiguity(low, r)
        return r

    @staticmethod
    def _detect_ambiguity(low: str, r: IntentResult) -> Optional[str]:
        """冲突/歧义检测"""
        if r.payload_type == "communication" and r.frequency_bands:
            if "激光" in r.frequency_bands and len(r.frequency_bands) > 2:
                return "同时出现射频与激光频段，请明确激光终端用于星间链路还是星地下行"
        if r.forwarding_mode == "transparent" and "数字透明处理" in r.key_technologies:
            return "同时提到透明转发与 DTP 数字透明处理，请确认是纯透明还是柔性(DTP)体制"
        if r.orbit_type == "GEO" and "手机直连" in r.special_requirements:
            return "GEO 轨道手机直连链路余量受限，请确认是否改为 LEO 星座或确认为固定终端业务"
        return None


# ============================================================
# LLM 后端（可选）
# ============================================================

LLM_INTENT_PROMPT = """你是卫星有效载荷需求分析专家。从用户需求中提取结构化信息，只输出 JSON。

字段说明:
payload_type: communication | remote_sensing | navigation | science | unknown
orbit_type: LEO | MEO | GEO | SSO | HEO | unknown
frequency_bands: 频段列表，如 ["Ku","Ka"]；未明确则为空数组
key_technologies: 关键技术列表，如 ["相控阵天线","数字透明处理"]
antenna_types: 天线形态，如 ["相控阵","反射面"]
forwarding_mode: transparent | regenerative | dtp | null
special_requirements: 特殊需求，如 ["批产","抗干扰"]
metrics: 数值指标对象，键为 eirp_dbw/gt_dbk/mass_kg/power_w/life_years/capacity_gbps/beam_num/bandwidth_mhz
ambiguity: 需求歧义点，无则 null

规则: 缺项一律置空/null，禁止猜测填充；数值频段必须带 GHz 单位上下文才识别。

用户需求: {user_input}
"""


class LLMIntentParser:
    """LLM 驱动的意图解析（失败自动降级关键词）"""
    backend = "llm"

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "gpt-4o",
                 timeout: float = 60.0):
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self.model = model
        self.timeout = timeout
        self._fallback = KeywordIntentParser()

    def parse(self, text: str) -> IntentResult:
        if not self.api_key:
            return self._fallback.parse(text)
        try:
            return self._parse_llm(text)
        except Exception as e:  # noqa: BLE001 — 任何失败均降级，保证不中断
            logger.warning(f"LLM 意图解析失败，降级关键词后端: {e}")
            r = self._fallback.parse(text)
            r.backend = "keyword(fallback-from-llm)"
            return r

    def _parse_llm(self, text: str) -> IntentResult:
        import json
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user",
                           "content": LLM_INTENT_PROMPT.format(user_input=text)}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content or "{}")
        finally:
            client.close()

        kw = self._fallback.parse(text)
        r = IntentResult(
            payload_type=data.get("payload_type") or kw.payload_type,
            orbit_type=data.get("orbit_type") or kw.orbit_type,
            frequency_bands=data.get("frequency_bands") or kw.frequency_bands,
            key_technologies=data.get("key_technologies") or kw.key_technologies,
            antenna_types=data.get("antenna_types") or kw.antenna_types,
            forwarding_mode=data.get("forwarding_mode") or kw.forwarding_mode,
            special_requirements=data.get("special_requirements") or kw.special_requirements,
            metrics=data.get("metrics") or kw.metrics,
            ambiguity=data.get("ambiguity") or kw.ambiguity,
            backend="llm", raw_input=text,
        )
        return r


# ============================================================
# 统一入口
# ============================================================

class IntentChain:
    """意图解析统一入口: 有 LLM Key 用 LLM，否则关键词"""

    def __init__(self, use_llm: bool = True, api_key: str = "", base_url: str = "",
                 model: str = "gpt-4o"):
        self._kw = KeywordIntentParser()
        self._llm = LLMIntentParser(api_key=api_key, base_url=base_url, model=model) \
            if use_llm and api_key else None
        self.backend = "llm" if self._llm else "keyword"

    def parse(self, text: str) -> IntentResult:
        if self._llm:
            return self._llm.parse(text)
        return self._kw.parse(text)


# ============================================================
# 缺项澄清（流程节点: 需求确认闸口）
# ============================================================

REQUIRED_FIELDS = ["payload_type", "orbit_type"]


def build_clarifications(intent: IntentResult) -> List[dict]:
    """生成需要用户澄清的缺项清单 —— 禁止擅自假设

    触发条件:
      1. 载荷类型未识别
      2. 轨道类型未识别
      3. 通信载荷未指定频段
      4. 通信载荷未指定转发体制
      5. 意图解析器自身标记的歧义
    """
    items: List[dict] = []

    if intent.payload_type in (None, "", "unknown"):
        items.append({
            "field": "payload_type", "level": "blocking",
            "question": "未识别到载荷类型，本次设计的是哪类载荷？",
            "options": ["通信载荷", "遥感载荷", "导航载荷", "科学实验载荷"],
        })

    if intent.orbit_type in (None, "", "unknown"):
        items.append({
            "field": "orbit_type", "level": "blocking",
            "question": "未识别到目标轨道，卫星运行在哪类轨道？",
            "options": ["GEO 地球静止轨道", "LEO 低地球轨道",
                        "MEO 中地球轨道", "SSO 太阳同步轨道"],
        })

    is_comm = intent.payload_type == "communication"
    if is_comm and not intent.frequency_bands:
        items.append({
            "field": "frequency_bands", "level": "blocking",
            "question": "通信载荷未指定工作频段，使用哪个频段？",
            "options": ["L 频段", "S 频段", "C 频段", "Ku 频段", "Ka 频段", "激光"],
        })

    if is_comm and not intent.forwarding_mode:
        items.append({
            "field": "forwarding_mode", "level": "warning",
            "question": "未指定转发体制，采用哪种？（不指定将按业务场景推荐）",
            "options": ["透明转发 Bent-Pipe", "处理转发 星上再生", "柔性载荷 DTP"],
        })

    if is_comm and "eirp_dbw" not in intent.metrics:
        items.append({
            "field": "eirp_dbw", "level": "warning",
            "question": "未给出 EIRP 指标要求，将按频段与波束数推算，是否确认？",
            "options": [],
        })

    if intent.ambiguity:
        items.append({
            "field": "ambiguity", "level": "blocking",
            "question": f"需求存在歧义：{intent.ambiguity}",
            "options": [],
        })

    return items


if __name__ == "__main__":
    cases = [
        "设计GEO Ka频段高通量通信载荷，EIRP≥62dBW，G/T≥12，多波束相控阵，DTP柔性体制，容量50Gbps",
        "做一个L波段手机直连的低轨星座载荷，12米伞天线，寿命7年，要批产",
        "设计30GHz上行、20GHz下行的GEO载荷，质量不超过650kg，功耗≤8kW",
        "帮我看看遥感载荷",
    ]
    p = KeywordIntentParser()
    for c in cases:
        r = p.parse(c)
        print(f"\n输入: {c}\n  → {r.summary()}")
        cl = build_clarifications(r)
        if cl:
            print(f"  → 需澄清 {len(cl)} 项: " + "; ".join(x["field"] for x in cl))
        else:
            print("  → 需求完整，可进入选型")
