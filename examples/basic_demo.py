#!/usr/bin/env python3
"""MESA引擎基础演示"""

from core.engine import MESAEngine
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    """演示MESA引擎基本功能"""
    print("🚀 启动MESA引擎演示")

    # 创建引擎
    engine = MESAEngine("demo_engine")

    try:
        # 启动引擎
        await engine.start()
        print("✅ MESA引擎启动成功")

        # 获取状态
        status = engine.get_status()
        print(f"📊 引擎状态: {status}")

        # 运行2秒
        await asyncio.sleep(2)

        # 健康检查
        health = await engine.health_check()
        print(f"🔍 健康检查: {health['status']}")

    finally:
        # 停止引擎
        await engine.stop()
        print("🛑 MESA引擎已停止")


if __name__ == "__main__":
    asyncio.run(main())
