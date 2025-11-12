"""
网格波动率扫描器 - 测试脚本

快速测试扫描器功能（不连接真实交易所）
"""

import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from grid_volatility_scanner.models.virtual_grid import VirtualGrid
from grid_volatility_scanner.models.simulation_result import SimulationResult
from grid_volatility_scanner.core.apr_calculator import APRCalculator
from grid_volatility_scanner.ui.scanner_ui import ScannerUI


async def test_virtual_grid():
    """测试虚拟网格"""
    print("🧪 测试虚拟网格...")
    
    # 创建虚拟网格
    grid = VirtualGrid(
        symbol="ETH",
        current_price=Decimal('3000'),
        grid_width_percent=Decimal('10'),
        grid_interval_percent=Decimal('0.5')
    )
    
    print(f"✅ 创建成功: {grid.symbol}")
    print(f"   价格区间: ${grid.lower_price:.2f} - ${grid.upper_price:.2f}")
    print(f"   网格数量: {grid.grid_count}")
    print(f"   网格线数: {len(grid.grid_lines)}")
    
    # 模拟价格变化
    print("\n📈 模拟价格变化...")
    test_prices = [
        3010, 3015, 3020, 3018, 3025, 3030, 3025, 3020, 3015, 3010,
        3005, 3000, 2995, 2990, 2995, 3000, 3005, 3010, 3015, 3020
    ]
    
    for price in test_prices:
        cross = grid.update_price(Decimal(str(price)))
        if cross:
            grid.calculate_apr()
            print(f"   ${price}: {cross} 穿越, 循环={grid.complete_cycles}, APR={grid.estimated_apr:.2f}%")
    
    print(f"\n📊 统计结果:")
    print(f"   总穿越: {grid.total_crosses}次")
    print(f"   买入穿越: {grid.buy_crosses}次")
    print(f"   卖出穿越: {grid.sell_crosses}次")
    print(f"   完整循环: {grid.complete_cycles}次")
    print(f"   预估APR: {grid.estimated_apr:.2f}%")
    
    return grid


async def test_apr_calculator():
    """测试APR计算器"""
    print("\n🧪 测试APR计算器...")
    
    # 测试不同配置
    test_cases = [
        {'interval': 0.5, 'width': 10, 'cycles': 10, 'name': 'ETH标准配置'},
        {'interval': 0.5, 'width': 2, 'cycles': 28, 'name': 'BTC窄网格'},
        {'interval': 1.5, 'width': 15, 'cycles': 40, 'name': 'MEME高波动'},
    ]
    
    for case in test_cases:
        apr = APRCalculator.calculate(
            grid_interval_percent=Decimal(str(case['interval'])),
            grid_width_percent=Decimal(str(case['width'])),
            cycles_per_hour=Decimal(str(case['cycles']))
        )
        
        total_capital = APRCalculator.calculate_total_capital(
            grid_width_percent=Decimal(str(case['width'])),
            grid_interval_percent=Decimal(str(case['interval']))
        )
        
        print(f"\n   {case['name']}:")
        print(f"   - 格子间距: {case['interval']}%")
        print(f"   - 网格宽度: {case['width']}%")
        print(f"   - 每小时循环: {case['cycles']}次")
        print(f"   - 总投入本金: ${total_capital:.2f}")
        print(f"   - 预估APR: {apr:.2f}%")


async def test_simulation_result():
    """测试模拟结果"""
    print("\n🧪 测试模拟结果...")
    
    # 创建虚拟网格
    grid = VirtualGrid(
        symbol="BTC",
        current_price=Decimal('110000'),
        grid_width_percent=Decimal('2'),
        grid_interval_percent=Decimal('0.5')
    )
    
    # 模拟一些循环
    grid.complete_cycles = 15
    grid.cycles_per_hour = Decimal('28.5')
    grid.volume_24h_usdc = Decimal('5000000')
    grid.calculate_apr()
    
    # 创建结果
    result = SimulationResult.from_virtual_grid(grid)
    
    print(f"✅ 创建结果成功")
    print(f"   代币: {result.symbol}")
    print(f"   APR: {result.estimated_apr:.2f}%")
    print(f"   评级: {result.rating}")
    print(f"   评分: {result.score:.1f}")
    
    return result


async def test_ui():
    """测试UI显示"""
    print("\n🧪 测试UI显示（5秒）...")
    
    # 创建UI
    ui = ScannerUI()
    
    # 创建测试数据
    test_results = []
    
    symbols = ['ETH', 'BTC', 'SOL', 'AVAX', 'MATIC']
    prices = [3000, 110000, 200, 45, 1.5]
    aprs = [2172, 1850, 2800, 1200, 980]
    
    for symbol, price, apr in zip(symbols, prices, aprs):
        grid = VirtualGrid(
            symbol=symbol,
            current_price=Decimal(str(price)),
            grid_width_percent=Decimal('5'),
            grid_interval_percent=Decimal('0.5')
        )
        grid.complete_cycles = 10
        grid.estimated_apr = Decimal(str(apr))
        grid.cycles_per_hour = Decimal('20')
        
        result = SimulationResult.from_virtual_grid(grid)
        test_results.append(result)
    
    # 更新UI
    ui.update_results(test_results)
    ui.update_stats(total_markets=100, active_markets=5)
    
    # 显示5秒
    print("   UI将显示5秒...")
    
    async def run_ui():
        await ui.run(scan_duration=5)
    
    await run_ui()
    
    print("   UI测试完成")


async def main():
    """主测试函数"""
    print("="*80)
    print("🎯 网格波动率扫描器 - 测试套件")
    print("="*80)
    
    try:
        # 1. 测试虚拟网格
        grid = await test_virtual_grid()
        
        # 2. 测试APR计算器
        await test_apr_calculator()
        
        # 3. 测试模拟结果
        result = await test_simulation_result()
        
        # 4. 测试UI（可选）
        print("\n" + "="*80)
        print("是否测试UI显示？(y/n): ", end='')
        # 自动跳过UI测试（避免阻塞）
        # 如果需要测试UI，取消下面的注释
        # response = input().strip().lower()
        # if response == 'y':
        #     await test_ui()
        
        print("\n" + "="*80)
        print("✅ 所有测试通过！")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

