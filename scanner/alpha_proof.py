#!/usr/bin/env python3
"""
高精度子集验证（alpha proof）—— 在财报次日入场的事件级回测上，找"高收益+低风险+跨年份稳健"的条件组合。

背景: backtest-findings.md 已证明裸信号平均无alpha(胜率~40%)、curation=风控。
本脚本回答用户目标的最后一问: 是否存在一个**规则化、可复制**的严格子集,
其事件级12月超额(vs同期SPY)跨入场年份一致为正、胜率高、暴雷率低——宁缺毋滥。

口径(比 earnings_entry.py 的"持有至今/峰值"更严谨):
  - 固定horizon: 入场次日收盘 → 6/12/24月后最近交易日收盘(±15天容忍)
  - 超额 = 个股区间回报 - 同区间SPY回报(逐事件对齐,消灭"持有至今"的时点偏差)
  - 纯PIT闸门: profitable/lumpy/val_ok 全部用 filed<=财报日 的EDGAR数据重算
  - 去重: first12m = 该票365天内首次触发(可复制的"持有中不加仓"规则)
偏差声明: universe为当前存续公司(幸存者偏差,绝对回报高估);逐事件SPY超额部分缓解但不消除。
输出: alpha_proof.csv (事件级明细,供切片分析)
"""
import json
import time
import pandas as pd
from pathlib import Path
from backtest import _companyfacts_cached, _cik_map, REV_TAGS
from curation import _units, _pit_shares, _ttm, _lumpy
from signals import pit_qseries, yoy

BASE = Path(__file__).resolve().parent
PX_CACHE = BASE / "cache" / "prices"
HORIZONS = (6, 12, 24)
DATA_END = pd.Timestamp("2026-07-01")   # 价格缓存的可靠右端


def _load_px(tk):
    fp = PX_CACHE / f"{tk}.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp, index_col=0)
        if df.empty:
            return None
        s = df.iloc[:, 0]
        idx = pd.to_datetime(s.index, errors="coerce")
        s.index = idx
        s = s[s.index.notna()]
        return pd.to_numeric(s, errors="coerce").dropna().sort_index()
    except Exception:
        return None


def _px_near(h, date, tol=15):
    d = pd.Timestamp(date)
    sub = h[(h.index >= d - pd.Timedelta(days=tol)) & (h.index <= d + pd.Timedelta(days=tol))]
    if sub.empty:
        return None
    i = (sub.index - d).to_series().abs().values.argmin()
    return float(sub.iloc[i])


def cap_tier(m):
    if m is None or m != m or m <= 0:
        return ""
    for thr, code in [(200, "mega"), (10, "large"), (2, "mid"), (0.3, "small"), (0.05, "micro")]:
        if m >= thr:
            return code
    return "nano"


def run():
    ev = pd.read_csv(BASE / "earnings_entry.csv")
    uni = pd.read_csv(BASE / "universe.csv").set_index("ticker")
    ciks = _cik_map()
    spy = _load_px("SPY")
    print(f"事件 {len(ev)} 条 / {ev.ticker.nunique()} 票", flush=True)

    rows = []
    t0 = time.time()
    for n, (tk, g) in enumerate(ev.groupby("ticker"), 1):
        h = _load_px(tk)
        if h is None:
            continue
        cik = ciks.get(str(tk).upper())
        facts = _companyfacts_cached(cik) if cik else None
        rev_u = ni_u = None
        if facts:
            for tg in REV_TAGS:
                rev_u = _units(facts, tg)
                if rev_u:
                    break
            ni_u = _units(facts, "NetIncomeLoss")
        sec = uni["sector"].get(tk, "")
        ind = uni["industry"].get(tk, "")
        last_entry = None   # 365天去重
        for _, r in g.sort_values("earn_date").iterrows():
            F = pd.Timestamp(r["earn_date"])
            fut = h[h.index > F]
            if fut.empty:
                continue
            d0, p0 = fut.index[0], float(fut.iloc[0])
            first12 = last_entry is None or (d0 - last_entry).days >= 365
            if first12:
                last_entry = d0
            # PIT闸门
            asof = r["earn_date"]
            ttm_ni = _ttm(ni_u, asof) if ni_u else None
            profitable = ttm_ni is not None and ttm_ni > 0
            lumpy = _lumpy(ni_u, asof) if ni_u else False
            ttm_rev = _ttm(rev_u, asof) if rev_u else None
            sh = _pit_shares(facts, asof) if facts else None
            mcap = p0 * sh / 1e9 if sh else None
            gr = yoy(pit_qseries(rev_u, asof), 0) if rev_u else None
            ps = (mcap * 1e9 / ttm_rev) if (mcap and ttm_rev and ttm_rev > 0) else None
            pe = (mcap * 1e9 / ttm_ni) if (mcap and ttm_ni and ttm_ni > 0) else None
            if profitable and pe:
                peg = pe / (gr * 100) if (gr and gr > 0) else None
                val_ok = (peg <= 3) if peg is not None else (pe <= 50)
            elif ps:
                val_ok = ps <= 15
            else:
                val_ok = True
            row = {"ticker": tk, "earn_date": r["earn_date"], "sig": r["sig"],
                   "entry_date": str(d0.date()), "entry": round(p0, 2),
                   "first12": first12, "mcap_pit": round(mcap, 3) if mcap else None,
                   "tier": cap_tier(mcap), "sector": sec, "industry": ind,
                   "profitable": profitable, "lumpy": lumpy, "val_ok": val_ok,
                   "rev_yoy": round(gr, 3) if gr is not None else None,
                   "pe": round(pe, 1) if pe else None, "ps": round(ps, 1) if ps else None}
            for hz in HORIZONS:
                tgt = d0 + pd.DateOffset(months=hz)
                if tgt > DATA_END:
                    row[f"ret{hz}"] = None
                    row[f"xs{hz}"] = None
                    continue
                p1 = _px_near(h, tgt)
                s0, s1 = _px_near(spy, d0), _px_near(spy, tgt)
                if p1 is None or not s0 or not s1:
                    row[f"ret{hz}"] = None
                    row[f"xs{hz}"] = None
                    continue
                row[f"ret{hz}"] = round(p1 / p0 - 1, 4)
                row[f"xs{hz}"] = round((p1 / p0 - 1) - (s1 / s0 - 1), 4)
            rows.append(row)
        if n % 300 == 0:
            print(f"  {n} 票 / {len(rows)} 事件  {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(BASE / "alpha_proof.csv", index=False)
    print(f"→ alpha_proof.csv  {len(df)} 事件", flush=True)


def analyze():
    """规范切片输出(报告引用的所有数字由此产生,可复现)"""
    df = pd.read_csv(BASE / "alpha_proof.csv")
    df["year"] = pd.to_datetime(df.entry_date).dt.year
    for s in ("S1", "S1超", "S2a", "S2b"):
        df[f"has_{s}"] = df.sig.str.split("+").apply(lambda x, s=s: s in x)
    f = df[df.first12].copy()

    def cur(r):
        ok = True
        if r.has_S1 or r["has_S1超"]:
            ok = ok and (not r.lumpy)
        if r["has_S1超"]:
            ok = ok and r.profitable
        if r.has_S2a:
            ok = ok and r.profitable
        if r.has_S2b:
            ok = ok and r.val_ok
        return ok
    f["cur"] = f.apply(cur, axis=1)

    def stat(d, label, hz=12):
        x = d[f"xs{hz}"].dropna()
        r = d[f"ret{hz}"].dropna()
        if len(x) < 5:
            return None
        return {"组": label, "n": len(x), "中位超额pp": round(x.median() * 100),
                "均值超额pp": round(x.mean() * 100), "胜率vsSPY%": round((x > 0).mean() * 100),
                "中位绝对%": round(r.median() * 100), "暴雷%(<-30)": round((r < -0.3).mean() * 100),
                "重雷%(<-50)": round((r < -0.5).mean() * 100), "大牛%(>100)": round((r > 1.0).mean() * 100)}

    def show(rows, title):
        rows = [r for r in rows if r]
        if rows:
            print(f"\n===== {title} =====", flush=True)
            print(pd.DataFrame(rows).to_string(index=False), flush=True)

    show([stat(f[f[f"has_{s}"]], s) for s in ("S1", "S1超", "S2a", "S2b")] + [stat(f, "全体")],
         "各信号 12月超额(vs同期SPY)")
    show([stat(f[f.year == y], f"全体·{y}") for y in range(2021, 2026)], "全体 × 入场年份")
    for y in range(2021, 2026):
        d = f[f.year == y]
        show([stat(d[d.cur], f"过curation·{y}"), stat(d[~d.cur], f"被剔除·{y}")], f"{y} 信号专属curation对照")
    show([stat(f[f.has_S2b & ~f.val_ok & (f.year == y)], f"S2b估值贵·{y}") for y in range(2021, 2026)],
         "反向规则1: S2b+估值贵(PEG>3或PS>15)")
    show([stat(f[f["has_S1超"] & ~f.profitable], "S1超+不盈利·全期")], "反向规则2: S1超+不盈利(伪周期)")
    show([stat(f[(f.sector == "Energy") & (f.year == y)], f"Energy·{y}") for y in range(2021, 2026)],
         "Energy板块 × 年份(regime检验)")


if __name__ == "__main__":
    import sys
    if "--analyze" in sys.argv:
        analyze()
    else:
        run()
        analyze()
