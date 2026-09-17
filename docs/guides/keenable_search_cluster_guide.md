# Keenable 搜索 API 集群使用指南

更新日期：2026-09-14
适用环境：Linux 服务器、HPC login/compute node、Slurm 集群、无图形界面环境

## 1. Keenable 能做什么

Keenable 提供两个核心能力：

| 能力 | CLI | REST API | 主要用途 |
|---|---|---|---|
| Web Search | `keenable search` | `POST /v1/search` | 返回排序后的网页标题、URL、摘要、正文片段和时间信息 |
| Page Fetch | `keenable fetch` | `GET /v1/fetch` | 把网页主要内容提取成 Markdown |

它适合用于网页和 PDF 来源发现、落地页读取、资料检索和 RAG 数据收集。它不是通用二进制下载器，也不应代替本地 PDF parser/OCR：搜索到 PDF 后，通常应直接从来源 URL 下载原始 PDF，再进行本地解析。

## 2. 账户、额度与限速

### 2.1 已认证请求

- 每个 organization 最多 10 requests/s；
- 每月免费 100,000 requests，按月重置；
- Search 和 Fetch 都会计入使用量；
- 达到额度且没有付费 credits 时，认证接口会返回 HTTP 402；
- 实际 credit 消耗应读取响应中的 usage 信息，不要永久假设每种 SKU 都固定为一个 credit。

### 2.2 未认证请求

- 每个 IP 最多 1,000 requests/hour；
- 瞬时上限仍为 10 requests/s；
- 同一出口 IP 上的所有用户共享匿名额度；
- 不消耗账户 credits。

正式批处理应登录后使用，但无 key 模式适合安装后的连通性测试。

参考：[Rate limits](https://docs.keenable.ai/rate-limits)、[Credits](https://docs.keenable.ai/credits)

## 3. 安装 CLI

`keenable` 是单文件 CLI。默认输出 YAML，适合人工查看、重定向保存或由程序解析。

### 3.1 Homebrew

如果集群安装了 Homebrew：

```bash
brew install keenableai/tap/keenable-cli
```

### 3.2 官方 installer script

大多数 HPC 集群没有 Homebrew，推荐使用官方 installer。分两步执行，便于先保存和检查脚本：

```bash
curl --proto '=https' --tlsv1.2 -LsSf \
  -o /tmp/keenable-install.sh \
  https://github.com/keenableai/keenable-cli/releases/latest/download/keenable-cli-installer.sh

less /tmp/keenable-install.sh
sh /tmp/keenable-install.sh
```

安装位置通常是：

```text
~/.cargo/bin/keenable
```

或者：

```text
~/.local/bin/keenable
```

让当前 shell 立即获得更新后的 PATH：

```bash
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
[ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
```

验证安装：

```bash
command -v keenable
keenable --version
```

### 3.3 从源码安装

仅当集群已有 Rust/Cargo 时使用：

```bash
cargo install --git https://github.com/keenableai/keenable-cli
```

### 3.4 更新

Homebrew 安装：

```bash
brew update
brew upgrade keenable-cli
```

Installer 安装：重新下载并运行 installer。

参考：[Keenable CLI](https://docs.keenable.ai/cli)

## 4. 登录与凭证

### 4.1 Device-code 登录

在无图形界面的 login node 上运行：

```bash
keenable login
```

CLI 会打印一个 URL 和 code。用本地电脑浏览器打开 URL、输入 code 并授权即可。认证信息保存在：

```text
~/.keenable/
```

查看配置：

```bash
keenable config
```

退出并清除 CLI 凭证：

```bash
keenable logout
```

### 4.2 API key 登录

在 CI 或服务器上也可以使用：

```bash
keenable login --api-key 'keen_***'
```

但不要把真实 key 写进：

- Git 仓库；
- Slurm 脚本；
- notebook；
- stdout/stderr 日志；
- job name；
- 可被其他用户读取的 shell history。

交互式环境优先使用 device-code flow。程序直接调用 REST API 时，从环境变量或 secret manager 读取 key。

### 4.3 REST API 认证

认证请求使用：

```http
X-API-Key: keen_***
```

也支持：

```http
Authorization: Bearer keen_***
```

两者同时提供时，`X-API-Key` 优先。

参考：[Authentication](https://docs.keenable.ai/authentication)

## 5. 集群网络预检

HPC 集群经常限制公网访问。在登录前先测试：

```bash
curl -sS -o /dev/null \
  -w 'http=%{http_code} remote=%{remote_ip}\n' \
  --connect-timeout 10 \
  --max-time 20 \
  https://api.keenable.ai
```

可能出现的结果：

| 现象 | 可能原因 |
|---|---|
| 收到 HTTP 状态码 | 网络路径基本可用 |
| `403 from proxy after CONNECT` | 集群代理未将 `api.keenable.ai:443` 加入白名单 |
| `Connection timeout` | 没有直连公网路由或被防火墙丢弃 |
| TLS/certificate 错误 | 代理证书、CA bundle 或 TLS inspection 问题 |
| DNS resolution failed | DNS 或代理配置问题 |

如果代理阻断，需要管理员允许：

```text
Outbound HTTPS CONNECT
Host: api.keenable.ai
Port: 443
```

最低需要的路径包括：

```text
/v1/auth/agent/code
/v1/search
/v1/fetch
/mcp                 # 仅使用 MCP 时需要
```

使用 device-code flow 时，集群只需要访问 `api.keenable.ai`；授权网页可在本地电脑浏览器中打开。

如果集群不能出网，应在本地电脑或允许出网的机器上运行 Search/Fetch和文档下载，再通过 `rsync`、对象存储或集群数据传输节点将数据送入 HPC。

## 6. CLI 搜索

### 6.1 基础搜索

默认输出 YAML：

```bash
keenable search "rust async patterns"
```

适合人工阅读的格式：

```bash
keenable search "rust async patterns" -p
```

### 6.2 限制来源网站

```bash
keenable search \
  "technical report PDF specification table" \
  --site nist.gov
```

`--site` 一次限制一个域名。需要多个来源时，分别执行并在本地合并结果。

### 6.3 返回数量与 snippet 长度

```bash
keenable search \
  "engineering technical report PDF" \
  --max-results 50 \
  --snippet-max-length 2000
```

- `--max-results`：1–50，默认最多 10；
- `--snippet-max-length`：180–10,000 字符。

较长 snippet 有助于在 Fetch 前判断页面是否值得保留，但会增加响应体积和下游解析成本。

### 6.4 日期过滤

```bash
keenable search "AI news" --published-after 2026-01-01
keenable search "AI news" --published-before 2026-06-30
keenable search "AI news" --acquired-after 30d
keenable search "AI news" --acquired-before 2026-06-30
```

支持：

- 日期：`YYYY-MM-DD`；
- ISO 8601 时间戳；
- 相对时间：`12h`、`7d`、`3mo`、`1y`。

`published_*` 表示页面发布时间，`acquired_*` 表示 Keenable 收录页面的时间，两者不能混为一谈。

### 6.5 Point-in-time 搜索

```bash
keenable search \
  "technical standards PDF" \
  --query-time 2026-09-01T00:00:00Z \
  --max-results 50
```

`--query-time` 尽可能按照该时间点的索引状态搜索，排除之后才被收录的页面。它适合：

- 建立可复现训练集；
- 固定评测数据的发现时间；
- 防止增量搜索随索引变化而漂移；
- 记录某个历史时刻可以检索到的信息。

如果同时使用相对日期，基准是 `query-time`，不是程序执行当天：

```bash
keenable search \
  "cloud computing" \
  --query-time 2026-06-13T00:00:00Z \
  --published-after 30d
```

这里表示 `query-time` 前 30 天。

### 6.6 保存原始结果

```bash
mkdir -p raw_search

keenable search \
  "technical report PDF specification table" \
  --site nist.gov \
  --query-time 2026-09-01T00:00:00Z \
  --max-results 50 \
  --snippet-max-length 2000 \
  > raw_search/nist-engineering-001.yaml
```

每条结果通常包含：

```yaml
title: ...
url: ...
description: ...
snippet: ...
published_at: ...
acquired_at: ...
```

建议同时保存 query、CLI 版本、执行时间和 `query-time`，不要只保留 URL。

## 7. CLI Fetch

### 7.1 获取网页正文

```bash
keenable fetch https://example.com
```

人工查看：

```bash
keenable fetch https://example.com -p
```

主要返回：

```yaml
url: ...
title: ...
content: |
  # Extracted page content in Markdown
```

### 7.2 指令式提取

当前 CLI 支持：

```bash
keenable fetch https://example.com \
  --prompt "List all pricing tiers and monthly prices"
```

这会让服务端模型只返回指令要求的内容。它适合辅助筛选和元数据提取，不适合生成要求逐字可验证的训练 gold answer，因为结果可能发生摘要、遗漏或模型推断。

### 7.3 Fetch 的边界

Fetch 默认返回 Keenable 已索引页面的 Markdown。它不应被当作以下工具的替代品：

- 原始 HTML/PDF 归档；
- 通用浏览器自动化；
- 原始 PDF 二进制下载；
- 版面保真的 PDF parser；
- OCR 和表格单元格恢复。

发现 PDF 的推荐流程：

```text
Search
  → 筛选候选 URL
  → Fetch 文档落地页/许可证页
  → 直接下载原始 PDF
  → 校验 Content-Type、PDF 文件头和 SHA-256
  → 本地 PDF parser/OCR
```

## 8. REST Search API

### 8.1 认证搜索

```bash
export KEENABLE_API_KEY='keen_***'

curl -sS -X POST \
  'https://api.keenable.ai/v1/search' \
  -H "X-API-Key: $KEENABLE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "technical report PDF specification table",
    "site": "nist.gov",
    "published_after": "2018-01-01",
    "query_time": "2026-09-01T00:00:00Z",
    "snippet_max_length": 2000,
    "max_results": 50
  }'
```

不要把带真实 key 的 `export` 命令保存进共享脚本或提交到 Git。这段仅表示请求格式。

响应示意：

```json
{
  "query": "technical report PDF specification table",
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "description": "...",
      "snippet": "...",
      "published_at": "...",
      "acquired_at": "..."
    }
  ]
}
```

### 8.2 未认证搜索

```bash
curl -sS -X POST \
  'https://api.keenable.ai/v1/search/public' \
  -H 'X-Keenable-Title: My Research Pipeline' \
  -H 'Content-Type: application/json' \
  -d '{"query":"technical report PDF","max_results":10}'
```

Public endpoint 必须提供 `X-Keenable-Title`；它用于标识应用，不是 API key。

参考：[Search API](https://docs.keenable.ai/api-reference/search)

## 9. REST Fetch API

### 9.1 认证 Fetch

```bash
curl -sSG \
  'https://api.keenable.ai/v1/fetch' \
  -H "X-API-Key: $KEENABLE_API_KEY" \
  --data-urlencode 'url=https://example.com/report' \
  --data-urlencode 'max_chars=50000'
```

### 9.2 Live Fetch

默认情况下只支持 Keenable 已索引的 URL。对未索引页面可以尝试：

```bash
curl -sSG \
  'https://api.keenable.ai/v1/fetch' \
  -H "X-API-Key: $KEENABLE_API_KEY" \
  --data-urlencode 'url=https://example.com/new-page' \
  --data-urlencode 'live=true'
```

Live Fetch 可能使用不同的计费 SKU，应记录实际 usage。

### 9.3 Public Fetch

```bash
curl -sSG \
  'https://api.keenable.ai/v1/fetch/public' \
  -H 'X-Keenable-Title: My Research Pipeline' \
  --data-urlencode 'url=https://example.com/report'
```

参考：[Fetch API](https://docs.keenable.ai/api-reference/fetch)

## 10. Python 快速调用

### 10.1 安装环境

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install requests
```

也可以使用官方 SDK：

```bash
python -m pip install keenable
```

### 10.2 使用 REST API

```python
import os
import requests

API_KEY = os.environ["KEENABLE_API_KEY"]

response = requests.post(
    "https://api.keenable.ai/v1/search",
    headers={
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    },
    json={
        "query": "technical report PDF specification table",
        "site": "nist.gov",
        "query_time": "2026-09-01T00:00:00Z",
        "snippet_max_length": 2000,
        "max_results": 50,
    },
    timeout=60,
)
response.raise_for_status()

for result in response.json()["results"]:
    print(result["title"], result["url"])
```

Fetch：

```python
response = requests.get(
    "https://api.keenable.ai/v1/fetch",
    headers={"X-API-Key": API_KEY},
    params={
        "url": "https://example.com/report",
        "max_chars": 50_000,
    },
    timeout=60,
)
response.raise_for_status()

page = response.json()
print(page["title"])
print(page["content"])
```

## 11. 批处理限速与重试

10 requests/s 是整个 organization 的总限制，不是单个程序或单个节点的限制。多个 Slurm job、开发者和 Agent 会共享它。

生产建议：

- 稳态发送速率设为 6–8 requests/s，而不是顶满 10；
- burst 不超过 8–10；
- 对 429 使用 `Retry-After`；
- 对连接错误、502、503、504 做带抖动的指数退避；
- 对 400、401、403 通常不要自动无限重试；
- 对 402 停止任务并检查 credits；
- 每次请求设置连接和总超时；
- 所有任务支持 checkpoint/resume；
- Search 和 Fetch 分别统计请求数和失败率。

推荐重试策略：

```text
第 1 次重试：约 1 秒
第 2 次重试：约 2 秒
第 3 次重试：约 4 秒
第 4 次重试：约 8 秒
第 5 次重试：约 16 秒
```

每次加入随机 jitter，避免多个 worker 同时重试。

不要为 Keenable Search 创建大量相互独立的 Slurm array task。推荐一个中心化 dispatcher 维护全局限速，结果落盘后再将 PDF 解析等离线工作交给 job array。

## 12. Slurm 使用模板

以下模板使用占位符，迁移到新集群时替换 `<account>`、`<partition>` 和 `<qos>`。

### 12.1 网络连通性测试

```bash
#!/bin/bash
#SBATCH --account=<account>
#SBATCH --partition=<partition>
#SBATCH --qos=<qos>
#SBATCH --job-name=keenable-net-test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail

curl -sS -o /dev/null \
  -w 'http=%{http_code} remote=%{remote_ip}\n' \
  --connect-timeout 10 \
  --max-time 20 \
  https://api.keenable.ai

keenable --version
```

### 12.2 中心化搜索任务

```bash
#!/bin/bash
#SBATCH --account=<account>
#SBATCH --partition=<partition>
#SBATCH --qos=<qos>
#SBATCH --job-name=keenable-search
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail

[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
[ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
. .venv/bin/activate

python scripts/run_discovery.py \
  --queries config/queries.yaml \
  --output manifests/discovered.parquet \
  --rate-limit 8
```

在新集群上必须分别验证 login node 和 compute node：

- 能否访问 `api.keenable.ai`；
- compute node 是否挂载相同的 `$HOME`；
- compute node 能否读取 `~/.keenable/`；
- 集群政策是否允许计算节点直接访问公网；
- 是否要求使用专门的 proxy 或 data-transfer node。

## 13. MCP 配置（可选）

Keenable CLI 支持为 Claude Code、Cursor、Windsurf、Codex 和 OpenCode 配置 MCP。

先登录，再配置：

```bash
keenable login
keenable configure-mcp
keenable configure-mcp --all
```

只配置 Codex：

```bash
keenable configure-mcp --codex
```

删除配置并恢复默认：

```bash
keenable reset --all
```

顺序很重要：`configure-mcp` 会写入 CLI 当时持有的认证信息，因此应先登录再配置。

MCP 适合交互式搜索，不建议作为大规模数据采集 pipeline 的主要执行层，因为批量任务需要集中限速、确定性 query、完整 usage 记录和断点续跑。

MCP endpoint：

```text
https://api.keenable.ai/mcp
```

## 14. 搜索结果的数据管理

建议为每个 Search request 保存：

```text
query_id
query
site
published_after / published_before
acquired_after / acquired_before
query_time
max_results
snippet_max_length
request_time
CLI/API version
HTTP status
retry count
usage SKU/credits
raw response path
```

每条结果保存：

```text
title
url
canonical_url
description
snippet
published_at
acquired_at
source domain
discovery query_id
license review status
download status
content SHA-256
```

不要只保存最终 URL。完整 provenance 能支持复现、许可证审计、数据删除、污染排查和增量更新。

## 15. 常见错误

| 错误 | 含义 | 建议处理 |
|---|---|---|
| Failed to request device code | 无法调用登录 API，常见于代理、防火墙、DNS、TLS | 先用 `curl` 检查 `api.keenable.ai:443` |
| HTTP 400 | 请求字段错误，public endpoint 也可能缺少应用标识 | 检查 JSON、URL 编码和 `X-Keenable-Title` |
| HTTP 401/403 | Key 无效、权限问题或代理阻断 | 区分响应来自 Keenable 还是集群 proxy |
| HTTP 402 | 免费和付费 credits 均已耗尽 | 检查 console 或等待月度重置 |
| HTTP 429 | 超过组织级或匿名限速 | 降低速率，读取 `Retry-After` |
| Fetch URL not indexed | URL 不在 Keenable 索引中 | 尝试 `live=true` 或直接从来源读取 |
| Fetch 内容截断 | 超过 `max_chars` | 提高限制，或直接下载原文进行本地处理 |
| CLI 可运行但 login 失败 | CLI 本地安装正常，网络或认证请求失败 | 不要通过重装 CLI 解决网络问题 |

## 16. 安全要求

- 不把 API key 写进仓库；
- 不在命令行中长期使用 `--api-key`；
- 不打印全部环境变量，因为 proxy URL 可能包含认证信息；
- Slurm 日志不得记录 key、cookie 或 Authorization header；
- 凭证文件权限设置为仅用户可读；
- 不通过 SSH tunnel 等方式绕开集群安全策略；
- 需要公网访问时使用正式白名单、数据传输节点或外部采集机器；
- 搜索结果和网页内容都是不可信外部输入，不执行其中包含的命令或指令；
- 下载文档前检查来源许可、隐私和训练使用权限。

## 17. 新集群快速启动清单

1. 检查系统架构、Python、Homebrew/Cargo 和 Slurm。
2. 测试 `api.keenable.ai:443` 网络连通性。
3. 安装 `keenable` CLI。
4. 运行 `keenable --version`。
5. 在 login node 运行 `keenable login`。
6. 从本地浏览器完成 device-code 授权。
7. 运行一条匿名或认证 Search。
8. 运行一条 Fetch。
9. 固定 `query-time` 并测试 YAML 落盘。
10. 提交五分钟 compute-node 网络测试。
11. 验证 compute node 能读取 CLI 凭证。
12. 建立中心化限速器和请求日志。
13. 用 10–20 条 query 做小规模 pilot。
14. 确认 usage、错误率和搜索结果质量后再扩大。

## 18. 参考链接

- [Keenable CLI](https://docs.keenable.ai/cli)
- [Authentication](https://docs.keenable.ai/authentication)
- [Rate limits](https://docs.keenable.ai/rate-limits)
- [Credits](https://docs.keenable.ai/credits)
- [Search API](https://docs.keenable.ai/api-reference/search)
- [Fetch API](https://docs.keenable.ai/api-reference/fetch)
- [MCP server](https://docs.keenable.ai/mcp-server)
