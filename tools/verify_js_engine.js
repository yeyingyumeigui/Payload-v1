// 从生成的 HTML 中提取 DATA + ENGINE JS，在 Node 中跑 4 预设，输出关键指标供与 Python 冒烟结果比对
const fs = require("fs");
const html = fs.readFileSync("D:/ZWL/文生载荷Workbuddy/output/载荷信息流仿真计算器.html", "utf-8");

const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (blocks.length < 3) throw new Error("expect 3 script blocks, got " + blocks.length);
const dataSrc = blocks[0];    // const DATA = {...};
const engineSrc = blocks[1];  // 引擎

// 一次性在函数作用域内 eval（DATA 与引擎共享闭包），导出 API
const api = eval("(function(){" + dataSrc + "\n" + engineSrc +
  "\nreturn {DATA, compute_all, fspl, pick_modcod, rain_at_avail};})()");
const { DATA, compute_all, fspl, pick_modcod, rain_at_avail } = api;

const out = [];
function p(s) { out.push(s); }

// 基础自检
p("FSPL(38000,20)=" + fspl(38000, 20).toFixed(3) + " (期望 210.066)");
p("FSPL(38000,30)=" + fspl(38000, 30).toFixed(2) + " (期望 213.59)");
const mc = pick_modcod(16.5);
p("MODCOD(16.5)=" + (mc ? mc.name : "None") + " (期望 32APSK 5/6, 含 m_target=3 时)");
p("rain(7,99.9,30)=" + rain_at_avail(7.0, 99.9, 30).toFixed(2) + " (期望 1.76)");

// 4 预设
const defaults = {};
DATA.PARAMS.forEach(x => { defaults[x.sym] = x.def; });
for (const key of Object.keys(DATA.PRESETS)) {
  const vals = Object.assign({}, defaults, DATA.PRESETS[key].values);
  const r = compute_all(vals);
  const s = r.summary;
  p("");
  p("### " + DATA.PRESETS[key].label);
  p("  G_ant=" + s.G_ant.toFixed(2) + " T_sys=" + s.T_sys.toFixed(1) +
    " EIRP=" + s.EIRP.toFixed(2) + " GT=" + s.GT.toFixed(2));
  p("  上行 CN0=" + s.CN0_up.toFixed(2) + " CN=" + s.CN_up.toFixed(2) + " M=" + s.M_up.toFixed(2));
  p("  下行 CN0=" + s.CN0_dn.toFixed(2) + " CN=" + s.CN_dn.toFixed(2) + " M=" + s.M_dn.toFixed(2) + " " + s.modcod);
  p("  e2e M=" + s.M_e2e.toFixed(2) + " C_link=" + s.C_link.toFixed(3) + " C_sys=" + s.C_sys);
  if (r.laser_isl) p("  ISL M=" + r.laser_isl.M_db.toFixed(2) + " P_rx=" + r.laser_isl.P_rx_dbm.toFixed(1) + " ATP=" + r.laser_isl.c18.ok);
  p("  flows=" + Object.keys(r.flows).length + " 约束=" + s.pass_count + "/" + s.total_count +
    " 判据=" + s.judge_pass + "/" + s.judge_total + " fail=[" + s.fail + "] warn=[" + s.warn + "]");
  p("  loop.need=" + r.loop.need + (r.loop.need ? " deficit=" + r.loop.deficit.toFixed(2) : ""));
}

fs.writeFileSync("D:/ZWL/文生载荷Workbuddy/tools/_js_verify.txt", out.join("\n"), "utf-8");
console.log("js verify written, lines=" + out.length);

// APP 层 JS 语法检查（不执行，仅解析）
try {
  new Function(blocks[2]);
  console.log("APP_JS syntax OK, length=" + blocks[2].length);
} catch (e) {
  console.log("APP_JS SYNTAX ERROR: " + e.message);
}
// DATA/ENGINE 块完整性
console.log("script blocks: " + blocks.length +
  " | DATA bytes=" + blocks[0].length + " | ENGINE bytes=" + blocks[1].length);
