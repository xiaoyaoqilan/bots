"""
APR报警管理器 - APR Alert Manager

当APR超过阈值时播放声音报警，并限制报警次数
"""
import logging
import platform
import subprocess
from typing import Dict, Set
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class APRAlertManager:
    """
    APR报警管理器

    功能：
    - 检测APR超过阈值时播放声音报警
    - 限制报警次数（避免无限报警）
    - 记录已报警的代币和时间
    """

    def __init__(
        self,
        apr_threshold: float = 100.0,
        max_alerts_per_symbol: int = 3,
        alert_cooldown_seconds: int = 300  # 5分钟内不重复报警
    ):
        """
        初始化报警管理器

        Args:
            apr_threshold: APR阈值（%），超过此值触发报警
            max_alerts_per_symbol: 每个代币最大报警次数
            alert_cooldown_seconds: 报警冷却时间（秒），避免频繁报警
        """
        self.apr_threshold = apr_threshold
        self.max_alerts_per_symbol = max_alerts_per_symbol
        self.alert_cooldown_seconds = alert_cooldown_seconds

        # 记录每个代币的报警次数
        self.alert_counts: Dict[str, int] = {}

        # 记录每个代币的最后报警时间
        self.last_alert_times: Dict[str, datetime] = {}

        # 记录已经触发过报警的代币（用于避免重复报警）
        self.alerted_symbols: Set[str] = set()

        logger.info(
            f"🔔 APR报警管理器初始化: "
            f"阈值={apr_threshold}%, "
            f"最大报警次数={max_alerts_per_symbol}, "
            f"冷却时间={alert_cooldown_seconds}秒"
        )

    def check_and_alert(self, symbol: str, apr: Decimal) -> bool:
        """
        检查APR是否超过阈值，如果超过则触发报警

        Args:
            symbol: 代币符号
            apr: 当前APR值（%）

        Returns:
            是否触发了报警
        """
        apr_float = float(apr)

        # 检查是否超过阈值
        if apr_float < self.apr_threshold:
            # APR低于阈值，重置报警状态（允许下次超过阈值时再次报警）
            if symbol in self.alerted_symbols:
                self.alerted_symbols.remove(symbol)
            return False

        # APR超过阈值，检查是否需要报警

        # 检查是否已经报警过（避免重复报警）
        if symbol in self.alerted_symbols:
            # 检查冷却时间
            if symbol in self.last_alert_times:
                time_since_last = (
                    datetime.now() - self.last_alert_times[symbol]).total_seconds()
                if time_since_last < self.alert_cooldown_seconds:
                    # 还在冷却期内，不报警
                    return False

        # 检查是否超过最大报警次数
        alert_count = self.alert_counts.get(symbol, 0)
        if alert_count >= self.max_alerts_per_symbol:
            # 已达到最大报警次数，不再报警
            return False

        # 触发报警
        self._trigger_alert(symbol, apr_float)

        # 更新记录
        self.alert_counts[symbol] = alert_count + 1
        self.last_alert_times[symbol] = datetime.now()
        self.alerted_symbols.add(symbol)

        return True

    def _trigger_alert(self, symbol: str, apr: float):
        """
        触发声音报警

        Args:
            symbol: 代币符号
            apr: APR值
        """
        try:
            alert_count = self.alert_counts.get(symbol, 0) + 1
            logger.warning(
                f"🔔 APR报警 #{alert_count}: {symbol} APR={apr:.2f}% "
                f"(阈值={self.apr_threshold}%)"
            )

            # 播放系统声音
            self._play_sound()

        except Exception as e:
            logger.error(f"触发报警失败 {symbol}: {e}")

    def _play_sound(self):
        """
        播放系统声音 - 连续急促尖锐的报警声

        支持不同操作系统：
        - macOS: 连续播放尖锐的系统声音
        - Linux: 使用 beep 或 aplay
        - Windows: 使用 winsound
        """
        try:
            system = platform.system()

            if system == "Darwin":  # macOS
                # 🚨 使用连续急促的尖锐报警声
                # 优先使用尖锐、短促的系统声音
                alert_sounds = [
                    "/System/Library/Sounds/Basso.aiff",     # 低沉尖锐（推荐）
                    "/System/Library/Sounds/Sosumi.aiff",    # 清脆尖锐
                    "/System/Library/Sounds/Ping.aiff",      # 短促尖锐
                    "/System/Library/Sounds/Glass.aiff",     # 玻璃碎裂声
                ]
                
                # 🔥 连续快速播放5次，制造急促尖锐感
                sound_played = False
                for sound_file in alert_sounds:
                    try:
                        # 快速连续播放5次
                        success_count = 0
                        for i in range(5):
                            result = subprocess.run(
                                ["afplay", sound_file],
                                check=False,
                                timeout=0.5,  # 0.5秒超时，确保快速播放
                                capture_output=True
                            )
                            if result.returncode == 0:
                                success_count += 1
                            # 不等待，立即播放下一次（急促感）
                        
                        # 如果至少成功播放3次，认为成功
                        if success_count >= 3:
                            sound_played = True
                            break
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
                
                # 如果所有声音文件都不存在，使用连续系统beep
                if not sound_played:
                    # 连续8次短促的beep（更急促）
                    subprocess.run(
                        ["osascript", "-e", "beep 8"],
                        check=False,
                        timeout=2
                    )
            elif system == "Linux":
                # 尝试使用 beep 命令
                try:
                    subprocess.run(["beep"], check=False, timeout=1)
                except FileNotFoundError:
                    # beep 不存在，尝试使用 aplay 播放系统提示音
                    try:
                        subprocess.run(
                            ["aplay", "/usr/share/sounds/alsa/Front_Left.wav"],
                            check=False,
                            timeout=1
                        )
                    except FileNotFoundError:
                        # 如果都不存在，打印到终端（至少有个提示）
                        print("\a", end="", flush=True)  # 终端响铃
            elif system == "Windows":
                # Windows 使用 winsound
                try:
                    import winsound
                    winsound.Beep(1000, 500)  # 1000Hz, 500ms
                except ImportError:
                    print("\a", end="", flush=True)  # 终端响铃
            else:
                # 其他系统，使用终端响铃
                print("\a", end="", flush=True)

        except Exception as e:
            logger.debug(f"播放声音失败: {e}")
            # 如果所有方法都失败，至少打印终端响铃
            try:
                print("\a", end="", flush=True)
            except:
                pass

    def reset_symbol(self, symbol: str):
        """
        重置某个代币的报警记录（允许重新报警）

        Args:
            symbol: 代币符号
        """
        if symbol in self.alert_counts:
            del self.alert_counts[symbol]
        if symbol in self.last_alert_times:
            del self.last_alert_times[symbol]
        if symbol in self.alerted_symbols:
            self.alerted_symbols.remove(symbol)

    def reset_all(self):
        """重置所有报警记录"""
        self.alert_counts.clear()
        self.last_alert_times.clear()
        self.alerted_symbols.clear()
        logger.info("🔔 已重置所有报警记录")

    def get_status(self) -> Dict[str, any]:
        """
        获取报警状态

        Returns:
            包含报警统计信息的字典
        """
        return {
            'apr_threshold': self.apr_threshold,
            'max_alerts_per_symbol': self.max_alerts_per_symbol,
            'alert_cooldown_seconds': self.alert_cooldown_seconds,
            'total_symbols_alerted': len(self.alerted_symbols),
            'alert_counts': dict(self.alert_counts),
        }
