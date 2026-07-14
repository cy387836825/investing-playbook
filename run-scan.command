#!/bin/bash
# 双击运行:用今天的数据跑当日实时漏斗 → 把新快照内联进 live.html → 打开页面。
# 全程无需常驻 server。进度在本终端窗口里显示(约1-2分钟,会先拉当日 Finviz universe)。
cd "$(dirname "$0")/scanner" || { echo "找不到 scanner 目录"; exit 1; }
PY="../.venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "======================================================"
echo " 当日实时扫描  (先拉 Finviz universe,再全量扫,约1-2分钟)"
echo "======================================================"
"$PY" live_funnel.py
rc=$?
echo "------------------------------------------------------"
if [ $rc -eq 0 ]; then
  echo "完成 → 打开 site/live.html"
  open "../site/live.html"
else
  echo "扫描出错(退出码 $rc)。上面有报错信息;网络不通时 Finviz 刷新会卡,"
  echo "可改用免刷新快跑:  $PY live_funnel.py --no-refresh"
fi
echo ""
echo "(此窗口可关闭)"
