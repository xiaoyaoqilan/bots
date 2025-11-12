"""价格监控统计模型"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from collections import deque


@dataclass
class PricePoint:
    """价格点数据"""
    timestamp: datetime
    price: Decimal


@dataclass
class SymbolStatistics:
    """单个代币统计数据"""
    symbol: str
    current_price: Decimal = Decimal("0")
    price_24h_ago: Decimal = Decimal("0")
    highest_price_24h: Decimal = Decimal("0")
    lowest_price_24h: Decimal = Decimal("0")
    
    # 时间窗口内的价格历史
    price_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    # 报警统计
    total_alerts: int = 0
    volatility_alerts: int = 0
    price_upper_alerts: int = 0
    price_lower_alerts: int = 0
    
    # 最后报警时间（用于冷却）
    last_volatility_alert_time: Optional[datetime] = None
    last_price_upper_alert_time: Optional[datetime] = None
    last_price_lower_alert_time: Optional[datetime] = None
    
    # 最后更新时间
    last_update_time: Optional[datetime] = None
    
    def add_price_point(self, price: Decimal, timestamp: datetime = None):
        """添加价格点"""
        if timestamp is None:
            timestamp = datetime.now()
        self.price_history.append(PricePoint(timestamp=timestamp, price=price))
        self.current_price = price
        self.last_update_time = timestamp
        
        # 更新24小时最高最低价
        if self.highest_price_24h == Decimal("0") or price > self.highest_price_24h:
            self.highest_price_24h = price
        if self.lowest_price_24h == Decimal("0") or price < self.lowest_price_24h:
            self.lowest_price_24h = price
    
    def get_price_change_percent(self, time_window_seconds: int) -> Optional[float]:
        """获取指定时间窗口内的价格变化百分比"""
        if not self.price_history or len(self.price_history) < 2:
            return None
        
        current_time = datetime.now()
        current_price = self.current_price
        
        # 找到时间窗口开始时的价格
        window_start_price = None
        for price_point in reversed(self.price_history):
            time_diff = (current_time - price_point.timestamp).total_seconds()
            if time_diff >= time_window_seconds:
                window_start_price = price_point.price
                break
        
        if window_start_price is None or window_start_price == Decimal("0"):
            return None
        
        # 计算百分比变化
        change_percent = float((current_price - window_start_price) / window_start_price * 100)
        return change_percent
    
    def get_24h_change_percent(self) -> Optional[float]:
        """获取24小时价格变化百分比"""
        if self.price_24h_ago == Decimal("0") or self.current_price == Decimal("0"):
            return None
        
        change_percent = float((self.current_price - self.price_24h_ago) / self.price_24h_ago * 100)
        return change_percent
    
    def can_alert(self, alert_type: str, cooldown_seconds: int) -> bool:
        """检查是否可以报警（冷却时间）"""
        now = datetime.now()
        
        if alert_type == "volatility":
            if self.last_volatility_alert_time is None:
                return True
            time_diff = (now - self.last_volatility_alert_time).total_seconds()
            return time_diff >= cooldown_seconds
        
        elif alert_type == "price_upper":
            if self.last_price_upper_alert_time is None:
                return True
            time_diff = (now - self.last_price_upper_alert_time).total_seconds()
            return time_diff >= cooldown_seconds
        
        elif alert_type == "price_lower":
            if self.last_price_lower_alert_time is None:
                return True
            time_diff = (now - self.last_price_lower_alert_time).total_seconds()
            return time_diff >= cooldown_seconds
        
        return False
    
    def record_alert(self, alert_type: str):
        """记录报警"""
        now = datetime.now()
        self.total_alerts += 1
        
        if alert_type == "volatility":
            self.volatility_alerts += 1
            self.last_volatility_alert_time = now
        elif alert_type == "price_upper":
            self.price_upper_alerts += 1
            self.last_price_upper_alert_time = now
        elif alert_type == "price_lower":
            self.price_lower_alerts += 1
            self.last_price_lower_alert_time = now

