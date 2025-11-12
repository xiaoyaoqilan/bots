# 网格配置生成器 - 快速参考

## ⚡ 一分钟上手

### 基本使用

```bash
# 只需输入代币名称（大小写随意）
python3 tools/grid_config_generator.py btc
python3 tools/grid_config_generator.py ETH
python3 tools/grid_config_generator.py Bnb
```

### 工作流程

```
输入代币 → 获取价格 → 计算参数 → 更新配置 → [自动同步] → 完成！
```

---

## ⚙️ 快速配置

编辑 `tools/grid_config_generator.yaml`：

```yaml
grid_value_per_order: 12          # 每格投入：$12 USDC
grid_range_percentage: 50         # 网格区间：50%
follow_grid_count: 500            # 总网格数：500
auto_sync: true                   # 自动同步：开启
```

---

## 📊 计算逻辑

### 做多 (Long)

```
当前价格: $100,000
区间百分比: 50%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
价格区间: [$50,000, $100,000]
网格间隔: $50,000 / 500 = $100
首格价格: $50,100
每格数量: $12 / $50,100 = 0.0002395 BTC
```

### 做空 (Short)

```
当前价格: $100,000
区间百分比: 50%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
价格区间: [$100,000, $150,000]
网格间隔: $50,000 / 500 = $100
首格价格: $149,900
每格数量: $12 / $149,900 = 0.0000800 BTC
```

---

## 🎯 实战示例

### 示例1：生成BTC配置

```bash
$ python3 tools/grid_config_generator.py btc

==================================================
  🚀 网格配置生成器
==================================================

✅ 工具配置加载成功
📡 正在获取 BTC 价格...
✅ 获取价格成功: BTC = $99,845.50
🧮 正在计算网格参数...
✅ 计算完成

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 计算结果摘要 - BTC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 价格信息：
  • 当前价格: $99,845.50
  • 价格区间: [$49,922.75, $99,845.50]
  • 网格间隔: 99.85

⚙️  网格参数：
  • 总网格数: 500
  • 每格数量: 0.00023989 BTC
  • 数量精度: 5
  • 价格精度: 1

💰 投入估算：
  • 每格价值: $12 USDC
  • 总投入: $6,000 USDC (全部成交)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 配置文件已保存: lighter-long-perp-btc.yaml
🔄 正在同步配置到其他目录...
✅ 同步完成！

✅ 全部完成！
```

### 示例2：批量生成

```bash
# 生成多个代币配置
for token in btc eth bnb mega zk; do
  python3 tools/grid_config_generator.py $token
done
```

---

## 🔧 常用调整

### 1. 修改投入金额

```yaml
# tools/grid_config_generator.yaml
grid_value_per_order: 15  # 改为 $15 USDC/格
```

### 2. 修改网格区间

```yaml
# tools/grid_config_generator.yaml
grid_range_percentage: 70  # 改为 70%
```

### 3. 启用马丁递增

```yaml
# tools/grid_config_generator.yaml
enable_martingale: true
martingale_increment_usd: 1  # 每格递增 $1 USDC
```

### 4. 切换做空模式

```yaml
# tools/grid_config_generator.yaml
direction: "short"  # 改为做空
```

### 5. 禁用自动同步

```yaml
# tools/grid_config_generator.yaml
auto_sync: false  # 禁用自动同步
```

---

## 📁 文件命名

| 输入 | 生成的文件名 | symbol字段 |
|------|-------------|-----------|
| `btc` | `lighter-long-perp-btc.yaml` | `BTC` |
| `ETH` | `lighter-long-perp-eth.yaml` | `ETH` |
| `Bnb` | `lighter-long-perp-bnb.yaml` | `BNB` |

**自动处理大小写！**

---

## ❓ 常见问题

### Q: 无法获取价格？

**A:** 检查网络连接，或手动在配置文件中设置参数。

### Q: 想用已有配置作为模板？

**A:** 编辑工具配置：
```yaml
template_file: "lighter-long-perp-btc.yaml"
```

### Q: 如何验证计算是否正确？

**A:** 工具会显示详细的计算摘要，检查：
- 价格区间是否合理
- 网格间隔是否合适
- 每格数量是否符合预期

### Q: 生成后想微调某些参数？

**A:** 直接编辑生成的配置文件，或修改工具配置后重新生成。

---

## 📚 完整文档

- 详细使用说明：[README_grid_config_generator.md](./README_grid_config_generator.md)
- 配置同步工具：[README_sync_configs.md](./README_sync_configs.md)
- 系统主文档：[../README.md](../README.md)

---

## 💡 最佳实践

1. **先测试单个代币** → 检查结果 → 批量生成
2. **定期备份配置** → 避免误操作
3. **小资金测试** → 验证参数正确性
4. **监控首次运行** → 确保网格正常工作

---

**祝你使用愉快！🎉**

