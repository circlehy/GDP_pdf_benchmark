# 文档索引

本目录保存多模态 PDF SFT pipeline 的计划、规范、研究依据和操作指南。文档按用途组织，避免与即将建立的生产代码混放。

## 文档层级

```text
docs/
├── README.md
├── plans/
│   └── multimodal_pdf_sft_initial_pipeline.md
├── specs/
│   └── gdp_like_task_design_spec.md
├── research/
│   ├── gdp_pdf_benchmark_analysis.zh-CN.md
│   └── gdp_pdf_benchmark_analysis.en.md
└── guides/
    └── keenable_search_cluster_guide.md
```

## 阅读顺序与状态

| 优先级 | 文档 | 角色 | 状态 |
|---:|---|---|---|
| 1 | [`plans/multimodal_pdf_sft_initial_pipeline.md`](./plans/multimodal_pdf_sft_initial_pipeline.md) | 项目目标、技术栈、数据源、阶段流程、模型服务、训练评测和里程碑 | **Source of Truth** |
| 2 | [`specs/gdp_like_task_design_spec.md`](./specs/gdp_like_task_design_spec.md) | GDP-like task、gold、evidence graph、rubric 和困难准入的详细规范 | **Normative Spec** |
| 3 | [`research/gdp_pdf_benchmark_analysis.zh-CN.md`](./research/gdp_pdf_benchmark_analysis.zh-CN.md) | GDP.pdf 数据、任务分布、文档模态和 AA 评分研究 | Research Reference |
| 4 | [`guides/keenable_search_cluster_guide.md`](./guides/keenable_search_cluster_guide.md) | Keenable 搜索、认证、集群部署、限速和安全操作 | Operational Guide |
| 5 | [`research/gdp_pdf_benchmark_analysis.en.md`](./research/gdp_pdf_benchmark_analysis.en.md) | Benchmark 分析英文版本 | Translation |

发生冲突时按下列优先级处理：

```text
Initial Pipeline 总计划
> GDP-like 任务设计规范
> 研究报告与操作指南
```

研究报告描述 benchmark 事实和当时的审计结果；总计划记录我们针对训练生产做出的当前决策。例如 40%/45%/15% 是项目软配额，不是 GDP.pdf 官方分布。

## 维护约定

- 新的执行决策优先更新总计划；
- generator、gold、rubric 或难度规则的细节更新任务设计规范；
- 实验结果放入未来的 `reports/`，不要回写成 benchmark 事实；
- 外部服务的具体版本、endpoint 和 prompt 版本放入 run manifest，不在规范中静默替换；
- 文档内部使用相对链接，README 和交付说明可使用仓库相对路径；
- 中英文研究报告是平行版本，不作为两个独立决策来源；
- GDP.pdf 及其他评测集始终只用于分析和测试，不用于训练。

## 下一步

代码已具备 V0 骨架。下一步从总计划的“当前待实现的最小 Backlog”继续：将主文本 extractor 迁移到 LiteParse 2.5.0，增加 `text_only` / `multimodal` target input profile、动态 512K 上下文预算和生成前 document view 构建，再让 generator、verifier、训练与评测统一消费这套输入。
