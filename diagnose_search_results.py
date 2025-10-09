#!/usr/bin/env python3
"""
诊断脚本：检查PubMed和PMC的检索结果对比
分析哪些疾病在PubMed中有结果但在PMC中没有
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Set

# 添加src目录到Python路径
project_root = Path(__file__).parent
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

from literature_downloader import OptimizedPMCDownloader, OptimizedPMCConfig, PubMedDownloader, PubMedConfig

def analyze_existing_data():
    """分析已存在的数据"""
    print("🔍 分析已下载的数据...")

    # 检查PubMed数据
    pubmed_dir = project_root / "knowledge_graph" / "data" / "literature" / "PubMed_abstracts" / "abstracts"
    pubmed_files = list(pubmed_dir.glob("*.json"))

    pubmed_data = {}
    for file_path in pubmed_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                disease = data.get('disease', '')
                total_articles = data.get('total_articles', 0)
                articles = data.get('articles', [])

                pmids = [article.get('pmid', '') for article in articles if article.get('pmid')]
                pmcids = [article.get('pmcid', '') for article in articles if article.get('pmcid')]

                pubmed_data[disease] = {
                    'total_articles': total_articles,
                    'pmids': set(pmids),
                    'pmcids': set(pmcids),
                    'file_path': file_path
                }
        except Exception as e:
            print(f"❌ 读取文件失败 {file_path}: {e}")

    print(f"📊 找到 {len(pubmed_data)} 个疾病的PubMed数据")

    # 检查PMC数据
    pmc_dir = project_root / "knowledge_graph" / "data" / "literature" / "PMC_full_text"
    pmc_files = list(pmc_dir.rglob("*.json")) if pmc_dir.exists() else []

    pmc_data = {}
    for file_path in pmc_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # 处理不同的JSON格式
                if 'disease' in data:
                    disease = data.get('disease', '')
                    articles = data.get('articles', [])
                elif 'articles' in data:
                    disease = data.get('identifier', file_path.stem)
                    articles = data.get('articles', [])
                else:
                    continue

                pmc_ids = [article.get('pmc_id', '') for article in articles if article.get('pmc_id')]

                if disease not in pmc_data:
                    pmc_data[disease] = set()
                pmc_data[disease].update(pmc_ids)

        except Exception as e:
            print(f"❌ 读取PMC文件失败 {file_path}: {e}")

    print(f"📊 找到 {len(pmc_data)} 个疾病的PMC数据")

    return pubmed_data, pmc_data

def compare_search_results():
    """对比PubMed和PMC的搜索结果"""
    print("\n" + "="*80)
    print("🔍 PubMed vs PMC 检索结果对比分析")
    print("="*80)

    # 分析现有数据
    pubmed_data, pmc_data = analyze_existing_data()

    if not pubmed_data:
        print("❌ 没有找到PubMed数据，请先运行PubMed下载")
        return

    print(f"\n📊 数据概况:")
    print(f"   📄 PubMed数据: {len(pubmed_data)} 个疾病")
    print(f"   📚 PMC数据: {len(pmc_data)} 个疾病")

    # 统计PubMed中包含PMC ID的文献
    diseases_with_pmc_refs = 0
    total_pmc_refs_in_pubmed = 0

    for disease, data in pubmed_data.items():
        if data['pmcids']:
            diseases_with_pmc_refs += 1
            total_pmc_refs_in_pubmed += len(data['pmcids'])

    print(f"\n📈 PubMed中的PMC引用:")
    print(f"   🔗 有PMC引用的疾病: {diseases_with_pmc_refs}/{len(pubmed_data)} ({diseases_with_pmc_refs/len(pubmed_data)*100:.1f}%)")
    print(f"   📚 总PMC引用数: {total_pmc_refs_in_pubmed}")

    # 显示详细对比
    print(f"\n📋 详细对比 (前10个疾病):")
    print("-" * 80)
    print(f"{'疾病名称':<40} {'PubMed文献':<10} {'PMC引用':<8} {'PMC下载':<8}")
    print("-" * 80)

    count = 0
    for disease, data in sorted(pubmed_data.items()):
        if count >= 10:
            break

        pubmed_count = data['total_articles']
        pmc_refs_count = len(data['pmcids'])
        pmc_downloaded_count = len(pmc_data.get(disease, set()))

        print(f"{disease[:38]:<40} {pubmed_count:<10} {pmc_refs_count:<8} {pmc_downloaded_count:<8}")
        count += 1

    # 分析缺失的PMC数据
    missing_pmc = []
    for disease, data in pubmed_data.items():
        if data['pmcids'] and disease not in pmc_data:
            missing_pmc.append({
                'disease': disease,
                'pubmed_articles': data['total_articles'],
                'pmc_refs': len(data['pmcids']),
                'pmc_ids': list(data['pmcids'])[:5]  # 显示前5个
            })

    if missing_pmc:
        print(f"\n⚠️  缺失PMC数据的疾病 (前5个):")
        for item in missing_pmc[:5]:
            print(f"   📋 {item['disease']}")
            print(f"      📄 PubMed: {item['pubmed_articles']} 篇")
            print(f"      🔗 PMC引用: {item['pmc_refs']} 个")
            print(f"      📚 PMC IDs: {', '.join(item['pmc_ids'])}")
            print()

    print(f"💡 总结: 共有 {len(missing_pmc)} 个疾病在PubMed中有PMC引用但未下载PMC全文")

def test_individual_search():
    """测试单个疾病的搜索结果"""
    print("\n" + "="*80)
    print("🧪 测试单个疾病的搜索结果")
    print("="*80)

    # 配置
    email = "1666526339@qq.com"
    api_key = "f7f3e5ffa36e0446a4a3c6540d8fa7e72808"

    # 测试疾病
    test_disease = "14q11.2 microdeletion syndrome"

    print(f"🔬 测试疾病: {test_disease}")

    # 初始化下载器
    pmc_config = OptimizedPMCConfig(
        email=email,
        api_key=api_key,
        output_dir="test_pmc",
        batch_size=10,
        max_records_per_search=100
    )

    pubmed_config = PubMedConfig(
        email=email,
        api_key=api_key,
        output_dir="test_pubmed",
        batch_size=10,
        max_records_per_search=100
    )

    pmc_downloader = OptimizedPMCDownloader(pmc_config)
    pubmed_downloader = PubMedDownloader(pubmed_config)

    # 测试PMC搜索
    print(f"\n📚 PMC搜索测试...")
    try:
        pmc_ids = pmc_downloader.search_pmc_by_disease(test_disease)
        print(f"   ✅ PMC找到 {len(pmc_ids)} 个ID")
        if pmc_ids:
            print(f"   📋 前5个PMC ID: {', '.join(pmc_ids[:5])}")
    except Exception as e:
        print(f"   ❌ PMC搜索失败: {e}")

    # 测试PubMed搜索
    print(f"\n📄 PubMed搜索测试...")
    try:
        pmids = pubmed_downloader.search_pubmed(test_disease)
        print(f"   ✅ PubMed找到 {len(pmids)} 个PMID")
        if pmids:
            print(f"   📋 前5个PMID: {', '.join(pmids[:5])}")

            # 获取摘要以检查PMC ID
            articles = pubmed_downloader.fetch_abstracts_batch(pmids[:10], test_disease)
            pmc_ids_in_articles = [article.pmcid for article in articles if article.pmcid]
            print(f"   🔗 文章中的PMC ID: {len(pmc_ids_in_articles)} 个")
            if pmc_ids_in_articles:
                print(f"   📋 前5个PMC ID: {', '.join(pmc_ids_in_articles[:5])}")
    except Exception as e:
        print(f"   ❌ PubMed搜索失败: {e}")

def main():
    """主函数"""
    print("🧬 罕见疾病文献检索诊断工具")
    print("="*50)

    # 分析现有数据
    compare_search_results()

    # 测试搜索
    test_individual_search()

    print(f"\n🎯 诊断完成！")
    print(f"💡 如果PMC搜索结果为空，说明该疾病在PMC中没有免费全文")
    print(f"💡 如果PMC有结果但未下载，说明下载流程可能有问题")

if __name__ == "__main__":
    main()