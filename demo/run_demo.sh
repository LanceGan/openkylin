#!/usr/bin/env bash
# =============================================================================
# KylinBootLab 一键复现脚本
#
# 用 demo/sample-run/ 里的一份真实 openKylin 冷启动探针数据，完整跑一遍
# 「数据采集入库 → 基线报告 → 因果图瓶颈分析 → 优化候选排序」闭环。
#
# 用法（在仓库根目录执行）：
#     bash demo/run_demo.sh
#
# 前提：
#     - 已安装 uv（winget install --id astral-sh.uv）
#     - uv 可用 Python 3.12（uv python install 3.12）
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/src"

# 独立的 demo 数据根，避免污染真实采集数据；每次运行前清空，保证可重复
DATA_ROOT="var/demo-runs"
rm -rf "$DATA_ROOT"

echo "======================================================================"
echo "  KylinBootLab 一键复现  ingest → report → analyze → optimize plan"
echo "======================================================================"
echo ""

echo "[1/4] 导入样例数据包 demo/sample-run ..."
RUN_ID="$(uv run kbl ingest ../demo/sample-run --data-root "$DATA_ROOT")"
echo "      run_id = ${RUN_ID}"
echo ""

echo "[2/4] 生成基线报告 ..."
uv run kbl report "$RUN_ID" --data-root "$DATA_ROOT"
echo ""

echo "[3/4] 因果图 + 瓶颈分析 ..."
uv run kbl analyze "$RUN_ID" --data-root "$DATA_ROOT"
echo ""

echo "[4/4] 优化候选方案排序 ..."
uv run kbl optimize plan "$RUN_ID" --data-root "$DATA_ROOT"
echo ""

echo "======================================================================"
echo "  完成。"
echo "  基线 HTML 报告：${DATA_ROOT}/${RUN_ID}/reports/baseline.html"
echo "  瓶颈报告 JSON：${DATA_ROOT}/${RUN_ID}/derived/bottleneck-report.json"
echo "  因果图 JSON  ：${DATA_ROOT}/${RUN_ID}/derived/causal-graph.json"
echo "======================================================================"
