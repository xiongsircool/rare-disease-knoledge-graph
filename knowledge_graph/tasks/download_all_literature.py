#!/usr/bin/env python3
"""
罕见疾病全量文献下载脚本
基于修复后的PMC下载器，下载所有罕见疾病相关文献并生成统计报告
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

# 添加src目录到Python路径
project_root = Path(__file__).parent.parent.parent
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

from literature_downloader import OptimizedPMCDownloader, OptimizedPMCConfig, PubMedDownloader, PubMedConfig


class AllLiteratureDownloader:
    """全量文献下载器"""

    def __init__(self, download_mode: str = "pmc_only"):
        """
        初始化配置

        Args:
            download_mode: 下载模式
                - "pmc_only": 仅下载PMC全文
                - "pubmed_only": 仅下载PubMed摘要
                - "both": 同时下载PubMed摘要和PMC全文
        """
        self.email = "1666526339@qq.com"
        self.api_key = "f7f3e5ffa36e0446a4a3c6540d8fa7e72808"
        self.download_mode = download_mode

        # 输出目录
        self.base_output_dir = project_root / "knowledge_graph" / "data" / "literature"
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化下载器
        self.init_downloaders()

    def init_downloaders(self):
        """初始化下载器"""
        # PMC下载器配置
        if self.download_mode in ["pmc_only", "both"]:
            self.pmc_config = OptimizedPMCConfig(
                email=self.email,
                api_key=self.api_key,
                output_dir=str(self.base_output_dir / "PMC_full_text"),
                batch_size=100,  # 每批下载的文章数
                disease_batch_size=20,  # 每批处理的疾病数
                max_records_per_search=100000,
                sleep_time=0.34,
                sleep_time_with_key=0.12,
                max_retry=3,
                save_parsed_json=True,
                save_raw_xml=True,
                parse_detailed_content=True
            )
            self.pmc_downloader = OptimizedPMCDownloader(self.pmc_config)

        # PubMed下载器配置
        if self.download_mode in ["pubmed_only", "both"]:
            self.pubmed_config = PubMedConfig(
                email=self.email,
                api_key=self.api_key,
                output_dir=str(self.base_output_dir / "PubMed_abstracts"),
                max_records_per_search=100000,
                batch_size=1000,
                disease_batch_size=20,
                sleep_time=0.34,
                sleep_time_with_key=0.12,
                max_retry=3,
                request_timeout=30,
                max_workers=3
            )
            self.pubmed_downloader = PubMedDownloader(self.pubmed_config)

        # 统计信息
        self.stats = {
            'total_diseases': 0,
            'successful_retrievals': 0,
            'failed_retrievals': 0,
            'total_pubmed_pmids': 0,
            'total_pubmed_abstracts': 0,
            'total_pmc_ids': 0,
            'total_pmc_articles': 0,
            'disease_stats': {},
            'start_time': None,
            'end_time': None,
            'duration': 0
        }

    def load_disease_list(self) -> List[str]:
        """加载罕见疾病列表"""
        disease_file = project_root / "all_rare_disease_names.txt"
        print(f"📋 加载疾病列表: {disease_file}")

        with open(disease_file, 'r', encoding='utf-8') as f:
            diseases = [line.strip() for line in f if line.strip()]

        print(f"✅ 加载了 {len(diseases)} 个罕见疾病")
        return diseases

    def process_all_diseases(self, diseases: List[str], max_diseases: Optional[int] = None):
        """处理所有疾病"""
        if max_diseases:
            diseases = diseases[:max_diseases]

        self.stats['total_diseases'] = len(diseases)
        self.stats['start_time'] = datetime.now()

        print(f"\n🚀 开始下载 {len(diseases)} 个罕见疾病的文献")
        print(f"📂 输出目录: {self.base_output_dir}")
        print(f"⏰ 开始时间: {self.stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        for i, disease in enumerate(diseases, 1):
            print(f"\n📋 进度: {i}/{len(diseases)} - {disease[:80]}...")

            disease_stats = self.process_single_disease(disease)
            self.stats['disease_stats'][disease] = disease_stats

            # 更新总体统计
            has_content = (disease_stats.get('pubmed_pmids', 0) > 0 or
                          disease_stats.get('pmc_ids', 0) > 0)

            if has_content:
                self.stats['successful_retrievals'] += 1
            else:
                self.stats['failed_retrievals'] += 1

            # 累计计数
            self.stats['total_pubmed_pmids'] += disease_stats.get('pubmed_pmids', 0)
            self.stats['total_pubmed_abstracts'] += disease_stats.get('pubmed_abstracts', 0)
            self.stats['total_pmc_ids'] += disease_stats.get('pmc_ids', 0)
            self.stats['total_pmc_articles'] += disease_stats.get('pmc_articles', 0)

            # 每10个疾病显示一次进度
            if i % 10 == 0:
                self.show_progress_summary(i)

            # 避免请求过快
            time.sleep(0.5)

        self.stats['end_time'] = datetime.now()
        self.stats['duration'] = (self.stats['end_time'] - self.stats['start_time']).total_seconds()

        print(f"\n✅ 全部下载完成！")
        print(f"⏰ 结束时间: {self.stats['end_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  总用时: {self.stats['duration']:.1f} 秒")

    def process_single_disease(self, disease: str) -> Dict:
        """处理单个疾病"""
        disease_stats = {
            'disease': disease,
            'pubmed_pmids': 0,
            'pubmed_abstracts': 0,
            'pmc_ids': 0,
            'pmc_articles': 0,
            'success': False,
            'error': None,
            'processing_time': 0
        }

        start_time = time.time()

        try:
            # PubMed下载
            if self.download_mode in ["pubmed_only", "both"]:
                print(f"   🔍 搜索PubMed摘要...")
                try:
                    result = self.pubmed_downloader.process_single_disease(disease)
                    disease_stats['pubmed_pmids'] = result.get('pmids_found', 0)
                    disease_stats['pubmed_abstracts'] = result.get('articles_downloaded', 0)

                    if disease_stats['pubmed_pmids'] > 0:
                        print(f"   📄 找到 {disease_stats['pubmed_pmids']} 个PMID")
                        print(f"   ✅ 成功下载 {disease_stats['pubmed_abstracts']} 篇摘要")
                    else:
                        print(f"   ❌ PubMed中未找到相关文献")

                except Exception as e:
                    print(f"   ❌ PubMed处理失败: {e}")

            # PMC下载
            if self.download_mode in ["pmc_only", "both"]:
                print(f"   🔍 搜索PMC全文...")
                pmc_ids = self.pmc_downloader.search_pmc_by_disease(disease)
                disease_stats['pmc_ids'] = len(pmc_ids)

                if pmc_ids:
                    print(f"   📚 找到 {len(pmc_ids)} 个PMC ID")

                    # 下载全文
                    articles_count = self.pmc_downloader.download_pmc_by_disease(disease, pmc_ids)
                    disease_stats['pmc_articles'] = articles_count
                    print(f"   ✅ 成功下载 {articles_count} 篇全文")
                else:
                    print(f"   ❌ PMC中未找到免费全文")

            disease_stats['success'] = True  # 处理成功

        except Exception as e:
            print(f"   ❌ 处理失败: {e}")
            disease_stats['error'] = str(e)

        disease_stats['processing_time'] = time.time() - start_time
        return disease_stats

    def show_progress_summary(self, processed_count: int):
        """显示进度摘要"""
        success_rate = (self.stats['successful_retrievals'] / processed_count) * 100

        print(f"\n📊 进度摘要 (处理了 {processed_count} 个疾病):")
        print(f"   ✅ 成功检索: {self.stats['successful_retrievals']} ({success_rate:.1f}%)")

        if self.download_mode in ["pubmed_only", "both"]:
            avg_pubmed = self.stats['total_pubmed_pmids'] / processed_count if processed_count > 0 else 0
            print(f"   📄 PubMed摘要: {self.stats['total_pubmed_pmids']} PMIDs (平均 {avg_pubmed:.1f} 个/疾病)")
            print(f"   📄 已下载摘要: {self.stats['total_pubmed_abstracts']} 篇")

        if self.download_mode in ["pmc_only", "both"]:
            avg_pmc = self.stats['total_pmc_ids'] / processed_count if processed_count > 0 else 0
            print(f"   📚 PMC全文: {self.stats['total_pmc_ids']} PMC IDs (平均 {avg_pmc:.1f} 个/疾病)")
            print(f"   📄 已下载全文: {self.stats['total_pmc_articles']} 篇")

    def generate_final_report(self):
        """生成最终报告"""
        summary = {
            'total_diseases': self.stats['total_diseases'],
            'successful_retrievals': self.stats['successful_retrievals'],
            'failed_retrievals': self.stats['failed_retrievals'],
            'success_rate': (self.stats['successful_retrievals'] / self.stats['total_diseases']) * 100 if self.stats['total_diseases'] > 0 else 0,
            'start_time': self.stats['start_time'].isoformat(),
            'end_time': self.stats['end_time'].isoformat(),
            'duration_seconds': self.stats['duration'],
            'duration_formatted': f"{self.stats['duration']/3600:.1f} 小时" if self.stats['duration'] > 3600 else f"{self.stats['duration']/60:.1f} 分钟",
            'download_mode': self.download_mode
        }

        # 根据下载模式添加相应统计
        if self.download_mode in ["pubmed_only", "both"]:
            summary.update({
                'total_pubmed_pmids': self.stats['total_pubmed_pmids'],
                'total_pubmed_abstracts': self.stats['total_pubmed_abstracts'],
                'avg_pubmed_pmids_per_disease': self.stats['total_pubmed_pmids'] / self.stats['total_diseases'] if self.stats['total_diseases'] > 0 else 0
            })

        if self.download_mode in ["pmc_only", "both"]:
            summary.update({
                'total_pmc_ids': self.stats['total_pmc_ids'],
                'total_pmc_articles': self.stats['total_pmc_articles'],
                'avg_pmc_articles_per_disease': self.stats['total_pmc_ids'] / self.stats['total_diseases'] if self.stats['total_diseases'] > 0 else 0
            })

        report = {
            'summary': summary,
            'output_directory': str(self.base_output_dir),
            'disease_details': self.stats['disease_stats']
        }

        # 保存报告
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.base_output_dir / f"download_report_{timestamp}.json"

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n📄 详细报告已保存: {report_file}")

        # 显示摘要
        self.display_summary(report['summary'])

    def display_summary(self, summary: Dict):
        """显示摘要信息"""
        print("\n" + "="*80)
        print("📊 罕见疾病文献下载统计报告")
        print("="*80)
        print(f"📅 处理时间: {summary['start_time'][:19]} ~ {summary['end_time'][:19]}")
        print(f"⏱️  总用时: {summary['duration_formatted']}")
        print(f"📥 下载模式: {summary['download_mode']}")
        print()
        print(f"🔬 疾病总数: {summary['total_diseases']}")
        print(f"✅ 成功检索: {summary['successful_retrievals']} ({summary['success_rate']:.1f}%)")
        print(f"❌ 检索失败: {summary['failed_retrievals']}")
        print()

        # 根据下载模式显示相应统计
        if self.download_mode in ["pubmed_only", "both"]:
            print(f"📄 PubMed摘要:")
            print(f"   🔍 总PMIDs: {summary.get('total_pubmed_pmids', 0)}")
            print(f"   📥 已下载摘要: {summary.get('total_pubmed_abstracts', 0)}")
            print(f"   📈 平均每疾病: {summary.get('avg_pubmed_pmids_per_disease', 0):.1f} 个")
            print()

        if self.download_mode in ["pmc_only", "both"]:
            print(f"📚 PMC全文:")
            print(f"   🔍 总PMC IDs: {summary.get('total_pmc_ids', 0)}")
            print(f"   📥 已下载全文: {summary.get('total_pmc_articles', 0)}")
            print(f"   📈 平均每疾病: {summary.get('avg_pmc_articles_per_disease', 0):.1f} 篇")
            print()

        print(f"📁 数据保存位置: {self.base_output_dir}")
        print("="*80)


def main():
    """主函数"""
    print("🧬 罕见疾病全量文献下载工具")
    print("="*50)

    # 选择下载模式
    print("请选择下载模式:")
    print("1. 📄 仅下载PubMed摘要")
    print("2. 📚 仅下载PMC全文")
    print("3. 🔄 同时下载PubMed摘要和PMC全文")

    while True:
        try:
            choice = input("\n请输入选项 (1-3): ").strip()
            if choice == '1':
                download_mode = "pubmed_only"
                break
            elif choice == '2':
                download_mode = "pmc_only"
                break
            elif choice == '3':
                download_mode = "both"
                break
            else:
                print("❌ 请输入 1-3 之间的数字")
        except KeyboardInterrupt:
            print("\n👋 用户取消，退出程序")
            return

    print(f"\n🚀 选择了下载模式: {download_mode}")
    downloader = AllLiteratureDownloader(download_mode)

    # 加载疾病列表
    diseases = downloader.load_disease_list()

    # 询问用户要处理多少个疾病
    print(f"\n💡 提示:")
    print(f"   - 测试建议: 50-100 个疾病")
    print(f"   - 中等规模: 500-1000 个疾病")
    print(f"   - 全量下载: {len(diseases)} 个疾病")
    print(f"   - 按 Ctrl+C 可随时停止")

    while True:
        try:
            user_input = input(f"\n请输入要处理的疾病数量 (1-{len(diseases)}, 默认50): ").strip()
            if not user_input:
                max_diseases = 50
            else:
                max_diseases = int(user_input)
                if max_diseases < 1 or max_diseases > len(diseases):
                    print(f"❌ 请输入 1-{len(diseases)} 之间的数字")
                    continue
            break
        except ValueError:
            print("❌ 请输入有效的数字")
        except KeyboardInterrupt:
            print("\n👋 用户取消，退出程序")
            return

    print(f"\n🚀 开始处理 {max_diseases} 个疾病...")

    try:
        # 处理疾病
        downloader.process_all_diseases(diseases, max_diseases)

        # 生成报告
        downloader.generate_final_report()

        print(f"\n🎉 任务完成！")
        print(f"💡 可以查看下载的文献数据和统计报告")

    except KeyboardInterrupt:
        print(f"\n⚠️  用户中断了下载过程")
        downloader.stats['end_time'] = datetime.now()
        downloader.generate_final_report()
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()