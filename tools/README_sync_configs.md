# 配置文件同步工具使用说明

## 📋 功能介绍

这个工具帮助你将主目录（`crypto-trading`）的配置文件快速同步到所有子账户目录。

## 🚀 快速开始

### 1. 基本使用

```bash
# 进入工具目录
cd /Volumes/T7/crypto-trading/tools

# 同步所有配置文件
./sync_configs.sh

# 查看帮助
./sync_configs.sh --help
```

## 📖 使用示例

### 示例1：同步所有配置文件

```bash
./sync_configs.sh
```

**效果：**
- 将主目录所有 `.yaml` 配置文件同步到 5 个子账户目录
- 自动跳过不存在的目录

### 示例2：只同步BTC配置

```bash
./sync_configs.sh lighter-long-perp-btc.yaml
```

**效果：**
- 只更新BTC配置文件
- 其他配置文件保持不变

### 示例3：同步多个指定币种

```bash
./sync_configs.sh 'lighter-long-perp-{btc,eth,mega}.yaml'
```

**注意：** 需要用引号包裹通配符

### 示例4：同步前自动备份

```bash
./sync_configs.sh --backup lighter-long-perp-btc.yaml
```

**效果：**
- 同步前自动备份目标文件
- 备份保存在 `/Volumes/T7/config_backups/日期时间/`

### 示例5：预览模式（不实际修改）

```bash
./sync_configs.sh --dry-run
```

**效果：**
- 只显示将要同步的文件
- 显示文件差异
- 不实际修改文件

### 示例6：交互式确认

```bash
./sync_configs.sh --interactive
```

**效果：**
- 每个文件询问是否同步
- 更安全，防止误操作

### 示例7：只同步到指定账户

```bash
./sync_configs.sh --target zhanghu1,zhanghu3 lighter-long-perp-btc.yaml
```

**效果：**
- 只同步到账户1和账户3
- 其他账户不受影响

### 示例8：组合使用

```bash
# 备份 + 交互式 + 指定文件
./sync_configs.sh --backup --interactive lighter-long-perp-btc.yaml

# 预览 + 详细输出
./sync_configs.sh --dry-run --verbose
```

## 🎯 常用场景

### 场景1：修改了通用参数，同步到所有账户

```bash
# 1. 修改主目录配置
vim /Volumes/T7/crypto-trading/config/grid/lighter-long-perp-btc.yaml

# 2. 预览将要更新的内容
./sync_configs.sh --dry-run lighter-long-perp-btc.yaml

# 3. 确认无误后同步
./sync_configs.sh lighter-long-perp-btc.yaml
```

### 场景2：批量更新多个币种配置

```bash
# 修改了BTC、ETH、MEGA的配置
./sync_configs.sh 'lighter-long-perp-{btc,eth,mega}.yaml'
```

### 场景3：重要更新，需要备份

```bash
# 修改了关键参数，同步前备份
./sync_configs.sh --backup --interactive lighter-long-perp-btc.yaml
```

### 场景4：测试新配置，先只更新一个账户

```bash
# 只更新到账户1测试
./sync_configs.sh --target zhanghu1 lighter-long-perp-btc.yaml

# 测试通过后，再同步到所有账户
./sync_configs.sh lighter-long-perp-btc.yaml
```

## ⚙️ 选项说明

| 选项 | 简写 | 说明 |
|-----|------|------|
| `--help` | `-h` | 显示帮助信息 |
| `--all` | `-a` | 同步所有配置文件（默认） |
| `--dry-run` | `-d` | 预览模式，不实际修改 |
| `--backup` | `-b` | 同步前备份目标文件 |
| `--interactive` | `-i` | 交互式确认每个文件 |
| `--target <账户>` | `-t` | 只同步到指定账户 |
| `--verbose` | `-v` | 显示详细信息 |

## 🛡️ 安全建议

### ✅ 推荐做法

1. **修改配置前先预览**
   ```bash
   ./sync_configs.sh --dry-run
   ```

2. **重要修改记得备份**
   ```bash
   ./sync_configs.sh --backup
   ```

3. **不确定时使用交互模式**
   ```bash
   ./sync_configs.sh --interactive
   ```

### ⚠️ 注意事项

1. **脚本会覆盖目标文件** - 请确保主目录的配置是正确的
2. **账户特定配置不要同步** - 如果某个账户有特殊配置，使用 `--target` 排除
3. **同步前检查程序是否在运行** - 最好在程序停止时同步配置

## 📁 目录结构

```
/Volumes/T7/
├── crypto-trading/                    # 主目录（配置源）
│   ├── config/grid/
│   │   ├── lighter-long-perp-btc.yaml
│   │   ├── lighter-long-perp-eth.yaml
│   │   └── ...
│   └── tools/
│       └── sync_configs.sh            # 同步脚本
│
├── crypto-trading_zhanghu1/          # 子账户1（同步目标）
│   └── config/grid/
├── crypto-trading_zhanghu2/          # 子账户2（同步目标）
│   └── config/grid/
├── crypto-trading_zhanghu3/          # 子账户3（同步目标）
│   └── config/grid/
├── crypto-trading_zhanghu4/          # 子账户4（同步目标）
│   └── config/grid/
├── crypto-trading_zhanghu5/          # 子账户5（同步目标）
│   └── config/grid/
│
└── config_backups/                    # 备份目录（自动创建）
    └── 20251110_120000/
        ├── crypto-trading_zhanghu1/
        └── ...
```

## 🔧 自定义配置

如果你有更多子账户目录，可以编辑脚本修改 `TARGETS` 数组：

```bash
vim /Volumes/T7/crypto-trading/tools/sync_configs.sh

# 找到这一行，添加新目录：
TARGETS=(
    "/Volumes/T7/crypto-trading_zhanghu1/config/grid"
    "/Volumes/T7/crypto-trading_zhanghu2/config/grid"
    # ... 添加更多
)
```

## 🐛 故障排查

### 问题1：权限错误

```bash
# 解决：添加可执行权限
chmod +x /Volumes/T7/crypto-trading/tools/sync_configs.sh
```

### 问题2：找不到文件

```bash
# 检查源目录路径是否正确
ls /Volumes/T7/crypto-trading/config/grid/
```

### 问题3：同步失败

```bash
# 使用详细模式查看错误
./sync_configs.sh --verbose --dry-run
```

## 💡 高级技巧

### 技巧1：创建别名

在 `~/.zshrc` 或 `~/.bashrc` 中添加：

```bash
alias sync-grid='cd /Volumes/T7/crypto-trading/tools && ./sync_configs.sh'
```

然后就可以在任何位置运行：

```bash
sync-grid lighter-long-perp-btc.yaml
```

### 技巧2：定时同步

创建 cron 任务，每天自动同步（慎用）：

```bash
# 每天凌晨3点同步
0 3 * * * /Volumes/T7/crypto-trading/tools/sync_configs.sh --backup
```

### 技巧3：同步后自动通知

```bash
# 同步完成后发送通知
./sync_configs.sh && osascript -e 'display notification "配置同步完成" with title "网格交易系统"'
```

## 📞 支持

如果遇到问题或有改进建议，请查看主项目的 README 或联系开发者。

---

**版本：** 1.0  
**最后更新：** 2025-11-10

