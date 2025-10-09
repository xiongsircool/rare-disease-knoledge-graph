"""
罕见疾病文献下载模块
支持PubMed摘要和PMC全文下载
"""

from .pubmed_downloader import PubMedDownloader, PubMedConfig
from .optimized_pmc_downloader import OptimizedPMCDownloader, OptimizedPMCConfig
from .literature_manager import LiteratureManager, LiteratureConfig

__version__ = "1.0.0"
__all__ = ["PubMedDownloader", "PubMedConfig", "OptimizedPMCDownloader", "OptimizedPMCConfig", "LiteratureManager", "LiteratureConfig"]