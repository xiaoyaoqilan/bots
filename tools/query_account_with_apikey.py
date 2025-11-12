#!/usr/bin/env python3
"""
使用 API Key 查询 Lighter Account Index

如果您已经有 API Key，但不知道 account_index，可以使用这个工具查询
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import lighter
    from lighter import Configuration, ApiClient, SignerClient
    from lighter.api import AccountApi
    LIGHTER_AVAILABLE = True
except ImportError:
    LIGHTER_AVAILABLE = False
    print("❌ Lighter SDK 未安装")
    print("请运行: pip install git+https://github.com/elliottech/lighter-python.git")
    sys.exit(1)


class AccountInfoQuery:
    """通过 API Key 查询账户信息"""

    def __init__(self):
        self.testnet = True
        self.api_key_private_key = ""
        self.base_url = ""
        self.account_index_guess = 0
        self.api_key_index = 0

    def print_header(self, title):
        """打印标题"""
        print("\n" + "=" * 70)
        print(f"  {title}")
        print("=" * 70)

    def welcome(self):
        """欢迎信息"""
        self.print_header("使用 API Key 查询 Account Index")
        print("\n✅ 这个方法最可靠！")
        print("\n您需要准备：")
        print("  • API Key Private Key（您创建 API Key 时保存的私钥）")
        print("  • API Key Index（通常是 0, 1, 2 等）")
        print("\n💡 提示：")
        print("  • 我们会尝试多个可能的 account_index")
        print("  • 直到找到正确的为止")

    def get_user_input(self):
        """获取用户输入"""
        self.print_header("步骤1：输入 API Key 信息")

        # 选择网络
        print("\n请选择网络：")
        print("  1. 测试网 (Testnet)")
        print("  2. 主网 (Mainnet)")

        while True:
            choice = input("\n请选择 [2]: ").strip() or "2"
            if choice in ["1", "2"]:
                self.testnet = choice == "1"
                break
            print("❌ 请输入 1 或 2")

        # 设置 URL
        if self.testnet:
            self.base_url = "https://testnet.zklighter.elliot.ai"
            print(f"\n✅ 已选择测试网: {self.base_url}")
        else:
            self.base_url = "https://mainnet.zklighter.elliot.ai"
            print(f"\n✅ 已选择主网: {self.base_url}")

        # 获取 API Key 私钥
        print("\n请输入您的 API Key Private Key：")
        print("💡 这是您创建 API Key 时保存的私钥，以 0x 开头")

        while True:
            self.api_key_private_key = input("\nAPI Key Private Key: ").strip()
            if not self.api_key_private_key:
                print("❌ 私钥不能为空")
                continue
            if not self.api_key_private_key.startswith("0x"):
                print("⚠️  私钥应该以 0x 开头，是否自动添加？(y/n) [y]: ", end="")
                add_prefix = input().strip().lower() or "y"
                if add_prefix == "y":
                    self.api_key_private_key = "0x" + self.api_key_private_key
            break

        print(
            f"\n✅ 私钥已接收: {self.api_key_private_key[:10]}...{self.api_key_private_key[-10:]}")

        # 获取 API Key Index
        print("\n请输入您的 API Key Index：")
        print("💡 从截图看，您可能是 0 (Desktop) 或 1 (Mobile)")

        while True:
            api_key_index_str = input("\nAPI Key Index [0]: ").strip() or "0"
            try:
                self.api_key_index = int(api_key_index_str)
                break
            except ValueError:
                print("❌ 请输入有效的整数")

        print(f"\n✅ API Key Index: {self.api_key_index}")

    async def try_account_index(self, account_index):
        """尝试使用特定的 account_index 连接"""
        try:
            # 创建 SignerClient
            client = lighter.SignerClient(
                url=self.base_url,
                private_key=self.api_key_private_key,
                account_index=account_index,
                api_key_index=self.api_key_index,
            )

            # 检查客户端
            err = client.check_client()

            if err is None:
                # 成功！
                print(f"    ✅ 成功！account_index = {account_index}")

                # 尝试获取账户信息验证
                api_client = lighter.ApiClient(
                    configuration=lighter.Configuration(host=self.base_url))
                account_api = lighter.AccountApi(api_client)

                try:
                    account_info = await account_api.account(by="index", value=str(account_index))
                    if hasattr(account_info, 'account'):
                        acc = account_info.account
                        print(f"\n    账户信息：")
                        if hasattr(acc, 'account_index'):
                            print(f"      Account Index: {acc.account_index}")
                        if hasattr(acc, 'account_type'):
                            print(f"      Account Type: {acc.account_type}")
                except Exception:
                    pass

                await api_client.close()
                await client.close()
                return account_index
            else:
                # 失败，继续尝试
                return None

        except Exception as e:
            return None

    async def search_account_index(self):
        """搜索正确的 account_index"""
        self.print_header("步骤2：搜索 Account Index")

        print("\n正在尝试不同的 account_index 值...")
        print("(这可能需要一些时间，请稍候)\n")

        # 尝试范围：0-100, 然后更大的范围
        test_ranges = [
            range(0, 100),        # 常见范围
            range(100, 500),      # 扩展范围
            range(500, 1000),     # 更大范围
            range(1000, 5000, 10)  # 跳跃搜索
        ]

        for test_range in test_ranges:
            print(f"🔍 搜索范围: {test_range.start} - {test_range.stop}")

            for account_index in test_range:
                if account_index % 10 == 0:
                    print(f"  测试: {account_index}...", end='\r')

                result = await self.try_account_index(account_index)
                if result is not None:
                    return result

            print()  # 换行

        print("\n⚠️  在尝试的范围内未找到匹配的 account_index")
        return None

    def show_result(self, account_index):
        """显示结果"""
        self.print_header("步骤3：配置信息")

        if account_index is not None:
            print(f"\n🎉 找到了！您的配置信息：")
            print(f"\n  Network: {'Testnet' if self.testnet else 'Mainnet'}")
            print(f"  Account Index: {account_index}")
            print(f"  API Key Index: {self.api_key_index}")

            print("\n请使用以下配置：")
            print("\n--- config/exchanges/lighter_config.yaml ---")
            print(f"api_config:")
            print(f"  testnet: {'true' if self.testnet else 'false'}")
            print(f"  auth:")
            print(f"    account_index: {account_index}")
            print(f"    api_key_private_key: \"{self.api_key_private_key}\"")
            print(f"    api_key_index: {self.api_key_index}")
            print("-------------------------------------------")

            print("\n或者使用环境变量：")
            print(
                f"  export LIGHTER_TESTNET=\"{'true' if self.testnet else 'false'}\"")
            print(f"  export LIGHTER_ACCOUNT_INDEX=\"{account_index}\"")
            print(f"  export LIGHTER_API_KEY=\"{self.api_key_private_key}\"")
            print(f"  export LIGHTER_API_KEY_INDEX=\"{self.api_key_index}\"")

            print("\n✅ 接下来可以：")
            print("  1. 运行配置助手: python3 tools/lighter_config_helper.py")
            print("  2. 运行测试: python3 tests/adapters/lighter/test_lighter_adapter.py")
        else:
            print("\n⚠️  未能找到正确的 account_index")
            print("\n可能的原因：")
            print("  1. API Key Private Key 不正确")
            print("  2. API Key Index 不正确")
            print("  3. 网络选择不正确（测试网/主网）")
            print("\n建议：")
            print("  1. 检查 API Key Private Key 是否正确")
            print("  2. 尝试其他 API Key Index (0, 1, 2...)")
            print("  3. 确认网络选择（主网/测试网）")
            print("  4. 联系 Lighter 官方支持")

    async def run(self):
        """运行查询流程"""
        self.welcome()
        self.get_user_input()

        account_index = await self.search_account_index()
        self.show_result(account_index)

        self.print_header("查询完成")
        print()


async def main():
    """主函数"""
    query = AccountInfoQuery()
    try:
        await query.run()
    except KeyboardInterrupt:
        print("\n\n❌ 查询已取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
