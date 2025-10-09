#!/usr/bin/env python3
"""
并发版罕见疾病文献下载脚本
采用三阶段策略：
1. 阶段一：并发收集所有疾病的文献ID，去重
2. 阶段二：批量下载去重后的PMC全文
3. 阶段三：批量下载去重后的PubMed摘要
"""

import os
import sys
import time
import json
import pickle
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal

# 添加src目录到Python路径
project_root = Path(__file__).parent.parent.parent
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

from literature_downloader import OptimizedPMCDownloader, OptimizedPMCConfig, PubMedDownloader, PubMedConfig


@dataclass
class DiseaseLiteratureInfo:
    """疾病文献信息"""
    disease: str
    search_terms: List[str]
    pmc_ids: List[str]
    pmids: List[str]
    pmc_count: int
    pmid_count: int
    processing_time: float
    success: bool
    error: Optional[str] = None


@dataclass
class LiteratureMetadata:
    """文献元数据"""
    pmc_id: str = ""
    pmid: str = ""
    title: str = ""
    authors: List[str] = None
    journal: str = ""
    publication_date: str = ""
    abstract: str = ""
    doi: str = ""
    related_diseases: List[str] = None

    def __post_init__(self):
        if self.authors is None:
            self.authors = []
        if self.related_diseases is None:
            self.related_diseases = []


class ConcurrentLiteratureDownloader:
    """并发版文献下载器"""

    def __init__(self, download_mode: str = "pmc_only", max_workers: int = 5):
        """
        初始化配置

        Args:
            download_mode: 下载模式
                - "pmc_only": 仅下载PMC全文
                - "pubmed_only": 仅下载PubMed摘要
                - "both": 同时下载PubMed摘要和PMC全文
            max_workers: 最大并发工作线程数
        """
        self.email = "1666526339@qq.com"
        self.api_key = "f7f3e5ffa36e0446a4a3c6540d8fa7e72808"
        self.download_mode = download_mode
        self.max_workers = max_workers

        # 输出目录
        self.base_output_dir = project_root / "knowledge_graph" / "data" / "literature"
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        # 线程锁
        self.data_lock = threading.Lock()
        self.progress_lock = threading.Lock()

        # 初始化下载器
        self.init_downloaders()

        # 数据存储
        self.disease_literature_mapping: Dict[str, DiseaseLiteratureInfo] = {}
        self.unique_pmc_ids: Set[str] = set()
        self.unique_pmids: Set[str] = set()
        self.literature_disease_mapping: Dict[str, List[str]] = defaultdict(list)
        self.literature_metadata: Dict[str, LiteratureMetadata] = {}

        # 进度跟踪
        self.processed_count = 0
        self.successful_count = 0
        self.failed_count = 0

        # 断点续传文件路径
        self.progress_file = self.base_output_dir / "concurrent_progress_state.pkl"
        self.disease_pmc_mapping_file = self.base_output_dir / "disease_pmc_mapping.json"

        # 控制标志
        self.should_stop = False

        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n⚠️  接收到停止信号，正在安全退出...")
        self.should_stop = True

    def init_downloaders(self):
        """初始化下载器"""
        # PMC下载器配置
        if self.download_mode in ["pmc_only", "both"]:
            self.pmc_config = OptimizedPMCConfig(
                email=self.email,
                api_key=self.api_key,
                output_dir=str(self.base_output_dir / "PMC_full_text"),
                batch_size=500,
                disease_batch_size=50,
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
                disease_batch_size=50,
                sleep_time=0.34,
                sleep_time_with_key=0.12,
                max_retry=3,
                request_timeout=30,
                max_workers=3
            )
            self.pubmed_downloader = PubMedDownloader(self.pubmed_config)

    def load_progress_state(self) -> Dict:
        """加载进度状态"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'rb') as f:
                    state = pickle.load(f)
                print(f"📂 发现有断点文件，已处理 {len(state.get('processed_diseases', []))} 个疾病")
                return state
            except Exception as e:
                print(f"⚠️  断点文件损坏，重新开始: {e}")
        return {}

    def save_progress_state(self, processed_diseases: List[str]):
        """保存进度状态"""
        try:
            with self.progress_lock:
                state = {
                    'processed_diseases': processed_diseases,
                    'disease_literature_mapping': self.disease_literature_mapping,
                    'unique_pmc_ids': list(self.unique_pmc_ids),
                    'unique_pmids': list(self.unique_pmids),
                    'literature_disease_mapping': dict(self.literature_disease_mapping),
                    'processed_count': self.processed_count,
                    'successful_count': self.successful_count,
                    'failed_count': self.failed_count,
                    'timestamp': datetime.now().isoformat()
                }

                with open(self.progress_file, 'wb') as f:
                    pickle.dump(state, f)

        except Exception as e:
            print(f"⚠️  保存进度失败: {e}")

    def save_disease_pmc_mapping(self):
        """保存疾病-PMC ID映射关系"""
        mapping_data = {}
        with self.data_lock:
            for disease, info in self.disease_literature_mapping.items():
                if info.success and info.pmc_ids:
                    mapping_data[disease] = {
                        'pmc_ids': info.pmc_ids,
                        'pmc_count': len(info.pmc_ids),
                        'pmids': info.pmids,
                        'pmid_count': len(info.pmids),
                        'processing_time': info.processing_time,
                        'last_updated': datetime.now().isoformat()
                    }

        try:
            with open(self.disease_pmc_mapping_file, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
            print(f"📋 疾病-PMC映射关系已保存: {self.disease_pmc_mapping_file}")
        except Exception as e:
            print(f"⚠️  保存疾病-PMC映射失败: {e}")

    def load_disease_list(self) -> List[str]:
        """加载罕见疾病列表"""
        disease_file = project_root / "all_rare_disease_names.txt"
        print(f"📋 加载疾病列表: {disease_file}")

        with open(disease_file, 'r', encoding='utf-8') as f:
            diseases = [line.strip() for line in f if line.strip()]

        print(f"✅ 加载了 {len(diseases)} 个罕见疾病")
        return diseases

    def collect_single_disease_literature(self, disease: str) -> DiseaseLiteratureInfo:
        """收集单个疾病的文献ID（线程安全）"""
        if self.should_stop:
            # 返回一个失败的结果
            return DiseaseLiteratureInfo(
                disease=disease,
                search_terms=[disease],
                pmc_ids=[],
                pmids=[],
                pmc_count=0,
                pmid_count=0,
                processing_time=0,
                success=False,
                error="Process stopped"
            )

        disease_info = DiseaseLiteratureInfo(
            disease=disease,
            search_terms=[disease],
            pmc_ids=[],
            pmids=[],
            pmc_count=0,
            pmid_count=0,
            processing_time=0,
            success=False
        )

        start_time = time.time()

        try:
            # PMC检索
            if self.download_mode in ["pmc_only", "both"]:
                # 为每个线程创建独立的下载器实例
                pmc_downloader = OptimizedPMCDownloader(self.pmc_config)
                pmc_ids = pmc_downloader.collect_pmc_ids_only(disease)
                disease_info.pmc_ids = pmc_ids
                disease_info.pmc_count = len(pmc_ids)

            # PubMed检索
            if self.download_mode in ["pubmed_only", "both"]:
                # 为每个线程创建独立的下载器实例
                pubmed_downloader = PubMedDownloader(self.pubmed_config)
                try:
                    pmids = pubmed_downloader.search_pubmed(disease)
                    disease_info.pmids = pmids
                    disease_info.pmid_count = len(pmids)
                except Exception as e:
                    print(f"   ❌ PubMed检索失败 {disease}: {e}")

            disease_info.success = True

        except Exception as e:
            disease_info.error = str(e)

        disease_info.processing_time = time.time() - start_time
        return disease_info

    def process_disease_result(self, disease_info: DiseaseLiteratureInfo):
        """处理单个疾病的检索结果（线程安全）"""
        with self.data_lock:
            # 保存结果
            self.disease_literature_mapping[disease_info.disease] = disease_info

            if disease_info.success:
                self.successful_count += 1

                # 添加到去重集合
                self.unique_pmc_ids.update(disease_info.pmc_ids)
                self.unique_pmids.update(disease_info.pmids)

                # 建立文献-疾病映射
                for pmc_id in disease_info.pmc_ids:
                    self.literature_disease_mapping[pmc_id].append(disease_info.disease)
                for pmid in disease_info.pmids:
                    self.literature_disease_mapping[pmid].append(disease_info.disease)
            else:
                self.failed_count += 1

            self.processed_count += 1

    def stage_one_concurrent_collect(self, diseases: List[str], max_diseases: Optional[int] = None):
        """阶段一：并发收集所有疾病的文献ID"""
        if max_diseases:
            diseases = diseases[:max_diseases]

        # 加载进度状态
        progress_state = self.load_progress_state()
        processed_diseases = set(progress_state.get('processed_diseases', []))

        # 恢复之前的状态
        if progress_state:
            with self.data_lock:
                self.disease_literature_mapping = progress_state.get('disease_literature_mapping', {})
                self.unique_pmc_ids = set(progress_state.get('unique_pmc_ids', []))
                self.unique_pmids = set(progress_state.get('unique_pmids', []))
                self.literature_disease_mapping = defaultdict(list, progress_state.get('literature_disease_mapping', {}))
                self.processed_count = progress_state.get('processed_count', 0)
                self.successful_count = progress_state.get('successful_count', 0)
                self.failed_count = progress_state.get('failed_count', 0)

        # 过滤未处理的疾病
        remaining_diseases = [d for d in diseases if d not in processed_diseases]

        if not remaining_diseases:
            print("✅ 所有疾病已处理完毕！")
            return

        print(f"\n🚀 阶段一：并发收集文献ID")
        print(f"📊 总疾病数: {len(diseases)}, 已处理: {len(processed_diseases)}, 剩余: {len(remaining_diseases)}")
        print(f"🔧 并发线程数: {self.max_workers}")
        print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        start_time = time.time()

        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_disease = {
                executor.submit(self.collect_single_disease_literature, disease): disease
                for disease in remaining_diseases
            }

            # 处理完成的任务
            for future in as_completed(future_to_disease):
                if self.should_stop:
                    break

                disease = future_to_disease[future]
                try:
                    disease_info = future.result()
                    self.process_disease_result(disease_info)

                    # 显示进度
                    progress = (self.processed_count / len(diseases)) * 100
                    print(f"📊 进度: {self.processed_count}/{len(diseases)} ({progress:.1f}%) - "
                          f"✅{self.successful_count} ❌{self.failed_count} - {disease[:50]}...")

                    # 每10个疾病保存一次进度
                    if self.processed_count % 10 == 0:
                        processed_diseases.add(disease)
                        self.save_progress_state(list(processed_diseases))
                        self.save_disease_pmc_mapping()

                except Exception as e:
                    print(f"❌ 处理疾病 {disease} 时发生错误: {e}")
                    with self.data_lock:
                        self.failed_count += 1
                        self.processed_count += 1

                # 短暂延迟避免请求过快
                time.sleep(0.1)

        # 最终保存进度
        final_processed = processed_diseases.union(set(remaining_diseases[:self.processed_count - len(processed_diseases)]))
        self.save_progress_state(list(final_processed))
        self.save_disease_pmc_mapping()

        collection_time = time.time() - start_time

        print(f"\n✅ 阶段一完成！")
        print(f"⏰ 用时: {collection_time:.1f} 秒")
        print(f"📊 成功收集: {self.successful_count} 个疾病")
        print(f"❌ 收集失败: {self.failed_count} 个疾病")
        print(f"🔍 去重前 PMC IDs: {sum(len(info.pmc_ids) for info in self.disease_literature_mapping.values())}")
        print(f"🔍 去重前 PubMed IDs: {sum(len(info.pmids) for info in self.disease_literature_mapping.values())}")
        print(f"✨ 去重后 PMC IDs: {len(self.unique_pmc_ids)}")
        print(f"✨ 去重后 PubMed IDs: {len(self.unique_pmids)}")

        # 计算去重效果
        original_pmc = sum(len(info.pmc_ids) for info in self.disease_literature_mapping.values())
        original_pmid = sum(len(info.pmids) for info in self.disease_literature_mapping.values())

        if original_pmc > 0:
            pmc_reduction = (original_pmc - len(self.unique_pmc_ids)) / original_pmc * 100
            print(f"📈 PMC ID去重率: {pmc_reduction:.1f}%")

        if original_pmid > 0:
            pmid_reduction = (original_pmid - len(self.unique_pmids)) / original_pmid * 100
            print(f"📈 PubMed ID去重率: {pmid_reduction:.1f}%")

    def stage_two_batch_download(self):
        """阶段二：批量下载去重后的文献"""
        if self.should_stop:
            print("⚠️  检测到停止信号，跳过下载阶段")
            return

        print(f"\n🚀 阶段二：批量下载去重后的文献")
        print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        start_time = time.time()

        # PMC批量下载
        if self.download_mode in ["pmc_only", "both"] and self.unique_pmc_ids:
            print(f"\n📚 开始批量下载 {len(self.unique_pmc_ids)} 个PMC全文...")
            self.batch_download_pmc_articles()

        # PubMed批量下载
        if self.download_mode in ["pubmed_only", "both"] and self.unique_pmids:
            print(f"\n📄 开始批量下载 {len(self.unique_pmids)} 个PubMed摘要...")
            self.batch_download_pubmed_abstracts()

        download_time = time.time() - start_time

        print(f"\n✅ 阶段二完成！")
        print(f"⏰ 用时: {download_time:.1f} 秒")

    def batch_download_pmc_articles(self):
        """批量下载PMC文章（简化版，复用原有逻辑）"""
        if not self.unique_pmc_ids or self.should_stop:
            print("   ℹ️  没有PMC文章需要下载或已停止")
            return

        # 这里可以复用原有的PMC批量下载逻辑
        # 为了简化，我们暂时只打印统计信息
        print(f"   📚 需要下载 {len(self.unique_pmc_ids)} 个PMC全文")
        print(f"   💡 建议运行原有的批量下载脚本完成下载")

    def batch_download_pubmed_abstracts(self):
        """批量下载PubMed摘要（简化版，复用原有逻辑）"""
        if not self.unique_pmids or self.should_stop:
            print("   ℹ️  没有PubMed摘要需要下载或已停止")
            return

        # 这里可以复用原有的PubMed批量下载逻辑
        print(f"   📄 需要下载 {len(self.unique_pmids)} 个PubMed摘要")
        print(f"   💡 建议运行原有的批量下载脚本完成下载")

    def save_final_report(self):
        """保存最终报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.base_output_dir / f"concurrent_report_{timestamp}.json"

        # 统计信息
        total_diseases = len(self.disease_literature_mapping)
        successful_diseases = sum(1 for info in self.disease_literature_mapping.values() if info.success)

        # 计算重复情况
        total_original_pmc = sum(len(info.pmc_ids) for info in self.disease_literature_mapping.values())
        total_original_pmid = sum(len(info.pmids) for info in self.disease_literature_mapping.values())

        report = {
            'concurrent_summary': {
                'strategy': 'concurrent_collection_batch_download',
                'timestamp': timestamp,
                'max_workers': self.max_workers,
                'total_diseases_processed': total_diseases,
                'successful_diseases': successful_diseases,
                'success_rate': (successful_diseases / total_diseases * 100) if total_diseases > 0 else 0,
                'processing_time': self.processed_count
            },
            'deduplication_stats': {
                'pmc_original_count': total_original_pmc,
                'pmc_deduplicated_count': len(self.unique_pmc_ids),
                'pmc_reduction_percentage': ((total_original_pmc - len(self.unique_pmc_ids)) / total_original_pmc * 100) if total_original_pmc > 0 else 0,
                'pubmed_original_count': total_original_pmid,
                'pubmed_deduplicated_count': len(self.unique_pmids),
                'pubmed_reduction_percentage': ((total_original_pmid - len(self.unique_pmids)) / total_original_pmid * 100) if total_original_pmid > 0 else 0
            },
            'performance_stats': {
                'processed_count': self.processed_count,
                'successful_count': self.successful_count,
                'failed_count': self.failed_count,
                'concurrent_efficiency': f"{self.successful_count}/{self.processed_count}"
            }
        }

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n📊 并发下载报告已保存: {report_file}")
        self.display_concurrent_summary(report)

    def display_concurrent_summary(self, report: Dict):
        """显示并发下载摘要"""
        print("\n" + "="*80)
        print("📊 并发文献下载优化报告")
        print("="*80)

        summary = report['concurrent_summary']
        dedup = report['deduplication_stats']
        perf = report['performance_stats']

        print(f"📅 处理时间: {summary['timestamp']}")
        print(f"🔧 并发线程数: {summary['max_workers']}")
        print(f"🔬 处理疾病: {summary['total_diseases_processed']}")
        print(f"✅ 成功收集: {summary['successful_diseases']} ({summary['success_rate']:.1f}%)")
        print()

        print("🎯 去重效果:")
        print(f"   📚 PMC: {dedup['pmc_original_count']} → {dedup['pmc_deduplicated_count']} (减少 {dedup['pmc_reduction_percentage']:.1f}%)")
        print(f"   📄 PubMed: {dedup['pubmed_original_count']} → {dedup['pubmed_deduplicated_count']} (减少 {dedup['pubmed_reduction_percentage']:.1f}%)")
        print()

        print("⚡ 性能统计:")
        print(f"   📊 处理统计: {perf['processed_count']} 总计")
        print(f"   ✅ 成功/失败: {perf['successful_count']}/{perf['failed_count']}")
        print(f"   🎯 成功率: {perf['concurrent_efficiency']}")
        print()

        print("💡 并发优势:")
        print("   ✅ 并发收集，大幅提升检索速度")
        print("   ✅ 线程安全，保证数据一致性")
        print("   ✅ 断点续传，支持中断恢复")
        print("   ✅ 去重优化，避免重复下载")
        print("="*80)

    def run_concurrent_download(self, diseases: List[str], max_diseases: Optional[int] = None):
        """运行并发下载流程"""
        print("🧬 并发版罕见疾病文献下载工具")
        print("⚡ 采用并发收集 + 批量下载策略")
        print("="*50)

        try:
            # 阶段一：并发收集文献ID
            self.stage_one_concurrent_collect(diseases, max_diseases)

            if self.should_stop:
                print("⚠️  用户中断了收集过程")
                return

            # 阶段二：批量下载
            self.stage_two_batch_download()

            # 保存最终报告
            self.save_final_report()

            print(f"\n🎉 并发下载完成！")
            print(f"💡 可查看下载的文献数据和并发报告")

        except KeyboardInterrupt:
            print(f"\n⚠️  用户中断了下载过程")
            # 即使中断也要保存已收集的数据
            if self.disease_literature_mapping:
                self.save_progress_state([])
                self.save_final_report()
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主函数"""
    print("🧬 并发版罕见疾病文献下载工具")
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

    # 选择并发数量
    print(f"\n请选择并发线程数:")
    print("1. 🐌 低并发 (2-3 线程，推荐用于不稳定网络)")
    print("2. 🚶 中等并发 (5-8 线程，推荐用于一般使用)")
    print("3. 🏃 高并发 (10-15 线程，推荐用于稳定网络)")
    print("4. 🚀 自定义并发数")

    while True:
        try:
            choice = input("\n请输入选项 (1-4): ").strip()
            if choice == '1':
                max_workers = 3
                break
            elif choice == '2':
                max_workers = 6
                break
            elif choice == '3':
                max_workers = 12
                break
            elif choice == '4':
                max_workers = int(input("请输入自定义并发数 (1-20): ").strip())
                if 1 <= max_workers <= 20:
                    break
                else:
                    print("❌ 并发数应在 1-20 之间")
            else:
                print("❌ 请输入 1-4 之间的数字")
        except ValueError:
            print("❌ 请输入有效的数字")
        except KeyboardInterrupt:
            print("\n👋 用户取消，退出程序")
            return

    print(f"\n🚀 选择了并发下载模式: {download_mode}, 线程数: {max_workers}")
    downloader = ConcurrentLiteratureDownloader(download_mode, max_workers)

    # 加载疾病列表
    diseases = downloader.load_disease_list()

    # 询问用户要处理多少个疾病
    print(f"\n💡 并发版下载提示:")
    print(f"   - 测试建议: 100-500 个疾病")
    print(f"   - 中等规模: 1000-2000 个疾病")
    print(f"   - 全量下载: {len(diseases)} 个疾病")
    print(f"   - 按 Ctrl+C 可随时停止")
    print(f"   - 并发版会自动去重，大幅提升效率")

    while True:
        try:
            user_input = input(f"\n请输入要处理的疾病数量 (1-{len(diseases)}, 默认100): ").strip()
            if not user_input:
                max_diseases = 100
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

    print(f"\n🚀 开始并发处理 {max_diseases} 个疾病...")

    try:
        # 运行并发下载
        downloader.run_concurrent_download(diseases, max_diseases)

    except KeyboardInterrupt:
        print(f"\n⚠️  用户中断了下载过程")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()