#!/usr/bin/env python3
"""
信号定义 —— 唯一真源(single source of truth)。
backtest.py(回测) 和 scan.py(实时扫描) 都从这里导入,保证回测测的=实盘flag的。
所有信号基于 PIT EDGAR 数据(companyfacts的filed日期),函数纯粹:输入units字典+asof,输出bool。

f = {"rev": rev_units, "ni": ni_units, "gp": gp_units}  (来自 companyfacts, 各为 SEC XBRL facts 列表)
asof = point-in-time 日期字符串; 只采信 filed<=asof 的数据(无前视)
"""
import pandas as pd

REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet", "SalesRevenueGoodsNet"]


def pit_qseries(units, asof):
    """filed<=asof 的季度序列(end→val),point-in-time。单季=期间75-100天;重述取filed<=asof中最新filed"""
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


def yoy(s, i):
    """第i个最新季度的同比: 与350-380天前的可比季度比(按日期匹配,容忍Q4缺口)"""
    if s is None or len(s) <= i:
        return None
    end = s.index[i]
    base = s[(s.index >= end - pd.Timedelta(days=380)) & (s.index <= end - pd.Timedelta(days=350))]
    if base.empty or base.iloc[0] == 0:
        return None
    return float(s.iloc[i] / base.iloc[0] - 1)


def s1_core(f, asof):
    """返回(连续改善季数, TTM毛利率, 历史基线毛利率, 营收同比) 供S1/S1超判定"""
    rev = pit_qseries(f.get("rev"), asof)
    gp = pit_qseries(f.get("gp"), asof)
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
    hist = gm.iloc[4:].mean()   # 第5季往前的均值 = 历史基线
    ry = yoy(rev, 0)
    return consec, ttm, hist, (ry if ry is not None else 0)


# ===== 四个信号定义 =====

def sig_s2b(f, asof):
    """S2b 营收加速: 最新季营收同比≥25% 且 > 上一季同比(在加速)"""
    s = pit_qseries(f.get("rev"), asof)
    y0, y1 = yoy(s, 0), yoy(s, 1)
    if y0 is None or y1 is None:
        return None
    return (y0 >= 0.25) and (y0 > y1)


def sig_s2a(f, asof):
    """S2a 首次盈利: 最新季GAAP净利>0 且 前4季中≥3季≤0"""
    s = pit_qseries(f.get("ni"), asof)
    if s is None or len(s) < 5:
        return None
    v = list(s.values)
    return v[0] > 0 and sum(1 for x in v[1:5] if x <= 0) >= 3


def sig_s1(f, asof):
    """S1 周期反转: 毛利率连续≥2季改善 且 TTM<历史基线(周期底部均值回归)"""
    c = s1_core(f, asof)
    if c is None:
        return None
    consec, ttm, hist, _ = c
    return consec >= 2 and ttm < hist


def sig_s1super(f, asof):
    """S1超 超级周期: 连续≥2季改善 且 TTM≥历史基线 且 营收同比≥40%(结构突破)"""
    c = s1_core(f, asof)
    if c is None:
        return None
    consec, ttm, hist, ry = c
    return consec >= 2 and ttm >= hist and ry >= 0.4


SIGNALS = {"S1": sig_s1, "S1超": sig_s1super, "S2a": sig_s2a, "S2b": sig_s2b}
