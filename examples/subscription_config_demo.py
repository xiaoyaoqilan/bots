#!/usr/bin/env python3
"""
订阅配置演示脚本

展示如何使用新的灵活订阅配置功能，让用户可以选择：
- 只订阅ticker数据
- 只订阅orderbook数据
- 同时订阅两种数据
- 自定义订阅策略
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from injector import Injector
from core.di.container import DIContainer
from core.di.modules import ALL_MODULES
from core.services.interfaces.monitoring_service import (
    MonitoringService, SubscriptionStrategy, ExchangeSubscriptionConfig
)
# 使用统一日志系统
from core.logging import get_logger


async def demo_ticker_only_strategy():
    """演示：只订阅ticker数据策略"""
    print("🔍 演示：只订阅ticker数据策略")
    print("=" * 50)
    
    # 初始化DI容器
    di_container = DIContainer()
    for module in ALL_MODULES:
        di_container.register_module(module)
    
    # 获取服务
    monitoring_service = di_container.injector.get(MonitoringService)
    logger = get_logger("SubscriptionDemo")
    
    # 配置EdgeX只订阅ticker数据
    edgex_config = ExchangeSubscriptionConfig(
        exchange_id="edgex",
        strategy=SubscriptionStrategy.TICKER_ONLY,
        ticker_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],  # 只指定ticker订阅的交易对
        enabled=True
    )
    
    # 应用配置
    await monitoring_service.configure_exchange_subscription(edgex_config)
    
    # 查看配置结果
    status = await monitoring_service.get_subscription_status()
    print(f"📊 EdgeX配置结果: {status.get('edgex', {})}")
    
    print("✅ 优势：资源消耗少，适合只需要价格信息的场景")
    print("❌ 限制：无法获取bid/ask信息，无法进行深度分析")
    print()


async def demo_orderbook_only_strategy():
    """演示：只订阅orderbook数据策略"""
    print("🔍 演示：只订阅orderbook数据策略")
    print("=" * 50)
    
    # 初始化DI容器
    di_container = DIContainer()
    for module in ALL_MODULES:
        di_container.register_module(module)
    
    # 获取服务
    monitoring_service = di_container.injector.get(MonitoringService)
    
    # 配置EdgeX只订阅orderbook数据
    edgex_config = ExchangeSubscriptionConfig(
        exchange_id="edgex",
        strategy=SubscriptionStrategy.ORDERBOOK_ONLY,
        orderbook_symbols=["BTCUSDT", "ETHUSDT"],  # 只指定orderbook订阅的交易对
        enabled=True
    )
    
    # 应用配置
    await monitoring_service.configure_exchange_subscription(edgex_config)
    
    # 查看配置结果
    status = await monitoring_service.get_subscription_status()
    print(f"📊 EdgeX配置结果: {status.get('edgex', {})}")
    
    print("✅ 优势：获取详细的买卖盘信息，适合套利分析")
    print("❌ 限制：无法获取历史价格变化，数据量较大")
    print()


async def demo_both_strategy():
    """演示：同时订阅ticker和orderbook数据策略"""
    print("🔍 演示：同时订阅ticker和orderbook数据策略")
    print("=" * 50)
    
    # 初始化DI容器
    di_container = DIContainer()
    for module in ALL_MODULES:
        di_container.register_module(module)
    
    # 获取服务
    monitoring_service = di_container.injector.get(MonitoringService)
    
    # 配置Backpack同时订阅两种数据
    backpack_config = ExchangeSubscriptionConfig(
        exchange_id="backpack",
        strategy=SubscriptionStrategy.BOTH,
        ticker_symbols=["SOL_USDC_PERP", "BTC_USDC_PERP", "ETH_USDC_PERP"],
        orderbook_symbols=["SOL_USDC_PERP", "BTC_USDC_PERP", "ETH_USDC_PERP"],
        enabled=True
    )
    
    # 应用配置
    await monitoring_service.configure_exchange_subscription(backpack_config)
    
    # 查看配置结果
    status = await monitoring_service.get_subscription_status()
    print(f"📊 Backpack配置结果: {status.get('backpack', {})}")
    
    print("✅ 优势：数据完整，适合全面分析和套利监控")
    print("❌ 限制：资源消耗大，适合高性能场景")
    print()


async def demo_custom_strategy():
    """演示：自定义订阅策略"""
    print("🔍 演示：自定义订阅策略")
    print("=" * 50)
    
    # 初始化DI容器
    di_container = DIContainer()
    for module in ALL_MODULES:
        di_container.register_module(module)
    
    # 获取服务
    monitoring_service = di_container.injector.get(MonitoringService)
    
    # 配置自定义策略：为不同交易对使用不同的订阅类型
    custom_config = ExchangeSubscriptionConfig(
        exchange_id="edgex",
        strategy=SubscriptionStrategy.CUSTOM,
        ticker_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"],  # 主要交易对订阅ticker
        orderbook_symbols=["BTCUSDT", "ETHUSDT"],  # 只为BTC和ETH订阅orderbook（套利分析）
        enabled=True
    )
    
    # 应用配置
    await monitoring_service.configure_exchange_subscription(custom_config)
    
    # 查看配置结果
    status = await monitoring_service.get_subscription_status()
    print(f"📊 EdgeX自定义配置结果: {status.get('edgex', {})}")
    
    print("✅ 优势：灵活配置，资源利用最优化")
    print("🎯 适用场景：精确控制订阅，满足特定业务需求")
    print()


async def demo_dynamic_subscription_changes():
    """演示：动态订阅变更"""
    print("🔍 演示：动态订阅变更")
    print("=" * 50)
    
    # 初始化DI容器
    di_container = DIContainer()
    for module in ALL_MODULES:
        di_container.register_module(module)
    
    # 获取服务
    monitoring_service = di_container.injector.get(MonitoringService)
    
    # 初始配置：只订阅ticker
    print("1️⃣ 初始配置：只订阅ticker")
    await monitoring_service.subscribe_ticker("edgex", ["BTCUSDT"])
    
    # 动态添加orderbook订阅
    print("2️⃣ 动态添加orderbook订阅")
    await monitoring_service.subscribe_orderbook("edgex", ["BTCUSDT"])
    
    # 添加更多ticker订阅
    print("3️⃣ 添加更多ticker订阅")
    await monitoring_service.subscribe_ticker("edgex", ["ETHUSDT", "SOLUSDT"])
    
    # 查看最终状态
    status = await monitoring_service.get_subscription_status()
    print(f"📊 最终订阅状态: {status.get('edgex', {})}")
    
    print("✅ 优势：运行时动态调整，响应业务变化")
    print()


async def demo_real_world_scenarios():
    """演示：实际应用场景"""
    print("🔍 演示：实际应用场景")
    print("=" * 50)
    
    print("📈 场景1：价格监控系统")
    print("   - 策略：TICKER_ONLY")
    print("   - 适用：价格报警、趋势分析")
    print("   - 资源消耗：低")
    print()
    
    print("💰 场景2：套利交易系统")
    print("   - 策略：BOTH")
    print("   - 适用：跨交易所套利、深度分析")
    print("   - 资源消耗：高")
    print()
    
    print("🎯 场景3：做市商系统")
    print("   - 策略：ORDERBOOK_ONLY")
    print("   - 适用：流动性提供、价差分析")
    print("   - 资源消耗：中等")
    print()
    
    print("🔧 场景4：研究分析系统")
    print("   - 策略：CUSTOM")
    print("   - 适用：特定交易对深度分析")
    print("   - 资源消耗：可控")
    print()


def print_configuration_guide():
    """打印配置指南"""
    print("📚 配置指南")
    print("=" * 50)
    
    print("🔧 1. 在代码中配置：")
    print("""
    from core.services.interfaces.monitoring_service import (
        SubscriptionStrategy, ExchangeSubscriptionConfig
    )
    
    # 创建配置
    config = ExchangeSubscriptionConfig(
        exchange_id="backpack",
        strategy=SubscriptionStrategy.BOTH,
        ticker_symbols=["SOL_USDC_PERP"],
        orderbook_symbols=["SOL_USDC_PERP"],
        enabled=True
    )
    
    # 应用配置
    await monitoring_service.configure_exchange_subscription(config)
    """)
    
    print("🔧 2. 动态订阅：")
    print("""
    # 订阅ticker
    await monitoring_service.subscribe_ticker("edgex", ["BTCUSDT"])
    
    # 订阅orderbook
    await monitoring_service.subscribe_orderbook("edgex", ["BTCUSDT"])
    
    # 查看状态
    status = await monitoring_service.get_subscription_status()
    """)
    
    print("✅ 3. 最佳实践：")
    print("   - 根据业务需求选择合适的策略")
    print("   - 避免过度订阅，控制资源消耗")
    print("   - 使用自定义策略精确控制订阅")
    print("   - 监控订阅状态，及时调整配置")
    print()


async def main():
    """主函数"""
    print("🚀 交易策略系统 - 灵活订阅配置演示")
    print("=" * 70)
    print()
    
    # 注意：以下演示只是配置演示，不会实际连接WebSocket
    print("📝 注意：这些是配置演示，不会实际连接到交易所")
    print()
    
    # 演示不同的订阅策略
    await demo_ticker_only_strategy()
    await demo_orderbook_only_strategy()
    await demo_both_strategy()
    await demo_custom_strategy()
    await demo_dynamic_subscription_changes()
    await demo_real_world_scenarios()
    
    # 打印配置指南
    print_configuration_guide()
    
    print("🎯 总结：")
    print("   - 接口提供功能，用户选择使用")
    print("   - ticker和orderbook完全独立")
    print("   - 支持灵活的订阅策略配置")
    print("   - 支持运行时动态调整")
    print("   - 资源消耗可控，按需订阅")
    print()
    print("✅ 这样的设计符合单一职责原则，给用户最大的灵活性！")


if __name__ == "__main__":
    asyncio.run(main()) 