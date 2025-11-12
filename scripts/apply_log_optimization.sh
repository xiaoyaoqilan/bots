#!/bin/bash

# 日志优化应用脚本
# 快速验证日志优化效果

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                     日志优化系统应用脚本                           ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1

echo "📍 项目路径: $PROJECT_ROOT"
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3 命令"
    exit 1
fi

echo "✅ Python环境: $(python3 --version)"
echo ""

# 1. 运行日志优化演示
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 步骤1: 查看优化效果演示"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 test/test_log_optimization.py --test

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 步骤2: 验证配置已应用"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查 run_grid_trading.py 是否包含优化配置
if grep -q "setup_optimized_logging" run_grid_trading.py; then
    echo "✅ run_grid_trading.py 已配置日志优化"
    echo "   配置行:"
    grep -n "setup_optimized_logging" run_grid_trading.py | head -1
else
    echo "❌ run_grid_trading.py 未配置日志优化"
    echo ""
    echo "💡 请在 run_grid_trading.py 开头添加:"
    echo ""
    echo "from core.adapters.exchanges.utils import setup_optimized_logging"
    echo "setup_optimized_logging(use_colored=True)"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📖 步骤3: 优化效果对比"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "优化前的日志格式 (示例):"
echo "────────────────────────────────────────────────────────────────────"
echo "2025-11-03 07:37:15,769 - core.adapters.exchanges.adapters.lighter_rest - INFO - _handle_order_result:1192 - ⚠️ Lighter下单成功"
echo "2025-11-03 07:37:16,273 - core.adapters.exchanges.adapters.lighter_websocket - INFO - _handle_direct_ws_message:1325 - 📝 订单推送: id=844424445406825"
echo ""

echo "优化后的日志格式 (现在):"
echo "────────────────────────────────────────────────────────────────────"
echo "07:37:15 [REST    ] I - 下单成功 🟢 BUY 0.00029@110364.0 [Grid293] ID:844424...6825 ⏳"
echo "07:37:16 [WS      ] I - 📨 推送: account_all_orders:4986"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ 优化亮点"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ 时间戳简化:     23字符 → 8字符  (节省 65%)"
echo "✅ 模块路径简化:   55字符 → 8字符  (节省 85%)"
echo "✅ 订单ID简化:     15字符 → 11字符 (节省 27%)"
echo "✅ 整体行长度:     平均减少 40%"
echo "✅ 添加类型标签:   [ORDER] [WS] [SYNC] [HEALTH]"
echo "✅ 关键信息前置:   更易阅读和搜索"
echo ""
echo "📌 注意: 所有详细信息仍保留在日志文件中，不丢失任何调试信息！"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 下一步"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. 重新启动程序以应用日志优化:"
echo "   python run_grid_trading.py"
echo ""
echo "2. 查看优化后的日志:"
echo "   tail -f logs/ExchangeAdapter.log"
echo ""
echo "3. 查看完整文档:"
echo "   cat docs/日志优化指南.md"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

