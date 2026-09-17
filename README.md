# Multimodal PDF SFT Pipeline

本项目以 GDP.pdf benchmark 的任务结构为主要参考，构建高难、多模态、可验证的专业 PDF SFT 数据生产与评测 pipeline。

当前已进入 V0 smoke pipeline 实现与反馈阶段。三个已审核 NASA PDF 已完成发现、下载、解析、候选生成和静态验证；研究材料统一放在 [`docs/`](./docs/) 中。

V0.2 已冻结目标模型输入协议：文本统一使用 LiteParse 2.5.0（English OCR），支持 `text_only` 与 `multimodal` 两种 profile；后者输入冻结 document view 的所有完整页面图像、问题和完整提取文本。默认 view 是完整 PDF；超长 PDF 在题目生成前按完整页面/章节构造 bounded view，训练时禁止静默截断。现有 PyMuPDF/raw-PDF OpenAI smoke 实现将按总计划迁移，不能视为最终训练输入链路。

## 从这里开始

1. **执行总计划**：[`docs/plans/multimodal_pdf_sft_initial_pipeline.md`](./docs/plans/multimodal_pdf_sft_initial_pipeline.md)
2. **任务准入规范**：[`docs/specs/gdp_like_task_design_spec.md`](./docs/specs/gdp_like_task_design_spec.md)
3. **全部文档索引**：[`docs/README.md`](./docs/README.md)
4. **当前 smoke 运行报告**：[`reports/smoke_test_v0.md`](./reports/smoke_test_v0.md)

总计划是当前唯一的 pipeline Source of Truth；任务设计规范负责约束 generator、gold answer、evidence graph、rubric 和难度判定。研究报告及指南提供依据，但不覆盖总计划中的当前决定。

## 当前目录结构

```text
.
├── README.md
├── docs/
│   ├── README.md
│   ├── plans/
│   ├── specs/
│   ├── research/
│   └── guides/
├── benchmarks/
│   └── README.md
└── scripts/
    ├── benchmarks/
    └── research/
```

后续按照总计划逐步增加：

```text
configs/        # source、model、prompt 和 run 配置
src/pdf_sft/    # pipeline Python package
tests/          # schema、stage 和验证测试
data/           # manifest 与阶段产物；默认不提交大文件
raw_pdfs/       # 原始 PDF；不提交
parsed/         # 页面图像与解析结果；不提交
logs/           # API、stage 和 difficulty 日志；不提交
reports/        # Golden/Pilot 汇总报告
```

GDP.pdf 等独立评测资产放在 `benchmarks/` 的本地忽略目录中。下载方式和隔离规则见 [`benchmarks/README.md`](./benchmarks/README.md)。

## 研究脚本

历史 benchmark 审计工具位于 [`scripts/research/`](./scripts/research/)：

- [`analyze_gdp.py`](./scripts/research/analyze_gdp.py)：提取 GDP.pdf 文本、页数、图片对象和 rubric 统计；
- [`analyze_liteparse_complexity.py`](./scripts/research/analyze_liteparse_complexity.py)：使用 LiteParse 检查页面复杂度和 OCR 路由；
- [`parse_selected_liteparse.py`](./scripts/research/parse_selected_liteparse.py)：对选定 benchmark 样本执行 OCR/解析抽查。

这些脚本默认依赖 `/tmp` 中的研究数据和依赖目录，不属于生产 pipeline。复用前需要参数化输入、输出和依赖路径。

Benchmark 下载工具位于 [`scripts/benchmarks/`](./scripts/benchmarks/)，只负责构建独立评测资产，不向训练目录复制数据。

## Pipeline 快速启动

安装项目环境：

```bash
uv sync
```

本地密钥文件已经创建在 `configs/local/secrets.env`，该目录已被 `.gitignore` 排除。请填入：

```text
OPENAI_API_KEY=...
KEENABLE_API_KEY=...
LOCAL_VLM_API_KEY=local
LOCAL_VLM_BASE_URL=http://127.0.0.1:8000/v1
```

提交仓库时只保留无密钥模板 [`configs/secrets.env.example`](./configs/secrets.env.example)。不要在聊天、日志或 run manifest 中打印实际 key。

检查配置与模型凭证状态：

```bash
.venv/bin/pdf-sft validate-config
```

在 [`configs/sources/smoke_nasa.yaml`](./configs/sources/smoke_nasa.yaml) 填入 3–5 份已审核 PDF 后，依次运行：

```bash
.venv/bin/pdf-sft discover
.venv/bin/pdf-sft ingest
.venv/bin/pdf-sft parse
.venv/bin/pdf-sft generate
.venv/bin/pdf-sft static-verify
.venv/bin/pdf-sft model-verify --limit 1
.venv/bin/pdf-sft review-pack
```

`static-verify` 只完成 schema、引用和 GDP-like 结构检查。它会明确保持 `eligible_for_difficulty=false`，直到后续独立 verifier、确定性重算、rubric 单元测试和人工审核全部完成，防止静态检查结果被误当作正确 gold。

`model-verify` 先在不提供 gold/claims 的情况下仅用任务和证据页盲解，再单独审计 gold。API 配额、服务错误、缺图或不可读输入会标记为 `needs_review`，不会计作任务困难或进入 difficulty gate；修复服务后用 `--overwrite` 重试。Smoke 配置使用 OpenAI verifier，默认配置保留 OpenAI-compatible 本地 VLM 接口。

运行开发检查：

```bash
.venv/bin/ruff check src tests scripts/benchmarks
.venv/bin/ruff format --check src tests scripts/benchmarks
.venv/bin/pytest
```

## 数据边界

GDP.pdf 公开数据只有 test split，并标记为 `not-for-training`。Benchmark PDF、prompt、rubric、reference answer、模型回答及其改写都不得进入训练数据或 generator 上下文。

大型 PDF、解析结果、JSONL/Parquet、日志、模型响应、API key 和本地环境文件不应提交到仓库。外部 PDF 必须逐文档完成来源、授权、第三方素材和污染检查。

## 主要参考

- [GDP.pdf 论文](https://arxiv.org/abs/2607.11192)
- [GDP.pdf 官方数据卡](https://huggingface.co/datasets/surgeai/GDP.pdf)
- [Artificial Analysis GDP.pdf](https://artificialanalysis.ai/evaluations/gdp-pdf)
- [Keenable 文档](https://docs.keenable.ai)
