"""
日志系统配置工具

提供统一的日志配置接口，支持多种格式化器
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

from .log_formatter import (
    CompactFormatter,
    DetailedFormatter,
    ColoredFormatter,
    format_order_log,
    format_ws_log,
    format_sync_log,
    simplify_order_id
)


class LoggingConfig:
    """日志配置管理器"""

    # 默认日志级别
    DEFAULT_LEVEL = logging.INFO

    # 日志文件配置
    LOG_DIR = Path("logs")
    MAX_BYTES = 10 * 1024 * 1024  # 10MB
    BACKUP_COUNT = 5

    # 格式化器类型
    FORMATTER_TYPES = {
        'compact': CompactFormatter,      # 简洁格式（终端）
        'detailed': DetailedFormatter,    # 详细格式（文件）
        'colored': ColoredFormatter,      # 彩色格式（终端）
    }

    @classmethod
    def setup_logger(cls,
                     name: str,
                     log_file: Optional[str] = None,
                     console_formatter: str = 'compact',
                     file_formatter: str = 'detailed',
                     level: int = None) -> logging.Logger:
        """
        设置logger

        Args:
            name: Logger名称
            log_file: 日志文件名（相对于logs目录）
            console_formatter: 控制台格式化器类型
            file_formatter: 文件格式化器类型
            level: 日志级别

        Returns:
            配置好的Logger对象
        """
        logger = logging.getLogger(name)
        logger.setLevel(level or cls.DEFAULT_LEVEL)
        logger.propagate = False  # 不传播到父logger

        # 清除现有handlers
        logger.handlers.clear()

        # 添加控制台handler
        if console_formatter:
            console_handler = cls._create_console_handler(console_formatter)
            logger.addHandler(console_handler)

        # 添加文件handler
        if log_file:
            file_handler = cls._create_file_handler(log_file, file_formatter)
            logger.addHandler(file_handler)

        return logger

    @classmethod
    def _create_console_handler(cls, formatter_type: str) -> logging.Handler:
        """创建控制台handler"""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(cls.DEFAULT_LEVEL)

        # 获取格式化器
        formatter_class = cls.FORMATTER_TYPES.get(
            formatter_type, CompactFormatter)
        handler.setFormatter(formatter_class())

        return handler

    @classmethod
    def _create_file_handler(cls, log_file: str, formatter_type: str) -> logging.Handler:
        """创建文件handler"""
        # 确保日志目录存在
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 创建RotatingFileHandler
        file_path = cls.LOG_DIR / log_file
        handler = RotatingFileHandler(
            file_path,
            maxBytes=cls.MAX_BYTES,
            backupCount=cls.BACKUP_COUNT,
            encoding='utf-8'
        )
        handler.setLevel(cls.DEFAULT_LEVEL)

        # 获取格式化器
        formatter_class = cls.FORMATTER_TYPES.get(
            formatter_type, DetailedFormatter)
        handler.setFormatter(formatter_class())

        return handler

    @classmethod
    def setup_exchange_adapter_logging(cls,
                                       use_colored: bool = True,
                                       console_level: int = logging.INFO,
                                       file_level: int = logging.DEBUG):
        """
        为交易所适配器设置优化的日志配置

        Args:
            use_colored: 是否使用彩色格式（终端支持ANSI颜色时）
            console_level: 控制台日志级别
            file_level: 文件日志级别
        """
        # 确定格式化器类型
        console_formatter = 'colored' if use_colored and cls._supports_color() else 'compact'

        # WebSocket模块
        ws_logger = cls.setup_logger(
            'core.adapters.exchanges.adapters.lighter_websocket',
            log_file='ExchangeAdapter.log',
            console_formatter=console_formatter,
            file_formatter='detailed',
            level=console_level
        )

        # REST API模块
        rest_logger = cls.setup_logger(
            'core.adapters.exchanges.adapters.lighter_rest',
            log_file='ExchangeAdapter.log',
            console_formatter=console_formatter,
            file_formatter='detailed',
            level=console_level
        )

        # 价格日志（只输出到文件，不输出到控制台）
        price_logger = cls.setup_logger(
            'core.adapters.exchanges.adapters.lighter_websocket.price',
            log_file='ExchangeAdapter.log',
            console_formatter=None,  # 不输出到控制台
            file_formatter='detailed',
            level=file_level
        )

        return ws_logger, rest_logger, price_logger

    @classmethod
    def setup_grid_engine_logging(cls,
                                  use_colored: bool = True,
                                  console_level: int = logging.INFO):
        """
        为网格引擎设置优化的日志配置

        Args:
            use_colored: 是否使用彩色格式
            console_level: 控制台日志级别
        """
        console_formatter = 'colored' if use_colored and cls._supports_color() else 'compact'

        # 网格引擎
        engine_logger = cls.setup_logger(
            'core.services.grid.implementations.grid_engine_impl',
            log_file='core.services.grid.implementations.grid_engine_impl.log',
            console_formatter=console_formatter,
            file_formatter='detailed',
            level=console_level
        )

        # 网格协调器
        coord_logger = cls.setup_logger(
            'core.services.grid.coordinator.grid_coordinator',
            log_file='core.services.grid.coordinator.grid_coordinator.log',
            console_formatter=console_formatter,
            file_formatter='detailed',
            level=console_level
        )

        # 健康检查
        health_logger = cls.setup_logger(
            'core.services.grid.implementations.order_health_checker',
            log_file='core.services.grid.implementations.order_health_checker.log',
            console_formatter=console_formatter,
            file_formatter='detailed',
            level=console_level
        )

        return engine_logger, coord_logger, health_logger

    @staticmethod
    def _supports_color() -> bool:
        """检测终端是否支持ANSI颜色"""
        # 检测是否在支持颜色的终端中
        if not hasattr(sys.stdout, 'isatty'):
            return False

        if not sys.stdout.isatty():
            return False

        # Windows终端需要额外检测
        import platform
        if platform.system() == 'Windows':
            # Windows 10及以上支持ANSI颜色
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except:
                return False

        return True


# 便捷函数
def setup_optimized_logging(use_colored: bool = True):
    """
    一键设置所有优化的日志配置

    Args:
        use_colored: 是否使用彩色输出
    """
    # 设置交易所适配器日志
    LoggingConfig.setup_exchange_adapter_logging(use_colored=use_colored)

    # 设置网格引擎日志
    LoggingConfig.setup_grid_engine_logging(use_colored=use_colored)

    logging.info("✅ 优化的日志系统已配置")


# 导出工具函数
__all__ = [
    'LoggingConfig',
    'setup_optimized_logging',
    'format_order_log',
    'format_ws_log',
    'format_sync_log',
    'simplify_order_id',
]
