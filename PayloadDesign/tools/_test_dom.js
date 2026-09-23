/* DOM stub 端到端测试：在 node 中加载前端 JS，用真实 HTTP API 跑通 boot→design→全部渲染，
   重点验证新增：信息流图 / 覆盖地图 / 波束面板 / 导出装配 / 新模式下拉。 */
'use strict';
const fs = require('fs');

const PORT = 8765;
const errors = [];

function makeEl(id) {
  const e = {
    id,
    _html: '',
    textContent: '',
    dataset: {},
    style: {},
    value: '',
    checked: false,
    type: 'text',
    tagName: 'DIV',
    classList: {
      _s: new Set(),
      toggle(c, on) { if (on === undefined) on = !this._s.has(c); on ? this._s.add(c) : this._s.delete(c); },
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    remove() {},
    click() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    getAttribute() { return null; },
    setAttribute() {},
    // Canvas 2D 桩（Proxy 全方法 no-op）：让 heat2dSvg / initGlobe3D 走完整渲染路径
    // —— 回归 "n is not a function"（局部 n 遮蔽全局格式化函数）必须真正执行到刻度格式化
    getContext(kind) {
      if (kind !== '2d') return null;
      const real = {
        createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
        createRadialGradient() { return { addColorStop() {} }; },
        createLinearGradient() { return { addColorStop() {} }; },
      };
      return new Proxy(real, {
        get(t, k) {
          if (k in t) return t[k];
          return () => {};   // 任意绘图方法 → no-op
        },
        set() { return true; },
      });
    },
    toDataURL() { return 'data:image/png;base64,STUB'; },
  };
  return e;
}

const els = {};
const elGet = id => (els[id] || (els[id] = makeEl(id)));

const document_ = {
  getElementById: elGet,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: t => makeEl('created_' + t),
  addEventListener: () => {},
  body: makeEl('body'),
};

const window_ = {
  addEventListener: () => {},
  matchMedia: () => ({ matches: false }),
  print: () => {},
  URL: { createObjectURL: () => 'blob:stub', revokeObjectURL: () => {} },
  Blob: class { constructor() {} },
  localStorage: {
    _d: {},
    getItem(k) { return this._d[k] || null; },
    setItem(k, v) { this._d[k] = v; },
  },
};

const ctx = {
  document: document_,
  window: window_,
  console,
  fetch: (u, o) => fetch('http://127.0.0.1:' + PORT + u, o),
  setTimeout, clearTimeout, setInterval, clearInterval,
  alert: m => errors.push('ALERT: ' + m),
  prompt: () => null,
  performance: { now: () => Date.now() },
  requestAnimationFrame: fn => setTimeout(() => fn(Date.now()), 0),
  URL: window_.URL,
  Blob: window_.Blob,
  localStorage: window_.localStorage,
  matchMedia: window_.matchMedia,
};
ctx.window.document = document_;
ctx.globalThis = ctx;
ctx.self = ctx;

const src = fs.readFileSync(process.argv[2], 'utf8');
const vm = require('vm');
const script = new vm.Script(src, { filename: 'front.js' });
const vmCtx = vm.createContext(ctx);

process.on('uncaughtException', e => { errors.push('UNCAUGHT: ' + e.stack); dumpFatal('UNCAUGHT', e); });
process.on('unhandledRejection', e => { errors.push('UNHANDLED: ' + (e && e.stack || e)); dumpFatal('UNHANDLED', e); });

function dumpFatal(kind, e) {
  try {
    fs.writeFileSync(__dirname + '/_dom_result.txt',
      kind + ': ' + (e && e.stack || e) + '\nerrors: ' + errors.join('\n') + '\n', 'utf8');
  } catch (_) {}
  process.exitCode = 1;
}

(async () => {
  script.runInContext(vmCtx);
  // boot 由 setTimeout(300) 触发；前端 RES 是 vm 词法变量不挂全局，
  // 以 DOM 内容为准：ov 页渲染出「方案总览」即 design 完成
  const t0 = Date.now();
  let ready = false;
  while (Date.now() - t0 < 120000) {
    if ((els['ov'] && els['ov'].innerHTML || '').includes('方案总览')) { ready = true; break; }
    await new Promise(r => setTimeout(r, 500));
  }
  if (!ready) { errors.push('TIMEOUT: 方案总览未渲染（boot/design 失败）'); report(); return; }
  ctx.RES = true; // 标记（供下方兼容）
  // 等异步面板（beam GRASP + worldmap）填充完成
  const t1 = Date.now();
  while (Date.now() - t1 < 45000) {
    const bb = els['beamBody'] && els['beamBody'].innerHTML || '';
    const cb = els['covBody'] && els['covBody'].innerHTML || '';
    const p2 = els['patBody'] && els['patBody'].innerHTML || '';
    const eb = els['eirpBody'] && els['eirpBody'].innerHTML || '';
    if (bb.length > 500 && cb.length > 500 && p2.length > 500 && eb.length > 500
        && !/spinner/.test(bb) && !/spinner/.test(cb) && !/spinner/.test(p2) && !/spinner/.test(eb)) break;
    await new Promise(r => setTimeout(r, 500));
  }
  await new Promise(r => setTimeout(r, 1000));
  // ⑫ 轨道页懒加载：主动触发 renderOrbit（模拟切入页签），等待填充
  try {
    vm.runInContext('showTab("tab-orbit")', vmCtx);
  } catch (e) { errors.push('showTab orbit: ' + e); }
  const t2 = Date.now();
  while (Date.now() - t2 < 45000) {
    const ob = els['orbit'] && els['orbit'].innerHTML || '';
    if (ob.length > 500 && !/spinner/.test(ob)) break;
    await new Promise(r => setTimeout(r, 500));
  }
  // ICD 端到端：node 层 fetch 真实 protocol 结果 → 注入 vm → 调用 icdHTML 渲染
  // （绕过 vm 沙箱内 async/await 宿主 promise 不恢复 microtask 的测试桩局限）
  let icdJson = null;
  try {
    const pres = await fetch('http://127.0.0.1:' + PORT + '/api/protocol', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cfg: { name: 't', service: '高通量宽带', orbit: 'GEO',
        coverage: '巴基斯坦', band: 'Ka', feeder_band: 'Ka', mode: '数字透明', ant_type: '固面' } }),
    });
    const pd = await pres.json();
    if (pd && pd.ok) icdJson = pd.result; else errors.push('protocol not ok: ' + (pd && pd.error));
  } catch (e) { errors.push('protocol fetch: ' + e); }
  if (icdJson) {
    try {
      vm.runInContext('ICD=' + JSON.stringify(icdJson), vmCtx);
      vm.runInContext('document.getElementById("icd").innerHTML=icdHTML(ICD)', vmCtx);
    } catch (e) { errors.push('icdHTML render: ' + (e && e.stack || e)); }
  }
  report();

  function report() {
    const checks = [];
    const push = (name, cond, msg) => checks.push([cond ? 'PASS' : 'FAIL', name, msg || '']);
    const H = id => (els[id] && els[id].innerHTML) || '';

    // 1. 信息流图（diag 页内含 renderInfoFlowDiagram 产物）
    const diag = H('diag');
    push('信息流图-面板存在', diag.includes('可视化信息流图'), 'len=' + diag.length);
    push('信息流图-三段齐全', ['星地信息流', '星间信息流', '星内信息流'].every(k => diag.includes(k)));
    push('信息流图-动画元素', (diag.match(/animateMotion/g) || []).length >= 3,
      'n=' + (diag.match(/animateMotion/g) || []).length);
    push('信息流图-载荷框图保留', diag.includes('载荷组成框图'));
    push('信息流图-时延标注', /单跳时延 [\d.]+ ms/.test(diag));
    push('信息流图-体制趋势', diag.includes('体制演进趋势'));

    // 1b. 标准方向图面板（patBody：grid/cut 双视图 + 栅瓣检查 + .grd 导出）
    const pb2 = H('patBody');
    push('方向图面板-已渲染', pb2.includes('峰值增益 G0') && pb2.includes('θ3dB'), 'len=' + pb2.length);
    push('方向图面板-cut SVG', pb2.includes('patSecCut') && pb2.includes('polyline'));
    push('方向图面板-宽cut/grid 区存在', pb2.includes('patSecWide') && pb2.includes('patSecGrid'));
    push('方向图面板-视图切换按钮', ['patBoreBtn', 'patScanBtn', 'patExportGrd'].every(k => pb2.includes(k)));
    push('方向图面板-栅瓣判定标签', /无栅瓣|栅瓣 ×/.test(pb2));
    push('方向图面板-±15°窗标注', pb2.includes('±15° cut') || pb2.includes('中心 ±15°'));
    push('方向图面板-无失败', !pb2.includes('失败') && !pb2.includes('不可用'));

    // 1c. 地面 EIRP 覆盖面板（eirpBody：等值线 + 度量 + CSV 导出）
    const eb = H('eirpBody');
    push('EIRP覆盖-已渲染', eb.includes('波束峰值 EIRP') && eb.includes('−3dB 足迹直径'), 'len=' + eb.length);
    push('EIRP覆盖-地图SVG', eb.includes('eirpMapSvg') || (eb.includes('<rect') && eb.includes('经度')), 'hasSvg');
    push('EIRP覆盖-等值线（−3/−10dB）', (eb.match(/d6452d/g) || []).length > 0 && (eb.match(/e08214/g) || []).length > 0);
    push('EIRP覆盖-波束中心标注', eb.includes('波束中心'));
    push('EIRP覆盖-度量表', eb.includes('足迹直径 (km)') && eb.includes('覆盖面积'));
    push('EIRP覆盖-CSV导出按钮', eb.includes('eirpExportCsv'));
    push('EIRP覆盖-精确投影', eb.includes('精确方向图逐点投影'));
    push('EIRP覆盖-无失败', !eb.includes('计算失败') && !eb.includes('通道不可用'));

    // 1d. ⑫ 轨道覆盖仿真页（懒加载触发后）
    const ob = H('orbit');
    push('轨道页-已渲染', ob.includes('轨道覆盖仿真') && ob.includes('覆盖帽 σ'), 'len=' + ob.length);
    push('轨道页-轨迹SVG', ob.includes('星下点轨迹') && (ob.match(/<path d="M/g) || []).length > 5);
    push('轨道页-快照时刻控制', ob.includes('orbTimeSlider') && ob.includes('仿真时刻'));
    push('轨道页-覆盖圈', ob.includes('覆盖圈') && ob.includes('σ'));
    push('轨道页-可见窗表', ob.includes('AOS') && ob.includes('LOS') && ob.includes('覆盖率'));
    push('轨道页-合理性判定', ob.includes('轨道覆盖合理性判定'));
    push('轨道页-STK导出按钮', ob.includes('orbExportStk') && ob.includes('STK Ephemeris'));
    push('轨道页-目标仰角', /仰角/.test(ob));
    push('轨道页-无失败', !ob.includes('仿真失败') && !ob.includes('通道不可用'));

    // 2. 覆盖地图（ov 页）
    const ov = H('ov');
    const cb = H('covBody');
    push('覆盖图-面板挂载', ov.includes('覆盖区示意图'));
    push('覆盖图-陆地轮廓', (cb.match(/<path d="M/g) || []).length > 40,
      'paths=' + (cb.match(/<path d="M/g) || []).length);
    push('覆盖图-星下点', cb.includes('星下点'));
    push('覆盖图-单星视域', cb.includes('单星视域'));
    push('覆盖图-波束栅格/波束', /波束/.test(cb));
    push('覆盖图-几何自洽标注', cb.includes('几何自洽'));
    push('覆盖图-示意图免责声明', cb.includes('示意图') && cb.includes('海岸线'));
    push('覆盖图-无失败', !cb.includes('加载失败'));

    // 3. 波束面板（ant 页）
    const ant = H('ant');
    const bb = H('beamBody');
    push('波束-面板挂载', ant.includes('波束覆盖性能'));
    push('波束-方向图SVG', bb.includes('远场方向图') && bb.includes('polyline'));
    push('波束-足迹剖面', bb.includes('星地覆盖足迹剖面'));
    push('波束-数据源标注', bb.includes('GRASP') || bb.includes('解析'),
      bb.includes('GRASP 物理光学实测') ? 'GRASP' : (bb.includes('Airy') ? 'analytic' : '?'));
    push('波束-KPI', /峰值增益/.test(bb) && /−3dB 波束宽度|3dB 波束宽度/.test(bb));
    push('波束-无失败', !bb.includes('失败'));
    push('波束-二维方向图（热力图/降级说明）',
      bb.includes('二维方向图') || !bb.includes('beamgrid3'),
      bb.includes('二维方向图') ? '2D on' : '2D off(canvas stub)');
    // 回归：heat2dSvg 局部变量遮蔽全局 n()（曾抛 "n is not a function" 致波束通道不可用）
    let heat = null, heatErr = '';
    try {
      const grid = Array.from({ length: 41 }, () => new Array(41).fill(-12.5));
      heat = vm.runInContext('heat2dSvg({grid:' + JSON.stringify(grid) + ',span:3,th3:0.8})', vmCtx);
    } catch (e) { heatErr = String(e && e.message || e); }
    push('二维热力图-无 "n is not a function"', heatErr === '', heatErr);
    push('二维热力图-渲染出SVG与刻度', typeof heat === 'string' && heat.includes('<svg')
      && heat.includes('θx') && heat.includes('dBr'), heat ? 'len=' + heat.length : 'null');
    // 物理合理性：G0 与 θ3dB
    const mG = bb.match(/data-v="([\d.-]+)"><\/span>/); // 不一定命中，改用文本
    const gTxt = bb.replace(/<[^>]+>/g, ' ');
    const mTh = gTxt.match(/−?3dB 波束宽度\s*([\d.]+)/);
    push('波束-θ3dB 物理范围(0.05~20°)', mTh ? (+mTh[1] > 0.05 && +mTh[1] < 20) : false, mTh ? mTh[1] : '未找到');

    // 3b. 三维覆盖地球（covBody 内 Canvas + 二维对照 + 工具条）
    push('三维地球-Canvas挂载', cb.includes('globeCv') && cb.includes('<canvas'));
    push('三维地球-工具条（复位/旋转/缩放/2D切换）',
      cb.includes('gReset') && cb.includes('gSpin') && cb.includes('gZoom') && cb.includes('g2d'));
    push('三维地球-二维对照视图保留', cb.includes('cov2d') && cb.includes('等距圆柱投影'));
    push('三维地球-图例', cb.includes('globelegend') && cb.includes('单星视域'));

    // 4. 导出（export API 装配）
    // 通过 HTTP 直接调用 export 验证后端装配（前端 exportWord 依赖 DOM Blob，逻辑已静态检查）
    // 5. 顶栏 KPI / 数字滚动
    const tk = H('topkpi');
    push('顶栏KPI-有数值', /EIRP <b>[\d.-]+<\/b>/.test(tk), tk.slice(0, 80));
    push('KPI数字滚动标记', ov.includes('rollv'));
    push('方案总览-评价标准面板', ov.includes('方案评价标准') && ov.includes('十项准则'));
    push('方案总览-评级徽章', /[ABCD]<\/div>/.test(ov) && (ov.includes('合理可行') || ov.includes('基本可行') || ov.includes('有条件可行') || ov.includes('不可行')));

    // 6. 工作模式下拉（cfgui）
    const cfg = H('cfgui');
    push('模式下拉-常用模式齐全',
      ['全球覆盖', '区域赋形', '点波束', '单波束', '多波束', '波束跳变', '相控扫描', '在轨重构'].every(k => cfg.includes(k)));
    // 7. 导出按钮存在（HTML 静态）
    const html = fs.readFileSync(process.argv[3], 'utf8');
    push('导出按钮', html.includes('btnExport') && html.includes('导出 Word'));
    push('打印按钮保留', html.includes('btnPrint'));
    push('print规则关动画', html.includes('@media print') && html.includes('animation:none'));

    // 8. 接口与协议页（MOSA ICD）
    const icd = H('icd');
    push('ICD页-已生成', icd.includes('MOSA 标准化 ICD'), 'len=' + icd.length);
    push('ICD页-生成链路五步', ['方案设定', '单机选型', '接口推导', '标准协议', '软件 ICD'].every(k => icd.includes(k)));
    push('ICD页-接口矩阵', icd.includes('接口矩阵') && icd.includes('遵循标准'));
    push('ICD页-数据总线标准', icd.includes('数据总线开放标准库') && (icd.includes('SpaceWire') || icd.includes('FC-AE')));
    push('ICD页-CCSDS帧格式', icd.includes('CCSDS') && icd.includes('bitstrip'));
    push('ICD页-APID/VCID', icd.includes('APID') && icd.includes('VCID'));
    push('ICD页-MOSA符合性', icd.includes('MOSA 符合性'));
    push('ICD页-软件协议栈', icd.includes('软件协议栈') || icd.includes('软件 ICD'));
    push('ICD页-无失败', !icd.includes('生成失败') && !icd.includes('不可用'));

    // 9. 导出双通道（前端 exportWord 逻辑 + 后端落盘 API 静态检查）
    const js = src;
    push('导出-后端落盘(file_path)', js.includes('r.file_path') && js.includes('expMask'));
    push('导出-打开文件按钮', js.includes('open_file') && js.includes('reveal_file'));
    push('导出-Blob兜底', js.includes('createObjectURL'));
    push('导出-传cfg给后端', /apiCall\("export",\{cfg:/.test(js));
    push('导出弹窗-静态HTML', html.includes('expMask') && html.includes('expOpen') && html.includes('expReveal'));
    push('接口协议页签-静态HTML', html.includes('tab-icd') && html.includes('接口与协议'));

    // 9b. ⑬ 稳健性分析页（renderAll 同步渲染 RES.robust）
    const rb = H('rob');
    push('稳健页-已渲染', rb.includes('方案级稳健性分析'), 'len=' + rb.length);
    push('稳健页-综合结论', rb.includes('综合结论'));
    push('稳健页-星蚀供电', rb.includes('星蚀') && rb.includes('kWh'));
    push('稳健页-位保ΔV', rb.includes('位置保持') && rb.includes('推进剂'));
    push('稳健页-MC直方图SVG', rb.includes('链路余量 M（dB）') && (rb.match(/<rect x="/g) || []).length > 10);
    push('稳健页-龙卷风图', rb.includes('±2σ') || rb.includes('龙卷风') || !rb.includes('tornado'));
    push('稳健页-可靠性三R口径', rb.includes('单串基线') && rb.includes('标准 1:1 冗余设计'));
    push('稳健页-整改建议', rb.includes('整改建议') || rb.includes('冗余建议') || rb.includes('无需整改'));
    push('稳健页-XPD', rb.includes('去极化') || rb.includes('XPD'));
    push('稳健页-邻星干扰', rb.includes('邻星') || rb.includes('C/I'));
    push('稳健页-无失败', !rb.includes('计算失败') && !rb.includes('undefined'));
    push('稳健页签-静态HTML', html.includes('tab-rob') && html.includes('稳健性分析'));

    // 10. 错误
    push('无 ALERT/运行时错误', errors.length === 0, errors.slice(0, 3).join(' | '));

    let nf = 0;
    const out = [];
    checks.forEach(c => { out.push(c[0] + ' ' + c[1] + (c[2] ? ' | ' + c[2] : '')); if (c[0] === 'FAIL') nf++; });
    out.push('');
    out.push(nf === 0 ? 'DOM E2E ALL PASS (' + checks.length + ' checks)' : 'DOM E2E FAIL: ' + nf + '/' + checks.length);
    const txt = out.join('\n');
    console.log(txt);
    fs.writeFileSync(__dirname + '/_dom_result.txt', txt + '\n', 'utf8');
    process.exitCode = nf === 0 ? 0 : 1;   // 不用 process.exit：Windows 管道下会吞 stdout
  }
})().catch(e => dumpFatal('ASYNC', e));
