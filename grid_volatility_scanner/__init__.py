"""
网格波动率扫描器 - Grid Volatility Scanner

功能：
- 实时监控所有市场的价格波动
- 模拟网格交易，统计循环次数
- 计算预估年化APR
- 提供代币选择建议

核心原理：
1. 为每个交易对创建虚拟网格（不实际下单）
2. 通过WebSocket接收实时价格
3. 检测价格穿越网格线
4. 统计完整循环次数（1买1卖配对）
5. 计算实时APR并排序
"""

__version__ = "1.0.0"
__author__ = "Crypto Trading System"

from .models.virtual_grid import VirtualGrid
from .models.simulation_result import SimulationResult
from .core.price_monitor import PriceMonitor
from .core.cycle_detector import CycleDetector
from .core.apr_calculator import APRCalculator

__all__ = [
    'VirtualGrid',
    'SimulationResult',
    'PriceMonitor',
    'CycleDetector',
    'APRCalculator',
]

