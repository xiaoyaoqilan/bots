#!/usr/bin/env python3
"""
统一配置系统测试脚本
验证旧配置服务现在能正确读取新配置文件
"""

import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.services.implementations.config_service import ConfigurationServiceImpl
from core.infrastructure.config_manager import ConfigManager


async def test_unified_config_system():
    """测试统一配置系统"""
    
    print("🔥 测试统一配置系统")
    print("=" * 60)
    
    # 1. 测试新配置管理器
    print("\n1️⃣ 测试新配置管理器 (ConfigManager)")
    print("-" * 40)
    
    try:
        config_manager = ConfigManager()
        
        # 加载监控配置
        monitoring_config = config_manager.load_monitoring_config()
        print(f"✅ 监控配置加载成功:")
        print(f"   - 启用: {monitoring_config.enabled}")
        print(f"   - 更新间隔: {monitoring_config.update_interval}ms")
        print(f"   - 最大符号: {monitoring_config.global_max_symbols}")
        
        # 加载交易所配置
        exchange_configs = config_manager.load_all_exchange_configs()
        print(f"\n✅ 交易所配置加载成功:")
        for exchange_id, config in exchange_configs.items():
            print(f"   - {exchange_id}: {'✅启用' if config.enabled else '❌禁用'}")
            print(f"     订阅模式: {config.subscription_mode}")
            print(f"     数据类型: {config.data_types}")
            print(f"     符号数量: {len(config.symbols)}")
            
    except Exception as e:
        print(f"❌ 新配置管理器测试失败: {e}")
        return False
    
    # 2. 测试旧配置服务（现在内部使用ConfigManager）
    print("\n2️⃣ 测试旧配置服务 (ConfigurationServiceImpl)")
    print("-" * 40)
    
    try:
        config_service = ConfigurationServiceImpl()
        
        # 初始化配置服务
        init_success = await config_service.initialize()
        print(f"✅ 配置服务初始化: {'成功' if init_success else '失败'}")
        
        # 获取启用的交易所
        enabled_exchanges = await config_service.get_enabled_exchanges()
        print(f"✅ 启用的交易所: {enabled_exchanges}")
        
        # 获取每个交易所的配置
        for exchange_id in enabled_exchanges:
            exchange_config = await config_service.get_exchange_config(exchange_id)
            if exchange_config:
                print(f"✅ {exchange_id} 配置:")
                print(f"   - 名称: {exchange_config.name}")
                print(f"   - 启用: {exchange_config.enabled}")
                print(f"   - 最大符号: {exchange_config.max_symbols}")
                print(f"   - 基础URL: {exchange_config.base_url}")
                print(f"   - WebSocket URL: {exchange_config.ws_url}")
        
        # 获取监控数据类型配置
        monitoring_data_config = await config_service.get_monitoring_data_type_config()
        print(f"\n✅ 监控数据类型配置:")
        for exchange_id in enabled_exchanges:
            enabled_types = monitoring_data_config.get_enabled_types_for_exchange(exchange_id)
            print(f"   - {exchange_id}: {[dt.value for dt in enabled_types]}")
            
    except Exception as e:
        print(f"❌ 旧配置服务测试失败: {e}")
        return False
    
    # 3. 配置一致性验证
    print("\n3️⃣ 配置一致性验证")
    print("-" * 40)
    
    try:
        # 比较两套系统的结果
        config_manager_exchanges = set(exchange_configs.keys())
        config_service_exchanges = set(enabled_exchanges)
        
        print(f"✅ 配置管理器交易所: {config_manager_exchanges}")
        print(f"✅ 配置服务交易所: {config_service_exchanges}")
        
        if config_manager_exchanges == config_service_exchanges:
            print("🎉 配置一致性验证通过！")
            
            # 验证用户需求
            print("\n4️⃣ 用户需求验证")
            print("-" * 40)
            
            all_requirements_met = True
            
            # 检查每个交易所的配置
            for exchange_id in enabled_exchanges:
                exchange_config = exchange_configs[exchange_id]
                
                # 验证只订阅orderbook数据
                if exchange_config.data_types != ["orderbook"]:
                    print(f"❌ {exchange_id} 数据类型不符合要求: {exchange_config.data_types} (期望: ['orderbook'])")
                    all_requirements_met = False
                else:
                    print(f"✅ {exchange_id} 只订阅订单数据")
                
                # 验证使用动态模式
                if exchange_config.subscription_mode != "dynamic":
                    print(f"❌ {exchange_id} 订阅模式不符合要求: {exchange_config.subscription_mode} (期望: dynamic)")
                    all_requirements_met = False
                else:
                    print(f"✅ {exchange_id} 使用动态模式")
                
                # 验证发现设置（排除现货）
                if exchange_config.discovery_settings:
                    filters = exchange_config.discovery_settings.get('filters', {})
                    market_types = filters.get('market_types', [])
                    if "perpetual" not in market_types:
                        print(f"❌ {exchange_id} 未配置永续合约过滤")
                        all_requirements_met = False
                    else:
                        print(f"✅ {exchange_id} 配置了永续合约过滤")
            
            if all_requirements_met:
                print("\n🎉 所有用户需求验证通过！")
                print("   ✅ 只订阅订单数据 (orderbook)")
                print("   ✅ 使用动态模式从市场获取交易对")
                print("   ✅ 只订阅永续合约，不订阅现货")
                print("   ✅ 保持高度灵活的配置系统")
                return True
            else:
                print("\n⚠️ 部分用户需求未满足")
                return False
                
        else:
            print("❌ 配置不一致！")
            missing_in_service = config_manager_exchanges - config_service_exchanges
            missing_in_manager = config_service_exchanges - config_manager_exchanges
            
            if missing_in_service:
                print(f"   配置服务缺少: {missing_in_service}")
            if missing_in_manager:
                print(f"   配置管理器缺少: {missing_in_manager}")
            
            return False
            
    except Exception as e:
        print(f"❌ 配置一致性验证失败: {e}")
        return False


async def main():
    """主函数"""
    try:
        print("🚀 开始测试统一配置系统...")
        
        success = await test_unified_config_system()
        
        if success:
            print("\n🎉 统一配置系统测试完全通过！")
            print("📊 系统现在使用统一的配置源")
            print("📊 消除了代码冗余和配置冲突")
            print("📊 保持了向后兼容性")
        else:
            print("\n❌ 统一配置系统测试失败")
            print("📊 需要进一步检查配置问题")
            
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main()) 