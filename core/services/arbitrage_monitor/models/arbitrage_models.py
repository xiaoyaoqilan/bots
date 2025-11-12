"""
套利监控数据模型

定义价差、资金费率差、套利机会和配置的数据结构。
"""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import List, Optional


@dataclass
class ArbitrageConfig:
    """套利监控配置"""
    # 交易所列表
    exchanges: List[str] = field(default_factory=list)
    
    # 监控的交易对列表
    symbols: List[str] = field(default_factory=list)
    
    # 阈值配置
    price_spread_threshold: Decimal = Decimal("0.005")      # 价差阈值（0.5%）
    funding_rate_threshold: Decimal = Decimal("0.0001")     # 资金费率差阈值（0.01%）
    min_score_threshold: Decimal = Decimal("0.001")         # 最小评分阈值（0.1%）
    
    # 监控配置
    update_interval: int = 5                               # 更新间隔（秒）
    enable_sound_alert: bool = True                        # 启用声音报警
    alert_repeat: int = 3                                  # 报警重复次数
    
    # 显示配置
    refresh_rate: float = 1.0                             # 刷新率（秒）
    max_opportunities: int = 20                           # 最多显示的套利机会数量
    show_all_prices: bool = True                          # 显示所有交易对价格
    show_funding_rates: bool = True                       # 显示资金费率


@dataclass
class PriceSpread:
    """价差数据"""
    symbol: str                     # 标准化交易对符号（如BTC-USDC-PERP）
    exchange_buy: str               # 买入交易所（价格低）
    exchange_sell: str              # 卖出交易所（价格高）
    price_buy: Decimal             # 买入价格
    price_sell: Decimal            # 卖出价格
    spread_abs: Decimal            # 绝对价差
    spread_pct: Decimal            # 百分比价差
    timestamp: datetime            # 时间戳
    
    @property
    def spread_bps(self) -> int:
        """价差（基点，1bp = 0.01%）"""
        return int(self.spread_pct * 10000)


@dataclass
class FundingRateSpread:
    """资金费率差"""
    symbol: str                     # 标准化交易对符号
    exchange_high: str              # 资金费率高的交易所
    exchange_low: str               # 资金费率低的交易所
    rate_high: Decimal             # 高资金费率
    rate_low: Decimal              # 低资金费率
    spread_abs: Decimal            # 绝对费率差
    spread_pct: Decimal            # 百分比费率差
    timestamp: datetime            # 时间戳
    
    @property
    def spread_bps(self) -> int:
        """费率差（基点）"""
        return int(self.spread_abs * 10000)


@dataclass
class ArbitrageOpportunity:
    """套利机会"""
    symbol: str                                             # 标准化交易对符号
    opportunity_type: str                                    # 机会类型：price_spread/funding_rate/combined
    
    # 价差相关
    price_spread: Optional[PriceSpread] = None
    
    # 资金费率相关
    funding_rate_spread: Optional[FundingRateSpread] = None
    
    # 综合评分
    score: Decimal = Decimal("0")                          # 套利评分
    
    # 时间戳
    detected_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """计算综合评分"""
        if self.opportunity_type == "price_spread" and self.price_spread:
            self.score = self.price_spread.spread_pct
        elif self.opportunity_type == "funding_rate" and self.funding_rate_spread:
            self.score = self.funding_rate_spread.spread_abs
        elif self.opportunity_type == "combined":
            price_score = self.price_spread.spread_pct if self.price_spread else Decimal("0")
            funding_score = self.funding_rate_spread.spread_abs if self.funding_rate_spread else Decimal("0")
            self.score = price_score + funding_score
    
    def is_profitable(self, min_score: Decimal = Decimal("0.001")) -> bool:
        """
        判断是否有利可图
        
        Args:
            min_score: 最小评分阈值
        
        Returns:
            是否有利可图
        """
        return self.score >= min_score

