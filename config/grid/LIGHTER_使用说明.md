# Lighter 交易所网格交易使用说明

## ⚠️ 重要前提

**由于 Lighter SDK (v0.1.4) 存在 Bug，脚本无法自动设置保证金模式。**

在运行网格交易前，您**必须**先在 Lighter 网页端手动设置保证金模式和杠杆倍数。

---

## 🔧 设置步骤

### 1. 登录 Lighter 交易所

访问：https://app.lighter.xyz

### 2. 为每个交易对设置保证金模式

对于您计划运行的每个交易对（如 BTC-USD、MEGA-USD 等）：

1. **选择交易对**
2. **设置保证金模式**：
   - `Cross`（全仓）：推荐用于主流币
   - `Isolated`（逐仓）：推荐用于高风险小币
3. **设置杠杆倍数**：
   - 主流币（BTC/ETH）：10-20倍
   - 小市值币（MEGA/VIRTUAL）：3-5倍
   - 做空操作：至少 3 倍

### 3. 运行脚本

设置完成后，直接运行网格交易脚本：

```bash
python3 run_grid_trading.py --config config/grid/lighter-long-perp-btc.yaml
```

脚本会使用您在网页端设置的保证金模式和杠杆倍数。

---

## 📝 配置文件说明

配置文件中的 `margin_mode` 和 `leverage` 参数**仅作为文档参考**，不会自动生效。

**示例配置**：

```yaml
# 这些参数不会自动设置，仅作为参考
margin_mode: "cross"      # 实际模式需在网页端设置
leverage: 20              # 实际杠杆需在网页端设置
```

**建议**：
- 配置文件中填写与网页端一致的值
- 方便日后查看和维护

---

## ⚡ 启动日志

正确设置后，启动时会显示：

```
⚠️ 已跳过保证金模式自动设置（SDK bug: isolated模式无法生效）
📝 当前配置: BTC → cross模式, 20x杠杆
💡 建议: 请在 Lighter 网页端手动设置保证金模式和杠杆（一次性设置即可）
```

如果看到此日志，**且您已在网页端设置好**，则可正常交易。

---

## 📊 推荐配置表

| 代币类型 | 保证金模式 | 杠杆倍数 | 说明 |
|---------|-----------|---------|------|
| BTC, ETH | Cross 或 Isolated | 10-20x | 主流币，流动性好 |
| TRUMP, WLFI | Cross 或 Isolated | 10-20x | 热门 Meme 币 |
| MEGA, VIRTUAL | Cross 或 Isolated | 3-5x | 小市值，高波动 |
| 0G, RESOLV, ZK | Cross 或 Isolated | 3-5x | 新币种，限制较多 |
| 做空操作 | Cross 或 Isolated | ≥3x | 做空需要更多保证金 |

---

## ❓ 常见问题

### Q: 配置文件中的 margin_mode 会生效吗？
**A**: 不会。只能在网页端设置。

### Q: 每次运行都要重新设置吗？
**A**: 不需要。网页端设置一次后，脚本会一直使用该设置。

### Q: 如何验证设置是否成功？
**A**: 运行脚本后，观察是否能正常下单。如果下单失败并报错 `invalid margin mode`，说明网页端设置有问题。

### Q: 为什么不修复 SDK？
**A**: SDK 的底层是编译后的 C 库，无法通过 Python 代码修复。已向 Lighter 官方报告此 Bug。

### Q: 可以混合使用 Cross 和 Isolated 吗？
**A**: 可以。不同交易对可以设置不同的保证金模式。

---

## 📚 更多信息

详细技术说明：`docs/fixes/lighter_margin_mode_sdk_bug.md`

---

**最后更新**: 2025-11-11

