"""
订单健康检查器

职责：
1. 检测并清理重复订单
2. 检测并清理超出范围的订单
3. 评估网格覆盖情况
4. 根据安全规则决定是否补单
"""

import asyncio
from typing import List, Tuple, Set, Dict, Optional
from decimal import Decimal
from datetime import datetime
from collections import defaultdict

from ....logging import get_logger
from ....adapters.exchanges import OrderSide as ExchangeOrderSide, PositionSide, OrderType, MarginMode
from ....adapters.exchanges.models import PositionData
from ..models import GridConfig, GridOrder, GridOrderSide, GridOrderStatus, GridType


class OrderHealthChecker:
    """订单健康检查器"""

    def __init__(self, config: GridConfig, engine, reserve_manager=None):
        """
        初始化健康检查器

        Args:
            config: 网格配置
            engine: 网格引擎实例（用于访问交易所和下单功能）
            reserve_manager: 现货预留管理器（可选，仅现货）
        """
        self.config = config
        self.engine = engine
        self.reserve_manager = reserve_manager  # 🔥 保存预留管理器引用
        self.logger = get_logger(__name__)

        # 🔥 配置健康检查日志：只输出到文件，不显示在终端UI
        import logging
        from logging.handlers import RotatingFileHandler

        # 🔥 关键修复：直接操作底层的 logging.Logger，确保级别设置生效
        # BaseLogger 的 logger 属性是标准的 logging.Logger 对象
        underlying_logger = self.logger.logger

        # 设置 logger 级别为 DEBUG（必须，否则 debug 日志会被过滤）
        underlying_logger.setLevel(logging.DEBUG)

        # 移除控制台处理器（保留文件处理器）
        handlers_to_remove = []
        for handler in list(underlying_logger.handlers):  # 使用 list() 避免迭代时修改
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handlers_to_remove.append(handler)

        for handler in handlers_to_remove:
            underlying_logger.removeHandler(handler)

        # 确保有文件处理器且级别为 DEBUG
        has_file_handler = False
        for handler in underlying_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                has_file_handler = True
                handler.setLevel(logging.DEBUG)  # 🔥 确保文件处理器级别是 DEBUG

        if not has_file_handler:
            # 如果没有文件处理器，添加一个
            log_file = f"logs/{__name__}.log"
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,  # 5MB (与 logging.yaml 保持一致)
                backupCount=3,  # 3个备份
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            underlying_logger.addHandler(file_handler)

        # 🔥 最终验证和强制设置：确保 logger 级别和所有文件处理器级别都是 DEBUG
        underlying_logger.setLevel(logging.DEBUG)

        # 🔥 关键修复：禁用日志传播，避免父logger影响
        underlying_logger.propagate = False

        for handler in underlying_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(logging.DEBUG)

        # 🔥 测试日志输出（验证配置是否生效）
        underlying_logger.debug("=" * 80)
        underlying_logger.debug(
            "✅ 健康检查器日志配置完成：logger级别=DEBUG，文件处理器级别=DEBUG，propagate=False")
        underlying_logger.debug("=" * 80)

        # 🆕 异步锁：防止多次并发执行健康检查
        self._health_check_lock = asyncio.Lock()
        self._last_trigger_time = 0  # 上次触发时间
        self._trigger_interval = 5  # 触发间隔（秒），防止频繁触发

        self.logger.debug(
            f"订单健康检查器初始化: 网格数={config.grid_count}, "
            f"反手距离={config.reverse_order_grid_distance}格"
        )

    async def _fetch_orders_and_positions(self) -> Tuple[List, List[PositionData]]:
        """
        获取订单和持仓数据（纯REST API）

        🔥 重大修改：持仓数据也使用REST API，不再依赖WebSocket缓存
        原因：Backpack WebSocket持仓流不推送订单成交导致的变化

        修改内容：
        - 订单：从交易所REST API获取（实时准确）✅
        - 持仓：从交易所REST API获取（不再使用WebSocket缓存）✅

        Returns:
            (订单列表, 持仓列表)
        """
        try:
            # 获取订单（使用REST API）
            orders = await self.engine.exchange.get_open_orders(self.config.symbol)

            # 🔥 获取持仓（区分现货和合约）
            try:
                if self._is_spot_mode():
                    # 🔥 现货模式：通过余额查询
                    positions = await self._query_spot_position()
                    self.logger.debug("📊 健康检查(现货): 使用余额查询持仓")
                else:
                    # 🔥 合约模式：通过持仓查询
                    positions = await self.engine.exchange.get_positions([self.config.symbol])
                    self.logger.debug("📊 健康检查(合约): 使用持仓查询")

                if positions:
                    self.logger.debug(
                        f"📊 健康检查使用REST API持仓数据: "
                        f"方向={positions[0].side.value}, 数量={positions[0].size}, "
                        f"成本={positions[0].entry_price}"
                    )
                else:
                    self.logger.debug("📊 健康检查: REST API显示无持仓")

            except Exception as rest_error:
                self.logger.error(f"❌ REST API获取持仓失败: {rest_error}")
                import traceback
                self.logger.error(traceback.format_exc())
                positions = []

            return orders, positions

        except Exception as e:
            self.logger.error(f"获取订单和持仓失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return [], []

    def _calculate_expected_position(self, total_grids: int, current_buy_orders: int, current_sell_orders: int) -> Decimal:
        """
        根据订单状态计算预期持仓数量

        逻辑：
        - 普通网格：预期持仓 = 成交数量 × 单格金额
        - 马丁网格：逐个格式化累加（模拟交易所的精度处理）

        🔥 关键改进：马丁网格不再使用等差数列公式
        原因：交易所会对每个订单金额进行精度格式化（四舍五入），
        破坏了等差性质，必须逐个格式化后累加才能得到准确的预期持仓。

        Args:
            total_grids: 总网格数量
            current_buy_orders: 当前买单数量
            current_sell_orders: 当前卖单数量

        Returns:
            预期持仓数量（正数=多头，负数=空头）
        """
        from decimal import ROUND_HALF_UP

        # 计算已成交的订单数量
        if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
            # 做多网格：原本应该有total_grids个买单，现在有current_buy_orders个
            # 说明成交了 (total_grids - current_buy_orders) 个买单
            filled_buy_count = total_grids - current_buy_orders

            # 判断是否为马丁网格
            if self.config.martingale_increment and self.config.martingale_increment > 0:
                # 马丁网格：逐个格式化后累加（模拟交易所处理）
                # 假设从高价往低价连续成交（Grid N → Grid N-M+1）
                expected_position = Decimal('0')
                precision_quantizer = Decimal(
                    '0.1') ** self.config.quantity_precision

                # 计算哪些Grid已成交（从高价格ID开始）
                start_grid_id = self.config.grid_count - filled_buy_count + 1

                for grid_id in range(start_grid_id, self.config.grid_count + 1):
                    # 获取该网格的理论金额
                    raw_amount = self.config.get_grid_order_amount(grid_id)
                    # 🔥 关键：应用交易所的精度格式化（四舍五入）
                    formatted_amount = raw_amount.quantize(
                        precision_quantizer, rounding=ROUND_HALF_UP)
                    expected_position += formatted_amount

                self.logger.debug(
                    f"📊 马丁做多网格预期持仓计算: "
                    f"成交{filled_buy_count}个 (Grid {start_grid_id}-{self.config.grid_count}), "
                    f"精度={self.config.quantity_precision}位小数, "
                    f"总计={expected_position}"
                )
            else:
                # 普通网格：固定金额
                expected_position = Decimal(
                    str(filled_buy_count)) * self.config.order_amount

        elif self.config.grid_type in [GridType.SHORT, GridType.FOLLOW_SHORT, GridType.MARTINGALE_SHORT]:
            # 做空网格：原本应该有total_grids个卖单，现在有current_sell_orders个
            # 说明成交了 (total_grids - current_sell_orders) 个卖单
            filled_sell_count = total_grids - current_sell_orders

            # 判断是否为马丁网格
            if self.config.martingale_increment and self.config.martingale_increment > 0:
                # 马丁网格：逐个格式化后累加（模拟交易所处理）
                # 假设从低价往高价连续成交（Grid 1 → Grid M）
                expected_position = Decimal('0')
                precision_quantizer = Decimal(
                    '0.1') ** self.config.quantity_precision

                for grid_id in range(1, filled_sell_count + 1):
                    # 获取该网格的理论金额
                    raw_amount = self.config.get_grid_order_amount(grid_id)
                    # 🔥 关键：应用交易所的精度格式化（四舍五入）
                    formatted_amount = raw_amount.quantize(
                        precision_quantizer, rounding=ROUND_HALF_UP)
                    expected_position += formatted_amount

                # 做空网格持仓为负数
                expected_position = -expected_position

                self.logger.debug(
                    f"📊 马丁做空网格预期持仓计算: "
                    f"成交{filled_sell_count}个 (Grid 1-{filled_sell_count}), "
                    f"精度={self.config.quantity_precision}位小数, "
                    f"总计={expected_position}"
                )
            else:
                # 普通网格：固定金额（负数）
                expected_position = - \
                    Decimal(str(filled_sell_count)) * self.config.order_amount

        else:
            self.logger.debug(f"未知的网格类型: {self.config.grid_type}")
            expected_position = Decimal('0')

        return expected_position

    def _check_position_health(
        self,
        expected_position: Decimal,
        actual_positions: List[PositionData]
    ) -> Dict[str, any]:
        """
        检查持仓健康状态

        Args:
            expected_position: 预期持仓数量（正数=多头，负数=空头）
            actual_positions: 实际持仓列表

        Returns:
            健康检查结果字典
        """
        result = {
            'is_healthy': True,
            'issues': [],
            'expected_position': expected_position,
            'actual_position': Decimal('0'),
            'position_side': None,
            'expected_side': None,
            'needs_adjustment': False,
            'adjustment_amount': Decimal('0'),
            # 'open_long', 'open_short', 'close_long', 'close_short', 'reverse'
            'adjustment_action': None
        }

        # 确定预期方向
        if expected_position > 0:
            result['expected_side'] = PositionSide.LONG
        elif expected_position < 0:
            result['expected_side'] = PositionSide.SHORT
        else:
            result['expected_side'] = None  # 无持仓

        # 查找当前交易对的持仓
        position = None
        for pos in actual_positions:
            if pos.symbol == self.config.symbol:
                position = pos
                break

        # 获取实际持仓
        if position:
            # 检查持仓数量是否有效
            if position.size is None or position.size == 0:
                # 🔥 持仓数量为None或0时，都视为无持仓
                # 防止"幽灵持仓"（size=0但有side的情况）
                if position.size == 0:
                    self.logger.debug(
                        f"⚠️ 检测到0持仓但有方向({position.side})，视为无持仓")
                else:
                    self.logger.debug(f"⚠️ 持仓数量为None，视为无持仓")
                result['actual_position'] = Decimal('0')
                result['position_side'] = None
            else:
                # 根据方向确定持仓数量的正负号
                if position.side == PositionSide.LONG:
                    result['actual_position'] = position.size
                    result['position_side'] = PositionSide.LONG
                elif position.side == PositionSide.SHORT:
                    result['actual_position'] = -position.size  # 空头用负数表示
                    result['position_side'] = PositionSide.SHORT
        else:
            result['actual_position'] = Decimal('0')
            result['position_side'] = None

        # 🔥 获取容差配置（所有情况都使用统一的容错）
        position_tolerance_config = getattr(
            self.config, 'position_tolerance', {})
        tolerance_multiplier = position_tolerance_config.get(
            'tolerance_multiplier', 1.0) if isinstance(position_tolerance_config, dict) else 1.0
        tolerance = self.config.order_amount * \
            Decimal(str(tolerance_multiplier))

        # 检查持仓方向
        if result['expected_side'] != result['position_side']:
            if result['expected_side'] is None:
                # 预期无持仓，但实际有持仓
                # 🔥 应用容错：只有当实际持仓 > 容错阈值时才判定为异常
                actual_position_abs = abs(result['actual_position'])

                self.logger.debug(
                    f"🔍 持仓容错检查（预期无持仓）: 预期=0, "
                    f"实际={result['actual_position']}, "
                    f"差异={actual_position_abs}, 容错={tolerance}"
                )

                if actual_position_abs >= tolerance:
                    # 实际持仓达到或超过容错范围，判定为异常
                    result['is_healthy'] = False
                    result['needs_adjustment'] = True
                    result['issues'].append('存在多余持仓需要平仓')
                    if result['position_side'] == PositionSide.LONG:
                        result['adjustment_action'] = 'close_long'
                        result['adjustment_amount'] = result['actual_position']
                    else:
                        result['adjustment_action'] = 'close_short'
                        result['adjustment_amount'] = abs(
                            result['actual_position'])

                    self.logger.debug(
                        f"❌ 持仓异常（超出容错范围）: 差异={actual_position_abs} >= 容错={tolerance}"
                    )
                else:
                    # 差异严格小于容错，视为健康
                    self.logger.debug(
                        f"✅ 持仓检查通过（在容错范围内）: "
                        f"差异={actual_position_abs} < 容错={tolerance}"
                    )

            elif result['position_side'] is None:
                # 预期有持仓，但实际无持仓
                # 🔥 应用容错：只有当预期持仓 > 容错阈值时才判定为异常
                expected_position_abs = abs(expected_position)

                self.logger.debug(
                    f"🔍 持仓容错检查（预期有持仓）: 预期={expected_position}, "
                    f"实际=0, 差异={expected_position_abs}, 容错={tolerance}"
                )

                if expected_position_abs >= tolerance:
                    # 预期持仓达到或超过容错范围，判定为异常
                    result['is_healthy'] = False
                    result['needs_adjustment'] = True
                    result['issues'].append('缺少持仓需要开仓')
                    if result['expected_side'] == PositionSide.LONG:
                        result['adjustment_action'] = 'open_long'
                        result['adjustment_amount'] = expected_position
                    else:
                        result['adjustment_action'] = 'open_short'
                        result['adjustment_amount'] = abs(expected_position)

                    self.logger.debug(
                        f"❌ 持仓异常（超出容错范围）: 差异={expected_position_abs} >= 容错={tolerance}"
                    )
                else:
                    # 差异严格小于容错，视为健康
                    self.logger.debug(
                        f"✅ 持仓检查通过（在容错范围内）: "
                        f"差异={expected_position_abs} < 容错={tolerance}"
                    )

            else:
                # 持仓方向相反
                result['is_healthy'] = False
                result['needs_adjustment'] = True
                result['issues'].append('持仓方向错误需要反向')
                result['adjustment_action'] = 'reverse'
                if result['expected_side'] == PositionSide.LONG:
                    # 当前是空头，需要先平空，再开多
                    result['adjustment_amount'] = expected_position
                else:
                    # 当前是多头，需要先平多，再开空
                    result['adjustment_amount'] = abs(expected_position)

        # 检查持仓数量（只有方向正确时才检查数量）
        elif result['expected_side'] is not None:
            # 🔥 现货模式：actual_position 已经在 _query_spot_position() 中减去了预留
            # 所以这里不需要再减去预留，直接使用即可
            actual_position_for_check = result['actual_position']

            position_diff = abs(actual_position_for_check - expected_position)

            self.logger.debug(
                f"🔍 持仓容错检查（方向正确）: 预期={expected_position}, "
                f"实际={actual_position_for_check}, "
                f"差异={position_diff}, 容错={tolerance}"
            )

            if position_diff >= tolerance:
                result['is_healthy'] = False
                result['needs_adjustment'] = True
                result['issues'].append(
                    f'持仓数量不匹配（差异: {position_diff}, 容错: {tolerance}）'
                )

                if actual_position_for_check > expected_position:
                    # 持仓过多，需要平仓
                    result['adjustment_amount'] = position_diff
                    if result['expected_side'] == PositionSide.LONG:
                        result['adjustment_action'] = 'close_long'
                    else:
                        result['adjustment_action'] = 'close_short'
                else:
                    # 持仓不足，需要开仓
                    result['adjustment_amount'] = position_diff
                    if result['expected_side'] == PositionSide.LONG:
                        result['adjustment_action'] = 'open_long'
                    else:
                        result['adjustment_action'] = 'open_short'
            else:
                # 🔥 差异严格小于容错，视为健康
                self.logger.debug(
                    f"✅ 持仓检查通过（在容错范围内）: "
                    f"差异={position_diff} < 容错={tolerance}"
                )

        return result

    async def _adjust_position(self, adjustment_info: Dict) -> bool:
        """
        调整持仓到预期状态

        Args:
            adjustment_info: 调整信息字典

        Returns:
            是否调整成功
        """
        try:
            action = adjustment_info['adjustment_action']
            amount = adjustment_info['adjustment_amount']

            if action is None or amount == 0:
                self.logger.debug("无需调整持仓")
                return True

            self.logger.debug(f"开始持仓调整: 动作={action}, 数量={amount}")

            # 获取当前价格（用于市价单）
            current_price = await self.engine.get_current_price()

            if action == 'reverse':
                # 反向持仓：先平仓，再开仓
                self.logger.debug("⚠️ 检测到持仓方向错误，需要反向调整")

                # 🔥 检查实际持仓是否为0（幽灵持仓）
                actual_position_abs = abs(adjustment_info['actual_position'])
                if actual_position_abs == 0:
                    self.logger.debug(
                        "⚠️ 实际持仓为0（可能是幽灵持仓），跳过平仓步骤，直接建仓"
                    )
                else:
                    # 第一步：平掉反向仓位（只有真实持仓才需要平仓）
                    if adjustment_info['position_side'] == PositionSide.LONG:
                        self.logger.debug(
                            f"第1步：平多仓 {adjustment_info['actual_position']}")
                        await self._close_position(
                            PositionSide.LONG,
                            actual_position_abs,
                            current_price
                        )
                    else:
                        self.logger.debug(
                            f"第1步：平空仓 {actual_position_abs}")
                        await self._close_position(
                            PositionSide.SHORT,
                            actual_position_abs,
                            current_price
                        )

                    # 等待平仓生效
                    await asyncio.sleep(1.5)  # 优化：2秒→1.5秒（等待平仓生效）

                # 第二步：开正确方向的仓位
                if adjustment_info['expected_side'] == PositionSide.LONG:
                    self.logger.debug(f"第2步：开多仓 {amount}")
                    await self._open_position(PositionSide.LONG, amount, current_price)
                else:
                    self.logger.debug(f"第2步：开空仓 {amount}")
                    await self._open_position(PositionSide.SHORT, amount, current_price)

            elif action == 'close_long':
                # 平多仓
                self.logger.debug(f"平多仓: {amount}")
                await self._close_position(PositionSide.LONG, amount, current_price)

            elif action == 'close_short':
                # 平空仓
                self.logger.debug(f"平空仓: {amount}")
                await self._close_position(PositionSide.SHORT, amount, current_price)

            elif action == 'open_long':
                # 开多仓
                self.logger.debug(f"开多仓: {amount}")
                await self._open_position(PositionSide.LONG, amount, current_price)

            elif action == 'open_short':
                # 开空仓
                self.logger.debug(f"开空仓: {amount}")
                await self._open_position(PositionSide.SHORT, amount, current_price)

            self.logger.debug("✅ 持仓调整完成")
            return True

        except Exception as e:
            self.logger.error(f"❌ 持仓调整失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    async def _close_position(self, side: PositionSide, amount: Decimal, current_price: Decimal):
        """
        平仓（使用市价单）

        Args:
            side: 持仓方向（要平的仓位）
            amount: 平仓数量
            current_price: 当前价格（仅用于日志记录）
        """
        try:
            # 平多仓 = 卖出，平空仓 = 买入
            if side == PositionSide.LONG:
                order_side = ExchangeOrderSide.SELL
            else:
                order_side = ExchangeOrderSide.BUY

            # 使用市价单平仓，确保成交
            self.logger.debug(
                f"使用市价单平仓: {order_side.value} {amount} (参考价格: {current_price})")

            # 🔥 多交易所兼容处理
            # Lighter: 必须使用 place_market_order + reduce_only=True
            # 其他交易所: 使用 create_order
            if hasattr(self.engine.exchange, 'place_market_order'):
                # Lighter 交易所：使用专用方法确保正确平仓
                self.logger.debug("使用 Lighter 专用平仓方法（reduce_only=True）")
                order = await self.engine.exchange.place_market_order(
                    symbol=self.config.symbol,
                    side=order_side,
                    quantity=amount,
                    reduce_only=True  # 🔥 Lighter必需：只减仓模式
                )
            else:
                # Backpack/Hyperliquid: 使用通用方法
                self.logger.debug("使用通用平仓方法（create_order）")
                order = await self.engine.exchange.create_order(
                    symbol=self.config.symbol,
                    side=order_side,
                    order_type=OrderType.MARKET,
                    amount=amount,
                    price=current_price  # Hyperliquid需要价格计算滑点
                )

            if order is None:
                raise Exception(
                    f"平仓失败: 交易所返回None ({order_side.value} {amount})")

            self.logger.debug(
                f"✅ 平仓市价单已提交: {order_side.value} {amount}, OrderID={order.id}")

        except Exception as e:
            self.logger.error(f"❌ 平仓失败: {e}")
            raise

    async def _open_position(self, side: PositionSide, amount: Decimal, current_price: Decimal):
        """
        开仓（使用市价单）

        Args:
            side: 持仓方向（要开的仓位）
            amount: 开仓数量
            current_price: 当前价格（仅用于日志记录）
        """
        try:
            # 开多仓 = 买入，开空仓 = 卖出
            if side == PositionSide.LONG:
                order_side = ExchangeOrderSide.BUY
            else:
                order_side = ExchangeOrderSide.SELL

            # 使用市价单开仓，确保成交
            self.logger.debug(
                f"使用市价单开仓: {order_side.value} {amount} (参考价格: {current_price})")

            # 🔥 多交易所兼容处理
            # Lighter: 使用 place_market_order + reduce_only=False
            # 其他交易所: 使用 create_order
            if hasattr(self.engine.exchange, 'place_market_order'):
                # Lighter 交易所：使用专用方法
                self.logger.debug("使用 Lighter 专用开仓方法（reduce_only=False）")
                order = await self.engine.exchange.place_market_order(
                    symbol=self.config.symbol,
                    side=order_side,
                    quantity=amount,
                    reduce_only=False  # 🔥 Lighter：允许开仓
                )
            else:
                # Backpack/Hyperliquid: 使用通用方法
                self.logger.debug("使用通用开仓方法（create_order）")
                order = await self.engine.exchange.create_order(
                    symbol=self.config.symbol,
                    side=order_side,
                    order_type=OrderType.MARKET,
                    amount=amount,
                    price=current_price,  # Hyperliquid需要价格计算滑点
                    params={}
                )

            if order is None:
                raise Exception(
                    f"开仓失败: 交易所返回None ({order_side.value} {amount})")

            self.logger.debug(
                f"✅ 开仓市价单已提交: {order_side.value} {amount}, OrderID={order.id}")

        except Exception as e:
            self.logger.error(f"❌ 开仓失败: {e}")
            raise

    async def perform_health_check(
        self,
        snapshot_orders: Optional[List] = None,
        snapshot_positions: Optional[List] = None
    ):
        """
        执行订单健康检查（含持仓检查）

        Args:
            snapshot_orders: 🚀 可选的快照订单数据（避免重复API调用）
            snapshot_positions: 🚀 可选的快照持仓数据（避免重复API调用）

        流程：
        1. 使用快照数据或并发获取订单和持仓数据
        2. 检查订单数量和持仓状态
        3. 如有异常，进行二次检查（订单+持仓）
        4. 确认问题后执行修复（持仓优先，然后订单）
        5. 安全检查和补单决策
        """
        # 🆕 使用锁防止并发执行
        if self._health_check_lock.locked():
            self.logger.info("⏸️ 健康检查已在执行中，跳过本次触发")
            return

        async with self._health_check_lock:
            return await self._perform_health_check_internal(
                snapshot_orders=snapshot_orders,
                snapshot_positions=snapshot_positions
            )

    async def trigger_health_check_now(self):
        """
        立即触发健康检查（带去重和锁保护）

        用于异常成交后立即补单。
        带有时间间隔去重，避免短时间内频繁触发。
        """
        import time

        current_time = time.time()
        time_since_last = current_time - self._last_trigger_time

        if time_since_last < self._trigger_interval:
            self.logger.debug(
                f"⏸️ 距离上次触发仅 {time_since_last:.1f}秒，"
                f"小于间隔 {self._trigger_interval}秒，跳过本次触发"
            )
            return

        self.logger.info("⚡ 立即触发健康检查（异常成交后补单）")
        self._last_trigger_time = current_time
        await self.perform_health_check()

    async def _perform_health_check_internal(
        self,
        snapshot_orders: Optional[List] = None,
        snapshot_positions: Optional[List] = None
    ):
        """
        健康检查的内部实现（带锁保护）

        Args:
            snapshot_orders: 🚀 可选的快照订单数据
            snapshot_positions: 🚀 可选的快照持仓数据
        """
        try:
            # 🔥 强制重新设置日志级别（确保DEBUG日志能输出）
            import logging
            underlying_logger = self.logger.logger
            underlying_logger.setLevel(logging.DEBUG)
            for handler in underlying_logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.setLevel(logging.DEBUG)

            # 🔥 直接测试 underlying_logger（绕过 BaseLogger 的包装）
            underlying_logger.debug("=" * 80)
            underlying_logger.debug("🔍 [直接测试] 开始执行订单和持仓健康检查")
            underlying_logger.debug("=" * 80)

            # 🔥 强制刷新所有处理器
            for handler in underlying_logger.handlers:
                handler.flush()

            # 🔥 确保日志能够写入（测试日志功能）
            self.logger.debug("=" * 80)
            self.logger.debug("🔍 开始执行订单和持仓健康检查")
            self.logger.debug("=" * 80)
            self.logger.info("📊 健康检查器被调用")
            self.logger.debug("🔍 INFO日志后的DEBUG测试")

            # 再次强制刷新
            for handler in underlying_logger.handlers:
                handler.flush()

            # ==================== 健康检查开始 ====================
            from datetime import datetime
            check_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self.logger.info("")
            self.logger.info("=" * 80)
            self.logger.info(f"🔍 健康检查开始 [{check_time}]")
            self.logger.info("=" * 80)
            self.logger.info("📸 快照验证: ✅ 数据已通过3次快照验证，稳定可靠")

            # ==================== 阶段0: 剥头皮模式检查 ====================
            # 🔥 如果剥头皮模式已激活，只进行诊断报告，不做任何修改操作
            is_scalping_active = False
            if hasattr(self.engine, 'coordinator') and self.engine.coordinator:
                coordinator = self.engine.coordinator
                if coordinator.scalping_manager and coordinator.scalping_manager.is_active():
                    is_scalping_active = True
                    self.logger.info("🔴 剥头皮模式激活: 仅执行诊断，不执行修复操作")

            # ==================== 阶段1: 并发获取订单和持仓数据 ====================
            self.logger.info("")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.logger.info("【阶段1】数据获取")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 🔥 优先使用快照数据（避免重复REST API调用）
            if snapshot_orders is not None and snapshot_positions is not None:
                self.logger.info("  🚀 使用快照数据（无需重复REST API调用）")
                orders = snapshot_orders
                positions = snapshot_positions
            else:
                self.logger.info("  📡 从REST API获取订单和持仓")
                orders, positions = await self._fetch_orders_and_positions()

            first_order_count = len(orders)

            if not orders:
                self.logger.warning("⚠️ 未获取到任何挂单，跳过健康检查")
                return

            # 统计订单类型
            buy_count = sum(1 for o in orders if o.side ==
                            ExchangeOrderSide.BUY)
            sell_count = sum(1 for o in orders if o.side ==
                             ExchangeOrderSide.SELL)

            self.logger.info(
                f"  📡 订单数据: {len(orders)}个 (买单: {buy_count}, 卖单: {sell_count})"
            )
            self.logger.info(
                f"  📍 持仓数据: {positions[0].size if positions else 0} {self.config.symbol.split('-')[0]} "
                f"(方向: {positions[0].side.name if positions else 'NONE'})"
            )

            # ==================== 阶段2: 订单全面诊断 ====================
            self.logger.info("")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.logger.info("【阶段2】订单全面诊断")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # ========== 2.1 订单数量检查 ==========
            self.logger.info("")
            self.logger.info("  ▶ 2.1 订单数量检查")
            order_count_abnormal = first_order_count != self.config.grid_count
            self.logger.info(f"    当前订单: {first_order_count}个")
            self.logger.info(f"    目标订单: {self.config.grid_count}个")
            if order_count_abnormal:
                diff = self.config.grid_count - first_order_count
                self.logger.info(f"    ❌ 结论: 缺少 {diff}个订单")
            else:
                self.logger.info(f"    ✅ 结论: 订单数量正确")
            
            # 🔥 特殊处理：订单数为0的情况（可能是API故障）
            if first_order_count == 0 and buy_count == 0 and sell_count == 0:
                self.logger.critical(
                    f"    🚨 警告: 订单数为0！可能是API故障或严重问题"
                )

            # ========== 2.2 订单质量检查 ==========
            self.logger.info("")
            self.logger.info("  ▶ 2.2 订单质量检查")
            
            # 计算实际范围和理论范围
            actual_range = self._calculate_actual_range_from_orders(orders)
            theoretical_range = self._determine_extended_range(orders)
            
            # 显示范围信息
            self.logger.info(f"    网格范围: Grid [{actual_range['min_grid']}, {actual_range['max_grid']}] "
                             f"(价格: [{actual_range['min_price']:.1f}, {actual_range['max_price']:.1f}])")
            self.logger.info(f"    理论范围: Grid [{theoretical_range['min_grid']}, {theoretical_range['max_grid']}] "
                             f"(价格: [{theoretical_range['lower_price']:.2f}, {theoretical_range['upper_price']:.2f}])")
            
            # 诊断问题订单
            problem_orders = self._diagnose_problem_orders(
                orders, actual_range, theoretical_range)
            
            duplicate_count = len(problem_orders['duplicates'])
            out_range_count = len(problem_orders['out_of_range'])
            off_grid_count = len(problem_orders.get('off_grid', []))
            
            self.logger.info(
                f"    {'❌' if duplicate_count > 0 else '✅'} 重复订单: {duplicate_count}个")
            self.logger.info(
                f"    {'❌' if out_range_count > 0 else '✅'} 超范围订单: {out_range_count}个")
            self.logger.info(
                f"    {'❌' if off_grid_count > 0 else '✅'} 偏离网格点: {off_grid_count}个")
            
            # 安全检查
            allow_filling = len(orders) < self.config.grid_count

            # ========== 2.3 网格覆盖评估 ==========
            self.logger.info("")
            self.logger.info("  ▶ 2.3 网格覆盖评估")
            
            covered_grids, missing_grids, profit_gap_grids = await self._evaluate_grid_coverage(
                orders, theoretical_range
            )
            
            self.logger.info(f"    已覆盖网格: {len(covered_grids)}格")
            self.logger.info(
                f"    获利空格: {len(profit_gap_grids)}格 {f'[Grid {min(profit_gap_grids)}-{max(profit_gap_grids)}]' if profit_gap_grids else ''}")
            self.logger.info(
                f"    {'❌ 缺失网格' if missing_grids else '✅ 网格完整'}: {len(missing_grids)}格")
            
            if missing_grids:
                # 显示缺失的网格详情
                for grid_id in missing_grids[:5]:  # 最多显示5个
                    price = self.config.lower_price + \
                        (grid_id - 1) * self.config.grid_step
                    # 判断是买单还是卖单
                    side_str = "BUY" if (profit_gap_grids and grid_id < profit_gap_grids[0]) else "SELL"
                    self.logger.info(f"      - Grid {grid_id} @ ${price:.1f} ({side_str})")
                if len(missing_grids) > 5:
                    self.logger.info(f"      ... 还有 {len(missing_grids) - 5}个缺失网格")
            
            # 显示订单诊断总结
            self.logger.info("")
            has_order_issues = (order_count_abnormal or duplicate_count > 0 or 
                               out_range_count > 0 or off_grid_count > 0 or len(missing_grids) > 0)
            if has_order_issues:
                issues = []
                if order_count_abnormal:
                    issues.append(f"缺{self.config.grid_count - first_order_count}个订单")
                if duplicate_count > 0:
                    issues.append(f"重复{duplicate_count}个")
                if out_range_count > 0:
                    issues.append(f"超范围{out_range_count}个")
                if off_grid_count > 0:
                    issues.append(f"偏离{off_grid_count}个")
                self.logger.info(f"  📝 订单诊断结果: {', '.join(issues)}")
            else:
                self.logger.info(f"  📝 订单诊断结果: 完全正常 ✅")

            # ==================== 阶段3: 持仓验证（基于修复后）====================
            self.logger.info("")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.logger.info("【阶段3】持仓验证（基于修复后）")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 🔥 关键逻辑：持仓检查基于"修复后的目标状态"
            # 计算修复后的预期买卖单数量
            if order_count_abnormal:
                # 订单数量不正确，计算修复后的状态
                if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                    # 做多网格：修复后应该有 grid_count 个买单，已有的卖单保持不变
                    expected_buy_count = self.config.grid_count - sell_count
                    expected_sell_count = sell_count
                else:
                    # 做空网格：修复后应该有 grid_count 个卖单，已有的买单保持不变
                    expected_buy_count = buy_count
                    expected_sell_count = self.config.grid_count - buy_count

                self.logger.info("")
                self.logger.info("  🔥 基于修复后状态计算预期持仓:")
                self.logger.info(f"    当前状态: {buy_count}买 + {sell_count}卖 = {first_order_count}个")
                self.logger.info(f"    修复后: {expected_buy_count}买 + {expected_sell_count}卖 = {self.config.grid_count}个 (补充{self.config.grid_count - first_order_count}个{'买单' if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG] else '卖单'})")
            else:
                # 订单数量正确，基于当前实际买卖单计算
                expected_buy_count = buy_count
                expected_sell_count = sell_count
                
                self.logger.info("")
                self.logger.info("  ✅ 订单数量正确，基于实际订单计算预期持仓:")
                self.logger.info(f"    实际状态: {buy_count}买 + {sell_count}卖 = {self.config.grid_count}个")

            # 计算预期持仓
            expected_position = self._calculate_expected_position(
                self.config.grid_count,
                expected_buy_count,
                expected_sell_count
            )

            # 检查持仓健康状态
            position_health = self._check_position_health(
                expected_position, positions)

            # 计算偏差
            actual_pos = position_health['actual_position']
            position_diff = abs(actual_pos - expected_position)

            self.logger.info("")
            self.logger.info(
                f"  预期持仓: {expected_position} (基于{'修复后' if order_count_abnormal else '实际'}{expected_buy_count}买单)")
            self.logger.info(f"  实际持仓: {actual_pos}")
            self.logger.info(
                f"  偏差: {position_diff} (容错: {position_health.get('tolerance', 'N/A')})")

            # 判断持仓是否异常
            position_abnormal = not position_health['is_healthy']
            
            self.logger.info("")
            if position_abnormal:
                self.logger.info(f"  ❌ 持仓健康: 异常（持仓{'多了' if actual_pos > expected_position else '少了'} {position_diff})")
            else:
                self.logger.info(f"  ✅ 持仓健康: 正常")

            # 剥头皮模式持仓偏差检测
            if is_scalping_active:
                self.logger.debug("🔍 剥头皮模式持仓偏差检测")

                # 计算偏差
                expected_pos = position_health['expected_position']
                actual_pos = position_health['actual_position']

                if expected_pos != 0:
                    position_diff = abs(actual_pos - expected_pos)
                    deviation_percent = float(
                        position_diff / abs(expected_pos) * 100)

                    self.logger.debug(
                        f"📊 持仓偏差分析:\n"
                        f"   预期持仓: {expected_pos}\n"
                        f"   实际持仓: {actual_pos}\n"
                        f"   偏差: {deviation_percent:.1f}%"
                    )

                    # 判断偏差等级（两级：警告10% + 紧急停止50%）
                    warning_threshold = 10   # 警告阈值：10%
                    emergency_threshold = 50  # 紧急停止阈值：50%

                    if deviation_percent >= emergency_threshold:
                        # 紧急级别：触发紧急停止
                        self.logger.critical(
                            f"🚨 剥头皮模式持仓偏差达到紧急阈值！\n"
                            f"   预期持仓: {expected_pos}\n"
                            f"   实际持仓: {actual_pos}\n"
                            f"   偏差: {deviation_percent:.1f}% (紧急阈值: {emergency_threshold}%)\n"
                            f"   ⚠️ 触发紧急停止，停止所有订单操作！\n"
                            f"   需要人工检查和干预！"
                        )

                        # 触发紧急停止
                        coordinator.is_emergency_stopped = True

                        # 不再继续执行后续的修复流程
                        self.logger.critical("🚨 终止健康检查，等待人工干预")
                        return

                    elif deviation_percent >= warning_threshold:
                        # 警告级别：输出警告
                        self.logger.debug(
                            f"⚠️ 剥头皮模式持仓偏差超过警告阈值\n"
                            f"   预期持仓: {expected_pos}\n"
                            f"   实际持仓: {actual_pos}\n"
                            f"   偏差: {deviation_percent:.1f}% (警告阈值: {warning_threshold}%)\n"
                            f"   请关注持仓变化"
                        )

                    else:
                        # 正常级别
                        self.logger.debug(
                            f"✅ 剥头皮模式持仓检查通过，偏差: {deviation_percent:.1f}%"
                        )

                elif actual_pos != 0:
                    # 预期持仓为0，但实际有持仓
                    self.logger.critical(
                        f"🚨 剥头皮模式异常：预期持仓为0，但实际持仓为{actual_pos}！\n"
                        f"   触发紧急停止，需要人工检查！"
                    )
                    coordinator.is_emergency_stopped = True
                    self.logger.critical("🚨 终止健康检查，等待人工干预")
                    return
                else:
                    # 预期和实际都为0
                    self.logger.debug("✅ 剥头皮模式持仓检查通过，预期和实际均为0")

            # ==================== 阶段4: 执行操作 ====================
            self.logger.info("")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.logger.info("【阶段4】执行操作")
            self.logger.info(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # ========== 4.1 订单操作 ==========
            self.logger.info("")
            self.logger.info("  ▶ 4.1 订单操作")
            
            # 判断是否有问题订单需要清理
            has_problem_orders = (duplicate_count > 0 or out_range_count > 0 or off_grid_count > 0)
            if has_problem_orders:
                if is_scalping_active:
                    # 剥头皮模式激活，只报告问题，不清理
                    self.logger.info("    🔴 剥头皮模式激活中，跳过清理问题订单")
                else:
                    # 正常模式，执行清理
                    self.logger.info("    🔧 清理问题订单:")
                    cleaned_count = await self._clean_problem_orders(problem_orders)

                    if cleaned_count > 0:
                        self.logger.info(f"  🧹 已清理: {cleaned_count}个问题订单")
                        await asyncio.sleep(1.5)  # 等待订单取消生效

                        # ==================== 重新获取市场数据 ====================
                        orders = await self.engine.exchange.get_open_orders(self.config.symbol)

                        # 🆕 重新统计订单数量
                        buy_count = sum(
                            1 for o in orders if o.side == ExchangeOrderSide.BUY)
                        sell_count = sum(
                            1 for o in orders if o.side == ExchangeOrderSide.SELL)

                        self.logger.info(
                            f"  📡 清理后剩余: {len(orders)}个 (买单: {buy_count}, 卖单: {sell_count})")

                        # 🆕 重新计算补单许可（关键！）
                        # 如果清理后订单数量少于预期，允许补单
                        allow_filling = len(orders) < self.config.grid_count

                        if allow_filling:
                            self.logger.debug(
                                f"✅ 清理后重新检查: 订单数({len(orders)}) < 网格数({self.config.grid_count}), "
                                f"允许补单"
                            )
                        else:
                            self.logger.debug(
                                f"⚠️ 清理后重新检查: 订单数({len(orders)}) >= 网格数({self.config.grid_count}), "
                                f"禁止补单（可能还有其他问题订单）"
                            )

                        # 🆕 重新计算预期持仓（基于清理后的订单）
                        expected_position = self._calculate_expected_position(
                            self.config.grid_count,
                            buy_count,
                            sell_count
                        )

                        # 🆕 重新检查持仓
                        position_health = self._check_position_health(
                            expected_position, positions)

                        # 🆕 重新计算实际范围和理论范围
                        actual_range = self._calculate_actual_range_from_orders(
                            orders)
                        theoretical_range = self._determine_extended_range(
                            orders)

                        # 重新更新这些变量供后续使用
                        first_order_count = len(orders)
                        # 重新评估网格覆盖
                        covered_grids, missing_grids, profit_gap_grids = await self._evaluate_grid_coverage(
                            orders, theoretical_range
                        )
                        
                        self.logger.debug(
                            f"🔄 已重新计算: 预期持仓={expected_position}, "
                            f"实际持仓={position_health['actual_position']}, "
                            f"持仓健康={position_health['is_healthy']}"
                        )
            else:
                self.logger.info("    ✅ 无问题订单需要清理")

            # 补单操作
            if missing_grids and len(missing_grids) > 0:
                self.logger.info("")
                if is_scalping_active:
                    # 剥头皮模式激活，只报告缺失，不补单
                    self.logger.info(f"    🔴 检测到 {len(missing_grids)}个缺失网格，剥头皮模式跳过补单")
                elif not allow_filling:
                    self.logger.info(f"    ⚠️ 检测到 {len(missing_grids)}个缺失网格，订单数已达上限，禁止补单")
                else:
                    self.logger.info(f"    🔧 补充缺失订单: {len(missing_grids)}个")
                    # 正常补单
                    # 🔥 现货模式特殊处理：先补充持仓，再补充订单
                    # 原因：现货模式下，卖单需要有实际持仓才能挂出
                    if self._is_spot_mode() and position_health['needs_adjustment']:
                        # 检查是否需要开仓（买入）
                        action = position_health['adjustment_action']
                        if action in ['open_long', 'open_short', 'reverse']:
                            self.logger.info(f"  📍 现货模式: 需先调整持仓 ({action})")

                            # 先调整持仓
                            adjustment_success = await self._adjust_position(position_health)

                            if adjustment_success:
                                self.logger.info("  ✅ 持仓调整完成")
                                await asyncio.sleep(1.5)

                                # 重新获取持仓验证
                                _, updated_positions = await self._fetch_orders_and_positions()
                                updated_position_health = self._check_position_health(
                                    expected_position, updated_positions
                                )

                                if not updated_position_health['is_healthy']:
                                    self.logger.warning(
                                        f"  ⚠️ 持仓调整后仍有问题"
                                    )
                            else:
                                self.logger.error("  ❌ 持仓调整失败")

                    # 执行补单
                    await self._fill_missing_grids(missing_grids, theoretical_range)
                    # 显示已补单的网格（最多5个）
                    for grid_id in missing_grids[:5]:
                        price = self.config.lower_price + (grid_id - 1) * self.config.grid_step
                        side_str = "BUY" if (profit_gap_grids and grid_id < profit_gap_grids[0]) else "SELL"
                        self.logger.info(f"      ✅ Grid {grid_id} @ ${price:.1f} ({side_str} 0.002) - 已挂单")
                    if len(missing_grids) > 5:
                        self.logger.info(f"      ... 还有 {len(missing_grids) - 5}个")
            else:
                if not has_order_issues:
                    self.logger.info("    ✅ 订单完整，无需补单")

            # ========== 4.2 持仓操作 ==========
            self.logger.info("")
            self.logger.info("  ▶ 4.2 持仓操作")
            
            # 🔥 关键：持仓调整基于"快照诊断时的结果"（阶段3），无需重新REST API验证
            # 原因：阶段3已经基于"修复后的目标状态"计算预期持仓
            if position_abnormal and not is_scalping_active:
                self.logger.info(f"    🔧 执行持仓调整: {', '.join(position_health['issues'])}")
                self.logger.info(
                    f"      预期: {expected_position}")
                self.logger.info(
                    f"      实际: {actual_pos}")
                self.logger.info(
                    f"      偏差: {position_diff}")
                self.logger.info(
                    f"      操作: {'平多仓' if actual_pos > expected_position else '补多仓'} {position_diff}")
                
                adjustment_success = await self._adjust_position(position_health)

                if adjustment_success:
                    self.logger.info("      ✅ 持仓调整完成")
                else:
                    self.logger.error("      ❌ 持仓调整失败")
            elif position_abnormal and is_scalping_active:
                self.logger.info("    🔴 剥头皮模式激活，跳过持仓调整")
            else:
                self.logger.info("    ✅ 无需调整（持仓正常）")

            # ========== 4.3 缓存同步 ==========
            self.logger.info("")
            self.logger.info("  ▶ 4.3 缓存同步")
            
            # 🔥 规则：只有在"无任何问题"时才同步缓存
            has_any_issues = (
                order_count_abnormal or
                position_abnormal or
                bool(problem_orders['duplicates']) or
                bool(problem_orders['out_of_range']) or
                bool(problem_orders.get('off_grid', [])) or
                bool(missing_grids)
            )

            # 🔥 使用快照的订单数据进行缓存同步（不重新获取）
            await self._sync_orders_to_engine(orders)

            cache_count = len(self.engine._pending_orders_by_client_id)
            market_count = len(orders)  # 🔥 使用快照数据

            self.logger.info(
                f"    📊 缓存差异: 缓存={cache_count}个, 市场={market_count}个, "
                f"差异={abs(cache_count - market_count)}个"
            )

            if cache_count != market_count:
                # 🔥 判断是否可以安全同步缓存（基于快照诊断结果）
                # 只有在"无任何问题"时才同步缓存
                system_stable = not has_any_issues

                if system_stable and not is_scalping_active:
                    self.logger.info("    ✅ 系统稳定，缓存一致，无需同步")
                    # await self._clean_stale_cache()  # 已经通过 _sync_orders_to_engine 同步
                else:
                    if is_scalping_active:
                        self.logger.info("    ⏸️  剥头皮模式激活，跳过缓存同步")
                    elif not system_stable:
                        self.logger.info("    ⏸️  系统不稳定（有操作），跳过缓存同步")
            else:
                self.logger.info("    ✅ 缓存一致，无需同步")

            # ==================== 健康检查完成 ====================
            self.logger.info("")
            self.logger.info("=" * 80)
            self.logger.info("✅ 健康检查完成")
            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error(f"❌ 订单健康检查失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _calculate_actual_range_from_orders(self, orders: List) -> Dict:
        """
        从订单价格反向计算实际网格范围

        遍历所有订单，找出最低价和最高价，
        然后反向计算这些价格对应的网格ID

        Args:
            orders: 订单列表

        Returns:
            实际范围信息字典
        """
        if not orders:
            return {
                'min_price': None,
                'max_price': None,
                'min_grid': None,
                'max_grid': None,
                'price_span': None
            }

        # 找出最低价和最高价
        prices = [order.price for order in orders]
        min_price = min(prices)
        max_price = max(prices)

        # 反向计算网格ID
        if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
            # 做多网格：Grid 1 = lower_price
            min_grid = round(
                (min_price - self.config.lower_price) / self.config.grid_interval
            ) + 1
            max_grid = round(
                (max_price - self.config.lower_price) / self.config.grid_interval
            ) + 1
        else:
            # 做空网格：Grid 1 = upper_price
            min_grid = round(
                (self.config.upper_price - max_price) / self.config.grid_interval
            ) + 1
            max_grid = round(
                (self.config.upper_price - min_price) / self.config.grid_interval
            ) + 1

        result = {
            'min_price': min_price,
            'max_price': max_price,
            'min_grid': min_grid,
            'max_grid': max_grid,
            'price_span': max_price - min_price
        }

        self.logger.debug(
            f"📊 实际订单分布: "
            f"价格范围 [{min_price}, {max_price}], "
            f"网格范围 [Grid {min_grid}, Grid {max_grid}]"
        )

        return result

    def _determine_extended_range(self, orders: List) -> Dict:
        """
        确定扩展范围

        根据订单类型判断是否需要扩展网格范围：
        - 做多网格 + 存在卖单 → 向上扩展
        - 做空网格 + 存在买单 → 向下扩展

        Args:
            orders: 订单列表

        Returns:
            扩展范围信息字典
        """
        # 检查订单类型
        has_buy = any(o.side == ExchangeOrderSide.BUY for o in orders)
        has_sell = any(o.side == ExchangeOrderSide.SELL for o in orders)

        # 基础范围
        result = {
            'lower_price': self.config.lower_price,
            'upper_price': self.config.upper_price,
            'min_grid': 1,
            'max_grid': self.config.grid_count,
            'expected_count': self.config.grid_count,
            'extended': False,
            'direction': None
        }

        # 判断是否需要扩展
        if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
            if has_sell:
                # 做多网格有卖单，向上扩展
                result['extended'] = True
                result['direction'] = 'up'
                result['max_grid'] = self.config.grid_count + \
                    self.config.reverse_order_grid_distance
                result['upper_price'] = self.config.upper_price + (
                    self.config.grid_interval * self.config.reverse_order_grid_distance
                )
                # ⚠️ 重要：预期订单数保持不变（200），因为中间有获利空格
                # 物理范围扩展到202格，但预期订单数仍然是200
                result['expected_count'] = self.config.grid_count

                self.logger.debug(
                    f"🔼 做多网格检测到卖单，向上扩展:"
                )
                self.logger.debug(
                    f"   基础: [{result['lower_price']}, {self.config.upper_price}] "
                    f"(Grid 1-{self.config.grid_count})"
                )
                self.logger.debug(
                    f"   扩展: [{result['lower_price']}, {result['upper_price']}] "
                    f"(Grid 1-{result['max_grid']})"
                )
                self.logger.debug(
                    f"   预期订单数: {result['expected_count']}个 "
                    f"(中间{self.config.reverse_order_grid_distance}格为获利空格)"
                )

        elif self.config.grid_type in [GridType.SHORT, GridType.FOLLOW_SHORT, GridType.MARTINGALE_SHORT]:
            if has_buy:
                # 做空网格有买单，向下扩展
                result['extended'] = True
                result['direction'] = 'down'
                result['max_grid'] = self.config.grid_count + \
                    self.config.reverse_order_grid_distance
                result['lower_price'] = self.config.lower_price - (
                    self.config.grid_interval * self.config.reverse_order_grid_distance
                )
                # ⚠️ 重要：预期订单数保持不变（200），因为中间有获利空格
                # 物理范围扩展到202格，但预期订单数仍然是200
                result['expected_count'] = self.config.grid_count

                self.logger.debug(
                    f"🔽 做空网格检测到买单，向下扩展:"
                )
                self.logger.debug(
                    f"   基础: [{self.config.lower_price}, {result['upper_price']}] "
                    f"(Grid 1-{self.config.grid_count})"
                )
                self.logger.debug(
                    f"   扩展: [{result['lower_price']}, {result['upper_price']}] "
                    f"(Grid 1-{result['max_grid']})"
                )
                self.logger.debug(
                    f"   预期订单数: {result['expected_count']}个 "
                    f"(中间{self.config.reverse_order_grid_distance}格为获利空格)"
                )

        if not result['extended']:
            self.logger.debug(
                f"📏 使用基础范围: [{result['lower_price']}, {result['upper_price']}] "
                f"(Grid 1-{result['max_grid']})"
            )

        return result

    def _compare_ranges(self, actual_range: Dict, theoretical_range: Dict):
        """
        对比实际范围和理论范围，输出差异分析

        Args:
            actual_range: 实际订单覆盖的网格范围
            theoretical_range: 理论扩展范围
        """
        if not actual_range['min_grid'] or not actual_range['max_grid']:
            self.logger.debug("⚠️ 实际范围无效，跳过对比")
            return

        actual_min = actual_range['min_grid']
        actual_max = actual_range['max_grid']
        theory_min = theoretical_range['min_grid']
        theory_max = theoretical_range['max_grid']

        self.logger.debug("=" * 60)
        self.logger.debug("📊 范围对比分析:")
        self.logger.debug(
            f"   实际范围: Grid [{actual_min}, {actual_max}] "
            f"(价格: [{actual_range['min_price']}, {actual_range['max_price']}])"
        )
        self.logger.debug(
            f"   理论范围: Grid [{theory_min}, {theory_max}] "
            f"(价格: [{theoretical_range['lower_price']}, {theoretical_range['upper_price']}])"
        )

        # 分析差异
        issues = []

        if actual_min < theory_min:
            below_count = theory_min - actual_min
            issues.append(f"下限超出: {below_count}格低于理论下限")
            self.logger.debug(
                f"   ⚠️ 订单低于理论下限: Grid {actual_min} < Grid {theory_min} "
                f"(超出{below_count}格)"
            )

        if actual_max > theory_max:
            above_count = actual_max - theory_max
            issues.append(f"上限超出: {above_count}格高于理论上限")
            self.logger.debug(
                f"   ⚠️ 订单高于理论上限: Grid {actual_max} > Grid {theory_max} "
                f"(超出{above_count}格)"
            )

        if not issues:
            self.logger.debug("   ✅ 实际范围在理论范围内，正常")
        else:
            self.logger.debug(
                f"   ❌ 发现{len(issues)}个范围问题: {', '.join(issues)}")

        self.logger.debug("=" * 60)

    def _diagnose_problem_orders(
        self,
        orders: List,
        actual_range: Dict,
        theoretical_range: Dict
    ) -> Dict:
        """
        诊断问题订单（直接分析市场订单）

        🔥 新方案：不对比缓存，直接分析市场订单是否符合预期

        检测：
        1. 重复订单（相同价格的订单）
        2. 超出理论扩展范围的订单
        3. 订单价格不在正确网格点上的订单

        Args:
            orders: 订单列表
            actual_range: 实际订单范围
            theoretical_range: 理论扩展范围

        Returns:
            问题订单字典 {'duplicates': [], 'out_of_range': [], 'off_grid': []}
        """
        problem_orders = {
            'duplicates': [],      # 重复订单
            'out_of_range': [],    # 超出范围订单
            'off_grid': []         # 不在正确网格点的订单
        }

        # 📊 缓存统计（仅供参考，不影响判断）
        cached_count = len(self.engine._pending_orders_by_client_id)
        actual_count = len(orders)
        self.logger.debug(
            f"📊 缓存统计（参考）: client_id缓存={cached_count}个, 市场实际={actual_count}个, 差异={abs(cached_count - actual_count)}个"
        )
        self.logger.debug("💡 注意: 以下检查仅基于市场订单，不依赖缓存")

        # ========== 检查1: 重复订单 ==========
        self.logger.debug("📍 检查1: 诊断重复订单（相同价格）")

        price_to_orders = defaultdict(list)
        for order in orders:
            price_to_orders[order.price].append(order)

        duplicate_count = 0
        for price, order_list in price_to_orders.items():
            if len(order_list) > 1:
                # 保留第一个，其他标记为重复
                keep_order = order_list[0]
                duplicates = order_list[1:]
                problem_orders['duplicates'].extend(duplicates)
                duplicate_count += len(duplicates)

                self.logger.debug(
                    f"   ❌ 发现重复订单 @${price}: {len(order_list)}个订单, "
                    f"保留{keep_order.id[:10]}..., 标记{len(duplicates)}个为重复"
                )

        if duplicate_count > 0:
            self.logger.debug(
                f"   🔍 重复订单统计: 共{duplicate_count}个重复订单需要清理"
            )
        else:
            self.logger.debug("   ✅ 无重复订单")

        # ========== 检查2: 超出理论范围的订单 ==========
        self.logger.debug("📍 检查2: 诊断超出理论范围的订单")

        out_of_range_count = 0
        for order in orders:
            # 跳过已被标记为重复的订单
            if order in problem_orders['duplicates']:
                continue

            # 计算订单的真实网格ID
            if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                raw_index = round(
                    (order.price - self.config.lower_price) /
                    self.config.grid_interval
                ) + 1
            else:
                raw_index = round(
                    (self.config.upper_price - order.price) /
                    self.config.grid_interval
                ) + 1

            # 判断是否超出理论扩展范围
            if raw_index < theoretical_range['min_grid'] or raw_index > theoretical_range['max_grid']:
                problem_orders['out_of_range'].append((order, raw_index))
                out_of_range_count += 1
                self.logger.debug(
                    f"   ❌ 订单超出理论范围: {order.side.value} @{order.price} "
                    f"(Grid {raw_index}, 理论范围: {theoretical_range['min_grid']}-{theoretical_range['max_grid']})"
                )

        if out_of_range_count > 0:
            self.logger.debug(
                f"   🔍 超范围订单统计: 共{out_of_range_count}个订单超出理论范围"
            )
        else:
            self.logger.debug("   ✅ 所有订单都在理论范围内")

        # ========== 检查3: 🔥 新方案：订单价格是否在正确的网格点上 ==========
        self.logger.debug("📍 检查3: 检查订单价格是否在正确的网格点上")

        off_grid_count = 0
        price_tolerance = self.config.grid_interval * Decimal('0.01')  # 1%容差

        for order in orders:
            # 跳过已被标记为其他问题的订单
            if order in problem_orders['duplicates']:
                continue
            if any(order == o for o, _ in problem_orders['out_of_range']):
                continue

            # 计算订单的网格ID
            if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                grid_id = round(
                    (order.price - self.config.lower_price) /
                    self.config.grid_interval
                ) + 1
            else:
                grid_id = round(
                    (self.config.upper_price - order.price) /
                    self.config.grid_interval
                ) + 1

            # 计算该网格ID的标准价格
            expected_price = self.config.get_grid_price(grid_id)

            # 检查实际价格是否偏离标准价格
            price_diff = abs(order.price - expected_price)

            if price_diff > price_tolerance:
                # 价格偏离网格点
                problem_orders['off_grid'].append(
                    (order, grid_id, expected_price))
                off_grid_count += 1
                self.logger.debug(
                    f"   ❌ 订单价格偏离网格点: {order.side.value} @{order.price} "
                    f"(Grid {grid_id} 标准价格: {expected_price}, 偏差: {price_diff})"
                )

        if off_grid_count > 0:
            self.logger.debug(
                f"   🔍 偏离网格点订单统计: 共{off_grid_count}个订单价格不在网格点上"
            )
        else:
            self.logger.debug("   ✅ 所有订单都在正确的网格点上")

        return problem_orders

    async def _clean_problem_orders(self, problem_orders: Dict) -> int:
        """
        清理问题订单

        Args:
            problem_orders: 问题订单字典

        Returns:
            清理的订单数量
        """
        cleaned_count = 0

        # 清理重复订单
        for order in problem_orders['duplicates']:
            try:
                # 标记为预期取消（避免自动重新挂单）
                self.engine._expected_cancellations.add(order.id)
                await self.engine.exchange.cancel_order(order.id, self.config.symbol)
                cleaned_count += 1
                self.logger.debug(
                    f"🧹 已取消重复订单: {order.side.value} @{order.price} "
                    f"(ID: {order.id[:10]}...)"
                )
            except Exception as e:
                self.logger.error(f"❌ 取消重复订单失败: {e}")

        # 清理超出范围的订单
        for order, raw_index in problem_orders['out_of_range']:
            try:
                # 标记为预期取消
                self.engine._expected_cancellations.add(order.id)
                await self.engine.exchange.cancel_order(order.id, self.config.symbol)
                cleaned_count += 1
                self.logger.debug(
                    f"🧹 已取消超范围订单: {order.side.value} @{order.price} "
                    f"Grid={raw_index} (ID: {order.id[:10]}...)"
                )
            except Exception as e:
                self.logger.error(f"❌ 取消超范围订单失败: {e}")

        # 🔥 新方案：清理偏离网格点的订单
        for order, grid_id, expected_price in problem_orders.get('off_grid', []):
            try:
                # 标记为预期取消
                self.engine._expected_cancellations.add(order.id)
                await self.engine.exchange.cancel_order(order.id, self.config.symbol)
                cleaned_count += 1
                self.logger.debug(
                    f"🧹 已取消偏离网格点订单: {order.side.value} @{order.price} "
                    f"(Grid {grid_id} 标准价格: {expected_price}, ID: {order.id[:10]}...)"
                )
            except Exception as e:
                self.logger.error(f"❌ 取消偏离网格点订单失败: {e}")

        if cleaned_count > 0:
            self.logger.debug(f"✅ 问题订单清理完成: 共清理{cleaned_count}个订单")

        return cleaned_count

    async def _get_current_grid_id_from_rest(self) -> Optional[int]:
        """
        从REST API获取最新价格，并转换为网格ID

        用于关键决策点（如补单判断），确保使用最新价格

        Returns:
            网格ID，如果无法获取则返回None
        """
        try:
            # 🔥 通过REST API获取最新价格
            current_price = await self.engine.get_current_price()

            if current_price is None or current_price <= 0:
                self.logger.debug(f"⚠️ REST API返回无效价格: {current_price}")
                return None

            # 使用config将价格转换为网格ID
            grid_id = self.config.get_grid_index_by_price(current_price)

            self.logger.debug(
                f"📍 REST查询最新价格: ${current_price}, 所在网格: Grid {grid_id}"
            )

            return grid_id

        except Exception as e:
            self.logger.error(f"❌ 从REST API获取当前网格ID失败: {e}")
            return None

    async def _evaluate_grid_coverage(
        self,
        orders: List,
        extended_range: Dict
    ) -> Tuple[Set[int], List[int], Set[int]]:
        """
        评估网格覆盖情况

        Args:
            orders: 订单列表
            extended_range: 扩展范围信息

        Returns:
            (已覆盖的网格集合, 缺失的网格列表, 获利空格集合)
        """
        covered_grids = set()
        anomaly_orders = []  # 记录异常订单（清理失败的）

        # 映射订单到网格
        for order in orders:
            try:
                if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                    raw_index = round(
                        (order.price - self.config.lower_price) /
                        self.config.grid_interval
                    ) + 1
                else:
                    raw_index = round(
                        (self.config.upper_price - order.price) /
                        self.config.grid_interval
                    ) + 1

                # 双重检查：如果订单超出范围，记录为异常（可能是清理失败）
                if raw_index < extended_range['min_grid'] or raw_index > extended_range['max_grid']:
                    anomaly_orders.append((order, raw_index))
                    self.logger.error(
                        f"❌ 发现异常订单（应该已被清理但仍存在）: "
                        f"{order.side.value} @{order.price} (Grid {raw_index}, "
                        f"范围: {extended_range['min_grid']}-{extended_range['max_grid']})"
                    )
                    # 不将异常订单加入覆盖统计
                    continue

                covered_grids.add(raw_index)

            except Exception as e:
                self.logger.debug(f"⚠️ 订单 @{order.price} 映射失败: {e}")

        # 如果有异常订单，输出警告
        if anomaly_orders:
            self.logger.error(
                f"🚨 警告: 发现 {len(anomaly_orders)} 个异常订单未被清理！"
            )
            self.logger.error(
                f"💡 建议: 这些订单可能需要手动取消"
            )

        # 找出缺失的网格
        all_grids = set(range(
            extended_range['min_grid'],
            extended_range['max_grid'] + 1
        ))
        missing_grids_raw = sorted(all_grids - covered_grids)

        # 动态计算获利空格：买单和卖单之间的空隙
        profit_gap_grids = set()
        if extended_range['extended'] and orders:
            # 分离买单和卖单
            buy_grids = []
            sell_grids = []

            for order in orders:
                # 计算订单的网格ID
                if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                    grid_id = round(
                        (order.price - self.config.lower_price) /
                        self.config.grid_interval
                    ) + 1
                else:
                    grid_id = round(
                        (self.config.upper_price - order.price) /
                        self.config.grid_interval
                    ) + 1

                # 分类
                if order.side == ExchangeOrderSide.BUY:
                    buy_grids.append(grid_id)
                elif order.side == ExchangeOrderSide.SELL:
                    sell_grids.append(grid_id)

            # 计算获利空格：买单最高网格 和 卖单最低网格 之间
            if buy_grids and sell_grids:
                max_buy_grid = max(buy_grids)
                min_sell_grid = min(sell_grids)

                # 所有空网格 = (max_buy_grid, min_sell_grid) 之间的所有网格
                if min_sell_grid > max_buy_grid:
                    all_empty_grids = set(
                        range(max_buy_grid + 1, min_sell_grid))

                    # 预期获利空网格数量
                    expected_profit_gap_count = self.config.reverse_order_grid_distance

                    self.logger.debug(
                        f"📍 获利空格分析: 买单最高Grid={max_buy_grid}, "
                        f"卖单最低Grid={min_sell_grid}, "
                        f"实际空网格={len(all_empty_grids)}个, "
                        f"预期获利空格={expected_profit_gap_count}个"
                    )

                    # 第一步：判断是否需要补单
                    if len(all_empty_grids) <= expected_profit_gap_count:
                        # 空网格数量 <= 预期，说明正常，所有空网格都是合法的获利空格
                        profit_gap_grids = all_empty_grids
                        self.logger.debug(
                            f"   ✅ 空网格数量正常，所有空网格都是获利空格: {sorted(profit_gap_grids)}"
                        )
                    else:
                        # 空网格数量 > 预期，需要判断哪些需要补单
                        # 🔥 关键决策点：通过REST API获取最新价格，确保判断准确
                        self.logger.debug(
                            f"⚠️ 检测到空网格超标({len(all_empty_grids)}个 > {expected_profit_gap_count}个)，"
                            f"正在通过REST API查询最新价格以准确判断..."
                        )
                        current_grid_id = await self._get_current_grid_id_from_rest()

                        if current_grid_id is not None:
                            # 按距离当前价格的远近排序
                            empty_grids_sorted = sorted(
                                all_empty_grids,
                                key=lambda g: abs(g - current_grid_id)
                            )

                            # 距离最近的N个空网格是合法的获利空格
                            profit_gap_grids = set(
                                empty_grids_sorted[:expected_profit_gap_count])

                            # 需要补单的空网格
                            grids_need_fill = all_empty_grids - profit_gap_grids

                            self.logger.debug(
                                f"⚠️ 空网格数量超标: 当前价格Grid={current_grid_id}, "
                                f"实际空网格={sorted(all_empty_grids)}, "
                                f"合法获利空格={sorted(profit_gap_grids)}, "
                                f"需要补单={sorted(grids_need_fill)}"
                            )
                        else:
                            # 无法获取当前价格，保守处理：所有空网格都视为获利空格，不补单
                            profit_gap_grids = all_empty_grids
                            self.logger.debug(
                                f"⚠️ 无法获取当前价格所在网格，暂时将所有空网格视为获利空格，不补单"
                            )

        # 真正的缺失网格（排除获利空格）
        missing_grids = [
            g for g in missing_grids_raw if g not in profit_gap_grids]

        # 日志输出
        if profit_gap_grids:
            profit_gaps_in_missing = [
                g for g in missing_grids_raw if g in profit_gap_grids]
            if profit_gaps_in_missing:
                self.logger.debug(
                    f"📍 网格覆盖: 已覆盖={len(covered_grids)}格, "
                    f"获利空格={len(profit_gaps_in_missing)}格 (正常), "
                    f"真正缺失={len(missing_grids)}格"
                )
                self.logger.debug(
                    f"   获利空格: {sorted(profit_gaps_in_missing)} (用于获利，正常空着)"
                )
            else:
                self.logger.debug(
                    f"📍 网格覆盖: 已覆盖={len(covered_grids)}格, "
                    f"缺失={len(missing_grids)}格, "
                    f"预期={extended_range['expected_count']}格"
                )
        else:
            self.logger.debug(
                f"📍 网格覆盖: 已覆盖={len(covered_grids)}格, "
                f"缺失={len(missing_grids)}格, "
                f"预期={extended_range['expected_count']}格"
            )

        if missing_grids:
            if len(missing_grids) <= 10:
                self.logger.debug(f"   真正缺失网格: {missing_grids}")
            else:
                self.logger.debug(
                    f"   真正缺失网格: {missing_grids[:5]}...{missing_grids[-5:]} "
                    f"(共{len(missing_grids)}个)"
                )

        return covered_grids, missing_grids, profit_gap_grids

    async def _fill_missing_grids(self, missing_grids: List[int], extended_range: Dict):
        """
        补充缺失的网格

        Args:
            missing_grids: 缺失的网格ID列表
            extended_range: 扩展范围信息
        """
        try:
            if not missing_grids:
                return

            self.logger.debug(f"🔧 准备补充 {len(missing_grids)} 个缺失网格")

            # 获取当前价格
            current_price = await self.engine.get_current_price()
            self.logger.debug(f"📊 当前价格: ${current_price}")

            # 创建订单
            orders_to_place = []

            for grid_id in missing_grids:
                try:
                    grid_price = self.config.get_grid_price(grid_id)

                    # 判断订单方向
                    if grid_price < current_price:
                        side = GridOrderSide.BUY
                    elif grid_price > current_price:
                        side = GridOrderSide.SELL
                    else:
                        continue  # 价格相等，跳过

                    # 🔥 使用格式化后的订单数量（符合交易所精度）
                    amount = self.config.get_formatted_grid_order_amount(
                        grid_id)

                    # 创建订单
                    order = GridOrder(
                        order_id="",
                        grid_id=grid_id,
                        side=side,
                        price=grid_price,
                        amount=amount,  # 格式化后的金额
                        status=GridOrderStatus.PENDING,
                        created_at=datetime.now()
                    )
                    orders_to_place.append(order)

                except Exception as e:
                    self.logger.error(f"❌ 创建Grid {grid_id}订单失败: {e}")

            # 批量下单
            if orders_to_place:
                success_count = 0
                fail_count = 0

                for order in orders_to_place:
                    try:
                        await self.engine.place_order(order)
                        success_count += 1
                        self.logger.debug(
                            f"✅ 补充Grid {order.grid_id}: "
                            f"{order.side.value} {order.amount}@{order.price}"
                        )
                    except Exception as e:
                        fail_count += 1
                        self.logger.error(f"❌ 补充Grid {order.grid_id}失败: {e}")

                self.logger.debug(
                    f"✅ 补单完成: 成功={success_count}个, 失败={fail_count}个, "
                    f"总计={len(orders_to_place)}个"
                )

        except Exception as e:
            self.logger.error(f"❌ 补充缺失网格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def _clean_stale_cache(self):
        """
        🔥 同步缓存与市场（可删除，可添加）

        策略：
        1. 重新获取最新的市场数据
        2. 验证市场数据是否符合预期（订单数量正确）
        3. 马上开始同步（最快速度完成）
        4. 删除：缓存中有但市场上没有的订单
        5. 添加：市场上有但缓存中没有的订单（有client_id的）

        关键：
        - 从获取市场数据到同步完成，以最快速度执行
        - 最小化时间窗口，防止市场发生变化
        - 如果重新获取的数据不符合预期，放弃本次同步
        - 确保缓存与市场完全一致
        """
        try:
            self.logger.debug("🔄 开始同步缓存与市场...")

            # 统计同步前的缓存数量
            cache_before = len(self.engine._pending_orders_by_client_id)

            # 🔥 步骤1: 重新获取最新的市场数据（确保数据最新）
            self.logger.debug("📡 重新获取最新市场数据...")
            latest_orders = await self.engine.exchange.get_open_orders(self.config.symbol)

            # 🔥 步骤1.5: 验证最新数据是否符合预期（关键安全检查）
            if len(latest_orders) != self.config.grid_count:
                self.logger.warning(
                    f"⚠️ 放弃缓存同步: 重新获取的市场数据不符合预期 "
                    f"(市场订单={len(latest_orders)}个 ≠ 预期={self.config.grid_count}个)\n"
                    f"   可能原因: 市场正在成交/补单/取消订单，处于不稳定状态\n"
                    f"   处理方式: 本次同步取消，等待下次健康检查"
                )
                return

            self.logger.debug(
                f"✅ 市场数据验证通过: 订单数量={len(latest_orders)}个 = 预期={self.config.grid_count}个"
            )

            # 🔥 步骤2: 马上构建市场订单映射（最快速度）
            # 按 order_id 映射
            exchange_orders_by_id = {
                order.id: order for order in latest_orders}

            # 按 client_id 映射（用于添加新订单）
            exchange_orders_by_client_id = {}
            for order in latest_orders:
                if hasattr(order, 'client_id') and order.client_id:
                    exchange_orders_by_client_id[str(order.client_id)] = order

            # 🔥 步骤3: 删除缓存中有但市场上没有的订单
            to_remove = []
            for client_id, cached_order in self.engine._pending_orders_by_client_id.items():
                # 删除有order_id且不在市场的订单
                if cached_order.order_id and cached_order.order_id not in exchange_orders_by_id:
                    to_remove.append((client_id, cached_order))

            for client_id, cached_order in to_remove:
                del self.engine._pending_orders_by_client_id[client_id]
                self.logger.debug(
                    f"🧹 删除过期缓存: client_id={client_id}, "
                    f"order_id={cached_order.order_id[:10]}..., "
                    f"{cached_order.side.value} @{cached_order.price} "
                    f"(Grid {cached_order.grid_id})"
                )

            # 🔥 步骤4: 添加市场上有但缓存中没有的订单（有client_id的）
            to_add = []
            for client_id, exchange_order in exchange_orders_by_client_id.items():
                # 添加缓存中没有的订单
                if client_id not in self.engine._pending_orders_by_client_id:
                    to_add.append((client_id, exchange_order))

            for client_id, exchange_order in to_add:
                # 计算网格ID
                if self.config.grid_type in [GridType.LONG, GridType.FOLLOW_LONG, GridType.MARTINGALE_LONG]:
                    grid_id = round(
                        (exchange_order.price - self.config.lower_price) /
                        self.config.grid_interval
                    ) + 1
                else:
                    grid_id = round(
                        (self.config.upper_price - exchange_order.price) /
                        self.config.grid_interval
                    ) + 1

                # 创建 GridOrder 对象
                grid_order = GridOrder(
                    order_id=exchange_order.id,
                    grid_id=grid_id,
                    side=GridOrderSide.BUY if exchange_order.side == ExchangeOrderSide.BUY else GridOrderSide.SELL,
                    price=exchange_order.price,
                    amount=exchange_order.amount,
                    status=GridOrderStatus.PENDING,
                    created_at=exchange_order.timestamp or datetime.now(),
                    client_id=client_id
                )

                # 添加到缓存
                self.engine._pending_orders_by_client_id[client_id] = grid_order
                self.logger.debug(
                    f"➕ 添加缺失订单到缓存: client_id={client_id}, "
                    f"order_id={exchange_order.id[:10]}..., "
                    f"{grid_order.side.value} @{grid_order.price} "
                    f"(Grid {grid_id})"
                )

            # 统计同步后的缓存数量
            cache_after = len(self.engine._pending_orders_by_client_id)

            # 汇总日志
            if to_remove or to_add:
                self.logger.info(
                    f"✅ 缓存同步完成: 删除{len(to_remove)}个, 添加{len(to_add)}个 "
                    f"(缓存: {cache_before}个 → {cache_after}个, 市场: {len(latest_orders)}个)"
                )
            else:
                self.logger.debug(
                    f"✅ 缓存检查完成: 缓存与市场一致 "
                    f"(缓存={cache_after}个, 市场={len(latest_orders)}个)"
                )

        except Exception as e:
            self.logger.error(f"❌ 同步缓存失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def _sync_orders_to_engine(self, exchange_orders: List):
        """
        同步订单到引擎的本地缓存

        Args:
            exchange_orders: 交易所订单列表
        """
        try:
            # 调用引擎的同步方法
            await self.engine._sync_orders_from_exchange(exchange_orders)

        except Exception as e:
            self.logger.error(f"❌ 同步订单到引擎失败: {e}")

    def _is_spot_mode(self) -> bool:
        """判断是否是现货模式"""
        try:
            from ....adapters.exchanges.interface import ExchangeType
            if hasattr(self.engine, 'exchange') and hasattr(self.engine.exchange, 'config'):
                is_spot = self.engine.exchange.config.exchange_type == ExchangeType.SPOT
                return is_spot
        except Exception as e:
            self.logger.error(f"❌ 判断现货模式失败: {e}")
        return False

    async def _query_spot_position(self) -> List[PositionData]:
        """
        查询现货持仓（通过余额）

        Returns:
            List[PositionData]: 持仓列表（0或1个元素）
        """
        try:
            # 解析交易对，获取基础货币
            symbol_parts = self.config.symbol.split('/')
            base_currency = symbol_parts[0]  # UBTC

            # 查询余额
            balances = await self.engine.exchange.get_balances()

            # 获取基础货币余额
            total_balance = Decimal('0')
            if balances:
                for balance in balances:
                    if balance.currency == base_currency:
                        total_balance = balance.total  # 总余额
                        break

            # 🔥 减去预留（如果有）
            trading_balance = total_balance
            if self.reserve_manager:
                reserve_amount = self.reserve_manager.reserve_amount  # 使用固定预留
                trading_balance = total_balance - reserve_amount
                self.logger.debug(
                    f"📊 现货持仓检查: 总余额={total_balance}, 预留={reserve_amount}, "
                    f"交易持仓={trading_balance}"
                )

            # 如果没有持仓，返回空列表
            if trading_balance <= 0:
                return []

            # 🔥 构造 PositionData 对象
            # 现货只有多头
            position = PositionData(
                symbol=self.config.symbol,
                side=PositionSide.LONG,
                size=trading_balance,
                entry_price=Decimal('0'),  # 健康检查不需要准确的成本价
                mark_price=None,  # 标记价格（现货不需要）
                current_price=None,  # 当前价格（健康检查不需要）
                unrealized_pnl=Decimal('0'),
                realized_pnl=Decimal('0'),  # 已实现盈亏
                percentage=None,  # 收益率百分比
                leverage=1,
                margin_mode=MarginMode.CROSS,  # 🔥 修复：使用CROSS而不是CROSSED
                margin=Decimal('0'),
                liquidation_price=None,
                timestamp=datetime.now(),
                raw_data={}  # 原始数据
            )

            self.logger.debug(
                f"📊 现货持仓查询成功: {trading_balance} {base_currency}"
            )

            return [position]

        except Exception as e:
            self.logger.error(f"❌ 查询现货持仓失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
