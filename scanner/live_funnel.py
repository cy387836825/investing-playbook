#!/usr/bin/env python3
"""当日实时漏斗构建器 —— 用今天的数据跑同一套 6 层过滤,产出可存档的快照。

层序与回测一致(sector 最上游):universe → 行业板块排除 → 信号命中 → 市值≥$1B → curation → 通过。
与回测的区别:① 无"未来",不标牛股/暴雷股,只追踪今日命中股沿漏斗往下;
② 当日市值直接用 Finviz 当前 mcap_b(非回测的 PIT 股数×入场价)。

每份快照冻结当时全部条件(FLOOR_B / 行业排除名单 / 信号定义 / curation 规则),
日后改条件不影响旧快照。CLI 可无服务器直接生成:python live_funnel.py [--limit N] [--no-refresh]
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import sector_exclusion as se
from sector_exclusion import classify_exclusion, LAYER_CRITERIA
from funnel_common import FLOOR_B, cap_tier
from signals import SIGNALS, pit_qseries, yoy, REV_TAGS
from curation import _units, _ttm, _lumpy, curate_pass
from backtest import _cik_map, _companyfacts_cached

BASE = Path(__file__).resolve().parent
SNAP_DIR = BASE / "snapshots"
RND_TAG = "ResearchAndDevelopmentExpense"

# 当日各层"具体标准"文案(点击漏斗层展开;冻结进快照)
def _crit(floor_b):
    return {
        'universe': {'title': 'universe·有数据(当日 Finviz 快照)',
            'rules': ['Finviz 当日快照,剔除 ETF/基金(Stocks only)', '需 EDGAR companyfacts 可得才判信号'],
            'note': '当前快照,非全域;是数据覆盖上界'},
        'sector': LAYER_CRITERIA,
        'signal': {'title': '信号命中(S1/S1超/S2a/S2b 任一,截至今日最新季)',
            'rules': ['S1 周期反转:毛利率连续≥2季改善 且 TTM毛利率 < 历史基线',
                      'S1超 超级周期:连续≥2季改善 且 TTM≥历史基线 且 营收同比≥40%',
                      'S2a 首次盈利:最新季 GAAP 净利>0 且 前4季中≥3季≤0',
                      'S2b 营收加速:最新季营收同比≥25% 且 > 上一季同比'],
            'note': '实时:对 asof=今日 取最新可得季度判定(与回测同一 signals.py 定义)'},
        'mcap': {'title': f'当前市值 ≥ ${floor_b:.0f}B',
            'rules': ['市值 = Finviz 当前市值(mcap_b)', f'< ${floor_b:.0f}B 的命中在此剔除'],
            'note': '实时用当前市值,非回测的触发时 PIT 市值'},
        'curation': {'title': 'curation 通过(信号专属质量门)',
            'rules': ['S1/S1超 → 要求非一次性(排除 lumpy 利润)',
                      'S1超 / S2a → 要求盈利(TTM 净利>0)',
                      'S2b → 要求估值合格:盈利用 PEG≤3(无PEG则PE≤50);不盈利回退 PS≤15',
                      '关键数据缺失时不剔除(避免误杀)'],
            'note': '见 curation.py::curate_pass'},
    }


def _frozen_criteria(floor_b):
    """冻结当时的机器可读条件(原始名单+阈值),供快照溯源。"""
    return {
        'floor_b': floor_b,
        'sector_rules': {
            'SHELL': sorted(se.SHELL),
            'BIOTECH_IND': se.BIOTECH_IND, 'BIOTECH_RND_RATIO': se.BIOTECH_RND_RATIO,
            'AIRLINE_MARINE': sorted(se.AIRLINE_MARINE),
            'COMMODITY_MICRO': sorted(se.COMMODITY_MICRO), 'COMMODITY_MCAP_CEIL': se.COMMODITY_MCAP_CEIL,
            'LEGACY_RETAIL_MEDIA': sorted(se.LEGACY_RETAIL_MEDIA),
        },
        'layer_criteria': _crit(floor_b),
    }


def _facts_units(cik):
    """一次性从 companyfacts 取 rev/ni/gp/rnd units。返回 dict 或 None。"""
    if not cik:
        return None
    fc = _companyfacts_cached(cik)
    if not fc:
        return None
    rev_u = None
    for tg in REV_TAGS:
        rev_u = _units(fc, tg)
        if rev_u:
            break
    return {'rev': rev_u, 'ni': _units(fc, 'NetIncomeLoss'),
            'gp': _units(fc, 'GrossProfit'), 'rnd': _units(fc, RND_TAG)}


def _live_curation(sigset, u, asof, mcap_b):
    """当日 curation:用当前市值算 PS/PE/PEG,复用 curate_pass。返回 (pass:bool, reason:str, extras:dict)。"""
    tr = _ttm(u['rev'], asof) if u.get('rev') else None
    tn = _ttm(u['ni'], asof) if u.get('ni') else None
    mc = mcap_b * 1e9 if (mcap_b is not None and mcap_b == mcap_b) else None
    ps = (mc / tr) if (mc and tr and tr > 0) else None
    pe = (mc / tn) if (mc and tn and tn > 0) else None
    g = yoy(pit_qseries(u['rev'], asof), 0) if u.get('rev') else None
    prof = (tn is not None and tn > 0)
    lum = _lumpy(u['ni'], asof) if u.get('ni') else False
    peg = (pe / (g * 100)) if (pe and g and g > 0) else None
    if prof and pe:
        valok = (peg <= 3) if peg is not None else (pe <= 50)
    elif ps:
        valok = ps <= 15
    else:
        valok = True
    ok = curate_pass(sigset, prof, lum, valok)
    reasons = []
    if ('S2a' in sigset) and not prof: reasons.append('S2a要求盈利未过')
    if ('S1超' in sigset) and not prof: reasons.append('S1超要求盈利未过(伪周期)')
    if (('S1' in sigset) or ('S1超' in sigset)) and lum: reasons.append('S1非一次性未过')
    if ('S2b' in sigset) and not valok:
        vm = (f"PE{pe:.0f}" if pe else "") + (f" PS{ps:.0f}" if ps else "")
        reasons.append(f'S2b估值透支({vm.strip()})' if vm.strip() else 'S2b估值透支')
    extras = {'ps': round(ps, 1) if ps else None, 'pe': round(pe, 1) if pe else None,
              'rev_yoy': round(g * 100) if g is not None else None,
              'profitable': prof, 'lumpy': lum}
    return (ok, '' if ok else ('+'.join(reasons) or '未过curation'), extras)


def build(asof=None, limit=None, refresh=True, progress_cb=None):
    """跑当日漏斗,返回 snapshot dict。progress_cb(stage, done, total, hits) 供进度条。"""
    asof = asof or time.strftime('%Y-%m-%d')
    def prog(stage, done, total, hits):
        if progress_cb:
            progress_cb(stage, done, total, hits)

    if refresh:
        prog('刷新universe', 0, 0, 0)
        import scan
        scan.fetch_universe()

    uni = pd.read_csv(BASE / 'universe.csv')
    uni['mcap_b'] = pd.to_numeric(uni['mcap_b'], errors='coerce')
    if uni['mcap_b'].max() > 1e5:                      # 与 scan/assemble_viz 一致:单位需/1e6得十亿
        uni['mcap_b'] = uni['mcap_b'] / 1e6
    if limit:
        uni = uni.head(limit)
    ciks = _cik_map()
    n_all = len(uni)

    n_excl = 0
    hitrows = []
    sector_excluded = []          # 所有被行业板块排除的公司(不限命中),按当前市值排名
    for i, (_, row) in enumerate(uni.iterrows(), 1):
        tk = str(row['ticker'])
        industry = row.get('industry') if isinstance(row.get('industry'), str) else ''
        mcap_b = row['mcap_b']
        mcap_b = float(mcap_b) if (mcap_b is not None and mcap_b == mcap_b) else None
        u = _facts_units(ciks.get(tk.upper()))
        ttm_rev = _ttm(u['rev'], asof) if (u and u.get('rev')) else None
        ttm_rnd = _ttm(u['rnd'], asof) if (u and u.get('rnd')) else None

        sec_excl, swhy = classify_exclusion(industry, mcap_b, ttm_rev, ttm_rnd)

        # 信号命中(截至 asof 最新季)
        fl = []
        if u:
            f = {'rev': u['rev'], 'ni': u['ni'], 'gp': u['gp']}
            fl = [name for name, fn in SIGNALS.items() if fn(f, asof) is True]

        if sec_excl:
            n_excl += 1
            sector_excluded.append({
                'ticker': tk, 'name': (row.get('name') or ''), 'sector': (row.get('sector') or ''),
                'industry': industry, 'mcap_b': round(mcap_b, 2) if mcap_b is not None else None,
                'cap_tier': cap_tier(mcap_b), 'exit_layer': 'sector', 'why': swhy,
                'hit': bool(fl), 'signals': '+'.join(fl)})   # hit=是否也命中了信号(信号在行业排除之后,仅供参考)

        if fl:  # 只收录今日命中股,追踪其退出层
            sigset = set(fl)
            if sec_excl:
                layer, why, extras = 'sector', swhy, {}
            elif mcap_b is None or mcap_b < FLOOR_B:
                mtxt = f'${mcap_b:.2f}B' if mcap_b is not None else '市值缺失'
                layer, why, extras = 'mcap', f'当前市值{mtxt}<${FLOOR_B:.0f}B', {}
            else:
                cok, creason, extras = _live_curation(sigset, u, asof, mcap_b)
                layer, why = ('passed', '通过全部层') if cok else ('curation', creason)
            rec = {'ticker': tk, 'name': (row.get('name') or ''), 'sector': (row.get('sector') or ''),
                   'industry': industry, 'mcap_b': round(mcap_b, 2) if mcap_b is not None else None,
                   'cap_tier': cap_tier(mcap_b), 'signals': '+'.join(fl),
                   'exit_layer': layer, 'why': why,
                   'ps': extras.get('ps'), 'pe': extras.get('pe'), 'rev_yoy': extras.get('rev_yoy'),
                   'profitable': extras.get('profitable'), 'lumpy': extras.get('lumpy')}
            hitrows.append(rec)

        if i % 100 == 0 or i == n_all:
            prog('扫描', i, n_all, len(hitrows))

    # 层计数(sector 最上游;signal/mcap/curation 均在未排除票中计)
    n_after_excl = n_all - n_excl
    non_excl_hits = [r for r in hitrows if r['exit_layer'] != 'sector']
    n_sig = len(non_excl_hits)
    n_mcap = sum(1 for r in non_excl_hits if r['exit_layer'] != 'mcap')
    n_cur = sum(1 for r in hitrows if r['exit_layer'] == 'passed')
    shortlist = [r for r in hitrows if r['exit_layer'] == 'passed']
    sector_excluded.sort(key=lambda r: -(r['mcap_b'] or 0))    # 按当前市值降序排名

    crit = _crit(FLOOR_B)
    snap = {
        'asof': asof,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'floor_b': FLOOR_B,
        'universe_n': n_all, 'excluded_n': n_excl, 'hit_n': len(hitrows), 'shortlist_n': len(shortlist),
        'layers': [
            {'code': 'market', 'name': '全市场美股', 'n': '~4000+', 'note': '免费数据未覆盖全域,此层不可枚举'},
            {'code': 'universe', 'name': 'universe·有数据', 'n': n_all, 'note': 'Finviz当日快照', 'criteria': crit['universe']},
            {'code': 'sector', 'name': '第1层·行业板块排除', 'n': n_after_excl, 'note': '空壳/早期生物/航空海运/小资源商/衰退传统', 'criteria': crit['sector']},
            {'code': 'signal', 'name': '第2层·信号命中', 'n': n_sig, 'note': 'S1/S1超/S2a/S2b任一(截至今日最新季)', 'criteria': crit['signal']},
            {'code': 'mcap', 'name': f'第3层·当前市值≥${FLOOR_B:.0f}B', 'n': n_mcap, 'note': 'Finviz当前市值', 'criteria': crit['mcap']},
            {'code': 'curation', 'name': '第4层·curation通过', 'n': n_cur, 'note': '信号专属过滤(估值/盈利/非一次性)', 'criteria': crit['curation']},
        ],
        'hitrows': hitrows,
        'shortlist': shortlist,
        'sector_excluded': sector_excluded,     # 所有被行业排除的公司(按当前市值排名),供点击行业层查看全量
        'criteria_frozen': _frozen_criteria(FLOOR_B),
    }
    return snap


def save_snapshot(snap, rebuild=True):
    """写 snapshots/<asof>.json(每日一份,同日覆盖)+ 更新 index.json。
    rebuild=True 时顺带重建 site/live.html(把新快照内联进去,离线 file:// 可看)。"""
    SNAP_DIR.mkdir(exist_ok=True)
    path = SNAP_DIR / f"{snap['asof']}.json"
    json.dump(snap, open(path, 'w'), ensure_ascii=False)
    dates = sorted(p.stem for p in SNAP_DIR.glob('*.json') if p.stem != 'index')
    json.dump({'dates': dates}, open(SNAP_DIR / 'index.json', 'w'), ensure_ascii=False)
    if rebuild:
        try:
            import build_live_site
            build_live_site.main()
        except Exception as e:                          # 重建失败不阻断快照保存
            print(f"⚠️ 重建 live.html 失败: {e}", flush=True)
    return path


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, help='只扫前N只(冒烟测试)')
    ap.add_argument('--no-refresh', action='store_true', help='跳过 Finviz universe 刷新,用现有 universe.csv')
    ap.add_argument('--asof', type=str, help='覆盖日期(默认今天)')
    a = ap.parse_args()

    def _p(stage, done, total, hits):
        print(f"  [{stage}] {done}/{total} 命中{hits}", flush=True)

    snap = build(asof=a.asof, limit=a.limit, refresh=not a.no_refresh, progress_cb=_p)
    path = save_snapshot(snap)
    L = {l['code']: l['n'] for l in snap['layers']}
    print(f"→ {path}")
    print(f"  universe {L['universe']} → 行业排除后 {L['sector']} → 命中 {L['signal']} "
          f"→ 市值≥${snap['floor_b']:.0f}B {L['mcap']} → curation通过 {L['curation']}(=今日shortlist)")
