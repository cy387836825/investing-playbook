#!/usr/bin/env python3
"""抓取并缓存 S&P 500 / Nasdaq-100 成分股(维基百科),供winners/funnel标注指数归属。
⚠️免费数据只拿得到【当前】成分,拿不到触发时的point-in-time成分。故指数标注是"截至asof日的当前成分",
   不代表信号触发当时就在指数内(很多是触发后成长进指数的)。缓存7天。"""
import io, json, time, urllib.request
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
CACHE = BASE / 'cache' / 'index_membership.json'
TTL_DAYS = 7


def _norm(s):
    return str(s).replace('.', '-').strip().upper()


_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def _tables(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
    return pd.read_html(io.StringIO(html))


def _col(df, names):
    cols = {str(c): c for c in df.columns}
    for n in names:
        if n in cols:
            return cols[n]
    return None


def _fetch_sp500():
    for df in _tables('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'):
        c = _col(df, ('Symbol', 'Ticker'))
        if c is not None and len(df) > 400:      # 成分表~503行,避开页面上的小表
            return {_norm(s) for s in df[c].dropna()}
    return set()


def _fetch_ndx():
    # 维基Nasdaq-100成分现为导航框(navbox),read_html取不到ticker;改用slickcharts(表0含Symbol列)
    for df in _tables('https://www.slickcharts.com/nasdaq100'):
        c = _col(df, ('Symbol', 'Ticker'))
        if c is not None and 90 <= len(df) <= 110:   # 成分表~100行
            return {_norm(s) for s in df[c].dropna()}
    return set()


def membership(force=False):
    """返回 (sp500:set, ndx:set, asof:str)。命中缓存则不联网。"""
    if CACHE.exists() and not force:
        if time.time() - CACHE.stat().st_mtime < TTL_DAYS * 86400:
            d = json.load(open(CACHE))
            return set(d['sp500']), set(d['ndx']), d.get('asof', '')
    sp, nd = _fetch_sp500(), _fetch_ndx()
    asof = time.strftime('%Y-%m-%d')
    if sp and nd:      # 抓取成功才写缓存,避免把空集固化
        CACHE.parent.mkdir(exist_ok=True)
        json.dump({'sp500': sorted(sp), 'ndx': sorted(nd), 'asof': asof},
                  open(CACHE, 'w'))
    return sp, nd, asof


if __name__ == '__main__':
    sp, nd, asof = membership(force=True)
    print(f"asof {asof}: S&P500 {len(sp)}只, Nasdaq-100 {len(nd)}只")
    print("重叠(既SP500又N100):", len(sp & nd))
    for t in ['NVDA', 'AAPL', 'VRT', 'PLTR', 'AAOI', 'QBTS']:
        print(f"  {t}: SP500={t in sp} N100={t in nd}")
