#!/bin/bash
# 刷量交易快速启动脚本

echo "======================================================"
echo "🎯 刷量交易系统启动脚本"
echo "======================================================"
echo ""

# 检查配置文件
CONFIG_FILE="config/volume_maker/backpack_btc_volume_maker.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ 错误: 配置文件不存在 - $CONFIG_FILE"
    exit 1
fi

echo "✅ 配置文件: $CONFIG_FILE"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3"
    exit 1
fi

echo "✅ Python版本: $(python3 --version)"
echo ""

# 检查依赖
echo "🔍 检查依赖包..."
python3 -c "import rich, yaml, aiohttp" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  缺少依赖包，正在安装..."
    pip3 install -r requirements.txt
fi
echo "✅ 依赖包完整"
echo ""

# 启动程序
echo "🚀 启动刷量交易系统..."
echo ""
python3 run_volume_maker.py "$CONFIG_FILE"

echo ""
echo "======================================================"
echo "👋 程序已退出"
echo "======================================================"

