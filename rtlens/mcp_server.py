"""MCP（Model Context Protocol）服务器：给 AI agent 调用的工具接口。

工具列表（tools/list 返回）：
  search_symbol       按名称搜索符号 {query}
  get_module          查模块详情 {name}
  get_references      查全部引用 {name}
  get_instances       谁例化了此模块 {module_type}
  list_unresolved_modules  外部模块清单：厂商原语 vs 疑似拼写错误 {suggest?}
  parse_sim_log      解析仿真日志(iverilog/verilator/vcs)并按模块聚合 {log_text}
  analyze_change_impact  变更影响分析：改了哪些文件→重跑哪些 testbench {changed_files}
  get_hierarchy       例化层级树 {top_module}
  get_drivers         信号驱动源 {file, signal}
  get_constraints     引脚约束 {signal?}
  parse_code          解析代码片段 {code}
  get_macros          宏定义列表
  get_primitives      eLinx 原语列表

JSON-RPC over stdio，与 Codex / Claude / Cursor 等兼容。
"""

from __future__ import annotations

import json
import os
import sys
import time as _time
import traceback
from typing import Any, Dict, List, Optional

from .indexer import WorkspaceIndex
from .elinx import ELinxSupport
from .preprocessor import Preprocessor
from .parser import parse
from .monitor import get_monitor
from . import __version__


class MCPServer:
    def __init__(self, include_paths=None, stub_dir=None, index_root=None, defines=None):
        self.index = WorkspaceIndex(include_paths=include_paths, defines=defines)
        self.elinx = ELinxSupport(stub_dir=stub_dir)
        if index_root:
            if os.path.isdir(index_root):
                self.index.index_directory(index_root)
        # v3.0: 初始化 AI 工具（修复：之前漏了这行，所有 AI 工具调用都会 AttributeError）
        from .ai_tools import AITools
        self.ai = AITools(self.index)
        # v4.0: verible 后端引用
        self._verible = self.index._verible
        # v5.1.1: 跨进程监控桥接 —— MCP 进程把实时快照写到文件，
        # 用户在浏览器里 `rtlens web --root <同工程>` 就能看到 workbuddy 实际触发的 MCP 调用耗时
        # v5.2.0: 无 root 时用 PID 隔离，避免多进程冲突
        try:
            from .monitor import get_monitor, bridge_snapshot_path
            _bridge_root = index_root
            _bridge_pid = os.getpid() if not index_root else None
            get_monitor().enable_bridge(bridge_snapshot_path(_bridge_root, pid=_bridge_pid))
            # 初始索引用一次 record，让桥接文件第一时间有内容
            get_monitor().record("mcp_startup", "mcp_startup", 0.0, success=True,
                                 detail=f"root={index_root}, files={self.index.stats.files}, pid={_bridge_pid}")
        except Exception:
            pass

    TOOLS = [
        {"name": "search_symbol", "description": "Search symbols by name in the indexed Verilog workspace",
         "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "get_module", "description": "Get module details (ports, params, instances, signals)",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "get_references", "description": "Find all references of a symbol across the workspace",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "get_instances", "description": "Find who instantiates a given module type",
         "inputSchema": {"type": "object", "properties": {"module_type": {"type": "string"}}, "required": ["module_type"]}},
        {"name": "list_unresolved_modules", "description": "List all unresolved (external) module types instantiated in the workspace, classified as vendor_primitive (BUFG/MMCM/SB_IO etc.) or unknown (possible typo, with name suggestions)",
         "inputSchema": {"type": "object", "properties": {"suggest": {"type": "boolean", "description": "include fuzzy name suggestions for unknown types (default true)"}}}},
        {"name": "parse_sim_log", "description": "Parse simulation log text (iverilog/verilator/vcs formats) into structured entries, attribute each to the indexed module, and return a per-module triage summary (error/warning counts, top modules, lint rules). Use after a failing regression run.",
         "inputSchema": {"type": "object", "properties": {"log_text": {"type": "string", "description": "raw simulation/compile log text"}, "top": {"type": "integer", "description": "max modules in summary ranking (default 10)"}}, "required": ["log_text"]}},
        {"name": "analyze_change_impact", "description": "Change impact analysis: given changed file paths, reverse-BFS the instantiation graph to find impacted modules, root modules and testbenches that should be re-run. Use before a regression to avoid re-running the full suite.",
         "inputSchema": {"type": "object", "properties": {"changed_files": {"type": "array", "items": {"type": "string"}, "description": "list of changed source file paths"}}, "required": ["changed_files"]}},
        {"name": "get_hierarchy", "description": "Get the instantiation hierarchy tree starting from a top module",
         "inputSchema": {"type": "object", "properties": {"top_module": {"type": "string"}}, "required": ["top_module"]}},
        {"name": "get_drivers", "description": "Find all driver locations of a signal in a file",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "signal": {"type": "string"}},
                         "required": ["file", "signal"]}},
        {"name": "get_constraints", "description": "Get pin constraints. If signal given, returns that signal's pin; otherwise all.",
         "inputSchema": {"type": "object", "properties": {"signal": {"type": "string"}}}},
        {"name": "parse_code", "description": "Parse a Verilog code snippet and return structured AST info",
         "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
        {"name": "get_macros", "description": "List all macro definitions in the workspace",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "get_primitives", "description": "List all known eLinx FPGA primitives",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "index_directory", "description": "Index a Verilog project directory. Optional 'defines' (list like [\"SIM\"] or {\"SIM\":\"1\"}, +define+ semantics) rebuilds the index with builtin macros for `ifdef evaluation — required when the project's port lists are guarded by config macros.",
         "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "defines": {"type": "array", "items": {"type": "string"}, "description": "e.g. [\\\"SIM\\\", \\\"W=8\\\"]"}}, "required": ["root"]}},
        {"name": "rename_symbol", "description": "Rename a symbol across all files in the workspace",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "line": {"type": "integer"}, "col": {"type": "integer"}, "new_name": {"type": "string"}}, "required": ["file", "line", "col", "new_name"]}},
        {"name": "get_code_lens", "description": "Get code lens (reference counts, navigation hints) for a file",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
        {"name": "get_document_tree", "description": "Get hierarchical document symbol tree for a file",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
        {"name": "get_semantic_tokens", "description": "Get semantic tokens for a file (for syntax highlighting). max_tokens caps the returned token count (default 50000) to protect agents on huge files; pass max_tokens=0 for all",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "max_tokens": {"type": "integer"}}, "required": ["file"]}},
        {"name": "get_folding_ranges", "description": "Get foldable regions for a file",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
        # ---- v3.0 AI 工具 ----
        {"name": "analyze_design", "description": "Get overall design overview: module count, port count, hierarchy tree",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "get_module_info", "description": "Get detailed module info: ports, parameters, signals, instantiation sites",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "generate_instantiation", "description": "Generate Verilog instantiation template with named connections (_i/_o suffixes)",
         "inputSchema": {"type": "object", "properties": {"module": {"type": "string"}, "instance_name": {"type": "string"}}, "required": ["module"]}},
        {"name": "generate_testbench", "description": "Generate a complete testbench skeleton: signal declarations, DUT, clock, reset, test sequence",
         "inputSchema": {"type": "object", "properties": {"module": {"type": "string"}}, "required": ["module"]}},
        {"name": "trace_signal", "description": "Trace a signal from driver to all usage points (replaces multiple grep calls). limit>0 caps drivers/usages each and sets truncated flag",
         "inputSchema": {"type": "object", "properties": {"signal": {"type": "string"}, "file": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["signal"]}},
        {"name": "get_design_metrics", "description": "Get design metrics: fan-in, fan-out, hierarchy depth, port density, line counts per module",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "check_port_mismatches", "description": "Check all instantiations for port mismatches (missing, extra, count mismatch)",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "search_code_semantic", "description": "Semantic code search across indexed symbols (faster than grep, no file I/O)",
         "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "kind": {"type": "string"}}, "required": ["query"]}},
        {"name": "get_context_for_ai", "description": "Generate a compact text summary of the entire design for AI context (call this first when an AI starts working on the project)",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "module": {"type": "string"}}}},
        # ---- 动态工作区工具 ----
        {"name": "switch_workspace", "description": "Switch the indexed workspace to a different RTL project directory at runtime. Use this when the user wants to analyze a different project without restarting the MCP server.",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute path to the new RTL project directory"}}, "required": ["path"]}},
        {"name": "index_file", "description": "Add a single Verilog file to the workspace index for analysis. Use this to analyze individual .v/.sv files.",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute path to the .v or .sv file"}}, "required": ["path"]}},
        {"name": "list_indexed_files", "description": "List all files currently in the workspace index",
         "inputSchema": {"type": "object", "properties": {}}},
        # ---- v4.0 Verible 后端工具 ----
        {"name": "verible_status", "description": "Check if verible (Google official SystemVerilog parser) backend is active, and which parser is being used",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "verible_syntax_check", "description": "Run verible-verilog-syntax to check for syntax errors in a file (official Google parser, more accurate than custom parser). max_errors caps returned errors (default 100)",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "max_errors": {"type": "integer"}}, "required": ["file"]}},
        {"name": "verible_lint", "description": "Run verible-verilog-lint to check for style violations and code quality issues. max_results caps violations returned (default 200; 0 = all, can be huge on large files)",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["file"]}},
        {"name": "verible_format", "description": "Run verible-verilog-format to format code (preview mode, does not modify original file)",
         "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
        # ---- v4.5 批量分析工具 ----
        {"name": "lint_all", "description": "Batch lint ALL indexed files at once. Returns per-file violation counts sorted by severity. Much faster than calling verible_lint for each file separately.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "get_design_summary", "description": "Generate a comprehensive design summary: all modules with ports/params/instances, auto-detected top modules, and overall stats. Use this to understand the full design at a glance.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "get_module_graph", "description": "Build module dependency graph (nodes + edges) for visualization. Each node is a module; each edge is an instantiation relationship (parent → child).",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "code_search", "description": "Regex search across ALL indexed file contents. Returns matching lines with file/line context. Max 200 matches. Use this instead of multiple grep calls.",
         "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Regular expression pattern to search for"}}, "required": ["pattern"]}},
        # ---- v5.0 批量 + 状态工具 ----
        {"name": "batch_index_files", "description": "Index MULTIPLE Verilog files in a single MCP call. Pass a list of file paths. Returns per-file status + aggregate stats. Use this instead of calling index_file N times to reduce MCP channel overhead (99% of MCP time is IPC, not parsing).",
         "inputSchema": {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}, "description": "List of absolute file paths to .v/.sv files"}}, "required": ["paths"]}},
        {"name": "get_workspace_status", "description": "Get comprehensive workspace status: file count, module/port/signal/instance stats, verible backend status, and version. Use this as the first call to understand the current state of the indexed workspace.",
         "inputSchema": {"type": "object", "properties": {}},},
        # ---- v5.3.0 聊天窗口直传代码工具 ----
        {"name": "index_code", "description": "Index Verilog/SystemVerilog files from TEXT CONTENT directly — no files on disk needed. Pass an array of {path, content} objects. Each path is a virtual filename (e.g. 'top.v'); content is the full file text. `include directives are automatically resolved from the virtual file pool — no directory structure needed. After indexing, all cross-file analysis tools (search_symbol, get_references, get_instances, trace_signal, check_port_mismatches, etc.) work normally. This is the recommended way to analyze code pasted in the chat window.",
         "inputSchema": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string", "description": "Virtual filename, e.g. 'top.v'"}, "content": {"type": "string", "description": "Full file content"}}, "required": ["path", "content"]}}}, "required": ["files"]}},
    ]

    def run(self):
        # v6.1.0: 请求级错误隔离 —— 单个消息处理失败只影响该请求
        # （按 JSON-RPC 规范返回 error response），会话继续服务后续请求。
        # 历史版本在异常时直接 break，一次坏调用会杀死整个 MCP 会话。
        self._configure_stdio_utf8()
        while True:
            try:
                msg = self._read()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
                print(f"rtlens-mcp: skipping malformed message: {e}", file=sys.stderr)
                continue
            if msg is None:
                break  # stdin 关闭，正常退出
            req_id = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params", {}) or {}
            try:
                if method == "ping":
                    result: Any = {}
                elif method in ("initialize", "tools/list", "tools/call"):
                    result = self._dispatch(method, params)
                elif method.startswith("notifications/"):
                    continue  # 通知无需响应
                else:
                    if req_id is None:
                        continue  # 未知通知，静默忽略
                    self._send({"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": f"Method not found: {method}"}})
                    continue
                if req_id is not None:
                    self._send({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                if req_id is not None:
                    self._send({"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32603, "message": f"internal error: {e}"}})

    @staticmethod
    def _configure_stdio_utf8():
        """Windows 下 stdio 默认编码可能是 GBK；强制 UTF-8 防止非 ASCII 输出崩溃。"""
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                if stream is not None and hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    def _read(self) -> Optional[Dict]:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def _send(self, msg: Dict):
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def _dispatch(self, method: str, params: Any) -> Any:
        if method == "ping":
            return {}
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                    "serverInfo": {"name": "rtlens-mcp", "version": __version__}}
        if method == "tools/list":
            return {"tools": self.TOOLS}
        if method == "tools/call":
            return self._call_tool(params.get("name", ""), params.get("arguments", {}))
        return None

    def _call_tool(self, name: str, args: Dict) -> Dict:
        # v5.0: 性能监控 — 记录每次工具调用的真实耗时
        monitor = get_monitor()
        t0 = _time.perf_counter()
        try:
            result = self._call_tool_impl(name, args)
            duration_ms = (_time.perf_counter() - t0) * 1000
            # 估算影响的文件/符号数
            files_aff = 0
            sym_aff = 0
            if name in ("index_file", "index_directory"):
                files_aff = self.index.stats.files
                sym_aff = self.index.stats.modules + self.index.stats.ports + self.index.stats.signals
            elif name in ("batch_index_files"):
                files_aff = args.get("paths", [])
                files_aff = len(files_aff) if isinstance(files_aff, list) else 0
            elif name in ("search_symbol", "get_references", "get_instances"):
                sym_aff = 1
            monitor.record(name, name, duration_ms, success=True,
                          files_affected=files_aff, symbols_affected=sym_aff,
                          detail=str(args.get("query", args.get("name", args.get("path", ""))))[:100])
            return result
        except Exception as e:
            duration_ms = (_time.perf_counter() - t0) * 1000
            monitor.record(name, name, duration_ms, success=False,
                          error=str(e)[:200], detail=str(args)[:100])
            raise

    def _call_tool_impl(self, name: str, args: Dict) -> Dict:
        if name == "search_symbol":
            syms = self.index.workspace_symbols(args.get("query", ""), limit=200)
            return {"content": [{"type": "text", "text": json.dumps([_sym_dict(s) for s in syms], ensure_ascii=False)}]}

        if name == "get_module":
            mod = self.index.get_module(args.get("name", ""))
            if not mod:
                return {"content": [{"type": "text", "text": f"module not found: {args.get('name')}"}]}
            return {"content": [{"type": "text", "text": json.dumps(_module_dict(mod), ensure_ascii=False)}]}

        if name == "get_references":
            refs = self.index.find_references(args.get("name", ""))
            return {"content": [{"type": "text", "text": json.dumps([_ref_dict(r) for r in refs], ensure_ascii=False)}]}

        if name == "get_instances":
            insts = self.index.who_instantiates(args.get("module_type", ""))
            return {"content": [{"type": "text", "text": json.dumps([_sym_dict(s) for s in insts], ensure_ascii=False)}]}

        if name == "list_unresolved_modules":
            unres = self.index.list_unresolved_modules(suggest=args.get("suggest", True))
            summary = {}
            for e in unres:
                summary[e["kind"]] = summary.get(e["kind"], 0) + 1
            out = {"summary": summary, "count": len(unres), "modules": unres}
            return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}

        # v6.0.4: 仿真日志解析 — 回归失败后按模块 triage
        if name == "parse_sim_log":
            from .simlog import parse_sim_log, annotate, summarize
            entries = parse_sim_log(args.get("log_text", ""))
            annotate(entries, self.index)
            top_n = int(args.get("top", 10))
            out = {
                "summary": summarize(entries, top=top_n),
                "entries": [e.to_dict() for e in entries],
            }
            return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}

        # v6.0.4: 变更影响分析 — 增量回归入口
        if name == "analyze_change_impact":
            files = args.get("changed_files", [])
            if isinstance(files, str):
                files = [files]
            out = self.index.analyze_change_impact(files)
            return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}

        if name == "get_hierarchy":
            return {"content": [{"type": "text", "text": json.dumps(self.index.get_hierarchy(args.get("top_module", "")), ensure_ascii=False)}]}

        if name == "get_drivers":
            drivers = self.index.get_signal_drivers(args.get("file", ""), args.get("signal", ""))
            return {"content": [{"type": "text", "text": json.dumps([_ref_dict(d) for d in drivers], ensure_ascii=False)}]}

        if name == "get_constraints":
            sig = args.get("signal", "")
            if sig:
                c = self.elinx.get_pin(sig)
                return {"content": [{"type": "text", "text": json.dumps(_constraint_dict(c) if c else None, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": json.dumps([_constraint_dict(c) for c in self.elinx.get_all_constraints()], ensure_ascii=False)}]}

        if name == "parse_code":
            result = parse(args.get("code", ""))
            return {"content": [{"type": "text", "text": json.dumps({
                "modules": [_module_dict(m) for m in result.modules],
                "macros": [{"name": m.name, "value": m.value} for m in result.macros],
                "errors": result.errors[:20],
            }, ensure_ascii=False)}]}

        if name == "get_macros":
            macros = self.index.get_macros()
            return {"content": [{"type": "text", "text": json.dumps([{"name": k, "detail": v.detail} for k, v in macros.items()], ensure_ascii=False)}]}

        if name == "get_primitives":
            return {"content": [{"type": "text", "text": json.dumps(sorted(self.elinx.stub_modules.keys()), ensure_ascii=False)}]}

        if name == "index_directory":
            root = args.get("root", "")
            defines = args.get("defines")
            if defines is not None:
                # defines 改变预处理结果 —— 重建索引并重新接线依赖
                self.index = WorkspaceIndex(include_paths=self.index.include_paths or None,
                                            defines=_normalize_defines(defines))
                from .ai_tools import AITools
                self.ai = AITools(self.index)
                self._verible = self.index._verible
            if os.path.isdir(root):
                count = self.index.index_directory(root)
                return {"content": [{"type": "text", "text": json.dumps({"indexed": count, "stats": _stats_dict(self.index.stats)}, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": f"directory not found: {root}"}]}

        # ---- v2.0.0 新增工具 ----

        if name == "rename_symbol":
            result = self.index.rename_symbol(args.get("file", ""), args.get("line", 0), args.get("col", 0), args.get("new_name", ""))
            if not result:
                return {"content": [{"type": "text", "text": "symbol not found or not renameable"}]}
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        if name == "get_code_lens":
            lenses = self.index.get_code_lens(args.get("file", ""))
            return {"content": [{"type": "text", "text": json.dumps(lenses, ensure_ascii=False)}]}

        if name == "get_document_tree":
            tree = self.index.document_symbol_tree(args.get("file", ""))
            return {"content": [{"type": "text", "text": json.dumps(tree, ensure_ascii=False)}]}

        if name == "get_semantic_tokens":
            fp = args.get("file", "")
            fidx = self.index._files.get(fp)
            if not fidx:
                return {"content": [{"type": "text", "text": "file not indexed"}]}
            from .semantic import compute_semantic_tokens
            max_tokens = int(args.get("max_tokens", 50000) or 50000)
            tokens = compute_semantic_tokens(fidx.text, max_tokens=max_tokens)
            return {"content": [{"type": "text", "text": json.dumps(tokens, ensure_ascii=False)}]}

        if name == "get_folding_ranges":
            fp = args.get("file", "")
            fidx = self.index._files.get(fp)
            if not fidx:
                return {"content": [{"type": "text", "text": "file not indexed"}]}
            from .semantic import compute_folding_ranges
            return {"content": [{"type": "text", "text": json.dumps(compute_folding_ranges(fidx.text), ensure_ascii=False)}]}

        # ---- v3.0 AI 工具 ----
        if name == "analyze_design":
            return {"content": [{"type": "text", "text": json.dumps(self.ai.analyze_design(), ensure_ascii=False)}]}

        if name == "get_module_info":
            info = self.ai.get_module_info(args.get("name", ""))
            if not info:
                return {"content": [{"type": "text", "text": f"module not found: {args.get('name')}"}]}
            return {"content": [{"type": "text", "text": json.dumps(info, ensure_ascii=False)}]}

        if name == "generate_instantiation":
            mod_name = args.get("module", "") or args.get("name", "")
            code = self.ai.generate_instantiation(mod_name, args.get("instance_name", "u_inst"))
            return {"content": [{"type": "text", "text": code}]}

        if name == "generate_testbench":
            code = self.ai.generate_testbench(args.get("module", "") or args.get("name", ""))
            return {"content": [{"type": "text", "text": code}]}

        if name == "trace_signal":
            sig = args.get("signal", "") or args.get("name", "")
            return {"content": [{"type": "text", "text": json.dumps(
                self.ai.trace_signal(sig, args.get("file", ""), limit=args.get("limit", 0)),
                ensure_ascii=False)}]}

        if name == "get_design_metrics":
            return {"content": [{"type": "text", "text": json.dumps(self.ai.get_design_metrics(), ensure_ascii=False)}]}

        if name == "check_port_mismatches":
            return {"content": [{"type": "text", "text": json.dumps(self.ai.check_port_mismatches(), ensure_ascii=False)}]}

        if name == "search_code_semantic":
            return {"content": [{"type": "text", "text": json.dumps(self.ai.search_code(args.get("query", ""), args.get("kind", "")), ensure_ascii=False)}]}

        if name == "get_context_for_ai":
            return {"content": [{"type": "text", "text": self.ai.get_context_for_ai(args.get("file", ""), args.get("module", ""))}]}

        # ---- 动态工作区工具 ----
        if name == "switch_workspace":
            # v5.0: 安全切换 — 先索引新目录，成功后原子替换
            #   旧版本先清空再索引，超时/崩溃会导致整个索引丢失
            path = args.get("path", "")
            if not path:
                return {"content": [{"type": "text", "text": json.dumps({"error": "path is required"}, ensure_ascii=False)}]}
            result = self.index.safe_switch_workspace(path)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        if name == "batch_index_files":
            # v5.0: 批量索引 — 一次 MCP 调用索引多个文件，减少 IPC 往返
            paths = args.get("paths", [])
            if not paths or not isinstance(paths, list):
                return {"content": [{"type": "text", "text": json.dumps({"error": "paths (list of file paths) is required"}, ensure_ascii=False)}]}
            result = self.index.batch_index_files(paths)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        if name == "get_workspace_status":
            # v5.0: 工作区状态概览 — 一次调用获取全部统计 + 文件列表
            files = list(self.index._files.keys())
            result = {
                "files_indexed": len(files),
                "files": files[:100],  # 限制返回数量
                "files_truncated": len(files) > 100,
                "stats": {
                    "modules": self.index.stats.modules,
                    "ports": self.index.stats.ports,
                    "signals": self.index.stats.signals,
                    "params": self.index.stats.params,
                    "instances": self.index.stats.instances,
                    "functions": self.index.stats.functions,
                    "macros": self.index.stats.macros,
                    "interfaces": self.index.stats.interfaces,      # v6.0.1
                    "typedefs": self.index.stats.typedefs,           # v6.0.1
                    "packages": self.index.stats.packages,           # v6.0.1
                },
                "verible_active": bool(self._verible and self._verible.available),
                "version": __version__,
            }
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        if name == "index_file":
            path = args.get("path", "")
            if not path:
                return {"content": [{"type": "text", "text": json.dumps({"error": "path is required"}, ensure_ascii=False)}]}
            if not os.path.isfile(path):
                return {"content": [{"type": "text", "text": json.dumps({"error": f"file not found: {path}"}, ensure_ascii=False)}]}
            self.index.index_file(path)
            return {"content": [{"type": "text", "text": json.dumps({
                "status": "indexed",
                "file": path,
                "modules": self.index.stats.modules,
                "parser": "python (hybrid indexer)",
            }, ensure_ascii=False)}]}

        if name == "list_indexed_files":
            files = list(self.index._files.keys())
            return {"content": [{"type": "text", "text": json.dumps({
                "file_count": len(files),
                "files": files,
                "stats": {
                    "modules": self.index.stats.modules,
                    "ports": self.index.stats.ports,
                    "signals": self.index.stats.signals,
                    "instances": self.index.stats.instances,
                }
            }, ensure_ascii=False)}]}

        # ---- v4.0 Verible 后端工具 ----
        if name == "verible_status":
            if self._verible and self._verible.available:
                return {"content": [{"type": "text", "text": json.dumps({
                    "backend": "hybrid",
                    "indexer": "python (fast, full reference tracking)",
                    "syntax_check_lint_format": "verible (Google official SystemVerilog parser)",
                    "executable": self._verible.executable,
                    "status": "active — Python for indexing, verible for syntax/lint/format",
                    "tools_available": len(self.TOOLS),
                    "version": __version__,
                    "architecture": "hybrid: python parser builds the index (fast, ~0.7ms/file, full refs/connections), verible handles syntax_check/lint/format tools only (called on-demand)",
                }, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": json.dumps({
                "backend": "python-only",
                "indexer": "python (fast, full reference tracking)",
                "syntax_check_lint_format": "not available (verible not found)",
                "status": "verible not found — syntax_check/lint/format tools will return error. Indexing still works.",
                "tools_available": len(self.TOOLS),
                "how_to_enable": "Download verible from https://github.com/chipsalliance/verible/releases and place binaries in the rtlens/verible/ directory",
            }, ensure_ascii=False)}]}

        if name == "verible_syntax_check":
            if self._verible and self._verible.available:
                fp = args.get("file", "")
                result = self._verible.syntax_check(fp, max_errors=args.get("max_errors", 100))
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": "verible not available. Install verible to use this tool."}]}

        if name == "verible_lint":
            if self._verible and self._verible.available:
                fp = args.get("file", "")
                result = self._verible.lint(fp, max_results=args.get("max_results", 200))
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": "verible not available. Install verible to use this tool."}]}

        if name == "verible_format":
            if self._verible and self._verible.available:
                fp = args.get("file", "")
                result = self._verible.format_code(fp)
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
            return {"content": [{"type": "text", "text": "verible not available. Install verible to use this tool."}]}

        # ---- v4.5 批量分析工具 ----
        if name == "lint_all":
            if not self._verible or not self._verible.available:
                return {"content": [{"type": "text", "text": "verible not available"}]}
            files = list(self.index._files.keys())
            results = []
            total = 0
            for fp in files:
                r = self._verible.lint(fp, max_results=500)
                vc = r.get("violation_count", 0)
                total += vc
                results.append({"file": os.path.basename(fp), "violations": vc, "passed": r.get("passed", True)})
            results.sort(key=lambda x: x["violations"], reverse=True)
            return {"content": [{"type": "text", "text": json.dumps({
                "file_count": len(files), "total_violations": total,
                "clean_files": sum(1 for r in results if r["violations"] == 0),
                "dirty_files": sum(1 for r in results if r["violations"] > 0),
                "files": results,
            }, ensure_ascii=False)}]}

        if name == "get_design_summary":
            from .api import _run_design_summary
            return {"content": [{"type": "text", "text": json.dumps(_run_design_summary(self.index), ensure_ascii=False)}]}

        if name == "get_module_graph":
            from .api import _build_module_graph
            return {"content": [{"type": "text", "text": json.dumps(_build_module_graph(self.index), ensure_ascii=False)}]}

        if name == "code_search":
            from .api import _code_search
            pattern = args.get("pattern", "")
            return {"content": [{"type": "text", "text": json.dumps(_code_search(self.index, pattern), ensure_ascii=False)}]}

        # ---- v5.3.0: 聊天窗口直传代码索引（虚拟 include 解析）----
        if name == "index_code":
            files_list = args.get("files", [])
            if not files_list or not isinstance(files_list, list):
                return {"content": [{"type": "text", "text": json.dumps({"error": "files (array of {path, content}) is required"}, ensure_ascii=False)}]}
            result = self.index.index_code_batch(files_list)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        return {"content": [{"type": "text", "text": f"unknown tool: {name}"}]}


def _normalize_defines(defines) -> Dict[str, str]:
    """接受 ["SIM", "W=8"] 或 {"SIM": "1"} → {"SIM": "1", "W": "8"}（+define+ 语义）。"""
    out: Dict[str, str] = {}
    if isinstance(defines, dict):
        for k, v in defines.items():
            out[str(k)] = str(v)
    elif isinstance(defines, list):
        for item in defines:
            s = str(item)
            if "=" in s:
                k, _, v = s.partition("=")
                out[k.strip()] = v.strip()
            elif s.strip():
                out[s.strip()] = "1"
    return out


# 共享序列化函数（与 api.py 保持一致）
def _stats_dict(s):
    return {"files": s.files, "modules": s.modules, "ports": s.ports, "signals": s.signals,
            "params": s.params, "instances": s.instances, "functions": s.functions, "macros": s.macros}

def _sym_dict(s):
    return {"name": s.name, "kind": s.kind, "file": s.file,
            "range": {"start_line": s.range.start_line, "start_col": s.range.start_col,
                      "end_line": s.range.end_line, "end_col": s.range.end_col},
            "detail": s.detail, "container": s.container}

def _ref_dict(r):
    return {"name": r.name, "file": r.file, "context": r.context,
            "range": {"start_line": r.range.start_line, "start_col": r.range.start_col,
                      "end_line": r.range.end_line, "end_col": r.range.end_col}}

def _module_dict(m):
    return {"name": m.name,
            "ports": [{"name": p.name, "direction": p.direction, "type": p.data_type, "width": p.width} for p in m.ports],
            "params": [{"name": p.name, "detail": p.detail} for p in m.params],
            "signals": [{"name": s.name, "type": s.data_type, "width": s.width} for s in m.signals],
            "instances": [{"inst_name": i.inst_name, "module_type": i.module_type} for i in m.instances]}

def _constraint_dict(c):
    return {"signal": c.signal, "pin": c.pin, "iostandard": c.iostandard, "file": c.file}


def run_mcp(include_paths=None, stub_dir=None, index_root=None, defines=None):
    MCPServer(include_paths=include_paths, stub_dir=stub_dir, index_root=index_root,
              defines=defines).run()
