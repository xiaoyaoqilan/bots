#!/bin/bash
# ==============================================================================
# Lighter市价刷量系统 - 快速启动脚本
# ==============================================================================

echo "======================================================================="
echo "  🎯 Lighter市价刷量系统（多信号源支持）"
echo "======================================================================="
echo ""

# 检查Python版本
python3 --version || {
    echo "❌ Python3未安装，请先安装Python 3.9+"
    exit 1
}

# 检查配置文件
CONFIG_FILE="config/volume_maker/lighter_volume_maker.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ 配置文件不存在: $CONFIG_FILE"
    echo "请先创建配置文件"
    exit 1
fi

echo "✅ 配置文件检查通过"
echo ""

# 检查信号源配置（Backpack 或 Hyperliquid）
SIGNAL_EXCHANGE=$(grep -A 1 "signal_exchange:" "$CONFIG_FILE" | tail -n 1 | sed 's/.*"\(.*\)".*/\1/' | tr -d ' ')
if [ -z "$SIGNAL_EXCHANGE" ]; then
    SIGNAL_EXCHANGE="backpack"
fi

echo "信号源交易所: $SIGNAL_EXCHANGE"

if [ "$SIGNAL_EXCHANGE" = "backpack" ]; then
    SIGNAL_CONFIG="config/exchanges/backpack_config.yaml"
elif [ "$SIGNAL_EXCHANGE" = "hyperliquid" ]; then
    SIGNAL_CONFIG="config/exchanges/hyperliquid_config.yaml"
else
    echo "❌ 不支持的信号源: $SIGNAL_EXCHANGE"
    exit 1
fi

if [ ! -f "$SIGNAL_CONFIG" ]; then
    echo "⚠️  警告: 信号源配置不存在: $SIGNAL_CONFIG"
    echo "系统将无法监控信号"
fi

# 检查Lighter配置
LIGHTER_CONFIG="config/exchanges/lighter_config.yaml"
if [ ! -f "$LIGHTER_CONFIG" ]; then
    echo "⚠️  警告: Lighter配置不存在: $LIGHTER_CONFIG"
    echo "系统将无法执行交易"
fi

echo ""
echo "🚀 启动Lighter市价刷量系统..."
echo ""

# 启动系统
python3 run_lighter_volume_maker.py "$CONFIG_FILE"

