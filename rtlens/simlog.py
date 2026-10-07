# -*- coding: utf-8 -*-
"""v6.0.4: 仿真日志解析（simlog）。

验证占 FPGA 开发 60-70% 的时间，而回归失败时工程师要人肉翻几千行
仿真日志，把报错/警告逐条对应到源码模块。本模块把这一步自动化：

- parse_sim_log(): 解析 iverilog / verilator / vcs 风格日志，抽取结构化条目
  （工具/严重级/文件/行/列/规则/消息）
- annotate(): 把日志条目归属到索引中的模块（利用 WorkspaceIndex），
  输出「按模块聚合」的错误视图 + Top-N 模块排行

支持格式（实测样本驱动）：
- iverilog:    foo.v:123: message            （可带列 foo.v:123:4: msg）
- verilator:   %Error: foo.v:123:12: message
               %Warning-WIDTH: foo.v:123:12: message
               %Error-...: ... （规则名任意大写/数字/下划线）
- vcs:         Error-[IND] foo.v, 123 / Warning-[...] ...
- 通用兜底:    任意行内出现 <file>.v:<line>: 的也尝试抽取（宽松模式）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict

# --- 正则 -----------------------------------------------------------------

_FILE_EXT = r'[^:\s]+?\.(?:v|sv|vh|svh)'

# iverilog: file.v:123: message / file.v:123:4: message
IVERILOG_RE = re.compile(
    r'^(?P<file>' + _FILE_EXT + r'):'
    r'(?P<line>\d+)'
    r'(?::(?P<col>\d+))?'
    r'\s*:\s*(?P<msg>.*)$'
)

# verilator: %Error: file.v:123:12: msg / %Warning-WIDTH: file.v:123:12: msg
VERILATOR_RE = re.compile(
    r'^%(?P<sev>Error|Warning)'
    r'(?:-(?P<rule>[A-Z0-9_]+))?'
    r':\s*(?P<file>' + _FILE_EXT + r'):'
    r'(?P<line>\d+)'
    r'(?::(?P<col>\d+))?'
    r':\s*(?P<msg>.*)$'
)

# vcs: Error-[ID] message / file.v, 123 —— vcs 的文件/行常与消息分行，
# 只抽主行，行内若含 file.v:<line> 也由宽松模式兜底
VCS_RE = re.compile(
    r'^(?P<sev>Error|Warning)-\[(?P<rule>[A-Z0-9]+)\]\s*(?P<msg>.*)$'
)

# 宽松兜底：任意行内出现 file.v:123: （前面不是 %Error 等已处理形态）
LOOSE_RE = re.compile(
    r'(?P<file>' + _FILE_EXT + r'):'
    r'(?P<line>\d+)'
    r'(?::(?P<col>\d+))?'
    r':\s*(?P<msg>\S.*)$'
)

_SEV_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(slots=True)
class SimLogEntry:
    """一条结构化仿真日志。"""
    tool: str            # iverilog / verilator / vcs / unknown
    severity: str        # error / warning / info
    file: str = ""
    line: int = 0
    col: Optional[int] = None
    rule: str = ""       # verilator lint 规则（WIDTH/UNOPTFLAT…）或 vcs 错误号
    message: str = ""
    raw: str = ""
    module: str = ""     # annotate() 填充：归属的 Verilog 模块名

    def to_dict(self) -> dict:
        return asdict(self)


def _mk(tool: str, severity: str, msg: str, raw: str,
        file: str = "", line: int = 0, col: Optional[int] = None,
        rule: str = "") -> SimLogEntry:
    return SimLogEntry(tool=tool, severity=severity.lower(), file=file,
                       line=int(line), col=(int(col) if col is not None else None),
                       rule=rule or "", message=msg.strip(), raw=raw.rstrip("\n"))


def parse_sim_log(text: str) -> List[SimLogEntry]:
    """解析仿真日志文本，返回结构化条目（按出现顺序）。

    自动逐行识别 iverilog / verilator / vcs 格式；无法归类但内嵌
    file.v:line: 模式的行用宽松模式兜底。
    """
    entries: List[SimLogEntry] = []
    if not text:
        return entries
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = VERILATOR_RE.match(line)
        if m:
            entries.append(_mk("verilator", m.group("sev"), m.group("msg"), raw,
                               file=m.group("file"), line=m.group("line"),
                               col=m.group("col"), rule=m.group("rule") or ""))
            continue
        m = IVERILOG_RE.match(line)
        if m:
            # iverilog 编译错误无独立严重级；消息含 "error" 视为 error，否则 warning
            msg = m.group("msg")
            sev = "error" if re.search(r'\berror\b', msg, re.I) else "warning"
            entries.append(_mk("iverilog", sev, msg, raw,
                               file=m.group("file"), line=m.group("line"),
                               col=m.group("col")))
            continue
        m = VCS_RE.match(line)
        if m:
            # vcs 主行常不带位置；同一行里若有 file.v:line: 也一并提取
            sev = m.group("sev").lower()
            rule = m.group("rule")
            rest = m.group("msg")
            lm = LOOSE_RE.search(rest)
            if lm:
                entries.append(_mk("vcs", sev, lm.group("msg"), raw,
                                   file=lm.group("file"), line=lm.group("line"),
                                   col=lm.group("col"), rule=rule))
            else:
                entries.append(_mk("vcs", sev, rest, raw, rule=rule))
            continue
        # 宽松兜底：行内任意位置出现 file.v:123: msg
        m = LOOSE_RE.search(line)
        if m:
            sev = "error" if re.search(r'\berror\b', line, re.I) else "warning"
            entries.append(_mk("unknown", sev, m.group("msg"), raw,
                               file=m.group("file"), line=m.group("line"),
                               col=m.group("col")))
    return entries


def _resolve_file(path: str, index) -> Optional[str]:
    """把日志里的文件路径解析到索引中已知的路径（双向后缀/文件名匹配）。"""
    if index is None:
        return None
    files = getattr(index, "_files", {}) or {}
    if not files:
        return None
    p = path.replace("\\", "/")
    if p in files:
        return p
    # 统一转成 / 分隔再比较（Windows 索引键是 \ 分隔，历史版本混用导致匹配落空）
    norm_files = {f.replace("\\", "/"): f for f in files}
    # 后缀匹配（索引绝对路径 + 日志相对路径，或反之）
    suf = [f for fn, f in norm_files.items() if fn.endswith(p) or p.endswith(fn)]
    if len(suf) >= 1:
        return suf[0]
    # 文件名匹配
    base = p.rsplit("/", 1)[-1]
    same = [f for fn, f in norm_files.items() if fn.rsplit("/", 1)[-1] == base]
    if len(same) == 1:
        return same[0]
    return None


def annotate(entries: List[SimLogEntry], index) -> List[SimLogEntry]:
    """为每条带位置的条目归属模块（就地填充 entry.module，并返回同一列表）。

    依赖 WorkspaceIndex._module_at(file, line)；日志路径与索引路径
    不一致时先做后缀/文件名解析。
    """
    if index is None:
        return entries
    cache: Dict[str, str] = {}
    for e in entries:
        if not e.file or e.line <= 0:
            continue
        key = f"{e.file}:{e.line}"
        if key in cache:
            e.module = cache[key]
            continue
        resolved = _resolve_file(e.file, index)
        mod = ""
        if resolved:
            try:
                mod = index._module_at(resolved, e.line) or ""
            except Exception:
                mod = ""
        cache[key] = mod
        e.module = mod
    return entries


def summarize(entries: List[SimLogEntry], top: int = 10) -> dict:
    """按模块/严重级/规则聚合，产出回归 triage 视图。"""
    by_module: Dict[str, Dict[str, int]] = {}
    by_rule: Dict[str, int] = {}
    sev_count = {"error": 0, "warning": 0, "info": 0}
    located = 0
    for e in entries:
        sev_count[e.severity] = sev_count.get(e.severity, 0) + 1
        if e.file:
            located += 1
        if e.rule:
            by_rule[e.rule] = by_rule.get(e.rule, 0) + 1
        key = e.module or (e.file or "(no location)")
        slot = by_module.setdefault(key, {"errors": 0, "warnings": 0, "files": set()})
        if e.severity == "error":
            slot["errors"] += 1
        else:
            slot["warnings"] += 1
        if e.file:
            slot["files"].add(e.file)
    top_modules = [
        {"module": k, "errors": v["errors"], "warnings": v["warnings"],
         "files": sorted(v["files"])[:5]}
        for k, v in sorted(by_module.items(),
                           key=lambda kv: (-kv[1]["errors"], -kv[1]["warnings"]))[:top]
    ]
    return {
        "total": len(entries),
        "errors": sev_count["error"],
        "warnings": sev_count["warning"],
        "info": sev_count["info"],
        "located": located,          # 有文件位置可跳转的条目数
        "modules_with_issues": len(by_module),
        "top_modules": top_modules,
        "top_rules": sorted(by_rule.items(), key=lambda kv: -kv[1])[:top],
    }
