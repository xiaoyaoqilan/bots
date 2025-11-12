"""价格监控报警服务实现"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
from pathlib import Path

from ....adapters.exchanges.interface import ExchangeInterface
from ....adapters.exchanges.models import TickerData
from ..interfaces.price_alert_service import IPriceAlertService
from ..models.alert_config import PriceAlertSystemConfig, SymbolConfig
from ..models.alert_statistics import SymbolStatistics


class PriceAlertServiceImpl(IPriceAlertService):
    """价格监控报警服务实现"""

    def __init__(self, exchange_adapter: ExchangeInterface):
        """
        初始化服务
        
        Args:
            exchange_adapter: 交易所适配器
        """
        self.exchange_adapter = exchange_adapter
        self.config: Optional[PriceAlertSystemConfig] = None
        self.statistics: Dict[str, SymbolStatistics] = {}
        self.logger: Optional[logging.Logger] = None
        self.alert_logger: Optional[logging.Logger] = None
        
        self._running = False
        self._should_stop = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def initialize(self, config: PriceAlertSystemConfig) -> bool:
        """初始化服务"""
        try:
            self.config = config
            
            # 设置日志
            self._setup_logging()
            
            self.logger.info("=" * 70)
            self.logger.info("🚨 价格监控报警系统")
            self.logger.info("=" * 70)
            self.logger.info(f"交易所: {config.exchange.upper()}")
            self.logger.info(f"监控代币数量: {len([s for s in config.symbols if s.enabled])}")
            self.logger.info("=" * 70)
            
            # 初始化统计数据
            for symbol_config in config.symbols:
                if symbol_config.enabled:
                    self.statistics[symbol_config.symbol] = SymbolStatistics(
                        symbol=symbol_config.symbol
                    )
                    self.logger.info(f"✅ 已添加监控: {symbol_config.symbol} ({symbol_config.market_type})")
            
            # 连接交易所
            if not self.exchange_adapter.is_connected():
                self.logger.info(f"🔗 连接到{config.exchange.upper()}...")
                await self.exchange_adapter.connect()
                self.logger.info(f"✅ {config.exchange.upper()}连接成功")
            
            self.logger.info("✅ 初始化完成")
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"❌ 初始化失败: {e}")
            return False

    async def start(self):
        """启动监控"""
        if self._running:
            self.logger.warning("监控已在运行中")
            return
        
        self._running = True
        self._should_stop = False
        
        self.logger.info("🚀 启动价格监控...")
        
        # 订阅所有代币的ticker数据
        await self._subscribe_tickers()
        
        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        try:
            await self._monitor_task
        except asyncio.CancelledError:
            self.logger.info("监控任务已取消")

    async def stop(self):
        """停止监控"""
        if not self._running:
            return
        
        self.logger.info("⏸️  正在停止监控...")
        self._should_stop = True
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self._running = False
        self.logger.info("✅ 监控已停止")

    def get_statistics(self) -> Dict[str, SymbolStatistics]:
        """获取统计数据"""
        return self.statistics

    async def _subscribe_tickers(self):
        """订阅ticker数据"""
        symbols = [s.symbol for s in self.config.symbols if s.enabled]
        
        self.logger.info(f"📡 订阅{len(symbols)}个代币的价格数据...")
        
        # 为每个交易对单独订阅ticker
        for symbol in symbols:
            try:
                # 创建带symbol上下文的回调函数
                def create_callback(sym: str):
                    async def callback(ticker: TickerData):
                        await self._on_ticker_update(sym, ticker)
                    return callback
                
                await self.exchange_adapter.subscribe_ticker(
                    symbol=symbol,
                    callback=create_callback(symbol)
                )
                self.logger.info(f"✅ {symbol} 订阅成功")
            except Exception as e:
                self.logger.error(f"❌ {symbol} 订阅失败: {e}")
        
        self.logger.info("✅ 所有订阅完成")

    async def _on_ticker_update(self, symbol: str, ticker: TickerData):
        """ticker更新回调"""
        if symbol not in self.statistics:
            return
        
        stats = self.statistics[symbol]
        
        # 更新价格数据
        stats.add_price_point(ticker.last, datetime.now())
        
        # 更新24小时数据
        if ticker.open:
            stats.price_24h_ago = ticker.open
        if ticker.high:
            stats.highest_price_24h = ticker.high
        if ticker.low:
            stats.lowest_price_24h = ticker.low
        
        # 检查报警条件
        await self._check_alerts(symbol)

    async def _check_alerts(self, symbol: str):
        """检查报警条件"""
        if symbol not in self.statistics:
            return
        
        stats = self.statistics[symbol]
        symbol_config = self._get_symbol_config(symbol)
        
        if not symbol_config:
            return
        
        # 检查波动报警
        if symbol_config.volatility_alert.enabled:
            await self._check_volatility_alert(symbol, stats, symbol_config)
        
        # 检查价格目标报警
        if symbol_config.price_alert.enabled:
            await self._check_price_alert(symbol, stats, symbol_config)

    async def _check_volatility_alert(self, symbol: str, stats: SymbolStatistics, symbol_config: SymbolConfig):
        """检查波动报警"""
        time_window = symbol_config.volatility_alert.time_window
        threshold = symbol_config.volatility_alert.threshold_percent
        
        change_percent = stats.get_price_change_percent(time_window)
        
        if change_percent is None:
            return
        
        # 检查是否超过阈值
        if abs(change_percent) >= threshold:
            # 检查冷却时间
            if stats.can_alert("volatility", self.config.alert.cooldown_seconds):
                direction = "上涨" if change_percent > 0 else "下跌"
                message = f"⚠️ {symbol} {time_window}秒内{direction} {abs(change_percent):.2f}% (阈值: {threshold}%)"
                
                await self._trigger_alert("volatility", symbol, message, change_percent)
                stats.record_alert("volatility")

    async def _check_price_alert(self, symbol: str, stats: SymbolStatistics, symbol_config: SymbolConfig):
        """检查价格目标报警"""
        current_price = stats.current_price
        upper_limit = symbol_config.price_alert.upper_limit
        lower_limit = symbol_config.price_alert.lower_limit
        
        # 检查价格上限
        if upper_limit > Decimal("0") and current_price >= upper_limit:
            if stats.can_alert("price_upper", self.config.alert.cooldown_seconds):
                message = f"📈 {symbol} 突破上限 {upper_limit} (当前: {current_price})"
                await self._trigger_alert("price_upper", symbol, message)
                stats.record_alert("price_upper")
        
        # 检查价格下限
        if lower_limit > Decimal("0") and current_price <= lower_limit:
            if stats.can_alert("price_lower", self.config.alert.cooldown_seconds):
                message = f"📉 {symbol} 跌破下限 {lower_limit} (当前: {current_price})"
                await self._trigger_alert("price_lower", symbol, message)
                stats.record_alert("price_lower")

    async def _trigger_alert(self, alert_type: str, symbol: str, message: str, change_percent: float = 0):
        """触发报警"""
        # 记录到日志
        self.logger.warning(message)
        
        # 记录到报警历史
        if self.alert_logger:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.alert_logger.info(f"[{timestamp}] {alert_type.upper()} | {message}")
        
        # 播放声音
        if self.config.alert.sound_enabled:
            await self._play_alert_sound()

    async def _play_alert_sound(self):
        """播放报警声音"""
        try:
            sound_type = self.config.alert.sound_type
            duration = self.config.alert.sound_duration
            repeat = self.config.alert.sound_repeat
            
            if sound_type == "beep":
                # 使用系统beep
                for _ in range(repeat):
                    # 跨平台beep
                    if sys.platform == "darwin":  # macOS
                        os.system(f"afplay /System/Library/Sounds/Ping.aiff &")
                    elif sys.platform.startswith("linux"):
                        os.system("beep -f 1000 -l 500 &")
                    elif sys.platform == "win32":
                        import winsound
                        winsound.Beep(1000, int(duration * 1000))
                    else:
                        # 终端bell
                        print("\a", flush=True)
                    
                    await asyncio.sleep(duration)
            
            elif sound_type == "system":
                # 使用系统铃声
                if sys.platform == "darwin":
                    for _ in range(repeat):
                        os.system("afplay /System/Library/Sounds/Sosumi.aiff &")
                        await asyncio.sleep(1)
                else:
                    # 其他系统使用终端bell
                    for _ in range(repeat):
                        print("\a", flush=True)
                        await asyncio.sleep(duration)
        
        except Exception as e:
            self.logger.error(f"播放声音失败: {e}")

    async def _monitor_loop(self):
        """监控循环"""
        while not self._should_stop:
            await asyncio.sleep(1)

    def _get_symbol_config(self, symbol: str) -> Optional[SymbolConfig]:
        """获取代币配置"""
        for s in self.config.symbols:
            if s.symbol == symbol:
                return s
        return None

    def _setup_logging(self):
        """设置日志"""
        if not self.config.logging.enabled:
            return
        
        # 创建日志目录
        log_dir = Path(self.config.logging.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 主日志
        self.logger = logging.getLogger("PriceAlertService")
        self.logger.setLevel(getattr(logging, self.config.logging.log_level))
        
        if self.config.logging.log_to_file:
            log_file = log_dir / self.config.logging.log_file
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(file_handler)
        
        if self.config.logging.log_to_console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(console_handler)
        
        # 报警历史日志
        self.alert_logger = logging.getLogger("AlertHistory")
        self.alert_logger.setLevel(logging.INFO)
        
        alert_file = Path(self.config.logging.alert_history_file)
        alert_file.parent.mkdir(parents=True, exist_ok=True)
        alert_handler = logging.FileHandler(alert_file, encoding='utf-8')
        alert_handler.setFormatter(logging.Formatter('%(message)s'))
        self.alert_logger.addHandler(alert_handler)

