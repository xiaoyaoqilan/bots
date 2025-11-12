"""
循环检测器 - Cycle Detector

检测完整的买卖循环
"""

from decimal import Decimal
from typing import Optional


class CycleDetector:
    """
    循环检测器
    
    功能：
    1. 检测价格穿越网格线
    2. 统计买入和卖出穿越
    3. 计算完整循环次数（1买1卖配对）
    """
    
    @staticmethod
    def detect_cross(
        old_price: Decimal,
        new_price: Decimal,
        grid_lines: list
    ) -> Optional[str]:
        """
        检测价格是否穿越网格线
        
        Args:
            old_price: 旧价格
            new_price: 新价格
            grid_lines: 网格线列表
            
        Returns:
            'buy': 向上穿越
            'sell': 向下穿越
            None: 未穿越
        """
        if new_price > old_price:
            return 'buy'
        elif new_price < old_price:
            return 'sell'
        return None
    
    @staticmethod
    def calculate_cycles(buy_count: int, sell_count: int) -> int:
        """
        计算完整循环次数
        
        Args:
            buy_count: 买入穿越次数
            sell_count: 卖出穿越次数
            
        Returns:
            完整循环次数 = min(买入次数, 卖出次数)
        """
        return min(buy_count, sell_count)

