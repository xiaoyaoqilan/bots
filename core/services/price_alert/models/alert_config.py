"""价格监控报警配置模型"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from decimal import Decimal


@dataclass
class VolatilityAlertConfig:
    """波动报警配置"""
    enabled: bool = True
    time_window: int = 60  # 秒
    threshold_percent: float = 1.0  # 百分比


@dataclass
class PriceAlertConfig:
    """价格目标报警配置"""
    enabled: bool = True
    upper_limit: Decimal = Decimal("0")  # 0表示不设置
    lower_limit: Decimal = Decimal("0")  # 0表示不设置


@dataclass
class SymbolConfig:
    """单个代币配置"""
    symbol: str
    market_type: str = "spot"  # spot 或 perpetual
    enabled: bool = True
    volatility_alert: VolatilityAlertConfig = field(
        default_factory=VolatilityAlertConfig)
    price_alert: PriceAlertConfig = field(default_factory=PriceAlertConfig)


@dataclass
class AlertSoundConfig:
    """报警声音配置"""
    sound_enabled: bool = True
    sound_type: str = "beep"  # beep 或 system
    sound_duration: float = 0.5
    sound_repeat: int = 3
    cooldown_seconds: int = 30


@dataclass
class DisplayConfig:
    """显示配置"""
    refresh_interval: int = 1
    show_columns: List[str] = field(default_factory=lambda: [
        "symbol", "price", "change_24h", "change_window",
        "high_low", "alert_count", "last_update"
    ])
    colors: Dict[str, str] = field(default_factory=lambda: {
        "price_up": "green",
        "price_down": "red",
        "alert": "yellow",
        "normal": "white"
    })


@dataclass
class LoggingConfig:
    """日志配置"""
    enabled: bool = True
    log_to_file: bool = True
    log_to_console: bool = False
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = "price_alert.log"
    alert_history_file: str = "logs/alert_history.log"


@dataclass
class PriceAlertSystemConfig:
    """价格监控报警系统配置"""
    exchange: str = "binance"
    symbols: List[SymbolConfig] = field(default_factory=list)
    alert: AlertSoundConfig = field(default_factory=AlertSoundConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict) -> 'PriceAlertSystemConfig':
        """从字典创建配置"""
        config_data = data.get('price_alert', {})

        # 解析代币配置
        symbols = []
        for symbol_data in config_data.get('symbols', []):
            volatility_config = VolatilityAlertConfig(
                enabled=symbol_data.get('volatility_alert', {}).get('enabled', True),
                time_window=symbol_data.get('volatility_alert', {}).get('time_window', 60),
                threshold_percent=symbol_data.get('volatility_alert', {}).get('threshold_percent', 1.0)
            )

            price_config = PriceAlertConfig(
                enabled=symbol_data.get('price_alert', {}).get('enabled', True),
                upper_limit=Decimal(str(symbol_data.get('price_alert', {}).get('upper_limit', 0))),
                lower_limit=Decimal(str(symbol_data.get('price_alert', {}).get('lower_limit', 0)))
            )

            symbol_config = SymbolConfig(
                symbol=symbol_data['symbol'],
                market_type=symbol_data.get('market_type', 'spot'),
                enabled=symbol_data.get('enabled', True),
                volatility_alert=volatility_config,
                price_alert=price_config
            )
            symbols.append(symbol_config)

        # 解析报警配置
        alert_data = config_data.get('alert', {})
        alert_config = AlertSoundConfig(
            sound_enabled=alert_data.get('sound_enabled', True),
            sound_type=alert_data.get('sound_type', 'beep'),
            sound_duration=alert_data.get('sound_duration', 0.5),
            sound_repeat=alert_data.get('sound_repeat', 3),
            cooldown_seconds=alert_data.get('cooldown_seconds', 30)
        )

        # 解析显示配置
        display_data = config_data.get('display', {})
        display_config = DisplayConfig(
            refresh_interval=display_data.get('refresh_interval', 1),
            show_columns=display_data.get('show_columns', [
                "symbol", "price", "change_24h", "change_window",
                "high_low", "alert_count", "last_update"
            ]),
            colors=display_data.get('colors', {
                "price_up": "green",
                "price_down": "red",
                "alert": "yellow",
                "normal": "white"
            })
        )

        # 解析日志配置
        logging_data = config_data.get('logging', {})
        logging_config = LoggingConfig(
            enabled=logging_data.get('enabled', True),
            log_to_file=logging_data.get('log_to_file', True),
            log_to_console=logging_data.get('log_to_console', False),
            log_level=logging_data.get('log_level', 'INFO'),
            log_dir=logging_data.get('log_dir', 'logs'),
            log_file=logging_data.get('log_file', 'price_alert.log'),
            alert_history_file=logging_data.get('alert_history_file', 'logs/alert_history.log')
        )

        return cls(
            exchange=config_data.get('exchange', 'binance'),
            symbols=symbols,
            alert=alert_config,
            display=display_config,
            logging=logging_config
        )

