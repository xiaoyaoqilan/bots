#!/usr/bin/env python3
"""
马丁网格计算器
用于快速计算马丁网格的总投入金额和倍数关系
"""

from decimal import Decimal, ROUND_HALF_UP
import sys


def calculate_martin_grid(order_amount: Decimal, martingale_increment: Decimal,
                          grid_count: int = 200, price_range_percent: Decimal = Decimal('20')):
    """
    计算马丁网格的总投入金额

    Args:
        order_amount: 第一个格子的金额
        martingale_increment: 马丁递增金额
        grid_count: 网格数量（默认200）
        price_range_percent: 价格幅度百分比（默认20%）

    Returns:
        dict: 包含计算结果的字典
    """
    # 计算第一个和最后一个格子的金额
    grid_1_amount = order_amount
    grid_last_amount = order_amount + (grid_count - 1) * martingale_increment

    # 计算倍数关系
    ratio = grid_last_amount / \
        grid_1_amount if grid_1_amount > 0 else Decimal('0')

    # 计算总金额（使用等差数列求和公式）
    # 总和 = (首项 + 末项) × 项数 / 2
    total_amount = (grid_1_amount + grid_last_amount) * grid_count / 2

    # 计算平均每个格子的金额
    average_amount = total_amount / grid_count

    # 计算累积资金分布关键点
    # 找出用完 50%、75%、90% 资金时到达的网格
    cumulative_amount = Decimal('0')
    milestone_50_grid = None
    milestone_75_grid = None
    milestone_90_grid = None

    for grid_id in range(1, grid_count + 1):
        grid_amount = order_amount + (grid_id - 1) * martingale_increment
        cumulative_amount += grid_amount

        percentage = (cumulative_amount / total_amount) * 100

        if milestone_50_grid is None and percentage >= 50:
            milestone_50_grid = grid_id
        if milestone_75_grid is None and percentage >= 75:
            milestone_75_grid = grid_id
        if milestone_90_grid is None and percentage >= 90:
            milestone_90_grid = grid_id

    # 🔥 修复：计算后期网格的资金占比（确保不超过网格总数）
    last_10_count = min(10, grid_count)
    last_20_count = min(20, grid_count)
    last_50_count = min(50, grid_count)

    last_10_amount = sum(order_amount + (i - 1) * martingale_increment
                         for i in range(max(1, grid_count - last_10_count + 1), grid_count + 1))
    last_20_amount = sum(order_amount + (i - 1) * martingale_increment
                         for i in range(max(1, grid_count - last_20_count + 1), grid_count + 1))
    last_50_amount = sum(order_amount + (i - 1) * martingale_increment
                         for i in range(max(1, grid_count - last_50_count + 1), grid_count + 1))

    last_10_percent = (last_10_amount / total_amount) * \
        100 if total_amount > 0 else Decimal('0')
    last_20_percent = (last_20_amount / total_amount) * \
        100 if total_amount > 0 else Decimal('0')
    last_50_percent = (last_50_amount / total_amount) * \
        100 if total_amount > 0 else Decimal('0')

    # 🔥 动态生成采样点（不再硬编码）
    # 选择关键点：第1格、10%、25%、50%、75%、90%、最后1格
    grid_samples = {}
    sample_points = [
        1,                                    # 第1格
        max(1, int(grid_count * 0.1)),      # 10%
        max(1, int(grid_count * 0.25)),     # 25%
        max(1, int(grid_count * 0.5)),      # 50%
        max(1, int(grid_count * 0.75)),     # 75%
        max(1, int(grid_count * 0.9)),      # 90%
        grid_count                           # 最后1格
    ]

    # 去重并排序
    sample_points = sorted(set(sample_points))

    for grid_id in sample_points:
        amount = order_amount + (grid_id - 1) * martingale_increment
        grid_samples[grid_id] = amount

    return {
        'grid_1_amount': grid_1_amount,
        'grid_last_amount': grid_last_amount,
        'ratio': ratio,
        'total_amount': total_amount,
        'average_amount': average_amount,
        'milestone_50_grid': milestone_50_grid,
        'milestone_75_grid': milestone_75_grid,
        'milestone_90_grid': milestone_90_grid,
        'last_10_count': last_10_count,
        'last_10_percent': last_10_percent,
        'last_20_count': last_20_count,
        'last_20_percent': last_20_percent,
        'last_50_count': last_50_count,
        'last_50_percent': last_50_percent,
        'grid_count': grid_count,
        'price_range_percent': price_range_percent,
        'grid_samples': grid_samples
    }


def print_result(result: dict):
    """打印计算结果"""
    print()
    print("=" * 80)
    print("📊 马丁网格计算结果")
    print("=" * 80)
    print()

    print("【配置参数】")
    print("-" * 80)
    print(f"网格数量: {result['grid_count']}")
    print(f"价格幅度: {result['price_range_percent']}%")
    print()

    print("【网格金额分布】")
    print("-" * 80)
    for grid_id, amount in result['grid_samples'].items():
        if grid_id == 1:
            label = "← 起点（最低价）"
        elif grid_id == result['grid_count']:
            label = f"← 终点（最高价，{result['ratio']:.2f}x）"
        else:
            label = ""
        print(f"Grid {grid_id:3d}: {amount:>12.6f} {label}")
    print()

    print("【核心数据】")
    print("=" * 80)
    print(f"💰 总投入金额:        ${result['total_amount']:>15,.2f}")
    print(f"📊 平均每格金额:      ${result['average_amount']:>15,.6f}")
    print(f"🎯 Grid 1 金额:       ${result['grid_1_amount']:>15,.6f}")
    print(
        f"🎯 Grid {result['grid_count']} 金额:     ${result['grid_last_amount']:>15,.6f}")
    print(f"📈 倍数关系:          {result['ratio']:>15.2f}x")
    print()

    print("【资金消耗进度】")
    print("-" * 80)
    print(
        f"💵 用完 50% 资金:     Grid {result['milestone_50_grid']:>3d} (还剩 {result['grid_count'] - result['milestone_50_grid']} 个网格)")
    print(
        f"💵 用完 75% 资金:     Grid {result['milestone_75_grid']:>3d} (还剩 {result['grid_count'] - result['milestone_75_grid']} 个网格)")
    print(
        f"💵 用完 90% 资金:     Grid {result['milestone_90_grid']:>3d} (还剩 {result['grid_count'] - result['milestone_90_grid']} 个网格)")
    print()

    print("【后期网格资金占比】← 马丁递增越大，这个比例越高")
    print("-" * 80)
    print(
        f"🔸 最后 {result['last_10_count']:2d} 个网格:    占总资金的 {result['last_10_percent']:>5.1f}%")
    print(
        f"🔸 最后 {result['last_20_count']:2d} 个网格:    占总资金的 {result['last_20_percent']:>5.1f}%")
    print(
        f"🔸 最后 {result['last_50_count']:2d} 个网格:    占总资金的 {result['last_50_percent']:>5.1f}%")
    print()

    # 提供一些有用的参考信息
    print("【参考信息】")
    print("-" * 80)
    print(
        f"• 如果初始本金为 ${result['total_amount']:,.2f}，可以承受价格跌幅 {result['price_range_percent']}%")
    print(f"• 每个格子平均投入约 ${result['average_amount']:,.2f}")
    print(f"• 最后一格投入是第一格的 {result['ratio']:.2f} 倍")
    print()

    # 如果倍数关系接近某些常见值，给出提示
    if abs(result['ratio'] - 10) < 0.5:
        print(f"💡 倍数关系接近 10x，适合强趋势行情")
    elif abs(result['ratio'] - 5) < 0.5:
        print(f"💡 倍数关系接近 5x，风险适中")
    elif result['ratio'] < 3:
        print(f"💡 倍数关系较低（<3x），风险较小但资金利用率低")
    elif result['ratio'] > 15:
        print(f"⚠️  倍数关系较高（>15x），后期资金压力大")
    print()


def interactive_mode():
    """交互式模式"""
    print()
    print("=" * 80)
    print("🧮 马丁网格计算器")
    print("=" * 80)
    print()
    print("默认参数:")
    print("  • 网格数量: 200")
    print("  • 价格幅度: 20%")
    print()
    print("提示: 输入 'q' 或 'exit' 退出程序")
    print("提示: 直接回车使用默认值")
    print()

    while True:
        try:
            print("-" * 80)

            # 输入第一个格子的金额
            order_amount_input = input("请输入第一个格子的金额 (例如 0.01): ").strip()
            if order_amount_input.lower() in ['q', 'quit', 'exit']:
                print("\n👋 再见！")
                break

            order_amount = Decimal(order_amount_input)
            if order_amount <= 0:
                print("❌ 金额必须大于 0，请重新输入！")
                continue

            # 输入马丁递增金额
            martingale_input = input("请输入马丁递增金额 (例如 0.0004): ").strip()
            if martingale_input.lower() in ['q', 'quit', 'exit']:
                print("\n👋 再见！")
                break

            martingale_increment = Decimal(martingale_input)
            if martingale_increment < 0:
                print("❌ 递增金额不能为负数，请重新输入！")
                continue

            # 🔥 新增：输入网格数量（支持默认值）
            grid_count_input = input("请输入网格数量 [默认200]: ").strip()
            if grid_count_input.lower() in ['q', 'quit', 'exit']:
                print("\n👋 再见！")
                break

            if grid_count_input == '':
                grid_count = 200  # 默认值
            else:
                grid_count = int(grid_count_input)
                if grid_count <= 0:
                    print("❌ 网格数量必须大于 0，请重新输入！")
                    continue
                elif grid_count > 10000:
                    print("⚠️  网格数量过大（>10000），可能导致计算缓慢")
                    confirm = input("是否继续？(y/N): ").strip().lower()
                    if confirm != 'y':
                        continue

            # 🔥 新增：输入价格幅度（支持默认值）
            price_range_input = input("请输入价格幅度百分比 [默认20%]: ").strip()
            if price_range_input.lower() in ['q', 'quit', 'exit']:
                print("\n👋 再见！")
                break

            if price_range_input == '':
                price_range_percent = Decimal('20')  # 默认值
            else:
                # 去除可能的百分号
                price_range_input = price_range_input.rstrip('%')
                price_range_percent = Decimal(price_range_input)
                if price_range_percent <= 0:
                    print("❌ 价格幅度必须大于 0，请重新输入！")
                    continue
                elif price_range_percent > 100:
                    print("⚠️  价格幅度过大（>100%），请确认是否正确")
                    confirm = input("是否继续？(y/N): ").strip().lower()
                    if confirm != 'y':
                        continue

            # 计算结果
            result = calculate_martin_grid(
                order_amount, martingale_increment, grid_count, price_range_percent)

            # 打印结果
            print_result(result)

            # 询问是否继续
            continue_input = input("是否继续计算？(Y/n): ").strip().lower()
            if continue_input in ['n', 'no']:
                print("\n👋 再见！")
                break

        except ValueError as e:
            print(f"❌ 输入格式错误: {e}")
            print("请输入有效的数字（例如 0.01 或 0.0004）")
            continue
        except KeyboardInterrupt:
            print("\n\n👋 程序被中断，再见！")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")
            continue


def command_line_mode(args: list):
    """
    命令行模式

    支持参数：
    - args[0]: 第一个格子的金额
    - args[1]: 马丁递增金额
    - args[2]: 网格数量（可选，默认200）
    - args[3]: 价格幅度百分比（可选，默认20）
    """
    try:
        # 必需参数
        order_amount_decimal = Decimal(args[0])
        martingale_increment_decimal = Decimal(args[1])

        if order_amount_decimal <= 0:
            print("❌ 第一个格子的金额必须大于 0")
            sys.exit(1)

        if martingale_increment_decimal < 0:
            print("❌ 马丁递增金额不能为负数")
            sys.exit(1)

        # 🔥 可选参数：网格数量
        grid_count = 200  # 默认值
        if len(args) >= 3:
            grid_count = int(args[2])
            if grid_count <= 0:
                print("❌ 网格数量必须大于 0")
                sys.exit(1)

        # 🔥 可选参数：价格幅度
        price_range_percent = Decimal('20')  # 默认值
        if len(args) >= 4:
            # 去除可能的百分号
            price_input = args[3].rstrip('%')
            price_range_percent = Decimal(price_input)
            if price_range_percent <= 0:
                print("❌ 价格幅度必须大于 0")
                sys.exit(1)

        result = calculate_martin_grid(
            order_amount_decimal, martingale_increment_decimal,
            grid_count, price_range_percent)
        print_result(result)

    except (ValueError, IndexError) as e:
        print(f"❌ 参数格式错误: {e}")
        print()
        print("使用方法:")
        print(
            "  python martin_grid_calculator.py <第一格金额> <递增金额> [网格数量] [价格幅度%]")
        print()
        print("示例:")
        print("  python martin_grid_calculator.py 0.01 0.0004")
        print("  python martin_grid_calculator.py 0.01 0.0004 300")
        print("  python martin_grid_calculator.py 0.01 0.0004 300 15")
        print()
        sys.exit(1)


def print_usage():
    """打印使用说明"""
    print()
    print("🧮 马丁网格计算器")
    print()
    print("使用方法:")
    print("  1. 交互式模式（推荐）:")
    print("     python martin_grid_calculator.py")
    print()
    print("  2. 命令行模式:")
    print(
        "     python martin_grid_calculator.py <第一格金额> <递增金额> [网格数量] [价格幅度%]")
    print()
    print("参数说明:")
    print("  <第一格金额>   必需，第一个格子的金额（例如：0.01）")
    print("  <递增金额>     必需，马丁递增金额（例如：0.0004）")
    print("  [网格数量]     可选，默认200")
    print("  [价格幅度%]    可选，默认20%")
    print()
    print("示例:")
    print("  python martin_grid_calculator.py 0.01 0.0004")
    print("  python martin_grid_calculator.py 0.01 0.0004 300")
    print("  python martin_grid_calculator.py 0.01 0.0004 300 15")
    print()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 交互式模式
        interactive_mode()
    elif len(sys.argv) >= 3:
        # 🔥 命令行模式（支持2-4个参数）
        command_line_mode(sys.argv[1:])
    else:
        # 参数错误
        print_usage()
        sys.exit(1)
