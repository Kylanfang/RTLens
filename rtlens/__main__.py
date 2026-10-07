"""CLI 入口：python -m rtlens <command> [options]

Commands:
  lsp         启动 LSP 服务器（stdio JSON-RPC）
  api         启动 REST API 服务器
  mcp         启动 MCP 服务器（stdio JSON-RPC）
  tui         启动交互式终端
  web         启动 REST API + Web UI 仪表盘
  index       索引目录并打印统计
  query       查询符号
  parse       解析文件并打印 AST
  quickstart  一键启动：索引示例工程 + 打开 Web UI
  version     显示版本号

Use --version to see the version.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _parse_defines(items):
    """--define SIM --define W=8 → {"SIM":"1","W":"8"}（+define+ 语义）"""
    out = {}
    for s in items or []:
        if "=" in s:
            k, _, v = s.partition("=")
            out[k.strip()] = v.strip()
        elif s.strip():
            out[s.strip()] = "1"
    return out or None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rtlens", description="Verilog LSP + AI interface")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    sub = parser.add_subparsers(dest="command")

    p_lsp = sub.add_parser("lsp", help="Start LSP server (stdio)")
    p_lsp.add_argument("--include-path", "-I", action="append", default=[], help="Include search path")
    p_lsp.add_argument("--stub-dir", default=None, help="eLinx stub directory")
    p_lsp.add_argument("--root", default=None, help="Workspace root to auto-index")
    p_lsp.add_argument("--define", "-D", action="append", default=[], help="Builtin macro, e.g. -D SIM or -D W=8")

    p_api = sub.add_parser("api", help="Start REST API server")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8765)
    p_api.add_argument("--root", default=None, help="Project root to index")
    p_api.add_argument("--include-path", "-I", action="append", default=[])
    p_api.add_argument("--stub-dir", default=None)

    p_mcp = sub.add_parser("mcp", help="Start MCP server (stdio)")
    p_mcp.add_argument("--root", default=None)
    p_mcp.add_argument("--include-path", "-I", action="append", default=[])
    p_mcp.add_argument("--stub-dir", default=None)
    p_mcp.add_argument("--define", "-D", action="append", default=[], help="Builtin macro, e.g. -D SIM or -D W=8")

    p_index = sub.add_parser("index", help="Index directory and print stats")
    p_index.add_argument("root")
    p_index.add_argument("--include-path", "-I", action="append", default=[])
    p_index.add_argument("--define", "-D", action="append", default=[], help="Builtin macro, e.g. -D SIM or -D W=8")

    p_query = sub.add_parser("query", help="Query a symbol")
    p_query.add_argument("root", help="Project root")
    p_query.add_argument("name", help="Symbol name")
    p_query.add_argument("--include-path", "-I", action="append", default=[])
    p_query.add_argument("--define", "-D", action="append", default=[], help="Builtin macro, e.g. -D SIM or -D W=8")

    p_parse = sub.add_parser("parse", help="Parse a file and print AST")
    p_parse.add_argument("file")

    p_tui = sub.add_parser("tui", help="Start interactive terminal (TUI)")
    p_tui.add_argument("--root", default=None, help="Project root to index")
    p_tui.add_argument("--include-path", "-I", action="append", default=[])
    p_tui.add_argument("--stub-dir", default=None)

    p_web = sub.add_parser("web", help="Start REST API + Web UI dashboard")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.add_argument("--root", default=None, help="Project root to index")
    p_web.add_argument("--include-path", "-I", action="append", default=[])
    p_web.add_argument("--stub-dir", default=None)
    p_web.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    p_qs = sub.add_parser("quickstart", help="One-click: index examples + start Web UI")
    p_qs.add_argument("--port", type=int, default=8765)
    p_qs.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    p_qs.add_argument("--root", default=None, help="Project root (default: built-in examples)")

    # ---- v5.0 自动配置 ----
    p_setup = sub.add_parser("setup", help="Auto-configure: detect AI tools, write MCP config, self-test")
    p_setup.add_argument("--tool", default="auto",
                         choices=["auto", "claude-code", "cursor", "cline", "windsurf", "workbuddy", "zcode", "generic"],
                         help="AI tool to configure (default: auto-detect)")
    p_setup.add_argument("--project", default=None, help="Verilog project root directory")
    p_setup.add_argument("--pkg-dir", default=None, help="rtlens package directory")
    p_setup.add_argument("--skip-install", action="store_true", help="Skip pip install step")
    p_setup.add_argument("--list-tools", action="store_true", help="List detected AI tools and exit")

    # ---- v3.0 新增命令 ----
    p_tpl = sub.add_parser("template", help="Generate code templates (testbench / instance)")
    p_sub_tpl = p_tpl.add_subparsers(dest="template_cmd")
    p_tb = p_sub_tpl.add_parser("testbench", help="Generate testbench skeleton for a module")
    p_tb.add_argument("module", help="Module name")
    p_tb.add_argument("-r", "--root", default=".", help="Project root to index")
    p_inst = p_sub_tpl.add_parser("instance", help="Generate instantiation template for a module")
    p_inst.add_argument("module", help="Module name")
    p_inst.add_argument("-n", "--name", default="u_inst", help="Instance name (default: u_inst)")
    p_inst.add_argument("-r", "--root", default=".", help="Project root to index")

    p_trace = sub.add_parser("trace", help="Trace signal driver -> usage chain")
    p_trace.add_argument("signal", help="Signal name to trace")
    p_trace.add_argument("-f", "--file", default="", help="Specific file (optional)")
    p_trace.add_argument("-r", "--root", default=".", help="Project root to index")

    p_metrics = sub.add_parser("metrics", help="Show design metrics (fan-in/fan-out/depth)")
    p_metrics.add_argument("-r", "--root", default=".", help="Project root to index")

    p_check = sub.add_parser("check", help="Check port connection mismatches")
    p_check.add_argument("-r", "--root", default=".", help="Project root to index")

    p_ctx = sub.add_parser("context", help="Generate AI context summary")
    p_ctx.add_argument("-m", "--module", default="", help="Focus on specific module (optional)")
    p_ctx.add_argument("-r", "--root", default=".", help="Project root to index")

    # ---- v6.2.0 证据出口（rtlens.evidence/1 契约，见 docs/EVIDENCE_CONTRACT.md）----
    p_ev = sub.add_parser(
        "evidence",
        help="Emit the machine-readable evidence pack (rtlens.evidence/1) for downstream tools")
    p_ev.add_argument("root", help="Project root to index")
    p_ev.add_argument("--include-path", "-I", action="append", default=[],
                      help="Include search path")
    p_ev.add_argument("--define", "-D", action="append", default=[],
                      help="Builtin macro, e.g. -D SIM or -D W=8 (changes what the index contains)")
    p_ev.add_argument("--out", "-o", default=None, help="Also write the envelope to this file")
    p_ev.add_argument("--max-files", type=int, default=5000, help="Index at most N files")
    p_ev.add_argument("--max-signals", type=int, default=256,
                      help="Per-module signal cap (exceeding it sets signalsTruncated)")
    p_ev.add_argument("--max-connections", type=int, default=256,
                      help="Per-instance connection cap (exceeding it sets connectionsTruncated)")
    p_ev.add_argument("--json", action="store_true",
                      help="Print the envelope to stdout (single parseable document)")
    p_ev.add_argument("--compact", action="store_true", help="Single-line JSON instead of pretty")

    args = parser.parse_args(argv)

    if args.version:
        from . import __version__
        print(f"rtlens v{__version__}")
        return

    if not args.command:
        parser.print_help()
        return

    if args.command == "lsp":
        from .server import run_server
        run_server(include_paths=args.include_path or None, stub_dir=args.stub_dir,
                   defines=_parse_defines(args.define))

    elif args.command == "api":
        from .api import run_api
        try:
            run_api(host=args.host, port=args.port, index_root=args.root,
                    include_paths=args.include_path or None, stub_dir=args.stub_dir)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"[error] Port {args.port} already in use. Try --port {args.port + 1}", file=sys.stderr)
            else:
                raise

    elif args.command == "mcp":
        from .mcp_server import run_mcp
        run_mcp(include_paths=args.include_path or None, stub_dir=args.stub_dir, index_root=args.root,
                defines=_parse_defines(args.define))

    elif args.command == "index":
        from rtlens.indexer import WorkspaceIndex
        idx = WorkspaceIndex(include_paths=args.include_path or None,
                             defines=_parse_defines(args.define))
        count = idx.index_directory(args.root)
        s = idx.stats
        print(f"Indexed {count} files")
        print(f"  Modules:   {s.modules}")
        print(f"  Ports:     {s.ports}")
        print(f"  Signals:   {s.signals}")
        print(f"  Params:    {s.params}")
        print(f"  Instances: {s.instances}")
        print(f"  Functions: {s.functions}")
        print(f"  Macros:    {s.macros}")

    elif args.command == "evidence":
        from .evidence import build_evidence, EVIDENCE_SCHEMA
        from .indexer import WorkspaceIndex
        # A typo'd root must be a usage error, never an empty evidence pack: an
        # empty document reads as "this project has no modules", which a
        # downstream consumer has no way to distinguish from a real empty tree.
        if not os.path.isdir(args.root):
            print(f"rtlens evidence: root is not a directory: {args.root}", file=sys.stderr)
            return 2
        _defines = _parse_defines(args.define)
        _idx = WorkspaceIndex(include_paths=args.include_path or None, defines=_defines)
        _idx.index_directory(args.root, max_files=args.max_files)
        _ev = build_evidence(_idx, args.root, defines=_defines,
                             max_signals=args.max_signals,
                             max_connections=args.max_connections)
        _payload = json.dumps(_ev, ensure_ascii=False,
                              indent=None if args.compact else 2,
                              separators=(",", ":") if args.compact else None)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as _fh:
                _fh.write(_payload + "\n")
        if args.json:
            print(_payload)
        else:
            _s = _ev["stats"]
            print(f"{EVIDENCE_SCHEMA}: {_s['files']} files, {_s['modules']} modules, "
                  f"{_s['instances']} instances"
                  + (f" -> {args.out}" if args.out else " (pass --json for stdout)"),
                  file=sys.stderr)

    elif args.command == "query":
        from .indexer import WorkspaceIndex
        idx = WorkspaceIndex(include_paths=args.include_path or None,
                             defines=_parse_defines(args.define))
        idx.index_directory(args.root)
        syms = idx.workspace_symbols(args.name, limit=50)
        refs = idx.find_references(args.name)
        print(f"Symbol '{args.name}':")
        print(f"  Definitions: {len(syms)}")
        for s in syms:
            print(f"    [{s.kind}] {s.name} in {s.file}:{s.range.start_line} ({s.detail})")
        print(f"  References: {len(refs)}")
        for r in refs[:20]:
            print(f"    [{r.context}] {r.name} in {r.file}:{r.range.start_line}")

    elif args.command == "parse":
        from .parser import parse
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        result = parse(text)
        print(f"Modules: {len(result.modules)}")
        for mod in result.modules:
            print(f"  module {mod.name} ({len(mod.ports)} ports, {len(mod.params)} params, {len(mod.signals)} signals, {len(mod.instances)} instances)")
            for inst in mod.instances:
                print(f"    instance: {inst.module_type} {inst.inst_name} ({len(inst.connections)} connections)")
        print(f"Macros: {len(result.macros)}")
        print(f"Includes: {len(result.includes)}")
        if result.errors:
            print(f"Errors: {len(result.errors)}")
            for e in result.errors[:5]:
                print(f"  {e}")

    elif args.command == "tui":
        from .tui import run_tui
        run_tui(index_root=args.root, include_paths=args.include_path or None, stub_dir=args.stub_dir)

    elif args.command == "web":
        import threading
        import webbrowser as _wb
        from .api import run_api
        url = f"http://{args.host}:{args.port}"
        print(f"[rtlens] Web UI: {url}")
        if not args.no_browser:
            threading.Timer(1.0, lambda: _wb.open(url)).start()
        try:
            run_api(host=args.host, port=args.port, index_root=args.root,
                    include_paths=args.include_path or None, stub_dir=args.stub_dir)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"[error] Port {args.port} already in use. Try --port {args.port + 1}", file=sys.stderr)
            else:
                raise

    if args.command in ("template", "trace", "metrics", "check", "context"):
        from .indexer import WorkspaceIndex
        from .ai_tools import AITools
        import json as _json
        _idx = WorkspaceIndex()
        if os.path.isdir(args.root):
            _idx.index_directory(args.root)
        _ai = AITools(_idx)
        if args.command == "template":
            if args.template_cmd == "testbench":
                print(_ai.generate_testbench(args.module))
            elif args.template_cmd == "instance":
                print(_ai.generate_instantiation(args.module, args.name))
        elif args.command == "trace":
            print(_json.dumps(_ai.trace_signal(args.signal, args.file), indent=2, ensure_ascii=False))
        elif args.command == "metrics":
            print(_json.dumps(_ai.get_design_metrics(), indent=2, ensure_ascii=False))
        elif args.command == "check":
            issues = _ai.check_port_mismatches()
            if not issues:
                print("No port mismatches found.")
            else:
                print(_json.dumps(issues, indent=2, ensure_ascii=False))
        elif args.command == "context":
            print(_ai.get_context_for_ai("", args.module))
        return

    if args.command == "quickstart":
        import threading
        import webbrowser as _wb
        from .api import run_api

        # 确定要索引的目录
        if args.root:
            root = args.root
        else:
            # 使用内置示例
            pkg_dir = os.path.dirname(os.path.abspath(__file__))
            root = os.path.join(pkg_dir, "..", "examples", "hierarchy")
            root = os.path.normpath(root)
            if not os.path.isdir(root):
                root = os.path.join(pkg_dir, "..", "examples")
                root = os.path.normpath(root)

        url = f"http://127.0.0.1:{args.port}"
        print()
        print("=" * 56)
        print("  RTLens Web UI is starting...")
        print()
        print(f"  URL:   {url}")
        print(f"  Index: {root}")
        print()
        print("  Browser will open automatically.")
        print("  If not, copy the URL above into your browser.")
        print("  Press Ctrl+C to stop the server.")
        print("=" * 56)
        print()
        if not args.no_browser:
            threading.Timer(1.5, lambda: _wb.open(url)).start()
        try:
            run_api(host="127.0.0.1", port=args.port, index_root=root)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"[error] Port {args.port} already in use. Try --port {args.port + 1}", file=sys.stderr)
            else:
                raise


    elif args.command == "setup":
        from .auto_setup import run_setup, list_tools
        if args.list_tools:
            list_tools()
        else:
            success = run_setup(
                tool=args.tool,
                project_root=args.project,
                pkg_dir=args.pkg_dir,
                skip_install=args.skip_install,
            )
            if not success:
                sys.exit(1)


if __name__ == "__main__":
    # Propagate the handler's exit code. Without sys.exit() here, any
    # `return 1`/`return 2` from a command handler is silently discarded and the
    # process reports success — the one failure mode a caller cannot detect.
    sys.exit(main())
