#!/usr/bin/env python3
"""
罕见疾病文献下载启动器
提供简单的交互界面来选择和运行不同的下载脚本
"""

import os
import sys
from pathlib import Path

def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')

def display_banner():
    """显示横幅"""
    print("🧬" + "="*60 + "🧬")
    print("     罕见疾病知识图谱 - 文献下载工具")
    print("🧬" + "="*60 + "🧬")
    print()

def main():
    """主函数"""
    clear_screen()
    display_banner()

    print("📋 请选择下载脚本:")
    print()
    print("1️⃣  优化版脚本 (推荐新手使用)")
    print("   📌 特点: 顺序处理，稳定可靠，网络压力小")
    print("   🎯 适用: 稳定网络环境，注重数据完整性")
    print()
    print("2️⃣  并发版脚本 (推荐高级用户使用)")
    print("   📌 特点: 并发处理，速度快，网络压力中等")
    print("   🎯 适用: 高性能环境，注重处理速度")
    print()
    print("3️⃣  查看使用说明")
    print("   📌 查看详细的使用指南和配置说明")
    print()
    print("4️⃣  退出程序")
    print()

    while True:
        try:
            choice = input("请输入选项 (1-4): ").strip()
            print()

            if choice == '1':
                print("🚀 启动优化版文献下载脚本...")
                print("📁 脚本路径: optimized_download_literature.py")
                print("-" * 50)

                # 检查脚本文件是否存在
                script_path = Path(__file__).parent / "optimized_download_literature.py"
                if not script_path.exists():
                    print("❌ 错误: 找不到 optimized_download_literature.py 文件")
                    input("按回车键继续...")
                    continue

                # 切换到脚本目录并运行
                os.chdir(script_path.parent)
                os.system(f"python {script_path.name}")
                break

            elif choice == '2':
                print("⚡ 启动并发版文献下载脚本...")
                print("📁 脚本路径: concurrent_download_literature.py")
                print("-" * 50)

                # 检查脚本文件是否存在
                script_path = Path(__file__).parent / "concurrent_download_literature.py"
                if not script_path.exists():
                    print("❌ 错误: 找不到 concurrent_download_literature.py 文件")
                    input("按回车键继续...")
                    continue

                # 切换到脚本目录并运行
                os.chdir(script_path.parent)
                os.system(f"python {script_path.name}")
                break

            elif choice == '3':
                print("📖 打开使用说明...")
                print("📁 文档路径: README_DOWNLOAD_SCRIPTS.md")
                print("-" * 50)

                # 检查文档文件是否存在
                doc_path = Path(__file__).parent / "README_DOWNLOAD_SCRIPTS.md"
                if not doc_path.exists():
                    print("❌ 错误: 找不到 README_DOWNLOAD_SCRIPTS.md 文件")
                    input("按回车键继续...")
                    continue

                # 显示文档内容
                try:
                    with open(doc_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        print(content)
                        input("\n按回车键返回主菜单...")
                        clear_screen()
                        display_banner()
                        print("📋 请选择下载脚本:")
                        print()
                        print("1️⃣  优化版脚本 (推荐新手使用)")
                        print("   📌 特点: 顺序处理，稳定可靠，网络压力小")
                        print("   🎯 适用: 稳定网络环境，注重数据完整性")
                        print()
                        print("2️⃣  并发版脚本 (推荐高级用户使用)")
                        print("   📌 特点: 并发处理，速度快，网络压力中等")
                        print("   🎯 适用: 高性能环境，注重处理速度")
                        print()
                        print("3️⃣  查看使用说明")
                        print("   📌 查看详细的使用指南和配置说明")
                        print()
                        print("4️⃣  退出程序")
                        print()
                        continue
                except Exception as e:
                    print(f"❌ 读取文档失败: {e}")
                    input("按回车键继续...")
                    continue

            elif choice == '4':
                print("👋 感谢使用罕见疾病文献下载工具！")
                print("🌟 如果觉得有用，请给个Star支持一下项目！")
                break

            else:
                print("❌ 请输入有效的选项 (1-4)")
                input("按回车键重新输入...")
                clear_screen()
                display_banner()
                print("📋 请选择下载脚本:")
                print()
                print("1️⃣  优化版脚本 (推荐新手使用)")
                print("   📌 特点: 顺序处理，稳定可靠，网络压力小")
                print("   🎯 适用: 稳定网络环境，注重数据完整性")
                print()
                print("2️⃣  并发版脚本 (推荐高级用户使用)")
                print("   📌 特点: 并发处理，速度快，网络压力中等")
                print("   🎯 适用: 高性能环境，注重处理速度")
                print()
                print("3️⃣  查看使用说明")
                print("   📌 查看详细的使用指南和配置说明")
                print()
                print("4️⃣  退出程序")
                print()

        except KeyboardInterrupt:
            print("\n\n👋 用户取消，退出程序")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
            input("按回车键继续...")
            clear_screen()
            display_banner()
            continue

if __name__ == "__main__":
    main()