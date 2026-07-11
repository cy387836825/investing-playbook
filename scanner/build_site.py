#!/usr/bin/env python3
"""把 winners.json / funnel.json 内联进两个自包含HTML页面"""
import json, pathlib
OUT = pathlib.Path('../site'); OUT.mkdir(exist_ok=True)
winners = json.load(open('winners.json'))
funnel = json.load(open('funnel.json'))

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
input,select{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:7px 10px;font-size:13px}
.wrap{overflow-x:auto;border:1px solid #30363d;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
th{background:#161b22;text-align:right;padding:9px 12px;position:sticky;top:0;cursor:pointer;user-select:none;font-weight:600;border-bottom:1px solid #30363d}
th:first-child,td:first-child,th.l,td.l{text-align:left}
th:hover{color:#58a6ff}
td{padding:8px 12px;border-bottom:1px solid #21262d;font-variant-numeric:tabular-nums}
tr:hover td{background:#161b22}
.pos{color:#3fb950}.neg{color:#f85149}.mut{color:#8b949e}
a.tk{color:inherit;text-decoration:none}a.tk:hover{color:#58a6ff;text-decoration:underline}
.tag{display:inline-block;background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb44;border-radius:4px;padding:1px 6px;font-size:11px;margin-right:3px}
.tag.sup{background:#a371f722;color:#a371f7;border-color:#a371f744}
.note{color:#8b949e;font-size:12px;margin-top:8px;font-style:italic}
.dtag{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600;margin-right:5px}
.d-fund{background:#3fb95022;color:#3fb950;border:1px solid #3fb95055}
.d-part{background:#4a9eff22;color:#58a6ff;border:1px solid #4a9eff55}
.d-weak{background:#d2992222;color:#e3b341;border:1px solid #d2992255}
.d-none{background:#8b949e22;color:#8b949e;border:1px solid #8b949e55}
.ctag{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600;white-space:nowrap}
.c-win{background:#3fb95022;color:#3fb950;border:1px solid #3fb95055}
.c-pass{background:#4a9eff22;color:#58a6ff;border:1px solid #4a9eff55}
.c-miss{background:#d2992222;color:#e3b341;border:1px solid #d2992255}
/* funnel */
.funnel{display:flex;flex-direction:column;gap:6px;margin:20px 0;align-items:center}
.flayer{border-radius:8px;padding:14px 20px;text-align:center;color:#fff;transition:.2s;position:relative}
.flayer .fn{font-size:15px;font-weight:600}.flayer .fc{font-size:26px;font-weight:700}.flayer .fnote{font-size:11px;opacity:.85}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px;background:#21262d;border:1px solid #30363d}
.reason{color:#8b949e;font-size:12px;white-space:normal}
.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.b-sig{background:#f8514922;color:#f85149;border:1px solid #f8514944}
.b-mcap{background:#db6d2822;color:#db6d28;border:1px solid #db6d2844}
.b-cur{background:#d2992222;color:#d29922;border:1px solid #d2992244}
.b-pass{background:#3fb95022;color:#3fb950;border:1px solid #3fb95044}
"""

JS_TABLE = """
function fmtPct(v){if(v==null)return '<span class=mut>-</span>';const c=v>0?'pos':(v<0?'neg':'mut');const s=v>0?'+':'';return `<span class=${c}>${s}${v}%</span>`;}
function sortTable(tbl,col,num,asc){const rows=[...tbl.tBodies[0].rows];rows.sort((a,b)=>{let x=a.cells[col].dataset.v??a.cells[col].innerText,y=b.cells[col].dataset.v??b.cells[col].innerText;if(num){x=parseFloat(x)||-1e15;y=parseFloat(y)||-1e15;return asc?x-y:y-x;}return asc?String(x).localeCompare(y):String(y).localeCompare(x);});rows.forEach(r=>tbl.tBodies[0].appendChild(r));}
"""

def tk_link(t):
    """ticker→Google Finance报价页(?q=会自动重定向到带交易所的URL)"""
    return f'<a class=tk href="https://www.google.com/finance?q={t}" target=_blank rel=noopener><b>{t}</b></a>'

def sig_tags(s):
    out=''
    for p in s.replace('+',' ').split():
        cls='tag sup' if p=='S1超' else 'tag'
        out+=f'<span class="{cls}">{p}</span>'
    return out

# ============ PAGE 1: winners.html ============
DRIVER_CLS={'fund':'d-fund','partial':'d-part','weak':'d-weak','none':'d-none'}
def driver_tag(w):
    cls=DRIVER_CLS.get(w.get('driver_tier'),'d-weak')
    g=w.get('rev_growth_pct')
    gtxt=f' 营收{"+"if(g and g>0)else""}{g}%' if g is not None else ' 无营收'
    return f'<span class="dtag {cls}">{w.get("driver","")}</span><span class=mut style=font-size:11px>{gtxt}</span>'

def hit_mark(w):
    """信号日期下标注:触发时市值 + 第几次命中"""
    out=''
    if w.get('mcap_pit_b') is not None:
        out+=f'<br><span class=mut style=font-size:11px>触发时市值 ${w["mcap_pit_b"]}B</span>'
    if w.get('hit_total', 1) > 1:
        out+=f'<br><span class=mut style=font-size:11px>第{w.get("hit_n","?")}/{w["hit_total"]}次命中</span>'
    return out

CAT_CLS={'大牛·过三层':'c-win','过三层·非大牛':'c-pass','大牛·被curation挡':'c-miss'}
def cat_tag(w):
    c=w.get('cat','')
    return f'<span class="ctag {CAT_CLS.get(c,"c-pass")}">{c}</span>'

def winners_rows():
    r=''
    for w in winners:
        r+=f"""<tr data-tier="{w.get('driver_tier','')}" data-cat="{w.get('cat','')}">
<td class=l data-v="{w['ticker']}">{tk_link(w['ticker'])}<br><span class=mut style=font-size:11px>{(w['name'] or '')[:22]}</span></td>
<td class=l data-v="{w.get('cat','')}">{cat_tag(w)}</td>
<td class=l data-v="{w.get('driver_tier','')}">{driver_tag(w)}</td>
<td class=l data-v="{w['sector'] or ''}">{w['sector'] or ''}</td>
<td data-v="{w['low'] or 0}">${w['low']}<br><span class=mut style=font-size:11px>{w['low_date'] or ''}</span></td>
<td data-v="{w['high'] or 0}">${w['high']}<br><span class=mut style=font-size:11px>{w['high_date'] or ''}</span></td>
<td data-v="{w['low2high_pct'] or 0}">{fmtPct_py(w['low2high_pct'])}</td>
<td class=l data-v="{w['signal_date']}">{w['signal_date']}{hit_mark(w)}</td>
<td class=l data-v="{w['signal_type']}">{sig_tags(w['signal_type'])}</td>
<td data-v="{w['entry']}">${w['entry']}</td>
<td data-v="{w['hold_pct']}">{fmtPct_py(w['hold_pct'])}</td>
<td data-v="{w['peak_pct']}">{fmtPct_py(w['peak_pct'])}</td>
<td data-v="{w['maxdd_pct']}">{fmtPct_py(w['maxdd_pct'])}</td>
<td data-v="{w['maxloss_pct']}">{fmtPct_py(w['maxloss_pct'])}</td>
</tr>"""
    return r

def fmtPct_py(v):
    if v is None: return '<span class=mut>-</span>'
    if isinstance(v, str): return f'<span class=pos>+{v}%</span>'   # 已截断的极端值
    c='pos' if v>0 else ('neg' if v<0 else 'mut'); s='+' if v>0 else ''
    return f'<span class={c}>{s}{v}%</span>'

secs=sorted({w['sector'] for w in winners if w['sector']})
sec_opts=''.join(f'<option>{s}</option>' for s in secs)
# 每票可有多次命中:统计卡按"股票"计,表格按"命中"逐行展示
def _utk(pred): return len({w['ticker'] for w in winners if pred(w)})
n_win_pass=_utk(lambda w: w['is_winner'] and w['curation_pass'])       # 大牛·过三层
n_pass_non=_utk(lambda w: (not w['is_winner']) and w['curation_pass']) # 过三层·非大牛
n_win_block=_utk(lambda w: w['is_winner'] and not w['curation_pass'])  # 大牛·被curation挡
n_win=_utk(lambda w: w['is_winner'])                                   # 大牛总数
n_passed_all=n_win_pass+n_pass_non                                     # 通过三层(所有推荐)
precision=round(100*n_win_pass/n_passed_all) if n_passed_all else 0
page1=f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>回测 · 三层候选与大牛股</title><style>{CSS}</style></head><body>
<div class=nav><a href=index.html>← 漏斗视图</a><a href=winners.html>候选与大牛股</a></div>
<h1>回测 · 通过三层的候选 + 大牛股</h1>
<div class=sub>含两类(用「类别」列区分、可筛选):① 大牛股(峰值>300%);② 通过全部三层的其他股票(信号命中+触发时市值≥$1B+curation过,但未成大牛)。前者看框架抓到什么,后者看框架推荐里没兑现的。⚠️point-in-time回测,非可复制策略</div>
<div class=stats>
<div class=stat><div class="v pos">{n_win_pass}</div><div class=l>大牛·过三层(框架抓到)</div></div>
<div class=stat><div class="v" style=color:#58a6ff>{n_pass_non}</div><div class=l>过三层·非大牛(推荐未兑现)</div></div>
<div class=stat><div class=v>{precision}%</div><div class=l>框架精度(过三层中成大牛比例)</div></div>
<div class=stat><div class="v" style=color:#e3b341>{n_win_block}</div><div class=l>大牛·被curation挡(漏掉的)</div></div>
<div class=stat><div class=v>{n_win}</div><div class=l>大牛股总数 · 共{len(winners)}次命中</div></div>
</div>
<div class=ctrl>
<input id=q placeholder="搜索代码/名称..." oninput=filt()>
<select id=fc onchange=filt()><option value="">全部类别</option><option value=大牛·过三层>大牛·过三层</option><option value=过三层·非大牛>过三层·非大牛</option><option value=大牛·被curation挡>大牛·被curation挡</option></select>
<select id=fd onchange=filt()><option value="">全部驱动</option><option value=fund>基本面·营收翻倍+</option><option value=partial>基本面·营收增长</option><option value=weak>弱基本面(商品/加密/生物/投机)</option><option value=none>无营收·投机叙事</option></select>
<select id=fs onchange=filt()><option value="">全部行业</option>{sec_opts}</select>
</div>
<div class=wrap><table id=t>
<thead><tr>
<th class=l onclick=srt(0,0)>股票</th><th class=l onclick=srt(1,0)>类别</th><th class=l onclick=srt(2,0)>驱动类型</th><th class=l onclick=srt(3,0)>行业</th>
<th onclick=srt(4,1)>低点/日期</th><th onclick=srt(5,1)>高点/日期</th><th onclick=srt(6,1)>低→高</th>
<th class=l onclick=srt(7,0)>信号日期</th><th class=l onclick=srt(8,0)>信号类型</th>
<th onclick=srt(9,1)>入场价</th><th onclick=srt(10,1)>持有至今</th>
<th onclick=srt(11,1)>峰值(潜在)</th><th onclick=srt(12,1)>最大回调</th><th onclick=srt(13,1)>最大浮亏</th>
</tr></thead><tbody>{winners_rows()}</tbody></table></div>
<div class=note>类别:大牛·过三层=框架推荐且峰值>300% · 过三层·非大牛=框架推荐但未成大牛 · 大牛·被curation挡=成了大牛但curation会剔除(框架漏掉) · 持有至今/峰值/回调/浮亏=从信号财报次日买入起算</div>
<script>{JS_TABLE}
let asc={{}};const t=document.getElementById('t');
function srt(c,n){{asc[c]=!asc[c];sortTable(t,c,n,asc[c]);}}
function filt(){{const q=document.getElementById('q').value.toUpperCase(),s=document.getElementById('fs').value,d=document.getElementById('fd').value,c=document.getElementById('fc').value;
for(const r of t.tBodies[0].rows){{const tx=r.cells[0].innerText.toUpperCase(),sec=r.cells[3].innerText,ti=r.dataset.tier,ca=r.dataset.cat;
r.style.display=(tx.includes(q)&&(!s||sec===s)&&(!d||ti===d)&&(!c||ca===c))?'':'none';}}}}
</script></body></html>"""
(OUT/'winners.html').write_text(page1)

# ============ PAGE 2: index.html (funnel) ============
LC=['#30363d','#1f6feb','#8957e5','#db6d28','#238636']
def flayer(L,w,c):
    n=L['n'];note=L.get('note','')
    return f'<div class=flayer style="width:{w}%;background:{c}"><div class=fn>{L["name"]}</div><div class=fc>{n}</div><div class=fnote>{note}</div></div>'
lys=funnel['layers']
widths=[100,90,62,46,36][:len(lys)]
fun_html=''.join(flayer(L,widths[i],LC[i]) for i,L in enumerate(lys))

def badge(layer):
    return {'signal':'<span class="badge b-sig">信号层漏掉</span>','mcap':'<span class="badge b-mcap">市值门槛剔除</span>','curation':'<span class="badge b-cur">curation剔除</span>','passed':'<span class="badge b-pass">通过全部三层</span>'}.get(layer,layer)

def cap(v):  # 极端值截断显示
    return '&gt;5000' if v and v>5000 else v

def win_rows():
    r=''
    # 过滤极端artifact(低→高>3000%多为仙股/拆股),按退出层重要性+涨幅排,全量展示(可筛选)
    order={'mcap':0,'curation':1,'passed':2,'signal':3}
    ws=[w for w in funnel['winners'] if (w['low2high_pct'] or 0)<=3000]
    ws.sort(key=lambda x:(order.get(x['exit_layer'],9), -(x['low2high_pct'] or 0)))
    for w in ws:
        r+=f"""<tr data-layer="{w['exit_layer']}">
<td class=l data-v="{w['ticker']}">{tk_link(w['ticker'])} <span class=mut style=font-size:11px>{(w['name']or'')[:18]}</span></td>
<td class=l>{w['sector'] or ''}</td>
<td data-v="{w['low2high_pct']}">{fmtPct_py(cap(w['low2high_pct']))}</td>
<td class=l>{sig_tags(w['signal_type']) if w['signal_type'] else '<span class=mut>未触发</span>'}</td>
<td class=l>{badge(w['exit_layer'])}</td>
<td class="l reason">{w['why']}</td></tr>"""
    return r

def blow_rows():
    r=''
    # 漏网(passed)优先显示(关键洞察),再mcap/curation/signal,全量展示(可筛选)
    order={'passed':0,'mcap':1,'curation':2,'signal':3}
    bs=sorted(funnel['blowups'], key=lambda x:(order.get(x['exit_layer'],9), x.get('blow_dd_pct',x['dd_peak_pct'])))
    for b in bs:
        dd=b.get('blow_dd_pct',b['dd_peak_pct'])
        r+=f"""<tr data-layer="{b['exit_layer']}">
<td class=l data-v="{b['ticker']}">{tk_link(b['ticker'])} <span class=mut style=font-size:11px>{(b['name']or'')[:18]}</span></td>
<td class=l>{b['sector'] or ''}</td>
<td data-v="{dd}">{fmtPct_py(dd)}</td>
<td class=l>{sig_tags(b['signal_type']) if b['signal_type'] else '<span class=mut>未触发</span>'}</td>
<td class=l>{badge(b['exit_layer'])}</td></tr>"""
    return r

from collections import Counter
wc=Counter(w['exit_layer'] for w in funnel['winners'])
bc=Counter(b['exit_layer'] for b in funnel['blowups'])
page2=f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>漏斗视图 · 大牛股与暴雷股</title><style>{CSS}</style></head><body>
<div class=nav><a href=index.html>漏斗视图</a><a href=winners.html>大牛股列表 →</a></div>
<h1>过滤漏斗 · 大牛股在哪层被过滤 / 暴雷股是否漏网</h1>
<div class=sub>全市场 → 信号命中 → 触发时市值≥${funnel.get('floor_b',1):.0f}B → curation通过 · 第一层市值门槛按信号触发当时(股数×入场价)计,非今天市值 · 追踪每只大牛股的退出层,每只暴雷股是否穿过过滤网</div>
<div class=funnel>{fun_html}</div>

<h2>大牛股(低→高>300%,共{len(funnel['winners'])}只)在哪一层被过滤</h2>
<div class=stats>
<div class=stat><div class="v neg">{wc['signal']}</div><div class=l>信号层漏掉(未触发)</div></div>
<div class=stat><div class="v" style=color:#db6d28>{wc['mcap']}</div><div class=l>触发时市值&lt;${funnel.get('floor_b',1):.0f}B剔除</div></div>
<div class=stat><div class="v" style=color:#d29922>{wc['curation']}</div><div class=l>curation剔除</div></div>
<div class=stat><div class="v pos">{wc['passed']}</div><div class=l>通过全部三层</div></div>
</div>
<div class=ctrl><input id=wq placeholder="搜索..." oninput=filtW()>
<select id=wl onchange=filtW()><option value="">全部退出层</option><option value=signal>信号层漏掉</option><option value=mcap>市值门槛剔除</option><option value=curation>curation剔除</option><option value=passed>通过全部三层</option></select></div>
<div class=wrap><table id=wt><thead><tr>
<th class=l onclick=srtW(0,0)>股票</th><th class=l>行业</th><th onclick=srtW(2,1)>低→高</th><th class=l>信号类型</th><th class=l>退出层</th><th class=l>原因</th>
</tr></thead><tbody>{win_rows()}</tbody></table></div>
<div class=note>信号层漏掉多为:信号滞后于股价(暴涨在财报确认前)/不达阈值/币-仙股-生物二元等非基本面驱动(框架本就不抓)。市值门槛剔除=触发当时市值不足${funnel.get('floor_b',1):.0f}B的大牛(多为最猛的微盘,如QBTS/DAVE入场时仅$0.1-0.3B)</div>

<h2>暴雷股(回撤>70%,共{len(funnel['blowups'])}只;已触发信号的按"首次入场后回撤"计,入场前的崩盘不算) — 有多少漏过了过滤网</h2>
<div class=stats>
<div class=stat><div class="v neg">{bc['passed']}</div><div class=l>⚠️漏网(通过全部三层)</div></div>
<div class=stat><div class="v" style=color:#8b949e>{bc['signal']}</div><div class=l>被信号层挡住(未触发)</div></div>
<div class=stat><div class="v" style=color:#db6d28>{bc['mcap']}</div><div class=l>被市值门槛挡住</div></div>
<div class=stat><div class="v" style=color:#d29922>{bc['curation']}</div><div class=l>被curation挡住</div></div>
</div>
<div class=ctrl><input id=bq placeholder="搜索..." oninput=filtB()>
<select id=bl onchange=filtB()><option value="">全部</option><option value=passed>⚠️漏网</option><option value=signal>信号层挡住</option><option value=mcap>市值门槛挡住</option><option value=curation>curation挡住</option></select></div>
<div class=wrap><table id=bt><thead><tr>
<th class=l onclick=srtB(0,0)>股票</th><th class=l>行业</th><th onclick=srtB(2,1)>暴雷回撤(入场后/全期)</th><th class=l>信号类型</th><th class=l>过滤结果</th>
</tr></thead><tbody>{blow_rows()}</tbody></table></div>
<div class=note>⚠️{bc['passed']}只暴雷股穿过全部三层=框架假阳性(如CVNA/OPEN/PTON疫情泡沫:峰值时营收加速触发S2b+通过curation,随后崩99%)。这是"营收加速信号无法区分真成长与泡沫"的直接证据</div>

<script>{JS_TABLE}
let a={{}};
function mk(tid,pfx){{const t=document.getElementById(tid);
window['srt'+pfx]=(c,n)=>{{a[tid+c]=!a[tid+c];sortTable(t,c,n,a[tid+c]);}};
window['filt'+pfx]=()=>{{const q=document.getElementById(pfx.toLowerCase()+'q').value.toUpperCase(),l=document.getElementById(pfx.toLowerCase()+'l').value;
for(const r of t.tBodies[0].rows){{const tx=r.cells[0].innerText.toUpperCase();r.style.display=(tx.includes(q)&&(!l||r.dataset.layer===l))?'':'none';}}}};}}
mk('wt','W');mk('bt','B');
</script></body></html>"""
(OUT/'index.html').write_text(page2)
print(f"→ ../site/index.html (漏斗) + ../site/winners.html (大牛股列表)")
print(f"  大牛股表{len(winners)}行, 漏斗大牛{len(funnel['winners'])}+暴雷{len(funnel['blowups'])}行")
