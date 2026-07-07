#!/usr/bin/env python3
"""
暴涨机会捕捉框架 —— 全域字段级扫描器（免费数据源版）
配套 ~/Documents/暴涨机会捕捉框架-playbook.md

数据源:
  - finvizfinance: 全市场 universe（市值 ≥ $5B）
  - yfinance:      季度利润表字段（毛利率/营收/净利）

用法:
  python scan.py universe            # 拉取并缓存 universe（universe.csv）
  python scan.py scan [--limit N] [--tickers A,B,C]   # 逐票拉字段，断点续传写 results.csv
  python scan.py report              # 按筛选器规则出信号报告 signals.md

信号定义（对应 playbook）:
  S1  周期反转初筛: 毛利率连续 ≥2 个季度环比改善，且 TTM 毛利率低于 4 年年报均值（早周期证据）
  S2a 首次盈利:     最新季度 GAAP 净利 >0，且之前 4 个季度中至少 3 个 ≤0
  S2b 营收加速:     最新季度营收同比 ≥25% 且高于上一季度的同比增速
局限:
  - yfinance 季度数据仅 ~5 个季度、年报仅 ~4 年 → "10年P/B分位"降级为"4年毛利率均值对比"
  - 金融/银行股无毛利率概念 → 自动跳过 S1
  - 入场决策前，关键数字用 SEC EDGAR 或财报原文交叉核对
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
UNIVERSE_CSV = BASE / "universe.csv"
RESULTS_CSV = BASE / "results.csv"
SIGNALS_MD = BASE / "signals.md"
MIN_MCAP = 5e9

RESULT_FIELDS = [
    "ticker", "name", "sector", "industry", "mcap_b",
    "quarters", "gm_series", "gm_consec_improve", "gm_ttm", "gm_hist_avg",
    "ni_series", "first_profit", "rev_yoy_latest", "rev_yoy_prior",
    "error",
]


def fetch_universe():
    from finvizfinance.screener.overview import Overview
    print("从 Finviz 拉取市值 >$2B 的全部美股（分页较多，约几分钟）...")
    ov = Overview()
    ov.set_filter(filters_dict={"Market Cap.": "+Mid (over $2bln)"})
    df = ov.screener_view(order="Market Cap.", ascend=False, sleep_sec=1)
    # finviz 的 Market Cap 列为美元原值
    df = df.rename(columns={"Market Cap": "mcap_m"})
    df["mcap_b"] = pd.to_numeric(df["mcap_m"], errors="coerce") / 1e9
    df = df[df["mcap_b"] >= MIN_MCAP / 1e9].copy()
    df = df[["Ticker", "Company", "Sector", "Industry", "mcap_b"]]
    df.columns = ["ticker", "name", "sector", "industry", "mcap_b"]
    df.to_csv(UNIVERSE_CSV, index=False)
    print(f"universe.csv 已保存: {len(df)} 家市值 ≥$5B 的公司")


def _row(stmt, names):
    for n in names:
        if n in stmt.index:
            return stmt.loc[n]
    return None


def analyze_ticker(tk, meta):
    import yfinance as yf
    out = {k: "" for k in RESULT_FIELDS}
    out.update({"ticker": tk, "name": meta.get("name", ""), "sector": meta.get("sector", ""),
                "industry": meta.get("industry", ""), "mcap_b": round(float(meta.get("mcap_b", 0)), 1)})
    try:
        t = yf.Ticker(tk)
        q = t.quarterly_income_stmt
        if q is None or q.empty:
            out["error"] = "no_quarterly_data"
            return out
        q = q[sorted(q.columns, reverse=True)]  # 最新季度在前
        rev = _row(q, ["Total Revenue", "Operating Revenue"])
        gp = _row(q, ["Gross Profit"])
        ni = _row(q, ["Net Income", "Net Income Common Stockholders"])
        out["quarters"] = len(q.columns)

        # --- S1: 毛利率连续环比改善 ---
        if rev is not None and gp is not None:
            gm = (gp / rev).dropna()
            gm = gm[rev.reindex(gm.index) > 0]
            vals = list(gm.values)  # 最新在前
            out["gm_series"] = "|".join(f"{v:.3f}" for v in vals)
            consec = 0
            for i in range(len(vals) - 1):
                if vals[i] > vals[i + 1]:
                    consec += 1
                else:
                    break
            out["gm_consec_improve"] = consec
            # TTM vs 4年年报均值
            a = t.income_stmt
            if a is not None and not a.empty:
                arev, agp = _row(a, ["Total Revenue", "Operating Revenue"]), _row(a, ["Gross Profit"])
                if arev is not None and agp is not None:
                    hist = (agp / arev).dropna()
                    if len(hist) >= 2:
                        out["gm_hist_avg"] = round(float(hist.mean()), 3)
            r4 = rev.dropna()[:4]
            g4 = gp.reindex(r4.index).dropna()
            if len(r4) >= 4 and len(g4) >= 4 and r4.sum() > 0:
                out["gm_ttm"] = round(float(g4.sum() / r4.sum()), 3)

        # --- S2a: 首次盈利 ---
        if ni is not None:
            niv = list(ni.dropna().values)
            out["ni_series"] = "|".join(f"{v/1e6:.0f}" for v in niv)
            if len(niv) >= 4 and niv[0] > 0:
                prior = niv[1:5]
                if sum(1 for v in prior if v <= 0) >= 3:
                    out["first_profit"] = 1

        # --- S2b: 营收同比加速 ---
        if rev is not None:
            rv = rev.dropna()
            if len(rv) >= 5:
                y0 = (rv.iloc[0] - rv.iloc[4]) / abs(rv.iloc[4])
                out["rev_yoy_latest"] = round(float(y0), 3)
            if len(rv) >= 6:
                y1 = (rv.iloc[1] - rv.iloc[5]) / abs(rv.iloc[5])
                out["rev_yoy_prior"] = round(float(y1), 3)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:120]
    return out


def run_scan(limit=None, tickers=None):
    if not UNIVERSE_CSV.exists():
        sys.exit("请先运行: python scan.py universe")
    uni = pd.read_csv(UNIVERSE_CSV)
    if tickers:
        uni = uni[uni["ticker"].isin(tickers)]
    done = set()
    if RESULTS_CSV.exists():
        done = set(pd.read_csv(RESULTS_CSV)["ticker"].astype(str))
    todo = uni[~uni["ticker"].isin(done)]
    if limit:
        todo = todo.head(limit)
    print(f"universe={len(uni)}  已完成={len(done)}  本次待扫={len(todo)}")
    write_header = not RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if write_header:
            w.writeheader()
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            res = analyze_ticker(row["ticker"], row.to_dict())
            w.writerow(res)
            f.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} ... {row['ticker']}")
            time.sleep(0.4)
    print("扫描完成 → results.csv")


EDGAR_CSV = BASE / "edgar_rev.csv"
DEEP_MD = BASE / "deep.md"
UA = {"User-Agent": "Personal investment research cy387836825@gmail.com"}
REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet", "SalesRevenueGoodsNet"]


def _get_json(url):
    import json
    import urllib.request
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _cik_map():
    data = _get_json("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}


def _edgar_quarterly_rev(cik):
    """从 companyfacts 提取季度营收序列（含8+季完整历史，修复yfinance仅5季的缺陷）"""
    facts = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in REV_TAGS:
        units = gaap.get(tag, {}).get("units", {}).get("USD")
        if not units:
            continue
        q = {}
        for r in units:
            if "start" not in r or "end" not in r:
                continue
            try:
                d = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
            except Exception:
                continue
            if 75 <= d <= 100:  # 单季期间
                q[r["end"]] = r["val"]  # 修正版申报覆盖旧值
        if len(q) >= 6:
            s = pd.Series(q)
            s.index = pd.to_datetime(s.index)
            return s.sort_index(ascending=False)
    return None


def _yoy(series, i):
    """第 i 个最新季度的同比：找 350-380 天前的可比季度（按日期对齐，容忍Q4缺口）"""
    if series is None or len(series) <= i:
        return None
    end = series.index[i]
    base = series[(series.index >= end - pd.Timedelta(days=380))
                  & (series.index <= end - pd.Timedelta(days=350))]
    if base.empty or base.iloc[0] == 0:
        return None
    return float(series.iloc[i] / base.iloc[0] - 1)


def edgar_fix():
    """对 S2b 候选（营收同比≥25%）用 EDGAR 完整历史补算加速确认"""
    df = pd.read_csv(RESULTS_CSV)
    mc = pd.to_numeric(df["mcap_b"], errors="coerce")
    if mc.max() > 1e5:
        mc = mc / 1e6
    cand = df[(pd.to_numeric(df["rev_yoy_latest"], errors="coerce") >= 0.25) & (mc >= 5)]
    done = set()
    if EDGAR_CSV.exists():
        done = set(pd.read_csv(EDGAR_CSV)["ticker"])
    todo = [t for t in cand["ticker"] if t not in done]
    print(f"S2b候选 {len(cand)} 家，待补 EDGAR 数据 {len(todo)} 家")
    ciks = _cik_map()
    write_header = not EDGAR_CSV.exists()
    with open(EDGAR_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "e_yoy_latest", "e_yoy_prior", "e_quarters", "e_error"])
        if write_header:
            w.writeheader()
        for i, tk in enumerate(todo, 1):
            row = {"ticker": tk, "e_yoy_latest": "", "e_yoy_prior": "", "e_quarters": "", "e_error": ""}
            cik = ciks.get(str(tk).upper())
            if not cik:
                row["e_error"] = "no_cik(外国发行人/ADR)"
            else:
                try:
                    s = _edgar_quarterly_rev(cik)
                    if s is None:
                        row["e_error"] = "no_usgaap_quarterly_rev"
                    else:
                        row["e_quarters"] = len(s)
                        y0, y1 = _yoy(s, 0), _yoy(s, 1)
                        row["e_yoy_latest"] = round(y0, 3) if y0 is not None else ""
                        row["e_yoy_prior"] = round(y1, 3) if y1 is not None else ""
                except Exception as e:
                    row["e_error"] = f"{type(e).__name__}"[:40]
            w.writerow(row)
            f.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(todo)} ... {tk}")
            time.sleep(0.15)  # SEC 限速 10req/s
    print(f"完成 → {EDGAR_CSV}")


def deep(tickers):
    """深度分析卷宗：价格位置(是否已错过底部)、估值、分析师EPS修正方向、下次财报日"""
    import yfinance as yf
    lines = [f"# 深度分析卷宗\n\n生成: {time.strftime('%Y-%m-%d %H:%M')}\n"]
    for tk in tickers:
        t = yf.Ticker(tk)
        info = t.info or {}
        px = info.get("currentPrice") or info.get("regularMarketPrice")
        lo, hi = info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")
        lines.append(f"\n## {tk} — {info.get('shortName','')}\n")
        if px and lo and hi:
            lines.append(f"- **价格位置**: ${px}｜距52周低点 +{(px/lo-1)*100:.0f}%｜距52周高点 {(px/hi-1)*100:.0f}%"
                         f"（反弹>100%说明第一段已走完，按'中段'纪律入场）")
        lines.append(f"- **估值**: P/B={info.get('priceToBook','?')} | P/S(TTM)={info.get('priceToSalesTrailing12Months','?')}"
                     f" | 前瞻PE={info.get('forwardPE','?')} | 毛利率={info.get('grossMargins','?')}")
        tgt = info.get("targetMeanPrice")
        if tgt and px:
            lines.append(f"- **卖方**: 平均目标价 ${tgt}（{(tgt/px-1)*100:+.0f}%）｜评级均值 {info.get('recommendationMean','?')}"
                         f"（1=强买 5=强卖）｜覆盖 {info.get('numberOfAnalystOpinions','?')} 家")
        try:
            rv = t.eps_revisions
            if rv is not None and not rv.empty and "0y" in rv.index:
                up, dn = rv.loc["0y", "upLast30days"], rv.loc["0y", "downLast30days"]
                verdict = "上修占优 ✅(筛选器2确认条件)" if (up or 0) > (dn or 0) else "下修占优/停滞 ⚠️"
                lines.append(f"- **EPS修正(30天,本财年)**: 上修{up} vs 下修{dn} → {verdict}")
        except Exception:
            pass
        try:
            cal = t.calendar
            ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if ed:
                lines.append(f"- **下次财报**: {ed[0] if isinstance(ed, list) else ed}（确认信号的决断日）")
        except Exception:
            pass
        si = info.get("shortPercentOfFloat")
        if si:
            lines.append(f"- **空头占流通盘**: {si*100:.1f}%（>15%注意轧空/分歧极大）")
        time.sleep(0.3)
    DEEP_MD.write_text("\n".join(lines))
    print(f"卷宗已生成 → {DEEP_MD}")


# 确认层：各行业必须核实的特有指标（初筛命中后逐票验证，数据在财报/股东信/行业源）
SECTOR_KPI = {
    "Technology": "SaaS看NRR(≥100%?)与RPO增速；半导体看库存周转天数、合同价趋势(TrendForce)、HBM/先进制程占比",
    "Communication Services": "DAU/MAU增速、ARPU、广告主数量增速；流量来源集中度(搜索依赖)",
    "Consumer Cyclical": "同店销售SSS与客流(transactions)拆分、单店经济模型、库存/销售比；会员制看续费率",
    "Consumer Defensive": "同店销售、会员续费率(≥90%?)、自有品牌渗透率",
    "Basic Materials": "产品现货/合同价趋势(锂/PE价差/铜)、行业开工率、库存天数、龙头capex公告",
    "Energy": "商品价格曲线、储量替代率、盈亏平衡成本、资本纪律(回购vs扩产)",
    "Industrials": "订单book-to-bill(≥1.2?)、积压订单backlog增速、订单/收入转化周期",
    "Healthcare": "管线里程碑日历、处方量趋势(IQVIA)、专利悬崖时间表、医保覆盖决定",
    "Financial Services": "净息差NIM、信贷损失拨备趋势、贷款增速、费用收入占比；经纪看客户资产净流入",
    "Real Estate": "出租率、同店NOI增速、cap rate vs 融资成本利差",
    "Utilities": "费率案进度、数据中心接入订单(GW)、受监管资产基数RAB增速",
}


def report():
    df = pd.read_csv(RESULTS_CSV)
    df = df[df["error"].isna() | (df["error"] == "")]
    # 兼容旧 results.csv 的市值单位错误（当时按 /1000 存，实为美元原值）
    if pd.to_numeric(df["mcap_b"], errors="coerce").max() > 1e5:
        df["mcap_b"] = pd.to_numeric(df["mcap_b"], errors="coerce") / 1e6
    df = df[pd.to_numeric(df["mcap_b"], errors="coerce") >= 5]
    df = df.drop_duplicates(subset="name")  # 双类股 (Z/ZG 等)
    for c in ["gm_consec_improve", "gm_ttm", "gm_hist_avg", "first_profit",
              "rev_yoy_latest", "rev_yoy_prior", "mcap_b"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 单季最新毛利率（gm_series 首值），修正 TTM 的 ~2 季滞后
    df["gm_latest"] = pd.to_numeric(
        df["gm_series"].astype(str).str.split("|").str[0], errors="coerce")

    s1 = df[(df["gm_consec_improve"] >= 2) & (df["gm_ttm"] < df["gm_hist_avg"])].copy()

    def stage(r):
        # 用"最新单季 vs 历史均值"判断周期热度，避免 TTM 滞后把中段误判为早期
        if pd.isna(r["gm_latest"]) or pd.isna(r["gm_hist_avg"]):
            return "?"
        ratio = r["gm_latest"] / r["gm_hist_avg"] if r["gm_hist_avg"] else float("nan")
        if r["gm_latest"] <= r["gm_hist_avg"]:
            return "早期"          # 单季也仍低于历史 → 真正的早周期
        if ratio <= 1.3:
            return "中段·已启动"   # 单季刚越过历史均值 → 第一段可能已走完
        return "偏晚·谨慎"         # 单季远超历史 → 只是TTM还没跟上，接近排除线

    s1["stage"] = s1.apply(stage, axis=1)
    s1 = s1.sort_values(["stage", "mcap_b"], ascending=[True, False])

    s2a = df[df["first_profit"] == 1].sort_values("mcap_b", ascending=False)

    # 优先用 EDGAR 完整历史（edgar 命令生成）覆盖 yfinance 的 5 季局限
    if EDGAR_CSV.exists():
        e = pd.read_csv(EDGAR_CSV)
        df = df.merge(e[["ticker", "e_yoy_latest", "e_yoy_prior"]], on="ticker", how="left")
        df["rev_yoy_latest"] = pd.to_numeric(df["e_yoy_latest"], errors="coerce").fillna(df["rev_yoy_latest"])
        df["rev_yoy_prior"] = pd.to_numeric(df["e_yoy_prior"], errors="coerce").fillna(df["rev_yoy_prior"])

    s2b = df[(df["rev_yoy_latest"] >= 0.25)
             & (df["rev_yoy_prior"].isna() | (df["rev_yoy_latest"] > df["rev_yoy_prior"]))].copy()
    s2b["accel_confirmed"] = (df["rev_yoy_latest"] > df["rev_yoy_prior"]).map({True: "是", False: "数据不足"})
    s2b = s2b.sort_values("rev_yoy_latest", ascending=False)

    lines = [f"# 全域扫描信号报告\n",
             f"生成时间: {time.strftime('%Y-%m-%d %H:%M')}  |  已扫描: {len(df)} 家（≥$5B）\n"]

    def section(title, d, cols):
        lines.append(f"\n## {title}（{len(d)} 家）\n")
        if len(d):
            lines.append(d[cols].to_markdown(index=False))
            lines.append("")

    section("S1 周期反转初筛：毛利率连续≥2季环比改善 且 TTM低于4年均值（按周期阶段分层）", s1,
            ["ticker", "name", "sector", "mcap_b", "gm_consec_improve",
             "gm_latest", "gm_ttm", "gm_hist_avg", "stage"])
    section("S2a 首次GAAP盈利", s2a,
            ["ticker", "name", "sector", "mcap_b", "ni_series"])
    section("S2b 营收≥25%且同比增速在加速", s2b.head(40),
            ["ticker", "name", "sector", "mcap_b", "rev_yoy_latest", "rev_yoy_prior", "accel_confirmed"])

    # 确认层任务清单：每个命中股按行业列出必须核实的特有指标
    hits = pd.concat([s1, s2a, s2b.head(40)]).drop_duplicates(subset="ticker")
    lines.append("\n## 确认层任务清单（初筛命中后逐票核实的 sector 特有指标）\n")
    for sec, grp in hits.groupby("sector"):
        kpi = SECTOR_KPI.get(sec, "（无预设清单，按 playbook 对应筛选器的确认信号核实）")
        lines.append(f"- **{sec}**（{', '.join(grp['ticker'].astype(str))}）: {kpi}")

    lines.append("\n> 注意：S1/S2 均为**初筛**，入场前必须按 playbook 完成确认信号验证（新闻/财报/行业价格）。\n")
    SIGNALS_MD.write_text("\n".join(str(x) for x in lines))
    print(f"报告已生成 → {SIGNALS_MD}")
    print(f"S1={len(s1)}  S2a={len(s2a)}  S2b={len(s2b)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["universe", "scan", "report", "edgar", "deep"])
    p.add_argument("--limit", type=int)
    p.add_argument("--tickers", type=str)
    a = p.parse_args()
    if a.cmd == "universe":
        fetch_universe()
    elif a.cmd == "scan":
        run_scan(a.limit, a.tickers.split(",") if a.tickers else None)
    elif a.cmd == "edgar":
        edgar_fix()
    elif a.cmd == "deep":
        if not a.tickers:
            sys.exit("用法: python scan.py deep --tickers MCHP,SYM,BE")
        deep(a.tickers.split(","))
    else:
        report()
