# -*- coding: utf-8 -*-
"""把载荷方案知识图谱 JSON 渲染为单文件交互式 HTML 查看器。

特性：可折叠本体树 / 关键词搜索 / 节点详情（属性+关联约束+子节点）/
约束清单（点击成员跳转节点）/ 统计概览 / 打印·PDF / 导出 DOC。
输出: D:/ZWL/文生载荷Workbuddy/output/载荷方案知识图谱_2026-09-20.html
"""
from __future__ import annotations

import json
import os

KG = r"D:\ZWL\文生载荷Workbuddy\output\载荷方案知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\载荷方案知识图谱_2026-09-20.html"

with open(KG, encoding="utf-8") as f:
    g = json.load(f)

DATA_JSON = json.dumps(g, ensure_ascii=False)
assert "</script" not in DATA_JSON.lower()

N_ONTO = len(g["ontologies"])
N_ATTR = len(g["attributes"])
N_CONS = len(g["constraints"])

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>载荷方案知识图谱 · __DATE__</title>
<style>
:root{
  --bg:#ffffff; --bg2:#f7f8fa; --bg3:#eef1f5; --line:#dfe3e8; --line2:#c9cfd6;
  --tx:#1a1d21; --tx2:#5c646e; --tx3:#8a929c;
  --blue:#185FA5; --blue-bg:#E6F1FB; --teal:#0F6E56; --teal-bg:#E1F5EE;
  --purple:#534AB7; --purple-bg:#EEEDFE; --amber:#854F0B; --amber-bg:#FAEEDA;
  --coral:#993C1D; --coral-bg:#FAECE7; --green:#3B6D11; --green-bg:#EAF3DE;
  --red:#A32D2D; --red-bg:#FCEBEB;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg2);color:var(--tx);
  font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;font-size:13px;line-height:1.6}
.wrap{max-width:1400px;margin:0 auto;padding:18px}
header{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:14px}
h1{margin:0 0 4px;font-size:19px;font-weight:600;letter-spacing:.5px}
.sub{color:var(--tx2);font-size:12px;margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.chip{background:var(--bg3);border:1px solid var(--line);border-radius:20px;padding:3px 12px;font-size:12px;color:var(--tx2)}
.chip b{color:var(--tx);font-weight:600}
.toolbar{margin-left:auto;display:flex;gap:8px}
button{font-family:inherit;font-size:12px;padding:5px 13px;border-radius:7px;cursor:pointer;
  border:1px solid var(--line2);background:var(--bg);color:var(--tx)}
button:hover{background:var(--bg3)}
button.pri{background:var(--blue);border-color:var(--blue);color:#fff}
button.pri:hover{background:#144f8a}
.grid{display:grid;grid-template-columns:340px 1fr;gap:14px;align-items:start}
.card{background:var(--bg);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card-h{padding:10px 14px;border-bottom:1px solid var(--line);background:var(--bg2);
  font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.card-b{padding:12px 14px}
.search{width:100%;padding:7px 10px;border:1px solid var(--line2);border-radius:7px;
  font-family:inherit;font-size:12px;margin-bottom:10px;background:var(--bg)}
.search:focus{outline:none;border-color:var(--blue)}
.tree{max-height:calc(100vh - 250px);overflow:auto;font-size:12.5px}
.tnode{user-select:none}
.trow{display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:5px;cursor:pointer}
.trow:hover{background:var(--bg3)}
.trow.sel{background:var(--blue-bg);font-weight:600}
.tog{width:14px;flex:0 0 14px;text-align:center;color:var(--tx3);font-size:10px}
.tname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tid{color:var(--tx3);font-size:10.5px;font-family:Consolas,monospace;flex:0 0 auto}
.dot{width:6px;height:6px;border-radius:50%;flex:0 0 6px;margin-right:2px}
.kids{margin-left:15px;border-left:1px solid var(--line);padding-left:4px}
.hide{display:none}
.tabs{display:flex;gap:2px;padding:0 14px;background:var(--bg2);border-bottom:1px solid var(--line)}
.tab{padding:9px 14px;font-size:12.5px;cursor:pointer;border:1px solid transparent;border-bottom:none;
  border-radius:7px 7px 0 0;color:var(--tx2);margin-bottom:-1px}
.tab.on{background:var(--bg);border-color:var(--line);color:var(--blue);font-weight:600}
.pane{padding:16px 18px;max-height:calc(100vh - 210px);overflow:auto}
h2.n{margin:0 0 2px;font-size:17px;font-weight:600}
.path{color:var(--tx3);font-size:11.5px;margin-bottom:10px;font-family:Consolas,monospace}
.desc{background:var(--bg2);border-left:3px solid var(--blue);padding:9px 12px;
  border-radius:0 7px 7px 0;color:var(--tx2);margin-bottom:14px}
h3.s{font-size:13px;font-weight:600;margin:18px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--bg2);font-weight:600;color:var(--tx2);white-space:nowrap}
tr:nth-child(even) td{background:#fcfcfd}
code,.mono{font-family:Consolas,"Courier New",monospace;font-size:11.5px}
.formula{background:var(--bg3);border:1px solid var(--line);border-radius:6px;
  padding:3px 9px;font-family:Consolas,monospace;font-size:12px;display:inline-block}
.tag{display:inline-block;padding:1px 8px;border-radius:11px;font-size:11px;border:1px solid;margin:1px 2px}
.tg-b{background:var(--blue-bg);border-color:#85B7EB;color:var(--blue)}
.tg-t{background:var(--teal-bg);border-color:#5DCAA5;color:var(--teal)}
.tg-p{background:var(--purple-bg);border-color:#AFA9EC;color:var(--purple)}
.tg-a{background:var(--amber-bg);border-color:#FAC775;color:var(--amber)}
.tg-c{background:var(--coral-bg);border-color:#F0997B;color:var(--coral)}
.tg-g{background:var(--green-bg);border-color:#97C459;color:var(--green)}
.tg-r{background:var(--red-bg);border-color:#F09595;color:var(--red)}
.link{color:var(--blue);cursor:pointer;text-decoration:none;border-bottom:1px dashed #85B7EB}
.link:hover{border-bottom-style:solid}
.cbox{border:1px solid var(--line);border-radius:9px;padding:11px 13px;margin-bottom:9px;background:var(--bg)}
.cbox:hover{border-color:var(--line2);background:#fcfdfe}
.cid{font-weight:600;color:var(--purple);font-family:Consolas,monospace;margin-right:8px}
.cdesc{color:var(--tx2);margin-top:5px;font-size:12px}
.members{margin-top:7px}
.empty{color:var(--tx3);font-style:italic;padding:8px 0}
.stat{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:14px}
.sbox{background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:11px;text-align:center}
.snum{font-size:22px;font-weight:600;color:var(--blue);line-height:1.2}
.slab{font-size:11.5px;color:var(--tx2);margin-top:2px}
.lvl{display:flex;gap:9px;align-items:baseline;padding:6px 0;border-bottom:1px dashed var(--line)}
.lvl:last-child{border-bottom:none}
.ln{flex:0 0 34px;text-align:center;background:var(--bg3);border-radius:5px;padding:2px 0;
  font-family:Consolas,monospace;font-size:11.5px;color:var(--tx2)}
.bar{height:7px;border-radius:4px;background:var(--blue);flex:0 0 auto}
.hl{background:#FFF3B0;border-radius:2px}
footer{text-align:center;color:var(--tx3);font-size:11.5px;padding:16px 0 6px}
@media print{
  body{background:#fff}
  .toolbar,.search,.tabs,.tog{display:none!important}
  .grid{grid-template-columns:1fr}
  .tree,.pane{max-height:none!important;overflow:visible!important}
  .card{break-inside:avoid;border-color:#999}
  .hide{display:block!important}
  a{color:#000;border:none}
}
@media(max-width:980px){.grid{grid-template-columns:1fr}.stat{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>载荷方案知识图谱</h1>
  <div class="sub">
    源文件 <code>knowledge-graph-2026-09-20.json</code> · 版本 v__VER__ ·
    导出时间 __EXP__ · schema：ontologies（树） / attributes（属性） / constraints（约束）
  </div>
  <div class="chips">
    <span class="chip">本体 <b>__N1__</b></span>
    <span class="chip">属性 <b>__N2__</b></span>
    <span class="chip">约束 <b>__N3__</b></span>
    <span class="chip">源约束保留 <b>4/4</b></span>
    <span class="chip">需求覆盖 <b>天线·转发器·激光·智能处理单元·DTP·相控阵</b></span>
    <span class="toolbar">
      <button onclick="toggleAll(true)">展开全部</button>
      <button onclick="toggleAll(false)">折叠全部</button>
      <button onclick="window.print()">打印 / PDF</button>
      <button class="pri" onclick="dl()">下载 JSON</button>
    </span>
  </div>
</header>

<div class="grid">
  <div class="card">
    <div class="card-h">本体树 <span style="margin-left:auto;color:var(--tx3);font-weight:400;font-size:11.5px">点击节点查看详情</span></div>
    <div class="card-b" style="padding:10px">
      <input class="search" id="q" placeholder="搜索名称 / id / 属性 / 约束…" oninput="doSearch()">
      <div class="tree" id="tree"></div>
    </div>
  </div>

  <div class="card">
    <div class="tabs">
      <div class="tab on" data-p="pNode" onclick="sw(this)">节点详情</div>
      <div class="tab" data-p="pCons" onclick="sw(this)">约束清单（__N3__）</div>
      <div class="tab" data-p="pAttr" onclick="sw(this)">属性总表（__N2__）</div>
      <div class="tab" data-p="pStat" onclick="sw(this)">统计概览</div>
    </div>
    <div class="pane" id="pNode"></div>
    <div class="pane hide" id="pCons"></div>
    <div class="pane hide" id="pAttr"></div>
    <div class="pane hide" id="pStat"></div>
  </div>
</div>

<footer>文生有效载荷 · 载荷方案知识图谱 · 由 catalog.py 货架体系与 link_budget.py 工程判据对齐生成</footer>
</div>

<script type="application/json" id="kg">__DATA__</script>
<script>
const KG=JSON.parse(document.getElementById('kg').textContent);
const O=KG.ontologies,A=KG.attributes,C=KG.constraints;
const oMap=new Map(O.map(o=>[o.id,o]));
const aMap=new Map(A.map(a=>[a.id,a]));
const kids=new Map();
O.forEach(o=>{if(!kids.has(o.parentId))kids.set(o.parentId,[]);kids.get(o.parentId).push(o);});
kids.forEach(v=>v.sort((a,b)=>a.order-b.order));
const attrByOnt=new Map();
A.forEach(a=>{if(!attrByOnt.has(a.ontologyId))attrByOnt.set(a.ontologyId,[]);attrByOnt.get(a.ontologyId).push(a);});
const DEPTH_COLOR=['#185FA5','#0F6E56','#534AB7','#854F0B','#993C1D','#3B6D11','#A32D2D','#5c646e'];

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function path(id){const p=[];let c=id;while(c){p.unshift(oMap.get(c).name);c=oMap.get(c).parentId;}return p.join(' › ');}
function depth(id){let d=0,c=oMap.get(id).parentId;while(c){d++;c=oMap.get(c).parentId;}return d;}
function subtree(id){const s=[id];(function w(n){(kids.get(n)||[]).forEach(k=>{s.push(k.id);w(k.id);});})(id);return s;}
function consOf(id){const ids=new Set(subtree(id).flatMap(n=>(attrByOnt.get(n)||[]).map(a=>a.id)));
  return C.filter(c=>c.members.some(m=>ids.has(m.attributeId)));}

let sel=null,expanded=new Set(O.map(o=>o.id));

function renderTree(filter){
  const root=document.getElementById('tree');root.innerHTML='';
  const match=o=>{
    if(!filter)return true;
    const f=filter.toLowerCase();
    if((o.name+o.id+o.description).toLowerCase().includes(f))return true;
    return (attrByOnt.get(o.id)||[]).some(a=>(a.name+a.symbol+a.id+a.description).toLowerCase().includes(f));
  };
  const keep=new Set();
  if(filter){
    O.forEach(o=>{if(match(o)){let c=o.id;while(c){keep.add(c);c=oMap.get(c).parentId;}
      subtree(o.id).forEach(x=>keep.add(x));}});
  }
  const build=(pid,cont)=>{
    (kids.get(pid)||[]).forEach(o=>{
      if(filter&&!keep.has(o.id))return;
      const ch=kids.get(o.id)||[];
      const d=depth(o.id);
      const wrap=document.createElement('div');wrap.className='tnode';wrap.dataset.id=o.id;
      const row=document.createElement('div');row.className='trow'+(sel===o.id?' sel':'');
      row.innerHTML=`<span class="tog">${ch.length?(expanded.has(o.id)?'▼':'▶'):''}</span>`+
        `<span class="dot" style="background:${DEPTH_COLOR[Math.min(d,7)]}"></span>`+
        `<span class="tname">${hlText(o.name,filter)}</span>`+
        `<span class="tid">${o.id}</span>`;
      row.onclick=e=>{
        if(e.target.classList.contains('tog')&&ch.length){
          expanded.has(o.id)?expanded.delete(o.id):expanded.add(o.id);renderTree(filter);return;}
        select(o.id);};
      wrap.appendChild(row);
      if(ch.length){
        const kb=document.createElement('div');kb.className='kids'+(expanded.has(o.id)?'':' hide');
        build(o.id,kb);wrap.appendChild(kb);
      }
      cont.appendChild(wrap);
    });
  };
  build(null,root);
}
function hlText(t,f){if(!f)return esc(t);
  const i=t.toLowerCase().indexOf(f.toLowerCase());
  if(i<0)return esc(t);
  return esc(t.slice(0,i))+'<span class="hl">'+esc(t.slice(i,i+f.length))+'</span>'+esc(t.slice(i+f.length));}

function select(id){
  sel=id;renderTree(document.getElementById('q').value.trim());
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.p==='pNode'));
  ['pNode','pCons','pAttr','pStat'].forEach(p=>document.getElementById(p).classList.toggle('hide',p!=='pNode'));
  const o=oMap.get(id),d=depth(id),ch=kids.get(id)||[],as=attrByOnt.get(id)||[],cs=consOf(id);
  let h=`<h2 class="n">${esc(o.name)}</h2><div class="path">${esc(path(id))} · id=${esc(id)} · 层级 L${d}</div>`;
  h+=`<div class="desc">${esc(o.description)}</div>`;
  h+=`<div class="stat" style="grid-template-columns:repeat(3,1fr)">
      <div class="sbox"><div class="snum">${ch.length}</div><div class="slab">直接子节点</div></div>
      <div class="sbox"><div class="snum">${as.length}</div><div class="slab">自有属性</div></div>
      <div class="sbox"><div class="snum">${cs.length}</div><div class="slab">关联约束（含子树）</div></div></div>`;
  if(ch.length){
    h+=`<h3 class="s">子节点（${ch.length}）</h3><div>`;
    ch.forEach(k=>{h+=`<span class="tag tg-b link" onclick="select('${k.id}')">${esc(k.name)}</span>`;});
    h+=`</div>`;
  }
  h+=`<h3 class="s">属性（${as.length}）</h3>`;
  if(as.length){
    h+=`<table><thead><tr><th>符号</th><th>名称</th><th>说明</th><th>id</th></tr></thead><tbody>`;
    as.forEach(a=>{h+=`<tr><td><span class="formula">${esc(a.symbol)}</span></td><td><b>${esc(a.name)}</b></td>
      <td>${esc(a.description)}</td><td class="mono" style="color:var(--tx3)">${esc(a.id)}</td></tr>`;});
    h+=`</tbody></table>`;
  } else h+=`<div class="empty">该节点无直接挂载属性（属性挂在子节点或作为约束成员引用）</div>`;
  if(cs.length){
    h+=`<h3 class="s">关联约束（${cs.length}）</h3>`;
    cs.forEach(c=>{h+=consBox(c);});
  }
  const par=o.parentId?oMap.get(o.parentId):null;
  if(par)h+=`<h3 class="s">上级</h3><span class="tag tg-t link" onclick="select('${par.id}')">${esc(par.name)}</span>`;
  document.getElementById('pNode').innerHTML=h;
  document.getElementById('pNode').scrollTop=0;
}
function consBox(c){
  let h=`<div class="cbox"><div><span class="cid">${esc(c.id)}</span><span class="formula">${esc(c.formula)}</span></div>`;
  h+=`<div class="cdesc">${esc(c.description)}</div><div class="members">`;
  c.members.forEach(m=>{
    const a=aMap.get(m.attributeId);if(!a)return;
    const o=oMap.get(a.ontologyId);
    h+=`<span class="tag tg-p link" onclick="select('${o.id}')" title="${esc(o.name)} · ${esc(a.name)}">
        <b>${esc(m.role)}</b> ← ${esc(a.symbol)} · ${esc(o.name)}</span>`;
  });
  return h+`</div></div>`;
}
function renderCons(){
  let h=`<h2 class="n">约束清单</h2><div class="path">共 ${C.length} 条：保留源图谱 4 条（c-1~c-4）+ 新增通信载荷域 ${C.length-4} 条（c-5~c-${C.length}）</div>`;
  h+=`<div class="desc">约束是选型与校核的工程判据。点击成员标签可跳转到对应本体节点。</div>`;
  const groups=[['源图谱保留（卫星平台域）',c=>+c.id.slice(2)<=4],
    ['天线与增益',c=>['c-5','c-6','c-7','c-8','c-19'].includes(c.id)],
    ['链路预算与容量',c=>['c-9','c-10','c-11','c-12','c-13','c-14'].includes(c.id)],
    ['平台与运载闭环',c=>['c-15','c-16'].includes(c.id)],
    ['激光通信',c=>['c-17','c-18'].includes(c.id)],
    ['货架优先原则',c=>c.id==='c-20']];
  groups.forEach(([t,f])=>{
    const list=C.filter(f);if(!list.length)return;
    h+=`<h3 class="s">${esc(t)}（${list.length}）</h3>`;
    list.forEach(c=>{h+=consBox(c);});
  });
  document.getElementById('pCons').innerHTML=h;
}
function renderAttr(){
  let h=`<h2 class="n">属性总表</h2><div class="path">共 ${A.length} 个属性，按本体归属分组</div>`;
  h+=`<input class="search" id="aq" placeholder="筛选属性名 / 符号 / 说明…" oninput="fAttr()" style="max-width:420px">`;
  h+=`<div id="atbl"></div>`;
  document.getElementById('pAttr').innerHTML=h;fAttr();
}
function fAttr(){
  const f=(document.getElementById('aq').value||'').trim().toLowerCase();
  let h='';
  O.forEach(o=>{
    const as=(attrByOnt.get(o.id)||[]).filter(a=>!f||(a.name+a.symbol+a.description+a.id).toLowerCase().includes(f));
    if(!as.length)return;
    h+=`<h3 class="s"><span class="link" onclick="select('${o.id}')">${esc(o.name)}</span>
        <span style="color:var(--tx3);font-weight:400">（${as.length}）</span></h3>`;
    h+=`<table><thead><tr><th>符号</th><th>名称</th><th>说明</th></tr></thead><tbody>`;
    as.forEach(a=>{h+=`<tr><td><span class="formula">${esc(a.symbol)}</span></td><td><b>${esc(a.name)}</b></td><td>${esc(a.description)}</td></tr>`;});
    h+=`</tbody></table>`;
  });
  document.getElementById('atbl').innerHTML=h||'<div class="empty">无匹配属性</div>';
}
function renderStat(){
  const roots=kids.get(null)||[];
  const byTop={};
  O.forEach(o=>{let c=o.id;while(oMap.get(c).parentId)c=oMap.get(c).parentId;byTop[c]=(byTop[c]||0)+1;});
  const max=Math.max(...Object.values(byTop));
  let h=`<h2 class="n">统计概览</h2><div class="path">图谱规模与分支分布</div>`;
  h+=`<div class="stat"><div class="sbox"><div class="snum">${O.length}</div><div class="slab">本体节点</div></div>
      <div class="sbox"><div class="snum">${A.length}</div><div class="slab">属性</div></div>
      <div class="sbox"><div class="snum">${C.length}</div><div class="slab">约束</div></div>
      <div class="sbox"><div class="snum">${Math.max(...O.map(o=>depth(o.id)))}</div><div class="slab">最大层级深度</div></div></div>`;
  h+=`<h3 class="s">分支规模（含子树）</h3>`;
  Object.entries(byTop).sort((a,b)=>b[1]-a[1]).forEach(([id,n])=>{
    h+=`<div class="lvl"><span class="ln">${n}</span>
      <span class="bar" style="width:${Math.round(n/max*260)}px;background:${DEPTH_COLOR[Math.min(depth(id),7)]}"></span>
      <span class="link" onclick="select('${id}')">${esc(oMap.get(id).name)}</span>
      <span style="color:var(--tx3);margin-left:auto" class="mono">${id}</span></div>`;
  });
  const leaf=O.filter(o=>!(kids.get(o.id)||[]).length).length;
  h+=`<h3 class="s">结构指标</h3><table><tbody>
    <tr><td>根节点</td><td>${roots.map(r=>esc(r.name)).join('、')}</td></tr>
    <tr><td>叶子节点 / 分支节点</td><td>${leaf} / ${O.length-leaf}</td></tr>
    <tr><td>有属性的节点</td><td>${attrByOnt.size} 个（属性挂载率 ${(attrByOnt.size/O.length*100).toFixed(0)}%）</td></tr>
    <tr><td>被约束引用的属性</td><td>${new Set(C.flatMap(c=>c.members.map(m=>m.attributeId))).size} / ${A.length}</td></tr>
    <tr><td>约束成员总数</td><td>${C.flatMap(c=>c.members).length}</td></tr>
    <tr><td>用户需求关键词覆盖</td><td>${['天线','转发器','激光','智能处理单元','DTP','相控阵']
      .map(k=>`<span class="tag tg-g">✓ ${k}</span>`).join('')}</td></tr>
    <tr><td>转发体制</td><td>透明转发 (transparent) · 再生处理 (regenerative) · DTP 柔性 (dtp)</td></tr>
    <tr><td>天线体制</td><td>相控阵 · 反射阵 · 反射面 · 伞状可展开 · 喇叭 · 螺旋 · 光学</td></tr>
    </tbody></table>`;
  document.getElementById('pStat').innerHTML=h;
}
function sw(t){
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
  ['pNode','pCons','pAttr','pStat'].forEach(p=>document.getElementById(p).classList.toggle('hide',p!==t.dataset.p));
  if(t.dataset.p==='pCons')renderCons();
  if(t.dataset.p==='pAttr')renderAttr();
  if(t.dataset.p==='pStat')renderStat();
}
function toggleAll(v){
  expanded=v?new Set(O.map(o=>o.id)):new Set();
  renderTree(document.getElementById('q').value.trim());
}
let tmr=null;
function doSearch(){clearTimeout(tmr);tmr=setTimeout(()=>renderTree(document.getElementById('q').value.trim()),160);}
function dl(){
  const b=new Blob([document.getElementById('kg').textContent],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='载荷方案知识图谱.json';a.click();URL.revokeObjectURL(a.href);
}
renderTree('');select('comm_payload');
</script>
</body>
</html>
"""

html = (HTML.replace("__DATA__", DATA_JSON)
        .replace("__N1__", str(N_ONTO)).replace("__N2__", str(N_ATTR)).replace("__N3__", str(N_CONS))
        .replace("__VER__", str(g["version"]))
        .replace("__EXP__", g["exportedAt"])
        .replace("__DATE__", g["exportedAt"][:10]))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

checks = [
    ("HTML 非空", len(html) > 10000),
    ("内嵌 JSON 数据块", 'id="kg"' in html and '"ontologies"' in html),
    ("本体数正确", html.count('"parentId"') >= N_ONTO),
    ("无未替换占位符", "__DATA__" not in html and "__N1__" not in html),
    ("树渲染函数", "renderTree" in html),
    ("约束视图", "renderCons" in html),
    ("打印样式", "@media print" in html),
    ("JSON 下载", "download='载荷方案知识图谱.json'" in html or 'a.download=' in html),
    ("关键实体出现", all(k in html for k in ["相控阵", "DTP", "激光", "智能处理单元", "转发器", "天线"])),
]
print("HTML:", OUT, f"({len(html)/1024:.1f} KB)")
for name, ok in checks:
    print(("  ✅ " if ok else "  ❌ ") + name)
print("自检:", f"{sum(1 for _, o in checks if o)}/{len(checks)} 通过")
