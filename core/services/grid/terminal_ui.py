"""
网格交易系统终端界面

使用Rich库实现实时监控界面
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Deque
from datetime import timedelta, datetime
from decimal import Decimal
from collections import deque

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from ...logging import get_logger
from .models import GridStatistics, GridType
from .models.grid_order import GridOrderStatus, GridOrderSide
from .coordinator import GridCoordinator


class UILogHandler(logging.Handler):
    """UI日志处理器 - 将日志捕获到队列中供UI显示"""

    def __init__(self, log_queue: deque, max_size: int = 10):
        super().__init__()
        self.log_queue = log_queue
        self.max_size = max_size

    def emit(self, record: logging.LogRecord):
        """捕获日志记录"""
        try:
            # 格式化日志消息
            msg = self.format(record)

            # 添加到队列（保持最新N条）
            self.log_queue.append({
                'time': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                'level': record.levelname,
                'module': record.name.split('.')[-1] if '.' in record.name else record.name,
                'message': msg,
                'raw_record': record
            })

            # 保持队列大小
            while len(self.log_queue) > self.max_size:
                self.log_queue.popleft()
        except Exception:
            # 忽略处理日志时的错误，避免死循环
            pass


class GridTerminalUI:
    """
    网格交易终端界面

    显示内容：
    1. 运行状态
    2. 订单统计
    3. 持仓信息
    4. 盈亏统计
    5. 最近成交订单
    """

    def __init__(self, coordinator: GridCoordinator):
        """
        初始化终端界面

        Args:
            coordinator: 网格协调器
        """
        self.logger = get_logger(__name__)
        self.coordinator = coordinator
        self.console = Console()

        # 界面配置
        self.refresh_rate = 2  # 刷新频率（次/秒）- 降低刷新率减少闪烁
        self.history_limit = 10  # 显示历史记录数

        # 运行控制
        self._running = False

        # 提取基础货币名称（从交易对符号中提取）
        # 例如: BTC_USDC_PERP -> BTC, HYPE_USDC_PERP -> HYPE
        symbol = self.coordinator.config.symbol
        self.base_currency = symbol.split('_')[0] if '_' in symbol else symbol

        # 🔥 日志显示相关
        self.log_queue: deque = deque(maxlen=20)  # 最新20条日志
        self.ui_log_handler: Optional[UILogHandler] = None
        self._removed_console_handlers: dict = {}  # 存储被移除的控制台handler
        self._setup_log_capture()

        # 🔥 价格精度（从配置中获取，用于动态显示价格）
        self.price_decimals = self.coordinator.config.price_decimals

    def _format_price(self, price: Decimal) -> str:
        """
        格式化价格显示，使用配置的价格精度

        Args:
            price: 价格（Decimal类型）

        Returns:
            格式化后的价格字符串（例如：$110,000.5 或 $0.0234）
        """
        return f"${price:,.{self.price_decimals}f}"

    def _setup_log_capture(self):
        """设置日志捕获 - 监听关键模块的日志并禁用控制台输出"""
        try:
            # 创建UI日志处理器
            self.ui_log_handler = UILogHandler(self.log_queue, max_size=20)
            self.ui_log_handler.setLevel(logging.INFO)  # 只捕获INFO及以上级别

            # 简化日志格式（去掉时间戳和模块路径，因为UI表格会显示）
            formatter = logging.Formatter('%(message)s')
            self.ui_log_handler.setFormatter(formatter)

            # 关键模块列表（需要禁用控制台输出的模块）
            key_modules = [
                # 交易所适配器
                'core.adapters.exchanges.adapters.lighter_rest',
                'core.adapters.exchanges.adapters.lighter_websocket',
                'core.adapters.exchanges.adapters.lighter_websocket.price',  # 价格logger
                'core.adapters.exchanges.adapters.lighter_base',
                # 实现层
                'core.services.grid.implementations.grid_engine_impl',
                'core.services.grid.implementations.order_health_checker',
                'core.services.grid.implementations.position_tracker_impl',  # 持仓追踪
                'core.services.grid.implementations.grid_strategy_impl',  # 网格策略
                # Coordinator 协调层
                'core.services.grid.coordinator.grid_coordinator',
                'core.services.grid.coordinator.position_monitor',  # 持仓监控
                'core.services.grid.coordinator.balance_monitor',  # 余额监控
                'core.services.grid.coordinator.order_operations',  # 订单操作
                'core.services.grid.coordinator.scalping_operations',  # 剥头皮操作
                'core.services.grid.coordinator.grid_reset_manager',  # 网格重置
            ]

            # 存储被移除的控制台handler，以便恢复
            self._removed_console_handlers = {}

            # 🔥 禁用root logger的控制台输出（避免其他模块的日志输出到控制台）
            root_logger = logging.getLogger()
            root_console_handlers = []
            for handler in root_logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                    root_console_handlers.append(handler)
                    root_logger.removeHandler(handler)
            if root_console_handlers:
                self._removed_console_handlers['root'] = root_console_handlers

            for module_name in key_modules:
                module_logger = logging.getLogger(module_name)

                # 🔥 移除控制台输出handler（StreamHandler），只保留文件输出
                console_handlers_to_remove = []
                for handler in module_logger.handlers[:]:  # 使用切片复制列表
                    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                        console_handlers_to_remove.append(handler)
                        module_logger.removeHandler(handler)

                # 保存被移除的handler（如果需要恢复）
                if console_handlers_to_remove:
                    self._removed_console_handlers[module_name] = console_handlers_to_remove

                # 添加UI日志处理器（避免重复添加）
                if self.ui_log_handler not in module_logger.handlers:
                    module_logger.addHandler(self.ui_log_handler)
                module_logger.setLevel(logging.INFO)

                # 🔥 禁用传播到root logger（避免root logger的控制台输出）
                module_logger.propagate = False

        except Exception as e:
            self.logger.warning(f"设置日志捕获失败: {e}")

    def _ensure_console_logging_disabled(self):
        """确保控制台日志输出已禁用（额外检查）"""
        key_modules = [
            # 交易所适配器
            'core.adapters.exchanges.adapters.lighter_rest',
            'core.adapters.exchanges.adapters.lighter_websocket',
            'core.adapters.exchanges.adapters.lighter_websocket.price',
            'core.adapters.exchanges.adapters.lighter_base',
            # 实现层
            'core.services.grid.implementations.grid_engine_impl',
            'core.services.grid.implementations.order_health_checker',
            'core.services.grid.implementations.position_tracker_impl',  # 持仓追踪
            'core.services.grid.implementations.grid_strategy_impl',  # 网格策略
            # Coordinator 协调层
            'core.services.grid.coordinator.grid_coordinator',
            'core.services.grid.coordinator.position_monitor',  # 持仓监控
            'core.services.grid.coordinator.balance_monitor',  # 余额监控
            'core.services.grid.coordinator.order_operations',  # 订单操作
            'core.services.grid.coordinator.scalping_operations',  # 剥头皮操作
            'core.services.grid.coordinator.grid_reset_manager',  # 网格重置
        ]

        # 再次检查并移除控制台handler
        for module_name in key_modules:
            module_logger = logging.getLogger(module_name)
            for handler in module_logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                    if handler not in self._removed_console_handlers.get(module_name, []):
                        module_logger.removeHandler(handler)
            # 确保不传播到root
            module_logger.propagate = False

        # 检查root logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                if 'root' not in self._removed_console_handlers or handler not in self._removed_console_handlers.get('root', []):
                    root_logger.removeHandler(handler)

    def create_logs_table(self) -> Panel:
        """创建日志显示表格"""
        table = Table(show_header=True, box=None, padding=(0, 1))
        table.add_column("时间", style="dim", width=8, no_wrap=True)
        table.add_column("级别", style="bold", width=6, no_wrap=True)
        table.add_column("模块", style="cyan", width=12, no_wrap=True)
        table.add_column("消息", style="white")  # 🔥 移除overflow限制，完整显示消息

        # 如果没有日志，显示提示
        if not self.log_queue:
            table.add_row("--:--:--", "--", "等待日志", "[dim]暂无日志[/dim]")
        else:
            # 显示最新10条日志（从新到旧，最新的在最下面）
            log_list = list(self.log_queue)
            for log_entry in log_list:
                # 根据日志级别设置颜色
                level = log_entry['level']
                if level == 'ERROR':
                    level_style = "[bold red]ERROR[/bold red]"
                elif level == 'WARNING':
                    level_style = "[bold yellow]WARN[/bold yellow]"
                elif level == 'INFO':
                    level_style = "[bold green]INFO[/bold green]"
                elif level == 'DEBUG':
                    level_style = "[dim]DEBUG[/dim]"
                else:
                    level_style = level

                # 简化消息格式
                message = log_entry['message']

                # 移除常见的前缀emoji（保留文本信息）
                emoji_map = {
                    '✅ ': '', '❌ ': '', '⚠️ ': '', '📝 ': '',
                    '📨 ': '', '🔄 ': '', '🔗 ': '', '💓 ': '',
                    '📦 ': '', '📊 ': '', '🔍 ': '', '🚀 ': ''
                }
                for emoji, replacement in emoji_map.items():
                    message = message.replace(emoji, replacement)

                # 简化模块路径（如果消息中包含）
                if 'core.adapters.exchanges.adapters.' in message:
                    message = message.replace(
                        'core.adapters.exchanges.adapters.', '')
                if 'core.services.grid.' in message:
                    message = message.replace('core.services.grid.', '')

                # 🔥 根据消息类型设置颜色
                # [成交] = 绿色, [反手] = 蓝色, 其他 = 白色
                if '[成交]' in message:
                    message_style = "bold green"
                elif '[反手]' in message:
                    message_style = "bold cyan"
                else:
                    message_style = "white"

                # 🔥 不限制消息长度，完整显示所有信息
                # 使用富文本格式应用颜色
                formatted_message = f"[{message_style}]{message}[/{message_style}]"

                table.add_row(
                    log_entry['time'],
                    level_style,
                    log_entry['module'][:12],  # 限制模块名长度
                    formatted_message
                )

        return Panel(table, title="📋 最新日志 (最新20条)", border_style="blue", height=23)

    def create_header(self, stats: GridStatistics) -> Panel:
        """创建标题栏"""
        # 判断网格类型（做多/做空）
        is_long = self.coordinator.config.grid_type in [
            GridType.LONG, GridType.MARTINGALE_LONG, GridType.FOLLOW_LONG]
        grid_type_text = "做多网格" if is_long else "做空网格"

        title = Text()
        title.append("🎯 网格交易系统实时监控 ", style="bold cyan")
        title.append("v2.8", style="bold magenta")
        title.append(" - ", style="bold white")
        title.append(
            f"{self.coordinator.config.exchange.upper()}/", style="bold yellow")
        title.append(f"{self.coordinator.config.symbol}", style="bold green")

        return Panel(title, style="bold white on blue")

    def create_status_panel(self, stats: GridStatistics) -> Panel:
        """创建运行状态面板"""
        # 判断网格类型（做多/做空）和模式（普通/马丁/价格移动）
        grid_type = self.coordinator.config.grid_type

        if grid_type == GridType.LONG:
            grid_type_text = "做多网格（普通）"
        elif grid_type == GridType.SHORT:
            grid_type_text = "做空网格（普通）"
        elif grid_type == GridType.MARTINGALE_LONG:
            grid_type_text = "做多网格（马丁）"
        elif grid_type == GridType.MARTINGALE_SHORT:
            grid_type_text = "做空网格（马丁）"
        elif grid_type == GridType.FOLLOW_LONG:
            grid_type_text = "做多网格（价格移动）"
        elif grid_type == GridType.FOLLOW_SHORT:
            grid_type_text = "做空网格（价格移动）"
        else:
            grid_type_text = grid_type.value

        status_text = self.coordinator.get_status_text()

        # 格式化运行时长
        running_time = str(stats.running_time).split('.')[0]  # 移除微秒

        # 🔥 获取剥头皮模式状态
        scalping_enabled = self.coordinator.config.scalping_enabled
        scalping_active = False
        if self.coordinator.scalping_manager:
            scalping_active = self.coordinator.scalping_manager.is_active()

        # 🛡️ 获取本金保护模式状态
        capital_protection_enabled = self.coordinator.config.capital_protection_enabled
        capital_protection_active = False
        if self.coordinator.capital_protection_manager:
            capital_protection_active = self.coordinator.capital_protection_manager.is_active()

        content = Text()
        content.append(
            f"├─ 网格策略: {grid_type_text} ({stats.grid_count}格)   ", style="white")
        content.append(f"状态: {status_text}", style="bold")
        content.append("\n")

        # 📊 显示马丁模式状态（如果启用）
        if self.coordinator.config.martingale_increment and self.coordinator.config.martingale_increment > 0:
            content.append("├─ 马丁模式: ", style="white")
            content.append("✅ 已启用", style="bold green")
            content.append(f"  |  递增: ", style="white")
            content.append(
                f"{self.coordinator.config.martingale_increment} {self.base_currency}", style="bold yellow")
            content.append("\n")

        # 🔥 显示剥头皮模式状态
        if scalping_enabled:
            content.append("├─ 剥头皮: ", style="white")

            # 🧠 检查是否启用智能模式
            smart_info = None
            if self.coordinator.scalping_manager:
                smart_info = self.coordinator.scalping_manager.get_smart_progress_info()

            if scalping_active:
                content.append("🔴 已激活", style="bold red")
            else:
                # 🆕 智能剥头皮进度显示
                if smart_info:
                    state = smart_info['state']
                    if state == 'tracking':
                        content.append("📉 追踪中", style="bold yellow")
                        content.append(
                            f" ({smart_info['drop_count']}/{smart_info['allowed_drops']})", style="cyan")
                    elif state == 'waiting_rebound':
                        content.append("⏳ 等待反弹", style="bold yellow")
                        content.append(
                            f" ({smart_info['drop_count']}/{smart_info['allowed_drops']})", style="cyan")
                    elif state == 'activated':
                        content.append("🎯 已准备", style="bold green")
                        content.append(
                            f" (G{smart_info['activation_grid']})", style="cyan")
                    else:
                        content.append("⚪ 待触发", style="bold cyan")
                else:
                    content.append("⚪ 待触发", style="bold cyan")

            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(f"{stats.scalping_trigger_count}",
                           style="bold yellow")

            # 🆕 显示触发网格和价格（智能模式显示当前阈值，常规模式显示固定触发点）
            if smart_info and smart_info['current_threshold']:
                trigger_grid = smart_info['current_threshold']
                content.append(f"  |  当前阈值: ", style="white")
            else:
                trigger_grid = self.coordinator.config.get_scalping_trigger_grid()
                content.append(f"  |  触发网格: ", style="white")

            trigger_price = self.coordinator.config.get_grid_price(
                trigger_grid)
            content.append(f"Grid {trigger_grid}", style="bold cyan")
            content.append(
                f" ({self._format_price(trigger_price)})", style="cyan")
            content.append("\n")

        # 🛡️ 显示本金保护模式状态
        if capital_protection_enabled:
            content.append("├─ 本金保护: ", style="white")
            if capital_protection_active:
                content.append("🟢 已触发", style="bold green")
            else:
                content.append("⚪ 待触发", style="bold cyan")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.capital_protection_trigger_count}", style="bold yellow")
            content.append("\n")

        # 💰 显示止盈模式状态
        if stats.take_profit_enabled:
            content.append("├─ 止盈: ", style="white")
            if stats.take_profit_active:
                content.append("🔴 已触发", style="bold red")
            else:
                # 显示当前盈利率和阈值
                profit_rate = float(stats.take_profit_profit_rate)
                threshold = float(stats.take_profit_threshold)
                content.append("⚪ 待触发  |  ", style="bold cyan")
                if profit_rate >= 0:
                    content.append(
                        f"当前: +{profit_rate:.2f}%  阈值: {threshold:.2f}%", style="bold green")
                else:
                    content.append(
                        f"当前: {profit_rate:.2f}%  阈值: {threshold:.2f}%", style="bold red")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.take_profit_trigger_count}", style="bold yellow")
            content.append("\n")

        # 🔒 显示价格锁定模式状态
        if stats.price_lock_enabled:
            content.append("├─ 价格锁定: ", style="white")
            if stats.price_lock_active:
                content.append("🔒 已激活 (冻结)", style="bold yellow")
            else:
                threshold = stats.price_lock_threshold
                current = stats.current_price
                content.append("⚪ 待触发  |  ", style="bold cyan")
                content.append(
                    f"当前: {self._format_price(current)}  阈值: {self._format_price(threshold)}", style="white")
            content.append("\n")

        # 🛑 止损保护模式状态
        if hasattr(self.coordinator, 'stop_loss_monitor'):
            stop_loss_status = self.coordinator.stop_loss_monitor.get_status()
            if stop_loss_status['enabled']:
                # 获取价格信息
                current_price = stop_loss_status.get('current_price')
                trigger_price = stop_loss_status.get('trigger_price')
                trigger_percent = stop_loss_status.get('trigger_percent', 100)
                apr_threshold = stop_loss_status.get('apr_threshold', 50)

                # 显示止损保护状态
                if stop_loss_status['is_escaped']:
                    # 正在脱离，显示倒计时
                    elapsed = stop_loss_status['elapsed_seconds']
                    remaining = stop_loss_status['remaining_seconds']
                    content.append("├─ 止损保护: ", style="white")
                    content.append(
                        f"⚠️  脱离中 ({elapsed}秒/{stop_loss_status['timeout']}秒)", style="bold red")
                    content.append(f"  剩余{remaining}秒触发\n",
                                   style="bold yellow")

                    # 第二行：当前价格 vs 触发价格
                    if current_price and trigger_price:
                        content.append(
                            f"│  当前: {self._format_price(current_price)}", style="yellow")
                        content.append(
                            f"  触发: {self._format_price(trigger_price)}", style="red")

                        # 计算距离触发位置的百分比
                        if current_price != trigger_price:
                            distance_percent = abs(
                                (current_price - trigger_price) / trigger_price * 100)
                            content.append(
                                f"  (偏离{distance_percent:.1f}%)\n", style="cyan")
                        else:
                            content.append("\n", style="white")

                elif stop_loss_status['triggered']:
                    content.append("├─ 止损保护: ", style="white")
                    content.append("🛑 已触发\n", style="bold red")

                else:
                    # 监控中，显示详细参数
                    content.append("├─ 止损保护: ", style="white")
                    content.append("✅ 监控中  |  ", style="green")
                    content.append(f"触发: {trigger_percent:.1f}%", style="cyan")
                    content.append(
                        f"  APR阈值: {apr_threshold:.1f}%", style="cyan")
                    if trigger_price:
                        content.append(
                            f"  触发价: {self._format_price(trigger_price)}", style="yellow")
                    content.append("\n")

        # 🔄 显示价格脱离倒计时（价格移动网格专用）
        if stats.price_escape_active:
            content.append("├─ 价格脱离: ", style="white")
            direction_text = "⬇️ 向下" if stats.price_escape_direction == "down" else "⬆️ 向上"
            content.append(f"{direction_text} ", style="bold yellow")
            content.append(
                f"⏱️ {stats.price_escape_remaining}s", style="bold red")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.price_escape_trigger_count}", style="bold yellow")
            content.append("\n")
        # 🆕 即使没有脱离，如果是价格移动网格，也显示历史触发次数
        elif self.coordinator.config.is_follow_mode():
            content.append("├─ 价格脱离: ", style="white")
            content.append("✅ 正常  ", style="bold green")
            content.append(f"|  历史触发次数: ", style="white")
            content.append(
                f"{stats.price_escape_trigger_count}", style="bold yellow")
            content.append("\n")

        content.append(
            f"├─ 价格区间: {self._format_price(stats.price_range[0])} - {self._format_price(stats.price_range[1])}  ", style="white")
        content.append(f"网格间隔: ${stats.grid_interval}  ", style="cyan")
        content.append(
            f"反手距离: {self.coordinator.config.reverse_order_grid_distance}格\n", style="magenta")

        # 🆕 显示单格金额（仅作为显示，无实质功能）
        content.append(f"├─ 单格金额: ", style="white")
        content.append(
            f"{self.coordinator.config.order_amount} {self.base_currency}  ", style="bold cyan")
        content.append(
            f"数量精度: {self.coordinator.config.quantity_precision}位\n", style="white")

        content.append(
            f"├─ 当前价格: {self._format_price(stats.current_price)}             ", style="bold yellow")
        content.append(
            f"当前位置: Grid {stats.current_grid_id}/{stats.grid_count}\n", style="white")

        # 🔥 显示网格启动价格（启动或重置时的价格）
        if self.coordinator.state.initial_price:
            initial_price = self.coordinator.state.initial_price
            content.append(
                f"├─ 启动价格: {self._format_price(initial_price)}             ", style="cyan")

            # 计算价格变化百分比
            if stats.current_price and initial_price:
                price_change_pct = (
                    (stats.current_price - initial_price) / initial_price) * 100
                if price_change_pct > 0:
                    content.append(
                        f"变化: +{price_change_pct:.2f}%\n", style="bold green")
                elif price_change_pct < 0:
                    content.append(
                        f"变化: {price_change_pct:.2f}%\n", style="bold red")
                else:
                    content.append(
                        f"变化: {price_change_pct:.2f}%\n", style="white")
            else:
                content.append("\n", style="white")

        content.append(f"└─ 运行时长: {running_time}", style="white")

        return Panel(content, title="📊 运行状态", border_style="green")

    def create_orders_panel(self, stats: GridStatistics) -> Panel:
        """创建订单统计面板"""
        content = Text()

        # 🔥 显示监控方式
        monitoring_mode = getattr(stats, 'monitoring_mode', 'WebSocket')
        if monitoring_mode == "WebSocket":
            mode_icon = "📡"
            mode_style = "bold cyan"
        else:
            mode_icon = "📊"
            mode_style = "bold yellow"

        content.append(f"├─ 监控方式: ", style="white")
        content.append(f"{mode_icon} {monitoring_mode}", style=mode_style)
        content.append("\n")

        # 🔥 修复：从实际订单中获取Grid ID范围，而不是基于current_grid_id猜测
        # 这样可以准确显示实际挂单的网格范围
        buy_grid_ids = []
        sell_grid_ids = []

        # 从coordinator的state中获取实际订单
        if hasattr(self.coordinator, 'state') and hasattr(self.coordinator.state, 'active_orders'):
            for order in self.coordinator.state.active_orders.values():
                if hasattr(order, 'grid_id') and order.grid_id:
                    if order.side == GridOrderSide.BUY:
                        buy_grid_ids.append(order.grid_id)
                    elif order.side == GridOrderSide.SELL:
                        sell_grid_ids.append(order.grid_id)

        # 计算买单范围
        if buy_grid_ids:
            min_buy = min(buy_grid_ids)
            max_buy = max(buy_grid_ids)
            buy_range = f"Grid {min_buy}-{max_buy}" if min_buy != max_buy else f"Grid {min_buy}"
        else:
            buy_range = "无"

        # 计算卖单范围
        if sell_grid_ids:
            min_sell = min(sell_grid_ids)
            max_sell = max(sell_grid_ids)
            sell_range = f"Grid {min_sell}-{max_sell}" if min_sell != max_sell else f"Grid {min_sell}"
        else:
            sell_range = "无"

        content.append(
            f"├─ 未成交买单: {stats.pending_buy_orders}个 ({buy_range}) ⏳\n", style="green")
        content.append(
            f"├─ 未成交卖单: {stats.pending_sell_orders}个 ({sell_range}) ⏳\n", style="red")

        # 🔥 显示剥头皮止盈订单（更详细）
        if self.coordinator.config.is_scalping_enabled():
            if self.coordinator.scalping_manager and self.coordinator.scalping_manager.is_active():
                tp_order = self.coordinator.scalping_manager.get_current_take_profit_order()
                if tp_order:
                    content.append(f"├─ 🎯 止盈订单: ", style="white")
                    content.append(
                        f"sell {abs(tp_order.amount):.5f}@{self._format_price(tp_order.price)} (Grid {tp_order.grid_id})",
                        style="bold yellow"
                    )
                    content.append("\n")
                else:
                    content.append(f"├─ 🎯 止盈订单: ", style="white")
                    content.append("⚠️ 未挂出", style="red")
                    content.append("\n")
            else:
                # 剥头皮模式启用但未激活
                content.append(f"├─ 🎯 止盈订单: ", style="white")
                content.append("⏳ 待触发", style="yellow")
                content.append("\n")

        content.append(
            f"└─ 总挂单数量: {stats.total_pending_orders}个", style="white")

        return Panel(content, title="📋 订单统计", border_style="blue")

    def _calculate_liquidation_price(self, stats: GridStatistics) -> tuple:
        """
        计算爆仓价格（仅作为风险提示，无实质功能）

        核心思路（更简单合理）：
        1. 假设极端情况：所有未成交的方向性订单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格（净权益 = 0）

        适用于所有模式（包括剥头皮模式）

        爆仓条件: 净权益 ≤ 0
        净权益 = 当前权益 + 持仓未实现盈亏

        Returns:
            (liquidation_price, distance_percent, risk_level, position_value, avg_cost)
            - liquidation_price: 爆仓价格（Decimal），None表示无风险
            - distance_percent: 距离当前价格的百分比（float）
            - risk_level: 风险等级 'safe'/'warning'/'danger'/'N/A'
            - position_value: 网格总仓位价值（Decimal），所有订单的总价值
            - avg_cost: 平均成本（Decimal），加权平均价格
        """
        from decimal import Decimal

        try:
            # 获取未成交订单（从 GridState 的 active_orders 字典获取）
            open_orders = [
                order for order in self.coordinator.state.active_orders.values()
                if order.status == GridOrderStatus.PENDING  # 只获取待成交的订单
            ]

            # 特殊情况: 无持仓且无订单，不计算
            if stats.current_position == 0 and len(open_orders) == 0:
                return (None, 0.0, 'N/A', None, None)

            # 获取当前状态
            current_equity = stats.collateral_balance  # 当前权益
            current_position = stats.current_position  # 当前持仓（正数=多，负数=空）
            average_cost = stats.average_cost  # 平均成本
            current_price = stats.current_price  # 当前价格

            # 判断网格类型（基于当前持仓或订单方向）
            if current_position > 0:
                is_long = True
            elif current_position < 0:
                is_long = False
            else:
                # 无持仓，根据订单判断
                buy_orders = [
                    o for o in open_orders if o.side == GridOrderSide.BUY]
                is_long = len(buy_orders) > 0

            if is_long:
                # 做多网格：计算所有买单成交后的爆仓价格
                liquidation_price, position_value, avg_cost = self._calculate_long_liquidation(
                    current_equity, current_position, average_cost, open_orders
                )
                if liquidation_price:
                    distance_percent = float(
                        (liquidation_price - current_price) / current_price * 100)
                else:
                    # 权益充足，不会爆仓
                    return (None, 0.0, 'safe', position_value, avg_cost)
            else:
                # 做空网格：计算所有卖单成交后的爆仓价格
                liquidation_price, position_value, avg_cost = self._calculate_short_liquidation(
                    current_equity, current_position, average_cost, open_orders
                )
                if liquidation_price:
                    distance_percent = float(
                        (liquidation_price - current_price) / current_price * 100)
                else:
                    # 权益充足，不会爆仓
                    return (None, 0.0, 'safe', position_value, avg_cost)

            # 判断风险等级
            abs_distance = abs(distance_percent)
            if abs_distance > 20:
                risk_level = 'safe'
            elif abs_distance > 10:
                risk_level = 'warning'
            else:
                risk_level = 'danger'

            return (liquidation_price, distance_percent, risk_level, position_value, avg_cost)

        except Exception as e:
            self.logger.error(f"计算爆仓价格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return (None, 0.0, 'N/A', None, None)

    def _calculate_long_liquidation(self, equity: Decimal, position: Decimal,
                                    avg_cost: Decimal, open_orders: list) -> tuple:
        """
        计算做多网格的爆仓价格（极端情况：所有买单成交）

        核心思路：
        1. 假设所有未成交买单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格

        公式推导：
        净权益 = 0
        equity + final_position × (liquidation_price - final_avg_cost) = 0
        => liquidation_price = final_avg_cost - equity / final_position

        Args:
            equity: 当前权益
            position: 当前持仓数量（正数或0）
            avg_cost: 平均成本
            open_orders: 未成交订单列表

        Returns:
            (liquidation_price, position_value, avg_cost)
            - liquidation_price: 爆仓价格（Decimal），None表示权益充足不会爆仓
            - position_value: 网格总仓位价值（Decimal），所有订单的总价值
            - avg_cost: 平均成本（Decimal），加权平均价格
        """
        from decimal import Decimal

        # 获取所有未成交的买单
        buy_orders = [o for o in open_orders if o.side == GridOrderSide.BUY]

        if len(buy_orders) == 0:
            # 无未成交买单
            if position == 0:
                return (None, Decimal('0'), Decimal('0'))  # 无持仓也无订单
            # 有持仓但无订单，直接计算
            position_value = position * avg_cost
            liquidation_price = avg_cost - equity / position
            return (liquidation_price if liquidation_price > 0 else None, position_value, avg_cost)

        # 假设所有买单全部成交，计算最终持仓和平均成本
        total_buy_amount = sum(o.amount for o in buy_orders)
        total_buy_cost = sum(o.amount * o.price for o in buy_orders)

        final_position = position + total_buy_amount

        if position > 0:
            # 有初始持仓
            # 总价值 = 当前持仓价值 + 买单总价值
            position_value = position * avg_cost + total_buy_cost
            final_avg_cost = position_value / final_position
        else:
            # 无初始持仓
            position_value = total_buy_cost
            final_avg_cost = total_buy_cost / final_position

        # 计算爆仓价格
        # equity + final_position × (liquidation_price - final_avg_cost) = 0
        # => liquidation_price = final_avg_cost - equity / final_position
        liquidation_price = final_avg_cost - equity / final_position

        # 如果爆仓价格为负数或极小值，表示权益充足
        if liquidation_price <= 0:
            return (None, position_value, final_avg_cost)

        return (liquidation_price, position_value, final_avg_cost)

    def _calculate_short_liquidation(self, equity: Decimal, position: Decimal,
                                     avg_cost: Decimal, open_orders: list) -> tuple:
        """
        计算做空网格的爆仓价格（极端情况：所有卖单成交）

        核心思路：
        1. 假设所有未成交卖单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格

        公式推导：
        净权益 = 0
        equity + |final_position| × (final_avg_cost - liquidation_price) = 0
        => liquidation_price = final_avg_cost + equity / |final_position|

        Args:
            equity: 当前权益
            position: 当前持仓数量（负数或0）
            avg_cost: 平均成本
            open_orders: 未成交订单列表

        Returns:
            (liquidation_price, position_value, avg_cost)
            - liquidation_price: 爆仓价格（Decimal），None表示权益充足不会爆仓
            - position_value: 网格总仓位价值（Decimal），所有订单的总价值
            - avg_cost: 平均成本（Decimal），加权平均价格
        """
        from decimal import Decimal

        # 获取所有未成交的卖单
        sell_orders = [o for o in open_orders if o.side == GridOrderSide.SELL]

        if len(sell_orders) == 0:
            # 无未成交卖单
            if position == 0:
                return (None, Decimal('0'), Decimal('0'))  # 无持仓也无订单
            # 有持仓但无订单，直接计算
            position_value = abs(position) * avg_cost
            liquidation_price = avg_cost + equity / abs(position)
            return (liquidation_price, position_value, avg_cost)

        # 假设所有卖单全部成交，计算最终持仓和平均成本
        total_sell_amount = sum(o.amount for o in sell_orders)
        total_sell_cost = sum(o.amount * o.price for o in sell_orders)

        position_abs = abs(position)
        final_position_abs = position_abs + total_sell_amount

        if position_abs > 0:
            # 有初始持仓
            # 总价值 = 当前持仓价值 + 卖单总价值
            position_value = position_abs * avg_cost + total_sell_cost
            final_avg_cost = position_value / final_position_abs
        else:
            # 无初始持仓
            position_value = total_sell_cost
            final_avg_cost = total_sell_cost / final_position_abs

        # 计算爆仓价格
        # equity + final_position_abs × (final_avg_cost - liquidation_price) = 0
        # => liquidation_price = final_avg_cost + equity / final_position_abs
        liquidation_price = final_avg_cost + equity / final_position_abs

        return (liquidation_price, position_value, final_avg_cost)

    def create_position_panel(self, stats: GridStatistics) -> Panel:
        """创建持仓信息面板"""
        position_color = "green" if stats.current_position > 0 else "red" if stats.current_position < 0 else "white"
        position_type = "做多" if stats.current_position > 0 else "做空" if stats.current_position < 0 else "空仓"

        content = Text()
        content.append(f"├─ 当前持仓: ", style="white")
        content.append(
            f"{stats.current_position:+.5f} {self.base_currency} ({position_type})      ", style=f"bold {position_color}")

        # 🆕 计算持仓金额（仅作为显示，无实质功能）
        position_value = abs(stats.current_position) * stats.average_cost
        content.append(
            f"平均成本: {self._format_price(stats.average_cost)}  ", style="white")
        content.append(
            f"持仓金额: {self._format_price(position_value)}\n", style="bold cyan")

        # 🔥 显示持仓数据来源（实时）
        data_source = stats.position_data_source
        if "WebSocket" in data_source:
            source_color = "bold green"
            source_icon = "📡"
        elif "REST" in data_source:
            source_color = "bold yellow"
            source_icon = "🔄"
        else:
            source_color = "cyan"
            source_icon = "📊"

        content.append(f"├─ 持仓来源: ", style="white")
        content.append(f"{source_icon} {data_source}\n", style=source_color)

        # 💰 基础资金信息（始终显示）
        # 显示初始本金和当前权益
        content.append(
            f"├─ 初始本金: ${stats.initial_capital:,.3f} USDC      ", style="white")
        content.append(
            f"当前权益: ${stats.collateral_balance:,.3f} USDC\n", style="yellow")

        # 🔥 显示余额数据来源（实时）
        balance_source = stats.balance_data_source
        if "WebSocket" in balance_source:
            balance_source_color = "bold green"
            balance_source_icon = "📡"
        elif "REST" in balance_source:
            balance_source_color = "bold yellow"
            balance_source_icon = "🔄"
        else:
            balance_source_color = "cyan"
            balance_source_icon = "📊"

        content.append(f"├─ 余额来源: ", style="white")
        content.append(
            f"{balance_source_icon} {balance_source}\n", style=balance_source_color)

        # 计算并显示本金盈亏
        profit_loss = stats.capital_profit_loss
        if profit_loss >= 0:
            pl_sign = "+"
            pl_color = "bold green"
            pl_emoji = "📈"
        else:
            pl_sign = ""
            pl_color = "bold red"
            pl_emoji = "📉"

        profit_loss_rate = (profit_loss / stats.initial_capital *
                            100) if stats.initial_capital > 0 else Decimal('0')
        content.append(f"├─ 本金盈亏: ", style="white")
        content.append(f"{pl_emoji} ", style=pl_color)
        content.append(
            f"{pl_sign}${profit_loss:,.3f} ({pl_sign}{profit_loss_rate:.2f}%)\n",
            style=pl_color
        )

        # 🛡️ 本金保护模式状态
        if stats.capital_protection_enabled:
            # 显示本金保护状态
            if stats.capital_protection_active:
                status_text = "🟢 已触发"
                status_color = "bold green"
            else:
                status_text = "⚪ 待触发"
                status_color = "cyan"

            content.append(f"├─ 本金保护: ", style="white")
            content.append(f"{status_text}\n", style=status_color)

        # 🔒 价格锁定模式状态
        if stats.price_lock_enabled:
            # 显示价格锁定状态
            if stats.price_lock_active:
                status_text = "🔒 已激活（冻结中）"
                status_color = "bold yellow"
            else:
                status_text = "⚪ 待触发"
                status_color = "cyan"

            content.append(f"├─ 价格锁定: ", style="white")
            content.append(f"{status_text}      ", style=status_color)
            content.append(
                f"阈值: {self._format_price(stats.price_lock_threshold)}\n", style="white")

        # 💵 余额信息（始终显示）
        content.append(
            f"├─ 现货余额: {self._format_price(stats.spot_balance)} USDC      ", style="white")
        content.append(
            f"订单冻结: {self._format_price(stats.order_locked_balance)} USDC\n", style="white")

        # 🔥 预留币种信息（仅现货且启用预留时显示）
        if self.coordinator.reserve_manager:
            reserve_status = self.coordinator.reserve_manager.get_status()

            # 状态emoji和颜色
            status_emoji = reserve_status['emoji']  # 🟢/🟡/🔴
            health_percent = reserve_status['health_percent']

            if health_percent >= 50:
                health_color = "bold green"
            elif health_percent >= 30:
                health_color = "bold yellow"
            else:
                health_color = "bold red"

            # 预留信息（动态获取币种名称）
            reserve_amount = reserve_status['reserve_amount']
            current_reserve = reserve_status['current_reserve']
            total_consumed = reserve_status['total_consumed']
            base_currency = self.coordinator.reserve_manager.base_currency

            # 🔥 动态显示币种名称（不硬编码BTC）
            content.append(f"├─ 预留{base_currency}: ", style="white")
            content.append(
                f"{status_emoji} {current_reserve:.8f}/{reserve_amount:.8f} {base_currency}  ",
                style=health_color
            )
            content.append(f"健康度: {health_percent:.1f}%\n", style=health_color)

            content.append(f"│  └─ 已消耗: ", style="white")
            content.append(
                f"{total_consumed:.8f} {base_currency}  ",
                style="cyan"
            )
            content.append(
                f"交易次数: {reserve_status['trades_count']}  ",
                style="white"
            )
            content.append(
                f"补充次数: {reserve_status['replenish_count']}\n",
                style="white"
            )

        # 🔥 未实现盈亏已删除（重复显示，盈亏统计面板中已有）

        # 🆕 爆仓风险提示（仅作为风险提示，无实质功能）
        liquidation_price, distance_percent, risk_level, position_value, avg_cost = self._calculate_liquidation_price(
            stats)

        # 🔥 爆仓风险始终是最后一行
        content.append(f"└─ 爆仓风险: ", style="white")

        if risk_level == 'N/A':
            # 剥头皮模式或无持仓
            content.append("N/A", style="cyan")
        elif liquidation_price is None:
            # 网格范围内安全
            content.append("✅ 安全（网格内不会爆仓）", style="bold green")
            if position_value and avg_cost:
                content.append(
                    f" | 仓位=${position_value:,.0f}, 成本={self._format_price(avg_cost)}", style="dim white")
        else:
            # 显示爆仓价格和距离
            direction_icon = "⬇️" if stats.current_position > 0 else "⬆️"

            # 根据风险等级设置颜色
            if risk_level == 'safe':
                risk_color = "green"
                risk_icon = "✅"
            elif risk_level == 'warning':
                risk_color = "yellow"
                risk_icon = "⚠️"
            else:  # danger
                risk_color = "red"
                risk_icon = "🚨"

            content.append(
                f"{risk_icon} {self._format_price(liquidation_price)} ", style=f"bold {risk_color}")
            content.append(
                f"({direction_icon} {abs(distance_percent):.1f}%)", style=risk_color)

            # 显示网格总仓位价值和平均成本（如果存在）
            if position_value and avg_cost:
                content.append(
                    f" | 仓位=${position_value:,.0f}, 成本={self._format_price(avg_cost)}", style="dim white")

        return Panel(content, title="💰 持仓信息", border_style="yellow")

    def create_pnl_panel(self, stats: GridStatistics) -> Panel:
        """创建盈亏统计面板"""
        # 总盈亏颜色
        total_color = "green" if stats.total_profit > 0 else "red" if stats.total_profit < 0 else "white"
        total_sign = "+" if stats.total_profit >= 0 else ""

        # 已实现盈亏颜色
        realized_color = "green" if stats.realized_profit > 0 else "red" if stats.realized_profit < 0 else "white"
        realized_sign = "+" if stats.realized_profit >= 0 else ""

        # 收益率颜色
        rate_color = "green" if stats.profit_rate > 0 else "red" if stats.profit_rate < 0 else "white"
        rate_sign = "+" if stats.profit_rate >= 0 else ""

        content = Text()
        content.append(f"├─ 已实现: ", style="white")
        content.append(
            f"{realized_sign}{self._format_price(stats.realized_profit)}             ", style=f"bold {realized_color}")
        content.append(
            f"网格收益: {realized_sign}{self._format_price(stats.realized_profit)}\n", style=realized_color)

        content.append(f"├─ 未实现: ", style="white")
        unrealized_color = "cyan" if stats.unrealized_profit >= 0 else "red"
        content.append(f"{'+' if stats.unrealized_profit >= 0 else ''}{self._format_price(stats.unrealized_profit)}             ",
                       style=unrealized_color)
        content.append(
            f"手续费: -{self._format_price(stats.total_fees)}\n", style="red")

        content.append(f"└─ 总盈亏: ", style="white")
        content.append(f"{total_sign}{self._format_price(stats.total_profit)} ",
                       style=f"bold {total_color}")
        content.append(
            f"({rate_sign}{stats.profit_rate:.2f}%)  ", style=f"bold {rate_color}")
        content.append(
            f"净收益: {total_sign}{self._format_price(stats.net_profit)}", style=total_color)

        return Panel(content, title="🎯 盈亏统计", border_style="magenta")

    def create_trigger_panel(self, stats: GridStatistics) -> Panel:
        """创建触发统计面板"""
        content = Text()

        content.append(
            f"├─ 买单成交: {stats.filled_buy_count}次               ", style="green")
        content.append(f"卖单成交: {stats.filled_sell_count}次\n", style="red")

        content.append(
            f"├─ 完整循环: {stats.completed_cycles}次 (一买一卖)      ", style="yellow")
        content.append(f"网格利用率: {stats.grid_utilization:.1f}%\n", style="cyan")

        # 平均每次循环收益
        avg_cycle_profit = stats.realized_profit / \
            stats.completed_cycles if stats.completed_cycles > 0 else Decimal(
                '0')
        content.append(f"├─ 平均循环收益: {self._format_price(avg_cycle_profit)}",
                       style="green" if avg_cycle_profit > 0 else "white")
        content.append("\n")

        # 🔥 循环APR预估（显示两种APR：现有APR和实时APR）
        if stats.cycle_apr_estimate > 0 and stats.cycle_apr_formula_data:
            # 现有循环APR（基于全部运行时间）
            apr_color = "bold green" if stats.cycle_apr_estimate > 10 else "yellow" if stats.cycle_apr_estimate > 5 else "white"
            formula_data = stats.cycle_apr_formula_data
            capital_text = f"${formula_data.get('grid_total_capital', 0):,.0f}"
            formula_text = (
                f"${formula_data.get('net_profit_per_cycle', 0):.4f}/次 × "
                f"{formula_data.get('cycles_per_hour', 0):.2f}次/h × "
                f"8766h = ${formula_data.get('annual_profit_amount', 0):,.0f} ÷ {capital_text} → "
                f"{stats.cycle_apr_estimate:.2f}%"
            )
            content.append(f"├─ 现有循环APR: {stats.cycle_apr_estimate:.2f}%",
                           style=apr_color)
            content.append(f"│  ({formula_text})", style="dim")

            # 实时循环APR（基于过去10分钟）
            if stats.realtime_cycle_apr_estimate > 0 and stats.realtime_apr_formula_data:
                realtime_apr_color = "bold green" if stats.realtime_cycle_apr_estimate > 10 else "yellow" if stats.realtime_cycle_apr_estimate > 5 else "white"
                realtime_data = stats.realtime_apr_formula_data
                recent_cycles = realtime_data.get('recent_cycles', 0)
                realtime_formula_text = (
                    f"${realtime_data.get('net_profit_per_cycle', 0):.4f}/次 × "
                    f"{realtime_data.get('cycles_per_hour', 0):.2f}次/h × "
                    f"8766h = ${realtime_data.get('annual_profit_amount', 0):,.0f} ÷ {capital_text} → "
                    f"{stats.realtime_cycle_apr_estimate:.2f}% (近10分钟{recent_cycles}次)"
                )
                content.append(f"└─ 实时循环APR: {stats.realtime_cycle_apr_estimate:.2f}%",
                               style=realtime_apr_color)
                content.append(f"   ({realtime_formula_text})", style="dim")
            else:
                content.append("└─ 实时循环APR: 计算中...", style="dim")
        else:
            content.append("├─ 现有循环APR: 计算中...", style="dim")
            content.append("└─ 实时循环APR: 计算中...", style="dim")

        return Panel(content, title="🎯 触发统计", border_style="cyan")

    def create_recent_trades_table(self, stats: GridStatistics) -> Panel:
        """创建最近成交订单表格"""
        table = Table(show_header=True, header_style="bold magenta", box=None)

        table.add_column("时间", style="cyan", width=10)
        table.add_column("类型", width=4)
        table.add_column("价格", style="yellow", width=12)
        table.add_column("数量", style="white", width=12)
        table.add_column("网格层级", style="blue", width=10)

        # 获取最近交易记录
        trades = self.coordinator.tracker.get_trade_history(self.history_limit)

        for trade in reversed(trades[-5:]):  # 只显示最新5条
            time_str = trade['time'].strftime("%H:%M:%S")
            side = trade['side']
            side_style = "green" if side == "buy" else "red"
            price = self._format_price(trade['price'])
            amount = f"{trade['amount']:.5f} {self.base_currency}"
            grid_text = f"Grid {trade['grid_id']}"

            table.add_row(
                time_str,
                f"[{side_style}]{side.upper()}[/{side_style}]",
                price,
                amount,
                grid_text
            )

        if not trades:
            table.add_row("--", "--", "--", "--", "--")

        return Panel(table, title="📈 最近成交订单 (最新5条)", border_style="green")

    def create_controls_panel(self) -> Panel:
        """创建控制命令面板"""
        content = Text()
        content.append("[P]", style="bold yellow")
        content.append("暂停  ", style="white")
        content.append("[R]", style="bold green")
        content.append("恢复  ", style="white")
        content.append("[S]", style="bold red")
        content.append("停止  ", style="white")
        content.append("[Q]", style="bold cyan")
        content.append("退出", style="white")

        return Panel(content, title="🔧 控制命令", border_style="white")

    def create_layout(self, stats: GridStatistics) -> Layout:
        """创建完整布局"""
        layout = Layout()

        # 🔥 新布局：header + main + logs + controls
        layout.split_column(
            Layout(self.create_header(stats), size=3),
            Layout(name="main"),
            # 🔥 底部日志区域（固定高度23行：1标题+1表头+20数据+1边框）
            Layout(self.create_logs_table(), size=23),
            Layout(self.create_controls_panel(), size=3)
        )

        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )

        layout["left"].split_column(
            Layout(self.create_status_panel(stats)),
            Layout(self.create_orders_panel(stats)),
            Layout(self.create_trigger_panel(stats))
        )

        layout["right"].split_column(
            Layout(self.create_position_panel(stats)),
            Layout(self.create_pnl_panel(stats)),
            Layout(self.create_recent_trades_table(stats))
        )

        return layout

    async def run(self):
        """运行终端界面"""
        self._running = True

        # ✅ 在 Live 上下文之前打印启动信息
        self.console.print("\n[bold green]✅ 网格交易系统终端界面已启动[/bold green]")
        self.console.print("[cyan]提示: 使用 Ctrl+C 停止系统[/cyan]\n")

        # 短暂延迟，让启动信息显示
        await asyncio.sleep(1)

        # ✅ 清屏，避免之前的输出干扰
        self.console.clear()

        # 🔥 修复：先获取初始统计数据，避免在Live上下文初始化时阻塞
        self.console.print("[cyan]📊 正在获取初始统计数据...[/cyan]")
        try:
            initial_stats = await self.coordinator.get_statistics()
            self.console.print("[green]✅ 初始统计数据获取成功[/green]")
        except Exception as e:
            self.console.print(f"[red]❌ 获取初始统计数据失败: {e}[/red]")
            import traceback
            self.console.print(f"[yellow]{traceback.format_exc()}[/yellow]")
            # 使用空的统计数据作为fallback
            from .models import GridStatistics
            initial_stats = GridStatistics()

        self.console.print("[cyan]🖥️  正在启动Rich终端界面...[/cyan]")

        # 🔥 确保控制台日志输出已禁用（在进入Live上下文之前）
        # _setup_log_capture 已经在 __init__ 中调用，这里再次确保
        try:
            self._ensure_console_logging_disabled()
        except Exception as e:
            self.logger.warning(f"禁用控制台日志输出失败: {e}")

        # 🔥 修复：检查是否使用全屏模式（可通过环境变量控制）
        import os
        use_fullscreen = os.getenv(
            'GRID_UI_FULLSCREEN', 'true').lower() == 'true'

        # 🔥 修复：使用try-except捕获Live初始化错误
        try:
            self.console.print(
                f"[yellow]📺 创建Live显示对象（全屏模式: {use_fullscreen}）...[/yellow]")
            live_display = Live(
                self.create_layout(initial_stats),
                refresh_per_second=self.refresh_rate,
                console=self.console,
                screen=use_fullscreen,  # 可配置的全屏模式
                transient=False  # 不使用临时显示
            )
            self.console.print("[green]✅ Live对象创建成功[/green]")
        except Exception as e:
            self.console.print(f"[red]❌ 创建Live对象失败: {e}[/red]")
            import traceback
            self.console.print(f"[yellow]{traceback.format_exc()}[/yellow]")

            # 如果全屏模式失败，尝试非全屏模式
            if use_fullscreen:
                self.console.print("[yellow]⚠️ 尝试使用非全屏模式...[/yellow]")
                try:
                    live_display = Live(
                        self.create_layout(initial_stats),
                        refresh_per_second=self.refresh_rate,
                        console=self.console,
                        screen=False,  # 非全屏模式
                        transient=False
                    )
                    self.console.print("[green]✅ 非全屏模式启动成功[/green]")
                except Exception as e2:
                    self.console.print(f"[red]❌ 非全屏模式也失败: {e2}[/red]")
                    return
            else:
                return

        self.console.print("[cyan]🚀 正在进入Live上下文...[/cyan]")

        # 🔥 添加日志，不使用console.print（因为Live会清除）
        self.logger.info("📺 正在进入Live上下文管理器...")

        with live_display as live:
            self.logger.info("✅ Rich Live上下文已启动，开始主循环")

            # 🔥 添加一个变量来跟踪是否成功进入主循环
            loop_started = False

            try:
                while self._running:
                    # 获取最新统计数据
                    try:
                        if not loop_started:
                            self.logger.info("🔄 主循环首次迭代开始...")

                        # 🔥 添加5秒超时保护
                        try:
                            stats = await asyncio.wait_for(
                                self.coordinator.get_statistics(),
                                timeout=5.0
                            )
                            if not loop_started:
                                self.logger.info("✅ 首次统计数据获取成功")
                        except asyncio.TimeoutError:
                            self.logger.error("⏰ 获取统计数据超时（5秒），跳过本次更新")
                            continue

                        # 更新界面
                        live.update(self.create_layout(stats))

                        if not loop_started:
                            self.logger.info("✅ 首次界面更新成功，UI已启动！")
                            loop_started = True
                    except Exception as e:
                        self.logger.error(f"❌ 更新界面失败: {e}")
                        import traceback
                        self.logger.error(f"详细错误: {traceback.format_exc()}")
                        # 继续运行，不要因为单次更新失败而停止

                    # 休眠
                    await asyncio.sleep(1 / self.refresh_rate)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]收到退出信号...[/yellow]")
                # 🔥 在Live上下文退出前执行清理（此时event loop仍然可用）
                try:
                    self.console.print("[cyan]🧹 正在执行退出清理...[/cyan]")
                    cleanup_result = await self.coordinator.cleanup_on_exit()
                    if cleanup_result:
                        self.console.print("[green]✅ 退出清理完成[/green]")
                    else:
                        self.console.print("[yellow]⚠️ 退出清理部分失败[/yellow]")
                except Exception as cleanup_error:
                    self.logger.error(
                        f"❌ 退出清理异常: {cleanup_error}", exc_info=True)
                    self.console.print(f"[red]❌ 退出清理异常: {cleanup_error}[/red]")
            finally:
                self._running = False

    def _cleanup_log_capture(self):
        """清理日志捕获 - 移除UI日志处理器"""
        try:
            if self.ui_log_handler:
                # 从所有logger中移除handler
                key_modules = [
                    'core.adapters.exchanges.adapters.lighter_rest',
                    'core.adapters.exchanges.adapters.lighter_websocket',
                    'core.adapters.exchanges.adapters.lighter_websocket.price',
                    'core.adapters.exchanges.adapters.lighter_base',
                    'core.services.grid.implementations.grid_engine_impl',
                    'core.services.grid.coordinator.grid_coordinator',
                    'core.services.grid.implementations.order_health_checker',
                ]

                for module_name in key_modules:
                    module_logger = logging.getLogger(module_name)
                    if self.ui_log_handler in module_logger.handlers:
                        module_logger.removeHandler(self.ui_log_handler)
                    # 恢复传播（如果需要）
                    # module_logger.propagate = True

                self.ui_log_handler = None
                self.log_queue.clear()
                self._removed_console_handlers.clear()
        except Exception as e:
            self.logger.warning(f"清理日志捕获失败: {e}")

    def stop(self):
        """停止终端界面"""
        self._running = False
        self._cleanup_log_capture()
