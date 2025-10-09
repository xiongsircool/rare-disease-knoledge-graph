#!/usr/bin/env python3
"""
PubMed摘要批量下载器
专门针对罕见疾病文献的PubMed摘要下载
支持大批量处理和高效下载策略
"""

import os
import re
import time
import json
import math
from pathlib import Path
from typing import List, Dict, Optional, Set
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead
from dataclasses import dataclass, asdict
from Bio import Entrez
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


@dataclass
class PubMedConfig:
    """PubMed下载配置"""
    email: str
    api_key: Optional[str] = None
    output_dir: str = "pubmed_data"

    # 下载参数
    max_records_per_search: int = 100000  # PubMed单次最大记录数
    batch_size: int = 1000  # 每次efetch的记录数
    disease_batch_size: int = 50  # 每批处理的疾病数

    # 控制参数
    sleep_time: float = 0.34  # 无API key时的延迟
    sleep_time_with_key: float = 0.12  # 有API key时的延迟
    max_retry: int = 3
    request_timeout: int = 30

    # 并发控制
    max_workers: int = 3  # 最大并发线程数


class PubMedArticle:
    """PubMed文章数据类"""

    def __init__(self):
        self.pmid = ""
        self.pmcid = ""  # PMC ID
        self.title = ""
        self.abstract = ""
        self.authors = []
        self.journal = ""
        self.publication_date = {}
        self.doi = ""
        self.mesh_terms = []
        self.publication_types = []
        self.keywords = []
        self.abstract_languages = []
        self.disease = ""  # 关联的罕见疾病

    def to_dict(self) -> Dict:
        """转换为字典"""
        try:
            return asdict(self)
        except Exception:
            # 如果asdict失败，手动转换
            return {
                'pmid': self.pmid,
                'pmcid': self.pmcid,
                'title': self.title,
                'abstract': self.abstract,
                'authors': self.authors,
                'journal': self.journal,
                'publication_date': self.publication_date,
                'doi': self.doi,
                'mesh_terms': self.mesh_terms,
                'publication_types': self.publication_types,
                'keywords': self.keywords,
                'abstract_languages': self.abstract_languages,
                'disease': self.disease
            }

    def is_valid(self) -> bool:
        """检查文章是否有效"""
        return bool(self.pmid and self.title)


class PubMedDownloader:
    """PubMed摘要下载器"""

    def __init__(self, config: PubMedConfig):
        self.config = config
        self.setup_entrez()
        self.setup_directories()
        self.lock = threading.Lock()
        self.processed_pmids: Set[str] = set()  # 用于去重

    def setup_entrez(self):
        """设置Entrez配置"""
        Entrez.email = self.config.email
        Entrez.tool = "rare_disease_pubmed_downloader"
        if self.config.api_key:
            Entrez.api_key = self.config.api_key
            print(f"[INFO] 使用API key: {self.config.api_key[:8]}...")
        else:
            print("[INFO] 未使用API key，将使用默认延迟")

    def setup_directories(self):
        """创建目录结构"""
        self.base_dir = Path(self.config.output_dir)
        self.abstracts_dir = self.base_dir / "abstracts"
        self.metadata_dir = self.base_dir / "metadata"
        self.temp_dir = self.base_dir / "temp"

        for dir_path in [self.base_dir, self.abstracts_dir, self.metadata_dir, self.temp_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def load_disease_list(self, disease_file: str) -> List[str]:
        """加载罕见疾病列表"""
        with open(disease_file, 'r', encoding='utf-8') as f:
            diseases = [line.strip() for line in f if line.strip()]
        print(f"[INFO] 加载了 {len(diseases)} 个罕见疾病")
        return diseases

    def get_sleep_time(self) -> float:
        """获取适当的延迟时间"""
        return (self.config.sleep_time_with_key
                if self.config.api_key
                else self.config.sleep_time)

    def safe_search_term(self, disease_name: str) -> str:
        """构造安全的PubMed检索式 - 扩大到全文检索"""
        # 清理疾病名称，移除特殊字符
        disease_clean = re.sub(r'[^\w\s\-\.]', ' ', disease_name).strip()

        # 针对不同类型的疾病构造不同的检索策略
        if 'microdeletion' in disease_clean.lower() or 'microduplication' in disease_clean.lower():
            # 染色体微缺失/微重复综合征 - 使用更灵活的检索
            parts = disease_clean.split()
            search_terms = []

            # 提取染色体区域
            chr_region = ''
            for part in parts:
                if 'q' in part and ('.' in part or part.endswith('q')):
                    chr_region = part
                    break

            if chr_region:
                # 基于染色体区域的检索 - 保持Title/Abstract限定以提高精确度
                search_terms.append(f'({chr_region} AND (deletion OR microdeletion OR duplication OR microduplication))[Title/Abstract]')
                search_terms.append(f'("chromosome {chr_region}" AND (deletion OR microdeletion))[Title/Abstract]')

                # 添加更精确的检索
                search_terms.append(f'("{chr_region} deletion" AND (syndrome OR disorder OR abnormality))[Title/Abstract]')
                search_terms.append(f'("{chr_region} microdeletion" AND (syndrome OR disorder OR abnormality))[Title/Abstract]')

            # 添加原始术语的宽松匹配
            if 'microdeletion' in disease_clean.lower():
                base_name = disease_clean.replace("microdeletion syndrome", "").strip()
                search_terms.append(f'(microdeletion AND "{base_name}")')
                search_terms.append(f'("{disease_clean}")')
            elif 'microduplication' in disease_clean.lower():
                base_name = disease_clean.replace("microduplication syndrome", "").strip()
                search_terms.append(f'(microduplication AND "{base_name}")')
                search_terms.append(f'("{disease_clean}")')

            # 如果是综合征，添加相关术语
            if 'syndrome' in disease_clean.lower():
                base_name = disease_clean.replace('syndrome', '').strip()
                search_terms.append(f'("{base_name}" AND (syndrome OR disorder OR condition))')

            return ' OR '.join(search_terms) if search_terms else disease_clean

        elif 'syndrome' in disease_clean.lower() and len(disease_clean.split()) > 1:
            # 其他综合征 - 使用关键词组合，扩大检索范围
            base_terms = disease_clean.replace('syndrome', '').strip()
            return f'("{base_terms}" AND (syndrome OR disorder OR condition)) OR ("{disease_clean}")'

        elif disease_clean.count(' ') >= 3:
            # 复杂疾病名称 - 使用AND连接关键词
            keywords = disease_clean.split()[:3]  # 取前3个关键词
            return f'({" AND ".join(keywords)}) OR ("{disease_clean}")'

        else:
            # 简单疾病名称 - 直接匹配，扩大检索范围
            if ' ' in disease_clean:
                return f'("{disease_clean}") OR ({disease_clean.replace(" ", " AND ")})'
            else:
                return disease_clean

    def retry_call(self, func, *args, **kwargs):
        """重试机制"""
        sleep_time = self.get_sleep_time()

        for attempt in range(self.config.max_retry):
            try:
                return func(*args, **kwargs)
            except (HTTPError, URLError, IncompleteRead) as e:
                if attempt == self.config.max_retry - 1:
                    raise
                wait_time = sleep_time * (attempt + 1) * 2  # 指数退避
                print(f"[WARN] 第 {attempt + 1} 次重试，等待 {wait_time:.1f}s: {e}")
                time.sleep(wait_time)

    def search_pubmed(self, disease: str) -> List[str]:
        """搜索PubMed获取PMID列表"""
        search_term = self.safe_search_term(disease)
        print(f"[DEBUG] {disease}: 检索式 = {search_term}")

        try:
            # 先获取总数
            handle = self.retry_call(
                Entrez.esearch,
                db="pubmed",
                term=search_term,
                retmax=0,
                usehistory="y"
            )
            search_result = Entrez.read(handle)
            handle.close()

            count = int(search_result["Count"])
            if count == 0:
                print(f"[INFO] {disease}: 未找到相关文献")
                return []

            print(f"[INFO] {disease}: 找到 {count} 篇相关文献")

            # 获取所有PMID
            all_pmids = []
            retmax = min(self.config.max_records_per_search, count)

            # 如果记录数超过单次限制，需要分批获取
            if count > retmax:
                print(f"[INFO] {disease}: 文献数较多({count})，将分批获取")

                # 分批搜索
                for retstart in range(0, count, retmax):
                    current_retmax = min(retmax, count - retstart)

                    handle = self.retry_call(
                        Entrez.esearch,
                        db="pubmed",
                        term=search_term,
                        retstart=retstart,
                        retmax=current_retmax,
                        usehistory="y"
                    )
                    result = Entrez.read(handle)
                    handle.close()

                    batch_pmids = result["IdList"]
                    all_pmids.extend(batch_pmids)

                    print(f"[INFO] {disease}: 获取了 {len(batch_pmids)} 个PMID ({len(all_pmids)}/{count})")
                    time.sleep(self.get_sleep_time())
            else:
                # 一次性获取所有PMID
                handle = self.retry_call(
                    Entrez.esearch,
                    db="pubmed",
                    term=search_term,
                    retmax=count,
                    usehistory="y"
                )
                result = Entrez.read(handle)
                handle.close()
                all_pmids = result["IdList"]

            return all_pmids

        except Exception as e:
            print(f"[ERROR] {disease}: 搜索失败 - {e}")
            return []

    def fetch_abstracts_batch(self, pmids: List[str], disease: str) -> List[PubMedArticle]:
        """批量获取摘要"""
        if not pmids:
            return []

        print(f"[INFO] {disease}: 开始下载 {len(pmids)} 篇摘要")

        all_articles = []

        # 分批获取摘要
        for i in range(0, len(pmids), self.config.batch_size):
            batch_pmids = pmids[i:i+self.config.batch_size]
            batch_num = i // self.config.batch_size + 1
            total_batches = math.ceil(len(pmids) / self.config.batch_size)

            print(f"[INFO] {disease}: 下载摘要批次 {batch_num}/{total_batches} ({len(batch_pmids)} 篇)")

            try:
                # 使用post方法获取摘要
                handle = self.retry_call(
                    Entrez.efetch,
                    db="pubmed",
                    id=batch_pmids,
                    rettype="xml",
                    retmode="xml"
                )

                xml_content = handle.read()
                handle.close()

                # 解析XML
                articles = self.parse_pubmed_xml(xml_content, disease)
                all_articles.extend(articles)

                print(f"[OK] {disease}: 批次 {batch_num} 成功解析 {len(articles)} 篇文章")

            except Exception as e:
                print(f"[ERROR] {disease}: 批次 {batch_num} 下载失败 - {e}")

            time.sleep(self.get_sleep_time())

        return all_articles

    def parse_pubmed_xml(self, xml_content, disease: str) -> List[PubMedArticle]:
        """解析PubMed XML数据"""
        try:
            if isinstance(xml_content, bytes):
                xml_content = xml_content.decode('utf-8')

            root = ET.fromstring(xml_content)
            articles = []

            for article_elem in root.findall('.//PubmedArticle'):
                try:
                    article = PubMedArticle()
                    article.disease = disease

                    # 解析各个字段
                    article.pmid = self._get_text(article_elem, './/PMID')
                    article.pmcid = self._get_text(article_elem, './/ArticleId[@IdType="pmc"]')
                    # 确保PMCID格式正确（移除PMC前缀中的数字）
                    if article.pmcid and article.pmcid.startswith('PMC'):
                        article.pmcid = article.pmcid  # 保持完整格式如 "PMC123456"

                    article.title = self._get_text(article_elem, './/ArticleTitle')
                    article.abstract = self._parse_abstract(article_elem)
                    article.authors = self._parse_authors(article_elem)
                    article.journal = self._get_text(article_elem, './/JournalTitle')
                    article.publication_date = self._parse_publication_date(article_elem)
                    article.doi = self._get_text(article_elem, './/ArticleId[@IdType="doi"]')
                    # 如果没有找到DOI，尝试其他可能的DOI格式
                    if not article.doi:
                        article.doi = self._get_text(article_elem, './/ELocationID[@EIdType="doi"]')
                    article.mesh_terms = self._parse_mesh_terms(article_elem)
                    article.publication_types = self._parse_publication_types(article_elem)
                    article.keywords = self._parse_keywords(article_elem)
                    article.abstract_languages = self._parse_languages(article_elem)

                    # 检查是否有效且未重复
                    if article.is_valid() and article.pmid not in self.processed_pmids:
                        articles.append(article)
                        self.processed_pmids.add(article.pmid)

                except Exception as e:
                    print(f"[WARN] 解析文章失败: {e}")
                    continue

            return articles

        except ET.ParseError as e:
            print(f"[ERROR] XML解析失败: {e}")
            return []

    def _get_text(self, element, xpath: str) -> str:
        """安全获取XML元素文本"""
        elem = element.find(xpath)
        return elem.text.strip() if elem is not None and elem.text else ""

    def _parse_abstract(self, article_elem) -> str:
        """解析摘要文本"""
        abstract_texts = []
        for abs_text in article_elem.findall('.//AbstractText'):
            if abs_text.text:
                abstract_texts.append(abs_text.text.strip())

        return ' '.join(abstract_texts)

    def _parse_authors(self, article_elem) -> List[str]:
        """解析作者信息"""
        authors = []
        for author in article_elem.findall('.//Author'):
            last_name = self._get_text(author, './/LastName')
            fore_name = self._get_text(author, './/ForeName')
            initials = self._get_text(author, './/Initials')

            if last_name:
                author_name = f"{last_name} {fore_name}".strip()
                if not author_name or author_name == last_name:
                    author_name = f"{last_name} {initials}".strip()
                authors.append(author_name)

        return authors[:10]  # 限制作者数量

    def _parse_publication_date(self, article_elem) -> Dict:
        """解析发表日期"""
        pub_date = article_elem.find('.//PubDate')
        if pub_date is not None:
            year = self._get_text(pub_date, './/Year')
            month = self._get_text(pub_date, './/Month')
            day = self._get_text(pub_date, './/Day')

            # 格式化日期
            date_parts = []
            if year:
                date_parts.append(year)
            if month:
                date_parts.append(month.zfill(2))
            if day:
                date_parts.append(day.zfill(2))

            formatted_date = '-'.join(date_parts) if date_parts else year

            return {
                'year': year,
                'month': month,
                'day': day,
                'formatted': formatted_date
            }
        return {}

    def _parse_mesh_terms(self, article_elem) -> List[str]:
        """解析MeSH术语"""
        mesh_terms = []
        for mesh in article_elem.findall('.//MeshHeading'):
            descriptor = self._get_text(mesh, './/DescriptorName')
            if descriptor:
                mesh_terms.append(descriptor)
        return mesh_terms

    def _parse_publication_types(self, article_elem) -> List[str]:
        """解析发表类型"""
        pub_types = []
        for pub_type in article_elem.findall('.//PublicationType'):
            if pub_type.text:
                pub_types.append(pub_type.text.strip())
        return pub_types

    def _parse_keywords(self, article_elem) -> List[str]:
        """解析关键词"""
        keywords = []
        for keyword in article_elem.findall('.//Keyword'):
            if keyword.text:
                keywords.append(keyword.text.strip())
        return keywords

    def _parse_languages(self, article_elem) -> List[str]:
        """解析语言信息"""
        languages = []
        for lang in article_elem.findall('.//Abstract/AbstractText[@Language]'):
            lang_code = lang.get('Language')
            if lang_code:
                languages.append(lang_code)
        return list(set(languages))

    def save_articles(self, articles: List[PubMedArticle], disease: str):
        """保存文章数据"""
        if not articles:
            return

        # 生成安全的文件名
        safe_disease_name = re.sub(r'[^\w\-\.]+', '_', disease)[:50]
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        # 保存JSON文件
        json_file = self.abstracts_dir / f"{safe_disease_name}_{timestamp}.json"

        data = {
            'disease': disease,
            'search_timestamp': timestamp,
            'total_articles': len(articles),
            'articles': [article.to_dict() for article in articles]
        }

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[OK] 保存摘要: {json_file} ({len(articles)} 篇)")

        # 保存CSV文件（可选）
        self.save_articles_csv(articles, disease, safe_disease_name, timestamp)

    def save_articles_csv(self, articles: List[PubMedArticle], disease: str, safe_name: str, timestamp: str):
        """保存为CSV格式"""
        import csv

        csv_file = self.abstracts_dir / f"{safe_name}_{timestamp}.csv"

        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # 写入标题行
            writer.writerow([
                'PMID', 'PMCID', 'Title', 'Abstract', 'Authors', 'Journal',
                'Publication Year', 'DOI', 'MeSH Terms', 'Publication Types',
                'Keywords', 'Languages', 'Disease'
            ])

            # 写入数据
            for article in articles:
                writer.writerow([
                    article.pmid,
                    article.pmcid,
                    article.title,
                    article.abstract[:1000] + '...' if len(article.abstract) > 1000 else article.abstract,
                    '; '.join(article.authors),
                    article.journal,
                    article.publication_date.get('year', ''),
                    article.doi,
                    '; '.join(article.mesh_terms),
                    '; '.join(article.publication_types),
                    '; '.join(article.keywords),
                    '; '.join(article.abstract_languages),
                    article.disease
                ])

        print(f"[OK] 保存CSV: {csv_file}")

    def process_single_disease(self, disease: str) -> Dict:
        """处理单个疾病"""
        print(f"\n{'='*60}")
        print(f"🔬 处理疾病: {disease}")
        print(f"{'='*60}")

        result = {
            'disease': disease,
            'success': False,
            'pmids_found': 0,
            'articles_downloaded': 0,
            'error': None,
            'processing_time': 0
        }

        start_time = time.time()

        try:
            # 搜索PubMed
            pmids = self.search_pubmed(disease)
            result['pmids_found'] = len(pmids)

            if not pmids:
                result['success'] = True  # 没找到文献也算成功
                print(f"[INFO] {disease}: 未找到相关文献")
                return result

            # 下载摘要
            articles = self.fetch_abstracts_batch(pmids, disease)
            result['articles_downloaded'] = len(articles)

            # 保存数据
            if articles:
                self.save_articles(articles, disease)

            result['success'] = True
            print(f"[OK] {disease}: 完成，获得 {len(articles)} 篇摘要")

        except Exception as e:
            result['error'] = str(e)
            print(f"[ERROR] {disease}: 处理失败 - {e}")

        finally:
            result['processing_time'] = time.time() - start_time

        return result

    def process_diseases_batch(self, diseases: List[str]) -> List[Dict]:
        """批量处理疾病"""
        print(f"\n🚀 开始批量处理 {len(diseases)} 个疾病")
        print(f"📂 输出目录: {self.base_dir}")
        print(f"🧵 并发线程数: {self.config.max_workers}")

        results = []

        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # 提交所有任务
            future_to_disease = {
                executor.submit(self.process_single_disease, disease): disease
                for disease in diseases
            }

            # 处理完成的任务
            for i, future in enumerate(as_completed(future_to_disease), 1):
                disease = future_to_disease[future]
                print(f"\n📋 进度: {i}/{len(diseases)} - {disease}")

                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f"[ERROR] {disease}: 任务执行失败 - {e}")
                    results.append({
                        'disease': disease,
                        'success': False,
                        'error': f"Task execution failed: {e}",
                        'pmids_found': 0,
                        'articles_downloaded': 0,
                        'processing_time': 0
                    })

        # 保存批处理结果
        self.save_batch_results(results)
        self.print_batch_summary(results)

        return results

    def save_batch_results(self, results: List[Dict]):
        """保存批处理结果"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        results_file = self.metadata_dir / f"batch_results_{timestamp}.json"

        summary = {
            'timestamp': timestamp,
            'total_diseases': len(results),
            'successful_diseases': sum(1 for r in results if r['success']),
            'total_pmids': sum(r['pmids_found'] for r in results),
            'total_articles': sum(r['articles_downloaded'] for r in results),
            'total_processing_time': sum(r['processing_time'] for r in results),
            'failed_diseases': [r['disease'] for r in results if not r['success']],
            'detailed_results': results
        }

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n[INFO] 批处理结果已保存: {results_file}")

    def print_batch_summary(self, results: List[Dict]):
        """打印批处理总结"""
        print("\n" + "="*80)
        print("📊 PubMed批量下载完成总结")
        print("="*80)

        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]

        print(f"📅 处理时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔬 总疾病数: {len(results)}")
        print(f"✅ 成功处理: {len(successful)}")
        print(f"❌ 处理失败: {len(failed)}")

        if successful:
            total_pmids = sum(r['pmids_found'] for r in successful)
            total_articles = sum(r['articles_downloaded'] for r in successful)
            total_time = sum(r['processing_time'] for r in successful)

            print(f"📊 找到PMID: {total_pmids}")
            print(f"📄 下载摘要: {total_articles}")
            print(f"⏱️  总用时: {total_time:.1f} 秒")
            print(f"⚡ 平均速度: {total_articles/max(total_time, 1):.1f} 篇/秒")

        if failed:
            print(f"\n❌ 失败的疾病:")
            for result in failed[:10]:  # 只显示前10个
                print(f"   - {result['disease']}: {result.get('error', 'Unknown error')}")
            if len(failed) > 10:
                print(f"   ... 还有 {len(failed) - 10} 个失败疾病")

        print(f"\n📁 数据保存在: {self.base_dir}")
        print(f"📋 详细结果在: {self.metadata_dir}")
        print("="*80)


def main():
    """主函数"""

    # 配置
    config = PubMedConfig(
        email="your_email@example.com",  # 请替换为你的邮箱
        api_key=None,  # 如有NCBI API key可填入，可大幅提高下载速度
        output_dir="pubmed_data",
        disease_batch_size=50,  # 每批处理50个疾病
        batch_size=1000,  # 每次efetch获取1000条记录
        max_workers=3,  # 3个并发线程
        sleep_time=0.34,  # 无API key时的延迟
        sleep_time_with_key=0.12  # 有API key时的延迟
    )

    # 初始化下载器
    downloader = PubMedDownloader(config)

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    all_diseases = downloader.load_disease_list(disease_file)

    # 示例：处理前10个疾病作为测试
    test_diseases = all_diseases[:10]

    print(f"🧪 测试模式：处理前 {len(test_diseases)} 个疾病")
    print(f"📋 疾病列表: {', '.join(test_diseases[:3])}...")

    # 执行下载
    results = downloader.process_diseases_batch(test_diseases)

    print(f"\n🎉 测试完成！")
    print(f"💡 如需处理全部{len(all_diseases)}个疾病，请修改 main() 函数中的 test_diseases")
    print(f"💡 建议获取NCBI API key以提高下载速度：https://www.ncbi.nlm.nih.gov/account/")


if __name__ == "__main__":
    main()