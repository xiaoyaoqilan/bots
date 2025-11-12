"""
模拟结果模型 - Simulation Result Model

存储和管理网格模拟的最终结果
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class SimulationResult:
    """
    网格模拟结果

    用于存储和展示每个交易对的模拟结果
    """

    # 基础信息
    symbol: str                              # 交易对符号
    current_price: Decimal                   # 当前价格

    # 网格配置
    grid_width_percent: Decimal              # 网格宽度（%）
    grid_interval_percent: Decimal           # 格子间距（%）
    grid_count: int                          # 网格数量
    price_range: str                         # 价格区间（格式化字符串）

    # 统计数据
    running_seconds: int                     # 运行时长（秒）
    total_crosses: int                       # 总穿越次数
    buy_crosses: int                         # 买入穿越
    sell_crosses: int                        # 卖出穿越
    complete_cycles: int                     # 完整循环次数
    cycles_per_hour: Decimal                 # 每小时循环次数
    avg_cycles_per_5min: Decimal             # 平均5分钟循环次数（基于总运行时间）
    recent_5min_cycles: int                  # 最近5分钟的循环次数

    # APR预估
    estimated_apr: Decimal                   # 预估年化APR（%）

    # 市场数据
    volume_24h_usdc: Decimal                 # 24小时成交量（USDC）
    price_change_24h_percent: Decimal        # 24小时价格变化（%）

    # 评级
    rating: str = ""                         # 评级（S/A/B/C/D）
    score: float = 0.0                       # 综合评分（0-100）
    s_rating_duration_str: str = "--"        # S级持续时间（格式: D/H/M）

    def calculate_rating(self) -> str:
        """
        根据APR计算评级

        评级标准:
        - S级: APR >= 500%（极度推荐）
        - A级: APR >= 300%（强烈推荐）
        - B级: APR >= 150%（推荐）
        - C级: APR >= 50%（可考虑）
        - D级: APR < 50%（不推荐）

        Returns:
            评级字符串（带emoji）
        """
        apr = float(self.estimated_apr)

        if apr >= 500:
            self.rating = "🔥 S"
            self.score = 95.0
        elif apr >= 300:
            self.rating = "⭐ A"
            self.score = 85.0
        elif apr >= 150:
            self.rating = "✅ B"
            self.score = 75.0
        elif apr >= 50:
            self.rating = "🟡 C"
            self.score = 60.0
        else:
            self.rating = "❌ D"
            self.score = 40.0

        # 根据循环次数微调评分
        if self.cycles_per_hour > Decimal('50'):
            self.score += 5.0  # 高频交易加分
        elif self.cycles_per_hour < Decimal('5'):
            self.score -= 10.0  # 低频交易扣分

        # 根据成交量微调评分
        volume_millions = float(self.volume_24h_usdc) / 1_000_000
        if volume_millions >= 10:
            self.score += 5.0  # 高流动性加分
        elif volume_millions < 0.5:
            self.score -= 10.0  # 低流动性扣分

        # 限制评分范围
        self.score = max(0.0, min(100.0, self.score))

        return self.rating

    def get_running_time_str(self) -> str:
        """获取运行时长（格式化字符串）"""
        hours = self.running_seconds // 3600
        minutes = (self.running_seconds % 3600) // 60
        seconds = self.running_seconds % 60

        if hours > 0:
            return f"{hours}时{minutes}分"
        elif minutes > 0:
            return f"{minutes}分{seconds}秒"
        else:
            return f"{seconds}秒"

    def get_volume_str(self) -> str:
        """获取成交量（格式化字符串）"""
        volume = float(self.volume_24h_usdc)

        if volume >= 1_000_000:
            return f"${volume/1_000_000:.2f}M"
        elif volume >= 1_000:
            return f"${volume/1_000:.2f}K"
        else:
            return f"${volume:.0f}"

    @classmethod
    def from_virtual_grid(cls, grid: 'VirtualGrid') -> 'SimulationResult':
        """
        从虚拟网格创建模拟结果

        Args:
            grid: 虚拟网格对象

        Returns:
            SimulationResult对象
        """
        result = cls(
            symbol=grid.symbol,
            current_price=grid.current_price,
            grid_width_percent=grid.grid_width_percent,
            grid_interval_percent=grid.grid_interval_percent,
            grid_count=grid.grid_count,
            price_range=f'${grid.lower_price:,.2f} - ${grid.upper_price:,.2f}',
            running_seconds=grid.get_running_time_seconds(),
            total_crosses=grid.total_crosses,
            buy_crosses=grid.buy_crosses,
            sell_crosses=grid.sell_crosses,
            complete_cycles=grid.complete_cycles,
            cycles_per_hour=grid.cycles_per_hour,
            avg_cycles_per_5min=grid.get_avg_cycles_per_5min(),
            recent_5min_cycles=grid.get_recent_5min_cycles(),
            estimated_apr=grid.estimated_apr,
            volume_24h_usdc=grid.volume_24h_usdc,
            price_change_24h_percent=grid.price_change_24h_percent,
        )

        # 计算评级
        result.calculate_rating()
        
        # 🔥 更新VirtualGrid的评级并获取S级持续时间
        grid.update_rating(result.rating)
        result.s_rating_duration_str = grid.get_s_rating_duration_str()

        return result

    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"{self.symbol}: "
            f"APR={self.estimated_apr:.2f}%, "
            f"循环={self.complete_cycles}次, "
            f"评级={self.rating}"
        )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'current_price': float(self.current_price),
            'grid_width': f'{self.grid_width_percent}%',
            'grid_interval': f'{self.grid_interval_percent}%',
            'grid_count': self.grid_count,
            'price_range': self.price_range,
            'running_time': self.get_running_time_str(),
            'total_crosses': self.total_crosses,
            'buy_crosses': self.buy_crosses,
            'sell_crosses': self.sell_crosses,
            'complete_cycles': self.complete_cycles,
            'cycles_per_hour': float(self.cycles_per_hour),
            'estimated_apr': float(self.estimated_apr),
            'volume_24h': self.get_volume_str(),
            'price_change_24h': f'{self.price_change_24h_percent:+.2f}%',
            'rating': self.rating,
            'score': self.score,
        }
