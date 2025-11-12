# 🔄 Account Index 快速转换参考

## 快速启动
```bash
python tools/convert_account_index.py
```

## 常用命令

| 场景 | 命令 | 示例 |
|------|------|------|
| 十进制→十六进制 | `python tools/convert_account_index.py [数字]` | `python tools/convert_account_index.py 123` → `0x7b` |
| 十六进制→十进制 | `python tools/convert_account_index.py [0x数字]` | `python tools/convert_account_index.py 0x7b` → `123` |
| 批量转换 | `python tools/convert_account_index.py [值1] [值2]...` | `python tools/convert_account_index.py 0 1 10` |
| 交互模式 | `python tools/convert_account_index.py` | 持续输入，输入 `q` 退出 |

## 常见案例

### 前端显示 → 配置文件
```
前端: 0x7b
命令: python tools/convert_account_index.py 0x7b
结果: 123
配置: account_index: 123
```

### 配置文件 → 区块链浏览器
```
配置: account_index: 123
命令: python tools/convert_account_index.py 123
结果: 0x7b
浏览器: https://explorer.lighter.xyz/account/0x7b
```

## 常用值对照表

| 十进制 | 十六进制 |
|-------|---------|
| 0 | 0x0 |
| 1 | 0x1 |
| 2 | 0x2 |
| 10 | 0xa |
| 100 | 0x64 |
| 123 | 0x7b |
| 255 | 0xff |

---

💡 **提示**: 配置文件只接受十进制！

