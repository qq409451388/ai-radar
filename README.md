# AI Radar · AI 工程情报雷达

个人 AI 技术动态追踪与认知覆盖分析工具。每天采集 AI 领域的官方新闻、公告与 GitHub Release，将其抽象、合并为独立的「知识变化点」，并读取你私有 GitHub 记忆仓库中的 Markdown 客观事实，动态判断你对各知识变化点的覆盖程度与对各 AI 技术领域的当前了解度。

新版界面按任务而不是数据库表组织为：今日雷达、情报收件箱、知识地图、我的进展、自动化与设置。默认以最近 90 天为当前跟进窗口，同时保留终身覆盖分数和每次覆盖评估历史。

## 首次使用

只需要安装 Git 和 Python 3.11+，其余工作由启动脚本完成。

### 1. 克隆项目

```bash
git clone https://github.com/qq409451388/ai-radar.git
cd ai-radar
```

### 2. 一键启动

macOS / Linux：

```bash
./run.sh
```

如果系统提示没有执行权限，只需执行一次：

```bash
chmod +x run.sh
./run.sh
```

Windows PowerShell：

```powershell
.\run.bat
```

Windows CMD：

```bat
run.bat
```

也可以在文件管理器中双击 `run.bat`。两个脚本都会自动完成：

1. 创建项目独立的 `.venv` 虚拟环境。
2. 安装或更新 `requirements.txt` 中的依赖。
3. 启动 AI Radar。

终端出现启动成功信息后，打开：

```text
http://localhost:8501
```

### 3. 完成首次配置

第一次打开会自动进入「平台配置」页面，需要填写：

- OpenAI-compatible API 地址、API Key 和模型名。
- GitHub Fine-grained Token。
- 保存 GPT 交流记录的私有仓库，格式为 `owner/repo`。
- 可选的时区、分析批次和定时任务设置。

点击「保存并进入雷达」后，配置会写入操作系统用户目录，不会写入项目仓库。进入首页后点击「运行今日更新」，系统会开始采集资讯、同步记忆并生成第一批知识变化点。

### 后续启动与更新

后续启动仍然只需要：

```bash
# macOS / Linux
./run.sh
```

```powershell
# Windows
.\run.bat
```

更新项目：

```bash
git pull
./run.sh
```

Windows 更新后运行 `run.bat`。用户配置和 SQLite 数据不会因 `git pull` 被覆盖。按 `Ctrl+C` 可以停止服务。

```
Agent 架构与编排       ████████░░ 82%  ↓3
MCP / Tools / Skills  █████████░ 91%  ↓1
Coding Agent 与 CLI   ██████░░░░ 64%  ↓8
Memory / 个人知识库    ███████░░░ 73%  ↓6
```

## 项目目标

- 新闻不是评分单位，「知识变化点」才是。
- 多篇报道同一件事时只形成一个知识变化点。
- 用户 Markdown 只保存客观事实，不保存评分。
- 评分只能追溯到具体知识变化点和具体个人事实；无充分事实时判定为未覆盖。
- 行业出现新变化而事实记录未覆盖时，对应领域分数自然下降。

## 核心概念

| 概念 | 说明 |
| --- | --- |
| 知识变化点 (change_point) | 一条真实的产品/协议/能力变化，多篇报道合并为一个点 |
| 个人事实 (profile_fact) | 从你 GitHub 记忆仓库 Markdown 中抽取的客观事实 |
| 覆盖等级 (coverage_level) | NONE / AWARE / UNDERSTOOD / PRACTICED |
| 覆盖系数 | NONE=0.00、AWARE=0.25、UNDERSTOOD=0.65、PRACTICED=1.00 |
| 领域快照 (topic_snapshot) | 每日领域评分与相对前一日变化 |

## 技术架构

- Python 3.11+ / Streamlit / SQLite / SQLAlchemy 2.x / Pydantic 2
- feedparser + httpx（采集） / APScheduler（定时）
- OpenAI-compatible API（分析、抽取、覆盖评估），严格 JSON + Pydantic 校验
- 不使用向量数据库、Redis、Celery、前后端分离、用户登录、LangChain 等

```
ai-radar/
├── app.py                      Streamlit 入口
├── pages/                      5 个任务页面（home / inbox / knowledge / progress / automation）
├── ai_radar/
│   ├── collectors/             RSS、GitHubRelease 采集器
│   ├── profile/                GitHub Contents 同步 + 事实抽取
│   ├── llm/                    LLM 客户端、Schema、Prompt
│   ├── services/               采集/分析/去重/覆盖/评分
│   ├── scheduler/              APScheduler 定时任务
│   ├── models/                 SQLAlchemy 模型（含 LLM 缓存与用量台账）
│   ├── repositories/            job_log 助手
│   ├── config.py / database.py / bootstrap.py / orchestrator.py / ui.py
├── config/
│   ├── app.example.yaml        不含密钥的用户配置模板
│   └── default_sources.yaml    默认领域与资讯源
├── tests/                      pytest 自动化测试
├── requirements.txt / .env.example（仅环境覆盖示例）
├── run.sh / run.bat            macOS、Linux、Windows 一键启动
```

## 手动安装（高级）

通常不需要执行本节，直接运行 `run.sh` 或 `run.bat` 即可。

```bash
cd ai-radar
python3.11 -m venv .venv          # 或 python3.12
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

首次启动会自动建表并写入 `config/default_sources.yaml` 中的 8 个领域与默认资讯源，然后进入「平台配置」页面填写 AI API 和 GitHub。

## 用户配置

桌面使用时，密钥和设置保存在操作系统的用户配置目录：

| 平台 | 配置文件 |
| --- | --- |
| macOS | `~/Library/Application Support/AI Radar/config.yaml` |
| Windows | `%APPDATA%\AI Radar\config.yaml` |
| Linux | `~/.config/ai-radar/config.yaml` |

- 首次进入会自动打开「平台配置」页面。
- 仓库只包含不带密钥的 `config/app.example.yaml`。
- 配置文件以仅当前用户可读写的权限创建（支持该权限模型的平台上为 `0600`）。
- 检测到旧项目 `.env` 时，会只读加载已有值；在配置页保存后写入用户配置文件。旧 `.env` 不会自动删除。
- 可用 `AI_RADAR_CONFIG_DIR` 自定义配置目录，或用 `AI_RADAR_CONFIG_PATH` 指定完整配置文件路径。

配置优先级：

```text
进程环境变量 > 用户 config.yaml > 旧 .env（仅迁移兼容）> 默认值
```

## 环境变量覆盖

环境变量主要用于 CI、容器和临时覆盖。应用不再自动将项目 `.env` 注入进程环境。

| 变量 | 说明 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI 兼容 API 根地址（不含 `/chat/completions`） |
| `LLM_API_KEY` | LLM 密钥 |
| `LLM_MODEL` | 模型名，默认 `qwen-plus` |
| `LLM_TIMEOUT_SECONDS` | 单次调用超时，默认 120 |
| `GITHUB_TOKEN` | GitHub Releases 采集用 Token（可选，无则匿名限流） |
| `PROFILE_GITHUB_REPO` | 记忆仓库 `owner/repo`，如 `owner/private-memory` |
| `PROFILE_GITHUB_REF` | 分支，默认 `main` |
| `PROFILE_GITHUB_PATH_PREFIX` | 读取目录前缀，留空读整个仓库 |
| `PROFILE_GITHUB_TOKEN` | 记忆仓库 Token（留空则回退到 `GITHUB_TOKEN`） |
| `AI_RADAR_DB_PATH` | SQLite 路径，默认 `data/ai_radar.db` |
| `AI_RADAR_TIMEZONE` | 时区，默认 `Asia/Shanghai` |
| `AI_RADAR_SCHEDULER_ENABLED` | 是否启用定时任务，默认 `true` |
| `AI_RADAR_HTTP_TIMEOUT` | 外部 HTTP 超时秒数，默认 20 |
| `AI_RADAR_ANALYZE_BATCH_SIZE` | 单次最多分析的资讯数，默认 30 |
| `AI_RADAR_SCORE_WINDOW_DAYS` | 当前跟进评分窗口，默认 90 天 |
| `AI_RADAR_MAX_ASSESSMENT_FACTS` | 单知识点最多发送的候选事实数，默认 24 |

### OpenAI-compatible API 配置

推荐直接在首次进入的页面填写。对应 YAML 示例：

```yaml
llm:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key: 你的 API Key
  model: qwen-plus
  timeout_seconds: 120
```

兼容任何 OpenAI `/chat/completions` 协议的服务（DeepSeek、Moonshot、OpenAI 官方等），把 `LLM_BASE_URL` 改为对应地址即可。

### GitHub 私有记忆仓库配置

```yaml
github:
  token: github_pat_xxx

profile:
  repo: owner/private-memory
  ref: main
  path_prefix: ""
  token: ""  # 留空复用 github.token
```

- 仅通过 GitHub Contents API **只读**访问，应用不会创建/修改/删除仓库文件。
- 递归读取仓库内所有 `.md` 文件；`PATH_PREFIX` 非空时只读该子目录。
- 分开记录已抓取 hash 与已抽取 hash；未变化不重复抽取，抽取失败会在下次同步重试。
- 同步失败时保留上一次成功的事实，页面会显示失败原因与最后一次成功时间。

#### GitHub Token 最小权限建议

- 用 Fine-grained personal access token，仅授权 **记忆仓库** 的 `Contents: Read-only`。
- 若同时用于 GitHub Releases 采集，则对该仓库加 `Metadata: Read` 即可（公开仓库可不配 Token，但会受匿名限流 60 次/小时）。
- Token 通过首次配置页面写入用户配置目录，不会写入代码或日志。

## 页面说明

服务启动后，左侧导航包含：

- 「今日雷达」直接查看优先知识缺口并一键运行今日更新。
- 「情报收件箱」处理知识变化与资讯积压。
- 「知识地图」查看评分依据、官方来源和覆盖变化历史。
- 「我的进展」查看 GPT 记忆抽取出的研究、设计、实现和生产证据。
- 「自动化与设置」管理任务、资讯源、Token 用量与响应缓存。

### 手动流水线

「自动化与设置」→「任务流水线」提供三种更新范围：

- 完整更新：采集资讯 → AI 分析 → 同步记忆 → 关联评估 → 更新快照。
- 仅更新情报：采集资讯 → AI 分析 → 关联评估 → 更新快照。
- 仅同步记忆：同步记忆 → 更新快照。

手动流水线在后台线程中运行，切换到其他页面或关闭浏览器标签不会中断；侧边栏会继续显示当前步骤和总体进度，任务页每 2 秒刷新一次处理数量、耗时和错误。为避免重复消耗 Token，同一时间只允许一条手动流水线运行。关闭运行 `run.sh` / `run.bat` 的终端或停止应用进程会中断任务，下次启动时会将其标记为「已中断」，可重新运行。

## 默认数据初始化

首次启动自动写入：

- 8 个一级领域（Agent 架构与编排、MCP / Tools / Skills、Coding Agent 与 CLI、模型能力与模型路由、Memory / 个人知识库、企业 AI 落地、AI 安全评测与可观测性、Java AI 生态）。
- 默认资讯源（仅官方博客/GitHub Release；不确定是否有稳定 RSS 的源默认停用）。

可在「自动化与设置」的「资讯源」页签中新增、编辑或启停，也可以调整 `config/default_sources.yaml` 后重启。

## RSS 和 GitHub Release 添加方式

**页面**：「自动化与设置」→「资讯源」→ 新增来源，填写名称、类型（RSS / GITHUB_RELEASE）、URL、仓库（仅 GitHub Release）和默认领域。

**配置文件**：编辑 `config/default_sources.yaml`：

```yaml
rss_sources:
  - name: 我的 RSS
    url: https://example.com/rss.xml
    default_topic: 模型能力与模型路由
    enabled: true

github_release_sources:
  - name: 我的仓库
    url: https://github.com/owner/repo
    repository: owner/repo
    default_topic: Coding Agent 与 CLI
    enabled: true
```

## 评分算法

当前跟进覆盖（默认最近 90 天）和终身覆盖均使用：

```
Σ(知识变化点重要度 × 覆盖系数)
────────────────────────── × 100
Σ(当前有效知识变化点重要度)
```

- 仅计入 `change_point.status = ACTIVE` 的知识点。
- 新知识点创建后默认覆盖系数为 0（NONE）。事实不变、分母增加时分数自然下降。
- `DEPRECATED` 知识点不参与评分。
- 当前跟进覆盖只统计评分窗口内的变化，避免多年历史稀释近期信号。
- 同时显示重要知识缺口、实践率与平均跟进时延。
- 每天 23:00 保存快照并计算相对前一天的 `score_delta`。

示例：知识点 A(importance=5, PRACTICED=1.00) + B(importance=3, UNDERSTOOD=0.65) + C(importance=3, NONE=0)
= (5×1.00 + 3×0.65 + 3×0) / (5+3+3) × 100。

## 个人事实抽取规则

- 输入：文件路径、Markdown 标题层级、原文、行号。
- 只能抽取原文明确存在的事实，**不得**根据上下文补充未经记录的经历。
- 不得生成百分比/掌握度/熟练度/精通等主观评价。
- 每条事实带 `evidence_type`：DISCUSSION / RESEARCH / DESIGN / DEMO / IMPLEMENTATION / PRODUCTION / DECISION。
- 相同事实按 `fact_key` 与文本相似度去重；文件更新后消失的事实标记为 `active=false`，不物理删除。
- LLM 输出经 Pydantic 校验；最小无关输出和非标准重要度会自动归一化，其余失败进入退避重试队列。
- 非 NONE 覆盖必须匹配到真实事实；DISCUSSION 最高只能得到 AWARE。
- 覆盖评估采用追加历史，不再删除旧判断。
- 精确相同的 Prompt + 模型会命中 SQLite 持久缓存，不重复请求 LLM。

## 定时任务

| 时间 | 任务 |
| --- | --- |
| 08:00 | 采集全部资讯 → 按批次分析待处理资讯 |
| 09:00 | 同步 GitHub 记忆 → 重新抽取变更文件事实 → 重新评估受影响知识点 |
| 23:00 | 评估新增知识点 → 重新计算评分 → 保存今日快照 |

- 可通过 `AI_RADAR_SCHEDULER_ENABLED=false` 关闭。
- Streamlit 重载不会重复启动调度器（单例 + 锁保护）。
- 单个任务异常不影响调度器整体运行（每个任务被 `_safe` 包裹）。
- 调度器依附于 Streamlit 进程；应用关闭期间可在首页用「运行今日更新」补跑。

## 常见错误处理

| 现象 | 处理 |
| --- | --- |
| LLM 调用 401/403 | 检查 `LLM_API_KEY` 与 `LLM_BASE_URL` |
| LLM JSON 校验失败 | 常见字段偏差自动兼容；其余记为 `FAILED` 并按退避策略重试 |
| GitHub 401/403 | 检查 `PROFILE_GITHUB_TOKEN` 权限（需 `Contents: Read`） |
| GitHub 限流 403/429 | 该来源本次跳过，下次重试；建议配置 `GITHUB_TOKEN` |
| RSS 源 malformed | feedparser 容错解析，并在日志中告警 |
| 单个来源采集失败 | 仅记录 `last_error`，不影响其它来源 |
| 同步失败 | 保留上一次成功的事实，「今日雷达」显示失败原因与最后成功时间 |
| 调度器重复启动 | 已用单例 + 锁保护，无需手动处理 |

## 数据文件位置

- SQLite：`data/ai_radar.db`（由 `AI_RADAR_DB_PATH` 控制，相对项目根目录）
- 日志：标准输出 / Streamlit 控制台
- 用户配置：操作系统用户配置目录中的 `config.yaml`
- 仓库模板与默认源：`config/app.example.yaml`、`config/default_sources.yaml`

## SQLite 备份方式

```bash
# 在线备份（不停服）
sqlite3 data/ai_radar.db ".backup data/ai_radar.backup.db"

# 或直接复制（建议停服或低峰期）
cp data/ai_radar.db data/ai_radar.$(date +%Y%m%d).db
```

## 测试

```bash
.venv/bin/python -m pytest -q
```

测试覆盖评分算法、新增知识点致分数下降、DEPRECATED 排除、RSS/GitHub Release 去重、event_key 合并、SQLite 时区兼容、LLM 输出归一化、事实增量抽取与失败重试、证据等级硬约束、覆盖历史保留、LLM 持久缓存、跨平台用户配置与优先级、同步失败保留事实和快照 delta 计算。

## 限制与说明

- 第一版去重使用 `difflib` + 关键词交集 + 时间窗口，不引入向量数据库。
- 默认资讯源中不确定是否存在稳定 RSS 的来源默认停用，不编写复杂网页爬虫。
- 数据库使用 `create_all` 建表，结构便于后续接入 Alembic 迁移。
- 时间统一存储为 UTC，页面按 `AI_RADAR_TIMEZONE` 本地时区展示。
- 页面默认中文。
