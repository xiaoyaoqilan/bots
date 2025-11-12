"""
套利监控服务实现

实现多交易所实时价差和资金费率监控功能。
"""

import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict
from itertools import combinations

# 修复导入路径：TickerData 在 adapters 模块中
from core.adapters.exchanges.models import TickerData
from ..interfaces.arbitrage_monitor_service import IArbitrageMonitorService
from ..models.arbitrage_models import (
    ArbitrageOpportunity,
    PriceSpread,
    FundingRateSpread,
    ArbitrageConfig
)
# 🔥 极简符号转换器（套利系统专用，~150行代码）
from ..utils.symbol_converter import SimpleSymbolConverter


class ArbitrageMonitorService(IArbitrageMonitorService):
    """套利监控服务实现"""
    
    def __init__(
        self,
        adapters: Dict[str, object],          # {exchange_name: adapter}
        config: ArbitrageConfig,
        logger: Optional[logging.Logger] = None,
        symbol_converter: Optional[SimpleSymbolConverter] = None  # 🔥 极简符号转换器
    ):
        """
        初始化套利监控服务
        
        Args:
            adapters: 交易所适配器字典
            config: 监控配置
            logger: 日志记录器
            symbol_converter: 极简符号转换器（可选）
        """
        self.adapters = adapters
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # 🔥 极简符号转换器（可选）
        self.symbol_converter = symbol_converter or SimpleSymbolConverter(self.logger)
        self.logger.info("✅ 使用极简符号转换器（~150行代码，零冗余）")
        
        # 数据缓存
        self.ticker_data: Dict[str, Dict[str, TickerData]] = defaultdict(dict)  # {exchange: {symbol: ticker}}
        
        # 套利机会缓存
        self.opportunities: List[ArbitrageOpportunity] = []
        
        # 运行状态
        self.running = False
        self.monitor_task = None
        
        # 回调函数
        self.opportunity_callbacks = []
        
        # 🔥 WebSocket连接监控（新增 - 解决数据停止更新问题）
        self.last_data_time: Dict[str, Dict[str, datetime]] = defaultdict(dict)  # {exchange: {symbol: 最后更新时间}}
        self.data_timeout_seconds = 90  # 🔧 数据超时阈值（90秒，平衡灵敏度和稳定性）
        self.connection_monitor_task = None  # 连接监控任务
        self.connection_check_interval = 45  # 🔧 连接检查间隔（45秒，更及时发现问题）
        self.max_reconnect_attempts = 3  # 🔧 最大重连次数（3次，避免频繁重连）
        self.reconnect_attempts: Dict[str, int] = defaultdict(int)  # {exchange: 重连次数}
        self.reconnecting: Dict[str, bool] = defaultdict(bool)  # 🔧 正在重连标志（防止并发）
        self.start_time = datetime.now()  # 🔧 系统启动时间（用于启动缓冲期）
        self.startup_grace_period = 120  # 🔧 启动缓冲期（120秒内不检查，给足够时间接收首次数据）
        self.last_health_check_log = datetime.now()  # 🔧 上次健康检查日志时间
        self.health_check_log_interval = 300  # 🔧 健康检查日志间隔（5分钟输出一次状态）
        
        # 🔥 订阅信息缓存（用于重连后恢复订阅）
        self.subscribed_callbacks: Dict[str, Dict[str, object]] = defaultdict(dict)  # {exchange: {symbol: callback}}
    
    async def start(self) -> bool:
        """启动监控服务"""
        if self.running:
            self.logger.warning("监控服务已经在运行")
            return False
        
        try:
            self.logger.info("🚀 启动套利监控服务...")
            self.running = True
            
            # 订阅所有交易所的ticker数据
            await self._subscribe_all()
            
            # 启动监控任务
            self.monitor_task = asyncio.create_task(self._monitor_loop())
            
            # 🔥 启动连接监控任务（新增 - 防止WebSocket静默断开）
            self.connection_monitor_task = asyncio.create_task(self._monitor_connections())
            self.logger.info(f"✅ 连接监控已启动（每{self.connection_check_interval}秒检查一次）")
            
            self.logger.info("✅ 套利监控服务启动成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 套利监控服务启动失败: {e}", exc_info=True)
            self.running = False
            return False
    
    async def stop(self) -> None:
        """停止监控服务"""
        if not self.running:
            return
        
        self.logger.info("🛑 停止套利监控服务...")
        self.running = False
        
        # 取消监控任务
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # 🔥 取消连接监控任务（新增）
        if self.connection_monitor_task:
            self.connection_monitor_task.cancel()
            try:
                await self.connection_monitor_task
            except asyncio.CancelledError:
                pass
        
        # 取消所有订阅
        await self._unsubscribe_all()
        
        self.logger.info("✅ 套利监控服务已停止")
    
    def get_opportunities(self) -> List[ArbitrageOpportunity]:
        """获取当前所有套利机会"""
        return self.opportunities.copy()
    
    def get_current_prices(self, symbol: str) -> Dict[str, Decimal]:
        """获取当前价格"""
        prices = {}
        for exchange_name in self.adapters.keys():
            ticker = self.ticker_data[exchange_name].get(symbol)
            if ticker and ticker.last:
                prices[exchange_name] = ticker.last
        return prices
    
    def get_current_funding_rates(self, symbol: str) -> Dict[str, Decimal]:
        """获取当前资金费率"""
        rates = {}
        for exchange_name in self.adapters.keys():
            ticker = self.ticker_data[exchange_name].get(symbol)
            if ticker and ticker.funding_rate is not None:
                rates[exchange_name] = ticker.funding_rate
        return rates
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            "total_exchanges": len(self.adapters),
            "monitored_symbols": len(self.config.symbols),
            "active_opportunities": len(self.opportunities),
            "ticker_data_count": sum(len(tickers) for tickers in self.ticker_data.values()),
            "running": self.running
        }
    
    def add_opportunity_callback(self, callback) -> None:
        """添加套利机会回调函数"""
        self.opportunity_callbacks.append(callback)
    
    # === 私有方法 ===
    
    async def _subscribe_all(self):
        """订阅所有交易所的ticker数据"""
        for exchange_name, adapter in self.adapters.items():
            self.logger.info(f"📡 订阅 {exchange_name} 的ticker数据...")
            
            # 🔥 Lighter 特殊处理：使用统一回调，订阅所有 symbol
            if exchange_name == "lighter":
                # 定义统一回调（只注册一次）
                callback_registered = False
                
                def lighter_callback(ticker):
                    """Lighter 统一回调：从 ticker.symbol 反查标准 symbol"""
                    try:
                        # ticker.symbol 是 Lighter 原始格式（如 "BTC", "ETH", "AAVE"）
                        # 需要转换为标准格式（如 "BTC-USDC-PERP"）
                        std_symbol = self.symbol_converter.convert_from_exchange(ticker.symbol, "lighter")
                        
                        # 只处理我们监控的 symbol
                        if std_symbol in self.config.symbols:
                            self._on_ticker_update("lighter", std_symbol, ticker)
                    except Exception as e:
                        self.logger.error(f"❌ Lighter 回调处理失败 (symbol={ticker.symbol}): {e}", exc_info=True)
                
                # 订阅所有监控的 symbol（回调只注册一次）
                for idx, symbol in enumerate(self.config.symbols):
                    try:
                        exchange_symbol = self.symbol_converter.convert_to_exchange(symbol, "lighter")
                        
                        # 🔥 第一次订阅时注册回调，后续订阅传 None
                        if idx == 0:
                            await adapter.subscribe_ticker(exchange_symbol, lighter_callback)
                            self.logger.info(f"✅ 已订阅 lighter.{exchange_symbol} (首次注册回调)")
                        else:
                            await adapter.subscribe_ticker(exchange_symbol, None)
                            self.logger.info(f"✅ 已订阅 lighter.{exchange_symbol}")
                    except Exception as e:
                        self.logger.error(f"❌ 订阅失败 lighter.{symbol}: {e}")
                
                self.logger.info(f"✅ Lighter 订阅完成，共 {len(self.config.symbols)} 个symbol，统一回调")
                continue
            
            # 🔥 其他交易所（Backpack, EdgeX）：逐个订阅
            for symbol in self.config.symbols:
                try:
                    # 符号转换：标准格式 -> 交易所格式
                    exchange_symbol = self.symbol_converter.convert_to_exchange(symbol, exchange_name)
                    
                    # 创建包装回调函数，处理不同适配器的回调签名
                    def create_callback(ex, std_symbol):
                        """创建回调函数工厂，捕获当前的 exchange 和 symbol"""
                        def callback_wrapper(*args, **kwargs):
                            # 兼容不同的回调签名
                            if len(args) == 1:
                                # 只有 ticker 数据
                                ticker = args[0]
                            elif len(args) == 2:
                                # symbol + ticker（Backpack 格式）
                                _, ticker = args
                            else:
                                self.logger.error(f"⚠️  未知的回调参数格式: {len(args)} 个参数")
                                return
                            
                            # 调用统一的处理函数
                            self._on_ticker_update(ex, std_symbol, ticker)
                        return callback_wrapper
                    
                    # 订阅ticker数据（使用包装后的回调）
                    await adapter.subscribe_ticker(
                        exchange_symbol,
                        create_callback(exchange_name, symbol)
                    )
                    self.logger.info(f"✅ 已订阅 {exchange_name}.{exchange_symbol} (标准: {symbol})")
                except Exception as e:
                    self.logger.error(f"❌ 订阅失败 {exchange_name}.{symbol}: {e}")
    
    async def _unsubscribe_all(self):
        """取消所有订阅"""
        for exchange_name, adapter in self.adapters.items():
            try:
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
            except Exception as e:
                self.logger.error(f"❌ 断开连接失败 {exchange_name}: {e}")
    
    def _on_ticker_update(self, exchange: str, symbol: str, ticker: TickerData):
        """处理ticker更新"""
        # 🔥 数据验证：过滤异常价格
        if not self._validate_ticker_data(ticker, exchange, symbol):
            return
        
        # 🔥 记录数据更新时间（新增 - 用于连接健康检查）
        self.last_data_time[exchange][symbol] = datetime.now()
        
        # 重置重连计数（数据正常更新说明连接恢复）
        if self.reconnect_attempts[exchange] > 0:
            self.logger.info(f"✅ {exchange} 数据恢复正常，重置重连计数")
            self.reconnect_attempts[exchange] = 0
        
        self.ticker_data[exchange][symbol] = ticker
        self.logger.debug(f"📊 {exchange}.{symbol}: 价格={ticker.last}, 资金费率={ticker.funding_rate}")
    
    def _validate_ticker_data(self, ticker: TickerData, exchange: str, symbol: str) -> bool:
        """
        验证 ticker 数据是否合理
        
        Args:
            ticker: ticker 数据
            exchange: 交易所名称
            symbol: 交易对符号
            
        Returns:
            数据是否有效
        """
        try:
            # 1. 价格必须存在且大于 0
            if ticker.last is None or ticker.last <= 0:
                self.logger.warning(f"⚠️  {exchange}.{symbol}: 价格无效 (last={ticker.last})")
                return False
            
            # 2. 价格不能异常大（> 10亿）
            if ticker.last > Decimal("1000000000"):
                self.logger.warning(f"⚠️  {exchange}.{symbol}: 价格异常大 (last={ticker.last})")
                return False
            
            # 3. 价格不能异常小（< 0.0001）
            if ticker.last < Decimal("0.0001"):
                self.logger.warning(f"⚠️  {exchange}.{symbol}: 价格异常小 (last={ticker.last})")
                return False
            
            # 4. 对于主流币种，检查价格范围是否合理
            if symbol in ['BTC-USDC-PERP', 'BTC-USD-PERP']:
                # BTC 价格应该在 10,000 ~ 200,000 之间
                if ticker.last < Decimal("10000") or ticker.last > Decimal("200000"):
                    self.logger.warning(
                        f"⚠️  {exchange}.{symbol}: BTC价格超出合理范围 (last={ticker.last})")
                    return False
            
            elif symbol in ['ETH-USDC-PERP', 'ETH-USD-PERP']:
                # ETH 价格应该在 500 ~ 10,000 之间
                if ticker.last < Decimal("500") or ticker.last > Decimal("10000"):
                    self.logger.warning(
                        f"⚠️  {exchange}.{symbol}: ETH价格超出合理范围 (last={ticker.last})")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 验证ticker数据失败 {exchange}.{symbol}: {e}")
            return False
    
    async def _monitor_loop(self):
        """监控循环"""
        self.logger.info("🔄 启动监控循环...")
        
        while self.running:
            try:
                await asyncio.sleep(self.config.update_interval)
                
                # 计算所有交易对的套利机会
                all_opportunities = []
                
                for symbol in self.config.symbols:
                    opportunities = await self._check_arbitrage_opportunity(symbol)
                    all_opportunities.extend(opportunities)
                
                # 更新机会缓存
                self.opportunities = all_opportunities
                
                # 调用回调函数
                if all_opportunities:
                    for callback in self.opportunity_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(all_opportunities)
                            else:
                                callback(all_opportunities)
                        except Exception as e:
                            self.logger.error(f"❌ 回调函数执行失败: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"❌ 监控循环错误: {e}", exc_info=True)
    
    async def _check_arbitrage_opportunity(self, symbol: str) -> List[ArbitrageOpportunity]:
        """检查单个交易对的套利机会"""
        # 收集所有交易所的价格和资金费率
        prices = {}
        funding_rates = {}
        
        for exchange_name in self.adapters.keys():
            ticker = self.ticker_data[exchange_name].get(symbol)
            
            if ticker:
                # 价格
                if ticker.last and ticker.last > 0:
                    prices[exchange_name] = ticker.last
                
                # 资金费率
                if ticker.funding_rate is not None:
                    funding_rates[exchange_name] = ticker.funding_rate
        
        # 至少需要2个交易所有价格数据
        if len(prices) < 2:
            return []
        
        # 识别套利机会
        opportunities = self._identify_opportunities(
            symbol=symbol,
            prices=prices,
            funding_rates=funding_rates if len(funding_rates) >= 2 else None
        )
        
        return opportunities
    
    def _identify_opportunities(
        self,
        symbol: str,
        prices: Dict[str, Decimal],
        funding_rates: Optional[Dict[str, Decimal]] = None
    ) -> List[ArbitrageOpportunity]:
        """识别套利机会"""
        opportunities = []
        
        # 1. 价差套利机会
        price_spreads = self._calculate_price_spreads(symbol, prices)
        for spread in price_spreads:
            if spread.spread_pct >= self.config.price_spread_threshold:
                opportunities.append(ArbitrageOpportunity(
                    symbol=symbol,
                    opportunity_type="price_spread",
                    price_spread=spread
                ))
        
        # 2. 资金费率套利机会
        if funding_rates:
            funding_spreads = self._calculate_funding_rate_spreads(symbol, funding_rates)
            for spread in funding_spreads:
                if spread.spread_abs >= self.config.funding_rate_threshold:
                    opportunities.append(ArbitrageOpportunity(
                        symbol=symbol,
                        opportunity_type="funding_rate",
                        funding_rate_spread=spread
                    ))
        
        # 3. 组合套利机会（价差 + 资金费率）
        if price_spreads and funding_rates:
            best_price_spread = price_spreads[0] if price_spreads else None
            
            if best_price_spread:
                buy_ex = best_price_spread.exchange_buy
                sell_ex = best_price_spread.exchange_sell
                
                if buy_ex in funding_rates and sell_ex in funding_rates:
                    rate_buy = funding_rates[buy_ex]
                    rate_sell = funding_rates[sell_ex]
                    
                    # 理想情况：买入交易所费率高，卖出交易所费率低
                    if rate_buy > rate_sell:
                        funding_spread = FundingRateSpread(
                            symbol=symbol,
                            exchange_high=buy_ex,
                            exchange_low=sell_ex,
                            rate_high=rate_buy,
                            rate_low=rate_sell,
                            spread_abs=rate_buy - rate_sell,
                            spread_pct=Decimal("0"),
                            timestamp=datetime.now()
                        )
                        
                        # 检查是否都超过阈值
                        if (best_price_spread.spread_pct >= self.config.price_spread_threshold and
                            funding_spread.spread_abs >= self.config.funding_rate_threshold):
                            opportunities.append(ArbitrageOpportunity(
                                symbol=symbol,
                                opportunity_type="combined",
                                price_spread=best_price_spread,
                                funding_rate_spread=funding_spread
                            ))
        
        # 按评分降序排列
        opportunities.sort(key=lambda x: x.score, reverse=True)
        
        return opportunities
    
    def _calculate_price_spreads(
        self,
        symbol: str,
        prices: Dict[str, Decimal]
    ) -> List[PriceSpread]:
        """计算价差"""
        spreads = []
        
        # 对所有交易所两两组合计算价差
        for exchange1, exchange2 in combinations(prices.keys(), 2):
            price1 = prices[exchange1]
            price2 = prices[exchange2]
            
            # 确保价格有效
            if price1 <= 0 or price2 <= 0:
                continue
            
            # 确定买入和卖出交易所
            if price1 < price2:
                exchange_buy = exchange1
                exchange_sell = exchange2
                price_buy = price1
                price_sell = price2
            else:
                exchange_buy = exchange2
                exchange_sell = exchange1
                price_buy = price2
                price_sell = price1
            
            # 计算价差
            spread_abs = price_sell - price_buy
            spread_pct = (spread_abs / price_buy) * Decimal("100")
            
            spreads.append(PriceSpread(
                symbol=symbol,
                exchange_buy=exchange_buy,
                exchange_sell=exchange_sell,
                price_buy=price_buy,
                price_sell=price_sell,
                spread_abs=spread_abs,
                spread_pct=spread_pct,
                timestamp=datetime.now()
            ))
        
        # 按价差百分比降序排列
        spreads.sort(key=lambda x: x.spread_pct, reverse=True)
        
        return spreads
    
    def _calculate_funding_rate_spreads(
        self,
        symbol: str,
        funding_rates: Dict[str, Decimal]
    ) -> List[FundingRateSpread]:
        """计算资金费率差"""
        spreads = []
        
        # 对所有交易所两两组合计算费率差
        for exchange1, exchange2 in combinations(funding_rates.keys(), 2):
            rate1 = funding_rates[exchange1]
            rate2 = funding_rates[exchange2]
            
            # 确定高费率和低费率交易所
            if rate1 > rate2:
                exchange_high = exchange1
                exchange_low = exchange2
                rate_high = rate1
                rate_low = rate2
            else:
                exchange_high = exchange2
                exchange_low = exchange1
                rate_high = rate2
                rate_low = rate1
            
            # 计算费率差
            spread_abs = rate_high - rate_low
            
            # 计算百分比差
            if rate_low != 0:
                spread_pct = (spread_abs / abs(rate_low)) * Decimal("100")
            else:
                spread_pct = Decimal("0")
            
            spreads.append(FundingRateSpread(
                symbol=symbol,
                exchange_high=exchange_high,
                exchange_low=exchange_low,
                rate_high=rate_high,
                rate_low=rate_low,
                spread_abs=spread_abs,
                spread_pct=spread_pct,
                timestamp=datetime.now()
            ))
        
        # 按绝对费率差降序排列
        spreads.sort(key=lambda x: x.spread_abs, reverse=True)
        
        return spreads
    
    # === 🔥 WebSocket连接监控相关方法（新增 - 解决数据停止更新问题）===
    
    async def _monitor_connections(self):
        """
        监控WebSocket连接健康状态
        
        定期检查每个交易所的数据更新情况：
        - 🔧 启动后120秒内不检查（给足够时间接收首次数据）
        - 如果数据超过阈值时间未更新，触发重连
        - 🔧 防止并发重连（同一交易所同时只能有一个重连任务）
        """
        self.logger.info(
            f"🔄 WebSocket连接监控循环已启动 "
            f"(检查间隔: {self.connection_check_interval}秒, "
            f"启动缓冲期: {self.startup_grace_period}秒)"
        )
        
        while self.running:
            try:
                current_time = datetime.now()
                
                # 🔧 启动缓冲期检查
                elapsed_since_start = (current_time - self.start_time).total_seconds()
                if elapsed_since_start < self.startup_grace_period:
                    remaining = self.startup_grace_period - elapsed_since_start
                    # 🔧 改用INFO级别，让用户看到监控循环在工作
                    if remaining > 60:  # 只在缓冲期前半段输出
                        self.logger.info(
                            f"⏳ 连接监控启动缓冲期中，剩余 {remaining:.0f} 秒后开始检查"
                        )
                    await asyncio.sleep(self.connection_check_interval)
                    continue
                
                # 检查每个交易所的数据时效性
                for exchange_name in self.adapters.keys():
                    # 🔧 检查是否正在重连
                    if self.reconnecting.get(exchange_name, False):
                        self.logger.debug(f"⏳ {exchange_name} 正在重连中，跳过本次检查")
                        continue
                    
                    # 🔧 检查重连次数
                    if self.reconnect_attempts[exchange_name] >= self.max_reconnect_attempts:
                        # 已达上限，不再检查
                        continue
                    
                    # 检查该交易所的所有监控符号
                    stale_symbols = []
                    
                    for symbol in self.config.symbols:
                        if self._is_data_stale(exchange_name, symbol, current_time):
                            stale_symbols.append(symbol)
                    
                    # 🔧 只有当大部分符号都超时时才重连（避免误判）
                    total_symbols = len(self.config.symbols)
                    stale_ratio = len(stale_symbols) / total_symbols if total_symbols > 0 else 0
                    
                    if stale_ratio > 0.5:  # 超过50%的符号超时才重连
                        self.logger.warning(
                            f"⚠️  {exchange_name} 检测到 {len(stale_symbols)}/{total_symbols} "
                            f"个符号数据超时 ({stale_ratio*100:.0f}%)"
                        )
                        
                        # 🔧 触发重连（异步执行，但标记正在重连）
                        asyncio.create_task(self._reconnect_exchange(exchange_name))
                
                # 🔧 定期输出健康检查日志（每5分钟一次）
                time_since_last_log = (current_time - self.last_health_check_log).total_seconds()
                if time_since_last_log >= self.health_check_log_interval:
                    self._log_connection_health(current_time)
                    self.last_health_check_log = current_time
                
                # 等待下次检查
                await asyncio.sleep(self.connection_check_interval)
                
            except asyncio.CancelledError:
                self.logger.info("连接监控循环已取消")
                break
            except Exception as e:
                self.logger.error(f"❌ 连接监控循环异常: {e}", exc_info=True)
                await asyncio.sleep(10)  # 出错后等待10秒再继续
    
    def _is_data_stale(self, exchange: str, symbol: str, current_time: datetime) -> bool:
        """
        检查指定交易所和符号的数据是否过期
        
        Args:
            exchange: 交易所名称
            symbol: 交易对符号
            current_time: 当前时间
            
        Returns:
            bool: 数据是否过期
        """
        last_update = self.last_data_time.get(exchange, {}).get(symbol)
        
        # 如果从未收到数据，认为是过期的
        if not last_update:
            return True
        
        # 计算距离上次更新的时间
        elapsed = (current_time - last_update).total_seconds()
        
        # 超过阈值认为过期
        return elapsed > self.data_timeout_seconds
    
    def _log_connection_health(self, current_time: datetime):
        """
        输出连接健康状态日志
        
        定期输出每个交易所的数据更新情况，帮助用户了解系统状态
        
        Args:
            current_time: 当前时间
        """
        self.logger.info("=" * 60)
        self.logger.info("📊 WebSocket 连接健康检查")
        
        for exchange_name in self.adapters.keys():
            # 统计该交易所的数据状态
            total_symbols = len(self.config.symbols)
            stale_count = 0
            min_elapsed = None
            max_elapsed = None
            
            for symbol in self.config.symbols:
                last_update = self.last_data_time.get(exchange_name, {}).get(symbol)
                
                if not last_update:
                    stale_count += 1
                    continue
                
                elapsed = (current_time - last_update).total_seconds()
                
                if self._is_data_stale(exchange_name, symbol, current_time):
                    stale_count += 1
                
                # 更新最小/最大时间差
                if min_elapsed is None or elapsed < min_elapsed:
                    min_elapsed = elapsed
                if max_elapsed is None or elapsed > max_elapsed:
                    max_elapsed = elapsed
            
            # 输出状态
            healthy_count = total_symbols - stale_count
            status = "✅ 正常" if stale_count == 0 else f"⚠️  异常 ({stale_count}个超时)"
            
            if min_elapsed is not None and max_elapsed is not None:
                self.logger.info(
                    f"  {exchange_name:10s}: {status} | "
                    f"健康: {healthy_count}/{total_symbols} | "
                    f"数据延迟: {min_elapsed:.0f}~{max_elapsed:.0f}秒"
                )
            else:
                self.logger.info(
                    f"  {exchange_name:10s}: {status} | "
                    f"健康: {healthy_count}/{total_symbols} | "
                    f"数据延迟: 无数据"
                )
            
            # 显示重连次数
            reconnect_count = self.reconnect_attempts.get(exchange_name, 0)
            if reconnect_count > 0:
                self.logger.info(
                    f"    ↳ 重连次数: {reconnect_count}/{self.max_reconnect_attempts}"
                )
        
        self.logger.info("=" * 60)
    
    async def _reconnect_exchange(self, exchange_name: str):
        """
        重连指定交易所
        
        重连流程：
        1. 🔧 设置重连标志（防止并发）
        2. 断开现有连接
        3. 等待一段时间
        4. 重新连接
        5. 恢复所有订阅
        6. 🔧 清除重连标志
        
        Args:
            exchange_name: 交易所名称
        """
        try:
            # 🔧 防止并发重连
            if self.reconnecting.get(exchange_name, False):
                self.logger.warning(f"⚠️  {exchange_name} 已经在重连中，跳过")
                return
            
            # 设置重连标志
            self.reconnecting[exchange_name] = True
            
            self.reconnect_attempts[exchange_name] += 1
            attempt = self.reconnect_attempts[exchange_name]
            
            self.logger.info(
                f"🔄 开始重连 {exchange_name} "
                f"(第 {attempt}/{self.max_reconnect_attempts} 次尝试)..."
            )
            
            adapter = self.adapters.get(exchange_name)
            if not adapter:
                self.logger.error(f"❌ {exchange_name} 适配器不存在")
                return
            
            # 1. 断开现有连接
            try:
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
                    self.logger.info(f"✅ {exchange_name} 已断开连接")
            except Exception as e:
                self.logger.warning(f"⚠️  {exchange_name} 断开连接时出错: {e}")
            
            # 2. 等待一段时间（指数退避）
            wait_time = min(5 * attempt, 30)  # 最多等30秒
            self.logger.info(f"⏳ 等待 {wait_time} 秒后重连...")
            await asyncio.sleep(wait_time)
            
            # 3. 重新连接
            try:
                if hasattr(adapter, 'connect'):
                    await adapter.connect()
                    self.logger.info(f"✅ {exchange_name} 已重新连接")
            except Exception as e:
                self.logger.error(f"❌ {exchange_name} 重新连接失败: {e}")
                return
            
            # 4. 恢复所有订阅
            self.logger.info(f"📡 恢复 {exchange_name} 的订阅...")
            
            # 🔥 Lighter 特殊处理
            if exchange_name == "lighter":
                # 使用统一回调
                def lighter_callback(ticker):
                    """Lighter 统一回调"""
                    try:
                        std_symbol = self.symbol_converter.convert_from_exchange(
                            ticker.symbol, "lighter"
                        )
                        if std_symbol in self.config.symbols:
                            self._on_ticker_update("lighter", std_symbol, ticker)
                    except Exception as e:
                        self.logger.error(
                            f"❌ Lighter 回调处理失败 (symbol={ticker.symbol}): {e}"
                        )
                
                # 重新订阅所有符号
                for idx, symbol in enumerate(self.config.symbols):
                    try:
                        exchange_symbol = self.symbol_converter.convert_to_exchange(
                            symbol, "lighter"
                        )
                        
                        if idx == 0:
                            await adapter.subscribe_ticker(exchange_symbol, lighter_callback)
                        else:
                            await adapter.subscribe_ticker(exchange_symbol, None)
                        
                        self.logger.debug(f"✅ 已重新订阅 lighter.{exchange_symbol}")
                    except Exception as e:
                        self.logger.error(f"❌ 重新订阅失败 lighter.{symbol}: {e}")
            
            # 🔥 其他交易所
            else:
                for symbol in self.config.symbols:
                    try:
                        exchange_symbol = self.symbol_converter.convert_to_exchange(
                            symbol, exchange_name
                        )
                        
                        # 创建回调函数
                        def create_callback(ex, std_symbol):
                            def callback_wrapper(*args, **kwargs):
                                if len(args) == 1:
                                    ticker = args[0]
                                elif len(args) == 2:
                                    _, ticker = args
                                else:
                                    return
                                self._on_ticker_update(ex, std_symbol, ticker)
                            return callback_wrapper
                        
                        # 重新订阅
                        await adapter.subscribe_ticker(
                            exchange_symbol,
                            create_callback(exchange_name, symbol)
                        )
                        
                        self.logger.debug(
                            f"✅ 已重新订阅 {exchange_name}.{exchange_symbol}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"❌ 重新订阅失败 {exchange_name}.{symbol}: {e}"
                        )
            
            self.logger.info(
                f"✅ {exchange_name} 重连完成，已恢复所有订阅 "
                f"(共 {len(self.config.symbols)} 个符号)"
            )
            
        except Exception as e:
            self.logger.error(f"❌ {exchange_name} 重连过程失败: {e}", exc_info=True)
        finally:
            # 🔧 清除重连标志（无论成功还是失败）
            self.reconnecting[exchange_name] = False

