#!/usr/bin/env python3
"""
罕见疾病文献下载入口脚本
简化版使用示例，支持快速测试和大规模下载
"""

import os
import sys
from pathlib import Path

# 添加src目录到Python路径
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from literature_downloader import LiteratureManager, LiteratureConfig, OptimizedPMCDownloader, OptimizedPMCConfig


def quick_test():
    """快速测试 - 处理3个疾病"""
    print("🧪 快速测试模式")
    print("="*50)

    config = LiteratureConfig(
        email="1666526339@qq.com",
        api_key=None,
        base_output_dir="literature_test",

        # 测试配置 - 小规模
        pubmed_disease_batch_size=3,
        pmc_disease_batch_size=3,
        pubmed_max_workers=1,  # 单线程，更稳定
        pubmed_batch_size=100,  # 小批次
        pmc_batch_size=100,
    )

    manager = LiteratureManager(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = manager.load_disease_list(disease_file)

    # 选择前3个疾病测试
    test_diseases = all_diseases[:3]

    print(f"📋 测试疾病: {', '.join(test_diseases)}")

    try:
        results = manager.download_both_sources(test_diseases)
        manager.print_final_summary(results)
        return True
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


def pubmed_only_test():
    """仅测试PubMed下载"""
    print("📄 PubMed摘要下载测试")
    print("="*50)

    config = LiteratureConfig(
        email="1666526339@qq.com",
        api_key=None,
        base_output_dir="pubmed_test",
        pubmed_disease_batch_size=5,
        pubmed_max_workers=2,
        pubmed_batch_size=500,
    )

    manager = LiteratureManager(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = manager.load_disease_list(disease_file)

    # 选择5个疾病测试
    test_diseases = all_diseases[:5]

    print(f"📋 测试疾病: {', '.join(test_diseases)}")

    try:
        results = manager.download_pubmed_abstracts(test_diseases)
        print(f"✅ PubMed测试完成，共获得 {sum(r.get('articles_downloaded', 0) for r in results)} 篇摘要")
        return True
    except Exception as e:
        print(f"❌ PubMed测试失败: {e}")
        return False


def pmc_only_test():
    """仅测试PMC下载"""
    print("📚 PMC全文下载测试")
    print("="*50)

    config = LiteratureConfig(
        email="1666526339@qq.com",
        api_key=None,
        base_output_dir="pmc_test",
        pmc_disease_batch_size=3,
        pmc_batch_size=200,
    )

    manager = LiteratureManager(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = manager.load_disease_list(disease_file)

    # 选择3个疾病测试
    test_diseases = all_diseases[:3]

    print(f"📋 测试疾病: {', '.join(test_diseases)}")

    try:
        results = manager.download_pmc_fulltext(test_diseases)
        print(f"✅ PMC测试完成，共获得 {sum(r.get('articles_downloaded', 0) for r in results)} 篇全文")
        return True
    except Exception as e:
        print(f"❌ PMC测试失败: {e}")
        return False




def optimized_pmc_test():
    """测试优化版PMC下载（基于原脚本）"""
    print("⚡ 优化版PMC批量下载测试")
    print("="*50)

    config = OptimizedPMCConfig(
        email="1666526339@qq.com",
        api_key="f7f3e5ffa36e0446a4a3c6540d8fa7e72808",
        output_dir="optimized_pmc_test",

        # 下载参数（基于原脚本）
        batch_size=200,  # 每批200篇文章
        disease_batch_size=2,  # 每批处理2个疾病
        max_records_per_search=5000,

        # 解析选项
        save_parsed_json=True,
        save_raw_xml=True,
        parse_detailed_content=True
    )

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    with open(disease_file, 'r', encoding='utf-8') as f:
        all_diseases = [line.strip() for line in f if line.strip()]

    # 选择2个疾病测试
    test_diseases = all_diseases[:2]

    print(f"📋 测试疾病: {', '.join(test_diseases)}")
    print(f"📄 批次大小: {config.batch_size} 篇/批")
    print(f"🔧 使用原脚本的核心下载逻辑")

    try:
        downloader = OptimizedPMCDownloader(config)
        results = downloader.process_diseases_batch(test_diseases)
        total_articles = sum(r.get('articles_downloaded', 0) for r in results)
        total_pmids = sum(r.get('pmc_ids_found', 0) for r in results)

        print(f"✅ 优化版PMC测试完成")
        print(f"📊 找到PMC ID: {total_pmids}")
        print(f"📄 下载全文: {total_articles}")
        print(f"📁 数据保存在: {config.output_dir}")

        if total_articles > 0:
            print(f"\n🔧 优化版特点:")
            print(f"   ⚡ 批量下载效率高")
            print(f"   📄 基于原脚本稳定性好")
            print(f"   🔍 支持详细内容解析")
            print(f"   💾 同时保存XML和JSON")

        return True
    except Exception as e:
        print(f"❌ 优化版PMC测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def batch_download():
    """批量下载 - 处理更多疾病"""
    print("🚀 批量下载模式")
    print("="*50)

    config = LiteratureConfig(
        email="1666526339@qq.com",
        api_key="f7f3e5ffa36e0446a4a3c6540d8fa7e72808",
        base_output_dir="literature_batch",

        # 批量配置
        pubmed_disease_batch_size=20,  # 每批20个疾病
        pmc_disease_batch_size=10,
        pubmed_max_workers=3,
        pubmed_batch_size=1000,
        pmc_batch_size=500,
    )

    manager = LiteratureManager(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = manager.load_disease_list(disease_file)

    # 选择前20个疾病
    test_diseases = all_diseases[:20]

    print(f"📋 将处理 {len(test_diseases)} 个疾病")
    print("📋 前5个疾病:", ', '.join(test_diseases[:5]), "...")

    # 确认继续
    response = input(f"\n❓ 确定要开始批量下载吗？(y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("❌ 用户取消下载")
        return False

    try:
        results = manager.download_both_sources(test_diseases)
        manager.print_final_summary(results)
        return True
    except Exception as e:
        print(f"❌ 批量下载失败: {e}")
        return False


def main():
    """主函数 - 交互式选择"""
    print("🧬 罕见疾病文献下载工具")
    print("="*50)

    # 检查邮箱配置
    email = "1666526339@qq.com"
    if email == "your_email@example.com":
        print("❌ 请先在脚本中配置你的邮箱地址！")
        print("💡 编辑 download_literature.py 文件，修改 email 变量")
        return

    print(f"📧 使用邮箱: {email}")
    print()

    # 提供选项
    print("请选择下载模式:")
    print("1. 🧪 快速测试 (3个疾病，PubMed+PMC)")
    print("2. 📄 仅PubMed摘要测试 (5个疾病)")
    print("3. 📚 仅PMC全文测试 (3个疾病)")
    print("4. ⚡ 优化版PMC批量下载 (基于原脚本，高性能)")
    print("5. 🚀 批量下载 (20个疾病，PubMed+PMC)")
    print("q. 退出")

    while True:
        choice = input("\n请输入选项 (1-5, q): ").strip().lower()

        if choice == '1':
            print("\n开始快速测试...")
            success = quick_test()
            break
        elif choice == '2':
            print("\n开始PubMed摘要测试...")
            success = pubmed_only_test()
            break
        elif choice == '3':
            print("\n开始PMC全文测试...")
            success = pmc_only_test()
            break
        elif choice == '4':
            print("\n开始优化版PMC批量下载...")
            success = optimized_pmc_test()
            break
        elif choice == '5':
            print("\n开始批量下载...")
            success = batch_download()
            break
        elif choice == 'q':
            print("👋 退出程序")
            return
        else:
            print("❌ 无效选项，请重新选择")

    if success:
        print(f"\n🎉 下载完成！")
        print(f"💡 查看输出目录获取下载的文献数据")
        print(f"💡 建议获取NCBI API key以提高下载速度: https://www.ncbi.nlm.nih.gov/account/")
    else:
        print(f"\n❌ 下载失败，请检查错误信息")


if __name__ == "__main__":
    main()