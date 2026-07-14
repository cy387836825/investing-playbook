#!/usr/bin/env python3
"""把 winners.json / funnel.json 内联进两个自包含HTML页面"""
import json, pathlib
OUT = pathlib.Path('../site'); OUT.mkdir(exist_ok=True)
winners = json.load(open('winners.json'))
funnel = json.load(open('funnel.json'))
try:
    IDX_ASOF = json.load(open('market_index_history/cache/sp500_history.json')).get('asof', '')
except Exception:
    IDX_ASOF = ''

# 市值分层展示(代码→中文短标签 / 下拉全标签)
CAP_SHORT = {'mega':'巨盘','large':'大盘','mid':'中盘','small':'小盘','micro':'微盘','nano':'纳盘'}
CAP_OPTS = [('mega','巨盘 ≥$200B'),('large','大盘 $10–200B'),('mid','中盘 $2–10B'),
            ('small','小盘 $0.3–2B'),('micro','微盘 $50–300M'),('nano','纳盘 <$50M')]
def cap_badge(tier):
    return f'<span class="captag cap-{tier}">{CAP_SHORT[tier]}</span>' if tier in CAP_SHORT else ''
def ix_badges(w):
    out = ''
    if w.get('in_sp500'): out += '<span class="ixtag ix-sp">S&amp;P 500</span>'
    if w.get('in_ndx'):   out += '<span class="ixtag ix-ndx">N100</span>'
    return out
def cap_cell(w):
    m = w.get('mcap_pit_b')
    mtxt = f'${m}B' if m is not None else '<span class=mut>-</span>'
    ix = ix_badges(w) or '<span class=mut style=font-size:11px>—</span>'
    return f'{mtxt} {cap_badge(w.get("cap_tier",""))}<br>{ix}'
def cap_sel(sid, onch):
    return (f'<select id={sid} onchange="{onch}"><option value="">全部市值</option>'
            + ''.join(f'<option value={c}>{lab}</option>' for c, lab in CAP_OPTS) + '</select>')
def ix_sel(sid, onch):
    return (f'<select id={sid} onchange="{onch}"><option value="">全部(指数无关)</option>'
            '<option value=sp>S&amp;P 500成分</option><option value=ndx>Nasdaq-100成分</option>'
            '<option value=any>任一指数成分</option><option value=none>非指数成分</option></select>')

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
.arw{color:#58a6ff}
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
/* 市值分层 + 指数 */
.captag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid;white-space:nowrap}
.cap-mega{background:#a371f722;color:#a371f7;border-color:#a371f755}
.cap-large{background:#3fb95022;color:#3fb950;border-color:#3fb95055}
.cap-mid{background:#4a9eff22;color:#58a6ff;border-color:#4a9eff55}
.cap-small{background:#d2992222;color:#e3b341;border-color:#d2992255}
.cap-micro{background:#db6d2822;color:#db6d28;border-color:#db6d2855}
.cap-nano{background:#f8514922;color:#f85149;border-color:#f8514955}
.ixtag{display:inline-block;padding:1px 5px;border-radius:4px;font-size:10px;font-weight:700;margin-left:3px;white-space:nowrap}
.ix-sp{background:#238636;color:#fff}
.ix-ndx{background:#1f6feb;color:#fff}
/* funnel */
.funnel{display:flex;flex-direction:column;gap:6px;margin:20px 0;align-items:center}
.flayer{border-radius:8px;padding:14px 20px;text-align:center;color:#fff;transition:.2s;position:relative;cursor:pointer}
.flayer:hover{filter:brightness(1.13)}
.flayer.sel{outline:2px solid #58a6ff;outline-offset:2px}
.flayer .fn{font-size:15px;font-weight:600}.flayer .fc{font-size:26px;font-weight:700}.flayer .fnote{font-size:11px;opacity:.85}
.flayer .fclick{font-size:10px;opacity:.7;margin-top:2px}
.critbox{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 18px;margin-bottom:12px}
.crittitle{font-weight:600;color:#e6edf3;margin-bottom:8px;font-size:15px}
.critbox ul{margin:0 0 0 18px}.critbox li{margin:4px 0;font-size:13px;color:#c9d1d9}
.critnote{color:#8b949e;font-size:12px;margin-top:8px;font-style:italic}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px;background:#21262d;border:1px solid #30363d}
.reason{color:#8b949e;font-size:12px;white-space:normal}
.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.b-sig{background:#f8514922;color:#f85149;border:1px solid #f8514944}
.b-mcap{background:#db6d2822;color:#db6d28;border:1px solid #db6d2844}
.b-cur{background:#d2992222;color:#d29922;border:1px solid #d2992244}
.b-pass{background:#3fb95022;color:#3fb950;border:1px solid #3fb95044}
.b-sector{background:#39c5cf22;color:#39c5cf;border:1px solid #39c5cf44}
"""

JS_TABLE = """
function fmtPct(v){if(v==null)return '<span class=mut>-</span>';const c=v>0?'pos':(v<0?'neg':'mut');const s=v>0?'+':'';return `<span class=${c}>${s}${v}%</span>`;}
function sortTable(tbl,col,num,asc){const rows=[...tbl.tBodies[0].rows];rows.sort((a,b)=>{let x=a.cells[col].dataset.v??a.cells[col].innerText,y=b.cells[col].dataset.v??b.cells[col].innerText;if(num){x=parseFloat(x)||-1e15;y=parseFloat(y)||-1e15;return asc?x-y:y-x;}return asc?String(x).localeCompare(y):String(y).localeCompare(x);});rows.forEach(r=>tbl.tBodies[0].appendChild(r));}
"""

def tk_link(t):
    """ticker→Yahoo Finance报价页(裸ticker即可解析;Google Finance的?q=已失效会跳首页)"""
    return f'<a class=tk href="https://finance.yahoo.com/quote/{t}" target=_blank rel=noopener><b>{t}</b></a>'

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
    """信号日期下标注:第几次命中(触发时市值已移到独立列)"""
    out=''
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
        r+=f"""<tr data-tier="{w.get('driver_tier','')}" data-cat="{w.get('cat','')}" data-cap="{w.get('cap_tier','')}" data-sp="{1 if w.get('in_sp500') else 0}" data-ndx="{1 if w.get('in_ndx') else 0}">
<td class=l data-v="{w['ticker']}">{tk_link(w['ticker'])}<br><span class=mut style=font-size:11px>{(w['name'] or '')[:22]}</span></td>
<td class=l data-v="{w.get('cat','')}">{cat_tag(w)}</td>
<td class=l data-v="{w.get('driver_tier','')}">{driver_tag(w)}</td>
<td class=l data-v="{w['sector'] or ''}">{w['sector'] or ''}<br><span class=mut style=font-size:11px>{w.get('industry') or ''}</span></td>
<td data-v="{w.get('mcap_pit_b') or 0}">{cap_cell(w)}</td>
<td data-v="{w['low'] or 0}">${w['low']}<br><span class=mut style=font-size:11px>{w['low_date'] or ''}</span></td>
<td data-v="{w['high'] or 0}">${w['high']}<br><span class=mut style=font-size:11px>{w['high_date'] or ''}</span></td>
<td data-v="{w['low2high_pct'] or 0}">{fmtPct_py(w['low2high_pct'])}</td>
<td class=l data-v="{w['signal_date']}">{w['signal_date']}{hit_mark(w)}</td>
<td class=l data-v="{w['signal_type']}">{sig_tags(w['signal_type'])}</td>
<td data-v="{w['entry']}">${w['entry']}</td>
<td data-v="{w['hold_pct']}">{fmtPct_py(w['hold_pct'])}</td>
<td data-v="{w.get('ann_hold_pct') if w.get('ann_hold_pct') is not None else -1e9}">{fmtPct_py(w.get('ann_hold_pct'))}</td>
<td data-v="{w['peak_pct']}">{fmtPct_py(w['peak_pct'])}</td>
<td data-v="{w.get('ann_peak_pct') if w.get('ann_peak_pct') is not None else -1e9}">{fmtPct_py(w.get('ann_peak_pct'))}</td>
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
# 各信号命中率(过三层候选中成大牛的比例,去重票,信号可组合故按token计)
_seen=set(); _passed=[]
for w in winners:
    if not w['curation_pass'] or w['ticker'] in _seen: continue
    _seen.add(w['ticker']); _passed.append(w)
SIG_DESC={'S1':'周期反转','S1超':'强周期反转','S2a':'首次盈利','S2b':'营收加速'}
def sig_hit_rows():
    out=''
    for s in ['S1','S1超','S2a','S2b']:
        g=[w for w in _passed if s in (w['signal_type'] or '').split('+')]
        if not g: continue
        n=len(g); win=sum(1 for w in g if w['is_winner']); hr=round(100*win/n)
        cls='tag sup' if s=='S1超' else 'tag'
        out+=f'<tr><td class=l><span class="{cls}">{s}</span> <span class=mut style=font-size:11px>{SIG_DESC.get(s,"")}</span></td><td>{n}</td><td>{win}</td><td><b>{hr}%</b></td></tr>'
    return out
page1=f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>回测 · 三层候选与大牛股</title><style>{CSS}</style></head><body>
<div class=nav><a href=index.html>← 漏斗视图</a><a href=winners.html>候选与大牛股</a><a href=live.html>当日实时 →</a></div>
<h1>回测 · 通过三层的候选 + 大牛股</h1>
<div class=sub>含两类(用「类别」列区分、可筛选):① 大牛股(峰值>300%);② 通过全部三层的其他股票(信号命中+触发时市值≥$1B+curation过,但未成大牛)。前者看框架抓到什么,后者看框架推荐里没兑现的。⚠️point-in-time回测,非可复制策略</div>
<div class=stats>
<div class=stat><div class="v pos">{n_win_pass}</div><div class=l>大牛·过三层(框架抓到)</div></div>
<div class=stat><div class="v" style=color:#58a6ff>{n_pass_non}</div><div class=l>过三层·非大牛(推荐未兑现)</div></div>
<div class=stat><div class=v>{precision}%</div><div class=l>框架精度(过三层中成大牛比例)</div></div>
<div class=stat><div class="v" style=color:#e3b341>{n_win_block}</div><div class=l>大牛·被curation挡(漏掉的)</div></div>
<div class=stat><div class=v>{n_win}</div><div class=l>大牛股总数 · 共{len(winners)}次命中</div></div>
</div>
<h2>各信号命中率(过三层候选中成大牛的比例)</h2>
<div class=wrap style=max-width:520px><table>
<thead><tr><th class=l>信号</th><th>过三层候选</th><th>成大牛</th><th>命中率</th></tr></thead>
<tbody>{sig_hit_rows()}</tbody></table></div>
<div class=note>信号可组合触发(如 S1超+S2b),按token分别计入 · S1超命中率最高但最稀有;S2b量最大但质最低</div>
<div class=ctrl>
<input id=q placeholder="搜索代码/名称..." oninput=filt()>
<select id=fc onchange=filt()><option value="">全部类别</option><option value=大牛·过三层>大牛·过三层</option><option value=过三层·非大牛>过三层·非大牛</option><option value=大牛·被curation挡>大牛·被curation挡</option></select>
{cap_sel('fcap','filt()')}
{ix_sel('fi','filt()')}
<select id=fd onchange=filt()><option value="">全部驱动</option><option value=fund>基本面·营收翻倍+</option><option value=partial>基本面·营收增长</option><option value=weak>弱基本面(商品/加密/生物/投机)</option><option value=none>无营收·投机叙事</option></select>
<select id=fs onchange=filt()><option value="">全部行业</option>{sec_opts}</select>
</div>
<div class=wrap><table id=t>
<thead><tr>
<th class=l onclick=srt(0,0)>股票</th><th class=l onclick=srt(1,0)>类别</th><th class=l onclick=srt(2,0)>驱动类型</th><th class=l onclick=srt(3,0)>板块 / 细分行业</th>
<th onclick=srt(4,1)>触发市值/分层</th>
<th onclick=srt(5,1)>低点/日期</th><th onclick=srt(6,1)>高点/日期</th><th onclick=srt(7,1)>低→高</th>
<th class=l onclick=srt(8,0)>信号日期</th><th class=l onclick=srt(9,0)>信号类型</th>
<th onclick=srt(10,1)>入场价</th><th onclick=srt(11,1)>持有至今</th><th onclick=srt(12,1)>持有年化</th>
<th onclick=srt(13,1)>峰值(潜在)</th><th onclick=srt(14,1)>峰值年化</th><th onclick=srt(15,1)>最大回调</th><th onclick=srt(16,1)>最大浮亏</th>
</tr></thead><tbody>{winners_rows()}</tbody></table></div>
<div class=note>类别:大牛·过三层=框架推荐且峰值>300% · 过三层·非大牛=框架推荐但未成大牛 · 大牛·被curation挡=成了大牛但curation会剔除(框架漏掉) · 持有至今/峰值/回调/浮亏=从信号财报次日买入起算 · 持有年化=入场到今日的复合年化;峰值年化=入场到峰值日的复合年化(到峰时间短则年化偏高,仅供横向比较)</div>
<div class=note>市值分层=传统定义,按<b>信号触发当时</b>的point-in-time市值(股数×入场价)分箱:巨盘≥$200B · 大盘$10–200B · 中盘$2–10B · 小盘$0.3–2B · 微盘$50–300M · 纳盘<$50M。⚠️第一层按<b>首次触发</b>市值≥$1B过滤,故首次入选时至少是小盘;但同一票<b>后续命中</b>若已崩成微盘/纳盘,会作为独立行出现(如TDUP $1.86B→$0.07B、BBBY)。触发时市值本就<$1B的那批大牛在<a href=index.html style=color:#58a6ff>漏斗页</a>的"市值门槛剔除"里。市值缺失(股数数据缺口)不分层。指数标注 <span class="ixtag ix-sp">S&amp;P 500</span>/<span class="ixtag ix-ndx">N100</span> 为<b>信号触发当日的point-in-time成分</b>(按维基变更日志回滚判定),故未标注者=触发时尚未进指数,不少是命中后才成长纳入的。日志数据截至{IDX_ASOF}。</div>
<script>{JS_TABLE}
let asc={{}};const t=document.getElementById('t');
function srt(c,n){{asc[c]=!asc[c];sortTable(t,c,n,asc[c]);}}
function filt(){{const q=document.getElementById('q').value.toUpperCase(),s=document.getElementById('fs').value,d=document.getElementById('fd').value,c=document.getElementById('fc').value,cp=document.getElementById('fcap').value,ix=document.getElementById('fi').value;
for(const r of t.tBodies[0].rows){{const tx=r.cells[0].innerText.toUpperCase(),sec=r.cells[3].innerText,ti=r.dataset.tier,ca=r.dataset.cat,cap=r.dataset.cap,sp=r.dataset.sp==='1',nd=r.dataset.ndx==='1';
let ixok=true;if(ix==='sp')ixok=sp;else if(ix==='ndx')ixok=nd;else if(ix==='any')ixok=sp||nd;else if(ix==='none')ixok=!sp&&!nd;
r.style.display=(tx.includes(q)&&(!s||sec===s)&&(!d||ti===d)&&(!c||ca===c)&&(!cp||cap===cp)&&ixok)?'':'none';}}}}
</script></body></html>"""
(OUT/'winners.html').write_text(page1)

# ============ PAGE 2: index.html (funnel) ============
# 层色:市场/universe/sector(青)/signal/mcap/curation
LC=['#30363d','#1f6feb','#39c5cf','#8957e5','#db6d28','#238636']
def flayer(L,w,c):
    n=L['n'];note=L.get('note','');code=L.get('code','')
    clickable=' <div class=fclick>▸ 点击看标准/被排股票</div>' if L.get('criteria') else ''
    return (f'<div class=flayer data-code="{code}" onclick="selLayer(\'{code}\')" '
            f'style="width:{w}%;background:{c}"><div class=fn>{L["name"]}</div>'
            f'<div class=fc>{n}</div><div class=fnote>{note}</div>{clickable}</div>')
lys=funnel['layers']
widths=[100,92,76,60,46,36][:len(lys)]
fun_html=''.join(flayer(L,widths[i],LC[i]) for i,L in enumerate(lys))

def badge(layer):
    return {'sector':'<span class="badge b-sector">行业板块排除</span>','signal':'<span class="badge b-sig">信号层漏掉</span>','mcap':'<span class="badge b-mcap">市值门槛剔除</span>','curation':'<span class="badge b-cur">curation剔除</span>','passed':'<span class="badge b-pass">通过全部三层</span>'}.get(layer,layer)

def cap(v):  # 极端值截断显示
    return '&gt;5000' if v and v>5000 else v

def win_rows():
    r=''
    # 过滤极端artifact(低→高>3000%多为仙股/拆股),按退出层重要性+涨幅排,全量展示(可筛选)
    order={'sector':0,'mcap':1,'curation':2,'passed':3,'signal':4}
    ws=[w for w in funnel['winners'] if (w['low2high_pct'] or 0)<=3000]
    ws.sort(key=lambda x:(order.get(x['exit_layer'],9), -(x['low2high_pct'] or 0)))
    for w in ws:
        r+=f"""<tr data-layer="{w['exit_layer']}" data-cap="{w.get('cap_tier','')}" data-sp="{1 if w.get('in_sp500') else 0}" data-ndx="{1 if w.get('in_ndx') else 0}">
<td class=l data-v="{w['ticker']}">{tk_link(w['ticker'])} <span class=mut style=font-size:11px>{(w['name']or'')[:18]}</span></td>
<td class=l>{w['sector'] or ''}<br><span class=mut style=font-size:11px>{w.get('industry') or ''}</span></td>
<td data-v="{w.get('mcap_pit_b') or 0}">{cap_cell(w)}</td>
<td data-v="{w['low2high_pct']}">{fmtPct_py(cap(w['low2high_pct']))}</td>
<td class=l>{sig_tags(w['signal_type']) if w['signal_type'] else '<span class=mut>未触发</span>'}</td>
<td class=l>{badge(w['exit_layer'])}</td>
<td class="l reason">{w['why']}</td></tr>"""
    return r

def blow_rows():
    r=''
    # 漏网(passed)优先显示(关键洞察),再sector/mcap/curation/signal,全量展示(可筛选)
    order={'passed':0,'sector':1,'mcap':2,'curation':3,'signal':4}
    bs=sorted(funnel['blowups'], key=lambda x:(order.get(x['exit_layer'],9), x.get('blow_dd_pct',x['dd_peak_pct'])))
    for b in bs:
        dd=b.get('blow_dd_pct',b['dd_peak_pct'])
        r+=f"""<tr data-layer="{b['exit_layer']}">
<td class=l data-v="{b['ticker']}">{tk_link(b['ticker'])} <span class=mut style=font-size:11px>{(b['name']or'')[:18]}</span></td>
<td class=l>{b['sector'] or ''}<br><span class=mut style=font-size:11px>{b.get('industry') or ''}</span></td>
<td data-v="{dd}">{fmtPct_py(dd)}</td>
<td class=l>{sig_tags(b['signal_type']) if b['signal_type'] else '<span class=mut>未触发</span>'}</td>
<td class=l>{badge(b['exit_layer'])}</td></tr>"""
    return r

from collections import Counter
wc=Counter(w['exit_layer'] for w in funnel['winners'])
bc=Counter(b['exit_layer'] for b in funnel['blowups'])

# 层详情(点击漏斗层展开):合并牛股+暴雷股,每行标注类别,客户端按选中层渲染
def _layerrows():
    rows=[]
    for w in funnel['winners']:
        rows.append({'tk':w['ticker'],'nm':(w['name'] or '')[:20],'sec':w['sector'] or '','ind':w.get('industry','') or '',
                     'layer':w['exit_layer'],'why':w['why'],'kind':'win','metric':w['low2high_pct'] or 0})
    for b in funnel['blowups']:
        rows.append({'tk':b['ticker'],'nm':(b['name'] or '')[:20],'sec':b['sector'] or '','ind':b.get('industry','') or '',
                     'layer':b['exit_layer'],'why':b['why'],'kind':'blow','metric':b.get('blow_dd_pct',b['dd_peak_pct'])})
    return rows
LAYERROWS=json.dumps(_layerrows(), ensure_ascii=False)
LAYERCRIT=json.dumps({L['code']:L['criteria'] for L in funnel['layers'] if L.get('criteria')}, ensure_ascii=False)
LAYERNAME=json.dumps({L['code']:L['name'] for L in funnel['layers']}, ensure_ascii=False)
page2=f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>漏斗视图 · 大牛股与暴雷股</title><style>{CSS}</style></head><body>
<div class=nav><a href=index.html>漏斗视图</a><a href=winners.html>大牛股列表 →</a><a href=live.html>当日实时 →</a></div>
<h1>过滤漏斗 · 大牛股在哪层被过滤 / 暴雷股是否漏网</h1>
<div class=sub>全市场 → <b>行业板块排除</b> → 信号命中 → 触发时市值≥${funnel.get('floor_b',1):.0f}B → curation通过 · 追踪每只大牛股在哪层退出、每只暴雷股是否穿过过滤网 · <b>点击下方漏斗任意一层</b>查看该层具体标准 + 被过滤的股票(牛股/暴雷股标注)</div>
<div class=funnel>{fun_html}</div>
<div id=layerPanel style="display:none;margin:8px 0 24px">
<div id=layerCrit class=critbox></div>
<div class=ctrl><span id=layerCount class=mut></span></div>
<div class=ctrl>
<input id=LfQ placeholder="搜索代码/名称..." oninput=LrenderRows()>
<select id=LfSec onchange=LonSecChange()></select>
<select id=LfInd onchange=LrenderRows()></select>
<select id=LfKind onchange=LrenderRows()><option value="">全部类别</option><option value=win>牛股</option><option value=blow>暴雷股</option></select>
</div>
<div class=wrap><table id=lt><thead><tr>
<th class=l data-key=tk onclick="LsortBy('tk')">股票</th><th class=l data-key=sec onclick="LsortBy('sec')">板块 / 细分行业</th><th class=l data-key=kind onclick="LsortBy('kind')">类别</th><th data-key=metric onclick="LsortBy('metric')">关键指标</th><th class=l data-key=why onclick="LsortBy('why')">被过滤原因</th>
</tr></thead><tbody id=ltb></tbody></table></div>
<div class=note>关键指标:牛股=低→高涨幅(被此层排除=框架为控风险付出的代价),暴雷股=峰值后最大回撤(被此层拦下=风控收益)。同一只票若既暴涨又暴跌会各出一行。</div>
</div>

<h2>大牛股(低→高>300%,共{len(funnel['winners'])}只)在哪一层被过滤</h2>
<div class=stats>
<div class=stat><div class="v" style=color:#39c5cf">{wc['sector']}</div><div class=l>行业板块排除(最上游)</div></div>
<div class=stat><div class="v neg">{wc['signal']}</div><div class=l>信号层漏掉(未触发)</div></div>
<div class=stat><div class="v" style=color:#db6d28>{wc['mcap']}</div><div class=l>触发时市值&lt;${funnel.get('floor_b',1):.0f}B剔除</div></div>
<div class=stat><div class="v" style=color:#d29922>{wc['curation']}</div><div class=l>curation剔除</div></div>
<div class=stat><div class="v pos">{wc['passed']}</div><div class=l>通过全部四层</div></div>
</div>
<div class=ctrl><input id=wq placeholder="搜索..." oninput=filtW()>
<select id=wl onchange=filtW()><option value="">全部退出层</option><option value=sector>行业板块排除</option><option value=signal>信号层漏掉</option><option value=mcap>市值门槛剔除</option><option value=curation>curation剔除</option><option value=passed>通过全部四层</option></select>
{cap_sel('wcap','filtW()')}
{ix_sel('wi','filtW()')}</div>
<div class=wrap><table id=wt><thead><tr>
<th class=l onclick=srtW(0,0)>股票</th><th class=l>板块 / 细分行业</th><th onclick=srtW(2,1)>触发市值/分层</th><th onclick=srtW(3,1)>低→高</th><th class=l>信号类型</th><th class=l>退出层</th><th class=l>原因</th>
</tr></thead><tbody>{win_rows()}</tbody></table></div>
<div class=note>信号层漏掉多为:信号滞后于股价(暴涨在财报确认前)/不达阈值/币-仙股-生物二元等非基本面驱动(框架本就不抓)。市值门槛剔除=触发当时市值不足${funnel.get('floor_b',1):.0f}B的大牛(多为最猛的微盘,如QBTS/DAVE入场时仅$0.1-0.3B)。市值分层按触发时PIT市值;指数标注为<b>触发当日point-in-time成分</b>(已触发按触发日回滚判定,未触发者按当前成分)</div>

<h2>暴雷股(回撤>70%,共{len(funnel['blowups'])}只;已触发信号的按"首次入场后回撤"计,入场前的崩盘不算) — 有多少漏过了过滤网</h2>
<div class=stats>
<div class=stat><div class="v neg">{bc['passed']}</div><div class=l>⚠️漏网(通过全部四层)</div></div>
<div class=stat><div class="v" style=color:#39c5cf">{bc['sector']}</div><div class=l>被行业板块排除挡住</div></div>
<div class=stat><div class="v" style=color:#8b949e>{bc['signal']}</div><div class=l>被信号层挡住(未触发)</div></div>
<div class=stat><div class="v" style=color:#db6d28>{bc['mcap']}</div><div class=l>被市值门槛挡住</div></div>
<div class=stat><div class="v" style=color:#d29922>{bc['curation']}</div><div class=l>被curation挡住</div></div>
</div>
<div class=ctrl><input id=bq placeholder="搜索..." oninput=filtB()>
<select id=bl onchange=filtB()><option value="">全部</option><option value=passed>⚠️漏网</option><option value=sector>行业板块排除挡住</option><option value=signal>信号层挡住</option><option value=mcap>市值门槛挡住</option><option value=curation>curation挡住</option></select></div>
<div class=wrap><table id=bt><thead><tr>
<th class=l onclick=srtB(0,0)>股票</th><th class=l>板块 / 细分行业</th><th onclick=srtB(2,1)>暴雷回撤(入场后/全期)</th><th class=l>信号类型</th><th class=l>过滤结果</th>
</tr></thead><tbody>{blow_rows()}</tbody></table></div>
<div class=note>⚠️{bc['passed']}只暴雷股穿过全部三层=框架假阳性(如CVNA/OPEN/PTON疫情泡沫:峰值时营收加速触发S2b+通过curation,随后崩99%)。这是"营收加速信号无法区分真成长与泡沫"的直接证据</div>

<script>{JS_TABLE}
let a={{}};
function mk(tid,pfx){{const t=document.getElementById(tid);
window['srt'+pfx]=(c,n)=>{{a[tid+c]=!a[tid+c];sortTable(t,c,n,a[tid+c]);}};
window['filt'+pfx]=()=>{{const q=document.getElementById(pfx.toLowerCase()+'q').value.toUpperCase(),l=document.getElementById(pfx.toLowerCase()+'l').value;
for(const r of t.tBodies[0].rows){{const tx=r.cells[0].innerText.toUpperCase();r.style.display=(tx.includes(q)&&(!l||r.dataset.layer===l))?'':'none';}}}};}}
mk('wt','W');mk('bt','B');
// 大牛表额外支持 市值分层 + 指数 筛选(覆盖mk生成的filtW)
(function(){{const t=document.getElementById('wt');
window.filtW=()=>{{const q=document.getElementById('wq').value.toUpperCase(),l=document.getElementById('wl').value,cp=document.getElementById('wcap').value,ix=document.getElementById('wi').value;
for(const r of t.tBodies[0].rows){{const tx=r.cells[0].innerText.toUpperCase(),cap=r.dataset.cap,sp=r.dataset.sp==='1',nd=r.dataset.ndx==='1';
let ixok=true;if(ix==='sp')ixok=sp;else if(ix==='ndx')ixok=nd;else if(ix==='any')ixok=sp||nd;else if(ix==='none')ixok=!sp&&!nd;
r.style.display=(tx.includes(q)&&(!l||r.dataset.layer===l)&&(!cp||cap===cp)&&ixok)?'':'none';}}}};}})();
// ==== 漏斗层点击 → 展开该层标准 + 被过滤股票(牛股/暴雷股标注)====
const LAYERROWS={LAYERROWS},LAYERCRIT={LAYERCRIT},LAYERNAME={LAYERNAME};
const tkl=function(t){{return '<a class=tk href="https://finance.yahoo.com/quote/'+encodeURIComponent(t)+'" target=_blank rel=noopener><b>'+t+'</b></a>';}};
function critHtml(c){{if(!c)return '<div class=critnote>该层为数据覆盖层,无逐票排除标准</div>';var h='<div class=crittitle>'+c.title+'</div><ul>';for(var i=0;i<c.rules.length;i++)h+='<li>'+c.rules[i]+'</li>';h+='</ul>';if(c.note)h+='<div class=critnote>'+c.note+'</div>';return h;}}
var LROWS=[],LBASE='',LKEY='metric',LASC=false;var LNUM=['metric'];
function Lopts(arr){{return '<option value="">'+arr[0]+'</option>'+arr[1].map(function(s){{return '<option>'+s+'</option>';}}).join('');}}
function Luniq(rows,f){{var out=[],seen={{}};for(var i=0;i<rows.length;i++){{var v=f(rows[i]);if(v&&!seen[v]){{seen[v]=1;out.push(v);}}}}out.sort();return out;}}
function LrowHtml(r){{
var kind=r.kind==='win'?'<span class="ctag c-win">牛股</span>':'<span class="badge b-sig">暴雷股</span>';
var mtxt=(r.kind==='win'&&r.metric>5000)?'<span class=pos>&gt;5000%</span>':fmtPct(r.metric);
return '<tr><td class=l>'+tkl(r.tk)+' <span class=mut style=font-size:11px>'+r.nm+'</span></td><td class=l>'+(r.sec||'')+'<br><span class=mut style=font-size:11px>'+(r.ind||'')+'</span></td><td class=l>'+kind+'</td><td>'+mtxt+'</td><td class="l reason">'+r.why+'</td></tr>';
}}
function LfillFilters(rows){{
document.getElementById('LfSec').innerHTML=Lopts(['全部板块',Luniq(rows,function(r){{return r.sec;}})]);
document.getElementById('LfInd').innerHTML=Lopts(['全部细分行业',Luniq(rows,function(r){{return r.ind;}})]);
document.getElementById('LfQ').value='';document.getElementById('LfKind').value='';
}}
function LonSecChange(){{
var fs=document.getElementById('LfSec').value;
document.getElementById('LfInd').innerHTML=Lopts(['全部细分行业',Luniq(LROWS.filter(function(r){{return !fs||r.sec===fs;}}),function(r){{return r.ind;}})]);
LrenderRows();
}}
function LsortBy(key){{if(LKEY===key)LASC=!LASC;else{{LKEY=key;LASC=(LNUM.indexOf(key)<0);}}LrenderRows();}}
function LrenderRows(){{
var q=(document.getElementById('LfQ').value||'').toUpperCase();
var fs=document.getElementById('LfSec').value,fi=document.getElementById('LfInd').value,fk=document.getElementById('LfKind').value;
var rows=LROWS.filter(function(r){{
if(q&&((r.tk+' '+(r.nm||'')).toUpperCase().indexOf(q)<0))return false;
if(fs&&(r.sec||'')!==fs)return false;
if(fi&&(r.ind||'')!==fi)return false;
if(fk&&r.kind!==fk)return false;
return true;}});
var num=LNUM.indexOf(LKEY)>=0;
rows.sort(function(a,b){{
var x,y;
if(LKEY==='sec'){{x=(a.sec||'')+'|'+(a.ind||'');y=(b.sec||'')+'|'+(b.ind||'');}}
else{{x=a[LKEY];y=b[LKEY];}}
if(num){{x=(x==null||x!==x)?-1e15:x;y=(y==null||y!==y)?-1e15:y;return LASC?x-y:y-x;}}
return LASC?String(x||'').localeCompare(String(y||'')):String(y||'').localeCompare(String(x||''));}});
var ths=document.querySelectorAll('#lt thead th[data-key]');
for(var t=0;t<ths.length;t++){{var old=ths[t].querySelector('.arw');if(old)old.remove();if(ths[t].dataset.key===LKEY){{var sp=document.createElement('span');sp.className='arw';sp.textContent=LASC?' ▲':' ▼';ths[t].appendChild(sp);}}}}
document.getElementById('layerCount').innerHTML=LBASE+(rows.length!==LROWS.length?' <span class=mut>(筛后 '+rows.length+'/'+LROWS.length+')</span>':'');
var h='';for(var j=0;j<rows.length;j++)h+=LrowHtml(rows[j]);
document.getElementById('ltb').innerHTML=h||'<tr><td colspan=5 class=mut>无匹配</td></tr>';
}}
function selLayer(code){{
var fl=document.querySelectorAll('.flayer');for(var i=0;i<fl.length;i++)fl[i].classList.toggle('sel',fl[i].dataset.code===code);
document.getElementById('layerCrit').innerHTML=critHtml(LAYERCRIT[code]);
LROWS=LAYERROWS.filter(function(r){{return r.layer===code;}});
var nw=LROWS.filter(function(r){{return r.kind==='win';}}).length,nb=LROWS.length-nw;
LBASE=(LAYERNAME[code]||code)+' — 该层涉及 <span class=pos>'+nw+'</span> 只牛股 · <span class=neg>'+nb+'</span> 只暴雷股';
LKEY='metric';LASC=false;
LfillFilters(LROWS);
LrenderRows();
document.getElementById('layerPanel').style.display='';
var wl=document.getElementById('wl');if(wl){{for(var k=0;k<wl.options.length;k++)if(wl.options[k].value===code){{wl.value=code;filtW();break;}}}}
var bl=document.getElementById('bl');if(bl){{for(var k2=0;k2<bl.options.length;k2++)if(bl.options[k2].value===code){{bl.value=code;filtB();break;}}}}
document.getElementById('layerPanel').scrollIntoView({{behavior:'smooth',block:'start'}});
}}
</script></body></html>"""
(OUT/'index.html').write_text(page2)
print(f"→ ../site/index.html (漏斗) + ../site/winners.html (大牛股列表)")
print(f"  大牛股表{len(winners)}行, 漏斗大牛{len(funnel['winners'])}+暴雷{len(funnel['blowups'])}行")
