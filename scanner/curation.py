#!/usr/bin/env python3
"""
Curation规则回测 —— 验证"深挖的规则化filter"能否在筛选器命中的候选里提升精度。
测的不是人工判断(不可回测),是判断所编码的可机械化规则:
  ①估值闸门(L17): PIT P/S过高=剔除  ②盈利质量: TTM净利>0  ③非一次性(L5): ni不跳变
方法: 对'任一基本面信号命中'的候选,在锚点T按PIT数据打curation标,
      比较 命中全体 vs 命中且过curation 的远期回报分布(中位/胜率/大牛股捕获/暴雷率)。
纯PIT: 估值用 price(T)×shares(filed<=T) / TTM_rev(filed<=T),无前视。
"""
import time
import pandas as pd
from pathlib import Path
from backtest import (_companyfacts_cached, _cik_map, _pit_from_units, _pit_qseries,
                      _price_hist, _px_from_hist, REV_TAGS)

BASE = Path(__file__).resolve().parent
ANCHORS = ["2021-06-30", "2022-06-30", "2023-06-30"]
SHARE_TAGS = ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding",
              "WeightedAverageNumberOfSharesOutstandingBasic", "EntityCommonStockSharesOutstanding"]


def _units(facts, tag):
    return facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD") \
        or facts.get("facts", {}).get("dei", {}).get(tag, {}).get("units", {}).get("shares")


def _pit_latest(facts, tags, asof):
    """某标签 filed<=asof 的最新值(用于shares等瞬时量)"""
    for t in tags:
        for ns in ("us-gaap", "dei"):
            arr = facts.get("facts", {}).get(ns, {}).get(t, {}).get("units", {})
            for unit, rows in arr.items():
                cand = [(r["end"], r["val"], r["filed"]) for r in rows
                        if "end" in r and "filed" in r and r["filed"] <= asof]
                if cand:
                    cand.sort(key=lambda x: (x[0], x[2]))
                    return cand[-1][1]
    return None


def _ttm(units, asof):
    s = _pit_qseries(units, asof)
    if s is None or len(s) < 4:
        return None
    return float(s.iloc[:4].sum())


def _lumpy(units, asof):
    s = _pit_qseries(units, asof)
    if s is None or len(s) < 4:
        return False
    v = list(s.iloc[:4].values)
    signs = [1 if x > 0 else -1 for x in v]
    flips = sum(1 for i in range(3) if signs[i] != signs[i + 1])
    return flips >= 2


def run():
    per = pd.read_csv(BASE / "backtest_perticker.csv")
    flagged = per[pd.to_numeric(per["any_hit"], errors="coerce").fillna(0) == 1].copy()
    tickers = sorted(flagged["ticker"].unique())
    ciks = _cik_map()
    print(f"筛选器命中候选: {len(flagged)}条 / {len(tickers)}只  拉PIT估值+质量(缓存)", flush=True)

    hmin, hmax = "2020-06-01", "2026-07-30"
    recs = []
    for i, tk in enumerate(tickers, 1):
        cik = ciks.get(tk.upper())
        if not cik:
            continue
        facts = _companyfacts_cached(cik)
        if facts is None:
            continue
        rev_u = None
        for tg in REV_TAGS:
            rev_u = _units(facts, tg)
            if rev_u:
                break
        ni_u = _units(facts, "NetIncomeLoss")
        h = _price_hist(tk, hmin, hmax)
        for a in ANCHORS:
            sub = flagged[(flagged["ticker"] == tk) & (flagged["anchor"] == a)]
            if sub.empty:
                continue
            px = _px_from_hist(h, a) if h is not None else None
            sh = _pit_latest(facts, SHARE_TAGS, a)
            ttm_rev = _ttm(rev_u, a) if rev_u else None
            ttm_ni = _ttm(ni_u, a) if ni_u else None
            ps = (px * sh / ttm_rev) if (px and sh and ttm_rev and ttm_rev > 0) else None
            profitable = (ttm_ni is not None and ttm_ni > 0)
            lumpy = _lumpy(ni_u, a) if ni_u else False
            # curation规则(全部通过才算"过curation")
            val_ok = (ps is None) or (ps <= 12)      # 估值不极端(P/S≤12);缺失不因此剔除
            pass_cur = val_ok and profitable and (not lumpy)
            for hz in (12, 36):
                r = sub.iloc[0].get(f"ret{hz}")
                if pd.isna(r) or r == "":
                    continue
                recs.append({"ticker": tk, "anchor": a, "hz": hz, "ret": float(r),
                             "ps": round(ps, 1) if ps else None, "profitable": profitable,
                             "lumpy": lumpy, "pass_cur": pass_cur})
        if i % 50 == 0:
            print(f"  {i}/{len(tickers)}", flush=True)
        time.sleep(0.1)

    df = pd.DataFrame(recs)
    df.to_csv(BASE / "curation_perticker.csv", index=False)
    print("\n\n========= Curation精度检验 (命中全体 vs 命中且过curation) =========", flush=True)
    spy = {("2021-06-30", 12): -11, ("2021-06-30", 36): 33, ("2022-06-30", 12): 19,
           ("2022-06-30", 36): 71, ("2023-06-30", 12): 25, ("2023-06-30", 36): 75}
    for hz in (12, 36):
        print(f"\n--- {hz}月 ---", flush=True)
        for a in ANCHORS:
            d = df[(df["anchor"] == a) & (df["hz"] == hz)]
            if len(d) < 20:
                continue
            allm = d["ret"].median()
            cur = d[d["pass_cur"]]
            curm = cur["ret"].median() if len(cur) else float("nan")
            s = spy[(a, hz)]
            # 精度指标: 中位, 跑赢SPY比例, 暴雷率(<-30%), 大牛(>100%)比例
            def stat(x):
                return (round(x["ret"].median()), round((x["ret"] > s).mean() * 100),
                        round((x["ret"] < -30).mean() * 100), round((x["ret"] > 100).mean() * 100), len(x))
            am, aw, ab, ag, an = stat(d)
            cm, cw, cb, cg, cn = stat(cur) if len(cur) else (float('nan'),)*5
            print(f"{a}: 命中全体(n{an}) 中位{am}% 胜率{aw}% 暴雷{ab}% 大牛{ag}%  |  "
                  f"过curation(n{cn}) 中位{cm}% 胜率{cw}% 暴雷{cb}% 大牛{cg}%", flush=True)
    print("\n判定: curated组 中位/胜率更高 且 暴雷率更低 → 规则化curation提升精度", flush=True)


if __name__ == "__main__":
    run()
