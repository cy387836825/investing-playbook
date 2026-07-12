#!/usr/bin/env python3
"""
财报次日入场回测 —— 最忠实复现playbook的"财报后第二天追入"规则。
不再用固定季度末锚点,而是: 对每次财报(EDGAR filed日期),检查信号是否触发,
若触发→在该财报申报日的次一交易日买入。入场精度到"财报次日"。

对比锚点法的价值: 入场绑定真实财报日(2月/5月/8月/11月任意日),而非日历季度末→更早、更准。
纯PIT: 信号只用 filed<=该财报日 的数据;买入价=filed日之后第一个交易日收盘。
"""
import time
import pandas as pd
from pathlib import Path
from backtest import _fetch_all, _companyfacts_cached, _cik_map, _price_hist, REV_TAGS, SIGNALS
from curation import _pit_shares

BASE = Path(__file__).resolve().parent
WIN_START, WIN_END = "2021-01-01", "2025-06-30"   # 财报日窗口(留12月远期)
END = "2026-07-01"


def _earnings_dates(rev_units):
    """从营收units提取季度财报的申报日(filed):按季度末(end)去重,每个财报周期只留最早filed。
    同一季度会在多份申报里重复出现(10-K/10-K/A的对比列、后续季报的去年同期列),
    只有'首次披露该季度'的那份是真财报事件。故对每个end取min(filed),避免年报/修正案重复触发。"""
    first_filed = {}   # end(季度末) -> 最早filed日期
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
        if e not in first_filed or fd < first_filed[e]:
            first_filed[e] = fd
    # 每个季度末取其最早filed;再按回测窗口过滤(用最早披露日,重报的对比列不再触发)
    return sorted({fd for fd in first_filed.values() if WIN_START <= fd <= WIN_END})


def _px_after(h, date):
    """date之后第一个交易日收盘(财报次日买入)"""
    d = pd.Timestamp(date)
    fut = h[h.index > d]
    return float(fut.iloc[0]) if not fut.empty else None


def _mdd(s):
    run = s.cummax()
    return float((s / run - 1).min())


def run():
    uni = pd.read_csv(BASE / "universe.csv")["ticker"].astype(str).tolist()
    ciks = _cik_map()
    print(f"财报次日入场回测: 样本≤{len(uni)}  财报窗口{WIN_START}~{WIN_END}", flush=True)
    rows = []
    for i, tk in enumerate(uni, 1):
        cik = ciks.get(tk.upper())
        if not cik:
            continue
        f = _fetch_all(cik)   # 缓存,快
        if f is None or not f.get("rev"):
            continue
        edates = _earnings_dates(f["rev"])
        if not edates:
            continue
        h = _price_hist(tk, "2020-06-01", END)
        if h is None:
            continue
        facts = _companyfacts_cached(cik)   # 缓存,取PIT股数用
        # 记录每次信号触发的财报(first=首次触发;回测统计只用首次,与买入持有结论一致)
        seen = False
        for F in edates:
            fl = [s for s, fn in SIGNALS.items() if fn(f, F) is True]
            if not fl:
                continue
            entry = _px_after(h, F)         # 财报次日买入
            if not entry:
                continue
            after = h[h.index > pd.Timestamp(F)]
            if after.empty:
                continue
            now = float(after.iloc[-1]); peak = float(after.max())
            # 脏价过滤:反向拆股未复权时,入场价停留在拆股前的天价(如XTIA $1.89M/现$1.70、NXTT $314K/现$1.33),
            # 整行(入场价/收益/市值)都不可用→跳过。阈值放宽以保住真高价股(BRK-A $434K→$751K、NVR $5K 均不误伤)。
            if entry > 1000 and now < entry / 100:
                continue
            peak_date = str(after.idxmax().date())   # 峰值出现日期(用于峰值年化)
            # 触发时市值($B) = filed<=F的最新股数 × 入场价 (point-in-time,无前视)
            sh = _pit_shares(facts, F) if facts else None
            mcap_pit = round(sh * entry / 1e9, 3) if sh else None
            rows.append({"ticker": tk, "earn_date": F, "sig": "+".join(fl), "first": not seen,
                         "entry": round(entry, 2), "now": round(now, 2), "mcap_pit": mcap_pit,
                         "peak_date": peak_date,
                         "ret": round(now / entry - 1, 3), "pkr": round(peak / entry - 1, 3),
                         "mul": round(after.min() / entry - 1, 3), "dd": round(_mdd(after), 3)})
            seen = True
        if i % 200 == 0:
            print(f"  {i}/{len(uni)} 触发{len(rows)}次", flush=True)
        time.sleep(0.02)
    df = pd.DataFrame(rows)
    df.to_csv(BASE / "earnings_entry.csv", index=False)
    fdf = df[df["first"]]   # 回测统计只看首次触发入场
    print(f"\n信号触发(财报次日入场)的股票: {len(fdf)}只 / 共{len(df)}次命中", flush=True)
    print(f"全体(首次入场): 持有至今 中位{fdf['ret'].median()*100:.0f}% 均值{fdf['ret'].mean()*100:.0f}%  峰值 中位{fdf['pkr'].median()*100:.0f}%", flush=True)
    big = fdf[fdf["pkr"] > 3.0]
    print(f"\n大牛股(首次入场→峰值>300%): {len(big)}只 ({len(big)/len(fdf)*100:.0f}%)", flush=True)
    print(f"  持有至今 中位{big['ret'].median()*100:.0f}% 均值{big['ret'].mean()*100:.0f}%", flush=True)
    print(f"  最大浮亏 平均{big['mul'].mean()*100:.0f}% 最深{big['mul'].min()*100:.0f}%", flush=True)
    print(f"  最大回撤 平均{big['dd'].mean()*100:.0f}% ({(big['dd']<-0.5).sum()}/{len(big)}次>50%)", flush=True)
    print(f"\n大牛股Top20(按峰值,含首触发财报日):", flush=True)
    for _, r in big.nlargest(20, "pkr").iterrows():
        print(f"  {r['ticker']:6} 财报{r['earn_date']} {r['sig']:10} 次日买${r['entry']:.2f}→今${r['now']:.2f} 持有{r['ret']*100:+.0f}% 峰{r['pkr']*100:+.0f}% 回撤{r['dd']*100:.0f}%", flush=True)


if __name__ == "__main__":
    run()
