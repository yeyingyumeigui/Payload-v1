# -*- coding: utf-8 -*-
"""生成单文件 HTML「载荷信息流仿真计算器」。

数据层（UNITS/BANDS/MODCOD/PARAMS/PRESETS/LINK_META + 知识图谱链路链）经 json.dumps
内嵌为 JS 常量；计算引擎为 infoflow_engine.py 的等价 JS 翻译；界面含：
  概览 KPI / 链路预算 / 15 条信息流逐级可视化 / 25 约束看板 / 参数面板 / 回环建议
  + DOC 下载 + 打印 PDF（打印样式）。
输出: output/载荷信息流仿真计算器.html
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from infoflow_data import UNITS, BANDS, MODCOD, PARAMS, PARAM_GROUPS, PRESETS, LINK_META

SRC = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\载荷信息流仿真计算器.html"

with open(SRC, "r", encoding="utf-8") as f:
    kg = json.load(f)

# 仅保留有 chain 的本体节点（信息流链路），压缩体积
chains = {}
for o in kg["ontologies"]:
    if o.get("chain"):
        chains[o["id"]] = dict(name=o.get("name", o["id"]),
                               desc=o.get("description", ""), chain=o["chain"])
constraints_kg = [dict(id=c["id"], formula=c.get("formula", ""),
                       description=c.get("description", ""))
                  for c in kg["constraints"]]

DATA = dict(UNITS=UNITS, BANDS=BANDS, MODCOD=MODCOD, PARAMS=PARAMS,
            PARAM_GROUPS=PARAM_GROUPS, PRESETS=PRESETS, LINK_META=LINK_META,
            CHAINS=chains, CONSTRAINTS_KG=constraints_kg,
            kg_meta=dict(version=kg.get("version"), name=kg.get("name")))

data_js = json.dumps(DATA, ensure_ascii=False)

# ================================================================
# JS 引擎（与 infoflow_engine.py 等价）
# ================================================================
ENGINE_JS = r"""
'use strict';
const K_BOLTZ_DB = -228.6;

function to_f(v, def) {
  if (def === undefined) def = 0.0;
  if (v === null || v === undefined || v === "") return def;
  const x = parseFloat(v);
  return isNaN(x) ? def : x;
}
function w2dbm(w) { return w > 0 ? 10 * Math.log10(w) + 30.0 : -999.0; }
function w2dbw(w) { return w > 0 ? 10 * Math.log10(w) : -999.0; }
function fmt(v, nd, unit) {
  if (nd === undefined) nd = 2;
  unit = unit || "";
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (!isFinite(v)) return "—";
  let s = v.toFixed(nd);
  s = s.replace(/\.?0+$/, "");
  if (s === "" || s === "-") s = "0";
  return s + unit;
}
function lam_m(f_ghz) { const f = to_f(f_ghz); return f > 0 ? 299792458.0 / (f * 1e9) : 0.0; }

/* ---------------- 一、逐级信号流 ---------------- */
function unit_params(vid, p) {
  const u = DATA.UNITS[vid];
  if (!u) return { id: vid, cn: vid, kind: "pass", g_db: 0, nf_db: 0, p_w: 0, m_kg: 0,
                   note: "知识图谱节点（无电气默认值）", specs: {}, overridden: false };
  let g = u.g_db || 0, nf = u.nf_db || 0, pw = u.p_w || 0, mk = u.m_kg || 0;
  const specs = Object.assign({}, u.specs || {});
  let note = u.note || "", ovr = false;
  if (vid === "lna") { g = to_f(p.G_lna, g); nf = to_f(p.NF_lna, nf);
    specs.G_lna = g; specs.NF_lna = nf; ovr = true; }
  else if (vid === "twta") {
    if (p.amp_type === "TWTA") { specs.P_twta = to_f(p.P_out, specs.P_twta); specs["η_twta"] = to_f(p["η_pa"], specs["η_twta"]); }
    ovr = true; }
  else if (vid === "sspa") {
    if (p.amp_type === "SSPA") { specs.P_sspa = to_f(p.P_out, specs.P_sspa); specs["η_sspa"] = to_f(p["η_pa"], specs["η_sspa"]); }
    specs.IMD3 = to_f(p.IMD3, specs.IMD3); ovr = true; }
  else if (vid === "mpa") { specs.P_sspa = p.amp_type === "MPA" ? to_f(p.P_out, 100) : 100;
    specs["η_sspa"] = to_f(p["η_pa"], specs["η_sspa"]); ovr = true; }
  else if (vid === "tr_module") { specs.T_j = to_f(p.T_j, specs.T_j); specs.P_tr = to_f(p.P_tr, specs.P_tr);
    pw = specs.P_tr; ovr = true; }
  else if (vid === "circulator") { specs.I_iso = to_f(p.I_iso, specs.I_iso); ovr = true; }
  else if (vid === "tx_filter") { specs.A_rej = to_f(p.A_rej, specs.A_rej); ovr = true; }
  else if (vid === "switch_matrix") { specs.I_sw = to_f(p.I_sw, specs.I_sw); ovr = true; }
  else if (vid === "feed") { specs["η_ill"] = to_f(p["η_ill"], specs["η_ill"]); ovr = true; }
  else if (vid === "deploy") { specs["δ_dep"] = to_f(p["δ_dep"], specs["δ_dep"]); ovr = true; }
  else if (vid === "pointing") { specs["Δ_pnt"] = to_f(p["Δ_pnt"], specs["Δ_pnt"]); ovr = true; }
  else if (vid === "beam_former") { specs.N_bf = to_f(p.N_bf, specs.N_bf); ovr = true; }
  else if (vid === "beam_port") { specs.N_port = to_f(p.N_port, specs.N_port); ovr = true; }
  else if (vid === "cal_network") { specs["Δ_cal"] = to_f(p["Δ_cal"], specs["Δ_cal"]); ovr = true; }
  else if (vid === "dswitch") { specs.C_dsw = to_f(p.C_dsw, specs.C_dsw);
    pw = 45.0 + 0.35 * Math.max(0, specs.C_dsw - 100); ovr = true; }
  else if (vid === "adc") { pw = 25.0 * Math.max(1, Math.floor(to_f(p.N_ch, 32) / 8));
    specs.N_ch = to_f(p.N_ch, 32); specs.B_sub = to_f(p.B_sub, 40); ovr = true; }
  else if (vid === "dac") { pw = 20.0 * Math.max(1, Math.floor(to_f(p.N_ch, 32) / 8)); ovr = true; }
  else if (vid === "atp_coarse") { specs.P_acq = to_f(p.P_acq, specs.P_acq); specs.t_acq = to_f(p.t_acq, specs.t_acq); ovr = true; }
  else if (vid === "fsm") { specs["σ_track"] = to_f(p["σ_track"], specs["σ_track"]);
    specs["θ_fsm"] = to_f(p["θ_fsm"], specs["θ_fsm"]); ovr = true; }
  else if (vid === "tx_laser") { specs.P_opt = to_f(p.P_opt, specs.P_opt); ovr = true; }
  else if (vid === "edfa") { specs.G_edfa = to_f(p.G_edfa, specs.G_edfa); g = specs.G_edfa; ovr = true; }
  else if (vid === "optical_antenna") { specs.D_opt = to_f(p.D_opt, specs.D_opt); ovr = true; }
  else if (vid === "photodetector") { specs.S_opt = to_f(p.S_opt, specs.S_opt); ovr = true; }
  else if (vid === "dpsk_modem") { specs.CN_dpsk = to_f(p.CN_dpsk, specs.CN_dpsk); ovr = true; }
  else if (vid === "data_bus") { specs.R_bus = to_f(p.R_bus, specs.R_bus); ovr = true; }
  else if (vid === "storage") { specs.E_store = to_f(p.E_store, specs.E_store); ovr = true; }
  else if (vid === "dpu") { specs.CR = to_f(p.CR, specs.CR); specs.R_dpu = to_f(p.R_dpu, specs.R_dpu); ovr = true; }
  else if (vid === "baseband") { specs.R_bb = to_f(p.R_bb, specs.R_bb); ovr = true; }
  else if (vid === "ai_unit") { specs.AI_TOPS = to_f(p.AI_TOPS, specs.AI_TOPS); ovr = true; }
  else if (vid === "obc_payload") { specs.MIPS = to_f(p.MIPS, specs.MIPS); ovr = true; }
  else if (vid === "reconfig_ctrl") { specs.t_rec = to_f(p.t_rec, specs.t_rec); ovr = true; }
  else if (vid === "router_unit") { specs.N_route = to_f(p.N_route, specs.N_route); ovr = true; }
  return { id: vid, cn: u.cn, kind: u.kind, g_db: g, nf_db: nf, p_w: pw, m_kg: mk,
           note: note, specs: specs, overridden: ovr };
}

function propagate_tx(chain, p) {
  const amp_type = p.amp_type || "TWTA";
  const amp_vid = { TWTA: "twta", SSPA: "sspa", MPA: "mpa" }[amp_type] || "twta";
  const amp_pout_w = to_f(p.P_out, 180.0);
  const amp_pout_dbw = w2dbw(amp_pout_w);
  let cur = -20.0;
  const stages = [];
  let total_loss = 0, total_gain = 0, amp_seen = false;
  chain.forEach((vid, idx) => {
    const u = unit_params(vid, p);
    let g_eff, p_in, p_out, note;
    if (vid === amp_vid) {
      g_eff = amp_pout_dbw - cur; p_in = cur; p_out = amp_pout_dbw; amp_seen = true;
      const pdc = amp_pout_w / Math.max(1e-6, to_f(p["η_pa"], 58) / 100);
      note = amp_type + " 饱和输出 " + fmt(amp_pout_w, 1) + "W = " + fmt(amp_pout_dbw, 2) +
             "dBW；本级等效增益 " + fmt(g_eff, 2) + "dB；P_dc = P_out/η = " + fmt(pdc, 1) + "W";
    } else if (u.kind === "amp" && !amp_seen) {
      p_in = cur; p_out = cur + u.g_db; g_eff = u.g_db;
      total_gain += Math.max(0, u.g_db);
      note = u.note || ("增益 " + fmt(u.g_db, 2) + "dB");
    } else if (["dig", "ctrl", "mech", "opt"].includes(u.kind)) {
      p_in = cur; p_out = cur + u.g_db; g_eff = u.g_db;
      if (u.g_db < 0) total_loss += -u.g_db;
      note = u.note || "电平不变（数字/控制域）";
    } else {
      p_in = cur; p_out = cur + u.g_db; g_eff = u.g_db;
      if (u.g_db < 0) total_loss += -u.g_db;
      note = u.note || ("插损 " + fmt(-u.g_db, 2) + "dB");
    }
    stages.push({ seq: idx + 1, id: vid, cn: u.cn, kind: u.kind, g_db: g_eff,
                  p_in: p_in, p_out: p_out, note: note, specs: u.specs,
                  p_w: u.p_w, m_kg: u.m_kg });
    cur = p_out;
  });
  return { stages: stages, p_exit_dbw: cur, total_loss_db: total_loss,
           total_gain_db: total_gain, amp_dbw: amp_pout_dbw, amp_w: amp_pout_w };
}

function propagate_rx(chain, p, T_ant) {
  if (T_ant === undefined || T_ant === null) T_ant = to_f(p.T_ant, 50.0);
  const us = chain.map(vid => unit_params(vid, p));
  const stages = [];
  let cum_g = 0, T_total = T_ant;
  us.forEach((u, i) => {
    const L_lin = u.g_db < 0 ? Math.pow(10, -u.g_db / 10) : 1.0;
    let T_dev = 0;
    if (u.kind === "amp" && u.nf_db > 0) {
      const F = Math.pow(10, u.nf_db / 10); T_dev = (F - 1) * 290.0;
    } else if (u.kind === "pass" && u.g_db < 0) {
      T_dev = (L_lin - 1) * 290.0;
    }
    const contrib = cum_g !== 0 ? T_dev / Math.pow(10, cum_g / 10) : T_dev;
    stages.push({ seq: i + 1, id: u.id, cn: u.cn, kind: u.kind, g_db: u.g_db,
                  nf_db: u.nf_db, T_dev: T_dev, cum_g_db: cum_g, T_contrib: contrib,
                  note: u.note, specs: u.specs, p_w: u.p_w, m_kg: u.m_kg });
    T_total += contrib;
    cum_g += u.g_db;
  });
  const NF_total = T_total > 0 ? 10 * Math.log10(1 + T_total / 290.0) : 0;
  return { stages: stages, T_sys: T_total, NF_total_db: NF_total,
           G_rx_total_db: cum_g, T_ant: T_ant };
}

/* ---------------- 二、天线电气 ---------------- */
function antenna_electrical(p) {
  const f_dn = to_f(p.f_down, 20.0);
  const lam = lam_m(f_dn), lam_mm = lam * 1000;
  const at = p.ant_type || "反射面天线";
  const eta = to_f(p["η_ill"], 68) / 100.0;
  const res = { lam_m: lam, lam_mm: lam_mm, ant_type: at };
  let G_calc;
  if (at === "相控阵天线") {
    const N_el = to_f(p.N_el, 1024), G_el = to_f(p.G_el, 6.0);
    const th_scan = to_f(p["θ_scan"], 0);
    const G_pa = 10 * Math.log10(Math.max(N_el * eta, 1e-9)) + G_el;
    const scan_loss = th_scan > 0
      ? -10 * 1.5 * Math.log10(Math.max(Math.cos(th_scan * Math.PI / 180), 1e-6)) : 0;
    G_calc = G_pa + scan_loss;
    const D = to_f(p.D_ap, 0.8);
    const A_phys = D > 0 ? Math.PI * Math.pow(D / 2, 2) : N_el * Math.pow(lam / 2, 2);
    const L_side = Math.sqrt(A_phys);
    res.formula = "c-3"; res.G_pa_db = G_pa; res.scan_loss_db = scan_loss;
    res.A_phys_m2 = A_phys; res.D_equiv_m = 2 * Math.sqrt(A_phys / Math.PI);
    res["θ_3dB"] = L_side > 0 ? (0.886 * lam / Math.max(L_side, 1e-6)) * 180 / Math.PI : 0;
  } else {
    const D = to_f(p.D_ap, 2.5);
    G_calc = 10 * Math.log10(Math.max(eta * Math.pow(Math.PI * D / lam, 2), 1e-9));
    res.formula = "c-4"; res.G_refl_db = G_calc; res.D_m = D;
    res.A_phys_m2 = Math.PI * Math.pow(D / 2, 2);
    res["θ_3dB"] = D > 0 ? 70.0 * lam / D : 0;
    res.scan_loss_db = 0.0;
  }
  let G_ant;
  if (p.G_ant_ovr !== undefined && p.G_ant_ovr !== null && p.G_ant_ovr !== "" &&
      !isNaN(to_f(p.G_ant_ovr, NaN))) {
    G_ant = to_f(p.G_ant_ovr); res.G_source = "手动覆盖";
  } else { G_ant = G_calc; res.G_source = res.formula; }
  res.G_ant = G_ant;
  const lim = lam_mm / 32.0;
  const d_surf = to_f(p["δ_surf"], 0.20), d_dep = to_f(p["δ_dep"], 0.20);
  res.c5 = { limit_mm: lim, "δ_surf": d_surf, "δ_dep": d_dep,
             ok_surf: d_surf <= lim, ok_dep: d_dep <= d_surf,
             ok: d_surf <= lim && d_dep <= d_surf };
  const th_e = to_f(p["θ_e"], 0.05);
  const th3 = (res["θ_3dB"] || 0.5) || 0.5;
  res.c6 = { "θ_e": th_e, "θ_3dB": th3, L_pnt_db: 12.0 * Math.pow(th_e / th3, 2) };
  const dAmp = to_f(p["Δ_amp"], 0.4), dPhs = to_f(p["Δ_phs"], 4.0);
  const SLL = to_f(p.SLL, -22), AR = to_f(p.AR, 1.5), dCal = to_f(p["Δ_cal"], 0.3);
  res.c23 = { "Δ_amp": dAmp, "Δ_phs": dPhs, SLL: SLL, AR: AR, "Δ_cal": dCal,
              ok: dAmp <= 0.5 && dPhs <= 5.0 && SLL <= -20 && AR <= 3.0 && dCal <= dAmp };
  return res;
}

/* ---------------- 三、EIRP / G/T ---------------- */
function eirp_calc(p, ant, tx_flow) {
  const P_out_w = to_f(p.P_out, 180.0), P_out_dbw = w2dbw(P_out_w);
  const G_ant = ant.G_ant, L_feed = to_f(p.L_feed, 0.8);
  const L_tx_chain = tx_flow.stages
    .filter(s => s.g_db < 0 && !["twta", "sspa", "mpa"].includes(s.id))
    .reduce((a, s) => a - s.g_db, 0);
  const hasUser = p.L_tx !== undefined && p.L_tx !== null && p.L_tx !== "";
  const L_tx = hasUser ? to_f(p.L_tx) : L_tx_chain;
  const EIRP = P_out_dbw + G_ant - L_feed - L_tx;
  const eta_pa = to_f(p["η_pa"], 58) / 100.0;
  return { c: "c-1", P_out_w: P_out_w, P_out_dbw: P_out_dbw, G_ant: G_ant,
           L_feed: L_feed, L_tx: L_tx, L_tx_chain: L_tx_chain,
           L_tx_source: hasUser ? "用户输入" : "发射链累加",
           EIRP: EIRP, P_dc_w: eta_pa > 0 ? P_out_w / eta_pa : 0, "η_pa_pct": to_f(p["η_pa"], 58) };
}

function gt_calc(p, ant, rx_flow) {
  const G_ant = ant.G_ant;
  let T_sys, src;
  const hasOvr = p.T_sys_ovr !== undefined && p.T_sys_ovr !== null && p.T_sys_ovr !== "";
  if (hasOvr && to_f(p.T_sys_ovr, 0) > 0) { T_sys = to_f(p.T_sys_ovr); src = "手动覆盖"; }
  else { T_sys = rx_flow.T_sys; src = "接收链 Friis 级联"; }
  return { c: "c-2", G_ant: G_ant, T_sys: T_sys, T_ant: rx_flow.T_ant,
           T_rx: T_sys - rx_flow.T_ant, GT: T_sys > 0 ? G_ant - 10 * Math.log10(T_sys) : -999,
           source: src, NF_total_db: rx_flow.NF_total_db };
}

/* ---------------- 四、链路预算 ---------------- */
function rain_at_avail(A_ref, avail_pct, el_deg) {
  const p_ref = 0.01;
  const pp = Math.max(100.0 - to_f(avail_pct, 99.9), 1e-6);
  const el = Math.max(to_f(el_deg, 30), 5.0);
  const k = Math.pow(pp / p_ref, -0.6);
  return to_f(A_ref, 0.0) * k * (Math.sin(30 * Math.PI / 180) / Math.sin(el * Math.PI / 180));
}
function fspl(d_km, f_ghz) {
  const d = to_f(d_km, 38000) * 1000.0, f = to_f(f_ghz, 20.0) * 1e9;
  if (d <= 0 || f <= 0) return 0;
  return 20 * Math.log10(d) + 20 * Math.log10(f) - 147.55;
}
function pick_modcod(cn_db, forced, m_target) {
  if (forced) { const m = DATA.MODCOD.find(x => x.name === forced); if (m) return m; }
  const ok = DATA.MODCOD.filter(m => cn_db >= m.cn_req);
  if (!ok.length) return null;
  let best = ok.reduce((a, b) => b.eta > a.eta ? b : a);
  if (m_target !== undefined && m_target !== null && m_target > 0) {
    const ok_m = ok.filter(m => cn_db - m.cn_req >= m_target);
    if (ok_m.length) best = ok_m.reduce((a, b) => b.eta > a.eta ? b : a);
  }
  return best;
}

function rf_link_budget(p, ant, direction) {
  const f = to_f(direction === "up" ? p.f_up : p.f_down, 30.0);
  const d = to_f(direction === "up" ? p.d_slant : p.d_dl, 38000);
  const avail = to_f(p.A_avail, 99.9), el = to_f(p.el_deg, 30);
  const A_ref = to_f(direction === "up" ? p.A_up_ref : p.A_dn_ref, 7.0);
  const A_rain = rain_at_avail(A_ref, avail, el);
  const A_atm = to_f(direction === "up" ? p.A_atm : p.A_atm_dl, 0.3);
  const L_pnt = ant.c6.L_pnt_db;
  const L_pol = to_f(p.L_pol, 0.3), L_impl = to_f(p.L_impl, 1.0);
  const L_fs = fspl(d, f);
  const sum_L = A_rain + A_atm + L_pnt + L_pol + L_impl;
  const B_beam = to_f(p.B_beam, 125);
  let B_car = to_f(p.B_carrier, B_beam) || B_beam;
  if (B_beam > 0) B_car = Math.min(B_car, B_beam);
  const N_carrier = B_car > 0 ? B_beam / B_car : 1.0;
  let EIRP_total, EIRP, GT, gt_sym, share_db;
  if (direction === "up") {
    EIRP_total = to_f(p.EIRP_gs, 75.0); EIRP = EIRP_total;
    GT = ant._GT || 0; gt_sym = "GT_ant"; share_db = 0;
  } else {
    EIRP_total = ant._EIRP || 0;
    share_db = N_carrier > 1 ? 10 * Math.log10(N_carrier) : 0;
    EIRP = EIRP_total - share_db;
    GT = to_f(p.GT_gs, 15.0); gt_sym = "GT_gs";
  }
  const CN0 = EIRP - L_fs - sum_L + GT - K_BOLTZ_DB;
  const B_hz = B_car * 1e6;
  const CN = B_hz > 0 ? CN0 - 10 * Math.log10(B_hz) : CN0;
  const mc = pick_modcod(CN, null, to_f(p.M_target, 3.0));
  const CN_req = mc ? mc.cn_req : DATA.MODCOD[0].cn_req;
  const eta = mc ? mc.eta : 0;
  const M = CN - CN_req;
  return { direction: direction, f_ghz: f, d_km: d, L_fs: L_fs,
           EIRP: EIRP, EIRP_total: EIRP_total, share_db: share_db,
           N_carrier: N_carrier, GT: GT, gt_sym: gt_sym,
           A_rain: A_rain, A_atm: A_atm, L_pnt: L_pnt, L_pol: L_pol, L_impl: L_impl,
           sum_L: sum_L, CN0: CN0, B_mhz: B_car, B_beam_mhz: B_beam, CN: CN,
           modcod: mc ? mc.name : "无法闭合（低于最低阶门限）",
           eta: eta, CN_req: CN_req, M: M,
           C_link_mbps: B_car * eta, C_link_gbps: B_car * eta / 1000,
           C_beam_mbps: B_beam * eta, C_beam_gbps: B_beam * eta / 1000,
           avail: avail, el: el,
           c8: "C/N0 = EIRP − L_fs − ΣL + G/T − k", c9: "C/N = C/N0 − 10lg(B)",
           c10: "M = C/N − (C/N)_req ≥ 3dB", c11: "C_link = B × η(MODCOD)" };
}

function total_cn(cn_up, cn_dn) {
  const lin = x => Math.pow(10, x / 10);
  return -10 * Math.log10(1 / lin(cn_up) + 1 / lin(cn_dn));
}

/* ---------------- 五、激光 ---------------- */
function laser_link(p, kind) {
  const D_mm = to_f(p.D_opt, 135), D = D_mm / 1000;
  const lam_nm = to_f(p["λ_opt"], 1550), lam = lam_nm * 1e-9;
  const eta = to_f(p["η_opt"], 60) / 100;
  const G_opt = 10 * Math.log10(Math.max(eta * Math.pow(Math.PI * D / lam, 2), 1e-9));
  const d_km = kind === "isl" ? to_f(p.d_isl, 5000) : to_f(p.d_dl, 1200);
  const d = d_km * 1000;
  const L_fs_opt = 20 * Math.log10(Math.max(4 * Math.PI * d / lam, 1e-9));
  const th_div = to_f(p["θ_div"], 100), sig_jit = to_f(p["σ_jit"], 3.0);
  const L_point = th_div > 0 ? 12.0 * Math.pow(sig_jit / th_div, 2) : 0;
  const P_tx_w = to_f(p.P_opt, 1.0), P_tx_dbm = w2dbm(P_tx_w);
  const G_edfa = to_f(p.G_edfa, 25), G_edfa_eff = Math.min(G_edfa, 20.0);
  const L_turb = kind === "sgl" ? to_f(p.L_turb, 1.5) : 0;
  const L_atm = kind === "sgl" ? 0.2 : 0;
  const L_opt_sw = 1.5;
  const EIRP_opt = P_tx_dbm + G_edfa_eff + G_opt;
  const P_rx_dbm = EIRP_opt + G_opt - L_fs_opt - L_point - L_turb - L_atm - L_opt_sw;
  let R = to_f(kind === "isl" ? p.R_isl : p.R_sgl, 10);
  R = Math.max(R, 0.01);
  const S_opt = to_f(p.S_opt, -42);
  const P_req = S_opt + 10 * Math.log10(R / 1.0);
  const M = P_rx_dbm - P_req;
  const CN_dpsk = to_f(p.CN_dpsk, 8.0);
  const R_max = M < 100 ? R * Math.pow(10, M / 10) : R;
  const P_acq = to_f(p.P_acq, 97), sig_track = to_f(p["σ_track"], 0.8), t_acq = to_f(p.t_acq, 30);
  const c18 = { P_acq: P_acq, "σ_track": sig_track, t_acq: t_acq,
                ok_acq: P_acq >= 95.0, ok_track: sig_track <= 1.0,
                ok: P_acq >= 95.0 && sig_track <= 1.0 };
  const P_cloud = kind === "sgl" ? to_f(p.P_cloud, 8) : 0;
  return { kind: kind, D_mm: D_mm, lam_nm: lam_nm, G_opt_db: G_opt, d_km: d_km,
           L_fs_opt: L_fs_opt, "θ_div": th_div, "σ_jit": sig_jit, L_point: L_point,
           P_tx_w: P_tx_w, P_tx_dbm: P_tx_dbm, G_edfa: G_edfa, G_edfa_eff: G_edfa_eff,
           EIRP_opt_dbm: EIRP_opt, L_turb: L_turb, L_atm: L_atm, L_opt_sw: L_opt_sw,
           P_rx_dbm: P_rx_dbm, R_gbps: R, S_opt_dbm: S_opt, P_req_dbm: P_req,
           M_db: M, CN_equiv: CN_dpsk + M, CN_dpsk: CN_dpsk, R_max_gbps: R_max,
           c18: c18, P_cloud: P_cloud, avail_pct: 100.0 - P_cloud,
           ok: M >= to_f(p.M_target, 3.0) };
}

/* ---------------- 六、星内数据链 ---------------- */
function data_link(p) {
  const R_pdl = to_f(p.R_pdl, 1200), CR = Math.max(to_f(p.CR, 4), 1.0);
  const R_bus = to_f(p.R_bus, 4000), R_bb = to_f(p.R_bb, 2000), R_dpu = to_f(p.R_dpu, 1500);
  const T_blind = to_f(p.T_blind, 15), E_store = to_f(p.E_store, 4.0);
  const R_need_bus = R_pdl / CR;
  const ok_bus = R_bus >= R_need_bus, ok_bb = R_bb >= R_pdl, ok_dpu = R_dpu >= R_pdl;
  const E_need_tbit = R_pdl * T_blind * 60.0 / CR / 1e6;
  const ok_store = E_store >= E_need_tbit;
  return { c: "c-20", R_pdl: R_pdl, CR: CR, R_bus: R_bus, R_bb: R_bb, R_dpu: R_dpu,
           R_need_bus: R_need_bus, T_blind: T_blind, E_store: E_store,
           E_need_tbit: E_need_tbit, ok_bus: ok_bus, ok_bb: ok_bb, ok_dpu: ok_dpu,
           ok_store: ok_store, ok: ok_bus && ok_bb && ok_dpu && ok_store,
           bus_margin_pct: R_need_bus > 0 ? (R_bus / R_need_bus - 1) * 100 : 0,
           store_margin_pct: E_need_tbit > 0 ? (E_store / E_need_tbit - 1) * 100 : 0 };
}

/* ---------------- 七、系统级约束 ---------------- */
function system_checks(p, ant, eirp, gt, dn, up, laser_isl, laser_sgl, dl_data) {
  const R = [];
  const add = (cid, formula, items, ok, note, sev) =>
    R.push({ id: cid, formula: formula, items: items, ok: !!ok, note: note || "",
             sev: sev || "hard" });
  const N_beam = to_f(p.N_beam, 64), B_beam = to_f(p.B_beam, 125);
  const B_total = to_f(p.B_total, 2500), k_reuse = to_f(p.k_reuse, 4);
  const eta = dn.eta || 0;
  const C_sys_gbps = N_beam * B_beam * eta * k_reuse / 1000;
  const C_req = to_f(p.C_req, 20);
  add("c-12", "C_sys = N_beam × B_beam × η × k_reuse",
      [["N_beam", N_beam, ""], ["B_beam", B_beam, "MHz"], ["η", eta, "bps/Hz"],
       ["k_reuse", k_reuse, "色"], ["C_sys", C_sys_gbps, "Gbps"], ["C_req", C_req, "Gbps"]],
      C_sys_gbps >= C_req,
      "系统容量 " + fmt(C_sys_gbps) + " Gbps " + (C_sys_gbps >= C_req ? "≥" : "<") + " 需求 " + fmt(C_req) + " Gbps");
  const lhs = N_beam * B_beam, rhs = B_total * k_reuse;
  add("c-13", "N_beam × B_beam ≤ B_total × k_reuse",
      [["N_beam×B_beam", lhs, "MHz"], ["B_total×k_reuse", rhs, "MHz"],
       ["占用率", rhs ? lhs / rhs * 100 : 0, "%"]],
      lhs <= rhs,
      lhs <= rhs ? "无频率冲突（ITU-R S.466 指配 / S.1528 限值）" : "频率冲突！需减波束数/带宽或增复用色数");
  const C_sw = to_f(p.C_sw, 100), N_ch = to_f(p.N_ch, 32), B_sub = to_f(p.B_sub, 40), B_trp = to_f(p.B_trp, 1000);
  const C_need = N_beam * B_beam * eta / 1000;
  const ok_sw = C_sw >= C_need, ok_ch = N_ch * B_sub >= B_trp;
  add("c-14", "C_sw ≥ N_beam×B_beam×η 且 N_ch×B_sub ≥ B_trp",
      [["C_sw", C_sw, "Gbps"], ["需求交换容量", C_need, "Gbps"],
       ["N_ch×B_sub", N_ch * B_sub, "MHz"], ["B_trp", B_trp, "MHz"]],
      ok_sw && ok_ch,
      ok_sw && ok_ch ? "DTP 信道化与交换容量覆盖需求"
        : (!ok_sw ? "交换容量瓶颈！" : "") + (!ok_ch ? "；信道化不足！" : ""));
  const I_iso = to_f(p.I_iso, 100), I_trp = to_f(p.I_trp, 85);
  add("c-15", "I_iso ≥ 100dB 且 I_trp ≥ 80dB",
      [["I_iso（收发）", I_iso, "dB"], ["I_trp（舱内）", I_trp, "dB"]],
      I_iso >= 100 && I_trp >= 80,
      (I_iso >= 100 && I_trp >= 80) ? "符合 GJB 151B / MIL-STD-461 / ECSS-E-ST-20C" : "隔离不足，存在自激/互调风险");
  const T_j = to_f(p.T_j, 105), P_out = to_f(p.P_out, 180);
  const eta_pa = to_f(p["η_pa"], 58) / 100;
  const P_dc = eta_pa > 0 ? P_out / eta_pa : 0;
  const P_trp = to_f(p.P_trp, 900);
  const N_el = p.ant_type === "相控阵天线" ? to_f(p.N_el, 0) : 0;
  const P_tr = to_f(p.P_tr, 8.0), P_face = N_el * P_tr;
  add("c-16", "T_j ≤ 125℃ 且 P_dc = P_out/η ≤ P_trp",
      [["T_j", T_j, "℃"], ["P_dc（功放直流）", P_dc, "W"], ["P_trp（分系统预算）", P_trp, "W"],
       ["阵面功耗 N_el×P_tr", P_face, "W"]],
      T_j <= 125 && P_dc <= P_trp,
      "结温 " + (T_j <= 125 ? "达标" : "超限") + "；功放直流功耗 " + fmt(P_dc, 1) + "W " +
      (P_dc <= P_trp ? "≤" : ">") + " 预算 " + fmt(P_trp, 1) + "W");
  const m_sum = ["m_ant", "m_trp", "m_laser", "m_ipu"].reduce((a, k) => a + to_f(p[k], 0), 0);
  const p_sum = ["P_ant", "P_trp", "P_laser", "P_ipu"].reduce((a, k) => a + to_f(p[k], 0), 0);
  const M_budget = to_f(p.M_budget, 480), P_budget = to_f(p.P_budget, 1900);
  const m_marg = M_budget ? (1 - m_sum / M_budget) * 100 : 0;
  const p_marg = P_budget ? (1 - p_sum / P_budget) * 100 : 0;
  add("c-17", "M_pay = Σm_i ≤ M_budget 且 P_pay = ΣP_i ≤ P_budget（裕度≥10%）",
      [["M_pay", m_sum, "kg"], ["M_budget", M_budget, "kg"], ["质量裕度", m_marg, "%"],
       ["P_pay", p_sum, "W"], ["P_budget", P_budget, "W"], ["功耗裕度", p_marg, "%"]],
      m_sum <= M_budget && p_sum <= P_budget && m_marg >= 10 && p_marg >= 10,
      "质量 " + fmt(m_sum, 1) + "/" + fmt(M_budget, 1) + "kg（裕度 " + fmt(m_marg, 1) + "%）、功耗 " +
      fmt(p_sum, 1) + "/" + fmt(P_budget, 1) + "W（裕度 " + fmt(p_marg, 1) + "%）");
  const c18 = ((laser_isl || laser_sgl) || {}).c18;
  if (c18) add("c-18", "P_acq ≥ 95% 且 σ_track ≤ 1μrad",
      [["P_acq", c18.P_acq, "%"], ["σ_track", c18["σ_track"], "μrad"], ["t_acq", c18.t_acq, "s"]],
      c18.ok, c18.ok ? "ATP 建链判据达标" : "ATP 判据不达标");
  [["星间 ISL", laser_isl], ["星地", laser_sgl]].forEach(([lk, res]) => {
    if (res && res.R_gbps > 0)
      add("c-19", "R_laser ≤ f(EIRP_opt, GT_opt, L_fs_opt, L_turb) [" + lk + "]",
        [["EIRP_opt", res.EIRP_opt_dbm, "dBm"], ["L_fs_opt", res.L_fs_opt, "dB"],
         ["L_point", res.L_point, "dB"], ["P_rx", res.P_rx_dbm, "dBm"],
         ["P_req", res.P_req_dbm, "dBm"], ["M", res.M_db, "dB"],
         ["R", res.R_gbps, "Gbps"], ["R_max", res.R_max_gbps, "Gbps"]],
        res.ok, lk + " 激光链路余量 " + fmt(res.M_db) + "dB " +
        (res.ok ? "≥" : "<") + " " + fmt(to_f(p.M_target, 3), 1) + "dB");
  });
  if (dl_data) add("c-20", "R_bus ≥ R_pdl/CR 且 E_store ≥ R_pdl×T_blind/CR",
      [["R_pdl", dl_data.R_pdl, "Mbps"], ["CR", dl_data.CR, ":1"],
       ["R_bus", dl_data.R_bus, "Mbps"], ["需求总线速率", dl_data.R_need_bus, "Mbps"],
       ["E_store", dl_data.E_store, "Tbit"], ["需求存储", dl_data.E_need_tbit, "Tbit"]],
      dl_data.ok,
      "总线裕度 " + fmt(dl_data.bus_margin_pct, 0) + "%、存储裕度 " + fmt(dl_data.store_margin_pct, 0) + "%");
  const N_gap = to_f(p.N_gap, 2), H = to_f(p.H_scheme, 3);
  const ok21 = N_gap <= 2 && H >= 3;
  add("c-21", "N_gap → 0 且 H_scheme → 4",
      [["N_gap", N_gap, "项"], ["H_scheme", H, "级"]], ok21,
      "缺口 " + N_gap + " 项、货架水平 " + H + "（1定制~4飞行继承货架）；" +
      (N_gap > 0 ? "每项缺口须记录需求/风险/研制周期" : "无定制缺口") +
      (ok21 ? "" : "（趋近型目标：建议提升货架化水平，不作硬性拦截）"), "warning");
  const EIRP_req = to_f(p.EIRP_req, 65), GT_req = to_f(p.GT_req, 25);
  const MODE_ORDER = { "单波束": 1, "多波束": 2, "波束跳变": 3, "在轨重构": 4 };
  const Mode = p.Mode || "多波束", Mode_req = p.Mode_req || "多波束";
  const ok_mode = (MODE_ORDER[Mode] || 0) >= (MODE_ORDER[Mode_req] || 0);
  add("c-22", "EIRP_ant ≥ EIRP_req 且 GT_ant ≥ GT_req 且 Mode ⊇ Mode_req",
      [["EIRP_ant", eirp.EIRP, "dBW"], ["EIRP_req", EIRP_req, "dBW"],
       ["GT_ant", gt.GT, "dB/K"], ["GT_req", GT_req, "dB/K"],
       ["Mode", Mode, ""], ["Mode_req", Mode_req, ""]],
      eirp.EIRP >= EIRP_req && gt.GT >= GT_req && ok_mode,
      "EIRP 余 " + fmt(eirp.EIRP - EIRP_req) + "dB、G/T 余 " + fmt(gt.GT - GT_req) + "dB、模式" +
      (ok_mode ? "覆盖" : "不覆盖") + "需求；不满足触发内环换天线（≤3次）");
  const c23 = ant.c23;
  add("c-23", "Δ_amp≤0.5dB 且 Δ_phs≤5° 且 SLL≤−20dB 且 AR≤3dB",
      [["Δ_amp", c23["Δ_amp"], "dB"], ["Δ_phs", c23["Δ_phs"], "°"],
       ["SLL", c23.SLL, "dB"], ["AR", c23.AR, "dB"], ["Δ_cal", c23["Δ_cal"], "dB"]],
      c23.ok, c23.ok ? "满足 ITU-R S.1323 方向图要求" : "旁瓣/轴比/一致性超限");
  const arch = p.arch || "透明转发器";
  const M_dn = dn.M, dM_reg = to_f(p["ΔM_reg"], 4.5), M_target = to_f(p.M_target, 3.0);
  const need_up = M_dn < M_target;
  const lowest = String(dn.modcod).startsWith("QPSK");
  const trig = need_up && lowest && arch === "透明转发器";
  add("c-24", "M < 3dB 且 MODCOD 已最低阶 ⇒ ΔM_reg ≥ 3dB → 改再生/DTP",
      [["当前体制", arch, ""], ["下行余量 M", M_dn, "dB"], ["当前 MODCOD", dn.modcod, ""],
       ["ΔM_reg", dM_reg, "dB"], ["τ_trans", to_f(p["τ_trans"], 200), "ns"],
       ["τ_reg", to_f(p["τ_reg"], 30), "ms"]],
      !trig,
      trig ? "触发体制升级：透明余量不足且已降至最低阶，建议改再生（+" + fmt(dM_reg, 1) + "dB）或 DTP"
        : (!need_up ? "体制 " + arch + " 可闭合（余量 " + fmt(M_dn) + "dB）"
           : "余量 " + fmt(M_dn) + "dB 偏低但 MODCOD 未至最低阶，可先降阶/减带宽"));
  const N_bf = to_f(p.N_bf, 64), N_port = to_f(p.N_port, 64), N_sch = to_f(p.N_sch, 64);
  const ok25 = N_bf >= N_beam && N_port >= N_beam && N_sch >= N_beam;
  add("c-25", "N_bf ≥ N_beam 且 N_port ≥ N_beam 且 N_sch ≥ N_beam",
      [["N_beam", N_beam, ""], ["N_bf", N_bf, ""], ["N_port", N_port, ""], ["N_sch", N_sch, ""]],
      ok25, ok25 ? "波束赋形/端口/调度能力一致" : "能力不足，波束数指标无法实现");
  const c5 = ant.c5;
  add("c-5", "δ_surf ≤ λ/32 且 δ_dep ≤ δ_surf",
      [["λ/32 限值", c5.limit_mm, "mm"], ["δ_surf", c5["δ_surf"], "mm"], ["δ_dep", c5["δ_dep"], "mm"]],
      c5.ok, "面精度限值 " + fmt(c5.limit_mm, 3) + "mm（f=" + fmt(to_f(p.f_down, 20), 1) + "GHz）");
  add("c-6", "L_pnt = 12×(θ_e/θ_3dB)²",
      [["θ_e", ant.c6["θ_e"], "°"], ["θ_3dB", ant.c6["θ_3dB"], "°"], ["L_pnt", ant.c6.L_pnt_db, "dB"]],
      ant.c6.L_pnt_db <= 1.0, "指向损耗 " + fmt(ant.c6.L_pnt_db, 3) + "dB（判据 ≤1.0dB 为宜）");
  if (ant.formula === "c-3")
    add("c-3", "G_pa = 10lg(N_el × η) + G_el − 扫描损耗",
        [["N_el", to_f(p.N_el, 0), ""], ["η", to_f(p["η_ill"], 68), "%"],
         ["G_el", to_f(p.G_el, 6), "dBi"], ["扫描损耗", -(ant.scan_loss_db || 0), "dB"],
         ["G_ant", ant.G_ant, "dBi"]],
        true, "相控阵增益 " + fmt(ant.G_ant) + "dBi（θ_scan=" + fmt(to_f(p["θ_scan"], 0), 0) + "°）");
  else
    add("c-4", "G_refl = 10lg(η(πD/λ)²)，θ_3dB ≈ 70λ/D",
        [["D", ant.D_m, "m"], ["λ", ant.lam_m * 100, "cm"], ["η", to_f(p["η_ill"], 68), "%"],
         ["G_ant", ant.G_ant, "dBi"], ["θ_3dB", ant["θ_3dB"], "°"]],
        true, "反射面增益 " + fmt(ant.G_ant) + "dBi，波束宽度 " + fmt(ant["θ_3dB"], 3) + "°");
  return R;
}

/* ---------------- 八、主入口 ---------------- */
function compute_all(p) {
  const res = { params: p };
  const ant = antenna_electrical(p);
  const flows = {};
  Object.keys(DATA.LINK_META).forEach(lid => {
    const meta = DATA.LINK_META[lid];
    const node = DATA.CHAINS[lid];
    const chain = (node || {}).chain || [];
    if (!chain.length) return;
    const dir = meta.dir === "ctl" ? "both" : meta.dir;
    if (dir === "tx") {
      const f = propagate_tx(chain, p);
      f.meta = { name: node.name, dir: "tx", kind: meta.kind, cat: meta.cat, chain: chain };
      flows[lid] = f;
    } else if (dir === "rx") {
      const f = propagate_rx(chain, p);
      f.meta = { name: node.name, dir: "rx", kind: meta.kind, cat: meta.cat, chain: chain };
      flows[lid] = f;
    } else {
      const ft = propagate_tx(chain, p), fr = propagate_rx(chain, p);
      flows[lid] = { tx: ft, rx: fr,
        meta: { name: node.name, dir: "both", kind: meta.kind, cat: meta.cat, chain: chain } };
    }
  });
  res.flows = flows;
  const tx_ant = flows.ant_tx_path || { stages: [] };
  const eirp = eirp_calc(p, ant, { stages: tx_ant.stages || [] });
  const rx_chain_id = p.ant_type === "相控阵天线" ? "ant_rx_path" : "uplink";
  let rx_flow_sel = flows[rx_chain_id];
  let rx;
  if (rx_flow_sel && rx_flow_sel.T_sys !== undefined) rx = rx_flow_sel;
  else if (rx_flow_sel && rx_flow_sel.rx) rx = rx_flow_sel.rx;
  else rx = propagate_rx((DATA.CHAINS[rx_chain_id] || {}).chain || [], p);
  const gt = gt_calc(p, ant, rx);
  gt.rx_chain_id = rx_chain_id;
  gt.rx_chain_name = (DATA.CHAINS[rx_chain_id] || {}).name || rx_chain_id;
  ant._EIRP = eirp.EIRP; ant._GT = gt.GT;
  res.antenna = ant; res.eirp = eirp; res.gt = gt;
  const dn = rf_link_budget(p, ant, "down"), up = rf_link_budget(p, ant, "up");
  const arch = p.arch || "透明转发器";
  const CN_total = total_cn(up.CN, dn.CN);
  const mc_total = pick_modcod(CN_total, null, to_f(p.M_target, 3.0));
  const M_total = CN_total - (mc_total ? mc_total.cn_req : DATA.MODCOD[0].cn_req);
  const regen_bonus = arch === "再生转发器" ? to_f(p["ΔM_reg"], 4.5) : 0;
  res.uplink = up; res.downlink = dn;
  res.e2e = { arch: arch, CN_up: up.CN, CN_dn: dn.CN, CN_total: CN_total,
              modcod: mc_total ? mc_total.name : "无法闭合",
              eta: mc_total ? mc_total.eta : 0,
              CN_req: mc_total ? mc_total.cn_req : 0,
              M: M_total + regen_bonus, regen_bonus: regen_bonus,
              C_link_gbps: dn.C_link_gbps };
  res.laser_isl = to_f(p.R_isl, 0) > 0 ? laser_link(p, "isl") : null;
  res.laser_sgl = to_f(p.R_sgl, 0) > 0 ? laser_link(p, "sgl") : null;
  res.data = to_f(p.R_pdl, 0) > 0 ? data_link(p) : null;
  res.checks = system_checks(p, ant, eirp, gt, dn, up, res.laser_isl, res.laser_sgl, res.data);
  const info = [];
  info.push({ id: "c-1", formula: "EIRP = P_out + G_ant − L_feed − L_tx", ok: true, sev: "info",
    items: [["P_out", eirp.P_out_dbw, "dBW"], ["G_ant", eirp.G_ant, "dBi"],
            ["L_feed", eirp.L_feed, "dB"], ["L_tx", eirp.L_tx, "dB"], ["EIRP", eirp.EIRP, "dBW"]],
    note: "星上 EIRP = " + fmt(eirp.EIRP) + " dBW（功放 " + fmt(eirp.P_out_w, 0) + "W）" });
  info.push({ id: "c-2", formula: "G/T = G_ant − 10lg(T_ant + T_rx)", ok: true, sev: "info",
    items: [["G_ant", gt.G_ant, "dBi"], ["T_ant", gt.T_ant, "K"], ["T_rx", gt.T_rx, "K"],
            ["T_sys", gt.T_sys, "K"], ["G/T", gt.GT, "dB/K"]],
    note: "接收品质因数 G/T = " + fmt(gt.GT) + " dB/K（" + gt.source + "）" });
  [[up, "上行"], [dn, "下行"]].forEach(([lk, nm]) => {
    info.push({ id: "c-7", formula: "L_fs = 20lg(d) + 20lg(f) − 147.55", ok: true, sev: "info",
      items: [["d", lk.d_km, "km"], ["f", lk.f_ghz, "GHz"], ["L_fs", lk.L_fs, "dB"]],
      note: nm + "自由空间损耗 " + fmt(lk.L_fs) + " dB" });
    info.push({ id: "c-8", formula: "C/N0 = EIRP − L_fs − ΣL + G/T − k", ok: true, sev: "info",
      items: [["EIRP", lk.EIRP, "dBW"], ["L_fs", lk.L_fs, "dB"], ["ΣL", lk.sum_L, "dB"],
              ["G/T", lk.GT, "dB/K"], ["k", K_BOLTZ_DB, "dBW/Hz/K"], ["C/N0", lk.CN0, "dBHz"]],
      note: nm + " C/N0 = " + fmt(lk.CN0) + " dBHz（雨衰 " + fmt(lk.A_rain) + "dB @可用性 " + fmt(lk.avail) + "%）" });
    info.push({ id: "c-9", formula: "C/N = C/N0 − 10lg(B)", ok: true, sev: "info",
      items: [["C/N0", lk.CN0, "dBHz"], ["B", lk.B_mhz, "MHz"], ["C/N", lk.CN, "dB"]],
      note: nm + " C/N = " + fmt(lk.CN) + " dB" });
    const M_t = to_f(p.M_target, 3.0);
    info.push({ id: "c-10", formula: "M = C/N − (C/N)_req ≥ 3dB", ok: lk.M >= M_t,
      items: [["C/N", lk.CN, "dB"], ["MODCOD", lk.modcod, ""], ["(C/N)_req", lk.CN_req, "dB"], ["M", lk.M, "dB"]],
      note: nm + "余量 " + fmt(lk.M) + "dB " + (lk.M >= M_t ? "≥" : "<") + " " + fmt(M_t, 1) + "dB " +
            (lk.M >= M_t ? "闭合" : "不闭合，触发回环"),
      tag: nm });
    info.push({ id: "c-11", formula: "C_link = B × η(MODCOD)", ok: true, sev: "info",
      items: [["B", lk.B_mhz, "MHz"], ["η", lk.eta, "bps/Hz"], ["C_link", lk.C_link_gbps, "Gbps"]],
      note: nm + "链路容量 " + fmt(lk.C_link_gbps, 3) + " Gbps", tag: nm });
  });
  // 合并：每个 id 一条主条目（用于统计），c-10/c-11 另附上/下行两条带 tag 的副本（仅展示）
  const allc = {};
  const extra = [];
  info.forEach(c => {
    if (c.tag) extra.push(c); else allc[c.id] = c;
  });
  res.checks.forEach(c => { allc[c.id] = c; });
  const mains = [], shown = [];
  for (let i = 1; i <= 25; i++) {
    const cid = "c-" + i;
    if (allc[cid]) { mains.push(allc[cid]); shown.push(allc[cid]); }
    extra.filter(e => e.id === cid).forEach(e => shown.push(e));
  }
  // c-10/c-11 主条目缺失时用带 tag 副本兜底（mains 每 id 仅一条，shown 保留上/下行两条）
  ["c-10", "c-11"].forEach(cid => {
    if (!mains.some(c => c.id === cid)) {
      const t = extra.filter(e => e.id === cid);
      if (t.length) mains.push(t[t.length - 1]);
      if (!shown.some(c => c.id === cid)) t.forEach(e => shown.push(e));
    }
  });
  mains.sort((a, b) => parseInt(a.id.slice(2)) - parseInt(b.id.slice(2)));
  shown.sort((a, b) => parseInt(a.id.slice(2)) - parseInt(b.id.slice(2)));
  res.constraints = shown;      // 看板展示（含上/下行副本）
  res._main = mains;            // 统计口径（每 id 一条）
  res.loop = build_loop_advice(p, res);
  const n_pass = mains.filter(c => c.ok).length;
  const JUDGE = ["c-5", "c-6", "c-10", "c-12", "c-13", "c-14", "c-15", "c-16", "c-17",
                 "c-18", "c-19", "c-20", "c-21", "c-22", "c-23", "c-24", "c-25"];
  const judged = mains.filter(c => JUDGE.includes(c.id));
  res.summary = {
    EIRP: eirp.EIRP, GT: gt.GT, G_ant: ant.G_ant, T_sys: gt.T_sys,
    CN0_dn: dn.CN0, CN_dn: dn.CN, M_dn: dn.M, modcod: dn.modcod,
    C_link: dn.C_link_gbps, CN0_up: up.CN0, CN_up: up.CN, M_up: up.M,
    M_e2e: res.e2e.M, C_sys: null,
    pass_count: n_pass, total_count: mains.length,
    judge_pass: judged.filter(c => c.ok).length, judge_total: judged.length,
    fail: mains.filter(c => !c.ok && (c.sev || "hard") === "hard").map(c => c.id),
    warn: mains.filter(c => !c.ok && c.sev === "warning").map(c => c.id)
  };
  const c12 = mains.find(c => c.id === "c-12");
  if (c12) { const it = c12.items.find(x => x[0] === "C_sys"); if (it) res.summary.C_sys = it[1]; }
  return res;
}

/* ---------------- 回环建议 ---------------- */
function build_loop_advice(p, res) {
  const dn = res.downlink, up = res.uplink, e2e = res.e2e;
  const M_t = to_f(p.M_target, 3.0);
  const worst = Math.min(dn.M, up.M, e2e.M);
  if (worst >= M_t)
    return { need: false, worst_M: worst, target: M_t, advice: [], note: "全部链路余量达标，无需回环" };
  const deficit = M_t - worst;
  const adv = [];
  const cur_eta = dn.eta;
  const lower = DATA.MODCOD.filter(m => m.cn_req < dn.CN_req);
  if (lower.length) {
    const best = lower.reduce((a, b) => b.eta > a.eta ? b : a);
    const gain = dn.CN_req - best.cn_req;
    adv.push({ step: "① 降阶调制", action: dn.modcod + " → " + best.name, gain_db: gain,
      cost: "容量 " + fmt(dn.B_mhz * cur_eta / 1000, 3) + " → " + fmt(dn.B_mhz * best.eta / 1000, 3) +
            " Gbps（−" + fmt((1 - best.eta / Math.max(cur_eta, 1e-9)) * 100, 1) + "%）",
      enough: gain >= deficit });
  }
  const B = dn.B_mhz;
  for (const [frac, lbl] of [[0.5, "减半"], [0.25, "减至 1/4"]]) {
    const g = -10 * Math.log10(frac);
    adv.push({ step: "② 减小单载波带宽", action: "B_carrier " + fmt(B, 0) + " → " + fmt(B * frac, 0) + " MHz（" + lbl + "）",
      gain_db: g, cost: "单载波容量同比 −" + fmt((1 - frac) * 100, 0) + "%", enough: g >= deficit });
    if (g >= deficit) break;
  }
  const need_db = deficit;
  const P_out = to_f(p.P_out, 180);
  const P_new = P_out * Math.pow(10, need_db / 10);
  const eta_pa = Math.max(to_f(p["η_pa"], 58) / 100, 1e-6);
  adv.push({ step: "③ 增大功放功率 / 天线口径",
    action: "P_out " + fmt(P_out, 0) + " → " + fmt(P_new, 0) + " W（+" + fmt(need_db) + "dB）",
    gain_db: need_db,
    cost: "直流功耗 " + fmt(P_out / eta_pa, 0) + " → " + fmt(P_new / eta_pa, 0) + " W；热控与供电压力上升（c-16/c-17）",
    enough: true });
  const A_ref = to_f(p.A_dn_ref, 7.0), cur_rain = dn.A_rain;
  for (const tgt of [99.5, 99.0, 98.0]) {
    const new_rain = rain_at_avail(A_ref, tgt, dn.el);
    const g = cur_rain - new_rain;
    if (g > 0) {
      adv.push({ step: "④ 放宽可用性要求", action: "A_avail " + fmt(dn.avail) + "% → " + tgt + "%",
        gain_db: g, cost: "雨衰 " + fmt(cur_rain) + " → " + fmt(new_rain) + " dB；业务可用度下降",
        enough: g >= deficit });
      if (g >= deficit) break;
    }
  }
  if (p.arch === "透明转发器") {
    const dMr = to_f(p["ΔM_reg"], 4.5);
    adv.push({ step: "⑤ 体制升级（c-24）", action: "透明 → 再生/DTP", gain_db: dMr,
      cost: "时延 +" + fmt(to_f(p["τ_reg"], 30), 0) + "ms；功耗/质量上升；基带与路由单机增加",
      enough: dMr >= deficit });
  }
  adv.push({ step: "⑥ 换天线重选（外环 ≤2 次）", action: "增大口径/阵元数或改体制（相控阵↔反射面）",
    gain_db: null, cost: "触发内环平台可行性回环（≤3 次），质量/功耗需重新闭环", enough: false });
  return { need: true, worst_M: worst, target: M_t, deficit: deficit, advice: adv,
           note: "最差链路余量 " + fmt(worst) + "dB < 目标 " + fmt(M_t, 1) + "dB，缺口 " + fmt(deficit) + "dB" };
}
"""

# ================================================================
# 页面 CSS / HTML / 应用 JS
# ================================================================
CSS = r"""
:root{
  --bg:#f4f6fa; --panel:#ffffff; --ink:#1c2733; --muted:#5f7183; --line:#dde5ee;
  --accent:#0b5cad; --accent2:#0a7ea4; --ok:#1d8a4e; --okbg:#e5f5ec;
  --warn:#b07514; --warnbg:#fdf3e0; --bad:#c0392b; --badbg:#fdeae8;
  --info:#4a6fa5; --infobg:#eaf1fa; --chip:#eef3f9;
}
*{box-sizing:border-box;margin:0;padding:0}
html{font-size:14px}
body{background:var(--bg);color:var(--ink);
     font-family:"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;line-height:1.55}
#app{max-width:1560px;margin:0 auto;padding:14px 18px 60px}
header.top{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;
  background:linear-gradient(120deg,#0b3d6e,#0b5cad 55%,#0a7ea4);
  color:#fff;border-radius:12px;padding:16px 22px;margin-bottom:14px}
header.top h1{font-size:1.35rem;letter-spacing:.5px}
header.top .sub{font-size:.82rem;opacity:.85}
header.top .tools{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.btn{border:1px solid rgba(255,255,255,.5);background:rgba(255,255,255,.12);color:#fff;
  border-radius:7px;padding:6px 14px;font-size:.82rem;cursor:pointer;transition:.15s}
.btn:hover{background:rgba(255,255,255,.28)}
.btn.solid{background:#fff;color:var(--accent);border-color:#fff;font-weight:600}
nav.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
nav.tabs button{border:1px solid var(--line);background:var(--panel);color:var(--muted);
  padding:8px 18px;border-radius:9px 9px 0 0;font-size:.9rem;cursor:pointer;border-bottom:none}
nav.tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
section.tab{display:none}
section.tab.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.card .k{font-size:.72rem;color:var(--muted)}
.card .v{font-size:1.28rem;font-weight:700;color:var(--accent)}
.card .v small{font-size:.68rem;font-weight:400;color:var(--muted)}
.card.good .v{color:var(--ok)} .card.bad .v{color:var(--bad)} .card.warn .v{color:var(--warn)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.panel h3{font-size:.98rem;color:var(--accent);margin-bottom:8px;border-left:4px solid var(--accent);padding-left:8px}
.panel h4{font-size:.88rem;color:var(--muted);margin:10px 0 6px}
table{border-collapse:collapse;width:100%;font-size:.82rem}
th,td{border:1px solid var(--line);padding:5px 9px;text-align:left;vertical-align:top}
th{background:var(--chip);color:var(--ink);font-weight:600;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.hl td{background:#f2f8ff}
.tag{display:inline-block;padding:1px 8px;border-radius:9px;font-size:.72rem;font-weight:600}
.tag.ok{background:var(--okbg);color:var(--ok)} .tag.bad{background:var(--badbg);color:var(--bad)}
.tag.warn{background:var(--warnbg);color:var(--warn)} .tag.info{background:var(--infobg);color:var(--info)}
.muted{color:var(--muted);font-size:.78rem}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:1100px){.grid2,.grid3{grid-template-columns:1fr}}
/* 链路流 */
.flowrow{display:flex;flex-wrap:wrap;gap:6px;align-items:stretch;margin:8px 0 4px}
.stage{border:1px solid var(--line);border-radius:8px;background:#fbfdff;min-width:118px;max-width:150px;
  padding:6px 8px;font-size:.72rem;position:relative;cursor:default}
.stage:hover{border-color:var(--accent);box-shadow:0 2px 8px rgba(11,92,173,.15)}
.stage .nm{font-weight:600;color:var(--ink);font-size:.74rem}
.stage .g{color:var(--accent2);font-variant-numeric:tabular-nums}
.stage .pw{color:var(--muted);font-variant-numeric:tabular-nums}
.stage.amp{background:#fff6e8;border-color:#eed9ae}
.stage.dig{background:#eef7f0;border-color:#c3dfcc}
.stage.opt{background:#f3eefb;border-color:#d9c8ef}
.stage.mech{background:#fdf0f0;border-color:#eec9c9}
.stage.ctrl{background:#eef3fa;border-color:#c9d8ec}
.arrow{align-self:center;color:var(--muted);font-size:.9rem}
.stage .tip{display:none;position:absolute;left:0;top:102%;z-index:30;width:260px;background:#20313f;
  color:#e8eef5;border-radius:8px;padding:8px 10px;font-size:.72rem;line-height:1.5;box-shadow:0 6px 18px rgba(0,0,0,.3)}
.stage:hover .tip{display:block}
.linktabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.linktabs button{border:1px solid var(--line);background:var(--panel);color:var(--muted);
  padding:5px 12px;border-radius:16px;font-size:.78rem;cursor:pointer}
.linktabs button.on{background:var(--accent2);border-color:var(--accent2);color:#fff;font-weight:600}
.vsel{display:flex;gap:8px;align-items:center;margin-bottom:4px}
.vsel button{border:1px solid var(--line);background:var(--panel);padding:4px 14px;border-radius:7px;
  font-size:.78rem;cursor:pointer;color:var(--muted)}
.vsel button.on{background:var(--info);border-color:var(--info);color:#fff}
/* 约束看板 */
.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px}
.cbox{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--panel)}
.cbox.ok{border-left:5px solid var(--ok)} .cbox.bad{border-left:5px solid var(--bad)}
.cbox.warnbox{border-left:5px solid var(--warn)} .cbox.infobox{border-left:5px solid var(--info)}
.cbox .cid{font-weight:700;font-size:.85rem}
.cbox .cf{font-family:Consolas,monospace;font-size:.74rem;color:var(--accent2);margin:2px 0 4px}
.cbox .cn{font-size:.76rem;color:var(--muted)}
.cbox details{margin-top:4px}
.cbox summary{font-size:.74rem;color:var(--info);cursor:pointer}
/* 参数面板 */
.pgroup{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;background:var(--panel)}
.pgroup>summary{padding:9px 14px;font-weight:600;color:var(--accent);cursor:pointer;font-size:.9rem;
  list-style:none;display:flex;align-items:center;gap:8px}
.pgroup>summary::before{content:"▸";transition:.2s;color:var(--muted)}
.pgroup[open]>summary::before{transform:rotate(90deg)}
.pgroup .pbody{padding:4px 14px 12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px}
.pitem{display:grid;grid-template-columns:1fr 128px;gap:6px;align-items:center}
.pitem label{font-size:.78rem;color:var(--ink)}
.pitem .hint{font-size:.68rem;color:var(--muted);grid-column:1/-1;margin-top:-4px}
.pitem input,.pitem select{border:1px solid var(--line);border-radius:6px;padding:4px 8px;font-size:.8rem;
  background:#fff;color:var(--ink);width:100%}
.pitem input:focus,.pitem select:focus{outline:2px solid rgba(11,92,173,.25);border-color:var(--accent)}
.presetbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.presetbar select{border:1px solid var(--line);border-radius:7px;padding:7px 10px;font-size:.84rem;background:#fff}
.presetbar .btn{background:var(--accent);border-color:var(--accent)}
.presetbar .btn.ghost{background:var(--panel);color:var(--muted);border-color:var(--line)}
.searchbox{margin-left:auto}
.searchbox input{border:1px solid var(--line);border-radius:7px;padding:7px 12px;font-size:.82rem;width:220px}
.loopbox{border:1px solid #eed9ae;background:#fffaf0;border-radius:10px;padding:12px 14px;margin-bottom:14px}
.loopbox.ok{border-color:#c3dfcc;background:#f4fbf6}
.loopbox h3{color:var(--warn);border:none;padding:0;margin-bottom:6px;font-size:.95rem}
.loopbox.ok h3{color:var(--ok)}
.loopitem{border-top:1px dashed #eed9ae;padding:7px 2px;font-size:.8rem}
.loopitem .en{font-weight:700}
.loopitem .en.yes{color:var(--ok)} .loopitem .en.no{color:var(--bad)}
footer{color:var(--muted);font-size:.74rem;text-align:center;margin-top:26px}
.badge-kg{background:rgba(255,255,255,.18);border-radius:6px;padding:2px 8px;font-size:.72rem}
/* 打印 */
@media print{
  body{background:#fff}
  #app{max-width:100%;padding:0}
  nav.tabs,.presetbar,.tools,.searchbox,.linktabs,.vsel{display:none!important}
  section.tab{display:block!important;page-break-after:always}
  .panel,.card,.cbox{break-inside:avoid}
  header.top{border-radius:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

APP_JS = r"""
'use strict';
let P_ = {};            // 当前参数
let RES = null;         // 当前计算结果
let curTab = "tab-ov";
let curLink = "transparent";
let curView = "tx";

function defaultParams() {
  const d = {};
  DATA.PARAMS.forEach(x => { d[x.sym] = x.def; });
  return d;
}
function applyPreset(key) {
  const pre = DATA.PRESETS[key];
  if (!pre) return;
  P_ = defaultParams();
  Object.assign(P_, pre.values);
  renderAll();
}
function bandPreset(band) {
  const b = DATA.BANDS[band];
  if (!b || band === "激光") return;
  P_.f_up = b.f_up; P_.f_down = b.f_down;
  P_.A_up_ref = b.A_up; P_.A_dn_ref = b.A_dn;
  P_.B_total = b.B_total; P_.k_reuse = String(b.k_reuse);
}

/* ---------- 渲染 ---------- */
function el(id) { return document.getElementById(id); }
function h(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function n(v, nd) { return fmt(v, nd === undefined ? 2 : nd); }

function renderAll() {
  RES = compute_all(P_);
  renderOverview();
  renderBudget();
  renderFlows();
  renderConstraints();
  renderLoop();
  renderParams();
  syncTopbar();
  el("kgver").textContent = (DATA.kg_meta.name || "知识图谱") + " v" + (DATA.kg_meta.version || "?");
}

function kpi(k, v, unit, cls) {
  return '<div class="card ' + (cls || "") + '"><div class="k">' + k + '</div>' +
         '<div class="v">' + v + (unit ? ' <small>' + unit + '</small>' : "") + '</div></div>';
}
function renderOverview() {
  const s = RES.summary, dn = RES.downlink, up = RES.uplink, e2e = RES.e2e;
  let html = '<div class="cards">';
  html += kpi("星上 EIRP（整波束）", n(s.EIRP), "dBW");
  html += kpi("接收 G/T", n(s.GT), "dB/K");
  html += kpi("天线增益 G_ant", n(s.G_ant), "dBi");
  html += kpi("系统噪声温度 T_sys", n(s.T_sys, 1), "K");
  html += kpi("上行 C/N", n(s.CN_up), "dB", s.M_up >= to_f(P_.M_target, 3) ? "good" : "bad");
  html += kpi("下行 C/N", n(s.CN_dn), "dB", s.M_dn >= to_f(P_.M_target, 3) ? "good" : "bad");
  html += kpi("下行 MODCOD", h(s.modcod), "");
  html += kpi("端到端余量", n(s.M_e2e), "dB", s.M_e2e >= to_f(P_.M_target, 3) ? "good" : "bad");
  html += kpi("单载波容量", n(s.C_link, 3), "Gbps");
  html += kpi("系统容量 C_sys", s.C_sys !== null ? n(s.C_sys, 1) : "—", "Gbps");
  const jt = s.judge_total, jp = s.judge_pass;
  html += kpi("判据约束通过", jp + " / " + jt, "", jp === jt ? "good" : (s.fail.length ? "bad" : "warn"));
  html += kpi("信息流链路", Object.keys(RES.flows).length + " 条", "");
  html += '</div>';
  // 激光 / 数据链小卡
  if (RES.laser_isl || RES.laser_sgl) {
    html += '<div class="panel"><h3>激光链路</h3><table><tr><th>链路</th><th>速率</th><th>EIRP_opt</th>' +
            '<th>L_fs</th><th>指向代价</th><th>P_rx</th><th>P_req</th><th>余量 M</th><th>ATP</th><th>判定</th></tr>';
    [["星间 ISL", RES.laser_isl], ["星地 SGL", RES.laser_sgl]].forEach(([nm, r]) => {
      if (!r) return;
      html += '<tr><td>' + nm + '</td><td class="num">' + n(r.R_gbps, 1) + ' Gbps</td>' +
        '<td class="num">' + n(r.EIRP_opt_dbm, 1) + ' dBm</td><td class="num">' + n(r.L_fs_opt, 1) + ' dB</td>' +
        '<td class="num">' + n(r.L_point, 2) + ' dB</td><td class="num">' + n(r.P_rx_dbm, 1) + ' dBm</td>' +
        '<td class="num">' + n(r.P_req_dbm, 1) + ' dBm</td><td class="num">' + n(r.M_db) + ' dB</td>' +
        '<td>' + (r.c18.ok ? '<span class="tag ok">达标</span>' : '<span class="tag bad">不达标</span>') + '</td>' +
        '<td>' + (r.ok ? '<span class="tag ok">闭合</span>' : '<span class="tag bad">不闭合</span>') + '</td></tr>';
    });
    html += '</table></div>';
  }
  if (RES.data) {
    const d = RES.data;
    html += '<div class="panel"><h3>星内数据链路（c-20）</h3><table><tr>' +
      '<th>数据产生率 R_pdl</th><th>压缩比 CR</th><th>总线需求</th><th>总线速率 R_bus</th>' +
      '<th>存储需求</th><th>存储容量 E_store</th><th>判定</th></tr><tr>' +
      '<td class="num">' + n(d.R_pdl, 0) + ' Mbps</td><td class="num">' + n(d.CR, 0) + ':1</td>' +
      '<td class="num">' + n(d.R_need_bus, 0) + ' Mbps</td><td class="num">' + n(d.R_bus, 0) + ' Mbps</td>' +
      '<td class="num">' + n(d.E_need_tbit, 2) + ' Tbit</td><td class="num">' + n(d.E_store, 1) + ' Tbit</td>' +
      '<td>' + (d.ok ? '<span class="tag ok">闭合</span>' : '<span class="tag bad">不闭合</span>') + '</td>' +
      '</tr></table></div>';
  }
  // 端到端
  html += '<div class="panel"><h3>端到端链路（' + h(e2e.arch) + '）</h3><table>' +
    '<tr><th>体制</th><th>上行 C/N</th><th>下行 C/N</th><th>合成 C/N</th><th>MODCOD</th>' +
    '<th>再生增益</th><th>端到端余量</th></tr><tr>' +
    '<td>' + h(e2e.arch) + '</td><td class="num">' + n(e2e.CN_up) + ' dB</td>' +
    '<td class="num">' + n(e2e.CN_dn) + ' dB</td><td class="num">' + n(e2e.CN_total) + ' dB</td>' +
    '<td>' + h(e2e.modcod) + '</td><td class="num">+' + n(e2e.regen_bonus, 1) + ' dB</td>' +
    '<td class="num">' + n(e2e.M) + ' dB</td></tr></table>' +
    '<div class="muted" style="margin-top:6px">注：知识图谱 c-7 描述中“GEO 约 205dB@30GHz”为笔误，' +
    '205dB 对应约 12GHz；30GHz GEO 斜距实际约 213.6dB。本软件按标准公式 L_fs=20lg(d)+20lg(f)−147.55 计算。</div></div>';
  el("ov").innerHTML = html;
}

function budgetRows(lk, nm) {
  const rows = [
    ["频率 f", n(lk.f_ghz, 1) + " GHz"],
    ["斜距 d", n(lk.d_km, 0) + " km"],
    ["EIRP（" + (lk.direction === "up" ? "关口站单载波" : "单载波，整波束 " + n(lk.EIRP_total) + "dBW ÷ " + n(lk.N_carrier, 1) + " 载波") + "）", n(lk.EIRP) + " dBW"],
    ["自由空间损耗 L_fs（c-7）", "−" + n(lk.L_fs) + " dB"],
    ["雨衰 A(p)（可用性 " + n(lk.avail, 2) + "%，仰角 " + n(lk.el, 0) + "°）", "−" + n(lk.A_rain) + " dB"],
    ["大气吸收", "−" + n(lk.A_atm) + " dB"],
    ["指向损耗 L_pnt（c-6）", "−" + n(lk.L_pnt, 3) + " dB"],
    ["极化失配", "−" + n(lk.L_pol, 1) + " dB"],
    ["实现损耗", "−" + n(lk.L_impl, 1) + " dB"],
    ["接收 G/T（" + lk.gt_sym + "）", n(lk.GT) + " dB/K"],
    ["玻尔兹曼常数 k", "−228.6 dBW/Hz/K"],
    ["C/N0（c-8）", n(lk.CN0) + " dBHz"],
    ["噪声带宽 B（单载波）", n(lk.B_mhz, 0) + " MHz"],
    ["C/N（c-9）", n(lk.CN) + " dB"],
    ["MODCOD 自适应（c-11）", lk.modcod + "（η=" + n(lk.eta) + " bps/Hz，门限 " + n(lk.CN_req, 1) + "dB）"],
    ["余量 M（c-10，目标 ≥" + n(to_f(P_.M_target, 3), 1) + "dB）", n(lk.M) + " dB"],
    ["单载波容量（c-11）", n(lk.C_link_gbps, 3) + " Gbps"],
    ["整波束容量", n(lk.C_beam_gbps, 3) + " Gbps"],
  ];
  let html = '<div class="panel"><h3>' + nm + '链路预算</h3><table>';
  rows.forEach((r, i) => {
    const cls = ["C/N（c-9）", "余量 M（c-10，目标 ≥" + n(to_f(P_.M_target, 3), 1) + "dB）"].includes(r[0]) ? ' class="hl"' : "";
    html += '<tr' + cls + '><td>' + r[0] + '</td><td class="num">' + r[1] + '</td></tr>';
  });
  const M_t = to_f(P_.M_target, 3);
  html += '</table><div style="margin-top:6px">' +
    (lk.M >= M_t ? '<span class="tag ok">链路闭合</span>' : '<span class="tag bad">余量不足，见回环建议</span>') +
    '</div></div>';
  return html;
}
function renderBudget() {
  el("budget").innerHTML =
    '<div class="grid2">' + budgetRows(RES.uplink, "上行（馈电）") + budgetRows(RES.downlink, "下行（用户）") + '</div>';
}

/* ---------- 信息流可视化 ---------- */
const KIND_CLS = { amp: "amp", pass: "", dig: "dig", opt: "opt", mech: "mech", ctrl: "ctrl" };
function stageCard(s, mode) {
  const specs = Object.entries(s.specs || {}).map(([k, v]) => k + "=" + v).join("，");
  let body;
  if (mode === "tx") {
    body = '<div class="g">' + (s.g_db >= 0 ? "+" : "") + n(s.g_db) + ' dB</div>' +
           '<div class="pw">' + n(s.p_in) + ' → ' + n(s.p_out) + ' dBW</div>';
  } else {
    body = '<div class="g">NF ' + n(s.nf_db, 1) + ' dB</div>' +
           '<div class="pw">T_dev=' + n(s.T_dev, 1) + 'K<br>贡献 ' + n(s.T_contrib, 3) + 'K<br>cumG ' +
           (s.cum_g_db >= 0 ? "+" : "") + n(s.cum_g_db, 1) + 'dB</div>';
  }
  const tip = '<div class="tip"><b>' + h(s.cn) + '</b>（' + h(s.id) + ' · ' + h(s.kind) + '）<br>' +
    h(s.note || "") + (specs ? '<br>规格: ' + h(specs) : "") +
    (s.p_w ? '<br>功耗 ' + n(s.p_w, 1) + 'W' : "") + (s.m_kg ? ' · 质量 ' + n(s.m_kg, 2) + 'kg' : "") + '</div>';
  return '<div class="stage ' + (KIND_CLS[s.kind] || "") + '">' +
    '<div class="nm">' + s.seq + '. ' + h(s.cn) + '</div>' + body + tip + '</div>';
}
function flowStrip(stages, mode) {
  let html = '<div class="flowrow">';
  stages.forEach((s, i) => {
    if (i) html += '<div class="arrow">→</div>';
    html += stageCard(s, mode);
  });
  html += '</div>';
  return html;
}
function renderFlows() {
  const links = Object.keys(RES.flows);
  if (!links.includes(curLink)) curLink = links[0];
  let tabs = '<div class="linktabs">';
  links.forEach(lid => {
    const f = RES.flows[lid];
    tabs += '<button class="' + (lid === curLink ? "on" : "") + '" onclick="pickLink(\'' + lid + '\')">' +
      h(f.meta.name) + '</button>';
  });
  tabs += '</div>';
  const f = RES.flows[curLink];
  let body = '<div class="muted">' + h(f.meta.cat) + ' · ' + h(DATA.CHAINS[curLink].desc || "") + '</div>';
  if (f.meta.dir === "both") {
    body += '<div class="vsel" style="margin-top:8px"><span class="muted">视图：</span>' +
      '<button class="' + (curView === "tx" ? "on" : "") + '" onclick="pickView(\'tx\')">发射视图（逐级功率）</button>' +
      '<button class="' + (curView === "rx" ? "on" : "") + '" onclick="pickView(\'rx\')">接收视图（Friis 噪声级联）</button></div>';
    if (curView === "tx") {
      body += flowStrip(f.tx.stages, "tx");
      body += '<div class="muted">出口功率 ' + n(f.tx.p_exit_dbw) + ' dBW · 累计插损 ' + n(f.tx.total_loss_db) +
        ' dB · 功放级按饱和输出功率置电平</div>';
    } else {
      body += flowStrip(f.rx.stages, "rx");
      body += '<div class="muted">T_sys = ' + n(f.rx.T_sys, 1) + ' K · 总噪声系数 ' + n(f.rx.NF_total_db) +
        ' dB（天线口 T_ant=' + n(f.rx.T_ant, 0) + 'K 起算）</div>';
    }
  } else if (f.meta.dir === "tx") {
    body += flowStrip(f.stages, "tx");
    body += '<div class="muted">出口功率 ' + n(f.p_exit_dbw) + ' dBW · 累计插损 ' + n(f.total_loss_db) + ' dB</div>';
  } else {
    body += flowStrip(f.stages, "rx");
    body += '<div class="muted">T_sys = ' + n(f.T_sys, 1) + ' K · 总噪声系数 ' + n(f.NF_total_db) + ' dB</div>';
  }
  el("flows").innerHTML = tabs + '<div class="panel">' + body + '</div>';
}
function pickLink(lid) { curLink = lid; curView = "tx"; renderFlows(); }
function pickView(v) { curView = v; renderFlows(); }

/* ---------- 约束看板 ---------- */
function renderConstraints() {
  const kgMap = {};
  DATA.CONSTRAINTS_KG.forEach(c => { kgMap[c.id] = c; });
  let html = '<div class="cgrid">';
  RES.constraints.forEach(c => {
    const sev = c.sev || "hard";
    let cls, tag;
    if (c.ok && sev === "info") { cls = "infobox"; tag = '<span class="tag info">信息项</span>'; }
    else if (c.ok) { cls = "ok"; tag = '<span class="tag ok">通过</span>'; }
    else if (sev === "warning") { cls = "warnbox"; tag = '<span class="tag warn">警告</span>'; }
    else { cls = "bad"; tag = '<span class="tag bad">不通过</span>'; }
    const kgc = kgMap[c.id] || {};
    let items = "";
    (c.items || []).forEach(it => {
      const v = typeof it[1] === "number" ? n(it[1], Math.abs(it[1]) >= 100 ? 1 : 3) : h(it[1]);
      items += '<tr><td>' + h(it[0]) + '</td><td class="num">' + v + '</td><td>' + h(it[2] || "") + '</td></tr>';
    });
    html += '<div class="cbox ' + cls + '"><div class="cid">' + c.id +
      (c.tag ? '（' + h(c.tag) + '）' : "") + ' ' + tag + '</div>' +
      '<div class="cf">' + h(c.formula) + '</div>' +
      '<div class="cn">' + h(c.note || "") + '</div>' +
      (kgc.description ? '<details><summary>知识图谱释义</summary><div class="cn">' + h(kgc.description) + '</div></details>' : "") +
      (items ? '<details><summary>计算明细</summary><table>' + items + '</table></details>' : "") +
      '</div>';
  });
  html += '</div>';
  el("cons").innerHTML = html;
}

/* ---------- 回环建议 ---------- */
function renderLoop() {
  const lp = RES.loop;
  if (!lp.need) {
    el("loop").innerHTML = '<div class="loopbox ok"><h3>回环状态：无需回环</h3>' +
      '<div class="muted">' + h(lp.note) + '（最差余量 ' + n(lp.worst_M) + 'dB ≥ 目标 ' + n(lp.target, 1) + 'dB）</div></div>';
    return;
  }
  let html = '<div class="loopbox"><h3>⚠ 触发回环：' + h(lp.note) + '</h3>';
  lp.advice.forEach(a => {
    html += '<div class="loopitem"><b>' + h(a.step) + '</b>：' + h(a.action) +
      ' → 增益 ' + (a.gain_db === null ? "?" : "+" + n(a.gain_db) + "dB") +
      ' <span class="en ' + (a.enough ? "yes" : "no") + '">[' + (a.enough ? "足够闭合" : "不足") + ']</span>' +
      '<div class="muted">代价：' + h(a.cost) + '</div></div>';
  });
  html += '<div class="muted" style="margin-top:6px">回环规则：外环（链路参数调整）≤2 次 → 内环（换天线/平台可行性）≤3 次；' +
    '体制升级判据见 c-24。</div></div>';
  el("loop").innerHTML = html;
}

/* ---------- 参数面板 ---------- */
function renderParams() {
  const q = (el("psearch") ? el("psearch").value : "").trim().toLowerCase();
  let html = "";
  DATA.PARAM_GROUPS.forEach(g => {
    const ps = DATA.PARAMS.filter(x => x.group === g &&
      (!q || x.sym.toLowerCase().includes(q) || x.label.toLowerCase().includes(q) ||
       (x.note || "").toLowerCase().includes(q)));
    if (!ps.length) return;
    html += '<details class="pgroup" ' + (q ? "open" : "") + '><summary>' + g +
      '<span class="muted">（' + ps.length + ' 项）</span></summary><div class="pbody">';
    ps.forEach(x => {
      const v = P_[x.sym];
      let inp;
      if (x.kind === "select") {
        inp = '<select data-sym="' + x.sym + '">';
        (x.options || []).forEach(o => {
          inp += '<option value="' + h(o) + '"' + (String(v) === String(o) ? " selected" : "") + '>' + h(o) + '</option>';
        });
        inp += '</select>';
      } else {
        inp = '<input type="number" step="any" data-sym="' + x.sym + '" value="' +
          (v === "" || v === undefined || v === null ? "" : v) + '">';
      }
      html += '<div class="pitem"><label title="' + h(x.note || "") + '">' + h(x.label) +
        (x.unit ? ' <span class="muted">(' + h(x.unit) + ')</span>' : "") + '</label>' + inp +
        (x.note ? '<div class="hint">' + h(x.sym) + ' · ' + h(x.note) + '</div>' : "") + '</div>';
    });
    html += '</div></details>';
  });
  el("params").innerHTML = html;
  document.querySelectorAll("#params [data-sym]").forEach(node => {
    node.addEventListener("change", onParamChange);
    node.addEventListener("input", debounceParam);
  });
}
let _deb = null;
function debounceParam(e) {
  clearTimeout(_deb);
  const node = e.target;
  _deb = setTimeout(() => onParamChange({ target: node }), 350);
}
function onParamChange(e) {
  const sym = e.target.dataset.sym;
  const raw = e.target.value;
  const meta = DATA.PARAMS.find(x => x.sym === sym);
  P_[sym] = meta && meta.kind === "num" ? (raw === "" ? "" : raw) : raw;
  if (sym === "band") bandPreset(P_.band);
  // 局部刷新（不重渲染参数面板，避免输入焦点丢失）
  RES = compute_all(P_);
  renderOverview(); renderBudget(); renderFlows(); renderConstraints(); renderLoop();
  syncTopbar();
}
function syncTopbar() {
  const s = RES.summary;
  el("tb-eirp").textContent = n(s.EIRP) + " dBW";
  el("tb-gt").textContent = n(s.GT) + " dB/K";
  el("tb-m").textContent = n(s.M_dn) + " dB";
  const badge = el("tb-badge");
  if (s.fail.length) { badge.className = "tag bad"; badge.textContent = "硬性不通过 " + s.fail.join(" "); }
  else if (s.warn.length) { badge.className = "tag warn"; badge.textContent = "警告 " + s.warn.join(" "); }
  else { badge.className = "tag ok"; badge.textContent = "全部约束闭合"; }
}

/* ---------- Tab ---------- */
function showTab(id) {
  curTab = id;
  document.querySelectorAll("nav.tabs button").forEach(b =>
    b.classList.toggle("on", b.dataset.tab === id));
  document.querySelectorAll("section.tab").forEach(s =>
    s.classList.toggle("on", s.id === id));
}

/* ---------- DOC / 打印 ---------- */
function buildReportHTML() {
  const s = RES.summary;
  let rows = "";
  RES._main.forEach(c => {
    rows += '<tr><td>' + c.id + '</td><td>' + h(c.formula) + '</td><td>' +
      (c.ok ? "通过" : (c.sev === "warning" ? "警告" : "不通过")) + '</td><td>' + h(c.note || "") + '</td></tr>';
  });
  return '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">' +
    '<head><meta charset="utf-8"><title>载荷信息流仿真计算报告</title>' +
    '<style>body{font-family:"宋体",SimSun,serif;font-size:12pt;line-height:1.6}' +
    'h1{font-family:"黑体",SimHei;font-size:16pt;text-align:center}' +
    'h2{font-family:"黑体",SimHei;font-size:14pt;margin-top:14pt}' +
    'table{border-collapse:collapse;width:100%;font-size:10.5pt}' +
    'td,th{border:1px solid #666;padding:3px 6px}th{background:#e8eef6}</style></head><body>' +
    '<h1>通信有效载荷信息流仿真计算报告</h1>' +
    '<p style="text-align:center">生成时间：' + new Date().toLocaleString("zh-CN") +
    '　|　依据：' + h(DATA.kg_meta.name || "通信有效载荷知识图谱") + ' v' + h(DATA.kg_meta.version || "") + '</p>' +
    '<h2>一、关键指标</h2><table>' +
    '<tr><th>指标</th><th>数值</th><th>指标</th><th>数值</th></tr>' +
    '<tr><td>星上 EIRP</td><td>' + n(s.EIRP) + ' dBW</td><td>接收 G/T</td><td>' + n(s.GT) + ' dB/K</td></tr>' +
    '<tr><td>天线增益</td><td>' + n(s.G_ant) + ' dBi（' + h(RES.antenna.ant_type) + '）</td>' +
    '<td>系统噪声温度</td><td>' + n(s.T_sys, 1) + ' K</td></tr>' +
    '<tr><td>上行 C/N 及余量</td><td>' + n(s.CN_up) + ' dB / ' + n(s.M_up) + ' dB</td>' +
    '<td>下行 C/N 及余量</td><td>' + n(s.CN_dn) + ' dB / ' + n(s.M_dn) + ' dB</td></tr>' +
    '<tr><td>下行 MODCOD</td><td>' + h(s.modcod) + '</td><td>端到端余量（' + h(RES.e2e.arch) + '）</td>' +
    '<td>' + n(s.M_e2e) + ' dB</td></tr>' +
    '<tr><td>单载波容量</td><td>' + n(s.C_link, 3) + ' Gbps</td><td>系统容量</td>' +
    '<td>' + (s.C_sys !== null ? n(s.C_sys, 1) + ' Gbps' : '—') + '</td></tr>' +
    '<tr><td>判据约束</td><td>' + s.judge_pass + '/' + s.judge_total + ' 通过</td>' +
    '<td>硬性不通过 / 警告</td><td>' + (s.fail.join(" ") || "无") + ' / ' + (s.warn.join(" ") || "无") + '</td></tr>' +
    '</table>' +
    '<h2>二、约束校验明细（c-1 ~ c-25）</h2><table>' +
    '<tr><th>约束</th><th>判据/公式</th><th>结果</th><th>说明</th></tr>' + rows + '</table>' +
    (RES.loop.need ? '<h2>三、回环建议</h2><p>' + h(RES.loop.note) + '</p><table>' +
      RES.loop.advice.map(a => '<tr><td>' + h(a.step) + '</td><td>' + h(a.action) + '</td><td>' +
        (a.gain_db === null ? "?" : "+" + n(a.gain_db) + "dB") + (a.enough ? "（足够）" : "（不足）") + '</td><td>' +
        h(a.cost) + '</td></tr>').join("") + '</table>' : '<h2>三、回环建议</h2><p>全部链路余量达标，无需回环。</p>') +
    '<h2>' + (RES.loop.need ? "四" : "三") + '、主要参数</h2><table>' +
    '<tr><th>参数</th><th>取值</th><th>参数</th><th>取值</th></tr>' +
    (function () {
      const ps = DATA.PARAMS.filter(x => P_[x.sym] !== "" && P_[x.sym] !== undefined);
      let out = "";
      for (let i = 0; i < ps.length; i += 2) {
        const a = ps[i], b = ps[i + 1];
        out += '<tr><td>' + h(a.label) + '（' + a.sym + '）</td><td>' + h(String(a.unit ? P_[a.sym] + " " + a.unit : P_[a.sym])) + '</td>' +
          (b ? '<td>' + h(b.label) + '（' + b.sym + '）</td><td>' + h(String(b.unit ? P_[b.sym] + " " + b.unit : P_[b.sym])) + '</td>'
             : '<td></td><td></td>') + '</tr>';
      }
      return out;
    })() + '</table>' +
    '<p style="margin-top:12pt;font-size:9pt;color:#666">注：知识图谱 c-7 描述“GEO 约 205dB@30GHz”为笔误（205dB 对应约 12GHz，30GHz 实际约 213.6dB），' +
    '本报告按标准公式计算。C/N 噪声带宽取单载波带宽 B_carrier，下行星上 EIRP 按载波数折算。</p>' +
    '</body></html>';
}
function downloadDoc() {
  const blob = new Blob(["\ufeff", buildReportHTML()], { type: "application/msword;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "载荷信息流仿真计算报告_" + new Date().toISOString().slice(0, 10) + ".doc";
  a.click();
  URL.revokeObjectURL(a.href);
}
function printPdf() {
  // 打印前展开全部 tab
  document.querySelectorAll("section.tab").forEach(s => s.style.display = "block");
  window.print();
  document.querySelectorAll("section.tab").forEach(s => s.style.display = "");
}

/* ---------- 初始化 ---------- */
window.addEventListener("DOMContentLoaded", () => {
  applyPreset("geo_ka_hts");
  syncTopbar();
  document.querySelectorAll("nav.tabs button").forEach(b =>
    b.addEventListener("click", () => showTab(b.dataset.tab)));
  el("presetSel").addEventListener("change", e => {
    applyPreset(e.target.value); syncTopbar();
  });
  el("psearch").addEventListener("input", renderParams);
  el("btnReset").addEventListener("click", () => {
    applyPreset(el("presetSel").value); syncTopbar();
  });
  el("btnDoc").addEventListener("click", downloadDoc);
  el("btnPrint").addEventListener("click", printPdf);
  showTab("tab-ov");
});
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>载荷信息流仿真计算器 · 通信有效载荷知识图谱</title>
<style>__CSS__</style>
</head>
<body>
<div id="app">
  <header class="top">
    <div>
      <h1>载荷信息流仿真计算器</h1>
      <div class="sub">通信有效载荷 · 信号流逐级仿真 × 25 条工程约束闭环校验 ·
        <span class="badge-kg" id="kgver">知识图谱</span></div>
    </div>
    <div class="tools">
      <span class="sub" style="align-self:center">EIRP <b id="tb-eirp">—</b> ｜ G/T <b id="tb-gt">—</b>
        ｜ 下行余量 <b id="tb-m">—</b> ｜ <span class="tag ok" id="tb-badge">—</span></span>
      <button class="btn solid" id="btnDoc">⬇ 下载 DOC 报告</button>
      <button class="btn" id="btnPrint">🖨 打印 / PDF</button>
    </div>
  </header>

  <div class="presetbar">
    <b>场景预设：</b>
    <select id="presetSel">
      <option value="geo_ka_hts">GEO Ka 高通量（多波束 · DTP）</option>
      <option value="geo_ku_single">GEO Ku 单波束（透明转发）</option>
      <option value="leo_broadband">LEO 宽带星座（相控阵 · 再生 · 激光 ISL）</option>
      <option value="leo_d2d">LEO L 波段手机直连 D2D</option>
    </select>
    <button class="btn ghost" id="btnReset">↺ 恢复预设</button>
    <span class="muted" style="align-self:center">改动任一参数即实时重算全部信息流与约束</span>
    <div class="searchbox"><input id="psearch" placeholder="🔍 搜索参数（符号/名称/说明）"></div>
  </div>

  <nav class="tabs">
    <button data-tab="tab-ov" class="on">概览 KPI</button>
    <button data-tab="tab-budget">链路预算</button>
    <button data-tab="tab-flow">信息流（15 链路）</button>
    <button data-tab="tab-cons">约束看板（c-1~c-25）</button>
    <button data-tab="tab-param">参数面板</button>
  </nav>

  <section class="tab on" id="tab-ov"><div id="loop"></div><div id="ov"></div></section>
  <section class="tab" id="tab-budget"><div id="budget"></div></section>
  <section class="tab" id="tab-flow"><div id="flows"></div></section>
  <section class="tab" id="tab-cons"><div id="cons"></div></section>
  <section class="tab" id="tab-param"><div id="params"></div></section>

  <footer>
    载荷信息流仿真计算器 · 基于《__KGNAME__》v__KGVER__（__NONT__ 本体 / __NATTR__ 属性 / __NCON__ 约束 / __NREL__ 关系）生成 ·
    计算模型：chain 逐级信号流（Friis 噪声级联） + DVBS2X MODCOD 自适应 + 雨衰 A(p)∝p^−0.6 + 激光灵敏度模型 ·
    单机默认值为工程典型值，仅用于方案级论证，正式设计以详细链路预算为准
  </footer>
</div>
<script>const DATA = __DATA__;</script>
<script>__ENGINE__</script>
<script>__APP__</script>
</body>
</html>
"""

html = (HTML.replace("__CSS__", CSS)
        .replace("__DATA__", data_js)
        .replace("__ENGINE__", ENGINE_JS)
        .replace("__APP__", APP_JS)
        .replace("__KGNAME__", kg.get("name", "通信有效载荷知识图谱"))
        .replace("__KGVER__", str(kg.get("version", "")))
        .replace("__NONT__", str(len(kg.get("ontologies", []))))
        .replace("__NATTR__", str(len(kg.get("attributes", []))))
        .replace("__NCON__", str(len(kg.get("constraints", []))))
        .replace("__NREL__", str(len(kg.get("relations", [])))))

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print("HTML written:", OUT)
print("size: %.1f KB" % (len(html.encode("utf-8")) / 1024))
print("chains embedded:", len(chains))
print("constraints embedded:", len(constraints_kg))
