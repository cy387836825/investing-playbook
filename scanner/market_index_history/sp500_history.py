#!/usr/bin/env python3
"""抓取 S&P 500【当前成分+纳入日】以及【2014年以来被剔除成分】,输出两张CSV,可重复运行更新。

数据源:英文维基"List of S&P 500 companies"(与 ../index_membership.py 同源)。
  - 表0:当前~503只成分,含 Symbol / Date added(纳入日)。
  - 表1:成分变更日志(约2000年至今),含 生效日 / 纳入ticker / 剔除ticker / 原因。
变更日志的通用解析在 wiki_index.py,与 nasdaq100_history.py 共用。

⚠️局限:变更日志只回溯到~2000年。被剔除的老成分若纳入日早于日志起点,则无法回填 date_added,留空。
   这是免费数据的固有缺陷(付费的point-in-time数据才完整),与 index_membership.py 的"拿不到历史成分"同理。

更新方式:直接重跑本脚本(或 --force 跳过缓存)。维基页面永远反映最新成分,无需手工维护。
输出:sp500_current.csv、sp500_delisted.csv;原始表缓存 cache/sp500_history.json(TTL 7天)。
"""
import json, sys, time
from pathlib import Path
import pandas as pd
import wiki_index as wi

BASE = Path(__file__).resolve().parent
CACHE = BASE / 'cache' / 'sp500_history.json'
CURRENT_CSV = BASE / 'sp500_current.csv'
DELISTED_CSV = BASE / 'sp500_delisted.csv'
TTL_DAYS = 7
SINCE = '2014-01-01'          # 剔除名单的起始日
URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'


def _parse_current(t0):
    """表0 -> [{ticker, security, sector, date_added}]"""
    rows = []
    for _, r in t0.iterrows():
        rows.append({
            'ticker': wi.norm(r['Symbol']),
            'security': str(r.get('Security', '')).strip(),
            'sector': str(r.get('GICS Sector', '')).strip(),
            'date_added': wi.iso(r.get('Date added', '')),
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
               if 'Symbol' in [str(c) for c in t.columns] and len(t) > 400), None)
    t1 = next((t for t in tabs
               if any('Removed' in str(c) for c in t.columns)), None)
    if t0 is None or t1 is None:
        raise RuntimeError('维基页面结构变了,找不到成分表或变更表')
    current = _parse_current(t0)
    changes = wi.parse_changes(t1)
    asof = time.strftime('%Y-%m-%d')
    if len(current) > 400:      # 抓取成功才写缓存,避免固化坏数据
        CACHE.parent.mkdir(exist_ok=True)
        json.dump({'current': current, 'changes': changes, 'asof': asof},
                  open(CACHE, 'w'), ensure_ascii=False)
    return current, changes, asof


def build(force=False):
    """抓取/读缓存,写出两张CSV。返回 (current, delisted, asof)。"""
    current, changes, asof = load_tables(force=force)
    delisted = wi.build_delisted(changes, SINCE)
    pd.DataFrame(current, columns=['ticker', 'security', 'sector', 'date_added']) \
        .to_csv(CURRENT_CSV, index=False)
    pd.DataFrame(delisted, columns=['ticker', 'security', 'date_added',
                                    'date_removed', 'reason']) \
        .to_csv(DELISTED_CSV, index=False)
    return current, delisted, asof


if __name__ == '__main__':
    force = '--force' in sys.argv
    current, delisted, asof = build(force=force)
    filled = sum(1 for d in delisted if d['date_added'])
    print(f"asof {asof}")
    print(f"当前成分 {len(current)} 只 -> {CURRENT_CSV.name}")
    print(f"{SINCE} 以来被剔除 {len(delisted)} 只 -> {DELISTED_CSV.name}"
          f"(其中 {filled} 只回填到纳入日,{len(delisted) - filled} 只纳入日早于日志起点留空)")
    print("抽样剔除记录:")
    for d in delisted[-5:]:
        print(f"  {d['ticker']:6} 入{d['date_added'] or '  ??  ':10} 出{d['date_removed']}  {d['reason'][:50]}")
