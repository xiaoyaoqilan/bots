# Scripts 脚本目录

本目录包含系统部署、维护和工具脚本。

## 目录结构

### `deployment/` - 部署脚本
- **`start_system.sh`** - 系统启动脚本（简单版本）
- **`stop_system.sh`** - 系统停止脚本（包含端口清理）

### `migration/` - 迁移脚本
- 用于数据库迁移、配置迁移等脚本（预留）

### 工具脚本
- **`check_ports.sh`** - 端口占用检查工具

## 使用说明

### 部署脚本

#### 启动系统
```bash
# 使用部署脚本启动
bash scripts/deployment/start_system.sh

# 或直接使用主程序（推荐）
python main.py           # API模式
python run_monitor.py    # 监控模式  
python run_hybrid.py     # 混合模式
```

#### 停止系统
```bash
# 停止系统并清理端口
bash scripts/deployment/stop_system.sh
```

### 工具脚本

#### 检查端口占用
```bash
# 检查系统使用的端口状态
bash scripts/check_ports.sh
```

## 注意事项

- 部署脚本适用于简单的部署场景
- 生产环境建议使用更完善的部署工具（如Docker、systemd等）
- 工具脚本主要用于开发和调试 