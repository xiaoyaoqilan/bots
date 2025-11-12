#!/bin/bash

echo "🛑 停止所有网格交易系统..."

# 停止所有grid会话
tmux kill-session -t grid_btc 2>/dev/null && echo "✅ BTC网格已停止" || echo "⚠️  BTC网格未运行"
tmux kill-session -t grid_eth 2>/dev/null && echo "✅ ETH网格已停止" || echo "⚠️  ETH网格未运行"
tmux kill-session -t grid_sol 2>/dev/null && echo "✅ SOL网格已停止" || echo "⚠️  SOL网格未运行"

echo ""
echo "✅ 所有网格已停止！"
