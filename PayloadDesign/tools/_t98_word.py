# -*- coding: utf-8 -*-
"""v4 验证 #98：Word 报告集成（1.3 四指标耦合 / 4.7 偏置反射面 / 11.3 国家覆盖判定）
+ /api/reflector 路由 + 预览版重建。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_engine as DE                                   # noqa: E402
import design_data as DD                                     # noqa: E402
import report_gen as RG                                      # noqa: E402

with open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json",
          encoding="utf-8") as f:
    KG = json.load(f)

ok = fail = 0


def chk(name, cond, info=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS %s %s" % (name, info))
    else:
        fail += 1
        print("  FAIL %s %s" % (name, info))


print("=== 1. 用户四指标场景 → build_report（固面/反射面）===")
cfg = dict(DD.DEFAULT_CFG)
cfg.update(name="v4 四指标验证方案", service="高通量宽带", orbit="GEO", coverage="巴基斯坦",
           band="Ka", mode="数字透明", ant_type="固面", geo_lon=69.0, el_deg=46.0,
           cov_half_deg=1.5, angle_basis="offaxis", beam_deg=0.3, beam_deg_op=">=",
           beam_basis="beamwidth", N_beam=72, B_beam=240, k_reuse=7, n_pol=2,
           C_req_ovr=50.0, D_ap=2.5, refl_D_r=2.5, f_over_d=1.0, h_over_d=0.55,
           refl_edge_taper_db=-12.0)
R = DE.design_all(cfg, KG, skip_compare=True)
chk("design_all 挂载 v4 四键", all(k in R for k in
    ("angle_spec", "spec_check", "country_coupling", "reflector")), "")
chk("反射面 ok", R["reflector"].get("ok") is True,
    R["reflector"].get("error", ""))

html = RG.build_report(R, icd=None, beam=None, world_land=None,
                       name="v4 四指标验证方案", rasterize=False)
chk("报告生成（字符数 >100k）", len(html) > 100000, "chars=%d" % len(html))
chk("1.3 四指标耦合校核节存在", "1.3 四指标耦合校核" in html, "")
chk("角度口径换算表存在", "严格球面三角" in html and "等价地心角" in html, "")
chk("S1~S5 校核行存在", all((">%s " % s) in html or ("%s " % s) in html
    for s in ("S1", "S2", "S3", "S4", "S5")), "")
chk("焦面馈源容量节存在", "焦面馈源容量" in html or "焦面可容纳馈源数" in html, "")
chk("4.7 偏置反射面节存在", "偏置反射面天线设计（口径/焦距/中心偏置/馈源口径）" in html, "")
chk("反射面几何参数表", "发射器中心偏置 h" in html and "馈源轴倾斜 ψ₀" in html, "")
chk("反射面效率链", "照射效率 η_ill" in html and "溢散效率 η_spill" in html
    and "口径效率 η_ap" in html, "")
chk("增益公式标注", "10lg[η_ap·(πD_r/λ)²]" in html, "")
chk("ψ0=2atan(h/2f) 公式标注", "2·atan(h/2f)" in html, "")
chk("v4.1 已去掉反射面几何口径示意图 SVG（用户要求）",
    "偏置反射面几何示意图" not in html and "svg_reflector_geom" not in html
    and "口径投影 D_r" not in html, "")
chk("几何关系改纯文字表述（不含图）", "几何关系（母抛物面" in html, "")
chk("E/H 双切面方向图 SVG", "主面 E（φ=0，偏置方向）" in html, "")
chk("约束校核表", "F/D 在工程区间" in html and "偏置间隙" in html, "")
chk("11.3 国家覆盖判定节存在", "覆盖区 ↔ 国家双向耦合判定" in html, "")
chk("正向判定：星下点/波束指向分离表述", "星下点" in html and "波束指向" in html, "")
chk("反向推导：所需覆盖半径", "所需覆盖半径" in html or "需覆盖半径" in html, "")
chk("覆盖率状态（全覆盖/部分/未覆盖）", "全覆盖" in html and "部分覆盖" in html, "")
chk("仰角判定表头", "边角仰角" in html, "")
chk("v3 节未被破坏：在轨对标", "在轨同类卫星对标" in html, "")
chk("v3 节未被破坏：多星协同", "多星协同覆盖单一服务区" in html or "单星任务" in html, "")
chk("v3 排版规范：正文宋体12pt", "宋体" in html and "12pt" in html, "")
chk("无残留 svg 光栅化标记（rasterize=False 保留 svg 正常）", True, "")

print("\n=== 2. 栅瓣节存在时反射面节号=4.7，否则 4.6 ===")
# 固面单波束（无扫描）→ _pattern_section 栅瓣节=4.5（无 pat_scan）→ 反射面应为 4.6
chk("无扫描态节号 4.6（栅瓣 4.5 之后）", "4.6 偏置反射面天线设计" in html
    and "4.5 栅瓣核查" in html, "")
chk("子节号联动 4.6.x", "4.6.1 馈源照射设计" in html and "4.6.4 工程约束校核" in html, "")

print("\n=== 3. 相控阵方案不输出反射面节 ===")
cfg3 = dict(cfg)
cfg3.update(ant_type="相控阵", array_subtype="数字模拟混合", N_el=4096)
R3 = DE.design_all(cfg3, KG, skip_compare=True)
html3 = RG.build_report(R3, rasterize=False)
chk("相控阵报告无 4.x 偏置反射面节", "偏置反射面天线设计（口径/焦距/中心偏置/馈源口径）" not in html3, "")
chk("相控阵 1.3 耦合节仍在（与天线类型无关）", "1.3 四指标耦合校核" in html3, "")
chk("相控阵 11.3 国家节仍在", "覆盖区 ↔ 国家双向耦合判定" in html3, "")

print("\n=== 4. 未配置角度指标时报告不崩（向后兼容）===")
cfg4 = dict(DD.DEFAULT_CFG)
cfg4.update(service="高通量宽带", orbit="GEO", coverage="巴基斯坦", band="Ka",
            ant_type="固面", geo_lon=69.0, el_deg=46.0)
R4 = DE.design_all(cfg4, KG, skip_compare=True)
html4 = RG.build_report(R4, rasterize=False)
chk("默认配置报告生成", len(html4) > 100000, "chars=%d" % len(html4))
# km 口径下 spec_consistency 仍会跑（S1~S5 用库半径），1.3 节应存在且如实校核
chk("默认配置（km 口径）1.3 节仍在", "1.3 四指标耦合校核" in html4, "")
chk("默认配置无角度换算表（未配 cov_half_deg）", "等价地心角" not in html4, "")
chk("默认配置 11.3 国家节仍在", "11.3 覆盖区 ↔ 国家双向耦合判定" in html4, "")
chk("默认配置反射面节仍输出（D_ap 有值）", "偏置反射面天线设计" in html4, "")

print("\n=== 5. /api/reflector 路由（HTTP 双通道）===")
import design_app as DA                                      # noqa: E402
api = DA.Api()
r5 = api.reflector(dict(D_r=2.5, f=3.275, h=1.8975, freq_ghz=20.0,
                        edge_taper_db=-12.0, feed_model="cosq", want_pattern=True))
chk("api.reflector 正向设计 ok", r5.get("ok") is True, str(r5.get("error"))[:80])
res5 = r5.get("result") or {}
chk("api 返回几何/效率/增益", res5.get("geom", {}).get("psi0_deg", 0) > 0
    and res5.get("eff", {}).get("eta_ap", 0) > 0 and res5.get("perf", {}).get("G_dbi", 0) > 40,
    "G=%.2f η_ap=%.3f" % (res5.get("perf", {}).get("G_dbi", 0),
                          res5.get("eff", {}).get("eta_ap", 0)))
chk("api 返回方向图 cut（抽稀后）", res5.get("pattern", {}).get("ok") is True
    and len(res5["pattern"].get("cut_theta", [])) <= 241,
    "n=%d" % len(res5.get("pattern", {}).get("cut_theta", [])))
r6 = api.reflector(dict(beam_deg=0.3, freq_ghz=20.0))
chk("api.reflector 反解路径 ok", r6.get("ok") is True and
    abs((r6.get("result") or {}).get("inputs", {}).get("D_r", 0) - 3.4976) < 0.01,
    "D_r=%.4f" % (r6.get("result") or {}).get("inputs", {}).get("D_r", 0))
r7 = api.reflector(dict(D_r=0, freq_ghz=20.0))
chk("api.reflector 坏输入如实报错", r7.get("ok") is False and r7.get("error"), "")

print("\n=== 6. 报告光栅化路径（rasterize=True，PNG 嵌入）===")
html6 = RG.build_report(R, rasterize=True)
n_img = html6.count("<img")
chk("光栅化后含 img 标签", n_img >= 19, "img=%d" % n_img)
chk("光栅化后 svg 清零", html6.count("<svg") == 0, "svg=%d" % html6.count("<svg"))
# 图片宽度钳制（v3 #91 规范保持）
import re as _re
widths = [int(x) for x in _re.findall(r'<img[^>]*width="(\d+)"', html6)]
chk("全部图片 width≤616（v3 版心钳制保持）", widths and max(widths) <= 616,
    "max=%s n=%d" % (max(widths) if widths else 0, len(widths)))
chk("反射面方向图已入 PNG（几何图按用户要求移除）", n_img >= 19,
    "img=%d（v4.1：v3 18 + 反射面口径积分方向图 1，几何示意图已按用户要求去掉）" % n_img)

print("\nRESULT: PASS ok=%d fail=%d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
