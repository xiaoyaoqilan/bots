#!/usr/bin/env python3
"""
简单直接查询 Lighter Account Index

使用官方 API: accountsByL1Address
参考: https://apidocs.lighter.xyz/reference/accountsbyl1address
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import lighter
    from lighter import Configuration, ApiClient
    from lighter.api import AccountApi
    LIGHTER_AVAILABLE = True
except ImportError:
    LIGHTER_AVAILABLE = False
    print("❌ Lighter SDK 未安装")
    print("请运行: pip install git+https://github.com/elliottech/lighter-python.git")
    sys.exit(1)


async def query_account(wallet_address: str, testnet: bool = False):
    """
    查询账户信息
    
    Args:
        wallet_address: 钱包地址（可以大小写混合）
        testnet: 是否使用测试网
    """
    # 设置 URL
    base_url = "https://testnet.zklighter.elliot.ai" if testnet else "https://mainnet.zklighter.elliot.ai"
    network_name = "测试网 (Testnet)" if testnet else "主网 (Mainnet)"
    
    print("\n" + "=" * 70)
    print(f"  查询 Lighter Account Index")
    print("=" * 70)
    print(f"\n网络: {network_name}")
    print(f"URL: {base_url}")
    print(f"钱包地址: {wallet_address}")
    print("\n正在查询...\n")
    
    try:
        # 创建 API 客户端
        configuration = Configuration(host=base_url)
        api_client = ApiClient(configuration=configuration)
        account_api = AccountApi(api_client)
        
        # 尝试原始地址
        print(f"🔍 尝试查询 (原始地址): {wallet_address}")
        try:
            response = await account_api.accounts_by_l1_address(l1_address=wallet_address)
            
            if hasattr(response, 'accounts') and response.accounts:
                print(f"✅ 成功！找到 {len(response.accounts)} 个账户\n")
                
                for idx, account in enumerate(response.accounts, 1):
                    print(f"账户 #{idx}:")
                    print(f"  Account Index: {getattr(account, 'account_index', 'N/A')}")
                    
                    if hasattr(account, 'account_id'):
                        print(f"  Account ID: {account.account_id}")
                    if hasattr(account, 'account_type'):
                        print(f"  Account Type: {account.account_type}")
                    if hasattr(account, 'l1_address'):
                        print(f"  Wallet Address: {account.l1_address}")
                    
                    print()
                
                await api_client.close()
                return response.accounts
            else:
                print("⚠️  未找到账户")
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 查询失败: {error_msg}")
            
            # 如果是 404 或 account not found，尝试其他格式
            if "not found" in error_msg.lower() or "404" in error_msg:
                print("\n尝试其他地址格式...")
                
                # 尝试 checksum 格式
                try:
                    from eth_account import Account
                    checksum_address = Account.to_checksum_address(wallet_address)
                    
                    if checksum_address != wallet_address:
                        print(f"🔍 尝试 Checksum 格式: {checksum_address}")
                        
                        response = await account_api.accounts_by_l1_address(l1_address=checksum_address)
                        
                        if hasattr(response, 'accounts') and response.accounts:
                            print(f"✅ 成功！找到 {len(response.accounts)} 个账户\n")
                            
                            for idx, account in enumerate(response.accounts, 1):
                                print(f"账户 #{idx}:")
                                print(f"  Account Index: {getattr(account, 'account_index', 'N/A')}")
                                if hasattr(account, 'account_type'):
                                    print(f"  Account Type: {account.account_type}")
                                print()
                            
                            await api_client.close()
                            return response.accounts
                except ImportError:
                    print("⚠️  需要安装 eth-account: pip install eth-account")
                except Exception as e2:
                    print(f"❌ Checksum 格式也失败: {e2}")
        
        await api_client.close()
        return None
        
    except Exception as e:
        print(f"\n❌ 查询出错: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """主函数"""
    print("\n" + "🔍 " * 20)
    print("Lighter Account Index 查询工具")
    print("基于官方 API: accountsByL1Address")
    print("🔍 " * 20)
    
    # 获取钱包地址
    print("\n请输入您的以太坊钱包地址：")
    wallet_address = input("钱包地址: ").strip()
    
    if not wallet_address:
        print("❌ 地址不能为空")
        sys.exit(1)
    
    # 确保有 0x 前缀
    if not wallet_address.startswith("0x"):
        wallet_address = "0x" + wallet_address
    
    # 选择网络
    print("\n请选择网络：")
    print("  1. 测试网 (Testnet)")
    print("  2. 主网 (Mainnet)")
    choice = input("\n请选择 [2]: ").strip() or "2"
    
    testnet = choice == "1"
    
    # 查询主网
    accounts = await query_account(wallet_address, testnet=testnet)
    
    # 如果没找到，尝试另一个网络
    if accounts is None or len(accounts) == 0:
        other_network = "测试网" if not testnet else "主网"
        print(f"\n💡 在当前网络未找到账户，是否尝试查询{other_network}？(y/n) [y]: ", end="")
        try_other = input().strip().lower() or "y"
        
        if try_other == "y":
            accounts = await query_account(wallet_address, testnet=not testnet)
    
    # 显示结果
    print("\n" + "=" * 70)
    print("  查询完成")
    print("=" * 70)
    
    if accounts and len(accounts) > 0:
        print("\n✅ 找到账户信息！")
        print("\n接下来请：")
        print("  1. 记录上面显示的 account_index")
        print("  2. 前往 https://app.lighter.xyz/apikeys 查看或创建 API Key")
        print("  3. 记录 api_key_index 和保存 api_key_private_key")
        print("  4. 运行配置助手: python3 tools/lighter_config_helper.py")
    else:
        print("\n⚠️  未找到账户")
        print("\n可能的原因：")
        print("  1. 该钱包地址未在 Lighter 注册")
        print("  2. 地址输入错误")
        print("\n建议：")
        print("  1. 检查钱包地址是否正确")
        print("  2. 确认您在 Lighter 使用的是哪个钱包")
        print("  3. 访问 https://app.lighter.xyz 确认账户状态")
        print("  4. 如果有 API Key，可以运行: python3 tools/query_account_with_apikey.py")
    
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ 查询已取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

