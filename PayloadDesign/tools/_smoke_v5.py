# -*- coding: utf-8 -*-
"""v5 冒烟：protocol / export 完整报告落盘 / beam 二维 / open_file 安全校验。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_data as DD                       # noqa: E402
import design_app as DA                        # noqa: E402

ok = fail = 0


def chk(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK] %s %s" % (name, extra))
    else:
        fail += 1
        print("  [FAIL] %s %s" % (name, extra))


api = DA.Api()

# ---- 1. protocol ----
print("== 1. /api/protocol（MOSA ICD 自动生成） ==")
for scen_key in list(DD.SCENARIOS.keys())[:3]:
    cfg = dict(DD.SCENARIOS[scen_key]["cfg"])
    r = api.protocol({"cfg": cfg})
    chk("protocol[%s]" % scen_key, r.get("ok") and r["result"]["stats"]["n_if"] > 0,
        "ifaces=%s" % (r.get("result", {}).get("stats", {}) if r.get("ok") else r.get("error")))
    if r.get("ok"):
        icd = r["result"]
        chk("  icd keys[%s]" % scen_key,
            all(k in icd for k in ("layers", "interfaces", "power", "bus_standards",
                                   "ctrl_buses", "frames", "apids", "vcids", "sw_icd",
                                   "mosa", "stats")))

# ---- 2. export 完整报告（落盘） ----
print("== 2. /api/export（完整报告 → 落盘 output/） ==")
cfg = dict(DD.SCENARIOS[list(DD.SCENARIOS.keys())[0]]["cfg"])
r = api.export_html({"cfg": cfg, "name": "冒烟测试方案"})
chk("export ok", r.get("ok") is True, r.get("error", ""))
chk("export chars", (r.get("chars") or 0) > 100000, "%s chars" % r.get("chars"))
fp = r.get("file_path") or ""
chk("export file_path", bool(fp) and os.path.exists(fp), fp)
if fp and os.path.exists(fp):
    html = open(fp, encoding="utf-8").read()
    for kw in ("目&nbsp;&nbsp;录", "项目概述与需求分析", "设计原理与方法论", "总体方案", "天线与波束性能",
               "链路预算", "单机选型", "接口与协议", "约束校验", "星座组网与多覆盖区", "附录",
               "地面 EIRP 覆盖分析", "轨道覆盖仿真", "ProgId", "WordSection1", "skill"):
        chk("  报告含[%s]" % kw, kw in html)
    # 项目论证报告版式（封面 / 摘要 / 题注）
    chk("  报告含封面", 'class="cover"' in html and "方案论证报告" in html)
    chk("  报告含封面评级徽章", "cover-grade" in html and "方案评级" in html)
    chk("  报告含摘要", "摘&nbsp;&nbsp;要" in html and "可行性结论" in html)
    chk("  报告含图题注", 'class="figcap"' in html and "图 2-1" in html)
    chk("  报告含表题注", 'class="tabcap"' in html and "表 2-1" in html)
    chk("  报告含章导语", 'class="lead"' in html)
    chk("  报告含第一性原理公式表", "第一性原理公式体系" in html and "Friis" in html)
    chk("  报告含封面/摘要分页", "page-break-after:always" in html)
    chk("  报告含架构图节点", "载荷组成架构图" in html)
    # 注：方向图标题文字在 SVG 内，光栅化后转入 PNG → 改查 HTML 层小节标题
    chk("  报告含波束方向图节", "4.3 波束方向图" in html)
    chk("  报告含三维地球", ("三维覆盖示意图" in html) and ("单星视域" in html))
    chk("  报告含 ICD 矩阵", "接口矩阵" in html)
    chk("  报告含 MOSA", "MOSA" in html)
    chk("  报告含 CCSDS", "CCSDS" in html)
    # v5 新增：评价标准章节 + 新增框架图 + SVG 全部光栅化为 PNG（Word 可显示）
    chk("  报告含评价章节", "方案评价标准与可行性结论" in html)
    chk("  报告含十项准则", "十项评价准则逐项判定" in html)
    chk("  报告含雷达图", "六维评分雷达图" in html)
    chk("  报告含信息流框架图", "载荷信息流框架图" in html)
    chk("  报告含功能框架图", "载荷功能框架图" in html)
    chk("  报告含链路原理图", "端到端链路原理图" in html)
    chk("  报告含频率规划图", "频率规划与复用示意图" in html)
    # 三引擎章节（#63）：方向图 grid/cut + EIRP 覆盖 + 轨道仿真
    chk("  报告含次级方向图节", "4.4 天线次级方向图" in html)
    chk("  报告含栅瓣核查节", "栅瓣核查" in html)
    chk("  报告含 EIRP 覆盖节", "11.1 地面 EIRP 覆盖投影" in html)
    chk("  报告含覆盖足迹度量", "11.2 覆盖足迹度量" in html)
    chk("  报告含轨道轨迹节", "12.1 星下点轨迹与瞬时覆盖" in html)
    chk("  报告含轨道快照节", "12.2 指定时刻覆盖快照" in html)
    chk("  报告含可见窗评估节", "12.3 24h 可见窗与轨道合理性评估" in html)
    chk("  报告含 STK 导出说明", "STK Ephemeris" in html)
    chk("  报告含 GRASP 导出说明", ".grd" in html or "grd" in html.lower())
    chk("  SVG 已光栅化(无残留<svg)", "<svg" not in html,
        "残留 %d 个" % html.count("<svg"))
    chk("  PNG data URI", 'data:image/png' in html,
        "%d 张" % html.count('data:image/png'))
    chk("  PNG≥15 张（含三引擎 5 图）", html.count('data:image/png') >= 15,
        "%d 张" % html.count('data:image/png'))
    os.remove(fp)   # 冒烟产物清理

# ---- 2b. suggest 闭环（一键建议值满足设计要求） ----
print("== 2b. /api/suggest closed=true（闭环建议值） ==")
rs = api.suggest({"cfg": cfg, "closed": True})
chk("suggest closed ok", rs.get("ok") is True, rs.get("error", ""))
cl = (rs.get("result") or {}).get("closed") or {}
chk("suggest closed 评级", cl.get("grade") in ("A", "B", "C", "D"), "grade=%s" % cl.get("grade"))
chk("suggest closed 结论", bool(cl.get("conclusion")), str(cl.get("conclusion"))[:60])
chk("suggest values 非空", bool((rs.get("result") or {}).get("values")))
rs2 = api.suggest({"cfg": cfg})
chk("suggest 轻量模式兼容", rs2.get("ok") and "closed" not in (rs2.get("result") or {}))
rs3 = api.suggest(cfg)
chk("suggest 旧 dict 签名兼容", rs3.get("ok") and bool((rs3.get("result") or {}).get("values")))

# ---- 3. export 旧通道兼容（sections） ----
print("== 3. /api/export 旧 sections 通道兼容 ==")
r2 = api.export_html({"name": "旧通道", "sections": [{"title": "T1", "html": "<p>hi</p>"}],
                      "kpi": "k"})
chk("sections ok", r2.get("ok") and "hi" in r2.get("html", ""))

# ---- 4. beam with_2d ----
print("== 4. /api/beam（with_2d 二维方向图） ==")
r3 = api.beam({"D_ap": 2.5, "freq_ghz": 20.0, "prefer": "grasp", "with_2d": True,
               "scan_deg": 6})
chk("beam ok", r3.get("ok") is True)
res3 = r3.get("result") or {}
chk("beam 1d", len(res3.get("theta") or []) > 50)
p2 = res3.get("pattern2d")
chk("beam 2d grid", bool(p2) and len(p2.get("grid") or []) == 41 and len(p2["grid"][0]) == 41)
chk("beam 2d th3", bool(p2) and p2.get("th3", 0) > 0, "th3=%s" % (p2 or {}).get("th3"))

# ---- 5. open_file / reveal_file 安全 ----
print("== 5. open_file / reveal_file 安全校验 ==")
r5 = api.open_file({"path": r"C:\Windows\system32\calc.exe"})
chk("open_file 拒绝目录外", r5.get("ok") is False and "安全限制" in (r5.get("error") or ""))
r6 = api.reveal_file({"path": r"C:\Windows\system32"})
chk("reveal_file 拒绝目录外", r6.get("ok") is False and "安全限制" in (r6.get("error") or ""))
r7 = api.open_file({"path": os.path.join(DA._out_dir(), "不存在.doc")})
chk("open_file 不存在", r7.get("ok") is False and "不存在" in (r7.get("error") or ""))

print("\n==== SMOKE v5: OK=%d FAIL=%d ====" % (ok, fail))
sys.exit(1 if fail else 0)
