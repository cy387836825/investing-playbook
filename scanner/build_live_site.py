#!/usr/bin/env python3
"""生成 site/live.html —— 当日实时漏斗页(离线优先:快照内联进 HTML,file:// 直接可看)。

双模:① 离线(file:// 或无后端)—— 用内联的 SNAPSHOTS 渲染,「运行今日扫描」提示双击 run-scan.command;
     ② 有后端(serve.py 运行时)—— 优先走 /api/* 取最新数据,按钮实时触发 pipeline + 进度条。
每跑一次 live_funnel 都会重建本页,把新快照内联进来。CSS 取自 build_site.py(各持一份,保回测页零风险)。
"""
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent
OUT = BASE.parent / 'site'; OUT.mkdir(exist_ok=True)
SNAP_DIR = BASE / 'snapshots'

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC',sans-serif;line-height:1.5;padding:24px;max-width:1400px;margin:0 auto}
h1{font-size:24px;margin-bottom:4px}h2{font-size:17px;margin:28px 0 12px;color:#e6edf3}
.sub{color:#8b949e;font-size:13px;margin-bottom:20px}
.nav{margin-bottom:20px}.nav a{color:#58a6ff;text-decoration:none;margin-right:16px;font-size:14px}.nav a:hover{text-decoration:underline}
.stats{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 18px;min-width:120px}
.stat .v{font-size:22px;font-weight:600;color:#e6edf3}.stat .l{font-size:12px;color:#8b949e}
.ctrl{margin-bottom:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input,select,button{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:7px 10px;font-size:13px}
button.run{background:#238636;border-color:#2ea043;color:#fff;font-weight:600;cursor:pointer;padding:8px 16px}
button.run:hover{background:#2ea043}button.run:disabled{background:#30363d;border-color:#30363d;color:#8b949e;cursor:not-allowed}
.wrap{overflow-x:auto;border:1px solid #30363d;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
th{background:#161b22;text-align:right;padding:9px 12px;position:sticky;top:0;font-weight:600;border-bottom:1px solid #30363d}
th[data-key]{cursor:pointer;user-select:none}th[data-key]:hover{color:#58a6ff}.arw{color:#58a6ff}
th:first-child,td:first-child,th.l,td.l{text-align:left}
td{padding:8px 12px;border-bottom:1px solid #21262d;font-variant-numeric:tabular-nums}
tr:hover td{background:#161b22}
.pos{color:#3fb950}.neg{color:#f85149}.mut{color:#8b949e}
a.tk{color:inherit;text-decoration:none}a.tk:hover{color:#58a6ff;text-decoration:underline}
.tag{display:inline-block;background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb44;border-radius:4px;padding:1px 6px;font-size:11px;margin-right:3px}
.tag.sup{background:#a371f722;color:#a371f7;border-color:#a371f744}
.note{color:#8b949e;font-size:12px;margin-top:8px;font-style:italic}
.reason{color:#8b949e;font-size:12px;white-space:normal}
.captag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid;white-space:nowrap}
.cap-mega{background:#a371f722;color:#a371f7;border-color:#a371f755}.cap-large{background:#3fb95022;color:#3fb950;border-color:#3fb95055}
.cap-mid{background:#4a9eff22;color:#58a6ff;border-color:#4a9eff55}.cap-small{background:#d2992222;color:#e3b341;border-color:#d2992255}
.cap-micro{background:#db6d2822;color:#db6d28;border-color:#db6d2855}.cap-nano{background:#f8514922;color:#f85149;border-color:#f8514955}
.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.b-sig{background:#f8514922;color:#f85149;border:1px solid #f8514944}
.b-mcap{background:#db6d2822;color:#db6d28;border:1px solid #db6d2844}
.b-cur{background:#d2992222;color:#d29922;border:1px solid #d2992244}
.b-pass{background:#3fb95022;color:#3fb950;border:1px solid #3fb95044}
.b-sector{background:#39c5cf22;color:#39c5cf;border:1px solid #39c5cf44}
.funnel{display:flex;flex-direction:column;gap:6px;margin:20px 0;align-items:center}
.flayer{border-radius:8px;padding:14px 20px;text-align:center;color:#fff;transition:.2s;position:relative;cursor:pointer}
.flayer:hover{filter:brightness(1.13)}.flayer.sel{outline:2px solid #58a6ff;outline-offset:2px}
.flayer .fn{font-size:15px;font-weight:600}.flayer .fc{font-size:26px;font-weight:700}.flayer .fnote{font-size:11px;opacity:.85}
.flayer .fclick{font-size:10px;opacity:.7;margin-top:2px}
.critbox{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 18px;margin-bottom:12px}
.crittitle{font-weight:600;color:#e6edf3;margin-bottom:8px;font-size:15px}
.critbox ul{margin:0 0 0 18px}.critbox li{margin:4px 0;font-size:13px;color:#c9d1d9}
.critnote{color:#8b949e;font-size:12px;margin-top:8px;font-style:italic}
.progwrap{flex-basis:100%;height:10px;background:#161b22;border:1px solid #30363d;border-radius:6px;overflow:hidden;display:none}
.progbar{height:100%;width:0;background:#2ea043;transition:width .3s}
.progtxt{font-size:12px;color:#8b949e}
.frozen{background:#1f6feb18;border:1px solid #1f6feb44;color:#58a6ff;border-radius:6px;padding:2px 8px;font-size:11px}
"""

HTML = """<div class=nav><a href=index.html>← 回测漏斗</a><a href=winners.html>回测大牛股</a><a href=live.html>当日实时</a></div>
<h1>当日实时漏斗 · 用今天的数据跑同一套 6 层过滤</h1>
<div class=sub>universe → 行业板块排除 → 信号命中 → 当前市值≥$1B → curation → 通过=今日可操作 shortlist · 点「运行今日扫描」用当日数据跑管线并存快照 · 每份快照冻结当时全部条件</div>
<div class=ctrl>
<button class=run id=runBtn onclick=runScan()>▶ 运行今日扫描</button>
<label class=mut title="勾选=先拉当日 Finviz universe(较慢,1-2分钟);取消=用现有 universe.csv 直接扫(快)"><input type=checkbox id=refreshChk checked> 刷新universe(Finviz)</label>
<label class=mut>历史快照 <select id=dateSel onchange=loadDate()></select></label>
<span id=frozen class=frozen style=display:none></span>
<span class=progtxt id=progtxt></span>
<div class=progwrap id=progwrap><div class=progbar id=progbar></div></div>
</div>
<div class=stats id=stats></div>
<div class=funnel id=funnel></div>
<div id=layerPanel style="display:none;margin:8px 0 24px">
<div id=layerCrit class=critbox></div>
<div class=ctrl><span id=layerCount class=mut></span></div>
<div class=ctrl>
<input id=fQ placeholder="搜索代码/名称..." oninput=renderRows()>
<select id=fSec onchange=onSecChange()></select>
<select id=fInd onchange=renderRows()></select>
</div>
<div class=wrap><table id=lt><thead><tr>
<th class=l data-key=ticker onclick="sortBy('ticker')">股票</th>
<th class=l data-key=sec onclick="sortBy('sec')">板块 / 细分行业</th>
<th class=l data-key=signals onclick="sortBy('signals')">信号</th>
<th data-key=mcap_b onclick="sortBy('mcap_b')">当前市值/分层</th>
<th data-key=ps onclick="sortBy('ps')">PS</th>
<th data-key=rev_yoy onclick="sortBy('rev_yoy')">营收YoY</th>
<th class=l data-key=exit_layer onclick="sortBy('exit_layer')">退出层</th>
<th class=l>原因/说明</th>
</tr></thead><tbody id=ltb></tbody></table></div>
<div class=note>当日漏斗无「未来」,不标牛股/暴雷股;每层展示今日命中股沿漏斗的去向。「信号命中」层=今日全部命中股;「通过」层=可操作 shortlist。</div>
</div>
<div class=note id=emptynote style=display:none>还没有任何快照。双击项目里的 <b>run-scan.command</b>(或在 scanner 目录运行 <code>python live_funnel.py</code>)用今天的数据生成第一份。</div>
"""

JS = r"""
const LC={market:'#30363d',universe:'#1f6feb',sector:'#39c5cf',signal:'#8957e5',mcap:'#db6d28',curation:'#238636'};
const WIDTHS={market:100,universe:92,sector:76,signal:60,mcap:46,curation:36};
const BADGE={sector:'<span class="badge b-sector">行业板块排除</span>',mcap:'<span class="badge b-mcap">市值门槛剔除</span>',curation:'<span class="badge b-cur">curation剔除</span>',passed:'<span class="badge b-pass">通过全部层</span>'};
let SNAP=null;
const tkl=t=>`<a class=tk href="https://finance.yahoo.com/quote/${encodeURIComponent(t)}" target=_blank rel=noopener><b>${t}</b></a>`;
const capBadge=c=>c?`<span class="captag cap-${c}">${({mega:'巨盘',large:'大盘',mid:'中盘',small:'小盘',micro:'微盘',nano:'纳盘'})[c]}</span>`:'';
const sigTags=s=>(s||'').split('+').map(p=>`<span class="tag${p==='S1超'?' sup':''}">${p}</span>`).join('');
function fmtPct(v){if(v==null)return '<span class=mut>-</span>';const c=v>0?'pos':(v<0?'neg':'mut');return `<span class=${c}>${v>0?'+':''}${v}%</span>`;}

async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(await r.text());return r.json();}

let SERVER=false;   // 是否检测到后端(serve.py 运行中)
async function boot(){
  // 优先探测后端:有则用 /api/*(最新);否则用内联 SNAPSHOTS(离线,file:// 直接可看)
  let dates;
  try{const idx=await j('/api/snapshots');SERVER=true;dates=idx.dates||[];}
  catch(e){SERVER=false;dates=SNAP_DATES;}
  updateRunBtn();
  const sel=document.getElementById('dateSel');
  if(!dates||!dates.length){document.getElementById('emptynote').style.display='';return;}
  sel.innerHTML=dates.slice().reverse().map(d=>`<option value=${d}>${d}</option>`).join('');
  await loadDate();
}
async function loadDate(){
  const d=document.getElementById('dateSel').value;if(!d)return;
  SNAP = SERVER ? await j('/api/snapshot/'+d) : SNAPSHOTS[d];
  if(!SNAP){document.getElementById('emptynote').style.display='';return;}
  render();
}
function updateRunBtn(){
  const b=document.getElementById('runBtn'),chk=document.getElementById('refreshChk');
  if(SERVER){b.textContent='▶ 运行今日扫描';b.title='';if(chk)chk.parentElement.style.display='';}
  else{b.textContent='▶ 运行今日扫描(需双击 run-scan.command)';b.title='离线模式:浏览器不能直接跑 Python 扫描';if(chk)chk.parentElement.style.display='none';}
}
function render(){
  document.getElementById('emptynote').style.display='none';
  const fz=document.getElementById('frozen');fz.style.display='';
  fz.textContent='条件冻结于 '+SNAP.asof+'(FLOOR $'+SNAP.floor_b.toFixed(0)+'B)';
  const s=SNAP;
  document.getElementById('stats').innerHTML=[
    ['universe·当日',s.universe_n,'#e6edf3',null],['行业排除后',s.layers.find(l=>l.code==='sector').n,'#39c5cf','sector'],
    ['今日命中',s.hit_n,'#8957e5','signal'],['市值≥$'+s.floor_b.toFixed(0)+'B',s.layers.find(l=>l.code==='mcap').n,'#db6d28','mcap'],
    ['通过=shortlist',s.shortlist_n,'#3fb950','passed']
  ].map(([l,v,c,code])=>`<div class=stat ${code?`onclick="selLayer('${code}')" style=cursor:pointer`:''}><div class=v style=color:${c}>${v}</div><div class=l>${l}${code?' ▸':''}</div></div>`).join('');
  document.getElementById('funnel').innerHTML=s.layers.map(L=>{
    const clickable=L.criteria?'<div class=fclick>▸ 点击看标准/命中股</div>':'';
    return `<div class=flayer data-code=${L.code} onclick="selLayer('${L.code}')" style="width:${WIDTHS[L.code]}%;background:${LC[L.code]}"><div class=fn>${L.name}</div><div class=fc>${L.n}</div><div class=fnote>${L.note||''}</div>${clickable}</div>`;
  }).join('');
  document.getElementById('layerPanel').style.display='none';
}
function critHtml(c){if(!c)return '<div class=critnote>该层为数据覆盖层,无逐票标准</div>';
  let h=`<div class=crittitle>${c.title}</div><ul>`;for(const r of c.rules)h+=`<li>${r}</li>`;h+='</ul>';
  if(c.note)h+=`<div class=critnote>${c.note}</div>`;return h;}
const LABEL={
  sector:(c,h)=>`被【行业板块排除】的全部公司:${c}(按当前市值排名;其中今日也命中信号的 ${h} 只)`,
  signal:c=>`今日命中信号的股票:${c}(下表按最终退出层标注去向)`,
  mcap:c=>`被【市值门槛】剔除的今日命中股:${c}(当前市值<$1B)`,
  curation:c=>`被【curation】剔除的今日命中股:${c}(质量门未过)`,
  passed:c=>`✅ 通过全部层 · 今日可操作 shortlist:${c}`,
};
let CUR_ROWS=[], BASE_LABEL='', sortKey='mcap_b', sortAsc=false;
const NUMKEYS=['mcap_b','ps','rev_yoy'];
function rowHtml(r){
  const mc=r.mcap_b!=null?('$'+r.mcap_b+'B '+capBadge(r.cap_tier)):'<span class=mut>-</span>';
  return `<tr><td class=l>${tkl(r.ticker)} <span class=mut style=font-size:11px>${(r.name||'').slice(0,20)}</span></td>
<td class=l>${r.sector||'<span class=mut>-</span>'}<br><span class=mut style=font-size:11px>${r.industry||''}</span></td><td class=l>${sigTags(r.signals)}</td><td>${mc}</td>
<td>${r.ps!=null?r.ps:'<span class=mut>-</span>'}</td><td>${fmtPct(r.rev_yoy)}</td>
<td class=l>${BADGE[r.exit_layer]||r.exit_layer}</td><td class="l reason">${r.why||''}</td></tr>`;
}
function fillFilters(rows){
  const secs=[...new Set(rows.map(r=>r.sector).filter(Boolean))].sort();
  const inds=[...new Set(rows.map(r=>r.industry).filter(Boolean))].sort();
  document.getElementById('fSec').innerHTML='<option value="">全部板块</option>'+secs.map(s=>`<option>${s}</option>`).join('');
  document.getElementById('fInd').innerHTML='<option value="">全部细分行业</option>'+inds.map(s=>`<option>${s}</option>`).join('');
  document.getElementById('fQ').value='';
}
function onSecChange(){
  const fs=document.getElementById('fSec').value;
  const inds=[...new Set(CUR_ROWS.filter(r=>!fs||r.sector===fs).map(r=>r.industry).filter(Boolean))].sort();
  document.getElementById('fInd').innerHTML='<option value="">全部细分行业</option>'+inds.map(s=>`<option>${s}</option>`).join('');
  renderRows();
}
function sortBy(key){
  if(sortKey===key) sortAsc=!sortAsc;
  else{sortKey=key; sortAsc=!NUMKEYS.includes(key);}   // 数值列默认降序,文本列默认升序
  renderRows();
}
function renderRows(){
  const q=(document.getElementById('fQ').value||'').toUpperCase();
  const fs=document.getElementById('fSec').value, fi=document.getElementById('fInd').value;
  let rows=CUR_ROWS.filter(r=>{
    if(q && !((r.ticker+' '+(r.name||'')).toUpperCase().includes(q))) return false;
    if(fs && (r.sector||'')!==fs) return false;
    if(fi && (r.industry||'')!==fi) return false;
    return true;
  });
  const num=NUMKEYS.includes(sortKey);
  rows.sort((a,b)=>{
    let x,y;
    if(sortKey==='sec'){x=(a.sector||'')+'|'+(a.industry||'');y=(b.sector||'')+'|'+(b.industry||'');}
    else{x=a[sortKey];y=b[sortKey];}
    if(num){x=(x==null||x!==x)?-1e15:x;y=(y==null||y!==y)?-1e15:y;return sortAsc?x-y:y-x;}
    return sortAsc?String(x||'').localeCompare(String(y||'')):String(y||'').localeCompare(String(x||''));
  });
  // 表头排序箭头
  document.querySelectorAll('#lt thead th[data-key]').forEach(th=>{
    const old=th.querySelector('.arw'); if(old) old.remove();
    if(th.dataset.key===sortKey){const s=document.createElement('span');s.className='arw';s.textContent=sortAsc?' ▲':' ▼';th.appendChild(s);}
  });
  document.getElementById('layerCount').innerHTML=BASE_LABEL+(rows.length!==CUR_ROWS.length?` <span class=mut>(筛后 ${rows.length}/${CUR_ROWS.length})</span>`:'');
  document.getElementById('ltb').innerHTML = rows.length? rows.map(rowHtml).join('') : '<tr><td colspan=8 class=mut>无匹配</td></tr>';
}
function selLayer(code){
  document.querySelectorAll('.flayer').forEach(e=>e.classList.toggle('sel',e.dataset.code===code));
  // 行业层=全部被排除公司(不限命中);信号层=今日全部命中股;passed=最终shortlist;其余层=退出层==code
  let rows, crit, label;
  if(code==='sector'){
    rows=(SNAP.sector_excluded||SNAP.hitrows.filter(r=>r.exit_layer==='sector')).slice();
    crit=SNAP.layers.find(l=>l.code==='sector').criteria;
    label=LABEL.sector(rows.length, rows.filter(r=>r.hit).length);
  } else if(code==='signal'){rows=SNAP.hitrows.filter(r=>r.exit_layer!=='sector'); crit=SNAP.layers.find(l=>l.code==='signal').criteria; label=LABEL.signal(rows.length);}
  else if(code==='passed'){rows=SNAP.hitrows.filter(r=>r.exit_layer==='passed'); crit=SNAP.layers.find(l=>l.code==='curation').criteria; label=LABEL.passed(rows.length);}
  else{rows=SNAP.hitrows.filter(r=>r.exit_layer===code); const L=SNAP.layers.find(l=>l.code===code); crit=L&&L.criteria; label=(LABEL[code]||(x=>x+''))(rows.length);}
  document.getElementById('layerCrit').innerHTML=critHtml(crit);
  CUR_ROWS=rows; BASE_LABEL=label; sortKey='mcap_b'; sortAsc=false;   // 每次进层重置为按市值降序
  fillFilters(rows);
  renderRows();
  document.getElementById('layerPanel').style.display='';
  document.getElementById('layerCrit').scrollIntoView({behavior:'smooth',block:'nearest'});
}

let POLL=null;
async function runScan(){
  if(!SERVER){
    alert('离线模式:浏览器无法直接运行扫描(不能跑 Python)。\n\n请双击项目根目录的 run-scan.command\n(或在 scanner 目录运行:python live_funnel.py)\n\n跑完会自动重建并打开刷新后的本页。');
    return;
  }
  const btn=document.getElementById('runBtn');btn.disabled=true;
  document.getElementById('progwrap').style.display='';
  document.getElementById('progtxt').textContent='启动…';
  const refresh=document.getElementById('refreshChk').checked;
  try{await j('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh})});}
  catch(e){document.getElementById('progtxt').textContent='已有任务在跑';}
  POLL=setInterval(poll,1000);
}
async function poll(){
  let st;try{st=await j('/api/progress');}catch(e){return;}
  const pct=st.total?Math.round(100*st.done/st.total):(st.running?3:0);
  document.getElementById('progbar').style.width=pct+'%';
  document.getElementById('progtxt').textContent=st.error?('出错: '+st.error):
    (st.running?`[${st.stage}] ${st.done}/${st.total} 命中${st.hits}`:'完成');
  if(!st.running){
    clearInterval(POLL);document.getElementById('runBtn').disabled=false;
    setTimeout(()=>document.getElementById('progwrap').style.display='none',1500);
    if(!st.error){await boot();}   // 重载快照列表并渲染最新
  }
}
boot();
"""


def _embed():
    """把 snapshots/*.json 内联成 JS,离线(file://)也能看历史快照。"""
    snaps, dates = {}, []
    if SNAP_DIR.exists():
        for p in sorted(SNAP_DIR.glob('*.json')):
            if p.stem == 'index':
                continue
            try:
                snaps[p.stem] = json.loads(p.read_text())
                dates.append(p.stem)
            except Exception:
                pass
    dates.sort()
    return (f"const SNAPSHOTS={json.dumps(snaps, ensure_ascii=False)};"
            f"const SNAP_DATES={json.dumps(dates, ensure_ascii=False)};\n")


def main():
    embed = _embed()
    page = (f"<!doctype html><html lang=zh><head><meta charset=utf-8>"
            f"<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>当日实时漏斗 · shortlist</title><style>{CSS}</style></head><body>"
            f"{HTML}<script>{embed}{JS}</script></body></html>")
    (OUT / 'live.html').write_text(page)
    n = embed.count('"asof"')
    print(f"→ {OUT / 'live.html'}(内联 {n} 份快照,file:// 可直接看)")


if __name__ == '__main__':
    main()
