"""
智能剥头皮状态追踪器

管理智能剥头皮模式的状态机，包括：
1. 深度下跌追踪
2. 位置记录（最低/最高价格）
3. 有效性验证
4. 激活位置动态调整
"""

from typing import Optional
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum

from ....logging import get_logger
from ..models import GridType


class SmartScalpingState(Enum):
    """智能剥头皮状态"""
    IDLE = "idle"                           # 空闲状态（未触发）
    TRACKING = "tracking"                   # 追踪状态（记录最低/最高位置）
    WAITING_REBOUND = "waiting_rebound"     # 等待反弹状态
    ACTIVATED = "activated"                 # 已激活剥头皮


@dataclass
class DeepDropRecord:
    """深度下跌记录"""
    drop_number: int                    # 第几次深度下跌
    start_grid: int                     # 起始网格位置
    lowest_grid: int                    # 最低网格位置（做多）/ 最高网格位置（做空）
    drop_percent: float                 # 下跌百分比
    is_valid: bool                      # 是否有效


class SmartScalpingTracker:
    """
    智能剥头皮状态追踪器

    功能：
    1. 追踪深度下跌过程
    2. 记录最低/最高位置
    3. 验证下跌有效性
    4. 管理状态转换
    """

    def __init__(
        self,
        grid_type: GridType,
        grid_count: int,
        initial_trigger_grid: int,
        allowed_deep_drops: int,
        min_drop_threshold_percent: int
    ):
        """
        初始化智能剥头皮追踪器

        Args:
            grid_type: 网格类型
            grid_count: 网格总数
            initial_trigger_grid: 初始触发网格位置
            allowed_deep_drops: 允许的深度下跌次数
            min_drop_threshold_percent: 最小下跌百分比阈值
        """
        self.logger = get_logger(__name__)
        self.grid_type = grid_type
        self.grid_count = grid_count
        self.initial_trigger_grid = initial_trigger_grid
        self.allowed_deep_drops = allowed_deep_drops
        self.min_drop_threshold_percent = min_drop_threshold_percent

        # 状态
        self.state = SmartScalpingState.IDLE

        # 当前追踪的深度下跌次数（1-based）
        self.current_drop_number = 0

        # 深度下跌记录列表
        self.deep_drop_records: list[DeepDropRecord] = []

        # 当前追踪中的最低/最高网格位置
        self.tracking_extreme_grid: Optional[int] = None

        # 当前有效的阈值网格（每次有效下跌后更新）
        self.current_threshold_grid = initial_trigger_grid

        # 最终激活网格位置
        self.final_activation_grid: Optional[int] = None

        self.logger.info(
            f"🧠 智能剥头皮追踪器初始化: "
            f"初始触发网格={initial_trigger_grid}, "
            f"允许深度下跌次数={allowed_deep_drops}, "
            f"最小下跌阈值={min_drop_threshold_percent}%"
        )

    def update(self, current_grid: int) -> bool:
        """
        更新状态（每次价格变化时调用）

        Args:
            current_grid: 当前网格位置

        Returns:
            是否应该激活剥头皮模式
        """
        is_long = self.grid_type in [
            GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]

        # ============================================================
        # 状态机逻辑
        # ============================================================

        if self.state == SmartScalpingState.IDLE:
            # 空闲状态：检查是否跌破初始触发点
            if self._is_below_threshold(current_grid, self.initial_trigger_grid, is_long):
                self._enter_tracking(current_grid)

        elif self.state == SmartScalpingState.TRACKING:
            # 追踪状态：记录最低/最高位置
            if self._is_below_threshold(current_grid, self.current_threshold_grid, is_long):
                # 继续下跌，更新极值
                self._update_extreme_grid(current_grid, is_long)
            else:
                # 反弹，检查有效性并进入等待反弹状态
                self._exit_tracking_and_wait_rebound(current_grid, is_long)

        elif self.state == SmartScalpingState.WAITING_REBOUND:
            # 等待反弹状态：检查是否反弹回阈值以上
            if not self._is_below_threshold(current_grid, self.current_threshold_grid, is_long):
                # 反弹回阈值以上
                if self.current_drop_number < self.allowed_deep_drops:
                    # 还有剩余次数，重新进入IDLE等待下一次下跌
                    self._confirm_drop_and_reset()
                else:
                    # 达到允许次数，等待激活
                    self._prepare_for_activation()
            else:
                # 继续下跌，回到追踪状态
                self.state = SmartScalpingState.TRACKING
                self._update_extreme_grid(current_grid, is_long)
                self.logger.debug(
                    f"🔄 继续下跌，回到追踪状态: Grid {current_grid}"
                )

        elif self.state == SmartScalpingState.ACTIVATED:
            # 已准备激活：检查是否跌到激活位置
            if self.final_activation_grid is not None:
                if self._is_below_threshold(current_grid, self.final_activation_grid, is_long):
                    self.logger.warning(
                        f"🔴 智能剥头皮激活! "
                        f"当前Grid {current_grid} <= 激活Grid {self.final_activation_grid}"
                    )
                    return True  # 返回True表示应该激活剥头皮

        return False  # 不激活

    def _is_below_threshold(self, current_grid: int, threshold_grid: int, is_long: bool) -> bool:
        """
        判断当前网格是否在阈值网格之下（价格更低或更高）

        Args:
            current_grid: 当前网格
            threshold_grid: 阈值网格
            is_long: 是否做多网格

        Returns:
            做多：current_grid <= threshold_grid（网格索引小，价格低）
            做空：current_grid >= threshold_grid（网格索引大，价格高）
        """
        if is_long:
            # 做多：Grid 1=最低价，索引越小价格越低
            return current_grid <= threshold_grid
        else:
            # 做空：Grid 1=最高价，索引越大价格越高
            return current_grid >= threshold_grid

    def _enter_tracking(self, current_grid: int):
        """进入追踪状态"""
        self.current_drop_number += 1
        self.state = SmartScalpingState.TRACKING
        self.tracking_extreme_grid = current_grid

        self.logger.warning(
            f"📉 第{self.current_drop_number}次深度下跌追踪开始: "
            f"Grid {current_grid} (阈值Grid {self.current_threshold_grid})"
        )

    def _update_extreme_grid(self, current_grid: int, is_long: bool):
        """更新极值网格位置（最低或最高）"""
        if self.tracking_extreme_grid is None:
            self.tracking_extreme_grid = current_grid
            return

        if is_long:
            # 做多：记录最低位置（索引更小）
            if current_grid < self.tracking_extreme_grid:
                self.logger.info(
                    f"📊 更新最低位置: Grid {self.tracking_extreme_grid} → {current_grid}"
                )
                self.tracking_extreme_grid = current_grid
        else:
            # 做空：记录最高位置（索引更大）
            if current_grid > self.tracking_extreme_grid:
                self.logger.info(
                    f"📊 更新最高位置: Grid {self.tracking_extreme_grid} → {current_grid}"
                )
                self.tracking_extreme_grid = current_grid

    def _exit_tracking_and_wait_rebound(self, current_grid: int, is_long: bool):
        """退出追踪状态，进入等待反弹"""
        if self.tracking_extreme_grid is None:
            self.logger.warning("⚠️ 追踪极值为空，跳过")
            self.state = SmartScalpingState.IDLE
            return

        # 计算下跌幅度百分比
        drop_grids = abs(self.tracking_extreme_grid -
                         self.current_threshold_grid)
        drop_percent = (drop_grids / self.grid_count) * 100

        # 验证有效性
        is_valid = drop_percent >= self.min_drop_threshold_percent

        self.logger.info(
            f"🔍 第{self.current_drop_number}次下跌验证: "
            f"起始Grid {self.current_threshold_grid} → 极值Grid {self.tracking_extreme_grid}, "
            f"下跌{drop_grids}格 ({drop_percent:.1f}%), "
            f"{'✅有效' if is_valid else '❌无效'} (阈值{self.min_drop_threshold_percent}%)"
        )

        # 记录本次下跌
        record = DeepDropRecord(
            drop_number=self.current_drop_number,
            start_grid=self.current_threshold_grid,
            lowest_grid=self.tracking_extreme_grid,
            drop_percent=drop_percent,
            is_valid=is_valid
        )
        self.deep_drop_records.append(record)

        if is_valid:
            self.state = SmartScalpingState.WAITING_REBOUND
        else:
            # 无效，回到IDLE重新开始
            self.current_drop_number -= 1
            self.tracking_extreme_grid = None
            self.state = SmartScalpingState.IDLE
            self.logger.info(
                f"❌ 下跌幅度不足，本次下跌无效，回到空闲状态"
            )

    def _confirm_drop_and_reset(self):
        """确认本次深度下跌，准备下一次"""
        if self.tracking_extreme_grid is None:
            return

        # 更新阈值为本次极值
        old_threshold = self.current_threshold_grid
        self.current_threshold_grid = self.tracking_extreme_grid

        self.logger.warning(
            f"✅ 第{self.current_drop_number}次深度下跌确认! "
            f"阈值更新: Grid {old_threshold} → {self.current_threshold_grid}, "
            f"剩余次数: {self.allowed_deep_drops - self.current_drop_number}"
        )

        # 重置追踪状态
        self.tracking_extreme_grid = None
        self.state = SmartScalpingState.IDLE

    def _prepare_for_activation(self):
        """准备激活（达到允许次数）"""
        if self.tracking_extreme_grid is None:
            return

        # 最后一次下跌的极值就是激活位置
        self.final_activation_grid = self.tracking_extreme_grid
        self.state = SmartScalpingState.ACTIVATED

        self.logger.warning(
            f"🎯 智能剥头皮准备完成! "
            f"完成{self.current_drop_number}次深度下跌, "
            f"激活位置: Grid {self.final_activation_grid}"
        )

        # 打印所有深度下跌记录
        self.logger.info("📋 深度下跌记录:")
        for record in self.deep_drop_records:
            if record.is_valid:
                self.logger.info(
                    f"   第{record.drop_number}次: Grid {record.start_grid} → {record.lowest_grid} "
                    f"({record.drop_percent:.1f}%)"
                )

    def get_current_activation_grid(self) -> int:
        """
        获取当前激活网格位置

        Returns:
            如果智能模式已完成，返回最终激活位置
            否则返回当前阈值位置
        """
        if self.state == SmartScalpingState.ACTIVATED and self.final_activation_grid is not None:
            return self.final_activation_grid
        return self.current_threshold_grid

    def get_progress_info(self) -> dict:
        """
        获取进度信息（用于UI显示）

        Returns:
            包含状态、进度等信息的字典
        """
        return {
            'state': self.state.value,
            'drop_count': self.current_drop_number,
            'allowed_drops': self.allowed_deep_drops,
            'current_threshold': self.current_threshold_grid,
            'activation_grid': self.final_activation_grid,
            'tracking_extreme': self.tracking_extreme_grid
        }

    def reset(self):
        """重置追踪器"""
        self.state = SmartScalpingState.IDLE
        self.current_drop_number = 0
        self.deep_drop_records.clear()
        self.tracking_extreme_grid = None
        self.current_threshold_grid = self.initial_trigger_grid
        self.final_activation_grid = None

        self.logger.info("🔄 智能剥头皮追踪器已重置")

    def __repr__(self) -> str:
        return (
            f"SmartScalpingTracker("
            f"state={self.state.value}, "
            f"drops={self.current_drop_number}/{self.allowed_deep_drops}, "
            f"threshold={self.current_threshold_grid}, "
            f"activation={self.final_activation_grid})"
        )
