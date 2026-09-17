# Smoke Test V0 运行报告

更新日期：2026-09-15  
运行 ID：`smoke_test_v0`

## 结论

Initial pipeline 已经从来源发现运行到独立 verifier。3 份权利审核通过的 NASA PDF 均
完成下载、210 页渲染与解析、困难候选生成、GDP-like 静态准入和两阶段模型验证；3 条
候选最终全部通过正确性门，并可进入 difficulty gate。当前结果仍是 smoke test，不替代
Golden V0 的正式人工审核。

独立 verifier 的第一阶段不接收 gold/claims，只用问题和证据页盲解；第二阶段再对 blind
reconstruction、gold、claims 和原页逐项审计。第三条样例首次审计时准确发现 gold 漏写
“实际器件参数/辐射敏感应用必须有合适的地面 TID/TNID/DDD 数据”这一适用条件。该条件
经可复现的人工修订脚本补入 gold、evidence graph、claim 和 rubric 后重新验证通过。

## 数据与产物

| 项目 | 结果 |
|---|---:|
| 已审核来源 PDF | 3 |
| PDF 总页数 | 210 |
| 原始 PDF 体积 | 7.5 MiB |
| 解析产物体积 | 60 MiB |
| 生成候选 | 3 |
| 静态准入 | 3/3 |
| verifier passed | 3 |
| verifier needs_review | 0 |
| verifier not_run | 0 |
| eligible_for_difficulty | 3 |

生成 JSONL 约 40 KiB，包含任务 prompt、gold answer、evidence graph、claims、derivations、
atomic rubric 和生成 provenance。训练导出尚未执行；最终 SFT token 统计必须同时覆盖文档
多模态输入、问题和答案，不能只统计答案文本。

## 三条候选

### 1. NACA 0012 CFD 档案筛选

- 主证据：`visual_spatial`
- 证据页：13、14、19、20
- 结构：10 个 evidence nodes、12 个 operations、3 个 derivations、9 条 rubric
- 必要步骤：跨表筛选实验来源；绑定侧壁处理说明；解析 Figure 15 图例符号；读取最前
  激波位置；与区间边缘比较；结合正文对 benchmark 可用性作受限结论。
- 复核结果：Lowe/Ohman 的筛选、NAL 的排除条件、约 0.41 的图读数和约 0.03 的区间
  偏离均与页面一致；独立 verifier 的全部 claim 均通过。

### 2. 锌空气电池采购筛选

- 主证据：`structured_layout`
- 证据页：18、45、49
- 结构：6 个 evidence nodes、10 个 operations、5 个 derivations、10 条 rubric
- 必要步骤：绑定型号脚注并排除停产型号；跨页取得 1.1 V；理解串并联规则；分别计算
  最小配置、容量、最大膨胀高度和包含吸氧增重的放电后质量；求预算超限量。
- 复核结果：`6S7P/42`、`6S4P/24`、`37.8/56.4 mm`、`179.2833/154.746 g`
  及最终“没有型号同时满足两项预算”的结论均复算正确；独立 verifier 的全部 claim
  均通过。

### 3. GEO 辐射屏蔽权衡

- 主证据：`visual_spatial`
- 证据页：64、69、70
- 结构：4 个 evidence nodes、10 个 operations、5 个 derivations、12 条 rubric
- 必要步骤：绑定 Figure 18 的 GEO 图例；按离散 marker 做 20% 阈值筛选；识别前一个
  失败点；计算屏蔽增量；跨页判断 cold spare 是否适用并识别不同器件设计例外；限定
  任务环境、应用和寿命范围。
- 复核结果：一年任务选 150 mils、十年任务选 250 mils，增加 100 mils/66.7%；图中
  概率读数和 cold-sparing 结论与页面一致。首次审计发现并补齐地面辐射测试数据的适用
  条件，修订后全部 claim 通过。

## 模态分布

当前只有 3 条，不能用来评价长期分布：

| 主证据类型 | 条数 | 比例 |
|---|---:|---:|
| visual_spatial | 2 | 66.7% |
| structured_layout | 1 | 33.3% |
| text_reasoning | 0 | 0% |

这符合“视觉和结构任务优先、纯文本较少”的方向，但 40%/45%/15% 仍只是规模化时的软
配额，不应在小样本上硬凑比例。

## API 使用反馈

3 次成功 generator 请求合计：

| token 类型 | 数量 |
|---|---:|
| input | 525,144 |
| output | 27,136 |
| total | 552,280 |

单次总 token 约为 96k、297k、159k。此前一次要求同一 PDF 返回 3 条任务时还发生过
12k 输出截断。由此得到两个明确修正：

1. Smoke 阶段维持每请求 1 条候选并使用断点续跑，避免长 structured output 截断。
2. 10B 扩展不能逐题把整本 PDF 交给昂贵 frontier generator。下一版应先用解析结果和
   本地模型做章节/证据簇选择，再只把候选页及必要邻页交给 generator；OpenAI 保留给
   Golden、prompt 校准、边界样本和分层审计。

最终 3 条样例的两阶段 verifier 共使用 57,167 input tokens、15,554 output tokens，合计
72,721 tokens。reconstruction 与 audit 使用稳定的 prompt cache key，但本轮日志中的
`cached_tokens` 均为 0，因此不能把它计作已实现的节省。为不降低证据覆盖和验证强度，
本轮没有删减页面、降低图片分辨率或压低推理强度；规模化节省应主要来自前置证据簇选择、
本地模型初筛和抽样式 frontier 审计。

## 已验证的工程性质

- benchmark 目录禁止作为训练输入，GDP.pdf 资产与训练源隔离；
- key 位于被 gitignore 排除的本地配置，配置检查只打印是否存在；
- generation 按文档断点续跑并逐文档原子落盘；
- strict JSON Schema 适配 OpenAI Structured Outputs；
- claim 可以依赖前序 claim，但校验其引用存在、无环并最终落到 PDF evidence node；
- derivation 的 result 和 inputs 均检查引用完整性；
- verifier 的第一阶段 prompt 有自动测试保证不包含 gold/claims；
- verifier 服务错误落为 `needs_review` 且 `eligible_for_difficulty=false`；
- 可生成包含问题、gold、独立盲解、审计、rubric、证据原页和 claim 链的离线 review pack；
- 16 个单元测试、Ruff lint 和 format check 全部通过。

## 下一步

1. 人工检查 `reports/smoke_test_v0/review_pack/README.md`，逐条批准或退回；目前不能由
   pipeline 自行把模型审计通过等同于 human-approved。
2. 为数值/集合任务增加确定性 calculator/checker，并把本次发现的“适用条件遗漏”加入
   generator/verifier 回归规则。
3. 在这 3 条 Golden 候选上小规模校准 difficulty solver 与 rubric judge prompt；批量阶段
   使用本地 served 模型初筛，OpenAI 只做抽样和边界复核。
4. 实现多模态 SFT export，仅导出 static、independent verifier、difficulty 和人工审核均
   达标的样本，并把文档图像、问题和答案全部纳入 token/规模统计。
