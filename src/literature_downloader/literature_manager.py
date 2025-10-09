#!/usr/bin/env python3
"""
罕见疾病文献管理器
整合PubMed摘要和PMC全文下载功能
提供统一的文献获取和管理接口
"""

import os
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from .pubmed_downloader import PubMedDownloader, PubMedConfig
from .optimized_pmc_downloader import OptimizedPMCDownloader, OptimizedPMCConfig


@dataclass
class LiteratureConfig:
    """文献下载统一配置"""
    email: str
    api_key: Optional[str] = None
    base_output_dir: str = "literature_data"

    # PubMed配置
    pubmed_batch_size: int = 1000
    pubmed_disease_batch_size: int = 50
    pubmed_sleep_time: float = 0.34
    pubmed_max_workers: int = 3

    # PMC配置
    pmc_batch_size: int = 500
    pmc_disease_batch_size: int = 20
    pmc_sleep_time: float = 0.34
    pmc_max_records_per_search: int = 10000

    # 通用配置
    max_retry: int = 3
    request_timeout: int = 30


class LiteratureManager:
    """罕见疾病文献管理器"""

    def __init__(self, config: LiteratureConfig):
        self.config = config
        self.setup_directories()
        self.init_downloaders()

    def setup_directories(self):
        """创建目录结构"""
        self.base_dir = Path(self.config.base_output_dir)
        self.pubmed_dir = self.base_dir / "pubmed"
        self.pmc_dir = self.base_dir / "pmc"
        self.integrated_dir = self.base_dir / "integrated"
        self.metadata_dir = self.base_dir / "metadata"

        for dir_path in [self.base_dir, self.pubmed_dir, self.pmc_dir,
                        self.integrated_dir, self.metadata_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def init_downloaders(self):
        """初始化下载器"""
        # PubMed下载器配置
        pubmed_config = PubMedConfig(
            email=self.config.email,
            api_key=self.config.api_key,
            output_dir=str(self.pubmed_dir),
            batch_size=self.config.pubmed_batch_size,
            disease_batch_size=self.config.pubmed_disease_batch_size,
            sleep_time=self.config.pubmed_sleep_time,
            max_workers=self.config.pubmed_max_workers,
            max_retry=self.config.max_retry,
            request_timeout=self.config.request_timeout
        )

        # PMC下载器配置
        pmc_config = OptimizedPMCConfig(
            email=self.config.email,
            api_key=self.config.api_key,
            output_dir=str(self.pmc_dir),
            batch_size=self.config.pmc_batch_size,
            disease_batch_size=self.config.pmc_disease_batch_size,
            sleep_time=self.config.pmc_sleep_time,
            max_records_per_search=self.config.pmc_max_records_per_search,
            max_retry=self.config.max_retry
        )

        self.pubmed_downloader = PubMedDownloader(pubmed_config)
        self.pmc_downloader = OptimizedPMCDownloader(pmc_config)

    def load_disease_list(self, disease_file: str) -> List[str]:
        """加载罕见疾病列表"""
        with open(disease_file, 'r', encoding='utf-8') as f:
            diseases = [line.strip() for line in f if line.strip()]
        print(f"[INFO] 加载了 {len(diseases)} 个罕见疾病")
        return diseases

    def download_pubmed_abstracts(self, diseases: List[str]) -> List[Dict]:
        """下载PubMed摘要"""
        print("\n" + "="*60)
        print("📄 开始下载PubMed摘要")
        print("="*60)

        return self.pubmed_downloader.process_diseases_batch(diseases)

    def download_pmc_fulltext(self, diseases: List[str]) -> List[Dict]:
        """下载PMC全文"""
        print("\n" + "="*60)
        print("📚 开始下载PMC全文")
        print("="*60)

        return self.pmc_downloader.process_diseases_batch(diseases)

    def download_both_sources(self, diseases: List[str]) -> Dict:
        """同时下载PubMed摘要和PMC全文"""
        print("\n" + "="*80)
        print("🔬 罕见疾病文献批量下载 - 双数据源")
        print("="*80)

        results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'diseases_processed': diseases,
            'total_diseases': len(diseases),
            'start_time': time.time(),
            'pubmed_results': None,
            'pmc_results': None,
            'integrated_summary': None
        }

        # 下载PubMed摘要
        try:
            results['pubmed_results'] = self.download_pubmed_abstracts(diseases)
        except Exception as e:
            print(f"[ERROR] PubMed下载失败: {e}")
            results['pubmed_results'] = []

        # 下载PMC全文
        try:
            results['pmc_results'] = self.download_pmc_fulltext(diseases)
        except Exception as e:
            print(f"[ERROR] PMC下载失败: {e}")
            results['pmc_results'] = []

        # 生成整合总结
        results['end_time'] = time.time()
        results['total_time'] = results['end_time'] - results['start_time']
        results['integrated_summary'] = self.generate_integrated_summary(results)

        # 保存完整结果
        self.save_integrated_results(results)

        return results

    def generate_integrated_summary(self, results: Dict) -> Dict:
        """生成整合总结"""
        pubmed_results = results.get('pubmed_results', [])
        pmc_results = results.get('pmc_results', [])

        # 统计PubMed结果
        pubmed_successful = [r for r in pubmed_results if r.get('success', False)]
        pubmed_failed = [r for r in pubmed_results if not r.get('success', False)]
        total_pmids = sum(r.get('pmids_found', 0) for r in pubmed_successful)
        total_abstracts = sum(r.get('articles_downloaded', 0) for r in pubmed_successful)

        # 统计PMC结果
        pmc_successful = [r for r in pmc_results if r.get('success', False)]
        pmc_failed = [r for r in pmc_results if not r.get('success', False)]
        total_pmc_ids = sum(r.get('pmc_ids_found', 0) for r in pmc_successful)
        total_fulltext = sum(r.get('articles_downloaded', 0) for r in pmc_successful)

        # 找出共同成功的疾病
        pubmed_diseases = {r['disease'] for r in pubmed_successful}
        pmc_diseases = {r['disease'] for r in pmc_successful}
        common_diseases = pubmed_diseases.intersection(pmc_diseases)

        return {
            'processing_summary': {
                'total_diseases': len(results['diseases_processed']),
                'total_time_minutes': results['total_time'] / 60,
                'average_time_per_disease': results['total_time'] / len(results['diseases_processed'])
            },
            'pubmed_summary': {
                'successful_diseases': len(pubmed_successful),
                'failed_diseases': len(pubmed_failed),
                'total_pmids_found': total_pmids,
                'total_abstracts_downloaded': total_abstracts,
                'success_rate': len(pubmed_successful) / len(pubmed_results) if pubmed_results else 0
            },
            'pmc_summary': {
                'successful_diseases': len(pmc_successful),
                'failed_diseases': len(pmc_failed),
                'total_pmc_ids_found': total_pmc_ids,
                'total_fulltext_downloaded': total_fulltext,
                'success_rate': len(pmc_successful) / len(pmc_results) if pmc_results else 0
            },
            'coverage_analysis': {
                'diseases_with_pubmed_only': len(pubmed_diseases - pmc_diseases),
                'diseases_with_pmc_only': len(pmc_diseases - pubmed_diseases),
                'diseases_with_both_sources': len(common_diseases),
                'diseases_with_no_data': len(results['diseases_processed']) - len(pubmed_diseases.union(pmc_diseases))
            },
            'data_quality': {
                'avg_abstracts_per_disease': total_abstracts / len(pubmed_successful) if pubmed_successful else 0,
                'avg_fulltext_per_disease': total_fulltext / len(pmc_successful) if pmc_successful else 0,
                'total_literature_items': total_abstracts + total_fulltext
            }
        }

    def save_integrated_results(self, results: Dict):
        """保存整合结果"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        results_file = self.metadata_dir / f"integrated_results_{timestamp}.json"

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n[INFO] 整合结果已保存: {results_file}")

        # 生成简要报告
        report_file = self.metadata_dir / f"summary_report_{timestamp}.txt"
        self.generate_text_report(results, report_file)

    def generate_text_report(self, results: Dict, report_file: Path):
        """生成文本报告"""
        summary = results['integrated_summary']

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("罕见疾病文献下载报告\n")
            f.write("="*50 + "\n\n")
            f.write(f"下载时间: {results['timestamp']}\n")
            f.write(f"处理疾病数: {results['total_diseases']}\n")
            f.write(f"总用时: {results['total_time']:.1f} 秒 ({results['total_time']/60:.1f} 分钟)\n\n")

            # PubMed摘要统计
            pubmed_summary = summary['pubmed_summary']
            f.write("📄 PubMed摘要下载统计:\n")
            f.write(f"  成功疾病: {pubmed_summary['successful_diseases']}\n")
            f.write(f"  失败疾病: {pubmed_summary['failed_diseases']}\n")
            f.write(f"  找到PMID: {pubmed_summary['total_pmids_found']}\n")
            f.write(f"  下载摘要: {pubmed_summary['total_abstracts_downloaded']}\n")
            f.write(f"  成功率: {pubmed_summary['success_rate']:.1%}\n\n")

            # PMC全文统计
            pmc_summary = summary['pmc_summary']
            f.write("📚 PMC全文下载统计:\n")
            f.write(f"  成功疾病: {pmc_summary['successful_diseases']}\n")
            f.write(f"  失败疾病: {pmc_summary['failed_diseases']}\n")
            f.write(f"  找到PMC ID: {pmc_summary['total_pmc_ids_found']}\n")
            f.write(f"  下载全文: {pmc_summary['total_fulltext_downloaded']}\n")
            f.write(f"  成功率: {pmc_summary['success_rate']:.1%}\n\n")

            # 数据覆盖分析
            coverage = summary['coverage_analysis']
            f.write("📊 数据覆盖分析:\n")
            f.write(f"  仅有摘要的疾病: {coverage['diseases_with_pubmed_only']}\n")
            f.write(f"  仅有全文的疾病: {coverage['diseases_with_pmc_only']}\n")
            f.write(f"  双数据源疾病: {coverage['diseases_with_both_sources']}\n")
            f.write(f"  无数据疾病: {coverage['diseases_with_no_data']}\n\n")

            # 数据质量评估
            quality = summary['data_quality']
            f.write("📈 数据质量评估:\n")
            f.write(f"  平均摘要数/疾病: {quality['avg_abstracts_per_disease']:.1f}\n")
            f.write(f"  平均全文数/疾病: {quality['avg_fulltext_per_disease']:.1f}\n")
            f.write(f"  总文献条目: {quality['total_literature_items']}\n\n")

            f.write(f"📁 数据保存位置:\n")
            f.write(f"  PubMed摘要: {self.pubmed_dir}\n")
            f.write(f"  PMC全文: {self.pmc_dir}\n")
            f.write(f"  元数据: {self.metadata_dir}\n")

        print(f"[INFO] 文本报告已保存: {report_file}")

    def print_final_summary(self, results: Dict):
        """打印最终总结"""
        summary = results['integrated_summary']
        proc_summary = summary['processing_summary']

        print("\n" + "="*80)
        print("🎉 罕见疾病文献下载完成！")
        print("="*80)

        print(f"📅 处理时间: {results['timestamp']}")
        print(f"🔬 处理疾病: {proc_summary['total_diseases']} 个")
        print(f"⏱️  总用时: {proc_summary['total_time_minutes']:.1f} 分钟")
        print(f"⚡ 平均速度: {proc_summary['average_time_per_disease']:.1f} 秒/疾病")

        print(f"\n📄 PubMed摘要:")
        pubmed = summary['pubmed_summary']
        print(f"   ✅ 成功: {pubmed['successful_diseases']} 疾病")
        print(f"   📊 摘要: {pubmed['total_abstracts_downloaded']} 篇")
        print(f"   📈 成功率: {pubmed['success_rate']:.1%}")

        print(f"\n📚 PMC全文:")
        pmc = summary['pmc_summary']
        print(f"   ✅ 成功: {pmc['successful_diseases']} 疾病")
        print(f"   📊 全文: {pmc['total_fulltext_downloaded']} 篇")
        print(f"   📈 成功率: {pmc['success_rate']:.1%}")

        coverage = summary['coverage_analysis']
        print(f"\n📊 数据覆盖:")
        print(f"   🔄 双数据源: {coverage['diseases_with_both_sources']} 疾病")
        print(f"   📄 仅摘要: {coverage['diseases_with_pubmed_only']} 疾病")
        print(f"   📚 仅全文: {coverage['diseases_with_pmc_only']} 疾病")
        print(f"   ❌ 无数据: {coverage['diseases_with_no_data']} 疾病")

        print(f"\n📁 文件位置:")
        print(f"   📂 数据目录: {self.base_dir}")
        print(f"   📋 报告文件: {self.metadata_dir}")

        print("="*80)


def main():
    """主函数示例"""
    print("🧬 罕见疾病文献管理器示例")
    print("="*50)

    # 配置
    config = LiteratureConfig(
        email="1666526339@qq.com",  # 请替换为你的邮箱
        api_key=None,  # 可选：NCBI API key
        base_output_dir="rare_disease_literature",

        # 小规模测试配置
        pubmed_disease_batch_size=5,  # 每批处理5个疾病
        pmc_disease_batch_size=5,
        pubmed_max_workers=2,         # 降低并发数
    )

    print(f"📧 邮箱: {config.email}")
    print(f"📁 输出目录: {config.base_output_dir}")

    # 检查邮箱配置
    if config.email == "your_email@example.com":
        print("\n❌ 请先配置你的邮箱地址！")
        return

    # 初始化管理器
    manager = LiteratureManager(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = manager.load_disease_list(disease_file)

    # 选择测试疾病
    test_diseases = all_diseases[:3]  # 只处理前3个疾病作为测试

    print(f"\n🧪 测试模式：处理前 {len(test_diseases)} 个疾病")
    print("📋 疾病列表:")
    for i, disease in enumerate(test_diseases, 1):
        print(f"   {i}. {disease}")

    # 确认继续
    response = input(f"\n❓ 确定要开始下载吗？(y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("❌ 用户取消下载")
        return

    try:
        # 执行下载
        results = manager.download_both_sources(test_diseases)

        # 打印最终总结
        manager.print_final_summary(results)

    except KeyboardInterrupt:
        print(f"\n⚠️ 用户中断下载")
    except Exception as e:
        print(f"\n❌ 下载过程出现错误: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n🎉 示例完成！")


if __name__ == "__main__":
    main()