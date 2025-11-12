#!/usr/bin/env python3
"""
套利监控系统 - 主程序

实时监控多交易所价差和资金费率，识别套利机会。
"""

import asyncio
import sys
import signal
import logging
import yaml
from pathlib import Path
from decimal import Decimal
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Any
from logging.handlers import RotatingFileHandler

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.live import Live
from rich.layout import Layout

from core.services.arbitrage_monitor import ArbitrageMonitorService, ArbitrageConfig
from core.adapters.exchanges.factory import get_exchange_factory
# 🔥 极简符号转换器（套利系统专用）
from core.services.arbitrage_monitor.utils import SimpleSymbolConverter


class UILogHandler(logging.Handler):
    """
    UI日志处理器 - 将日志捕获到队列中供UI显示
    
    关键特性：
    - 线程安全（使用deque）
    - 固定大小队列（自动淘汰旧日志）
    - 简化格式（移除冗余信息）
    """
    
    def __init__(self, log_queue: deque, max_size: int = 20):
        super().__init__()
        self.log_queue = log_queue
        self.max_size = max_size
        
    def emit(self, record: logging.LogRecord):
        """捕获日志记录"""
        try:
            # 格式化日志消息（简化格式）
            msg = self.format(record)
            
            # 添加到队列（保持最新N条）
            self.log_queue.append({
                'time': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                'level': record.levelname,
                'module': record.name.split('.')[-1] if '.' in record.name else record.name,
                'message': msg,
            })
            
            # 保持队列大小
            while len(self.log_queue) > self.max_size:
                self.log_queue.popleft()
        except Exception:
            # 忽略处理日志时的错误，避免死循环
            pass


class ArbitrageMonitorApp:
    """套利监控应用"""
    
    def __init__(self, config_path: str = "config/arbitrage/monitor.yaml"):
        self.config_path = config_path
        self.config = None
        self.adapters = {}
        self.monitor_service = None
        self.symbol_converter = None  # 🔥 符号转换服务
        self.console = Console()
        self.running = False
        
        # 🔥 日志捕获系统
        self.log_queue: deque = deque(maxlen=20)
        self.ui_log_handler: Optional[UILogHandler] = None
        
        # 🔥 排序缓存系统（每分钟更新一次排序）
        self.last_sort_time: Optional[datetime] = None
        self.sorted_symbols_cache: list = []  # 缓存排序后的symbol顺序
        self.sort_interval_seconds: int = 60  # 排序更新间隔（秒）
        
        # 🔥 费率差异持续时间跟踪系统
        self.rate_diff_tracking: Dict[str, Dict[str, Any]] = {}  # {symbol: {start_time, last_diff}}
        self.rate_diff_threshold: float = 50.0  # 年化费率差阈值（百分比）
        
        # 设置日志（先基础配置）
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger("arbitrage_monitor")
        
        # 🔥 设置日志捕获（在初始化后会被禁用控制台输出）
        self._setup_log_capture()
    
    def _setup_log_capture(self):
        """设置日志捕获并禁用控制台输出"""
        try:
            # 🔥 创建日志目录（如果不存在）
            log_dir = Path(__file__).parent / "logs"
            log_dir.mkdir(exist_ok=True)
            
            # 🔥 创建文件日志处理器（写入文件）
            log_file = log_dir / "arbitrage_monitor.log"
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            
            # 创建UI日志处理器
            self.ui_log_handler = UILogHandler(self.log_queue, max_size=20)
            self.ui_log_handler.setLevel(logging.INFO)
            
            # 简化日志格式（UI表格会显示时间、级别、模块）
            formatter = logging.Formatter('%(message)s')
            self.ui_log_handler.setFormatter(formatter)
            
            # 关键模块列表（需要捕获日志的模块）
            key_modules = [
                'arbitrage_monitor',
                'core.services.arbitrage_monitor',
                'core.adapters.exchanges.adapters.edgex_websocket',
                'core.adapters.exchanges.adapters.lighter_websocket',
            ]
            
            # 🔥 为root logger添加文件处理器（捕获所有日志）
            root_logger = logging.getLogger()
            if file_handler not in root_logger.handlers:
                root_logger.addHandler(file_handler)
            
            # 为每个关键模块配置日志
            for module_name in key_modules:
                module_logger = logging.getLogger(module_name)
                
                # 🔥 添加文件日志处理器（写入文件）
                if file_handler not in module_logger.handlers:
                    module_logger.addHandler(file_handler)
                
                # 添加UI日志处理器
                if self.ui_log_handler not in module_logger.handlers:
                    module_logger.addHandler(self.ui_log_handler)
                
        except Exception as e:
            self.logger.warning(f"设置日志捕获失败: {e}")
    
    def _disable_console_logging(self):
        """禁用控制台日志输出（在UI启动前调用）"""
        try:
            key_modules = [
                'arbitrage_monitor',
                'core.services.arbitrage_monitor',
                'core.adapters.exchanges.adapters.edgex_websocket',
                'core.adapters.exchanges.adapters.lighter_websocket',
            ]
            
            # 禁用root logger的控制台输出
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and \
                   not isinstance(handler, RotatingFileHandler):
                    root_logger.removeHandler(handler)
            
            # 为每个关键模块移除控制台输出
            for module_name in key_modules:
                module_logger = logging.getLogger(module_name)
                
                # 移除控制台输出handler（保留文件输出）
                for handler in module_logger.handlers[:]:
                    if isinstance(handler, logging.StreamHandler) and \
                       not isinstance(handler, RotatingFileHandler):
                        module_logger.removeHandler(handler)
                
                # 禁用传播到root logger
                module_logger.propagate = False
                
        except Exception as e:
            print(f"禁用控制台日志失败: {e}")
    
    def _format_log_message(self, message: str) -> str:
        """格式化日志消息（移除emoji）"""
        emoji_map = {
            '✅ ': '', '❌ ': '', '⚠️ ': '', '📝 ': '', 
            '📨 ': '', '🔄 ': '', '🔗 ': '', '💓 ': '',
            '📦 ': '', '📊 ': '', '🔍 ': '', '🚀 ': '',
            '🔌 ': '', '⚡ ': '', '🎯 ': ''
        }
        for emoji, replacement in emoji_map.items():
            message = message.replace(emoji, replacement)
        return message
    
    def _format_duration(self, seconds: float) -> str:
        """
        格式化持续时间为 1D1H1M 格式
        
        Args:
            seconds: 持续秒数
            
        Returns:
            格式化的时间字符串，例如：1D2H30M
        """
        if seconds < 60:
            return "-"  # 少于1分钟不显示
        
        total_seconds = int(seconds)
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}D")
        if hours > 0:
            parts.append(f"{hours}H")
        if minutes > 0:
            parts.append(f"{minutes}M")
        
        return "".join(parts) if parts else "-"
    
    def _update_rate_diff_tracking(self, symbol: str, rate_diff_annual: float):
        """
        更新费率差异持续时间跟踪
        
        Args:
            symbol: 交易对
            rate_diff_annual: 年化费率差（百分比）
        """
        current_time = datetime.now()
        abs_diff = abs(rate_diff_annual)
        
        if abs_diff >= self.rate_diff_threshold:
            # 费率差大于阈值
            if symbol not in self.rate_diff_tracking:
                # 首次超过阈值，开始记录
                self.rate_diff_tracking[symbol] = {
                    'start_time': current_time,
                    'last_diff': rate_diff_annual
                }
            else:
                # 更新最后差异值
                self.rate_diff_tracking[symbol]['last_diff'] = rate_diff_annual
        else:
            # 费率差低于阈值，清除记录
            if symbol in self.rate_diff_tracking:
                del self.rate_diff_tracking[symbol]
    
    def _get_rate_diff_duration(self, symbol: str) -> str:
        """
        获取费率差异持续时间
        
        Args:
            symbol: 交易对
            
        Returns:
            格式化的持续时间字符串
        """
        if symbol not in self.rate_diff_tracking:
            return "-"
        
        start_time = self.rate_diff_tracking[symbol]['start_time']
        duration_seconds = (datetime.now() - start_time).total_seconds()
        
        return self._format_duration(duration_seconds)
    
    def load_config(self):
        """加载配置"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        self.logger.info("✅ 配置加载成功")
    
    async def initialize(self):
        """初始化"""
        print("\n" + "="*60)
        print("🚀 套利监控系统启动中...")
        print("="*60 + "\n")
        
        # 🔥 第1步：创建极简符号转换器（无需配置文件）
        self.symbol_converter = SimpleSymbolConverter(self.logger)
        self.logger.info("✅ 极简符号转换器就绪（~150行代码，零冗余）")
        
        # 第2步：初始化交易所适配器
        self.logger.info("🔌 初始化交易所适配器...")
        print("🔌 正在初始化交易所适配器...\n")
        
        # 🔥 用于收集所有交易所支持的symbol
        exchange_symbols = {}
        
        factory = get_exchange_factory()
        
        for exchange_name in self.config['exchanges']:
            adapter = None
            try:
                # 尝试从配置文件加载（包含API密钥）
                try:
                    adapter = await factory.create_adapter(exchange_name)
                    await adapter.connect()
                    self.adapters[exchange_name] = adapter
                    self.logger.info(f"✅ {exchange_name} 初始化成功（使用配置文件）")
                except Exception as config_error:
                    # 如果配置文件失败，尝试"公开数据模式"（无需API密钥）
                    self.logger.warning(f"⚠️  {exchange_name} 配置文件加载失败: {config_error}")
                    self.logger.info(f"🔄 尝试公开数据模式...")
                    
                    # 创建虚拟配置（用于公开数据访问）
                    from core.adapters.exchanges.interface import ExchangeConfig
                    from core.adapters.exchanges.models import ExchangeType
                    
                    dummy_config = ExchangeConfig(
                        exchange_id=exchange_name,
                        name=exchange_name.capitalize(),
                        exchange_type=ExchangeType.PERPETUAL,  # 套利监控主要用永续合约
                        api_key="public_data_only",
                        api_secret="public_data_only",
                        testnet=False
                    )
                    
                    # 根据交易所类型创建适配器
                    if exchange_name == 'backpack':
                        from core.adapters.exchanges.adapters.backpack import BackpackAdapter
                        adapter = BackpackAdapter(dummy_config)
                    elif exchange_name == 'edgex':
                        from core.adapters.exchanges.adapters.edgex import EdgeXAdapter
                        adapter = EdgeXAdapter(dummy_config)
                    elif exchange_name == 'lighter':
                        from core.adapters.exchanges.adapters.lighter import LighterAdapter
                        adapter = LighterAdapter(dummy_config)
                    else:
                        raise ValueError(f"不支持的交易所: {exchange_name}")
                    
                    # 只连接WebSocket（不进行认证）
                    await adapter.connect()
                    self.adapters[exchange_name] = adapter
                    self.logger.info(f"✅ {exchange_name} 初始化成功（公开数据模式）")
                
                # 🔥 获取该交易所支持的symbol（转换为标准格式）- 无论哪种模式都执行
                if adapter:
                    try:
                        # 🔥 EdgeX特殊处理：主动获取交易对
                        if exchange_name == 'edgex':
                            self.logger.info("⏳ 正在获取EdgeX支持的交易对...")
                            print("⏳ 正在获取EdgeX交易对列表（约10秒）...")
                            # 调用 fetch_supported_symbols() 来真正获取交易对
                            if hasattr(adapter, 'websocket') and hasattr(adapter.websocket, 'fetch_supported_symbols'):
                                await adapter.websocket.fetch_supported_symbols()
                            elif hasattr(adapter, '_websocket') and hasattr(adapter._websocket, 'fetch_supported_symbols'):
                                await adapter._websocket.fetch_supported_symbols()
                            else:
                                await asyncio.sleep(12)  # 降级方案：等待metadata自动到达
                        
                        raw_symbols = await adapter.get_supported_symbols()
                        self.logger.info(f"🔍 {exchange_name} 原始symbols数量: {len(raw_symbols)}")
                        
                        if len(raw_symbols) == 0:
                            print(f"❌ {exchange_name}: 未获取到交易对！")
                            self.logger.warning(f"{exchange_name} 未获取到任何交易对")
                        else:
                            # 🔥 显示前5个原始symbol（调试用）
                            sample_raw = raw_symbols[:5] if len(raw_symbols) >= 5 else raw_symbols
                            print(f"   📋 前5个原始symbol: {', '.join(sample_raw)}")
                        
                        standard_symbols = set()
                        for raw_symbol in raw_symbols:
                            try:
                                std_symbol = self.symbol_converter.convert_from_exchange(raw_symbol, exchange_name)
                                if std_symbol.endswith('-PERP') or std_symbol.endswith('-USDC-PERP'):  # 永续合约
                                    standard_symbols.add(std_symbol)
                            except Exception as convert_error:
                                # 转换失败，忽略
                                pass
                        
                        exchange_symbols[exchange_name] = standard_symbols
                        self.logger.info(f"📊 {exchange_name} 支持 {len(standard_symbols)} 个永续合约")
                        
                        if len(standard_symbols) > 0:
                            print(f"✅ {exchange_name}: 发现 {len(raw_symbols)} 个交易对 → {len(standard_symbols)} 个永续合约")
                        else:
                            print(f"⚠️  {exchange_name}: {len(raw_symbols)} 个交易对中没有永续合约")
                    except Exception as e:
                        self.logger.error(f"⚠️  无法获取 {exchange_name} 支持的symbol: {e}")
                        print(f"❌ {exchange_name}: 获取symbol失败 - {e}")  # 临时调试
                        import traceback
                        self.logger.error(traceback.format_exc())
                        exchange_symbols[exchange_name] = set()
                    
            except Exception as e:
                self.logger.error(f"❌ {exchange_name} 初始化失败: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
        
        if not self.adapters:
            raise RuntimeError("❌ 没有可用的交易所适配器，请检查：\n"
                             "  1. 配置文件是否正确：config/exchanges/\n"
                             "  2. API密钥是否有效\n"
                             "  3. 网络连接是否正常")
        
        # 🔥 第3步：计算重叠的symbol
        print(f"\n📊 交易所symbol统计:")
        self.logger.info(f"📊 exchange_symbols 字典内容: {list(exchange_symbols.keys())}")
        for ex_name, symbols in exchange_symbols.items():
            print(f"   {ex_name}: {len(symbols)} 个永续合约")
            self.logger.info(f"   - {ex_name}: {len(symbols)} 个symbol")
        
        if len(exchange_symbols) >= 2:
            # 计算交集
            common_symbols = set.intersection(*exchange_symbols.values()) if exchange_symbols else set()
            print(f"\n🔍 发现 {len(common_symbols)} 个重叠永续合约")
            self.logger.info(f"🔍 发现 {len(common_symbols)} 个重叠symbol")
            
            if common_symbols:
                # 显示前10个重叠symbol
                sample_common = sorted(list(common_symbols))[:10]
                print(f"   前10个: {', '.join(sample_common)}")
                self.logger.info(f"   示例: {', '.join(sample_common)}")
            
            # 如果有重叠symbol，使用它们；否则使用配置文件中的
            if common_symbols:
                # 排序（不限制数量）
                sorted_symbols = sorted(list(common_symbols))
                self.config['symbols'] = sorted_symbols  # 使用所有重叠symbol
                print(f"✅ 最终监控 {len(self.config['symbols'])} 个交易对\n")
                self.logger.info(f"✅ 使用 {len(self.config['symbols'])} 个重叠symbol")
                self.logger.info(f"   前10个: {', '.join(self.config['symbols'][:10])}")
            else:
                print("⚠️  没有发现重叠symbol，使用配置文件中的symbol\n")
                self.logger.warning("⚠️  没有发现重叠symbol，使用配置文件中的symbol")
        else:
            print(f"⚠️  交易所数量不足（{len(exchange_symbols)}），需要至少2个\n")
            self.logger.warning(f"⚠️  exchange_symbols 数量不足（{len(exchange_symbols)}），需要至少2个")
        
        # 第4步：创建监控服务
        print(f"\n🔧 创建监控服务配置:")
        print(f"   交易所: {list(self.adapters.keys())}")
        print(f"   监控交易对数量: {len(self.config['symbols'])} 个")
        print(f"   前10个: {', '.join(self.config['symbols'][:10])}")
        
        arbitrage_config = ArbitrageConfig(
            exchanges=list(self.adapters.keys()),
            symbols=self.config['symbols'],
            price_spread_threshold=Decimal(str(self.config['thresholds']['price_spread'])),
            funding_rate_threshold=Decimal(str(self.config['thresholds']['funding_rate'])),
            min_score_threshold=Decimal(str(self.config['thresholds']['min_score'])),
            update_interval=self.config['monitoring']['update_interval'],
            refresh_rate=self.config['display']['refresh_rate'],
            max_opportunities=self.config['display']['max_opportunities'],
            show_all_prices=self.config['display']['show_all_prices']
        )
        
        self.monitor_service = ArbitrageMonitorService(
            adapters=self.adapters,
            config=arbitrage_config,
            logger=self.logger,
            symbol_converter=self.symbol_converter  # 🔥 传递符号转换服务
        )
        
        await self.monitor_service.start()
        self.logger.info("✅ 套利监控服务启动成功")
    
    def _get_price_precision(self, price: float) -> int:
        """
        根据价格大小动态决定显示精度
        
        Args:
            price: 价格
            
        Returns:
            小数位数
        """
        if price >= 1000:
            return 2  # 大币种：BTC, ETH 等 → 100,204.00
        elif price >= 10:
            return 3  # 中等价格 → 39.123
        elif price >= 1:
            return 4  # 接近1的价格 → 2.8456
        elif price >= 0.01:
            return 6  # 小价格 → 0.012345
        else:
            return 8  # 极小价格 → 0.00012345
    
    def create_logs_table(self) -> Panel:
        """创建日志表格"""
        table = Table(show_header=True, box=None, padding=(0, 1))
        
        # 定义列
        table.add_column("时间", style="dim", width=8, no_wrap=True)
        table.add_column("级别", style="bold", width=6, no_wrap=True)
        table.add_column("模块", style="cyan", width=15, no_wrap=True)
        table.add_column("消息", style="white")  # 无长度限制，完整显示
        
        # 如果没有日志，显示提示
        if not self.log_queue:
            table.add_row("--:--:--", "--", "等待日志", "[dim]暂无日志[/dim]")
        else:
            # 显示最新20条日志
            for log_entry in list(self.log_queue):
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
                
                # 格式化消息（移除emoji）
                message = self._format_log_message(log_entry['message'])
                
                table.add_row(
                    log_entry['time'],
                    level_style,
                    log_entry['module'][:15],  # 限制模块名长度
                    message
                )
        
        # 返回Panel（固定高度：1标题+1表头+20数据+1边框=23）
        return Panel(
            table, 
            title="📋 最新日志 (最新20条)", 
            border_style="blue", 
            height=23
        )
    
    def create_header(self) -> Panel:
        """创建标题栏"""
        title_text = Text()
        title_text.append("🎯 ", style="bold yellow")
        title_text.append("套利监控系统", style="bold green")
        title_text.append(" - ", style="dim")
        title_text.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="bold cyan")
        
        # 🔥 显示下次排序倒计时
        if self.last_sort_time is not None:
            time_since_sort = (datetime.now() - self.last_sort_time).total_seconds()
            time_until_next_sort = self.sort_interval_seconds - time_since_sort
            if time_until_next_sort > 0:
                title_text.append(" | ", style="dim")
                title_text.append(f"下次排序: {int(time_until_next_sort)}秒", style="bold magenta")
            else:
                title_text.append(" | ", style="dim")
                title_text.append("正在排序...", style="bold yellow")
        
        return Panel(
            title_text,
            border_style="green",
            padding=(0, 1)
        )
    
    def create_controls_panel(self) -> Panel:
        """创建控制命令面板"""
        controls_text = Text()
        controls_text.append("按 ", style="dim")
        controls_text.append("Ctrl+C", style="bold red")
        controls_text.append(" 退出程序", style="dim")
        
        return Panel(
            controls_text,
            border_style="white",
            padding=(0, 1)
        )
    
    def generate_display(self) -> Layout:
        """生成显示内容（使用Layout布局）"""
        layout = Layout()
        
        if not self.monitor_service:
            # 初始化布局
            layout.split_column(
                Layout(self.create_header(), size=3),
                Layout(Panel("等待初始化...", border_style="yellow")),
                Layout(self.create_logs_table(), size=23),
                Layout(self.create_controls_panel(), size=3)
            )
            return layout
        
        # 统计信息
        stats = self.monitor_service.get_statistics()
        stats_text = Text()
        stats_text.append(f"交易所: {stats['total_exchanges']}  ", style="bold cyan")
        stats_text.append(f"监控: {stats['monitored_symbols']}对  ", style="bold green")
        stats_text.append(f"机会: {stats['active_opportunities']}  ", style="bold yellow")
        stats_text.append(f"数据: {stats['ticker_data_count']}", style="bold magenta")
        # 🔥 显示配置的symbol数量（调试用）
        if hasattr(self, 'config') and 'symbols' in self.config:
            stats_text.append(f" [配置:{len(self.config['symbols'])}]", style="dim")
        
        # 套利机会表格
        opportunities = self.monitor_service.get_opportunities()
        
        # 🔥 在标题中显示总机会数和显示数量
        opp_count = len(opportunities) if opportunities else 0
        table_title = f"🎯 套利机会 (显示前5条/共{opp_count}条) - {datetime.now().strftime('%H:%M:%S')}"
        
        table = Table(
            title=table_title,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("交易对", style="cyan", width=15)
        table.add_column("类型", style="yellow", width=10)
        table.add_column("买入", style="green", width=10)
        table.add_column("卖出", style="red", width=10)
        table.add_column("价差%", style="bold yellow", justify="right", width=10)
        table.add_column("评分", style="bold magenta", justify="right", width=10)
        
        if opportunities:
            # 🔥 只显示前5条套利机会，为价格表格留出空间
            for opp in opportunities[:5]:
                type_str = "价差" if opp.opportunity_type == "price_spread" else \
                          "费率" if opp.opportunity_type == "funding_rate" else "组合"
                
                if opp.price_spread:
                    buy_ex = opp.price_spread.exchange_buy
                    sell_ex = opp.price_spread.exchange_sell
                    spread_pct = f"{float(opp.price_spread.spread_pct):.3f}%"
                elif opp.funding_rate_spread:
                    buy_ex = opp.funding_rate_spread.exchange_low
                    sell_ex = opp.funding_rate_spread.exchange_high
                    spread_pct = f"{float(opp.funding_rate_spread.spread_abs * 100):.3f}%"
                else:
                    buy_ex = sell_ex = spread_pct = "-"
                
                score = f"{float(opp.score):.4f}"
                style = "bold green" if opp.score >= Decimal("0.01") else "green" if opp.score >= Decimal("0.005") else "white"
                
                table.add_row(opp.symbol, type_str, buy_ex, sell_ex, spread_pct, score, style=style)
        else:
            table.add_row("暂无套利机会", "-", "-", "-", "-", "-", style="dim")
        
        # 价格表格
        if self.config['display']['show_all_prices']:
            # 🔥 添加数据就绪状态提示
            total_symbols = len(self.config['symbols'])
            ready_symbols = len([s for s in self.config['symbols'] if self.monitor_service.get_current_prices(s)])
            data_ready_pct = (ready_symbols / total_symbols * 100) if total_symbols > 0 else 0
            
            if data_ready_pct < 100:
                price_table_title = f"💰 实时价格 & 资金费率 [数据准备中: {ready_symbols}/{total_symbols} ({data_ready_pct:.0f}%)]"
            else:
                price_table_title = "💰 实时价格 & 资金费率"
            
            price_table = Table(title=price_table_title, box=box.SIMPLE, show_header=True, header_style="bold cyan")
            price_table.add_column("交易对", style="cyan", width=15)
            
            for exchange in self.config['exchanges']:
                price_table.add_column(f"{exchange.upper()}\n价格", justify="right", width=12)
                if self.config['display'].get('show_funding_rates', True):
                    price_table.add_column(f"{exchange.upper()}\n8h/年化", justify="right", width=16)
            
            price_table.add_column("价差%", style="yellow", justify="right", width=10)
            
            # 🔥 添加费率差列（8小时 + 年化）
            if self.config['display'].get('show_funding_rates', True) and len(self.config['exchanges']) >= 2:
                price_table.add_column("费率差\n8h/年化", style="magenta", justify="right", width=16)
                # 🔥 添加持续时间列（当年化差>50%时显示）
                price_table.add_column("持续\n时间", style="bold red", justify="center", width=8)
                # 🔥 添加同向列
                price_table.add_column("同向", style="bold cyan", justify="center", width=6)
            
            # 🔥 第1步：收集所有数据并计算价差（实时数据）
            symbol_data_dict = {}  # 使用dict方便按symbol查找
            
            for symbol in self.config['symbols']:
                prices = self.monitor_service.get_current_prices(symbol)
                if not prices:
                    continue
                
                # 获取funding_rates
                funding_rates = {}
                ticker_data = self.monitor_service.ticker_data
                for exchange in self.config['exchanges']:
                    if exchange in ticker_data and symbol in ticker_data[exchange]:
                        funding_rate = ticker_data[exchange][symbol].funding_rate
                        funding_rates[exchange] = funding_rate
                
                price_values = []
                for exchange in self.config['exchanges']:
                    price = prices.get(exchange)
                    if price:
                        price_values.append(price)
                
                # 计算价差用于排序
                spread_value = 0
                if len(price_values) >= 2:
                    max_price = max(price_values)
                    min_price = min(price_values)
                    spread_value = float(((max_price - min_price) / min_price) * Decimal("100"))
                
                # 保存数据（使用dict，key为symbol）
                symbol_data_dict[symbol] = {
                    'symbol': symbol,
                    'prices': prices,
                    'funding_rates': funding_rates,
                    'spread_value': spread_value
                }
            
            # 🔥 第2步：检查是否需要重新排序（每60秒更新一次排序）
            current_time = datetime.now()
            need_resort = False
            
            if self.last_sort_time is None:
                # 首次运行，需要排序
                need_resort = True
                self.logger.info("首次排序价格表格")
            else:
                # 检查距离上次排序是否超过60秒
                time_since_last_sort = (current_time - self.last_sort_time).total_seconds()
                if time_since_last_sort >= self.sort_interval_seconds:
                    need_resort = True
                    self.logger.info(f"距离上次排序已过 {time_since_last_sort:.0f} 秒，重新排序")
            
            # 🔥 优化：如果有数据且需要排序，立即排序；如果是首次且数据少，也先排序显示
            if len(symbol_data_dict) > 0 and (need_resort or (self.last_sort_time is None and len(symbol_data_dict) >= 3)):
                # 需要重新排序：按价差从高到低排序
                symbol_data_list = list(symbol_data_dict.values())
                symbol_data_list.sort(key=lambda x: x['spread_value'], reverse=True)
                
                # 更新缓存
                self.sorted_symbols_cache = [data['symbol'] for data in symbol_data_list]
                self.last_sort_time = current_time
                
                self.logger.info(f"排序完成，共{len(self.sorted_symbols_cache)}个交易对，前5名: {', '.join(self.sorted_symbols_cache[:5])}")
            
            # 🔥 第3步：按缓存的排序顺序显示（数据是实时的）
            # 如果缓存为空，使用当前可用数据的顺序
            symbols_to_display = self.sorted_symbols_cache if self.sorted_symbols_cache else list(symbol_data_dict.keys())
            
            for symbol in symbols_to_display:
                # 从dict中获取该symbol的最新数据
                if symbol not in symbol_data_dict:
                    continue
                
                data = symbol_data_dict[symbol]
                symbol = data['symbol']
                prices = data['prices']
                funding_rates = data['funding_rates']
                
                price_values = []
                funding_rate_values = []
                row = []  # 初始化row（不包含symbol，最后再添加）
                
                # 🔥 预先计算费率差，用于判断是否高亮显示
                has_high_rate_diff = False
                
                # 🔥 第一步：收集价格和资金费率数据
                for exchange in self.config['exchanges']:
                    price = prices.get(exchange)
                    if price:
                        price_values.append(price)
                    else:
                        price_values.append(None)
                    
                    if self.config['display'].get('show_funding_rates', True):
                        funding_rate = funding_rates.get(exchange)
                        funding_rate_values.append(funding_rate)
                
                # 🔥 第二步：预先计算同向和做多/做空交易所
                same_direction = False
                price_long_idx = None
                price_short_idx = None
                
                if (len(self.config['exchanges']) >= 2 and 
                    len([p for p in price_values if p is not None]) >= 2 and
                    len([fr for fr in funding_rate_values if fr is not None]) >= 2):
                    
                    # 1. 价差方向：价格低的做多
                    valid_prices = [(i, p) for i, p in enumerate(price_values) if p is not None]
                    if len(valid_prices) >= 2:
                        min_price_tuple = min(valid_prices, key=lambda x: x[1])
                        max_price_tuple = max(valid_prices, key=lambda x: x[1])
                        price_long_idx = min_price_tuple[0]
                        price_short_idx = max_price_tuple[0]
                        price_long_ex = self.config['exchanges'][price_long_idx]
                        
                        # 2. 资金费率方向：费率低（数学上小）的做多
                        valid_frs = [(i, fr) for i, fr in enumerate(funding_rate_values) if fr is not None]
                        if len(valid_frs) >= 2:
                            min_fr_tuple = min(valid_frs, key=lambda x: x[1])
                            fr_long_ex = self.config['exchanges'][min_fr_tuple[0]]
                            
                            # 3. 判断是否同向
                            if price_long_ex == fr_long_ex:
                                same_direction = True
                
                # 🔥 第三步：构建row，根据同向应用颜色
                for idx, exchange in enumerate(self.config['exchanges']):
                    price = price_values[idx] if idx < len(price_values) else None
                    
                    if price is not None:
                        # 🔥 动态精度：根据价格大小决定显示位数
                        precision = self._get_price_precision(float(price))
                        price_str = f"{float(price):,.{precision}f}"
                        
                        # 🔥 根据同向判断应用颜色
                        if same_direction:
                            if idx == price_long_idx:
                                price_str = f"[green]{price_str}[/green]"  # 做多 = 绿色
                            elif idx == price_short_idx:
                                price_str = f"[red]{price_str}[/red]"      # 做空 = 红色
                        
                        row.append(price_str)
                    else:
                        row.append("-")
                    
                    # 添加资金费率（8小时 + 年化）
                    if self.config['display'].get('show_funding_rates', True):
                        funding_rate = funding_rate_values[idx] if idx < len(funding_rate_values) else None
                        if funding_rate is not None:
                            # 8小时费率
                            fr_8h = float(funding_rate * 100)
                            # 年化费率：8小时 × 3次/天 × 365天 = × 1095
                            fr_annual = fr_8h * 1095
                            row.append(f"{fr_8h:.4f}%/{fr_annual:.1f}%")
                        else:
                            row.append("-")
                
                # 🔥 第四步：计算价差
                valid_price_values = [p for p in price_values if p is not None]
                if len(valid_price_values) >= 2:
                    max_price = max(valid_price_values)
                    min_price = min(valid_price_values)
                    spread_pct = ((max_price - min_price) / min_price) * Decimal("100")
                    row.append(f"{float(spread_pct):.3f}%")
                else:
                    row.append("-")
                
                # 🔥 第五步：费率差计算（保留正负号，显示8小时 + 年化）
                if self.config['display'].get('show_funding_rates', True) and len(self.config['exchanges']) >= 2:
                    valid_fr_values = [fr for fr in funding_rate_values if fr is not None]
                    if len(valid_fr_values) >= 2 and len(funding_rate_values) >= 2:
                        fr1 = funding_rate_values[0]  # EdgeX (已转换为8小时)
                        fr2 = funding_rate_values[1]  # Lighter (8小时)
                        
                        if fr1 is not None and fr2 is not None:
                            # 直接相减，保留正负号
                            # 正数：EdgeX费率更高（EdgeX空头收费，Lighter空头付费）
                            # 负数：Lighter费率更高（Lighter空头收费，EdgeX空头付费）
                            rate_diff = fr1 - fr2
                            
                            # 8小时差值
                            diff_8h = float(rate_diff * 100)
                            # 年化差值：8小时差值 × 1095
                            diff_annual = diff_8h * 1095
                            
                            # 🔥 判断是否有高费率差（年化≥50%）
                            if abs(diff_annual) >= self.rate_diff_threshold:
                                has_high_rate_diff = True
                            
                            # 🔥 更新费率差异跟踪
                            self._update_rate_diff_tracking(symbol, diff_annual)
                            
                            # 显示时保留符号
                            sign = "+" if rate_diff >= 0 else ""
                            row.append(f"{sign}{diff_8h:.4f}%/{sign}{diff_annual:.1f}%")
                            
                            # 🔥 添加持续时间显示
                            duration_str = self._get_rate_diff_duration(symbol)
                            row.append(duration_str)
                            
                            # 🔥 添加同向显示（已在前面计算）
                            row.append("是" if same_direction else "")
                        else:
                            row.append("-")
                            row.append("-")  # 持续时间列
                            row.append("")   # 同向列
                    else:
                        row.append("-")
                        row.append("-")  # 持续时间列
                        row.append("")   # 同向列
                
                # 🔥 构建完整的row，交易对名称根据费率差高亮
                symbol_display = f"[bold green]{symbol}[/bold green]" if has_high_rate_diff else symbol
                final_row = [symbol_display] + row
                
                price_table.add_row(*final_row)
            
            # 🔥 使用Layout布局管理（Header + Main + Logs + Controls）
            layout.split_column(
                Layout(self.create_header(), size=3),
                Layout(name="main"),
                Layout(self.create_logs_table(), size=23),  # 固定高度
                Layout(self.create_controls_panel(), size=3)
            )
            
            # 主内容区分为三个部分：统计 + 套利机会 + 价格表
            layout["main"].split_column(
                Layout(Panel.fit(Text.assemble(stats_text, "\n\n"), title="📊 统计"), size=5),
                Layout(Panel(table, border_style="magenta"), size=10, name="opportunities"),  # 🔥 固定高度10行
                Layout(price_table, name="prices")
            )
            
            return layout
        
        # 🔥 使用Layout布局管理（没有价格表的情况）
        layout.split_column(
            Layout(self.create_header(), size=3),
            Layout(name="main"),
            Layout(self.create_logs_table(), size=23),  # 固定高度
            Layout(self.create_controls_panel(), size=3)
        )
        
        # 主内容区分为两个部分：统计 + 套利机会
        layout["main"].split_column(
            Layout(Panel.fit(Text.assemble(stats_text, "\n\n"), title="📊 统计"), size=5),
            Layout(table, name="opportunities")
        )
        
        return layout
    
    async def run_ui(self):
        """运行UI（使用全屏Layout模式，稳定无闪烁）"""
        self.running = True
        
        # 🔥 在UI启动前禁用控制台日志输出
        self._disable_console_logging()
        
        # 🔥 使用Rich Live全屏模式
        with Live(
            self.generate_display(),
            console=self.console,
            refresh_per_second=4,  # 每秒刷新4次，确保实时更新
            screen=True,  # 全屏模式，稳定布局
            transient=False
        ) as live:
            while self.running:
                try:
                    # 生成新的显示内容（获取最新数据）
                    layout = self.generate_display()
                    
                    # 🔥 更新显示（Layout自动管理布局，无闪烁）
                    live.update(layout)
                    
                    # 等待配置的刷新间隔（默认2秒）
                    await asyncio.sleep(self.config['display']['refresh_rate'])
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    # 错误也记录到UI日志队列
                    self.logger.error(f"UI错误: {e}")
                    await asyncio.sleep(1)  # 避免错误循环
    
    async def run(self):
        """运行应用"""
        try:
            self.load_config()
            await self.initialize()
            
            # 🔥 不再使用console.print，直接启动UI
            # 所有日志都会显示在UI的日志表格中
            self.logger.info("套利监控系统已启动")
            
            await self.run_ui()
            
        except KeyboardInterrupt:
            self.logger.info("用户中断")
        except Exception as e:
            self.logger.error(f"系统错误: {e}", exc_info=True)
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        self.logger.info("🧹 清理资源...")
        
        if self.monitor_service:
            await self.monitor_service.stop()
        
        for adapter in self.adapters.values():
            try:
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
            except Exception as e:
                self.logger.error(f"❌ 断开连接失败: {e}")
        
        self.logger.info("✅ 资源清理完成")


async def main():
    """主函数"""
    app = ArbitrageMonitorApp()
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序退出")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        sys.exit(1)

