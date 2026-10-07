# RTLens

![License](https://img.shields.io/badge/license-MIT-blue) ![Version](https://img.shields.io/badge/version-6.2.0-green) ![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

**RTLens 是给 FPGA 工程师和 AI 编程助手的 Verilog/SystemVerilog 代码智能引擎：把整个 RTL 工程解析成结构化符号数据库，同时以 LSP、MCP、REST、Web、TUI、CLI 六种接口提供层级树、端口一致性检查、变更影响分析与机器可读证据导出——让 AI 不用 grep 就能真正"看懂"你的 RTL，让工程师像查数据库一样查询模块、信号与例化关系。**

- 自身代码 100% 纯 Python 标准库，**零强制依赖**（`rtlens/*.py` 只 import 标准库），Python 3.8+ 开箱即用
- 双后端解析：内置 Python 解析器永远可用；检测到 Verible（C++）二进制时自动切换到更快、语法覆盖更完整的后端，对上层所有接口行为一致
- 可选增强：`psutil`（进程级性能采样，缺失自动降级）、Verible 二进制（语法 / Lint / 格式化）

## 为什么需要它

- **AI 助手读不懂 RTL**：Claude Code、Cursor 等 AI 工具面对 Verilog 工程只能 grep + 凭记忆猜模块名，答错端口、编造层级是常态。RTLens 把"谁例化了谁、这个信号谁驱动、端口接没接对"变成对索引的确定性查询，AI 拿到的是带 `file:line` 的事实，不是猜测。
- **Verilog 缺一个好用的语言服务器**：主流编辑器对 Verilog 的跳转定义、查找引用、语义高亮支持零散且依赖繁重。RTLens 一个 `python -m rtlens lsp` 就能接入任意 LSP 客户端，无需安装任何依赖。
- **跨工具传事实靠口口相传**：不同工具的行号基准（0-based / 1-based）、路径风格（绝对 / 相对）不一致，两个工具互相指控对方"造假"是真实发生过的事故（见 `docs/CROSS_ENGINE_PARITY.md`）。`rtlens evidence` 用冻结契约 `rtlens.evidence/1` 把行号双基准、root 相对 POSIX 路径、sha256 一次性说清楚。
- **现有工具链太重**：elaboration 级工具（Verilator / Yosys）能力强但要装环境、跑编译；RTLens 秒级索引、零安装，先解决"工程结构是什么"这一层的问题。

## 核心能力

| 能力 | 规模 | 说明 | 代码位置 |
|---|---|---|---|
| LSP 语言服务器 | 17 种请求方法 | 跳转定义、查找引用、自动补全、重命名、语义高亮（13 类 token × 6 修饰符）、代码折叠、CodeLens、嵌入提示、文档高亮、选择范围、格式化、工作区符号 | `rtlens/server.py`、`rtlens/semantic.py` |
| MCP 服务器 | 42 个工具 | 例化层级树、端口一致性检查、信号驱动源查询、变更影响分析、仿真日志解析（iverilog/verilator/vcs）、testbench/例化模板生成、Verible 状态与 Lint/格式化等 | `rtlens/mcp_server.py` |
| REST API | 39 个路由（GET 33 + POST 6） | 覆盖符号查询、层级、指标、端口检查、Lint、性能基准等 | `rtlens/api.py` |
| Web 仪表盘 | 10 个标签页 | 概览、模块、代码生成、信号追踪、Lint、层级、端口检查、依赖图、搜索、实时监控 | `rtlens/webui.py` |
| 终端界面 TUI | 17 条命令 | 在终端内交互式查询模块 / 端口 / 信号 / 例化 / 宏 / 约束 | `rtlens/tui.py` |
| CLI 分析命令 | 9 条 | `index` / `query` / `check` / `trace` / `metrics` / `context` / `template` / `parse` / `evidence` | `rtlens/__main__.py`、`rtlens/ai_tools.py` |
| 证据出口 | schema `rtlens.evidence/1` | 把整棵工程导出成机器可读、带 sha256 与双基准行号的证据包，供下游工具消费 | `rtlens/evidence.py`、`docs/EVIDENCE_CONTRACT.md` |
| 国产 FPGA 支持 | eLinx GTP 原语 | 内置常见 GTP 原语 stub（可经 `elinx_stubs/*.v` 扩展）；解析 SDC / XDC / PCF 约束，提供"信号 → 物理引脚"映射查询 | `rtlens/elinx.py`、`examples/elinx_demo/` |
| 双后端解析 | 自动选择 | 内置 Python 解析器（词法 + 语法，纯标准库）↔ Verible 后端（`verible-verilog-syntax --export_json` 的 CST → 索引），二进制缺失自动回退 | `rtlens/lexer.py`、`rtlens/parser.py`、`rtlens/preprocessor.py`、`rtlens/verible_backend.py` |

> LSP 的 17 种方法不含 `initialized` / `didOpen` / `didChange` / `didClose` 四个通知与 `publishDiagnostics` 推送；TUI 的 17 条不含内置 `help` / `quit`。

## 快速开始

**一行命令安装（推荐）**

```powershell
# Windows（PowerShell）
irm https://raw.githubusercontent.com/Kylanfang/RTLens/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/Kylanfang/RTLens/main/install.sh | bash
```

脚本自动完成：定位 Python ≥ 3.8 → 下载/定位源码 → `pip install -e .`（失败不阻塞，零依赖 cwd 方式也能跑）→ 导入自检 → `python -m rtlens setup` 写入 MCP 配置（见 `install.ps1:1-20` / `install.sh:1-16` 的行为注释）。已下载仓库时直接运行脚本即可；支持环境变量 `RTLENS_PROJECT`（要索引的工程目录）与 `RTLENS_TOOL`（只配置指定工具）。

**30 秒体验**

```bash
# 方式一：源码直接跑（零依赖，无需 pip）
python -m rtlens quickstart        # 索引内置示例 + 自动打开浏览器

# 方式二：pip 安装后使用 rtlens 命令
pip install -e .
rtlens quickstart
```

Windows 用户可直接双击 `start.bat`（macOS / Linux 用 `./start.sh`）。默认地址 `http://127.0.0.1:8765`，quickstart 默认索引 `examples/hierarchy`（缺失时回退整个 `examples/`，见 `rtlens/__main__.py:316-321`）。

**验证安装**

```bash
python -m rtlens --version         # → rtlens v6.2.0
python tests/run_tests.py          # 本仓库实测：470 passed, 0 failed
python -m rtlens index examples/hierarchy
```

## 接入 AI 助手（MCP）

一条命令自动检测 AI 工具、写入 MCP 配置并自测：

```bash
python -m rtlens setup             # --list-tools 只列出检测到的工具
```

自动探测支持：**ZCode**、Claude Code、Cursor、Cline、Windsurf、Workbuddy，以及 generic（`rtlens/__main__.py:96-98`）。

也可手动配置。**Claude Code / Cursor / Codex 等**，在项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "rtlens": {
      "command": "python",
      "args": ["-m", "rtlens", "mcp"]
    }
  }
}
```

**ZCode** 用嵌套 `mcp.servers` 结构且 schema 严格（多余字段被丢弃，路径需绝对路径）：用户级写 `~/.zcode/cli/config.json`，或工作区级建 `.zcode/config.json`：

```json
{
  "mcp": {
    "servers": {
      "rtlens": {
        "type": "stdio",
        "command": "<python 的绝对路径>",
        "args": ["-m", "rtlens", "mcp"],
        "cwd": "<rtlens 目录的绝对路径>",
        "timeoutMs": 60000
      }
    }
  }
}
```

配置完成后 AI 助手可以直接：查询例化层级树与模块详情（基于索引的精确结果，而非 grep 猜测）、检查例化端口与模块定义是否一致、变更后获得"该重跑哪些 testbench"的建议清单、按模块聚合解析 iverilog / verilator / vcs 仿真日志、按真实端口定义生成例化模板和 testbench 骨架。

更多材料：`AI_INSTALL_PROMPT.md`（复制给 AI 助手让它自动完成安装配置）、`配置指南_说人话版.md`（面向非专业用户）。

## 接入编辑器（LSP）

1. 在任意支持自定义 LSP server 的客户端扩展中，把服务端启动命令配置为：

   ```
   python -m rtlens lsp
   ```

2. 开启 semanticTokens 支持以获得语义高亮。

`vscode/settings.json` 是现成的接入模板（`rtlens.server.command` / `rtlens.server.args`）；详细配置见 `docs/manual.html`。

## 作为 Agent 技能使用（DSH 插件）

RTLens 同时打包为 **DSH skill-only 插件**（npm 包名 `rtlens-dsh`，`package.json` 声明 `dsh.bundle` 与 node ≥ 18）：安装后 agent 按技能名调用，技能文件 `skills/rtlens/SKILL.md` 教 agent 用零依赖 Python CLI（`index` / `query` / `context` / `check` / `trace` / `metrics` / `template` / `parse` / `evidence`）对 RTL 工程做证据优先分析——不需要起 MCP/LSP 服务。`lib/index.js` 提供 skill 根目录解析，`cordis.patch.yml` 向 DSH 注册 `rtlens-skill-filesystem` skill provider。

```bash
# 从 GitHub 安装（命令语法以 DSH 文档为准）
dsh plugin --profile <你的 profile> add github:Kylanfang/RTLens
```

## 证据出口（rtlens evidence）

`rtlens evidence` 把整棵 RTL 工程导出成一份机器可读、证据级的 JSON（schema id `rtlens.evidence/1`，契约冻结，全文见 `docs/EVIDENCE_CONTRACT.md`）。用途是**喂给别的工具**：同生态的硬件拓扑插件 hw-topo 直接消费这份事实，而不是各自再扫一遍源码、用启发式猜模块 / 例化 / 坐标。

```bash
python -m rtlens evidence <工程根目录> --json                 # 打到 stdout（单份可解析 JSON）
python -m rtlens evidence <工程根目录> -o evidence.json       # 落盘（stdout 为空，stderr 打一行摘要）
python -m rtlens evidence <工程根目录> --json -o evidence.json -D SIM -D W=8   # 传宏，-D 可重复
```

| 参数 | 说明 |
|---|---|
| `root`（位置参数） | 要索引的工程根目录；不是目录（含不存在）时 stderr 报错并以 **exit 2** 退出（`rtlens/__main__.py:202-204`，实测验证）——绝不返回一份"看起来合法"的空文档 |
| `-D NAME` / `--define` | 内置宏，可重复（`-D SIM`、`-D W=8`），`+define+` 语义，参与 `` `ifdef`` 求值——define 集不同，证据内容不同 |
| `-I PATH` / `--include-path` | `` `include`` 搜索路径，可重复 |
| `-o FILE` / `--out` | 写入该文件（不写 stdout） |
| `--json` | 把文档打到 stdout；`--compact` 单行 JSON（默认缩进 2 空格） |
| `--max-files N` | 最多索引 N 个文件（默认 5000，`rtlens/indexer.py:298`）；触顶在 `diagnostics.filesCapped` 如实披露 |
| `--max-signals N` | 单模块 signals 上限（默认 256；超出置 `signalsTruncated: true`） |
| `--max-connections N` | 单例化连接列表上限（默认 256；超出置 `connectionsTruncated: true`） |

消费方必须知道的两条坐标契约（`docs/EVIDENCE_CONTRACT.md` 规则 R1/R2）：

- **行号双基准同时给出**：`line1` 是 1-based（编辑器 / 人类），`line0` 是 0-based（LSP / 词法器原生），恒有 `line1 == line0 + 1`；文档里**不存在**裸 `line` 字段，消费方必须显式挑一个并写明挑了哪个。
- **路径是 root 相对 POSIX**（正斜杠、无盘符、无前导 `/`），绝对路径单独放在 `absPath`；每个源文件带 `sha256` 与 `bytes`。

实际运行（`python -m rtlens evidence examples/hierarchy --json`，节选）：

```json
{
  "schema": "rtlens.evidence/1",
  "tool": { "name": "rtlens", "version": "6.2.0" },
  "stats": { "files": 5, "modules": 4, "ports": 17, "signals": 6,
             "params": 2, "instances": 3, "topModules": ["positional_demo", "top"] },
  "files": [ { "path": "counter.v", "bytes": …, "lines": …, "sha256": "…" } ]
}
```

## 架构与工作方式

```
                 ┌────────────────────────────┐
                 │      WorkspaceIndex        │  ← 统一符号索引（rtlens/indexer.py）
                 │  模块 / 端口 / 信号 / 例化  │     含统计、引用查找、重命名
                 └──────────┬─────────────────┘
                            │ 解析结果回填（数据结构不变，上层接口无感）
        ┌───────────────────┴───────────────────┐
        │                                       │
  内置 Python 解析器                     Verible 后端（可选）
  lexer.py → preprocessor.py →          verible_backend.py 调用
  parser.py（纯标准库，永远可用）        verible-verilog-syntax --export_json
                                        的 CST 树 → 提取符号
```

- **一条解析流水线，六个出口**：`lexer.py`（词法）→ `preprocessor.py`（宏 / `` `include`` / `` `ifdef``，行数保持语义）→ `parser.py`（模块 / 端口 / 参数 / 信号 / 例化）→ `indexer.py` 的 `WorkspaceIndex`（统一符号数据库）→ `semantic.py`（语义高亮 / 折叠 / 高亮范围等派生数据）→ 同时供 `server.py`（LSP）、`mcp_server.py`（MCP）、`api.py`（REST）、`webui.py`（Web）、`tui.py`（TUI）与 `__main__.py` 的 CLI 命令消费。
- **后端自动选择**：`verible_backend.py` 检测到 Verible 二进制即走 C++ 后端，否则无缝回退内置解析器；对上层所有 MCP 工具、LSP 方法行为一致，无需用户干预。
- **AI 工具层**：`ai_tools.py` 封装端口一致性检查、信号追踪、设计指标、testbench / 例化模板生成等高层能力，CLI 的 `check/trace/metrics/template/context` 与 MCP 工具共用。
- **宏语义与真实编译器一致**：`` `define`` 按索引顺序跨文件累积（单编译单元语义）；`-D / +define+` 传入的内置宏参与 `` `ifdef`` 求值，defines 变化即重建索引。
- **自动配置**：`auto_setup.py` 实现 `rtlens setup` 的 AI 工具探测与 MCP 配置写入；`monitor.py` 提供性能采样（检测到 `psutil` 时进程级采样，否则降级）。

## 目录结构

| 顶层路径 | 作用 |
|---|---|
| `rtlens/` | 核心代码包：词法 / 预处理 / 解析 / 索引 / 语义 / LSP / MCP / REST / Web / TUI / 证据出口 / 自动配置 |
| `rtlens/verible/` | Verible 可选后端二进制（Windows 版 3 个 exe；**该目录被 `.gitignore` 排除出 git 追踪**，克隆后为空属正常，见"许可证"与 `THIRD_PARTY_NOTICES.md`） |
| `examples/` | 6 个演示工程：`counter`、`hierarchy`、`macros`、`soc_mini`、`test_design`、`elinx_demo`（含 PCF 约束示例） |
| `tests/` | `run_tests.py`（纯标准库测试套件）与 `test_webui_e2e.py`（Web UI 端到端） |
| `docs/` | `EVIDENCE_CONTRACT.md`（证据契约）、`CROSS_ENGINE_PARITY.md`（跨引擎等价性实测）、`TUTORIAL.md`（7 个实验教程）、`manual.html`（用户手册） |
| `skills/rtlens/` | DSH / Agent 技能文件 `SKILL.md`（命令手册 + 证据规则 + 已知边界） |
| `lib/`、`cordis.patch.yml`、`package.json` | DSH 插件封装（npm 包 `rtlens-dsh`） |
| `vscode/` | VS Code LSP 接入配置模板 |
| `tools/` | 辅助脚本（`xengine-compare.mjs`） |
| `install.ps1` / `install.sh` | 一行命令安装脚本（Windows / macOS / Linux） |
| `start.bat` / `start.sh` | 一键启动（quickstart） |
| `AI_INSTALL_PROMPT.md`、`配置指南_说人话版.md` | 给 AI 助手的安装提示词 / 给非专业用户的配置教程 |
| `LICENSE`、`THIRD_PARTY_NOTICES.md` | MIT 许可证、第三方组件声明 |

## 与相关项目的关系

- **Verible（CHIPS Alliance）**：可选的 C++ 解析 / Lint / 格式化后端，以独立进程调用，不与 RTLens 代码链接；缺失时自动回退内置解析器，核心功能不受影响。Linux / macOS 用户可从 [Verible Release](https://github.com/chipsalliance/verible/releases) 下载放入 `rtlens/verible/`。
- **hw-topo（硬件拓扑图插件）**：`rtlens evidence` 的下游消费方。两插件间的坐标 / 截断 / 降级约定由冻结契约 `docs/EVIDENCE_CONTRACT.md` 唯一约束（行号双基准、root 相对 POSIX 路径、sha256、显式降级）。
- **DSH（DeepSeek Harness）**：RTLens 以 `rtlens-dsh` 包形态注册为技能插件，让 agent 无需服务进程即可使用 CLI 分析能力。
- **psutil（可选）**：性能监控面板检测到时启用进程级内存 / CPU 采样，未安装自动降级。

## 质量验证

- **测试套件**：`python tests/run_tests.py` 纯标准库运行，本仓库 2026-10-07 实测 **470 passed, 0 failed**（覆盖解析 / 索引 / LSP 语义 / evidence 截断语义等）。
- **跨引擎等价性实测**（`docs/CROSS_ENGINE_PARITY.md`，RTLens v6.2.0，2026-10-06）：与 hw-topo 内置扫描器在同一棵树上逐元素比对——picorv32（41 文件 / 61 模块 / 108 例化）、ibex（33 文件 / 30 模块）、verilog-ethernet（183 文件 / 183 模块 / 247 例化，逐元素完全一致）三套真实开源工程，所有两边共报的事实**坐标 0 错位**；差异（如 generate 块内例化、死 `` `ifdef`` 区）逐条溯源并显式记录。
- **证据契约冻结**：`docs/EVIDENCE_CONTRACT.md` 定义 `rtlens.evidence/1` 的硬性规则 R1–R6（双基准行号、POSIX 路径、sha256、禁裸 `line`、同后端验证、显式降级），作为跨工具事实传递的唯一接口。
- 开发过程中持续修复真实工程暴露的解析问题（SystemVerilog 包限定类型、`parameter type`、宏统计、genvar 误计、预处理器行数保持等），保证 LSP 跳转 / 诊断 / rename 的行号与原文件严格一致。

## 常见问题（命令速查）

```
rtlens setup       自动检测 AI 工具、写入 MCP 配置并自测（--list-tools 仅列出）
rtlens lsp         启动 LSP 服务器（stdio JSON-RPC）
rtlens mcp         启动 MCP 服务器（供 AI 助手调用）
rtlens web         启动 Web 仪表盘（默认 127.0.0.1:8765，--no-browser 不自动开浏览器）
rtlens api         启动 REST API 服务器
rtlens tui         启动终端交互界面
rtlens quickstart  一键体验：索引示例工程 + 打开 Web 仪表盘
rtlens index       索引目录并打印统计（-D 传宏、-I 加搜索路径）
rtlens query       查询符号的定义与引用
rtlens check       检查例化端口连接是否与模块定义一致
rtlens trace       追踪信号驱动源 → 使用链
rtlens metrics     设计指标（fan-in / fan-out / 层级深度）
rtlens context     生成给 AI 的工程上下文摘要
rtlens template    按真实端口生成 testbench / 例化骨架
rtlens parse       单文件 AST 解析（快速 sanity check）
rtlens evidence    导出机器可读证据包（rtlens.evidence/1）
rtlens --version   查看版本
```

- **端口被占用**：换个端口，如 `python -m rtlens web --port 8766`
- **AI 工具里找不到 rtlens**：配置后需重启 AI 客户端；或按上文 JSON 手动配置
- **某段代码解析报错但仿真器能跑**：内置解析器覆盖主流 RTL 子集，复杂 SystemVerilog 建议启用 Verible 后端（放入 `rtlens/verible/` 即自动启用）
- **分析结果不符合目标构建配置**：工程若用 `` `ifdef`` 守卫端口 / 代码，用 `-D` 传入内置宏（CLI：`python -m rtlens index <dir> -D SIM -D W=8`；MCP：`index_directory` 工具传 `"defines": ["SIM", "W=8"]`）
- **端口检查报 `definition_parse_suspect`**：模块定义可能含尚未支持的 SystemVerilog 语法而解析不完整，工具已自动抑制逐端口误报，建议启用 Verible 后端复核

## 已知边界

- **不做 elaboration**：参数值与位宽保留源码文本（如 `[W-1:0]`），RTLens 不能验证位宽匹配；此类问题应交给 verilator / yosys（`skills/rtlens/SKILL.md` "Known boundaries"）。
- **生成块内例化不进索引**：`for (genvar ...)` 生成块体内的例化不会出现在层级 / 拓扑中（elaboration 范畴，`docs/CROSS_ENGINE_PARITY.md` §2.1 有 ibex 实例）。
- **宏按单编译单元语义跨文件累积**：同一文件"单独索引"与"随目录索引"可能因宏来源不同而展开不同（这是 Verilog 固有语义，不是 bug）。
- **Assertion / class / UVM 构造不建模**；过程块内的驱动 / 使用分类是启发式的（对括号深度 0 的 `<=` / `=` 精确）。
- **Web / API / MCP 默认只监听 127.0.0.1**（`rtlens/__main__.py:50,82`），面向本机使用；如需远程访问请自行评估安全边界。

## 许可证

- **RTLens 自身源代码**：[MIT](LICENSE)（Copyright (c) 2025 rtlens project）
- **捆绑的 Verible 二进制**：Apache-2.0，版权归 Google / CHIPS Alliance 所有，以独立进程调用，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。注意 `rtlens/verible/` 已被 `.gitignore` 排除出 git 追踪，GitHub 克隆不含二进制——需要时自行下载放入该目录，或直接使用内置 Python 解析器。
- **psutil（可选运行时增强，不随库分发）**：BSD 3-Clause

---

> 版本与工具数量以 `python -m rtlens --version` 及实际运行为准；文档更新如滞后于代码，以实际行为为准。
