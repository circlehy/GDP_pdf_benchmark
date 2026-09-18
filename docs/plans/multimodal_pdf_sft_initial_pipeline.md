# 多模态 PDF SFT Initial Pipeline：完整执行计划

更新日期：2026-09-17  
状态：V0.2 Source of Truth；目标模型输入协议已冻结，代码迁移待实施  
适用范围：Golden V0、Training Pilot V0，以及后续 10B 扩展前的设计约束

## 0. 执行摘要

项目目标是生成接近或高于 GDP.pdf benchmark 难度的多模态 PDF SFT 数据。训练模型将能够同时理解页面图像和文本，因此不会跳过图表、工程图、地图、表格、表单或二维空间关系任务。

Initial Pipeline 的核心路线是：

```text
真实且可授权的专业 PDF
→ 页面图像、文本和版面解析
→ 先选择多处证据，再设计多步任务
→ 生成可核验答案、evidence graph 和 atomic rubric
→ 正确性验证
→ GDP-like 结构准入与难度校准
→ 多模态 SFT 导出
→ Base / Control / Treatment 对照训练
→ GDP.pdf、补充 benchmark 和内部 holdout 评测
→ 根据失败分片修正 generator prompt 与数据配比
```

V0.2 冻结以下目标模型输入决策：

- 原始 PDF 是数据源和审计资产，不是本地模型直接消费的 tensor；
- 完整文本统一由固定版本 `LiteParse 2.5.0` 生成，开启英文 OCR；
- 页面视觉输入是按页码排列的**完整页面渲染图**，不是由 evidence graph 选择的图表裁剪；
- 支持 `text_only` 与 `multimodal` 两种目标输入 profile，pipeline 默认使用 `multimodal`；
- 默认以完整 PDF 为训练文档；`text_only` 输入为问题和文档视图内每一页的完整提取文本；
- `multimodal` 输入为文档视图内全部完整页面图像、问题和相同页面的完整提取文本；
- generator、verifier、difficulty solver、训练和评测应看到同一种 target-visible input package；
- OpenAI 原生 PDF 输入仅作为可选对照或故障诊断，不再是标准生成链路；
- 不再划分长度桶；对 512K 上下文采用动态预算，输入默认目标约为窗口的 80%，完整序列必须不超过窗口；
- 超长 PDF 必须在问题和答案生成**之前**冻结按完整页面或完整章节组成的 bounded document view，之后禁止训练时静默截断。

V0 先追求一个正确、困难、可追溯的闭环，不直接追求 10B。第一阶段使用 20–50 份 PDF 生成约 500 个候选，保留约 100–200 个高质量任务；第二阶段扩展到 2,000–5,000 份 PDF 和 20,000–40,000 个任务，进行第一次对照训练。

关键决策：

- GDP.pdf 是主要任务设计和评测依据，其他 benchmark 只补充操作模板和能力切片。
- GDP.pdf 的文档、问题、rubric、reference answer、模型回答及其改写均不进入训练数据或 generator 上下文。
- 难度必须来自多处证据、多步依赖操作和控制性信息，不能来自问题歧义、缺页或 OCR 错误。
- Gold 正确性不能由“强模型也答不出”证明，必须通过 evidence、计算、独立重建、rubric 单元测试和人工抽检验证。
- 不使用 Claude API；只接入 OpenAI API 和本地 served 模型。
- OpenAI 强模型用于 Golden V0、prompt 调整和分层审计，不在 10B 阶段逐样本调用。
- Initial 实现采用轻量 Python CLI 和文件化产物；OpenCode/Codex 可辅助开发，但不是生产 pipeline 框架。

### 0.1 目标输入 profile

```yaml
target_input:
  profile: text_only | multimodal
  extractor:
    name: liteparse
    version: "2.5.0"
    ocr_enabled: true
    ocr_language: eng
  page_images:
    renderer: pymupdf
    dpi: 150
    minimum_dpi: 72
    include: all_pages
    packing: single_page
  evidence_graph_in_prompt: false

context_budget:
  model_context_tokens: 524288
  target_input_utilization: 0.80
  preferred_input_utilization_range: [0.70, 0.85]
  maximum_input_utilization: 0.90
  minimum_output_and_safety_reserve_tokens: 32768
```

两个 profile 的逻辑序列为：

```text
text_only
  = task question
  + training document view 的 LiteParse 完整逐页文本

multimodal
  = training document view 的第 1 页完整图像 ... 第 N 页完整图像
  + task question
  + 同一 document view 的 LiteParse 完整逐页文本
```

顺序参照 Artificial Analysis 的 GDP.pdf 实现。训练框架若要求特殊 image placeholder，可以改变物理序列化格式，但不得改变可见信息集合。最困难的标准样本不提供 evidence graph、关键页提示、关键区域裁剪或推理步骤。

Canonical 资产始终是一页一图。只有模型接口存在硬性图片数量限制时，delivery adapter 才可以像 AA 一样把 2–4 个**完整页面**合成带清晰页码的 composite image；这不是图表裁剪，也不得遗漏后续页面。默认本地训练使用 `single_page`，避免无必要地降低小字、图表和工程图细节。

`training_document_view` 默认覆盖完整 PDF。只有完整输入无法在动态上下文预算内安全容纳时，才从原 PDF 派生 `scope=bounded` 的视图。该视图必须先冻结，再生成问题、gold 和 evidence graph；因此不存在“已经生成了依赖后续页面的问题，再把后续页面截掉”的情况。

这里对“最终数据里的文档是完整文档”作如下精确定义：`scope=full_pdf` 时保存并输入完整原 PDF；`scope=bounded` 时，最终样本保存并输入完整、不可再裁剪的 document view，同时在 provenance 中明确它来自原 PDF 的哪些页，不能把 bounded view 伪装成完整原 PDF。

同一道 task 可以声明一个或多个 `supported_input_profiles`：

- 纯文本证据足够的题可以导出 `text_only`，也可以在受控实验中导出 `multimodal` 变体；
- 决定性证据来自图表、空间关系、工程图或视觉布局的题只能导出 `multimodal`；
- 不允许把视觉题强行导出为 `text_only`，否则模型面对的是不可回答输入，会制造错误监督；
- 两种变体共享 `task_id` 和 gold，使用不同 `sample_id`，训练混合时按 `task_id` 去重或限权，避免同一道题重复支配 token。

Golden V0 的生成调用预算先按 `multimodal 75%–85%`、`text_only 15%–25%` 作为软范围，呼应视觉/复杂结构任务占比更高、纯正文任务占比更低的目标；最终训练 token 占比以实际 tokenizer 统计为准，不按任务条数硬凑。`primary_evidence_type` 与 input profile 不是同一维度：例如复杂表格任务既可能从 LiteParse 结构中完成，也可能必须依赖页面布局，应以决定性证据是否在 text-only package 中可见来判定。

## 1. 项目目标、成功条件与非目标

### 1.1 最终目标

构建约 10B `total_sequence_tokens` 的多模态 PDF SFT 数据，使下一代模型在以下能力上获得可测量提升：

- 图像、图表、地图、工程图和空间关系理解；
- 表格、表单、多栏、层级、脚注和复杂版面理解；
- 跨页检索、交叉引用、比较、核对和版本判断；
- 多步计算、筛选、排序、集合运算和专业结论生成；
- 对证据缺失、遮挡或不支持的问题正确 abstain；
- 用简洁、完整、可由原文档验证的方式回答。

### 1.2 Initial Pipeline 的成功条件

V0 成功不等于生成很多数据，而是证明以下闭环成立：

```text
来源合法可追溯
+ 输入确实包含完整多模态证据
+ task 满足 GDP-like 多步结构
+ gold 可被独立复现
+ rubric 可以稳定区分正确与典型错误
+ 数据可直接进入训练
+ Treatment 相比等 token Control 有可解释增益
```

### 1.3 非目标

V0 暂不建设：

- 全量 10B 分布式生产系统；
- 复杂在线微服务或多人标注平台；
- 对所有样本进行多个昂贵强模型的重复试答；
- 一开始训练自动 difficulty predictor；
- 自动解决所有许可证和第三方素材问题；
- 为了凑数量保留简单、歧义或错误任务。

## 2. 设计依据：以 GDP.pdf 为主

### 2.1 从 GDP.pdf 继承的原则

GDP.pdf 面向真实专业 PDF，任务来自真实工作场景，并使用多条 atomic rubric 判断回答是否完整完成。我们继承：

- 文档依赖与专业真实性；
- 原始页面视觉和文本的联合输入；
- correctness、grounding、spatial awareness；
- semantic reading flow、typographic hierarchy、table/chart understanding；
- complex multi-page tables、cross-referencing、artifact/noise 和 unsupported queries；
- Primary Intent 与 Dodged Bullet 类型的原子标准；
- All-pass 和 Mean Pass 两类互补指标；
- 用强模型失败分析校准困难度。

不直接继承：

- GDP.pdf 公开 100 题的领域或模态比例；
- “两个 frontier 模型失败”作为 10B 全量逐样本门槛；
- benchmark 文档、问题或答案本身。

GDP.pdf 是偏难、偏对抗性的测试集。我们复现其高难任务机制，但实际训练混合比例由训练反馈决定。

### 2.2 与 Artificial Analysis 评测的关系

最终评测借鉴 AA：

- 每题进行 5 次独立尝试；
- 每条 criterion 单独做二元 Pass/Fail；
- `All-pass` 衡量一次回答是否通过该题全部 criterion；
- `Mean Pass` 衡量每题 criterion 平均完成程度，再对任务做 macro average；
- 同时报告重复稳定性，不能只报告最好一次。

生产阶段不机械运行 5 次；Golden V0 通常单次试答，最终 golden、随机审计和异常样本可运行 3 次。正式训练效果评测再使用 5 次。

### 2.3 补充 benchmark 的边界

其他 benchmark 只补充模板，不取代 GDP.pdf：

| Benchmark | 可补充内容 |
|---|---|
| MMLongBench-Doc | 长文档、多页证据和跨页检索 |
| TAT-QA / FinQA | 表格与正文联合数值推理 |
| ChartQAPro / CharXiv | 复杂图表、视觉读数和假设推理 |
| DUDE / MP-DocVQA | 多页文档问答和证据定位 |
| OmniDocBench | 阅读顺序、表格、公式和 bbox 解析质量 |

任何补充模板仍必须通过本计划的 GDP-like 结构准入。

## 3. 数据范围与初始软配额

### 3.1 主证据类型

| `primary_evidence_type` | Initial 软配额 | 内容 |
|---|---:|---|
| `visual_spatial` | 40% | 图表、地图、工程图、照片、图例、箭头、对象位置和空间对应 |
| `structured_layout` | 45% | 复杂表格、表单、财务报表、多栏、合并表头、脚注和字段绑定 |
| `text_reasoning` | 15% | 长正文、跨页条款、定义、修订、比较和专业推理 |

这是根据训练需求设置的起始比例，不是 GDP.pdf 官方比例，也不是硬配额。任务可以多标签，统计时只使用一个主证据类型。若某类难以生成正确任务，宁可少产，不为配额降低质量。

### 3.2 能力标签

建议至少支持：

```text
visual_spatial_grounding
chart_reasoning
diagram_legend_binding
standard_table
complex_multi_page_table
form_field_binding
semantic_reading_order
typographic_hierarchy
cross_reference
cross_page_retrieval
calculation
comparison
reconciliation
filter_sort_set_operation
definition_exception
version_supersession
artifact_noise
unsupported_abstention
```

每条高难任务至少覆盖一个 GDP Tier 2 轴和一个 Tier 3 轴；Tier 1 正确性与 grounding 是所有任务的基础，不能单独作为困难来源。

## 4. 数据源计划

### 4.1 Golden V0：从一个最容易控制的来源开始

首选 NASA Technical Reports Server（NTRS）中的公开技术报告：

- 专业性强，包含图表、示意图、表格、公式和跨章节引用；
- 来源和元数据集中，易于发现、下载和保存 provenance；
- 能同时覆盖视觉、结构和正文任务；
- 仍需逐文档检查 rights、distribution、第三方图片、承包商内容和标识限制。

Golden V0 只选 20–50 份：

- 可公开访问完整 PDF；
- 英文优先，后续再扩语言；
- 约 10–150 页，避免初期极端长度；
- 至少具有图表、表格、图例、复杂版面或跨页引用中的两类；
- 无访问控制、敏感信息或明显第三方受限素材；
- 文档间主题不要高度重复。

NASA 内容通常有较宽松的使用条件，但不能把“政府网站上的文件”自动等同于整份文件无任何第三方权利。每份 PDF 仍须保存权利依据和审查结果。

### 4.2 后续来源优先级

1. 其他授权清晰的美国联邦机构技术报告、手册和 GovInfo 文档；
2. 明确标注 CC BY、CC BY-SA、CC0 或兼容许可的研究与技术 PDF；
3. 政府开放数据门户中的地图、规划、统计和工程报告；
4. 许可证可逐文档确认的公司报告、标准或行业文档；
5. Keenable 搜索发现的长尾专业 PDF。

以下来源不在 V0 默认白名单：

- 只有“公开下载”但没有训练/再利用依据的 PDF；
- 付费标准、教材、商业报告和受限数据库；
- 用户隐私、医疗记录、内部文件或含个人敏感信息的材料；
- benchmark 测试文档及其近似副本；
- 无法确定第三方图片、图表或附录权利的文档。

### 4.3 Keenable 的角色

Keenable 只负责发现和网页元数据提取，不替代：

- 原始 PDF 下载；
- PDF 内容解析；
- license 审查；
- benchmark 污染检查。

搜索请求采用中心化 dispatcher，执行统一限速、缓存、重试和去重；不要从大量 Slurm array task 同时直接调用 Keenable。每条搜索结果记录 query、URL、发现时间、来源域名、snippet 和原始响应路径。

### 4.4 权利与污染门槛

每份文档必须包含：

```json
{
  "source_url": "...",
  "publisher": "...",
  "retrieved_at": "...",
  "content_sha256": "...",
  "license_status": "approved | rejected | needs_review",
  "license_id": "...",
  "license_evidence_url": "...",
  "third_party_material_status": "none | cleared | excluded | needs_review",
  "review_notes": "..."
}
```

只有 `approved` 可进入生成。建立 GDP.pdf 和所有外部评测集的文档 hash、标题、URL、文本 fingerprint、图像 fingerprint 和 prompt 语义 denylist，训练前再次扫描。

## 5. 技术框架与系统架构

### 5.1 V0 推荐栈

| 层 | V0 选择 | 原因 |
|---|---|---|
| 编排 | Python CLI + 可重入 stage | 最简单，容易调试和重跑 |
| Schema | Pydantic + JSON Schema | 严格校验模型结构化输出 |
| 元数据 | JSONL/Parquet + DuckDB | 文件化、可查询、无需先部署数据库 |
| PDF 文本提取 | LiteParse 2.5.0 + English OCR | 与 AA 的 GDP.pdf 文本交付口径对齐，产出完整逐页文本 |
| 页面渲染 | PyMuPDF，150 DPI | 只负责稳定渲染完整页面和读取基础 PDF 元数据，不再作为主文本 extractor |
| 文档 IR | 版本化 JSON + 文本文件 + 页面图像 manifest | 将 parser 输出、页边界、页面图片和 token 统计解耦于具体训练格式 |
| LLM API | OpenAI SDK/Responses API + OpenAI-compatible 本地 endpoint | 一个客户端抽象两类服务 |
| 本地推理 | vLLM 或 SGLang，先按候选模型兼容性 bake-off | 提供 batching、GPU 服务和兼容 API |
| 计算验证 | Python 受限表达式/专用函数 | 确定性复算数值和集合题 |
| 集群 | Slurm job array | 解析、渲染、本地推理等离线并行 |
| 日志 | JSONL run events + manifest | 可追踪、可重放、便于统计成本 |

OpenCode/Codex 适合协助编写代码、检查 prompt 和分析失败，不负责生产调度、状态持久化或数据 lineage。V0 暂不需要 LangGraph、Dagster 或复杂 agent framework。进入百万级任务后，再视失败恢复与观测需求引入 Ray、工作流引擎或队列。

### 5.2 目录约定

```text
configs/
  sources/
  models/
  prompts/
  runs/
data/
  discovery/
  documents/
  generated/
  validated/
  exports/
raw_pdfs/
parsed/<document_id>/
  document.json
  liteparse.txt
  pages.jsonl
  page_0001.png
  ...
logs/
  api/
  stages/
  difficulty/
reports/
  golden_v0/
  training_pilot_v0/
```

每个 stage 都读取 manifest、写新产物，不原地覆盖上游文件。产物包含 `schema_version`、`run_id`、代码版本、配置 hash、prompt 版本和模型 snapshot。

### 5.3 八阶段架构

```text
1. discover
2. ingest
3. parse
4. build_document_view_and_input
5. generate
6. verify
7. difficulty_gate
8. export_and_evaluate
```

CLI 目标形态：

```bash
python -m pdf_sft discover --config configs/runs/golden_v0.yaml
python -m pdf_sft ingest --run golden_v0
python -m pdf_sft parse --run golden_v0
python -m pdf_sft build-input --run golden_v0 --profile multimodal
python -m pdf_sft generate --run golden_v0
python -m pdf_sft verify --run golden_v0
python -m pdf_sft difficulty-gate --run golden_v0
python -m pdf_sft export --run golden_v0
python -m pdf_sft report --run golden_v0
```

每一步必须满足幂等、可断点续跑、按 `document_id`/`sample_id` 重试、失败原因落盘，以及 dry-run 小样本模式。

`parse` 只建立与任务无关的 canonical document IR；`build-input` 先决定使用完整 PDF 还是 bounded document view，再按目标模型 profile 序列化输入并调用目标 tokenizer/vision processor 计数。这样同一份解析结果可以生成纯文本和多模态数据，而不重复 OCR 和页面渲染。

### 5.4 Canonical document IR 与 target-visible package

Canonical IR 每个页面至少保存：

```json
{
  "page_number": 1,
  "extracted_text": "...",
  "image_path": "page_0001.png",
  "width_points": 612,
  "height_points": 792,
  "parser": "liteparse",
  "parser_version": "2.5.0",
  "ocr_enabled": true,
  "ocr_language": "eng"
}
```

布局 block、bbox、表格结构和图片对象可以作为辅助字段保留，但 LiteParse/PyMuPDF 的输出不是 evidence graph。Evidence graph 是针对某一道题生成并验证的任务级 sidecar。

`build-input` 为每份文档产生不可变 manifest：

```json
{
  "document_id": "sha256:...",
  "document_view_id": "sha256:...:full",
  "document_scope": "full_pdf",
  "source_page_count": 48,
  "included_page_ranges": [[1, 48]],
  "input_profile": "multimodal",
  "question_position": "after_page_images_before_full_text",
  "complete_text_included": true,
  "page_image_coverage": "all_pages",
  "page_image_dpi": 150,
  "silent_truncation": false,
  "input_tokens": 310000,
  "input_utilization": 0.591,
  "tokenizer_version": "...",
  "vision_processor_version": "..."
}
```

任何降 DPI、页面合图、bounded view、格式变化或预算决策都必须写入 manifest，不能由 API 或 DataLoader 隐式发生。

## 6. LLM 服务与角色分工

### 6.1 原则

- 不使用 Claude API。
- 不把 generator 的自我确认视为正确性证明。
- 所有模型固定 snapshot、reasoning level、system prompt、采样参数、最大输出和输入预处理。
- 模型名不写死在数据 schema；实际版本写入 run manifest。
- OpenAI 与本地模型必须接收与待导出 profile 等价的 target-visible package；不能让 generator 依赖 OpenAI 私有 PDF parser 才能看到的信息。
- 所有生成使用结构化输出，并做 schema validation 和重试。
- 原始 PDF 仍保留并用于人工审计，但标准 generator 调用不再使用 provider-native PDF input。

### 6.2 Golden V0 的服务角色

| 角色 | 首选服务 | 工作 |
|---|---|---|
| Evidence/Task Generator | OpenAI 当前最强视觉推理模型，高 reasoning | 从明确的 `text_only` 或 `multimodal` target-visible package 中选择证据、设计问题、草拟 gold、rubric 和负例 |
| Independent Verifier | 本地强 VLM + 确定性工具 | 不看 generator 自述，从证据重建答案 |
| Difficulty Solver A | OpenAI 强模型 | 给出能力上限侧的实测难度 |
| Difficulty Solver B | 本地强 VLM | 测量本地模型家族的失败模式 |
| Rubric Judge | OpenAI 强模型，之后评估本地替代 | 逐 criterion 二元判分 |
| Target Base Model | 待训练 checkpoint 或最近似本地模型 | 生成训练前基线和规模化困难信号 |

截至本计划更新日，OpenAI 官方将 GPT-6 Astra 定位为最强复杂推理模型，最新模型支持图像输入。Golden V0 可把 `gpt-6-astra` 高 reasoning 作为强模型候选；成本敏感环节可测试 `gpt-5.6-sol` 或更便宜层级。正式运行前仍需用 20–30 道内部样题比较正确率、格式稳定性、延迟和成本，再冻结版本。

### 6.3 本地 served 模型选择

2026-09 最新候选与部署成本分析见
[`local_multimodal_generator_shortlist_2026-09.md`](../research/local_multimodal_generator_shortlist_2026-09.md)。
shortlist 只作为部署前记录；2026-09-17 已实际部署并对比 Qwen3.8-27B 与
GLM-5.3-Flash，当前 production 候选以本节实测结果为准。

不先凭榜单固定模型。用同一批 30–50 个已人工确认任务做 bake-off：

- 是否支持多图、长上下文和目标分辨率；
- 页面数量增加时是否截断；
- 图表、表格、空间绑定、跨页和 abstention 分片表现；
- JSON schema 遵循率；
- 吞吐、显存、并发和失败恢复；
- vLLM/SGLang 兼容性。

选择一个较强模型作为 verifier/difficulty solver，一个与最终训练目标最接近的 checkpoint
作为 target base。用于 gold 正确性验证时，generator 与 independent verifier 必须来自不同
模型家族；target-base 难度试答可以与其中一个家族相同，但日志必须区分角色。

#### 6.3.1 2026-09-17 本地模型实测

部署配置：

| 模型 | vLLM 配置 | 上下文 | 备注 |
|---|---|---:|---|
| Qwen3.8-27B | 8×H200、TP=8、BF16 权重、FP8 KV cache | 262,144 | 支持 `xhigh/medium/low`；完整页面图像与 LiteParse 全文输入正常 |
| GLM-5.3-Flash | 8×H200、TP=8、FP8 权重、MTP=5 | 1,048,576 | 支持 `max/high/medium/low`；1M KV cache 初始化成功 |

两者均通过健康检查、短文本推理、单页视觉识别和严格 JSON Schema 输出。GLM 冷启动约
22 分钟；服务常驻后不影响单次请求。GLM 的 MTP draft 不接收多模态 embedding，这只会
影响图片请求的 speculative decoding 收益，不改变主模型看到的多模态输入。

同一份 23 页完整多模态 GDP-like 解题测试表明：

| 配置 | 实际输入 token | 输出 token | 耗时 | 结果 |
|---|---:|---:|---:|---|
| Qwen `medium + 8K` | 74,427 | 5,311 | 44.9 s | 有 final，但误读关键图例编号，不可单独生成 gold |
| Qwen `xhigh + 8K` | 74,462 | 8,192 | 69.8 s | reasoning 用尽预算，无 final |
| Qwen `xhigh + 16K` | 74,469 | 14,352 | 112.7 s | 有 final，关键图例 5/6 正确，细图读数仍需核验 |
| GLM `high + 16K` | 88,095 | 16,142 | 77.6 s | 有 final，筛选结论正确，但将关键图点读得过于接近带边 |
| GLM `max + 16K` | 88,095 | 16,384 | 85.2 s | reasoning 用尽预算，无 final |
| GLM `max + 32K` | 88,095 | 32,768 | 144.7 s | 仍无 final，不适合作为批量默认配置 |

将 Figure 15 单页作为聚焦证据再测时，GLM `high` 能正确识别 Lowe/Ohman 为方框 5/6，
并将 Lowe 最低点读为约 0.42±0.01。这说明长文档错误不只是视觉能力不足，也包含证据
定位被完整文档稀释的问题。正确性 verifier 可以在保留完整 input package 的同时使用
sidecar evidence page/crop 做定向复核；标准 difficulty solver 仍必须使用无 hint 的完整输入。

真实 generator prompt 要求一次生成 3 个 task、gold、claims、derivations、evidence graph
和 rubric。初始 prompt 下，Qwen 与 GLM 都出现了 `final_output`、claim 或 derivation 引用不
闭合。加入精确 ID 规则和返回前 self-check 后，结果如下：

| 配置和文档 | 实际 prompt token | completion token | 耗时 | 结构结果 |
|---|---:|---:|---:|---|
| Qwen `xhigh + 24K`，23 页 | 约 75K | 24,576 | 约 194 s | 截断 JSON，无可用 batch |
| Qwen `xhigh + 32K`，23 页 | 75,198 | 29,533 | 232.7 s | schema 3/3；static gate 0/3，含 lookup-only 和 rubric 缺项 |
| GLM `high + 24K`，23 页 | 88,784 | 13,616 | 60.9 s | schema 3/3；本轮未保存完整 batch 做正式独立验证 |
| GLM `high + 24K`，88 页 | 283,074 | 15,599 | 92.3 s | self-check 后 static gate 2/3；余下一条为 derivation/rubric 引用错误 |
| GLM `high + 24K`，99 页 | 320,882 | 12,583 | 108.0 s | schema 3/3、static gate 3/3 |
| GLM `medium + 16K`，23 页 | 88,609 | 16,384 | 99.7 s | reasoning 用尽预算，无 final |
| GLM 正式 run config，23 页 | 88,964 | 14,414 | — | schema/static 3/3，但三题均偏向 text reasoning |

当前冻结建议：

- 默认本地 generator：GLM-5.3-Flash，`reasoning_effort=high`，
  `max_output_tokens=24576`，`temperature=0.1`，`top_p=0.95`；
- Qwen3.8-27B 不作为三候选全量 generator；保留 `xhigh` 用于聚焦视觉复核、困难样本
  抽查和异构模型交叉验证；
- 正确性验证固定使用交叉家族路由：GLM 生成由 Qwen 验证，Qwen 生成由 GLM 验证；
  同一模型家族自验记为 `needs_review`，不得进入 difficulty gate；
- 对应可执行配置为 `configs/runs/local_glm_generate_qwen_verify.yaml` 和
  `configs/runs/local_qwen_generate_glm_verify.yaml`。服务地址只从被 gitignore 的本地环境文件
  读取，运行日志记录实际模型名、reasoning、输出预算和采样参数；
- 模型服务窗口与未来 target 的 512K 窗口分别核算。Qwen verifier 为 262K，因此只能复核
  估算后适配其窗口的完整 package；当前 88/99 页 package 粗估约 287K/326K，不得为了让
  Qwen 接收而临时裁页。Qwen→GLM 可覆盖 Qwen 自己能够生成的输入，GLM→Qwen 的长文档则
  停在 `needs_review`，等待另一异构长上下文 verifier；
- GLM `max`、GLM `medium + 16K` 和 Qwen `xhigh + 24K` 不进入默认生成配置；
- static gate 是强制准入门，不合格 JSON 不进入 verifier；纯引用闭合错误允许一次
  deterministic repair 或带错误信息的结构修复，lookup-only、关键证据断链和缺少控制条件
  的任务直接拒绝或重生成；
- 本轮通过 schema/static gate 只证明格式和结构达到最低要求，不证明 gold 正确，也不证明
  难度已达到 GDP.pdf。所有候选仍需完成独立答案重建、数值复算、claim–evidence 核验、
  bbox/页码检查和人工抽检。

交叉模型验证降低 generator 自我确认和同系列错误相关性，但不等于 ground truth：两种模型
仍可能共同误读模糊图表或接受同一个错误前提。因此 cross-model agreement 只是正确性准入的
一层，不能替代确定性计算器、证据坐标/摘录检查，以及 Golden 阶段的人工抽检。

同一正式 run config 的首条端到端交叉验证中，Qwen 对 GLM 候选的 blind reconstruction
使用 74,698 prompt / 5,194 completion tokens，gold audit 使用 76,599 prompt / 2,085
completion tokens，最终状态为 `passed`。但人工复看仍发现：候选把“Group 1–4 数据不超过
M=0.95”进一步写成“在 M=0.95 没有可靠数据”，这一边界推论并非原句直接蕴含，Qwen audit
没有提出异议。因此 `independent_verifier_status=passed` 后仍保持
`eligible_for_difficulty=false`，直到计算、evidence location 和人工抽检等后续 gate 全部完成。

本轮还观察到候选偏向 `text_reasoning`。40% visual-spatial、45% structured-layout、15%
text-reasoning 的总体配比不能只依赖模型自由采样；generator 调用应显式指定本次所需任务
类型或按类型分队列生成，再由全局调度器控制近似分布。

纯文本 run 的 generator/verifier 不能接收页面图像；否则可能生成只能从视觉信息回答的问题。多模态 run 接收冻结 document view 的全部完整页面图像与相同页面的完整提取文本，不接收 evidence-only 图片包。OpenAI 的 `input_file` 原生 PDF 模式可以用于少量对照，判断显式 LiteParse 路径是否损失信息，但其输出不得直接进入标准难度比较或替代 target-visible 验证。

#### 6.3.2 2026-09-17 Qwen 512K 扩窗服务 checkpoint

本轮在单节点 8×H200、TP=8 上启动第二个 Qwen3.8-27B 服务，保留原生 262K 服务作为
对照。扩窗服务使用静态 YaRN `factor=2.0`、FP8 KV cache、`max_model_len=524288`，served
model name 为 `Qwen3.8-27B-512K`。启动日志确认配置实际生效：KV cache 共约
14,972,111 tokens，满 524,288-token 请求的理论最大并发约 28.56；`/v1/models`、短文本
`xhigh` 推理和严格 JSON Schema 均通过。首次启动的 profile/compile/warmup 约 14 分钟，
其中 FlashInfer kernel 首次编译是主要耗时；服务启动后未观察到 OOM 或 engine error。

真实完整多模态 package 测试结果：

| 测试 | 实际 prompt token | completion token | 墙钟时间 | 结果 |
|---|---:|---:|---:|---|
| 23 页，512K 首轮，`xhigh + 16K` | 74,698 | 3,039 | 33.6 s | Schema 合法、定位正确，但 `reconstructed_answer` 只写引言，漏答全部子问 |
| 23 页，512K 复测，`xhigh + 16K` | 74,698 | 6,375 | 84.4 s* | 完整回答且与 262K baseline 一致；首轮异常不是稳定失败 |
| 88 页，512K，`xhigh + 16K` | 228,818 | 6,251 | 98.8 s | 完整回答，电池配置、尺寸、质量和超限量均与 gold 一致 |
| 99 页，512K 首轮，`xhigh + 16K` | 261,147 | 16,384 | — | HTTP 200、无服务错误，但以 `length` 结束，hidden reasoning 用尽预算，无结构化 final |
| 99 页，512K 复测，`xhigh + 32K` | 261,147 | 9,967 | 120.9 s | 正常返回结构化 final，但关键 Figure 18 读数与 gold 冲突，不能通过正确性 gate |

`*` 23 页复测与 99 页首轮并发执行，不能用于单请求吞吐比较。262K baseline 的同一 23 页
任务为 74,698 prompt / 5,194 completion tokens，并正确完成；因此当前没有证据表明静态 YaRN
在短上下文上稳定回退，但单次漏答说明仍需覆盖性检查和有限重试。

99 页任务虽然 prompt 本身比 262,144 少 997 tokens，但 `261,147 + 16,384` 已超过原生
服务的总上下文限制；使用 32K 输出预算时总请求为 293,915-token budget。因此它是一个真实
需要扩窗 verifier 的 pipeline 场景，而不是把未来 target 的 512K 窗口误当成生成模型窗口。

99 页 32K 复测的结构和服务状态正常，但答案将 Figure 18 的 1-year/10-year 选择读成约
40/240 mil，并将前一失败点读成 20/220 mil；现有 gold 为 150/250 mil，前一失败点为
125/200 mil。该差异必须回到原图人工核验，当前应判为关键视觉读数失败，不能因为请求成功、
`input_complete=true` 或 JSON 合法就接受。它也再次证明：长上下文可运行不等于长文档视觉
答案可靠。

人工查看 150 DPI PDF page 64 后确认 gold 正确：diamond 的相邻点约为 125 mil/0.48 与
150 mil/0.15，triangle 的相邻点约为 200 mil/0.64 与 250 mil/0.14。随后只提供 Figure 18
完整页面进行聚焦复核，Qwen 512K `xhigh + 16K` 使用 2,263 prompt / 6,343 completion
tokens、40.7 秒，正确读出上述四个点。这说明主要问题是长文档证据定位/注意力稀释，而不是
模型完全不会读取该图；完整 package 无 hint 仍用于 difficulty，sidecar evidence page/crop
可用于独立的 gold correctness audit，但后者的成功不能改写前者的难度结果。

据此冻结的下一步配置建议：

- 保留原生 262K 与 512K 两个服务；当前先按安全侧的
  `provisional_input + max_output_tokens` 路由，接入真实 tokenizer/vision processor 后改为
  `actual_prompt + max_output_tokens`，而不是全部请求切到静态 YaRN 服务；
- 适配原生窗口的 verifier 默认继续使用 262K 服务；只有完整 package 加输出预算超出原生
  窗口时才路由到 512K；
- 超长 `xhigh` 请求默认预留 32K 输出；16K 的 `length/no final` 属于服务/预算失败，不计为
  模型解题失败；若 32K 仍持续只消耗 reasoning，再比较 `high + 16K/24K`，不无限加预算；
- 增加 response `finish_reason`、原始 reasoning/content token、空 content 和子问覆盖率检查；
  空 final 或漏答自动进入一次受限重试，仍失败则 `needs_review`；
- `input_complete` 只表示模型自报，不能替代 rubric coverage、数值复算和 evidence-page/crop
  定向视觉复核；99 页 Figure 18 样本保留为扩窗视觉回归用例。

可恢复状态：本轮所有推理请求均已结束，两个 Qwen 服务可以继续独立使用；下一次从
“人工复核 Figure 18 原图 → 为 512K 服务建立隔离 run config → 实现动态路由与 finish/coverage
gate”继续，无需重跑上述请求。

实现状态（同日续跑）：上述三项已经完成。`local_glm_generate_qwen_verify.yaml` 现在按完整
请求预算优先选择原生 262K verifier，超出后选择 512K/32K；
`local_glm_generate_qwen512_verify.yaml` 提供不覆盖原 run 的强制 512K A/B 配置。client 日志
记录 `finish_reason`、reasoning/content 字符数；blind reconstruction 对非 `stop`、空/过短
final 和显式分问漏答最多重试一次，仍失败则 `needs_review`。当前 provisional accounting 的
路由结果为：23 页→262K/16K，88/99 页→512K/32K。真实 CLI 集成 smoke 对第一条 23 页
候选自动选择 `Qwen3.8-27B` 原生服务；reconstruction 使用 74,741 prompt / 3,605 completion，
audit 使用 76,169 prompt / 1,781 completion，二者均为 `finish_reason=stop`，完整性 gate 与
gold audit 通过，最终状态为 `passed`，另外两条候选保持 `not_run`。代码检查为 Ruff clean、
27 tests passed。

Evidence-focused correctness audit 随后接入：blind reconstruction 的输入协议不变，仍为完整
23 页图像与完整文本；audit 才读取候选 sidecar evidence graph，将其节点、bbox、role、excerpt
作为“待核验定位”放入 prompt，并只附加对应的完整证据页。Audit prompt 明确禁止把 graph 当作
ground truth，定位错误、证据不足或与完整文本冲突时必须 dispute/转人工；完整 LiteParse 文本
默认继续提供，`text_only` audit 仍禁止图片输入。首条真实 CLI smoke 的 reconstruction 使用
74,741 prompt tokens；focused audit 只附加 PDF pages 8、10，使用 34,259 prompt / 2,800
completion tokens，核验 `e1–e5` 和 `c1–c5` 后状态为 `passed`。日志保存 audit scope、完整文档
页数、附加页码、DPI 和 evidence node IDs。

随后增加 bbox crop 与确定性坐标门禁。每个 evidence node 从 150 DPI 原始页面按标准化 bbox
裁剪，默认增加 10% padding 且短边至少 256 px；audit 同时接收对应完整页和 crop，并在 prompt
manifest/日志中记录附件顺序、页码、node ID、原始/扩展 bbox、像素尺寸和对齐结果。Crop 是定位
辅助而不是独立事实源，blind reconstruction 与 difficulty solver 的完整无 hint 输入保持不变。

坐标门禁分别计算 excerpt 对整页 LiteParse 文本与 bbox 相交 blocks 的 token coverage。若整页
coverage 足以证明摘录可见，而 bbox coverage 低于相对阈值，则标为 `misaligned`；无 excerpt 或
视觉/OCR-only 证据标为 `not_checkable_*`，不会被错误判成已对齐。任何 `misaligned`/`missing_page`
节点都会强制最终状态为 `needs_review`，即使 VLM 能依赖完整页或完整文本支持 gold。真实首条样本
复测中，Qwen audit 仍给出 `gold_supported=true`、无 disputed claims，但确定性检查发现 `e1`
（page coverage 1.0000 / bbox 0.2857）和 `e5`（0.9167 / 0.0833）错位，最终正确降为
`needs_review`；`e2–e4` 对齐。测试现为 Ruff clean、30 tests passed。

Bbox repair review 随后完成。对每个 `misaligned` 节点，pipeline 在同页 reading-order blocks 中
枚举最多 6 个连续 block 的窗口，以 excerpt token coverage 为主、precision 和窗口长度为辅进行
确定性排序；只有 coverage 与相对原框的 improvement 同时达到阈值才给出 replacement proposal。
建议记录 original/suggested bbox、两侧 coverage、score、confidence 和 matched block IDs，但不
修改候选。`review-pack` 为每条建议保存完整页、原始 crop、建议 crop、依赖 claims、机器可读
`bbox_repair_suggestions.json` 和初始为 `pending` 的 `bbox_repair_decisions.json`；重复生成不会覆盖
已经存在的人工决定文件。

首条真实样本生成两条 high-confidence 建议：`e1` 从 0.2857 提升到 0.8571，定位到
`p8_b23–p8_b27`；`e5` 从 0.0833 提升到 0.8333，定位到 `p10_b3–p10_b7`。人工视觉查看新旧
crop 后确认新框包含对应 Mdd 与 low-supersonic/Eqn. 6 语句，旧框没有。当前仍保持
`mutation_applied=false` 和 verifier `needs_review`；只有 reviewer 接受 decision 后，后续 apply
stage 才能创建修正版 sidecar。测试现为 Ruff clean、31 tests passed。

### 6.4 从 Golden 到规模化的调用变化

Golden V0 可以对全部验证候选调用 OpenAI 强模型和本地强 VLM。Training Pilot 以后使用：

```text
结构规则硬过滤
→ 目标本地模型试答
→ 本地规则或 difficulty predictor
→ 训练候选池
→ OpenAI 只审计分层样本、边界样本和异常样本
```

生产数据分别记录：

- `difficulty_predicted`：由结构特征或本地 predictor 推断；
- `difficulty_verified`：使用固定强模型配置实际测得；
- `difficulty_calibration_version`：阈值对应的校准版本。

## 7. GDP-like 任务生成规范

### 7.1 必要条件

每个高难候选必须同时满足：

1. 仅凭常识、搜索记忆或 prompt 不能回答；
2. 至少两个独立 evidence node，不能是同一句的连续复制；
3. 至少两个有依赖关系的 operation；
4. 至少一个 operation 不是 lookup；
5. 至少一个控制性证据会改变初步答案；
6. 最终答案依赖全部关键节点；
7. 对应真实专业工作动作；
8. Gold 的每个 claim 均可验证；
9. Rubric 能诊断关键遗漏和典型错误。

### 7.2 Evidence graph

允许的节点角色包括：

```text
base_value, comparison_value, label, legend, definition,
qualifier, exception, exclusion, footnote, threshold,
effective_date, superseding_rule, missing_required_evidence
```

允许的操作包括：

```text
lookup, spatial_bind, normalize, join, compare, calculate,
filter, exclude, rank, intersect, aggregate, reconcile,
resolve_scope, supersede, determine_support
```

最小示例：

```json
{
  "nodes": [
    {"id": "e1", "page": 4, "bbox": [0.1, 0.2, 0.8, 0.6], "role": "base_value"},
    {"id": "e2", "page": 9, "bbox": [0.2, 0.3, 0.9, 0.7], "role": "exception"},
    {"id": "e3", "page": 13, "bbox": [0.1, 0.1, 0.7, 0.4], "role": "superseding_rule"}
  ],
  "operations": [
    {"op": "lookup", "inputs": ["e1"], "output": "v1"},
    {"op": "exclude", "inputs": ["v1", "e2"], "output": "v2"},
    {"op": "supersede", "inputs": ["v2", "e3"], "output": "final_claim"}
  ]
}
```

执行 counterfactual deletion test：删除任一关键节点，答案应改变、变得不完整或必须 abstain；否则该节点不是真正依赖，任务需要重写。

### 7.3 推荐任务模板

1. **跨表核对与计算**：基础值 → 系数 → 脚注适用范围 → 计算 → 阈值比较。
2. **图表与正文联合推理**：图例 → 多个视觉点 → 正文定义 → 变化/比较 → 精度说明。
3. **工程图/平面图联合判断**：图例 → 图中定位/计数 → schedule 属性 → 排除 → 完整集合。
4. **条款与例外**：主条款 → 定义 → 排除项 → amendment/endorsement → 控制性结论。
5. **版本与生效范围**：旧规则 → 新修订 → 生效日期/对象 → 例外 → 当前有效结论。
6. **多对象集合操作**：多页候选 → 名称/单位标准化 → 多条件过滤 → 脚注增删 → 排名/交集。
7. **扫描表单空间绑定**：标签 → 二维位置绑定填写值 → 跨区核对身份 → 排除模板/噪声 → 汇总。
8. **Unsupported/受限结论**：相关证据 → 所需字段检查 → 缺失/遮挡判断 → 有限结论 + abstention。

### 7.4 明确拒绝的一步任务

- 从一个句子直接复制答案；
- 读取一个表格单元格；
- 只找标题、姓名、日期或页码；
- 只描述图片或读取一个柱子；
- prompt 已提供全部计算输入；
- 一次关键词搜索即可定位并作答；
- 多页事实只是并列，没有依赖关系；
- 不看 PDF 也能凭常识回答；
- 决定性视觉信息已在 caption 或 prompt 中泄露；
- 因 OCR 缺失、输入截断或问题歧义才变难。

### 7.5 每文档任务数

Golden V0 每份 PDF 先生成 3–10 个候选，但证据高度重叠的题只保留最强的一题。Training Pilot 根据文档复杂度动态设置，不允许少数长 PDF 支配训练 token 或产生大量近似题。

任务数由“可形成多少个低重叠、可验证的证据簇”决定，而不是固定按页数线性增加。建议 V0 默认：

- 10–30 页且结构中等：生成 3–5 个候选；
- 31–100 页或结构丰富：生成 5–8 个候选；
- 超过 100 页：先生成 6–10 个候选，仍按证据重叠和 token 占比限权；
- 同一 PDF 最终保留任务的关键 evidence overlap 过高时，只保留难度和正确性更好的任务；
- 单份文档的最终训练 token 原则上不超过当前数据 shard 的 1%，Golden 小样本阶段单独记录、不强制此比例。

若同一 task 同时导出 text-only 和 multimodal 变体，统计“每文档任务数”时按唯一 `task_id` 计数，token 预算则分别计算两个样本。

## 8. Gold answer 与正确性保证

### 8.1 Gold 输出结构

面向训练的答案应专业、自然、直接，包含：

- 最终结论；
- 使结论可复核的必要数值或对象；
- 控制性条件、例外或版本；
- 简短计算或比较；
- 图表读数的合理精度；
- 证据不足时明确说明缺少什么。

不保存或训练不可验证的自由形式隐藏思维过程。完整证据链保存在 sidecar：

```json
{
  "final_answer": "...",
  "claims": [
    {"claim_id": "c1", "text": "...", "supported_by": ["e1", "e2"]}
  ],
  "derivations": [
    {"result_claim": "c2", "expression": "(v2-v1)/v1", "inputs": ["c1"]}
  ],
  "uncertainty": {
    "type": "chart_reading_precision",
    "statement": "values are approximate"
  }
}
```

### 8.2 五层正确性验证

#### Gate A：输入完整性

- 所有引用页已成功渲染；
- 文本和图片输入未因上下文限制被静默截断；
- bbox 位于正确页面并覆盖目标内容；
- 跨页表头、图例和脚注已进入输入包。

#### Gate B：Claim–evidence coverage

- Gold 每个事实 claim 至少有一个证据节点；
- 每个计算输入均来自证据或明确常量；
- 不允许使用文档外专业常识补齐关键事实；
- 引用的条款必须实际控制结论，而非只“相关”。

#### Gate C：确定性重算

- 数值、百分比、单位换算和排序由程序复算；
- 集合题检查漏项、多报和重复项；
- 版本题检查日期区间与 supersession；
- 对近似图表读数设置显式容差。

#### Gate D：独立重建

Verifier 只看 prompt、页面输入和 evidence 候选，不看 generator 的解释，独立生成答案。比较两者的最终 claim、数值、单位、例外和完整性。分歧进入人工审查，不能通过多数投票自动消解。

#### Gate E：人工审核

Golden V0 对最终保留任务进行高比例、最好全量的人工审核。Training Pilot 采用按来源、模板、模态、generator 版本和困难层分层抽样，并对所有异常样本全审。

模型一致不是正确性的充分条件。两个模型可能同时受到同一解析错误、提示偏差或专业误解影响。

### 8.3 错误分类

```text
missing_input_or_truncation
ambiguous_question
incorrect_gold
unsupported_gold_claim
wrong_evidence_binding
calculation_error
rubric_error
judge_error
format_only
service_error
genuine_reasoning_failure
```

只有 `genuine_reasoning_failure` 可作为困难证据；其余必须修复、重跑或拒绝。

## 9. Rubric 与自动单元测试

### 9.1 Rubric 结构

Rubric 一般为 6–15 条，复杂集合题可更多，但不为了接近 GDP.pdf 平均数填充。每条只判断一个原子事实或错误：

```json
{
  "criterion_id": "r1",
  "criterion": "...",
  "criterion_type": "primary_intent | supporting_detail | dodged_bullet",
  "severity": "certain_dealbreaker | major | minor",
  "implicitness": "explicit | implicit",
  "subjectiveness": "objective | subjective",
  "failure_mode": "binary | scalar",
  "supported_by": ["c1", "e2"]
}
```

必须覆盖：

- 每个关键最终 claim；
- 决定结果的脚注、例外、定义或修订；
- 关键计算和单位；
- 列表/集合完整性；
- 至少一个最可能的 Dodged Bullet；
- unsupported 题的正确 abstention。

### 9.2 Rubric 单元测试

每条 task 自动构造：

```text
gold_answer             → 全部 criterion 通过
missing_evidence_answer → 对应 Primary Intent 失败
plausible_wrong_answer  → 对应 Dodged Bullet 或关键 criterion 失败
```

建议再增加：

```text
wrong_unit_answer
ignored_exception_answer
incomplete_list_answer
unsupported_confident_answer
```

若 judge 无法稳定区分，先修 rubric/judge prompt；不能用该 judge 结果筛选任务。

## 10. 困难度判定与 GDP 相似度

### 10.1 结构准入先于模型失败

模型失败不能挽救一步题、坏题或错误 gold。任务必须先通过第 7 节全部结构规则。

建议计算结构特征：

```text
evidence_node_count
dependent_operation_count
non_lookup_operation_count
page_span
modality_count
controlling_evidence_count
distractor_count
answer_claim_count
rubric_count
```

不使用 PDF 页数作为主要难度代理。一页复杂工程图可以很难，几百页文档中的单字段查找仍可能很简单。

### 10.2 Golden V0 难度校准

对已确认正确的候选，让 OpenAI 强模型和本地强 VLM 在相同输入条件下作答，由 rubric judge 评分。记录：

- All-pass；
- Mean Pass；
- certain-dealbreaker 失败数；
- 失败 criterion 类型；
- 重复试答稳定性；
- 截断、服务和格式错误；
- 人工判定的真实失败原因。

同样配置可对 GDP.pdf 做只读基线评测，以比较任务分片的失败分布。`GDP-like` 表示结构相似；只有经过同配置实测，才能标记为 `difficulty_verified`。

### 10.3 难度层级

| 标签 | V0 定义 |
|---|---|
| `rejected_simple` | 未通过多处证据或多步操作门槛 |
| `valid_unverified` | 正确且结构合格，尚未进行模型难度实测 |
| `hard` | 结构合格，目标本地模型发生关键实质失败 |
| `very_hard` | OpenAI 强模型和本地强 VLM重复试答仍稳定发生关键失败，并已排除坏题 |

“两个强模型都答不出”只用于 Golden 校准和 `very_hard` 标签，不作为 10B 全量成本门槛。

## 11. V0 数据 Schema

生产记录至少包含：

```json
{
  "schema_version": "0.1",
  "sample_id": "pdfsft_000001",
  "document": {
    "document_id": "sha256:...",
    "document_view_id": "sha256:...:full",
    "document_scope": "full_pdf | bounded",
    "source_page_count": 48,
    "included_page_ranges": [[1, 48]],
    "source_url": "https://...",
    "license_status": "approved",
    "license_id": "...",
    "license_evidence_url": "https://...",
    "pdf_path": "raw_pdfs/...pdf",
    "page_images": ["parsed/.../page_0001.png"],
    "parsed_text_path": "parsed/.../document.json",
    "page_count": 48
  },
  "task": {
    "task_id": "task_000001",
    "prompt": "...",
    "domain": "engineering",
    "primary_evidence_type": "visual_spatial",
    "capability_tags": ["cross_page", "diagram_legend_binding", "calculation"],
    "supported_input_profiles": ["multimodal"],
    "requires_visual_evidence": true,
    "gold_answer": "...",
    "claims": [],
    "evidence_graph": {"nodes": [], "operations": []}
  },
  "rubric": [],
  "generation": {
    "generator_model": "...",
    "generator_prompt_version": "...",
    "run_id": "..."
  },
  "validation": {
    "input_complete": true,
    "gold_verified": true,
    "evidence_verified": true,
    "programmatic_checks_passed": true,
    "rubric_unit_tests_passed": true,
    "human_review_status": "approved"
  },
  "difficulty": {
    "structural_gate_passed": true,
    "difficulty_predicted": "hard",
    "difficulty_verified": null,
    "solver_runs": [],
    "failure_reason": null
  },
  "token_accounting": {
    "input_profile": "multimodal",
    "system_tokens": 80,
    "document_text_tokens": 21000,
    "question_tokens": 180,
    "answer_tokens": 620,
    "image_tokens": 9000,
    "total_sequence_tokens": 30800,
    "loss_tokens": 620,
    "context_window_tokens": 524288,
    "input_utilization": 0.0576,
    "total_sequence_utilization": 0.0587,
    "tokenizer_version": "...",
    "vision_processor_version": "...",
    "count_is_estimate": false
  }
}
```

训练 conversation 与 provenance sidecar 分开导出。训练端只消费所需输入与 assistant answer；审计、evidence、rubric、license 和生成日志留在 sidecar。

训练 record 不内嵌重复的 PDF 或页面图像二进制，而是引用不可变 `document_id`、IR manifest 和 image refs；DataLoader 在训练时解析引用。发布数据集时应提供可物化的 self-contained manifest，避免依赖易失绝对路径。

## 12. 八阶段详细执行

### Stage 1：Discover

输入：source allowlist、Keenable queries。  
输出：`data/discovery/document_candidates.jsonl`。

执行：

- 首轮只检索 NTRS 或单一官方来源；
- 保存原始搜索响应；
- URL canonicalization 和初步去重；
- 基于标题、页数和 snippet 做复杂度预筛；
- 只把可能含图表、表格、图纸或跨页引用的文档送入 ingest。

### Stage 2：Ingest

输入：候选 URL。  
输出：`raw_pdfs/`、`data/documents/documents.jsonl`。

执行：

- 下载 PDF，记录 HTTP metadata；
- SHA-256、文件类型、页数和损坏检查；
- 精确 hash、文本 MinHash 和图像 fingerprint 去重；
- license allowlist 与第三方素材检查；
- benchmark denylist 检查；
- 失败原因落盘。

### Stage 3：Parse

输入：approved PDF。  
输出：LiteParse 完整逐页文本、150 DPI 完整页面 PNG 和 `parsed/<document_id>/document.json`。

执行：

- 使用固定版本 LiteParse 2.5.0，开启 English OCR，生成完整文本并保留页边界；
- 使用 PyMuPDF 固定 150 DPI 渲染每一个完整页面；
- PyMuPDF 原生文本仅用于诊断、差异检查和基础元数据，不作为标准训练文本；
- 可选保存 block、bbox、字体与阅读顺序，供证据候选和核验使用；
- 标记表格、图表、图片、公式、脚注和多栏；
- 生成页面缩略图与视觉密度指标；
- 识别候选跨页表格、图例引用和章节引用；
- 抽样对比页面图像与 LiteParse 文本，记录 parser、OCR 和 renderer 版本；
- 检查页数一致、空页、OCR 异常、字符乱码和页面渲染失败。

V0 不要求完美重建文档。`multimodal` 模型始终可以看到冻结 document view 内每一页的完整页面图像；`text_only` 模型只能看到相同 view 的 LiteParse 完整文本，因此 text-only task 必须额外通过“答案可由提取文本支持”的可见性 gate。

### Stage 4：Build Document View and Input

输入：canonical document IR、目标模型 tokenizer/vision processor、run profile 和上下文预算。  
输出：冻结的 `document_view`、`data/input_packages/<profile>/` 和 provisional token accounting。

执行：

1. 先尝试以完整 PDF 组装 target-visible package；
2. `text_only` 不加载页面图像，`multimodal` 加载所有完整页面图像；
3. 使用最终训练模型 tokenizer 和 vision processor 统计 system、文档文本、视觉 token、分隔符以及问题/答案预留；
4. 输入利用率约 70%–85% 时直接保留完整 PDF，80% 是默认目标而不是必须填满的配额；
5. 完整 PDF 略高于 85% 时，如果实际答案预算和至少 32K 安全余量仍满足，可以动态接受到 90%，优先保留完整文档；
6. multimodal 完整 PDF 超出安全预算时，先保持全部页面，按 150→120→96→72 DPI 重建并重新计数；
7. 仍不满足预算，或 text-only 本身过长时，按完整页面、章节或语义边界构造 `scope=bounded` 的 document view；
8. bounded view 目标回到约 70%–85% 输入利用率，并保存原始页数、保留页范围、截断方法和原因；
9. document view 一经冻结，下游 generator、verifier、训练和评测不得再改变页面集合；
10. 将所有适配和预算结果写入 manifest。

这里的“截断”是**生成前的文档视图构建**，不是训练时从 token 尾部直接裁掉。优先使用连续、语义完整的章节或页面范围，不在段落、表格、图、图例、脚注或跨页表格中间切断。若同一道题导出 text-only 和 multimodal 变体，两者必须引用相同 `document_view_id` 和相同页面集合。

80% 只作为软目标。最终硬条件是：

```text
actual_input_tokens
+ actual_answer_tokens
<= 524,288
```

同时满足至少 32K 的配置安全余量或经 Pilot 校准后的等价余量。生成后和 export 时使用实际问题与答案重新精确计数；如果超限，返回本 stage 重新构造视图和重新生成任务，不能只截掉现有样本的尾部。

### Stage 5：Generate

输入：明确 profile 的完整 target-visible package、软配额和 task template。  
输出：`data/generated/candidates.jsonl`。

严格采用“先证据、后问题”：

1. 选定 2 个以上证据节点；
2. 标记控制性证据和 distractor；
3. 设计至少 2 个有依赖关系的操作；
4. 执行 counterfactual deletion test；
5. 生成真实专业 prompt；
6. 生成 gold answer、claims 和 derivations；
7. 生成 atomic rubric；
8. 生成典型错误答案；
9. 标注主证据类型和能力轴；
10. 标注 `supported_input_profiles` 与 `requires_visual_evidence`；
11. 运行 schema validation。

Generator prompt 必须禁止：简单 lookup、文档外事实补齐、答案泄露、无法验证的开放写作题，以及对 benchmark 题目的模仿改写。

V0 为了输入一致性，OpenAI generator 接收显式页面图片与 LiteParse 文本，不再以 `input_file` 直接上传原始 PDF。规模化时可以先用本地索引提出候选证据簇来减少 generator 搜索成本，但最终 task 必须在完整 target-visible package 上做可回答性与正确性验证。

对于 bounded document view，generator 只能在视图冻结后运行，所有 evidence node、计算输入、定义、例外和控制条件必须来自保留页面。默认禁止生成“列出整份原始 PDF 的全部对象”“确认全文不存在某项”等需要被删除页面才能证明的全局穷举题；任务应明确限定在提供的章节、附录、日期范围或文档视图可支持的范围内。

### Stage 6：Verify

输入：候选 task。  
输出：`data/validated/verified.jsonl`、`rejected.jsonl`。

依次运行：

1. 输入完整性；
2. profile 可见性：所有 gold claim 的决定性证据必须存在于该 profile；
3. document-view 完整性：不能在段落、表格、图片、图例、脚注或跨页结构中间切断；
4. omitted-page audit：检查被省略页面是否包含同主题定义、例外、修订、脚注或相反证据；
5. evidence graph 结构校验；
6. claim–evidence coverage；
7. 程序重算；
8. 不同模型家族的 independent verifier 在相同 target-visible package 上盲重建；
9. rubric 原子性与单元测试；
10. prompt 答案泄露检查；
11. 重复/污染检查；
12. Golden 人工复核。

任何 critical gate 失败都不得进入 difficulty gate。

“不截断有用信息”在 pipeline 中定义为：题目作答所需的全部关键和控制性证据都在 document view 内，而且被省略页面不会改变、限定或推翻 gold。它不能仅靠“先截断再生成”自动保证，必须通过 omitted-page audit；审计发现潜在冲突时，扩展视图并重新生成，或拒绝该任务。

### Stage 7：Difficulty Gate

输入：已验证候选。  
输出：`hard.jsonl`、`valid_unverified.jsonl`、`rejected_simple.jsonl` 和 solver logs。

顺序：

```text
GDP-like 结构硬过滤
→ target base 本地试答
→ rubric judge
→ Golden 阶段 OpenAI + 本地强 VLM 校准
→ 失败原因复核
→ 难度标签
```

服务失败、截断或格式错误不计为模型能力失败。对于最终 Golden、随机样本和异常样本运行三次，检查失败是否稳定。

不同 input profile 的难度分数不能直接混用。同一任务在 text-only 和 multimodal 下分别记录 solver run；视觉题若不支持 text-only，则不进行 text-only 难度试答。

### Stage 8：Export and Evaluate

导出：

- 目标训练框架需要的多模态 conversation；
- provenance/evidence/rubric sidecar；
- split manifest；
- token accounting；
- 数据卡与质量报告。

至少导出两个逻辑 dataset view：

```text
exports/text_only/
  user = question + complete LiteParse text of the frozen document view
  assistant = gold answer

exports/multimodal/
  user = all full-page images of the same view + question + its complete LiteParse text
  assistant = gold answer
```

Rubric、evidence graph、claims、derivations、详细推理、验证日志和 difficulty solver 输出只进入 sidecar；除非显式构造 `hint_level > 0` 的课程学习实验，否则不进入标准 user prompt。

Export 必须用实际完整序列重新运行 tokenizer/vision processor，记录最终输入和总序列利用率。若超过上下文硬上限或低于配置安全余量，返回 Stage 4 重建 document view 并重新生成，禁止在 export 或 DataLoader 中临时截断。

同一 document family 不得跨 train、validation 和 internal holdout。按文档 hash、文本近似度和来源系列做 group split。

## 13. 训练与评测设计

### 13.1 对照实验

```text
Base      = 原始 checkpoint
Control   = 相同 total/loss token 的现有通用 SFT
Treatment = 新生成的多模态 PDF SFT
```

三组保持模型、训练步数、学习率、上下文长度、图片策略和其他超参数一致。若训练混合含通用数据，Control 与 Treatment 除 PDF SFT 替换部分外保持一致。

当前纯文本 checkpoint 先运行 `text_only` 对照；未来视觉模块接入后运行 `multimodal` 对照。不能用 text-only Base 与 multimodal Treatment 直接归因 SFT 效果，因为模型架构和可见输入同时发生了变化。

### 13.2 评测集

- GDP.pdf：主独立 benchmark，只用于测试；
- 其他文档 benchmark：用于跨 benchmark 泛化；
- 内部 holdout：按来源和 document family 隔离；
- 通用文本、视觉和安全评测：检查能力回退。

### 13.3 指标

总体：

- All-pass；
- Mean criterion pass；
- 五次运行稳定性；
- 置信区间和按任务 macro average。

质量与能力切片：

- evidence page/region grounding；
- 无依据陈述率；
- 视觉、结构、正文主证据类型；
- 表格、图表、空间关系、跨页、计算、脚注/例外、版本和 abstention；
- 输入长度、页数、证据节点数和操作数；
- 来源、领域和语言；
- 通用能力回归。

只有 Treatment 在相同 token 预算下稳定优于 Control，且没有不可接受的通用能力回退，才能说明新数据有效。

正式 GDP.pdf 评测至少报告输入协议：

- `AA-compatible text-only`：LiteParse 2.5.0 完整文本；
- `AA-compatible multimodal`：完整页面图像 + 问题 + LiteParse 2.5.0 完整文本；
- 如运行 provider-native PDF，只作为单独结果，不与上述结果合并。

## 14. 规模与 10B Token 口径

### 14.1 统一定义

```text
total_sequence_tokens
  = system_tokens
  + document_text_tokens
  + question_tokens
  + answer_tokens
  + image_tokens
```

- 问题和答案都计入 10B；
- 文档文本与视觉 token 也计入，因为它们参与模型前向计算；
- PDF 文件字节数不计作 token；
- `loss_tokens` 单独统计，通常主要来自 assistant answer；
- 视觉 token 必须按最终模型的分辨率、patch 和 tokenizer 策略重算；
- 历史统计保留 `tokenizer_version`，不能被新口径静默覆盖；
- evidence graph、rubric 和验证 sidecar 不进入标准训练序列，因此不计入训练 10B；只有显式 hint 变体实际放入 prompt 时才计入；
- generator/verifier API 的消耗单独记为生产成本，不计入训练数据 10B。

每次发布同时报告：

1. `total_sequence_tokens`；
2. `loss_tokens`；
3. PDF 数、页数、图片数与原始字节数；
4. 按主证据类型、能力标签、领域、来源和难度的 token 分布。

### 14.2 动态上下文预算与超长文档

暂按 `512K = 524,288 tokens` 配置。80% 即约 419K tokens，适合作为输入软目标，但不作为硬切线：完整文档如果占 82%–88%，且实际 gold answer 和安全余量足够，优先保留完整 PDF，而不是为了满足整齐比例进行无必要截断。

```yaml
context_budget:
  model_context_tokens: 524288
  target_input_utilization: 0.80
  preferred_input_utilization_range: [0.70, 0.85]
  maximum_input_utilization: 0.90
  minimum_output_and_safety_reserve_tokens: 32768
  oversized_document_policy: build_bounded_view_before_generation
  runtime_truncation: forbidden
```

预算口径：

```text
input_tokens
  = system_tokens
  + document_text_tokens
  + image_tokens
  + question_tokens
  + special/separator tokens

total_sequence_tokens
  = input_tokens
  + answer_tokens
  <= 524,288
```

动态范围的使用方式：

1. 70%–85% 是常规目标区间，80% 是默认规划点；
2. 低于 70% 不需要填充或拼接无关文档，短文档本身可以保留；
3. 高于 85% 不立即截断，先根据实际答案长度和安全余量判断；
4. 最高通常不超过 90% 输入利用率，为答案、特殊 token、视觉计数误差和训练实现留余量；
5. Gold answer 较长、视觉 tokenizer 波动较大或训练框架需要额外 token 时，单样本上限应自动下调；
6. Pilot 后使用问题长度、答案长度和视觉 token 误差的 P99 重新校准，而不是永久写死 80%。

超长文档处理：

1. 完整 PDF 优先；
2. multimodal 先保持全部页面并降低页面图片 DPI；
3. 仍过长时，在任务生成前构造 bounded document view；
4. 视图按整页和语义边界切分，可产生多个互不重叠或低重叠视图，但每个视图独立生成任务；
5. 不根据已经生成的 evidence graph 反向裁剪页面；
6. 问题、答案、rubric 和 evidence graph 全部在视图冻结之后生成；
7. omitted-page audit 检查被删除内容是否会改变答案；
8. 最终训练 record 保存完整的冻结视图以及与之对应的全部页面图像和文本；
9. 发布报告同时列出 `full_pdf` 与 `bounded` 样本比例、利用率分布、被保留页数比例和截断审计失败率。

不再建设数据长度 bucket。训练侧如需提高 batching 效率，可以按当批次实际 token 数做动态 batching 或排序采样，但这属于训练加载策略，不写成数据类别，也不改变样本内容。

### 14.3 阶段规模

| 阶段 | PDF | 生成候选 | 最终任务 | 目的 |
|---|---:|---:|---:|---|
| Smoke Test | 3–5 | 20–50 | 10–20 | 验证接口和 schema |
| Golden V0 | 20–50 | 约 500 | 100–200 | 调 prompt、gold、rubric 和难度门槛 |
| Training Pilot V0 | 2,000–5,000 | 视通过率决定 | 20,000–40,000 | 第一次对照训练，约 10M–30M loss tokens |
| Scale V1 | 根据 Pilot 测算 | 分批扩展 | 分批扩展 | 验证成本、吞吐与收益曲线 |
| 10B Production | Pilot 达标后确定 | 动态 | 动态 | 正式规模化生产 |

不要从任务数直接推算 10B。必须用目标 tokenizer 和视觉编码策略对实际导出样本测量。

## 15. 质量门槛与监控指标

### 15.1 单样本硬门槛

- license approved；
- 无 benchmark 污染；
- 输入未发生运行时静默截断；bounded view 已在生成前冻结并通过 omitted-page audit；
- evidence graph 满足结构规则；
- gold 所有关键 claim 有证据；
- 确定性计算通过；
- verifier 无未解决分歧；
- rubric 单元测试通过；
- 无答案泄露；
- 人工审核状态符合当前阶段要求。

### 15.2 每轮漏斗

```text
候选文档数
→ 授权通过率
→ 下载/解析成功率
→ 复杂文档命中率
→ 每文档生成候选数
→ 一步题拒绝率
→ evidence graph 合格率
→ gold/evidence 验证通过率
→ rubric 单元测试通过率
→ target base 关键失败率
→ OpenAI 分层审计结果
→ 人工抽检通过率
→ 最终 task/token 数
→ 训练后各能力 slice 增益
```

### 15.3 Golden V0 建议验收目标

以下为启动目标，可根据首轮结果调整：

- 最终 100–200 个任务无已知 critical gold error；
- 100% 通过结构、证据和 rubric 单元测试；
- 最终 Golden 尽量全量人工审核；
- 一步题、歧义题、缺页题和 OCR 假困难全部拒绝；
- 每个 task template 至少有可复核样例；
- OpenAI 与本地模型的失败已按原因分类；
- 可以一条命令导出训练格式并重新计算 token。

这些不是 10B 生产 SLA。Training Pilot 后再根据实测坏题率、成本与人工一致率制定正式 SLA。

## 16. 反馈闭环

每轮使用 `generator_prompt_version` 作为实验单元，不凭直觉直接覆盖 prompt。

| 观察 | 优先修正 |
|---|---|
| 一步题过多 | 强化 evidence graph、控制性证据和 deletion test |
| 模型通过率过高 | 增加跨页、跨模态、例外和依赖操作，不只增加页数 |
| 模型失败率高但人工质量差 | 修问题、gold、rubric、解析和 judge，停止扩量 |
| Gold 错误集中在计算 | 增加确定性计算模板与单位类型检查 |
| Gold 错误集中在视觉绑定 | 改善 bbox、页面裁剪和人工视觉审核 |
| Judge 误判 | 拆分 criterion、改负例测试或更换 judge 配置 |
| 视觉提升不足 | 增加真实视觉依赖，检查文本是否泄露图像答案 |
| 结构任务提升不足 | 增加合并表头、脚注、跨表计算和表单绑定 |
| 通用能力回退 | 调整训练混合和 sampling weight |
| 来源/题型重复 | 降低每文档任务数，加强 group dedup |
| OpenAI 审计与本地预测偏差 | 更新校准集或 difficulty predictor |

每次 prompt 修改至少比较：真实困难率、坏题率、错误 gold 率、rubric 稳定性、成本、生成吞吐和训练后增益。只有困难率上升且质量不下降，修改才算有效。

## 17. 成本、吞吐与扩展策略

### 17.1 V0 成本控制

- 每份 PDF 只生成少量候选；
- 先做解析和结构预筛，再调用强模型；
- 标准 target-visible package 保留完整文本和全部页面图像；内部 evidence candidate index 可以减少搜索调用，但不能改变最终可回答性验证所见输入；
- 相同文档前缀使用缓存能力时记录实际 cache 命中；
- OpenAI 请求保存 token、延迟、状态、重试和费用估算；
- 服务错误指数退避，能力失败不自动重试到通过。

### 17.2 扩展到 10B 前必须回答

- 每个最终合格 task 的平均生成与验证成本；
- 从下载到最终保留的全漏斗通过率；
- 每个主证据类型的错误 gold 率；
- 本地模型与 OpenAI 审计的一致性；
- 单 GPU 吞吐和集群总吞吐；
- 数据收益随 token 增加是否仍上升；
- 是否需要 Ray/队列、对象存储、集中元数据库和专门标注系统。

只有 Training Pilot 显示明确收益后，才投入全量调度和自动 difficulty predictor。

## 18. 安全、隐私与运维

- API key 只从环境或集群 secret 注入，不写入代码、配置、日志或提交；
- PDF、页面图像、模型原始响应和日志默认不提交 Git；
- OpenAI 输入前检查文档是否允许传给外部服务；不允许外发的文档只使用本地模型；
- 对 PII、医疗、未公开、出口管制和访问受限内容做 denylist；
- 下载器限制文件大小、MIME、重定向和域名，隔离异常 PDF；
- 记录删除 lineage，使文档撤权时可以定位并移除全部衍生 task；
- 每次发布生成数据卡，说明来源、许可、模型、prompt、质量指标和已知限制。

## 19. 实施顺序与交付物

### Milestone 0：冻结约定

交付：

- Pydantic schema；
- run manifest；
- source allowlist/denylist；
- GDP contamination denylist；
- model role 配置；
- generator/verifier/judge prompt V0。

### Milestone 1：Smoke Test

交付：

- 3–5 份 PDF 端到端跑通；
- 页面与解析抽检报告；
- 10–20 条可导出的样本；
- 失败原因与重试机制验证。

### Milestone 2：Golden V0

交付：

- 20–50 份 approved PDF；
- 约 500 候选和完整漏斗；
- 100–200 个高质量任务；
- OpenAI/本地强模型难度校准；
- 人工审核结果；
- generator prompt V1 建议。

### Milestone 3：Training Pilot V0

交付：

- 20,000–40,000 个困难任务；
- 训练与 sidecar 数据；
- token/accounting 和数据卡；
- Base/Control/Treatment checkpoint；
- GDP.pdf、补充 benchmark、内部 holdout 和回归评测报告。

### Milestone 4：Scale Decision

根据 Pilot 做 go/no-go：

- 若 Treatment 有稳定分片增益且质量可控：设计 V1 规模化系统；
- 若只在少数 slice 提升：针对性修数据配比和模板；
- 若无提升：优先检查任务答案、训练格式、上下文/图片策略和数据重复，而不是盲目扩量；
- 若成本不可接受：扩大本地生成/验证比例并保留 OpenAI 分层审计。

## 20. 当前待实现的最小 Backlog

现有代码已具备 CLI、配置、schema、discover、ingest、PyMuPDF 页面渲染、raw-PDF OpenAI generator、静态验证和初步 model verifier。它是可复用的 V0 骨架，但还不符合本节冻结的目标输入协议。

迁移按顺序执行：

1. 固定并安装 LiteParse 2.5.0，开启英文 OCR，定义逐页 canonical text IR；
2. 将 PyMuPDF 限定为 150 DPI 完整页面渲染器和基础元数据读取器；
3. 扩展配置和 schema，增加 `target_input.profile`、`supported_input_profiles`、document view 与动态 context accounting；
4. 实现 `text_only` / `multimodal` build-input stage，以及 full/bounded document view 构建；
5. 接入目标 tokenizer/vision processor，实现约 80% 软目标、动态安全余量和 512K 硬上限检查；
6. 修改 generator，使其消费显式 target-visible package，而不是 OpenAI 原生 PDF input；
7. 更新 evidence-first generator prompt，加入 profile 可见性约束；
8. 修改 verifier/difficulty solver，使其和被测 profile 接收完全相同的输入；
9. 完成 omitted-page audit、gold 计算器、claim–evidence validator、rubric 负例单元测试与 export；
10. 用现有 3 份 PDF 重新跑 dual-profile Smoke Test；
11. 人工比较旧 raw-PDF generator 与新显式输入链路，修复答案、可见性和难度差异；
12. 扩到 Golden V0，随后冻结 Training Pilot 配置并做对照训练。

### 20.1 2026-09-17 实施快照

- 已完成：精确 pin `liteparse==2.5.0`、English OCR、本地 tessdata cache、150 DPI
  PyMuPDF 整页渲染和逐页 canonical text IR；
- 已完成：配置/schema 中的 target input profile、document view、动态 context budget；目标
  25 万词表 tokenizer 已接入，文档文本改为精确计数，视觉 token 暂保留显式 provisional 计数；
- 已完成：`build-input` stage，支持 full PDF、显式 bounded page ranges、150→120→96→72
  DPI fallback，超预算时拒绝静默尾部截断；
- 已完成：generator 从 raw PDF `input_file` 迁移到显式 LiteParse 文本与整页图像，verifier
  复用相同 frozen input package；
- 已验证：现有 3 份 NASA PDF 共 210 页完成重新解析，并各自生成 text-only 与 multimodal
  输入包；
- 已完成：Qwen3.8-27B 与 GLM-5.3-Flash 本地服务 bake-off；当前默认本地 generator 候选
  冻结为 GLM `high + 24K`，Qwen `xhigh` 保留为聚焦视觉 verifier/difficulty solver；
- 已完成：本地 chat 请求正式传递 `reasoning_effort`、`temperature`、`top_p` 和输出预算；
  加入 GLM→Qwen、Qwen→GLM 两套隔离输出的 run config、模型家族独立性 gate、各服务自身
  context-window 预检和 verifier 模型溯源；
- 已完成：generator prompt 增加 evidence graph 精确 ID、claim/derivation/rubric 引用闭合和
  返回前 self-check；88 页三候选 batch 的 static 通过率由 0/3 提升到 2/3；
- 已完成：23 页完整 package 的本地端到端 smoke；GLM 生成 3 条并 static 3/3，Qwen 对其中
  1 条完成 blind reconstruction + gold audit 并通过。结果同时暴露了 task-type quota 和
  模型共同接受边界过推的问题，尚不能导出训练；
- 已确认：实验 batch 尚不能当作最终 SFT 数据；99 页 batch 虽 static 3/3，仍未完成独立
  gold reconstruction、确定性计算复核、bbox/摘录核验和人工审核；
- 已完成：correctness audit 的 evidence-page + bbox-crop 附件、附件 manifest、excerpt/bbox
  token 对齐门禁和日志；真实样本检出 `e1/e5` 错位并从模型审计的通过结果降为 `needs_review`；
- 已完成：非破坏性 bbox repair suggestion、旧/新 crop 对照和机器可读人工 decision 模板；真实
  `e1/e5` 建议均为 high confidence，但尚未接受或应用；
- 已完成：接入目标文本 tokenizer
  `/mnt/weka/shrd/k2m/mikhail.yurochkin/ilikejson-250k-tokenizer`，记录 tokenizer JSON 的
  SHA-256 指纹；待视觉模块冻结后再接入其真实 vision processor；
- 已完成：一次性结构修复重试、run-level task-type quota、prompt 内容 hash 和 V2 sample ID；
- 已完成：人工 bbox decision apply、final gate、受限算术 calculator、人工 omitted-page/视觉/rubric
  checklist、difficulty、export、report，以及隔离三文档 V1 smoke；
- 待完成（不阻塞 initial pipeline 代码闭环）：接入目标模型真实 vision processor 和最终 chat
  template、完成当前 V1 样本的人工签核，并用更大 Golden V0 校准 predicted difficulty 阈值和
  人工抽检比例。

### 20.2 Initial Pipeline V1 实测闭环

2026-09-17 后续实现已补齐以下可执行 stage：

```text
apply-bbox-repairs → model-verify(repaired) → finalize
→ difficulty-gate(predicted|judged) → export → report
```

- Bbox decision 必须为 `accepted`、具有非空 reviewer，且原 bbox 必须与 suggestion 中的旧值完全
  一致；否则拒绝 stale/无归属修复。修复写新 `repaired.jsonl`，不覆盖 verified，并清空旧模型
  验证状态，要求重新验证；
- `finalize` 统一检查来源授权和 benchmark denylist、frozen input package/context、full/bounded
  view、cross-model gold、bbox、受限算术复算、rubric 结构/负例、人工 checklist。未知项为
  `needs_review`，来源/计算矛盾、坏 rubric、verifier 否定或人工拒绝才为 `failed`；
- `difficulty-gate` 的 predicted 模式用于规模化预筛；judged 模式只把完整输入下的实质性 solver
  推理失败算作 verified hard，服务/格式/截断失败不计；
- `export` 分离 hint-free training conversation 与 audit sidecar，按 document hash 做 group split，
  严格模式拒绝未验证难度；允许 predicted 的 pilot export 永远不是 release-ready；
- `report` 汇总 task-type 分布、static 原因、verifier、repair、final、difficulty 和 export 漏斗。

生成侧同时补齐一次性结构修复和 run-level 类型配额。结构修复只处理 Pydantic/引用闭合错误，
最多一次且保留 raw/log；语义错误不自动改写。40/45/15 权重通过最大余数配额和确定性交错序列
分配到整个 run，再把每个 candidate index 的 required type 作为硬约束传入模型。Prompt 版本升级
为 `generator_v2+sha256:<digest>`，避免修改 prompt 后沿用旧 sample ID。

隔离 `initial_pipeline_v1` 对三份现有 PDF 各生成一条，精确得到 1 visual-spatial、1
structured-layout、1 text-reasoning。新版 static gate 新增 `has_primary_intent` 和
`rubric_covers_all_gold_claims`：视觉题因 lookup-only 被拒，文本题因 rubric 漏两条 claim 被拒，
仅 88 页跨 Table 3-1/Table 5-4 的结构任务通过。该任务由 Qwen3.8-27B-512K 用完整 88 页 blind
重建，再以 pages 18/56 focused audit；gold、5 个 claims 和 3 个 bbox 均通过，0 repair。最终
状态为 `needs_review`，只剩非算术筛选推导、rubric negative cases 和 human review checklist。

当前真实漏斗为 3 generated → 1 static accepted → 1 independent verifier passed → 1 final
needs-review → 0 difficulty → 0 export。该 0 导出是正确的安全结果，不是 pipeline 故障；人工审核
完成前不得伪造 release-ready。代码检查为 Ruff clean、39 tests passed。

### 20.3 目标 tokenizer 接入结果

V1 配置已冻结目标文本 tokenizer，并将 input package 放入 run 隔离目录。`build-input` 直接使用
`tokenizer.json` 统计完整逐页 LiteParse 文本，不添加 tokenizer 中不存在的 chat template；记录
`hf-fast:ilikejson-250k-tokenizer:sha256:7e4c364927e79537` 作为计数器身份。三份完整文档的结果为：

| 文档页数 | 精确文本 tokens | 视觉 tokens（估算） | 含 question/system 预留的输入估算 | 512K 利用率 |
|---:|---:|---:|---:|---:|
| 99 | 49,162 | 249,926 | 305,232 | 58.2% |
| 88 | 41,596 | 221,430 | 269,170 | 51.3% |
| 23 | 24,994 | 57,518 | 88,656 | 16.9% |

旧的 `chars/3.5` 对三份文本分别估算为 70,110、59,610、33,165 tokens；新计数合计
115,752，而旧估算合计 162,885，旧口径高估约 28.9%。这不会放松窗口硬门禁：当前
`exact=false`、`text_tokens_exact=true`、`image_tokens_exact=false`，因为视觉编码、system/chat
分隔符和最终序列化模板尚未冻结。训练 export 会对问题、完整文档文本和 gold answer 再做一次
文本精确计数，但整条多模态序列在 vision processor 接入前仍明确标为估算。

### 20.4 V1 人工签核与难度结果

人工 reviewer `yuan.huang` 已确认 88 页结构任务的问题无歧义、gold 正确、五条筛选/求交推导
成立，并完成 rubric 负例审阅。为保留不可变生成记录，三项修订作为
`sample_review_decision.json` 中的审计 override，由 `finalize` 应用到新 artifact：

1. `r2` 只强制题目明确要求的四个标称电压，不强制复述全部筛选字段；若主动写出筛选数值则
   仍须准确；
2. `r5` 的脚注要求由 minor 改为 major，因为这是问题明确要求的输出；
3. `r6` 删除重复的脚注处罚，只拦截把近似但不合格的体系加入最终集合。

`finalize` 结果为 1 passed、0 failed、0 needs-review，并记录三条
`AppliedRubricOverride`（原值、新值、原因、reviewer、decision artifact 和时间）。predicted
difficulty 随后给出 `0.6333 / medium`，低于 `hard >= 0.65` 门槛；而且独立 Qwen 已完整正确解出
该题，因此无需再为这条样本调用付费 judge。它是正确、可用的中等难度样本，但不会混入当前
只收 hard 的 release export。最新漏斗为 3 generated → 1 static accepted → 1 final passed →
1 difficulty assessed → 0 hard admitted → 0 exported。

### 20.5 单 PDF 多 hard-task 实验

Checkpoint `7f406d0` 之后新增 `golden_v0_single_pdf_battery` 实验。生成器支持重复
`--document-id` 精确选文档、`batches_per_document` 断点续跑，以及第二批读取前批候选摘要后
主动避开相同证据和问题。Hard profile 对每题要求至少 4 个决定性 evidence nodes、3 个证据页、
4 个依赖操作、2 个非 lookup 操作，并要求多阶段专业决策和近似项/例外陷阱。

新增的 `deduplicate` stage 在 model verifier 前比较：

- 同页 bbox IoU 匹配后的 evidence-region Jaccard；
- evidence-page Jaccard；
- prompt token Jaccard；
- operation-type Jaccard；
- 每文档上限与 primary-evidence-type 多样性。

88 页电池手册分两批各生成 3 题，类型配额得到 3 structured、2 visual、1 text。Static gate
保留 2/6：跨 pages 44/47/49/50 的锌空气储存与析氢任务，以及跨 pages 19/22/23、必须读取
Figure 4-1 的银锌防漏空间任务；两题 evidence 不重叠，去重后均保留，结构难度分别为
`0.8667 hard` 与 `0.9167 hard`。其余四题中，两题存在 key evidence 未接入 final output，四题均
存在 rubric 未直接覆盖 gold claim 的问题。生成器现已把这些检查前移到每批返回后，并利用既有
一次 structure-repair retry 修复，避免下一轮到 static gate 才浪费候选。

Qwen3.8-27B-512K 在完整 88 页 blind 输入上正确解出两题，focused audit 也确认全部 gold
claims，因此它们是结构 hard、gold 可靠，但不是当前 Qwen 的真实失败题。文本任务只剩 e2/e6
两个 high-confidence bbox 修订待人工确认（coverage 均提升到 1.0）；视觉任务的 Figure 4-1
原始 crop 正确，文本 coverage 不适合作为图形 bbox 判据。alignment gate 已将明确的 Figure
视觉节点改为 `not_checkable_visual_or_ocr`，交由 `visual_evidence_verified` 人工项确认。

人工 reviewer `yuan.huang` 随后批准两题的问题、gold、推导和 rubric，确认视觉任务原始 bbox
与图像证据，并接受文本任务 e2/e6 的高置信度建议 bbox。Repair stage 共应用 2 个文本 bbox；
未修改的视觉任务按新 alignment 规则刷新确定性检查并复用已完成的独立模型审计，修改后的文本
任务则重新执行完整 blind reconstruction 与 focused audit。最终 Qwen 独立核验 2/2 passed，
`finalize` 2/2 passed，predicted difficulty 2/2 admitted as hard，pilot export 得到 2 条训练记录和
2 条审计 sidecar，0 rejected，估算总序列长度 527,144 tokens。

该导出仍明确为 `release_ready=false`：两题的 hard 仅由结构规则预测，未通过 solver-failure judge；
视觉 token 和最终 chat serialization 也仍是估算。这个结果证明 Initial Pipeline 已能完成
“多候选生成 → static gate → 去重 → 独立 gold audit → 人工 bbox/内容签核 → 修复后复核 →
final gate → pilot export”的闭环，但不能把 pilot 标签误写成正式 release-ready 数据。

## 21. Source of Truth 与参考文档

本文是当前 Initial Pipeline 的总计划。更细的任务模板和准入规则见：

- [`gdp_like_task_design_spec.md`](../specs/gdp_like_task_design_spec.md)
- [`gdp_pdf_benchmark_analysis.zh-CN.md`](../research/gdp_pdf_benchmark_analysis.zh-CN.md)
- [`keenable_search_cluster_guide.md`](../guides/keenable_search_cluster_guide.md)

外部参考：

- [GDP.pdf 论文](https://arxiv.org/abs/2607.11192)
- [GDP.pdf 官方数据卡](https://huggingface.co/datasets/surgeai/GDP.pdf)
- [Artificial Analysis GDP.pdf](https://artificialanalysis.ai/evaluations/gdp-pdf)
- [AA Intelligence Benchmarking Methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)
- [OpenAI Models](https://developers.openai.com/api/docs/models)
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [NASA STI Repository](https://sti.nasa.gov/)
- [NASA Images and Media Guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/)
- [GovInfo Policies](https://www.govinfo.gov/about/policies)

## 22. 最终原则

```text
先证明来源可用，
再证明输入完整，
再证明答案正确，
再证明任务确实需要多处证据和多步操作，
最后才用模型失败衡量困难程度。
```

如果模型答不出是因为任务坏了，它不是高难数据；如果答案一步可得，即使模型偶然答错，它也不是 GDP-like 数据。只有正确、可验证、专业、真正依赖多模态多步推理的样本，才进入训练集。
