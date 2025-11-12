"""
虚拟网格模型 - Virtual Grid Model

模拟网格交易，不实际下单，用于统计循环次数和计算APR

🔥 关键修复：正确模拟实盘网格逻辑
- 使用状态机模式（持有USDT/持有币）
- 记录最后成交价和挂单价
- 避免价格震荡时的重复计数
"""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from collections import deque
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class GridState(Enum):
    """网格状态（模拟实盘挂单状态）"""
    HOLDING_USDT = "HOLDING_USDT"  # 持有USDT，等待买入
    HOLDING_COIN = "HOLDING_COIN"  # 持有币，等待卖出


def _is_btc_symbol(symbol: str) -> bool:
    """
    判断是否为BTC交易对

    匹配：BTC, BTC-USD, BTC_PERP, BTCUSDT, BTCUSD 等
    排除：WBTC, TBTC, RBTC 等包装BTC
    """
    symbol_upper = symbol.upper()
    return 'BTC' in symbol_upper and not any(x in symbol_upper for x in ['WBTC', 'TBTC', 'RBTC'])


@dataclass
class VirtualGrid:
    """
    虚拟网格（模拟用）

    🔥 核心改进：正确模拟实盘网格逻辑

    实盘网格流程：
    1. 初始状态：持有USDT，在下方挂买单
    2. 价格跌至买入价 → 买入成交，挂卖单（买入价+间距）
    3. 价格在买入价和卖出价之间震荡 → 不触发任何交易
    4. 价格涨至卖出价 → 卖出成交，挂买单（卖出价-间距）
    5. 完成1个循环

    功能：
    1. 根据配置生成网格线
    2. 维护挂单状态（买单/卖单）
    3. 检测价格触发挂单
    4. 统计真实的循环次数
    """

    # 基础配置
    symbol: str                          # 交易对符号
    current_price: Decimal               # 当前价格（初始化价格）
    grid_width_percent: Decimal          # 网格总宽度百分比（如5.0表示±5%）
    grid_interval_percent: Decimal       # 格子间距百分比（如0.5表示0.5%）

    # 网格参数（自动计算）
    lower_price: Decimal = field(init=False)      # 下边界
    upper_price: Decimal = field(init=False)      # 上边界
    grid_count: int = field(init=False)           # 网格数量
    grid_lines: List[Decimal] = field(default_factory=list)  # 所有网格线价格
    grid_interval_value: Decimal = field(init=False)  # 🔥 网格间距的绝对价格

    # 🔥 状态机相关（模拟实盘挂单）
    state: GridState = field(default=GridState.HOLDING_USDT)  # 当前状态
    last_trade_price: Optional[Decimal] = None    # 上次成交价
    pending_buy_price: Optional[Decimal] = None   # 挂单买入价
    pending_sell_price: Optional[Decimal] = None  # 挂单卖出价

    # 价格追踪
    last_price: Optional[Decimal] = None          # 上次价格（用于日志）
    current_grid_index: int = 0                   # 当前所在网格索引（仅供参考）

    # 穿越统计
    total_crosses: int = 0                        # 总穿越次数（实际成交次数）
    buy_crosses: int = 0                          # 买入成交次数
    sell_crosses: int = 0                         # 卖出成交次数
    complete_cycles: int = 0                      # 完整循环次数

    # 🔥 滚动窗口循环统计（用于APR计算）
    cycle_events: deque = field(default_factory=lambda: deque())  # 循环事件时间戳队列

    # 时间统计
    start_time: datetime = field(default_factory=datetime.now)  # 开始时间
    last_update_time: datetime = field(default_factory=datetime.now)  # 最后更新时间

    # APR相关
    estimated_apr: Decimal = Decimal('0')         # 预估年化APR
    cycles_per_hour: Decimal = Decimal('0')       # 每小时循环次数

    # 24小时数据
    volume_24h_usdc: Decimal = Decimal('0')       # 24小时成交量（USDC）
    price_change_24h_percent: Decimal = Decimal('0')  # 24小时价格变化（%）

    # 🔥 S级评级追踪
    current_rating: str = ""                      # 当前评级（S/A/B/C/D）
    s_rating_start_time: Optional[datetime] = None  # S级开始时间（None表示当前不是S级）
    s_rating_duration_seconds: int = 0            # S级持续时长（秒）

    def __post_init__(self):
        """初始化后计算网格参数"""
        self._calculate_grid_parameters()
        self._initialize_pending_orders()

    def _calculate_grid_parameters(self):
        """
        计算网格参数

        逻辑：
        1. 根据当前价格和宽度百分比计算上下边界
        2. 根据间距百分比计算网格数量
        3. 生成所有网格线价格
        4. 🔥 计算网格间距的绝对价格（用于挂单）
        """
        # 计算上下边界
        half_width = self.grid_width_percent / \
            Decimal('200')  # 单边宽度（除以200因为总宽度是上下各一半）
        self.lower_price = self.current_price * (Decimal('1') - half_width)
        self.upper_price = self.current_price * (Decimal('1') + half_width)

        # 计算网格数量
        self.grid_count = int(self.grid_width_percent /
                              self.grid_interval_percent)

        # 生成网格线（从下到上）
        self.grid_lines = []
        price_step = (self.upper_price - self.lower_price) / self.grid_count
        for i in range(self.grid_count + 1):
            grid_price = self.lower_price + price_step * i
            self.grid_lines.append(grid_price)

        # 🔥 计算网格间距的绝对价格（用于挂单计算）
        # 间距 = 当前价格 × 间距百分比
        self.grid_interval_value = self.current_price * \
            (self.grid_interval_percent / Decimal('100'))

        # 初始化当前网格索引
        self.current_grid_index = self._get_grid_index(self.current_price)
        self.last_price = self.current_price

        # 🔥 只记录BTC的日志
        if _is_btc_symbol(self.symbol):
            logger.debug(
                f"[{self.symbol}] 网格参数初始化: "
                f"价格=${self.current_price}, "
                f"范围=${self.lower_price:.2f}-${self.upper_price:.2f}, "
                f"网格数={self.grid_count}, "
                f"间距绝对值=${self.grid_interval_value}"
            )

    def _initialize_pending_orders(self):
        """
        初始化挂单价格

        🔥 关键：正确模拟实盘网格的双边挂单

        实盘网格逻辑（感谢用户指正）：
        1. 当前价格$100，间距$1
        2. 下方挂买单：$99, $98, $97...（整格位置）
        3. 上方挂卖单：$101, $102, $103...（整格位置）
        4. 当前价格$100是"空网格"（获利空网格，不挂单）

        修正：
        - ❌ 原实现：买单$99.5（半格），无卖单
        - ✅ 正确实现：买单$99（整格），卖单$101（整格）
        """
        # 🔥 修正：使用整格位置，不是半格
        # 下方最近的买单（整格位置）
        self.pending_buy_price = self.current_price - self.grid_interval_value

        # 上方最近的卖单（整格位置）
        self.pending_sell_price = self.current_price + self.grid_interval_value

        # 🔥 初始状态：中性（双边挂单）
        # 实际上模拟的是"50%持有USDT + 50%持有币"的状态
        # 这样价格上涨可以卖，价格下跌可以买
        self.state = GridState.HOLDING_USDT  # 初始状态（仅用于标记）

        # 🔥 只记录BTC的日志
        if _is_btc_symbol(self.symbol):
            logger.info(
                f"[{self.symbol}] 初始化双边挂单: "
                f"当前价格=${self.current_price:.4f}, "
                f"买单=${self.pending_buy_price:.4f}, "
                f"卖单=${self.pending_sell_price:.4f}, "
                f"空网格=${self.current_price:.4f} (获利空网格)"
            )

    def _get_grid_index(self, price: Decimal) -> int:
        """
        根据价格获取所在网格索引（仅供参考，不用于交易判断）

        Args:
            price: 价格

        Returns:
            网格索引（0到grid_count-1）
        """
        if price <= self.lower_price:
            return 0
        if price >= self.upper_price:
            return self.grid_count - 1

        # 二分查找
        for i in range(len(self.grid_lines) - 1):
            if self.grid_lines[i] <= price < self.grid_lines[i + 1]:
                return i

        return self.grid_count - 1

    def update_price(self, new_price: Decimal) -> Optional[str]:
        """
        更新价格并检测挂单触发

        🔥 核心修复：双边挂单模式

        Args:
            new_price: 新价格

        Returns:
            'buy': 买入成交（价格跌至买单价）
            'sell': 卖出成交（价格涨至卖单价）
            None: 未触发任何挂单

        逻辑（双边挂单）：
        1. 同时检查买单和卖单
        2. 价格跌至买单价 → 买入，反手在原价挂卖单
        3. 价格涨至卖单价 → 卖出，反手在原价挂买单
        4. 当前价格位置是"空网格"（已成交的格子）
        """
        if self.last_price is None:
            self.last_price = new_price
            self.current_grid_index = self._get_grid_index(new_price)
            self.current_price = new_price
            self.last_update_time = datetime.now()
            return None

        # 保存旧状态（用于日志）
        old_index = self.current_grid_index
        new_index = self._get_grid_index(new_price)

        # 更新价格和时间
        self.last_price = self.current_price
        self.current_price = new_price
        self.current_grid_index = new_index
        self.last_update_time = datetime.now()

        # 🔥 双边挂单逻辑：同时检查买单和卖单

        # 🔥 BTC详细日志：记录价格变化和挂单状态
        if _is_btc_symbol(self.symbol):
            logger.info(
                f"[{self.symbol}] 价格更新 | "
                f"${self.last_price:.4f} → ${new_price:.4f} | "
                f"买单=${self.pending_buy_price:.4f}, 卖单=${self.pending_sell_price:.4f} | "
                f"买入{self.buy_crosses}次, 卖出{self.sell_crosses}次, 循环{self.complete_cycles}次"
            )

        # 检查买单触发（价格下跌）
        if self.pending_buy_price and new_price <= self.pending_buy_price:
            # ✅ 买入成交
            buy_price = self.pending_buy_price
            self.last_trade_price = buy_price
            self.buy_crosses += 1
            self.total_crosses += 1

            # 🔥 反手挂卖单：在买入价上方一格
            old_sell_price = self.pending_sell_price
            self.pending_sell_price = buy_price + self.grid_interval_value

            # 🔥 下移买单：在买入价下方一格
            self.pending_buy_price = buy_price - self.grid_interval_value

            # 🔥 双边挂单模式：买入时也检查循环
            old_cycles = self.complete_cycles
            self._update_cycle_count()

            # 🔥 只记录BTC的日志
            if _is_btc_symbol(self.symbol):
                logger.info(
                    f"✅ [{self.symbol}] 买入成交 | "
                    f"价格: ${self.last_price:.4f} → ${new_price:.4f} | "
                    f"成交价=${buy_price:.4f} | "
                    f"买单: ${buy_price:.4f} → ${self.pending_buy_price:.4f} | "
                    f"卖单: ${old_sell_price or 0:.4f} → ${self.pending_sell_price:.4f} | "
                    f"空网格: ${buy_price:.4f} | "
                    f"买入次数: {self.buy_crosses} | "
                    f"完整循环: {old_cycles} → {self.complete_cycles}"
                )

            return 'buy'

        # 检查卖单触发（价格上涨）
        if self.pending_sell_price and new_price >= self.pending_sell_price:
            # ✅ 卖出成交
            sell_price = self.pending_sell_price
            self.last_trade_price = sell_price
            self.sell_crosses += 1
            self.total_crosses += 1

            # 🔥 反手挂买单：在卖出价下方一格
            old_buy_price = self.pending_buy_price
            self.pending_buy_price = sell_price - self.grid_interval_value

            # 🔥 上移卖单：在卖出价上方一格
            self.pending_sell_price = sell_price + self.grid_interval_value

            # 🔥 更新完整循环次数
            old_cycles = self.complete_cycles
            self._update_cycle_count()

            # 🔥 只记录BTC的日志
            if _is_btc_symbol(self.symbol):
                logger.info(
                    f"✅ [{self.symbol}] 卖出成交 | "
                    f"价格: ${self.last_price:.4f} → ${new_price:.4f} | "
                    f"成交价=${sell_price:.4f} | "
                    f"买单: ${old_buy_price or 0:.4f} → ${self.pending_buy_price:.4f} | "
                    f"卖单: ${sell_price:.4f} → ${self.pending_sell_price:.4f} | "
                    f"空网格: ${sell_price:.4f} | "
                    f"卖出次数: {self.sell_crosses} | "
                    f"完整循环: {old_cycles} → {self.complete_cycles}"
                )

            return 'sell'

        # 未触发任何挂单
        return None

    def _update_cycle_count(self):
        """
        更新完整循环次数

        🔥 修复：只在真正完成买入→卖出循环时才计数

        逻辑：
        - 完整循环 = min(买入次数, 卖出次数)
        - 记录循环事件时间戳（用于滚动窗口APR计算）
        """
        old_cycles = self.complete_cycles
        self.complete_cycles = min(self.buy_crosses, self.sell_crosses)

        # 如果有新的完整循环，记录时间戳
        if self.complete_cycles > old_cycles:
            new_cycles_count = self.complete_cycles - old_cycles
            self.cycle_events.append(datetime.now())

            # 🔥 只记录BTC的日志
            if _is_btc_symbol(self.symbol):
                logger.info(
                    f"🔄 [{self.symbol}] 完成 {new_cycles_count} 个循环! "
                    f"总循环: {old_cycles} → {self.complete_cycles} | "
                    f"买入={self.buy_crosses}, 卖出={self.sell_crosses} | "
                    f"计算: min({self.buy_crosses}, {self.sell_crosses}) = {self.complete_cycles}"
                )
        else:
            # 🔥 BTC专属：即使没有新循环，也记录计算过程
            if _is_btc_symbol(self.symbol):
                logger.debug(
                    f"[{self.symbol}] 循环检查: "
                    f"买入={self.buy_crosses}, 卖出={self.sell_crosses} | "
                    f"完整循环=min({self.buy_crosses}, {self.sell_crosses})={self.complete_cycles} (无变化)"
                )

    def calculate_apr(
        self,
        order_value_usdc: Decimal = Decimal('10'),
        fee_rate_percent: Decimal = Decimal('0.004'),
        time_window_minutes: int = 5  # 🔥 滚动窗口：5分钟
    ) -> Decimal:
        """
        计算实时预估APR（基于滚动窗口）

        Args:
            order_value_usdc: 每格订单价值（USDC）
            fee_rate_percent: 双边手续费率（%）
            time_window_minutes: 滚动窗口时长（分钟）

        Returns:
            年化APR（%）

        公式：
        APR = (格子间距% - 手续费%) × 格子间距% / 网格宽度% × 每小时循环 × 8760

        逻辑：
        - 只统计过去N分钟的循环次数
        - 运行时间<N分钟时返回0（数据不足）
        """
        # 🔥 关键：检查运行时长
        running_seconds = (self.last_update_time -
                           self.start_time).total_seconds()
        window_seconds = time_window_minutes * 60

        # 🔥 修复：最少运行1分钟即可计算APR（而不是等待5分钟）
        # 这样用户启动后1分钟就能看到APR数据
        if running_seconds < 60:
            # 运行时间不足1分钟，返回0
            return Decimal('0')

        # 🔥 关键：动态调整窗口时长
        # - 如果运行时间 < 5分钟，使用实际运行时间
        # - 如果运行时间 >= 5分钟，使用5分钟窗口
        # 这样启动后很快就能看到APR数据
        now = datetime.now()
        if running_seconds < window_seconds:
            # 运行时间不足5分钟，使用实际运行时间作为窗口
            actual_window_minutes = running_seconds / 60
            window_start = self.start_time
        else:
            # 运行时间超过5分钟，使用5分钟窗口
            actual_window_minutes = time_window_minutes
            window_start = now - timedelta(minutes=time_window_minutes)

        # 移除窗口外的事件（只在使用5分钟窗口时才清理）
        if running_seconds >= window_seconds:
            old_event_count = len(self.cycle_events)
            while self.cycle_events and self.cycle_events[0] < window_start:
                self.cycle_events.popleft()

        # 🔥 关键：统计窗口内的循环次数
        cycles_in_window = sum(
            1 for event in self.cycle_events if event >= window_start)

        if cycles_in_window == 0:
            # 窗口内无循环，返回0（不打印日志，避免刷屏）
            self.cycles_per_hour = Decimal('0')
            self.estimated_apr = Decimal('0')
            return Decimal('0')

        # 计算每小时循环次数（基于实际窗口时长）
        window_hours = Decimal(str(actual_window_minutes)) / Decimal('60')
        self.cycles_per_hour = Decimal(str(cycles_in_window)) / window_hours

        # 计算APR
        # APR = (格子间距 - 手续费) × 格子间距 / 网格宽度 × 每小时循环 × 8760
        net_profit_rate = self.grid_interval_percent - fee_rate_percent
        if net_profit_rate <= 0:
            # 🔥 只记录BTC的日志
            if _is_btc_symbol(self.symbol):
                logger.warning(
                    f"⚠️ [{self.symbol}] APR=0: 手续费超过利润 | "
                    f"格子间距={self.grid_interval_percent}%, 手续费={fee_rate_percent}%"
                )
            return Decimal('0')  # 手续费超过利润，无法盈利

        single_cycle_rate = net_profit_rate * \
            self.grid_interval_percent / self.grid_width_percent
        new_apr = single_cycle_rate * self.cycles_per_hour * Decimal('8760')

        # 🔥 只在APR显著变化时打印详细日志（避免刷屏）
        # 定义"显著变化"：变化幅度 > 5% 或者是首次计算（从0变为非0）
        apr_changed = False
        if self.estimated_apr == Decimal('0') and new_apr > Decimal('0'):
            apr_changed = True  # 首次计算出APR
        elif self.estimated_apr > Decimal('0'):
            change_percent = abs(
                (new_apr - self.estimated_apr) / self.estimated_apr * Decimal('100'))
            if change_percent > Decimal('5'):
                apr_changed = True  # APR变化超过5%

        self.estimated_apr = new_apr

        # 🔥 只记录BTC的日志
        if apr_changed and _is_btc_symbol(self.symbol):
            logger.info(
                f"💰 [{self.symbol}] APR更新: {self.estimated_apr:.2f}%\n"
                f"   ├─ 时间窗口: {time_window_minutes}分钟 (已运行{running_seconds/60:.1f}分钟)\n"
                f"   ├─ 窗口内循环次数: {cycles_in_window}次\n"
                f"   ├─ 每小时循环: {cycles_in_window}次 ÷ {window_hours:.2f}小时 = {self.cycles_per_hour:.2f}次/小时\n"
                f"   ├─ 净利润率: 格子间距{self.grid_interval_percent}% - 手续费{fee_rate_percent}% = {net_profit_rate}%\n"
                f"   ├─ 单次循环收益率: {net_profit_rate}% × {self.grid_interval_percent}% ÷ {self.grid_width_percent}% = {single_cycle_rate}%\n"
                f"   └─ 年化APR: {single_cycle_rate}% × {self.cycles_per_hour:.2f}次/时 × 8760小时 = {self.estimated_apr:.2f}%"
            )

        return self.estimated_apr

    def get_running_time_seconds(self) -> int:
        """获取运行时长（秒）"""
        return int((self.last_update_time - self.start_time).total_seconds())

    def get_avg_cycles_per_5min(self) -> Decimal:
        """
        计算平均5分钟循环次数

        基于启动后的总运行时间计算：
        平均5分钟循环 = 总循环次数 / 运行总分钟数 * 5

        Returns:
            平均每5分钟的循环次数
        """
        running_seconds = self.get_running_time_seconds()
        if running_seconds == 0:
            return Decimal('0')

        # 运行总分钟数
        running_minutes = Decimal(str(running_seconds)) / Decimal('60')

        # 平均5分钟循环次数 = 总循环 / 总分钟 * 5
        if running_minutes == 0:
            return Decimal('0')

        avg_per_5min = Decimal(str(self.complete_cycles)) / \
            running_minutes * Decimal('5')
        return avg_per_5min

    def get_recent_5min_cycles(self) -> int:
        """
        获取最近5分钟的循环次数

        通过清理cycle_events队列中超过5分钟的事件，
        返回队列中剩余的事件数量（即最近5分钟的循环次数）

        Returns:
            最近5分钟内的循环次数
        """
        # 清理超过5分钟的事件
        now = datetime.now()
        window_start = now - timedelta(minutes=5)

        # 统计窗口内的事件数量（不修改队列，只统计）
        recent_cycles = sum(
            1 for event in self.cycle_events if event >= window_start)

        return recent_cycles

    def update_rating(self, new_rating: str):
        """
        更新评级并追踪S级持续时间
        
        规则：
        1. 如果新评级为S，且之前不是S → 开始计时
        2. 如果新评级为S，且之前也是S → 累计时间
        3. 如果新评级不是S，且之前是S → 停止计时，清零
        4. 时间格式：D/H/M（天/小时/分钟）
        
        Args:
            new_rating: 新评级（如"🔥 S", "⭐ A"等）
        """
        # 提取评级字母（去除emoji）
        new_rating_letter = new_rating.split()[-1] if new_rating else ""
        old_rating_letter = self.current_rating.split()[-1] if self.current_rating else ""
        
        now = datetime.now()
        
        # 判断是否为S级
        is_s_rating_now = (new_rating_letter == "S")
        was_s_rating_before = (old_rating_letter == "S")
        
        if is_s_rating_now and not was_s_rating_before:
            # 🔥 情况1: 首次进入S级 → 开始计时
            self.s_rating_start_time = now
            self.s_rating_duration_seconds = 0
            
            if _is_btc_symbol(self.symbol):
                logger.info(
                    f"🌟 [{self.symbol}] 进入S级评级！开始计时 | "
                    f"APR={self.estimated_apr:.2f}%"
                )
        
        elif is_s_rating_now and was_s_rating_before:
            # 🔥 情况2: 持续保持S级 → 累计时间
            if self.s_rating_start_time:
                self.s_rating_duration_seconds = int(
                    (now - self.s_rating_start_time).total_seconds()
                )
        
        elif not is_s_rating_now and was_s_rating_before:
            # 🔥 情况3: 从S级降级 → 停止计时，清零
            duration = self.get_s_rating_duration_str()
            self.s_rating_start_time = None
            self.s_rating_duration_seconds = 0
            
            if _is_btc_symbol(self.symbol):
                logger.info(
                    f"📉 [{self.symbol}] 从S级降级至{new_rating} | "
                    f"持续时长: {duration} | "
                    f"当前APR={self.estimated_apr:.2f}%"
                )
        
        # 更新当前评级
        self.current_rating = new_rating
    
    def get_s_rating_duration_seconds(self) -> int:
        """
        获取S级持续时长（秒）
        
        Returns:
            持续秒数，如果当前不是S级则返回0
        """
        if self.s_rating_start_time is None:
            return 0
        
        # 实时计算持续时长
        now = datetime.now()
        duration = int((now - self.s_rating_start_time).total_seconds())
        return duration
    
    def get_s_rating_duration_str(self) -> str:
        """
        获取S级持续时长（格式化字符串: D/H/M）
        
        格式示例：
        - "35S" (35秒，不足1分钟)
        - "0D/0H/1M" (1分钟)
        - "0D/2H/30M" (2小时30分钟)
        - "1D/3H/15M" (1天3小时15分钟)
        - "--" (不是S级)
        
        Returns:
            格式化的时间字符串
        """
        duration_seconds = self.get_s_rating_duration_seconds()
        
        if duration_seconds == 0:
            return "--"
        
        # 🔥 如果不足1分钟，显示秒数
        if duration_seconds < 60:
            return f"{duration_seconds}S"
        
        # 计算天/小时/分钟
        days = duration_seconds // 86400
        hours = (duration_seconds % 86400) // 3600
        minutes = (duration_seconds % 3600) // 60
        
        return f"{days}D/{hours}H/{minutes}M"

    def get_summary(self) -> dict:
        """
        获取统计摘要

        Returns:
            包含所有关键统计数据的字典
        """
        return {
            'symbol': self.symbol,
            'current_price': float(self.current_price),
            'grid_range': f'${self.lower_price:.2f} - ${self.upper_price:.2f}',
            'grid_count': self.grid_count,
            'grid_interval': f'{self.grid_interval_percent}%',
            'state': self.state.value,
            'pending_buy_price': float(self.pending_buy_price) if self.pending_buy_price else None,
            'pending_sell_price': float(self.pending_sell_price) if self.pending_sell_price else None,
            'total_crosses': self.total_crosses,
            'buy_crosses': self.buy_crosses,
            'sell_crosses': self.sell_crosses,
            'complete_cycles': self.complete_cycles,
            'cycles_per_hour': float(self.cycles_per_hour),
            'estimated_apr': float(self.estimated_apr),
            'running_seconds': self.get_running_time_seconds(),
            'volume_24h_usdc': float(self.volume_24h_usdc),
            'price_change_24h': float(self.price_change_24h_percent),
        }
