"""
交易所订阅模式系统演示脚本

这个脚本展示了如何使用新的订阅模式系统：
1. 硬编码模式 - 使用预定义交易对
2. 动态模式 - 自动发现交易对
3. 混合订阅 - 支持任意组合
4. 自定义过滤器 - 灵活的过滤条件

支持的交易所：Hyperliquid、Backpack、EdgeX
"""

import asyncio
import json
from typing import Dict, List, Any
from datetime import datetime
import logging
import os
import sys

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adapters.exchanges.adapters.hyperliquid import HyperliquidAdapter
from core.adapters.exchanges.interface import ExchangeConfig
from core.adapters.exchanges.models import TickerData, OrderBookData, TradeData

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SubscriptionModeDemo:
    """订阅模式演示类"""
    
    def __init__(self):
        self.adapters = {}
        self.data_counts = {
            'ticker': 0,
            'orderbook': 0,
            'trades': 0
        }
        
    async def create_hyperliquid_adapter(self) -> HyperliquidAdapter:
        """创建Hyperliquid适配器"""
        config = ExchangeConfig(
            exchange_id="hyperliquid",
            api_key="",  # 公共访问模式
            api_secret="",
            testnet=False
        )
        
        adapter = HyperliquidAdapter(config)
        await adapter.connect()
        return adapter
    
    # === 回调函数 ===
    
    async def on_ticker_data(self, symbol: str, ticker_data: TickerData):
        """处理ticker数据"""
        self.data_counts['ticker'] += 1
        logger.info(f"📊 {symbol}: 价格=${ticker_data.last_price:.4f}, 成交量={ticker_data.volume:.2f}")
        
        # 每10条数据输出一次统计
        if self.data_counts['ticker'] % 10 == 0:
            logger.info(f"✅ 已接收ticker数据: {self.data_counts['ticker']}条")
    
    async def on_orderbook_data(self, symbol: str, orderbook_data: OrderBookData):
        """处理orderbook数据"""
        self.data_counts['orderbook'] += 1
        if orderbook_data.bids and orderbook_data.asks:
            bid_price = orderbook_data.bids[0].price
            ask_price = orderbook_data.asks[0].price
            spread = ask_price - bid_price
            logger.info(f"📖 {symbol}: 买一=${bid_price:.4f}, 卖一=${ask_price:.4f}, 价差=${spread:.4f}")
    
    async def on_trades_data(self, symbol: str, trade_data: TradeData):
        """处理trades数据"""
        self.data_counts['trades'] += 1
        logger.info(f"💰 {symbol}: 成交价=${trade_data.price:.4f}, 成交量={trade_data.quantity:.6f}")
    
    # === 演示场景 ===
    
    async def demo_predefined_mode(self):
        """演示硬编码模式"""
        logger.info("=" * 60)
        logger.info("🎯 演示场景1: 硬编码模式")
        logger.info("=" * 60)
        
        # 创建适配器
        adapter = await self.create_hyperliquid_adapter()
        
        # 获取订阅管理器
        sub_manager = adapter.get_subscription_manager()
        
        logger.info(f"订阅模式: {sub_manager.mode.value}")
        logger.info(f"预定义交易对: {sub_manager.get_subscription_symbols()}")
        
        # 使用硬编码模式批量订阅
        await adapter.batch_subscribe_tickers(
            symbols=None,  # 使用配置文件中的设置
            callback=self.on_ticker_data
        )
        
        # 运行30秒
        logger.info("运行30秒...")
        await asyncio.sleep(30)
        
        # 获取统计信息
        stats = adapter.get_subscription_stats()
        logger.info(f"订阅统计: {json.dumps(stats, indent=2)}")
        
        await adapter.disconnect()
    
    async def demo_dynamic_mode(self):
        """演示动态模式"""
        logger.info("=" * 60)
        logger.info("🚀 演示场景2: 动态模式")
        logger.info("=" * 60)
        
        # 创建适配器
        adapter = await self.create_hyperliquid_adapter()
        
        # 获取订阅管理器
        sub_manager = adapter.get_subscription_manager()
        
        # 临时切换到动态模式（演示用）
        sub_manager.mode = sub_manager.mode.DYNAMIC
        
        # 发现交易对
        discovered_symbols = await sub_manager.discover_symbols(adapter.get_supported_symbols)
        logger.info(f"发现交易对: {len(discovered_symbols)}个")
        logger.info(f"前10个交易对: {discovered_symbols[:10]}")
        
        # 使用动态模式批量订阅
        await adapter.batch_subscribe_tickers(
            symbols=discovered_symbols[:5],  # 只订阅前5个
            callback=self.on_ticker_data
        )
        
        # 运行30秒
        logger.info("运行30秒...")
        await asyncio.sleep(30)
        
        # 获取统计信息
        stats = adapter.get_subscription_stats()
        logger.info(f"订阅统计: {json.dumps(stats, indent=2)}")
        
        await adapter.disconnect()
    
    async def demo_mixed_subscription(self):
        """演示混合订阅"""
        logger.info("=" * 60)
        logger.info("🎨 演示场景3: 混合订阅（任意组合）")
        logger.info("=" * 60)
        
        # 创建适配器
        adapter = await self.create_hyperliquid_adapter()
        
        # 自定义交易对
        custom_symbols = ["BTC/USDC:PERP", "ETH/USDC:PERP", "SOL/USDC:PERP"]
        
        # 混合订阅
        await adapter.batch_subscribe_mixed(
            symbols=custom_symbols,
            ticker_callback=self.on_ticker_data,
            orderbook_callback=self.on_orderbook_data,
            trades_callback=self.on_trades_data
        )
        
        # 运行30秒
        logger.info("运行30秒...")
        await asyncio.sleep(30)
        
        # 输出数据统计
        logger.info("数据统计:")
        for data_type, count in self.data_counts.items():
            logger.info(f"  {data_type}: {count}条")
        
        await adapter.disconnect()
    
    async def demo_custom_filter(self):
        """演示自定义过滤器"""
        logger.info("=" * 60)
        logger.info("🔧 演示场景4: 自定义过滤器")
        logger.info("=" * 60)
        
        # 创建适配器
        adapter = await self.create_hyperliquid_adapter()
        
        # 获取订阅管理器
        sub_manager = adapter.get_subscription_manager()
        
        # 获取所有支持的交易对
        all_symbols = await adapter.get_supported_symbols()
        logger.info(f"所有支持的交易对: {len(all_symbols)}个")
        
        # 自定义过滤条件
        sub_manager._subscription_config.filter_criteria = {
            'market_types': ['perpetual'],
            'volume_threshold': 1000000,
            'max_symbols': 10,
            'include_patterns': ['*/USDC:PERP'],
            'exclude_patterns': ['*TEST*']
        }
        
        # 应用过滤器
        filtered_symbols = sub_manager.filter_symbols_by_criteria(all_symbols)
        logger.info(f"过滤后的交易对: {len(filtered_symbols)}个")
        logger.info(f"过滤后的交易对: {filtered_symbols}")
        
        # 订阅过滤后的交易对
        await adapter.batch_subscribe_tickers(
            symbols=filtered_symbols,
            callback=self.on_ticker_data
        )
        
        # 运行30秒
        logger.info("运行30秒...")
        await asyncio.sleep(30)
        
        await adapter.disconnect()
    
    async def demo_subscription_monitoring(self):
        """演示订阅监控"""
        logger.info("=" * 60)
        logger.info("📊 演示场景5: 订阅监控")
        logger.info("=" * 60)
        
        # 创建适配器
        adapter = await self.create_hyperliquid_adapter()
        
        # 订阅数据
        await adapter.batch_subscribe_tickers(
            symbols=["BTC/USDC:PERP", "ETH/USDC:PERP"],
            callback=self.on_ticker_data
        )
        
        # 监控订阅状态
        for i in range(5):
            await asyncio.sleep(10)
            
            # 获取连接状态
            connection_status = adapter.get_connection_status()
            logger.info(f"连接状态: {connection_status}")
            
            # 获取订阅统计
            subscription_stats = adapter.get_subscription_stats()
            logger.info(f"订阅统计: {json.dumps(subscription_stats, indent=2)}")
            
            # 获取活跃交易对
            active_symbols = adapter.get_subscription_manager().get_active_symbols()
            logger.info(f"活跃交易对: {list(active_symbols)}")
        
        await adapter.disconnect()
    
    async def run_all_demos(self):
        """运行所有演示"""
        logger.info("🚀 开始演示交易所订阅模式系统")
        logger.info(f"时间: {datetime.now()}")
        
        try:
            # 场景1: 硬编码模式
            await self.demo_predefined_mode()
            
            # 重置计数器
            self.data_counts = {'ticker': 0, 'orderbook': 0, 'trades': 0}
            
            # 场景2: 动态模式
            await self.demo_dynamic_mode()
            
            # 重置计数器
            self.data_counts = {'ticker': 0, 'orderbook': 0, 'trades': 0}
            
            # 场景3: 混合订阅
            await self.demo_mixed_subscription()
            
            # 场景4: 自定义过滤器
            await self.demo_custom_filter()
            
            # 场景5: 订阅监控
            await self.demo_subscription_monitoring()
            
        except Exception as e:
            logger.error(f"演示过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
        
        logger.info("✅ 所有演示完成")

async def main():
    """主函数"""
    demo = SubscriptionModeDemo()
    await demo.run_all_demos()

if __name__ == "__main__":
    # 运行演示
    asyncio.run(main()) 