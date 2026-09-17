# Local Multimodal Generator Shortlist

更新时间：2026-09-17
用途：为 GDP-like PDF SFT pipeline 选择可本地部署的 generator/verifier 候选。

## 结论

首轮建议同时部署或租用短时实例测试以下三档：

1. **默认性价比候选：Qwen3.6-35B-A3B-FP8**；
2. **同规模稳定性对照：Qwen3.6-27B-FP8**；
3. **质量升级候选：Qwen3.5-122B-A10B-FP8**。

另保留 **Qwen3-VL-30B-A3B-Thinking** 作为偏视觉推理的旧一代基线。最新的
**Kimi-K3** 用作开放权重能力上限参照，不建议作为当前大规模本地生成主力。

这个排序不是通用聊天 leaderboard 排名，而是针对本项目的工程判断：模型必须同时处理
大量完整页面图像、完整 OCR 文本、长上下文、严格 JSON schema 和多步证据任务。最终选择必须
由同一批 PDF 的 accepted-task/GPU-hour 决定。

厂商自报分数可用于初筛：Qwen3.6-35B-A3B 在 OmniDocBench1.5 / CC-OCR 上报告
89.9 / 81.9，Qwen3.5-122B-A10B 报告 89.8 / 81.8；后者另外报告
MMLongBench-Doc 59.0、OCRBench 92.1。两者在短文档识别榜上的差距很小，进一步说明不能仅凭
总参数选择 122B，必须测本项目的多页证据任务。这些数字来自各自 model card，并非独立复测。

## 候选比较

| 模型 | 架构与上下文 | 优点 | 主要风险 | 本项目定位 |
|---|---|---|---|---|
| Qwen3.6-35B-A3B-FP8 | 35B 总参数、3B 激活；原生 262,144，YaRN 可扩到约 1.01M | 最新 Qwen 开放多模态 MoE；吞吐/权重规模较均衡；Apache-2.0；vLLM/SGLang 支持 | 512K 不是原生窗口；超长多图输入仍需要较大 KV/视觉缓存；必须验证 JSON 稳定性 | **首选 bake-off 主力** |
| Qwen3.6-27B-FP8 | 27B dense；原生 262,144，可扩到约 1.01M | dense 路径通常更稳定；同为最新 Qwen3.6；Apache-2.0 | 每 token 激活 27B，吞吐和生成成本可能明显高于 A3B；官方长上下文部署同样偏多卡 | **质量/稳定性对照** |
| Qwen3.5-122B-A10B-FP8 | 122B 总参数、10B 激活；原生 262,144，可扩到约 1.01M | 更高容量，适合复杂 gold、rubric 和跨页推理 | 权重和 KV cache 成本显著提高；不应在未证明收益前全量使用 | **困难样本升级层** |
| Qwen3-VL-30B-A3B-Thinking | 30B 总参数、3B 激活；原生 256K，可扩到 1M | 专门强化视觉、空间和多模态 reasoning；vLLM/SGLang 支持；Apache-2.0 | 代际较旧；长文档 JSON/任务生成能力需实测 | **视觉推理基线** |
| Kimi-K3 | 2.8T 总参数、104B 激活；原生 1,048,576；仓库约 1.56TB | 2026-09 最新开放权重原生多模态长上下文模型之一；无需位置外推覆盖 512K | 多节点部署、存储和通信成本极高；Kimi 自定义许可；不符合当前性价比目标 | **能力上限参照，不作为主力** |

## 关于硬件成本

不能只用“激活参数”估算显存。MoE 的全部专家权重仍需驻留或分层加载，长上下文还会消耗
KV cache、视觉 token cache 和运行时 workspace。

- Qwen3.6-35B-A3B 的 vLLM recipe 把 FP8 短上下文列为可单卡，但模型官方 262K 示例使用
  8-way tensor parallel；本项目若开启约 512K，部署预算应先按多张 80GB GPU 规划，再通过
  prefix caching、batch=1 和实际页面 token 做压测。
- Qwen3.6-27B 虽然权重规模略小，但 dense 激活使生成吞吐可能不如 35B-A3B。
- 122B-A10B 应按质量升级池使用，例如只处理 35B-A3B 生成失败、证据复杂或人工标记的文档。
- Kimi-K3 权重仓库约 1.56TB，即使低精度也属于多节点系统，当前不应为了“最新”直接部署。

## 与当前三份 PDF 的关系

当前 provisional accounting（不是最终 tokenizer 结果）：

| 页数 | text-only 输入估算 | 150 DPI multimodal 输入估算 |
|---:|---:|---:|
| 99 | 76,254 | 326,180 |
| 88 | 65,754 | 287,184 |
| 23 | 39,309 | 96,827 |

因此 99 页和 88 页样本可能超过 Qwen 默认 262K 服务窗口。若选择 Qwen3.6，必须启用并验证
YaRN 长上下文；不能在请求阶段静默丢页。也可以把 120 DPI 作为受控对照，但只有在确认细字、
图表和工程图可读性没有明显下降后，才能改变 canonical delivery 设置。

## 决策实验

不要直接依据厂商总榜分数决定模型。对每个候选使用完全相同的 frozen input package：

1. 先在现有 3 份 PDF 上各生成 1 个候选；
2. 记录 schema 成功率、完整输入成功率、证据 bbox/page 有效率、静态 gate 通过率；
3. 用 OpenAI verifier 和人工复核检查 gold、claim、derivation 与 rubric；
4. 记录 prefill 时间、decode tokens/s、峰值显存、失败重试和 GPU-hour；
5. 比较 `accepted tasks / GPU-hour` 与 `人工修正分钟 / accepted task`；
6. 如果 35B-A3B 的 accepted rate 接近 122B-A10B，则主力用 35B，122B 只做升级路由；
7. 如果 27B dense 的正确率提升不足以抵消吞吐差距，则不保留为生产主力。

建议的初始 go/no-go：优先部署 **Qwen3.6-35B-A3B-FP8** 做 bake-off，但在完成上述三文档
对照前，不把它写死为 production generator。

## 主要资料

- [Qwen3.6-35B-A3B model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [Qwen3.6 vLLM recipe](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.6-35B-A3B.yaml)
- [Qwen3.6-27B model card](https://huggingface.co/Qwen/Qwen3.6-27B)
- [Qwen3.5-122B-A10B model card](https://huggingface.co/Qwen/Qwen3.5-122B-A10B)
- [Qwen3-VL-30B-A3B-Thinking model card](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Thinking)
- [Kimi-K3 model card](https://huggingface.co/moonshotai/Kimi-K3)
- [IDP Leaderboard methodology](https://www.idp-leaderboard.org/details/)

注意：截至本次检查，通用 VLM leaderboard 和 IDP leaderboard 未必覆盖所有 2026-09 最新
开放模型；厂商 model card 的分数也不是独立评测。因此它们只用于 shortlist，不作为最终选型证据。
