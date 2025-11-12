#!/bin/bash
# 新架构启动脚本

echo "启动 Trading System (新架构)"
echo "========================="

# 激活虚拟环境 (如果存在)
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "虚拟环境已激活"
fi

# 启动主应用
echo "启动 API 服务器..."
python main.py

echo "系统启动完成"
