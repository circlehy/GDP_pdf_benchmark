# GDP 式困难多模态 PDF 任务设计规范

更新日期：2026-09-15  
状态：V0，用于约束 task generator、gold answer、rubric 和困难度判断

## 1. 目标

本规范定义什么样的任务可以称为 `GDP-like`。核心不是复制 GDP.pdf 的题目或领域比例，而是复现其任务结构：模型必须从原始专业 PDF 的多个位置找到正确证据，理解文本、版面和视觉关系，完成多步专业操作，并避免被脚注、排除项、图例、相邻字段或失效条款误导。

GDP.pdf 本身及其 prompt、rubric、reference answer、模型答案和衍生改写不得进入训练数据或 generator 上下文。

主要依据：

- [GDP.pdf 论文](https://arxiv.org/abs/2607.11192)
- [GDP.pdf 官方数据卡](https://huggingface.co/datasets/surgeai/GDP.pdf)

## 2. GDP-like 的必要条件

一个候选 task 必须同时满足：

1. **文档依赖**：仅凭常识、搜索记忆或 prompt 本身不能回答。
2. **多处证据**：至少两个独立证据位置，且不能退化成同一段中的连续复制。
3. **多步操作**：至少包含两步有依赖关系的检索、绑定、比较、计算、筛选、排除、排序、求交集或版本判断。
4. **控制性证据**：至少有一个证据会改变初步答案，例如脚注、例外、图例、定义、排除项、修订或跨页表头。
5. **专业输出**：问题对应真实工作动作，而不是“这页写了什么”的课堂式问答。
6. **可验证 gold**：每个关键 claim 都能绑定证据页/区域或确定性计算。
7. **可诊断 rubric**：gold 能通过全部 criterion；删除关键事实或加入典型错误后必须触发对应失败。

若缺少任意一项，不进入高难训练集。

## 3. GDP.pdf 的能力轴如何用于生成

GDP.pdf 将能力分成三层十一轴。我们的 task 允许多标签，但每条高难任务至少覆盖一个 Tier 2 和一个 Tier 3 轴。

| 层级 | 能力轴 | 生成要求 |
|---|---|---|
| Tier 1 | Correctness & completeness | 需要完整提取决定答案的事实，不能漏项或改值 |
| Tier 1 | Grounding | 每个结论可回到 PDF，不能用常识补齐 |
| Tier 1 | Spatial awareness | 理解标签、箭头、对象及页面相对位置 |
| Tier 2 | Semantic reading flow | 正确处理多栏、侧栏、callout 和阅读顺序 |
| Tier 2 | Typographic hierarchy | 区分标题、子节、强调、列表和作用域 |
| Tier 2 | Standard table parsing | 保持行列、合并表头、相邻字段的对应关系 |
| Tier 2 | Chart & multimodal interpretation | 联合图例、坐标轴、视觉标记和正文语境 |
| Tier 3 | Complex & multi-page tables | 跨页保持表头、分组和嵌套关系 |
| Tier 3 | Cross-referencing | 连接脚注、附录、定义、引用和远处条款 |
| Tier 3 | Artifact & noise | 排除页眉页脚、水印、扫描噪声和失效内容 |
| Tier 3 | Unsupported queries | 证据缺失、遮挡或不支持结论时明确 abstain |

Tier 1 是所有样本的基础，不应单独作为困难来源。单纯 OCR、单字段定位或单图读数即使属于 Tier 1，也不算 GDP-like 高难任务。

## 4. 推荐任务模板

### 4.1 跨表格核对与计算

证据链：

```text
表 A 取基础值
→ 表 B 取适用系数
→ 脚注判断系数适用范围
→ 执行计算
→ 与阈值或另一对象比较
```

答案必须包括输入值、适用规则、必要计算和最终结论。Dodged Bullet 应检查相邻列误读、把折扣用于错误对象、遗漏单位或忽略脚注。

### 4.2 图表与正文联合推理

证据链：

```text
图例识别系列
→ 在指定坐标读取多个点或相对关系
→ 正文取得定义/基准
→ 计算变化或比较
→ 保留图表精度限制
```

不能只问单个柱子的数值。至少需要多个视觉点，或一个视觉读数与另一页正文/表格联合。

### 4.3 工程图/平面图与图例、schedule 对齐

证据链：

```text
图例定义符号
→ 图纸中定位或计数
→ schedule/规格表取得属性
→ 排除不满足条件的对象
→ 输出完整集合或数量
```

答案必须区分图号、零件号、区域、符号和实际对象。典型错误包括漏计、重复计数、把相似符号混同或未与 schedule 核对。

### 4.4 主条款、定义、排除项和 endorsement 联合判断

证据链：

```text
找到表面适用的主条款
→ 查远处定义
→ 检查排除项
→ 检查 endorsement/amendment
→ 判断最终控制规则
```

只引用真实但不控制本案的条款必须判错。答案要说明哪个条款最终控制，以及为什么早期条款不能单独决定答案。

### 4.5 版本、日期和 supersession

证据链：

```text
提取原规则及日期
→ 找到后续修订
→ 确定生效范围
→ 处理时间或对象例外
→ 输出当前有效结论
```

必须设置旧内容作为真实 distractor。引用已经被覆盖的数字或条款属于 dealbreaker。

### 4.6 多对象筛选、排序和求交集

证据链：

```text
从不同页面取得候选集合
→ 标准化名称/单位
→ 应用多个条件
→ 处理脚注造成的增删或改序
→ 输出精确集合/排名
```

答案必须满足集合完整性：漏项和多报都应有 rubric。不能使用模糊的“例如”。

### 4.7 扫描件、表单字段与空间绑定

证据链：

```text
识别字段标签
→ 根据二维位置绑定填写值
→ 跨页或跨区确认身份/日期
→ 排除页眉、模板文字或手写噪声
→ 汇总目标字段
```

仅识别字符不够；任务必须依赖字段和值的空间对应，或多处表单信息的一致性。

### 4.8 证据不足与受限结论

证据链：

```text
找到相关章节/图表
→ 检查所需字段或系列是否存在
→ 检查是否被遮挡、删减或仅能间接推测
→ 明确可回答和不可回答部分
```

答案不能只写“不知道”。Rubric 应要求说明缺失的决定性证据，并保留文档仍能支持的有限结论。

## 5. 明确拒绝的一步任务

以下候选即使答案正确，也不进入高难集：

- 答案可以从单个句子直接复制；
- 只读取一个表格单元格；
- 只识别标题、日期、姓名或页码；
- 只对一张图做无推理描述；
- prompt 已经给出所有计算输入；
- 只需一次关键词搜索即可定位并回答；
- 不看 PDF 也能凭常识回答；
- 所谓跨页只是把两个互不影响的事实并列抄出；
- 任务因 OCR 缺失、输入截断或问题歧义而“困难”；
- 视觉任务的决定性信息已经在 prompt 或 caption 中完整泄露。

## 6. 多步证据图

每条 task 保存显式的 evidence graph：

```json
{
  "nodes": [
    {"id": "e1", "page": 3, "bbox": [0.1, 0.2, 0.8, 0.6], "role": "base_value"},
    {"id": "e2", "page": 8, "bbox": [0.2, 0.3, 0.9, 0.7], "role": "exception"},
    {"id": "e3", "page": 11, "bbox": [0.1, 0.1, 0.7, 0.4], "role": "updated_rule"}
  ],
  "operations": [
    {"op": "lookup", "inputs": ["e1"], "output": "v1"},
    {"op": "filter", "inputs": ["v1", "e2"], "output": "v2"},
    {"op": "supersede", "inputs": ["v2", "e3"], "output": "final_claim"}
  ]
}
```

准入要求：

- 至少两个 evidence node；
- 至少两个有依赖关系的 operation；
- 至少一个 operation 不是 lookup；
- 至少一个节点承担 qualifier、exception、legend、definition、exclusion 或 supersession 角色；
- 最终答案必须依赖全部关键节点，删除任一关键节点会改变答案或使答案不充分。

这比用“页数大于多少”判断困难更可靠。长 PDF 可以很简单，一页复杂工程图也可以很难。

## 7. Gold answer 结构

Gold answer 面向用户，应自然、专业、完整；同时在 sidecar 中保存可验证结构：

```json
{
  "final_answer": "...",
  "claims": [
    {"claim_id": "c1", "text": "...", "supported_by": ["e1", "e2"]},
    {"claim_id": "c2", "text": "...", "supported_by": ["e3"]},
    {"claim_id": "c3", "text": "...", "supported_by": ["c1", "c2"]}
  ],
  "derivations": [
    {"result_claim": "c3", "expression": "(v2-v1)/v1", "inputs": ["c1", "c2"]}
  ],
  "uncertainty": {
    "type": "chart_reading_precision",
    "statement": "values are approximate"
  }
}
```

`supported_by` 可以引用 evidence node 或前序 claim，但 claim 依赖图必须无环，且每个
claim 最终都必须回溯到至少一个 PDF evidence node。`derivations.inputs` 同样只允许引用
已存在的 evidence node 或 claim；这样既能表达多步结论，又不能用悬空的模型断言替代证据。

答案正文应展示用户验证结论所需的数值、条件和简短计算，但不要求保存或训练不可验证的自由形式隐藏思维过程。完整 evidence graph 和 derivation 放在 sidecar 中。

## 8. Rubric 设计与单元测试

Rubric 数量由答案复杂度决定，不为了接近 GDP.pdf 的平均数而填充。一般建议 6–15 条；复杂集合题可以更多。

必须覆盖：

- 每个关键最终 claim；
- 决定结论的 qualifier/exception；
- 关键计算结果和单位；
- 列表或集合的完整性；
- 至少一个最可能发生的 Dodged Bullet；
- unsupported task 所需的明确 abstention。

每条 task 自动生成并验证三种响应：

```text
gold_answer                → 全部 criterion 通过
missing_evidence_answer    → 对应 Primary Intent 失败
plausible_wrong_answer     → 对应 Dodged Bullet 或关键 criterion 失败
```

若 judge 不能稳定区分三者，说明 rubric 或 judge prompt 不合格，任务不能进入训练集。

## 9. 困难度判定

### 9.1 结构准入

必须先满足第 2、5、6 节，才能进入困难候选池。模型失败不能挽救一步题、坏题或证据不足的 gold。

### 9.2 Golden V0 校准

在少量已确认正确的候选上，用 OpenAI 强模型和本地强 VLM 试答，以便：

- 找出仍能一步完成的伪困难题；
- 发现常见的真实失败模式；
- 调整 generator prompt；
- 为本地 difficulty predictor 建立标签。

### 9.3 大规模生产

全量阶段使用：

```text
结构准入规则
+ 目标 base model 试答
+ 本地 difficulty predictor
```

OpenAI 强模型只对按领域、任务模板和证据类型分层抽取的样本做审计。批量样本必须区分 `difficulty_predicted` 和 `difficulty_verified`。

## 10. 与额外 benchmark 的关系

额外 benchmark 只补充操作模板和评测切片：

- MMLongBench-Doc：跨页证据和长文档检索；
- TAT-QA/FinQA：表格与正文联合数值推理；
- ChartQAPro/CharXiv：真实图表、假设问题和复杂视觉推理；
- DUDE/MP-DocVQA：多页文档问答；
- OmniDocBench：表格、公式、阅读顺序和 bbox 解析质量。

最终准入仍以 GDP.pdf 的原则为主：专业真实性、正确 evidence grounding、多处控制性证据、实质性错误检查和严格 atomic rubric。

## 11. 生成反馈指标

每个 generator prompt 版本至少报告：

- 一步任务拒绝率；
- evidence graph 合格率；
- gold correctness gate 通过率；
- rubric 单元测试通过率；
- 目标 base model All-pass；
- Golden 审计中的强模型关键失败率；
- 坏题率和错误 gold 率；
- 各任务模板的训练后增益。

只有当“真实困难率上升”且“坏题率、错误 gold 率不上升”时，prompt 修改才算有效。
