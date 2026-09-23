"""链路预算与指标校核 (SK-BUDGET / SK-VALID)

校核是流程的闸门：C/N 余量 < 3 dB 即判不通过，触发回环调整。
所有计算为确定性公式，可复现、可审计。

参考: ITU-R S.1528、ECSS-E-ST-50-05C
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 玻尔兹曼常数 dBJ/K
K_BOLTZMANN_DB = -228.6
# 光速 m/s
C_LIGHT = 2.99792458e8

# 链路余量门槛（工程惯例：≥3 dB）
MARGIN_THRESHOLD_DB = 3.0


# ============================================================
# 基础公式
# ============================================================

def free_space_loss_db(freq_ghz: float, distance_km: float) -> float:
    """自由空间损耗 FSPL = 20lg(d) + 20lg(f) − 147.55  (d:m, f:Hz)"""
    if freq_ghz <= 0 or distance_km <= 0:
        raise ValueError("频率与距离必须为正")
    d_m = distance_km * 1e3
    f_hz = freq_ghz * 1e9
    return 20 * math.log10(d_m) + 20 * math.log10(f_hz) - 147.55


def antenna_gain_db(diameter_m: float, freq_ghz: float, efficiency: float = 0.6) -> float:
    """反射面天线增益 G = 10lg(η·(πD/λ)²)"""
    if diameter_m <= 0 or freq_ghz <= 0:
        raise ValueError("口径与频率必须为正")
    wavelength = C_LIGHT / (freq_ghz * 1e9)
    return 10 * math.log10(efficiency * (math.pi * diameter_m / wavelength) ** 2)


def array_gain_db(elements: int, element_gain_dbi: float = 6.0,
                  efficiency: float = 0.7) -> float:
    """相控阵增益 G = 10lg(N·η) + 单元增益（忽略扫描损耗时）"""
    if elements <= 0:
        raise ValueError("阵元数必须为正")
    return 10 * math.log10(elements * efficiency) + element_gain_dbi


def rain_attenuation_db(band: str, elevation_deg: float = 30.0,
                        availability: float = 99.9) -> float:
    """按频段、仰角与可用性估算雨衰 (dB)

    基准值取自温带雨区、仰角 30°、0.01% 时间超越概率（即 99.99% 可用性）。
    可用性换算按 A(p) ∝ p^-0.6：可用性要求越低（p 越大），所需余量越小。
    仰角修正按 1/sin(el) 归一到 30°：仰角越低穿越雨层路径越长。
    """
    # 0.01% 时间超越概率、30° 仰角的基准雨衰
    base_001 = {"L": 0.3, "S": 0.4, "C": 1.0, "X": 2.0, "Ku": 5.0,
                "Ka": 12.0, "Q": 20.0, "V": 28.0, "激光": 0.0}
    v = base_001.get(band, 2.0)
    if v == 0.0:
        return 0.0
    # 仰角修正（归一到 30°）
    if 0 < elevation_deg < 90:
        v *= math.sin(math.radians(30.0)) / max(math.sin(math.radians(elevation_deg)), 0.15)
    # 可用性修正：p = (100 - availability)/100，基准 p0 = 0.0001
    p = max(1e-6, (100.0 - availability) / 100.0)
    v *= (p / 0.0001) ** -0.6
    return round(v, 2)


def capacity_gbps(beam_num: int, bandwidth_mhz: float,
                  spectral_eff: float = 4.0, reuse_factor: float = 1.0) -> float:
    """容量 = 波束数 × 带宽 × 频谱效率 × 频率复用增益"""
    return round(beam_num * (bandwidth_mhz / 1000.0) * spectral_eff * reuse_factor, 2)


# ============================================================
# 链路预算
# ============================================================

@dataclass
class LinkBudget:
    """单条链路的预算结果

    auto_modcod=True 时不预设解调门限，而由算得的 C/N 反推可用调制体制并给出
    链路可达容量 —— 这是链路设计的正确方向：先有 C/N，再定体制与容量。
    """
    direction: str                 # uplink / downlink / inter-satellite
    band: str
    freq_ghz: float
    distance_km: float
    eirp_dbw: float
    gt_dbk: float
    bandwidth_mhz: float
    auto_modcod: bool = True       # 由 C/N 反推调制体制
    fspl_db: float = 0.0
    rain_db: float = 0.0
    pointing_db: float = 0.3       # 指向损耗
    polarization_db: float = 0.3   # 极化失配损耗
    atmospheric_db: float = 0.1    # 大气吸收
    implementation_db: float = 1.0 # 实现损耗
    cn0_dbhz: float = 0.0
    cn_db: float = 0.0
    cn_required_db: float = 10.0   # 解调门限（auto_modcod 时由体制阶梯选定）
    margin_db: float = 0.0
    modcod: str = ""               # 选定调制编码体制
    spectral_eff: float = 0.0      # 频谱效率 bps/Hz
    capacity_mbps: float = 0.0     # 该链路可达容量
    passed: bool = False
    breakdown: List[str] = field(default_factory=list)

    def compute(self) -> "LinkBudget":
        """执行链路预算计算"""
        self.fspl_db = free_space_loss_db(self.freq_ghz, self.distance_km)
        # C/N0 = EIRP − FSPL − 各类损耗 + G/T − k
        losses = (self.rain_db + self.pointing_db + self.polarization_db
                  + self.atmospheric_db + self.implementation_db)
        self.cn0_dbhz = (self.eirp_dbw - self.fspl_db - losses
                         + self.gt_dbk - K_BOLTZMANN_DB)
        self.cn_db = self.cn0_dbhz - 10 * math.log10(self.bandwidth_mhz * 1e6)

        if not self.modcod:
            # 由 C/N 反推体制与容量（激光链路用固定 DPSK 体制）
            self.modcod, self.spectral_eff, self.cn_required_db = select_modcod(self.cn_db)

        self.margin_db = self.cn_db - self.cn_required_db
        self.passed = self.margin_db >= MARGIN_THRESHOLD_DB
        self.capacity_mbps = round(self.bandwidth_mhz * self.spectral_eff, 1)

        self.breakdown = [
            f"EIRP                    {self.eirp_dbw:+8.2f} dBW",
            f"− 自由空间损耗 FSPL      {self.fspl_db:8.2f} dB   "
            f"(f={self.freq_ghz:g} GHz, d={self.distance_km:g} km)",
            f"− 雨衰                  {self.rain_db:8.2f} dB   ({self.band} 频段)",
            f"− 指向损耗              {self.pointing_db:8.2f} dB",
            f"− 极化失配              {self.polarization_db:8.2f} dB",
            f"− 大气吸收              {self.atmospheric_db:8.2f} dB",
            f"− 实现损耗              {self.implementation_db:8.2f} dB",
            f"+ G/T                   {self.gt_dbk:+8.2f} dB/K",
            f"− k (玻尔兹曼)          {K_BOLTZMANN_DB:8.2f} dBJ/K",
            f"= C/N0                  {self.cn0_dbhz:8.2f} dBHz",
            f"− 10lg(B) B={self.bandwidth_mhz:g} MHz "
            f"{' ' * max(0, 22 - len(f'{self.bandwidth_mhz:g}'))}"
            f"{10 * math.log10(self.bandwidth_mhz * 1e6):8.2f} dB",
            f"= C/N                   {self.cn_db:8.2f} dB",
            f"→ 自适应体制            {self.modcod}  "
            f"(η={self.spectral_eff:.2f} bps/Hz, 门限 {self.cn_required_db:.1f} dB)",
            f"= 链路余量              {self.margin_db:8.2f} dB   "
            f"(门槛 {MARGIN_THRESHOLD_DB:g} dB → {'✅ 通过' if self.passed else '❌ 不通过'})",
            f"= 链路容量              {self.capacity_mbps:8.1f} Mbps",
        ]
        return self

    def to_dict(self) -> dict:
        return {
            "direction": self.direction, "band": self.band,
            "freq_ghz": self.freq_ghz, "distance_km": self.distance_km,
            "eirp_dbw": self.eirp_dbw, "gt_dbk": self.gt_dbk,
            "bandwidth_mhz": self.bandwidth_mhz,
            "fspl_db": round(self.fspl_db, 2), "rain_db": self.rain_db,
            "cn0_dbhz": round(self.cn0_dbhz, 2), "cn_db": round(self.cn_db, 2),
            "modcod": self.modcod, "spectral_eff": self.spectral_eff,
            "cn_required_db": self.cn_required_db,
            "margin_db": round(self.margin_db, 2),
            "capacity_mbps": self.capacity_mbps, "passed": self.passed,
        }

    def markdown(self) -> str:
        return "\n".join([f"**{self.direction}（{self.band} 频段）**", "",
                          "```", *self.breakdown, "```"])


# 解调门限参考值（按调制体制，BER=1e-6 / FEC 后准无误码）
CN_REQUIRED = {
    "QPSK": 10.0, "8PSK": 13.5, "16APSK": 16.0, "32APSK": 19.0,
    "QPSK_DVBS2X": 5.5, "8PSK_DVBS2X": 9.0, "16APSK_DVBS2X": 12.0,
    "32APSK_DVBS2X": 15.5, "BPSK": 9.6, "DPSK_激光": 8.0,
}

# 体制 → (频谱效率 bps/Hz, C/N 门限 dB)，按频谱效率降序用于自适应选体制
MODCOD_LADDER: List[tuple] = [
    ("32APSK_DVBS2X", 4.45, 15.5),
    ("16APSK_DVBS2X", 3.70, 12.0),
    ("8PSK_DVBS2X",   2.85, 9.0),
    ("QPSK_DVBS2X",   1.79, 5.5),
]


def select_modcod(cn_db: float, margin_db: float = MARGIN_THRESHOLD_DB) -> tuple:
    """由实际 C/N 反推可用调制编码体制（满足余量门槛的最高阶）

    这是链路设计的正确方向：先有 C/N，再定体制与容量，
    而非先锁高阶体制再看链路是否闭合。
    """
    for name, eff, thr in MODCOD_LADDER:
        if cn_db - thr >= margin_db:
            return name, eff, thr
    # 全部不满足：返回最低阶，标记不可行
    name, eff, thr = MODCOD_LADDER[-1]
    return name, eff, thr


def orbit_distance_km(orbit: str, elevation_deg: float = 10.0) -> float:
    """按轨道与最小仰角估算星地斜距"""
    alt = {"GEO": 35786.0, "MEO": 21500.0, "LEO": 600.0, "SSO": 700.0, "HEO": 20000.0}
    h = alt.get(orbit.upper(), 600.0)
    r_e = 6371.0
    # 斜距 = sqrt((Re+h)^2 - (Re*cos(el))^2) - Re*sin(el)
    el = math.radians(elevation_deg)
    val = (r_e + h) ** 2 - (r_e * math.cos(el)) ** 2
    if val < 0:
        return h
    return round(math.sqrt(val) - r_e * math.sin(el), 1)


# ============================================================
# 校核工具 (SK-VALID)
# ============================================================

@dataclass
class ValidationResult:
    """方案三重校验结果：语法 / 语义 / 合规"""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: List[Dict[str, object]] = field(default_factory=list)

    def add(self, category: str, item: str, passed: bool,
            detail: str = "", level: str = "error") -> None:
        self.checks.append({"category": category, "item": item,
                            "passed": passed, "detail": detail})
        if not passed:
            if level == "error":
                self.errors.append(f"[{category}] {item}：{detail}")
                self.valid = False
            else:
                self.warnings.append(f"[{category}] {item}：{detail}")

    def markdown(self) -> str:
        out = ["### 方案三重校验", "",
               "| 类别 | 校核项 | 结果 | 说明 |", "|------|--------|------|------|"]
        for c in self.checks:
            out.append(f"| {c['category']} | {c['item']} | "
                       f"{'✅ 通过' if c['passed'] else '❌ 不通过'} | {c['detail']} |")
        out += ["", f"**校验结论**：{'✅ 通过' if self.valid else '❌ 不通过'}"]
        if self.errors:
            out += ["", "**阻断项（须回环调整）：**", ""] + [f"- {e}" for e in self.errors]
        if self.warnings:
            out += ["", "**告警项：**", ""] + [f"- {w}" for w in self.warnings]
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": self.errors,
                "warnings": self.warnings, "checks": self.checks}


def validate_scheme(plan, budgets: List[LinkBudget], intent) -> ValidationResult:
    """对选型方案与链路预算做三重校验

    语法校验: 文档要素完整性（章节/表格/单位）
    语义校验: 指标一致性（EIRP/G/T 满足需求、质量功耗在平台内）
    合规校验: 硬性工程规范（C/N 余量 ≥3dB、频段-产品匹配、无频段错配）
    """
    v = ValidationResult()
    req = plan.requirement

    # ---------- 语法校验 ----------
    v.add("语法", "天线/载荷选型结果非空",
          bool(plan.antenna or plan.noncomm_items),
          "已选出首选载荷产品" if (plan.antenna or plan.noncomm_items) else "选型结果为空")
    v.add("语法", "平台选型结果非空", plan.platform is not None,
          f"首选平台 {plan.platform['model']}" if plan.platform else "无可行平台")
    v.add("语法", "运载选型结果非空", bool(plan.launchers),
          f"首选运载 {plan.launcher['name']}" if plan.launcher else "无可行运载")

    # ---------- 语义校验 ----------
    if plan.antenna:
        v.add("语义", "天线 EIRP 能力 ≥ 需求",
              plan.antenna["eirp_cap_dbw"] >= req.eirp_dbw,
              f"能力 {plan.antenna['eirp_cap_dbw']:.0f} dBW vs 需求 {req.eirp_dbw:.0f} dBW")
        v.add("语义", "天线 G/T ≥ 需求",
              plan.antenna["gt_dbk"] >= req.gt_dbk,
              f"能力 {plan.antenna['gt_dbk']:.1f} dB/K vs 需求 {req.gt_dbk:.1f} dB/K")
        v.add("语义", "工作模式匹配",
              any(req.mode in m for m in plan.antenna["modes"]),
              f"需求 {req.mode}，具备 {'/'.join(plan.antenna['modes'])}")

    if plan.platform:
        v.add("语义", "载荷质量 ≤ 平台承载",
              plan.payload_mass_est <= plan.platform["payload_mass_kg"],
              f"{plan.payload_mass_est:.0f} kg vs {plan.platform['payload_mass_kg']:.0f} kg"
              f"（利用率 {plan.payload_mass_est / plan.platform['payload_mass_kg'] * 100:.0f}%）")
        v.add("语义", "载荷功耗 ≤ 平台供电",
              plan.payload_power_est <= plan.platform["payload_power_w"],
              f"{plan.payload_power_est:.0f} W vs {plan.platform['payload_power_w']:.0f} W"
              f"（利用率 {plan.payload_power_est / plan.platform['payload_power_w'] * 100:.0f}%）",
              level="error")
        # 利用率过高提示裕度风险（告警级）
        util = plan.payload_mass_est / plan.platform["payload_mass_kg"]
        v.add("语义", "平台承载裕度 ≥ 10%", util <= 0.9,
              f"利用率 {util * 100:.0f}%" + ("，裕度不足需评估校核" if util > 0.9 else ""),
              level="warning")

    if req.life_years and plan.platform:
        v.add("语义", "平台寿命 ≥ 任务寿命",
              plan.platform["life_years"] >= req.life_years,
              f"{plan.platform['life_years']} 年 vs 需求 {req.life_years:.0f} 年",
              level="warning")

    # 用户显式约束
    if req.mass_budget_kg is not None:
        v.add("语义", "载荷质量 ≤ 用户约束",
              plan.payload_mass_est <= req.mass_budget_kg,
              f"{plan.payload_mass_est:.0f} kg vs 约束 {req.mass_budget_kg:.0f} kg")
    if req.power_budget_w is not None:
        v.add("语义", "载荷功耗 ≤ 用户约束",
              plan.payload_power_est <= req.power_budget_w,
              f"{plan.payload_power_est:.0f} W vs 约束 {req.power_budget_w:.0f} W")

    # ---------- 合规校验 ----------
    # 频段一致性：业务链路单机频段必须覆盖任务频段（防 L 波段配 Ka 变频器）。
    # 测控/信标（TTC/BCN）按标准固定工作在 S 波段，与业务频段无关，予以豁免。
    BAND_EXEMPT_CATS = {"TTC", "BCN"}
    if plan.is_comm and req.bands:
        rf_bands = [b for b in req.bands if b != "激光"]
        mismatched = []
        for e in plan.equipment:
            if e.get("cat") in BAND_EXEMPT_CATS:
                continue
            eb = e.get("band", "")
            if "全频段" in eb:
                continue
            if rf_bands and not any(b.lower() in eb.lower() for b in rf_bands):
                mismatched.append(f"{e['model']}({eb})")
        v.add("合规", "业务链路单机频段与任务频段一致", not mismatched,
              "全部业务单机频段匹配（测控/信标按标准固定 S 波段）"
              if not mismatched else f"频段错配：{', '.join(mismatched)}")

    # 链路余量
    for lb in budgets:
        v.add("合规", f"{lb.direction} C/N 余量 ≥ {MARGIN_THRESHOLD_DB:g} dB",
              lb.passed,
              f"余量 {lb.margin_db:.2f} dB（C/N {lb.cn_db:.2f} dB，门限 {lb.cn_required_db:.1f} dB）")

    # 货架优先合规：统计定制缺口
    if plan.gaps:
        v.add("合规", "单机全部为货架产品", False,
              f"{len(plan.gaps)} 项定制缺口：" + "、".join(g["need"] for g in plan.gaps),
              level="warning")
    else:
        v.add("合规", "单机全部为货架产品", True, "无定制缺口，符合货架优先原则")

    # 平台可行性（L3 级：不可行直接判失败）
    v.add("合规", "平台/运载可行性", plan.feasible,
          "三级选型闭环可行" if plan.feasible else "载荷包络超所有同轨道平台能力")

    return v


# ============================================================
# 全链路预算编排
# ============================================================

def build_link_budgets(plan, intent, elevation_deg: float = 20.0,
                       availability: float = 99.9) -> List[LinkBudget]:
    """按选型结果自动生成上/下行链路预算（体制由 C/N 自适应选定）

    非通信载荷（遥感/导航/科学）按数传链路校核。
    """
    req = plan.requirement
    budgets: List[LinkBudget] = []

    if plan.is_comm and plan.antenna:
        ant = plan.antenna
        rf_bands = [b for b in req.bands if b != "激光"] or ["Ku"]
        from .catalog import FREQUENCY_BANDS
        # 单波束带宽：多波束按 250 MHz 波束带宽，单波束按转发器 36 MHz
        bw_mhz = 250.0 if (req.beam_num or 0) > 1 else 36.0
        dist = orbit_distance_km(req.orbit, elevation_deg)
        for b in rf_bands:
            fb = FREQUENCY_BANDS.get(b, {"up": 14.0, "down": 12.0})
            rain = rain_attenuation_db(b, elevation_deg, availability)
            # 上行：关口站 EIRP 高、星上 G/T 由天线决定
            budgets.append(LinkBudget(
                direction=f"上行链路 {b}", band=b, freq_ghz=fb["up"], distance_km=dist,
                eirp_dbw=75.0 if req.orbit == "GEO" else 65.0,
                gt_dbk=ant["gt_dbk"], bandwidth_mhz=bw_mhz,
                rain_db=rain * 0.6).compute())
            # 下行：星上 EIRP 由天线能力决定、地面站 G/T 取典型关口站值
            budgets.append(LinkBudget(
                direction=f"下行链路 {b}", band=b, freq_ghz=fb["down"], distance_km=dist,
                eirp_dbw=ant["eirp_cap_dbw"],
                gt_dbk=30.0 if req.orbit == "GEO" else 15.0,
                bandwidth_mhz=bw_mhz,
                rain_db=rain).compute())
        # 星间激光链路（固定 DPSK 体制，不走自适应阶梯）
        if "激光" in req.bands:
            budgets.append(LinkBudget(
                direction="星间激光链路", band="激光", freq_ghz=193400.0,
                distance_km=5000.0, eirp_dbw=105.0, gt_dbk=118.0,
                bandwidth_mhz=1000.0, rain_db=0.0, auto_modcod=False,
                modcod="DPSK_激光", spectral_eff=2.0,
                cn_required_db=CN_REQUIRED["DPSK_激光"]).compute())
    elif plan.noncomm_top:
        # 遥感/科学/导航：数传下行链路（X 频段，QPSK 体制）
        it = plan.noncomm_top
        dist = orbit_distance_km(req.orbit, elevation_deg)
        rate_mbps = it.get("data_rate_mbps") or 100.0
        budgets.append(LinkBudget(
            direction="数传下行链路（X 频段）", band="X", freq_ghz=8.0,
            distance_km=dist, eirp_dbw=45.0, gt_dbk=25.0,
            bandwidth_mhz=max(1.0, rate_mbps / 2.0), rain_db=1.0,
            auto_modcod=False, modcod="QPSK", spectral_eff=1.79,
            cn_required_db=CN_REQUIRED["QPSK"]).compute())

    return budgets


def link_budget_markdown(budgets: List[LinkBudget]) -> str:
    if not budgets:
        return "### 链路预算\n\n> 本载荷类型暂无需链路预算校核。"
    out = ["### 链路预算与余量校核",
           f"\n> 判据：C/N 余量 ≥ {MARGIN_THRESHOLD_DB:g} dB；调制体制由 C/N 自适应选定（DVBS2X 阶梯）\n"]
    out += ["| 链路 | 频段 | 频率 | 斜距 | EIRP | G/T | 带宽 | FSPL | 雨衰 | C/N0 | C/N | 体制 | 余量 | 容量 | 结论 |",
            "|------|------|------|------|------|-----|------|------|------|------|-----|------|------|------|------|"]
    for lb in budgets:
        out.append(
            f"| {lb.direction} | {lb.band} | {lb.freq_ghz:g} GHz | {lb.distance_km:g} km | "
            f"{lb.eirp_dbw:.1f} dBW | {lb.gt_dbk:.1f} | {lb.bandwidth_mhz:g} MHz | "
            f"{lb.fspl_db:.1f} dB | {lb.rain_db:.1f} dB | {lb.cn0_dbhz:.1f} dBHz | "
            f"{lb.cn_db:.1f} dB | {lb.modcod} | **{lb.margin_db:+.1f} dB** | "
            f"{lb.capacity_mbps:.0f} Mbps | {'✅' if lb.passed else '❌'} |")
    failed = [lb for lb in budgets if not lb.passed]
    total_cap = sum(lb.capacity_mbps for lb in budgets
                    if lb.direction.startswith("下行") or lb.direction.startswith("数传"))
    out += ["", f"**校核结论**：{len(budgets) - len(failed)}/{len(budgets)} 条链路通过；"
                f"下行总可用容量约 **{total_cap / 1000:.2f} Gbps**"]
    if failed:
        out += ["", "**不通过链路及调整建议（回环输入）：**", ""]
        for lb in failed:
            gap = MARGIN_THRESHOLD_DB - lb.margin_db
            # 体制已是阶梯最低阶，降阶无效 → 只能从 EIRP/G/T/带宽/可用性入手
            if lb.spectral_eff <= MODCOD_LADDER[-1][1]:
                advice = (f"体制已降至最低阶 {lb.modcod}，降阶无效；"
                          f"建议 ① 增大天线口径或阵元数提升 EIRP/G/T（需 {gap + 2:.0f} dB 以上）"
                          f" ② 减小单波束带宽（带宽减半约 +3 dB）"
                          f" ③ 放宽链路可用性要求（99.9%→99.5% 可省约 2-4 dB 雨衰）")
            else:
                advice = (f"建议 ① 降低解调阶数（当前 {lb.modcod}）"
                          f" ② 增大天线口径/功放功率 ③ 减小单波束带宽")
            out.append(f"- ❌ {lb.direction}：余量 {lb.margin_db:+.2f} dB，差 {gap:.2f} dB → {advice}")
    return "\n".join(out)


if __name__ == "__main__":
    from .intent import KeywordIntentParser, build_clarifications
    from .selection import SelectionEngine
    p = KeywordIntentParser()
    e = SelectionEngine()
    cases = [
        "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，48个波束相控阵，DTP柔性体制，容量50Gbps",
        "设计GEO Ku频段透明转发载荷，单波束，EIRP>=52dBW，G/T>=5",
        "设计LEO Ku频段宽带星座载荷，相控阵，EIRP>=45dBW，含激光星间链路",
        "设计SSO太阳同步轨道遥感载荷，空间分辨率优于0.5m，幅宽12km",
    ]
    for c in cases:
        print("\n" + "=" * 78)
        print("需求:", c)
        it = p.parse(c)
        cl = build_clarifications(it)
        if cl:
            print("需澄清:", "; ".join(x["field"] for x in cl))
            continue
        pl = e.run(it)
        budgets = build_link_budgets(pl, it)
        print(link_budget_markdown(budgets))
        print()
        v = validate_scheme(pl, budgets, it)
        print(v.markdown())
