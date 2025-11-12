"""
网格交易系统协调器

核心协调逻辑：
1. 初始化网格系统
2. 处理订单成交事件
3. 自动挂反向订单
4. 异常处理和暂停恢复

🔥 重要优化说明（2025-11-02）：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lighter 订单ID统一方案
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【新方案】
下单时在 lighter_rest.py 中立即查询 order_index，
让 OrderData.id 和 OrderData.client_id 都使用 order_index（统一标识）。

【优势】
1. 消除双键映射问题（不再需要 client_order_id ⇄ order_index 的映射）
2. 简化代码逻辑（删除了 ~200 行同步代码）
3. 降低 bug 风险（无内存泄漏、无匹配失败）
4. 架构更清晰（订单ID在下单时就确定，不需要事后同步）

【影响范围】
仅 Lighter 交易所内部实现，不影响其他交易所。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
重置期间立即成交订单的延迟处理机制（2025-11-02）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【问题】
网格重置时（止盈/本金保护/价格脱离），批量下单中的立即成交订单被 `_resetting` 锁拦截，
导致反向订单未挂出，网格不完整。

【根本原因】
- 立即成交检测时间：批量下单完成 + 3秒（REST API同步延迟）
- 重置锁释放时间：整个重置流程完成（批量下单 + 本金初始化 + 清理，约16秒）
- **锁释放总是晚于立即成交检测** → 反向订单被跳过

【解决方案】
1. 重置期间缓存立即成交订单到 `_pending_immediate_fills`
2. 重置完成、锁释放后，调用 `process_pending_immediate_fills()` 处理缓存订单
3. 此时本金已重新初始化，可以安全挂反向订单

【修改文件】
- grid_coordinator.py: 添加缓存列表和处理方法
- scalping_operations.py: 在 finally 块中调用处理
- grid_reset_manager.py: 在所有重置方法的 finally 块中调用处理

【影响范围】
所有交易所（Backpack、Hyperliquid、Lighter）均受益。
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from ....logging import get_logger
from ..interfaces import IGridStrategy, IGridEngine, IPositionTracker
from ..models import (
    GridConfig, GridState, GridOrder, GridOrderSide,
    GridOrderStatus, GridStatus, GridStatistics
)
from ..scalping import ScalpingManager
from ..capital_protection import CapitalProtectionManager
from ..take_profit import TakeProfitManager
from ..price_lock import PriceLockManager

# 🔥 导入新模块
from .grid_reset_manager import GridResetManager
from .position_monitor import PositionMonitor
from .balance_monitor import BalanceMonitor
from .scalping_operations import ScalpingOperations
from .stop_loss_monitor import StopLossMonitor


class GridCoordinator:
    """
    网格交易系统协调器

    职责：
    1. 整合策略、引擎、跟踪器
    2. 订单成交后的反向挂单逻辑
    3. 批量成交处理
    4. 系统状态管理
    5. 异常处理
    """

    def __init__(
        self,
        config: GridConfig,
        strategy: IGridStrategy,
        engine: IGridEngine,
        tracker: IPositionTracker,
        grid_state: GridState,
        reserve_manager=None  # 🔥 可选的预留管理器（仅现货）
    ):
        """
        初始化协调器

        Args:
            config: 网格配置
            strategy: 网格策略
            engine: 执行引擎
            tracker: 持仓跟踪器
            grid_state: 网格状态（共享实例）
            reserve_manager: 现货预留管理器（可选）
        """
        self.logger = get_logger(__name__)
        self.config = config
        self.strategy = strategy
        self.engine = engine
        self.tracker = tracker
        self.reserve_manager = reserve_manager  # 🔥 保存预留管理器引用

        # 🔥 设置 engine 的 coordinator 引用（用于 health_checker 访问剥头皮管理器等）
        if hasattr(engine, 'coordinator'):
            engine.coordinator = self

        # 网格状态（使用传入的共享实例）
        self.state = grid_state

        # 🔥 日志：预留管理状态
        if self.reserve_manager:
            self.logger.info("✅ 现货预留管理已启用（协调器已集成）")

            # 🔥 将预留管理器传递给健康检查器（稍后在 engine 初始化完成后设置）
            # 注意：_health_checker 在 engine.initialize() 中才创建，这里只是记录

        # 运行控制
        self._running = False
        self._paused = False
        self._paused_reason = None  # 🆕 暂停原因：'network'（网络故障）或 'error'（代码错误）
        self._resetting = False  # 🔥 重置进行中标志（本金保护、剥头皮重置等）
        self._pending_immediate_fills: List[GridOrder] = []  # 🔥 重置期间缓存的立即成交订单

        # 🆕 系统状态管理（REST失败保护）
        self.is_emergency_stopped = False  # 持仓异常时紧急停止

        # 异常计数
        self._error_count = 0
        self._max_errors = 5  # 最大错误次数，超过则暂停

        # 🆕 触发次数统计（仅标记次数，无实质性功能）
        self._scalping_trigger_count = 0  # 剥头皮模式触发次数
        self._price_escape_trigger_count = 0  # 价格朝有利方向脱离触发次数
        self._take_profit_trigger_count = 0  # 止盈模式触发次数
        self._capital_protection_trigger_count = 0  # 本金保护模式触发次数

        # 🔥 价格移动网格专用
        self._price_escape_start_time: Optional[float] = None  # 价格脱离开始时间
        self._last_escape_check_time: float = 0  # 上次检查时间
        self._escape_check_interval: int = 10  # 检查间隔（秒）
        self._is_resetting: bool = False  # 是否正在重置网格

        # 🔥 循环APR统计（重置时重新开始）
        self._cycle_start_time: Optional[datetime] = None  # 循环统计开始时间（重置时重新开始）
        # 上次APR更新时间（用于整点更新）
        self._last_apr_update_time: Optional[datetime] = None
        # 🆕 保存上次计算的APR数据（用于不更新时复用）
        self._last_apr_estimate: Decimal = Decimal('0')
        self._last_apr_formula_data: Dict = {}
        self._last_cycle_profit_pct: Decimal = Decimal('0')

        # 🆕 实时APR统计（基于过去10分钟）
        self._last_realtime_apr_estimate: Decimal = Decimal('0')
        self._last_realtime_apr_formula_data: Dict = {}
        # 🆕 循环时间戳记录（用于统计过去10分钟的循环次数）
        self._cycle_timestamps: List[datetime] = []  # 记录每次完成循环的时间戳

        # 🔥 剥头皮管理器
        self.scalping_manager: Optional[ScalpingManager] = None
        self._scalping_position_monitor_task: Optional[asyncio.Task] = None
        self._scalping_position_check_interval: int = 1  # 剥头皮模式持仓检查间隔（秒，REST轮询）
        self._last_ws_position_size = Decimal('0')  # 用于WebSocket事件驱动
        self._last_ws_position_price = Decimal('0')
        # 🔥 持仓监控状态（类似订单统计的混合模式）
        self._position_ws_enabled: bool = False  # WebSocket持仓监控是否启用
        self._last_position_ws_time: float = 0  # 最后一次收到WebSocket持仓更新的时间
        self._last_order_filled_time: float = 0  # 最后一次订单成交的时间（用于判断WS是否失效）
        self._position_ws_response_timeout: int = 5  # 订单成交后WebSocket响应超时（秒）
        self._position_ws_check_interval: int = 5  # 尝试恢复WebSocket的间隔（秒）
        self._last_position_ws_check_time: float = 0  # 上次检查WebSocket的时间
        # 🔥 定期REST校验（心跳检测）
        self._position_rest_verify_interval: int = 60  # 每分钟用REST校验WebSocket持仓（秒）
        self._last_position_rest_verify_time: float = 0  # 上次REST校验的时间
        if config.is_scalping_enabled():
            self.scalping_manager = ScalpingManager(config)
            self.logger.info("✅ 剥头皮管理器已启用")

        # 🛡️ 本金保护管理器
        self.capital_protection_manager: Optional[CapitalProtectionManager] = None
        if config.is_capital_protection_enabled():
            self.capital_protection_manager = CapitalProtectionManager(config)
            self.logger.info("✅ 本金保护管理器已启用")

        # 💰 止盈管理器
        self.take_profit_manager: Optional[TakeProfitManager] = None
        if config.take_profit_enabled:
            self.take_profit_manager = TakeProfitManager(config)
            self.logger.info("✅ 止盈管理器已启用")

        # 🔒 价格锁定管理器
        self.price_lock_manager: Optional[PriceLockManager] = None
        if config.price_lock_enabled:
            self.price_lock_manager = PriceLockManager(config)
            self.logger.info("✅ 价格锁定管理器已启用")

        # 💰 账户余额（由BalanceMonitor管理）
        self._spot_balance: Decimal = Decimal('0')  # 现货余额（未用作保证金）
        self._collateral_balance: Decimal = Decimal('0')  # 抵押品余额（用作保证金）
        self._order_locked_balance: Decimal = Decimal('0')  # 订单冻结余额

        # 🔥 新增：模块化组件初始化
        self.reset_manager = GridResetManager(
            self, config, grid_state, engine, tracker, strategy
        )
        self.reset_grid_manager = self.reset_manager  # 🔥 添加别名，供止损监控器使用
        self.position_monitor = PositionMonitor(
            engine, tracker, config, self
        )
        # 🔥 优化：余额监控间隔从10秒改为60秒，降低REST API调用频率
        # WebSocket正常时使用缓存，REST仅作为备用
        self.balance_monitor = BalanceMonitor(
            engine, config, self, update_interval=60
        )

        # 🛑 止损保护监控器（优先级最高）
        self.stop_loss_monitor = StopLossMonitor(
            engine, config, self
        )

        # 剥头皮操作模块（可选）
        self.scalping_ops: Optional[ScalpingOperations] = None
        if config.is_scalping_enabled() and self.scalping_manager:
            self.scalping_ops = ScalpingOperations(
                self, self.scalping_manager, engine, grid_state,
                tracker, strategy, config
            )

        self.logger.info(f"✅ 网格协调器初始化完成（模块化版本）: {config}")

    async def initialize(self):
        """初始化网格系统"""
        try:
            self.logger.info("开始初始化网格系统...")

            # 1. 先初始化执行引擎（设置 engine.config）
            await self.engine.initialize(self.config)
            self.logger.info("执行引擎初始化完成")

            # 🔥 价格移动网格：获取当前价格并设置价格区间
            if self.config.is_follow_mode():
                current_price = await self.engine.get_current_price()
                self.config.update_price_range_for_follow_mode(current_price)
                self.logger.info(
                    f"价格移动网格：根据当前价格 ${current_price:,.2f} 设置价格区间 "
                    f"[${self.config.lower_price:,.2f}, ${self.config.upper_price:,.2f}]"
                )

            # 2. 初始化网格状态
            self.state.initialize_grid_levels(
                self.config.grid_count,
                self.config.get_grid_price
            )
            self.logger.info(f"网格状态初始化完成，共{self.config.grid_count}个网格层级")

            # 3. 初始化策略，生成所有初始订单
            initial_orders = self.strategy.initialize(self.config)

            # 🔥 价格移动网格：价格区间在初始化后才设置
            if self.config.is_follow_mode():
                self.logger.info(
                    f"策略初始化完成，生成{len(initial_orders)}个初始订单，"
                    f"覆盖价格区间 [${self.config.lower_price:,.2f}, ${self.config.upper_price:,.2f}]"
                )
            else:
                self.logger.info(
                    f"策略初始化完成，生成{len(initial_orders)}个初始订单，"
                    f"覆盖价格区间 ${self.config.lower_price:,.2f} - ${self.config.upper_price:,.2f}"
                )

            # 🔥 新方案：不再构建预期网格价格集合，直接通过 client_id 映射原始订单
            # 订单下单时会存入 _pending_orders_by_client_id 缓存
            # WebSocket 推送时通过 client_id 找到原始订单，使用原始价格挂反手单

            # 4. 订阅订单更新
            self.engine.subscribe_order_updates(self._on_order_filled)
            self.logger.info("订单更新订阅完成")

            # 🔥 提前设置_running标志，确保监控任务能正常运行
            self._running = True

            # 🔥 记录循环统计开始时间（每次初始化/重置时重新开始）
            self._cycle_start_time = datetime.now()
            self._cycle_timestamps.clear()  # 🆕 清空循环时间戳
            self.logger.info(
                f"📊 循环统计开始时间: {self._cycle_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 🔄 4.5. 启动持仓监控（使用新模块 PositionMonitor）
            await self.position_monitor.start_monitoring()

            # 5. 批量下所有初始订单（关键修改）
            self.logger.info(f"开始批量挂单，共{len(initial_orders)}个订单...")
            placed_orders = await self.engine.place_batch_orders(initial_orders)

            # 6. 批量添加到状态追踪（只添加未成交的订单）
            self.logger.info(f"开始添加{len(placed_orders)}个订单到状态追踪...")
            added_count = 0
            skipped_count = 0
            for order in placed_orders:
                # 🔥 检查订单是否已经在状态中（可能已经通过WebSocket成交回调处理）
                if order.order_id in self.state.active_orders:
                    skipped_count += 1
                    self.logger.debug(
                        f"⏭️ 跳过已存在订单: {order.order_id} (Grid {order.grid_id}, {order.side.value})"
                    )
                    continue

                # 🔥 检查订单是否已经成交（状态为FILLED）
                if order.status == GridOrderStatus.FILLED:
                    skipped_count += 1
                    self.logger.debug(
                        f"⏭️ 跳过已成交订单: {order.order_id} (Grid {order.grid_id}, {order.side.value})"
                    )
                    continue

                self.state.add_order(order)
                added_count += 1
                self.logger.debug(
                    f"✅ 已添加订单到状态: {order.order_id} (Grid {order.grid_id}, {order.side.value})")

            self.logger.info(
                f"✅ 成功挂出{len(placed_orders)}/{len(initial_orders)}个订单，"
                f"覆盖整个价格区间"
            )
            self.logger.info(
                f"📊 订单添加统计: 新增={added_count}, 跳过={skipped_count} "
                f"(已存在或已成交)"
            )
            self.logger.info(
                f"📊 状态统计: "
                f"买单={self.state.pending_buy_orders}, "
                f"卖单={self.state.pending_sell_orders}, "
                f"活跃订单={len(self.state.active_orders)}"
            )

            # 7. 启动系统
            self.state.start()
            # self._running = True  # 已在启动监控任务前设置

            # 🔥 记录网格启动时的价格
            initial_price = await self.engine.get_current_price()
            self.state.initial_price = initial_price
            self.logger.info(f"📊 网格启动价格: ${initial_price:,.2f}")

            self.logger.info("✅ 网格系统初始化完成，所有订单已就位，等待成交")

        except Exception as e:
            self.logger.error(f"❌ 网格系统初始化失败: {e}")
            self.state.set_error()
            raise

    async def _on_order_filled(self, filled_order: GridOrder):
        """
        订单成交回调 - 核心逻辑

        当订单成交时：
        1. 记录成交信息
        2. 检查剥头皮模式
        3. 计算反向订单参数
        4. 立即挂反向订单

        Args:
            filled_order: 已成交订单
        """
        try:
            # 🔥 关键检查：防止在重置期间处理订单
            if self._paused:
                self.logger.warning("系统已暂停，跳过订单处理")
                return

            if self._resetting:
                # 🔥 重置中：缓存订单，稍后处理（避免反向订单丢失）
                self.logger.info(
                    f"⏳ 重置中，缓存立即成交订单: {filled_order.side.value} "
                    f"{filled_order.filled_amount}@{filled_order.filled_price} "
                    f"(Grid {filled_order.grid_id})"
                )
                self._pending_immediate_fills.append(filled_order)
                return

            self.logger.info(
                f"📢 订单成交: {filled_order.side.value} "
                f"{filled_order.filled_amount}@{filled_order.filled_price} "
                f"(Grid {filled_order.grid_id}) "
                f"[OrderID: {filled_order.order_id[:10]}..., ClientID: {filled_order.client_id or 'N/A'}]"
            )

            # 🔥 触发持仓查询（订单成交后立即查询持仓，带5秒去重）
            asyncio.create_task(
                self.position_monitor.trigger_event_query("订单成交")
            )

            # 🔥 新方案：不再验证价格，直接使用原始价格挂反手单
            # filled_order 已经包含了原始提交的价格（来自 client_id 缓存）
            # 1. 更新状态
            self.state.mark_order_filled(
                filled_order.order_id,
                filled_order.filled_price,
                filled_order.filled_amount or filled_order.amount
            )

            # 🔥 2. 记录交易历史（不影响持仓，只用于统计和显示）
            # 持仓数据完全来自 position_monitor 的REST查询
            # 此方法只记录交易历史和统计，不更新持仓
            prev_cycles = self.tracker.completed_cycles  # 记录当前循环次数
            self.tracker.record_filled_order(filled_order)

            # 🆕 2.1. 记录循环时间戳（用于实时APR计算）
            if self.tracker.completed_cycles > prev_cycles:
                # 循环次数增加，记录时间戳
                self._cycle_timestamps.append(datetime.now())
                # 只保留过去10分钟的时间戳（性能优化）
                cutoff_time = datetime.now() - timedelta(minutes=10)
                self._cycle_timestamps = [
                    ts for ts in self._cycle_timestamps if ts > cutoff_time
                ]

            # 🔥 2.5. 记录现货买入手续费（仅现货且启用预留）
            if self.reserve_manager and filled_order.side.value == 'buy':
                fee = self.reserve_manager.record_buy_fee(
                    filled_order.filled_amount or filled_order.amount
                )
                status = self.reserve_manager.get_status()
                self.logger.info(
                    f"📊 现货买入手续费: {fee} {self.reserve_manager.base_currency}, "
                    f"预留健康度: {status['health_percent']:.1f}%"
                )

            # 🔥 3. 检查剥头皮模式（使用新模块）
            if self.scalping_manager and self.scalping_ops:
                # 检查是否是止盈订单成交
                if self._is_take_profit_order_filled(filled_order):
                    await self.scalping_ops.handle_take_profit_filled()
                    return  # 止盈成交后不再挂反向订单

                # 🔥 只有在剥头皮模式激活时才执行以下逻辑（避免不必要的延迟）
                if self.scalping_manager.is_active():
                    # 🆕 更新最后一次方向性订单ID（做多追踪买单，做空追踪卖单）
                    self.scalping_ops.update_last_directional_order(
                        order_id=filled_order.order_id,
                        order_side=filled_order.side.value
                    )

                    # 🔥 优化：将余额更新和止盈订单更新改为后台任务，不阻塞反手单提交
                    # 原因：反手单提交速度更重要，余额更新和止盈订单更新可以稍后执行
                    async def _update_scalping_after_reverse_order():
                        """后台更新剥头皮相关数据（余额、持仓、止盈订单）"""
                        try:
                            # 🔥 剥头皮模式：等待持仓同步完成后再更新止盈订单
                            # 原因：REST API持仓同步有延迟，订单成交时tracker可能还没更新
                            # 解决方案：等待position_monitor的REST查询完成
                            await asyncio.sleep(1.0)  # 等待1秒让REST持仓同步完成

                            # 🔥 强制更新余额（确保当前权益计算准确）
                            # 原因：余额监控器默认10秒更新一次，订单成交后BTC/USDC数量变化需要立即反映
                            # 这样止盈价格计算才能使用最新的权益数据
                            self.logger.debug("💰 订单成交后强制更新余额...")
                            await self.balance_monitor.update_balance()

                            # 更新持仓信息到剥头皮管理器
                            current_position = self.tracker.get_current_position()
                            average_cost = self.tracker.get_average_cost()
                            initial_capital = self.scalping_manager.get_initial_capital()
                            self.scalping_manager.update_position(
                                current_position, average_cost, initial_capital,
                                self.balance_monitor.collateral_balance
                            )

                            # 检查是否需要更新止盈订单
                            await self.scalping_ops.update_take_profit_order_if_needed()
                        except Exception as e:
                            self.logger.error(f"❌ 后台更新剥头皮数据失败: {e}")

                    # 创建后台任务，不阻塞当前流程
                    asyncio.create_task(_update_scalping_after_reverse_order())

            # 🛡️ 3.5. 快速检查本金保护模式（仅检查是否已激活，阻止下单）
            # 🔥 优化：只做快速检查，阻止下单；详细检查移到后台
            if self.capital_protection_manager and self.capital_protection_manager.is_active():
                # 本金保护已激活，检查是否回本（快速检查）
                if self.capital_protection_manager.check_capital_recovery(
                    self.balance_monitor.collateral_balance
                ):
                    # 需要重置，阻止下单
                    self.logger.warning("🛡️ 本金保护：抵押品已回本，准备重置网格，跳过反手单")
                    # 触发重置（后台执行，不阻塞）
                    asyncio.create_task(
                        self.reset_manager.execute_capital_protection_reset()
                    )
                    return

            # 4. 计算反向订单参数
            # 🔥 剥头皮模式下可能不挂反向订单
            if self.scalping_manager and self.scalping_manager.is_active():
                # 剥头皮模式：只挂建仓单，不挂平仓单
                if not self._should_place_reverse_order_in_scalping(filled_order):
                    self.logger.info(f"🔴 剥头皮模式: 不挂反向订单")
                    return

            new_side, new_price, new_grid_id = self.strategy.calculate_reverse_order(
                filled_order,
                self.config.grid_interval,
                self.config.reverse_order_grid_distance
            )

            # 5. 创建反向订单
            reverse_order = GridOrder(
                order_id="",  # 等待执行引擎填充
                grid_id=new_grid_id,
                side=new_side,
                price=new_price,
                amount=filled_order.filled_amount or filled_order.amount,  # 数量完全一致
                status=GridOrderStatus.PENDING,
                created_at=datetime.now(),
                parent_order_id=filled_order.order_id
            )

            # 6. 下反向订单
            # 🔥 Lighter交易所：grid_engine_impl.py 的 place_order 方法已自动使用全局锁
            # 确保所有下单操作（反手单、止盈订单、健康检查补单等）都串行执行
            placed_order = await self.engine.place_order(reverse_order, source="反手单")
            self.state.add_order(placed_order)

            # 7. 记录关联关系
            filled_order.reverse_order_id = placed_order.order_id

            self.logger.info(
                f"✅ 反向订单已挂: {new_side.value} "
                f"{reverse_order.amount}@{new_price} "
                f"(Grid {new_grid_id}) "
                f"[ClientID: {reverse_order.client_id or 'N/A'}]"
            )

            # 🔥 优化：将所有非关键操作移到后台任务，不阻塞反手单提交流程
            async def _post_order_placement_tasks():
                """订单提交后的后台任务（不阻塞反手单提交）"""
                try:
                    # 🔥 注意：Lighter的串行延迟已移到主流程（第493行），确保反手单串行执行
                    # 这里不再需要延迟，避免重复等待

                    # 8. 更新当前价格（使用成交价格作为当前价格，避免REST API调用）
                    current_price = filled_order.filled_price
                    current_grid_id = self.config.get_grid_index_by_price(
                        current_price)
                    self.state.update_current_price(
                        current_price, current_grid_id)

                    # 🔥 9. 检查是否触发或退出剥头皮模式（后台执行）
                    await self._check_scalping_mode(current_price, current_grid_id)

                    # 🛡️ 完整本金保护检查（后台执行，不阻塞下单）
                    if self.capital_protection_manager:
                        if not self.capital_protection_manager.is_active():
                            # 检查是否应该触发本金保护
                            if self.capital_protection_manager.should_trigger(current_price, current_grid_id):
                                self.capital_protection_manager.activate()
                                self.logger.warning(
                                    f"🛡️ 本金保护已激活！等待抵押品回本... "
                                    f"初始本金: ${self.capital_protection_manager.get_initial_capital():,.2f}"
                                )
                except Exception as e:
                    self.logger.error(f"❌ 后台任务执行失败: {e}")

            # 创建后台任务，不阻塞当前流程
            asyncio.create_task(_post_order_placement_tasks())

            # 重置错误计数
            self._error_count = 0

        except Exception as e:
            self.logger.error(f"❌ 处理订单成交失败: {e}")
            self._handle_error(e)

    async def _on_batch_orders_filled(self, filled_orders: List[GridOrder]):
        """
        批量订单成交处理

        处理价格剧烈波动导致的多订单同时成交

        Args:
            filled_orders: 已成交订单列表
        """
        try:
            # 🔥 关键检查：防止在重置期间处理订单
            if self._paused:
                self.logger.warning("系统已暂停，跳过批量订单处理")
                return

            if self._resetting:
                self.logger.warning("⚠️ 系统正在重置中，跳过批量订单处理")
                return

            self.logger.info(
                f"⚡ 批量成交: {len(filled_orders)}个订单"
            )

            # 1. 批量更新状态和记录
            for order in filled_orders:
                self.state.mark_order_filled(
                    order.order_id,
                    order.filled_price,
                    order.filled_amount or order.amount
                )
                # 🔥 记录交易历史（不影响持仓）
                self.tracker.record_filled_order(order)

            # 2. 批量计算反向订单
            reverse_params = self.strategy.calculate_batch_reverse_orders(
                filled_orders,
                self.config.grid_interval,
                self.config.reverse_order_grid_distance
            )

            # 3. 创建反向订单列表
            reverse_orders = []
            for side, price, grid_id, amount in reverse_params:
                order = GridOrder(
                    order_id="",
                    grid_id=grid_id,
                    side=side,
                    price=price,
                    amount=amount,
                    status=GridOrderStatus.PENDING,
                    created_at=datetime.now()
                )
                reverse_orders.append(order)

            # 4. 批量下单
            placed_orders = await self.engine.place_batch_orders(reverse_orders)

            # 5. 批量更新状态
            for order in placed_orders:
                self.state.add_order(order)

            self.logger.info(
                f"✅ 批量反向订单已挂: {len(placed_orders)}个"
            )

            # 6. 更新当前价格
            current_price = await self.engine.get_current_price()
            current_grid_id = self.config.get_grid_index_by_price(
                current_price)
            self.state.update_current_price(current_price, current_grid_id)

            # 重置错误计数
            self._error_count = 0

        except Exception as e:
            self.logger.error(f"❌ 批量处理订单成交失败: {e}")
            self._handle_error(e)

    def _handle_error(self, error: Exception):
        """
        处理异常

        策略：
        1. 记录错误
        2. 增加错误计数
        3. 超过阈值则暂停系统

        Args:
            error: 异常对象
        """
        self._error_count += 1

        self.logger.error(
            f"异常发生 ({self._error_count}/{self._max_errors}): {error}"
        )

        # 如果错误次数过多，暂停系统
        if self._error_count >= self._max_errors:
            self.logger.error(
                f"❌ 错误次数达到上限({self._max_errors})，暂停系统"
            )
            # 🔥 判断是否为网络错误
            error_str = str(error).lower()
            if any(keyword in error_str for keyword in ['cannot connect', 'connection', 'timeout', 'ssl', 'network', '返回none']):
                asyncio.create_task(self.pause(reason='network'))
            else:
                asyncio.create_task(self.pause(reason='error'))

    async def process_pending_immediate_fills(self):
        """
        处理重置期间缓存的立即成交订单

        工作流程：
        1. 获取并清空缓存列表
        2. 批量计算反向订单
        3. 批量挂反向订单

        注意：
        - 此方法应在重置完成、锁释放后调用
        - 此时本金已重新初始化，网格已重置
        - 可以安全地挂反向订单
        """
        if not self._pending_immediate_fills:
            return

        pending = self._pending_immediate_fills.copy()
        self._pending_immediate_fills.clear()

        if not pending:
            return

        self.logger.info(
            f"🔄 开始处理 {len(pending)} 个缓存的立即成交订单..."
        )

        try:
            # 1. 批量计算反向订单
            reverse_params = self.strategy.calculate_batch_reverse_orders(
                pending,
                self.config.grid_interval,
                self.config.reverse_order_grid_distance
            )

            # 2. 创建反向订单列表
            reverse_orders = []
            for side, price, grid_id, amount in reverse_params:
                order = GridOrder(
                    order_id="",
                    grid_id=grid_id,
                    side=side,
                    price=price,
                    amount=amount,
                    status=GridOrderStatus.PENDING,
                    created_at=datetime.now()
                )
                reverse_orders.append(order)

            # 3. 批量下单
            placed_orders = await self.engine.place_batch_orders(reverse_orders)

            # 4. 批量更新状态
            for order in placed_orders:
                self.state.add_order(order)

            self.logger.info(
                f"✅ 缓存订单处理完成: 挂出 {len(placed_orders)} 个反向订单（来自 {len(pending)} 个缓存订单）"
            )

        except Exception as e:
            self.logger.error(f"❌ 处理缓存订单失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def _cleanup_before_start(self):
        """
        启动前清理旧订单和持仓

        目的：
        1. 避免ORDER_LIMIT错误（交易所订单数量上限）
        2. 确保系统从干净状态启动
        3. 避免本地状态与交易所状态不一致

        清理步骤：
        1. 取消所有开放订单
        2. 平掉所有持仓（市价单）
        3. 等待清理生效
        """
        self.logger.info("=" * 80)
        self.logger.info("🧹 启动前清理：正在清理旧订单和持仓...")
        self.logger.info("=" * 80)

        # 步骤1: 取消所有旧订单
        try:
            self.logger.info("📋 步骤1: 正在取消所有旧订单...")

            # 获取当前所有订单
            existing_orders = await self.engine.exchange.get_open_orders(
                symbol=self.config.symbol
            )

            if len(existing_orders) > 0:
                self.logger.warning(
                    f"⚠️ 检测到{len(existing_orders)}个旧订单，正在尝试批量取消..."
                )

                # 🔥 策略：优先使用批量取消API，如果不支持或失败则降级为逐个取消
                use_batch_cancel = True
                cancelled_count = 0

                # 步骤1: 尝试批量取消
                try:
                    cancelled_orders = await self.engine.exchange.cancel_all_orders(
                        symbol=self.config.symbol
                    )

                    if cancelled_orders:
                        cancelled_count = len(cancelled_orders)
                        self.logger.info(
                            f"✅ 批量取消API调用成功: 返回{cancelled_count}个订单"
                        )

                        # 🔥 检查：如果返回的订单数量明显少于实际订单，可能批量取消未完全生效
                        if cancelled_count < len(existing_orders) * 0.5:  # 少于50%，可能有问题
                            self.logger.warning(
                                f"⚠️ 批量取消返回订单数({cancelled_count})明显少于实际订单数({len(existing_orders)})，"
                                f"可能是交易所不支持真正的批量取消，需要验证并降级为逐个取消..."
                            )
                            # 继续验证，不立即降级
                    else:
                        # 返回空列表，可能是批量取消不支持或订单已被取消
                        self.logger.warning(
                            "⚠️ 批量取消返回空列表，可能是交易所不支持批量取消，"
                            "需要验证订单状态..."
                        )

                except AttributeError as e:
                    # 交易所没有实现 cancel_all_orders 方法
                    self.logger.warning(
                        f"⚠️ 交易所不支持批量取消API: {e}，使用逐个取消模式..."
                    )
                    use_batch_cancel = False
                except Exception as e:
                    # 批量取消API调用失败
                    self.logger.error(f"❌ 批量取消订单失败: {e}")
                    self.logger.warning("降级为逐个取消模式...")
                    use_batch_cancel = False

                # 步骤2: 等待交易所处理（链上确认需要时间）
                if use_batch_cancel:
                    await asyncio.sleep(2)

                    # 步骤3: 验证是否清理成功
                    remaining_orders = await self.engine.exchange.get_open_orders(
                        symbol=self.config.symbol
                    )

                    if len(remaining_orders) > 0:
                        self.logger.warning(
                            f"⚠️ 批量取消后仍有{len(remaining_orders)}个订单未取消，"
                            f"可能是链上确认延迟或批量取消未完全生效，等待中..."
                        )
                        # 再等待一次
                        await asyncio.sleep(3)
                        remaining_orders = await self.engine.exchange.get_open_orders(
                            symbol=self.config.symbol
                        )

                        if len(remaining_orders) > 0:
                            self.logger.warning(
                                f"⚠️ 仍有{len(remaining_orders)}个订单未取消，"
                                f"降级为逐个取消剩余订单..."
                            )
                            use_batch_cancel = False
                            # 使用剩余订单列表进行逐个取消
                            existing_orders = remaining_orders
                        else:
                            self.logger.info("✅ 所有旧订单已清理（延迟确认）")
                    else:
                        self.logger.info("✅ 所有旧订单已清理（批量取消成功）")
                else:
                    # 批量取消未尝试或返回空列表，需要验证并可能使用逐个取消
                    if cancelled_count == 0:
                        # 批量取消返回空，需要验证订单是否真的被取消
                        await asyncio.sleep(1)
                        remaining_orders = await self.engine.exchange.get_open_orders(
                            symbol=self.config.symbol
                        )
                        if len(remaining_orders) > 0:
                            self.logger.warning(
                                f"⚠️ 批量取消返回空但仍有{len(remaining_orders)}个订单，"
                                f"交易所可能不支持批量取消，使用逐个取消..."
                            )
                            existing_orders = remaining_orders
                        else:
                            self.logger.info("✅ 所有旧订单已清理（批量取消已生效）")
                            use_batch_cancel = True  # 标记为成功，跳过逐个取消

                # 步骤4: 如果批量取消失败或不支持，使用逐个取消
                if not use_batch_cancel:
                    self.logger.info(
                        f"📋 使用逐个取消模式取消{len(existing_orders)}个订单...")
                    cancel_count = 0
                    for order in existing_orders:
                        try:
                            await self.engine.exchange.cancel_order(
                                order_id=order.id,
                                symbol=self.config.symbol
                            )
                            cancel_count += 1
                        except Exception as e:
                            self.logger.warning(f"取消订单{order.id}失败: {e}")

                    self.logger.info(
                        f"✅ 已取消{cancel_count}/{len(existing_orders)}个旧订单（逐个取消模式）"
                    )

                    # 最终验证
                    await asyncio.sleep(1)
                    final_remaining = await self.engine.exchange.get_open_orders(
                        symbol=self.config.symbol
                    )
                    if len(final_remaining) > 0:
                        self.logger.warning(
                            f"⚠️ 逐个取消后仍有{len(final_remaining)}个订单未取消，"
                            f"可能需要手动处理"
                        )
                    else:
                        self.logger.info("✅ 所有旧订单已清理（逐个取消成功）")
            else:
                self.logger.info("✅ 无旧订单，跳过清理")

        except Exception as e:
            self.logger.error(f"❌ 清理旧订单失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

        # 步骤2: 平掉所有持仓
        try:
            self.logger.info("📊 步骤2: 正在检查持仓...")

            # 获取当前持仓
            positions = await self.engine.exchange.get_positions(
                symbols=[self.config.symbol]
            )

            if positions and len(positions) > 0:
                position = positions[0]
                position_size = position.size or Decimal('0')

                if position_size != 0:
                    self.logger.warning(
                        f"⚠️ 检测到持仓: {position_size} {self.config.symbol.split('_')[0]}, "
                        f"成本=${position.entry_price}, "
                        f"未实现盈亏=${position.unrealized_pnl}"
                    )

                    # 计算平仓方向和数量
                    close_side = 'Sell' if position_size > 0 else 'Buy'
                    close_amount = abs(position_size)

                    self.logger.warning(
                        f"🔄 正在平仓: {close_side} {close_amount} (市价单)..."
                    )

                    # 使用市价单平仓（参考 order_health_checker.py 的实现）
                    try:
                        from ....adapters.exchanges.models import OrderSide, OrderType

                        # 🔥 修复：获取当前市场价格（Hyperliquid市价单需要价格计算滑点）
                        ticker = await self.engine.exchange.get_ticker(self.config.symbol)
                        current_price = ticker.last

                        # 确定平仓方向：平多仓=卖出，平空仓=买入
                        order_side = OrderSide.SELL if close_side == 'Sell' else OrderSide.BUY

                        # 调用交易所接口平仓（使用市价单）
                        # 注意：
                        # - Backpack: 不支持 reduceOnly，price=None即可
                        # - Hyperliquid: 市价单需要price来计算滑点（默认5%）
                        placed_order = await self.engine.exchange.create_order(
                            symbol=self.config.symbol,
                            side=order_side,
                            order_type=OrderType.MARKET,
                            amount=close_amount,
                            price=current_price  # Hyperliquid需要价格计算滑点，Backpack会忽略
                        )

                        if placed_order is None:
                            raise Exception(
                                f"平仓失败: 交易所返回None ({order_side.value} {close_amount})")

                        self.logger.info(f"✅ 平仓订单已提交: {placed_order.id}")

                        # 等待平仓完成
                        await asyncio.sleep(3)

                        # 验证是否平仓成功
                        new_positions = await self.engine.exchange.get_positions(
                            symbols=[self.config.symbol]
                        )
                        if new_positions and len(new_positions) > 0:
                            new_position_size = new_positions[0].size or Decimal(
                                '0')
                            if new_position_size == 0:
                                self.logger.info("✅ 持仓已清空")
                            else:
                                self.logger.warning(
                                    f"⚠️ 持仓未完全清空，剩余: {new_position_size}"
                                )
                        else:
                            self.logger.info("✅ 持仓已清空")

                    except Exception as e:
                        self.logger.error(f"❌ 平仓失败: {e}")
                        import traceback
                        self.logger.error(traceback.format_exc())
                else:
                    self.logger.info("✅ 无持仓，跳过平仓")
            else:
                self.logger.info("✅ 无持仓，跳过平仓")

        except Exception as e:
            self.logger.error(f"❌ 检查/平仓失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

        self.logger.info("=" * 80)
        self.logger.info("✅ 启动前清理完成")
        self.logger.info("=" * 80)
        self.logger.info("")  # 空行分隔

    async def start(self):
        """启动网格系统"""
        if self._running:
            self.logger.warning("网格系统已经在运行")
            return

        # 🆕 启动前清理旧订单和持仓
        await self._cleanup_before_start()

        # 🔥 Lighter交易所：设置保证金模式（必须在下单前设置）
        exchange_id = str(self.config.exchange).lower(
        ) if self.config.exchange else ''
        if exchange_id == 'lighter':
            # ⚠️ 由于 Lighter SDK 的 C 库存在 Bug，无法正确设置 isolated 模式
            # SDK 的 update_leverage 方法传入 margin_mode=1 时，生成的交易 JSON 中 MarginMode 仍为 0
            # 因此暂时跳过保证金模式自动设置，使用账户默认模式或网页端手动设置的模式

            margin_mode = getattr(self.config, 'margin_mode', 'cross')
            leverage = getattr(self.config, 'leverage', 1)

            self.logger.warning("⚠️ 已跳过保证金模式自动设置（SDK bug: isolated模式无法生效）")
            self.logger.warning(
                f"📝 当前配置: {self.config.symbol} → {margin_mode}模式, {leverage}x杠杆")
            self.logger.warning("💡 建议: 请在 Lighter 网页端手动设置保证金模式和杠杆（一次性设置即可）")

        await self.initialize()
        await self.engine.start()

        # 🔥 主动同步初始持仓到WebSocket缓存
        # Backpack的WebSocket只在持仓变化时推送，不会推送初始状态
        # 所以我们需要在启动时主动获取一次
        position_data = {'size': Decimal('0'), 'entry_price': Decimal(
            '0'), 'unrealized_pnl': Decimal('0')}
        try:
            self.logger.info("📊 正在同步初始持仓数据...")
            position_data = await self.engine.get_real_time_position(self.config.symbol)

            # 如果WebSocket缓存为空，使用REST API获取并同步
            if position_data['size'] == 0 and position_data['entry_price'] == 0:
                positions = await self.engine.exchange.get_positions(symbols=[self.config.symbol])
                if positions and len(positions) > 0:
                    position = positions[0]
                    real_size = position.size or Decimal('0')
                    real_entry_price = position.entry_price or Decimal('0')

                    # 同步到WebSocket缓存
                    if hasattr(self.engine.exchange, '_position_cache'):
                        self.engine.exchange._position_cache[self.config.symbol] = {
                            'size': real_size,
                            'entry_price': real_entry_price,
                            'unrealized_pnl': position.unrealized_pnl or Decimal('0'),
                            'side': 'Long' if real_size > 0 else 'Short',
                            'timestamp': datetime.now()
                        }
                        self.logger.info(
                            f"✅ 初始持仓已同步到WebSocket缓存: "
                            f"{real_size} {self.config.symbol.split('_')[0]}, "
                            f"成本=${real_entry_price:,.2f}"
                        )
                        # 更新position_data供后续使用
                        position_data = {
                            'size': real_size,
                            'entry_price': real_entry_price,
                            'unrealized_pnl': position.unrealized_pnl or Decimal('0')
                        }
            else:
                # WebSocket缓存已有数据
                self.logger.info(
                    f"✅ WebSocket缓存已有持仓数据: "
                    f"{position_data['size']} {self.config.symbol.split('_')[0]}, "
                    f"成本=${position_data['entry_price']:,.2f}"
                )
        except Exception as e:
            self.logger.warning(f"同步初始持仓失败（不影响运行）: {e}")

        # 🔥 检查是否应该立即激活剥头皮模式
        # 如果启动时已有持仓，且价格已在触发阈值以下，立即激活
        if self.config.is_scalping_enabled():
            try:
                current_price = await self.engine.get_current_price()
                current_grid_id = self.config.get_grid_index_by_price(
                    current_price)

                # 更新scalping_manager的持仓信息
                if position_data['size'] != 0:
                    initial_capital = self.scalping_manager.get_initial_capital()
                    self.scalping_manager.update_position(
                        position_data['size'],
                        position_data['entry_price'],
                        initial_capital,
                        self.balance_monitor.collateral_balance  # 🔥 使用 BalanceMonitor 的余额
                    )

                # 检查是否应该触发剥头皮模式（需要传递current_price和current_grid_id）
                if self.scalping_manager.should_trigger(current_price, current_grid_id):
                    self.logger.info(
                        f"🎯 检测到启动时已在触发区域 (Grid {current_grid_id} <= "
                        f"Grid {self.config.get_scalping_trigger_grid()})，立即激活剥头皮模式"
                    )
                    # 🔥 使用新模块
                    if self.scalping_ops:
                        await self.scalping_ops.activate()
                else:
                    self.logger.info(
                        f"📊 剥头皮模式待触发 (当前: Grid {current_grid_id}, "
                        f"触发点: Grid {self.config.get_scalping_trigger_grid()})"
                    )
            except Exception as e:
                self.logger.warning(f"检查剥头皮模式失败: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

        # 🔥 订阅WebSocket持仓流（实时更新，避免频繁REST查询）
        try:
            self.logger.info("📡 正在订阅WebSocket持仓流...")
            await self.engine.exchange.subscribe_positions(self._on_position_update_from_ws)
            self.logger.info("✅ WebSocket持仓流订阅成功")
        except Exception as e:
            self.logger.warning(f"⚠️  WebSocket持仓流订阅失败: {e}，将使用REST API备用")

        # 🔥 价格移动网格：启动价格脱离监控
        if self.config.is_follow_mode():
            asyncio.create_task(self._price_escape_monitor())
            self.logger.info("✅ 价格脱离监控已启动")

        # 💰 启动余额轮询监控（使用新模块 BalanceMonitor）
        await self.balance_monitor.start_monitoring()

        # 🛑 启动止损保护监控（优先级最高）
        await self.stop_loss_monitor.start_monitoring()

        self.logger.info("🚀 网格系统已启动")

    async def pause(self, reason: str = 'manual'):
        """
        暂停网格系统（保留挂单）

        Args:
            reason: 暂停原因 ('network'=网络故障, 'error'=代码错误, 'manual'=手动暂停)
        """
        self._paused = True
        self._paused_reason = reason
        self.state.pause()

        reason_text = {
            'network': '网络故障',
            'error': '代码错误',
            'manual': '手动操作'
        }.get(reason, reason)

        self.logger.info(f"⏸️ 网格系统已暂停（原因: {reason_text}）")

    async def resume(self, auto: bool = False):
        """
        恢复网格系统

        Args:
            auto: 是否为自动恢复（网络恢复触发）
        """
        was_network_paused = self._paused_reason == 'network'

        self._paused = False
        self._paused_reason = None
        self._error_count = 0  # 重置错误计数
        self.state.resume()

        if auto:
            self.logger.info(f"▶️ 网格系统自动恢复（网络故障已恢复）")
        else:
            self.logger.info("▶️ 网格系统已恢复")

    async def stop(self):
        """停止网格系统（取消所有挂单）"""
        self._running = False
        self._paused = False

        # 🛑 停止止损保护监控
        await self.stop_loss_monitor.stop_monitoring()

        # 💰 停止余额监控（使用新模块）
        await self.balance_monitor.stop_monitoring()

        # 🔄 停止持仓同步监控（使用新模块）
        await self.position_monitor.stop_monitoring()

        # 取消所有挂单
        cancelled_count = await self.engine.cancel_all_orders()
        self.logger.info(f"取消了{cancelled_count}个挂单")

        # 停止引擎
        await self.engine.stop()

        # 更新状态
        self.state.stop()

        self.logger.info("⏹️ 网格系统已停止")

    async def get_statistics(self) -> GridStatistics:
        """
        获取统计数据（优先使用WebSocket真实持仓）

        Returns:
            网格统计数据
        """
        # 更新当前价格
        try:
            current_price = await self.engine.get_current_price()
            current_grid_id = self.config.get_grid_index_by_price(
                current_price)
            self.state.update_current_price(current_price, current_grid_id)
        except Exception as e:
            self.logger.warning(f"获取当前价格失败: {e}")

        # 🔥 同步engine的最新订单统计到state
        self._sync_orders_from_engine()

        # 获取统计数据（本地追踪器）
        stats = self.tracker.get_statistics()

        # 🔥 获取持仓数据来源（从 position_monitor 获取实际来源）
        if hasattr(self, 'position_monitor') and self.position_monitor:
            stats.position_data_source = self.position_monitor.get_position_data_source()
        else:
            # 🔥 如果没有position_monitor，默认为Tracker
            stats.position_data_source = "PositionTracker"

        # 🔥 添加监控方式信息
        stats.monitoring_mode = self.engine.get_monitoring_mode()

        # 💰 使用真实的账户余额（从 BalanceMonitor 获取）
        balances = self.balance_monitor.get_balances()
        stats.spot_balance = balances['spot_balance']
        stats.collateral_balance = balances['collateral_balance']
        stats.order_locked_balance = balances['order_locked_balance']
        stats.total_balance = balances['total_balance']

        # 🔥 获取余额数据来源（从 balance_monitor 获取实际来源）
        if hasattr(self.balance_monitor, 'get_balance_data_source'):
            stats.balance_data_source = self.balance_monitor.get_balance_data_source()
        else:
            stats.balance_data_source = "REST API"

        # 💰 初始本金和盈亏（始终设置，无论是否启用本金保护）
        stats.initial_capital = self.balance_monitor.initial_capital
        if stats.initial_capital > 0:
            stats.capital_profit_loss = self.balance_monitor.collateral_balance - \
                stats.initial_capital
        else:
            stats.capital_profit_loss = Decimal('0')

        # 🛡️ 本金保护模式状态
        if self.capital_protection_manager:
            stats.capital_protection_enabled = True
            stats.capital_protection_active = self.capital_protection_manager.is_active()

        # 🔄 价格脱离监控状态（价格移动网格专用）
        if self.config.is_follow_mode() and self._price_escape_start_time is not None:
            import time
            escape_duration = int(time.time() - self._price_escape_start_time)
            stats.price_escape_active = True
            stats.price_escape_duration = escape_duration
            stats.price_escape_timeout = self.config.follow_timeout
            stats.price_escape_remaining = max(
                0, self.config.follow_timeout - escape_duration)

            # 判断脱离方向
            if current_price < self.config.lower_price:
                stats.price_escape_direction = "down"
            elif current_price > self.config.upper_price:
                stats.price_escape_direction = "up"

        # 💰 止盈模式状态
        if self.take_profit_manager:
            stats.take_profit_enabled = True
            stats.take_profit_active = self.take_profit_manager.is_active()
            stats.take_profit_initial_capital = self.take_profit_manager.get_initial_capital()
            stats.take_profit_current_profit = self.take_profit_manager.get_profit_amount(
                self.balance_monitor.collateral_balance)  # 🔥 使用 BalanceMonitor 的余额
            stats.take_profit_profit_rate = self.take_profit_manager.get_profit_percentage(
                self.balance_monitor.collateral_balance)  # 🔥 使用 BalanceMonitor 的余额
            stats.take_profit_threshold = self.config.take_profit_percentage * 100  # 转为百分比

        # 🔒 价格锁定模式状态
        if self.price_lock_manager:
            stats.price_lock_enabled = True
            stats.price_lock_active = self.price_lock_manager.is_locked()
            stats.price_lock_threshold = self.config.price_lock_threshold

        # 🆕 触发次数统计（仅标记）
        stats.scalping_trigger_count = self._scalping_trigger_count
        stats.price_escape_trigger_count = self._price_escape_trigger_count
        stats.take_profit_trigger_count = self._take_profit_trigger_count
        stats.capital_protection_trigger_count = self._capital_protection_trigger_count

        # 🔥 计算循环APR预估（整点更新）
        self._calculate_cycle_apr(stats)

        return stats

    def _calculate_cycle_apr(self, stats: GridStatistics) -> None:
        """
        计算循环APR预估（每10分钟更新，运行超过10分钟即可开始计算）

        🆕 重大修改：
        1. 本金基准：从初始本金改为网格总仓位
        2. 统计两种APR：
           - 现有循环APR（基于全部运行时间）
           - 实时循环APR（基于过去10分钟）

        逻辑：
        1. 首次计算：运行超过10分钟且有完整循环，立即计算
        2. 后续更新：每10分钟更新一次
        3. 不足1小时时：根据当前速度推算1小时的循环次数
        4. 计算每次循环的盈利百分比（基于网格间隔和手续费）
        5. 根据推算的每小时循环次数，计算年化收益和APR
        """
        # 检查是否有足够的数据（需要至少有一个完整循环）
        if self._cycle_start_time is None or stats.completed_cycles == 0:
            stats.cycle_apr_estimate = Decimal('0')
            stats.realtime_cycle_apr_estimate = Decimal('0')
            stats.cycle_profit_percentage = Decimal('0')
            return

        # 计算运行时间（小时和分钟）
        now = datetime.now()
        running_seconds = (now - self._cycle_start_time).total_seconds()
        running_hours = running_seconds / 3600
        running_minutes = running_seconds / 60

        # 🆕 最小运行时间从1小时改为10分钟
        if running_minutes < 10:
            # 运行不足10分钟，数据不足以预估
            stats.cycle_apr_estimate = Decimal('0')
            stats.realtime_cycle_apr_estimate = Decimal('0')
            stats.cycle_profit_percentage = Decimal('0')
            return

        # 🆕 检查是否需要更新（每10分钟更新一次）
        should_update = False

        if self._last_apr_update_time is None:
            # 首次计算：运行超过10分钟且有完整循环，立即计算
            should_update = True
            self.logger.info(
                f"📊 首次APR计算: 运行时间={running_minutes:.1f}分钟, 循环次数={stats.completed_cycles}")
        else:
            # 后续更新：距离上次更新至少10分钟
            minutes_since_update = (
                now - self._last_apr_update_time).total_seconds() / 60
            if minutes_since_update >= 10:
                should_update = True

        if not should_update:
            # 🔥 不需要更新，使用上次计算的值（复用到新的stats对象）
            stats.cycle_apr_estimate = self._last_apr_estimate
            stats.realtime_cycle_apr_estimate = self._last_realtime_apr_estimate  # 🆕
            stats.cycle_apr_formula_data = self._last_apr_formula_data.copy()
            stats.realtime_apr_formula_data = self._last_realtime_apr_formula_data.copy()  # 🆕
            stats.cycle_profit_percentage = self._last_cycle_profit_pct
            return

        # ========== 第一部分：基础数据计算 ==========

        # 1. 计算网格中间价格（用于计算仓位价值）
        middle_price = (stats.price_range[0] +
                        stats.price_range[1]) / Decimal('2')
        grid_interval = stats.grid_interval
        order_amount = self.config.order_amount  # 每格订单数量（如0.00025 BTC）

        # 2. 🆕 计算网格总仓位作为本金基准
        # 网格总仓位 = 网格数量 × 每格基础数量 × 网格中间价格
        grid_total_capital = Decimal(
            str(self.config.grid_count)) * order_amount * middle_price

        # 3. 计算每次循环的净盈利金额
        # 🔥 关键修复：需要乘以反手挂单距离，因为反手距离>1时，一个循环产生的利润更高
        # 例如：reverse_order_grid_distance=2时，买@$2.00→卖@$2.02，价差利润是2格而不是1格
        reverse_distance = Decimal(
            str(self.config.reverse_order_grid_distance))
        price_profit_per_order = grid_interval * \
            order_amount * reverse_distance  # 价差收益
        fee_rate = self.config.fee_rate
        total_fee_per_order = middle_price * \
            order_amount * fee_rate * Decimal('2')  # 双边手续费
        net_profit_per_cycle = price_profit_per_order - total_fee_per_order

        # 4. 计算每次循环的盈利百分比（用于显示）
        if middle_price > 0:
            cycle_profit_pct = (net_profit_per_cycle /
                                (middle_price * order_amount)) * Decimal('100')
        else:
            cycle_profit_pct = Decimal('0')
        stats.cycle_profit_percentage = cycle_profit_pct

        # ========== 第二部分：现有循环APR（基于全部运行时间） ==========

        # 计算循环频率（次/小时）
        cycles_per_hour_overall = Decimal(
            str(stats.completed_cycles)) / Decimal(str(running_hours))
        hours_per_year = Decimal('365.25') * Decimal('24')  # 8766小时
        cycles_per_year_overall = cycles_per_hour_overall * hours_per_year
        annual_profit_overall = net_profit_per_cycle * cycles_per_year_overall

        # 计算现有循环APR
        if grid_total_capital > 0:
            stats.cycle_apr_estimate = (
                annual_profit_overall / grid_total_capital) * Decimal('100')
        else:
            stats.cycle_apr_estimate = Decimal('0')

        # 保存现有APR计算公式数据
        stats.cycle_apr_formula_data = {
            'net_profit_per_cycle': float(net_profit_per_cycle),
            'cycles_per_hour': float(cycles_per_hour_overall),
            'cycles_per_year': float(cycles_per_year_overall),
            'annual_profit_amount': float(annual_profit_overall),
            'grid_total_capital': float(grid_total_capital),
            'running_hours': float(running_hours),
            'completed_cycles': stats.completed_cycles
        }

        # ========== 第三部分：实时循环APR（基于过去10分钟） ==========

        # 统计过去10分钟的循环次数
        cutoff_time = now - timedelta(minutes=10)
        recent_cycles = len(
            [ts for ts in self._cycle_timestamps if ts > cutoff_time])

        if recent_cycles > 0:
            # 有过去10分钟的数据，计算实时APR
            cycles_per_hour_realtime = Decimal(
                str(recent_cycles)) * Decimal('6')  # 10分钟 × 6 = 1小时
            cycles_per_year_realtime = cycles_per_hour_realtime * hours_per_year
            annual_profit_realtime = net_profit_per_cycle * cycles_per_year_realtime

            if grid_total_capital > 0:
                stats.realtime_cycle_apr_estimate = (
                    annual_profit_realtime / grid_total_capital) * Decimal('100')
            else:
                stats.realtime_cycle_apr_estimate = Decimal('0')

            # 保存实时APR计算公式数据
            stats.realtime_apr_formula_data = {
                'net_profit_per_cycle': float(net_profit_per_cycle),
                'cycles_per_hour': float(cycles_per_hour_realtime),
                'cycles_per_year': float(cycles_per_year_realtime),
                'annual_profit_amount': float(annual_profit_realtime),
                'grid_total_capital': float(grid_total_capital),
                'recent_cycles': recent_cycles,
                'time_window': 10  # 分钟
            }
        else:
            # 过去10分钟没有循环，使用现有APR
            stats.realtime_cycle_apr_estimate = stats.cycle_apr_estimate
            stats.realtime_apr_formula_data = stats.cycle_apr_formula_data.copy()

        # ========== 第四部分：保存缓存和记录日志 ==========

        # 记录更新时间
        self._last_apr_update_time = now

        # 保存本次计算的值（用于下次不更新时复用）
        self._last_apr_estimate = stats.cycle_apr_estimate
        self._last_realtime_apr_estimate = stats.realtime_cycle_apr_estimate  # 🆕
        self._last_apr_formula_data = stats.cycle_apr_formula_data.copy()
        self._last_realtime_apr_formula_data = stats.realtime_apr_formula_data.copy()  # 🆕
        self._last_cycle_profit_pct = stats.cycle_profit_percentage

        # 日志显示
        if running_hours < 1.0:
            self.logger.info(
                f"📊 APR更新（推算）: 运行={running_minutes:.1f}分钟, "
                f"循环={stats.completed_cycles}次, "
                f"现有APR={stats.cycle_apr_estimate:.2f}% ({cycles_per_hour_overall:.2f}次/h), "
                f"实时APR={stats.realtime_cycle_apr_estimate:.2f}% (近10分钟{recent_cycles}次), "
                f"本金=${grid_total_capital:,.2f}"
            )
        else:
            self.logger.info(
                f"📊 APR更新: 运行={running_hours:.1f}小时, "
                f"循环={stats.completed_cycles}次, "
                f"现有APR={stats.cycle_apr_estimate:.2f}% ({cycles_per_hour_overall:.2f}次/h), "
                f"实时APR={stats.realtime_cycle_apr_estimate:.2f}% (近10分钟{recent_cycles}次), "
                f"本金=${grid_total_capital:,.2f}"
            )

    def get_state(self) -> GridState:
        """获取网格状态"""
        return self.state

    def is_running(self) -> bool:
        """是否运行中"""
        return self._running and not self._paused

    def is_paused(self) -> bool:
        """是否暂停"""
        return self._paused

    def is_stopped(self) -> bool:
        """是否已停止"""
        return not self._running

    def get_status_text(self) -> str:
        """获取状态文本"""
        if self._paused:
            return "⏸️ 已暂停"
        elif self._running:
            return "🟢 运行中"
        else:
            return "⏹️ 已停止"

    async def _scalping_position_monitor_loop(self):
        """
        [已弃用] 剥头皮模式持仓监控循环（REST API轮询方式）

        ⚠️ 此方法已被WebSocket事件驱动方式取代，保留仅作备份
        现在使用 _on_position_update_from_ws() 实时处理持仓更新
        """
        self.logger.warning("⚠️ 使用了已弃用的REST API轮询监控（应该使用WebSocket事件驱动）")
        self.logger.info("📊 剥头皮持仓监控循环已启动")

        last_position = Decimal('0')
        last_entry_price = Decimal('0')

        try:
            while self.scalping_manager and self.scalping_manager.is_active():
                try:
                    # 从API获取实时持仓
                    position_data = await self.engine.get_real_time_position(self.config.symbol)
                    current_position = position_data['size']
                    current_entry_price = position_data['entry_price']

                    # 检查是否有变化
                    position_changed = (
                        current_position != last_position or
                        current_entry_price != last_entry_price
                    )

                    if position_changed:
                        self.logger.info(
                            f"📊 持仓变化检测: "
                            f"数量 {last_position} → {current_position}, "
                            f"成本 ${last_entry_price:,.2f} → ${current_entry_price:,.2f}"
                        )

                        # 更新剥头皮管理器的持仓信息
                        initial_capital = self.scalping_manager.get_initial_capital()
                        self.scalping_manager.update_position(
                            current_position, current_entry_price, initial_capital,
                            self.balance_monitor.collateral_balance)  # 🔥 使用 BalanceMonitor 的余额

                        # 更新止盈订单
                        await self._update_take_profit_order_after_position_change(
                            current_position,
                            current_entry_price
                        )

                        # 更新记录
                        last_position = current_position
                        last_entry_price = current_entry_price

                    # 等待下次检查
                    await asyncio.sleep(self._scalping_position_check_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.logger.error(f"持仓监控出错: {e}")
                    await asyncio.sleep(self._scalping_position_check_interval)

        except asyncio.CancelledError:
            self.logger.info("📊 剥头皮持仓监控循环已取消")
        except Exception as e:
            self.logger.error(f"持仓监控循环异常: {e}")
        finally:
            self.logger.info("📊 剥头皮持仓监控循环已结束")

    async def _update_take_profit_order_after_position_change(
        self,
        new_position: Decimal,
        new_entry_price: Decimal
    ):
        """
        持仓变化后更新止盈订单

        Args:
            new_position: 新的持仓数量
            new_entry_price: 新的平均成本价
        """
        if new_position == 0:
            # 持仓归零，取消止盈订单
            if self.scalping_manager.get_current_take_profit_order():
                tp_order = self.scalping_manager.get_current_take_profit_order()
                try:
                    await self.engine.cancel_order(tp_order.order_id)
                    self.state.remove_order(tp_order.order_id)
                    self.logger.info("✅ 持仓归零，已取消止盈订单")
                except Exception as e:
                    self.logger.error(f"取消止盈订单失败: {e}")
            return

        # 取消旧止盈订单
        old_tp_order = self.scalping_manager.get_current_take_profit_order()
        if old_tp_order:
            try:
                await self.engine.cancel_order(old_tp_order.order_id)
                self.state.remove_order(old_tp_order.order_id)
                self.logger.info(f"🔄 已取消旧止盈订单: {old_tp_order.order_id}")
            except Exception as e:
                self.logger.error(f"取消旧止盈订单失败: {e}")

        # 挂新止盈订单
        await self._place_take_profit_order()
        self.logger.info("✅ 止盈订单已更新")

    async def _on_position_update_from_ws(self, position_info: Dict[str, Any]) -> None:
        """
        WebSocket持仓更新回调（事件驱动，实时响应）

        当WebSocket收到持仓更新推送时自动调用
        """
        try:
            # 只在剥头皮模式激活时处理
            if not self.scalping_manager or not self.scalping_manager.is_active():
                return

            # 只处理当前交易对的持仓
            if position_info.get('symbol') != self.config.symbol:
                return

            current_position = position_info.get('size', Decimal('0'))
            entry_price = position_info.get('entry_price', Decimal('0'))

            # 检查是否有变化
            position_changed = (
                current_position != self._last_ws_position_size or
                entry_price != self._last_ws_position_price
            )

            if position_changed:
                self.logger.info(
                    f"📊 WebSocket持仓变化: "
                    f"数量 {self._last_ws_position_size} → {current_position}, "
                    f"成本 ${self._last_ws_position_price:,.2f} → ${entry_price:,.2f}"
                )

                # 更新剥头皮管理器
                initial_capital = self.scalping_manager.get_initial_capital()
                self.scalping_manager.update_position(
                    current_position, entry_price, initial_capital,
                    self.balance_monitor.collateral_balance)  # 🔥 使用 BalanceMonitor 的余额

                # 更新止盈订单
                await self._update_take_profit_order_after_position_change(
                    current_position,
                    entry_price
                )

                # 更新记录
                self._last_ws_position_size = current_position
                self._last_ws_position_price = entry_price

        except Exception as e:
            self.logger.error(f"处理WebSocket持仓更新失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def __repr__(self) -> str:
        return (
            f"GridCoordinator("
            f"status={self.get_status_text()}, "
            f"position={self.tracker.get_current_position()}, "
            f"errors={self._error_count})"
        )

    # ==================== 价格移动网格专用方法 ====================

    async def _price_escape_monitor(self):
        """
        价格脱离监控（价格移动网格专用）

        定期检查价格是否脱离网格范围，如果脱离时间超过阈值则重置网格
        """
        import time

        self.logger.info("🔍 价格脱离监控循环已启动")

        while self._running and not self._paused:
            try:
                current_time = time.time()

                # 检查间隔
                if current_time - self._last_escape_check_time < self._escape_check_interval:
                    await asyncio.sleep(1)
                    continue

                self._last_escape_check_time = current_time

                # 获取当前价格
                current_price = await self.engine.get_current_price()

                # 检查是否脱离
                should_reset, direction = self.config.check_price_escape(
                    current_price)

                if should_reset:
                    # 记录脱离开始时间
                    if self._price_escape_start_time is None:
                        self._price_escape_start_time = current_time
                        self.logger.warning(
                            f"⚠️ 价格脱离网格范围（{direction}方向）: "
                            f"当前价格=${current_price:,.2f}, "
                            f"网格区间=[${self.config.lower_price:,.2f}, ${self.config.upper_price:,.2f}]"
                        )

                    # 检查脱离时间是否超过阈值
                    escape_duration = current_time - self._price_escape_start_time

                    if escape_duration >= self.config.follow_timeout:
                        self.logger.warning(
                            f"🔄 价格脱离超时（{escape_duration:.0f}秒 >= {self.config.follow_timeout}秒），"
                            f"准备重置网格..."
                        )
                        # 🔥 使用新模块
                        await self.reset_manager.execute_price_follow_reset(current_price, direction)
                        self._price_escape_start_time = None
                    else:
                        self.logger.info(
                            f"⏳ 价格脱离中（{direction}方向），"
                            f"已持续 {escape_duration:.0f}/{self.config.follow_timeout}秒"
                        )
                else:
                    # 价格回到范围内，重置脱离计时
                    if self._price_escape_start_time is not None:
                        self.logger.info(
                            f"✅ 价格已回到网格范围内: ${current_price:,.2f}"
                        )
                        self._price_escape_start_time = None

                    # 🔒 检查是否需要解除价格锁定
                    if self.price_lock_manager and self.price_lock_manager.is_locked():
                        if self.price_lock_manager.check_unlock_condition(
                            current_price,
                            self.config.lower_price,
                            self.config.upper_price
                        ):
                            self.price_lock_manager.deactivate_lock()
                            self.logger.info("🔓 价格锁定已解除，恢复正常网格交易")

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                self.logger.info("价格脱离监控已停止")
                break
            except Exception as e:
                self.logger.error(f"价格脱离监控出错: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                await asyncio.sleep(10)  # 出错后等待10秒再继续

    async def _check_scalping_mode(self, current_price: Decimal, current_grid_index: int):
        """
        检查是否触发或退出剥头皮模式

        Args:
            current_price: 当前价格
            current_grid_index: 当前网格索引
        """
        if not self.scalping_manager or not self.scalping_ops:
            return

        # 检查是否应该触发剥头皮（使用新模块）
        if self.scalping_manager.should_trigger(current_price, current_grid_index):
            await self.scalping_ops.activate()

        # 检查是否应该退出剥头皮（使用新模块）
        elif self.scalping_manager.should_exit(current_price, current_grid_index):
            await self.scalping_ops.deactivate()

    async def _check_capital_protection_mode(self, current_price: Decimal, current_grid_index: int):
        """
        检查是否触发本金保护模式

        Args:
            current_price: 当前价格
            current_grid_index: 当前网格索引
        """
        if not self.capital_protection_manager:
            return

        # 如果已经触发，检查是否回本
        if self.capital_protection_manager.is_active():
            # 检查抵押品是否回本
            if self.capital_protection_manager.check_capital_recovery(
                self.balance_monitor.collateral_balance
            ):
                self.logger.warning(
                    f"🛡️ 本金保护：抵押品已回本，准备重置网格！"
                )
                # 🔥 使用新模块
                await self.reset_manager.execute_capital_protection_reset()
        else:
            # 检查是否应该触发
            if self.capital_protection_manager.should_trigger(current_price, current_grid_index):
                self.capital_protection_manager.activate()
                self.logger.warning(
                    f"🛡️ 本金保护已激活！等待抵押品回本... "
                    f"初始本金: ${self.capital_protection_manager.get_initial_capital():,.2f}"
                )

    async def _reset_fixed_range_grid(self, new_capital: Optional[Decimal] = None):
        """重置固定范围网格（保持原有范围）

        Args:
            new_capital: 新的初始本金（止盈后使用）
        """
        try:
            self.logger.info("🔄 重置固定范围网格（保持价格区间）...")

            # 重置所有管理器状态
            if self.scalping_manager:
                self.scalping_manager.reset()
            if self.capital_protection_manager:
                self.capital_protection_manager.reset()
            if self.take_profit_manager:
                self.take_profit_manager.reset()

            # 重置追踪器和状态
            self.tracker.reset()
            self.state.active_orders.clear()  # 清空所有活跃订单
            self.state.pending_buy_orders = 0
            self.state.pending_sell_orders = 0

            # 🔥 重置循环统计开始时间（重置后重新开始统计）
            self._cycle_start_time = datetime.now()
            self._cycle_timestamps.clear()  # 🆕 清空循环时间戳
            self._last_apr_update_time = None  # 重置更新时间，下次立即计算
            # 🔥 清空APR缓存
            self._last_apr_estimate = Decimal('0')
            self._last_realtime_apr_estimate = Decimal('0')  # 🆕 清空实时APR缓存
            self._last_apr_formula_data = {}
            self._last_cycle_profit_pct = Decimal('0')
            self.logger.info(
                f"📊 循环统计已重置，新的开始时间: {self._cycle_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # 重新初始化网格层级（保持原有价格区间）
            self.state.initialize_grid_levels(
                self.config.grid_count,
                self.config.get_grid_price
            )

            # 生成并挂出新订单（使用原有价格范围）
            self.logger.info(
                f"🚀 重新初始化固定范围网格并挂单: "
                f"${self.config.lower_price:,.2f} - ${self.config.upper_price:,.2f}"
            )
            initial_orders = self.strategy.initialize(self.config)
            self.logger.info(f"📋 生成 {len(initial_orders)} 个初始订单")

            placed_orders = await self.engine.place_batch_orders(initial_orders)
            self.logger.info(f"✅ 成功挂出 {len(placed_orders)} 个订单")

            # 🔥 关键修复：等待WebSocket处理立即成交的订单
            await asyncio.sleep(2)

            # 添加到状态追踪（只添加未成交的订单）
            added_count = 0
            skipped_filled = 0
            skipped_exists = 0

            try:
                # 获取当前实际挂单（从引擎）
                engine_pending_orders = self.engine.get_pending_orders()
                engine_pending_ids = {
                    order.order_id for order in engine_pending_orders}

                for order in placed_orders:
                    if order.order_id in self.state.active_orders:
                        skipped_exists += 1
                        continue
                    # 🔥 关键：检查订单是否真的还在挂单中
                    if order.order_id not in engine_pending_ids:
                        self.logger.debug(f"订单 {order.order_id} 已成交或取消，跳过添加")
                        skipped_filled += 1
                        continue
                    self.state.add_order(order)
                    added_count += 1
            except Exception as e:
                self.logger.warning(f"⚠️ 无法从引擎获取挂单列表，使用订单状态判断: {e}")
                # Fallback：使用订单自身的状态
                for order in placed_orders:
                    if order.order_id in self.state.active_orders:
                        skipped_exists += 1
                        continue
                    if order.status == GridOrderStatus.FILLED:
                        self.logger.debug(f"订单 {order.order_id} 立即成交，跳过添加")
                        skipped_filled += 1
                        continue
                    self.state.add_order(order)
                    added_count += 1

            buy_count = len(
                [o for o in self.state.active_orders.values() if o.side == GridOrderSide.BUY])
            sell_count = len(
                [o for o in self.state.active_orders.values() if o.side == GridOrderSide.SELL])
            self.logger.info(
                f"📊 订单添加详情: "
                f"新增={added_count}, "
                f"跳过(已成交)={skipped_filled}, "
                f"跳过(已存在)={skipped_exists}"
            )
            self.logger.info(
                f"📊 状态统计: "
                f"买单={buy_count}, "
                f"卖单={sell_count}, "
                f"活跃订单={len(self.state.active_orders)}"
            )

            # 🔥 重新初始化本金（止盈后）
            if new_capital is not None:
                if self.capital_protection_manager:
                    self.capital_protection_manager.initialize_capital(
                        new_capital, is_reinit=True)
                if self.take_profit_manager:
                    self.take_profit_manager.initialize_capital(
                        new_capital, is_reinit=True)
                if self.scalping_manager:
                    self.scalping_manager.initialize_capital(
                        new_capital, is_reinit=True)
                self.logger.info(f"💰 本金已重新初始化: ${new_capital:,.3f}")

            self.logger.info("✅ 固定范围网格重置完成，继续运行")

        except Exception as e:
            self.logger.error(f"❌ 固定范围网格重置失败: {e}")
            raise

    def _is_spot_mode(self) -> bool:
        """判断是否是现货模式"""
        try:
            from ....adapters.exchanges.interface import ExchangeType
            if hasattr(self.engine, 'exchange') and hasattr(self.engine.exchange, 'config'):
                return self.engine.exchange.config.exchange_type == ExchangeType.SPOT
        except Exception as e:
            self.logger.debug(f"判断现货模式失败: {e}")
        return False

    def _get_reserve_amount(self) -> Decimal:
        """
        获取预留数量（仅现货模式）

        Returns:
            预留BTC数量，如果不是现货模式或没有预留管理器则返回0
        """
        if not self._is_spot_mode():
            return Decimal('0')

        try:
            if self.reserve_manager:
                return self.reserve_manager.reserve_amount
        except Exception as e:
            self.logger.debug(f"获取预留数量失败: {e}")

        return Decimal('0')

    async def _place_take_profit_order(self):
        """
        挂止盈订单

        🔥 重要：止盈订单会频繁取消重新挂出（每次持仓变化时）
        - 每次挂单后必须立即同步 order_index（仅 Lighter）
        - 确保快速成交时能正确识别止盈订单
        """
        if not self.scalping_manager or not self.scalping_manager.is_active():
            return

        # 获取当前价格
        current_price = await self.engine.get_current_price()

        # 计算止盈订单
        # 🔥 现货模式：传入预留BTC数量，用于对称计算回本价格
        reserve_amount = self._get_reserve_amount() if self._is_spot_mode() else None
        tp_order = self.scalping_manager.calculate_take_profit_order(
            current_price, reserve_amount=reserve_amount)

        if not tp_order:
            self.logger.warning("⚠️ 无法计算止盈订单（可能原因：初始本金未设置或无持仓）")
            return

        try:
            # 下止盈订单
            placed_order = await self.engine.place_order(tp_order, source="止盈单")
            self.state.add_order(placed_order)

            self.logger.info(
                f"💰 止盈订单已挂: {placed_order.side.value} "
                f"{placed_order.amount}@{placed_order.price} "
                f"(Grid {placed_order.grid_id})"
            )
        except Exception as e:
            self.logger.error(f"❌ 挂止盈订单失败: {e}")

    def _is_take_profit_order_filled(self, filled_order: GridOrder) -> bool:
        """判断是否是止盈订单成交"""
        if not self.scalping_manager or not self.scalping_manager.is_active():
            return False

        tp_order = self.scalping_manager.get_current_take_profit_order()
        if not tp_order:
            return False

        return filled_order.order_id == tp_order.order_id

    def _should_place_reverse_order_in_scalping(self, filled_order: GridOrder) -> bool:
        """
        判断在剥头皮模式下是否应该挂反向订单

        ⚠️ 剥头皮模式下不挂任何反向订单

        核心原则：
        - 剥头皮模式只保留被动成交订单（已有的挂单）
        - 除了止盈订单（由scalping_ops单独管理），不主动挂任何新订单
        - 订单成交后只更新止盈订单，不补新单

        工作流程：
        1. 做多网格：价格下跌，买单成交 → 只更新止盈订单，不补买单
        2. 做多网格：价格上涨，止盈订单成交 → 退出剥头皮，重置网格
        3. 任何其他订单成交 → 更新止盈订单，不挂反向订单

        Args:
            filled_order: 已成交订单

        Returns:
            False - 剥头皮模式下禁止所有反向订单
        """
        return False  # 🔥 剥头皮模式下禁止所有反向订单

    def _sync_orders_from_engine(self):
        """
        🔥 新方案：从 client_id 缓存同步订单统计到 state

        使用 _pending_orders_by_client_id 缓存作为统计来源，更准确可靠：
        1. 只统计有 client_id 的订单（我们主动挂的，排除历史订单）
        2. 与 WebSocket 推送同步，实时删除已成交订单
        3. 健康检查会同步这个缓存，确保与交易所一致

        原方案的问题：
        - get_pending_orders() 从 _pending_orders 统计
        - _pending_orders 可能包含已成交但未删除的订单
        - 导致 UI 显示的数量与交易所不一致
        """
        try:
            # 🔥 新方案：直接从 client_id 缓存统计
            client_id_cache = self.engine._pending_orders_by_client_id

            # 统计买单和卖单数量
            buy_count = sum(
                1 for order in client_id_cache.values()
                if order.side == GridOrderSide.BUY
            )
            sell_count = sum(
                1 for order in client_id_cache.values()
                if order.side == GridOrderSide.SELL
            )

            # 更新state的统计数据
            self.state.pending_buy_orders = buy_count
            self.state.pending_sell_orders = sell_count

            # 🔥 DEBUG 日志，仅在调试时使用（避免频繁打印）
            self.logger.debug(
                f"📊 UI订单同步: 从 client_id 缓存同步到State - "
                f"买单={buy_count}个, 卖单={sell_count}个, "
                f"缓存总数={len(client_id_cache)}个"
            )

            # 🔥 同步 state.active_orders（使用 client_id 缓存）
            # 确保 state.active_orders 包含所有 client_id 缓存中的订单
            cache_order_ids = {
                order.order_id for order in client_id_cache.values()}
            state_order_ids = set(self.state.active_orders.keys())

            # 1. 移除 state 中已不存在于缓存的订单
            removed_orders = state_order_ids - cache_order_ids
            for order_id in removed_orders:
                if order_id in self.state.active_orders:
                    del self.state.active_orders[order_id]

            # 2. 添加缓存中存在但 state 中没有的订单（健康检查新增的）
            added_orders = cache_order_ids - state_order_ids
            for order in client_id_cache.values():
                if order.order_id in added_orders:
                    # 添加到 state.active_orders，这样成交时能正确更新统计
                    self.state.active_orders[order.order_id] = order

            # 记录同步信息
            if removed_orders or added_orders:
                self.logger.debug(
                    f"📊 订单同步: State增加{len(added_orders)}个, 移除{len(removed_orders)}个, "
                    f"当前={len(self.state.active_orders)}个"
                )

            # 如果缓存和 state 的订单数量差异较大，记录日志
            state_total = len(self.state.active_orders)
            cache_total = len(client_id_cache)

            if abs(state_total - cache_total) > 5:
                self.logger.warning(
                    f"⚠️ 订单同步后仍有差异: State={state_total}个, client_id缓存={cache_total}个, "
                    f"差异={abs(state_total - cache_total)}个"
                )

        except Exception as e:
            self.logger.debug(f"同步订单统计失败: {e}")

    def _safe_decimal(self, value, default='0') -> Decimal:
        """安全转换为Decimal"""
        try:
            if value is None:
                return Decimal(default)
            return Decimal(str(value))
        except:
            return Decimal(default)

    async def cleanup_on_exit(self) -> bool:
        """
        退出清理：平仓所有持仓并取消所有订单

        用于用户按 Ctrl+C 手动退出时清理现场

        Returns:
            bool: 清理是否成功
        """
        if not self.config.exit_cleanup_enabled:
            self.logger.info("🔸 退出清理已禁用，跳过清理流程")
            print("   🔸 退出清理已禁用，跳过清理流程")
            return True

        self.logger.info("=" * 80)
        self.logger.info("🧹 开始退出清理流程...")
        self.logger.info("=" * 80)
        print("\n" + "=" * 80)
        print("🧹 开始退出清理流程...")
        print("=" * 80)

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                if retry_count > 0:
                    self.logger.info(f"🔄 第 {retry_count + 1} 次清理尝试...")
                    print(f"🔄 第 {retry_count + 1} 次清理尝试...")

                # 步骤1：并行执行平仓和取消订单
                self.logger.info("📍 步骤 1/2: 平仓持仓 + 取消订单（并行执行）...")
                print("📍 步骤 1/2: 平仓持仓 + 取消订单（并行执行）...")

                # 获取当前持仓和订单（注意：get_positions 需要传入列表）
                positions = await self.engine.exchange.get_positions([self.config.symbol])
                orders = await self.engine.exchange.get_open_orders(self.config.symbol)

                position_qty = Decimal('0')
                for pos in positions:
                    # 🔥 PositionData 使用 size 属性存储持仓数量，不是 amount
                    if hasattr(pos, 'size') and pos.size:
                        position_qty = abs(self._safe_decimal(pos.size))
                        break

                self.logger.info(f"   - 当前持仓: {position_qty}")
                self.logger.info(f"   - 当前订单: {len(orders)}个")
                print(f"   - 当前持仓: {position_qty}")
                print(f"   - 当前订单: {len(orders)}个")

                # 并行执行平仓和取消订单
                tasks = []

                # 平仓任务（如果有持仓）
                if position_qty > 0:
                    from ....adapters.exchanges.models import OrderSide

                    # 做多网格平仓用卖单，做空网格平仓用买单
                    side = OrderSide.SELL if self.config.grid_type.value.endswith(
                        'long') else OrderSide.BUY
                    side_str = 'sell' if side == OrderSide.SELL else 'buy'

                    self.logger.info(f"   ✓ 准备平仓: {position_qty} ({side_str})")
                    print(f"   ✓ 准备平仓: {position_qty} ({side_str})")
                    tasks.append(
                        self.engine.exchange.place_market_order(
                            symbol=self.config.symbol,
                            side=side,
                            quantity=position_qty,
                            reduce_only=True
                        )
                    )
                else:
                    self.logger.info("   ✓ 无持仓，跳过平仓")
                    print("   ✓ 无持仓，跳过平仓")

                # 取消订单任务（如果有订单）
                if orders:
                    self.logger.info(f"   ✓ 准备取消订单: {len(orders)}个")
                    print(f"   ✓ 准备取消订单: {len(orders)}个")
                    tasks.append(
                        self.engine.exchange.cancel_all_orders(
                            self.config.symbol)
                    )
                else:
                    self.logger.info("   ✓ 无订单，跳过取消")
                    print("   ✓ 无订单，跳过取消")

                # 执行所有任务
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # 检查结果
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            self.logger.error(f"   ❌ 任务 {i+1} 失败: {result}")
                            print(f"   ❌ 任务 {i+1} 失败: {result}")
                        else:
                            self.logger.info(f"   ✓ 任务 {i+1} 完成")
                            print(f"   ✓ 任务 {i+1} 完成")
                else:
                    self.logger.info("   ✓ 无需执行任何操作")
                    print("   ✓ 无需执行任何操作")

                # 步骤2：等待3秒，然后检查残留
                self.logger.info("📍 步骤 2/2: 等待3秒后验证...")
                print("📍 步骤 2/2: 等待3秒后验证...")
                await asyncio.sleep(3)

                # 重新获取持仓和订单（注意：get_positions 需要传入列表）
                positions_after = await self.engine.exchange.get_positions([self.config.symbol])
                orders_after = await self.engine.exchange.get_open_orders(self.config.symbol)

                position_qty_after = Decimal('0')
                for pos in positions_after:
                    # 🔥 PositionData 使用 size 属性存储持仓数量，不是 amount
                    if hasattr(pos, 'size') and pos.size:
                        position_qty_after = abs(self._safe_decimal(pos.size))
                        break

                self.logger.info(f"   - 验证持仓: {position_qty_after}")
                self.logger.info(f"   - 验证订单: {len(orders_after)}个")
                print(f"   - 验证持仓: {position_qty_after}")
                print(f"   - 验证订单: {len(orders_after)}个")

                # 检查是否完全清理
                if position_qty_after == 0 and len(orders_after) == 0:
                    self.logger.info("=" * 80)
                    self.logger.info("✅ 退出清理完成！持仓和订单已全部清空")
                    self.logger.info("=" * 80)
                    print("=" * 80)
                    print("✅ 退出清理完成！持仓和订单已全部清空")
                    print("=" * 80)
                    return True

                # 还有残留，继续重试
                self.logger.warning(
                    f"⚠️ 发现残留: 持仓={position_qty_after}, 订单={len(orders_after)}个")
                print(
                    f"⚠️ 发现残留: 持仓={position_qty_after}, 订单={len(orders_after)}个")
                retry_count += 1

                if retry_count >= max_retries:
                    self.logger.error("=" * 80)
                    self.logger.error(f"❌ 退出清理失败：已重试 {max_retries} 次，仍有残留")
                    self.logger.error(f"   - 残留持仓: {position_qty_after}")
                    self.logger.error(f"   - 残留订单: {len(orders_after)}个")
                    self.logger.error("=" * 80)
                    print("=" * 80)
                    print(f"❌ 退出清理失败：已重试 {max_retries} 次，仍有残留")
                    print(f"   - 残留持仓: {position_qty_after}")
                    print(f"   - 残留订单: {len(orders_after)}个")
                    print("=" * 80)
                    return False

            except Exception as e:
                self.logger.error(f"❌ 清理过程出错: {e}")
                print(f"❌ 清理过程出错: {e}")
                retry_count += 1

                if retry_count >= max_retries:
                    self.logger.error("=" * 80)
                    self.logger.error(f"❌ 退出清理失败：重试次数已用尽")
                    self.logger.error("=" * 80)
                    print("=" * 80)
                    print(f"❌ 退出清理失败：重试次数已用尽")
                    print("=" * 80)
                    return False

                await asyncio.sleep(2)

        return False
