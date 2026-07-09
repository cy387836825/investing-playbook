#!/usr/bin/env python3
"""装配两个可视化页面的数据: winners.json(大牛股列表) + funnel.json(漏斗)"""
import json, pandas as pd
from backtest import _price_hist, _px_from_hist, _companyfacts_cached, _cik_map, REV_TAGS
from curation import _units, _pit_latest, _ttm, _lumpy, SHARE_TAGS, curate_pass
from signals import pit_qseries, yoy

uni = pd.read_csv('universe.csv')
uni['mcap_b'] = pd.to_numeric(uni['mcap_b'], errors='coerce')
if uni['mcap_b'].max() > 1e5: uni['mcap_b'] = uni['mcap_b']/1e6  # 与scan.py一致(universe.csv市值单位需/1e6得十亿)
meta = {r['ticker']: (r['name'], r['sector'], round(r['mcap_b'],1)) for _,r in uni.iterrows()}
ee = pd.read_csv('earnings_entry.csv')
ee_map = {r.ticker: r for r in ee.itertuples()}
START, END = '2020-06-01', '2026-07-05'

def lowhigh(h):
    lo_d, hi_d = h.idxmin(), h.idxmax()
    return float(h.min()), str(lo_d.date()), float(h.max()), str(hi_d.date())

def dd_from_peak(h):
    """峰值后最大回调"""
    run = h.cummax(); dd = (h/run - 1)
    return float(dd.min())

# ---- 逐票算价格特征 ----
feat = {}
for tk in uni['ticker']:
    h = _price_hist(tk, START, END)
    if h is None or len(h) < 50: continue
    lo, lod, hi, hid = lowhigh(h)
    feat[tk] = {'low':round(lo,2),'low_date':lod,'high':round(hi,2),'high_date':hid,
                'low2high': round(hi/lo-1,3), 'dd_peak': round(dd_from_peak(h),3),
                'now': round(float(h.iloc[-1]),2)}

# ==== 1) winners.json: 信号命中的大牛股(峰值>300%) ====
winners = []
for r in ee.itertuples():
    if r.pkr <= 3.0: continue           # 峰值>300%
    f = feat.get(r.ticker, {})
    nm, sec, mc = meta.get(r.ticker, ('','',None))
    winners.append({
        'ticker': r.ticker, 'name': nm, 'sector': sec,
        'low': f.get('low'), 'low_date': f.get('low_date'),
        'high': f.get('high'), 'high_date': f.get('high_date'),
        'low2high_pct': round(f.get('low2high',0)*100) if f else None,
        'signal_date': r.earn_date, 'signal_type': r.sig,
        'entry': round(r.entry,2), 'now': round(r.now,2),
        'hold_pct': round(r.ret*100),          # 买入持有至今
        'peak_pct': round(r.pkr*100),          # 买入潜在最大回报
        'maxdd_pct': round(r.dd*100),          # 买入后最大回调
        'maxloss_pct': round(r.mul*100),       # 买入后最大浮亏
    })
winners.sort(key=lambda x: -x['peak_pct'])
json.dump(winners, open('winners.json','w'), ensure_ascii=False)
print(f"winners.json: {len(winners)}只大牛股")

# ==== 2) funnel.json ====
# 定义大牛股(全≥5B universe中低→高>300%)、暴雷股(峰值后回调>70%)
ciks = _cik_map()
def curation_status(tk):
    """返回(pass:bool, reason:str, sig:str) — 信号命中股的signal-specific curation"""
    if tk not in ee_map: return (None, '未触发信号', '')
    r = ee_map[tk]; cik = ciks.get(str(tk).upper())
    if not cik: return (True, '', r.sig)
    fc = _companyfacts_cached(cik)
    if not fc: return (True, '', r.sig)
    a = r.earn_date; rev_u = None
    for tg in REV_TAGS:
        rev_u = _units(fc, tg)
        if rev_u: break
    ni_u = _units(fc, 'NetIncomeLoss')
    sh = _pit_latest(fc, SHARE_TAGS, a); tr=_ttm(rev_u,a) if rev_u else None; tn=_ttm(ni_u,a) if ni_u else None
    mc=(r.entry*sh) if(r.entry and sh) else None
    ps=(mc/tr) if(mc and tr and tr>0) else None; pe=(mc/tn) if(mc and tn and tn>0) else None
    g=yoy(pit_qseries(rev_u,a),0) if rev_u else None
    prof=(tn is not None and tn>0); lum=_lumpy(ni_u,a) if ni_u else False
    peg=(pe/(g*100)) if(pe and g and g>0) else None
    if prof and pe: valok=(peg<=3) if peg is not None else(pe<=50)
    elif ps: valok=ps<=15
    else: valok=True
    sigset={s for s in('S1','S1超','S2a','S2b') if s in r.sig}
    ok = curate_pass(sigset, prof, lum, valok)
    if ok: return (True, '', r.sig)
    # 剔除原因
    reasons=[]
    if ('S2a' in sigset) and not prof: reasons.append('S2a要求盈利未过')
    if (('S1' in sigset)or('S1超'in sigset)) and lum: reasons.append('S1非一次性未过')
    if ('S2b' in sigset) and not valok:
        vm = (f"PE{pe:.0f}" if pe else "") + (f" PS{ps:.0f}" if ps else "")
        reasons.append(f'S2b估值透支({vm.strip()})' if vm.strip() else 'S2b估值透支')
    return (False, '+'.join(reasons) or '未过curation', r.sig)

winset, blowset = [], []
for tk, f in feat.items():
    nm, sec, mc = meta.get(tk, ('','',None))
    is_win = f['low2high'] > 3.0                 # 低→高>300%
    is_blow = f['dd_peak'] < -0.70               # 峰值后回调>70%=暴雷
    if not (is_win or is_blow): continue
    cur_pass, cur_reason, sig = curation_status(tk)
    triggered = tk in ee_map
    # 判定退出层
    if not triggered: layer, why = 'signal', '信号层未触发(信号滞后/不达阈值/板块指标缺)'
    elif cur_pass is False: layer, why = 'curation', cur_reason
    else: layer, why = 'passed', '通过全部三层'
    rec = {'ticker':tk,'name':nm,'sector':sec,'mcap_b':mc,
           'low2high_pct':round(f['low2high']*100),'dd_peak_pct':round(f['dd_peak']*100),
           'signal_type':sig,'exit_layer':layer,'why':why,'triggered':triggered}
    if is_win: winset.append(rec)
    if is_blow: blowset.append(rec)

winset.sort(key=lambda x:-x['low2high_pct'])
blowset.sort(key=lambda x: x['dd_peak_pct'])
# 漏斗层计数
n_all = len(uni)
n_sig = sum(1 for tk in uni['ticker'] if tk in ee_map)
n_cur = sum(1 for tk in uni['ticker'] if tk in ee_map and curation_status(tk)[0] is True)
funnel = {
    'layers': [
        {'name':'全市场美股','n':'~4000+','note':'免费数据未覆盖<$5B,此层不可枚举'},
        {'name':'第1层·市值≥$5B','n':n_all,'note':'universe(Finviz)'},
        {'name':'第2层·信号命中','n':n_sig,'note':'S1/S1超/S2a/S2b任一触发(财报次日,2021-2025)'},
        {'name':'第3层·curation通过','n':n_cur,'note':'信号专属过滤(估值/盈利/非一次性)'},
    ],
    'winners': winset,      # 大牛股(低→高>300%)及其退出层
    'blowups': blowset,     # 暴雷股(峰值后回调>70%)及是否漏过滤网
}
json.dump(funnel, open('funnel.json','w'), ensure_ascii=False)
# 统计:大牛股在各层的分布 + 暴雷股通过全部三层的(漏网)
from collections import Counter
wc = Counter(w['exit_layer'] for w in winset)
bc = Counter(b['exit_layer'] for b in blowset)
print(f"funnel.json: 大牛股{len(winset)}只 (信号层漏{wc['signal']}/curation剔{wc['curation']}/通过{wc['passed']})")
print(f"           暴雷股{len(blowset)}只 (通过全部三层=漏网{bc['passed']}/被信号层挡{bc['signal']}/被curation挡{bc['curation']})")
