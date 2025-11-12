#!/usr/bin/env python3
"""
配置设置测试脚本
验证配置分离系统是否正确读取了调整后的配置
"""

import asyncio
import logging
from core.infrastructure.config_manager import config_manager

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_config_setup():
    """测试配置设置"""
    logger.info("🧪 开始测试配置设置...")
    
    try:
        # 1. 测试全局监控配置
        logger.info("\n📊 测试全局监控配置...")
        monitoring_config = config_manager.load_monitoring_config()
        logger.info(f"✅ 全局配置加载成功")
        logger.info(f"   - 启用的交易所: {monitoring_config.monitoring.get('enabled_exchanges', [])}")
        logger.info(f"   - 全局最大交易对: {monitoring_config.global_max_symbols}")
        logger.info(f"   - 更新间隔: {monitoring_config.update_interval}ms")
        
        # 2. 测试所有交易所配置
        logger.info("\n🏢 测试交易所配置...")
        exchange_configs = config_manager.load_all_exchange_configs()
        
        for exchange_name, config in exchange_configs.items():
            logger.info(f"\n📈 {exchange_name.upper()} 配置:")
            logger.info(f"   ✅ 启用状态: {'启用' if config.enabled else '禁用'}")
            logger.info(f"   📡 订阅模式: {config.subscription_mode}")
            logger.info(f"   📊 数据类型: {config.data_types}")
            logger.info(f"   🎯 符号数量: {len(config.symbols)}")
            logger.info(f"   🔢 最大交易对: {config.max_symbols}")
            
            # 检查是否只订阅orderbook数据
            if config.data_types == ['orderbook']:
                logger.info(f"   ✅ 正确配置 - 只订阅订单数据")
            else:
                logger.warning(f"   ⚠️  配置异常 - 数据类型: {config.data_types}")
            
            # 检查是否为动态模式
            if config.subscription_mode == 'dynamic':
                logger.info(f"   ✅ 正确配置 - 使用动态模式")
                
                # 检查发现设置
                if config.discovery_settings:
                    filters = config.discovery_settings.get('filters', {})
                    logger.info(f"   🔍 过滤设置:")
                    logger.info(f"      - 市场类型: {filters.get('market_types', [])}")
                    logger.info(f"      - 最小交易量: {filters.get('volume_threshold', 0)}")
                    logger.info(f"      - 最大交易对: {filters.get('max_symbols', 0)}")
                    logger.info(f"      - 包含模式: {filters.get('include_patterns', [])}")
                    logger.info(f"      - 排除模式: {filters.get('exclude_patterns', [])}")
                    
                    # 检查是否正确配置为只获取永续合约
                    if 'perpetual' in filters.get('market_types', []) and 'spot' not in filters.get('market_types', []):
                        logger.info(f"   ✅ 正确配置 - 只获取永续合约")
                    else:
                        logger.warning(f"   ⚠️  配置异常 - 市场类型: {filters.get('market_types', [])}")
                else:
                    logger.warning(f"   ⚠️  缺少发现设置")
            else:
                logger.warning(f"   ⚠️  配置异常 - 使用预定义模式: {config.subscription_mode}")
            
            # 检查预定义组合
            if config.predefined_combinations:
                logger.info(f"   📋 预定义组合: {len(config.predefined_combinations)} 个")
                for combo_name, combo_config in config.predefined_combinations.items():
                    combo_data_types = combo_config.get('data_types', [])
                    if combo_data_types == ['orderbook']:
                        logger.info(f"      ✅ {combo_name}: 正确配置")
                    else:
                        logger.warning(f"      ⚠️  {combo_name}: 异常配置 - {combo_data_types}")
        
        # 3. 验证配置要求
        logger.info("\n🎯 验证配置要求...")
        
        all_requirements_met = True
        
        for exchange_name, config in exchange_configs.items():
            if not config.enabled:
                continue
                
            # 要求1: 只订阅订单数据
            if config.data_types != ['orderbook']:
                logger.error(f"❌ {exchange_name}: 未满足要求 - 应只订阅orderbook数据")
                all_requirements_met = False
            
            # 要求2: 使用动态模式
            if config.subscription_mode != 'dynamic':
                logger.error(f"❌ {exchange_name}: 未满足要求 - 应使用动态模式")
                all_requirements_met = False
            
            # 要求3: 只获取永续合约
            if config.discovery_settings:
                filters = config.discovery_settings.get('filters', {})
                market_types = filters.get('market_types', [])
                if 'perpetual' not in market_types or 'spot' in market_types:
                    logger.error(f"❌ {exchange_name}: 未满足要求 - 应只获取永续合约")
                    all_requirements_met = False
        
        if all_requirements_met:
            logger.info("🎉 配置验证通过！所有要求都已满足:")
            logger.info("   ✅ 只订阅订单数据 (orderbook)")
            logger.info("   ✅ 使用动态模式从市场获取交易对")
            logger.info("   ✅ 只订阅永续合约，不订阅现货")
            logger.info("\n🚀 系统已正确配置，可以启动监控！")
        else:
            logger.error("❌ 配置验证失败！请检查上述错误并修正配置。")
            
        return all_requirements_met
        
    except Exception as e:
        logger.error(f"❌ 配置测试失败: {e}")
        return False

async def main():
    """主函数"""
    logger.info("🎯 配置设置测试开始")
    
    success = await test_config_setup()
    
    if success:
        logger.info("\n✅ 配置测试完成 - 所有配置正确！")
        logger.info("📋 配置摘要:")
        logger.info("   🔥 订阅数据: 只订阅订单数据 (orderbook)")
        logger.info("   🔥 获取方式: 使用市场数据动态获取交易对")
        logger.info("   🔥 市场类型: 只订阅永续合约，不订阅现货")
        logger.info("   🔥 高度灵活: 保持企业级配置功能")
        logger.info("\n现在可以运行: python run_monitor.py")
    else:
        logger.error("\n❌ 配置测试失败 - 请修正配置后重试")
        
    return success

if __name__ == "__main__":
    asyncio.run(main()) 