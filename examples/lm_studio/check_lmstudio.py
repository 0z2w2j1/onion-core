"""
LM Studio 连接诊断脚本
"""
import asyncio
import sys


async def check_lmstudio():
    """诊断 LM Studio 连接状态"""
    import requests
    
    urls_to_try = [
        ("http://localhost:1234/v1/models", "OpenAI兼容"),
        ("http://localhost:1234/api/v1/models", "LM Studio v1 API"),
    ]
    
    print("="*50)
    print("LM Studio 连接诊断")
    print("="*50)
    
    for url, name in urls_to_try:
        print(f"\n尝试 {name}...")
        try:
            r = requests.get(url, timeout=5)
            print(f"✓ 状态码: {r.status_code}")
            print(f"  响应: {r.text[:200]}")
        except requests.exceptions.ConnectionError:
            print(f"✗ 无法连接 - 服务未启动")
        except requests.exceptions.Timeout:
            print(f"✗ 连接超时")
        except Exception as e:
            print(f"✗ 错误: {type(e).__name__}: {e}")
    
    print("\n" + "="*50)
    print("解决步骤:")
    print("="*50)
    print("""
1. 打开 LM Studio 应用程序
2. 在左侧搜索并下载模型 (如 gemma-4-e4b)
3. 点击模型 → Load
4. 点击底部中间的 "Start Local AI Server" 按钮 (三角形)
5. 确认显示 "Server Running at http://localhost:1234"
    """)


if __name__ == "__main__":
    asyncio.run(check_lmstudio())