#!/bin/bash

echo "======================================"
echo "       套利系统端口检查"
echo "======================================"

# 检查8000端口 (后端API)
echo "检查8000端口 (后端API服务)..."
if lsof -i:8000 >/dev/null 2>&1; then
    echo "✅ 8000端口已占用 (后端服务正在运行)"
    lsof -i:8000 | head -2
else
    echo "❌ 8000端口未占用 (后端服务未启动)"
fi

echo ""

# 检查5173端口 (前端Vite)
echo "检查5173端口 (前端Vite服务)..."
if lsof -i:5173 >/dev/null 2>&1; then
    echo "✅ 5173端口已占用 (前端服务正在运行)"
    lsof -i:5173 | head -2
else
    echo "❌ 5173端口未占用 (前端服务未启动)"
fi

echo ""

# 测试后端API连接
echo "测试后端API连接..."
if curl -s http://localhost:8000/docs >/dev/null 2>&1; then
    echo "✅ 后端API服务可访问: http://localhost:8000"
else
    echo "❌ 后端API服务不可访问"
fi

# 测试前端界面连接
echo "测试前端界面连接..."
if curl -s http://localhost:5173 >/dev/null 2>&1; then
    echo "✅ 前端界面可访问: http://localhost:5173"
else
    echo "❌ 前端界面不可访问"
fi

echo ""
echo "======================================"
echo "端口配置总结:"
echo "🎯 前端界面: http://localhost:5173"
echo "📡 后端API: http://localhost:8000"
echo "📖 API文档: http://localhost:8000/docs"
echo "======================================" 