# scanner/ 目录结构

暴涨机会捕捉框架的扫描器与回测工具链。

## 代码（根目录）
| 文件 | 作用 |
|---|---|
| **signals.py** | ⭐ 信号定义唯一真源(S1/S1超/S2a/S2b);回测与实时扫描共用 |
| scan.py | 实时扫描器。`live`=用signals.py判定当前信号;`report/deep/prices/track/audit` |
| backtest.py | PIT历史回测引擎(EDGAR filed防前视 + yfinance价) |
| earnings_entry.py | 财报次日入场回测(最忠实复现"财报后第二天追入") |
| momentum.py | 动量领先指标回测 |
| curation.py | curation规则(估值/质量/非一次性)精度回测 |

## 常用命令
```bash
python scan.py live              # ⭐实时信号扫描(与回测同定义)→ signals_live.md
python scan.py universe          # 拉全universe(≥$5B)
python scan.py scan / report     # yfinance逐票扫描 + 富展示报告
python scan.py deep --tickers X  # 深度卷宗(价格位置/估值/EPS修正)
python scan.py track --action grade   # 决策记分卡打分
python scan.py audit             # 流水线体检+缺口自问
python backtest.py --signals --anchors ... --horizons ...   # 多信号回测
```

## 数据文件（根目录，代码读写）
- universe.csv 全universe ｜ results.csv yfinance字段 ｜ edgar_rev.csv EDGAR营收
- backtest_perticker.csv 回测逐票结果 ｜ signals_live.md/signals.md/deep.md 扫描输出
- lessons.md 教训台账(纠错回路) ｜ scorecard.csv 决策记分卡
- cache/ EDGAR+价格磁盘缓存(gitignore,回测秒级复用)

## 文档
- **docs/信号定义.md** — 四信号精确定义
- **docs/findings/** — 回测发现(backtest-findings 主结论 / momentum-findings / 漏网分析)
- **docs/winners/** — 大牛股分析(17只/666/827/财报次日,含收益/最大浮亏/最大回撤)
- **theses/** — 个股论点卡+深度研究(ALNY/MCHP/RDDT等)

## 核心结论(见 docs/findings/backtest-findings.md)
筛选层=合格召回工具(基本面赢家82%),但无机械alpha(平均≈市场);
curation规则=风控(降暴雷不生alpha);价值依赖判断层(只能forward验证)。
