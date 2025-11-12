# 网格波动率扫描器 Grid Volatility Scanner

## 📖 简介

网格波动率扫描器是一个强大的市场分析工具，用于：
- 🔍 **实时监控**所有交易对的价格波动
- 📊 **模拟网格交易**，无需实际下单
- 💰 **计算预估APR**，准确预测收益
- 🏆 **推荐最佳标的**，优化交易选择

## 🎯 核心原理

### 模拟网格交易
1. 为每个交易对创建**虚拟网格**（不实际下单）
2. 通过WebSocket接收**实时价格**
3. 检测价格**穿越网格线**
4. 统计**完整循环次数**（1买1卖配对）
5. 计算**实时APR**并排序

### APR计算公式
```python
APR = (格子间距% - 手续费%) × 格子间距% / 网格宽度% × 每小时循环 × 8760
```

**示例：**
- 格子间距 = 0.5%
- 网格宽度 = 10%
- 每小时循环 = 10次
- 手续费 = 0.004%

```
APR = (0.5 - 0.004) × 0.5 / 10 × 10 × 8760
    = 0.496 × 0.05 × 87600
    = 2172.48%
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install rich pyyaml
```

### 2. 配置市场参数

编辑 `config/market_config.yaml`，为不同代币设置网格参数：

```yaml
BTC:
  grid_width_percent: 2.0      # 总宽度：±2%
  grid_interval_percent: 0.5   # 格子间距：0.5%

ETH:
  grid_width_percent: 3.0      # 总宽度：±3%
  grid_interval_percent: 0.5   # 格子间距：0.5%

# 高波动币种
PEPE:
  grid_width_percent: 15.0     # 总宽度：±15%
  grid_interval_percent: 1.5   # 格子间距：1.5%
```

### 3. 运行扫描器

```bash
# 扫描1小时（默认）
python grid_volatility_scanner/run_scanner.py

# 扫描30分钟
python grid_volatility_scanner/run_scanner.py --duration 1800

# 使用Hyperliquid交易所
python grid_volatility_scanner/run_scanner.py --exchange hyperliquid

# 自定义配置文件
python grid_volatility_scanner/run_scanner.py --config my_config.yaml
```

## 📊 UI界面

### 终端界面布局

```
┌─────────────────────────────────────────┐
│  🎯 网格波动率扫描器 v1.0                │
├─────────────────────────────────────────┤
│  📋 扫描摘要                             │
│  - 运行时长: 00:15:30                   │
│  - 监控市场数: 95/100                   │
│  - 有效结果数: 42                       │
│  - 最佳APR: ETH: 2172.48% (🔥 S)       │
├─────────────────────────────────────────┤
│  🏆 代币波动率排行榜 (Top 20)            │
│  ┌──────────────────────────────────┐  │
│  │排名│代币│当前价│循环│APR│评级│      │
│  ├──────────────────────────────────┤  │
│  │🥇  │ETH │$3450│45 │2172%│🔥 S│     │
│  │🥈  │BTC │$110k│28 │1850%│⭐ A│     │
│  │🥉  │SOL │$198 │62 │2800%│🔥 S│     │
│  └──────────────────────────────────┘  │
├─────────────────────────────────────────┤
│  📋 最新日志 (最新20条)                  │
│  ┌──────────────────────────────────┐  │
│  │时间  │级别│模块│消息             │   │
│  │17:30│INFO│scanner│开始扫描...   │   │
│  └──────────────────────────────────┘  │
├─────────────────────────────────────────┤
│  📌 Ctrl+C 停止扫描                      │
└─────────────────────────────────────────┘
```

### 评级系统

| 评级 | APR范围 | 说明 |
|------|---------|------|
| 🔥 S | ≥ 500% | 极度推荐 |
| ⭐ A | ≥ 300% | 强烈推荐 |
| ✅ B | ≥ 150% | 推荐 |
| 🟡 C | ≥ 50%  | 可考虑 |
| ❌ D | < 50%  | 不推荐 |

## ⚙️ 配置文件说明

### 市场配置参数

```yaml
代币名称:
  grid_width_percent: 5.0      # 网格总宽度（%）
  grid_interval_percent: 0.5   # 格子间距（%）
```

**网格数量计算：**
```
网格数量 = grid_width_percent / grid_interval_percent
例如：5% / 0.5% = 10格
```

**总投入本金计算：**
```
每格订单价值 = 10 USDC（固定）
总投入本金 = 10 USDC × 网格数量
例如：10 × 10 = 100 USDC
```

### 全局配置

```yaml
scanner_config:
  min_24h_volume_usdc: 100000      # 最小24h成交量（USDC）
  scan_duration_seconds: 3600      # 默认扫描时长（秒）
  order_value_usdc: 10             # 每格订单价值（固定）
  fee_rate_percent: 0.004          # 双边手续费率（固定）
  ui_refresh_interval: 0.5         # UI刷新间隔（秒）
```

## 📁 项目结构

```
grid_volatility_scanner/
├── __init__.py              # 模块初始化
├── scanner.py               # 主扫描器逻辑
├── run_scanner.py           # 启动脚本
├── README.md                # 本文档
├── config/
│   └── market_config.yaml   # 市场配置文件
├── models/
│   ├── virtual_grid.py      # 虚拟网格模型
│   └── simulation_result.py # 模拟结果模型
├── core/
│   ├── price_monitor.py     # 价格监控器
│   ├── cycle_detector.py    # 循环检测器
│   └── apr_calculator.py    # APR计算器
└── ui/
    └── scanner_ui.py        # Rich终端UI
```

## 🔧 高级用法

### 自定义配置

创建自己的配置文件 `my_config.yaml`：

```yaml
# 保守配置（低风险）
BTC:
  grid_width_percent: 1.5      # 窄网格
  grid_interval_percent: 0.3   # 小间距

# 激进配置（高风险高收益）
MEME_COIN:
  grid_width_percent: 30.0     # 宽网格
  grid_interval_percent: 3.0   # 大间距
```

### 过滤条件

编辑 `scanner_config` 部分：

```yaml
scanner_config:
  min_24h_volume_usdc: 500000  # 提高流动性要求
  min_cycles_to_display: 5     # 只显示循环≥5次的结果
```

## 📈 使用建议

### 1. 扫描时长建议

- **快速测试**: 300-600秒（5-10分钟）
- **标准扫描**: 1800-3600秒（30-60分钟）
- **深度分析**: 7200-10800秒（2-3小时）

### 2. 代币选择建议

根据扫描结果：

| APR | 流动性 | 建议 |
|-----|--------|------|
| >500% | >$1M | 🔥 强烈推荐 |
| >300% | >$500K | ⭐ 推荐 |
| >150% | >$100K | ✅ 可考虑 |
| <50% | 任意 | ❌ 不推荐 |

### 3. 风险提示

⚠️ **重要提示：**
1. APR是**预估值**，基于历史波动
2. 实际收益受市场环境影响
3. 高波动=高收益+高风险
4. 建议分散投资，控制仓位

## 🐛 故障排除

### 问题1：无法连接交易所

```bash
❌ 连接交易所失败: Connection refused
```

**解决方案：**
1. 检查API配置文件 `config/exchanges/lighter_config.yaml`
2. 确认网络连接正常
3. 检查API密钥是否有效

### 问题2：没有有效结果

```bash
⚠️ 没有有效结果
```

**解决方案：**
1. 延长扫描时长（增加 `--duration`）
2. 降低 `min_cycles_to_display` 配置
3. 检查市场是否有足够波动

### 问题3：UI显示异常

**解决方案：**
1. 确保终端窗口足够大（建议 120×40）
2. 检查是否安装了 `rich` 库
3. 尝试禁用其他终端UI工具

## 📞 技术支持

- 📖 文档: `/docs/终端UI稳定显示设计指南.md`
- 📁 日志目录: `/logs/grid_volatility_scanner_*.log`
- 🔧 配置文件: `/grid_volatility_scanner/config/market_config.yaml`

## 🔄 更新日志

### v1.0.0 (2025-01-08)
- ✨ 初始版本发布
- 🎨 Rich终端UI
- 📊 实时APR计算
- 🏆 代币排行榜
- ⚙️ 灵活的配置系统

---

**祝您找到最佳的网格交易标的！** 🚀📈

