"""选型引擎 (SK-ANTSEL / SK-EQUIP / SK-PLAT / SK-LAUNCH)

三级选型闭环: 载荷方案(天线+转发器) → 平台 → 运载火箭

核心原则:
  1. 天线选型由五要素确定: EIRP / G/T / 重量 / 功耗 / 工作模式
  2. 单机尽量选货架: 飞行继承货架 > 飞行继承 > 货架(在研转货架) > 定制
  3. 频段硬过滤: 请求频段有匹配产品时只返回匹配产品
  4. 平台/运载按多因子评分，附候选与推荐理由
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .intent import IntentResult
from .catalog import (
    CATALOG_ANTENNAS, CATALOG_EQUIPMENT, SATELLITE_PLATFORMS,
    LAUNCH_VEHICLES, ARCH_TEMPLATES, FREQUENCY_BANDS, ORBIT_TYPES,
    ANTENNA_SELECTION_CRITERIA, CATALOG_RS_PAYLOADS, CATALOG_NAV_PAYLOADS,
    CATALOG_SCI_PAYLOADS, NONCOMM_SELECTION_CRITERIA,
)

logger = logging.getLogger(__name__)

# 质量/功耗估算裕度（工程惯例 20%）
MARGIN = 0.20

# 转发链路单机品类顺序
CHAIN_ORDER = ["LNA", "DCONV", "OMUX", "DTP", "UCONV", "SSPA", "TWTA", "MPA",
               "CIRC", "SWITCH", "BCN", "TTC", "OPT"]


# ============================================================
# 选型需求
# ============================================================

@dataclass
class SelectionRequirement:
    """选型需求 = 天线五要素 + 轨道 + 寿命 + 容量

    质量/功耗预算分两层:
      budget_*  用户显式给出的硬约束（None = 未指定，不施加假约束）
      ref_*     按轨道给的工程参考包络，仅用于天线评分排序，不判可行性
    真正的可行性判据是"首选平台的实际承载/供电能力"，见 SelectionEngine.run()。
    """
    eirp_dbw: float = 55.0
    gt_dbk: float = 5.0
    mass_budget_kg: Optional[float] = None      # 用户硬约束（未指定为 None）
    power_budget_w: Optional[float] = None      # 用户硬约束（未指定为 None）
    ref_mass_kg: float = 650.0                  # 轨道典型参考包络（评分用）
    ref_power_w: float = 6000.0                 # 轨道典型参考包络（评分用）
    mode: str = "多波束"
    orbit: str = "GEO"
    life_years: Optional[float] = None
    capacity_gbps: Optional[float] = None
    beam_num: Optional[float] = None
    forwarding_mode: str = "transparent"
    bands: List[str] = field(default_factory=list)
    source: Dict[str, str] = field(default_factory=dict)  # 每项来自用户/默认/推算

    # 轨道典型参考包络
    REF_ENVELOPE: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "GEO": (650.0, 6000.0),
        "MEO": (380.0, 1800.0),
        "LEO": (150.0, 800.0),
        "SSO": (300.0, 1200.0),
        "HEO": (400.0, 2000.0),
    }, repr=False)

    @classmethod
    def from_intent(cls, intent: IntentResult) -> "SelectionRequirement":
        req = cls()
        m = intent.metrics
        src = {}

        # EIRP
        if "eirp_dbw" in m:
            req.eirp_dbw = float(m["eirp_dbw"])
            src["eirp_dbw"] = "用户指定"
        else:
            req.eirp_dbw = cls._default_eirp(intent)
            src["eirp_dbw"] = "按轨道/频段/体制推算"

        # G/T
        if "gt_dbk" in m:
            req.gt_dbk = float(m["gt_dbk"])
            src["gt_dbk"] = "用户指定"
        else:
            req.gt_dbk = cls._default_gt(intent)
            src["gt_dbk"] = "按轨道/频段推算"

        # 质量/功耗硬约束：仅当用户显式给出才设置
        if "mass_kg" in m:
            req.mass_budget_kg = float(m["mass_kg"])
            src["mass_budget_kg"] = "用户指定"
        else:
            src["mass_budget_kg"] = "未指定（按平台能力校核）"
        if "power_w" in m:
            req.power_budget_w = float(m["power_w"])
            src["power_budget_w"] = "用户指定"
        else:
            src["power_budget_w"] = "未指定（按平台能力校核）"

        # 轨道与参考包络
        orb = intent.orbit_type if intent.orbit_type in ORBIT_TYPES else "GEO"
        req.orbit = orb
        src["orbit"] = "用户指定" if intent.orbit_type in ORBIT_TYPES else "工程默认(GEO)"
        ref_m, ref_p = req.REF_ENVELOPE.get(orb, (650.0, 6000.0))
        # 用户硬约束存在时，参考包络取"约束与轨道典型"的较大者，避免评分被过紧参考压制
        req.ref_mass_kg = max(ref_m, req.mass_budget_kg or 0.0) or ref_m
        req.ref_power_w = max(ref_p, req.power_budget_w or 0.0) or ref_p

        req.life_years = float(m["life_years"]) if "life_years" in m else None
        src["life_years"] = "用户指定" if "life_years" in m else "未指定"
        req.capacity_gbps = float(m["capacity_gbps"]) if "capacity_gbps" in m else None
        req.beam_num = float(m["beam_num"]) if "beam_num" in m else None

        req.forwarding_mode = intent.forwarding_mode or "transparent"
        src["forwarding_mode"] = "用户指定" if intent.forwarding_mode else "默认透明转发"
        req.bands = list(intent.frequency_bands)
        src["bands"] = "用户指定" if req.bands else "待澄清"

        # 工作模式由关键技术推断
        techs = " ".join(intent.key_technologies)
        if "数字透明处理" in techs:
            req.mode = "在轨重构"
        elif "多波束" in techs:
            req.mode = "多波束"
        elif "相控阵天线" in techs:
            req.mode = "波束跳变"
        elif "伞天线" in techs or "反射面天线" in techs:
            req.mode = "多波束"
        else:
            req.mode = "单波束"
        src["mode"] = "由关键技术推断"

        req.source = src
        return req

    @staticmethod
    def _default_eirp(intent: IntentResult) -> float:
        """按轨道+频段推算 EIRP 默认值 (dBW)"""
        base = {"GEO": 55.0, "MEO": 48.0, "LEO": 42.0, "SSO": 40.0, "HEO": 50.0}
        v = base.get(intent.orbit_type, 52.0)
        bands = intent.frequency_bands
        if "Ka" in bands:
            v += 5.0
        elif "Ku" in bands:
            v += 3.0
        elif "L" in bands or "S" in bands:
            v -= 8.0
        elif "C" in bands:
            v -= 2.0
        if "相控阵天线" in intent.key_technologies:
            v += 2.0
        return v

    @staticmethod
    def _default_gt(intent: IntentResult) -> float:
        """按轨道+频段推算 G/T 默认值 (dB/K)"""
        base = {"GEO": 8.0, "MEO": 4.0, "LEO": 0.0, "SSO": 0.0, "HEO": 5.0}
        v = base.get(intent.orbit_type, 5.0)
        bands = intent.frequency_bands
        if "Ka" in bands:
            v += 4.0
        elif "Ku" in bands:
            v += 2.5
        elif "L" in bands:
            v -= 6.0
        elif "C" in bands:
            v -= 1.5
        return v


# ============================================================
# 天线选型：五要素评分
# ============================================================

def score_antenna(ant: dict, req: SelectionRequirement) -> Tuple[float, List[str]]:
    """五要素评分（满分 100）: EIRP 30 / G/T 25 / 重量 20 / 功耗 15 / 工作模式 10"""
    score = 0.0
    reasons: List[str] = []

    if ant["eirp_cap_dbw"] >= req.eirp_dbw:
        score += 30.0
        reasons.append(f"EIRP 能力 {ant['eirp_cap_dbw']:.0f} dBW ≥ 需求 {req.eirp_dbw:.0f} dBW")
    else:
        gap = req.eirp_dbw - ant["eirp_cap_dbw"]
        score += 30.0 * max(0.0, 1.0 - gap / 10.0)
        reasons.append(f"EIRP 能力不足（{ant['eirp_cap_dbw']:.0f} < {req.eirp_dbw:.0f} dBW，差 {gap:.1f} dB）")

    if ant["gt_dbk"] >= req.gt_dbk:
        score += 25.0
        reasons.append(f"G/T {ant['gt_dbk']:.1f} dB/K ≥ 需求 {req.gt_dbk:.1f} dB/K")
    else:
        gap = req.gt_dbk - ant["gt_dbk"]
        score += 25.0 * max(0.0, 1.0 - gap / 8.0)
        reasons.append(f"G/T 不足（{ant['gt_dbk']:.1f} < {req.gt_dbk:.1f} dB/K，差 {gap:.1f} dB）")

    if ant["mass_kg"] <= req.ref_mass_kg:
        score += 20.0
        reasons.append(f"质量 {ant['mass_kg']:.0f} kg ≤ 参考包络 {req.ref_mass_kg:.0f} kg"
                       f"（占用 {ant['mass_kg'] / req.ref_mass_kg * 100:.0f}%）")
    else:
        score += 20.0 * req.ref_mass_kg / ant["mass_kg"]
        reasons.append(f"质量偏大（{ant['mass_kg']:.0f} > 参考包络 {req.ref_mass_kg:.0f} kg）")

    if ant["power_w"] <= req.ref_power_w:
        score += 15.0
        reasons.append(f"功耗 {ant['power_w']:.0f} W ≤ 参考包络 {req.ref_power_w:.0f} W")
    else:
        score += 15.0 * req.ref_power_w / ant["power_w"]
        reasons.append(f"功耗偏大（{ant['power_w']:.0f} > 参考包络 {req.ref_power_w:.0f} W）")

    if any(req.mode in md for md in ant["modes"]):
        score += 10.0
        reasons.append(f"支持工作模式：{req.mode}")
    else:
        reasons.append(f"工作模式不匹配（需 {req.mode}，具备 {'/'.join(ant['modes'])}）")

    # 货架水平加权（同等条件下优先飞行继承）
    score += ant.get("heritage", 1) * 0.5

    return round(score, 2), reasons


class AntennaSelector:
    """天线选型器：五要素评分 + 频段硬过滤"""

    def select(self, req: SelectionRequirement, top_k: int = 3,
               exclude_models: Optional[List[str]] = None
               ) -> List[Tuple[float, dict, List[str]]]:
        exclude = set(exclude_models or [])

        def band_hit(ant: dict) -> bool:
            if not req.bands:
                return True
            return any(b.lower() in ant["band"].lower() for b in req.bands)

        scored = []
        for ant in CATALOG_ANTENNAS:
            if ant["model"] in exclude:      # 校核回环中被否决的候选不再参与
                continue
            s, rs = score_antenna(ant, req)
            if req.bands and not band_hit(ant):
                s *= 0.6
                rs.append("频段不匹配（降权 0.6）")
            scored.append((s, ant, rs))

        # 频段硬过滤：有匹配则只保留匹配项
        matched = [x for x in scored if band_hit(x[1])]
        if matched:
            scored = matched

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


# ============================================================
# 单机选型：货架优先
# ============================================================

class EquipmentSelector:
    """单机选型器：按转发体制与频段组链，货架优先

    频段硬约束: 请求频段的货架品不存在时，不回退到其他频段产品
    （L 波段载荷配 Ka 变频器是工程错误），而是记为定制缺口。
    """

    def select(self, intent: IntentResult, req: SelectionRequirement
               ) -> Tuple[List[dict], List[dict]]:
        """返回 (选中货架单机列表, 定制缺口列表)"""
        bands = req.bands or []
        mode = req.forwarding_mode
        picked: List[dict] = []
        gaps: List[dict] = []

        def match(cat: str, prefer_bands: List[str],
                  allow_band_fallback: bool = True) -> Optional[dict]:
            """在品类内选货架水平最高、频段匹配的产品

            allow_band_fallback=False 时，频段不匹配即返回 None（记为缺口），
            不回退到错误频段的货架品。
            """
            cands = [e for e in CATALOG_EQUIPMENT if e["cat"] == cat]
            if not cands:
                return None
            band_cands = [e for e in cands
                          if any(b.lower() in e["band"].lower() for b in prefer_bands)
                          or "全频段" in e["band"]]
            if band_cands:
                pool = band_cands
            elif allow_band_fallback:
                pool = cands
            else:
                return None
            pool = sorted(pool, key=lambda e: (-e.get("heritage", 1), e["model"]))
            return pool[0]

        def need(cat: str, label: str, prefer_bands: List[str],
                 fallback: bool = False) -> None:
            """取一个单机；取不到则记为定制缺口"""
            it = match(cat, prefer_bands, allow_band_fallback=fallback)
            if it is not None:
                if it not in picked:
                    picked.append(it)
            else:
                gaps.append({"cat": cat, "need": label,
                             "band": "/".join(prefer_bands) or "未指定",
                             "reason": f"产品库无 {label} 的 {'/'.join(prefer_bands)} 频段货架品"})

        # 光学/激光链路单独成链
        if "激光" in bands:
            need("OPT", "激光通信收发模块", ["激光"], fallback=False)

        rf_bands = [b for b in bands if b != "激光"]

        # 接收链：逐频段配 LNA
        for b in rf_bands:
            need("LNA", f"{b} 频段低噪声放大器", [b], fallback=False)

        # 变频/多工：按频段严格匹配，无则记缺口
        if rf_bands:
            need("DCONV", "下变频器", rf_bands, fallback=False)
            need("OMUX", "输入/输出多工器", rf_bands, fallback=False)

        # 体制相关
        if mode in ("dtp", "regenerative"):
            need("DTP", "数字透明处理器", ["全频段"], fallback=True)
            need("MPA", "多功放矩阵", rf_bands or ["全频段"], fallback=True)
        else:
            for b in (rf_bands or ["未指定"]):
                pa = match("SSPA", [b], allow_band_fallback=False) \
                    or match("TWTA", [b], allow_band_fallback=False)
                if pa is not None:
                    if pa not in picked:
                        picked.append(pa)
                    break
            else:
                gaps.append({"cat": "SSPA/TWTA", "need": "功率放大器",
                             "band": "/".join(rf_bands) or "未指定",
                             "reason": "产品库无该频段功放货架品"})

        if rf_bands:
            need("UCONV", "上变频器", rf_bands, fallback=False)
            need("CIRC", "环行器/隔离器", rf_bands, fallback=False)

        # 公用（频段无关）
        need("SWITCH", "微波开关矩阵", ["全频段"], fallback=True)
        need("BCN", "信标发射机", ["S"], fallback=True)
        need("TTC", "测控应答机", ["S"], fallback=True)

        # 去重并按链路顺序排序
        seen, uniq = set(), []
        for e in picked:
            if e["model"] not in seen:
                seen.add(e["model"])
                uniq.append(e)
        uniq.sort(key=lambda e: CHAIN_ORDER.index(e["cat"]) if e["cat"] in CHAIN_ORDER else 99)
        return uniq, gaps

    @staticmethod
    def totals(equipment: List[dict]) -> Tuple[float, float]:
        mass = sum(e.get("mass_kg", 0.0) for e in equipment)
        power = sum(e.get("power_w", 0.0) for e in equipment)
        return round(mass, 1), round(power, 1)


# ============================================================
# 非通信载荷选型（遥感/导航/科学）
# ============================================================

class NonCommSelector:
    """非通信载荷选型器

    判据与通信载荷完全不同（不用 EIRP/G/T 天线五维）:
      遥感  → 分辨率/幅宽/数据率/质量/功耗/指向
      导航  → 信号体制/EIRP·UERE/原子钟/质量/功耗
      科学  → 灵敏度/观测几何/数据率/质量/功耗
    """

    CATALOG_BY_TYPE = {
        "remote_sensing": CATALOG_RS_PAYLOADS,
        "navigation": CATALOG_NAV_PAYLOADS,
        "science": CATALOG_SCI_PAYLOADS,
    }

    def select(self, intent: IntentResult, req: SelectionRequirement,
               top_k: int = 3) -> Tuple[List[Tuple[float, dict, List[str]]], List[dict]]:
        """返回 (评分排序候选, 定制缺口)"""
        catalog = self.CATALOG_BY_TYPE.get(intent.payload_type, [])
        criteria = NONCOMM_SELECTION_CRITERIA.get(intent.payload_type, [])
        if not catalog:
            return [], [{"cat": intent.payload_type, "need": "载荷货架目录",
                         "band": "-", "reason": "产品库暂无该载荷类型货架目录，需定制研制"}]

        pool = catalog
        gaps: List[dict] = []

        # 遥感按细分类型过滤
        if intent.payload_type == "remote_sensing" and intent.rs_subtype:
            sub = [x for x in pool if intent.rs_subtype.lower() in str(x.get("subtype", "")).lower()
                   or intent.rs_subtype.lower() in x["name"].lower()]
            if sub:
                pool = sub
            else:
                gaps.append({"cat": "遥感", "need": f"{intent.rs_subtype} 载荷",
                             "band": "-",
                             "reason": f"产品库无 {intent.rs_subtype} 类型货架品，需定制"})

        scored = []
        for it in pool:
            s, rs = self._score(it, intent, req, criteria)
            scored.append((s, it, rs))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k], gaps

    def _score(self, it: dict, intent: IntentResult, req: SelectionRequirement,
               criteria: List[dict]) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        m = intent.metrics

        if intent.payload_type == "remote_sensing":
            # 分辨率 30
            need_res = m.get("resolution_m")
            got_res = it.get("resolution_m")
            if need_res and got_res:
                if got_res <= need_res:
                    score += 30.0
                    reasons.append(f"分辨率 {got_res} m ≤ 需求 {need_res} m（满足）")
                else:
                    score += 30.0 * max(0.0, 1.0 - (got_res - need_res) / need_res)
                    reasons.append(f"分辨率 {got_res} m 劣于需求 {need_res} m")
            elif got_res:
                score += 24.0
                reasons.append(f"分辨率 {got_res} m（需求未指定，按货架能力计）")
            # 幅宽 20
            need_sw = m.get("swath_km")
            got_sw = it.get("swath_km")
            if need_sw and got_sw:
                if got_sw >= need_sw:
                    score += 20.0
                    reasons.append(f"幅宽 {got_sw} km ≥ 需求 {need_sw} km")
                else:
                    score += 20.0 * got_sw / need_sw
                    reasons.append(f"幅宽 {got_sw} km < 需求 {need_sw} km")
            else:
                score += 16.0
                reasons.append(f"幅宽 {got_sw or '-'} km（需求未指定）")
            # 数据率 15
            score += 15.0 if it.get("data_rate_mbps") else 8.0
            reasons.append(f"数据率 {it.get('data_rate_mbps', '-')} Mbps")
        else:
            # 导航/科学：指标匹配度按货架能力给基础分
            score += 65.0
            reasons.append("按货架能力与任务匹配度计（指标需求未量化）")

        # 质量 15 / 功耗 10（对参考包络）
        mass, power = it.get("mass_kg", 0.0), it.get("power_w", 0.0)
        score += 15.0 if mass <= req.ref_mass_kg else 15.0 * req.ref_mass_kg / max(mass, 1e-6)
        reasons.append(f"质量 {mass:.0f} kg vs 参考包络 {req.ref_mass_kg:.0f} kg")
        score += 10.0 if power <= req.ref_power_w else 10.0 * req.ref_power_w / max(power, 1e-6)
        reasons.append(f"功耗 {power:.0f} W vs 参考包络 {req.ref_power_w:.0f} W")

        # 货架成熟度加权
        score += it.get("heritage", 1) * 0.5
        reasons.append(f"成熟度：{it.get('heritage_desc', '未知')}")
        return round(score, 2), reasons


# ============================================================
# 平台选型：五因子评分
# ============================================================

class PlatformSelector:
    """平台选型器: 轨道适配15 + 承载贴合30 + 供电贴合25 + 寿命匹配15 + 飞行成熟度15

    可行性预筛: 仅轨道匹配且承载/供电均满足的平台进入评分排序；
    全部不满足时返回空 feasible 列表，由上层触发"平台不可行"L3 处置。

    轨道包含关系: SSO 是 LEO 的子集（LEO 平台均可承接 SSO 任务）。
    """

    # 目标轨道 → 该轨道任务可接受的平台轨道能力
    ORBIT_COMPAT: Dict[str, List[str]] = {
        "GEO": ["GEO"],
        "MEO": ["MEO"],
        "LEO": ["LEO"],
        "SSO": ["SSO", "LEO"],   # SSO 任务可由 LEO 平台承接
        "HEO": ["HEO", "GEO"],
    }

    def _orbit_ok(self, platform_orbits: str, target_orbit: str) -> bool:
        accepted = self.ORBIT_COMPAT.get(target_orbit.upper(), [target_orbit.upper()])
        po = platform_orbits.upper()
        return any(a in po for a in accepted)

    def select(self, payload_mass: float, payload_power: float, orbit: str,
               life_years: Optional[float] = None, top_k: int = 3
               ) -> Tuple[List[Tuple[dict, float, List[str]]], List[dict]]:
        """返回 (可行平台排序列表, 被筛除的不满足项)"""
        feasible, rejected = [], []
        for p in SATELLITE_PLATFORMS:
            ok_orbit = self._orbit_ok(p["orbits"], orbit)
            ok_mass = p["payload_mass_kg"] >= payload_mass
            ok_power = p["payload_power_w"] >= payload_power
            if ok_orbit and ok_mass and ok_power:
                s, rs = self._score(p, payload_mass, payload_power, orbit, life_years)
                feasible.append((p, s, rs))
            else:
                why = []
                if not ok_orbit:
                    why.append(f"轨道不支持(仅{p['orbits']})")
                if not ok_mass:
                    why.append(f"承载{p['payload_mass_kg']:.0f}<{payload_mass:.0f}kg")
                if not ok_power:
                    why.append(f"供电{p['payload_power_w']:.0f}<{payload_power:.0f}W")
                rejected.append({"model": p["model"], "reason": "、".join(why)})
        feasible.sort(key=lambda x: x[1], reverse=True)
        return feasible[:top_k], rejected

    def _score(self, p: dict, mass: float, power: float, orbit: str,
               life: Optional[float]) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []

        # 轨道适配 15：直接声明该轨道满分，仅靠包含关系承接的给 12 分
        if orbit.upper() in p["orbits"].upper():
            score += 15.0
            reasons.append(f"轨道适配：平台直接支持 {orbit}")
        else:
            score += 12.0
            reasons.append(f"轨道适配：{orbit} 任务由 {p['orbits']} 平台承接（轨道子集）")

        # 承载贴合 30（利用率过高或过低都扣分，最优区间 60%-90%）
        cap = p["payload_mass_kg"]
        util = mass / cap
        if util >= 0.6:
            score += 30.0
        else:
            score += 30.0 * (0.5 + util)
        reasons.append(f"承载 {cap:.0f} kg ≥ 载荷 {mass:.0f} kg（利用率 {util * 100:.0f}%"
                       + ("，偏紧需关注裕度）" if util > 0.9 else "）"))

        # 供电贴合 25（最优区间 50%-90%）
        pw = p["payload_power_w"]
        util_p = power / pw
        if util_p >= 0.5:
            score += 25.0
        else:
            score += 25.0 * (0.5 + util_p)
        reasons.append(f"供电 {pw:.0f} W ≥ 载荷 {power:.0f} W（利用率 {util_p * 100:.0f}%）")

        # 寿命匹配 15
        if life:
            if p["life_years"] >= life:
                score += 15.0
                reasons.append(f"平台寿命 {p['life_years']} 年 ≥ 任务要求 {life:.0f} 年")
            else:
                score += 15.0 * p["life_years"] / life
                reasons.append(f"平台寿命 {p['life_years']} 年 < 任务要求 {life:.0f} 年（降分）")
        else:
            score += 12.0
            reasons.append(f"平台设计寿命 {p['life_years']} 年（任务寿命未指定）")

        # 飞行成熟度 15
        score += p.get("heritage", 1) / 4.0 * 15.0
        reasons.append(f"成熟度：{p.get('heritage_desc', '未知')}")

        return round(score, 2), reasons


# ============================================================
# 运载选型：四因子评分
# ============================================================

class LauncherSelector:
    """运载选型器: 入轨能力40 + 经济性25 + 飞行履历20 + 整流罩包络15"""

    CAP_KEY = {"GEO": "gto_kg", "LEO": "leo_kg", "MEO": "leo_kg",
               "SSO": "sso_kg", "HEO": "gto_kg"}

    def select(self, sat_mass_kg: float, orbit: str, sat_envelope_m: Optional[float] = None,
               top_k: int = 3) -> List[Tuple[dict, float, List[str]]]:
        cap_key = self.CAP_KEY.get(orbit.upper(), "leo_kg")
        out = []
        for lv in LAUNCH_VEHICLES:
            s, rs = self._score(lv, sat_mass_kg, cap_key, sat_envelope_m)
            out.append((lv, s, rs))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:top_k]

    def _score(self, lv: dict, sat_mass: float, cap_key: str,
               envelope: Optional[float]) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        cap = lv.get(cap_key)

        # 入轨能力 40
        if cap is None:
            reasons.append(f"无 {cap_key.replace('_kg','').upper()} 入轨数据（不适用）")
        elif cap >= sat_mass:
            util = sat_mass / cap
            score += 40.0 if util >= 0.5 else 40.0 * (0.4 + util)
            reasons.append(f"入轨能力 {cap:.0f} kg ≥ 整星 {sat_mass:.0f} kg（利用率 {util * 100:.0f}%）")
            if util < 0.5:
                reasons.append("能力余量 > 50%，存在搭载/拼单降本机会")
        else:
            reasons.append(f"入轨能力不足（{cap:.0f} < {sat_mass:.0f} kg）")

        # 经济性 25（单位质量发射成本）
        cost = lv.get("cost_musd")
        if cap and cost:
            per_kg = cost * 1e6 / cap
            score += max(0.0, 25.0 * (1.0 - min(per_kg / 30000.0, 1.0)))
            reasons.append(f"单位入轨成本约 {per_kg / 1000:.1f} k$/kg")

        # 飞行履历 20
        flights = lv.get("flights") or 0
        score += 20.0 * min(flights / 50.0, 1.0)
        reasons.append(f"飞行 {flights} 次（{'成熟' if flights >= 20 else '在役验证中'}）")

        # 整流罩包络 15
        if envelope and lv.get("fairing_m"):
            if lv["fairing_m"] >= envelope:
                score += 15.0
                reasons.append(f"整流罩 Φ{lv['fairing_m']} m ≥ 整星包络 Φ{envelope} m")
            else:
                reasons.append(f"整流罩包络超限（Φ{lv['fairing_m']} < Φ{envelope} m），需评估折叠/拆分")
        else:
            score += 10.0
            reasons.append("整流罩包络按默认校核（整星包络未提供）")

        return round(score, 2), reasons


# ============================================================
# 选型结果
# ============================================================

@dataclass
class SelectionPlan:
    """三级选型结果汇总"""
    requirement: SelectionRequirement
    payload_type: str = "communication"   # 决定选型判据与文档模板
    architecture: dict = field(default_factory=dict)
    antennas: List[Tuple[float, dict, List[str]]] = field(default_factory=list)
    equipment: List[dict] = field(default_factory=list)
    gaps: List[dict] = field(default_factory=list)            # 无货架品的定制缺口
    noncomm_items: List[Tuple[float, dict, List[str]]] = field(default_factory=list)
    platforms: List[Tuple[dict, float, List[str]]] = field(default_factory=list)
    platform_rejected: List[dict] = field(default_factory=list)  # 被可行性筛除的平台
    launchers: List[Tuple[dict, float, List[str]]] = field(default_factory=list)
    payload_mass_est: float = 0.0
    payload_power_est: float = 0.0
    sat_mass_est: float = 0.0
    equipment_mass: float = 0.0
    equipment_power: float = 0.0
    warnings: List[str] = field(default_factory=list)
    feasible: bool = True          # 平台/运载可行性总判据
    iteration: int = 0             # 校核回环迭代次数

    # ---------- 便捷属性 ----------
    @property
    def is_comm(self) -> bool:
        return self.payload_type == "communication"

    @property
    def antenna(self) -> Optional[dict]:
        """通信载荷首选天线；非通信载荷返回 None"""
        return self.antennas[0][1] if self.antennas else None

    @property
    def noncomm_top(self) -> Optional[dict]:
        """非通信载荷首选单机"""
        return self.noncomm_items[0][1] if self.noncomm_items else None

    @property
    def platform(self) -> Optional[dict]:
        return self.platforms[0][0] if self.platforms else None

    @property
    def launcher(self) -> Optional[dict]:
        return self.launchers[0][0] if self.launchers else None

    # ---------- Markdown 输出 ----------
    def requirement_markdown(self) -> str:
        r = self.requirement
        mass_txt = f"{r.mass_budget_kg:.0f} kg" if r.mass_budget_kg is not None else "未指定"
        power_txt = f"{r.power_budget_w:.0f} W" if r.power_budget_w is not None else "未指定"
        rows = [
            ("EIRP", f"{r.eirp_dbw:.1f} dBW", r.source.get("eirp_dbw", "")),
            ("G/T", f"{r.gt_dbk:.1f} dB/K", r.source.get("gt_dbk", "")),
            ("质量约束", mass_txt, r.source.get("mass_budget_kg", "")),
            ("功耗约束", power_txt, r.source.get("power_budget_w", "")),
            ("参考包络", f"{r.ref_mass_kg:.0f} kg / {r.ref_power_w:.0f} W",
             f"{r.orbit} 轨道典型值（仅用于评分排序）"),
            ("工作模式", r.mode, r.source.get("mode", "")),
            ("目标轨道", r.orbit, r.source.get("orbit", "")),
            ("任务寿命", f"{r.life_years:.0f} 年" if r.life_years else "未指定",
             r.source.get("life_years", "")),
            ("转发体制", ARCH_TEMPLATES.get(r.forwarding_mode, {}).get("name", r.forwarding_mode),
             r.source.get("forwarding_mode", "")),
            ("工作频段", "/".join(r.bands) or "未指定", r.source.get("bands", "")),
        ]
        if r.capacity_gbps:
            rows.append(("容量需求", f"{r.capacity_gbps:g} Gbps", "用户指定"))
        if r.beam_num:
            rows.append(("波束数", f"{int(r.beam_num)} 个", "用户指定"))
        out = ["### 选型需求（天线五要素）", "",
               "| 要素 | 取值 | 来源 |", "|------|------|------|"]
        out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
        return "\n".join(out)

    def antenna_markdown(self) -> str:
        out = ["### 天线选型（五要素评分）", "",
               "| 排序 | 型号 | 名称 | 频段 | EIRP能力 | G/T | 质量 | 功耗 | 波束数 | 评分 | 货架水平 |",
               "|------|------|------|------|---------|-----|------|------|--------|------|---------|"]
        for i, (s, a, _) in enumerate(self.antennas, 1):
            out.append(
                f"| {'★首选' if i == 1 else i} | {a['model']} | {a['name']} | {a['band']} | "
                f"{a['eirp_cap_dbw']:.0f} dBW | {a['gt_dbk']:.1f} | {a['mass_kg']:.0f} kg | "
                f"{a['power_w']:.0f} W | {a.get('beam_num', '-')} | **{s:.1f}** | "
                f"{a.get('heritage_desc', '-')} |")
        if self.antennas:
            out += ["", "**首选理由：**", ""]
            out += [f"- {r}" for r in self.antennas[0][2]]
        return "\n".join(out)

    def noncomm_markdown(self) -> str:
        """非通信载荷选型表（遥感/导航/科学）"""
        label = {"remote_sensing": "遥感", "navigation": "导航",
                 "science": "科学实验"}.get(self.payload_type, "载荷")
        crit = NONCOMM_SELECTION_CRITERIA.get(self.payload_type, [])
        out = [f"### {label}载荷选型", ""]
        if crit:
            out += ["**选型判据（权重）：**", "",
                    "| 判据 | 权重 | 设计动作 |", "|------|------|---------|"]
            out += [f"| {c['dim']} | {c['weight']} | {c['action']} |" for c in crit]
            out += [""]
        out += ["| 排序 | 型号 | 名称 | 分辨率 | 幅宽 | 数据率 | 质量 | 功耗 | 评分 | 货架水平 |",
                "|------|------|------|--------|------|--------|------|------|------|---------|"]
        for i, (s, it, _) in enumerate(self.noncomm_items, 1):
            out.append(
                f"| {'★首选' if i == 1 else i} | {it['model']} | {it['name']} | "
                f"{str(it.get('resolution_m', '-')) + ' m' if it.get('resolution_m') else '-'} | "
                f"{str(it.get('swath_km', '-')) + ' km' if it.get('swath_km') else '-'} | "
                f"{str(it.get('data_rate_mbps', '-')) + ' Mbps' if it.get('data_rate_mbps') else '-'} | "
                f"{it.get('mass_kg', 0):.0f} kg | {it.get('power_w', 0):.0f} W | "
                f"**{s:.1f}** | {it.get('heritage_desc', '-')} |")
        if self.noncomm_items:
            out += ["", "**首选理由：**", ""]
            out += [f"- {r}" for r in self.noncomm_items[0][2]]
        if self.gaps:
            out += ["", "**定制缺口：**", ""] + [f"- {g['need']}：{g['reason']}" for g in self.gaps]
        return "\n".join(out)

    def equipment_markdown(self) -> str:
        out = ["### 单机选型（货架产品优先）", "",
               "| 序号 | 型号 | 名称 | 品类 | 频段 | 质量 | 功耗 | 货架水平 | 供应商 |",
               "|------|------|------|------|------|------|------|---------|--------|"]
        for i, e in enumerate(self.equipment, 1):
            out.append(
                f"| {i} | {e['model']} | {e['name']} | {e['cat']} | {e['band']} | "
                f"{e.get('mass_kg', 0):.1f} kg | {e.get('power_w', 0):.0f} W | "
                f"{e.get('heritage_desc', '-')} | {e.get('vendor', '-')} |")
        out += ["", f"**单机合计**：{len(self.equipment)} 台货架品，"
                    f"质量 {self.equipment_mass:.1f} kg，功耗 {self.equipment_power:.0f} W"]
        if self.gaps:
            out += ["", "**定制缺口（产品库无对应频段货架品）：**", "",
                    "| 品类 | 需求 | 频段 | 原因 |", "|------|------|------|------|"]
            out += [f"| {g['cat']} | {g['need']} | {g['band']} | {g['reason']} |"
                    for g in self.gaps]
        out += ["", "> 货架水平排序：飞行继承货架 > 飞行继承 > 货架(在研转货架) > 定制"]
        return "\n".join(out)

    def platform_markdown(self) -> str:
        out = ["### 平台选型（五因子评分）", "",
               "> 轨道适配 15 + 承载贴合 30 + 供电贴合 25 + 寿命匹配 15 + 飞行成熟度 15", "",
               "| 排序 | 型号 | 名称 | 轨道 | 承载 | 供电 | 整星质量 | 寿命 | 评分 |",
               "|------|------|------|------|------|------|---------|------|------|"]
        for i, (p, s, _) in enumerate(self.platforms, 1):
            out.append(
                f"| {'★首选' if i == 1 else i} | {p['model']} | {p['name']} | {p['orbits']} | "
                f"{p['payload_mass_kg']:.0f} kg | {p['payload_power_w']:.0f} W | "
                f"{p['sat_mass_kg']:.0f} kg | {p['life_years']} 年 | **{s:.1f}** |")
        if self.platforms:
            out += ["", "**首选理由：**", ""]
            out += [f"- {r}" for r in self.platforms[0][2]]
        else:
            out += ["", "**⚠️ 无可行平台**（载荷包络超所有同轨道平台能力）"]
        if self.platform_rejected:
            out += ["", "<details><summary>被筛除的平台及原因</summary>", "",
                    "| 平台 | 筛除原因 |", "|------|---------|"]
            out += [f"| {rj['model']} | {rj['reason']} |" for rj in self.platform_rejected]
            out += ["", "</details>"]
        return "\n".join(out)

    def launcher_markdown(self) -> str:
        out = ["### 运载火箭选型（四因子评分）", "",
               "> 入轨能力 40 + 经济性 25 + 飞行履历 20 + 整流罩包络 15", "",
               "| 排序 | 火箭 | 国别 | GTO | LEO | SSO | 整流罩 | 飞行次数 | 评分 |",
               "|------|------|------|-----|-----|-----|--------|---------|------|"]
        for i, (lv, s, _) in enumerate(self.launchers, 1):
            fmt = lambda v: f"{v:.0f} kg" if v else "—"
            out.append(
                f"| {'★首选' if i == 1 else i} | {lv['name']} | {lv['country']} | "
                f"{fmt(lv.get('gto_kg'))} | {fmt(lv.get('leo_kg'))} | {fmt(lv.get('sso_kg'))} | "
                f"Φ{lv.get('fairing_m', '-')} m | {lv.get('flights', 0)} | **{s:.1f}** |")
        if self.launchers:
            out += ["", "**首选理由：**", ""]
            out += [f"- {r}" for r in self.launchers[0][2]]
        return "\n".join(out)

    def architecture_markdown(self) -> str:
        a = self.architecture
        if not a:
            return ""
        out = [f"### 转发体制：{a.get('name', '')}", "", a.get("desc", ""), "",
               "**载荷链路组成：**", "",
               "```", "  " + " → ".join(a.get("chain", [])), "```", "",
               "| 优势 | 局限 |", "|------|------|"]
        pros, cons = a.get("pros", []), a.get("cons", [])
        for i in range(max(len(pros), len(cons))):
            out.append(f"| {pros[i] if i < len(pros) else ''} | {cons[i] if i < len(cons) else ''} |")
        out += ["", f"**适用场景**：{a.get('适用', '')}"]
        return "\n".join(out)

    def summary_markdown(self) -> str:
        out = ["### 载荷指标汇总与平台校核", "",
               "| 项目 | 数值 | 约束 | 结论 |", "|------|------|------|------|"]
        r = self.requirement
        p = self.platform

        # 校核基准：首选平台实际能力（无平台时退回用户约束）
        cap_m = p["payload_mass_kg"] if p else r.mass_budget_kg
        cap_p = p["payload_power_w"] if p else r.power_budget_w
        cap_m_txt = f"≤ {cap_m:.0f} kg（平台）" if cap_m else "未指定"
        cap_p_txt = f"≤ {cap_p:.0f} W（平台）" if cap_p else "未指定"
        ok_m = "✅ 满足" if (cap_m is None or self.payload_mass_est <= cap_m) else "⚠️ 超标"
        ok_p = "✅ 满足" if (cap_p is None or self.payload_power_est <= cap_p) else "⚠️ 超标"

        out += [
            f"| 载荷质量（含 {int(MARGIN*100)}% 裕度） | {self.payload_mass_est:.1f} kg | {cap_m_txt} | {ok_m} |",
            f"| 载荷功耗（含 {int(MARGIN*100)}% 裕度） | {self.payload_power_est:.0f} W | {cap_p_txt} | {ok_p} |",
            f"| 其中天线 | {self.antenna['mass_kg']:.0f} kg / {self.antenna['power_w']:.0f} W | — | — |" if self.antenna else "",
            f"| 其中单机 | {self.equipment_mass:.1f} kg / {self.equipment_power:.0f} W | — | — |",
            f"| 整星质量估算 | {self.sat_mass_est:.0f} kg | — | 平台 {p['model'] if p else '待定'} |",
        ]
        # 用户显式约束的二次校核
        if r.mass_budget_kg is not None:
            ok = "✅" if self.payload_mass_est <= r.mass_budget_kg else "⚠️ 超用户约束"
            out.append(f"| 用户质量约束校核 | {self.payload_mass_est:.1f} kg | ≤ {r.mass_budget_kg:.0f} kg | {ok} |")
        if r.power_budget_w is not None:
            ok = "✅" if self.payload_power_est <= r.power_budget_w else "⚠️ 超用户约束"
            out.append(f"| 用户功耗约束校核 | {self.payload_power_est:.0f} W | ≤ {r.power_budget_w:.0f} W | {ok} |")
        if self.gaps:
            out.append(f"| 定制缺口 | {len(self.gaps)} 项 | — | 需定制研制 |")

        out += ["", f"**平台/运载可行性**：{'✅ 通过' if self.feasible else '❌ 未通过'}"
                    f"（校核迭代 {self.iteration} 次）"]
        if self.warnings:
            out += ["", "**选型告警：**", ""] + [f"- ⚠️ {w}" for w in self.warnings]
        return "\n".join(x for x in out if x != "")

    def to_dict(self) -> dict:
        return {
            "requirement": {
                "eirp_dbw": self.requirement.eirp_dbw,
                "gt_dbk": self.requirement.gt_dbk,
                "mass_budget_kg": self.requirement.mass_budget_kg,
                "power_budget_w": self.requirement.power_budget_w,
                "ref_mass_kg": self.requirement.ref_mass_kg,
                "ref_power_w": self.requirement.ref_power_w,
                "mode": self.requirement.mode, "orbit": self.requirement.orbit,
                "bands": self.requirement.bands,
                "forwarding_mode": self.requirement.forwarding_mode,
                "life_years": self.requirement.life_years,
                "capacity_gbps": self.requirement.capacity_gbps,
                "beam_num": self.requirement.beam_num,
            },
            "antennas": [(s, a["model"], a["name"], a["type"], a["band"])
                         for s, a, _ in self.antennas],
            "equipment": [(e["model"], e["name"], e["cat"]) for e in self.equipment],
            "gaps": self.gaps,
            "platform": self.platform["model"] if self.platform else None,
            "platform_rejected": self.platform_rejected,
            "launcher": self.launcher["name"] if self.launcher else None,
            "payload_mass_est": self.payload_mass_est,
            "payload_power_est": self.payload_power_est,
            "sat_mass_est": self.sat_mass_est,
            "feasible": self.feasible,
            "iteration": self.iteration,
            "warnings": self.warnings,
        }


# ============================================================
# 选型引擎
# ============================================================

class SelectionEngine:
    """三级选型引擎

    通信载荷: 天线五维选型 → 单机货架组链 → 平台 → 运载（含可行性回环）
    非通信载荷: 载荷单机选型（分辨率/幅宽 或 信号体制/灵敏度） → 平台 → 运载
    """

    def __init__(self):
        self.antenna_selector = AntennaSelector()
        self.equipment_selector = EquipmentSelector()
        self.noncomm_selector = NonCommSelector()
        self.platform_selector = PlatformSelector()
        self.launcher_selector = LauncherSelector()

    def run(self, intent: IntentResult, max_iter: int = 3,
            exclude_models: Optional[List[str]] = None) -> SelectionPlan:
        """三级选型 + 可行性回环

        回环逻辑（对应业务流程"校核不通过 → 调天线/体制 → 重跑选型"）:
          第 N 次迭代取评分第 N 的天线候选，估算载荷包络后选平台；
          若无可行平台（载荷超所有同轨道平台能力），换下一候选天线重试；
          候选耗尽仍不可行则标记 feasible=False，交上层 L3 处置。

        exclude_models: 外层链路（链路余量回环）否决过的天线型号，不再参与评分。
        """
        req = SelectionRequirement.from_intent(intent)
        plan = SelectionPlan(requirement=req, payload_type=intent.payload_type)

        # 非通信载荷走独立分支（天线五维判据不适用）
        if intent.payload_type != "communication":
            return self._run_noncomm(intent, req, plan, max_iter)

        ant_candidates = self.antenna_selector.select(
            req, top_k=max_iter, exclude_models=exclude_models)
        plan.architecture = ARCH_TEMPLATES.get(
            req.forwarding_mode, ARCH_TEMPLATES["transparent"])
        if not ant_candidates:
            plan.warnings.append("无匹配天线货架产品，需定制或放宽频段/指标约束")

        # 迭代次数 = min(max_iter, 天线候选数)，候选耗尽即止（重复试同一天线无意义）
        n_iter = max(1, min(max_iter, len(ant_candidates) if ant_candidates else 1))

        for it in range(n_iter):
            plan.iteration = it + 1
            # 当前首选 = ant_candidates[it]，后续候选保留供人工比对
            plan.antennas = ant_candidates[it:] if ant_candidates else []

            # 单机选型（与天线候选无关，循环内执行保证状态一致）
            plan.equipment, plan.gaps = self.equipment_selector.select(intent, req)
            plan.equipment_mass, plan.equipment_power = \
                self.equipment_selector.totals(plan.equipment)

            # 载荷包络估算（含裕度）
            ant = plan.antenna
            ant_mass = ant["mass_kg"] if ant else 0.0
            ant_power = ant["power_w"] if ant else 0.0
            plan.payload_mass_est = round((ant_mass + plan.equipment_mass) * (1 + MARGIN), 1)
            plan.payload_power_est = round((ant_power + plan.equipment_power) * (1 + MARGIN), 0)

            # 平台选型（含可行性预筛）
            plan.platforms, plan.platform_rejected = self.platform_selector.select(
                plan.payload_mass_est, plan.payload_power_est, req.orbit, req.life_years)

            if plan.platforms:
                plan.feasible = True
                plan.sat_mass_est = round(plan.platforms[0][0]["sat_mass_kg"], 0)
                if it > 0:
                    plan.warnings.append(
                        f"校核回环：首选天线 {ant_candidates[0][1]['model']} 载荷超平台能力，"
                        f"第 {it + 1} 次迭代改选 {ant['model'] if ant else '次选天线'} 后平台可行")
                break

            # 无可行平台 → 进入下一次迭代换天线
            plan.feasible = False
            plan.sat_mass_est = round(plan.payload_mass_est * 3, 0)

        # 回环结束仍不可行：给出处置建议
        if not plan.feasible:
            plan.warnings.append(
                f"{req.orbit} 轨道无平台可承载 {plan.payload_mass_est:.0f} kg / "
                f"{plan.payload_power_est:.0f} W 载荷；"
                f"建议：① 拆分载荷多星部署 ② 改换轨道 ③ 定制大平台（L3 人工决策）")

        self._finalize(plan, req)
        logger.info(
            f"选型完成(迭代{plan.iteration}次): 天线={plan.antenna['model'] if plan.antenna else '无'}, "
            f"单机={len(plan.equipment)}台+定制缺口{len(plan.gaps)}项, "
            f"载荷={plan.payload_mass_est}kg/{plan.payload_power_est}W, "
            f"平台={plan.platform['model'] if plan.platform else '无'}, "
            f"运载={plan.launcher['name'] if plan.launcher else '无'}, "
            f"可行性={'通过' if plan.feasible else '未通过'}, 告警={len(plan.warnings)}")
        return plan

    def _run_noncomm(self, intent: IntentResult, req: SelectionRequirement,
                     plan: SelectionPlan, max_iter: int = 3) -> SelectionPlan:
        """非通信载荷选型分支（遥感/导航/科学）

        与通信分支的差异:
          - 不用天线五维（EIRP/G/T）判据，改用分辨率/幅宽 或 信号体制/灵敏度
          - 不做转发体制架构规划（无转发链路）
          - 同样走"载荷包络 → 平台可行性 → 运载"校核回环
        """
        items, gaps = self.noncomm_selector.select(intent, req, top_k=max_iter)
        plan.noncomm_items = items
        plan.gaps = gaps
        if not items:
            plan.warnings.append("产品库无该载荷类型货架品，需定制研制")

        n_iter = max(1, min(max_iter, len(items) if items else 1))
        for it in range(n_iter):
            plan.iteration = it + 1
            plan.noncomm_items = items[it:] if items else []
            top = plan.noncomm_top
            core_mass = top.get("mass_kg", 0.0) if top else 0.0
            core_power = top.get("power_w", 0.0) if top else 0.0
            # 数传/测控等公用单机按经验占比附加
            plan.equipment_mass = round(core_mass * 0.25, 1)
            plan.equipment_power = round(core_power * 0.30, 1)
            plan.payload_mass_est = round((core_mass + plan.equipment_mass) * (1 + MARGIN), 1)
            plan.payload_power_est = round((core_power + plan.equipment_power) * (1 + MARGIN), 0)

            plan.platforms, plan.platform_rejected = self.platform_selector.select(
                plan.payload_mass_est, plan.payload_power_est, req.orbit, req.life_years)
            if plan.platforms:
                plan.feasible = True
                plan.sat_mass_est = round(plan.platforms[0][0]["sat_mass_kg"], 0)
                if it > 0:
                    plan.warnings.append(
                        f"校核回环：首选 {items[0][1]['model']} 超平台能力，"
                        f"第 {it + 1} 次迭代改选 {top['model'] if top else '次选'} 后平台可行")
                break
            plan.feasible = False
            plan.sat_mass_est = round(plan.payload_mass_est * 3, 0)

        if not plan.feasible:
            plan.warnings.append(
                f"{req.orbit} 轨道无平台可承载 {plan.payload_mass_est:.0f} kg / "
                f"{plan.payload_power_est:.0f} W 载荷；"
                f"建议：① 降低分辨率/幅宽要求 ② 拆分多星部署 ③ 定制平台（L3 人工决策）")

        self._finalize(plan, req)
        logger.info(
            f"[非通信] 选型完成(迭代{plan.iteration}次): 类型={intent.payload_type}, "
            f"首选={plan.noncomm_top['model'] if plan.noncomm_top else '无'}, "
            f"载荷={plan.payload_mass_est}kg/{plan.payload_power_est}W, "
            f"平台={plan.platform['model'] if plan.platform else '无'}, "
            f"可行性={'通过' if plan.feasible else '未通过'}")
        return plan

    def _finalize(self, plan: SelectionPlan, req: SelectionRequirement) -> None:
        """公共收尾：用户约束二次校核 + 运载选型"""
        if req.mass_budget_kg is not None and plan.payload_mass_est > req.mass_budget_kg:
            plan.warnings.append(
                f"载荷质量 {plan.payload_mass_est:.0f} kg 超用户约束 {req.mass_budget_kg:.0f} kg，"
                f"建议轻量化设计或放宽约束")
        if req.power_budget_w is not None and plan.payload_power_est > req.power_budget_w:
            plan.warnings.append(
                f"载荷功耗 {plan.payload_power_est:.0f} W 超用户约束 {req.power_budget_w:.0f} W，"
                f"建议改 MPA 功率池或提高功放效率")

        envelope = plan.platforms[0][0].get("envelope_m") if plan.platforms else None
        plan.launchers = self.launcher_selector.select(
            plan.sat_mass_est, req.orbit, sat_envelope_m=envelope)
        if not plan.launchers:
            plan.warnings.append("无匹配运载火箭，需评估减重或拆分发射")


if __name__ == "__main__":
    from .intent import KeywordIntentParser
    cases = [
        "设计GEO Ka频段高通量通信载荷，EIRP≥62dBW，G/T≥12，48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年",
        "设计LEO L波段手机直连星座载荷，12米伞天线，EIRP≥48dBW，寿命7年，要批产",
    ]
    p = KeywordIntentParser()
    eng = SelectionEngine()
    for c in cases:
        it = p.parse(c)
        pl = eng.run(it)
        print("\n" + "=" * 70)
        print(f"需求: {c}\n意图: {it.summary()}\n")
        print(pl.requirement_markdown())
        print()
        print(pl.antenna_markdown())
        print()
        print(pl.equipment_markdown())
        print()
        print(pl.platform_markdown())
        print()
        print(pl.launcher_markdown())
        print()
        print(pl.summary_markdown())
