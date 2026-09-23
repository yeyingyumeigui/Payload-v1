# -*- coding: utf-8 -*-
"""生成桌面应用的浏览器预览快照：预计算 8 场景 + 默认配置的设计结果与建议值，
注入 pywebview 桥模拟层 → output/载荷方案设计器_预览版.html。

预览版功能：所有页签完整渲染、场景一键切换、方案对比、建议值（预置场景）、诊断弹窗；
自定义参数实时重算请运行 exe 或 `python design_app.py --web`（网页版实时计算）。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_app
from design_app import Api

OUT = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\载荷方案设计器_预览版.html"

def _beam_D(res):
    """等效口径：反射面取 D_m；相控阵由增益反推（与前端 beamAperture 同式）。"""
    ant = res["res"]["antenna"]
    if ant.get("D_m"):
        return ant["D_m"]
    Glin = 10 ** ((ant.get("G_ant") or 0) / 10)
    eta = 0.65
    return (ant.get("lam_m") or 0.02) / 3.141592653589793 * (Glin / eta) ** 0.5

def _beam_f(res, meta):
    """下行中心频率（与前端 loadBeamPanel 同源：downlink.f_ghz 优先，频段表兜底）。"""
    lk = res["res"].get("downlink") or {}
    if lk.get("f_ghz"):
        return lk["f_ghz"]
    band = (res.get("cfg") or {}).get("band", "Ka")
    return (meta.get("band_freq", {}).get(band) or [20, 20])[1]

def main():
    api = Api()
    meta = api.meta()
    designs = {}
    cfgs = {}
    suggests = {}
    beams = []
    icds = {}
    for k, sc in meta["scenarios"].items():
        cfg = dict(meta["default_cfg"]); cfg.update(sc["cfg"])
        cfg["name"] = sc["label"]; cfg["isl_on"] = bool(sc["cfg"].get("isl_on"))
        r = api.design(cfg, with_compare=True)
        assert r["ok"], (k, r.get("error"))
        designs[k] = r["result"]; cfgs[k] = cfg
        s = api.suggest(cfg)
        suggests[k] = s["result"] if s.get("ok") else {"values": {}, "notes": {}, "auto": {}}
        # 预计算接口协议 ICD（protocol_gen，与 exe 同源）
        pc = api.protocol({"cfg": cfg})
        if pc.get("ok"):
            icds[k] = pc["result"]
        # 预计算波束方向图（解析法 + 二维，预览版离线可复现；exe 版走 GRASP 实时）
        b = api.beam({"D_ap": _beam_D(r["result"]), "freq_ghz": _beam_f(r["result"], meta),
                      "prefer": "analytic", "tag": "pv_" + k, "with_2d": True,
                      "scan_deg": cfg.get("θ_scan") or 0})
        if b.get("ok"):
            beams.append({"D": _beam_D(r["result"]), "f": _beam_f(r["result"], meta),
                          "result": b["result"]})
        print("precomputed:", k)
    cfg0 = dict(meta["default_cfg"]); cfg0["isl_on"] = False
    r0 = api.design(cfg0, with_compare=True)
    assert r0["ok"], r0.get("error")
    designs["__default"] = r0["result"]; cfgs["__default"] = cfg0
    s0 = api.suggest(cfg0)
    suggests["__default"] = s0["result"] if s0.get("ok") else {"values": {}, "notes": {}, "auto": {}}
    pc0 = api.protocol({"cfg": cfg0})
    if pc0.get("ok"):
        icds["__default"] = pc0["result"]
    b0 = api.beam({"D_ap": _beam_D(r0["result"]), "freq_ghz": _beam_f(r0["result"], meta),
                   "prefer": "analytic", "tag": "pv_default", "with_2d": True,
                   "scan_deg": cfg0.get("θ_scan") or 0})
    if b0.get("ok"):
        beams.append({"D": _beam_D(r0["result"]), "f": _beam_f(r0["result"], meta),
                      "result": b0["result"]})
    worldmap = api.worldmap()

    shim = """
<script>
/* 预览模式桥模拟：预计算结果内嵌，页面逻辑与 exe 完全一致 */
const PREVIEW = { meta: __META__, designs: __DESIGNS__, cfgs: __CFGS__, suggests: __SUGGESTS__,
                  beams: __BEAMS__, worldmap: __WORLDMAP__, icds: __ICDS__ };
(function(){
  function matchKey(cfg){
    const keys = Object.keys(PREVIEW.cfgs);
    for (const k of keys){
      const pc = PREVIEW.cfgs[k];
      const same = ["service","orbit","coverage","band","feeder_band","mode","ant_type",
                    "array_subtype","N_beam","B_beam","D_ap","N_el"].every(f=>
        String(cfg[f]===undefined?"":cfg[f]) === String(pc[f]===undefined?"":pc[f]));
      if (same) return k;
    }
    return null;
  }
  function matchBeam(D, f){
    let best = null, bd = 1e9;
    for (const b of PREVIEW.beams){
      const d = Math.abs(b.D - D) / Math.max(D, 0.01) + Math.abs(b.f - f) / Math.max(f, 0.01);
      if (d < bd){ bd = d; best = b; }
    }
    return (best && bd < 0.02) ? best.result : null;
  }
  const RUN_HINT = "预览版是静态快照（内置 8 个预置场景 + 默认配置的预计算结果）。\\n\\n修改参数后的实时重算请任选其一：\\n① 双击桌面版 dist\\\\载荷方案设计器.exe（离线运行）\\n② 网页版实时计算：python design_app.py --web → 浏览器打开 http://127.0.0.1:8642";
  window.pywebview = { api: {
    meta: async () => PREVIEW.meta,
    design: async (cfg, withCompare) => {
      const k = matchKey(cfg);
      if (k && PREVIEW.designs[k]) return { ok: true, result: PREVIEW.designs[k] };
      return { ok: false, error: RUN_HINT, trace: "" };
    },
    suggest: async (cfg) => {
      const k = matchKey(cfg);
      if (k && PREVIEW.suggests[k]) return { ok: true, result: PREVIEW.suggests[k] };
      return { ok: true, result: { values: {}, notes: {}, auto: {} } };
    },
    protocol: async (p) => {
      const k = matchKey((p||{}).cfg||{});
      if (k && PREVIEW.icds[k]) return { ok: true, result: PREVIEW.icds[k] };
      return { ok: false, error: "预览版仅内置预置场景的接口协议数据。\\n" + RUN_HINT };
    },
    beam: async (p) => {
      const r = matchBeam(+p.D_ap || 0, +p.freq_ghz || 0);
      if (r) return { ok: true, result: r };
      return { ok: false, error: "预览版仅内置预置场景的波束数据。\\n" + RUN_HINT };
    },
    worldmap: async () => PREVIEW.worldmap,
    export: async (payload) => ({ ok: false, error: "预览版导出请用浏览器打印→PDF，或运行 exe 版导出完整 Word 报告（含目录/流程图/架构图/波束方向图/三维覆盖/接口协议 ICD）。" }),
    export_html: async (payload) => ({ ok: false, error: "预览版导出请运行 exe 版。" }),
    open_file: async () => ({ ok: false, error: "预览版无本地文件，请运行 exe 版导出。" }),
    reveal_file: async () => ({ ok: false, error: "预览版无本地文件，请运行 exe 版导出。" })
  }};
  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(()=>document.dispatchEvent(new Event("pywebviewready")), 60);
  });
})();
</script>
"""
    shim = (shim.replace("__META__", json.dumps(meta, ensure_ascii=False))
                .replace("__DESIGNS__", json.dumps(designs, ensure_ascii=False))
                .replace("__CFGS__", json.dumps(cfgs, ensure_ascii=False))
                .replace("__SUGGESTS__", json.dumps(suggests, ensure_ascii=False))
                .replace("__BEAMS__", json.dumps(beams, ensure_ascii=False))
                .replace("__WORLDMAP__", json.dumps(worldmap, ensure_ascii=False))
                .replace("__ICDS__", json.dumps(icds, ensure_ascii=False)))

    html = design_app.FRONT_HTML
    # 注入 shim（在应用脚本之前）+ 预览横幅
    marker = "<script>\n'use strict';\nlet META = null"
    assert marker in html, "app script marker not found"
    html = html.replace(marker, shim + marker, 1)
    html = html.replace('<div class="sub">payload-design',
        '<div class="sub"><span class="tag warn">预览版（内置预计算结果）· 完整实时计算请运行 exe</span> payload-design', 1)
    html = html.replace("<title>通信卫星有效载荷方案设计器</title>",
        "<title>通信卫星有效载荷方案设计器 · 预览版</title>", 1)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("preview written:", OUT, "%.1f KB" % (len(html.encode("utf-8"))/1024))

if __name__ == "__main__":
    main()
