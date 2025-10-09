#!/usr/bin/env python3
"""
优化版PMC全文下载器
整合现有的批量下载脚本和解析功能
基于 test/pmc/downloadpmc.py 和 test/pmc/pmcpaser.py
"""

import os
import re
import math
import time
import json
from pathlib import Path
from typing import List, Dict, Optional, Set
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead
from dataclasses import dataclass, asdict
from Bio import Entrez
import xml.etree.ElementTree as ET


@dataclass
class OptimizedPMCConfig:
    """优化版PMC下载配置"""
    email: str
    api_key: Optional[str] = None
    output_dir: str = "optimized_pmc_data"

    # 下载参数（基于原有脚本优化）
    batch_size: int = 500  # 每批下载的文章数
    disease_batch_size: int = 10  # 每批处理的疾病数
    max_records_per_search: int = 100000  # PubMed单次最大记录数

    # 控制参数
    sleep_time: float = 0.34  # 无API key时的延迟
    sleep_time_with_key: float = 0.12  # 有API key时的延迟
    max_retry: int = 3

    # 解析选项
    save_parsed_json: bool = True
    save_raw_xml: bool = True
    parse_detailed_content: bool = True


class OptimizedPMCArticle:
    """优化版PMC文章数据类（基于原有解析器）"""

    def __init__(self):
        self.pmc_id = ""
        self.pmid = ""
        self.doi = ""
        self.title = ""
        self.abstract = ""
        self.authors = []
        self.journal = ""
        self.publication_date = {}
        self.article_type = ""
        self.disease = ""
        self.keywords = []
        self.publication_types = []
        self.italic_texts = []
        self.notes = ""
        self.notes_links = []
        self.full_text = ""
        self.figure_info_list = []
        self.table_list = []
        self.reference_list = []

    def to_dict(self) -> Dict:
        """转换为字典"""
        try:
            return asdict(self)
        except Exception:
            # 如果asdict失败，手动转换
            return {
                'pmc_id': self.pmc_id,
                'pmid': self.pmid,
                'doi': self.doi,
                'title': self.title,
                'abstract': self.abstract,
                'authors': self.authors,
                'journal': self.journal,
                'publication_date': self.publication_date,
                'article_type': self.article_type,
                'disease': self.disease,
                'keywords': self.keywords,
                'publication_types': self.publication_types,
                'italic_texts': self.italic_texts,
                'notes': self.notes,
                'notes_links': self.notes_links,
                'full_text': self.full_text,
                'figure_info_list': self.figure_info_list,
                'table_list': self.table_list,
                'reference_list': self.reference_list
            }


class OptimizedPMCDownloader:
    """优化版PMC全文下载器"""

    def __init__(self, config: OptimizedPMCConfig):
        self.config = config
        self.setup_entrez()
        self.setup_directories()
        self.processed_pmids: Set[str] = set()

    def setup_entrez(self):
        """设置Entrez配置"""
        Entrez.email = self.config.email
        Entrez.tool = "optimized_pmc_downloader"
        if self.config.api_key:
            Entrez.api_key = self.config.api_key

    def setup_directories(self):
        """创建目录结构"""
        self.base_dir = Path(self.config.output_dir)
        self.xml_dir = self.base_dir / "xml_files"
        self.parsed_dir = self.base_dir / "parsed_json"
        self.metadata_dir = self.base_dir / "metadata"

        for dir_path in [self.base_dir, self.xml_dir, self.parsed_dir, self.metadata_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def get_sleep_time(self) -> float:
        """获取适当的延迟时间"""
        return (self.config.sleep_time_with_key
                if self.config.api_key
                else self.config.sleep_time)

    def _safe_name(self, s: str, maxlen: int = 80) -> str:
        """安全文件名（来自原脚本）"""
        s = re.sub(r"[^\w\-\.\+]+", "_", s.strip())
        return s[:maxlen].strip("_") or "query"

    def _retry_call(self, fn, *args, **kwargs):
        """重试机制（来自原脚本）"""
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except (HTTPError, URLError, IncompleteRead) as e:
                attempt += 1
                if attempt > self.config.max_retry:
                    print(f"[ERROR] 重试 {self.config.max_retry} 次后仍然失败: {e}")
                    raise
                print(f"[WARN] 第 {attempt} 次重试，错误: {e}")
                time.sleep(self.get_sleep_time() * attempt)

    def _safe_fetch_with_retry(self, batch_ids: List[str], max_retries: int = 3):
        """安全的批量下载（来自原脚本）"""
        for attempt in range(max_retries):
            try:
                h = Entrez.efetch(
                    db="pmc",
                    id=",".join(batch_ids),
                    rettype="xml",
                    retmode="text"
                )

                # 分段读取，避免 IncompleteRead 错误
                xml_parts = []
                chunk_size = 8192  # 8KB chunks

                while True:
                    chunk = h.read(chunk_size)
                    if not chunk:
                        break
                    xml_parts.append(chunk)

                h.close()
                xml_text = b''.join(xml_parts)

                # 确保 xml_text 是字符串类型
                if isinstance(xml_text, bytes):
                    xml_text = xml_text.decode('utf-8')

                return xml_text

            except IncompleteRead as e:
                print(f"[WARN] 第 {attempt + 1} 次尝试出现 IncompleteRead 错误: {e}")
                if attempt < max_retries - 1:
                    print(f"[INFO] 等待 {self.get_sleep_time() * (attempt + 1)} 秒后重试...")
                    time.sleep(self.get_sleep_time() * (attempt + 1))
                    continue
                else:
                    print(f"[ERROR] 所有重试都失败了，跳过这批数据")
                    raise
            except Exception as e:
                print(f"[ERROR] 下载时出现未知错误: {e}")
                raise

    def safe_search_term(self, disease_name: str) -> str:
        """构造安全的PMC检索式 - 基于诊断结果优化"""
        disease_clean = re.sub(r'[^\w\s\-\.]', ' ', disease_name).strip()

        # 基于诊断结果的简单策略：直接使用疾病名称，不添加复杂限制
        # 诊断结果显示完整疾病名称在PMC中检索效果很好

        # 策略1: 直接使用完整疾病名称（不限制字段，效果最好）
        return f'"{disease_clean}"'

    def _try_search(self, search_term: str) -> tuple[int, dict]:
        """尝试搜索并返回结果数量和搜索结果"""
        try:
            # 先获取总数
            handle = self._retry_call(
                Entrez.esearch,
                db="pmc",
                term=search_term,
                retmax=0,
                usehistory="y"
            )
            search_result = Entrez.read(handle)
            handle.close()

            count = int(search_result["Count"])
            return count, search_result

        except Exception as e:
            print(f"[ERROR] 搜索失败: {e}")
            return 0, {}

    def search_pmc_by_disease(self, disease: str) -> List[str]:
        """通过疾病名称搜索PMC获取文章ID列表（基于原脚本优化）"""
        # 策略1: 精确检索（带引号）
        exact_search_term = self.safe_search_term(disease)
        print(f"[DEBUG] {disease}: PMC精确检索式 = {exact_search_term}")

        # 尝试精确检索
        count, search_result = self._try_search(exact_search_term)
        final_search_term = exact_search_term

        if count == 0:
            # 策略2: 宽松检索（不带引号）
            disease_clean = re.sub(r'[^\w\s\-\.]', ' ', disease).strip()
            loose_search_term = disease_clean
            print(f"[DEBUG] {disease}: 尝试宽松检索式 = {loose_search_term}")

            count, search_result = self._try_search(loose_search_term)

            if count == 0:
                print(f"[INFO] {disease}: PMC中未找到免费全文")
                return []
            else:
                print(f"[INFO] {disease}: 宽松检索找到 {count} 篇免费全文")
                final_search_term = loose_search_term
        else:
            print(f"[INFO] {disease}: 精确检索找到 {count} 篇免费全文")

        # 获取所有PMC ID（基于原脚本逻辑）
        all_ids = []
        retstart = 0
        page_size = min(self.config.max_records_per_search, count)

        while retstart < count:
            size = min(page_size, count - retstart)
            handle = self._retry_call(
                Entrez.esearch,
                db="pmc",
                term=final_search_term,
                retstart=retstart,
                retmax=size,
                usehistory="y"
            )
            r = Entrez.read(handle)
            handle.close()

            all_ids.extend([f"PMC{_id}" if not str(_id).upper().startswith("PMC") else str(_id).upper()
                       for _id in r["IdList"]])
            retstart += size
            print(f"[INFO] {disease}: 获取ID：{len(all_ids)}/{count}")
            time.sleep(self.get_sleep_time())

        return all_ids

    def download_pmc_by_disease(self, disease: str, pmc_ids: List[str]) -> int:
        """下载单个疾病的PMC全文（基于原脚本核心逻辑）"""
        if not pmc_ids:
            return 0

        print(f"[INFO] {disease}: 开始下载，每批 {self.config.batch_size} 篇，共 {math.ceil(len(pmc_ids)/self.config.batch_size)} 批。")

        # 创建疾病目录
        base = self._safe_name(disease)
        disease_dir = self.xml_dir / base
        disease_dir.mkdir(exist_ok=True)

        downloaded_count = 0
        batch_idx = 1
        failed_batches = []

        for i in range(0, len(pmc_ids), self.config.batch_size):
            batch_ids = pmc_ids[i:i+self.config.batch_size]
            print(f"[INFO] 正在下载第 {batch_idx} 批，包含 {len(batch_ids)} 篇文献...")

            try:
                # 使用原脚本的下载方法
                xml_text = self._safe_fetch_with_retry(batch_ids)

                # 保存XML文件（原脚本逻辑）
                outfile = disease_dir / f"{base}_batch_{batch_idx:05d}.xml"
                with open(outfile, "w", encoding="utf-8") as f:
                    f.write(xml_text)
                print(f"[OK] 保存：{outfile} （本批 {len(batch_ids)} 篇）")

                downloaded_count += len(batch_ids)

                # 如果启了解析，则解析这一批数据
                if self.config.parse_detailed_content:
                    self.parse_and_save_batch(xml_text, disease, batch_idx)

            except Exception as e:
                print(f"[ERROR] 第 {batch_idx} 批下载失败: {e}")
                failed_batches.append((batch_idx, batch_ids, str(e)))

            batch_idx += 1
            time.sleep(self.get_sleep_time())

        print(f"[INFO] {disease}: 下载完成！成功 {downloaded_count} 篇，失败批次 {len(failed_batches)}")
        return downloaded_count

    def parse_and_save_batch(self, xml_text: str, disease: str, batch_idx: int):
        """解析批次数据并保存（基于原解析器）"""
        try:
            # 使用原有的解析逻辑
            articles = self.parse_full_articles(xml_text, disease)

            if articles:
                safe_disease_name = self._safe_name(disease)
                timestamp = time.strftime('%Y%m%d_%H%M%S')

                # 保存解析结果
                json_file = self.parsed_dir / f"{safe_disease_name}_batch_{batch_idx:05d}_{timestamp}.json"

                data = {
                    'disease': disease,
                    'batch_number': batch_idx,
                    'search_timestamp': timestamp,
                    'total_articles': len(articles),
                    'articles': [article.to_dict() for article in articles]
                }

                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                print(f"[OK] 解析并保存: {json_file} ({len(articles)} 篇)")

        except Exception as e:
            print(f"[ERROR] 解析批次 {batch_idx} 失败: {e}")

    def parse_full_articles(self, xml_content: str, disease: str) -> List[OptimizedPMCArticle]:
        """解析完整文章（基于原解析器）"""
        try:
            if isinstance(xml_content, bytes):
                xml_content = xml_content.decode('utf-8')

            root = ET.fromstring(xml_content)
            articles = []

            # 处理命名空间
            namespace = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
            article_elements = root.findall('article')
            if not article_elements and namespace:
                article_elements = root.findall(f'{namespace}article')

            for article_elem in article_elements:
                try:
                    article = OptimizedPMCArticle()
                    article.disease = disease

                    # 使用原有解析器的逻辑
                    article.pmc_id = self.get_clean_text(article_elem, './/article-id[@pub-id-type="pmcid"]')
                    article.pmid = self.get_clean_text(article_elem, './/article-id[@pub-id-type="pmid"]')
                    article.doi = self.get_clean_text(article_elem, './/article-id[@pub-id-type="doi"]')
                    article.title = self.get_clean_text(article_elem, './/article-title')
                    article.abstract = self.get_clean_text(article_elem, './/abstract')
                    article.authors = self.parse_authors(article_elem)
                    article.journal = self.get_clean_text(article_elem, './/journal-title')
                    article.article_type = article_elem.get('article-type', '')
                    article.publication_date = self.parse_publication_date(article_elem)
                    article.keywords = self.parse_keywords(article_elem)
                    article.publication_types = self.parse_publication_types(article_elem)
                    article.italic_texts = self.parse_italic_texts(article_elem)
                    article.notes = self.get_clean_text(article_elem, './/notes')
                    article.notes_links = self.parse_notes_links(article_elem)

                    # 解析全文内容
                    article.full_text = self.parse_full_text(article_elem)

                    # 解析图表信息
                    article.figure_info_list = self.parse_figures(article_elem, article.pmc_id)
                    article.table_list = self.parse_tables(article_elem)

                    # 解析参考文献
                    article.reference_list = self.parse_references(article_elem)

                    if article.pmc_id and article.pmc_id not in self.processed_pmids:
                        articles.append(article)
                        self.processed_pmids.add(article.pmc_id)

                except Exception as e:
                    print(f"[WARN] 解析文章失败: {e}")
                    continue

            return articles

        except ET.ParseError as e:
            print(f"[ERROR] XML解析失败: {e}")
            return []

    # 以下方法来自原解析器
    def get_clean_text(self, element, xpath: str = '.') -> str:
        """安全获取文本内容（来自原解析器）"""
        if element is None:
            return ""
        elem = element.find(xpath)
        return elem.text.strip() if elem is not None and elem.text else ""

    def parse_authors(self, article_elem) -> List[str]:
        """解析作者信息（来自原解析器）"""
        authors = []
        for author in article_elem.findall('.//Author'):
            last_name = self.get_clean_text(author, './/LastName')
            fore_name = self.get_clean_text(author, './/ForeName')
            if last_name:
                author_name = f"{last_name} {fore_name}".strip()
                authors.append(author_name)
        return authors

    def parse_publication_date(self, article_elem) -> Dict:
        """解析发表日期（来自原解析器）"""
        pub_date = article_elem.find('.//pub-date')
        if pub_date is not None:
            year = self.get_clean_text(pub_date, './/year')
            month = self.get_clean_text(pub_date, './/month')
            day = self.get_clean_text(pub_date, './/day')

            date_parts = []
            if year:
                date_parts.append(year)
            if month:
                date_parts.append(month.zfill(2))
            if day:
                date_parts.append(day.zfill(2))

            return {
                'year': year,
                'month': month,
                'day': day,
                'formatted': '-'.join(date_parts) if date_parts else year
            }
        return {}

    def parse_keywords(self, article_elem) -> List[str]:
        """解析关键词（来自原解析器）"""
        keywords = []
        for keyword in article_elem.findall('.//kwd'):
            if keyword.text:
                keywords.append(keyword.text.strip())
        return keywords

    def parse_publication_types(self, article_elem) -> List[str]:
        """解析发表类型（来自原解析器）"""
        pub_types = []
        for pub_type in article_elem.findall('.//PublicationType'):
            if pub_type.text:
                pub_types.append(pub_type.text.strip())
        return pub_types

    def parse_italic_texts(self, article_elem) -> List[str]:
        """解析斜体文本（来自原解析器）"""
        italic_texts = []
        title_elem = article_elem.find('.//article-title')
        if title_elem is not None:
            for italic in title_elem.findall('.//italic'):
                text = self.get_clean_text(ET.Element('dummy', text=italic.text)) if italic.text else ""
                if text and len(text) > 1:
                    italic_texts.append(text)

        abstract_elem = article_elem.find('.//abstract')
        if abstract_elem is not None:
            for italic in abstract_elem.findall('.//italic'):
                text = self.get_clean_text(ET.Element('dummy', text=italic.text)) if italic.text else ""
                if text and len(text) > 1:
                    italic_texts.append(text)

        return list(set(italic_texts))

    def parse_notes_links(self, article_elem) -> List[str]:
        """解析笔记链接（来自原解析器）"""
        notes_links = []
        notes_elem = article_elem.find('.//notes')
        if notes_elem is not None:
            for ext_link in notes_elem.findall('.//ext-link'):
                href = ext_link.get('{http://www.w3.org/1999/xlink}href')
                if href:
                    notes_links.append(href)
        return notes_links

    def parse_full_text(self, article_elem) -> str:
        """解析全文内容"""
        text_parts = []
        body_elem = article_elem.find('.//body')
        if body_elem is not None:
            for p in body_elem.findall('.//p'):
                text = ''.join(p.itertext()).strip()
                if text:
                    text_parts.append(text)
        return ' '.join(text_parts)

    def parse_figures(self, article_elem, pmc_id: str) -> List[Dict]:
        """解析图表信息（来自原解析器）"""
        figures = []
        for fig in article_elem.findall('.//fig'):
            fig_info = {
                'id': fig.get('id', ''),
                'label': self.get_clean_text(fig, './/label'),
                'title': self.get_clean_text(fig, './/title'),
                'caption': self.get_clean_text(fig, './/caption'),
                'graphic_url': '',
                'download_url': ''
            }

            graphic = fig.find('.//graphic')
            if graphic is not None:
                graphic_url = graphic.get('{http://www.w3.org/1999/xlink}href', '') or graphic.get('href', '')
                fig_info['graphic_url'] = graphic_url

                if pmc_id and graphic_url:
                    fig_info['download_url'] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/instance/{pmc_id.replace('PMC', '')}/bin/{graphic_url}"

            if fig_info['id']:
                figures.append(fig_info)
        return figures

    def parse_tables(self, article_elem) -> List[Dict]:
        """解析表格信息（来自原解析器）"""
        tables = []
        for table_wrap in article_elem.findall('.//table-wrap'):
            table_info = {
                'id': table_wrap.get('id', ''),
                'label': self.get_clean_text(table_wrap, './/label'),
                'caption': self.get_clean_text(table_wrap, './/caption'),
                'rows': []
            }

            table = table_wrap.find('.//table')
            if table is not None:
                for row in table.findall('.//tr'):
                    row_data = []
                    for cell in row.findall('.//td|.//th'):
                        cell_text = ''.join(cell.itertext()).strip()
                        if cell_text:
                            row_data.append(cell_text)
                    if row_data:
                        table_info['rows'].append(row_data)

            if table_info['id']:
                tables.append(table_info)
        return tables

    def parse_references(self, article_elem) -> List[Dict]:
        """解析参考文献（基于原解析器逻辑）"""
        references = []
        ref_list = article_elem.find('.//ref-list')
        if ref_list is not None:
            for ref in ref_list.findall('.//ref'):
                ref_info = {
                    'label': self.get_clean_text(ref, './/label'),
                    'authors': '',
                    'article_title': self.get_clean_text(ref, './/article-title'),
                    'source': self.get_clean_text(ref, './/source'),
                    'year': self.get_clean_text(ref, './/year'),
                    'volume': self.get_clean_text(ref, './/volume'),
                    'issue': self.get_clean_text(ref, './/issue'),
                    'fpage': self.get_clean_text(ref, './/fpage'),
                    'lpage': self.get_clean_text(ref, './/lpage'),
                    'doi': self.get_clean_text(ref, './/pub-id[@pub-id-type="doi"]'),
                    'pmid': self.get_clean_text(ref, './/pub-id[@pub-id-type="pmid"]')
                }
                references.append(ref_info)
        return references

    def save_parsed_articles(self, articles: List[OptimizedPMCArticle], identifier: str):
        """保存解析后的文章数据"""
        if not articles or not self.config.save_parsed_json:
            return

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        json_file = self.parsed_dir / f"{identifier}_{timestamp}.json"

        data = {
            'identifier': identifier,
            'search_timestamp': timestamp,
            'total_articles': len(articles),
            'articles': [article.to_dict() for article in articles]
        }

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[OK] 保存解析数据: {json_file} ({len(articles)} 篇)")

    def process_single_disease(self, disease: str) -> Dict:
        """处理单个疾病"""
        print(f"\n{'='*60}")
        print(f"🔬 处理疾病: {disease}")
        print(f"{'='*60}")

        result = {
            'disease': disease,
            'success': False,
            'pmc_ids_found': 0,
            'articles_downloaded': 0,
            'error': None,
            'processing_time': 0
        }

        start_time = time.time()

        try:
            # 搜索PMC
            pmc_ids = self.search_pmc_by_disease(disease)
            result['pmc_ids_found'] = len(pmc_ids)

            if not pmc_ids:
                result['success'] = True
                print(f"[INFO] {disease}: PMC中未找到免费全文")
                return result

            # 下载全文
            downloaded_count = self.download_pmc_by_disease(disease, pmc_ids)
            result['articles_downloaded'] = downloaded_count

            result['success'] = True
            print(f"[OK] {disease}: 完成，下载 {downloaded_count} 篇")

        except Exception as e:
            result['error'] = str(e)
            print(f"[ERROR] {disease}: 处理失败 - {e}")

        finally:
            result['processing_time'] = time.time() - start_time

        return result

    def process_diseases_batch(self, diseases: List[str]) -> List[Dict]:
        """批量处理疾病"""
        print(f"\n🚀 开始优化版PMC批量处理 {len(diseases)} 个疾病")
        print(f"📂 输出目录: {self.base_dir}")

        results = []

        for i, disease in enumerate(diseases, 1):
            print(f"\n📋 进度: {i}/{len(diseases)} - {disease}")
            result = self.process_single_disease(disease)
            results.append(result)

        # 保存批处理结果
        self.save_batch_results(results)
        self.print_batch_summary(results)

        return results

    def save_batch_results(self, results: List[Dict]):
        """保存批处理结果"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        results_file = self.metadata_dir / f"optimized_pmc_results_{timestamp}.json"

        summary = {
            'timestamp': timestamp,
            'total_diseases': len(results),
            'successful_diseases': sum(1 for r in results if r['success']),
            'total_pmc_ids': sum(r['pmc_ids_found'] for r in results),
            'total_articles': sum(r['articles_downloaded'] for r in results),
            'total_processing_time': sum(r['processing_time'] for r in results),
            'failed_diseases': [r['disease'] for r in results if not r['success']],
            'detailed_results': results
        }

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n[INFO] 优化版PMC批处理结果已保存: {results_file}")

    def print_batch_summary(self, results: List[Dict]):
        """打印批处理总结"""
        print("\n" + "="*80)
        print("📊 优化版PMC批量下载完成总结")
        print("="*80)

        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]

        print(f"📅 处理时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔬 总疾病数: {len(results)}")
        print(f"✅ 成功处理: {len(successful)}")
        print(f"❌ 处理失败: {len(failed)}")

        if successful:
            total_pmc_ids = sum(r['pmc_ids_found'] for r in successful)
            total_articles = sum(r['articles_downloaded'] for r in successful)
            total_time = sum(r['processing_time'] for r in successful)

            print(f"📊 找到PMC ID: {total_pmc_ids}")
            print(f"📄 下载全文: {total_articles}")
            print(f"⏱️  总用时: {total_time:.1f} 秒")

        if failed:
            print(f"\n❌ 失败的疾病:")
            for result in failed[:5]:
                print(f"   - {result['disease']}: {result.get('error', 'Unknown error')}")

        print(f"\n📁 数据保存在: {self.base_dir}")
        print("="*80)


def main():
    """主函数示例"""
    print("🧬 优化版PMC全文下载器示例")
    print("="*50)

    # 配置（基于原脚本优化）
    config = OptimizedPMCConfig(
        email="1666526339@qq.com",
        api_key="f7f3e5ffa36e0446a4a3c6540d8fa7e72808",
        output_dir="optimized_pmc_test",

        # 下载参数
        batch_size=200,  # 每批200篇文章
        disease_batch_size=3,  # 每批处理3个疾病
        max_records_per_search=10000,

        # 解析选项
        save_parsed_json=True,
        save_raw_xml=True,
        parse_detailed_content=True
    )

    print(f"📧 邮箱: {config.email}")
    print(f"📁 输出目录: {config.output_dir}")
    print(f"📄 批次大小: {config.batch_size} 篇/批")

    # 加载疾病列表
    disease_file = "/Users/xiong/Documents/github/rare-disease-knowledge-graph/all_rare_disease_names.txt"
    with open(disease_file, 'r', encoding='utf-8') as f:
        all_diseases = [line.strip() for line in f if line.strip()]

    # 选择3个疾病测试
    test_diseases = all_diseases[:3]

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
        # 初始化下载器
        downloader = OptimizedPMCDownloader(config)

        # 执行下载
        results = downloader.process_diseases_batch(test_diseases)

        print(f"\n🎉 示例完成！")
        print(f"💡 如需处理更多疾病，请修改 main() 函数中的 test_diseases")

    except KeyboardInterrupt:
        print(f"\n⚠️ 用户中断下载")
    except Exception as e:
        print(f"\n❌ 下载过程出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()