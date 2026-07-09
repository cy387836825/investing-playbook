#!/usr/bin/env python3
"""signals.py + curation.curate_pass 的单元测试(纯逻辑,不联网)。
运行: python -m pytest test_signals.py -q  或  python test_signals.py"""
import unittest
import signals as S
from curation import curate_pass


def qunits(vals, start_year=2021, filed_lag=40, q_start_month=1):
    """生成季度XBRL风格units: vals[0]是最早季度。start/end约90天,filed=end后filed_lag天。"""
    import datetime
    out, y, m = [], start_year, q_start_month
    for v in vals:
        s = datetime.date(y, m, 1)
        e = s + datetime.timedelta(days=89)
        f = e + datetime.timedelta(days=filed_lag)
        out.append({"start": s.isoformat(), "end": e.isoformat(),
                    "filed": f.isoformat(), "val": v})
        m += 3
        if m > 12:
            m -= 12; y += 1
    return out


class TestPitQseries(unittest.TestCase):
    def test_needs_6_quarters(self):
        self.assertIsNone(S.pit_qseries(qunits([1, 2, 3, 4, 5]), "2030-01-01"))  # 仅5季
        self.assertIsNotNone(S.pit_qseries(qunits([1, 2, 3, 4, 5, 6]), "2030-01-01"))

    def test_pit_filters_future_filed(self):
        import pandas as pd
        u = qunits(list(range(10, 110, 10)))  # 10季,2021Q1起
        s_all = S.pit_qseries(u, "2030-01-01")
        s_mid = S.pit_qseries(u, "2023-06-01")   # 中途:部分已申报
        self.assertEqual(len(s_all), 10)
        self.assertGreater(len(s_all), len(s_mid))   # 中途看到的更少
        # 关键PIT保证: 任何"申报日>asof"的数据绝不出现在结果里
        cutoff = pd.Timestamp("2023-06-01")
        filed_after = [r for r in u if pd.Timestamp(r["filed"]) > cutoff]
        vals_after = {r["val"] for r in filed_after}
        self.assertTrue(vals_after)  # 确有未来申报的
        self.assertFalse(vals_after & set(s_mid.values))  # 但一个都没漏进来

    def test_latest_first(self):
        s = S.pit_qseries(qunits([1, 2, 3, 4, 5, 6]), "2030-01-01")
        self.assertGreater(s.index[0], s.index[-1])  # 最新在前

    def test_restatement_uses_latest_filed(self):
        u = qunits([10, 20, 30, 40, 50, 60])
        # 对最后一季追加一条"修正"(同end,更晚filed,不同val)
        last = u[-1].copy(); last["filed"] = "2029-01-01"; last["val"] = 999
        u.append(last)
        s = S.pit_qseries(u, "2030-01-01")
        self.assertEqual(s.iloc[0], 999)   # 取filed<=asof中最新filed的值

    def test_ignores_non_quarterly(self):
        u = qunits([10, 20, 30, 40, 50, 60])
        u.append({"start": "2022-01-01", "end": "2022-12-31", "filed": "2023-02-01", "val": 9999})  # 年度
        s = S.pit_qseries(u, "2030-01-01")
        self.assertNotIn(9999, list(s.values))


class TestYoy(unittest.TestCase):
    def test_basic_yoy(self):
        s = S.pit_qseries(qunits([100, 110, 120, 130, 150, 160]), "2030-01-01")
        y = S.yoy(s, 0)  # 最新季(第6季,值160) vs 约1年前(第2季,值110)
        self.assertAlmostEqual(y, 160 / 110 - 1, places=3)

    def test_none_when_no_base(self):
        s = S.pit_qseries(qunits([1, 2, 3, 4, 5, 6]), "2030-01-01")
        self.assertIsNone(S.yoy(s, 99))  # 越界


class TestS2b(unittest.TestCase):
    def test_accel_pass(self):
        # 营收: 同比加速且>25%。构造后段增速拉高
        vals = [100, 100, 100, 100, 140, 160]  # 最新160 vs 1年前(第2个100)=+60%; 上季140 vs 100=+40% → 加速
        f = {"rev": qunits(vals)}
        self.assertTrue(S.sig_s2b(f, "2030-01-01"))

    def test_decel_fail(self):
        vals = [100, 100, 100, 100, 200, 210]  # 最新+110%, 上季+100% 仍加速... 换成减速:
        vals = [100, 100, 100, 100, 250, 200]  # 最新200 vs100=+100%; 上季250 vs100=+150% → 减速
        self.assertFalse(S.sig_s2b({"rev": qunits(vals)}, "2030-01-01"))

    def test_below_25_fail(self):
        vals = [100, 100, 100, 100, 105, 110]  # 增速<25%
        self.assertFalse(S.sig_s2b({"rev": qunits(vals)}, "2030-01-01"))


class TestS2a(unittest.TestCase):
    def test_first_profit_pass(self):
        # 需≥6季(pit_qseries要求)。最新季>0,前4季≥3季≤0
        ni = [-9, -7, -5, -8, -2, 4]  # 6季,最新+4,前4季[-2,-8,-5,-7]全负
        self.assertTrue(S.sig_s2a({"ni": qunits(ni)}, "2030-01-01"))

    def test_established_profit_fail(self):
        ni = [4, 5, 6, 7, 8, 9]  # 一直盈利,非"首次"
        self.assertFalse(S.sig_s2a({"ni": qunits(ni)}, "2030-01-01"))

    def test_latest_loss_fail(self):
        ni = [-9, -5, -3, -8, -2, -1]  # 6季,最新仍亏
        self.assertFalse(S.sig_s2a({"ni": qunits(ni)}, "2030-01-01"))


class TestS1(unittest.TestCase):
    def _f(self, gm_vals, rev_growth=0.0):
        # 用rev固定、gp=rev*gm 构造目标毛利率序列; 需≥8季
        rev = [1000] * len(gm_vals)
        if rev_growth:
            rev = [1000 * (1 + rev_growth) ** i for i in range(len(gm_vals))]
        gp = [r * g for r, g in zip(rev, gm_vals)]
        return {"rev": qunits(rev), "gp": qunits(gp)}

    def test_s1_reversal_pass(self):
        # 毛利率连续改善(最新在前,序列递增) 且 TTM<历史基线
        # pit_qseries最新在前;这里vals[0]最早。要"最新几季改善"→后段(最新)高,但TTM<更早均值→矛盾
        # 早期反转: 历史高→崩→刚开始回升。历史基线(更早季)高, 近4季TTM低, 但最近2季在升
        gm = [0.40, 0.40, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20]  # 早期高40%,崩到10%,逐季回升
        self.assertTrue(S.sig_s1(self._f(gm), "2030-01-01"))

    def test_s1_no_improve_fail(self):
        gm = [0.20, 0.20, 0.20, 0.20, 0.18, 0.16, 0.14, 0.12]  # 近段在跌
        self.assertFalse(S.sig_s1(self._f(gm), "2030-01-01"))

    def test_s1super_needs_ttm_above_hist_and_growth(self):
        # 超级周期: 连续改善 + TTM≥历史基线 + 营收同比≥40%
        gm = [0.10, 0.12, 0.14, 0.16, 0.20, 0.24, 0.28, 0.32]  # 一路走高,TTM>历史
        f = self._f(gm, rev_growth=0.15)  # 每季+15%→同比约+75%
        self.assertTrue(S.sig_s1super(f, "2030-01-01"))
        # S1(要求TTM<历史)应为False
        self.assertFalse(S.sig_s1(f, "2030-01-01"))


class TestCuratePass(unittest.TestCase):
    def test_s1_only_lumpy(self):
        # S1: 只看非一次性,不看盈利/估值
        self.assertTrue(curate_pass({"S1"}, profitable=False, lumpy=False, val_ok=False))
        self.assertFalse(curate_pass({"S1"}, profitable=True, lumpy=True, val_ok=True))

    def test_s2a_only_profit(self):
        # S2a: 只看要求盈利,不看非一次性
        self.assertTrue(curate_pass({"S2a"}, profitable=True, lumpy=True, val_ok=False))
        self.assertFalse(curate_pass({"S2a"}, profitable=False, lumpy=False, val_ok=True))

    def test_s2b_only_valuation(self):
        # S2b: 只看估值,不看盈利
        self.assertTrue(curate_pass({"S2b"}, profitable=False, lumpy=True, val_ok=True))
        self.assertFalse(curate_pass({"S2b"}, profitable=True, lumpy=False, val_ok=False))

    def test_multi_signal_all_apply(self):
        # 多信号: 各自闸门都要过
        self.assertTrue(curate_pass({"S1超", "S2b"}, profitable=True, lumpy=False, val_ok=True))
        self.assertFalse(curate_pass({"S1超", "S2b"}, profitable=True, lumpy=True, val_ok=True))  # S1超要非一次性




if __name__ == "__main__":
    unittest.main(verbosity=2)
