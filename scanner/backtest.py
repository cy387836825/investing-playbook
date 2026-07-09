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


# 信号定义统一至 signals.py(唯一真源) —— 回测与实时扫描共用同一定义
from signals import sig_s2b, sig_s2a, sig_s1, sig_s1super, SIGNALS
from signals import s1_core as _s1_core  # 向后兼容别名
from signals import yoy as _yoy          # 统一至signals(去重)
from signals import pit_qseries as _pit_qseries  # 统一至signals(curation仍从此import)


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
    hz = [int(x) for x in a.horizons.split(",")]
    backtest_signals(anchors, hz, a.limit)   # 唯一回测入口(旧单/多锚点legacy已移除)
