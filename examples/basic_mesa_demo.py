#!/usr/bin/env python3
"""
MESA引擎完整演示
展示MESA引擎核心功能和交易所适配层的集成使用
"""

import structlog
from core.events.event import (
    Event, TickerUpdatedEvent, OrderFilledEvent, ComponentStartedEvent,
    OrderCreatedEvent, OrderCancelledEvent, ComponentStoppedEvent,
    ErrorOccurredEvent, HealthCheckEvent
)
from core.exchanges.models import ExchangeType
from core.exchanges.interface import ExchangeConfig
from core.exchanges.factory import ExchangeFactory
from core.exchanges.manager import ExchangeManager
from core.engine import MESAEngine
import asyncio
import sys
import os
from decimal import Decimal

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 配置日志
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def demo_mesa_engine_basic():
    """演示MESA引擎基础功能"""
    logger.info("🚀 演示MESA引擎基础功能")

    # 创建MESA引擎
    engine = MESAEngine("demo_engine")

    try:
        # 启动引擎
        await engine.start()
        logger.info("✅ MESA引擎启动成功")

        # 获取引擎状态
        status = engine.get_status()
        logger.info(f"📊 引擎状态: {status}")

        # 演示事件系统
        logger.info("📡 演示事件系统")

        # 创建一个简单的事件处理器
        def event_handler(event):
            logger.info(f"收到事件: {event.event_type} - {event.metadata}")

        # 订阅事件（使用事件类）
        engine.event_bus.subscribe(ComponentStartedEvent, event_handler)

        # 发布一个测试事件
        test_event = ComponentStartedEvent(
            component="demo_component",
            metadata={"message": "这是一个测试事件", "status": "testing"}
        )
        await engine.event_bus.publish(test_event)

        # 等待事件处理
        await asyncio.sleep(0.1)

        # 健康检查
        health = await engine.health_check()
        logger.info(f"🔍 健康检查: {health['status']}")

        # 获取引擎指标
        metrics = engine.get_metrics()
        logger.info(f"📈 引擎指标: {metrics}")

    finally:
        # 停止引擎
        await engine.stop()
        logger.info("🛑 MESA引擎已停止")


async def demo_exchange_integration():
    """演示交易所适配层集成"""
    logger.info("🔗 演示交易所适配层集成")

    # 创建MESA引擎
    engine = MESAEngine("exchange_demo_engine")

    try:
        # 启动引擎
        await engine.start()

        # 获取交易所管理器（如果引擎中有的话）
        # 注意：这里我们创建一个独立的交易所管理器用于演示
        exchange_manager = ExchangeManager(engine.event_bus)
        factory = ExchangeFactory()

        # 配置演示用的交易所
        demo_configs = {
            'binance': ExchangeConfig(
                exchange_id='binance',
                name='Binance Demo',
                exchange_type=ExchangeType.FUTURES,
                api_key='demo_api_key',
                api_secret='demo_api_secret',
                testnet=True
            ),
            'hyperliquid': ExchangeConfig(
                exchange_id='hyperliquid',
                name='Hyperliquid Demo',
                exchange_type=ExchangeType.PERPETUAL,
                api_key='demo_api_key',
                api_secret='demo_api_secret',
                testnet=True
            )
        }

        # 注册交易所
        for exchange_id, config in demo_configs.items():
            try:
                exchange_manager.register_exchange(exchange_id, config)
                logger.info(f"✅ 注册交易所: {exchange_id}")
            except Exception as e:
                logger.warning(f"⚠️ 跳过交易所 {exchange_id}: {e}")

        # 启动交易所管理器
        await exchange_manager.start()
        logger.info("✅ 交易所管理器启动完成")

        # 演示交易所功能
        exchange_ids = exchange_manager.get_registered_exchanges()
        logger.info(f"📋 已注册的交易所: {exchange_ids}")

        # 健康检查
        health_report = await exchange_manager.health_check_all()
        logger.info(f"🔍 交易所健康检查: {health_report}")

        # 演示事件集成
        logger.info("📡 演示交易所事件集成")

        def market_data_handler(event):
            logger.info(f"收到市场数据事件: {event.event_type}")

        def order_handler(event):
            logger.info(f"收到订单事件: {event.event_type}")

        # 订阅交易相关事件
        engine.event_bus.subscribe(TickerUpdatedEvent, market_data_handler)
        engine.event_bus.subscribe(OrderFilledEvent, order_handler)

        # 模拟一些事件
        market_event = TickerUpdatedEvent(
            symbol="BTC/USDT",
            exchange="binance",
            last=Decimal("50000"),
            volume=Decimal("1.5"),
            bid=Decimal("49999"),
            ask=Decimal("50001")
        )
        await engine.event_bus.publish(market_event)

        order_event = OrderFilledEvent(
            order_id="demo_order_123",
            symbol="BTC/USDT",
            exchange="binance",
            side="buy",
            amount=Decimal("0.1"),
            filled_amount=Decimal("0.1"),
            filled_price=Decimal("50000")
        )
        await engine.event_bus.publish(order_event)

        # 等待事件处理
        await asyncio.sleep(0.2)

        # 停止交易所管理器
        await exchange_manager.stop()
        logger.info("✅ 交易所管理器已停止")

    finally:
        # 停止引擎
        await engine.stop()
        logger.info("🛑 MESA引擎已停止")


async def demo_complete_workflow():
    """演示完整工作流程"""
    logger.info("🎯 演示完整工作流程")

    # 创建MESA引擎
    engine = MESAEngine("complete_workflow_engine")

    try:
        # 启动引擎
        await engine.start()
        logger.info("✅ MESA引擎启动成功")

        # 创建交易所管理器
        exchange_manager = ExchangeManager(engine.event_bus)

        # 配置真实的交易所（演示配置）
        exchange_configs = {
            'binance': ExchangeConfig(
                exchange_id='binance',
                name='Binance',
                exchange_type=ExchangeType.FUTURES,
                api_key='your_api_key_here',
                api_secret='your_api_secret_here',
                testnet=True  # 使用测试网
            )
        }

        # 注册交易所
        for exchange_id, config in exchange_configs.items():
            exchange_manager.register_exchange(exchange_id, config)
            logger.info(f"✅ 配置交易所: {exchange_id}")

        # 设置综合事件处理器
        def comprehensive_event_handler(event):
            event_data = {
                'type': event.event_type,
                'timestamp': event.timestamp.isoformat(),
                'source': getattr(event, 'source', 'unknown')
            }

            # 根据事件类型添加特定信息
            if hasattr(event, 'symbol'):
                event_data['symbol'] = event.symbol
            if hasattr(event, 'price'):
                event_data['price'] = str(event.price)
            if hasattr(event, 'status'):
                event_data['status'] = event.status

            logger.info(f"📡 事件: {event_data}")

        # 订阅所有主要事件类型
        event_types = [
            TickerUpdatedEvent,
            OrderFilledEvent,
            OrderCreatedEvent,
            OrderCancelledEvent,
            ComponentStartedEvent,
            ComponentStoppedEvent,
            ErrorOccurredEvent,
            HealthCheckEvent
        ]

        for event_type in event_types:
            engine.event_bus.subscribe(event_type, comprehensive_event_handler)

        # 启动交易所管理器
        await exchange_manager.start()
        logger.info("✅ 交易所管理器启动完成")

        # 演示完整的数据流
        logger.info("📊 演示数据流和事件处理")

        # 模拟一系列交易事件
        events_to_simulate = [
            TickerUpdatedEvent(
                symbol="BTC/USDT",
                exchange="binance",
                last=Decimal("51000"),
                volume=Decimal("100.5"),
                bid=Decimal("50999"),
                ask=Decimal("51001")
            ),
            OrderFilledEvent(
                order_id="order_001",
                symbol="BTC/USDT",
                exchange="binance",
                side="buy",
                amount=Decimal("0.05"),
                filled_amount=Decimal("0.05"),
                filled_price=Decimal("51000")
            ),
            TickerUpdatedEvent(
                symbol="ETH/USDT",
                exchange="binance",
                last=Decimal("3200"),
                volume=Decimal("50.2"),
                bid=Decimal("3199"),
                ask=Decimal("3201")
            )
        ]

        # 发布事件
        for event in events_to_simulate:
            await engine.event_bus.publish(event)
            await asyncio.sleep(0.1)  # 短暂延迟以观察事件处理

        # 等待所有事件处理完成
        await asyncio.sleep(0.5)

        # 最终状态检查
        logger.info("🔍 最终状态检查")

        # 引擎健康检查
        engine_health = await engine.health_check()
        logger.info(f"🏥 引擎健康状态: {engine_health['status']}")

        # 交易所健康检查
        exchange_health = await exchange_manager.health_check_all()
        logger.info(f"🏥 交易所健康状态: {len(exchange_health)} 个交易所")

        # 引擎指标
        metrics = engine.get_metrics()
        logger.info(f"📈 最终指标: {metrics}")

        # 停止交易所管理器
        await exchange_manager.stop()
        logger.info("✅ 交易所管理器已停止")

    finally:
        # 停止引擎
        await engine.stop()
        logger.info("🛑 MESA引擎已停止")


async def main():
    """主演示函数"""
    logger.info("🎉 开始MESA引擎完整演示")

    try:
        # 1. 基础引擎功能演示
        await demo_mesa_engine_basic()
        await asyncio.sleep(1)

        # 2. 交易所集成演示
        await demo_exchange_integration()
        await asyncio.sleep(1)

        # 3. 完整工作流程演示
        await demo_complete_workflow()

        logger.info("✨ 所有演示完成！")

    except Exception as e:
        logger.error(f"❌ 演示过程中发生错误: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
