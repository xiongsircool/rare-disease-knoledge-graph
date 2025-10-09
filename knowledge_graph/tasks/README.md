# 知识图谱构建任务目录

这个目录包含了为构建罕见疾病知识图谱而设计的各种任务脚本。

## 📁 目录结构

```
knowledge_graph/
├── tasks/                       # 任务脚本
│   ├── download_all_literature.py    # 全量文献下载脚本
│   └── README.md                      # 本文件
├── data/                        # 数据存储目录
│   └── literature/                  # 下载的文献数据
│       ├── PMC_full_text/           # PMC全文
│       ├── metadata/                # 元数据
│       └── reports/                 # 统计报告
└── notebooks/                    # Jupyter notebooks (未来)
```

## 🚀 当前可用脚本

### 1. download_all_literature.py - 全量文献下载

**功能**: 下载所有罕见疾病相关的PMC全文文献并生成统计报告

**特点**:
- 基于修复后的PMC下载器，检索成功率大幅提升
- 支持自定义处理疾病数量
- 实时进度显示和统计
- 详细的JSON格式统计报告
- 错误处理和中断恢复

**使用方法**:
```bash
cd knowledge_graph/tasks
python download_all_literature.py
```

**输出**:
- PMC全文XML文件
- 解析后的JSON数据
- 详细的统计报告

## 📊 输出文件说明

### 文献数据
- **PMC_full_text/**: 原始XML文件和解析后的JSON文件
- **metadata/**: 下载元数据和统计信息

### 统计报告
- **download_report_YYYYMMDD_HHMMSS.json**: 包含以下信息：
  - 总体统计（疾病数量、成功率、文献数量等）
  - 每个疾病的详细统计
  - 处理时间和性能指标

## 💡 使用建议

### 测试运行
- 建议先运行 50-100 个疾病进行测试
- 检查下载质量和统计报告

### 生产运行
- 可以处理全部 20,269 个罕见疾病
- 预计需要较长时间（数小时到数天）
- 建议在服务器环境中运行

### 性能优化
- 使用NCBI API key可以提高下载速度
- 可以调整批次大小来平衡内存使用和性能
- 网络状况会影响下载速度

## 🔧 配置选项

可以在脚本中调整以下参数：
- `batch_size`: 每批下载的文章数
- `disease_batch_size`: 每批处理的疾病数
- `sleep_time`: 请求间隔时间
- `max_retry`: 最大重试次数

## 📈 统计报告示例

```json
{
  "summary": {
    "total_diseases": 100,
    "successful_retrievals": 85,
    "success_rate": 85.0,
    "total_pmc_ids": 2543,
    "total_articles_downloaded": 2543,
    "avg_articles_per_disease": 25.4,
    "duration_formatted": "2.5 小时"
  }
}
```

## 🚨 注意事项

1. **网络要求**: 需要稳定的网络连接
2. **存储空间**: 全量下载可能需要数十GB空间
3. **运行时间**: 全量下载可能需要数小时到数天
4. **API限制**: NCBI有请求频率限制

## 📝 未来计划

- [ ] 增加PubMed摘要下载
- [ ] 添加增量下载功能
- [ ] 集成文献解析和分析功能
- [ ] 添加知识图谱构建脚本
- [ ] 创建可视化dashboard