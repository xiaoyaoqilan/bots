#!/bin/bash

echo "🚀 启动所有网格交易系统..."

# 检查tmux是否安装
if ! command -v tmux &> /dev/null; then
    echo "❌ tmux未安装，请先安装: brew install tmux"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 启动BTC网格
echo "📊 启动BTC网格..."
tmux new -s grid_btc -d "cd $SCRIPT_DIR && python run_grid_trading.py --config config/grid/backpack_long_grid.yaml"

# 等待1秒
sleep 1

# 启动ETH网格
echo "📊 启动ETH网格..."
tmux new -s grid_eth -d "cd $SCRIPT_DIR && python run_grid_trading.py --config config/grid/backpack_eth_long_grid.yaml"

# 等待1秒
sleep 1

# 启动SOL网格
echo "📊 启动SOL网格..."
tmux new -s grid_sol -d "cd $SCRIPT_DIR && python run_grid_trading.py --config config/grid/backpack_sol_long_grid.yaml"

echo ""
echo "✅ 所有网格已启动！"
echo ""
echo "查看运行状态："
echo "  tmux ls"
echo ""
echo "连接到某个网格："
echo "  tmux attach -t grid_btc"
echo "  tmux attach -t grid_eth"
echo "  tmux attach -t grid_sol"
echo ""
echo "停止所有网格："
echo "  ./stop_all_grids.sh"
