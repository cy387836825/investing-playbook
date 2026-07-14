#!/usr/bin/env python3
"""漏斗共享阈值 —— 回测(assemble_viz)与当日实时(live_funnel)单一真源。

FLOOR_B 是"第一层市值门槛"的唯一旋钮:调此一处即可同时改回测与实时的下限。
"""

FLOOR_B = 1.0   # 市值门槛:市值≥$1B(回测用触发时PIT市值,实时用当前Finviz市值)。调此一处即可换下限

# 传统市值分层(美元十亿),阈值降序;用市值(mcap_b)分箱
CAP_TIERS = [(200, 'mega'), (10, 'large'), (2, 'mid'), (0.3, 'small'), (0.05, 'micro'), (0.0, 'nano')]


def cap_tier(mcap_b):
    """按传统定义给市值分层。返回代码(mega/large/mid/small/micro/nano),缺失/≤0返回''。
    真实市值恒>0;缺失PIT股数会得0.0,故≤0一律当"未知"而非纳盘,避免把数据缺口误标成纳米盘。"""
    if mcap_b is None or mcap_b != mcap_b or mcap_b <= 0:
        return ''
    for thr, code in CAP_TIERS:
        if mcap_b >= thr:
            return code
    return 'nano'
