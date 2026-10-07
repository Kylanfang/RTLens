"""AI REST API（零依赖 stdlib http.server）。

端点：
  GET  /api/health              健康检查
  POST /api/index               索引工程目录 {root: "..."}
  GET  /api/stats               索引统计
  GET  /api/symbols?query=       工作区符号搜索
  GET  /api/module/{name}       模块详情（端口/参数/例化）
  GET  /api/references/{name}    全部引用
  GET  /api/instances/{module}   谁例化了此模块
  GET  /api/hierarchy/{top}      例化层级树
  GET  /api/drivers?file=...&signal=...   信号驱动源
  GET  /api/constraints?signal=  引脚约束
  GET  /api/primitives           eLinx 原语列表
  POST /api/parse                解析代码片段 {code: "..."}
  POST /api/expand               预处理（宏展开）{code: "..."}
  GET  /api/macros               宏定义列表
  GET  /api/code-lens?file=       代码透镜
  GET  /api/semantic-tokens?file= 语义 token
  GET  /api/folding?file=         折叠区域
  GET  /api/inlay-hints?file=&start=&end=  Inlay hints
  GET  /api/document-tree?file=   层级符号树
  POST /api/rename               跨文件重命名 {file, line, col, newName}
  POST /api/prepare-rename       检查可重命名 {file, line, col}
  GET  /api/lint?file=&max_results=  Verible lint 检查
  GET  /api/syntax-check?file=     Verible 语法检查
  GET  /api/benchmark              MCP vs grep 提速基准
  GET  /api/performance            实时性能监控数据（MCP/API 全部真实耗时）

设计：所有响应 JSON，AI agent 可直接消费。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, Optional

from .indexer import WorkspaceIndex
from .elinx import ELinxSupport
from .ai_tools import AITools
from .preprocessor import Preprocessor
from .parser import parse
from .webui import DASHBOARD_HTML
from .monitor import get_monitor, read_bridge_snapshot


class _APIState:
    index: WorkspaceIndex
    elinx: ELinxSupport
    ai: AITools
    index_root: Optional[str] = None


_STATE = _APIState()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默

    def _json(self, code: int, data: Any):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        monitor = get_monitor()
        t0 = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            result = self._handle_get(path, parsed)
            duration_ms = (time.perf_counter() - t0) * 1000
            monitor.record("api_get", path, duration_ms, success=True,
                          detail=path[:100])
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            monitor.record("api_get", path, duration_ms, success=False,
                          error=str(e)[:200], detail=path[:100])
            raise

    def _handle_get(self, path, parsed):
        qs = parse_qs(parsed.query)
        idx = _STATE.index
        elx = _STATE.elinx

        # Web UI 仪表盘
        if path == "/" or path == "/ui" or path == "/dashboard" or path == "/index.html":
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/health":
            return self._json(200, {"status": "ok", "stats": _stats_dict(idx.stats)})

        if path == "/api/files":
            return self._json(200, sorted(idx._files.keys()))

        if path == "/api/stats":
            return self._json(200, _stats_dict(idx.stats))

        if path == "/api/symbols":
            q = qs.get("query", [""])[0]
            syms = idx.workspace_symbols(q, limit=200)
            return self._json(200, [_sym_dict(s) for s in syms])

        if path.startswith("/api/module/"):
            name = path.split("/api/module/")[1]
            mod = idx.get_module(name)
            if not mod:
                return self._json(404, {"error": f"module '{name}' not found"})
            return self._json(200, _module_dict(mod))

        if path.startswith("/api/references/"):
            name = path.split("/api/references/")[1]
            refs = idx.find_references(name)
            return self._json(200, [_ref_dict(r) for r in refs])

        if path.startswith("/api/instances/"):
            name = path.split("/api/instances/")[1]
            insts = idx.who_instantiates(name)
            return self._json(200, [_sym_dict(s) for s in insts])

        if path.startswith("/api/hierarchy/"):
            name = path.split("/api/hierarchy/")[1]
            return self._json(200, idx.get_hierarchy(name))

        if path == "/api/drivers":
            fp = qs.get("file", [""])[0]
            sig = qs.get("signal", [""])[0]
            drivers = idx.get_signal_drivers(fp, sig)
            return self._json(200, [_ref_dict(d) for d in drivers])

        if path == "/api/constraints":
            sig = qs.get("signal", [""])[0]
            if sig:
                c = elx.get_pin(sig)
                return self._json(200, _constraint_dict(c) if c else None)
            return self._json(200, [_constraint_dict(c) for c in elx.get_all_constraints()])

        if path == "/api/primitives":
            return self._json(200, sorted(elx.stub_modules.keys()))

        if path == "/api/macros":
            macros = idx.get_macros()
            return self._json(200, [{"name": k, "detail": v.detail, "file": v.file} for k, v in macros.items()])

        # ---- v2.0.0 新增端点 ----

        if path == "/api/code-lens":
            fp = qs.get("file", [""])[0]
            if fp:
                return self._json(200, idx.get_code_lens(fp))
            return self._json(400, {"error": "file parameter required"})

        if path == "/api/semantic-tokens":
            fp = qs.get("file", [""])[0]
            if fp:
                fidx = idx._files.get(fp)
                if not fidx:
                    return self._json(404, {"error": "file not indexed"})
                from .semantic import compute_semantic_tokens, TOKEN_TYPES, TOKEN_MODIFIERS
                return self._json(200, {
                    "tokenTypes": TOKEN_TYPES,
                    "tokenModifiers": TOKEN_MODIFIERS,
                    "data": compute_semantic_tokens(fidx.text),
                })
            return self._json(400, {"error": "file parameter required"})

        if path == "/api/folding":
            fp = qs.get("file", [""])[0]
            if fp:
                fidx = idx._files.get(fp)
                if not fidx:
                    return self._json(404, {"error": "file not indexed"})
                from .semantic import compute_folding_ranges
                return self._json(200, compute_folding_ranges(fidx.text))
            return self._json(400, {"error": "file parameter required"})

        if path == "/api/inlay-hints":
            fp = qs.get("file", [""])[0]
            if fp:
                start = int(qs.get("start", ["0"])[0])
                end = int(qs.get("end", ["9999"])[0])
                return self._json(200, idx.get_inlay_hints(fp, start, end))
            return self._json(400, {"error": "file parameter required"})

        if path == "/api/document-tree":
            fp = qs.get("file", [""])[0]
            if fp:
                return self._json(200, idx.document_symbol_tree(fp))
            return self._json(400, {"error": "file parameter required"})

        # ---- v3.0 AI 端点 ----
        if path == "/api/analyze":
            return self._json(200, _STATE.ai.analyze_design())

        if path == "/api/metrics":
            return self._json(200, _STATE.ai.get_design_metrics())

        if path == "/api/check":
            return self._json(200, _STATE.ai.check_port_mismatches())

        if path.startswith("/api/template/testbench/"):
            mod_name = path.split("/api/template/testbench/")[1]
            return self._json(200, {"code": _STATE.ai.generate_testbench(mod_name)})

        if path.startswith("/api/template/instantiation/"):
            mod_name = path.split("/api/template/instantiation/")[1]
            inst = qs.get("inst", ["u_inst"])[0]
            return self._json(200, {"code": _STATE.ai.generate_instantiation(mod_name, inst)})

        if path.startswith("/api/trace/"):
            sig = path.split("/api/trace/")[1]
            fp = qs.get("file", [""])[0]
            return self._json(200, _STATE.ai.trace_signal(sig, fp))

        if path == "/api/search":
            q = qs.get("q", [""])[0]
            k = qs.get("kind", [""])[0]
            return self._json(200, _STATE.ai.search_code(q, k))

        if path == "/api/context":
            mod = qs.get("module", [""])[0]
            fp = qs.get("file", [""])[0]
            return self._json(200, {"text": _STATE.ai.get_context_for_ai(fp, mod)})

        # ---- v4.4 Verible lint / syntax-check / benchmark ----
        if path == "/api/lint":
            fp = qs.get("file", [""])[0]
            if not fp:
                return self._json(400, {"error": "file parameter required"})
            max_results = int(qs.get("max_results", ["200"])[0])
            verible = _STATE.index._verible
            if verible and verible.available:
                result = verible.lint(fp, max_results=max_results)
                return self._json(200, result)
            return self._json(200, {"file": fp, "error": "verible not available",
                                     "violation_count": 0, "violations": [], "passed": True})

        if path == "/api/syntax-check":
            fp = qs.get("file", [""])[0]
            if not fp:
                return self._json(400, {"error": "file parameter required"})
            verible = _STATE.index._verible
            if verible and verible.available:
                result = verible.syntax_check(fp)
                return self._json(200, result)
            return self._json(200, {"file": fp, "error": "verible not available",
                                     "error_count": 0, "errors": [], "passed": True})

        if path == "/api/benchmark":
            return self._json(200, _run_benchmark(_STATE.index))

        if path == "/api/performance":
            # v5.1.1: 优先读外部 MCP 进程的桥接快照（workbuddy 通过 stdio 拉起的 MCP 进程），
            # 这样浏览器看板显示的就是 workbuddy 实际触发的 MCP 调用耗时；
            # 桥接不存在/过期时回退到本进程监控。
            bridge = read_bridge_snapshot(_STATE.index_root, max_age_seconds=300.0)
            if bridge is not None:
                return self._json(200, bridge)
            snap = get_monitor().get_snapshot()
            snap["source"] = "this_process"
            snap["bridge_age_seconds"] = None
            return self._json(200, snap)

        # ---- v4.5 batch lint / design summary / module graph ----
        if path == "/api/lint-all":
            return self._json(200, _run_batch_lint(_STATE.index))

        if path == "/api/design-summary":
            return self._json(200, _run_design_summary(_STATE.index))

        if path == "/api/module-graph":
            return self._json(200, _build_module_graph(_STATE.index))

        if path == "/api/code-search":
            pattern = qs.get("q", [""])[0]
            if not pattern:
                return self._json(400, {"error": "q parameter required"})
            return self._json(200, _code_search(_STATE.index, pattern))

        return self._json(404, {"error": f"unknown endpoint: {path}"})

    def do_POST(self):
        monitor = get_monitor()
        t0 = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            result = self._handle_post(path, parsed)
            duration_ms = (time.perf_counter() - t0) * 1000
            monitor.record("api_post", path, duration_ms, success=True,
                          detail=path[:100])
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            monitor.record("api_post", path, duration_ms, success=False,
                          error=str(e)[:200], detail=path[:100])
            raise

    def _handle_post(self, path, parsed):
        try:
            body = self._read_body()
        except Exception as e:
            return self._json(400, {"error": f"invalid JSON: {e}"})
        idx = _STATE.index
        elx = _STATE.elinx

        if path == "/api/index":
            root = body.get("root", "")
            if not root or not os.path.isdir(root):
                return self._json(400, {"error": f"invalid root: {root}"})
            count = idx.index_directory(root)
            return self._json(200, {"indexed_files": count, "stats": _stats_dict(idx.stats)})

        if path == "/api/parse":
            code = body.get("code", "")
            result = parse(code)
            modules = [_module_dict(m) for m in result.modules]
            return self._json(200, {
                "modules": modules,
                "macros": [{"name": m.name, "value": m.value} for m in result.macros],
                "includes": [inc.path for inc in result.includes],
                "errors": result.errors[:20],
            })

        if path == "/api/expand":
            code = body.get("code", "")
            pp = Preprocessor()
            expanded = pp.process_text(code)
            return self._json(200, {"expanded": expanded, "macros": {k: v.value for k, v in pp.macros.items()}})

        if path == "/api/constraints/load":
            fp = body.get("file", "")
            if fp and os.path.isfile(fp):
                elx.parse_constraint_file(fp)
                return self._json(200, {"loaded": True, "constraints": len(elx.constraints)})
            return self._json(400, {"error": "file not found"})

        # ---- v2.0.0 新增 POST 端点 ----

        if path == "/api/rename":
            fp = body.get("file", "")
            line = body.get("line", 0)
            col = body.get("col", 0)
            new_name = body.get("newName", "")
            if not fp or not new_name:
                return self._json(400, {"error": "file and newName required"})
            result = idx.rename_symbol(fp, line, col, new_name)
            if not result:
                return self._json(404, {"error": "symbol not found or not renameable"})
            return self._json(200, result)

        if path == "/api/prepare-rename":
            fp = body.get("file", "")
            line = body.get("line", 0)
            col = body.get("col", 0)
            if not fp:
                return self._json(400, {"error": "file required"})
            result = idx.prepare_rename(fp, line, col)
            if not result:
                return self._json(404, {"error": "no symbol at position"})
            return self._json(200, result)

        return self._json(404, {"error": f"unknown endpoint: {path}"})


# ---- 序列化 ----

def _stats_dict(s) -> Dict:
    return {"files": s.files, "modules": s.modules, "ports": s.ports, "signals": s.signals,
            "params": s.params, "instances": s.instances, "functions": s.functions, "macros": s.macros}

def _sym_dict(s) -> Dict:
    return {"name": s.name, "kind": s.kind, "file": s.file,
            "range": {"start_line": s.range.start_line, "start_col": s.range.start_col,
                      "end_line": s.range.end_line, "end_col": s.range.end_col},
            "detail": s.detail, "container": s.container}

def _ref_dict(r) -> Dict:
    return {"name": r.name, "file": r.file, "context": r.context,
            "range": {"start_line": r.range.start_line, "start_col": r.range.start_col,
                      "end_line": r.range.end_line, "end_col": r.range.end_col}}

def _module_dict(m) -> Dict:
    return {
        "name": m.name,
        "range": {"start_line": m.range.start_line, "start_col": m.range.start_col,
                  "end_line": m.range.end_line, "end_col": m.range.end_col},
        "ports": [{"name": p.name, "direction": p.direction, "type": p.data_type, "width": p.width, "detail": p.detail} for p in m.ports],
        "params": [{"name": p.name, "detail": p.detail} for p in m.params],
        "signals": [{"name": s.name, "type": s.data_type, "width": s.width} for s in m.signals],
        "instances": [{"inst_name": i.inst_name, "module_type": i.module_type,
                       "connections": [{"port": c.port_name, "signal": c.signal_text} for c in i.connections]} for i in m.instances],
        "functions": [{"name": f.name, "detail": f.detail} for f in m.functions],
    }

def _constraint_dict(c) -> Dict:
    return {"signal": c.signal, "pin": c.pin, "iostandard": c.iostandard,
            "drive": c.drive, "slew": c.slew, "file": c.file, "line": c.line}


def _run_benchmark(idx: WorkspaceIndex) -> Dict:
    """运行 MCP vs grep 提速基准测试。

    对同一组查询（符号搜索、引用查找、信号追踪）分别用索引器（MCP 方式）
    和 grep（传统方式）计时，返回对比数据。
    """
    import tempfile
    import shutil

    # 收集已索引文件路径
    files = list(idx._files.keys())
    if not files:
        return {"error": "no files indexed", "tests": []}

    # 选 3 个有代表性的符号做测试
    test_symbols = []
    for name in sorted(idx._module_defs.keys())[:5]:
        test_symbols.append(name)
    if not test_symbols:
        for name in list(idx._all_symbols.keys())[:5]:
            test_symbols.append(name)
    if not test_symbols:
        return {"error": "no symbols found", "tests": []}

    # 取前 3 个做基准测试
    test_symbols = test_symbols[:3]

    results = []
    for sym in test_symbols:
        # --- MCP 方式：用索引器查询 ---
        t0 = time.perf_counter()
        mcp_refs = idx.find_references(sym)
        mcp_time = (time.perf_counter() - t0) * 1000  # ms

        # --- grep 方式：用 subprocess 调 grep ---
        grep_time = 0
        grep_count = 0
        try:
            # 把所有已索引文件写到一个临时目录（grep 需要文件系统路径）
            with tempfile.TemporaryDirectory() as tmpdir:
                for fp in files:
                    try:
                        shutil.copy2(fp, os.path.join(tmpdir, os.path.basename(fp)))
                    except Exception:
                        pass

                t0 = time.perf_counter()
                proc = subprocess.run(
                    ["grep", "-rn", "--include=*.v", "--include=*.sv", sym, tmpdir],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
                )
                grep_time = (time.perf_counter() - t0) * 1000  # ms
                grep_count = proc.stdout.count(b"\n")
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            grep_time = -1  # grep 不可用或超时

        speedup = grep_time / mcp_time if mcp_time > 0 and grep_time > 0 else 0
        results.append({
            "symbol": sym,
            "mcp_time_ms": round(mcp_time, 2),
            "grep_time_ms": round(grep_time, 2) if grep_time > 0 else None,
            "mcp_ref_count": len(mcp_refs),
            "grep_match_count": grep_count,
            "speedup": round(speedup, 1) if speedup > 0 else None,
        })

    # 汇总
    avg_speedup = sum(r["speedup"] or 0 for r in results) / max(1, len(results))
    total_mcp = sum(r["mcp_time_ms"] for r in results)
    total_grep = sum(r["grep_time_ms"] or 0 for r in results)

    return {
        "file_count": len(files),
        "module_count": idx.stats.modules,
        "tests": results,
        "avg_speedup": round(avg_speedup, 1),
        "total_mcp_ms": round(total_mcp, 2),
        "total_grep_ms": round(total_grep, 2),
        "summary": f"MCP 索引查询平均比 grep 快 {avg_speedup:.0f} 倍 "
                   f"({total_mcp:.1f}ms vs {total_grep:.1f}ms)",
    }


def _run_batch_lint(idx: WorkspaceIndex) -> Dict:
    """批量 lint 所有已索引文件，返回汇总。"""
    verible = idx._verible
    if not verible or not verible.available:
        return {"error": "verible not available", "files": [], "total_violations": 0}
    files = list(idx._files.keys())
    results = []
    total_violations = 0
    for fp in files:
        r = verible.lint(fp, max_results=500)
        vc = r.get("violation_count", 0)
        total_violations += vc
        results.append({
            "file": os.path.basename(fp),
            "path": fp,
            "violations": vc,
            "passed": r.get("passed", True),
            "by_rule": r.get("by_rule", {}),
        })
    # 按违规数降序
    results.sort(key=lambda x: x["violations"], reverse=True)
    return {
        "file_count": len(files),
        "total_violations": total_violations,
        "clean_files": sum(1 for r in results if r["violations"] == 0),
        "dirty_files": sum(1 for r in results if r["violations"] > 0),
        "files": results,
    }


def _run_design_summary(idx: WorkspaceIndex) -> Dict:
    """生成设计摘要：模块清单、端口统计、实例化层级、参数使用。"""
    modules = []
    for name, locs in sorted(idx._module_defs.items()):
        mod = idx.get_module(name)
        if not mod:
            continue
        port_list = [{"name": p.name, "dir": p.direction, "width": p.width}
                      for p in mod.ports]
        inst_list = [{"name": i.inst_name, "type": i.module_type}
                      for i in mod.instances]
        param_list = [{"name": p.name, "detail": p.detail}
                       for p in mod.params]
        modules.append({
            "name": name,
            "file": os.path.basename(locs[0].file),
            "ports": port_list,
            "params": param_list,
            "signals": len(mod.signals),
            "instances": inst_list,
            "functions": len(mod.functions),
        })
    # 找顶层模块（被其他模块例化的模块 = 非顶层）
    instantiated = set()
    for locs in idx._instances.values():
        for sl in locs:
            pass  # already collected via _instantiates
    for name, children in idx._instantiates.items():
        for child in children:
            instantiated.add(child)
    top_modules = [m["name"] for m in modules if m["name"] not in instantiated]
    return {
        "stats": {
            "files": idx.stats.files,
            "modules": idx.stats.modules,
            "ports": idx.stats.ports,
            "signals": idx.stats.signals,
            "params": idx.stats.params,
            "instances": idx.stats.instances,
            "functions": idx.stats.functions,
            "macros": idx.stats.macros,
        },
        "top_modules": top_modules,
        "modules": modules,
    }


def _build_module_graph(idx: WorkspaceIndex) -> Dict:
    """构建模块依赖图（用于前端可视化）。"""
    nodes = []
    edges = []
    for name in sorted(idx._module_defs.keys()):
        mod = idx.get_module(name)
        port_count = len(mod.ports) if mod else 0
        inst_count = len(mod.instances) if mod else 0
        nodes.append({
            "id": name,
            "label": name,
            "ports": port_count,
            "instances": inst_count,
        })
    for parent, children in idx._instantiates.items():
        for child in children:
            edges.append({"from": parent, "to": child})
    return {"nodes": nodes, "edges": edges}


def _code_search(idx: WorkspaceIndex, pattern: str) -> Dict:
    """正则搜索所有已索引文件内容。"""
    import re
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"invalid regex: {e}", "matches": []}
    matches = []
    for fp, ifile in idx._files.items():
        for i, line in enumerate(ifile.text.split("\n"), 1):
            if regex.search(line):
                matches.append({
                    "file": os.path.basename(fp),
                    "path": fp,
                    "line": i,
                    "text": line.strip()[:200],
                })
                if len(matches) >= 200:
                    return {"pattern": pattern, "match_count": len(matches), "truncated": True, "matches": matches}
    return {"pattern": pattern, "match_count": len(matches), "truncated": False, "matches": matches}


def run_api(host: str = "127.0.0.1", port: int = 8765, index_root: Optional[str] = None,
            include_paths=None, stub_dir=None, defines=None):
    _STATE.index = WorkspaceIndex(include_paths=include_paths, defines=defines)
    _STATE.elinx = ELinxSupport(stub_dir=stub_dir)
    _STATE.index_root = index_root
    if index_root and os.path.isdir(index_root):
        _STATE.index.index_directory(index_root)
    _STATE.ai = AITools(_STATE.index)
    server = HTTPServer((host, port), _Handler)
    print(f"[rtlens] REST API serving on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
