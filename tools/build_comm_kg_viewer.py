# -*- coding: utf-8 -*-
"""把「通信有效载荷知识图谱」JSON 渲染为单文件交互式 HTML 查看器。

特性：
  - 左侧可折叠本体树，按 category 着色（分系统/分组/体制/单机/链路/基础/指标）
  - category 过滤器 + 全文搜索（名称/id/属性/单机）
  - 节点详情：描述、子节点、自有属性、关联约束、组成单机链（chain）、关系（relations）
  - 链路/体制的 chain 以「有序单机流水线」可视化展示，点击单机可跳转
  - 约束清单按域分组；关系矩阵；属性总表；统计概览
  - 打印/PDF、下载 JSON
"""
from __future__ import annotations

import json
import os

KG = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"
OUT = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.html"

with open(KG, encoding="utf-8") as f:
    g = json.load(f)

DATA_JSON = json.dumps(g, ensure_ascii=False)
assert "</script" not in DATA_JSON.lower()

N_ONTO = len(g["ontologies"])
N_ATTR = len(g["attributes"])
N_CONS = len(g["constraints"])
N_REL = len(g.get("relations", []))

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>通信有效载荷知识图谱</title>
<style>
:root{
  --bg:#ffffff;--bg2:#f7f8fa;--bg3:#eef1f5;--line:#dfe3e8;--line2:#c9cfd6;
  --tx:#1a1d21;--tx2:#5c646e;--tx3:#8a929c;
  --blue:#185FA5;--blue-bg:#E6F1FB;--teal:#0F6E56;--teal-bg:#E1F5EE;
  --purple:#534AB7;--purple-bg:#EEEDFE;--amber:#854F0B;--amber-bg:#FAEEDA;
  --coral:#993C1D;--coral-bg:#FAECE7;--green:#3B6D11;--green-bg:#EAF3DE;
  --red:#A32D2D;--red-bg:#FCEBEB;--pink:#993556;--pink-bg:#FBEAF0;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg2);color:var(--tx);
  font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;font-size:13px;line-height:1.6}
.wrap{max-width:1480px;margin:0 auto;padding:16px}
header{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:12px}
h1{margin:0 0 3px;font-size:19px;font-weight:600;letter-spacing:.5px}
.sub{color:var(--tx2);font-size:12px;margin-bottom:11px}
.chips{display:flex;flex-wrap:wrap;gap:7px;align-items:center}
.chip{background:var(--bg3);border:1px solid var(--line);border-radius:20px;padding:3px 11px;font-size:12px;color:var(--tx2)}
.chip b{color:var(--tx);font-weight:600}
.toolbar{margin-left:auto;display:flex;gap:7px}
button{font-family:inherit;font-size:12px;padding:5px 12px;border-radius:7px;cursor:pointer;
  border:1px solid var(--line2);background:var(--bg);color:var(--tx)}
button:hover{background:var(--bg3)}
button.pri{background:var(--blue);border-color:var(--blue);color:#fff}
button.pri:hover{background:#144f8a}
.grid{display:grid;grid-template-columns:360px 1fr;gap:12px;align-items:start}
.card{background:var(--bg);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card-h{padding:9px 13px;border-bottom:1px solid var(--line);background:var(--bg2);
  font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.card-b{padding:10px 12px}
.search{width:100%;padding:7px 10px;border:1px solid var(--line2);border-radius:7px;
  font-family:inherit;font-size:12px;margin-bottom:8px;background:var(--bg)}
.search:focus{outline:none;border-color:var(--blue)}
.filters{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.fbtn{font-size:11px;padding:2px 9px;border-radius:12px;cursor:pointer;border:1px solid var(--line2);
  background:var(--bg);color:var(--tx2);user-select:none}
.fbtn.on{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.tree{max-height:calc(100vh - 290px);overflow:auto;font-size:12.5px}
.trow{display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:5px;cursor:pointer}
.trow:hover{background:var(--bg3)}
.trow.sel{background:var(--blue-bg);font-weight:600}
.tog{width:13px;flex:0 0 13px;text-align:center;color:var(--tx3);font-size:9px}
.tname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tid{color:var(--tx3);font-size:10px;font-family:Consolas,monospace;flex:0 0 auto}
.dot{width:6px;height:6px;border-radius:50%;flex:0 0 6px;margin-right:1px}
.kids{margin-left:13px;border-left:1px solid var(--line);padding-left:3px}
.hide{display:none}
.tabs{display:flex;gap:2px;padding:0 13px;background:var(--bg2);border-bottom:1px solid var(--line);flex-wrap:wrap}
.tab{padding:9px 13px;font-size:12.5px;cursor:pointer;border:1px solid transparent;border-bottom:none;
  border-radius:7px 7px 0 0;color:var(--tx2);margin-bottom:-1px}
.tab.on{background:var(--bg);border-color:var(--line);color:var(--blue);font-weight:600}
.pane{padding:15px 17px;max-height:calc(100vh - 220px);overflow:auto}
h2.n{margin:0 0 2px;font-size:17px;font-weight:600}
.path{color:var(--tx3);font-size:11.5px;margin-bottom:9px;font-family:Consolas,monospace}
.badge{display:inline-block;font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid;margin-left:6px;vertical-align:middle}
.desc{background:var(--bg2);border-left:3px solid var(--blue);padding:9px 12px;
  border-radius:0 7px 7px 0;color:var(--tx2);margin-bottom:13px}
h3.s{font-size:13px;font-weight:600;margin:17px 0 7px;padding-bottom:5px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--bg2);font-weight:600;color:var(--tx2);white-space:nowrap}
tr:nth-child(even) td{background:#fcfcfd}
code,.mono{font-family:Consolas,"Courier New",monospace;font-size:11.5px}
.formula{background:var(--bg3);border:1px solid var(--line);border-radius:6px;
  padding:2px 8px;font-family:Consolas,monospace;font-size:12px;display:inline-block}
.tag{display:inline-block;padding:1px 8px;border-radius:11px;font-size:11px;border:1px solid;margin:1px 2px}
.tg-b{background:var(--blue-bg);border-color:#85B7EB;color:var(--blue)}
.tg-t{background:var(--teal-bg);border-color:#5DCAA5;color:var(--teal)}
.tg-p{background:var(--purple-bg);border-color:#AFA9EC;color:var(--purple)}
.tg-a{background:var(--amber-bg);border-color:#FAC775;color:var(--amber)}
.tg-c{background:var(--coral-bg);border-color:#F0997B;color:var(--coral)}
.tg-g{background:var(--green-bg);border-color:#97C459;color:var(--green)}
.tg-r{background:var(--red-bg);border-color:#F09595;color:var(--red)}
.tg-k{background:var(--pink-bg);border-color:#ED93B1;color:var(--pink)}
.tg-y{background:var(--bg3);border-color:var(--line2);color:var(--tx2)}
.link{color:var(--blue);cursor:pointer;text-decoration:none;border-bottom:1px dashed #85B7EB}
.link:hover{border-bottom-style:solid}
.cbox{border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-bottom:8px;background:var(--bg)}
.cbox:hover{border-color:var(--line2);background:#fcfdfe}
.cid{font-weight:600;color:var(--purple);font-family:Consolas,monospace;margin-right:7px}
.cdesc{color:var(--tx2);margin-top:5px;font-size:12px}
.members{margin-top:6px}
.empty{color:var(--tx3);font-style:italic;padding:7px 0}
.stat{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:13px}
.sbox{background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:10px;text-align:center}
.snum{font-size:21px;font-weight:600;color:var(--blue);line-height:1.2}
.slab{font-size:11.5px;color:var(--tx2);margin-top:2px}
.pipe{display:flex;flex-wrap:wrap;align-items:center;gap:4px;padding:9px 10px;
  background:var(--bg2);border:1px solid var(--line);border-radius:9px;margin:7px 0}
.pstep{background:var(--bg);border:1px solid var(--line2);border-radius:7px;padding:4px 9px;
  font-size:11.5px;cursor:pointer;white-space:nowrap}
.pstep:hover{border-color:var(--blue);color:var(--blue);background:var(--blue-bg)}
.pstep .idx{color:var(--tx3);font-family:Consolas,monospace;font-size:10px;margin-right:3px}
.parrow{color:var(--tx3);font-size:12px}
.lvl{display:flex;gap:9px;align-items:center;padding:6px 0;border-bottom:1px dashed var(--line)}
.lvl:last-child{border-bottom:none}
.ln{flex:0 0 36px;text-align:center;background:var(--bg3);border-radius:5px;padding:2px 0;
  font-family:Consolas,monospace;font-size:11.5px;color:var(--tx2)}
.bar{height:7px;border-radius:4px;flex:0 0 auto}
.hl{background:#FFF3B0;border-radius:2px}
.legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:11px;color:var(--tx2)}
.legend span{display:flex;align-items:center;gap:3px}
footer{text-align:center;color:var(--tx3);font-size:11.5px;padding:14px 0 5px}
@media print{
  body{background:#fff}
  .toolbar,.search,.filters,.tabs,.tog{display:none!important}
  .grid{grid-template-columns:1fr}
  .tree,.pane{max-height:none!important;overflow:visible!important}
  .card{break-inside:avoid;border-color:#999}
  .hide{display:block!important}
  a,.link{color:#000;border:none}
}
@media(max-width:1000px){.grid{grid-template-columns:1fr}.stat{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>通信有效载荷知识图谱</h1>
  <div class="sub">
    范围：仅通信有效载荷（不含卫星系统/平台/运载） · 版本 v__VER__ · 导出 __EXP__ ·
    层级 L0 载荷 → L1 分系统 → L2 分组 → L3 体制/单机/链路
  </div>
  <div class="chips">
    <span class="chip">本体 <b>__N1__</b></span>
    <span class="chip">属性 <b>__N2__</b></span>
    <span class="chip">约束 <b>__N3__</b></span>
    <span class="chip">关系 <b>__N4__</b></span>
    <span class="chip">单机 <b>__NU__</b></span>
    <span class="chip">链路 <b>__NL__</b></span>
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
    <div class="card-h">本体树 <span style="margin-left:auto;color:var(--tx3);font-weight:400;font-size:11.5px">点击查看详情</span></div>
    <div class="card-b">
      <input class="search" id="q" placeholder="搜索名称 / id / 属性 / 单机…" oninput="doSearch()">
      <div class="filters" id="filters"></div>
      <div class="tree" id="tree"></div>
      <div class="legend" id="legend"></div>
    </div>
  </div>

  <div class="card">
    <div class="tabs">
      <div class="tab on" data-p="pNode" onclick="sw(this)">节点详情</div>
      <div class="tab" data-p="pChain" onclick="sw(this)">链路单机链</div>
      <div class="tab" data-p="pCons" onclick="sw(this)">约束（__N3__）</div>
      <div class="tab" data-p="pRel" onclick="sw(this)">关系（__N4__）</div>
      <div class="tab" data-p="pAttr" onclick="sw(this)">属性（__N2__）</div>
      <div class="tab" data-p="pStat" onclick="sw(this)">统计</div>
    </div>
    <div class="pane" id="pNode"></div>
    <div class="pane hide" id="pChain"></div>
    <div class="pane hide" id="pCons"></div>
    <div class="pane hide" id="pRel"></div>
    <div class="pane hide" id="pAttr"></div>
    <div class="pane hide" id="pStat"></div>
  </div>
</div>

<footer>文生有效载荷 · 通信有效载荷知识图谱 · 与 catalog.py 货架体系 / link_budget.py 工程判据对齐</footer>
</div>

<script type="application/json" id="kg">__DATA__</script>
<script>
const KG=JSON.parse(document.getElementById('kg').textContent);
const O=KG.ontologies,A=KG.attributes,C=KG.constraints,R=KG.relations||[];
const oMap=new Map(O.map(o=>[o.id,o]));
const aMap=new Map(A.map(a=>[a.id,a]));
const kids=new Map();
O.forEach(o=>{if(!kids.has(o.parentId))kids.set(o.parentId,[]);kids.get(o.parentId).push(o);});
kids.forEach(v=>v.sort((a,b)=>a.order-b.order));
const attrByOnt=new Map();
A.forEach(a=>{if(!attrByOnt.has(a.ontologyId))attrByOnt.set(a.ontologyId,[]);attrByOnt.get(a.ontologyId).push(a);});

const CAT_STYLE={
  '载荷总体':{c:'var(--blue)',bg:'var(--blue-bg)',b:'#85B7EB',tag:'tg-b'},
  '分系统':{c:'var(--teal)',bg:'var(--teal-bg)',b:'#5DCAA5',tag:'tg-t'},
  '分组':{c:'var(--purple)',bg:'var(--purple-bg)',b:'#AFA9EC',tag:'tg-p'},
  '体制':{c:'var(--coral)',bg:'var(--coral-bg)',b:'#F0997B',tag:'tg-c'},
  '单机':{c:'var(--amber)',bg:'var(--amber-bg)',b:'#FAC775',tag:'tg-a'},
  '链路':{c:'var(--green)',bg:'var(--green-bg)',b:'#97C459',tag:'tg-g'},
  '基础':{c:'#5F5E5A',bg:'var(--bg3)',b:'var(--line2)',tag:'tg-y'},
  '指标':{c:'var(--pink)',bg:'var(--pink-bg)',b:'#ED93B1',tag:'tg-k'}
};
const catOf=o=>CAT_STYLE[o.category]||CAT_STYLE['基础'];

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function path(id){const p=[];let c=id;while(c){p.unshift(oMap.get(c).name);c=oMap.get(c).parentId;}return p.join(' › ');}
function depth(id){let d=0,c=oMap.get(id).parentId;while(c){d++;c=oMap.get(c).parentId;}return d;}
function subtree(id){const s=[id];(function w(n){(kids.get(n)||[]).forEach(k=>{s.push(k.id);w(k.id);});})(id);return s;}
function consOf(id){const ids=new Set(subtree(id).flatMap(n=>(attrByOnt.get(n)||[]).map(a=>a.id)));
  return C.filter(c=>c.members.some(m=>ids.has(m.attributeId)));}
function relOf(id){return R.filter(r=>r.from===id||r.to===id);}

let sel=null,expanded=new Set(O.filter(o=>depth(o.id)<=2).map(o=>o.id));
let catFilter=new Set();

function buildFilters(){
  const cats=[...new Set(O.map(o=>o.category))];
  document.getElementById('filters').innerHTML=
    `<span class="fbtn on" data-c="__all" onclick="fAll(this)">全部</span>`+
    cats.map(c=>`<span class="fbtn" data-c="${c}" onclick="fCat(this)">${c}</span>`).join('');
  document.getElementById('legend').innerHTML=
    cats.map(c=>{const s=CAT_STYLE[c]||CAT_STYLE['基础'];
      return `<span><i class="dot" style="background:${s.c}"></i>${c}</span>`;}).join('');
}
function fAll(e){catFilter.clear();document.querySelectorAll('.fbtn').forEach(x=>x.classList.toggle('on',x===e));renderTree(document.getElementById('q').value.trim());}
function fCat(e){
  const c=e.dataset.c;
  if(catFilter.has(c)){catFilter.delete(c);e.classList.remove('on');}
  else{catFilter.add(c);e.classList.add('on');}
  document.querySelector('.fbtn[data-c="__all"]').classList.toggle('on',catFilter.size===0);
  renderTree(document.getElementById('q').value.trim());
}

function renderTree(filter){
  const root=document.getElementById('tree');root.innerHTML='';
  const match=o=>{
    let ok=true;
    if(filter){const f=filter.toLowerCase();
      ok=(o.name+o.id+(o.description||'')).toLowerCase().includes(f)
        || (attrByOnt.get(o.id)||[]).some(a=>(a.name+a.symbol+a.id+a.description).toLowerCase().includes(f))
        || (o.chain||[]).some(x=>x.includes(f));}
    if(ok&&catFilter.size)ok=catFilter.has(o.category)||subtreeHasCat(o.id);
    return ok;
  };
  const subtreeHasCat=id=>subtree(id).some(x=>catFilter.has(oMap.get(x).category));
  const keep=new Set();
  if(filter||catFilter.size){
    O.forEach(o=>{if(match(o)){let c=o.id;while(c){keep.add(c);c=oMap.get(c).parentId;}
      subtree(o.id).forEach(x=>keep.add(x));}});
  }
  const showNode=o=>!filter&&!catFilter.size||keep.has(o.id);
  const build=(pid,cont)=>{
    (kids.get(pid)||[]).forEach(o=>{
      if(!showNode(o))return;
      const ch=(kids.get(o.id)||[]).filter(showNode);
      const s=catOf(o);
      const wrap=document.createElement('div');
      const row=document.createElement('div');row.className='trow'+(sel===o.id?' sel':'');
      row.innerHTML=`<span class="tog">${ch.length?(expanded.has(o.id)?'▼':'▶'):''}</span>`+
        `<span class="dot" style="background:${s.c}"></span>`+
        `<span class="tname">${hlText(o.name,filter)}</span>`+
        `<span class="tid">${o.category==='单机'?'':o.category==='链路'?'链':''}${o.id}</span>`;
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

function pipe(chain,title){
  let h=`<div class="pipe">`;
  chain.forEach((u,i)=>{
    const o=oMap.get(u);if(!o)return;
    h+=`<span class="pstep" onclick="select('${u}')" title="${esc(o.name)} · ${esc(o.description||'')}">
        <span class="idx">${i+1}</span>${esc(o.name)}</span>`;
    if(i<chain.length-1)h+=`<span class="parrow">→</span>`;
  });
  return h+`</div>`;
}

function select(id){
  sel=id;renderTree(document.getElementById('q').value.trim());
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.p==='pNode'));
  ['pNode','pChain','pCons','pRel','pAttr','pStat'].forEach(p=>document.getElementById(p).classList.toggle('hide',p!=='pNode'));
  const o=oMap.get(id),s=catOf(o),d=depth(id),ch=kids.get(id)||[],as=attrByOnt.get(id)||[],cs=consOf(id),rs=relOf(id);
  let h=`<h2 class="n">${esc(o.name)}<span class="badge ${s.tag}">${esc(o.category)}</span></h2>
    <div class="path">${esc(path(id))} · id=${esc(id)} · L${d}</div>
    <div class="desc">${esc(o.description)}</div>`;
  h+=`<div class="stat" style="grid-template-columns:repeat(4,1fr)">
      <div class="sbox"><div class="snum">${ch.length}</div><div class="slab">直接子节点</div></div>
      <div class="sbox"><div class="snum">${as.length}</div><div class="slab">自有属性</div></div>
      <div class="sbox"><div class="snum">${cs.length}</div><div class="slab">关联约束</div></div>
      <div class="sbox"><div class="snum">${rs.length}</div><div class="slab">关联关系</div></div></div>`;

  if(o.chain&&o.chain.length){
    h+=`<h3 class="s">组成单机链（有序 ${o.chain.length} 个）</h3>`;
    h+=pipe(o.chain);
  }
  if(ch.length){
    h+=`<h3 class="s">子节点（${ch.length}）</h3><div>`;
    ch.forEach(k=>{const ks=catOf(oMap.get(k));
      h+=`<span class="tag ${ks.tag} link" onclick="select('${k.id}')">${esc(k.name)}</span>`;});
    h+=`</div>`;
  }
  h+=`<h3 class="s">属性（${as.length}）</h3>`;
  if(as.length){
    h+=`<table><thead><tr><th>符号</th><th>名称</th><th>说明</th><th>id</th></tr></thead><tbody>`;
    as.forEach(a=>{h+=`<tr><td><span class="formula">${esc(a.symbol)}</span></td><td><b>${esc(a.name)}</b></td>
      <td>${esc(a.description)}</td><td class="mono" style="color:var(--tx3)">${esc(a.id)}</td></tr>`;});
    h+=`</tbody></table>`;
  } else h+=`<div class="empty">无直接挂载属性（属性挂在子节点上，或作为约束成员引用）</div>`;

  if(rs.length){
    const out=rs.filter(r=>r.from===id),inn=rs.filter(r=>r.to===id);
    h+=`<h3 class="s">关系（${rs.length}）</h3>`;
    if(out.length){h+=`<div style="margin-bottom:5px;color:var(--tx2);font-size:12px">出边：</div>`;
      out.forEach(r=>{const t=oMap.get(r.to);h+=`<span class="tag tg-b link" onclick="select('${t.id}')"
        title="${esc(r.description)}">—${esc(r.type)}→ ${esc(t.name)}</span>`;});}
    if(inn.length){h+=`<div style="margin:8px 0 5px;color:var(--tx2);font-size:12px">入边：</div>`;
      inn.forEach(r=>{const f=oMap.get(r.from);h+=`<span class="tag tg-t link" onclick="select('${f.id}')"
        title="${esc(r.description)}">←${esc(r.type)}— ${esc(f.name)}</span>`;});}
  }
  if(cs.length){
    h+=`<h3 class="s">关联约束（${cs.length}）</h3>`;
    cs.forEach(c=>{h+=consBox(c);});
  }
  const par=o.parentId?oMap.get(o.parentId):null;
  if(par)h+=`<h3 class="s">上级</h3><span class="tag ${catOf(par).tag} link" onclick="select('${par.id}')">${esc(par.name)}</span>`;
  document.getElementById('pNode').innerHTML=h;
  document.getElementById('pNode').scrollTop=0;
}
function consBox(c){
  let h=`<div class="cbox"><div><span class="cid">${esc(c.id)}</span><span class="formula">${esc(c.formula)}</span></div>`;
  h+=`<div class="cdesc">${esc(c.description)}</div><div class="members">`;
  const seen=new Set();
  c.members.forEach(m=>{
    const a=aMap.get(m.attributeId);if(!a)return;
    const o=oMap.get(a.ontologyId);
    const key=a.id+m.role;if(seen.has(key))return;seen.add(key);
    h+=`<span class="tag tg-p link" onclick="select('${o.id}')" title="${esc(o.name)} · ${esc(a.name)}">
        <b>${esc(m.role)}</b> ← ${esc(a.symbol)} · ${esc(o.name)}</span>`;
  });
  return h+`</div></div>`;
}

function renderChain(){
  const chains=O.filter(o=>o.chain&&o.chain.length);
  const links=chains.filter(o=>o.category==='链路');
  const archs=chains.filter(o=>o.category!=='链路');
  let h=`<h2 class="n">链路单机链</h2>
    <div class="path">共 ${chains.length} 条有序单机链（链路 ${links.length} / 体制 ${archs.length}），点击单机名可跳转节点</div>
    <div class="desc">射频链路与通信链路均下沉到所属分系统内部，每条链路显式给出信号流经的单机顺序；
    转发体制给出该体制的单机组成链。</div>`;
  const sec=(title,list,tag)=>{
    let s=`<h3 class="s">${title}（${list.length}）</h3>`;
    list.forEach(o=>{
      const par=oMap.get(o.parentId);
      s+=`<div class="cbox"><div><span class="tag ${tag} link" onclick="select('${o.id}')"><b>${esc(o.name)}</b></span>
        <span style="color:var(--tx3);font-size:11.5px;margin-left:6px">${esc(par?par.name:'')} · ${o.chain.length} 个单机</span></div>
        <div class="cdesc">${esc(o.description)}</div>${pipe(o.chain)}</div>`;
    });
    return s;
  };
  h+=sec('转发体制单机链',archs,'tg-c');
  h+=sec('链路与通道',links,'tg-g');
  document.getElementById('pChain').innerHTML=h;
}
function renderCons(){
  let h=`<h2 class="n">约束清单</h2><div class="path">共 ${C.length} 条工程判据，点击成员标签跳转节点</div>
    <div class="desc">约束覆盖指标合成、链路预算、容量与频率规划、EMC 与热控、质量功耗预算、激光 ATP、
    星内数据链路、货架优先、需求闭环与体制选择。</div>`;
  const groups=[['天线指标合成（EIRP / G/T / 增益 / 面精度 / 指向）',c=>['c-1','c-2','c-3','c-4','c-5','c-6','c-23'].includes(c.id)],
    ['链路预算与容量（FSPL / C-N0 / C-N / 余量 / 容量 / 频率规划）',c=>['c-7','c-8','c-9','c-10','c-11','c-12','c-13'].includes(c.id)],
    ['DTP 与波束能力一致性',c=>['c-14','c-25'].includes(c.id)],
    ['EMC / 热控 / 质量功耗预算',c=>['c-15','c-16','c-17'].includes(c.id)],
    ['激光通信判据',c=>['c-18','c-19'].includes(c.id)],
    ['星内数据链路与智能处理',c=>c.id==='c-20'],
    ['货架优先与需求闭环',c=>c.id==='c-21'||c.id==='c-22'],
    ['体制选择',c=>c.id==='c-24']];
  groups.forEach(([t,f])=>{
    const list=C.filter(f);if(!list.length)return;
    h+=`<h3 class="s">${esc(t)}（${list.length}）</h3>`;
    list.forEach(c=>{h+=consBox(c);});
  });
  const shown=new Set(groups.flatMap(g=>C.filter(g[1]).map(c=>c.id)));
  const rest=C.filter(c=>!shown.has(c.id));
  if(rest.length){h+=`<h3 class="s">其他（${rest.length}）</h3>`;rest.forEach(c=>{h+=consBox(c);});}
  document.getElementById('pCons').innerHTML=h;
}
function renderRel(){
  const types=[...new Set(R.map(r=>r.type))];
  let h=`<h2 class="n">关系图谱</h2><div class="path">共 ${R.length} 条边，${types.length} 种关系类型</div>
    <div class="desc">「组成单机」类关系由 chain 字段自动派生，表达链路/体制的有序单机组成；
    其余为指标分配、频段适配、体制归属、控制、协同、衔接等语义关系。</div>`;
  types.sort((a,b)=>R.filter(r=>r.type===b).length-R.filter(r=>r.type===a).length);
  types.forEach(t=>{
    const list=R.filter(r=>r.type===t);
    h+=`<h3 class="s">${esc(t)}（${list.length}）</h3><table><thead><tr><th>源</th><th></th><th>目标</th><th>说明</th></tr></thead><tbody>`;
    list.forEach(r=>{
      const f=oMap.get(r.from),tt=oMap.get(r.to);
      h+=`<tr><td><span class="link" onclick="select('${f.id}')">${esc(f.name)}</span></td>
        <td style="text-align:center;color:var(--tx3)">→</td>
        <td><span class="link" onclick="select('${tt.id}')">${esc(tt.name)}</span></td>
        <td style="color:var(--tx2)">${esc(r.description)}</td></tr>`;
    });
    h+=`</tbody></table>`;
  });
  document.getElementById('pRel').innerHTML=h;
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
    const s=catOf(o);
    h+=`<h3 class="s"><span class="tag ${s.tag} link" onclick="select('${o.id}')">${esc(o.name)}</span>
        <span style="color:var(--tx3);font-weight:400;font-size:11.5px;margin-left:5px">${o.category} · ${as.length}</span></h3>`;
    h+=`<table><thead><tr><th>符号</th><th>名称</th><th>说明</th></tr></thead><tbody>`;
    as.forEach(a=>{h+=`<tr><td><span class="formula">${esc(a.symbol)}</span></td><td><b>${esc(a.name)}</b></td><td>${esc(a.description)}</td></tr>`;});
    h+=`</tbody></table>`;
  });
  document.getElementById('atbl').innerHTML=h||'<div class="empty">无匹配属性</div>';
}
function renderStat(){
  const l1=kids.get('comm_payload')||[];
  const cats=[...new Set(O.map(o=>o.category))];
  const cnt=cats.map(c=>[c,O.filter(o=>o.category===c).length]);
  const maxCat=Math.max(...cnt.map(x=>x[1]));
  let h=`<h2 class="n">统计概览</h2><div class="path">图谱规模与分布</div>`;
  h+=`<div class="stat"><div class="sbox"><div class="snum">${O.length}</div><div class="slab">本体节点</div></div>
      <div class="sbox"><div class="snum">${A.length}</div><div class="slab">属性</div></div>
      <div class="sbox"><div class="snum">${C.length}</div><div class="slab">约束</div></div>
      <div class="sbox"><div class="snum">${R.length}</div><div class="slab">关系</div></div></div>`;
  h+=`<h3 class="s">category 分布</h3>`;
  cnt.sort((a,b)=>b[1]-a[1]).forEach(([c,n])=>{
    const s=CAT_STYLE[c]||CAT_STYLE['基础'];
    h+=`<div class="lvl"><span class="ln">${n}</span>
      <span class="bar" style="width:${Math.round(n/maxCat*230)}px;background:${s.c}"></span>
      <span class="tag ${s.tag}">${c}</span></div>`;
  });
  h+=`<h3 class="s">一级分系统规模（含子树）</h3><table><thead>
    <tr><th>分系统</th><th>节点</th><th>分组</th><th>体制</th><th>单机</th><th>链路</th><th>属性</th></tr></thead><tbody>`;
  l1.forEach(id=>{
    const sub=subtree(id);
    const c=x=>sub.filter(i=>oMap.get(i).category===x).length;
    h+=`<tr><td><span class="link" onclick="select('${id}')">${esc(oMap.get(id).name)}</span></td>
      <td>${sub.length}</td><td>${c('分组')}</td><td>${c('体制')}</td><td>${c('单机')}</td><td>${c('链路')}</td>
      <td>${A.filter(a=>sub.includes(a.ontologyId)).length}</td></tr>`;
  });
  h+=`</tbody></table>`;
  h+=`<h3 class="s">关系类型分布</h3><table><thead><tr><th>类型</th><th>数量</th></tr></thead><tbody>`;
  [...new Set(R.map(r=>r.type))].map(t=>[t,R.filter(r=>r.type===t).length]).sort((a,b)=>b[1]-a[1])
    .forEach(([t,n])=>{h+=`<tr><td>${esc(t)}</td><td>${n}</td></tr>`;});
  h+=`</tbody></table>`;
  const chains=O.filter(o=>o.chain&&o.chain.length);
  const units=new Set(chains.flatMap(o=>o.chain));
  h+=`<h3 class="s">结构指标</h3><table><tbody>
    <tr><td>根节点</td><td>通信有效载荷 (comm_payload)，唯一根</td></tr>
    <tr><td>最大层级深度</td><td>L${Math.max(...O.map(o=>depth(o.id)))}</td></tr>
    <tr><td>有序单机链</td><td>${chains.length} 条（链路 ${chains.filter(o=>o.category==='链路').length} / 体制 ${chains.filter(o=>o.category!=='链路').length}）</td></tr>
    <tr><td>被链路引用的单机</td><td>${units.size} 种</td></tr>
    <tr><td>有属性的节点</td><td>${attrByOnt.size} 个（挂载率 ${(attrByOnt.size/O.length*100).toFixed(0)}%）</td></tr>
    <tr><td>被约束引用的属性</td><td>${new Set(C.flatMap(c=>c.members.map(m=>m.attributeId))).size} / ${A.length}</td></tr>
    <tr><td>用户需求覆盖</td><td>${['天线分系统','转发器分系统','激光','智能处理','相控阵','DTP','射频链路','通信链路','单机']
      .map(k=>`<span class="tag tg-g">✓ ${k}</span>`).join('')}</td></tr>
    </tbody></table>`;
  document.getElementById('pStat').innerHTML=h;
}
function sw(t){
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
  ['pNode','pChain','pCons','pRel','pAttr','pStat'].forEach(p=>document.getElementById(p).classList.toggle('hide',p!==t.dataset.p));
  if(t.dataset.p==='pChain')renderChain();
  if(t.dataset.p==='pCons')renderCons();
  if(t.dataset.p==='pRel')renderRel();
  if(t.dataset.p==='pAttr')renderAttr();
  if(t.dataset.p==='pStat')renderStat();
}
function toggleAll(v){
  expanded=v?new Set(O.map(o=>o.id)):new Set(['comm_payload']);
  renderTree(document.getElementById('q').value.trim());
}
let tmr=null;
function doSearch(){clearTimeout(tmr);tmr=setTimeout(()=>renderTree(document.getElementById('q').value.trim()),160);}
function dl(){
  const b=new Blob([document.getElementById('kg').textContent],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='通信有效载荷知识图谱.json';a.click();URL.revokeObjectURL(a.href);
}
buildFilters();renderTree('');select('comm_payload');
</script>
</body>
</html>
"""

cat_count = {}
for o in g["ontologies"]:
    cat_count[o["category"]] = cat_count.get(o["category"], 0) + 1

html = (HTML.replace("__DATA__", DATA_JSON)
        .replace("__N1__", str(N_ONTO)).replace("__N2__", str(N_ATTR))
        .replace("__N3__", str(N_CONS)).replace("__N4__", str(N_REL))
        .replace("__NU__", str(cat_count.get("单机", 0)))
        .replace("__NL__", str(cat_count.get("链路", 0)))
        .replace("__VER__", str(g["version"])).replace("__EXP__", g["exportedAt"][:19].replace("T", " ")))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

checks = [
    ("HTML 非空", len(html) > 15000),
    ("内嵌 JSON 数据块", 'id="kg"' in html and '"ontologies"' in html),
    ("无未替换占位符", not any(t in html for t in ["__DATA__", "__N1__", "__N2__", "__N3__", "__N4__", "__VER__", "__EXP__", "__NU__", "__NL__"])),
    ("树渲染函数", "renderTree" in html),
    ("链路单机链视图", "renderChain" in html),
    ("关系视图", "renderRel" in html),
    ("category 过滤", "fCat" in html),
    ("打印样式", "@media print" in html),
    ("JSON 下载", "a.download=" in html),
    ("五分系统出现", all(k in html for k in ["天线分系统", "转发器分系统", "激光通信分系统", "智能处理分系统", "载荷公共基础"])),
    ("关键单机出现", all(k in html for k in ["T/R组件", "低噪声放大器LNA", "行波管功放TWTA", "星上交换矩阵", "光学天线", "AI推理单元"])),
    ("不含卫星系统节点", not any(k in html for k in ['"卫星平台"', '"运载火箭"', '"测控分系统"'])),
]
with open(r"D:\ZWL\文生载荷Workbuddy\output\_viewer_build_log.txt", "w", encoding="utf-8") as f:
    f.write(f"HTML: {OUT} ({len(html)/1024:.1f} KB)\n")
    for name, ok in checks:
        f.write(("  [PASS] " if ok else "  [FAIL] ") + name + "\n")
    f.write(f"自检: {sum(1 for _, o in checks if o)}/{len(checks)} 通过\n")
