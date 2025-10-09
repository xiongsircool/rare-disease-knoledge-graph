#!/usr/bin/env python3
"""
优化版罕见疾病文献下载脚本
采用两阶段策略：
1. 阶段一：收集所有疾病的文献ID，去重
2. 阶段二：批量下载去重后的文献，建立疾病-文献映射关系
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict
from dataclasses import dataclass, asdict
import pickle

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


class OptimizedLiteratureDownloader:
    """优化版文献下载器"""

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

        # 数据存储
        self.disease_literature_mapping: Dict[str, DiseaseLiteratureInfo] = {}
        self.unique_pmc_ids: Set[str] = set()
        self.unique_pmids: Set[str] = set()
        self.literature_disease_mapping: Dict[str, List[str]] = defaultdict(list)
        self.literature_metadata: Dict[str, LiteratureMetadata] = {}

        # 断点续传文件路径
        self.progress_file = self.base_output_dir / "progress_state.pkl"
        self.disease_pmc_mapping_file = self.base_output_dir / "disease_pmc_mapping.json"

    def init_downloaders(self):
        """初始化下载器"""
        # PMC下载器配置
        if self.download_mode in ["pmc_only", "both"]:
            self.pmc_config = OptimizedPMCConfig(
                email=self.email,
                api_key=self.api_key,
                output_dir=str(self.base_output_dir / "PMC_full_text"),
                batch_size=500,  # 增大批次提高效率
                disease_batch_size=50,  # 增大疾病批次
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

    def save_progress_state(self, processed_diseases: List[str], current_disease_index: int):
        """保存进度状态"""
        try:
            state = {
                'processed_diseases': processed_diseases,
                'current_disease_index': current_disease_index,
                'disease_literature_mapping': self.disease_literature_mapping,
                'unique_pmc_ids': self.unique_pmc_ids,
                'unique_pmids': self.unique_pmids,
                'literature_disease_mapping': dict(self.literature_disease_mapping),
                'timestamp': datetime.now().isoformat()
            }

            with open(self.progress_file, 'wb') as f:
                pickle.dump(state, f)

        except Exception as e:
            print(f"⚠️  保存进度失败: {e}")

    def save_disease_pmc_mapping(self):
        """保存疾病-PMC ID映射关系"""
        mapping_data = {}
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

    def stage_one_collect_literature_ids(self, diseases: List[str], max_diseases: Optional[int] = None):
        """阶段一：收集所有疾病的文献ID（支持断点续传）"""
        if max_diseases:
            diseases = diseases[:max_diseases]

        # 加载进度状态
        progress_state = self.load_progress_state()
        processed_diseases = set(progress_state.get('processed_diseases', []))

        # 恢复之前的状态
        if progress_state:
            self.disease_literature_mapping = progress_state.get('disease_literature_mapping', {})
            self.unique_pmc_ids = set(progress_state.get('unique_pmc_ids', []))
            self.unique_pmids = set(progress_state.get('unique_pmids', []))
            self.literature_disease_mapping = defaultdict(list, progress_state.get('literature_disease_mapping', {}))

        # 过滤未处理的疾病
        remaining_diseases = [d for d in diseases if d not in processed_diseases]

        if not remaining_diseases:
            print("✅ 所有疾病已处理完毕！")
            return

        print(f"\n🚀 阶段一：收集文献ID（断点续传）")
        print(f"📊 总疾病数: {len(diseases)}, 已处理: {len(processed_diseases)}, 剩余: {len(remaining_diseases)}")
        print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        start_time = time.time()
        successful_collections = len([d for d in processed_diseases if hasattr(self.disease_literature_mapping.get(d), 'success') and self.disease_literature_mapping.get(d).success])
        failed_collections = len(processed_diseases) - successful_collections

        for i, disease in enumerate(remaining_diseases, 1):
            actual_index = len(processed_diseases) + i
            print(f"\n📋 进度: {actual_index}/{len(diseases)} - {disease[:80]}...")

            disease_info = self.collect_single_disease_literature(disease)
            self.disease_literature_mapping[disease] = disease_info

            if disease_info.success:
                successful_collections += 1

                # 添加到去重集合
                self.unique_pmc_ids.update(disease_info.pmc_ids)
                self.unique_pmids.update(disease_info.pmids)

                # 建立文献-疾病映射
                for pmc_id in disease_info.pmc_ids:
                    self.literature_disease_mapping[pmc_id].append(disease)
                for pmid in disease_info.pmids:
                    self.literature_disease_mapping[pmid].append(disease)

            else:
                failed_collections += 1

            # 更新已处理疾病列表
            processed_diseases.add(disease)

            # 每20个疾病保存一次进度并显示进度
            if i % 20 == 0:
                self.save_progress_state(list(processed_diseases), actual_index)
                self.show_collection_progress(actual_index, successful_collections, failed_collections)
                # 保存疾病-PMC映射关系
                self.save_disease_pmc_mapping()

            # 短暂延迟避免请求过快
            time.sleep(0.3)

        # 最终保存进度
        self.save_progress_state(list(processed_diseases), len(diseases))
        self.save_disease_pmc_mapping()

        collection_time = time.time() - start_time

        print(f"\n✅ 阶段一完成！")
        print(f"⏰ 用时: {collection_time:.1f} 秒")
        print(f"📊 成功收集: {successful_collections} 个疾病")
        print(f"❌ 收集失败: {failed_collections} 个疾病")
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

    def collect_single_disease_literature(self, disease: str) -> DiseaseLiteratureInfo:
        """收集单个疾病的文献ID"""
        disease_info = DiseaseLiteratureInfo(
            disease=disease,
            search_terms=[disease],  # 可以扩展为多个检索词
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
                print(f"   🔍 检索PMC全文...")
                # 使用新的ID收集方法
                pmc_ids = self.pmc_downloader.collect_pmc_ids_only(disease)
                disease_info.pmc_ids = pmc_ids
                disease_info.pmc_count = len(pmc_ids)

                if pmc_ids:
                    print(f"   📚 找到 {len(pmc_ids)} 个去重后PMC ID")

            # PubMed检索
            if self.download_mode in ["pubmed_only", "both"]:
                print(f"   🔍 检索PubMed摘要...")
                # 使用PubMed的ID收集方法
                try:
                    pmids = self.pubmed_downloader.search_pubmed(disease)
                    disease_info.pmids = pmids
                    disease_info.pmid_count = len(pmids)

                    if pmids:
                        print(f"   📄 找到 {len(pmids)} 个去重后PMID")

                except Exception as e:
                    print(f"   ❌ PubMed检索失败: {e}")

            disease_info.success = True

        except Exception as e:
            print(f"   ❌ 检索失败: {e}")
            disease_info.error = str(e)

        disease_info.processing_time = time.time() - start_time
        return disease_info

    def show_collection_progress(self, processed_count: int, successful: int, failed: int):
        """显示收集进度"""
        success_rate = (successful / processed_count) * 100 if processed_count > 0 else 0

        print(f"\n📊 收集进度摘要 (处理了 {processed_count} 个疾病):")
        print(f"   ✅ 成功收集: {successful} ({success_rate:.1f}%)")
        print(f"   ❌ 收集失败: {failed}")

        # 显示当前的去重统计
        current_pmc = len(self.unique_pmc_ids)
        current_pmid = len(self.unique_pmids)
        print(f"   📚 当前去重PMC IDs: {current_pmc}")
        print(f"   📄 当前去重PubMed IDs: {current_pmid}")

    def stage_two_batch_download(self):
        """阶段二：批量下载去重后的文献"""
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
        """批量下载PMC文章"""
        if not self.unique_pmc_ids:
            print("   ℹ️  没有PMC文章需要下载")
            return

        # 将PMC ID转换为列表并分批处理
        pmc_id_list = list(self.unique_pmc_ids)
        batch_size = self.pmc_config.batch_size

        total_batches = (len(pmc_id_list) + batch_size - 1) // batch_size
        successful_downloads = 0
        failed_downloads = 0
        all_pmc_articles = []

        print(f"   📦 批次大小: {batch_size}")
        print(f"   📦 总批次数: {total_batches}")

        for i in range(0, len(pmc_id_list), batch_size):
            batch_ids = pmc_id_list[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            print(f"   📥 下载批次 {batch_num}/{total_batches} ({len(batch_ids)} 篇)...")

            try:
                # 这里使用现有的批量下载逻辑
                # 需要适配现有的下载器接口
                batch_articles = self.download_pmc_batch(batch_ids, batch_num)
                if batch_articles:
                    all_pmc_articles.extend(batch_articles)
                successful_downloads += len(batch_ids)

            except Exception as e:
                print(f"   ❌ 批次 {batch_num} 下载失败: {e}")
                failed_downloads += len(batch_ids)

            # 请求间隔
            time.sleep(self.pmc_downloader.get_sleep_time())

        print(f"   ✅ PMC下载完成: 成功 {successful_downloads}, 失败 {failed_downloads}")

        # 保存合并的PMC数据为CSV
        if all_pmc_articles:
            self.save_pmc_csv_data(all_pmc_articles)

    def download_pmc_batch(self, pmc_ids: List[str], batch_num: int) -> List[Dict]:
        """下载PMC批次"""
        # 使用现有的PMC下载器逻辑
        # 这里需要根据实际的下载器接口进行适配

        # 创建批次目录
        batch_dir = Path(self.pmc_config.output_dir) / "batch_downloads"
        batch_dir.mkdir(exist_ok=True)

        # 构建批次文件名
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        batch_filename = f"optimized_batch_{batch_num:05d}_{timestamp}.xml"
        batch_file = batch_dir / batch_filename

        batch_articles = []

        try:
            # 使用现有的下载逻辑
            xml_text = self.pmc_downloader._safe_fetch_with_retry(pmc_ids)

            # 保存XML文件
            with open(batch_file, 'w', encoding='utf-8') as f:
                f.write(xml_text)

            print(f"   ✅ 保存批次文件: {batch_filename}")

            # 解析并保存元数据
            if self.pmc_config.parse_detailed_content:
                batch_articles = self.parse_batch_metadata(xml_text, pmc_ids, batch_num)

        except Exception as e:
            print(f"   ❌ 批次下载失败: {e}")
            raise

        return batch_articles

    def parse_batch_metadata(self, xml_text: str, pmc_ids: List[str], batch_num: int) -> List[Dict]:
        """解析批次元数据"""
        enhanced_articles = []
        try:
            # 使用现有的解析逻辑
            articles = self.pmc_downloader.parse_full_articles(xml_text, f"batch_{batch_num}")

            # 保存解析结果
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            json_file = Path(self.pmc_config.output_dir) / "parsed_json" / f"optimized_batch_{batch_num:05d}_{timestamp}.json"

            # 增强文章数据，添加相关疾病信息
            for article in articles:
                article_dict = article.to_dict()
                pmc_id = article_dict.get('pmc_id', '')

                # 添加相关疾病信息
                if pmc_id in self.literature_disease_mapping:
                    article_dict['related_diseases'] = self.literature_disease_mapping[pmc_id]

                    # 保存到元数据字典
                    metadata = LiteratureMetadata(
                        pmc_id=article_dict.get('pmc_id', ''),
                        pmid=article_dict.get('pmid', ''),
                        title=article_dict.get('title', ''),
                        authors=article_dict.get('authors', []),
                        journal=article_dict.get('journal', ''),
                        publication_date=str(article_dict.get('publication_date', {})),
                        abstract=article_dict.get('abstract', ''),
                        doi=article_dict.get('doi', ''),
                        related_diseases=self.literature_disease_mapping[pmc_id]
                    )
                    self.literature_metadata[pmc_id] = metadata

                enhanced_articles.append(article_dict)

            # 保存增强的JSON数据
            batch_data = {
                'batch_number': batch_num,
                'search_timestamp': timestamp,
                'pmc_ids': pmc_ids,
                'total_articles': len(enhanced_articles),
                'articles': enhanced_articles,
                'optimization_info': {
                    'batch_type': 'deduplicated_batch',
                    'total_related_diseases': len(set().union(*[a.get('related_diseases', []) for a in enhanced_articles])),
                    'download_strategy': 'two_phase_optimization'
                }
            }

            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(batch_data, f, ensure_ascii=False, indent=2)

            print(f"   ✅ 解析并保存: {json_file.name} ({len(enhanced_articles)} 篇)")

        except Exception as e:
            print(f"   ❌ 批次解析失败: {e}")

        return enhanced_articles

    def batch_download_pubmed_abstracts(self):
        """批量下载PubMed摘要"""
        if not self.unique_pmids:
            print("   ℹ️  没有PubMed摘要需要下载")
            return

        # 将PMID转换为列表并分批处理
        pmid_list = list(self.unique_pmids)
        batch_size = self.pubmed_config.batch_size

        total_batches = (len(pmid_list) + batch_size - 1) // batch_size
        successful_downloads = 0
        failed_downloads = 0
        all_articles = []

        print(f"   📦 批次大小: {batch_size}")
        print(f"   📦 总批次数: {total_batches}")

        for i in range(0, len(pmid_list), batch_size):
            batch_pmids = pmid_list[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            print(f"   📥 下载批次 {batch_num}/{total_batches} ({len(batch_pmids)} 篇)...")

            try:
                # 使用PubMed下载器的批量获取方法
                articles = self.pubmed_downloader.fetch_abstracts_batch(batch_pmids, "optimized_batch")

                # 增强文章数据，添加相关疾病信息
                enhanced_articles = []
                for article in articles:
                    article_dict = article.to_dict()
                    pmid = article_dict.get('pmid', '')

                    # 添加相关疾病信息
                    if pmid in self.literature_disease_mapping:
                        article_dict['related_diseases'] = self.literature_disease_mapping[pmid]

                        # 保存到元数据字典
                        metadata = LiteratureMetadata(
                            pmc_id=article_dict.get('pmcid', ''),
                            pmid=article_dict.get('pmid', ''),
                            title=article_dict.get('title', ''),
                            authors=article_dict.get('authors', []),
                            journal=article_dict.get('journal', ''),
                            publication_date=str(article_dict.get('publication_date', {})),
                            abstract=article_dict.get('abstract', ''),
                            doi=article_dict.get('doi', ''),
                            related_diseases=self.literature_disease_mapping[pmid]
                        )
                        self.literature_metadata[pmid] = metadata

                    enhanced_articles.append(article_dict)

                all_articles.extend(enhanced_articles)
                successful_downloads += len(articles)

                # 保存批次数据
                self.save_pubmed_batch_data(enhanced_articles, batch_pmids, batch_num)

                print(f"   ✅ 批次 {batch_num} 成功获取 {len(articles)} 篇摘要")

            except Exception as e:
                print(f"   ❌ 批次 {batch_num} 下载失败: {e}")
                failed_downloads += len(batch_pmids)

            # 请求间隔
            time.sleep(self.pubmed_downloader.get_sleep_time())

        # 保存合并的数据
        if all_articles:
            self.save_merged_pubmed_data(all_articles)

        print(f"   ✅ PubMed下载完成: 成功 {successful_downloads}, 失败 {failed_downloads}")

    def save_pubmed_batch_data(self, articles: List[Dict], pmids: List[str], batch_num: int):
        """保存PubMed批次数据"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        # 创建批次目录
        batch_dir = Path(self.pubmed_config.output_dir) / "batch_downloads"
        batch_dir.mkdir(exist_ok=True)

        # 保存JSON数据
        json_file = batch_dir / f"optimized_pubmed_batch_{batch_num:05d}_{timestamp}.json"

        batch_data = {
            'batch_number': batch_num,
            'search_timestamp': timestamp,
            'pmids': pmids,
            'total_articles': len(articles),
            'articles': articles,
            'optimization_info': {
                'batch_type': 'deduplicated_batch',
                'total_related_diseases': len(set().union(*[a.get('related_diseases', []) for a in articles])),
                'download_strategy': 'two_phase_optimization'
            }
        }

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)

        print(f"   ✅ 保存PubMed批次: {json_file.name} ({len(articles)} 篇)")

    def save_merged_pubmed_data(self, all_articles: List[Dict]):
        """保存合并的PubMed数据"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        # 保存合并的JSON数据
        merged_file = Path(self.pubmed_config.output_dir) / f"optimized_pubmed_merged_{timestamp}.json"

        merged_data = {
            'merge_timestamp': timestamp,
            'total_articles': len(all_articles),
            'download_mode': self.download_mode,
            'unique_pmids_count': len(self.unique_pmids),
            'total_diseases': len(self.disease_literature_mapping),
            'articles': all_articles,
            'optimization_summary': {
                'strategy': 'two_phase_deduplication',
                'deduplicated_pmids': len(self.unique_pmids),
                'total_related_diseases': len(set().union(*[a.get('related_diseases', []) for a in all_articles]))
            }
        }

        with open(merged_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)

        print(f"   ✅ 保存合并数据: {merged_file.name} ({len(all_articles)} 篇总计)")

        # 保存为CSV格式（按疾病分拆）
        self.save_articles_by_disease_csv(all_articles, timestamp)

        # 保存为统一的CSV文件
        self.save_unified_csv(all_articles, timestamp)

    def save_articles_by_disease_csv(self, all_articles: List[Dict], timestamp: str):
        """按疾病分拆保存为CSV文件"""
        # 创建CSV目录
        csv_dir = Path(self.pubmed_config.output_dir) / "csv_by_disease"
        csv_dir.mkdir(exist_ok=True)

        # 按疾病分组文章
        disease_articles = defaultdict(list)
        for article in all_articles:
            related_diseases = article.get('related_diseases', [])
            if related_diseases:
                for disease in related_diseases:
                    disease_articles[disease].append(article)

        # 为每个疾病保存CSV文件
        for disease, articles in disease_articles.items():
            csv_file = csv_dir / f"{disease.replace(' ', '_').replace('/', '_')}_{timestamp}.csv"

            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                import csv
                writer = csv.writer(f)

                # 写入标题行
                writer.writerow([
                    'PMID', 'PMCID', 'Title', 'Abstract', 'Authors', 'Journal',
                    'Publication Year', 'DOI', 'MeSH Terms', 'Publication Types',
                    'Keywords', 'Related Diseases', 'Publication Date', 'Article Language'
                ])

                # 写入数据
                for article in articles:
                    writer.writerow([
                        article.get('pmid', ''),
                        article.get('pmcid', ''),
                        article.get('title', '')[:1000] + '...' if len(article.get('title', '')) > 1000 else article.get('title', ''),
                        article.get('abstract', '')[:2000] + '...' if len(article.get('abstract', '')) > 2000 else article.get('abstract', ''),
                        '; '.join(article.get('authors', []))[:500] + '...' if len('; '.join(article.get('authors', []))) > 500 else '; '.join(article.get('authors', [])),
                        article.get('journal', ''),
                        article.get('publication_date', {}).get('year', ''),
                        article.get('doi', ''),
                        '; '.join(article.get('mesh_terms', [])),
                        '; '.join(article.get('publication_types', [])),
                        '; '.join(article.get('keywords', [])),
                        '; '.join(article.get('related_diseases', [])),
                        article.get('publication_date', {}).get('formatted', ''),
                        '; '.join(article.get('abstract_languages', []))
                    ])

            print(f"   📊 保存疾病CSV: {csv_file.name} ({len(articles)} 篇)")

    def save_unified_csv(self, all_articles: List[Dict], timestamp: str):
        """保存统一的CSV文件"""
        unified_csv_file = Path(self.pubmed_config.output_dir) / f"optimized_pubmed_unified_{timestamp}.csv"

        with open(unified_csv_file, 'w', newline='', encoding='utf-8') as f:
            import csv
            writer = csv.writer(f)

            # 写入标题行
            writer.writerow([
                'PMID', 'PMCID', 'Title', 'Abstract', 'Authors', 'Journal',
                'Publication Year', 'Publication Month', 'Publication Day',
                'DOI', 'MeSH Terms', 'Publication Types', 'Keywords',
                'Related Diseases', 'Abstract Languages', 'Disease Batch',
                'Download Timestamp'
            ])

            # 写入数据
            for article in all_articles:
                writer.writerow([
                    article.get('pmid', ''),
                    article.get('pmcid', ''),
                    article.get('title', ''),
                    article.get('abstract', ''),
                    '; '.join(article.get('authors', [])),
                    article.get('journal', ''),
                    article.get('publication_date', {}).get('year', ''),
                    article.get('publication_date', {}).get('month', ''),
                    article.get('publication_date', {}).get('day', ''),
                    article.get('doi', ''),
                    '; '.join(article.get('mesh_terms', [])),
                    '; '.join(article.get('publication_types', [])),
                    '; '.join(article.get('keywords', [])),
                    '; '.join(article.get('related_diseases', [])),
                    '; '.join(article.get('abstract_languages', [])),
                    article.get('disease', 'optimized_batch'),
                    timestamp
                ])

        print(f"   📋 保存统一CSV: {unified_csv_file.name} ({len(all_articles)} 篇总计)")

    def save_pmc_csv_data(self, all_articles: List[Dict]):
        """保存PMC数据为CSV格式"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        # 保存统一的PMC CSV文件
        unified_csv_file = Path(self.pmc_config.output_dir) / f"optimized_pmc_unified_{timestamp}.csv"

        with open(unified_csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            import csv
            writer = csv.writer(f)

            # 写入标题行
            writer.writerow([
                'PMC ID', 'PMID', 'Title', 'Abstract', 'Authors', 'Journal',
                'Publication Date', 'DOI', 'Full Text URL', 'Related Diseases',
                'Download Timestamp', 'Article Type', 'Language'
            ])

            # 写入数据
            for article in all_articles:
                # 处理作者列表
                authors = article.get('authors', [])
                authors_str = '; '.join(authors) if isinstance(authors, list) else str(authors)

                # 处理相关疾病列表
                related_diseases = article.get('related_diseases', [])
                diseases_str = '; '.join(related_diseases) if isinstance(related_diseases, list) else str(related_diseases)

                # 截断过长的字段
                title = article.get('title', '')
                if len(title) > 1000:
                    title = title[:1000] + '...'

                abstract = article.get('abstract', '')
                if len(abstract) > 2000:
                    abstract = abstract[:2000] + '...'

                # 处理发表日期
                pub_date = article.get('publication_date', {})
                if isinstance(pub_date, dict):
                    pub_date_str = f"{pub_date.get('year', '')}-{pub_date.get('month', '')}-{pub_date.get('day', '')}"
                else:
                    pub_date_str = str(pub_date)

                writer.writerow([
                    article.get('pmc_id', ''),
                    article.get('pmid', ''),
                    title,
                    abstract,
                    authors_str[:500] + '...' if len(authors_str) > 500 else authors_str,
                    article.get('journal', ''),
                    pub_date_str,
                    article.get('doi', ''),
                    article.get('full_text_url', ''),
                    diseases_str,
                    timestamp,
                    article.get('article_type', ''),
                    article.get('language', '')
                ])

        print(f"   📊 保存PMC统一CSV: {unified_csv_file.name} ({len(all_articles)} 篇总计)")

        # 按疾病分拆保存CSV文件（可选）
        self.save_pmc_csv_by_disease(all_articles, timestamp)

    def save_pmc_csv_by_disease(self, all_articles: List[Dict], timestamp: str):
        """按疾病分拆保存PMC CSV文件"""
        # 创建CSV目录
        csv_dir = Path(self.pmc_config.output_dir) / "csv_by_disease"
        csv_dir.mkdir(exist_ok=True)

        # 按疾病分组文章
        disease_articles = defaultdict(list)
        for article in all_articles:
            related_diseases = article.get('related_diseases', [])
            if related_diseases:
                for disease in related_diseases:
                    disease_articles[disease].append(article)

        # 为每个疾病保存CSV文件
        for disease, articles in disease_articles.items():
            # 清理疾病名称用于文件名
            safe_disease_name = disease.replace(' ', '_').replace('/', '_').replace('\\', '_')
            csv_file = csv_dir / f"PMC_{safe_disease_name}_{timestamp}.csv"

            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                import csv
                writer = csv.writer(f)

                # 写入标题行
                writer.writerow([
                    'PMC ID', 'PMID', 'Title', 'Abstract', 'Authors', 'Journal',
                    'Publication Date', 'DOI', 'Full Text URL', 'Download Timestamp'
                ])

                # 写入数据
                for article in articles:
                    # 处理作者列表
                    authors = article.get('authors', [])
                    authors_str = '; '.join(authors) if isinstance(authors, list) else str(authors)

                    # 截断过长的字段
                    title = article.get('title', '')
                    if len(title) > 1000:
                        title = title[:1000] + '...'

                    abstract = article.get('abstract', '')
                    if len(abstract) > 2000:
                        abstract = abstract[:2000] + '...'

                    # 处理发表日期
                    pub_date = article.get('publication_date', {})
                    if isinstance(pub_date, dict):
                        pub_date_str = f"{pub_date.get('year', '')}-{pub_date.get('month', '')}-{pub_date.get('day', '')}"
                    else:
                        pub_date_str = str(pub_date)

                    writer.writerow([
                        article.get('pmc_id', ''),
                        article.get('pmid', ''),
                        title,
                        abstract,
                        authors_str[:500] + '...' if len(authors_str) > 500 else authors_str,
                        article.get('journal', ''),
                        pub_date_str,
                        article.get('doi', ''),
                        article.get('full_text_url', ''),
                        timestamp
                    ])

            print(f"   📊 保存PMC疾病CSV: {csv_file.name} ({len(articles)} 篇)")

    def save_optimization_report(self):
        """保存优化报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.base_output_dir / f"optimization_report_{timestamp}.json"

        # 统计信息
        total_diseases = len(self.disease_literature_mapping)
        successful_diseases = sum(1 for info in self.disease_literature_mapping.values() if info.success)

        # 计算重复情况
        total_original_pmc = sum(len(info.pmc_ids) for info in self.disease_literature_mapping.values())
        total_original_pmid = sum(len(info.pmids) for info in self.disease_literature_mapping.values())

        report = {
            'optimization_summary': {
                'strategy': 'two_phase_deduplication',
                'timestamp': timestamp,
                'total_diseases_processed': total_diseases,
                'successful_diseases': successful_diseases,
                'success_rate': (successful_diseases / total_diseases * 100) if total_diseases > 0 else 0
            },
            'deduplication_stats': {
                'pmc_original_count': total_original_pmc,
                'pmc_deduplicated_count': len(self.unique_pmc_ids),
                'pmc_reduction_count': total_original_pmc - len(self.unique_pmc_ids),
                'pmc_reduction_percentage': ((total_original_pmc - len(self.unique_pmc_ids)) / total_original_pmc * 100) if total_original_pmc > 0 else 0,
                'pubmed_original_count': total_original_pmid,
                'pubmed_deduplicated_count': len(self.unique_pmids),
                'pubmed_reduction_count': total_original_pmid - len(self.unique_pmids),
                'pubmed_reduction_percentage': ((total_original_pmid - len(self.unique_pmids)) / total_original_pmid * 100) if total_original_pmid > 0 else 0
            },
            'literature_mapping': {
                'disease_count': len(self.disease_literature_mapping),
                'unique_pmc_count': len(self.unique_pmc_ids),
                'unique_pubmed_count': len(self.unique_pmids),
                'literature_disease_mappings': len(self.literature_disease_mapping)
            },
            'disease_details': {
                disease: {
                    'disease': info.disease,
                    'search_terms': info.search_terms,
                    'pmc_ids': info.pmc_ids,
                    'pmids': info.pmids,
                    'pmc_count': info.pmc_count,
                    'pmid_count': info.pmid_count,
                    'processing_time': info.processing_time,
                    'success': info.success,
                    'error': info.error
                } for disease, info in self.disease_literature_mapping.items()
            },
            'literature_disease_mapping': dict(self.literature_disease_mapping),
            'sample_literature_metadata': {
                pmc_id: {
                    'pmc_id': metadata.pmc_id,
                    'pmid': metadata.pmid,
                    'title': metadata.title,
                    'authors': metadata.authors,
                    'journal': metadata.journal,
                    'publication_date': metadata.publication_date,
                    'abstract': metadata.abstract,
                    'doi': metadata.doi,
                    'related_diseases': metadata.related_diseases
                } for pmc_id, metadata in list(self.literature_metadata.items())[:10]
            }
        }

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n📊 优化报告已保存: {report_file}")
        self.display_optimization_summary(report)

    def display_optimization_summary(self, report: Dict):
        """显示优化摘要"""
        print("\n" + "="*80)
        print("📊 文献下载优化报告")
        print("="*80)

        summary = report['optimization_summary']
        dedup = report['deduplication_stats']
        mapping = report['literature_mapping']

        print(f"📅 优化时间: {summary['timestamp']}")
        print(f"🔬 处理疾病: {summary['total_diseases_processed']}")
        print(f"✅ 成功收集: {summary['successful_diseases']} ({summary['success_rate']:.1f}%)")
        print()

        print("🎯 去重效果:")
        print(f"   📚 PMC: {dedup['pmc_original_count']} → {dedup['pmc_deduplicated_count']} (减少 {dedup['pmc_reduction_percentage']:.1f}%)")
        print(f"   📄 PubMed: {dedup['pubmed_original_count']} → {dedup['pubmed_deduplicated_count']} (减少 {dedup['pubmed_reduction_percentage']:.1f}%)")
        print()

        print("📊 数据统计:")
        print(f"   🔗 疾病-文献映射: {mapping['literature_disease_mappings']} 个")
        print(f"   📚 去重PMC文章: {mapping['unique_pmc_count']} 篇")
        print(f"   📄 去重PubMed摘要: {mapping['unique_pubmed_count']} 篇")
        print()

        print("💡 优化优势:")
        print("   ✅ 避免重复下载，节省存储空间")
        print("   ✅ 减少网络请求，提高下载效率")
        print("   ✅ 建立清晰的疾病-文献映射关系")
        print("   ✅ 便于后续的数据分析和处理")
        print("="*80)

    def run_optimized_download(self, diseases: List[str], max_diseases: Optional[int] = None):
        """运行优化下载流程"""
        print("🧬 优化版罕见疾病文献下载工具")
        print("🎯 采用两阶段去重策略")
        print("="*50)

        try:
            # 阶段一：收集文献ID
            self.stage_one_collect_literature_ids(diseases, max_diseases)

            # 阶段二：批量下载
            self.stage_two_batch_download()

            # 保存优化报告
            self.save_optimization_report()

            print(f"\n🎉 优化下载完成！")
            print(f"💡 可查看下载的文献数据和优化报告")

        except KeyboardInterrupt:
            print(f"\n⚠️  用户中断了下载过程")
            # 即使中断也要保存已收集的数据
            if self.disease_literature_mapping:
                self.save_optimization_report()
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主函数"""
    print("🧬 优化版罕见疾病文献下载工具")
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

    print(f"\n🚀 选择了优化下载模式: {download_mode}")
    downloader = OptimizedLiteratureDownloader(download_mode)

    # 加载疾病列表
    diseases = downloader.load_disease_list()

    # 询问用户要处理多少个疾病
    print(f"\n💡 优化版下载提示:")
    print(f"   - 测试建议: 50-100 个疾病")
    print(f"   - 中等规模: 500-1000 个疾病")
    print(f"   - 全量下载: {len(diseases)} 个疾病")
    print(f"   - 按 Ctrl+C 可随时停止")
    print(f"   - 优化版会自动去重，提高效率")

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

    print(f"\n🚀 开始优化处理 {max_diseases} 个疾病...")

    try:
        # 运行优化下载
        downloader.run_optimized_download(diseases, max_diseases)

    except KeyboardInterrupt:
        print(f"\n⚠️  用户中断了下载过程")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()