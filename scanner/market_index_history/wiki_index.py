#!/usr/bin/env python3
"""维基指数页面的共用抓取&解析工具。被 sp500_history.py / nasdaq100_history.py 共用。

S&P500 与 Nasdaq-100 的维基"List of ..."页面结构一致:
  - 一张当前成分表(各自列名不同,由各脚本自行解析);
  - 一张变更日志表(多级列头 Date / Added(Ticker,Security) / Removed(Ticker,Security) / Reason),此处统一解析。
"""
import io, urllib.request
import pandas as pd

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def norm(s):
    return str(s).replace('.', '-').strip().upper()


def iso(x):
    """把"June 22, 2026"这类日期解析成 ISO;解析不了返回空串。"""
    d = pd.to_datetime(x, errors='coerce')
    return '' if pd.isna(d) else d.strftime('%Y-%m-%d')


def fetch_tables(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
    return pd.read_html(io.StringIO(html))


def parse_changes(t):
    """变更表 -> 长表 [{date, action, ticker, security, reason}],按日期升序。action ∈ {'add','remove'}。"""
    df = t.copy()
    # 拍平多级列头:('Added','Ticker') -> 'Added Ticker'
    df.columns = [' '.join(str(x) for x in c).strip() if isinstance(c, tuple) else str(c)
                  for c in df.columns]

    def col(*cands):
        for c in df.columns:
            if any(k.lower() in c.lower() for k in cands):
                return c
        return None

    c_date = col('Effective Date', 'Date')
    c_add_t, c_add_s = col('Added Ticker'), col('Added Security')
    c_rem_t, c_rem_s = col('Removed Ticker'), col('Removed Security')
    c_reason = col('Reason')

    out = []
    for _, r in df.iterrows():
        date = iso(r.get(c_date, ''))
        if not date:
            continue
        reason = str(r.get(c_reason, '') or '').strip()
        at = r.get(c_add_t, '')
        if pd.notna(at) and str(at).strip():
            out.append({'date': date, 'action': 'add', 'ticker': norm(at),
                        'security': str(r.get(c_add_s, '') or '').strip(), 'reason': reason})
        rt = r.get(c_rem_t, '')
        if pd.notna(rt) and str(rt).strip():
            out.append({'date': date, 'action': 'remove', 'ticker': norm(rt),
                        'security': str(r.get(c_rem_s, '') or '').strip(), 'reason': reason})
    out.sort(key=lambda x: x['date'])
    return out


def latest_add_before(changes, ticker, before=None):
    """该 ticker 在 before 之前(before=None 则不限)最近一次纳入日;查不到返回 ''。"""
    ds = [c['date'] for c in changes
          if c['action'] == 'add' and c['ticker'] == ticker
          and (before is None or c['date'] < before)]
    return max(ds) if ds else ''


def member_asof(current, changes, ticker, date=None):
    """判断 ticker 在 date 当日是否为该指数成分(point-in-time)。

    从「当前成分集 current」出发,把 date 之后发生的变更逆向回滚(撤销加入/撤销移除),
    得到 date 当日的成分集。date=None 则直接返回当前成分。
    ⚠️只在 date 晚于变更日志起点时可靠;更早的日期日志不全,退化为"日志起点时的成分"。
    changes 需按日期升序(parse_changes 已保证)。"""
    t = norm(ticker)
    if not date:
        return t in current
    s = set(current)
    for c in reversed(changes):          # 从最新往回,滚到 date 为止
        if c['date'] <= date:
            break
        if c['action'] == 'add':
            s.discard(c['ticker'])       # 撤销"加入"
        elif c['action'] == 'remove':
            s.add(c['ticker'])           # 撤销"移除"
    return t in s


def build_delisted(changes, since):
    """从变更日志构造剔除名单:每条 remove(且 date>=since)回填其之前最近一次 add 作为 date_added。
    返回 [{ticker, security, date_added, date_removed, reason}],按剔除日升序。"""
    rows = []
    for c in changes:
        if c['action'] != 'remove' or c['date'] < since:
            continue
        rows.append({
            'ticker': c['ticker'],
            'security': c['security'],
            'date_added': latest_add_before(changes, c['ticker'], c['date']),
            'date_removed': c['date'],
            'reason': c['reason'],
        })
    rows.sort(key=lambda x: (x['date_removed'], x['ticker']))
    return rows
