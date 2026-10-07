"""Web UI 可视化界面 — 实战导向的单文件 HTML+CSS+JS 仪表盘。

由 api.py 在 GET / 时返回此 HTML。前端纯 vanilla JS，调用 /api/* 端点。
v4.4 重构：从花架子改为实战工具——lint 检查、代码生成+复制、MCP 提速展示、端口检查。
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RTLens — Verilog 工程分析</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #1c2330; --border: #30363d;
  --text: #c9d1d9; --text-dim: #8b949e; --accent: #58a6ff; --accent2: #3fb950;
  --accent3: #d29922; --accent4: #bc8cff; --danger: #f85149; --mono: 'SF Mono','Cascadia Code','Consolas',Menlo,monospace;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg); color:var(--text); font-size:14px; line-height:1.5; }
#app { display:flex; flex-direction:column; height:100vh; }
.header { background:var(--surface); border-bottom:1px solid var(--border); padding:10px 20px; display:flex; align-items:center; gap:12px; flex-shrink:0; }
.logo { font-size:16px; font-weight:700; color:var(--accent); white-space:nowrap; }
.kpi-bar { display:flex; gap:8px; flex-wrap:wrap; }
.kpi { background:var(--surface2); border:1px solid var(--border); border-radius:6px; padding:3px 10px; font-size:12px; }
.kpi .num { font-weight:700; color:var(--accent2); font-size:14px; }
.kpi .lbl { color:var(--text-dim); }
.header-right { margin-left:auto; display:flex; gap:8px; }
.btn { background:var(--surface2); border:1px solid var(--border); color:var(--text); padding:6px 14px; border-radius:6px; cursor:pointer; font-size:13px; transition:.15s; }
.btn:hover { border-color:var(--accent); color:var(--accent); }
.btn-primary { background:#1a3a5c; border-color:var(--accent); color:var(--accent); }
.btn-danger { border-color:var(--danger); color:var(--danger); }
.main { display:flex; flex:1; overflow:hidden; }
.sidebar { width:280px; min-width:240px; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; overflow:hidden; }
.search-box { padding:10px; border-bottom:1px solid var(--border); }
.search-box input { width:100%; background:var(--bg); border:1px solid var(--border); color:var(--text); padding:7px 11px; border-radius:6px; font-size:13px; outline:none; }
.search-box input:focus { border-color:var(--accent); }
.module-list { flex:1; overflow-y:auto; }
.module-list .item { padding:7px 12px; border-bottom:1px solid rgba(48,54,61,.4); cursor:pointer; transition:.12s; }
.module-list .item:hover { background:var(--surface2); }
.module-list .item.active { background:var(--surface2); border-left:3px solid var(--accent); }
.module-list .item .name { font-weight:600; font-family:var(--mono); font-size:13px; }
.module-list .item .kind { font-size:11px; color:var(--text-dim); }
.content { flex:1; overflow-y:auto; padding:16px 24px; }
.tabs { display:flex; gap:2px; border-bottom:2px solid var(--border); margin-bottom:16px; flex-wrap:wrap; }
.tab { padding:7px 16px; cursor:pointer; color:var(--text-dim); border-bottom:2px solid transparent; margin-bottom:-2px; font-size:13px; font-weight:500; transition:.15s; }
.tab:hover { color:var(--text); }
.tab.active { color:var(--accent); border-bottom-color:var(--accent); }
.tab .badge { background:var(--danger); color:#fff; font-size:10px; padding:1px 5px; border-radius:8px; margin-left:4px; }
.tab-content { display:none; }
.tab-content.active { display:block; }
table { border-collapse:collapse; width:100%; margin-bottom:16px; }
th { text-align:left; background:var(--surface2); color:var(--text-dim); font-size:11px; text-transform:uppercase; letter-spacing:.5px; padding:7px 10px; border-bottom:1px solid var(--border); }
td { padding:7px 10px; border-bottom:1px solid rgba(48,54,61,.3); font-family:var(--mono); font-size:12px; }
tr:hover { background:var(--surface2); }
.dir-in { color:var(--accent3); } .dir-out { color:var(--accent2); } .dir-inout { color:var(--accent4); }
.section-title { font-size:15px; font-weight:700; color:var(--text); margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.section-title .count { background:var(--surface2); color:var(--accent); font-size:11px; padding:2px 7px; border-radius:10px; font-weight:600; }
.empty { color:var(--text-dim); padding:40px; text-align:center; }
.loading { color:var(--text-dim); padding:16px; }
.module-header { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px 18px; margin-bottom:16px; }
.module-header .title { font-size:18px; font-family:var(--mono); font-weight:700; color:var(--accent); }
.module-header .meta { font-size:12px; color:var(--text-dim); margin-top:4px; }
.code-block { background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:12px 16px; font-family:var(--mono); font-size:12px; line-height:1.6; overflow-x:auto; white-space:pre; position:relative; }
.code-block .copy-btn { position:absolute; top:8px; right:8px; background:var(--surface2); border:1px solid var(--border); color:var(--text-dim); padding:3px 10px; border-radius:4px; cursor:pointer; font-size:11px; }
.code-block .copy-btn:hover { color:var(--accent); border-color:var(--accent); }
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:12px; }
.stat-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:16px; }
.stat-card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; text-align:center; }
.stat-card .num { font-size:24px; font-weight:800; color:var(--accent); }
.stat-card .num.green { color:var(--accent2); } .stat-card .num.yellow { color:var(--accent3); } .stat-card .num.red { color:var(--danger); }
.stat-card .lbl { font-size:11px; color:var(--text-dim); margin-top:2px; }
.speedup-bar { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:12px; }
.speedup-bar .big { font-size:32px; font-weight:800; color:var(--accent2); }
.speedup-bar .lbl { font-size:13px; color:var(--text-dim); }
.bar-chart { display:flex; align-items:end; gap:12px; height:120px; margin-top:12px; }
.bar-item { flex:1; display:flex; flex-direction:column; align-items:center; gap:4px; }
.bar { width:100%; border-radius:4px 4px 0 0; transition:.3s; min-height:2px; }
.bar.mcp { background:var(--accent2); } .bar.grep { background:var(--accent3); }
.bar-item .lbl { font-size:11px; color:var(--text-dim); }
.bar-item .val { font-size:11px; font-weight:600; }
.issue-badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }
.issue-badge.missing { background:rgba(248,81,73,.15); color:var(--danger); border:1px solid rgba(248,81,73,.3); }
.issue-badge.extra { background:rgba(210,153,34,.15); color:var(--accent3); border:1px solid rgba(210,153,34,.3); }
.issue-badge.mismatch { background:rgba(188,140,255,.15); color:var(--accent4); border:1px solid rgba(188,140,255,.3); }
select { background:var(--bg); border:1px solid var(--border); color:var(--text); padding:7px 11px; border-radius:6px; font-family:var(--mono); font-size:13px; }
input[type=text] { background:var(--bg); border:1px solid var(--border); color:var(--text); padding:7px 11px; border-radius:6px; font-family:var(--mono); font-size:13px; }
::-webkit-scrollbar { width:8px; height:8px; } ::-webkit-scrollbar-track { background:var(--bg); } ::-webkit-scrollbar-thumb { background:var(--border); border-radius:4px; }
.tree { font-family:var(--mono); font-size:12px; line-height:1.8; }
.tree-node { cursor:pointer; user-select:none; }
.tree-node .toggle { color:var(--text-dim); display:inline-block; width:16px; }
.tree-node .mod-type { color:var(--accent4); font-weight:600; }
.tree-node .inst-name { color:var(--text-dim); }
.tree-children { margin-left:18px; border-left:1px solid var(--border); padding-left:10px; }
.lint-row { padding:8px 12px; border-bottom:1px solid rgba(48,54,61,.3); font-size:12px; }
.lint-row .line-num { color:var(--accent3); font-family:var(--mono); font-weight:600; margin-right:8px; }
.lint-row .rule { background:var(--surface2); padding:1px 6px; border-radius:3px; font-size:10px; color:var(--accent4); margin-left:8px; }
.lint-row:hover { background:var(--surface2); }
.pill { display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; font-weight:600; }
.pill.ok { background:rgba(63,185,80,.15); color:var(--accent2); } .pill.fail { background:rgba(248,81,73,.15); color:var(--danger); }
.graph-svg { width:100%; height:600px; background:var(--bg); border:1px solid var(--border); border-radius:8px; }
.graph-node { cursor:pointer; }
.graph-node rect { fill:var(--surface2); stroke:var(--accent); stroke-width:1.5; rx:6; }
.graph-node:hover rect { fill:var(--surface); stroke-width:2.5; }
.graph-node text { fill:var(--text); font-family:var(--mono); font-size:12px; font-weight:600; text-anchor:middle; }
.graph-node.top rect { stroke:var(--accent2); stroke-width:2.5; fill:rgba(63,185,80,.1); }
.graph-edge { stroke:var(--text-dim); stroke-width:1; fill:none; marker-end:url(#arrow); opacity:.5; }
.graph-edge:hover { stroke:var(--accent); opacity:1; }
.search-result { padding:6px 12px; border-bottom:1px solid rgba(48,54,61,.3); font-family:var(--mono); font-size:12px; cursor:pointer; }
.search-result:hover { background:var(--surface2); }
.search-result .file { color:var(--accent); }
.search-result .line { color:var(--accent3); margin-right:8px; }
.search-result .text { color:var(--text); }
.search-result .match { background:rgba(88,166,255,.2); border-radius:2px; padding:0 2px; }
/* ---- 实时监控 ---- */
.mon-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; margin-bottom:16px; }
.mon-card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px; position:relative; overflow:hidden; }
.mon-card .num { font-size:28px; font-weight:800; font-family:var(--mono); }
.mon-card .num.green { color:var(--accent2); } .mon-card .num.blue { color:var(--accent); }
.mon-card .num.yellow { color:var(--accent3); } .mon-card .num.red { color:var(--danger); } .mon-card .num.purple { color:var(--accent4); }
.mon-card .lbl { font-size:11px; color:var(--text-dim); margin-top:4px; }
.mon-card .sub { font-size:10px; color:var(--text-dim); margin-top:2px; }
.mon-live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--accent2); animation:pulse 1.5s ease-in-out infinite; margin-right:5px; vertical-align:middle; }
@keyframes pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:.4; transform:scale(.8); } }
.mon-chart-wrap { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:16px; }
.mon-chart-title { font-size:14px; font-weight:700; margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.mon-chart-canvas { width:100%; height:200px; }
.mon-table { width:100%; border-collapse:collapse; font-size:12px; }
.mon-table th { text-align:left; background:var(--surface2); color:var(--text-dim); font-size:10px; text-transform:uppercase; padding:6px 10px; border-bottom:1px solid var(--border); }
.mon-table td { padding:6px 10px; border-bottom:1px solid rgba(48,54,61,.3); font-family:var(--mono); }
.mon-table tr:hover { background:var(--surface2); }
.mon-status-ok { color:var(--accent2); } .mon-status-fail { color:var(--danger); }
.mon-bar-row { display:flex; align-items:center; gap:8px; margin-bottom:4px; }
.mon-bar-label { width:140px; font-family:var(--mono); font-size:11px; color:var(--text-dim); }
.mon-bar-track { flex:1; height:20px; background:var(--bg); border-radius:4px; overflow:hidden; }
.mon-bar-fill { height:100%; border-radius:4px; transition:width .5s ease; }
.mon-bar-val { width:60px; text-align:right; font-family:var(--mono); font-size:11px; font-weight:600; }
.mon-refresh-bar { display:flex; align-items:center; gap:10px; margin-bottom:12px; font-size:12px; color:var(--text-dim); }
.mon-toggle { background:var(--surface2); border:1px solid var(--border); color:var(--text); padding:4px 12px; border-radius:6px; cursor:pointer; font-size:12px; }
.mon-toggle.active { background:#1a3a5c; border-color:var(--accent); color:var(--accent); }
.mon-mem-bar { height:8px; background:var(--bg); border-radius:4px; overflow:hidden; margin-top:6px; }
.mon-mem-fill { height:100%; background:linear-gradient(90deg,var(--accent2),var(--accent3)); border-radius:4px; transition:width .5s; }
</style>
</head>
<body>
<div id="app">
  <div class="header">
    <div class="logo">⚡ RTLens</div>
    <div class="kpi-bar" id="kpiBar"></div>
    <div class="header-right">
      <button class="btn" onclick="showIndexDialog()">📁 索引</button>
      <button class="btn" onclick="loadAll()">🔄 刷新</button>
    </div>
  </div>
  <div class="main">
    <div class="sidebar">
      <div class="search-box"><input type="text" id="searchInput" placeholder="搜索模块/符号..." oninput="onSearch()"></div>
      <div class="module-list" id="moduleList"><div class="loading">加载中...</div></div>
    </div>
    <div class="content">
      <div class="tabs">
        <div class="tab active" data-tab="overview" onclick="switchTab('overview')">概览</div>
        <div class="tab" data-tab="module" onclick="switchTab('module')">模块</div>
        <div class="tab" data-tab="codegen" onclick="switchTab('codegen')">代码生成</div>
        <div class="tab" data-tab="trace" onclick="switchTab('trace')">信号追踪</div>
        <div class="tab" data-tab="lint" onclick="switchTab('lint')">Lint 检查</div>
        <div class="tab" data-tab="hierarchy" onclick="switchTab('hierarchy')">层级</div>
        <div class="tab" data-tab="portcheck" onclick="switchTab('portcheck')">端口检查</div>
        <div class="tab" data-tab="graph" onclick="switchTab('graph')">依赖图</div>
        <div class="tab" data-tab="search" onclick="switchTab('search')">搜索</div>
        <div class="tab" data-tab="monitor" onclick="switchTab('monitor')">📊 实时监控</div>
      </div>
      <div class="tab-content active" id="tab-overview"><div class="loading">加载中...</div></div>
      <div class="tab-content" id="tab-module"><div class="empty">从左侧选择模块查看详情</div></div>
      <div class="tab-content" id="tab-codegen"><div class="empty">选择模块后生成代码</div></div>
      <div class="tab-content" id="tab-trace">
        <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
          <input type="text" id="traceSignal" placeholder="信号名 如 clk / rst_n" style="width:200px" onkeydown="if(event.key==='Enter')doTrace()">
          <button class="btn btn-primary" onclick="doTrace()">追踪</button>
        </div>
        <div id="traceResult"></div>
      </div>
      <div class="tab-content" id="tab-lint">
        <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <select id="lintFile" style="min-width:300px"></select>
          <button class="btn btn-primary" onclick="runLint()">Run Lint</button>
          <button class="btn" onclick="runSyntax()">语法检查</button>
          <button class="btn btn-danger" onclick="runBatchLint()">⚡ 批量 Lint 全部文件</button>
        </div>
        <div id="lintResult"></div>
      </div>
      <div class="tab-content" id="tab-hierarchy">
        <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
          <select id="hierTop" style="min-width:200px"></select>
          <button class="btn btn-primary" onclick="loadHierarchy()">生成</button>
        </div>
        <div class="tree" id="hierTree"><div class="empty">选择顶层模块后点击"生成"</div></div>
      </div>
      <div class="tab-content" id="tab-portcheck"><div class="loading">点击"端口检查"标签自动检查...</div></div>
      <div class="tab-content" id="tab-graph"><div class="loading">加载模块依赖图...</div></div>
      <div class="tab-content" id="tab-search">
        <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
          <input type="text" id="codeSearchInput" placeholder="正则表达式 如 assign.*clk 或 module\s+\w+" style="width:400px" onkeydown="if(event.key==='Enter')doCodeSearch()">
          <button class="btn btn-primary" onclick="doCodeSearch()">搜索</button>
        </div>
        <div id="searchResult"><div class="empty">输入正则表达式搜索全部已索引文件</div></div>
      </div>
      <div class="tab-content" id="tab-monitor">
        <div class="mon-refresh-bar">
          <span class="mon-live-dot"></span><span id="monLiveStatus">实时采集中</span>
          <span>·</span><span id="monUptime">运行时间: --</span>
          <span>·</span><span>刷新间隔:</span>
          <button class="mon-toggle active" onclick="monSetInterval(2000,this)">2s</button>
          <button class="mon-toggle" onclick="monSetInterval(5000,this)">5s</button>
          <button class="mon-toggle" onclick="monSetInterval(10000,this)">10s</button>
          <button class="mon-toggle" onclick="monTogglePause(this)">⏸ 暂停</button>
        </div>
        <div class="mon-grid" id="monKpiGrid"><div class="loading">等待数据...</div></div>
        <div class="mon-chart-wrap">
          <div class="mon-chart-title">📈 操作耗时趋势（最近 50 次操作）</div>
          <canvas class="mon-chart-canvas" id="monChart" width="800" height="200"></canvas>
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap">
          <div style="flex:1;min-width:400px">
            <div class="mon-chart-wrap">
              <div class="mon-chart-title">按操作类型统计</div>
              <div id="monTypeStats"><div class="loading">等待数据...</div></div>
            </div>
          </div>
          <div style="flex:1;min-width:400px">
            <div class="mon-chart-wrap">
              <div class="mon-chart-title">系统资源</div>
              <div id="monResource"><div class="loading">等待数据...</div></div>
            </div>
          </div>
        </div>
        <div class="mon-chart-wrap">
          <div class="mon-chart-title">最近操作日志（实时）</div>
          <div id="monRecentOps"><div class="loading">等待数据...</div></div>
        </div>
      </div>
    </div>
  </div>
</div>
<script>
let currentModule=null;
async function api(path){const r=await fetch(path);return r.json();}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ---- KPI ----
async function loadStats(){
  const s=await api('/api/stats');
  const kpis=[['files','文件'],['modules','模块'],['ports','端口'],['signals','信号'],['instances','实例'],['params','参数']];
  document.getElementById('kpiBar').innerHTML=kpis.map(([k,l])=>`<div class="kpi"><span class="num">${s[k]||0}</span> <span class="lbl">${l}</span></div>`).join('');
}

// ---- Module list ----
async function loadSymbols(query){
  const url=query?`/api/symbols?query=${encodeURIComponent(query)}`:'/api/symbols?query=';
  const syms=await api(url);
  const el=document.getElementById('moduleList');
  if(!syms.length){el.innerHTML='<div class="empty">无结果</div>';return;}
  const sorted=syms.sort((a,b)=>{if(a.kind==='module'&&b.kind!=='module')return-1;if(a.kind!=='module'&&b.kind==='module')return 1;return a.name.localeCompare(b.name);});
  el.innerHTML=sorted.map(s=>`<div class="item" onclick="selectModule('${esc(s.name)}')" data-name="${esc(s.name)}"><div class="name">${esc(s.name)}</div><div class="kind">${s.kind}${s.file?' · '+s.file.split(/[\\/]/).pop():''}</div></div>`).join('');
}
function onSearch(){clearTimeout(window._t);window._t=setTimeout(()=>loadSymbols(document.getElementById('searchInput').value),200);}

// ---- Overview tab ----
async function loadOverview(){
  const el=document.getElementById('tab-overview');
  el.innerHTML='<div class="loading">加载设计总览...</div>';
  try{
    const [stats,analyze,metrics,check]=await Promise.all([
      api('/api/stats'),api('/api/analyze'),api('/api/metrics'),api('/api/check')
    ]);
    let html='<div class="stat-grid">';
    html+=`<div class="stat-card"><div class="num">${stats.files}</div><div class="lbl">文件</div></div>`;
    html+=`<div class="stat-card"><div class="num green">${stats.modules}</div><div class="lbl">模块</div></div>`;
    html+=`<div class="stat-card"><div class="num">${stats.ports}</div><div class="lbl">端口</div></div>`;
    html+=`<div class="stat-card"><div class="num">${stats.instances}</div><div class="lbl">实例</div></div>`;
    html+=`<div class="stat-card"><div class="num yellow">${metrics.overall.max_hierarchy_depth}</div><div class="lbl">最大层级</div></div>`;
    html+=`<div class="stat-card"><div class="num">${metrics.overall.avg_fanout}</div><div class="lbl">平均扇出</div></div>`;
    html+=`<div class="stat-card"><div class="num ${check.length?'red':'green'}">${check.length}</div><div class="lbl">端口问题</div></div>`;
    html+='</div>';

    // Top modules
    if(analyze.summary.top_modules&&analyze.summary.top_modules.length){
      html+='<div class="card"><div class="section-title">顶层模块</div>';
      analyze.summary.top_modules.forEach(m=>{
        const mod=analyze.modules.find(x=>x.name===m);
        html+=`<div style="padding:4px 0"><span style="font-family:var(--mono);color:var(--accent);font-weight:600">${esc(m)}</span> <span style="color:var(--text-dim);font-size:12px">${mod?mod.ports:0} 端口, ${mod?mod.instances:0} 实例</span></div>`;
      });
      html+='</div>';
    }

    // Module list with fan-out
    html+='<div class="card"><div class="section-title">模块扇出 Top 10</div><table><thead><tr><th>模块</th><th>扇入</th><th>扇出</th><th>端口</th><th>层级</th></tr></thead><tbody>';
    metrics.modules.sort((a,b)=>b.fan_out-a.fan_out).slice(0,10).forEach(m=>{
      html+=`<tr style="cursor:pointer" onclick="selectModule('${esc(m.name)}')"><td style="color:var(--accent)">${esc(m.name)}</td><td>${m.fan_in}</td><td style="color:var(--accent3)">${m.fan_out}</td><td>${m.ports}</td><td>${m.hierarchy_depth}</td></tr>`;
    });
    html+='</tbody></table></div>';

    // Port check summary
    if(check.length){
      html+=`<div class="card"><div class="section-title">端口连接问题 <span class="count" style="background:var(--danger);color:#fff">${check.length}</span></div>`;
      html+='<table><thead><tr><th>类型</th><th>模块</th><th>实例</th><th>详情</th></tr></thead><tbody>';
      check.slice(0,10).forEach(i=>{
        const cls=i.type==='missing_port'?'missing':(i.type==='extra_port'?'extra':'mismatch');
        const detail=i.missing_ports?i.missing_ports.join(', '):(i.extra_ports?i.extra_ports.join(', '):`${i.expected}→${i.actual}`);
        html+=`<tr><td><span class="issue-badge ${cls}">${i.type}</span></td><td>${esc(i.module)}</td><td>${esc(i.instance)}</td><td style="color:var(--text-dim)">${esc(detail)}</td></tr>`;
      });
      html+='</tbody></table>';
      if(check.length>10)html+=`<div style="text-align:center;padding:8px"><button class="btn" onclick="switchTab('portcheck')">查看全部 ${check.length} 条</button></div>`;
      html+='</div>';
    }

    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">加载失败: '+esc(e.message)+'</div>';}
}

// ---- Speedup benchmark ----
async function loadBenchmark(){
  try{
    const b=await api('/api/benchmark');
    if(b.error){document.getElementById('benchmarkArea').innerHTML='<div class="empty">'+esc(b.error)+'</div>';return;}
    let html=`<div class="speedup-bar"><div class="big">${b.avg_speedup}x</div><div class="lbl">${esc(b.summary||'')}</div></div>`;
    html+='<div class="card"><div class="section-title">逐符号对比</div><table><thead><tr><th>符号</th><th>MCP (ms)</th><th>grep (ms)</th><th>提速</th><th>MCP 结果</th><th>grep 匹配</th></tr></thead><tbody>';
    b.tests.forEach(t=>{
      html+=`<tr><td style="color:var(--accent);font-family:var(--mono)">${esc(t.symbol)}</td>`;
      html+=`<td style="color:var(--accent2)">${t.mcp_time_ms}</td>`;
      html+=`<td style="color:var(--accent3)">${t.grep_time_ms||'N/A'}</td>`;
      html+=`<td style="font-weight:700;color:var(--accent2)">${t.speedup?t.speedup+'x':'-'}</td>`;
      html+=`<td>${t.mcp_ref_count}</td><td>${t.grep_match_count}</td></tr>`;
    });
    html+='</tbody></table></div>';
    document.getElementById('benchmarkArea').innerHTML=html;
  }catch(e){document.getElementById('benchmarkArea').innerHTML='<div class="empty">'+esc(e.message)+'</div>';}
}

// ---- Module detail ----
async function selectModule(name){
  document.querySelectorAll('.module-list .item').forEach(el=>el.classList.toggle('active',el.dataset.name===name));
  currentModule=name;
  switchTab('module');
  const el=document.getElementById('tab-module');
  el.innerHTML='<div class="loading">加载中...</div>';
  try{
    const mod=await api('/api/module/'+encodeURIComponent(name));
    let html=`<div class="module-header"><div class="title">module ${esc(mod.name)}</div><div class="meta">${mod.range?mod.range.start_line+'行':''}</div></div>`;
    if(mod.ports&&mod.ports.length){
      html+=`<div class="section-title">端口 <span class="count">${mod.ports.length}</span></div><table><thead><tr><th>方向</th><th>类型</th><th>位宽</th><th>名称</th></tr></thead><tbody>`;
      mod.ports.forEach(p=>{html+=`<tr><td class="${p.direction==='input'?'dir-in':p.direction==='output'?'dir-out':'dir-inout'}">${p.direction||'?'}</td><td>${esc(p.type)||'wire'}</td><td>${esc(p.width)||'1'}</td><td style="color:var(--accent)">${esc(p.name)}</td></tr>`;});
      html+='</tbody></table>';
    }
    if(mod.params&&mod.params.length){
      html+=`<div class="section-title">参数 <span class="count">${mod.params.length}</span></div><table><thead><tr><th>名称</th><th>默认值</th></tr></thead><tbody>`;
      mod.params.forEach(p=>{html+=`<tr><td style="color:var(--accent4)">${esc(p.name)}</td><td>${esc(p.detail)||'-'}</td></tr>`;});
      html+='</tbody></table>';
    }
    if(mod.signals&&mod.signals.length){
      html+=`<div class="section-title">内部信号 <span class="count">${mod.signals.length}</span></div><table><thead><tr><th>类型</th><th>位宽</th><th>名称</th></tr></thead><tbody>`;
      mod.signals.forEach(s=>{html+=`<tr><td>${esc(s.type)||'wire'}</td><td>${esc(s.width)||'1'}</td><td>${esc(s.name)}</td></tr>`;});
      html+='</tbody></table>';
    }
    if(mod.instances&&mod.instances.length){
      html+=`<div class="section-title">实例化 <span class="count">${mod.instances.length}</span></div>`;
      mod.instances.forEach(inst=>{
        html+=`<div class="card" style="padding:10px"><div style="font-family:var(--mono);font-weight:600;margin-bottom:6px"><span style="color:var(--accent4)">${esc(inst.module_type)}</span> <span style="color:var(--text-dim)">${esc(inst.inst_name)}</span></div>`;
        if(inst.connections&&inst.connections.length){
          html+='<table style="margin-bottom:0"><thead><tr><th>端口</th><th>信号</th></tr></thead><tbody>';
          inst.connections.forEach(c=>{html+=`<tr><td style="color:var(--accent)">${esc(c.port)||'(pos)'}</td><td>${esc(c.signal)||'-'}</td></tr>`;});
          html+='</tbody></table>';
        }
        html+='</div>';
      });
    }
    if(!html.includes('section-title'))html+='<div class="empty">此模块无端口/信号/实例</div>';
    el.innerHTML=html;
    // 同时更新 codegen tab 的模块选择
    updateCodegenModule(name);
  }catch(e){el.innerHTML='<div class="empty">加载失败</div>';}
}

// ---- Code generation tab ----
function updateCodegenModule(name){
  const sel=document.getElementById('codegenModule');
  if(sel)sel.value=name;
}
async function loadCodegenModuleList(){
  const sel=document.getElementById('codegenModule');
  if(!sel)return;
  try{
    const a=await api('/api/analyze');
    sel.innerHTML='<option value="">选择模块...</option>'+a.modules.map(m=>`<option value="${esc(m.name)}">${esc(m.name)} (${m.ports}p)</option>`).join('');
    if(currentModule)sel.value=currentModule;
  }catch(e){}
}
async function genTestbench(){
  const mod=document.getElementById('codegenModule').value;
  if(!mod){alert('请选择模块');return;}
  const r=await api('/api/template/testbench/'+encodeURIComponent(mod));
  showCode(r.code,'testbench_'+mod+'.v');
}
async function genInstantiation(){
  const mod=document.getElementById('codegenModule').value;
  if(!mod){alert('请选择模块');return;}
  const r=await api('/api/template/instantiation/'+encodeURIComponent(mod));
  showCode(r.code,'inst_'+mod+'.v');
}
async function genContext(){
  const mod=document.getElementById('codegenModule').value;
  const r=await api('/api/context'+(mod?'?module='+encodeURIComponent(mod):''));
  showCode(r.text,'context.txt');
}
function showCode(code,filename){
  const el=document.getElementById('tab-codegen');
  let html='<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">';
  html+='<select id="codegenModule" onchange="" style="min-width:200px"></select>';
  html+='<button class="btn btn-primary" onclick="genTestbench()">生成 Testbench</button>';
  html+='<button class="btn btn-primary" onclick="genInstantiation()">生成实例化</button>';
  html+='<button class="btn" onclick="genContext()">AI 上下文</button>';
  html+='</div>';
  html+=`<div class="code-block"><button class="copy-btn" onclick="copyCode(this)">复制</button>${esc(code)}</div>`;
  el.innerHTML=html;
  loadCodegenModuleList();
}
function copyCode(btn){
  const code=btn.parentElement.textContent.replace('复制','').trim();
  navigator.clipboard.writeText(code).then(()=>{btn.textContent='✓ 已复制';setTimeout(()=>btn.textContent='复制',2000);});
}

// ---- Signal trace ----
async function doTrace(){
  const sig=document.getElementById('traceSignal').value.trim();
  if(!sig){alert('请输入信号名');return;}
  const el=document.getElementById('traceResult');
  el.innerHTML='<div class="loading">追踪中...</div>';
  try{
    const r=await api('/api/trace/'+encodeURIComponent(sig));
    let html=`<div class="card"><div class="section-title">追踪: ${esc(sig)} ${r.truncated?'<span class="issue-badge mismatch">已截断</span>':''}</div>`;
    html+=`<div style="font-size:12px;color:var(--text-dim)">驱动源 ${r.driver_count} · 使用点 ${r.usage_count}</div></div>`;
    if(r.drivers&&r.drivers.length){
      html+='<div class="section-title">驱动源</div><table><thead><tr><th>文件</th><th>行</th><th>上下文</th></tr></thead><tbody>';
      r.drivers.forEach(d=>{html+=`<tr><td style="font-size:11px">${esc(d.file.split(/[\\/]/).pop())}</td><td style="color:var(--accent3)">${d.line}</td><td>${esc(d.context)}</td></tr>`;});
      html+='</tbody></table>';
    }
    if(r.usages&&r.usages.length){
      html+='<div class="section-title">使用点</div><table><thead><tr><th>文件</th><th>行</th><th>上下文</th></tr></thead><tbody>';
      r.usages.forEach(u=>{html+=`<tr><td style="font-size:11px">${esc(u.file.split(/[\\/]/).pop())}</td><td style="color:var(--accent3)">${u.line}</td><td>${esc(u.context)}</td></tr>`;});
      html+='</tbody></table>';
    }
    if(!r.drivers.length&&!r.usages.length)html='<div class="empty">未找到此信号的引用</div>';
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">追踪失败</div>';}
}

// ---- Lint ----
async function loadFileList(){
  try{
    const files=await api('/api/files');
    const sel=document.getElementById('lintFile');
    sel.innerHTML='<option value="">选择文件...</option>'+files.map(f=>`<option value="${esc(f)}">${esc(f.split(/[\\/]/).pop())}</option>`).join('');
  }catch(e){}
}
async function runLint(){
  const f=document.getElementById('lintFile').value;
  if(!f){alert('请选择文件');return;}
  const el=document.getElementById('lintResult');
  el.innerHTML='<div class="loading">Lint 运行中...（大文件可能需要 30-60 秒）</div>';
  try{
    const r=await api('/api/lint?file='+encodeURIComponent(f)+'&max_results=200');
    let html='';
    if(r.error){html=`<div class="card"><span class="pill fail">错误</span> ${esc(r.error)}</div>`;el.innerHTML=html;return;}
    if(r.passed){html=`<div class="card"><span class="pill ok">通过</span> 0 个违规</div>`;el.innerHTML=html;return;}
    html+=`<div class="card"><span class="pill fail">${r.violation_count} 个违规</span>`;
    if(r.violations_truncated)html+=` <span style="color:var(--text-dim);font-size:12px">（显示前 ${r.violations.length} 条，完整列表请用 max_results=0）</span>`;
    html+='</div>';
    if(r.by_rule&&Object.keys(r.by_rule).length){
      html+='<div class="card"><div class="section-title">按规则聚合</div><table><thead><tr><th>规则</th><th>数量</th></tr></thead><tbody>';
      Object.entries(r.by_rule).forEach(([rule,count])=>{html+=`<tr><td style="color:var(--accent4)">${esc(rule)}</td><td style="color:var(--accent3);font-weight:600">${count}</td></tr>`;});
      html+='</tbody></table></div>';
    }
    html+='<div class="section-title">违规详情</div>';
    r.violations.forEach(v=>{
      const parts=v.message.split(':');
      const line=parts.length>1?parts[1]:'';
      const msg=parts.length>3?parts.slice(3).join(':'):v.message;
      const ruleMatch=v.message.match(/\[([^\]]+)\]\s*$/);
      const rule=ruleMatch?ruleMatch[1]:'';
      html+=`<div class="lint-row"><span class="line-num">L${esc(line)}</span>${esc(msg)}${rule?`<span class="rule">${esc(rule)}</span>`:''}</div>`;
    });
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">Lint 失败: '+esc(e.message)+'</div>';}
}
async function runSyntax(){
  const f=document.getElementById('lintFile').value;
  if(!f){alert('请选择文件');return;}
  const el=document.getElementById('lintResult');
  el.innerHTML='<div class="loading">语法检查运行中...</div>';
  try{
    const r=await api('/api/syntax-check?file='+encodeURIComponent(f));
    let html='';
    if(r.error){html=`<div class="card"><span class="pill fail">错误</span> ${esc(r.error)}</div>`;el.innerHTML=html;return;}
    if(r.passed){html=`<div class="card"><span class="pill ok">通过</span> 语法检查无误</div>`;el.innerHTML=html;return;}
    html+=`<div class="card"><span class="pill fail">${r.error_count} 个语法错误</span></div>`;
    html+='<div class="section-title">错误详情</div>';
    r.errors.forEach(e=>{html+=`<div class="lint-row"><span class="line-num">L${e.line}:${e.column}</span>${esc(e.message)}</div>`;});
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">语法检查失败</div>';}
}

// ---- Hierarchy ----
async function loadHierarchyModuleList(){
  try{
    const a=await api('/api/analyze');
    const sel=document.getElementById('hierTop');
    sel.innerHTML='<option value="">选择顶层模块...</option>'+a.summary.top_modules.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('');
  }catch(e){}
}
async function loadHierarchy(){
  const top=document.getElementById('hierTop').value;
  if(!top)return;
  const el=document.getElementById('hierTree');
  el.innerHTML='<div class="loading">加载中...</div>';
  try{
    const tree=await api('/api/hierarchy/'+encodeURIComponent(top));
    el.innerHTML='';
    renderTree(tree,el,true);
  }catch(e){el.innerHTML='<div class="empty">加载失败</div>';}
}
function renderTree(node,parent,isRoot){
  const div=document.createElement('div');
  div.className='tree-node';
  const hasChildren=node.instances&&node.instances.length>0;
  if(isRoot){div.innerHTML=`<span class="toggle"></span><span class="mod-type">${esc(node.module)}</span>`;}
  else{
    const toggle=hasChildren?'▼':'•';
    div.innerHTML=`<span class="toggle">${toggle}</span><span class="mod-type">${esc(node.type)}</span> <span class="inst-name">${esc(node.instance)}</span>`;
    if(hasChildren){div.onclick=function(){const ch=this.nextElementSibling;if(ch){ch.style.display=ch.style.display==='none'?'':'none';this.querySelector('.toggle').textContent=ch.style.display==='none'?'▶':'▼';}};}
  }
  parent.appendChild(div);
  if(hasChildren){const c=document.createElement('div');c.className='tree-children';node.instances.forEach(child=>renderTree(child.sub||child,c,false));parent.appendChild(c);}
}

// ---- Port check ----
async function loadPortCheck(){
  const el=document.getElementById('tab-portcheck');
  el.innerHTML='<div class="loading">检查端口连接...</div>';
  try{
    const issues=await api('/api/check');
    if(!issues.length){el.innerHTML='<div class="card"><span class="pill ok">通过</span> 所有端口连接匹配，无问题。</div>';return;}
    let html=`<div class="card"><span class="pill fail">${issues.length} 个问题</span></div>`;
    html+='<table><thead><tr><th>类型</th><th>模块</th><th>实例</th><th>文件</th><th>行</th><th>详情</th></tr></thead><tbody>';
    issues.forEach(i=>{
      const cls=i.type==='missing_port'?'missing':(i.type==='extra_port'?'extra':'mismatch');
      const detail=i.missing_ports?'缺失: '+i.missing_ports.join(', '):(i.extra_ports?'多余: '+i.extra_ports.join(', '):`${i.expected} → ${i.actual}`);
      html+=`<tr><td><span class="issue-badge ${cls}">${i.type}</span></td><td style="color:var(--accent)">${esc(i.module)}</td><td>${esc(i.instance)}</td><td style="font-size:11px">${esc((i.file||'').split(/[\\/]/).pop())}</td><td style="color:var(--accent3)">${i.line}</td><td>${esc(detail)}</td></tr>`;
    });
    html+='</tbody></table>';
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">检查失败</div>';}
}

// ---- Module dependency graph ----
async function loadModuleGraph(){
  const el=document.getElementById('tab-graph');
  el.innerHTML='<div class="loading">加载模块依赖图...</div>';
  try{
    const g=await api('/api/module-graph');
    if(!g.nodes||!g.nodes.length){el.innerHTML='<div class="empty">无模块数据</div>';return;}
    const instantiated=new Set(g.edges.map(e=>e.to));
    const W=900,H=600;
    const layers={};const inDeg={};
    g.nodes.forEach(n=>inDeg[n.id]=0);
    g.edges.forEach(e=>{if(inDeg[e.to]!==undefined)inDeg[e.to]++;});
    const topMods=g.nodes.filter(n=>inDeg[n.id]===0).map(n=>n.id);
    const queue=topMods.map(m=>({id:m,layer:0}));
    const visited=new Set();
    while(queue.length){
      const{id,layer}=queue.shift();
      if(visited.has(id))continue;
      visited.add(id);layers[id]=layer;
      g.edges.filter(e=>e.from===id).forEach(e=>{
        if(!visited.has(e.to))queue.push({id:e.to,layer:layer+1});
      });
    }
    g.nodes.forEach(n=>{if(layers[n.id]===undefined)layers[n.id]=0;});
    const maxLayer=Math.max(...Object.values(layers));
    const layerCounts={};
    Object.values(layers).forEach(l=>layerCounts[l]=(layerCounts[l]||0)+1);
    const positions={};const layerIdx={};
    g.nodes.forEach(n=>{
      const l=layers[n.id];
      const x=W*(0.15+0.7*(layerIdx[l]||0)/Math.max(1,layerCounts[l]-1));
      const y=60+l*(H-80)/Math.max(1,maxLayer);
      positions[n.id]={x,y};layerIdx[l]=(layerIdx[l]||0)+1;
    });
    let svg='<svg class="graph-svg" viewBox="0 0 '+W+' '+H+'"><defs><marker id="arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="var(--text-dim)"/></marker></defs>';
    g.edges.forEach(e=>{
      const from=positions[e.from],to=positions[e.to];
      if(from&&to){
        const mx=(from.x+to.x)/2;
        svg+='<path class="graph-edge" d="M'+(from.x+60)+','+(from.y+12)+' C'+mx+','+from.y+' '+mx+','+to.y+' '+(to.x-60)+','+(to.y-12)+'"/>';
      }
    });
    g.nodes.forEach(n=>{
      const p=positions[n.id];
      const isTop=!instantiated.has(n.id);
      svg+='<g class="graph-node'+(isTop?' top':'')+'" onclick="selectModule(''+n.id+'')" transform="translate('+(p.x-60)+','+(p.y-14)+')">';
      svg+='<rect width="120" height="28" />';
      svg+='<text x="60" y="18">'+n.id+'</text>';
      svg+='</g>';
    });
    svg+='</svg>';
    let html='<div class="card" style="margin-bottom:12px"><div class="section-title">模块依赖图 <span class="count">'+g.nodes.length+' 节点 / '+g.edges.length+' 边</span></div>';
    html+='<div style="font-size:12px;color:var(--text-dim)">点击节点查看模块详情</div></div>';
    html+=svg;
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">加载失败: '+e.message+'</div>';}
}

// ---- Code search ----
async function doCodeSearch(){
  const q=document.getElementById('codeSearchInput').value.trim();
  if(!q){alert('请输入搜索模式');return;}
  const el=document.getElementById('searchResult');
  el.innerHTML='<div class="loading">搜索中...</div>';
  try{
    const r=await api('/api/code-search?q='+encodeURIComponent(q));
    if(r.error){el.innerHTML='<div class="card"><span class="pill fail">错误</span> '+r.error+'</div>';return;}
    let html='<div class="card"><div class="section-title">搜索结果 <span class="count">'+r.match_count+(r.truncated?'+(截断)':'')+'</span></div>';
    html+='<div style="font-size:12px;color:var(--text-dim)">模式: <code style="color:var(--accent4)">'+q+'</code></div></div>';
    if(r.matches&&r.matches.length){
      html+=r.matches.map(function(m){
        var text=esc(m.text);
        try{var re=new RegExp('('+q+')','gi');text=text.replace(re,'<span class="match">$1</span>');}catch(e){}
        return '<div class="search-result"><span class="file">'+esc(m.file)+'</span>:<span class="line">'+m.line+'</span><span class="text">'+text+'</span></div>';
      }).join('');
    }else{html+='<div class="empty">无匹配</div>';}
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">搜索失败: '+e.message+'</div>';}
}

// ---- Batch lint ----
async function runBatchLint(){
  const el=document.getElementById('lintResult');
  el.innerHTML='<div class="loading">批量 Lint 运行中...（可能需要 30-60 秒）</div>';
  try{
    const r=await api('/api/lint-all');
    if(r.error){el.innerHTML='<div class="card"><span class="pill fail">错误</span> '+r.error+'</div>';return;}
    let html='<div class="card"><div class="section-title">批量 Lint 结果 <span class="count">'+r.file_count+' 文件</span></div>';
    html+='<div style="display:flex;gap:16px;margin:8px 0">';
    html+='<div class="stat-card" style="min-width:100px"><div class="num '+(r.total_violations?'red':'green')+'">'+r.total_violations+'</div><div class="lbl">总违规</div></div>';
    html+='<div class="stat-card" style="min-width:100px"><div class="num green">'+r.clean_files+'</div><div class="lbl">干净文件</div></div>';
    html+='<div class="stat-card" style="min-width:100px"><div class="num '+(r.dirty_files?'red':'green')+'">'+r.dirty_files+'</div><div class="lbl">有问题文件</div></div>';
    html+='</div></div>';
    if(r.files&&r.files.length){
      html+='<table><thead><tr><th>文件</th><th>违规数</th><th>状态</th></tr></thead><tbody>';
      r.files.forEach(function(f){
        html+='<tr style="cursor:pointer" onclick="document.getElementById('lintFile').value=''+f.path+'';runLint()"><td style="font-size:12px">'+esc(f.file)+'</td><td style="color:'+(f.violations?'var(--danger)':'var(--accent2)')+';font-weight:600">'+f.violations+'</td><td>'+(f.passed?'<span class="pill ok">通过</span>':'<span class="pill fail">有问题</span>')+'</td></tr>';
      });
      html+='</tbody></table>';
    }
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">批量 Lint 失败: '+e.message+'</div>';}
}

// ---- Real-time performance monitor ----
let monTimer=null, monInterval=2000, monPaused=false, monHistory=[];
async function monPoll(){
  if(monPaused)return;
  try{
    const d=await api('/api/performance');
    monRender(d);
  }catch(e){}
}
function monRender(d){
  // uptime
  document.getElementById('monUptime').textContent='运行时间: '+(d.uptime_display||'--');
  // v5.1.1: 数据源标识 —— 显示当前看板数据来自哪个进程
  const src=d.source||'this_process';
  const age=d.bridge_age_seconds;
  const srcTxt=src==='mcp_process'
    ? 'MCP 进程实时'+(age!=null?`（${age}s前更新）`:'')
    : '本进程实时';
  const srcEl=document.getElementById('monLiveStatus');
  if(srcEl) srcEl.textContent=srcTxt;
  // KPI grid
  const totalErrors=Object.values(d.operation_stats||{}).reduce((s,v)=>s+v.fail_count,0);
  const errorRate=d.total_operations>0?(totalErrors/d.total_operations*100).toFixed(1):'0.0';
  const avgMs=Object.values(d.operation_stats||{}).reduce((s,v)=>s+v.avg_ms*v.count,0);
  const totalCount=Object.values(d.operation_stats||{}).reduce((s,v)=>s+v.count,0)||1;
  const kpis=[
    {num:d.total_operations||0,lbl:'总操作数',cls:'blue',sub:'次'},
    {num:(d.ops_per_minute||0).toFixed(1),lbl:'吞吐量',cls:'green',sub:'ops/min'},
    {num:(avgMs/totalCount).toFixed(1),lbl:'平均耗时',cls:'yellow',sub:'ms'},
    {num:d.total_files_processed||0,lbl:'处理文件',cls:'blue',sub:'个'},
    {num:errorRate,lbl:'错误率',cls:parseFloat(errorRate)>5?'red':'green',sub:'%'},
    {num:(d.cache_hit_rate||0).toFixed(1),lbl:'缓存命中率',cls:'green',sub:'%'},
  ];
  document.getElementById('monKpiGrid').innerHTML=kpis.map(k=>
    `<div class="mon-card"><div class="num ${k.cls}">${k.num}</div><div class="lbl">${k.lbl}</div><div class="sub">${k.sub}</div></div>`
  ).join('');
  // Chart
  monDrawChart(d.recent_operations||[]);
  // Type stats
  monRenderTypeStats(d.operation_stats||{});
  // Resources
  monRenderResources(d);
  // Recent ops
  monRenderRecent(d.recent_operations||[]);
}
function monDrawChart(ops){
  const cv=document.getElementById('monChart');
  if(!cv)return;
  const ctx=cv.getContext('2d');
  const W=cv.width=cv.offsetWidth*2, H=cv.height=400;
  ctx.scale(2,2);
  const w=W/2,h=H/2;
  ctx.clearRect(0,0,w,h);
  // grid
  ctx.strokeStyle='#30363d'; ctx.lineWidth=0.5;
  for(let i=0;i<=5;i++){const y=10+i*(h-20)/5;ctx.beginPath();ctx.moveTo(30,y);ctx.lineTo(w-10,y);ctx.stroke();}
  // labels
  ctx.fillStyle='#8b949e'; ctx.font='10px monospace';
  if(!ops.length){ctx.fillStyle='#8b949e';ctx.font='14px sans-serif';ctx.textAlign='center';ctx.fillText('暂无操作数据',w/2,h/2);return;}
  const maxMs=Math.max(...ops.map(o=>o.duration_ms),1);
  const data=ops.slice(-50);
  // draw line
  const stepX=(w-40)/Math.max(data.length-1,1);
  ctx.strokeStyle='#58a6ff'; ctx.lineWidth=1.5;
  ctx.beginPath();
  data.forEach((o,i)=>{
    const x=30+i*stepX;
    const y=h-10-(o.duration_ms/maxMs)*(h-20);
    if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.stroke();
  // fill area
  ctx.lineTo(30+(data.length-1)*stepX,h-10);
  ctx.lineTo(30,h-10);
  ctx.closePath();
  ctx.fillStyle='rgba(88,166,255,0.1)';
  ctx.fill();
  // dots
  data.forEach((o,i)=>{
    const x=30+i*stepX;
    const y=h-10-(o.duration_ms/maxMs)*(h-20);
    ctx.fillStyle=o.success?'#3fb950':'#f85149';
    ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();
  });
  // y-axis labels
  ctx.fillStyle='#8b949e'; ctx.font='9px monospace'; ctx.textAlign='right';
  for(let i=0;i<=5;i++){const y=10+i*(h-20)/5;const val=maxMs*(1-i/5);ctx.fillText(val.toFixed(0)+'ms',28,y+3);}
  // x-axis info
  ctx.textAlign='left'; ctx.fillText('最近 '+data.length+' 次操作',30,h-2);
}
function monRenderTypeStats(stats){
  const entries=Object.entries(stats).sort((a,b)=>b[1].count-a[1].count);
  if(!entries.length){document.getElementById('monTypeStats').innerHTML='<div class="empty">暂无数据</div>';return;}
  const maxCount=Math.max(...entries.map(e=>e[1].count));
  let html='<table class="mon-table"><thead><tr><th>操作</th><th>次数</th><th>成功</th><th>失败</th><th>平均(ms)</th><th>最小</th><th>最大</th><th>错误率</th></tr></thead><tbody>';
  entries.forEach(([name,s])=>{
    const errColor=s.error_rate>10?'red':s.error_rate>0?'yellow':'green';
    html+=`<tr><td style="color:var(--accent)">${esc(name)}</td><td>${s.count}</td><td class="mon-status-ok">${s.success_count}</td><td class="${s.fail_count?'mon-status-fail':''}">${s.fail_count}</td><td>${s.avg_ms}</td><td>${s.min_ms}</td><td>${s.max_ms}</td><td class="mon-status-${errColor==='green'?'ok':errColor==='red'?'fail':''}" style="color:var(--${errColor==='green'?'accent2':errColor==='red'?'danger':'accent3'})">${s.error_rate}%</td></tr>`;
  });
  html+='</tbody></table>';
  document.getElementById('monTypeStats').innerHTML=html;
}
function monRenderResources(d){
  const mem=d.memory_mb||0, peak=d.peak_memory_mb||0, cpu=d.cpu_percent||0;
  const hits=d.cache_hits||0, misses=d.cache_misses||0, total=hits+misses;
  let html='<div class="mon-card" style="margin-bottom:12px">';
  html+=`<div style="display:flex;justify-content:space-between;align-items:center"><span style="color:var(--text-dim);font-size:13px">内存占用</span><span style="font-family:var(--mono);font-weight:700;color:var(--accent)">${mem.toFixed(1)} MB</span></div>`;
  html+=`<div class="mon-mem-bar"><div class="mon-mem-fill" style="width:${Math.min(mem/512*100,100)}%"></div></div>`;
  html+=`<div class="sub" style="margin-top:4px">峰值: ${peak.toFixed(1)} MB</div></div>`;
  html+=`<div class="mon-card" style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;align-items:center"><span style="color:var(--text-dim);font-size:13px">CPU 占用</span><span style="font-family:var(--mono);font-weight:700;color:${cpu>50?'var(--danger)':'var(--accent2)'}">${cpu.toFixed(1)}%</span></div></div>`;
  html+=`<div class="mon-card"><div style="display:flex;justify-content:space-between;align-items:center"><span style="color:var(--text-dim);font-size:13px">缓存命中</span><span style="font-family:var(--mono);font-weight:700;color:var(--accent2)">${hits} / ${total}</span></div>`;
  html+=`<div class="mon-mem-bar"><div class="mon-mem-fill" style="width:${total>0?hits/total*100:0}%;background:var(--accent2)"></div></div>`;
  html+=`<div class="sub" style="margin-top:4px">命中: ${hits} · 未命中: ${misses} · 命中率: ${(d.cache_hit_rate||0).toFixed(1)}%</div></div>`;
  html+=`<div class="mon-card" style="margin-top:12px"><div style="color:var(--text-dim);font-size:13px;margin-bottom:6px">吞吐量</div>`;
  html+=`<div style="font-family:var(--mono);font-size:18px;font-weight:700;color:var(--accent3)">${(d.files_per_minute||0).toFixed(1)} <span style="font-size:12px;color:var(--text-dim)">files/min</span></div></div>`;
  document.getElementById('monResource').innerHTML=html;
}
function monRenderRecent(ops){
  if(!ops.length){document.getElementById('monRecentOps').innerHTML='<div class="empty">暂无操作记录</div>';return;}
  const recent=ops.slice(-30).reverse();
  let html='<table class="mon-table"><thead><tr><th>时间</th><th>操作</th><th>耗时(ms)</th><th>状态</th><th>详情</th></tr></thead><tbody>';
  recent.forEach(o=>{
    const t=new Date(o.timestamp*1000);
    const ts=String(t.getHours()).padStart(2,'0')+':'+String(t.getMinutes()).padStart(2,'0')+':'+String(t.getSeconds()).padStart(2,'0');
    const durColor=o.duration_ms>500?'var(--danger)':o.duration_ms>100?'var(--accent3)':'var(--accent2)';
    html+=`<tr><td style="color:var(--text-dim)">${ts}</td><td style="color:var(--accent)">${esc(o.op_type)}</td><td style="color:${durColor};font-weight:600">${o.duration_ms}</td><td class="${o.success?'mon-status-ok':'mon-status-fail'}">${o.success?'✓':'✗'}${o.error?' '+esc(o.error.slice(0,40)):''}</td><td style="color:var(--text-dim);font-size:11px">${esc((o.detail||'').slice(0,50))}</td></tr>`;
  });
  html+='</tbody></table>';
  document.getElementById('monRecentOps').innerHTML=html;
}
function monSetInterval(ms,btn){
  monInterval=ms;
  document.querySelectorAll('.mon-toggle').forEach(b=>{if(b.textContent!=='⏸ 暂停'&&b.textContent!=='▶ 继续')b.classList.remove('active');});
  btn.classList.add('active');
  if(monTimer)clearInterval(monTimer);
  if(!monPaused)monTimer=setInterval(monPoll,monInterval);
}
function monTogglePause(btn){
  monPaused=!monPaused;
  if(monPaused){
    if(monTimer)clearInterval(monTimer);monTimer=null;
    btn.textContent='▶ 继续';btn.classList.add('active');
    document.getElementById('monLiveStatus').textContent='已暂停';
  }else{
    monTimer=setInterval(monPoll,monInterval);
    btn.textContent='⏸ 暂停';btn.classList.remove('active');
    document.getElementById('monLiveStatus').textContent='实时采集中';
    monPoll();
  }
}
function monStart(){if(monTimer)clearInterval(monTimer);monTimer=setInterval(monPoll,monInterval);monPoll();}

// ---- Tabs ----
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if(name==='overview')loadOverview();
  if(name==='codegen'){
    const el=document.getElementById('tab-codegen');
    el.innerHTML='<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center"><select id="codegenModule" style="min-width:200px"></select><button class="btn btn-primary" onclick="genTestbench()">生成 Testbench</button><button class="btn btn-primary" onclick="genInstantiation()">生成实例化</button><button class="btn" onclick="genContext()">AI 上下文</button></div><div class="empty">选择模块后点击按钮生成代码</div>';
    loadCodegenModuleList();
  }
  if(name==='lint')loadFileList();
  if(name==='hierarchy')loadHierarchyModuleList();
  if(name==='portcheck')loadPortCheck();
  if(name==='graph')loadModuleGraph();
  if(name==='monitor')monStart();
  else{if(monTimer){clearInterval(monTimer);monTimer=null;}}
}

// ---- Index ----
function showIndexDialog(){const dir=prompt('输入要索引的目录路径：');if(dir)indexDir(dir);}
async function indexDir(dir){
  try{
    const res=await fetch('/api/index',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root:dir})});
    const data=await res.json();
    alert(`索引完成：${data.indexed_files||0} 个文件`);
    loadAll();
  }catch(e){alert('索引失败: '+e.message);}
}

// ---- Init ----
async function loadAll(){
  await loadStats();
  await loadSymbols('');
  loadFileList();
  loadOverview();
}
loadAll();
</script>
</body>
</html>
"""
