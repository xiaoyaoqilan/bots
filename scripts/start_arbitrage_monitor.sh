#!/bin/bash
# 套利监控系统启动脚本

echo "========================================"
echo "🎯 套利监控系统 - 启动中..."
echo "========================================"

cd "$(dirname "$0")/.."

if [ ! -f "config/arbitrage/monitor.yaml" ]; then
    echo "❌ 配置文件不存在: config/arbitrage/monitor.yaml"
    exit 1
fi

mkdir -p logs

echo ""
echo "🚀 启动套利监控系统..."
echo "📝 日志: logs/arbitrage_monitor.log"
echo "⏹️  停止: Ctrl+C"
echo ""

python3 run_arbitrage_monitor.py

echo ""
echo "✅ 套利监控系统已停止"

