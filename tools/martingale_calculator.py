#!/usr/bin/env python3
"""
马丁递增参数计算器

功能：
- 根据网格参数计算最优的马丁递增值
- 确保每个订单价值都 >= 最小订单价值（默认10 USDC）
- 支持做多和做空网格
- 输出详细的计算过程和验证结果

使用场景：
Lighter交易所要求每笔订单价值 >= 10 USDC。
在网格交易中，价格较低的格子可能导致订单价值不足。
通过马丁递增，逐步增加订单数量，确保所有订单都满足最小价值要求。

作者：网格交易系统
日期：2025-11-08
"""

from decimal import Decimal, ROUND_UP
from typing import Tuple, List
import sys


class MartingaleCalculator:
    """马丁递增参数计算器"""

    def __init__(self, min_order_value: Decimal = Decimal('10.0')):
        """
        初始化计算器

        Args:
            min_order_value: 最小订单价值（USDC），默认10
        """
        self.min_order_value = min_order_value

    def calculate_for_long_grid(
        self,
        current_price: Decimal,
        grid_count: int,
        grid_interval: Decimal,
        base_quantity: Decimal,
        is_percentage: bool = False
    ) -> Tuple[Decimal, List[dict]]:
        """
        计算做多网格的马丁递增参数

        做多网格：价格从上到下递减，最低价格的订单价值最小

        Args:
            current_price: 当前价格
            grid_count: 网格数量
            grid_interval: 每格间隔（绝对值或百分比）
            base_quantity: 基础数量（第一格的数量）
            is_percentage: 间隔是否为百分比（True=百分比，False=绝对值）

        Returns:
            (martingale_increment, grid_details)
            - martingale_increment: 马丁递增参数
            - grid_details: 每个网格的详细信息（用于验证）
        """
        print("\n" + "=" * 80)
        print("🔍 做多网格 - 马丁递增参数计算")
        print("=" * 80)

        # 计算每个格子的价格
        grid_prices = []
        for i in range(grid_count):
            if is_percentage:
                # 百分比模式：每格下跌 grid_interval%
                price = current_price * (Decimal('1') - grid_interval * i)
            else:
                # 绝对值模式：每格下跌固定金额
                price = current_price - (grid_interval * i)

            if price <= 0:
                print(f"❌ 错误：第 {i+1} 格价格为负数或零！")
                print(f"   建议：减少网格数量或增大价格间隔")
                sys.exit(1)

            grid_prices.append(price)

        # 找到最低价格（做多网格的最后一格）
        lowest_price = grid_prices[-1]

        print(f"\n📊 网格价格范围：")
        print(f"   最高价格（第1格）: ${grid_prices[0]:,.6f}")
        print(f"   最低价格（第{grid_count}格）: ${lowest_price:,.6f}")
        print(f"   价格跨度: ${grid_prices[0] - lowest_price:,.6f} ({((1 - lowest_price/grid_prices[0]) * 100):.2f}%)")

        # 计算最低价格格子需要的最小数量
        min_quantity_at_lowest = self.min_order_value / lowest_price

        print(f"\n💰 订单价值计算：")
        print(f"   最小订单价值要求: ${self.min_order_value} USDC")
        print(f"   基础数量（第1格）: {base_quantity}")
        print(f"   第1格订单价值: {base_quantity} × ${grid_prices[0]:,.6f} = ${base_quantity * grid_prices[0]:,.2f} USDC")
        print(f"   ")
        print(f"   ⚠️  如果不使用马丁递增：")
        print(f"   第{grid_count}格订单价值: {base_quantity} × ${lowest_price:,.6f} = ${base_quantity * lowest_price:,.2f} USDC")

        if base_quantity * lowest_price >= self.min_order_value:
            print(f"   ✅ 无需马丁递增！所有订单价值都 >= ${self.min_order_value} USDC")
            return Decimal('0'), []

        print(f"   ❌ 低于最小要求！")
        print(f"   ")
        print(f"   第{grid_count}格需要的最小数量: {min_quantity_at_lowest:.6f}")

        # 计算马丁递增参数
        # 公式：quantity_at_lowest = base_quantity + (grid_count - 1) × martingale_increment
        # 求解：martingale_increment = (quantity_at_lowest - base_quantity) / (grid_count - 1)
        martingale_increment = (min_quantity_at_lowest - base_quantity) / (grid_count - 1)

        # 向上取整到合理精度（保留6位小数）
        martingale_increment = martingale_increment.quantize(Decimal('0.000001'), rounding=ROUND_UP)

        print(f"\n📐 马丁递增参数计算：")
        print(f"   公式: martingale_increment = (最低格所需数量 - 基础数量) / (网格数 - 1)")
        print(f"   计算: ({min_quantity_at_lowest:.6f} - {base_quantity}) / ({grid_count} - 1)")
        print(f"   结果: {martingale_increment}")

        # 验证每个格子的订单价值
        print(f"\n✅ 验证结果（显示关键格子）：")
        grid_details = []
        critical_grids = [0, grid_count // 4, grid_count // 2, grid_count * 3 // 4, grid_count - 1]

        for i in critical_grids:
            price = grid_prices[i]
            quantity = base_quantity + (martingale_increment * i)
            order_value = price * quantity
            is_valid = order_value >= self.min_order_value

            grid_details.append({
                'index': i + 1,
                'price': price,
                'quantity': quantity,
                'order_value': order_value,
                'is_valid': is_valid
            })

            status = "✅" if is_valid else "❌"
            print(f"   {status} 第{i+1:3d}格: 价格=${price:,.6f}, 数量={quantity:.6f}, "
                  f"价值=${order_value:,.2f} USDC")

        return martingale_increment, grid_details

    def calculate_for_short_grid(
        self,
        current_price: Decimal,
        grid_count: int,
        grid_interval: Decimal,
        base_quantity: Decimal,
        is_percentage: bool = False
    ) -> Tuple[Decimal, List[dict]]:
        """
        计算做空网格的马丁递增参数

        做空网格：价格从下到上递增，最高价格的订单价值最小（相对而言）
        但通常做空网格的问题较小，因为价格上涨时卖单价值更高

        Args:
            current_price: 当前价格
            grid_count: 网格数量
            grid_interval: 每格间隔（绝对值或百分比）
            base_quantity: 基础数量（第一格的数量）
            is_percentage: 间隔是否为百分比

        Returns:
            (martingale_increment, grid_details)
        """
        print("\n" + "=" * 80)
        print("🔍 做空网格 - 马丁递增参数计算")
        print("=" * 80)

        # 计算每个格子的价格
        grid_prices = []
        for i in range(grid_count):
            if is_percentage:
                # 百分比模式：每格上涨 grid_interval%
                price = current_price * (Decimal('1') + grid_interval * i)
            else:
                # 绝对值模式：每格上涨固定金额
                price = current_price + (grid_interval * i)

            grid_prices.append(price)

        # 做空网格：最低价格的格子订单价值最小
        lowest_price = grid_prices[0]
        highest_price = grid_prices[-1]

        print(f"\n📊 网格价格范围：")
        print(f"   最低价格（第1格）: ${lowest_price:,.6f}")
        print(f"   最高价格（第{grid_count}格）: ${highest_price:,.6f}")
        print(f"   价格跨度: ${highest_price - lowest_price:,.6f} ({((highest_price/lowest_price - 1) * 100):.2f}%)")

        # 计算最低价格格子需要的最小数量
        min_quantity_at_lowest = self.min_order_value / lowest_price

        print(f"\n💰 订单价值计算：")
        print(f"   最小订单价值要求: ${self.min_order_value} USDC")
        print(f"   基础数量（第1格）: {base_quantity}")
        print(f"   第1格订单价值: {base_quantity} × ${lowest_price:,.6f} = ${base_quantity * lowest_price:,.2f} USDC")

        if base_quantity * lowest_price >= self.min_order_value:
            print(f"   ✅ 无需马丁递增！所有订单价值都 >= ${self.min_order_value} USDC")
            return Decimal('0'), []

        print(f"   ❌ 低于最小要求！")
        print(f"   第1格需要的最小数量: {min_quantity_at_lowest:.6f}")

        # 做空网格通常不需要马丁递增，因为价格越高订单价值越大
        # 但如果第一格就不满足，需要增加基础数量
        print(f"\n⚠️  建议：直接增加基础数量（order_amount）到 {min_quantity_at_lowest:.0f} 以上")
        print(f"   做空网格通常不需要马丁递增")

        return Decimal('0'), []


def get_decimal_input(prompt: str) -> Decimal:
    """获取 Decimal 类型的输入"""
    while True:
        try:
            value = input(prompt).strip()
            return Decimal(value)
        except Exception as e:
            print(f"❌ 输入无效，请输入数字: {e}")


def get_int_input(prompt: str) -> int:
    """获取整数类型的输入"""
    while True:
        try:
            value = input(prompt).strip()
            return int(value)
        except Exception:
            print(f"❌ 输入无效，请输入整数")


def get_bool_input(prompt: str) -> bool:
    """获取布尔类型的输入"""
    while True:
        value = input(prompt).strip().lower()
        if value in ['y', 'yes', '是', '1', 'true']:
            return True
        elif value in ['n', 'no', '否', '0', 'false']:
            return False
        else:
            print("❌ 输入无效，请输入 y/n")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("🎯 马丁递增参数计算器（做多网格专用）")
    print("=" * 80)
    print("功能：计算做多网格的马丁递增参数，确保所有订单价值 >= 10 USDC")
    print("=" * 80)
    print("\n💡 说明：")
    print("   - 做多网格价格向下，低价格订单可能价值不足")
    print("   - 做空网格价格向上，不存在此问题，无需马丁递增")
    print("=" * 80)

    # 初始化计算器
    calculator = MartingaleCalculator(min_order_value=Decimal('10.0'))

    while True:
        print("\n" + "-" * 80)
        print("📝 请输入网格参数（做多网格）：")
        print("-" * 80)

        # 固定为做多网格
        grid_type = 'long'

        # 简化输入：直接提供价格范围
        upper_price = get_decimal_input("上限价格（当前价格）: ")
        lower_price = get_decimal_input("下限价格（最低价格）: ")
        
        if lower_price >= upper_price:
            print("❌ 错误：下限价格必须小于上限价格！")
            continue
        
        grid_count = get_int_input("网格数量: ")
        base_quantity = get_decimal_input("基础数量（第一格的代币数量）: ")
        
        # 自动计算间隔
        current_price = upper_price
        price_range = upper_price - lower_price
        grid_interval = price_range / grid_count
        is_percentage = False
        
        print(f"\n💡 自动计算：")
        print(f"   价格区间: ${price_range:.6f} (${lower_price:.6f} ~ ${upper_price:.6f})")
        print(f"   每格间隔: ${grid_interval:.6f}")

        # 计算
        try:
            martingale_increment, grid_details = calculator.calculate_for_long_grid(
                current_price, grid_count, grid_interval, base_quantity, is_percentage
            )

            # 5. 输出结果
            print("\n" + "=" * 80)
            print("🎉 计算完成！")
            print("=" * 80)
            print(f"\n📋 关键参数：")
            print(f"   ✅ 网格间隔: {grid_interval}")
            print(f"   ✅ 马丁递增: {martingale_increment}")
            print(f"\n📋 完整配置示例：")
            print(f"   grid_type: \"martingale_{grid_type}\"")
            print(f"   grid_interval: {grid_interval}")
            print(f"   order_amount: {base_quantity}")
            print(f"   martingale_increment: {martingale_increment}")
            print("=" * 80)

        except Exception as e:
            print(f"\n❌ 计算失败: {e}")

        # 6. 是否继续
        print("\n")
        if not get_bool_input("是否继续计算？(y/n) [默认: n]: "):
            break

    print("\n👋 感谢使用马丁递增参数计算器！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已退出")
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()

