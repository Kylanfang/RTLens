# RTLens 实验教程

> 从零开始，7 个实验带你掌握 Verilog 语言工具链的全部能力。
> 实验环境：Windows / Mac / Linux + Python 3.8+，无需安装任何 pip 包。

---

## 实验零：环境准备（5 分钟）

### 目标
确认 RTLens 能在你的电脑上正常工作。

### 步骤

1. **解压** rtlens 压缩包到任意目录（如 `C:\rtlens` 或 `~/rtlens`）

2. **打开终端**，进入 rtlens 目录：
   - Windows：在文件管理器地址栏输入 `cmd` 回车
   - Mac/Linux：打开终端，`cd` 到解压目录

3. **运行测试套件**：
   ```
   python -m rtlens parse examples/counter/counter.v
   ```
   预期输出：`Modules: 1`，显示 counter 模块的端口/信号/实例数量

4. **跑测试**：
   ```
   python tests/run_tests.py
   ```
   预期：`50 passed, 0 failed`（或更多）

✅ **通过标准**：看到模块解析结果和测试全通过

---

## 实验一：交互终端 TUI（10 分钟）

### 目标
学会用命令行交互式查询 Verilog 工程的模块、信号、层级关系。

### 步骤

1. **启动 TUI**：
   ```
   python -m rtlens tui --root ./examples/hierarchy
   ```
   预期看到：
   ```
   [rtlens] 已索引 4 个文件 | 模块 3 | 信号 8 | 实例 2
   
   RTLens 交互终端 — 输入 help 查看命令，quit 退出
   rtlens>
   ```

2. **查看统计**：
   ```
   rtlens> stats
   ```

3. **搜索符号**（模糊匹配）：
   ```
   rtlens> find count
   ```
   预期：列出所有名字含 "count" 的符号

4. **查看模块详情**：
   ```
   rtlens> module counter
   ```
   预期：显示 counter 的端口（clk/rst_n/enable/count/overflow）、信号、参数

5. **查看端口**：
   ```
   rtlens> ports top
   ```

6. **查看内部信号**：
   ```
   rtlens> signals counter
   ```

7. **查看实例化关系**：
   ```
   rtlens> instances top
   ```
   预期：top 模块内部实例化了 counter 和 sub

8. **反向查询——谁实例化了 counter**：
   ```
   rtlens> whoinst counter
   ```

9. **查看引用**：
   ```
   rtlens> refs clk
   ```

10. **生成 ASCII 层级树**：
    ```
    rtlens> tree top
    ```
    预期输出：
    ```
    top
    ├── counter  u_counter  (counter.v)
    └── sub      u_sub      (sub.v)
    ```

11. **查看 eLinx 原语**：
    ```
    rtlens> primitives
    ```

12. **退出**：
    ```
    rtlens> quit
    ```

✅ **通过标准**：能成功执行 `tree top` 并看到 ASCII 层级树

### 练习
- 试试 `find ` 搜索其他关键词（如 `rst`、`data`）
- 试试 `module sub` 查看子模块的端口
- 试试 `load ./examples/elinx_demo` 索引新目录

---

## 实验二：Web UI 可视化界面（10 分钟）

### 目标
用浏览器可视化查看模块层级树、端口连接、引脚约束。

### 步骤

1. **启动 Web UI**：
   ```
   python -m rtlens web --root ./examples/hierarchy
   ```
   预期：浏览器**自动打开** `http://127.0.0.1:8765`

2. **认识界面布局**：
   - 顶部：KPI 统计条（模块数、端口数、信号数等）
   - 左侧：符号搜索框 + 模块列表
   - 右侧：6 个标签页

3. **搜索模块**：在左侧搜索框输入 `count`，实时过滤

4. **查看模块详情**：点击左侧 `counter` 模块，右侧"模块详情"标签展示：
   - 端口表格（方向/类型/位宽/名称）
   - 参数表格
   - 内部信号表格
   - 实例化列表（带端口连接关系）

5. **生成层级树**：
   - 切换到"层级树"标签
   - 输入顶层模块名 `top`
   - 点击"生成层级树"
   - 可折叠展开每个节点

6. **查看引用**：
   - 切换到"引用查找"标签
   - 输入符号名 `clk`
   - 点击"查找引用"

7. **查看 eLinx 原语**：
   - 切换到"eLinx 原语"标签
   - 看到 14 种 GTP 原语卡片

8. **索引新目录**：
   - 点击顶部"索引目录"按钮
   - 输入 `./examples/elinx_demo`
   - 查看左侧列表更新

9. **关闭服务器**：在终端按 `Ctrl+C`

✅ **通过标准**：能在浏览器里看到 `top` 的层级树并展开/折叠

---

## 实验三：REST API 调用（15 分钟）

### 目标
学会用 HTTP 请求查询 Verilog 工程信息，为 AI 集成做准备。

### 步骤

1. **启动 API 服务器**：
   ```
   python -m rtlens api --port 8765 --root ./examples/hierarchy
   ```

2. **健康检查**（新开一个终端）：
   ```
   curl http://127.0.0.1:8765/api/health
   ```
   预期：返回 JSON `{"status":"ok",...}`

3. **查看统计**：
   ```
   curl http://127.0.0.1:8765/api/stats
   ```

4. **搜索符号**：
   ```
   curl "http://127.0.0.1:8765/api/symbols?query=count"
   ```

5. **获取模块详情**：
   ```
   curl http://127.0.0.1:8765/api/module/counter
   ```
   返回完整的端口、参数、信号、实例化 JSON

6. **获取层级树**：
   ```
   curl http://127.0.0.1:8765/api/hierarchy/top
   ```

7. **查找引用**：
   ```
   curl http://127.0.0.1:8765/api/references/clk
   ```

8. **查找谁实例化了某模块**：
   ```
   curl http://127.0.0.1:8765/api/instances/counter
   ```

9. **查看 eLinx 原语**：
   ```
   curl http://127.0.0.1:8765/api/primitives
   ```

10. **解析代码片段**（POST）：
    ```
    curl -X POST http://127.0.0.1:8765/api/parse -H "Content-Type: application/json" -d "{\"code\": \"module test(input a, output b); assign b = a; endmodule\"}"
    ```
    预期：返回解析出的模块信息 JSON

11. **索引新目录**（POST）：
    ```
    curl -X POST http://127.0.0.1:8765/api/index -H "Content-Type: application/json" -d "{\"root\": \"./examples/elinx_demo\"}"
    ```

✅ **通过标准**：能独立用 curl 查到任意模块的端口列表

### Windows curl 提示
Windows 10+ 自带 curl。如果报错，用浏览器直接访问 URL（GET 端点）即可；POST 端点可以用 Postman 或 PowerShell 的 `Invoke-RestMethod`。

---

## 实验四：索引自己的真实工程（10 分钟）

### 目标
把 RTLens 指向你自己的 FPGA/RTL 工程目录，验证它能否正确解析。

### 步骤

1. **用 TUI 索引**：
   ```
   python -m rtlens tui --root "D:\你的工程\rtl"
   ```
   观察输出的索引统计：模块数、端口数是否与你的预期接近

2. **在 TUI 里检查**：
   - `stats` 看总数
   - `find <你的顶层模块名>` 搜索
   - `tree <顶层模块>` 看层级树是否完整
   - `module <某个子模块>` 检查端口是否正确识别

3. **用 Web UI 检查**：
   ```
   python -m rtlens web --root "D:\你的工程\rtl"
   ```
   在浏览器里浏览层级树和模块详情

4. **常见问题排查**：
   - 模块没找到 → 检查文件后缀是 `.v` 或 `.sv`
   - 端口识别不全 → 可能是非 ANSI 风格端口声明（老式写法），解析器支持但需检查
   - include 找不到 → 用 `--include-path` 指定头文件搜索目录
   - GTP 原语被误报未知 → 确认原语名是否在 14 种内置桩中

✅ **通过标准**：能看到你自己工程的层级树

---

## 实验五：MCP 接入 AI 编辑器（15 分钟）

### 目标
让 Cursor / Claude Desktop 通过 MCP 协议直接调用 RTLens 的 11 个工具。

### Cursor 配置

1. 在你的 FPGA 项目根目录创建 `.cursor/mcp.json`：
   ```json
   {
       "mcpServers": {
           "rtlens": {
               "command": "python",
               "args": ["-m", "rtlens", "mcp", "--root", "D:\\你的工程\\rtl"]
           }
       }
   }
   ```

2. 重启 Cursor

3. 在 AI 对话框测试：
   - "帮我查一下顶层模块有哪些端口"
   - "counter 模块被哪些文件实例化了？"
   - "画一下 top 模块的实例化层级树"
   - "搜索所有名字包含 clk 的信号"
   - "帮我看看有没有声明了但没使用的信号"

AI 会自动调用 RTLens 的 MCP 工具查询，而不是猜。

### Claude Desktop 配置

编辑 Claude 配置文件：
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
    "mcpServers": {
        "rtlens": {
            "command": "python",
            "args": ["-m", "rtlens", "mcp", "--root", "/path/to/your/rtl"]
        }
    }
}
```

✅ **通过标准**：AI 能准确回答你工程的模块结构问题

---

## 实验六：LSP 编辑器集成（15 分钟）

### 目标
在 VS Code / Neovim 里实现 Verilog 代码的跳转定义、自动补全、诊断。

### VS Code 配置

1. 安装 LSP 客户端扩展（如 "Verible language server" 或通用 LSP 客户端）

2. 在 `.vscode/settings.json` 中配置：
   ```json
   {
       "verilog.languageServer.path": "python",
       "verilog.languageServer.args": ["-m", "rtlens", "lsp", "--root", "${workspaceFolder}"],
       "files.associations": {
           "*.v": "verilog",
           "*.sv": "systemverilog"
       }
   }
   ```

3. 打开任意 `.v` 文件，测试：
   - 右键 → "转到定义"（跨文件跳转）
   - 悬停模块名 → 看到端口列表 Markdown 提示
   - 输入模块名 → 自动补全
   - 波浪线 → 诊断（未声明信号/未知模块警告）

### Neovim (coc.nvim) 配置

```json
{
    "languageserver": {
        "verilog": {
            "command": "python",
            "args": ["-m", "rtlens", "lsp", "--root", "${workspaceFolder}"],
            "filetypes": ["verilog", "systemverilog"]
        }
    }
}
```

✅ **通过标准**：在编辑器里右键能跳转到模块定义

---

## 实验七：约束文件 + eLinx 原语（10 分钟）

### 目标
验证 eLinx GTP 原语识别和约束文件解析能力。

### 步骤

1. **查看 eLinx 原语**：
   ```
   python -m rtlens tui --root ./examples/elinx_demo
   rtlens> primitives
   ```
   预期：列出 GTP_PLL / GTP_DPRAM / GTP_LUT 等 14 种原语

2. **查看 PLL 示例模块**：
   ```
   rtlens> module pll_inst
   ```
   预期：GTP_PLL 实例化不会被误报为"未知模块"

3. **加载约束文件**：
   ```
   rtlens> load ./examples/elinx_demo
   rtlens> constraints
   ```
   注意：约束需要通过 API 加载 PCF 文件

4. **用 API 加载约束**：
   ```
   curl -X POST http://127.0.0.1:8765/api/constraints/load -H "Content-Type: application/json" -d "{\"file\": \"./examples/elinx_demo/pll_demo.pcf\"}"
   ```

5. **查看约束**：
   ```
   curl http://127.0.0.1:8765/api/constraints
   ```
   预期：看到 clkin → A1、clkout → B2 等引脚映射

6. **查询单个信号约束**：
   ```
   curl http://127.0.0.1:8765/api/constraints?signal=clkin
   ```

✅ **通过标准**：能看到引脚约束表

---

## 实验八：v2.0.0 语义高亮 + 折叠（rust-analyzer 风格）

**目标**：体验 v2.0.0 新增的 semanticTokens 和 foldingRange。

1. **启动 API 服务器**：
   ```
   python -m rtlens api --root ./examples/hierarchy
   ```

2. **获取语义 token**（13 种类型 + 6 种修饰符）：
   ```
   curl "http://127.0.0.1:8765/api/semantic-tokens?file=$(pwd)/examples/hierarchy/top.v"
   ```
   返回的 `data` 数组每项 5 个值：`[deltaLine, deltaStart, length, tokenType, tokenModifiers]`

3. **获取折叠区域**：
   ```
   curl "http://127.0.0.1:8765/api/folding?file=$(pwd)/examples/hierarchy/top.v"
   ```
   返回 module/begin/case 等可折叠区域列表

✅ **通过标准**：semantic-tokens 返回非空数组，folding 返回至少 1 个区域

---

## 实验九：v2.0.0 跨文件重命名

**目标**：用 rename 功能在多文件间重命名一个信号/端口。

1. **启动 API 服务器**：
   ```
   python -m rtlens api --root ./examples/hierarchy
   ```

2. **检查可重命名**（先查看光标处是什么符号）：
   ```
   curl -X POST http://127.0.0.1:8765/api/prepare-rename \
     -H "Content-Type: application/json" \
     -d '{"file": "<你的路径>/examples/hierarchy/top.v", "line": 2, "col": 5}'
   ```

3. **执行重命名**：
   ```
   curl -X POST http://127.0.0.1:8765/api/rename \
     -H "Content-Type: application/json" \
     -d '{"file": "<你的路径>/examples/hierarchy/top.v", "line": 2, "col": 5, "newName": "new_clk"}'
   ```
   返回 `{changes: {文件路径: [TextEdit列表]}}`

4. **在 TUI 中体验**：
   ```
   python -m rtlens tui --root ./examples/hierarchy
   rename examples/hierarchy/top.v 2 5 new_clk
   ```

✅ **通过标准**：rename 返回影响多个文件的 TextEdit

---

## 实验十：v2.0.0 代码透镜 + 层级符号树

**目标**：用 codeLens 看引用计数，用 document-tree 看层级符号。

1. **获取代码透镜**：
   ```
   curl "http://127.0.0.1:8765/api/code-lens?file=$(pwd)/examples/hierarchy/top.v"
   ```
   返回每个模块/实例的引用计数和导航提示

2. **获取层级符号树**：
   ```
   curl "http://127.0.0.1:8765/api/document-tree?file=$(pwd)/examples/hierarchy/top.v"
   ```
   返回 module → ports/params/signals/instances/connections 的层级结构

3. **在 TUI 中体验**：
   ```
   python -m rtlens tui --root ./examples/hierarchy
   codelens examples/hierarchy/top.v
   dectree examples/hierarchy/top.v
   ```

✅ **通过标准**：codelens 显示引用计数，dectree 显示层级结构

---

## 总结

| 实验 | 能力 | 命令 |
|------|------|------|
| 零 | 环境验证 | `python tests/run_tests.py` |
| 一 | TUI 交互终端 | `python -m rtlens tui --root ...` |
| 二 | Web UI 可视化 | `python -m rtlens web --root ...` |
| 三 | REST API | `python -m rtlens api --root ...` |
| 四 | 索引真实工程 | `--root "D:\你的工程"` |
| 五 | MCP 接入 AI | `.cursor/mcp.json` |
| 六 | LSP 编辑器 | `.vscode/settings.json` |
| 七 | eLinx 原语 + 约束 | TUI `primitives` + API `constraints` |
| 八 | 语义高亮 + 折叠 | API `semantic-tokens` + `folding` |
| 九 | 跨文件重命名 | API `rename` + TUI `rename` |
| 十 | 代码透镜 + 符号树 | API `code-lens` + `document-tree` |

### 命令速查

| 命令 | 用途 |
|------|------|
| `python -m rtlens tui --root <dir>` | 交互终端 |
| `python -m rtlens web --root <dir>` | Web UI（自动开浏览器） |
| `python -m rtlens api --root <dir>` | REST API（给 AI 用） |
| `python -m rtlens mcp --root <dir>` | MCP（给 Cursor/Claude 用） |
| `python -m rtlens lsp` | LSP（给编辑器用） |
| `python -m rtlens index <dir>` | 索引并打印统计 |
| `python -m rtlens query <dir> <name>` | 查询单个符号 |
| `python -m rtlens parse <file>` | 解析单个文件 |

有问题把报错发给我，我帮你看。
