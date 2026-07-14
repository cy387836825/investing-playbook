#!/usr/bin/env python3
"""
退出纪律回测 —— 框架两个未验证alpha来源之一(另一个=人工curation,不可回测)。
backtest-findings.md: "框架价值(若有)只在深挖curation/择时纪律两个未验证处"。本脚本验证后者。

规则(事前规定,来自playbook否决条件,非数据拟合):
  入场: 同 earnings_entry(信号触发财报的次一交易日收盘, 365天去重)
  持有: 每个后续季度财报(EDGAR首次filed)重估触发信号的底层条件
  退出: 该事件全部触发信号的条件均"破坏"时,破坏财报的次一交易日收盘卖出
    S2b破坏: 最新季营收同比 < 15%(增长故事减半即离场; 另测严格版<25%)
    S1/S1超破坏: 最新单季毛利率 跌破触发时水平 或 连续2季环比下滑(L14容忍1季)
    S2a破坏: 最新季净利 ≤ 0(扭亏证伪)
  兜底: 数据右端(2026-07-01)仍持有的按最后收盘计(标记open)
指标: 逐事件真实持有区间回报 vs 同区间SPY, 年化超额; 按入场年份分层。
"""
import time
import pandas as pd
from pathlib import Path
from backtest import _fetch_all, _cik_map, REV_TAGS
from signals import pit_qseries, yoy

BASE = Path(__file__).resolve().parent
PX = BASE / "cache" / "prices"
DATA_END = pd.Timestamp("2026-07-01")
S2B_FLOOR = 0.15   # 破坏阈值(宽松版); --strict 用0.25


def _load_px(tk):
    fp = PX / f"{tk}.csv"
    if not fp.exists():
        return None
    try:
        s = pd.read_csv(fp, index_col=0)
        if s.empty:
            return None
        idx = pd.to_datetime(s.index, errors="coerce")
        ser = pd.to_numeric(s.iloc[:, 0], errors="coerce")
        ser.index = idx
        return ser[ser.index.notna()].dropna().sort_index()
    except Exception:
        return None


def _px_after(h, date):
    fut = h[h.index > pd.Timestamp(date)]
    return (fut.index[0], float(fut.iloc[0])) if not fut.empty else (None, None)


def _px_near(h, date, tol=15):
    d = pd.Timestamp(date)
    sub = h[(h.index >= d - pd.Timedelta(days=tol)) & (h.index <= d + pd.Timedelta(days=tol))]
    if sub.empty:
        return None
    return float(sub.iloc[(sub.index - d).to_series().abs().values.argmin()])


def _filing_dates(rev_units, lo, hi):
    """季度末去重后的财报首次filed日(同earnings_entry._earnings_dates,窗口可调)"""
    first = {}
    for r in rev_units or []:
        if "start" not in r or "end" not in r or "filed" not in r:
            continue
        try:
            days = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
        except Exception:
            continue
        if not (75 <= days <= 100):
            continue
        e, fd = r["end"], r["filed"]
        if e not in first or fd < first[e]:
            first[e] = fd
    return sorted({fd for fd in first.values() if lo < fd <= hi})


def _gm_series(f, asof):
    rev = pit_qseries(f.get("rev"), asof)
    gp = pit_qseries(f.get("gp"), asof)
    if rev is None or gp is None:
        return None
    gm = (gp / rev.reindex(gp.index)).dropna()
    return gm if len(gm) >= 2 else None


def broken(sigs, f, asof, gm0, s2b_floor):
    """该财报日,触发信号的底层条件是否全部破坏"""
    alive = False
    if "S2b" in sigs:
        y0 = yoy(pit_qseries(f.get("rev"), asof), 0)
        if y0 is not None and y0 >= s2b_floor:
            alive = True
    if ("S1" in sigs) or ("S1超" in sigs):
        gm = _gm_series(f, asof)
        if gm is not None:
            two_down = len(gm) >= 3 and gm.iloc[0] < gm.iloc[1] < gm.iloc[2]
            below0 = gm0 is not None and gm.iloc[0] < gm0
            if not (two_down or below0):
                alive = True
        else:
            alive = True   # 数据缺失不强制离场
    if "S2a" in sigs:
        ni = pit_qseries(f.get("ni"), asof)
        if ni is not None and ni.iloc[0] > 0:
            alive = True
    return not alive


def run(s2b_floor=S2B_FLOOR, tag=""):
    ev = pd.read_csv(BASE / "alpha_proof.csv")
    ev = ev[ev.first12].copy()
    ciks = _cik_map()
    spy = _load_px("SPY")
    rows = []
    t0 = time.time()
    for n, (tk, g) in enumerate(ev.groupby("ticker"), 1):
        h = _load_px(tk)
        cik = ciks.get(str(tk).upper())
        if h is None or not cik:
            continue
        f = _fetch_all(cik)
        if f is None:
            continue
        for _, r in g.iterrows():
            d0 = pd.Timestamp(r.entry_date)
            p0 = r.entry
            gm = _gm_series(f, r.earn_date)
            gm0 = float(gm.iloc[0]) if gm is not None else None
            sigs = set(r.sig.split("+"))
            exit_d, exit_p, is_open = None, None, False
            for F in _filing_dates(f.get("rev"), r.earn_date, "2026-06-30"):
                if broken(sigs, f, F, gm0, s2b_floor):
                    ed, ep = _px_after(h, F)
                    if ed is not None:
                        exit_d, exit_p = ed, ep
                    break
            if exit_d is None:   # 从未破坏,持有到数据右端
                last = h[h.index <= DATA_END]
                if last.empty:
                    continue
                exit_d, exit_p, is_open = last.index[-1], float(last.iloc[-1]), True
            days = (exit_d - d0).days
            if days < 5:
                continue
            ret = exit_p / p0 - 1
            s0, s1 = _px_near(spy, d0), _px_near(spy, exit_d)
            if not s0 or not s1:
                continue
            sret = s1 / s0 - 1
            ann = (1 + ret) ** (365.25 / days) - 1 if days >= 30 else None
            sann = (1 + sret) ** (365.25 / days) - 1 if days >= 30 else None
            rows.append({"ticker": tk, "earn_date": r.earn_date, "sig": r.sig,
                         "entry_date": r.entry_date, "entry": p0, "tier": r.tier,
                         "sector": r.sector, "profitable": r.profitable,
                         "lumpy": r.lumpy, "val_ok": r.val_ok,
                         "exit_date": str(exit_d.date()), "exit": round(exit_p, 2),
                         "open": is_open, "days": days,
                         "ret": round(ret, 4), "spy": round(sret, 4),
                         "xs": round(ret - sret, 4),
                         "ann_xs": round(ann - sann, 4) if ann is not None else None})
        if n % 300 == 0:
            print(f"  {n}票 {len(rows)}事件 {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    out = BASE / f"exit_discipline{tag}.csv"
    df.to_csv(out, index=False)
    print(f"→ {out.name} {len(df)}事件", flush=True)
    return df


def report(df, title):
    df = df.copy()
    df["year"] = pd.to_datetime(df.entry_date).dt.year

    def cur(r):
        sigs = set(r.sig.split("+"))
        ok = True
        if "S1" in sigs or "S1超" in sigs:
            ok = ok and (not r.lumpy)
        if "S1超" in sigs:
            ok = ok and r.profitable
        if "S2a" in sigs:
            ok = ok and r.profitable
        if "S2b" in sigs:
            ok = ok and r.val_ok
        return ok
    df["cur"] = df.apply(cur, axis=1)

    def stat(d, label):
        if len(d) < 5:
            return None
        return {"组": label, "n": len(d), "持有天数中位": int(d["days"].median()),
                "中位超额pp": round(d["xs"].median() * 100), "均值超额pp": round(d["xs"].mean() * 100),
                "胜率%": round((d["xs"] > 0).mean() * 100),
                "年化超额中位pp": round(d["ann_xs"].median() * 100) if d["ann_xs"].notna().any() else None,
                "暴雷%(<-30)": round((d["ret"] < -0.3).mean() * 100),
                "大牛%(>100)": round((d["ret"] > 1.0).mean() * 100)}
    print(f"\n========== {title} ==========", flush=True)
    rows = [stat(df, "全体")] + [stat(df[df.year == y], f"全体·{y}") for y in range(2021, 2026)]
    rows += [stat(df[df.cur], "过curation")] + [stat(df[df.cur & (df.year == y)], f"过curation·{y}")
                                             for y in range(2021, 2026)]
    print(pd.DataFrame([r for r in rows if r]).to_string(index=False), flush=True)


def nav_sim():
    """组合NAV回测: 逐日等权持有全部在场头寸(日频再平衡), 对比SPY。报告'组合NAV回测'节由此产生。"""
    import numpy as np
    e = pd.read_csv(BASE / "exit_discipline.csv")

    def curf(r):
        sigs = set(r.sig.split("+"))
        ok = True
        if "S1" in sigs or "S1超" in sigs:
            ok = ok and (not r.lumpy)
        if "S1超" in sigs:
            ok = ok and r.profitable
        if "S2a" in sigs:
            ok = ok and r.profitable
        if "S2b" in sigs:
            ok = ok and r.val_ok
        return ok
    e["cur"] = e.apply(curf, axis=1)

    def one(events, label):
        rets = {}
        for _, r in events.iterrows():
            h = _load_px(r.ticker)
            if h is None:
                continue
            seg = h[(h.index >= pd.Timestamp(r.entry_date)) & (h.index <= pd.Timestamp(r.exit_date))]
            for d, v in seg.pct_change().dropna().items():
                if abs(v) < 5:   # 排除脏数据
                    rets.setdefault(d, []).append(v)
        days = sorted(rets)
        curve = pd.Series([np.mean(rets[d]) for d in days], index=days).add(1).cumprod()
        spy = _load_px("SPY").reindex(pd.DatetimeIndex(days)).ffill()
        spy = spy / spy.iloc[0]

        def mdd(s):
            return float((s / s.cummax() - 1).min())
        yrs = (days[-1] - days[0]).days / 365.25
        print(f"\n===== {label} (n={len(events)}) {days[0].date()}~{days[-1].date()} =====", flush=True)
        print(f"策略: 总回报{curve.iloc[-1]*100-100:+.0f}% CAGR{(curve.iloc[-1]**(1/yrs)-1)*100:+.1f}% 回撤{mdd(curve)*100:.0f}%", flush=True)
        print(f"SPY : 总回报{spy.iloc[-1]*100-100:+.0f}% CAGR{(spy.iloc[-1]**(1/yrs)-1)*100:+.1f}% 回撤{mdd(spy)*100:.0f}%", flush=True)
        both = pd.DataFrame({"s": curve, "b": spy}).dropna()
        ann = both.resample("YE").last() / both.resample("YE").first() - 1
        for y, r in ann.iterrows():
            print(f"  {y.year}: 策略{r['s']*100:+.0f}% SPY{r['b']*100:+.0f}% 超额{(r['s']-r['b'])*100:+.0f}pp", flush=True)
    one(e[e.cur], "A. 全部curated+退出纪律")
    one(e[e.cur & e.sig.str.contains("S1超")], "B. S1超家族+闸门+退出纪律")
    one(e[e.cur & e.sig.str.contains(r"\+")], "C. ≥2信号+闸门+退出纪律")


if __name__ == "__main__":
    import sys
    if "--nav" in sys.argv:
        nav_sim()
    elif "--report" in sys.argv:
        report(pd.read_csv(BASE / "exit_discipline.csv"), "退出纪律(S2b破坏<15%)")
        fp = BASE / "exit_discipline_strict.csv"
        if fp.exists():
            report(pd.read_csv(fp), "退出纪律严格版(S2b破坏<25%)")
    else:
        df = run(0.15, "")
        report(df, "退出纪律(S2b破坏<15%)")
        df2 = run(0.25, "_strict")
        report(df2, "退出纪律严格版(S2b破坏<25%)")
