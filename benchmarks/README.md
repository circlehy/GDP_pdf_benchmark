# Benchmark 资产隔离区

本目录用于保存 GDP.pdf 等独立评测资产。除本说明外，目录内容全部由 `.gitignore` 排除。

## GDP.pdf 下载

在仓库根目录运行：

```bash
python3 scripts/benchmarks/download_gdp_pdf.py
```

默认输出：

```text
benchmarks/gdp_pdf/
├── source/                 # Hugging Face 官方 snapshot
│   ├── README.md
│   ├── data.parquet
│   └── pdfs/
└── manifest.json           # repo、commit、时间、文件大小和 SHA-256
```

下载器先将 `main` 解析成不可变 commit SHA，再下载该 snapshot。再次运行会复用本地文件并重新生成 manifest。

## 使用边界

- 只用于 benchmark 研究、评测 runner、难度校准和污染检测；
- 不复制到 `data/`、`raw_pdfs/`、`parsed/` 或训练导出目录；
- production generator、gold generator 和训练 verifier 默认禁止读取本目录；
- 不对问题、rubric、reference answer 或模型回答做改写以生成 SFT；
- 训练数据发布前，用文件 hash、文本/图像 fingerprint 和 prompt 相似度与本目录反向查重；
- 第三方 PDF 保留原始权利，benchmark 仓库的代码或元数据许可不能自动延伸到其中的 PDF。

## 建议的配置隔离

未来实现中分别维护：

```text
configs/runs/gdp_eval.yaml       # 允许读取 benchmarks/gdp_pdf
configs/runs/golden_v0.yaml      # 明确拒绝 benchmarks 路径
configs/runs/training_pilot.yaml # 明确拒绝 benchmarks 路径
```

训练 pipeline 应在路径校验层拒绝任何解析后位于 `benchmarks/` 下的输入，而不只依赖操作人员约定。
