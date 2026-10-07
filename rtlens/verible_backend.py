"""Verible 后端：用 Google 官方 verible-verilog-syntax 替换自定义解析器。

架构：
  verible-verilog-syntax --export_json (C++ 解析，快+准)
        ↓ JSON (CST 树)
  VeribleBackend (本文件，纯 Python 标准库)
        ↓ 提取 modules/ports/params/signals/instances
  填充到现有 WorkspaceIndex（数据结构不变，25 个 MCP 工具不变）

如果 verible 二进制不存在，自动回退到原有 Python 解析器。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


# ── CST 节点类型 ──────────────────────────────────────────────

class CSTNode:
    """CST 树节点（从 verible JSON 直接构建，不依赖 anytree）。"""
    __slots__ = ("tag", "start", "end", "children", "source", "parent")

    def __init__(self, raw: dict, source: bytes, parent: Optional["CSTNode"] = None):
        self.tag = raw.get("tag", "")
        self.start = raw.get("start")
        self.end = raw.get("end")
        self.source = source
        self.parent = parent
        self.children: List["CSTNode"] = []
        for child in raw.get("children", []):
            if child is not None:
                self.children.append(CSTNode(child, source, self))
        # verible 的 -export_json 只在叶子节点给出 start/end，
        # 中间节点为 None。这里用子节点的范围推导，使 .text 对
        # kPortDeclaration/kParamDeclaration 等中间节点也有效。
        if self.start is None and self.children:
            starts = [c.start for c in self.children if c.start is not None]
            if starts:
                self.start = min(starts)
        if self.end is None and self.children:
            ends = [c.end for c in self.children if c.end is not None]
            if ends:
                self.end = max(ends)

    @property
    def text(self) -> str:
        """从源码中截取本节点对应的文本。"""
        if self.start is not None and self.end is not None and self.source:
            return self.source[self.start:self.end].decode("utf-8", errors="replace")
        return ""

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def find(self, tag: str | list) -> Optional["CSTNode"]:
        """深度优先查找第一个匹配 tag 的子节点。"""
        tags = [tag] if isinstance(tag, str) else tag
        for child in self.children:
            if child.tag in tags:
                return child
        for child in self.children:
            found = child.find(tag)
            if found:
                return found
        return None

    def find_all(self, tag: str | list) -> List["CSTNode"]:
        """深度优先查找所有匹配 tag 的子节点。"""
        tags = [tag] if isinstance(tag, str) else tag
        results = []
        for child in self.children:
            if child.tag in tags:
                results.append(child)
            results.extend(child.find_all(tag))
        return results

    def find_identifier(self) -> Optional[str]:
        """在子树中找第一个标识符的文本。"""
        id_tags = ["SymbolIdentifier", "EscapedIdentifier"]
        node = self.find(id_tags)
        return node.text.strip() if node else None

    def ancestors(self) -> List["CSTNode"]:
        """从父节点到根节点的祖先链。"""
        out: List["CSTNode"] = []
        p = self.parent
        while p is not None:
            out.append(p)
            p = p.parent
        return out


# ── 行号工具 ──────────────────────────────────────────────────

def _extract_lint_rule(line: str) -> str:
    """从 verible lint 违规行提取规则名。

    行格式：`file:line:col-col: MESSAGE (PARAM). [Style: constants] [rule-id]`
    规则 id 在行尾 `[rule-id]`（kebab-case 无冒号）；某些行只有 `[Category: rule]`。
    提取失败返回空串。
    """
    import re as _re
    # 优先取行尾 [rule-id]（如 [explicit-parameter-storage-type]）
    m = _re.search(r"\[([a-zA-Z0-9_./-]+)\]\s*$", line)
    if m and ":" not in m.group(1):
        return m.group(1)
    # 兜底取 [Category: rule]
    m = _re.search(r"\[[A-Za-z]+:\s*([a-zA-Z0-9_./-]+)\]\s*$", line)
    return m.group(1) if m else ""


def _byte_to_line(source: bytes, offset: int) -> int:
    """字节偏移 → 行号（0-based）。"""
    return source[:offset].count(b"\n")


def _byte_to_col(source: bytes, offset: int) -> int:
    """字节偏移 → 列号（0-based）。"""
    nl = source.rfind(b"\n", 0, offset)
    return offset - (nl + 1) if nl >= 0 else offset


# ── 端口/参数提取 ─────────────────────────────────────────────

def _extract_port_info(node: CSTNode, source: bytes) -> Optional[dict]:
    """从 kPort / kPortDeclaration 节点提取端口信息（含真实位置）。"""
    direction = ""
    data_type = "wire"
    width = ""

    # 端口方向：verible export_json 中 input/output/inout 关键字直接以 tag 存在
    for kw_tag in ("input", "output", "inout"):
        kw_node = node.find(kw_tag)
        if kw_node:
            direction = kw_node.text.strip()
            break

    # 数据类型：wire/reg/logic 关键字直接以 tag 存在
    dt_node = node.find("kDataType")
    if dt_node:
        for kw_tag in ("wire", "reg", "logic"):
            kw = dt_node.find(kw_tag)
            if kw:
                data_type = kw.text.strip()
                break
        # 位宽：kDataType 内的 [x:y]
        width_text = dt_node.text.strip()
        if "[" in width_text and "]" in width_text:
            # 提取方括号内的内容
            import re
            m = re.search(r'\[([^\]]+)\]', width_text)
            if m:
                width = m.group(1)

    # 端口名
    name_node = node.find(["SymbolIdentifier", "EscapedIdentifier"])
    if not name_node:
        return None
    name = name_node.text.strip()
    if not name:
        return None

    return {
        "name": name,
        "direction": direction or "input",
        "data_type": data_type,
        "width": width,
        "line": _byte_to_line(source, name_node.start or 0),
        "col": _byte_to_col(source, name_node.start or 0),
        "end_line": _byte_to_line(source, name_node.end or 0),
        "end_col": _byte_to_col(source, name_node.end or 0),
    }


def _extract_param_info(node: CSTNode, source: bytes) -> Optional[dict]:
    """从 kParamDeclaration 节点提取参数信息（含真实位置）。"""
    is_localparam = False
    text = node.text.strip()

    # 检查是否是 localparam
    if "localparam" in text:
        is_localparam = True

    name_node = node.find(["SymbolIdentifier", "EscapedIdentifier"])
    if not name_node:
        return None
    name = name_node.text.strip()
    if not name:
        return None

    # 尝试提取默认值
    detail = "localparam" if is_localparam else "parameter"
    # 查找 = 后的值
    if "=" in text:
        parts = text.split("=", 1)
        if len(parts) > 1:
            detail = parts[1].strip().rstrip(";").strip()
            if is_localparam:
                detail = "localparam=" + detail
            else:
                detail = "parameter=" + detail

    return {
        "name": name, "detail": detail, "is_localparam": is_localparam,
        "line": _byte_to_line(source, name_node.start or 0),
        "col": _byte_to_col(source, name_node.start or 0),
        "end_line": _byte_to_line(source, name_node.end or 0),
        "end_col": _byte_to_col(source, name_node.end or 0),
    }


def _extract_signal_info(node: CSTNode, source: bytes) -> Optional[dict]:
    """从 kDataDeclaration / kNetDeclaration 节点提取信号信息（含真实位置）。"""
    # 跳过端口声明（已在 _extract_port_info 处理）
    if node.tag == "kPortDeclaration":
        return None

    data_type = "wire"
    width = ""

    # 数据类型：wire/reg/logic 关键字直接以 tag 存在
    dt_node = node.find("kDataType")
    if dt_node:
        for kw_tag in ("wire", "reg", "logic"):
            kw = dt_node.find(kw_tag)
            if kw:
                data_type = kw.text.strip()
                break
        width_text = dt_node.text.strip()
        if "[" in width_text and "]" in width_text:
            import re
            m = re.search(r'\[([^\]]+)\]', width_text)
            if m:
                width = m.group(1)

    # 找所有标识符（信号名），每个带真实位置
    items = []
    id_nodes = node.find_all(["SymbolIdentifier", "EscapedIdentifier"])
    for id_node in id_nodes:
        id_text = id_node.text.strip()
        # 跳过类型关键字（如 wire, reg）
        if id_text in ("wire", "reg", "logic", "integer", "input", "output", "inout",
                       "parameter", "localparam", "signed", "unsigned"):
            continue
        if id_text and not any(it["name"] == id_text for it in items):
            items.append({
                "name": id_text,
                "line": _byte_to_line(source, id_node.start or 0),
                "col": _byte_to_col(source, id_node.start or 0),
                "end_line": _byte_to_line(source, id_node.end or 0),
                "end_col": _byte_to_col(source, id_node.end or 0),
            })

    if not items:
        return None

    return {"names": items, "data_type": data_type, "width": width}


def _extract_instance_info(base: CSTNode, source: bytes) -> Optional[dict]:
    """从 kInstantiationBase（含 kInstantiationType + kGateInstance）提取实例信息。

    返回：inst_name / module_type / connections / 位置
    connections: [{port_name, signal_text, line, col, end_line, end_col}]
    """
    type_node = base.find("kInstantiationType")
    gate = base.find("kGateInstance")
    if not type_node or not gate:
        return None

    type_id = type_node.find(["SymbolIdentifier", "EscapedIdentifier"])
    inst_id = gate.find(["SymbolIdentifier", "EscapedIdentifier"])
    if not type_id or not inst_id:
        return None

    module_type = type_id.text.strip()
    inst_name = inst_id.text.strip()
    if not module_type or not inst_name:
        return None

    # 端口连接
    connections = []
    for actual in gate.find_all("kActualNamedPort"):
        ids = actual.find_all(["SymbolIdentifier", "EscapedIdentifier"])
        if not ids:
            continue
        port_name = ids[0].text.strip()
        expr = actual.find("kExpression")
        expr_id = expr.find(["SymbolIdentifier", "EscapedIdentifier"]) if expr else None
        signal_text = expr_id.text.strip() if expr_id else (expr.text.strip() if expr else "")
        # 用连接信号位置（无信号则用端口名位置）
        pos_node = expr_id or ids[0]
        connections.append({
            "port_name": port_name,
            "signal_text": signal_text,
            "line": _byte_to_line(source, pos_node.start or 0),
            "col": _byte_to_col(source, pos_node.start or 0),
            "end_line": _byte_to_line(source, pos_node.end or 0),
            "end_col": _byte_to_col(source, pos_node.end or 0),
        })
    # 位置连接（kPortActualList 的直接 kExpression 子节点，无端口名）
    for al in gate.find_all("kPortActualList"):
        for child in al.children:
            if child.tag == "kExpression":
                expr_id = child.find(["SymbolIdentifier", "EscapedIdentifier"])
                signal_text = expr_id.text.strip() if expr_id else child.text.strip()
                pos_node = expr_id or child
                connections.append({
                    "port_name": "",
                    "signal_text": signal_text,
                    "line": _byte_to_line(source, pos_node.start or 0),
                    "col": _byte_to_col(source, pos_node.start or 0),
                    "end_line": _byte_to_line(source, pos_node.end or 0),
                    "end_col": _byte_to_col(source, pos_node.end or 0),
                })

    return {
        "inst_name": inst_name,
        "module_type": module_type,
        "connections": connections,
        "line": _byte_to_line(source, inst_id.start or 0),
        "col": _byte_to_col(source, inst_id.start or 0),
        "end_line": _byte_to_line(source, inst_id.end or 0),
        "end_col": _byte_to_col(source, inst_id.end or 0),
    }


# ── Verible 后端主类 ──────────────────────────────────────────

class VeribleBackend:
    """用 verible-verilog-syntax 解析 Verilog 文件，提取结构化信息。

    用法：
        backend = VeribleBackend("verible-verilog-syntax")
        modules = backend.parse_file("design.v")
        # modules = [{name, ports, params, signals, instances, file, line}, ...]
    """

    def __init__(self, executable: str = "verible-verilog-syntax"):
        self.executable = executable
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """检测 verible 二进制是否可用。"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                [self.executable, "--help"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=5
            )
            self._available = result.returncode == 0 or result.returncode == 1
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self._available = False
        return self._available

    def parse_file(self, filepath: str) -> Optional[dict]:
        """用 verible 解析单个 Verilog 文件。

        返回：
            {filepath, source, tree, modules, errors}
            或 None（解析失败）
        """
        if not self.available:
            return None

        try:
            with open(filepath, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return None

        proc = subprocess.run(
            [self.executable, "-export_json", "-printtree", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        if proc.returncode not in (0, 1):  # verible 返回 1 表示有语法错误但仍有输出
            return None

        try:
            json_data = json.loads(proc.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        file_json = json_data.get(filepath, {})
        if not file_json:
            # verible 可能用完整路径，尝试找唯一的 key
            if len(json_data) == 1:
                file_json = list(json_data.values())[0]
            else:
                return None

        tree_raw = file_json.get("tree")
        if not tree_raw:
            return None

        tree = CSTNode(tree_raw, source)
        errors = file_json.get("errors", [])

        # 提取模块
        modules = self._extract_modules(tree, filepath, source)

        return {
            "filepath": filepath,
            "source": source,
            "tree": tree,
            "modules": modules,
            "errors": errors,
        }

    def parse_string(self, code: str) -> Optional[dict]:
        """用 verible 解析字符串（通过 stdin）。

        注意：必须以 bytes 喂给 stdin（binary mode）。
        Windows 上文本模式会把 \\n 翻译成 \\r\\n，导致 verible
        返回的字节偏移与源文件不一致，所有提取全部错位。
        """
        if not self.available:
            return None

        source = code.encode("utf-8")
        proc = subprocess.run(
            [self.executable, "-export_json", "-printtree", "-"],
            input=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        if proc.returncode not in (0, 1):
            return None

        try:
            json_data = json.loads(proc.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        file_json = json_data.get("-", {})
        if not file_json and len(json_data) == 1:
            file_json = list(json_data.values())[0]

        tree_raw = file_json.get("tree")
        if not tree_raw:
            return None

        tree = CSTNode(tree_raw, source)
        modules = self._extract_modules(tree, "<stdin>", source)
        errors = file_json.get("errors", [])

        return {
            "filepath": "<stdin>",
            "source": source,
            "tree": tree,
            "modules": modules,
            "errors": errors,
        }

    def _extract_modules(self, tree: CSTNode, filepath: str, source: bytes) -> List[dict]:
        """从 CST 中提取所有模块定义（含真实位置与引用）。"""
        modules = []

        for mod_node in tree.find_all("kModuleDeclaration"):
            header = mod_node.find("kModuleHeader")
            if not header:
                continue

            # 模块名
            name = header.find_identifier() or ""
            if not name:
                continue

            # 行号
            line = _byte_to_line(source, mod_node.start or 0) if mod_node.start else 0

            # 端口
            ports = []
            port_lists = header.find_all(["kPortDeclaration", "kPort"])
            for port_node in port_lists:
                # 避免重复：kPort 可能包含 kPortDeclaration
                if port_node.tag == "kPortDeclaration" or port_node.find("kPortDirection"):
                    info = _extract_port_info(port_node, source)
                    if info:
                        ports.append(info)

            # 参数
            params = []
            for param_node in header.find_all("kParamDeclaration"):
                info = _extract_param_info(param_node, source)
                if info:
                    params.append(info)

            # 信号
            signals = []
            body = mod_node.find("kModuleItemList")
            if body:
                for decl in body.find_all(["kDataDeclaration", "kNetDeclaration"]):
                    info = _extract_signal_info(decl, source)
                    if info:
                        for sig in info["names"]:
                            signals.append({
                                "name": sig["name"],
                                "data_type": info["data_type"],
                                "width": info["width"],
                                "line": sig["line"],
                                "col": sig["col"],
                                "end_line": sig["end_line"],
                                "end_col": sig["end_col"],
                            })

            # 实例化（kInstantiationBase 含类型名 + 实例 + 端口连接）
            instances = []
            if body:
                for inst_node in body.find_all("kInstantiationBase"):
                    info = _extract_instance_info(inst_node, source)
                    if info:
                        info["file"] = filepath
                        instances.append(info)

            # 引用（driver / usage / instantiation / port_connection）
            references = []
            if body:
                references = self._collect_refs(source, body, header)

            modules.append({
                "name": name,
                "file": filepath,
                "line": line,
                "ports": ports,
                "params": params,
                "signals": signals,
                "instances": instances,
                "references": references,
            })

        return modules

    def _collect_refs(self, source: bytes, body: CSTNode, header: CSTNode) -> List[dict]:
        """收集模块内的符号引用，按上下文分类：
        driver / usage / instantiation / port_connection（声明处由 indexer 自动补 declaration）。
        """
        refs: List[dict] = []

        def pos(node: CSTNode) -> dict:
            return {
                "line": _byte_to_line(source, node.start or 0),
                "col": _byte_to_col(source, node.start or 0),
                "end_line": _byte_to_line(source, node.end or 0),
                "end_col": _byte_to_col(source, node.end or 0),
            }

        def add(name: str, node: CSTNode, context: str):
            if name:
                refs.append({"name": name, "context": context, **pos(node)})

        marked = set()  # (start, end) 已标记的标识符位置

        def mark(node: CSTNode):
            if node.start is not None:
                marked.add((node.start, node.end))

        # 1. 赋值目标 → driver（kNetVariableAssignment 等节点内第一个标识符）
        for an in body.find_all([
                "kNonblockingAssignmentStatement", "kBlockingAssignmentStatement",
                "kContinuousAssignmentStatement"]):
            ids = an.find_all("SymbolIdentifier")
            if ids:
                add(ids[0].text.strip(), ids[0], "driver")
                mark(ids[0])

        # 2. 实例化类型名 → instantiation；实例名 → declaration
        for ib in body.find_all("kInstantiationBase"):
            type_node = ib.find("kInstantiationType")
            gate = ib.find("kGateInstance")
            if type_node:
                tids = type_node.find_all("SymbolIdentifier")
                if tids:
                    add(tids[0].text.strip(), tids[0], "instantiation")
                    mark(tids[0])
            if gate:
                gids = gate.find_all("SymbolIdentifier")
                if gids:
                    add(gids[0].text.strip(), gids[0], "declaration")
                    mark(gids[0])
                # 3. 命名端口连接 → port_connection（.port 名位置）
                for ap in gate.find_all("kActualNamedPort"):
                    aids = ap.find_all("SymbolIdentifier")
                    if aids:
                        add(aids[0].text.strip(), aids[0], "port_connection")
                        mark(aids[0])

        # 4. 其余标识符 → usage（跳过声明区/类型关键字/已标记）
        skip_ancestors = {
            "kPortDeclaration", "kDataDeclaration", "kNetDeclaration",
            "kParamDeclaration", "kLocalParamDeclaration",
            "kGateInstanceRegisterVariableList", "kUnpackedDimensions",
            "kInstantiationBase", "kInstantiationType", "kGateInstance",
        }
        for id_node in body.find_all("SymbolIdentifier"):
            if id_node.start is not None and (id_node.start, id_node.end) in marked:
                continue
            txt = id_node.text.strip()
            if not txt:
                continue
            if any(a.tag in skip_ancestors for a in id_node.ancestors()):
                continue
            add(txt, id_node, "usage")

        return refs

    # ── Verible 专属工具（lint / format / syntax check）──────────

    def lint(self, filepath: str, lint_executable: str = "verible-verilog-lint",
             max_results: int = 200) -> dict:
        """运行 verible linter。

        输出护栏（10MB 级文件实测）：12MB 文件可产生 21 万+ 违规（≈36MB 文本），
        若全部返回会撑爆 agent 上下文。因此默认只返回前 max_results 条，
        同时保留总违规数与按规则聚合统计，并置 violations_truncated 标志。
        max_results=0 表示不截断（谨慎使用）。
        """
        # 优先用 find_verible_binary 解析完整路径，避免依赖 PATH
        resolved = find_verible_binary(lint_executable) or lint_executable
        try:
            proc = subprocess.run(
                [resolved, filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            # verible-verilog-lint 把违规信息写到 stderr（而非 stdout），
            # 因此必须合并两个流，否则违规数恒为 0（误报 passed）。
            raw = (proc.stdout or b"") + (proc.stderr or b"")
            output = raw.decode("utf-8", errors="replace")
            violations = []
            by_rule = {}
            for line in output.strip().split("\n"):
                if line.strip():
                    violations.append({"message": line.strip()})
                    rule = _extract_lint_rule(line)
                    if rule:
                        by_rule[rule] = by_rule.get(rule, 0) + 1
            total = len(violations)
            capped = violations if max_results == 0 else violations[:max_results]
            return {
                "file": filepath,
                "violation_count": total,
                "violations": capped,
                "violations_truncated": total > len(capped),
                "by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])[:20]),
                "passed": total == 0,
                "note": f"{total} violations, showing {len(capped)}; "
                        f"pass max_results=0 to see all",
            }
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"file": filepath, "error": str(e)}

    def format_code(self, filepath: str, format_executable: str = "verible-verilog-format") -> dict:
        """运行 verible formatter（预览模式，不修改原文件）。"""
        # 优先用 find_verible_binary 解析完整路径，避免依赖 PATH
        resolved = find_verible_binary(format_executable) or format_executable
        try:
            proc = subprocess.run(
                [resolved, filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            formatted = proc.stdout.decode("utf-8", errors="replace")
            return {
                "file": filepath,
                "formatted": formatted,
                "changed": True,  # 简化判断
            }
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"file": filepath, "error": str(e)}

    def syntax_check(self, filepath: str, max_errors: int = 100) -> dict:
        """运行 verible 语法检查。

        注意：语法错误文件可能没有 tree 键（只有 errors），
        因此不能依赖 parse_file（其无 tree 时返回 None）。
        这里直接解析 verible 的 JSON 输出取 errors。

        性能（10MB 级文件实测）：不要加 -printtree 参数——它会把整棵 CST
        以人类可读文本转储到 stdout（12MB 文件 ≈ 538MB），subprocess.run
        全量缓冲进内存导致 RSS 飙到 1.18GB。-export_json 本身在无错误时
        只输出几十字节，有错误时输出结构化 errors 数组，足够。
        """
        try:
            proc = subprocess.run(
                [self.executable, "-export_json", filepath],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"file": filepath, "error": str(e)}

        errors = []
        file_json = {}
        try:
            json_data = json.loads(proc.stdout.decode("utf-8"))
            file_json = json_data.get(filepath, {})
            if not file_json and len(json_data) == 1:
                file_json = list(json_data.values())[0]
            if file_json is None:
                file_json = {}   # 干净文件 verible 输出 {"path": null}
            errors = file_json.get("errors", [])
        except (json.JSONDecodeError, IndexError, AttributeError):
            pass

        # 兜底：-export_json 在部分错误场景下可能不出 errors，改用 stderr 文本
        if not errors and proc.returncode != 0:
            err_text = proc.stderr.decode("utf-8", errors="replace")
            import re as _re
            pat = _re.compile(r":(\d+):(\d+)(?:-(\d+))?:\s*(.*)")
            for line in err_text.splitlines():
                m = pat.search(line)
                if m:
                    errors.append({"line": int(m.group(1)), "column": int(m.group(2)),
                                   "text": m.group(4).strip()})

        total = len(errors)
        capped = errors[:max_errors]
        return {
            "file": filepath,
            "error_count": total,
            "errors": [{"line": e.get("line", 0), "column": e.get("column", 0),
                        "message": e.get("text", "")} for e in capped],
            "errors_truncated": total > len(capped),
            "passed": total == 0,
            "modules_found": 1 if file_json.get("tree") else 0,
        }


def find_verible_binary(name: str = "verible-verilog-syntax") -> Optional[str]:
    """在常见位置查找 verible 二进制文件。

    搜索顺序：
    1. PATH 中的 verible-verilog-syntax / .exe
    2. rtlens 同目录下的 verible/ 子目录
    3. rtlens 同目录下的 verible-v*/bin/
    4. 用户指定的 VERIBLE_PATH 环境变量
    """
    # 1. PATH
    import shutil
    exe_name = name + (".exe" if sys.platform == "win32" else "")
    path_found = shutil.which(exe_name)
    if path_found:
        return path_found

    # 2. 同目录下的 verible/
    this_dir = os.path.dirname(os.path.abspath(__file__))
    verible_dir = os.path.join(this_dir, "verible")
    if os.path.isdir(verible_dir):
        candidate = os.path.join(verible_dir, exe_name)
        if os.path.isfile(candidate):
            return candidate

    # 3. 同目录下的 verible-v*/  (解压后的文件夹)
    if os.path.isdir(this_dir):
        for entry in os.listdir(this_dir):
            if entry.startswith("verible-v") and os.path.isdir(os.path.join(this_dir, entry)):
                candidate = os.path.join(this_dir, entry, exe_name)
                if os.path.isfile(candidate):
                    return candidate

    # 4. 环境变量
    env_path = os.environ.get("VERIBLE_PATH", "")
    if env_path:
        candidate = os.path.join(env_path, exe_name)
        if os.path.isfile(candidate):
            return candidate

    return None
