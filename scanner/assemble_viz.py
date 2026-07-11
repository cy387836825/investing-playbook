#!/usr/bin/env python3
"""装配两个可视化页面的数据: winners.json(大牛股列表) + funnel.json(漏斗)"""
import json, pandas as pd, time
from backtest import _price_hist, _px_from_hist, _companyfacts_cached, _cik_map, REV_TAGS
from curation import _units, _pit_latest, _ttm, _lumpy, SHARE_TAGS, curate_pass
from signals import pit_qseries, yoy

TODAY = time.strftime('%Y-%m-%d')
FLOOR_B = 1.0   # 第一层过滤:信号触发时市值(股数×入场价)≥$1B。调此一处即可换下限

def annualize(mult, d0, d1):
    """把总倍数mult(=终值/初值)按d0→d1的时长年化。返回百分数(int)或None(时长<30天不年化)。"""
    if mult is None or mult <= 0:
        return None
    try:
        days = (pd.Timestamp(d1) - pd.Timestamp(d0)).days
    except Exception:
        return None
    if days < 30:
        return None
    return round((mult ** (365.25 / days) - 1) * 100)

def classify_driver(rev_sig, rev_now, ni_sig, ni_now, sector):
    """驱动分类:基本面兑现可在'营收端'(S2b成长)或'利润端'(S1周期修复/S2a扭亏)。
    只看营收会误判周期股(如WDC:营收降但利润率修复)。故同时看营收增长+盈利改善。
    返回 (driver_label, tier, rev_growth_pct)。tier: fund/partial/weak/none 决定颜色。"""
    g = round((rev_now / rev_sig - 1) * 100) if (rev_sig and rev_now and rev_sig > 0) else None
    turned_profit = (ni_sig is not None and ni_now is not None and ni_sig <= 0 < ni_now)      # 扭亏为盈
    profit_grew = (ni_sig is not None and ni_now is not None and ni_sig > 0 and ni_now > ni_sig * 1.5)  # 利润扩张
    # 强基本面
    if g is not None and g >= 100:
        return ('基本面·营收翻倍+', 'fund', g)
    if turned_profit:
        return ('基本面·扭亏为盈', 'fund', g)
    # 中基本面
    if g is not None and g >= 40:
        return ('基本面·营收增长', 'partial', g)
    if profit_grew:
        return ('基本面·利润扩张', 'partial', g)
    # 营收利润都弱 → 用板块解释真实驱动
    sec = sector or ''
    if sec in ('Energy', 'Basic Materials'):
        return ('商品周期驱动', 'weak', g)
    if sec == 'Financial':
        return ('金融/加密驱动', 'weak', g)
    if sec == 'Healthcare':
        return ('生物药催化驱动', 'weak', g)
    if g is None:
        return ('无营收·投机/叙事', 'none', g)
    return ('弱基本面·情绪投机', 'weak', g)

uni = pd.read_csv('universe.csv')
uni['mcap_b'] = pd.to_numeric(uni['mcap_b'], errors='coerce')
if uni['mcap_b'].max() > 1e5: uni['mcap_b'] = uni['mcap_b']/1e6  # 与scan.py一致(universe.csv市值单位需/1e6得十亿)
meta = {r['ticker']: (r['name'], r['sector'], round(r['mcap_b'],1)) for _,r in uni.iterrows()}
ee = pd.read_csv('earnings_entry.csv')
ee_map = {}
for _r in ee.itertuples():
    ee_map.setdefault(_r.ticker, _r)   # 每票可有多次命中(按财报日升序),curation/漏斗只看首次触发
START, END = '2020-06-01', '2026-07-05'

def lowhigh(h):
    """尊重时间顺序的最大涨幅:低点必须在高点之前(否则是崩盘,不是低→高)。
    与dd_from_peak的cummax对称——用cummin求"从此前最低点到之后某高点"的最大涨幅。
    用位置索引(iloc/argmax),对价格序列中的重复日期免疫。"""
    ratio = (h / h.cummin()).values
    hi_pos = int(ratio.argmax())           # 最大涨幅出现位置(高点)
    hi = float(h.iloc[hi_pos]); hi_d = h.index[hi_pos]
    lo_pos = int(h.iloc[:hi_pos + 1].values.argmin())   # 高点之前(含)的最低点
    lo = float(h.iloc[lo_pos]); lo_d = h.index[lo_pos]
    return lo, str(lo_d.date()), hi, str(hi_d.date())

def dd_from_peak(h):
    """峰值后最大回调"""
    run = h.cummax(); dd = (h/run - 1)
    return float(dd.min())

# ---- 逐票算价格特征 ----
feat = {}
for tk in uni['ticker']:
    h = _price_hist(tk, START, END)
    if h is None or len(h) < 50: continue
    h = h[h > 0]                                 # 剔除微盘价格里的0/坏点(否则low2high除零)
    if len(h) < 50: continue
    lo, lod, hi, hid = lowhigh(h)
    if lo <= 0: continue
    feat[tk] = {'low':round(lo,2),'low_date':lod,'high':round(hi,2),'high_date':hid,
                'low2high': round(hi/lo-1,3), 'dd_peak': round(dd_from_peak(h),3),
                'now': round(float(h.iloc[-1]),2)}

# ==== 1) winners.json: 通过三层的候选(大牛 + 通过三层的非大牛),每次命中一行 ====
ciks = _cik_map()
def _mcp(r):   # 触发时市值($B),缺失当0
    v = getattr(r, 'mcap_pit', None)
    return float(v) if v == v and v is not None else 0.0

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
    reasons=[]
    if ('S2a' in sigset) and not prof: reasons.append('S2a要求盈利未过')
    if ('S1超' in sigset) and not prof: reasons.append('S1超要求盈利未过(伪周期)')
    if (('S1' in sigset)or('S1超'in sigset)) and lum: reasons.append('S1非一次性未过')
    if ('S2b' in sigset) and not valok:
        vm = (f"PE{pe:.0f}" if pe else "") + (f" PS{ps:.0f}" if ps else "")
        reasons.append(f'S2b估值透支({vm.strip()})' if vm.strip() else 'S2b估值透支')
    return (False, '+'.join(reasons) or '未过curation', r.sig)

# 逐票(首次触发)判定: 是否大牛(峰>300%) / 是否通过三层(curation过)。第一层市值门槛内。
cur_pass = {tk: (curation_status(tk)[0] is True) for tk in ee_map}
def _cat(tk):
    r = ee_map[tk]; w = r.pkr > 3.0; c = cur_pass.get(tk, False)
    if w and c: return ('大牛·过三层', w, c)
    if w and not c: return ('大牛·被curation挡', w, c)
    return ('过三层·非大牛', w, c)
# 候选 = 触发时市值≥$1B, 且(是大牛 或 通过三层)
big = {tk for tk, r in ee_map.items() if r.pkr > 3.0 and _mcp(r) >= FLOOR_B}
qualify = {tk for tk, r in ee_map.items()
           if _mcp(r) >= FLOOR_B and (r.pkr > 3.0 or cur_pass.get(tk))}
winners = []; hit_n = {}
for r in ee.itertuples():
    if r.ticker not in qualify: continue   # 候选的每一次命中都出一行
    hit_n[r.ticker] = hit_n.get(r.ticker, 0) + 1
    f = feat.get(r.ticker, {})
    nm, sec, mc = meta.get(r.ticker, ('','',None))
    # 持有期营收增长(信号日TTM vs 今日TTM) → 驱动分类
    cik = ciks.get(str(r.ticker).upper()); rev_sig=rev_now=ni_sig=ni_now=None
    if cik:
        fc = _companyfacts_cached(cik)
        if fc:
            ru=None
            for tg in REV_TAGS:
                ru=_units(fc,tg)
                if ru: break
            niu=_units(fc,'NetIncomeLoss')
            rev_sig=_ttm(ru,r.earn_date) if ru else None
            rev_now=_ttm(ru,TODAY) if ru else None
            ni_sig=_ttm(niu,r.earn_date) if niu else None
            ni_now=_ttm(niu,TODAY) if niu else None
    driver, tier, revg = classify_driver(rev_sig, rev_now, ni_sig, ni_now, sec)
    cat, is_win, cpass = _cat(r.ticker)        # 类别(票级,按首次触发判定)
    winners.append({
        'cat': cat, 'is_winner': is_win, 'curation_pass': cpass,
        'driver': driver, 'driver_tier': tier, 'rev_growth_pct': revg,
        'hit_n': hit_n[r.ticker],              # 该票第几次命中(按财报日升序)
        'mcap_pit_b': round(_mcp(r), 2),       # 触发时市值($B)
        'ticker': r.ticker, 'name': nm, 'sector': sec,
        'low': f.get('low'), 'low_date': f.get('low_date'),
        'high': f.get('high'), 'high_date': f.get('high_date'),
        'low2high_pct': round(f.get('low2high',0)*100) if f else None,
        'signal_date': r.earn_date, 'signal_type': r.sig,
        'entry': round(r.entry,2), 'now': round(r.now,2),
        'hold_pct': round(r.ret*100),          # 买入持有至今
        'peak_pct': round(r.pkr*100),          # 买入潜在最大回报
        'ann_hold_pct': annualize(1+r.ret, r.earn_date, TODAY),                          # 持有至今年化
        'ann_peak_pct': annualize(1+r.pkr, r.earn_date, getattr(r,'peak_date',TODAY)),   # 到峰值年化
        'maxdd_pct': round(r.dd*100),          # 买入后最大回调
        'maxloss_pct': round(r.mul*100),       # 买入后最大浮亏
    })
# 同票各次命中相邻排列:按该票最高峰值降序,票内按财报日升序
peak_tk = {}
for w in winners:
    peak_tk[w['ticker']] = max(peak_tk.get(w['ticker'], -10**9), w['peak_pct'])
for w in winners:
    w['hit_total'] = hit_n[w['ticker']]
winners.sort(key=lambda x: (-peak_tk[x['ticker']], x['ticker'], x['signal_date']))
json.dump(winners, open('winners.json','w'), ensure_ascii=False)
n_pass_nonwin = len({w['ticker'] for w in winners if w['curation_pass'] and not w['is_winner']})
print(f"winners.json: 大牛{len(big)}只 + 过三层非大牛{n_pass_nonwin}只 / {len(winners)}次命中")

def diagnose_miss(rev_u, ni_u, gp_u):
    """诊断一只'从未触发信号'的股票,具体卡在哪(用全历史数据看各信号为何都不触发)。"""
    revs = pit_qseries(rev_u, TODAY) if rev_u else None
    nis = pit_qseries(ni_u, TODAY) if ni_u else None
    gps = pit_qseries(gp_u, TODAY) if gp_u else None
    # S2b诊断: 营收增速峰值 + 是否曾加速
    max_yoy, accel_ever = None, False
    if revs is not None and len(revs) >= 6:
        ys = [yoy(revs, i) for i in range(min(10, len(revs) - 4))]
        ys = [y for y in ys if y is not None]
        if ys:
            max_yoy = max(ys)
            accel_ever = any(ys[i] >= 0.25 and ys[i] > ys[i + 1] for i in range(len(ys) - 1))
    # S2a诊断: 是否曾有"扭亏"形态
    first_profit_ever = False
    if nis is not None and len(nis) >= 5:
        v = list(nis.values)
        first_profit_ever = any(v[i] > 0 and sum(1 for x in v[i+1:i+5] if x <= 0) >= 3
                                for i in range(len(v) - 4))
    # 归因(优先给最具体的)
    if max_yoy is not None and max_yoy >= 0.25 and not accel_ever:
        return 'L13·营收高增长但从不"加速"(稳定复利,被S2b排除)'
    if gps is None and not first_profit_ever:
        return 'S1失明·无毛利数据 + 无首盈拐点(信号形状全不匹配)'
    if max_yoy is not None and max_yoy < 0.25:
        return f'增速不足·营收同比峰值仅{round(max_yoy*100)}%<25%阈值(基本面兑现在利润端)'
    if gps is None:
        return 'S1失明·无毛利数据(周期反转信号无法判定)'
    if max_yoy is None:
        return '数据缺口·营收季度数不足/IFRS外国股'
    return '信号滞后·拐点晚于测试窗口或未达阈值'


# ==== 2) funnel.json ====
# 暴雷股(峰值后回调>70%)。curation_status 已在上方(winners段)定义并复用。
def facts_and_driver(tk):
    """拉EDGAR,算全期营收/利润→驱动分类。返回(rev_u,ni_u,gp_u,driver,tier)"""
    cik = ciks.get(str(tk).upper())
    if not cik:
        return (None, None, None, '数据缺口', 'none')
    fc = _companyfacts_cached(cik)
    if not fc:
        return (None, None, None, '数据缺口', 'none')
    ru = None
    for tg in REV_TAGS:
        ru = _units(fc, tg)
        if ru:
            break
    niu, gpu = _units(fc, 'NetIncomeLoss'), _units(fc, 'GrossProfit')
    rs = pit_qseries(ru, TODAY) if ru else None
    ns = pit_qseries(niu, TODAY) if niu else None
    # 全期(最早→最新)营收/利润增长做驱动分类
    rev_early = float(rs.iloc[-4:].sum()) if (rs is not None and len(rs) >= 8) else None
    rev_now = float(rs.iloc[:4].sum()) if (rs is not None and len(rs) >= 4) else None
    ni_early = float(ns.iloc[-4:].sum()) if (ns is not None and len(ns) >= 8) else None
    ni_now = float(ns.iloc[:4].sum()) if (ns is not None and len(ns) >= 4) else None
    _, _, sector = meta.get(tk, ('', '', '')), None, meta.get(tk, ('', '', ''))[1]
    driver, tier, _ = classify_driver(rev_early, rev_now, ni_early, ni_now, sector)
    return (ru, niu, gpu, driver, tier)

winset, blowset = [], []
for tk, f in feat.items():
    nm, sec, mc = meta.get(tk, ('','',None))
    triggered = tk in ee_map
    mcap_pit = _mcp(ee_map[tk]) if triggered else None   # 触发时市值($B)
    is_win = f['low2high'] > 3.0                 # 低→高>300%
    # 暴雷判定按入场时点对齐:已触发的用"首次信号入场后回撤"(入场前的崩盘不算漏网),未触发的用全期回撤
    blow_dd = float(ee_map[tk].dd) if triggered else f['dd_peak']
    is_blow = blow_dd < -0.70
    if not (is_win or is_blow): continue
    cur_pass, cur_reason, sig = curation_status(tk)
    ru, niu, gpu, driver, tier = facts_and_driver(tk)
    # 判定退出层 + 具体原因(第一层已改为"触发时市值≥$1B")
    if not triggered:
        layer = 'signal'
        # 基本面驱动的漏网股→跑具体诊断; 非基本面→标注驱动
        if tier in ('fund', 'partial'):
            why = diagnose_miss(ru, niu, gpu)
        else:
            why = f'非基本面({driver})—框架本就不抓'
    elif mcap_pit < FLOOR_B:
        layer, why = 'mcap', f'触发时市值${mcap_pit:.2f}B<${FLOOR_B:.0f}B(第一层市值门槛)'
    elif cur_pass is False:
        layer, why = 'curation', cur_reason
    else:
        layer, why = 'passed', '通过全部三层'
    rec = {'ticker':tk,'name':nm,'sector':sec,'mcap_b':mc,'mcap_pit_b':round(mcap_pit,2) if mcap_pit is not None else None,
           'low2high_pct':round(f['low2high']*100),'dd_peak_pct':round(f['dd_peak']*100),
           'blow_dd_pct':round(blow_dd*100),   # 暴雷回撤:已触发=入场后,未触发=全期
           'signal_type':sig,'exit_layer':layer,'why':why,'triggered':triggered,
           'driver':driver,'driver_tier':tier}
    if is_win: winset.append(rec)
    if is_blow: blowset.append(rec)

winset.sort(key=lambda x:-x['low2high_pct'])
blowset.sort(key=lambda x: x['blow_dd_pct'])
# 漏斗层计数(第一层市值门槛现按触发时市值算,故排在信号命中之后)
trig = [tk for tk in uni['ticker'] if tk in ee_map]
n_all = len(uni)
n_sig = len(trig)
n_mcap = sum(1 for tk in trig if _mcp(ee_map[tk]) >= FLOOR_B)
n_cur = sum(1 for tk in trig if _mcp(ee_map[tk]) >= FLOOR_B and curation_status(tk)[0] is True)
funnel = {
    'floor_b': FLOOR_B,
    'layers': [
        {'name':'全市场美股','n':'~4000+','note':'免费数据未覆盖全域,此层不可枚举'},
        {'name':'universe·有数据','n':n_all,'note':'Finviz当前快照(EDGAR+价数据可得),数据覆盖上界'},
        {'name':'第1层·信号命中','n':n_sig,'note':'S1/S1超/S2a/S2b任一触发(财报次日,2021-2025)'},
        {'name':f'第2层·触发时市值≥${FLOOR_B:.0f}B','n':n_mcap,'note':'point-in-time市值=当时股数×入场价(无前视)'},
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
print(f"funnel.json: 大牛股{len(winset)}只 (信号层漏{wc['signal']}/市值<${FLOOR_B:.0f}B剔{wc['mcap']}/curation剔{wc['curation']}/通过{wc['passed']})")
print(f"           暴雷股{len(blowset)}只 (漏网{bc['passed']}/被信号层挡{bc['signal']}/被市值门槛挡{bc['mcap']}/被curation挡{bc['curation']})")
