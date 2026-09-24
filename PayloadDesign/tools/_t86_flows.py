# -*- coding: utf-8 -*-
"""#86 验证：信息流保序（stages 不排序）+ hops 方向正确。

关键回归：供能流 一次电源(L8)→EPC(L6)→功放(L6) 必须保持书写顺序，
旧版按层号排序会反转成 功放→EPC→一次电源。
"""
import sys
import json
import io
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import design_engine as DE

KG = json.load(open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json", encoding="utf-8"))
NPASS, NFAIL = 0, 0


def ck(cond, msg):
    global NPASS, NFAIL
    if cond:
        NPASS += 1
        print("  PASS %s" % msg)
    else:
        NFAIL += 1
        print("  FAIL %s" % msg)


# ---- 单元：_flow_stages 保序 ----
print("[单元] _flow_stages 保序 + hops")
st, hp = DE._flow_stages("平台一次电源（母线 100V）→ EPC（6kV 高压）→ 功放 TWTA")
layers = [s["layer"] for s in st]
print("  stages 层序=%s nodes=%s" % (layers, [s["node"] for s in st]))
ck(layers == ["L8", "L6", "L6"], "供能流保序 L8→L6→L6（未被排序反转）")
ck(st[0]["node"].startswith("平台一次电源"), "首节点=一次电源（真实源头）")
ck(hp[0]["fwd"] is False, "L8→L6 首跳为反向（fwd=False，渲染画回线）")
ck(hp[1]["fwd"] is True and hp[1]["f"] == "L6" and hp[1]["t"] == "L6",
   "L6→L6 同层跳 fwd=True（渲染合并同列）")

st2, hp2 = DE._flow_stages("用户终端 → 用户天线 → LNA → 下变频 → 处理交换 → 上变频 → 功放 → OMUX → 用户下行波束")
lay2 = [s["layer"] for s in st2]
print("  射频流层序=%s" % lay2)
ck(lay2 == ["L1", "L2", "L3", "L4", "L5", "L4", "L6", "L4", "L2"],
   "射频流 V 形保序（L4 出现 3 次：下变频/上变频/OMUX）")
ck(sum(1 for h in hp2 if not h["fwd"]) == 3, "3 个反向跳（L5→L4、L6→L4、L4→L2）")

st3, hp3 = DE._flow_stages("地面测控站 ⇄ 测控应答机 ⇄ 星载计算机")
ck(all(h["bid"] for h in hp3), "⇄ 分隔 → hops bid=True（双向虚线）")

st4, hp4 = DE._flow_stages("基带数据 → DPU 压缩 → FC-AE 总线；二次电源 → 数字单机")
subs = {s["sub"] for s in st4}
ck(subs == {0, 1}, "；分隔子链 sub=0/1")
ck(all(h["sub"] == hp4[0]["sub"] for h in hp4[:1]), "跨子链不产生跳")

# ---- 集成：design_all 后 flows 结构 ----
print("[集成] GEO Ka 固面 数字透明")
R = DE.design_all(dict(service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
                       band="Ka", ant_type="固面", D_ap=2.5, mode="数字透明", feeder_band="Ka",
                       cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15),
                  KG, skip_compare=True)
F = R["flows"]
allf = F["all"]
ck(len(allf) >= 6, "流总数 %d ≥6（sg+si+sn）" % len(allf))
ck(all("stages" in f and "hops" in f for f in allf), "每条流含 stages+hops")
# sn4 供能流方向
sn4 = next(f for f in allf if f["id"] == "sn4")
lay4 = [s["layer"] for s in sn4["stages"]]
print("  sn4 供能流层序=%s nodes=%s" % (lay4, [s["node"] for s in sn4["stages"]]))
ck(lay4[0] == "L8", "sn4 首节点=L8 一次电源（源头在前）")
ck(lay4[-1] in ("L6", "L5"), "sn4 末节点=L6 功放/L5 数字单机（负载在后）")
ck(sn4["tier"] == "power", "sn4 tier=power")
# sn1 射频流 V 形
sn1 = next(f for f in allf if f["id"] == "sn1")
lay1 = [s["layer"] for s in sn1["stages"]]
print("  sn1 射频流层序=%s" % lay1)
ck(lay1.count("L4") >= 2, "sn1 含多个 L4（下变频+上变频+OMUX 回程）")
ck(lay1[-1] == "L2", "sn1 末节点=L2 天线（回程闭合）")
# sg4 测控双向
sg4 = next(f for f in allf if f["id"] == "sg4")
ck(sg4.get("bidir") is True, "sg4 测控流 bidir=True（⇄）")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
