#!/usr/bin/env python3
"""抓取 Nasdaq-100【当前成分】以及【2014年以来被剔除成分】,输出两张CSV,可重复运行更新。

数据源:英文维基"List of NASDAQ-100 companies"(结构与 S&P 页面一致,变更日志解析共用 wiki_index.py)。
  - 表0:当前~101只成分,含 Ticker / Company / ICB Industry / ICB Subsector(无官方纳入日)。
  - 表1:成分变更日志,含 生效日 / 纳入ticker / 剔除ticker / 原因。

纳入日 date_added 由变更日志回填(该 ticker 最近一次纳入事件):
  - 当前成分:取历史上最近一次纳入日;若纳入早于日志起点则留空。
  - 被剔除成分:取剔除日之前最近一次纳入日;同样可能留空。
⚠️Nasdaq 不公开每只成分的官方纳入日,故 date_added 为"从变更日志推断",非官方,且老成分可能缺失。

更新方式:直接重跑本脚本(或 --force 跳过缓存)。
输出:nasdaq100_current.csv、nasdaq100_delisted.csv;原始表缓存 cache/nasdaq100_history.json(TTL 7天)。
"""
import json, sys, time
from pathlib import Path
import pandas as pd
import wiki_index as wi

BASE = Path(__file__).resolve().parent
CACHE = BASE / 'cache' / 'nasdaq100_history.json'
CURRENT_CSV = BASE / 'nasdaq100_current.csv'
DELISTED_CSV = BASE / 'nasdaq100_delisted.csv'
TTL_DAYS = 7
SINCE = '2014-01-01'          # 剔除名单的起始日
URL = 'https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies'


def _col(df, *cands):
    for c in df.columns:
        if any(k.lower() in str(c).lower() for k in cands):
            return c
    return None


def _parse_current(t0):
    """表0 -> [{ticker, company, icb_industry, icb_subsector}]"""
    c_tk = _col(t0, 'Ticker', 'Symbol')
    c_co = _col(t0, 'Company')
    c_ind = _col(t0, 'ICB Industry', 'Industry')
    c_sub = _col(t0, 'ICB Subsector', 'Subsector', 'Sub-Industry')
    rows = []
    for _, r in t0.iterrows():
        rows.append({
            'ticker': wi.norm(r[c_tk]),
            'company': str(r.get(c_co, '')).strip(),
            'icb_industry': str(r.get(c_ind, '')).strip() if c_ind else '',
            'icb_subsector': str(r.get(c_sub, '')).strip() if c_sub else '',
        })
    rows.sort(key=lambda x: x['ticker'])
    return rows


def load_tables(force=False):
    """返回 (current_rows, changes_rows, asof)。命中缓存则不联网。供 assemble_viz 做 point-in-time 标注。"""
    if CACHE.exists() and not force:
        if time.time() - CACHE.stat().st_mtime < TTL_DAYS * 86400:
            d = json.load(open(CACHE))
            return d['current'], d['changes'], d.get('asof', '')
    tabs = wi.fetch_tables(URL)
    t0 = next((t for t in tabs
               if _col(t, 'Ticker', 'Symbol') is not None and 90 <= len(t) <= 110), None)
    t1 = next((t for t in tabs
               if any('Removed' in str(c) for c in t.columns)), None)
    if t0 is None or t1 is None:
        raise RuntimeError('维基页面结构变了,找不到成分表或变更表')
    current = _parse_current(t0)
    changes = wi.parse_changes(t1)
    asof = time.strftime('%Y-%m-%d')
    if len(current) >= 90:      # 抓取成功才写缓存,避免固化坏数据
        CACHE.parent.mkdir(exist_ok=True)
        json.dump({'current': current, 'changes': changes, 'asof': asof},
                  open(CACHE, 'w'), ensure_ascii=False)
    return current, changes, asof


def build(force=False):
    """抓取/读缓存,写出两张CSV。返回 (current, delisted, asof)。"""
    current, changes, asof = load_tables(force=force)
    # 当前成分的 date_added 从变更日志回填(历史最近一次纳入)
    for c in current:
        c['date_added'] = wi.latest_add_before(changes, c['ticker'])
    delisted = wi.build_delisted(changes, SINCE)
    pd.DataFrame(current, columns=['ticker', 'company', 'icb_industry',
                                   'icb_subsector', 'date_added']) \
        .to_csv(CURRENT_CSV, index=False)
    pd.DataFrame(delisted, columns=['ticker', 'security', 'date_added',
                                    'date_removed', 'reason']) \
        .to_csv(DELISTED_CSV, index=False)
    return current, delisted, asof


if __name__ == '__main__':
    force = '--force' in sys.argv
    current, delisted, asof = build(force=force)
    cur_filled = sum(1 for c in current if c['date_added'])
    del_filled = sum(1 for d in delisted if d['date_added'])
    print(f"asof {asof}")
    print(f"当前成分 {len(current)} 只 -> {CURRENT_CSV.name}"
          f"(其中 {cur_filled} 只从日志推断出纳入日)")
    print(f"{SINCE} 以来被剔除 {len(delisted)} 只 -> {DELISTED_CSV.name}"
          f"(其中 {del_filled} 只回填到纳入日,{len(delisted) - del_filled} 只纳入日早于日志起点留空)")
    print("抽样剔除记录:")
    for d in delisted[-5:]:
        print(f"  {d['ticker']:6} 入{d['date_added'] or '  ??  ':10} 出{d['date_removed']}  {d['reason'][:50]}")
