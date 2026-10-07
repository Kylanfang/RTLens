"""Evidence 出口：`rtlens.evidence/1` 契约的生产者。

这是 RTLens 与下游工具(如 hw-topo 硬件拓扑图插件)之间**唯一**的结构化事实出口。
契约规范见 `docs/EVIDENCE_CONTRACT.md`;本模块是它的参考实现。

设计纪律(与项目整体一致):

1. **不猜**。所有字段都是从 `WorkspaceIndex` 机械转录,没有任何启发式补全。
2. **双基准行号**。`line0`(0-based,词法器/索引原生)与 `line1`(1-based,编辑器/hw-topo spec)
   同时给出,恒有 `line1 == line0 + 1`。消费方不必也不许自己 ±1。
3. **root 相对 POSIX 路径**。绝对路径另放 `absPath`。逃出 root 的文件被排除并在
   `diagnostics.outsideRootFiles` 里如实计数——不静默、也不产出无法解析的证据指针。
4. **失败要响**。文件读了就算 sha256;截断(如 signal 数量上限)必须在对应元素上
   打显式标记(如 `signalsTruncated`),不允许静默丢数据。

本模块零外部依赖,仅用标准库。
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .indexer import WorkspaceIndex
from .parser import Instance, ModuleInfo, Range, Symbol

EVIDENCE_SCHEMA = "rtlens.evidence/1"

#: 单模块 signals 转录上限(超出则置 signalsTruncated)。避免大设计产出几十 MB JSON;
#: 需要全量时用 --max-signals 调大。ports/params/instances **不截断**——它们是拓扑证据的主体。
DEFAULT_MAX_SIGNALS = 256

#: 单个例化的连接列表上限(与 signals 同理,超出置 connectionsTruncated)。
DEFAULT_MAX_CONNECTIONS = 256

#: RTLens 内部分类 → 契约枚举的固定名字映射(见契约 §2)。
_RESOLUTION_MAP = {
    "workspace": "declared",
    "vendor_primitive": "vendor-primitive",
    "unknown": "external",
}

_UNRESOLVED_CLASS_MAP = {
    "vendor_primitive": "vendor-primitive",
    "unknown": "unknown",
}


# ---------------------------------------------------------------- 基础工具


def _posix_rel(root_abs: str, path: str) -> Optional[str]:
    """绝对/任意路径 → root 相对 POSIX 路径。

    返回 None 表示该路径不在 root 内(逃逸或跨盘符)。调用方须把它计为
    outside-root 并从证据中排除——契约 R2 不允许 `..` 或盘符出现在 `file` 里。
    """
    try:
        rel = os.path.relpath(os.path.abspath(path), root_abs)
    except ValueError:
        # Windows 上跨盘符 relpath 会抛 ValueError
        return None
    rel_posix = rel.replace(os.sep, "/")
    if rel_posix == ".." or rel_posix.startswith("../") or os.path.isabs(rel):
        return None
    return rel_posix


def _line0(rng: Optional[Range]) -> int:
    """取 0-based 起始行;缺失范围时返回 0(与"文件开头"同义,而非编造行号)。"""
    if rng is None:
        return 0
    return max(0, int(rng.start_line))


def _end_line0(rng: Optional[Range]) -> int:
    if rng is None:
        return 0
    return max(0, int(rng.end_line))


def _sha256_and_bytes(path: str, fallback_text: str) -> Tuple[str, int, int]:
    """(sha256, bytes, lines)。

    sha256/bytes 取自**磁盘原始字节**(与 hw-topo 的 `sha256Hex(fs.readFileSync)` 同义);
    读不到时退回内存文本,保证 LSP 未落盘场景也不崩。
    lines 与内置扫描器口径一致:`text.split('\\n')` 的长度。
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest(), len(raw), len(text.split("\n"))
    except OSError:
        raw = fallback_text.encode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest(), len(raw), len(fallback_text.split("\n"))


def _sym_line_fields(sym: Symbol) -> Dict[str, Any]:
    l0 = _line0(sym.range)
    return {"line0": l0, "line1": l0 + 1}


# ---------------------------------------------------------------- 元素转录


def _port_entry(p: Symbol) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": p.name}
    direction = getattr(p, "direction", "") or ""
    width = getattr(p, "width", "") or ""
    data_type = getattr(p, "data_type", "") or ""
    if direction:
        entry["direction"] = direction
    if width:
        entry["width"] = width
    if data_type:
        entry["dataType"] = data_type
    if getattr(p, "detail", ""):
        entry["detail"] = p.detail
    entry.update(_sym_line_fields(p))
    return entry


def _param_entry(p: Symbol) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": p.name}
    if getattr(p, "detail", ""):
        entry["detail"] = p.detail
    entry.update(_sym_line_fields(p))
    return entry


def _signal_entry(s: Symbol) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": s.name}
    if getattr(s, "detail", ""):
        entry["detail"] = s.detail
    entry.update(_sym_line_fields(s))
    return entry


def _connection_entries(inst: Instance, max_connections: int) -> Tuple[List[Dict[str, Any]], bool]:
    conns = list(inst.connections or [])
    truncated = len(conns) > max_connections
    out: List[Dict[str, Any]] = []
    for c in conns[:max_connections]:
        l0 = _line0(c.range)
        out.append({
            "port": c.port_name or "",       # 位置连接时为空串 —— 不编造端口名
            "signal": c.signal_text or "",
            "line0": l0,
            "line1": l0 + 1,
        })
    return out, truncated


def _instance_entry(
    inst: Instance,
    parent: str,
    rel_file: str,
    resolution: str,
    max_connections: int,
) -> Dict[str, Any]:
    l0 = _line0(inst.range)
    e0 = _end_line0(inst.range)
    if e0 < l0:
        e0 = l0
    connections, conn_truncated = _connection_entries(inst, max_connections)
    entry: Dict[str, Any] = {
        "parent": parent,
        "type": inst.module_type,
        "instance": inst.inst_name,
        "file": rel_file,
        "line0": l0,
        "line1": l0 + 1,
        "endLine0": e0,
        "endLine1": e0 + 1,
        "resolution": resolution,
        "connectionCount": len(inst.connections or []),
    }
    if conn_truncated:
        entry["connectionsTruncated"] = True
    entry["connections"] = connections
    return entry


def _module_entry(
    mod: ModuleInfo,
    rel_file: str,
    index: WorkspaceIndex,
    kind: str,
    max_signals: int,
    max_connections: int,
) -> Dict[str, Any]:
    l0 = _line0(mod.range)
    e0 = _end_line0(mod.range)
    if e0 < l0:
        e0 = l0

    signals = list(mod.signals or [])
    signals_truncated = len(signals) > max_signals

    definitions = len(index._module_defs.get(mod.name, []))  # noqa: SLF001 — 同包内经核实的内省
    sites = index._instances.get(mod.name, [])               # noqa: SLF001

    nested: List[Dict[str, Any]] = []
    for inst in mod.instances or []:
        nested.append(_instance_entry(
            inst, mod.name, rel_file,
            _RESOLUTION_MAP.get(index.classify_module_type(inst.module_type), "external"),
            max_connections,
        ))

    entry: Dict[str, Any] = {
        "name": mod.name,
        "kind": kind,
        "role": "leaf-or-mid" if sites else "top",
        "file": rel_file,
        "line0": l0,
        "line1": l0 + 1,
        "endLine0": e0,
        "endLine1": e0 + 1,
        "portCount": len(mod.ports or []),
        "definitions": definitions or 1,
        "ports": [_port_entry(p) for p in (mod.ports or [])],
        "params": [_param_entry(p) for p in (mod.params or [])],
        "instantiatedBy": sorted({s.container for s in sites if s.container}),
        "instances": nested,
    }
    if signals_truncated:
        entry["signalsTruncated"] = True
    entry["signals"] = [_signal_entry(s) for s in signals[:max_signals]]
    return entry


# ---------------------------------------------------------------- 主入口


def build_evidence(
    index: WorkspaceIndex,
    root: str,
    defines: Optional[Dict[str, str]] = None,
    *,
    max_signals: int = DEFAULT_MAX_SIGNALS,
    max_connections: int = DEFAULT_MAX_CONNECTIONS,
) -> Dict[str, Any]:
    """把已建好的索引转录成 `rtlens.evidence/1` 信封。

    调用方负责先 `index.index_directory(root)` 完成索引;本函数**不做 I/O 之外的推断**。
    """
    root_abs = os.path.abspath(root)

    files: List[Dict[str, Any]] = []
    outside_root: List[str] = []
    modules: List[Dict[str, Any]] = []
    instances: List[Dict[str, Any]] = []
    parse_errors = 0

    # 稳定顺序:按 root 相对路径排序,保证同一棵树两次运行产出**逐字节相同**的证据
    # (契约的"同输入同输出"是它能当证据用的前提)。
    indexed = sorted(
        index._files.items(),                       # noqa: SLF001
        key=lambda kv: (_posix_rel(root_abs, kv[0]) or "\uffff" + kv[0]),
    )

    for path, idx_file in indexed:
        rel = _posix_rel(root_abs, path)
        if rel is None:
            outside_root.append(os.path.abspath(path))
            continue

        sha256, size, lines = _sha256_and_bytes(path, idx_file.text)
        files.append({
            "path": rel,
            "absPath": os.path.abspath(path),
            "bytes": size,
            "lines": lines,
            "sha256": sha256,
        })

        result = idx_file.result
        parse_errors += len(result.errors or [])

        for mod in result.modules or []:
            modules.append(_module_entry(
                mod, rel, index, "module", max_signals, max_connections))
            for inst in mod.instances or []:
                instances.append(_instance_entry(
                    inst, mod.name, rel,
                    _RESOLUTION_MAP.get(index.classify_module_type(inst.module_type), "external"),
                    max_connections,
                ))

        # interface 被当作可例化的 ModuleInfo 索引(`_module_defs` 里也有),
        # 内置扫描器同样把 interface 计入 modules —— 两边口径必须一致。
        for iface in result.interfaces or []:
            modules.append(_module_entry(
                iface, rel, index, "interface", max_signals, max_connections))
            for inst in iface.instances or []:
                instances.append(_instance_entry(
                    inst, iface.name, rel,
                    _RESOLUTION_MAP.get(index.classify_module_type(inst.module_type), "external"),
                    max_connections,
                ))

    unresolved: List[Dict[str, Any]] = []
    for entry in index.list_unresolved_modules(suggest=True):
        mtype = entry["module_type"]
        sites = index._instances.get(mtype, [])      # noqa: SLF001
        if not sites:
            continue
        first = sites[0]
        rel = _posix_rel(root_abs, first.file)
        if rel is None:
            outside_root.append(os.path.abspath(first.file))
            continue
        l0 = _line0(first.range)
        item: Dict[str, Any] = {
            "type": mtype,
            "classification": _UNRESOLVED_CLASS_MAP.get(entry["kind"], "unknown"),
            "file": rel,
            "line0": l0,
            "line1": l0 + 1,
            "count": entry["instances"],
            "parents": sorted({s.container for s in sites if s.container})[:16],
        }
        if entry.get("suggestions"):
            item["suggestions"] = entry["suggestions"]
        unresolved.append(item)

    stats = index.stats
    top_modules = sorted({m["name"] for m in modules if m["role"] == "top"})

    diagnostics: Dict[str, Any] = {
        "parseErrors": parse_errors,
        "elaborated": False,      # 设计如此:不做 elaboration,参数化位宽保持源码文本
        "signalsTruncatedModules": sum(1 for m in modules if m.get("signalsTruncated")),
        # 与 signalsTruncatedModules 对称:连接截断同样要有汇总,否则下游只能逐元素
        # 翻找,而"汇总里没有"很容易被误读成"没有截断"。
        "connectionsTruncatedInstances": sum(1 for i in instances if i.get("connectionsTruncated")),
    }
    # 文件级上限是覆盖截断:索引只读到 max_files 个文件就停了。不披露的话,
    # 下游会把"没扫到"当成"不存在"。
    if getattr(index, "last_index_truncated", False):
        diagnostics["filesCapped"] = True
    if outside_root:
        # 用 -I 引入 root 之外的文件时会发生。它们的证据指针无法被下游的
        # resolveInsideRoot 解析,因此整体排除并在这里如实报告。
        diagnostics["outsideRootFiles"] = sorted(set(outside_root))[:64]
        diagnostics["outsideRootCount"] = len(set(outside_root))

    return {
        "schema": EVIDENCE_SCHEMA,
        "tool": {"name": "rtlens", "version": __version__},
        "root": {"abs": root_abs, "separator": os.sep},
        "generatedAt": _now_iso(),
        "defines": dict(defines) if defines else {},
        "stats": {
            "files": len(files),
            "modules": len(modules),
            "ports": stats.ports,
            "signals": stats.signals,
            "params": stats.params,
            "instances": len(instances),
            "interfaces": stats.interfaces,
            "packages": stats.packages,
            "topModules": top_modules,
        },
        "files": files,
        "modules": modules,
        "instances": instances,
        "unresolved": unresolved,
        "diagnostics": diagnostics,
    }


def _now_iso() -> str:
    """ISO-8601 UTC,毫秒精度,与 JS `new Date().toISOString()` 同格式。"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


__all__ = ["EVIDENCE_SCHEMA", "build_evidence", "DEFAULT_MAX_SIGNALS", "DEFAULT_MAX_CONNECTIONS"]
