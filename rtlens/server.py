"""LSP 服务器 — 参考 rust-analyzer 架构的高仿版本。

v2.0.0 — 在 v1.0.0 基础上新增：
- semanticTokens/full（语义高亮）
- foldingRange（折叠区域）
- selectionRange（逐层选择）
- documentHighlight（文档内高亮）
- codeLens（代码透镜：引用计数/导航）
- inlayHint（端口名提示）
- rename / prepareRename（跨文件重命名）
- hierarchicalDocumentSymbol（层级符号树）
- ServerConfig（初始化配置管理）

v2.1.0 — bug 修复 + 兼容性增强：
- 修复 Windows URI 路径转换（file:///C:/ → C:\）
- 修复 documentSymbolProvider 重复声明
- 增强索引线程错误处理
- 统一路径归一化
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from .indexer import WorkspaceIndex
from .elinx import ELinxSupport
from .parser import Range
from .diagnostics import run_diagnostics
from .config import ServerConfig
from . import __version__
from .semantic import (
    compute_semantic_tokens,
    compute_folding_ranges,
    compute_selection_ranges,
    compute_document_highlights,
    TOKEN_TYPES,
    TOKEN_MODIFIERS,
)


class LSPServer:
    def __init__(self, include_paths: Optional[List[str]] = None, stub_dir: Optional[str] = None,
                 defines: Optional[Dict[str, str]] = None):
        self.index = WorkspaceIndex(include_paths=include_paths, defines=defines)
        self.elinx = ELinxSupport(stub_dir=stub_dir)
        self.config = ServerConfig()
        self._shutdown = False
        self._root: Optional[str] = None
        # v6.1.0: 后台索引就绪门控 —— 索引完成前挂起依赖索引的请求，
        # 消除"初始化竞态"导致的假阳性诊断（unknown module）与空结果。
        self._index_ready = threading.Event()
        self._index_ready.set()  # 无后台索引任务时立即可用

    # ---- URI / 路径工具（跨平台） ----
    @staticmethod
    def _uri_to_path(uri: str) -> str:
        """将 file:// URI 转为本地路径（Windows/Linux/macOS 兼容）。"""
        if not uri:
            return ""
        # 处理 file:// 或 file:/// 前缀
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            path = unquote(parsed.path)
            # Windows: file:///C:/Users/... → C:\Users\...
            if os.name == "nt" and path.startswith("/"):
                # 去掉前导 /，如果后面跟的是驱动器字母
                if len(path) >= 3 and path[2] == ":" and path[1].isalpha():
                    path = path[1:]
                elif re.match(r"^/[A-Za-z]:", path) is None:
                    # POSIX 风格路径（无驱动器字母）：保持原样不做 normpath，
                    # 避免 Windows 宿主把 /home/... 改写成 \home\...
                    return path
            return os.path.normpath(path)
        return os.path.normpath(uri)

    @staticmethod
    def _path_to_uri(path: str) -> str:
        """将本地路径转为 file:// URI（Windows/Linux/macOS 兼容）。"""
        # 规范化路径分隔符
        abs_path = os.path.abspath(path)
        # 统一用 / 作为 URI 路径分隔符
        uri_path = abs_path.replace("\\", "/")
        # Windows 需要额外的 / 前缀
        if os.name == "nt":
            return "file:///" + uri_path
        return "file://" + uri_path

    # ---- JSON-RPC 帧 ----
    def _read_message(self) -> Optional[Dict]:
        headers: Dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower().decode("ascii", "replace")] = v.strip().decode("ascii", "replace")
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        body = sys.stdin.buffer.read(length)
        return json.loads(body)

    def _send(self, msg: Dict):
        data = json.dumps(msg).encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def _send_response(self, req_id: Any, result: Any):
        self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(self, req_id: Any, code: int, message: str):
        self._send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    def _notify(self, method: str, params: Any):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- 主循环 ----
    # v6.1.0: 这些方法依赖完整工作区索引；后台索引未就绪时等待（超时后降级继续）
    _INDEX_DEPENDENT = {
        "textDocument/definition", "textDocument/references",
        "textDocument/documentSymbol", "textDocument/hover",
        "textDocument/completion", "workspace/symbol",
        "textDocument/rename", "textDocument/prepareRename",
        "textDocument/codeLens", "textDocument/foldingRange",
        "textDocument/semanticTokens/full", "textDocument/inlayHint",
        "textDocument/documentHighlight", "textDocument/selectionRange",
    }

    def run(self):
        while not self._shutdown:
            try:
                msg = self._read_message()
                if msg is None:
                    break
                method = msg.get("method", "")
                params = msg.get("params", {})
                req_id = msg.get("id")
                if method in self._INDEX_DEPENDENT:
                    # 最多等 30s；超时后照常处理（结果可能不完整，但可响应）
                    self._index_ready.wait(timeout=30.0)
                self._dispatch(method, params, req_id)
            except KeyboardInterrupt:
                break
            except Exception:
                traceback.print_exc(file=sys.stderr)

    def _dispatch(self, method: str, params: Any, req_id: Any):
        handler = getattr(self, f"_h_{method.replace('/', '_').replace('$', '_')}", None)
        if handler is None:
            if req_id is not None:
                self._send_error(req_id, -32601, f"Method not found: {method}")
            return
        try:
            result = handler(params)
            if req_id is not None:
                self._send_response(req_id, result)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            if req_id is not None:
                self._send_error(req_id, -32603, str(e))

    # ---- initialize ----
    def _h_initialize(self, p: Dict) -> Dict:
        opts = p.get("initializationOptions", {})
        self.config = ServerConfig.from_dict(opts)

        self._root = p.get("rootUri", "") or p.get("rootPath", "")
        if self._root:
            root = self._uri_to_path(self._root) if self._root.startswith("file://") else self._root
            if root and os.path.isdir(root):
                self._index_ready.clear()  # 索引期间挂起依赖索引的请求
                def _bg_index():
                    try:
                        self.index.index_directory(root)
                    except Exception:
                        traceback.print_exc(file=sys.stderr)
                    finally:
                        self._index_ready.set()
                threading.Thread(target=_bg_index, daemon=True).start()

        caps = {
            "textDocumentSync": {
                "openClose": True,
                "change": 1,  # full sync
            },
            # 基础能力
            "definitionProvider": True,
            "referencesProvider": True,
            "documentSymbolProvider": True,
            "hoverProvider": True,
            "completionProvider": {
                "triggerCharacters": [".", "#", "`"],
                "resolveProvider": False,
            },
            "documentFormattingProvider": True,
            "workspaceSymbolProvider": True,
            # v2.0.0 新增 — rust-analyzer 风格
            "renameProvider": {
                "prepareProvider": True,
            },
            "codeLensProvider": {
                "resolveProvider": False,
            },
            "semanticTokensProvider": {
                "legend": {
                    "tokenTypes": TOKEN_TYPES,
                    "tokenModifiers": TOKEN_MODIFIERS,
                },
                "full": True,
                "range": False,
            },
            "foldingRangeProvider": True,
            "selectionRangeProvider": True,
            "documentHighlightProvider": True,
            "inlayHintProvider": True,
        }

        return {
            "capabilities": caps,
            "serverInfo": {
                "name": "rtlens",
                "version": __version__,
            },
        }

    def _h_initialized(self, p: Dict):
        pass

    def _h_shutdown(self, p: Any) -> None:
        self._shutdown = True
        return None

    # ---- 文档同步 ----
    def _h_textDocument_didOpen(self, p: Dict):
        td = p["textDocument"]
        uri = td["uri"]
        path = self._uri_to_path(uri)
        self.index.index_file(path, text=td["text"], version=td.get("version", 0))
        self._publish_diagnostics(path)

    def _h_textDocument_didChange(self, p: Dict):
        td = p["textDocument"]
        uri = td["uri"]
        path = self._uri_to_path(uri)
        changes = p.get("contentChanges", [])
        if changes:
            self.index.index_file(path, text=changes[-1]["text"], version=td.get("version", 0))
            self._publish_diagnostics(path)

    def _h_textDocument_didClose(self, p: Dict):
        pass

    # ---- 导航 ----
    def _h_textDocument_definition(self, p: Dict) -> Optional[Dict]:
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        loc = self.index.find_definition(path, pos["line"], pos["character"])
        if loc:
            return self._loc(loc)
        return None

    def _h_textDocument_references(self, p: Dict) -> List[Dict]:
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        loc = self.index.find_definition(path, pos["line"], pos["character"])
        name = loc.name if loc else self._ident_at(path, pos["line"], pos["character"])
        if not name:
            return []
        refs = self.index.find_references(name)
        return [self._loc(r) for r in refs]

    def _h_textDocument_documentSymbol(self, p: Dict) -> List[Dict]:
        """层级文档符号 — 参考 rust-analyzer hierarchicalDocumentSymbolSupport。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        # 优先使用层级符号树
        tree = self.index.document_symbol_tree(path)
        if tree:
            return tree
        # 降级到平面列表
        syms = self.index.document_symbols(path)
        out = []
        for s in syms:
            out.append({
                "name": s.name,
                "kind": self._symbol_kind(s.kind),
                "range": self._range(s.range),
                "selectionRange": self._range(s.name_range),
                "detail": s.detail,
                "children": [],
            })
        return out

    def _h_textDocument_hover(self, p: Dict) -> Optional[Dict]:
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        loc = self.index.find_definition(path, pos["line"], pos["character"])
        if not loc:
            return None
        lines = []
        lines.append("```systemverilog")
        lines.append(f"{loc.kind} {loc.name}")
        if loc.detail:
            lines.append(f"// {loc.detail}")
        if loc.container:
            lines.append(f"// in module: {loc.container}")
        lines.append("```")
        if loc.kind == "module":
            mod = self.index.get_module(loc.name)
            if mod:
                lines.append("")
                lines.append(f"**Ports ({len(mod.ports)}):**")
                for pt in mod.ports[:20]:
                    parts = [pt.direction, pt.data_type, pt.width, pt.name]
                    lines.append(f"- `{' '.join(p for p in parts if p)}`")
                if len(mod.ports) > 20:
                    lines.append(f"- ... and {len(mod.ports) - 20} more")
                if mod.params:
                    lines.append(f"**Parameters ({len(mod.params)}):**")
                    for pm in mod.params[:10]:
                        lines.append(f"- `{pm.detail}`")
                if mod.instances:
                    lines.append(f"**Instances ({len(mod.instances)}):**")
                    for inst in mod.instances[:10]:
                        lines.append(f"- `{inst.module_type} {inst.inst_name}`")
        elif loc.kind == "instance":
            if self.elinx.is_known_primitive(loc.name):
                ports = self.elinx.get_stub_ports(loc.name)
                lines.append("")
                lines.append(f"**eLinx Primitive — {loc.name}**")
                for pt in ports:
                    lines.append(f"- `{pt.direction} {pt.name}`")
            pin = self.elinx.get_pin(loc.name)
            if pin and pin.pin:
                lines.append("")
                lines.append(f"**Pin:** {pin.pin}" + (f" ({pin.iostandard})" if pin.iostandard else ""))
        return {"contents": {"kind": "markdown", "value": "\n".join(lines)}}

    def _h_textDocument_completion(self, p: Dict) -> Dict:
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        word = self._ident_at(path, pos["line"], pos["character"]) or ""
        items = []
        seen = set()
        from .lexer import KEYWORDS
        for kw in sorted(KEYWORDS):
            if word.lower() in kw.lower() and kw not in seen:
                items.append({"label": kw, "kind": 14})  # Keyword
                seen.add(kw)
        for sl in self.index.workspace_symbols(word, limit=50):
            key = (sl.name, sl.kind)
            if key in seen:
                continue
            seen.add(key)
            items.append({"label": sl.name, "kind": self._symbol_kind(sl.kind), "detail": sl.detail})
        for name in sorted(self.elinx.stub_modules):
            if word.lower() in name.lower() and name not in seen:
                items.append({"label": name, "kind": 9, "detail": "eLinx primitive"})
                seen.add(name)
        return {"isIncomplete": False, "items": items}

    def _h_textDocument_formatting(self, p: Dict) -> List[Dict]:
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        idx = self.index._files.get(path)
        if not idx:
            return []
        from .formatter import format_verilog
        formatted = format_verilog(idx.text)
        lines = idx.text.split("\n")
        return [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": len(lines), "character": 0},
            },
            "newText": formatted,
        }]

    def _h_workspace_symbol(self, p: Dict) -> List[Dict]:
        query = p.get("query", "")
        out = []
        for sl in self.index.workspace_symbols(query, limit=200):
            out.append({
                "name": sl.name,
                "kind": self._symbol_kind(sl.kind),
                "location": self._loc(sl),
                "containerName": sl.container,
            })
        return out

    # ---- v2.0.0 新增：rust-analyzer 风格 LSP 方法 ----

    def _h_textDocument_rename(self, p: Dict) -> Optional[Dict]:
        """跨文件重命名 — 参考 rust-analyzer rename。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        new_name = p.get("newName", "")
        if not new_name:
            return None
        result = self.index.rename_symbol(path, pos["line"], pos["character"], new_name)
        if not result:
            return None
        # 把文件路径转为 file:// URI
        changes = {}
        for fp, edits in result.get("changes", {}).items():
            uri_str = fp if fp.startswith("file://") else self._path_to_uri(fp)
            changes[uri_str] = edits
        return {"changes": changes}

    def _h_textDocument_prepareRename(self, p: Dict) -> Optional[Dict]:
        """检查光标位置是否可重命名。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        result = self.index.prepare_rename(path, pos["line"], pos["character"])
        if not result:
            return None
        # 返回 range + placeholder
        return {
            "range": result["range"],
            "placeholder": result["placeholder"],
        }

    def _h_textDocument_codeLens(self, p: Dict) -> List[Dict]:
        """代码透镜 — 显示引用计数和模块导航。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        return self.index.get_code_lens(path)

    def _h_textDocument_semanticTokens_full(self, p: Dict) -> Dict:
        """语义 token 全量计算 — 参考 rust-analyzer semanticTokens。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        idx = self.index._files.get(path)
        if not idx:
            return {"data": []}
        tokens = compute_semantic_tokens(idx.text)
        return {"data": tokens}

    def _h_textDocument_foldingRange(self, p: Dict) -> List[Dict]:
        """折叠区域 — 参考 rust-analyzer foldingRange。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        idx = self.index._files.get(path)
        if not idx:
            return []
        return compute_folding_ranges(idx.text)

    def _h_textDocument_selectionRange(self, p: Dict) -> List[Dict]:
        """逐层选择范围 — 参考 rust-analyzer selectionRange。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        idx = self.index._files.get(path)
        if not idx:
            return []
        positions = [(pp["line"], pp["character"]) for pp in p.get("positions", [])]
        if not positions:
            return []
        return compute_selection_ranges(idx.text, positions)

    def _h_textDocument_documentHighlight(self, p: Dict) -> List[Dict]:
        """文档内高亮 — 同一符号在文件内所有出现。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        pos = p["position"]
        name = self._ident_at(path, pos["line"], pos["character"])
        if not name:
            return []
        idx = self.index._files.get(path)
        if not idx:
            return []
        return compute_document_highlights(idx.text, name)

    def _h_textDocument_inlayHint(self, p: Dict) -> List[Dict]:
        """Inlay hints — 端口名提示。"""
        uri = p["textDocument"]["uri"]
        path = self._uri_to_path(uri)
        rng = p.get("range", {})
        start_line = rng.get("start", {}).get("line", 0)
        end_line = rng.get("end", {}).get("line", 0xFFFF)
        return self.index.get_inlay_hints(path, start_line, end_line)

    # ---- diagnostics ----
    def _publish_diagnostics(self, path: str):
        if not self.config.diagnostics.enable:
            return
        # v6.1.0: 依赖全工作区索引的诊断（如 unknown module）等索引就绪再发布，
        # 避免后台索引未完成时发布假阳性
        self._index_ready.wait(timeout=30.0)
        idx = self.index._files.get(path)
        if not idx:
            return
        diags = run_diagnostics(idx.result, self.index, self.elinx)
        # 过滤被禁用的诊断
        if self.config.diagnostics.disabled:
            diags = [d for d in diags if d.get("source", "") not in self.config.diagnostics.disabled]
        # 限制最大条目
        if len(diags) > self.config.diagnostics.max_items:
            diags = diags[: self.config.diagnostics.max_items]
        uri = self._path_to_uri(path)
        self._notify("textDocument/publishDiagnostics", {
            "uri": uri,
            "diagnostics": diags,
        })

    # ---- 工具 ----
    def _loc(self, sl) -> Dict:
        r = sl.range if isinstance(sl.range, Range) else Range(**sl.range)
        return {
            "uri": self._path_to_uri(sl.file),
            "range": self._range(r),
        }

    def _range(self, r: Range) -> Dict:
        return {
            "start": {"line": r.start_line, "character": r.start_col},
            "end": {"line": r.end_line, "character": r.end_col},
        }

    def _symbol_kind(self, kind: str) -> int:
        return {
            "module": 2, "package": 3, "port": 8, "signal": 13,
            "parameter": 14, "instance": 15, "function": 12, "task": 12,
            "typedef": 23, "enum": 10, "macro": 6,
        }.get(kind, 13)

    def _ident_at(self, file: str, line: int, col: int) -> Optional[str]:
        return self.index._ident_at(file, line, col)


def run_server(include_paths=None, stub_dir=None, defines=None):
    LSPServer(include_paths=include_paths, stub_dir=stub_dir, defines=defines).run()
