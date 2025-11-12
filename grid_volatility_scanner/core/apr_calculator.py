"""
APR计算器 - APR Calculator

计算预估年化APR
"""

from decimal import Decimal


class APRCalculator:
    """
    APR计算器
    
    公式：
    APR = (格子间距% - 手续费%) × 格子间距% / 网格宽度% × 每小时循环 × 8760
    
    说明：
    - 每格订单价值固定为10 USDC
    - 手续费率固定为0.004%（双边）
    - 8760 = 24小时 × 365天
    """
    
    # 固定参数
    ORDER_VALUE_USDC = Decimal('10')         # 每格订单价值
    FEE_RATE_PERCENT = Decimal('0.004')      # 双边手续费率（%）
    HOURS_PER_YEAR = Decimal('8760')         # 一年小时数
    
    @staticmethod
    def calculate(
        grid_interval_percent: Decimal,
        grid_width_percent: Decimal,
        cycles_per_hour: Decimal
    ) -> Decimal:
        """
        计算预估APR
        
        Args:
            grid_interval_percent: 格子间距百分比（如0.5表示0.5%）
            grid_width_percent: 网格总宽度百分比（如5.0表示±5%）
            cycles_per_hour: 每小时循环次数
            
        Returns:
            年化APR（%）
            
        示例：
            格子间距 = 0.5%
            网格宽度 = 10%
            每小时循环 = 10次
            手续费 = 0.004%
            
            APR = (0.5 - 0.004) × 0.5 / 10 × 10 × 8760
                = 0.496 × 0.05 × 87600
                = 2172.48%
        """
        # 计算净收益率
        net_profit_rate = grid_interval_percent - APRCalculator.FEE_RATE_PERCENT
        
        if net_profit_rate <= 0:
            return Decimal('0')  # 手续费超过利润，无法盈利
        
        # 计算单次循环收益率
        single_cycle_rate = net_profit_rate * grid_interval_percent / grid_width_percent
        
        # 计算年化APR
        annual_apr = single_cycle_rate * cycles_per_hour * APRCalculator.HOURS_PER_YEAR
        
        return annual_apr
    
    @staticmethod
    def calculate_total_capital(
        grid_width_percent: Decimal,
        grid_interval_percent: Decimal
    ) -> Decimal:
        """
        计算总投入本金
        
        Args:
            grid_width_percent: 网格总宽度百分比
            grid_interval_percent: 格子间距百分比
            
        Returns:
            总投入本金（USDC）
            
        公式：
            网格数量 = grid_width_percent / grid_interval_percent
            总本金 = ORDER_VALUE_USDC × 网格数量
        """
        grid_count = grid_width_percent / grid_interval_percent
        total_capital = APRCalculator.ORDER_VALUE_USDC * grid_count
        return total_capital
    
    @staticmethod
    def calculate_profit_per_cycle(
        grid_interval_percent: Decimal
    ) -> Decimal:
        """
        计算单次循环收益
        
        Args:
            grid_interval_percent: 格子间距百分比
            
        Returns:
            单次循环净收益（USDC）
            
        公式：
            净收益 = ORDER_VALUE_USDC × (grid_interval_percent - FEE_RATE_PERCENT) / 100
        """
        net_rate = (grid_interval_percent - APRCalculator.FEE_RATE_PERCENT) / Decimal('100')
        profit = APRCalculator.ORDER_VALUE_USDC * net_rate
        return profit

