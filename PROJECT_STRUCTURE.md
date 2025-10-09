# 罕见疾病文献下载项目结构

## 📁 核心文件结构

```
rare-disease-knowledge-graph/
├── 📄 download_literature.py          # 🎯 主要使用入口脚本
├── 📄 all_rare_disease_names.txt     # 📋 罕见疾病列表（20,269个）
├── 📄 requirements.txt               # 📦 Python依赖
├── 📄 README.md                      # 项目说明
├── 📄 CLAUDE.md                      # Claude配置
└── 📁 src/                           # 💻 核心代码
    └── 📁 literature_downloader/       # 📚 文献下载模块
        ├── __init__.py
        ├── pubmed_downloader.py        # PubMed摘要下载
        ├── pmc_downloader.py           # PMC全文下载（基础版）
        ├── enhanced_pmc_downloader.py   # PMC全文下载（增强版）
        ├── optimized_pmc_downloader.py # PMC全文下载（优化版）
        └── literature_manager.py       # 统一管理器
```

## 🚀 使用方法

### 1. 运行下载脚本
```bash
python download_literature.py
```

### 2. 选择下载模式
- `1` - 🧪 快速测试（3个疾病，PubMed+PMC）
- `2` - 📄 仅PubMed摘要测试（5个疾病）
- `3` - 📚 仅PMC全文测试（3个疾病）
- `4` - 🔬 增强型PMC全文测试（3个疾病，详细解析）
- `5` - ⚡ 优化版PMC批量下载（基于原脚本，高性能）
- `6` - 🚀 批量下载（20个疾病，PubMed+PMC）

## 📊 下载器版本说明

### 📄 PubMed摘要下载器
- **功能**: 下载PubMed摘要和元数据
- **特点**: 提取PMCID、DOI、作者等信息
- **输出**: JSON + CSV格式

### 📚 PMC全文下载器（3个版本）

#### 1. 基础版 (pmc_downloader.py)
- 简单的PMC全文下载
- 基本的内容解析

#### 2. 增强版 (enhanced_pmc_downloader.py)
- 详细的内容解析
- 图表、表格、参考文献提取
- 结构化数据存储

#### 3. 优化版 (optimized_pmc_downloader.py)
- 基于你原有脚本的核心逻辑
- 高效的批量下载机制
- 稳定的错误处理

## 💾 输出数据格式

### PubMed摘要数据
```json
{
  "pmid": "12345678",
  "pmcid": "PMC1234567",
  "title": "文章标题",
  "abstract": "摘要内容",
  "authors": ["作者1", "作者2"],
  "doi": "10.1234/example",
  "disease": "疾病名称"
}
```

### PMC全文数据
```json
{
  "pmc_id": "PMC1234567",
  "pmid": "12345678",
  "title": "文章标题",
  "abstract": "摘要内容",
  "full_text": "全文内容",
  "figure_info_list": [...],
  "table_list": [...],
  "reference_list": [...],
  "disease": "疾病名称"
}
```

## ⚙️ 配置说明

### 邮箱配置
在 `download_literature.py` 中修改：
```python
email = "your_email@example.com"  # 替换为你的邮箱
```

### API Key（可选）
如需提高下载速度，可申请NCBI API Key：
1. 访问 https://www.ncbi.nlm.nih.gov/account/
2. 创建API Key
3. 在脚本中配置

## 🔧 扩展使用

### 处理更多疾病
修改 `download_literature.py` 中的测试疾病数量：
```python
test_diseases = all_diseases[:50]  # 处理前50个疾病
```

### 调整下载参数
```python
# 在相应配置类中调整
batch_size = 1000          # 每批处理的文章数
disease_batch_size = 10   # 每批处理的疾病数
max_workers = 3          # 并发线程数
```

## 📊 项目特点

✅ **支持双数据源**: PubMed摘要 + PMC全文
✅ **智能检索策略**: 针对罕见疾病优化的检索式
✅ **批量处理能力**: 支持大规模文献下载
✅ **完整数据解析**: 提取结构化内容
✅ **错误处理机制**: 稳定的重试和容错
✅ **多种输出格式**: JSON + CSV + XML
✅ **易于扩展**: 模块化设计，便于定制