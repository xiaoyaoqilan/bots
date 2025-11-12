#!/usr/bin/env python3
"""
EdgeX适配器演示脚本

演示如何使用EdgeX适配器进行基本的功能测试，
包括适配器创建、连接测试等。

注意：此脚本需要有效的EdgeX API密钥才能完整运行。
"""

from core.exchanges.factory import ExchangeFactory
from core.exchanges.models import OrderSide, OrderType, OrderStatus
from core.exchanges.interface import ExchangeConfig
from core.exchanges.adapters.edgex import EdgeXAdapter, EdgeXSymbolInfo
import asyncio
import sys
import os
import logging
from decimal import Decimal
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class EdgeXAdapterDemo:
    """EdgeX适配器演示类"""

    def __init__(self):
        """初始化演示"""
        self.setup_logging()
        self.factory = ExchangeFactory()
        self.adapter = None

    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger("EdgeXDemo")

    def create_test_config(self) -> ExchangeConfig:
        """创建测试配置"""
        return ExchangeConfig(
            name="EdgeX",
            exchange_id="edgex",
            api_key="test_api_key",  # 在实际测试中需要替换
            api_secret="test_api_secret",  # 在实际测试中需要替换
            api_config={
                "base_url": "https://pro.edgex.exchange/",
                "ws_url": "wss://quote.edgex.exchange/",
                "version": "v1",
                "timeout": 30
            },
            rate_limits={
                "orders": {"rate": 10, "per": 1},
                "market_data": {"rate": 100, "per": 1},
                "account": {"rate": 5, "per": 1}
            },
            precision={
                "BTCUSDTPERP": {"base": 8, "quote": 2},
                "ETHUSDTPERP": {"base": 8, "quote": 2}
            },
            symbol_mapping={
                "BTC/USDT:PERP": "BTCUSDTPERP",
                "ETH/USDT:PERP": "ETHUSDTPERP"
            }
        )

    async def test_adapter_creation(self) -> bool:
        """测试适配器创建"""
        try:
            self.logger.info("测试EdgeX适配器创建...")

            # 验证EdgeX适配器是否已注册
            registered_exchanges = self.factory.get_registered_exchanges()
            if "edgex" not in registered_exchanges:
                self.logger.error("EdgeX适配器未注册到工厂")
                return False

            # 获取EdgeX适配器信息
            edgex_info = self.factory.get_exchange_info("edgex")
            if edgex_info:
                self.logger.info(
                    f"EdgeX适配器信息: {edgex_info.name} - {edgex_info.description}")
                self.logger.info(f"支持的功能: {edgex_info.supported_features}")
            else:
                self.logger.error("无法获取EdgeX适配器信息")
                return False

            # 直接创建适配器实例（不使用工厂）
            config = self.create_test_config()
            self.adapter = EdgeXAdapter(config)

            if self.adapter:
                self.logger.info("EdgeX适配器创建成功")
                self.logger.info(f"适配器类型: {type(self.adapter).__name__}")
                self.logger.info(f"基础URL: {self.adapter.base_url}")
                self.logger.info(f"WebSocket URL: {self.adapter.ws_url}")
                return True
            else:
                self.logger.error("EdgeX适配器创建失败")
                return False

        except Exception as e:
            self.logger.error(f"适配器创建测试失败: {e}")
            return False

    async def test_adapter_configuration(self) -> bool:
        """测试适配器配置"""
        try:
            if not self.adapter:
                self.logger.error("适配器未创建")
                return False

            self.logger.info("测试适配器配置...")

            # 测试符号标准化
            test_cases = [
                ("BTC/USDT:PERP", "BTCUSDTPERP"),
                ("ETH/USDT:PERP", "ETHUSDTPERP"),
                ("BTC/USDT", "BTCUSDT"),
                ("btc/usdt", "BTCUSDT"),
                ("BTCUSDT", "BTCUSDT")
            ]

            for original, expected in test_cases:
                normalized = self.adapter._normalize_symbol(original)
                if normalized == expected:
                    self.logger.info(f"符号标准化测试成功: {original} -> {normalized}")
                else:
                    self.logger.error(
                        f"符号标准化测试失败: {original} -> {normalized}, 期望: {expected}")
                    return False

            # 测试签名生成
            test_params = {"symbol": "BTCUSDTPERP", "side": "BUY"}
            test_timestamp = 1703001234567
            signature = self.adapter._generate_signature(
                test_params, test_timestamp)

            # HMAC-SHA256 produces 64 char hex
            if signature and len(signature) == 64:
                self.logger.info(f"签名生成测试成功: {signature[:16]}...")
            else:
                self.logger.error("签名生成测试失败")
                return False

            # 测试订单类型转换
            order_type_mappings = [
                (OrderType.LIMIT, "LIMIT"),
                (OrderType.MARKET, "MARKET"),
                (OrderType.STOP_LIMIT, "STOP_LIMIT"),
                (OrderType.STOP_MARKET, "STOP_MARKET")
            ]

            for order_type, expected in order_type_mappings:
                edgex_type = self.adapter._convert_order_type(order_type)
                converted_back = self.adapter._convert_order_type_back(
                    edgex_type)

                if edgex_type == expected and converted_back == order_type:
                    self.logger.info(
                        f"订单类型转换测试成功: {order_type} <-> {edgex_type}")
                else:
                    self.logger.error(
                        f"订单类型转换测试失败: {order_type} -> {edgex_type} -> {converted_back}")
                    return False

            # 测试配置访问
            if hasattr(self.adapter, 'config') and self.adapter.config:
                self.logger.info(
                    f"配置访问测试成功: exchange_id = {self.adapter.config.exchange_id}")
            else:
                self.logger.error("配置访问测试失败")
                return False

            return True

        except Exception as e:
            self.logger.error(f"适配器配置测试失败: {e}")
            return False

    async def test_basic_methods(self) -> bool:
        """测试基础方法"""
        try:
            if not self.adapter:
                self.logger.error("适配器未创建")
                return False

            self.logger.info("测试基础方法...")

            # 测试必要方法的存在性
            required_methods = [
                'connect', 'disconnect', 'get_ticker', 'get_order_book',
                'get_recent_trades', 'get_account_info', 'get_balances',
                'place_order', 'cancel_order', 'get_order_status', 'get_open_orders',
                'subscribe_ticker', 'subscribe_order_book', 'subscribe_trades'
            ]

            for method_name in required_methods:
                if hasattr(self.adapter, method_name):
                    self.logger.info(f"方法 {method_name} 存在")
                else:
                    self.logger.error(f"方法 {method_name} 不存在")
                    return False

            # 测试工具方法
            tool_methods = [
                'get_supported_symbols', 'get_symbol_info', 'format_quantity',
                'format_price', 'get_exchange_status'
            ]

            for method_name in tool_methods:
                if hasattr(self.adapter, method_name):
                    self.logger.info(f"工具方法 {method_name} 存在")
                else:
                    self.logger.error(f"工具方法 {method_name} 不存在")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"基础方法测试失败: {e}")
            return False

    async def test_data_models(self) -> bool:
        """测试数据模型"""
        try:
            self.logger.info("测试数据模型...")

            # 测试EdgeXSymbolInfo
            test_symbol_info = EdgeXSymbolInfo(
                symbol="BTCUSDTPERP",
                base_asset="BTC",
                quote_asset="USDT",
                status="TRADING",
                base_precision=8,
                quote_precision=2,
                min_qty=Decimal("0.001"),
                max_qty=Decimal("1000"),
                min_price=Decimal("0.01"),
                max_price=Decimal("100000"),
                tick_size=Decimal("0.01"),
                min_notional=Decimal("10")
            )

            if test_symbol_info.symbol == "BTCUSDTPERP":
                self.logger.info("EdgeXSymbolInfo 创建测试成功")
            else:
                self.logger.error("EdgeXSymbolInfo 创建测试失败")
                return False

            # 测试格式化功能
            self.adapter.symbols_info["BTCUSDTPERP"] = test_symbol_info

            # 测试数量格式化
            test_quantity = Decimal("0.123456789")
            formatted_qty = self.adapter.format_quantity(
                "BTCUSDTPERP", test_quantity)
            expected_qty = Decimal("0.12345679")  # 8位精度

            self.logger.info(f"数量格式化测试: {test_quantity} -> {formatted_qty}")

            # 测试价格格式化
            test_price = Decimal("50000.999")
            formatted_price = self.adapter.format_price(
                "BTCUSDTPERP", test_price)
            expected_price = Decimal("50001.00")  # 2位精度

            self.logger.info(f"价格格式化测试: {test_price} -> {formatted_price}")

            return True

        except Exception as e:
            self.logger.error(f"数据模型测试失败: {e}")
            return False

    async def test_mock_functionality(self) -> bool:
        """测试模拟功能（不需要真实API）"""
        try:
            self.logger.info("测试模拟功能...")

            # 模拟创建一些符号信息
            test_symbols = ["BTCUSDTPERP", "ETHUSDTPERP", "SOLUSDTPERP"]
            for symbol in test_symbols:
                self.adapter.symbols_info[symbol] = EdgeXSymbolInfo(
                    symbol=symbol,
                    base_asset=symbol[:3],
                    quote_asset="USDT",
                    status="TRADING",
                    base_precision=8,
                    quote_precision=2,
                    min_qty=Decimal("0.001"),
                    max_qty=Decimal("1000"),
                    min_price=Decimal("0.01"),
                    max_price=Decimal("100000"),
                    tick_size=Decimal("0.01"),
                    min_notional=Decimal("10")
                )

            # 测试获取支持的符号
            symbols = self.adapter.get_supported_symbols()
            if len(symbols) == 3:
                self.logger.info(f"获取支持符号测试成功: {symbols}")
            else:
                self.logger.error(f"获取支持符号测试失败: {symbols}")
                return False

            # 测试获取符号信息
            symbol_info = self.adapter.get_symbol_info("BTCUSDTPERP")
            if symbol_info and symbol_info.symbol == "BTCUSDTPERP":
                self.logger.info(
                    f"获取符号信息测试成功: {symbol_info.base_asset}/{symbol_info.quote_asset}")
            else:
                self.logger.error("获取符号信息测试失败")
                return False

            # 测试获取交易所状态（离线模式）
            try:
                status = await self.adapter.get_exchange_status()
                self.logger.info(f"获取交易所状态测试: {status}")
            except Exception as e:
                self.logger.info(f"获取交易所状态测试（预期失败）: {e}")

            return True

        except Exception as e:
            self.logger.error(f"模拟功能测试失败: {e}")
            return False

    async def run_demo(self) -> None:
        """运行演示"""
        try:
            self.logger.info("开始EdgeX适配器演示...")
            self.logger.info("=" * 50)

            # 测试适配器创建
            if not await self.test_adapter_creation():
                self.logger.error("适配器创建测试失败，停止演示")
                return

            # 测试适配器配置
            if not await self.test_adapter_configuration():
                self.logger.error("适配器配置测试失败，停止演示")
                return

            # 测试基础方法
            if not await self.test_basic_methods():
                self.logger.error("基础方法测试失败，停止演示")
                return

            # 测试数据模型
            if not await self.test_data_models():
                self.logger.error("数据模型测试失败，停止演示")
                return

            # 测试模拟功能
            if not await self.test_mock_functionality():
                self.logger.error("模拟功能测试失败，停止演示")
                return

            self.logger.info("=" * 50)
            self.logger.info("✅ 所有测试通过！EdgeX适配器基础功能正常")
            self.logger.info("=" * 50)

            # 如果有真实API密钥，可以进行连接测试
            if (self.adapter.api_key != "test_api_key" and
                    self.adapter.api_secret != "test_api_secret"):

                self.logger.info("检测到真实API密钥，开始连接测试...")
                await self.test_real_connection()
            else:
                self.logger.info("使用测试API密钥，跳过连接测试")
                self.logger.info("如需测试连接功能，请在配置中设置真实的API密钥")

        except Exception as e:
            self.logger.error(f"演示运行失败: {e}")
            import traceback
            traceback.print_exc()

    async def test_real_connection(self) -> None:
        """测试真实连接（需要有效API密钥）"""
        try:
            self.logger.info("开始真实连接测试...")

            # 尝试连接
            if await self.adapter.connect():
                self.logger.info("✅ 连接成功！")

                # 测试获取交易所状态
                try:
                    status = await self.adapter.get_exchange_status()
                    self.logger.info(f"交易所状态: {status}")
                except Exception as e:
                    self.logger.warning(f"获取交易所状态失败: {e}")

                # 测试获取符号信息
                try:
                    symbols = self.adapter.get_supported_symbols()
                    self.logger.info(f"支持的交易对数量: {len(symbols)}")
                    if symbols:
                        self.logger.info(f"前3个交易对: {symbols[:3]}")
                except Exception as e:
                    self.logger.warning(f"获取符号信息失败: {e}")

                # 测试获取行情（如果有可用交易对）
                if hasattr(self.adapter, 'symbols_info') and self.adapter.symbols_info:
                    test_symbol = list(self.adapter.symbols_info.keys())[0]
                    try:
                        ticker = await self.adapter.get_ticker(test_symbol)
                        self.logger.info(
                            f"{test_symbol} 行情: {ticker.last_price}")
                    except Exception as e:
                        self.logger.warning(f"获取行情失败: {e}")

                # 测试获取账户信息
                try:
                    account_info = await self.adapter.get_account_info()
                    self.logger.info(
                        f"账户信息: {account_info.get('account_type', 'N/A')}")
                except Exception as e:
                    self.logger.warning(f"获取账户信息失败: {e}")

                # 测试获取余额
                try:
                    balances = await self.adapter.get_balances()
                    self.logger.info(f"非零余额数量: {len(balances)}")
                except Exception as e:
                    self.logger.warning(f"获取余额失败: {e}")

                self.logger.info("✅ 真实连接测试完成！")
            else:
                self.logger.error("❌ 连接失败")

        except Exception as e:
            self.logger.error(f"真实连接测试失败: {e}")
        finally:
            try:
                await self.adapter.disconnect()
                self.logger.info("已断开连接")
            except:
                pass


async def main():
    """主函数"""
    demo = EdgeXAdapterDemo()
    await demo.run_demo()


if __name__ == "__main__":
    asyncio.run(main())
