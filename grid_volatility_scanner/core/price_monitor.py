"""
价格监控器 - Price Monitor

通过WebSocket监听实时价格并更新虚拟网格
"""

import asyncio
import logging
from decimal import Decimal
from typing import Dict, Callable, Optional, Awaitable
from datetime import datetime


logger = logging.getLogger(__name__)


class PriceMonitor:
    """
    价格监控器
    
    功能：
    1. 订阅WebSocket价格推送
    2. 接收market_stats数据
    3. 将价格更新分发到对应的虚拟网格
    4. 处理WebSocket断线重连
    """
    
    def __init__(
        self,
        exchange_adapter,
        price_callback: Optional[Callable[[str, Decimal], Awaitable[None]]] = None
    ):
        """
        初始化价格监控器
        
        Args:
            exchange_adapter: 交易所适配器（LighterAdapter）
            price_callback: 价格更新回调函数（symbol, price）
        """
        self.adapter = exchange_adapter
        self.price_callback = price_callback
        self._running = False
        self._last_price_update: Dict[str, datetime] = {}
        
        logger.info("价格监控器初始化完成")
    
    async def start(self, symbols: list):
        """
        启动价格监控
        
        Args:
            symbols: 需要监控的交易对列表
        """
        self._running = True
        logger.info(f"开始监控 {len(symbols)} 个交易对的价格")
        
        # 订阅WebSocket价格推送
        # Lighter使用market_stats订阅
        # 这里简化实现，实际应该通过adapter的WebSocket接口订阅
        logger.warning("⚠️ 价格监控器需要与Lighter WebSocket集成，当前为占位实现")
    
    async def stop(self):
        """停止价格监控"""
        self._running = False
        logger.info("价格监控已停止")
    
    async def on_price_update(self, symbol: str, price: Decimal):
        """
        处理价格更新
        
        Args:
            symbol: 交易对符号
            price: 新价格
        """
        # 记录更新时间
        self._last_price_update[symbol] = datetime.now()
        
        # 调用回调函数
        if self.price_callback:
            try:
                await self.price_callback(symbol, price)
            except Exception as e:
                logger.error(f"处理 {symbol} 价格更新失败: {e}")
    
    def get_last_update_time(self, symbol: str) -> Optional[datetime]:
        """
        获取最后更新时间
        
        Args:
            symbol: 交易对符号
            
        Returns:
            最后更新时间，如果没有更新过则返回None
        """
        return self._last_price_update.get(symbol)
    
    def is_stale(self, symbol: str, timeout_seconds: int = 30) -> bool:
        """
        检查价格是否过期
        
        Args:
            symbol: 交易对符号
            timeout_seconds: 超时时间（秒）
            
        Returns:
            True表示价格已过期
        """
        last_update = self.get_last_update_time(symbol)
        if not last_update:
            return True
        
        elapsed = (datetime.now() - last_update).total_seconds()
        return elapsed > timeout_seconds

