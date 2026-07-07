# 暴涨机会捕捉框架（Investing Playbook + Scanner）

基于 2017–2026 年美股 5B+ 市值暴涨案例复盘建立的投资框架与全域扫描流水线。
建立于 2026-07-06（与 Claude 协作完成）。

## 内容

```
暴涨机会捕捉框架-playbook.md   框架宪法：五筛选器、扫描节奏、组合规则、季度快照
scanner/
  scan.py                     扫描器（五命令，见下）
  universe.csv                全域清单（2,127 家 ≥$5B，Finviz）
  results.csv                 逐票字段数据（yfinance 季度财务）
  edgar_rev.csv               SEC EDGAR 完整营收历史补充（S2b 加速确认）
  signals.md                  信号报告（S1 周期反转 / S2a 首次盈利 / S2b 营收加速 + 确认层任务清单）
  deep.md                     深度卷宗（价格位置/估值/EPS修正/财报日/空头占比）
  theses/                     个股论点卡（论点/三情景/分批/KPI/否决条件/决断日）
```

## 流水线（每季度财报季后运行一次）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 首次
cd scanner
../.venv/bin/python scan.py universe   # 1. 拉全域清单（~5分钟）
../.venv/bin/python scan.py scan       # 2. 逐票扫描（~1小时，断点续传）
../.venv/bin/python scan.py edgar      # 3. EDGAR 补全 S2b 历史（~5分钟）
../.venv/bin/python scan.py report     # 4. 生成 signals.md
../.venv/bin/python scan.py deep --tickers AAA,BBB   # 5. 命中者深度卷宗
```

重跑前把 `universe.csv`、`results.csv`、`edgar_rev.csv` 归档或删除（断点续传会跳过已扫描的票）。

## 四层漏斗

1. **全域初筛**（scan）：通用字段，1374 家 → ~90 家
2. **历史确认**（edgar）：完整季度史修正短历史盲区
3. **深度卷宗**（deep）：价格位置防"买已涨完的对的东西"、EPS修正方向、决断日
4. **质化确认**（人工/AI）：sector 特有 KPI 逐票核实（signals.md 尾部有任务清单）→ 论点卡

## 免责

个人研究工具，数据来自免费源（Finviz/yfinance/SEC EDGAR），有延迟与缺失，入场决策前关键数字需财报原文交叉核对。不构成投资建议。
