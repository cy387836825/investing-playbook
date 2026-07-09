# 代码审查与清理记录（2026-07-09）

## 死代码清理（已完成）
快速迭代中积累的 legacy 回测函数,已被 `backtest_signals`(财报次日/多锚点/信号专属)取代,全部移除:
| 移除 | 原因 |
|---|---|
| `backtest()` 单锚点v1 | 首版,用慢速非缓存路径,从未实用 |
| `backtest_multi()` v2 | S2b-only多锚点,被backtest_signals取代 |
| `_price_on` / `_pit_quarterly_rev` | 仅服务已删的backtest() |
| `_fetch_facts` | 仅服务已删的backtest_multi() |
| `_pit_from_units` | 仅backtest_multi用+curation死import |
| `_pit_qseries`(重复) / `_yoy`(重复) | 与signals.py字节相同,改为`from signals import`别名 |

**backtest.py: 484 → 245 行**。__main__ 简化为唯一入口 `backtest_signals`。
去重后 signals.py 是所有信号/PIT逻辑的唯一真源(backtest/curation/scan 均从此导入)。

## 修复的真bug
- **市值单位不一致**: `scan.py`用`/1e6`修正universe市值,`assemble_viz.py`误用`/1e9`(差1000倍)。
  验证: NVDA universe值4732310000, /1e6=4732(十亿,正确) vs /1e9=4.73(错)。
  已修assemble_viz为/1e6。属潜伏bug(该mcap列未在页面显示,故未暴露)。

## 已知代码异味（非bug,留记录）
- `assemble_viz.py`/`build_site.py` 无 `if __name__=='__main__'` 守卫,import即执行整个pipeline。
  影响小(仅手动运行的build脚本,生产不import);若纳入更大工程需加守卫。
- 两处 `_lumpy` 实现: `curation._lumpy`(flips≥2,curation闸门用) vs `scan._lumpy_flag`(flips≥2 或 cv>1.5,report展示用)。
  阈值不同但用途不同(gate vs display),非bug;若要统一以curation版为准(已验证)。

## 测试覆盖（test_signals.py, 20个)
- pit_qseries: 需≥6季/PIT过滤未来filed/最新在前/重述取最新filed/忽略非季度
- yoy: 基本同比/越界返回None
- 四信号 sig_s1/s1super/s2a/s2b: 正例反例各覆盖
- curate_pass 信号专属: S1只非一次性/S2a只要求盈利/S2b只估值/多信号各闸门叠加
运行: `python test_signals.py` 或 `python -m pytest test_signals.py -q`
