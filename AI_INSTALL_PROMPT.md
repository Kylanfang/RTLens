# RTLens 安装指令（给 AI Agent 的自然语言提示词）

> 复制以下内容，粘贴给你的 AI 编程助手（Claude Code / Cursor / Codex / Workbuddy 等），它就能自动完成安装和配置。

---

## 安装 RTLens Verilog 分析工具

请帮我安装并配置 RTLens——一个 Verilog/SystemVerilog 代码分析工具，提供 LSP 语言服务器和 MCP 工具接口。

> **v6.1.2** 正确性收口：修复 `semantic.py` 三个函数（semanticTokens/selectionRange/documentHighlight）的坐标 off-by-one——lexer 本就是 0-based，历史版本误减 1，导致语义高亮整体上移一行、首 token delta 为负（LSP 非法）；`check_port_mismatches` 支持**同名多定义模块**（缺失取各定义交集、多余对并集核对，PicoRV32 实测消掉 2 个确定性误报），且每条 issue 带 `severity`（extra_port=error / missing_port=warning / suspect=info），AI 可直接按严重级分诊。
> **v6.1.1** 开源工程实测迭代（ibex/PicoRV32/verilog-ethernet 驱动）：修复 SystemVerilog **模块头 import 子句**（`module m import pkg::*; #(...)` ——此前会把整个参数/端口列表跳掉，ibex 端口提取 210→1201）；支持 **隐式命名连接**（`.rst_ni` ≡ `.rst_ni(rst_ni)`）与 `.*` 通配连接（跳过静态核对）；`check_port_mismatches` 新增 `definition_parse_suspect` 守卫（定义解析残缺时报单条提示而非逐端口误报）；`prim_*`/`sky130_*` 开源 ASIC 平台原语归类为 vendor_primitive；新增 **defines（+define+ 语义）**：CLI `-D SIM -D W=8` / MCP `index_directory(defines=[...])`。
> **v6.1.0** 关键修复：预处理器重构为行数保持语义（`` `include`` 宏预加载、不活跃 `` `ifdef`` 分支置空），符号/引用/诊断/rename 的行号与原文件严格一致；MCP 请求级错误隔离（单次工具异常只返回 error response，会话存活）；psutil 改为可选依赖（缺失自动降级）；新增 ZCode 自动配置支持（`setup --tool zcode`）与 Windows/macOS/Linux 一行命令安装脚本。
> **v6.0.4** 新增：`parse_sim_log`（仿真日志解析）+ `analyze_change_impact`（变更影响分析）两个工具——前者把 iverilog/verilator/VCS 回归日志解析成结构化条目并按模块聚合 triage，后者沿例化关系反向 BFS，从改动文件直接推出要重跑哪些 testbench（PicoRV32 实测：全工程索引 0.34 秒、影响分析毫秒级，改 picorv32.v 即刻圈出 system_tb/testbench 两个需重跑的仿真顶层）。
> **v6.0.3** 新增：`list_unresolved_modules` 工具——列出工程中所有未解析的外部模块并自动分类：厂商原语（BUFG/MMCM/SB_IO/PCIe 硬核等 40+ 种命名模式）vs 疑似拼写错误（附相近模块名建议）。6 个开源工程 849 文件实战审计驱动：解析错误 0、模块覆盖 100%。

### 它能做什么
安装后，你可以通过 42 个 MCP 工具分析 Verilog 代码：
- 符号搜索、模块详情、引用追踪、实例化查找
- 信号驱动源追踪、端口连接检查、设计度量
- 自动生成 testbench 和实例化模板
- Verible Lint 检查（如已安装 Verible）
- 实时性能监控看板
- **仿真日志解析**（v6.0.4 新增）—— 把 iverilog/verilator/VCS 日志解析成结构化条目（严重级/文件/行/列/规则），结合索引归属到具体模块，输出「哪个模块报错最多、哪条 lint 规则最频发」的 triage 视图；日志路径与工程路径不一致时自动做后缀匹配
- **变更影响分析**（v6.0.4 新增）—— 告诉它你改了哪些文件，它沿例化关系反向追溯全部受波及模块与文件，并按 testbench 命名启发式（tb/test/bench）圈出建议重跑的仿真顶层——回归从「全量重跑」变「精准重跑」
- **SystemVerilog 接口解析**（v6.0.2 新增）—— `interface`/`endinterface` 块被完整解析为可搜索符号，含端口、参数、信号、modport；`typedef struct`/`typedef enum` 被索引为可搜索的 typedef/enum 符号（含模块内部的 typedef）
- **聊天窗口直传代码分析**（v5.3.0 增强）—— 不需要工程目录，直接在对话中传代码即可获得完整的跨文件分析能力，`` `include `` 指令自动从虚拟文件池解析，分析结果与磁盘索引完全一致

### 安装步骤

**第 1 步：获取代码**

如果已有代码目录，跳到第 2 步。如果需要从 GitHub 克隆：
```bash
git clone https://github.com/你的用户名/rtlens.git
cd rtlens
```

**第 2 步：安装 Python 包**
```bash
pip install -e .
```
如果遇到权限问题，加 `--user`。需要 Python 3.8+。

**第 3 步：运行自动配置**
```bash
python3 -m rtlens setup
```
这个命令会自动完成：
1. 检查 Python 版本和 pip
2. 验证 rtlens 安装
3. 检测你正在使用的 AI 工具（Claude Code / Cursor / Cline 等）
4. 自动写入 MCP 配置文件
5. 运行自测试验证功能正常

如果你想指定特定工具或工程目录：
```bash
python3 -m rtlens setup --tool claude-code --project /path/to/your/rtl
```

**第 4 步：验证安装**
```bash
# 索引示例工程
python3 -m rtlens index examples/soc_mini

# 查询符号
python3 -m rtlens query examples/soc_mini PLL

# 查看设计度量
python3 -m rtlens metrics -r examples/soc_mini

# 检查端口连接
python3 -m rtlens check -r examples/soc_mini

# 启动 Web 看板
python3 -m rtlens web --root examples/soc_mini
```

**第 5 步：确认 MCP 连接**

重启你的 AI 工具后，尝试调用以下 MCP 工具：
- `search_symbol` — 搜索 Verilog 符号
- `get_module` — 查看模块端口和信号
- `check_port_mismatches` — 检查端口连接问题
- `get_design_metrics` — 查看设计度量
- `batch_index_files` — 批量索引文件

如果工具出现在工具列表中，说明 MCP 连接成功。

---

### 手动配置 MCP（如果自动配置失败）

如果 `rtlens setup` 没有自动检测到你的工具，可以手动配置：

**方式一：全局配置（推荐 — 不绑定工程，支持聊天窗口直传代码）**

不需要 `--root` 参数。Agent 可以通过 `index_code` 工具直接在对话中传入代码，或通过 `index_directory` / `batch_index_files` 按需索引。

**Claude Code** — 在项目根目录创建 `.claude/mcp_servers.json`：
```json
{
  "mcpServers": {
    "rtlens": {
      "command": "python3",
      "args": ["-m", "rtlens", "mcp"]
    }
  }
}
```

**Cursor** — 在项目根目录创建 `.cursor/mcp.json`：
```json
{
  "mcpServers": {
    "rtlens": {
      "command": "python3",
      "args": ["-m", "rtlens", "mcp"]
    }
  }
}
```

**Workbuddy** — 在项目根目录创建 `.workbuddy/mcp.json`：
```json
{
  "mcpServers": {
    "rtlens": {
      "command": "python3",
      "args": ["-m", "rtlens", "mcp"]
    }
  }
}
```

**ZCode** — 配置结构与其余工具不同（嵌套 `mcp.servers` + 严格 schema + 绝对路径）。推荐工作区级：在仓库根目录创建 `.zcode/config.json`（用户级则写 `~/.zcode/cli/config.json`）：
```json
{
  "mcp": {
    "servers": {
      "rtlens": {
        "type": "stdio",
        "command": "C:\\abs\\path\\to\\python.exe",
        "args": ["-m", "rtlens", "mcp"],
        "cwd": "C:\\abs\\path\\to\\rtlens",
        "timeoutMs": 60000
      }
    }
  }
}
```
> ZCode 注意事项：`command` 用绝对路径；多余字段会导致整个 server 被静默丢弃；`${...}` 模板变量不会展开。`python -m rtlens setup --tool zcode` 可自动写入用户级配置。

**方式二：绑定工程目录（适合固定工程分析）**

如果需要 MCP 启动时自动索引某个工程目录，加 `--root` 参数：
```json
{
  "mcpServers": {
    "rtlens": {
      "command": "python3",
      "args": ["-m", "rtlens", "mcp", "--root", "/path/to/your/verilog/project"]
    }
  }
}
```

> `--root` 是可选的。不加 `--root` 时，MCP 启动后索引为空，Agent 通过 `index_code`（传代码文本）或 `index_directory`（传目录路径）按需索引。加了 `--root` 则启动时自动索引该目录。

---

### 可选：安装 Verible（增强 Lint 功能）

Verible 是 Google 开发的 Verilog 工具链，安装后 RTLens 可提供语法检查和 Lint：
- https://github.com/chipsalliance/verible/releases

不安装 Verible 也不影响核心功能（符号搜索、引用追踪、代码生成等全部可用）。

### 可选：安装 psutil（性能监控）

性能监控看板需要 psutil：
```bash
pip install psutil
```

---

### 安装后可用的 42 个 MCP 工具

| 类别 | 工具 |
|------|------|
| 符号查询 | search_symbol, get_module, get_references, get_instances, get_hierarchy |
| 信号分析 | get_drivers, trace_signal, get_constraints, get_primitives |
| 代码解析 | parse_code, get_macros, get_code_lens, get_semantic_tokens |
| 设计度量 | get_design_metrics, check_port_mismatches, get_design_summary, get_module_graph |
| 代码生成 | generate_testbench, generate_instantiation, get_context_for_ai |
| 索引管理 | index_code, index_file, batch_index_files, index_directory, get_workspace_status, switch_workspace |
| Lint 检查 | verible_lint, verible_syntax_check, lint_all |
| 代码搜索 | search_code, code_search |
| 折叠/重命名 | get_folding_ranges, get_inlay_hints, get_document_tree, rename_symbol, prepare_rename |
| 预处理 | expand_macros |

> **v5.3.0 `index_code` 升级**：`` `include `` 指令自动从虚拟文件池解析——传入的文件之间互相 include 也能正确展开，分析结果与 `index_directory` 完全一致（PicoRV32 41 文件实测：61/61 模块，8/8 宏，593/593 端口，全字段 parity）。性能仅比磁盘索引慢 10%，因为跳过了 mtime 缓存但增加了字符串传递开销。

> **v6.0.2 SystemVerilog 接口与 Typedef**：`interface`/`endinterface` 块现被完整解析为 ModuleInfo——包含端口、参数、信号、实例化、modport 声明。`typedef struct`/`typedef enum` 被追踪为可搜索符号（此前仅作引用记录，不在符号索引中）。接口同时加入 `_module_defs`（支持接口例化追踪）和 `_all_symbols`（支持 `search_symbol`）。所有统计数据（`get_workspace_status`）现包含 `interfaces` 和 `typedefs` 计数。实测 common_cells（168 个 SV 文件）：2/2 接口 + 24 个 typedef 全部解析，PicoRV32 零回归。

---

### Agent 推荐工作流（零配置 · 聊天窗口直传代码）

安装 MCP 后，Agent 不需要任何额外配置即可工作。推荐流程：

1. **用户在对话中贴代码** — 用户把 `.v` / `.sv` / `.vh` 文件内容直接粘贴到聊天窗口
2. **Agent 调用 `index_code`** — 一次调用传入所有文件：`{"files": [{"path": "top.v", "content": "..."}, {"path": "defines.vh", "content": "..."}]}`
3. **Agent 调用分析工具** — `search_symbol`、`get_module`、`get_references`、`check_port_mismatches`、`get_design_summary` 等
4. **Agent 报告结果** — 把分析结果整理后回复用户

`` `include `` 指令自动从传入的文件中解析，无需目录结构。分析结果与磁盘索引完全一致。

### 故障排除

| 问题 | 解决方案 |
|------|---------|
| `python3: No module named rtlens` | 运行 `pip install -e .`，或确认在 rtlens 目录下 |
| MCP 工具不出现 | 重启 AI 工具；检查配置文件路径是否正确 |
| `command not found: python3` | Windows 用 `python` 替代 `python3` |
| 端口被占用 | `python3 -m rtlens web --port 8766` |
| 中文路径报错 | 确保路径中无中文和空格 |
| pip 找不到 | `python3 -m pip install -e .` |

---

### 一行命令安装（已有代码时）

```bash
cd rtlens && pip install -e . && python3 -m rtlens setup
```
