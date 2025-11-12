#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
网格配置生成器 - Grid Configuration Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  根据U本位设置方案自动计算网格参数，生成/更新配置文件

使用方式：
  python3 tools/grid_config_generator.py btc
  python3 tools/grid_config_generator.py ETH
  python3 tools/grid_config_generator.py Bnb

输入：
  - 代币名称（大小写兼容）

输出：
  - 自动计算的网格参数
  - 生成/更新配置文件
  - 可选：自动同步到其他目录

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import yaml
import asyncio
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 颜色定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Colors:
    """终端颜色"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 工具类
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GridConfigGenerator:
    """网格配置生成器"""

    def __init__(self, tool_config_path: str):
        """
        初始化生成器

        Args:
            tool_config_path: 工具配置文件路径
        """
        self.tool_dir = Path(__file__).parent
        self.tool_config_path = self.tool_dir / tool_config_path
        self.config: Dict[str, Any] = {}

    def load_tool_config(self) -> None:
        """加载工具配置文件"""
        try:
            with open(self.tool_config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            print(f"{Colors.GREEN}✅ 工具配置加载成功{Colors.NC}")
        except Exception as e:
            print(f"{Colors.RED}❌ 加载工具配置失败: {e}{Colors.NC}")
            sys.exit(1)

    async def fetch_price(self, symbol: str) -> Optional[tuple]:
        """
        从Lighter API获取代币价格和精度配置

        🔥 使用与网格系统完全相同的方法：
        - lighter.api.OrderApi().order_books() 获取 market_id
        - lighter.api.OrderApi().order_book_details(market_id) 获取详细价格和精度
        - 与 core/adapters/exchanges/adapters/lighter_rest.py 的实现一致

        Args:
            symbol: 代币符号（任意大小写）

        Returns:
            (代币价格, price_decimals, min_base_amount) 元组，失败返回None
        """
        # 🔥 先检查SDK是否可用（使用与网格系统相同的导入）
        try:
            from lighter.api import OrderApi
            from lighter import Configuration, ApiClient
        except ImportError as e:
            print(f"{Colors.RED}❌ Lighter SDK未安装: {e}{Colors.NC}")
            print(f"{Colors.YELLOW}请运行: pip install lighter{Colors.NC}")
            return None

        # 🔥 使用SDK获取价格
        try:
            # 创建配置和API客户端（无需认证即可查询市场数据）
            config = Configuration()
            api_client = ApiClient(configuration=config)
            order_api = OrderApi(api_client)

            # 🔥 调用 order_books() API获取所有市场信息
            # 这与 lighter_rest.py 中的 get_exchange_info() 方法相同
            response = await order_api.order_books()

            if not response or not hasattr(response, 'order_books'):
                print(f"{Colors.YELLOW}⚠️  API返回数据为空{Colors.NC}")
                return await self._manual_input_price(symbol)

            # 查找匹配的交易对，获取market_id和最小下单数量
            symbol_upper = symbol.upper()
            market_id = None
            min_base_amount = None
            min_quote_amount = None

            for market in response.order_books:
                if hasattr(market, 'symbol') and market.symbol.upper() == symbol_upper:
                    # 获取market_id（可能是market_id或market_index字段）
                    # 🔥 注意：不能用 or，因为 market_id=0 会被视为 False（如ETH的market_id=0）
                    market_id = getattr(market, 'market_id', None)
                    if market_id is None:
                        market_id = getattr(market, 'market_index', None)

                    # 🔥 获取最小下单数量
                    if hasattr(market, 'min_base_amount'):
                        try:
                            min_base_amount = Decimal(
                                str(market.min_base_amount))
                        except (ValueError, TypeError):
                            pass

                    if hasattr(market, 'min_quote_amount'):
                        try:
                            min_quote_amount = Decimal(
                                str(market.min_quote_amount))
                        except (ValueError, TypeError):
                            pass

                    break

            # 🔥 如果找到了交易对，调用详细信息API获取价格
            if market_id is not None:
                print(
                    f"{Colors.GREEN}✅ 找到交易对: {symbol_upper} (market_id={market_id}){Colors.NC}")

                # 🔥 调用 order_book_details 获取详细价格信息（与网格系统相同）
                detail_response = await order_api.order_book_details(market_id=market_id)

                if not detail_response or not hasattr(detail_response, 'order_book_details') or not detail_response.order_book_details:
                    print(f"{Colors.YELLOW}⚠️  无法获取市场详细信息{Colors.NC}")
                    return await self._manual_input_price(symbol)

                detail = detail_response.order_book_details[0]

                # 尝试获取价格（与 lighter_rest.py 相同的逻辑）
                price = None
                price_field = None

                if hasattr(detail, 'last_trade_price') and detail.last_trade_price:
                    try:
                        price = Decimal(str(detail.last_trade_price))
                        price_field = 'last_trade_price'
                    except (ValueError, TypeError):
                        pass

                if not price and hasattr(detail, 'mark_price') and detail.mark_price:
                    try:
                        price = Decimal(str(detail.mark_price))
                        price_field = 'mark_price'
                    except (ValueError, TypeError):
                        pass

                if not price and hasattr(detail, 'index_price') and detail.index_price:
                    try:
                        price = Decimal(str(detail.index_price))
                        price_field = 'index_price'
                    except (ValueError, TypeError):
                        pass

                # 🔥 获取price_decimals（关键！必须从API获取，不能自动推断）
                price_decimals = None
                if hasattr(detail, 'price_decimals'):
                    price_decimals = detail.price_decimals

                if price and price > 0 and price_decimals is not None:
                    print(f"{Colors.GREEN}✅ 获取价格成功（字段: {price_field}）{Colors.NC}")
                    print(f"{Colors.CYAN}📊 价格精度: {price_decimals}位小数{Colors.NC}")

                    # 显示最小下单数量信息
                    if min_base_amount is not None:
                        print(
                            f"{Colors.CYAN}📊 最小下单数量: {min_base_amount} {symbol_upper}{Colors.NC}")

                    return (price, price_decimals, min_base_amount)
                else:
                    # 找到交易对但没有价格数据
                    print(
                        f"{Colors.YELLOW}⚠️  交易对 {symbol_upper} 暂无价格数据{Colors.NC}")
                    print(f"{Colors.CYAN}💡 详细信息中的价格字段：{Colors.NC}")
                    for field in ['last_trade_price', 'mark_price', 'index_price', 'daily_price_high', 'daily_price_low']:
                        value = getattr(detail, field, None) if hasattr(
                            detail, field) else None
                        print(f"  • {field}: {value}")
                    return await self._manual_input_price(symbol)

            # 如果没有找到交易对，显示完整列表和模糊匹配结果
            print(f"{Colors.YELLOW}⚠️  未找到交易对 {symbol_upper}{Colors.NC}")

            # 收集所有交易对
            available_symbols = []
            for market in response.order_books:
                if hasattr(market, 'symbol'):
                    available_symbols.append(market.symbol)

            # 尝试模糊匹配
            fuzzy_matches = [s for s in available_symbols if symbol_upper.lower(
            ) in s.lower() or s.lower() in symbol_upper.lower()]

            if fuzzy_matches:
                print(f"{Colors.CYAN}💡 找到相似的交易对：{Colors.NC}")
                for match in fuzzy_matches[:10]:  # 显示前10个匹配
                    print(f"  • {match}")

            print(
                f"\n{Colors.CYAN}💡 所有可用的交易对（共{len(available_symbols)}个）：{Colors.NC}")
            # 按字母顺序排序
            available_symbols.sort()

            # 分列显示（每行5个）
            for i in range(0, len(available_symbols), 5):
                row_symbols = available_symbols[i:i+5]
                print("  " + "  ".join(f"{s:<12}" for s in row_symbols))

            return await self._manual_input_price(symbol)

        except Exception as e:
            print(f"{Colors.RED}❌ 获取价格失败: {e}{Colors.NC}")
            print(f"{Colors.YELLOW}详细错误信息：{Colors.NC}")
            import traceback
            traceback.print_exc()
            return await self._manual_input_price(symbol)

    async def _manual_input_price(self, symbol: str) -> Optional[tuple]:
        """
        手动输入价格和精度

        Args:
            symbol: 代币符号

        Returns:
            (价格, price_decimals, None) 元组，或None（用户取消）
        """
        print(f"\n{Colors.YELLOW}💡 请手动输入价格和精度：{Colors.NC}")
        print(
            f"{Colors.CYAN}提示：您可以在 https://app.lighter.xyz 查看 {symbol.upper()} 的当前价格{Colors.NC}\n")

        # 输入价格
        price = None
        while not price:
            try:
                price_input = input(
                    f"请输入 {symbol.upper()} 的当前价格（输入0取消）: ").strip()

                if price_input == '0':
                    return None

                price = Decimal(price_input)
                if price <= 0:
                    print(f"{Colors.RED}❌ 价格必须大于0{Colors.NC}")
                    price = None
            except (ValueError, TypeError):
                print(f"{Colors.RED}❌ 无效的价格格式，请输入数字{Colors.NC}")
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}⚠️  用户取消输入{Colors.NC}")
                return None
            except EOFError:
                # 在非交互环境中（如测试）直接返回None
                return None

        # 输入price_decimals
        print(
            f"\n{Colors.CYAN}💡 price_decimals 是价格的小数位数（例如：BTC=1, ETH=2, WLFI=5）{Colors.NC}")
        price_decimals = None
        while price_decimals is None:
            try:
                decimals_input = input(
                    f"请输入 {symbol.upper()} 的 price_decimals（1-8）: ").strip()

                decimals = int(decimals_input)
                if 1 <= decimals <= 8:
                    price_decimals = decimals
                else:
                    print(f"{Colors.RED}❌ price_decimals必须在1-8之间{Colors.NC}")
            except (ValueError, TypeError):
                print(f"{Colors.RED}❌ 无效的格式，请输入整数{Colors.NC}")
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}⚠️  用户取消输入{Colors.NC}")
                return None
            except EOFError:
                # 在非交互环境中（如测试）直接返回None
                return None

        return (price, price_decimals, None)  # 手动输入时不提供最小下单数量

    def calculate_grid_params(self, symbol: str, current_price: Decimal, price_decimals: int) -> Dict[str, Any]:
        """
        计算网格参数

        Args:
            symbol: 代币符号
            current_price: 当前价格
            price_decimals: 价格精度（从Lighter API获取的真实值）

        Returns:
            计算后的网格参数字典
        """
        # 读取配置参数
        grid_value = Decimal(str(self.config['grid_value_per_order']))
        range_pct = Decimal(
            str(self.config['grid_range_percentage'])) / Decimal('100')
        grid_count = int(self.config['follow_grid_count'])
        direction = self.config['direction'].lower()
        enable_martingale = self.config.get('enable_martingale', False)
        martingale_usd = Decimal(
            str(self.config.get('martingale_increment_usd', 0)))

        # 计算价格区间
        if direction == 'long':
            # 做多：当前价格为上限，向下扩展
            upper_price = current_price
            lower_price = current_price * (Decimal('1') - range_pct)
        else:  # short
            # 做空：当前价格为下限，向上扩展
            lower_price = current_price
            upper_price = current_price * (Decimal('1') + range_pct)

        # 计算网格间隔
        price_range = upper_price - lower_price
        grid_interval = price_range / Decimal(str(grid_count))

        # 🔥 U本位网格核心计算（让所有格子价值都接近 grid_value）
        #
        # 目标：
        # - 做多：第1格（最高价）和第n格（最低价）价值都是 grid_value
        # - 做空：第1格（最低价）和第n格（最高价）价值都是 grid_value
        #
        # 公式推导：
        # Grid 1: price_1 × order_amount = grid_value
        # Grid n: price_n × (order_amount + (n-1) × increment) = grid_value
        #
        # 求解：
        # order_amount = grid_value / price_1
        # increment = grid_value × (1/price_n - 1/price_1) / (n-1)

        if direction == 'long':
            # 做多：第1格是最高价（当前价格附近），第n格是最低价
            price_1 = upper_price
            price_n = lower_price
        else:  # short
            # 做空：第1格是最低价（当前价格附近），第n格是最高价
            price_1 = lower_price
            price_n = upper_price

        # 计算每格基础数量（基于第1格价格）
        order_amount = grid_value / price_1

        # 🔥 自动计算马丁递增（确保所有格子都接近 grid_value）
        # increment = grid_value × (1/price_n - 1/price_1) / (grid_count - 1)
        martingale_increment = None
        if grid_count > 1:
            # 计算让第n格也达到 grid_value 所需的递增
            increment_for_balance = grid_value * \
                (Decimal('1')/price_n - Decimal('1')/price_1) / \
                Decimal(str(grid_count - 1))

            # 如果用户配置了 martingale_increment_usd，将其转换为数量递增（基于平均价格）
            if enable_martingale and martingale_usd > 0:
                avg_price = (lower_price + upper_price) / Decimal('2')
                user_increment = martingale_usd / avg_price
                # 使用用户配置的递增（但会在summary中显示警告）
                martingale_increment = user_increment
            else:
                # 使用自动计算的递增（推荐）
                martingale_increment = increment_for_balance if abs(
                    increment_for_balance) > Decimal('0.000001') else None

        # 🔥 根据Lighter的规则计算quantity_precision
        # 规律：quantity_multiplier = 10^(6 - price_decimals)
        # 因此：quantity_precision = 6 - price_decimals
        # 例如：WLFI price_decimals=5 → quantity_precision=1
        #      BTC price_decimals=1 → quantity_precision=5
        #      ETH price_decimals=2 → quantity_precision=4
        quantity_precision = 6 - price_decimals

        # 🔥 应用精度规则（四舍五入到正确的小数位数）
        # order_amount 使用 quantity_precision
        # grid_interval 使用 price_decimals
        if quantity_precision >= 0:
            order_amount_rounded = order_amount.quantize(
                Decimal(10) ** (-quantity_precision))
        else:
            # 如果 quantity_precision < 0（例如DOGE可能是0），取整
            order_amount_rounded = order_amount.quantize(Decimal('1'))

        grid_interval_rounded = grid_interval.quantize(
            Decimal(10) ** (-price_decimals))

        # 返回结果（使用精度处理后的值）
        result = {
            'follow_grid_count': grid_count,
            'grid_interval': float(grid_interval_rounded),
            'order_amount': float(order_amount_rounded),
            'quantity_precision': quantity_precision,
            'price_decimals': price_decimals,
        }

        # 🔥 马丁递增不受 quantity_precision 限制，但保持合理的小数位数（8位）
        # 这是因为马丁递增是一个增量值，不是订单数量本身
        # 例如：quantity_precision=2 时，order_amount 可能是 1.44
        #      但 martingale_increment 可以是 0.00288，这样累积后才能达到效果
        if martingale_increment is not None:
            # 保留8位小数，避免浮点误差，也不至于太多小数位
            martingale_increment_rounded = martingale_increment.quantize(
                Decimal('0.00000001'))  # 8位小数
            result['martingale_increment'] = float(
                martingale_increment_rounded)
        else:
            martingale_increment_rounded = None

        # 🔥 计算验证信息（第1格、中间格、第n格的价值）
        grid_1_value = price_1 * order_amount_rounded

        # 计算关键位置的格子价值（25%、50%、75%）
        sample_grids = []
        for pct in [25, 50, 75]:
            grid_num = max(1, int(grid_count * pct / 100))
            # 计算该格的价格
            if direction == 'long':
                grid_price = upper_price - \
                    Decimal(str(grid_num - 1)) * grid_interval_rounded
            else:
                grid_price = lower_price + \
                    Decimal(str(grid_num - 1)) * grid_interval_rounded

            # 计算该格的数量（考虑马丁递增）
            if martingale_increment_rounded is not None:
                grid_amount = order_amount_rounded + \
                    Decimal(str(grid_num - 1)) * martingale_increment_rounded
            else:
                grid_amount = order_amount_rounded

            grid_value_at_position = grid_price * grid_amount
            sample_grids.append({
                'position': pct,
                'grid_num': grid_num,
                'price': float(grid_price),
                'amount': float(grid_amount),
                'value': float(grid_value_at_position)
            })

        if martingale_increment_rounded is not None:
            grid_n_value = price_n * \
                (order_amount_rounded + Decimal(str(grid_count - 1))
                 * martingale_increment_rounded)
        else:
            grid_n_value = price_n * order_amount_rounded

        # 添加计算过程信息（用于显示）
        result['_calculation_info'] = {
            'current_price': float(current_price),
            'price_range': (float(lower_price), float(upper_price)),
            'price_1': float(price_1),
            'price_n': float(price_n),
            'avg_price': float((lower_price + upper_price) / Decimal('2')),
            'direction': direction,
            'grid_1_value': float(grid_1_value),
            'grid_n_value': float(grid_n_value),
            'target_value': float(grid_value),
            'sample_grids': sample_grids,
        }

        return result

    def get_config_file_path(self, symbol: str) -> Path:
        """
        获取配置文件路径

        Args:
            symbol: 代币符号（任意大小写）

        Returns:
            配置文件路径
        """
        config_dir = self.tool_dir / self.config['config_dir']
        exchange = self.config['exchange']
        direction = self.config['direction'].lower()
        market_type = self.config['market_type'].lower()

        # 文件名使用小写代币符号
        filename = f"{exchange}-{direction}-{market_type}-{symbol.lower()}.yaml"
        return config_dir / filename

    def load_or_create_config(self, symbol: str) -> tuple[Dict[str, Any], Path]:
        """
        加载或创建配置文件

        Args:
            symbol: 代币符号（任意大小写）

        Returns:
            (配置字典, 配置文件路径)
        """
        config_path = self.get_config_file_path(symbol)

        # 如果配置文件已存在，加载它
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            print(f"{Colors.CYAN}📄 加载现有配置: {config_path.name}{Colors.NC}")
            return config_data, config_path

        # 否则，从模板创建新配置
        template_path = self.tool_dir / \
            self.config['config_dir'] / self.config['template_file']

        if not template_path.exists():
            print(f"{Colors.RED}❌ 模板文件不存在: {template_path}{Colors.NC}")
            sys.exit(1)

        with open(template_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        print(f"{Colors.CYAN}📄 从模板创建新配置: {config_path.name}{Colors.NC}")
        return config_data, config_path

    def _format_decimal(self, value: float, significant_digits: int = 4) -> str:
        """
        格式化小数，保留指定位数的有效数字，避免科学计数法

        Args:
            value: 要格式化的数值
            significant_digits: 保留的有效数字位数（默认4位）

        Returns:
            格式化后的字符串

        Examples:
            0.00000000001234567 → "0.00000000001234"
            0.00288443 → "0.002884"
            1.234567 → "1.235"
            0.1 → "0.1"
        """
        from decimal import Decimal, ROUND_HALF_UP

        if value == 0:
            return "0"

        # 转换为 Decimal 以精确处理
        d = Decimal(str(value))

        # 计算有效数字的起始位置
        # 例如：0.00288443 的有效数字从第3位开始
        abs_d = abs(d)

        # 🔥 使用固定小数格式展开（避免科学计数法）
        str_d = format(abs_d, '.30f')  # 使用30位小数确保展开

        # 分离整数部分和小数部分
        if '.' in str_d:
            integer_part, decimal_part = str_d.split('.')
        else:
            integer_part = str_d
            decimal_part = ""

        # 如果整数部分有非零数字
        if integer_part != '0':
            # 计算需要保留的小数位数
            integer_digits = len(integer_part.lstrip('0'))
            if integer_digits >= significant_digits:
                # 整数部分已经有足够的有效数字，四舍五入到整数
                return str(int(round(value)))
            else:
                # 需要保留一些小数位
                decimal_digits = significant_digits - integer_digits
                quantize_str = '0.' + '0' * (decimal_digits - 1) + '1'
                result = d.quantize(Decimal(quantize_str),
                                    rounding=ROUND_HALF_UP)
                # 🔥 使用 format 强制普通小数格式
                return format(result, 'f').rstrip('0').rstrip('.')
        else:
            # 整数部分为0，找小数部分的第一个非零数字
            leading_zeros = len(decimal_part) - len(decimal_part.lstrip('0'))
            # 保留：前导0 + significant_digits位有效数字
            total_decimal_digits = leading_zeros + significant_digits
            quantize_str = '0.' + '0' * (total_decimal_digits - 1) + '1'
            result = d.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
            # 🔥 使用 format 强制普通小数格式
            return format(result, 'f').rstrip('0').rstrip('.')

    def update_config(self, template_path: Path, grid_params: Dict[str, Any], symbol: str) -> str:
        """
        更新配置文件中的关键参数（保留所有注释和格式）

        使用字符串替换而不是YAML解析，以保留原始模板的所有内容

        Args:
            template_path: 模板文件路径
            grid_params: 网格参数字典
            symbol: 代币符号（任意大小写）

        Returns:
            更新后的配置文件内容（字符串）
        """
        import re

        # 读取模板文件为纯文本
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 🔥 只替换需要修改的参数值（保留其他所有内容）

        # 1. 替换 symbol
        content = re.sub(
            r'(symbol:\s*["\']?)([A-Z]+)(["\']?)',
            rf'\g<1>{symbol.upper()}\g<3>',
            content,
            count=1
        )

        # 2. 替换 follow_grid_count
        content = re.sub(
            r'(follow_grid_count:\s*)(\d+)',
            rf'\g<1>{grid_params["follow_grid_count"]}',
            content
        )

        # 3. 替换 grid_interval（保留4位有效数字）
        grid_interval_str = self._format_decimal(
            grid_params['grid_interval'], 4)
        content = re.sub(
            r'(grid_interval:\s*)([0-9.eE+-]+)',
            rf'\g<1>{grid_interval_str}',
            content
        )

        # 4. 替换 order_amount（保留4位有效数字）
        order_amount_str = self._format_decimal(grid_params['order_amount'], 4)
        content = re.sub(
            r'(order_amount:\s*)([0-9.eE+-]+)',
            rf'\g<1>{order_amount_str}',
            content
        )

        # 5. 替换 quantity_precision
        content = re.sub(
            r'(quantity_precision:\s*)(\d+)',
            rf'\g<1>{grid_params["quantity_precision"]}',
            content
        )

        # 6. 替换 price_decimals
        content = re.sub(
            r'(price_decimals:\s*)(\d+)',
            rf'\g<1>{grid_params["price_decimals"]}',
            content
        )

        # 7. 如果有马丁递增，替换或添加（处理注释的情况）
        if 'martingale_increment' in grid_params:
            # 🔥 格式化马丁递增，保留4位有效数字
            # 例如：0.00000000001234567 → 0.00000000001234
            #      0.00288443 → 0.002884
            martingale_value = grid_params["martingale_increment"]
            martingale_str = self._format_decimal(martingale_value, 4)

            # 检查是否被注释
            if re.search(r'#\s*martingale_increment:', content):
                # 取消注释并替换值
                content = re.sub(
                    r'#\s*(martingale_increment:\s*)([0-9.eE+-]+)',
                    rf'\g<1>{martingale_str}',
                    content
                )
            elif re.search(r'martingale_increment:', content):
                # 已存在，直接替换（支持科学计数法格式）
                content = re.sub(
                    r'(martingale_increment:\s*)([0-9.eE+-]+)',
                    rf'\g<1>{martingale_str}',
                    content
                )

        return content

    def save_config(self, content: str, config_path: Path) -> None:
        """
        保存配置文件

        Args:
            content: 配置文件内容（字符串）
            config_path: 配置文件路径
        """
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"{Colors.GREEN}✅ 配置文件已保存: {config_path.name}{Colors.NC}")
        except Exception as e:
            print(f"{Colors.RED}❌ 保存配置文件失败: {e}{Colors.NC}")
            sys.exit(1)

    def sync_config(self, config_filename: str) -> None:
        """
        同步配置到其他目录

        Args:
            config_filename: 配置文件名
        """
        if not self.config.get('auto_sync', False):
            print(f"{Colors.YELLOW}⊘ 自动同步已禁用{Colors.NC}")
            return

        sync_script = self.tool_dir / self.config['sync_script']

        if not sync_script.exists():
            print(f"{Colors.YELLOW}⚠️  同步脚本不存在: {sync_script}{Colors.NC}")
            return

        print(f"\n{Colors.CYAN}🔄 正在同步配置到其他目录...{Colors.NC}")

        try:
            import subprocess
            # 🔥 自动输入 "y" 来确认同步（避免脚本卡住等待输入）
            result = subprocess.run(
                [str(sync_script), config_filename],
                cwd=self.tool_dir,
                input="y\n",  # 自动确认
                capture_output=True,
                text=True,
                timeout=30  # 30秒超时
            )

            if result.returncode == 0:
                print(f"{Colors.GREEN}✅ 同步完成！{Colors.NC}")
                # 显示同步输出（如果有）
                if result.stdout:
                    # 只显示关键信息（成功/失败统计）
                    for line in result.stdout.split('\n'):
                        if '成功' in line or '失败' in line or '统计' in line or '✓' in line:
                            print(f"  {line}")
            else:
                print(
                    f"{Colors.YELLOW}⚠️  同步脚本返回错误码: {result.returncode}{Colors.NC}")
                if result.stderr:
                    print(f"{Colors.YELLOW}{result.stderr}{Colors.NC}")
        except subprocess.TimeoutExpired:
            print(f"{Colors.RED}❌ 同步超时（30秒）{Colors.NC}")
        except Exception as e:
            print(f"{Colors.RED}❌ 同步失败: {e}{Colors.NC}")

    def print_summary(self, symbol: str, grid_params: Dict[str, Any]) -> None:
        """
        打印计算结果摘要

        Args:
            symbol: 代币符号
            grid_params: 网格参数字典
        """
        info = grid_params['_calculation_info']

        print(f"\n{Colors.BOLD}{'━' * 70}{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}  📊 计算结果摘要 - {symbol.upper()}{Colors.NC}")
        print(f"{Colors.BOLD}{'━' * 70}{Colors.NC}")

        print(f"\n{Colors.YELLOW}🔍 价格信息：{Colors.NC}")
        print(f"  • 当前价格: ${info['current_price']:,.6f}")
        print(
            f"  • 价格区间: [${info['price_range'][0]:,.6f}, ${info['price_range'][1]:,.6f}]")
        print(f"  • 第1格价格: ${info['price_1']:,.6f}")
        print(
            f"  • 第{grid_params['follow_grid_count']}格价格: ${info['price_n']:,.6f}")
        print(f"  • 平均价格: ${info['avg_price']:,.6f}")

        print(f"\n{Colors.YELLOW}⚙️  网格参数：{Colors.NC}")
        print(f"  • 总网格数: {grid_params['follow_grid_count']}")
        print(f"  • 网格间隔: {grid_params['grid_interval']:.6f}")
        print(f"  • 基础数量: {grid_params['order_amount']:.8f}")
        print(f"  • 数量精度: {grid_params['quantity_precision']}")
        print(f"  • 价格精度: {grid_params['price_decimals']}")

        if 'martingale_increment' in grid_params:
            print(f"  • 马丁递增: {grid_params['martingale_increment']:.8f}")

        print(
            f"\n{Colors.YELLOW}💰 U本位验证（目标: ${info['target_value']:.2f} USDC/格）：{Colors.NC}")

        # 计算偏差百分比
        grid_1_deviation = abs(
            info['grid_1_value'] - info['target_value']) / info['target_value'] * 100
        grid_n_deviation = abs(
            info['grid_n_value'] - info['target_value']) / info['target_value'] * 100

        # 评估状态（偏差 < 5% 为优秀，< 10% 为良好，>= 10% 为需要优化）
        def get_status(value, target):
            deviation = abs(value - target) / target * 100
            if deviation < 5:
                return '✅'
            elif deviation < 10:
                return '⚠️ '
            else:
                return '❌'

        grid_1_status = get_status(info['grid_1_value'], info['target_value'])
        grid_n_status = get_status(info['grid_n_value'], info['target_value'])

        print(
            f"  {grid_1_status} 第1格（最{info['direction'] == 'long' and '高' or '低'}价）: ${info['grid_1_value']:,.2f} USDC (偏差: {grid_1_deviation:.1f}%)")

        # 显示中间格的价值分布
        if 'sample_grids' in info:
            for sample in info['sample_grids']:
                sample_deviation = abs(
                    sample['value'] - info['target_value']) / info['target_value'] * 100
                sample_status = get_status(
                    sample['value'], info['target_value'])
                print(
                    f"  {sample_status} 第{sample['grid_num']}格（{sample['position']}%位置）: ${sample['value']:,.2f} USDC (偏差: {sample_deviation:.1f}%)")

        print(
            f"  {grid_n_status} 第{grid_params['follow_grid_count']}格（最{info['direction'] == 'long' and '低' or '高'}价）: ${info['grid_n_value']:,.2f} USDC (偏差: {grid_n_deviation:.1f}%)")

        # 验证是否符合Lighter最小订单要求
        min_order_value = 10.0
        if info['grid_n_value'] < min_order_value:
            print(
                f"\n{Colors.RED}❌ 严重警告：第{grid_params['follow_grid_count']}格价值 ${info['grid_n_value']:.2f} < ${min_order_value} USDC（Lighter最小订单要求）{Colors.NC}")
            print(f"{Colors.YELLOW}   解决方案：{Colors.NC}")
            print(
                f"{Colors.YELLOW}   1. 增加 grid_value_per_order（当前 ${info['target_value']:.2f}）{Colors.NC}")
            print(
                f"{Colors.YELLOW}   2. 减少 grid_range_percentage（当前 {self.config['grid_range_percentage']}%）{Colors.NC}")
            print(
                f"{Colors.YELLOW}   3. 减少 follow_grid_count（当前 {grid_params['follow_grid_count']}）{Colors.NC}")
        elif max(grid_1_deviation, grid_n_deviation) > 10:
            # 计算所有采样格的平均偏差
            all_deviations = [grid_1_deviation, grid_n_deviation]
            if 'sample_grids' in info:
                for sample in info['sample_grids']:
                    sample_dev = abs(
                        sample['value'] - info['target_value']) / info['target_value'] * 100
                    all_deviations.append(sample_dev)
            avg_deviation = sum(all_deviations) / len(all_deviations)

            print(f"\n{Colors.YELLOW}💡 U本位分析：{Colors.NC}")
            print(
                f"{Colors.CYAN}   当前配置：grid_value=${info['target_value']:.2f}, range={self.config['grid_range_percentage']}%, count={grid_params['follow_grid_count']}{Colors.NC}")
            print(
                f"{Colors.CYAN}   马丁递增：{grid_params.get('martingale_increment', 0):.8f}{Colors.NC}")
            print(f"{Colors.CYAN}   平均偏差：{avg_deviation:.1f}%{Colors.NC}")
            print()
            print(f"{Colors.CYAN}   说明：{Colors.NC}")
            print(
                f"{Colors.CYAN}   • 第1格和第{grid_params['follow_grid_count']}格价值最接近目标（数学公式保证）{Colors.NC}")
            print(f"{Colors.CYAN}   • 中间格可能有偏差（价格区间越大，偏差越明显）{Colors.NC}")
            print(f"{Colors.CYAN}   • 建议：如需减少偏差，可减小 grid_range_percentage{Colors.NC}")
        else:
            print(
                f"\n{Colors.GREEN}✅ 优秀！所有格子价值都接近目标值 ${info['target_value']:.2f} USDC{Colors.NC}")
            print(
                f"{Colors.GREEN}   当前配置（grid_value=${info['target_value']:.2f}, range={self.config['grid_range_percentage']}%）非常理想！{Colors.NC}")

        total_investment = info['target_value'] * \
            grid_params['follow_grid_count']
        print(f"\n  • 估算总投入: ${total_investment:,.2f} USDC (如果全部成交)")

        print(f"\n{Colors.BOLD}{'━' * 70}{Colors.NC}\n")

    async def run(self, symbol: str) -> None:
        """
        运行生成器

        Args:
            symbol: 代币符号（任意大小写）
        """
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.NC}")
        print(
            f"{Colors.BOLD}{Colors.CYAN}  🚀 网格配置生成器 - Grid Configuration Generator{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.NC}\n")

        # 1. 加载工具配置
        self.load_tool_config()

        # 2. 获取代币价格和精度（支持API自动获取或手动输入）
        print(f"\n{Colors.CYAN}📡 正在获取 {symbol.upper()} 价格和精度...{Colors.NC}")
        price_info = await self.fetch_price(symbol)

        if price_info is None:
            print(f"\n{Colors.RED}❌ 未能获取价格，操作已取消{Colors.NC}")
            sys.exit(1)

        current_price, price_decimals, min_base_amount = price_info
        print(
            f"\n{Colors.GREEN}✅ 价格确认: {symbol.upper()} = ${current_price:,.6f}{Colors.NC}")
        print(
            f"{Colors.CYAN}✅ 精度确认: price_decimals={price_decimals}, quantity_precision={6-price_decimals}{Colors.NC}")

        if min_base_amount is not None:
            print(
                f"{Colors.CYAN}✅ 最小下单数量: {min_base_amount} {symbol.upper()}{Colors.NC}")

        # 3. 计算网格参数
        print(f"\n{Colors.CYAN}🧮 正在计算网格参数...{Colors.NC}")
        grid_params = self.calculate_grid_params(
            symbol, current_price, price_decimals)
        print(f"{Colors.GREEN}✅ 计算完成{Colors.NC}")

        # 🔥 验证最小下单数量（如果API提供了该信息）
        if min_base_amount is not None:
            calculated_amount = Decimal(str(grid_params['order_amount']))

            # 检查基础数量
            if calculated_amount < min_base_amount:
                print(f"\n{Colors.BOLD}{Colors.RED}{'━' * 70}{Colors.NC}")
                print(f"{Colors.RED}❌ 错误：计算的下单数量不满足交易所最小要求！{Colors.NC}")
                print(f"{Colors.BOLD}{Colors.RED}{'━' * 70}{Colors.NC}\n")

                print(f"{Colors.YELLOW}📊 数量对比：{Colors.NC}")
                print(
                    f"  • 计算的基础数量: {Colors.RED}{calculated_amount} {symbol.upper()}{Colors.NC}")
                print(
                    f"  • 交易所最小要求: {Colors.GREEN}{min_base_amount} {symbol.upper()}{Colors.NC}")
                print(
                    f"  • 差距: {Colors.RED}{min_base_amount - calculated_amount} {symbol.upper()}{Colors.NC} (需要增加 {((min_base_amount / calculated_amount - 1) * 100):.1f}%)")

                # 检查最后一格（考虑马丁递增）
                last_grid_num = grid_params['follow_grid_count']
                if 'martingale_increment' in grid_params:
                    martingale_increment = Decimal(
                        str(grid_params['martingale_increment']))
                    last_grid_amount = calculated_amount + \
                        Decimal(str(last_grid_num - 1)) * martingale_increment
                else:
                    last_grid_amount = calculated_amount

                if last_grid_amount < min_base_amount:
                    print(
                        f"\n{Colors.YELLOW}⚠️  最后一格数量: {Colors.RED}{last_grid_amount} {symbol.upper()}{Colors.NC} (同样不满足最小要求)")

                # 🔥 计算建议的 grid_value（增加10%余量）
                min_value = min_base_amount * current_price * Decimal('1.1')

                print(f"\n{Colors.CYAN}💡 解决方案：{Colors.NC}")
                print(
                    f"\n  {Colors.BOLD}🔥 增加 grid_value_per_order（唯一有效方法）{Colors.NC}")
                print(f"     当前值: ${self.config['grid_value_per_order']} USDC")
                print(
                    f"     {Colors.GREEN}建议值: >=${min_value:.2f} USDC{Colors.NC}")
                print()
                print(f"  {Colors.CYAN}📝 说明：{Colors.NC}")
                print(f"     • 第1格数量 = grid_value ÷ 当前价格")
                print(f"     • 第1格价格最高 → 数量最少 → 最容易不满足要求")
                print(f"     • 只有提高 grid_value 才能提高第1格数量")
                print(f"     • 修改网格范围或格子数量对第1格数量无影响")

                print(f"\n{Colors.YELLOW}📝 修改配置文件后重新运行：{Colors.NC}")
                print(f"  vim tools/grid_config_generator.yaml")
                print(f"\n{Colors.BOLD}{Colors.RED}{'━' * 70}{Colors.NC}\n")
                print(f"{Colors.RED}🛑 操作已中止，未生成配置文件{Colors.NC}\n")
                sys.exit(1)
            else:
                print(
                    f"\n{Colors.GREEN}✅ 下单数量验证通过: {calculated_amount} {symbol.upper()} >= {min_base_amount} {symbol.upper()} (最小要求){Colors.NC}")

        # 4. 打印计算结果
        self.print_summary(symbol, grid_params)

        # 5. 确定配置文件路径和模板路径
        config_path = self.get_config_file_path(symbol)

        # 如果配置文件已存在，使用现有配置作为基础；否则使用模板
        if config_path.exists():
            print(f"{Colors.CYAN}📄 更新现有配置: {config_path.name}{Colors.NC}")
            template_path = config_path  # 使用现有配置作为基础
        else:
            print(f"{Colors.CYAN}📄 从模板创建新配置: {config_path.name}{Colors.NC}")
            template_path = self.tool_dir / \
                self.config['config_dir'] / self.config['template_file']

            if not template_path.exists():
                print(f"{Colors.RED}❌ 模板文件不存在: {template_path}{Colors.NC}")
                sys.exit(1)

        # 6. 更新配置（保留所有注释和格式）
        config_content = self.update_config(template_path, grid_params, symbol)

        # 7. 保存配置
        self.save_config(config_content, config_path)

        # 8. 同步配置（如果启用）
        self.sync_config(config_path.name)

        print(f"\n{Colors.GREEN}{Colors.BOLD}✅ 全部完成！{Colors.NC}\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def print_usage():
    """打印使用说明"""
    print(f"""
{Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}
{Colors.CYAN}  网格配置生成器 - 使用说明{Colors.NC}
{Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}

{Colors.GREEN}用法:{Colors.NC}
  python3 tools/grid_config_generator.py <代币名称>

{Colors.GREEN}示例:{Colors.NC}
  {Colors.BLUE}# 生成BTC配置{Colors.NC}
  python3 tools/grid_config_generator.py btc

  {Colors.BLUE}# 生成ETH配置（大小写兼容）{Colors.NC}
  python3 tools/grid_config_generator.py ETH

  {Colors.BLUE}# 生成BNB配置{Colors.NC}
  python3 tools/grid_config_generator.py Bnb

{Colors.GREEN}说明:{Colors.NC}
  • 代币名称支持大小写混合输入
  • 工具会自动获取当前价格
  • 参数从配置文件读取：tools/grid_config_generator.yaml
  • 如果配置文件不存在，从模板创建
  • 如果启用auto_sync，会自动同步到其他目录

{Colors.GREEN}修改默认参数:{Colors.NC}
  vim tools/grid_config_generator.yaml

{Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}
""")


async def main():
    """主函数"""
    # 检查命令行参数
    if len(sys.argv) != 2 or sys.argv[1] in ['-h', '--help', 'help']:
        print_usage()
        sys.exit(0)

    symbol = sys.argv[1]

    # 创建生成器并运行
    generator = GridConfigGenerator('grid_config_generator.yaml')
    await generator.run(symbol)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}⚠️  用户取消操作{Colors.NC}\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}❌ 发生错误: {e}{Colors.NC}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
