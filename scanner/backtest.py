#!/usr/bin/env python3
"""
历史回测（point-in-time，免费数据版）
验证: 在过去某锚点日T,筛选器命中的股票,其后N个月的远期回报是否跑赢未命中/基准。

严谨性:
  ✅ 无前视偏差: 用EDGAR的'filed'字段,只采信 filed<=T 的财报数据重构信号
  ✅ 远期回报真实: yfinance历史价,T→T+window
  ⚠️ 幸存者偏差(无法消除): universe是今天≥5B的公司,已退市/跌出者缺失→回报被高估,结果需向下折扣
  ⚠️ universe偏差: 缺"当时小盘后来长成5B"的多倍股(最好的猎物),结果对S1/价值型更友好

信号(PIT重构):
  S2b: 最新季营收同比≥25% 且 > 上一季同比(加速),全部用filed<=T的数据
用法:
  python backtest.py --anchor 2023-06-30 --months 24 --limit 150
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
EDGAR_CACHE = CACHE / "edgar"
PX_CACHE = CACHE / "prices"
for _d in (EDGAR_CACHE, PX_CACHE):
    _d.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Personal investment research cy387836825@gmail.com"}
REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet", "SalesRevenueGoodsNet"]


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode())


def _cik_map():
    d = _get("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in d.values()}


def _fetch_facts(cik):
    """拉一次 companyfacts,返回原始 units 列表(含filed日期),供多锚点复用"""
    try:
        facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in REV_TAGS:
        units = gaap.get(tag, {}).get("units", {}).get("USD")
        if units:
            return units
    return None


def _companyfacts_cached(cik):
    """companyfacts原始JSON,磁盘缓存(历史申报不可变,下载一次永久复用)"""
    fp = EDGAR_CACHE / f"CIK{cik}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text())
        except Exception:
            pass
    try:
        facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception:
        return None
    try:
        fp.write_text(json.dumps(facts))
    except Exception:
        pass
    return facts


def _fetch_all(cik):
    """一次companyfacts提取 营收/净利/毛利 三组units(带磁盘缓存)"""
    facts = _companyfacts_cached(cik)
    if facts is None:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    rev = None
    for tag in REV_TAGS:
        u = gaap.get(tag, {}).get("units", {}).get("USD")
        if u:
            rev = u
            break
    ni = gaap.get("NetIncomeLoss", {}).get("units", {}).get("USD")
    gp = gaap.get("GrossProfit", {}).get("units", {}).get("USD")
    if rev is None and ni is None:
        return None
    return {"rev": rev, "ni": ni, "gp": gp}


def _pit_qseries(units, asof):
    """通用: filed<=asof 的季度序列(end→val),point-in-time。单季=75-100天区间"""
    if not units:
        return None
    q = {}
    for r in units:
        if "start" not in r or "end" not in r or "filed" not in r:
            continue
        if r["filed"] > asof:
            continue
        try:
            days = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
        except Exception:
            continue
        if 75 <= days <= 100:
            if r["end"] not in q or r["filed"] > q[r["end"]][1]:
                q[r["end"]] = (r["val"], r["filed"])
    if len(q) >= 6:
        s = pd.Series({k: v[0] for k, v in q.items()})
        s.index = pd.to_datetime(s.index)
        return s.sort_index(ascending=False)
    return None


def sig_s2b(f, asof):
    """营收同比≥25%且加速"""
    s = _pit_qseries(f.get("rev"), asof)
    y0, y1 = _yoy(s, 0), _yoy(s, 1)
    if y0 is None or y1 is None:
        return None
    return (y0 >= 0.25) and (y0 > y1)


def sig_s2a(f, asof):
    """首次盈利: 最新季净利>0 且 前4季≥3季≤0"""
    s = _pit_qseries(f.get("ni"), asof)
    if s is None or len(s) < 5:
        return None
    v = list(s.values)
    return v[0] > 0 and sum(1 for x in v[1:5] if x <= 0) >= 3


def _s1_core(f, asof):
    """返回(consec改善, ttm_gm, hist_gm, rev_yoy) 供S1/S1超判定"""
    rev = _pit_qseries(f.get("rev"), asof)
    gp = _pit_qseries(f.get("gp"), asof)
    if rev is None or gp is None or len(gp) < 8:
        return None
    gm = (gp / rev.reindex(gp.index)).dropna()
    if len(gm) < 8:
        return None
    vals = list(gm.values)  # 最新在前
    consec = 0
    for i in range(len(vals) - 1):
        if vals[i] > vals[i + 1]:
            consec += 1
        else:
            break
    ttm = gm.iloc[:4].mean()
    hist = gm.iloc[4:].mean()   # 更早季度的均值=历史基线
    ry = _yoy(rev, 0)
    return consec, ttm, hist, (ry if ry is not None else 0)


def sig_s1(f, asof):
    """周期反转: 毛利率连续≥2季改善 且 TTM<历史基线"""
    c = _s1_core(f, asof)
    if c is None:
        return None
    consec, ttm, hist, _ = c
    return consec >= 2 and ttm < hist


def sig_s1super(f, asof):
    """超级周期: 连续≥2季改善 且 TTM≥历史基线 且 营收加速≥40%"""
    c = _s1_core(f, asof)
    if c is None:
        return None
    consec, ttm, hist, ry = c
    return consec >= 2 and ttm >= hist and ry >= 0.4


SIGNALS = {"S1": sig_s1, "S1超": sig_s1super, "S2a": sig_s2a, "S2b": sig_s2b}


def _pit_from_units(units, asof):
    """从已拉取的units,按filed<=asof重构季度营收序列(point-in-time)"""
    q = {}
    for r in units:
        if "start" not in r or "end" not in r or "filed" not in r:
            continue
        if r["filed"] > asof:
            continue
        try:
            days = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
        except Exception:
            continue
        if 75 <= days <= 100:
            if r["end"] not in q or r["filed"] > q[r["end"]][1]:
                q[r["end"]] = (r["val"], r["filed"])
    if len(q) >= 6:
        s = pd.Series({k: v[0] for k, v in q.items()})
        s.index = pd.to_datetime(s.index)
        return s.sort_index(ascending=False)
    return None


def _pit_quarterly_rev(cik, asof):
    """(保留单锚点用) filed<=asof 的季度营收序列"""
    try:
        facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in REV_TAGS:
        units = gaap.get(tag, {}).get("units", {}).get("USD")
        if not units:
            continue
        q = {}
        for r in units:
            if "start" not in r or "end" not in r or "filed" not in r:
                continue
            if r["filed"] > asof:            # 关键:剔除T之后才申报的数据(防前视)
                continue
            try:
                days = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
            except Exception:
                continue
            if 75 <= days <= 100:            # 单季
                # 同一end可能被多次申报(修正),保留filed<=asof中最新filed的
                if r["end"] not in q or r["filed"] > q[r["end"]][1]:
                    q[r["end"]] = (r["val"], r["filed"])
        if len(q) >= 6:
            s = pd.Series({k: v[0] for k, v in q.items()})
            s.index = pd.to_datetime(s.index)
            return s.sort_index(ascending=False)
    return None


def _yoy(s, i):
    if s is None or len(s) <= i:
        return None
    end = s.index[i]
    base = s[(s.index >= end - pd.Timedelta(days=380)) & (s.index <= end - pd.Timedelta(days=350))]
    if base.empty or base.iloc[0] == 0:
        return None
    return float(s.iloc[i] / base.iloc[0] - 1)


def _price_on(tk, date, window=15):
    """取date附近的收盘价"""
    import yfinance as yf
    d = pd.Timestamp(date)
    try:
        h = yf.Ticker(tk).history(start=(d - pd.Timedelta(days=window)).strftime("%Y-%m-%d"),
                                  end=(d + pd.Timedelta(days=window)).strftime("%Y-%m-%d"))
        if h.empty:
            return None
        h.index = h.index.tz_localize(None)
        i = (h.index - d).to_series().abs().values.argmin()
        return float(h["Close"].iloc[i])
    except Exception:
        return None


def _price_hist(tk, start, end):
    """全区间日线Series,磁盘缓存(缓存全历史,按需切片;历史价不可变)。
    缓存策略: 每票存一次尽量宽的历史(2015→今),后续任意start/end从盘上切。"""
    import yfinance as yf
    fp = PX_CACHE / f"{tk}.csv"
    ser = None
    if fp.exists():
        try:
            df = pd.read_csv(fp, index_col=0)
            if not df.empty:
                ser = df.iloc[:, 0]
                idx = pd.to_datetime(ser.index, errors="coerce")
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_convert(None)
                ser.index = idx
                ser = ser[ser.index.notna()]
                ser = pd.to_numeric(ser, errors="coerce").dropna()
                if ser.empty:
                    ser = None
        except Exception:
            ser = None
    if ser is None:
        try:
            h = yf.Ticker(tk).history(start="2015-01-01")
            if h.empty:
                # 存空标记避免反复重试
                fp.write_text("date,close\n")
                return None
            h.index = h.index.tz_localize(None)
            ser = h["Close"]
            ser.to_csv(fp, header=["close"])
        except Exception:
            return None
    if ser is None or ser.empty:
        return None
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    sub = ser[(ser.index >= s) & (ser.index <= e)]
    return sub if not sub.empty else None


def _px_from_hist(h, date, window=15):
    if h is None:
        return None
    d = pd.Timestamp(date)
    sub = h[(h.index >= d - pd.Timedelta(days=window)) & (h.index <= d + pd.Timedelta(days=window))]
    if sub.empty:
        return None
    i = (sub.index - d).to_series().abs().values.argmin()
    return float(sub.iloc[i])


def backtest_multi(anchors, months, limit):
    """全universe多锚点: 每只股票EDGAR+价格各拉一次,对所有锚点复用切片"""
    uni = pd.read_csv(BASE / "universe.csv")["ticker"].astype(str).tolist()[:limit]
    ciks = _cik_map()
    fwds = {a: (pd.Timestamp(a) + pd.DateOffset(months=months)).strftime("%Y-%m-%d") for a in anchors}
    hmin = (pd.Timestamp(min(anchors)) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    hmax = (pd.Timestamp(max(fwds.values())) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    print(f"全universe多锚点: 样本≤{len(uni)}  锚点{anchors}  远期+{months}m")
    print(f"每股EDGAR+价格各拉一次(区间{hmin}~{hmax}),对所有锚点复用\n")
    per = {a: [] for a in anchors}          # anchor → list of (hit, ret)
    n_ok = 0
    for i, tk in enumerate(uni, 1):
        cik = ciks.get(tk.upper())
        if not cik:
            continue
        units = _fetch_facts(cik)
        if not units:
            continue
        h = _price_hist(tk, hmin, hmax)
        if h is None:
            continue
        used = False
        for a in anchors:
            s = _pit_from_units(units, a)
            if s is None:
                continue
            y0, y1 = _yoy(s, 0), _yoy(s, 1)
            if y0 is None or y1 is None:
                continue
            p0, p1 = _px_from_hist(h, a), _px_from_hist(h, fwds[a])
            if not p0 or not p1:
                continue
            per[a].append((tk, (y0 >= 0.25) and (y0 > y1), (p1 / p0 - 1) * 100, y0))
            used = True
        if used:
            n_ok += 1
        if i % 50 == 0:
            print(f"  {i}/{len(uni)} 有效{n_ok}只")
        time.sleep(0.1)

    # SPY基准(每锚点)
    spy_h = _price_hist("SPY", hmin, hmax)
    summ = []
    for a in anchors:
        rows = per[a]
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["ticker", "hit", "ret_pct", "yoy"])
        df.to_csv(BASE / f"bt_{a}_{months}m.csv", index=False)
        hits, miss = df[df["hit"]], df[~df["hit"]]
        s0, s1 = _px_from_hist(spy_h, a), _px_from_hist(spy_h, fwds[a])
        spy = (s1 / s0 - 1) * 100 if s0 and s1 else float("nan")
        if hits.empty:
            continue
        hmed, mmed = hits["ret_pct"].median(), miss["ret_pct"].median()
        summ.append({"anchor": a, "样本": len(df), "命中": len(hits),
                     "命中中位%": round(hmed), "命中均值%": round(hits["ret_pct"].mean()),
                     "命中胜率%": round((hits["ret_pct"] > 0).mean() * 100),
                     "未命中中位%": round(mmed), "SPY%": round(spy),
                     "超额vs未命中pp": round(hmed - mmed), "超额vsSPYpp": round(hmed - spy)})
    if summ:
        sm = pd.DataFrame(summ)
        print("\n\n========= 全universe三锚点回测 (中位数口径) =========")
        print(sm.to_string(index=False))
        sm.to_csv(BASE / "backtest_summary.csv", index=False)
        print("\n判定: 超额vs未命中 若三个不同市场环境下都为正 → S2b有稳健预测力")
    return summ


def backtest_signals(anchors, horizons, limit):
    """全信号×全锚点×全horizon: 每股EDGAR+价格各拉一次,复用。
    输出每个(信号,锚点,horizon)的 命中中位 vs 未命中中位 vs SPY。"""
    uni = pd.read_csv(BASE / "universe.csv")["ticker"].astype(str).tolist()[:limit]
    ciks = _cik_map()
    maxh = max(horizons)
    hmin = (pd.Timestamp(min(anchors)) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    hmax = (pd.Timestamp(max(anchors)) + pd.DateOffset(months=maxh) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    print(f"全信号回测: 样本≤{len(uni)} 信号{list(SIGNALS)} 锚点{anchors} horizon{horizons}月", flush=True)
    print(f"价格区间{hmin}~{hmax}, 每股EDGAR+价格各拉一次\n", flush=True)
    # recs[(sig,anchor,h)] = list of (hit, ret)
    recs = {}
    perrows = []   # per-ticker: 用于召回率分析(哪些牛股被哪些信号抓到)
    n_ok = 0
    for i, tk in enumerate(uni, 1):
        cik = ciks.get(tk.upper())
        if not cik:
            continue
        f = _fetch_all(cik)
        if f is None:
            continue
        h = _price_hist(tk, hmin, hmax)
        if h is None:
            continue
        used = False
        for a in anchors:
            sigvals = {name: fn(f, a) for name, fn in SIGNALS.items()}
            if all(v is None for v in sigvals.values()):
                continue
            p0 = _px_from_hist(h, a)
            if not p0:
                continue
            rets = {}
            for hz in horizons:
                fwd = (pd.Timestamp(a) + pd.DateOffset(months=hz)).strftime("%Y-%m-%d")
                p1 = _px_from_hist(h, fwd)
                if not p1:
                    continue
                ret = (p1 / p0 - 1) * 100
                rets[hz] = ret
                for name, v in sigvals.items():
                    if v is None:
                        continue
                    recs.setdefault((name, a, hz), []).append((v, ret))
                used = True
            if rets:
                row = {"ticker": tk, "anchor": a}
                for name, v in sigvals.items():
                    row[name] = "" if v is None else int(bool(v))
                row["any_hit"] = int(any(bool(v) for v in sigvals.values() if v is not None))
                for hz in horizons:
                    row[f"ret{hz}"] = round(rets[hz]) if hz in rets else ""
                perrows.append(row)
        if used:
            n_ok += 1
        if i % 100 == 0:
            print(f"  {i}/{len(uni)} 有效{n_ok}只", flush=True)
        time.sleep(0.1)
    pd.DataFrame(perrows).to_csv(BASE / "backtest_perticker.csv", index=False)
    print(f"per-ticker明细 → backtest_perticker.csv ({len(perrows)}行)", flush=True)

    spy_h = _price_hist("SPY", hmin, hmax)
    rows = []
    for (name, a, hz), lst in sorted(recs.items()):
        df = pd.DataFrame(lst, columns=["hit", "ret"])
        hits, miss = df[df["hit"]], df[~df["hit"]]
        if len(hits) < 5:   # 命中太少无意义,跳过
            continue
        fwd = (pd.Timestamp(a) + pd.DateOffset(months=hz)).strftime("%Y-%m-%d")
        s0, s1 = _px_from_hist(spy_h, a), _px_from_hist(spy_h, fwd)
        spy = round((s1 / s0 - 1) * 100) if s0 and s1 else float("nan")
        hmed = round(hits["ret"].median())
        mmed = round(miss["ret"].median()) if len(miss) else float("nan")
        rows.append({"信号": name, "锚点": a, "月": hz, "命中": len(hits),
                     "命中中位%": hmed, "未命中中位%": mmed, "SPY%": spy,
                     "超额vs未命中": hmed - mmed, "超额vsSPY": hmed - spy})
    out = pd.DataFrame(rows)
    if out.empty:
        print("\n无足够命中(每组需≥5),扩大样本或换锚点", flush=True)
        return out
    out.to_csv(BASE / "backtest_signals.csv", index=False)
    print("\n\n========= 全信号回测 (中位数口径) =========", flush=True)
    for name in SIGNALS:
        sub = out[out["信号"] == name]
        if len(sub):
            print(f"\n--- {name} ---", flush=True)
            print(sub.drop(columns="信号").to_string(index=False), flush=True)
    print("\n判定: 某信号的'超额vs未命中'在多锚点多horizon下一致为正 → 该信号有稳健edge", flush=True)
    return out


def backtest(anchor, months, limit):
    fwd = (pd.Timestamp(anchor) + pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    uni = pd.read_csv(BASE / "universe.csv")["ticker"].astype(str).tolist()[:limit]
    ciks = _cik_map()
    print(f"锚点T={anchor}  远期={fwd}({months}月)  样本={len(uni)}")
    print("⚠️ 结果含幸存者偏差(今日≥5B的幸存者),真实值应向下折扣\n")
    rows = []
    for i, tk in enumerate(uni, 1):
        cik = ciks.get(tk.upper())
        if not cik:
            continue
        s = _pit_quarterly_rev(cik, anchor)
        if s is None:
            continue
        y0, y1 = _yoy(s, 0), _yoy(s, 1)
        if y0 is None or y1 is None:
            continue
        hit = (y0 >= 0.25) and (y0 > y1)          # S2b信号(PIT)
        p0 = _price_on(tk, anchor)
        p1 = _price_on(tk, fwd)
        if not p0 or not p1:
            continue
        rows.append({"ticker": tk, "hit": hit, "yoy": round(y0, 2),
                     "ret_pct": round((p1 / p0 - 1) * 100, 1)})
        if i % 25 == 0:
            print(f"  {i}/{len(uni)} 已算{len(rows)}只 ... {tk}")
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    if df.empty:
        print("无有效样本")
        return None
    df.to_csv(BASE / f"backtest_{anchor}_{months}m.csv", index=False)
    hits, miss = df[df["hit"]], df[~df["hit"]]
    spy0, spy1 = _price_on("SPY", anchor), _price_on("SPY", fwd)
    spy_ret = (spy1 / spy0 - 1) * 100 if spy0 and spy1 else float("nan")
    # 用中位数为主(抗单只怪兽),均值辅
    hmed, hmean, hn = hits["ret_pct"].median(), hits["ret_pct"].mean(), len(hits)
    mmed, mmean = miss["ret_pct"].median(), miss["ret_pct"].mean()
    print(f"\n=== {anchor} → +{months}m (样本{len(df)}, 命中{hn}) ===")
    print(f"S2b命中: 中位{hmed:.0f}% 均值{hmean:.0f}% 胜率{(hits['ret_pct']>0).mean()*100:.0f}%")
    print(f"未命中 : 中位{mmed:.0f}% 均值{mmean:.0f}%")
    print(f"SPY    : {spy_ret:.0f}%")
    print(f"命中vs未命中(中位): {hmed-mmed:+.0f}pp | 命中vs SPY(中位): {hmed-spy_ret:+.0f}pp")
    return {"anchor": anchor, "n": len(df), "hits": hn, "h_med": round(hmed, 0),
            "h_mean": round(hmean, 0), "h_win": round((hits['ret_pct'] > 0).mean() * 100),
            "m_med": round(mmed, 0), "spy": round(spy_ret, 0),
            "edge_vs_miss": round(hmed - mmed, 0), "edge_vs_spy": round(hmed - spy_ret, 0)}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--anchor", default="2023-06-30")
    p.add_argument("--anchors", type=str, help="逗号分隔多锚点,覆盖--anchor")
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--limit", type=int, default=99999)
    p.add_argument("--signals", action="store_true", help="全信号(S1/S1超/S2a/S2b)模式")
    p.add_argument("--horizons", type=str, default="12,36", help="逗号分隔的horizon月数")
    a = p.parse_args()
    anchors = a.anchors.split(",") if a.anchors else [a.anchor]
    if a.signals:
        hz = [int(x) for x in a.horizons.split(",")]
        backtest_signals(anchors, hz, a.limit)          # 全信号×多锚点×多horizon
    elif len(anchors) > 1:
        backtest_multi(anchors, a.months, a.limit)
    else:
        backtest(anchors[0], a.months, a.limit)
