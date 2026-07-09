#!/usr/bin/env python3
"""
动量领先指标回测 —— 验证"价格动量"是否比滞后的基本面信号更能捕捉暴涨。
纯领先: 锚点T的信号只用 T 之前的价格(6个月动量),不含任何未来/基本面数据。

对比对象: backtest_perticker.csv 里四个基本面信号(S1/S1超/S2a/S2b)的召回率25%。
问题: 在T按6月动量分档,高动量档 ①远期回报是否更高 ②对前10大牛股的召回是否>25%
用法: python momentum.py --anchors 2021-06-30,2022-06-30,2023-06-30 --horizons 12,36
"""
import argparse
import time
import pandas as pd
from pathlib import Path
from backtest import _price_hist, _px_from_hist   # 复用带缓存的价格函数

BASE = Path(__file__).resolve().parent


def run(anchors, horizons):
    uni = pd.read_csv(BASE / "universe.csv")["ticker"].astype(str).tolist()
    maxh = max(horizons)
    hmin = (pd.Timestamp(min(anchors)) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")  # 需锚点前1年
    hmax = (pd.Timestamp(max(anchors)) + pd.DateOffset(months=maxh) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    print(f"动量回测: 样本≤{len(uni)} 锚点{anchors} horizon{horizons}", flush=True)
    rows = []
    for i, tk in enumerate(uni, 1):
        h = _price_hist(tk, hmin, hmax)     # 缓存: 首次拉,之后读盘
        if h is None or len(h) < 130:
            continue
        for a in anchors:
            pT = _px_from_hist(h, a)
            pPrev = _px_from_hist(h, (pd.Timestamp(a) - pd.Timedelta(days=182)).strftime("%Y-%m-%d"))
            if not pT or not pPrev:
                continue
            mom6 = pT / pPrev - 1                       # 6月动量(纯领先)
            row = {"ticker": tk, "anchor": a, "mom6": round(mom6, 3)}
            for hz in horizons:
                p1 = _px_from_hist(h, (pd.Timestamp(a) + pd.DateOffset(months=hz)).strftime("%Y-%m-%d"))
                row[f"ret{hz}"] = round((p1 / pT - 1) * 100) if p1 else None
            rows.append(row)
        if i % 200 == 0:
            print(f"  {i}/{len(uni)} 有效{len(rows)}", flush=True)
        time.sleep(0.05)
    df = pd.DataFrame(rows)
    df.to_csv(BASE / "momentum_perticker.csv", index=False)

    # 合并基本面信号标记
    try:
        fund = pd.read_csv(BASE / "backtest_perticker.csv")[["ticker", "anchor", "any_hit"]]
        df = df.merge(fund, on=["ticker", "anchor"], how="left")
    except Exception:
        df["any_hit"] = None

    print("\n\n========= 动量回测结果 =========", flush=True)
    spy = _price_hist("SPY", hmin, hmax)
    for a in anchors:
        for hz in horizons:
            sub = df[(df["anchor"] == a) & df[f"ret{hz}"].notna()].copy()
            if len(sub) < 50:
                continue
            sub["r"] = pd.to_numeric(sub[f"ret{hz}"], errors="coerce")
            sub = sub.dropna(subset=["r"])
            # 按动量5档
            sub["q"] = pd.qcut(sub["mom6"], 5, labels=["Q1最低", "Q2", "Q3", "Q4", "Q5最高"], duplicates="drop")
            s0, s1 = _px_from_hist(spy, a), _px_from_hist(spy, (pd.Timestamp(a) + pd.DateOffset(months=hz)).strftime("%Y-%m-%d"))
            spyr = round((s1 / s0 - 1) * 100) if s0 and s1 else float("nan")
            qmed = sub.groupby("q", observed=True)["r"].median().round()
            # 前10大牛股召回: 高动量Q5 vs 基本面any_hit
            top = sub.sort_values("r", ascending=False).head(10)
            mom_recall = int((top["q"] == "Q5最高").sum())
            fund_recall = int(pd.to_numeric(top["any_hit"], errors="coerce").fillna(0).sum())
            print(f"\n--- {a} / {hz}月 (样本{len(sub)}, SPY {spyr}%) ---", flush=True)
            print(f"  动量5档远期中位%: {dict(qmed)}", flush=True)
            print(f"  前10大牛股召回: 高动量Q5抓到 {mom_recall}/10  vs  四基本面信号抓到 {fund_recall}/10", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--anchors", default="2021-06-30,2022-06-30,2023-06-30")
    p.add_argument("--horizons", default="12,36")
    a = p.parse_args()
    run(a.anchors.split(","), [int(x) for x in a.horizons.split(",")])
