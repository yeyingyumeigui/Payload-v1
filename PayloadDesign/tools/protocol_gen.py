# -*- coding: utf-8 -*-
"""接口标准化与协议自动生成引擎（参考 MOSA 模块化开放系统方法）。

生成链路（与用户流程一致）：
  方案设定(cfg) → 单机选型(equipment rows + diagram) → 接口自动推导(ICD 矩阵)
  → 标准协议规格(CCSDS/ECSS/MIL 帧格式 + 总线参数) → 软件 ICD（供软件开发）

标准化参考体系：
  · MOSA（Modular Open Systems Approach）：模块化 + 开放标准 + 接口解耦 + 关键接口公开
  · FACE（Future Airborne Capability Environment）五层软件参考：
      应用层 / 中间件(可移植服务) / OS 层(POSIX) / I/O 抽象层(IOSS) / 传输层(TSS)
  · ECSS 欧空局标准系列：SpaceWire(ECSS-E-ST-50-12C)、CAN、SpaceFibre、
      电源特性(ECSS-E-ST-30-11)、线束(SAE AS50881)
  · CCSDS 蓝皮书：133.0-B 空间包、132.0-B AOS 帧、232.0-B TC 帧、
      231.0-B CFDP 文件传递、131.0-B TM 帧
  · MIL-STD-1553B / FC-AE-1553（高吞吐星内总线）

输入：design_engine.design_all() 的结果 dict（含 cfg/equipment/diagram/params/res）
输出：ICD dict —— layers/interfaces/bus_standards/frames/channels/power/sw_icd/stats
"""
from __future__ import annotations

import math

# ---------------- 频段 → 射频传输介质/连接器 ----------------
RF_MEDIA = {
    "L":   ("50Ω N 型同轴", "N 型（≤18GHz）", "1.0~2.0"),
    "S":   ("50Ω N 型同轴", "N 型（≤18GHz）", "2.0~4.0"),
    "C":   ("WR-159 波导 / N 型同轴", "波导法兰 CBR159 / N 型", "4.0~8.0"),
    "X":   ("WR-90 波导", "波导法兰 CBR90", "8.0~12.0"),
    "Ku":  ("WR-75 波导（高功率）/ SMA（低功率）", "波导 CBR75 / SMA", "12.0~18.0"),
    "Ka":  ("WR-42 波导（高功率）/ 2.92mm（低功率）", "波导 CBR42 / 2.92mm", "18.0~40.0"),
    "Q/V": ("WR-22 / WR-19 波导", "波导 CBR22 / CBR19", "33.0~75.0"),
}

# ---------------- 频段 → 上/下行频率（GHz，与 design_data.BAND_FREQ 同源） ----------------
BAND_FREQ = {
    "L": (1.6265, 1.525), "S": (2.1, 2.3), "C": (6.0, 4.0), "X": (8.0, 7.5),
    "Ku": (14.0, 12.0), "Ka": (30.0, 20.0), "Q/V": (50.0, 40.0),
}

# ---------------- 数据总线标准库（按速率选型的开放标准） ----------------
BUS_BY_RATE = [
    # (上限Mbps, 总线, 标准, 介质/电气, 连接器, 说明)
    (1,     "CAN 2.0B", "ECSS-E-ST-50 系列（CANbus）",
     "双绞屏蔽 1Mbit/s，差分电平，120Ω 端接", "D-sub 9 / 微矩形",
     "低速控制/遥测遥控/健康采集；多主仲裁；单机级 FDIR 上报"),
    (200,   "SpaceWire", "ECSS-E-ST-50-12C",
     "LVDS（IEEE 1596.3 LVDSP）数据+频闪双对，2~200Mbit/s", "MDM-9（38999 系）9 芯",
     "星内中速数据主干；点对点/路由器组网；DS-TE 虚拟通道；驱动可移植（MOSA I/O 层）"),
    (1062,  "FC-AE-1553（1GFC）", "INCITS T11 FC-AE-1553",
     "850nm 多模光纤 / 铜缆，1.0625Gbaud", "LC / SFF 光连接器",
     "高吞吐载荷数据（DTP↔存储↔数传）；与 1553B 指令语义兼容，平滑升级"),
    (4250,  "FC-AE-1553（4GFC）", "INCITS T11 FC-AE-1553",
     "850/1310nm 光纤，4.25Gbaud", "LC 光连接器",
     "大容量星上数据总线（对应货架 BUS-FCAE 4000Mbps）"),
    (16000, "SpaceFibre", "ECSS-E-ST-50 系列（SpaceFibre）",
     "光纤/铜，78.125Mbit/s~15.625Gbit/s 可配", "光纤 LC / 高密度微矩形",
     "下一代星内高速串行；带宽可扩展；低误码 1e-12；面向批产星座"),
]

# ---------------- 控制总线（遥测遥控/健康） ----------------
CTRL_BUSES = [
    ("MIL-STD-1553B", "MIL-STD-1553B", "屏蔽双绞，1Mbit/s，曼彻斯特 II 双相码",
     "隔离变压器耦合，双冗余总线 A/B", "确定性指令/响应；载荷控制器↔OBC 关键指令链"),
    ("CAN 2.0B", "ECSS-E-ST-50 系列", "双绞屏蔽，1Mbit/s", "D-sub 9",
     "扩展帧 29bit ID；健康数据/FDIR 分布式采集"),
    ("RS-422A", "EIA-422", "差分点对点，≤10Mbit/s", "D-sub / 微矩形",
     "单机点对点控制（ACU/EPC/机构驱动）"),
]

# ---------------- CCSDS 帧格式（字段级，供软件协议栈开发） ----------------
CCSDS_FRAMES = [
    dict(name="CCSDS 空间包（Space Packet）主头", std="CCSDS 133.0-B", size="6 字节",
         fields=[
             ("包版本号", 3, "固定 000（空间包版本 1）"),
             ("包类型", 1, "0=TM 遥测包 / 1=TC 遥控包"),
             ("副头标志", 1, "1=含安全/时间码副头"),
             ("APID 应用过程标识符", 11, "标识业务源/目的（见 APID 分配表）"),
             ("序列标志", 2, "00=段序列 01=首段 10=末段 11=独立包"),
             ("包序列计数", 12, "0~4095 循环，丢包检测"),
             ("包数据长度", 16, "数据场字节数 − 1"),
         ]),
    dict(name="AOS 传输帧主头（星上高速数据）", std="CCSDS 132.0-B", size="6 字节",
         fields=[
             ("帧版本号", 2, "01=AOS 传输帧"),
             ("航天器标识 SCID", 10, "全球唯一星号"),
             ("虚拟信道 VCID", 3, "业务分流（见 VCID 分配表）"),
             ("重放标志", 1, "1=重放帧"),
             ("VCF 计数长度", 3, "VCF 计数字节数"),
             ("保留", 2, "置 0"),
             ("VCF 帧计数", 24, "按虚拟信道递增"),
             ("帧头差错控制", 16, "CRC-16 CCITT（可选）"),
         ]),
    dict(name="TC 传输帧主头（遥控上行）", std="CCSDS 232.0-B", size="5 字节",
         fields=[
             ("帧版本号", 2, "00=TC 传输帧"),
             ("旁路标志", 1, "0=序列 A（完整 COP-1）1=序列 B（ expedited）"),
             ("控制命令标志", 1, "1=直接指令"),
             ("保留", 2, "置 0"),
             ("SCID", 10, "航天器标识"),
             ("VCID", 6, "上行虚拟信道"),
             ("帧长度", 10, "帧总字节数 − 1"),
         ]),
    dict(name="TM 传输帧主头（遥测下行）", std="CCSDS 131.0-B", size="4 字节",
         fields=[
             ("帧版本号", 2, "00=TM"),
             ("SCID", 10, "航天器标识"),
             ("VCID", 3, "下行虚拟信道"),
             ("OCF 标志", 1, "1=含操作控制场"),
             ("主信道帧计数", 8, "0~255 循环"),
             ("虚信道帧计数", 8, "0~255 循环"),
             ("次级头标志/同步标志/包序标志", 3, "见标准"),
             ("帧长", 11, "帧总字节数 − 1"),
         ]),
    dict(name="CFDP 文件传递（星载大数据/软件上注）", std="CCSDS 231.0-B", size="PDU 可变",
         fields=[
             ("版本/方向/传输模式", 8, "1=版本 01；文件存储传输 FDT"),
             ("CRC 标志/大文件标志", 8, "按文件规模选 CRC-32C"),
             ("源/目的实体 ID", "各≤32", "星地实体标识"),
             ("事务序号", "≤64", "断点续传标识"),
             ("文件指令 PDU", "可变", "Put/EOF/Finished/NAK 重传"),
         ]),
]

# ---------------- MOSA/FACE 分层软件参考 ----------------
MOSA_LAYERS = [
    dict(layer="应用层（Application）", std="自定义应用 + CCSDS SLE",
         content="载荷业务应用（波束调度/资源管理/FDIR）、地面 SLE 服务接口",
         mosa="应用与平台解耦：应用只经中间件 API 访问资源，可跨平台移植"),
    dict(layer="中间件/可移植服务层（PSS）", std="CCSDS 133.0-B / 231.0-B、DDS/RTPS",
         content="空间包封装/解包、CFDP 文件服务、消息队列、时间服务（CUC/CDS）",
         mosa="标准服务接口公开（关键接口），第三方应用可即插即用"),
    dict(layer="操作系统层（OS）", std="POSIX 1003.13 / RTEMS / VxWorks / SpaceLinux",
         content="实时调度、内存保护、驱动框架",
         mosa="OS 可替换（开放 POSIX 接口），避免厂商锁定"),
    dict(layer="I/O 抽象层（IOSS）", std="ECSS 总线驱动模型",
         content="SpaceWire/CAN/1553B/FC-AE 驱动统一为设备句柄 API",
         mosa="换总线只换驱动，应用无感知（接口解耦核心）"),
    dict(layer="传输层（TSS）", std="ECSS-E-ST-50 系列、MIL-STD-1553B、FC-AE",
         content="物理链路：LVDS/光纤/双绞、连接器、电气特性",
         mosa="选用公开标准总线，货架单机跨任务复用"),
]


def _to_f(v, d=0.0):
    try:
        x = float(v)
        return d if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return d


def pick_bus(rate_mbps):
    """按需求速率选开放标准总线（MOSA：优先公开标准，速率就近向上）。"""
    rate = _to_f(rate_mbps, 0)
    for cap, bus, std, media, conn, note in BUS_BY_RATE:
        if rate <= cap:
            return dict(bus=bus, std=std, media=media, conn=conn, note=note,
                        rate_mbps=round(rate, 1), cap_mbps=cap)
    last = BUS_BY_RATE[-1]
    return dict(bus=last[1] + "（多链路聚合）", std=last[2], media=last[3],
                conn=last[4], note="超单链路能力 → 多链路捆绑或光交换",
                rate_mbps=round(rate, 1), cap_mbps=last[0] * 4)


def _node_map(R):
    d = R.get("diagram") or {}
    return {nd["id"]: nd for nd in d.get("nodes", [])}, d


def _band_of(label, band, fband):
    """从边标签推断频段（'馈电上行 Q/V'→Q/V；默认用户频段）。"""
    lb = str(label or "")
    if "馈电" in lb:
        return fband or band
    for b in ("Q/V", "Ka", "Ku", "C", "X", "S", "L"):
        if b in lb:
            return b
    return band


def derive_interfaces(R):
    """由载荷框图（diagram.edges）+ 单机清单自动推导接口矩阵（ICD 核心表）。"""
    nodes, d = _node_map(R)
    cfg = R.get("cfg") or {}
    p = R.get("params") or {}
    trp = R.get("transponder") or {}
    band = cfg.get("band", "Ka")
    fband = cfg.get("feeder_band") or band
    freq = BAND_FREQ.get(band, (30.0, 20.0))
    freq_f = BAND_FREQ.get(fband, freq)
    R_bus = _to_f(p.get("R_bus"), 4000)
    C_sw = _to_f(p.get("C_sw"), 100) * 1000     # Gbps → Mbps
    P_out = _to_f(p.get("P_out"), 0)

    rows = []
    idx = 0
    for e in d.get("edges", []):
        kind = e.get("kind", "")
        src = nodes.get(e.get("f"), {})
        dst = nodes.get(e.get("t"), {})
        sid, did = e.get("f", ""), e.get("t", "")
        label = e.get("label", "")
        idx += 1
        base = dict(idx=idx, src_id=sid, src_cn=(src.get("cn") or sid).replace("\n", "/"),
                    dst_id=did, dst_cn=(dst.get("cn") or did).replace("\n", "/"),
                    label=label)
        if kind in ("rf_up", "rf_dn"):
            b = _band_of(label, band, fband)
            fu, fd = (freq_f if b == fband and fband != band else freq)
            f_ghz = fu if kind == "rf_up" else fd
            media, conn, span = RF_MEDIA.get(b, RF_MEDIA["Ka"])
            rows.append(dict(base, itype="射频接口", subtype=("上行接收" if kind == "rf_up" else "下行发射"),
                             media=media, conn=conn,
                             param="f=%s GHz（%s 波段 %s）" % (f_ghz, b, span),
                             std="频段规划 ITU RR / GSO 网络资料；接口驻波 VSWR≤1.3:1",
                             electrical="插损≤0.5dB；隔离度≥100dB（环行器）；法兰扭矩按 ECSS-E-ST-70-38"
                                        + ("；功率 %sW/波束（TWTA/SSPA 输出）" % round(P_out, 1)
                                           if kind == "rf_dn" and P_out else ""),
                             note="波导/同轴按频段选型；高功率段用波导降低损耗与击穿风险"))
        elif kind in ("if", "if_"):
            rows.append(dict(base, itype="中频接口", subtype="中频模拟",
                             media="50Ω SMA 同轴（屏蔽）", conn="SMA-KY",
                             param="L 波段 950~2150MHz（G/T 归算点），电平 −30~0dBm",
                             std="DVB-S2X 中频谱模板 / 内部 ICD",
                             electrical="增益平坦度≤1dB；群时延≤5ns；镜像抑制≥60dBc",
                             note="变频前后中频统一 L 波段，便于货架滤波器/均衡器复用"))
        elif kind == "dig":
            rate = max(R_bus, C_sw) if ("交换" in base["src_cn"] or "交换" in base["dst_cn"]) else R_bus
            bus = pick_bus(rate)
            rows.append(dict(base, itype="数据接口", subtype="星内高速数据",
                             media=bus["media"], conn=bus["conn"],
                             param="%s（需求 %s Mbps）" % (bus["bus"], round(rate)),
                             std="%s；承载 CCSDS 133.0-B 空间包 / 132.0-B AOS 帧" % bus["std"],
                             electrical="误码率≤1e-10；时延抖动≤1μs；光链路预算≥6dB",
                             note=bus["note"]))
        elif kind == "opt":
            rows.append(dict(base, itype="光接口", subtype="激光星间/星地",
                             media="单模光纤耦合（1064/1550nm）+ 自由空间光", conn="光纤 FC/APC + 光学窗口",
                             param="%s Gbps（%s）" % (_to_f(cfg.get("isl_r_gbps"), 10), cfg.get("isl_type", "激光")),
                             std="内部 ICD；ATP 捕获跟踪协议（信标+精跟踪）",
                             electrical="发射功率≤1W；接收灵敏度≤−50dBm；指向精度≤1μrad",
                             note="与激光终端（货架 LCT）光机接口对齐；星内电接口用 SpaceFibre/FC-AE"))
        elif kind == "ctrl":
            rows.append(dict(base, itype="控制接口", subtype="指令/健康/FDIR",
                             media="MIL-STD-1553B 双冗余总线（A/B）+ CAN 备份", conn="隔离变压器耦合 / D-sub 9",
                             param="1553B 1Mbit/s；CAN 1Mbit/s；RS-422 点对点",
                             std="MIL-STD-1553B；ECSS CAN；遥控帧 CCSDS 232.0-B",
                             electrical="指令回读校验；总线终端 78Ω；响应超时≤RT 周期",
                             note="控制面与数据面物理隔离（MOSA 接口解耦）"))
        else:
            rows.append(dict(base, itype="其他", subtype=kind, media="—", conn="—",
                             param="—", std="—", electrical="—", note=""))

    # 电源接口（每个单机一条，按清单聚合）
    power = []
    for r in R.get("equipment") or []:
        if _to_f(r.get("power")) <= 0:
            continue
        cat = r.get("cat", "")
        if cat == "功放" and "行波管" in str(r.get("cn", "")):
            power.append(dict(unit=r["id"], cn=r["cn"], qty=r.get("qty", 1),
                              bus="6kV 高压（EPC 调节）+ 28V 灯丝",
                              std="ECSS-E-ST-30-11（高压电源特性）；EPC 过流/过压/拉弧保护",
                              note="TWTA 高压由 EPC 提供，母线→EPC→行波管"))
        else:
            power.append(dict(unit=r["id"], cn=r["cn"], qty=r.get("qty", 1),
                              bus="28V DC 不调节母线（±6%）→ 单机内 DC/DC 二次电源",
                              std="ECSS-E-ST-30-11；线束 SAE AS50881；浪涌按 ECSS-E-ST-20-04",
                              note="单机功耗 %sW × %s" % (round(_to_f(r.get("power")), 1), r.get("qty", 1))))
    return rows, power


def channel_plan(R):
    """APID / VCID 自动分配（供软件协议栈开发，CCSDS 133.0-B/132.0-B）。"""
    rows = R.get("equipment") or []
    # 处理类单机 → APID 段
    proc_cats = ("数字处理", "再生基带", "星务", "测控信标")
    apids, seen = [], set()
    apid = 16
    for r in rows:
        if r.get("cat") not in proc_cats or r["id"] in seen:
            continue
        seen.add(r["id"])
        apids.append(dict(apid=apid, unit=r["id"], cn=r["cn"],
                          svc="遥测/指令/业务数据按 APID 分流"))
        apid += 8
        if apid > 2040:
            break
    apids.append(dict(apid=2047, unit="IDLE", cn="空闲包（填充）", svc="链路空闲填充"))
    vcids = [
        dict(vcid=0, svc="星务遥测（健康/FDIR）", rate="低速", std="TM 帧 CCSDS 131.0-B"),
        dict(vcid=1, svc="载荷业务数据（透明/DTP 子带）", rate="中速", std="AOS 帧 CCSDS 132.0-B"),
        dict(vcid=2, svc="高速数传（再生基带/大容量存储回放）", rate="高速", std="AOS + CFDP CCSDS 231.0-B"),
        dict(vcid=3, svc="遥控上行（地面→星）", rate="低速", std="TC 帧 CCSDS 232.0-B"),
        dict(vcid=4, svc="星间链路业务（激光/微波 ISL）", rate="高速", std="AOS 帧"),
    ]
    return apids, vcids


def sw_icd(R, ifaces):
    """软件开发 ICD：每台处理类单机的协议栈（MOSA 分层落地）。"""
    rows = R.get("equipment") or []
    cfg = R.get("cfg") or {}
    mode = cfg.get("mode", "数字透明")
    sw = []
    for r in rows:
        if r.get("cat") not in ("数字处理", "再生基带", "星务", "测控信标"):
            continue
        stack = ["应用层：载荷业务逻辑（FDIR/调度/波束管理）",
                 "中间件：CCSDS 133.0-B 空间包封装/解包 + 时间服务（CUC）"]
        cat = r.get("cat")
        if cat == "再生基带":
            stack.insert(2, "业务层：物理层编解码（%s）/ 星上路由" % ("DVBS2X ACM" if mode != "透明" else "透明转发"))
            stack.append("链路层：AOS 帧 CCSDS 132.0-B（VCID 分流）+ CFDP 文件服务")
        elif cat == "数字处理":
            stack.append("链路层：子带交换控制面（SpaceWire/FC-AE 驱动，IOSS 抽象）")
        elif cat == "测控信标":
            stack.append("链路层：TC 帧 CCSDS 232.0-B（遥控）/ TM 帧 CCSDS 131.0-B（遥测）")
        else:
            stack.append("链路层：健康采集 CAN/1553B + TM 帧")
        stack.append("OS 层：RTEMS/POSIX（可替换）；传输层：%s" %
                     (ifaces and next((i["param"] for i in ifaces
                                       if i["itype"] == "数据接口"), "FC-AE-1553")))
        sw.append(dict(unit=r["id"], cn=r["cn"], qty=r.get("qty", 1), stack=stack))
    return sw


def mosa_checklist(R):
    """MOSA 符合性检查表（开放架构五要素逐项评估）。"""
    rows = R.get("equipment") or []
    n = max(len(rows), 1)
    lv4 = sum(1 for r in rows if _to_f(r.get("level")) >= 4)
    lv3 = sum(1 for r in rows if _to_f(r.get("level")) == 3)
    shelf_pct = (lv4 + lv3) / n * 100
    return [
        dict(item="模块化（Modularity）",
             eval="单机级模块化 %d 种货架单机；相控阵瓦片化/AiP 组件化" % len(rows),
             score=("满足" if len(rows) >= 8 else "部分"),
             note="货架单机独立封装、功能内聚"),
        dict(item="开放标准（Open Standards）",
             eval="数据面 CCSDS 133.0/132.0/232.0/231.0；总线 ECSS SpaceWire/FC-AE；控制 MIL-STD-1553B",
             score="满足", note="全部接口采用公开标准，无私有协议"),
        dict(item="接口解耦（Interface Decoupling）",
             eval="控制面/数据面/电源面物理分离；I/O 经 IOSS 抽象",
             score="满足", note="换单机只改 ICD 条目，不动系统"),
        dict(item="关键接口公开（Key Interface）",
             eval="本 ICD 矩阵 + APID/VCID 分配 + 帧格式字段级公开",
             score="满足", note="供第三方载荷软件即插即用"),
        dict(item="可替换/可竞争（Substitutability）",
             eval="货架水平 ≥L3 占比 %.0f%%（L4 %d / L3 %d / 共 %d 种）" % (shelf_pct, lv4, lv3, n),
             score=("满足" if shelf_pct >= 60 else "部分"),
             note="同类单机 ≥2 供应商可竞争替换"),
    ]


def generate_icd(R):
    """主入口：design_all 结果 → 完整 ICD/协议规格。"""
    ifaces, power = derive_interfaces(R)
    apids, vcids = channel_plan(R)
    return dict(
        layers=MOSA_LAYERS,
        interfaces=ifaces,
        power=power,
        bus_standards=[dict(bus=b, std=s, media=m, conn=c, note=nn, cap_mbps=cap)
                       for cap, b, s, m, c, nn in BUS_BY_RATE],
        ctrl_buses=[dict(bus=a, std=b, media=c, conn=dd, note=e) for a, b, c, dd, e in CTRL_BUSES],
        frames=CCSDS_FRAMES,
        apids=apids, vcids=vcids,
        sw_icd=sw_icd(R, ifaces),
        mosa=mosa_checklist(R),
        stats=dict(n_if=len(ifaces),
                   n_rf=sum(1 for i in ifaces if i["itype"] == "射频接口"),
                   n_dig=sum(1 for i in ifaces if i["itype"] == "数据接口"),
                   n_ctrl=sum(1 for i in ifaces if i["itype"] == "控制接口"),
                   n_opt=sum(1 for i in ifaces if i["itype"] == "光接口"),
                   n_ifmid=sum(1 for i in ifaces if i["itype"] == "中频接口"),
                   n_power=len(power), n_apid=len(apids), n_vc=len(vcids)),
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
    import design_data as DD
    import design_engine as DE
    import design_app as DA
    r = DE.design_all(dict(DD.DEFAULT_CFG, name="ICD自检", service="高通量宽带",
                           orbit="GEO", coverage="巴基斯坦", band="Ka",
                           feeder_band="Q/V", mode="数字透明", ant_type="固面"),
                      DA.KG, skip_compare=True)
    icd = generate_icd(r)
    print("interfaces:", icd["stats"])
    for i in icd["interfaces"][:8]:
        print(" ", i["idx"], i["src_id"], "->", i["dst_id"], "|", i["itype"], "|", i["param"][:60])
    print("apids:", len(icd["apids"]), "vcids:", len(icd["vcids"]))
