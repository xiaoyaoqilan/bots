"""价格监控报警服务接口"""

from abc import ABC, abstractmethod
from typing import Dict
from ..models.alert_config import PriceAlertSystemConfig
from ..models.alert_statistics import SymbolStatistics


class IPriceAlertService(ABC):
    """价格监控报警服务接口"""

    @abstractmethod
    async def initialize(self, config: PriceAlertSystemConfig) -> bool:
        """
        初始化服务
        
        Args:
            config: 系统配置
            
        Returns:
            bool: 是否成功初始化
        """
        pass

    @abstractmethod
    async def start(self):
        """启动监控"""
        pass

    @abstractmethod
    async def stop(self):
        """停止监控"""
        pass

    @abstractmethod
    def get_statistics(self) -> Dict[str, SymbolStatistics]:
        """
        获取统计数据
        
        Returns:
            Dict[str, SymbolStatistics]: 代币统计数据字典
        """
        pass

