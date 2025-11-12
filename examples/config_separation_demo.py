#!/usr/bin/env python3
"""
配置分离设计使用示例
演示如何使用分离的配置文件进行监控系统配置
"""

import asyncio
import logging
from typing import Dict, Any
from core.infrastructure.config_manager import config_manager

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MonitoringService:
    """监控服务示例"""
    
    def __init__(self):
        self.config_manager = config_manager
        self.monitoring_config = None
        self.exchange_configs = {}
        self.active_exchanges = []
        
    async def initialize(self):
        """初始化监控服务"""
        logger.info("🚀 初始化监控服务...")
        
        # 1. 加载全局监控配置
        self.monitoring_config = self.config_manager.load_monitoring_config()
        logger.info(f"✅ 全局监控配置加载完成")
        logger.info(f"   - 全局最大交易对数量: {self.monitoring_config.global_max_symbols}")
        logger.info(f"   - 更新间隔: {self.monitoring_config.update_interval}ms")
        logger.info(f"   - 启用统计: {self.monitoring_config.enable_statistics}")
        
        # 2. 加载所有交易所配置
        self.exchange_configs = self.config_manager.load_all_exchange_configs()
        logger.info(f"✅ 交易所配置加载完成，共 {len(self.exchange_configs)} 个交易所")
        
        # 3. 初始化启用的交易所
        for exchange_name, config in self.exchange_configs.items():
            if config.enabled:
                self.active_exchanges.append(exchange_name)
                logger.info(f"   - {exchange_name}: 启用")
                logger.info(f"     订阅模式: {config.subscription_mode}")
                logger.info(f"     数据类型: {config.data_types}")
                logger.info(f"     交易对数量: {len(config.symbols)}")
            else:
                logger.info(f"   - {exchange_name}: 禁用")
    
    async def start_monitoring(self):
        """启动监控"""
        logger.info("🏃 启动监控...")
        
        # 为每个启用的交易所启动监控
        tasks = []
        for exchange_name in self.active_exchanges:
            task = asyncio.create_task(
                self._monitor_exchange(exchange_name)
            )
            tasks.append(task)
        
        # 启动性能监控
        if self.monitoring_config.performance['enabled']:
            performance_task = asyncio.create_task(
                self._monitor_performance()
            )
            tasks.append(performance_task)
        
        # 等待所有任务完成
        await asyncio.gather(*tasks)
    
    async def _monitor_exchange(self, exchange_name: str):
        """监控特定交易所"""
        config = self.exchange_configs[exchange_name]
        logger.info(f"📊 启动 {exchange_name} 监控")
        
        # 模拟监控逻辑
        for i in range(10):  # 模拟10个周期
            await asyncio.sleep(self.monitoring_config.update_interval / 1000)  # 转换为秒
            
            # 根据配置决定订阅什么数据
            if "ticker" in config.data_types:
                logger.info(f"   {exchange_name} - 接收到ticker数据")
            
            if "orderbook" in config.data_types:
                logger.info(f"   {exchange_name} - 接收到orderbook数据")
            
            if "trades" in config.data_types:
                logger.info(f"   {exchange_name} - 接收到trades数据")
            
            # 检查交易对限制
            if config.max_symbols > 0 and len(config.symbols) > config.max_symbols:
                logger.warning(f"   {exchange_name} - 交易对数量超过限制: {len(config.symbols)}/{config.max_symbols}")
    
    async def _monitor_performance(self):
        """性能监控"""
        logger.info("📈 启动性能监控")
        
        metrics_interval = self.monitoring_config.performance['metrics_interval']
        
        for i in range(5):  # 模拟5个周期
            await asyncio.sleep(metrics_interval)
            
            # 模拟收集性能指标
            if self.monitoring_config.performance.get('memory_monitoring', False):
                logger.info("   📊 内存使用情况: 正常")
            
            if self.monitoring_config.performance.get('connection_monitoring', False):
                logger.info("   📡 连接状态: 正常")
            
            logger.info(f"   ⏱️  活跃交易所数量: {len(self.active_exchanges)}")
    
    def demonstrate_config_access(self):
        """演示配置访问方法"""
        logger.info("\n🔍 配置访问演示:")
        
        # 1. 检查交易所是否启用
        for exchange in ["hyperliquid", "edgex", "backpack", "binance"]:
            enabled = self.config_manager.is_exchange_enabled(exchange)
            logger.info(f"   {exchange}: {'✅' if enabled else '❌'}")
        
        # 2. 获取特定交易所的数据类型
        for exchange in self.active_exchanges:
            data_types = self.config_manager.get_exchange_data_types(exchange)
            logger.info(f"   {exchange} 数据类型: {data_types}")
        
        # 3. 获取交易对配置
        for exchange in self.active_exchanges:
            symbols = self.config_manager.get_exchange_symbols(exchange)
            logger.info(f"   {exchange} 交易对数量: {len(symbols)}")
        
        # 4. 展示配置分离的优势
        logger.info("\n💡 配置分离的优势:")
        logger.info("   ✅ 职责清晰 - 全局配置与交易所配置分离")
        logger.info("   ✅ 易于维护 - 每个交易所的配置独立管理")
        logger.info("   ✅ 扩展性强 - 新增交易所只需添加配置文件")
        logger.info("   ✅ 灵活性高 - 可以独立配置每个交易所的行为")
        logger.info("   ✅ 避免冲突 - 消除了配置重叠的问题")

async def main():
    """主函数"""
    logger.info("🎯 配置分离设计演示")
    
    # 创建监控服务实例
    monitoring_service = MonitoringService()
    
    try:
        # 初始化
        await monitoring_service.initialize()
        
        # 演示配置访问
        monitoring_service.demonstrate_config_access()
        
        # 启动监控（运行一段时间后退出）
        logger.info("\n🏁 开始监控演示...")
        await asyncio.wait_for(
            monitoring_service.start_monitoring(),
            timeout=30.0  # 30秒后退出
        )
        
    except asyncio.TimeoutError:
        logger.info("✅ 监控演示完成")
        
    except Exception as e:
        logger.error(f"❌ 演示过程中发生错误: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 