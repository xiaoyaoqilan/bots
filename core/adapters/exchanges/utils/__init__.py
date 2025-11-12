"""
交易所适配器工具模块

提供日志优化、格式化等工具函数
"""

from .setup_logging import (
    LoggingConfig,
    setup_optimized_logging,
    format_order_log,
    format_ws_log,
    format_sync_log,
    simplify_order_id,
)

from .log_formatter import (
    CompactFormatter,
    DetailedFormatter,
    ColoredFormatter,
)

__all__ = [
    # 日志配置
    'LoggingConfig',
    'setup_optimized_logging',

    # 格式化函数
    'format_order_log',
    'format_ws_log',
    'format_sync_log',
    'simplify_order_id',

    # 格式化器类
    'CompactFormatter',
    'DetailedFormatter',
    'ColoredFormatter',
]
