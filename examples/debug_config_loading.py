#!/usr/bin/env python3
"""
调试配置加载过程
找出配置系统中的问题
"""

import asyncio
import sys
import os
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 设置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from core.infrastructure.config_manager import ConfigManager
from core.services.implementations.config_service import ConfigurationServiceImpl

async def debug_config_loading():
    """调试配置加载过程"""
    
    print("🔍 调试配置加载过程")
    print("=" * 60)
    
    # 1. 测试ConfigManager
    print("\n1️⃣ 测试ConfigManager")
    print("-" * 40)
    
    try:
        config_manager = ConfigManager()
        
        # 加载监控配置
        print("加载监控配置...")
        monitoring_config = config_manager.load_monitoring_config()
        print(f"✅ 监控配置加载成功:")
        print(f"   - 启用: {monitoring_config.enabled}")
        print(f"   - 全局最大符号数: {monitoring_config.global_max_symbols}")
        print(f"   - 监控配置: {monitoring_config.monitoring}")
        
        # 检查启用的交易所
        enabled_exchanges = monitoring_config.monitoring.get('enabled_exchanges', [])
        print(f"   - 启用的交易所: {enabled_exchanges}")
        
        # 加载所有交易所配置
        print("\n加载所有交易所配置...")
        exchange_configs = config_manager.load_all_exchange_configs()
        print(f"✅ 交易所配置加载结果:")
        print(f"   - 加载数量: {len(exchange_configs)}")
        
        for exchange_id, config in exchange_configs.items():
            print(f"   - {exchange_id}: enabled={config.enabled}, mode={config.subscription_mode}, types={config.data_types}")
            
    except Exception as e:
        print(f"❌ ConfigManager测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 2. 测试ConfigurationServiceImpl
    print("\n2️⃣ 测试ConfigurationServiceImpl")
    print("-" * 40)
    
    try:
        config_service = ConfigurationServiceImpl()
        
        # 初始化配置服务
        print("初始化配置服务...")
        init_result = await config_service.initialize()
        print(f"✅ 配置服务初始化结果: {init_result}")
        
        # 获取启用的交易所
        print("\n获取启用的交易所...")
        enabled_exchanges = await config_service.get_enabled_exchanges()
        print(f"✅ 启用的交易所: {enabled_exchanges}")
        
        # 获取每个交易所的配置
        for exchange_id in enabled_exchanges:
            print(f"\n获取 {exchange_id} 的配置...")
            exchange_config = await config_service.get_exchange_config(exchange_id)
            if exchange_config:
                print(f"✅ {exchange_id} 配置:")
                print(f"   - 名称: {exchange_config.name}")
                print(f"   - 启用: {exchange_config.enabled}")
                print(f"   - 基础URL: {exchange_config.base_url}")
                print(f"   - WebSocket URL: {exchange_config.ws_url}")
                print(f"   - 最大符号数: {exchange_config.max_symbols}")
            else:
                print(f"❌ {exchange_id} 配置获取失败")
        
        # 获取监控数据类型配置
        print("\n获取监控数据类型配置...")
        monitoring_data_config = await config_service.get_monitoring_data_type_config()
        print(f"✅ 监控数据类型配置:")
        
        # 显示每个交易所的数据类型配置
        for exchange_id in enabled_exchanges:
            enabled_types = monitoring_data_config.get_enabled_types_for_exchange(exchange_id)
            print(f"   - {exchange_id}: {[dt.value for dt in enabled_types]}")
            
    except Exception as e:
        print(f"❌ ConfigurationServiceImpl测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. 测试配置文件是否存在
    print("\n3️⃣ 测试配置文件是否存在")
    print("-" * 40)
    
    config_files = [
        "config/monitoring/monitoring.yaml",
        "config/exchanges/hyperliquid_config.yaml",
        "config/exchanges/backpack_config.yaml",
        "config/exchanges/edgex_config.yaml"
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            print(f"✅ {config_file} 存在")
        else:
            print(f"❌ {config_file} 不存在")

if __name__ == "__main__":
    asyncio.run(debug_config_loading()) 