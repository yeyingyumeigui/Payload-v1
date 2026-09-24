# -*- coding: utf-8 -*-
"""#91 验证：Word 报告排版规范——正文小四宋体黑 + 标题1/2/3=三号/小三/四号黑体黑 + 图片适配版心。"""
import sys, io, re, traceback
TOOLS = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
sys.path.insert(0, TOOLS)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NPASS = NFAIL = 0
def ck(cond, msg):
    global NPASS, NFAIL
    if cond: NPASS += 1; print("  PASS %s" % msg)
    else:    NFAIL += 1; print("  FAIL %s" % msg)

import design_data as DD, design_engine as DE, design_app as DA
import report_gen as RG, protocol_gen as PG

cfg = dict(DD.DEFAULT_CFG, name="报告排版自检", service="高通量宽带", orbit="GEO",
           coverage="巴基斯坦", band="Ka", feeder_band="Ka", mode="数字透明", ant_type="固面")
sg = DE.suggest_closed_loop(cfg, DA.KG)
for k, v in (sg.get("values") or {}).items():
    if v != "":
        cfg[k] = v
R = DE.design_all(cfg, DA.KG, skip_compare=True)
R["_cov_meta"] = DD.COVERAGE.get("巴基斯坦", {})
R["_orbit_alt_km"] = DD.ORBITS["GEO"]["alt_km"]
icd = PG.generate_icd(R)

print("[生成] build_report(rasterize=True) ...")
try:
    doc = RG.build_report(R, icd=icd, world_land=DA.world_land(), rasterize=True)
except Exception:
    traceback.print_exc(); doc = ""

ck(len(doc) > 10000, "报告生成成功（%d 字符）" % len(doc))

print("[正文] 小四宋体黑色")
ck('body{font-family:"宋体","SimSun",serif;font-size:12pt;line-height:1.85;color:#000}' in doc,
   "body=宋体 12pt(小四) 黑色")
ck('.doc-p{font-size:12pt;margin:6pt 0;text-align:left;color:#000}' in doc, "doc-p 正文小四黑色")
ck('.doc-sec{font-size:12pt;color:#000}' in doc, "doc-sec 小四黑色")

print("[标题] 三级黑体黑色")
ck('.doc-h2{font-family:"黑体","SimHei",sans-serif;font-size:16pt' in doc, "标题1(doc-h2)=三号16pt黑体")
ck('.doc-h3{font-family:"黑体","SimHei",sans-serif;font-size:15pt' in doc, "标题2(doc-h3)=小三15pt黑体")
ck('.doc-h4{font-family:"黑体","SimHei",sans-serif;font-size:14pt' in doc, "标题3(doc-h4)=四号14pt黑体")
ck('border-bottom:1.5pt solid #000;color:#000;page-break-after:avoid' in doc, "标题1 黑色（去蓝）")

print("[图片] 适配版心（≤616px，Word 版心≈633px）")
widths = [int(x) for x in re.findall(r'<img[^>]*?width="(\d+)"', doc)]
ck(len(widths) > 0, "img 数=%d" % len(widths))
ck(max(widths) <= 616 if widths else False, "图片最大宽 %dpx ≤616（版心内）" % (max(widths) if widths else -1))
ck(all(w <= 616 for w in widths), "全部图片宽 ≤616px")
# 内联 style px 与 width 属性一致（Word + HTML 双通道）
ck('style="width:%dpx' % (max(widths) if widths else 0) in doc or not widths,
   "img 带内联 style px（Word/HTML 双保险）")
npng = doc.count("data:image/png")
ck(npng >= 15, "PNG 光栅化 %d 张（≥15）" % npng)
ck(doc.count("<svg") == 0, "SVG 残留=0（全部转 PNG）")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
print("img widths sample:", sorted(widths, reverse=True)[:8])
