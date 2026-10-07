"""预处理器：宏展开 + 条件编译 + include 宏预加载（Verible 不做的部分）。

v6.1.0 行数保持重构（位置正确性修复）：

历史版本把 `` `include `` 内联展开成 N 行、把不活跃的 `` `ifdef `` 分支整段删除，
导致输出文本的行号相对原文件平移——所有下游符号/引用/诊断/rename 的位置
全部指向错误的行。v6.1.0 起本模块保证：

    **输出文本与输入文本行数严格一致（逐行对应）**

- `` `define``          → 同一行的注释占位
- `` `undef``           → 空行
- `` `ifdef`` 等条件指令 → 空行（条件栈照常求值）
- 不活跃分支内的行      → 逐行置空（内容不可见，行位保留）
- `` `include``         → 同一行的注释占位；include 文件**不再内联**，
                          而是递归预加载其中的宏定义（宏的 Range 归位到
                          本文件的 include 行，保证跳转/引用行号正确）
- 普通行                → 行内宏展开（`` `NAME`` 替换为值）

已知取舍：行内宏展开若改变该行长度，其后的同行列号会有偏移（历史行为一致）；
行号（对 LSP/AI 最关键）始终精确。
"""

from __future__ import annotations

import os
import sys
import re
from typing import Dict, List, Optional

from .parser import ParseResult, MacroDef, IncludeRef, parse, Range


class Preprocessor:
    """对单文件做条件编译 + 宏处理，输出与输入**行数一致**的源码字符串 + 宏表。"""

    def __init__(self, include_paths: Optional[List[str]] = None, builtin_macros: Optional[Dict[str, str]] = None):
        self.include_paths = include_paths or []
        self.macros: Dict[str, MacroDef] = {}
        if builtin_macros:
            for name, val in builtin_macros.items():
                # 内置宏用 -1 行号作为哨兵，与真实文件第 0 行的宏区分开
                self.macros[name] = MacroDef(name=name, value=val,
                                             range=Range(-1,0,-1,0),
                                             name_range=Range(-1,0,-1,0))
        self._included: set = set()
        # v5.3.0: 虚拟文件池 — index_code 传入的文件内容，用于解析 `include
        # key = 虚拟路径（如 "defines.vh"），value = 文件全文
        self._virtual_files: Dict[str, str] = {}

    def set_virtual_files(self, files: Dict[str, str]):
        """设置虚拟文件池，使 `include 指令能从聊天窗口传入的代码中解析。"""
        self._virtual_files = files or {}

    def process_file(self, path: str) -> str:
        path = os.path.abspath(path)
        if path in self._included:
            return ""
        self._included.add(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"rtlens: cannot read {path}: {e}", file=sys.stderr)
            return ""
        return self.process_text(text, base_dir=os.path.dirname(path))

    def process_text(self, text: str, base_dir: str = ".") -> str:
        """条件编译 + 行内宏展开。输出与输入行数严格一致（逐行对应）。"""
        lines = text.split("\n")
        out: List[str] = []
        cond_stack: List[bool] = []  # True=当前分支有效

        def active() -> bool:
            return all(cond_stack) if cond_stack else True

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()

            # 宏定义（占位注释，行数不变）
            m = re.match(r"`\s*define\s+(\w+)", stripped)
            if m and active():
                name = m.group(1)
                rest = stripped[m.end():].strip()
                args: List[str] = []
                am = re.match(r"\(([^)]*)\)", rest)
                if am:
                    args = [a.strip() for a in am.group(1).split(",") if a.strip()]
                    rest = rest[am.end():].strip()
                self.macros[name] = MacroDef(name=name, value=rest, args=args,
                                             range=Range(i,0,i,0),
                                             name_range=Range(i,8,i,8+len(name)))
                out.append(f"// rtlens: macro {name} defined")
                i += 1
                continue

            # undef（空行占位）
            um = re.match(r"`\s*undef\s+(\w+)", stripped)
            if um and active():
                self.macros.pop(um.group(1), None)
                out.append("")
                i += 1
                continue

            # ifdef / ifndef（空行占位，条件栈照常求值）
            cm = re.match(r"`\s*(ifdef|ifndef)\s+(\w+)", stripped)
            if cm:
                name = cm.group(2)
                defined = name in self.macros
                cond = defined if cm.group(1) == "ifdef" else not defined
                if active():
                    cond_stack.append(cond)
                else:
                    cond_stack.append(False)  # 父级 inactive 时永远 false
                out.append("")
                i += 1
                continue

            em = re.match(r"`\s*(elsif)\s+(\w+)", stripped)
            if em and cond_stack:
                name = em.group(2)
                prev = cond_stack.pop()
                parent_ok = all(cond_stack) if cond_stack else True
                cond = parent_ok and (not prev) and (name in self.macros)
                cond_stack.append(cond)
                out.append("")
                i += 1
                continue

            if re.match(r"`\s*else\b", stripped) and cond_stack:
                prev = cond_stack.pop()
                parent_ok = all(cond_stack) if cond_stack else True
                cond_stack.append(parent_ok and not prev)
                out.append("")
                i += 1
                continue

            if re.match(r"`\s*endif\b", stripped) and cond_stack:
                cond_stack.pop()
                out.append("")
                i += 1
                continue

            # 不活跃分支：逐行置空（内容不可见，行位保留）
            if not active():
                out.append("")
                i += 1
                continue

            # include（占位注释 + 递归预加载宏；不内联文本）
            im = re.match(r'`\s*include\s+"([^"]+)"', stripped) or re.match(r"`\s*include\s+<([^>]+)>", stripped)
            if im:
                inc_name = im.group(1)
                inc_path = self._find_include(inc_name, base_dir)
                if inc_path is not None:
                    self._preload_include_macros(inc_path, inc_name, line_idx=i)
                    out.append(f"// rtlens: include {inc_name} (macros pre-loaded)")
                else:
                    out.append(f"// rtlens: include not found: {inc_name}")
                i += 1
                continue

            # 普通行：行内宏展开
            out.append(self._expand_line(line))
            i += 1

        # 防御：任何未预见路径导致的行数不一致，都恢复为逐行对齐（宁可少展开，不可错位）
        if len(out) != n:
            print(f"rtlens: preprocessor line-count invariant violated "
                  f"({len(out)} vs {n}); falling back to raw text", file=sys.stderr)
            return text
        return "\n".join(out)

    def _preload_include_macros(self, inc_path: str, inc_name: str, line_idx: int):
        """递归处理 include 文件，仅收集宏定义副作用；文本不进入输出。

        include 引入的宏 Range 归位到本文件的 include 行——
        跳转/引用的行号落在真实存在的行上，而不是别的文件的行号。
        """
        if inc_path in self._included:
            return
        self._included.add(inc_path)
        before = set(self.macros.keys())
        try:
            if inc_path in self._virtual_files:
                content = self._virtual_files[inc_path]
                base = os.path.dirname(inc_path) if os.path.isabs(inc_path) else "."
                self.process_text(content, base_dir=base)
            elif os.path.isfile(inc_path):
                with open(inc_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self.process_text(content, base_dir=os.path.dirname(inc_path))
            else:
                return
        except OSError as e:
            print(f"rtlens: cannot read include {inc_path}: {e}", file=sys.stderr)
            return
        for name in set(self.macros.keys()) - before:
            md = self.macros[name]
            md.range = Range(line_idx, 0, line_idx, 0)
            md.name_range = Range(line_idx, 0, line_idx, len(name))

    def _expand_line(self, line: str) -> str:
        def repl(m: re.Match) -> str:
            name = m.group(0)[1:]  # 去掉 `
            if name in self.macros:
                md = self.macros[name]
                if md.args:
                    # 带参宏：尝试匹配 `MACRO(arg1,arg2)`
                    return m.group(0)  # 简化：保留原样（带参宏展开易出错，不做深度展开）
                return md.value
            return m.group(0)

        return re.sub(r"`\w+", repl, line)

    def _find_include(self, name: str, base_dir: str) -> Optional[str]:
        # v5.3.0: 优先检查虚拟文件池（index_code 场景）
        if self._virtual_files:
            # 1a. 精确路径匹配
            if name in self._virtual_files:
                return name
            # 1b. 相对于 base_dir 的路径匹配
            joined = os.path.join(base_dir, name) if base_dir else name
            if joined in self._virtual_files:
                return joined
            # 1c. basename 匹配（最后手段：路径不同但文件名相同）
            basename = os.path.basename(name)
            for vpath in self._virtual_files:
                if os.path.basename(vpath) == basename:
                    return vpath
        # 2. 磁盘查找
        cands = [os.path.join(base_dir, name)] + [os.path.join(p, name) for p in self.include_paths]
        for c in cands:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return None


def preprocess_and_parse(path: str, include_paths: Optional[List[str]] = None) -> tuple:
    """预处理文件并返回 (展开后文本, ParseResult)。

    展开后文本与原文件行数一致——ParseResult 中的全部位置
    可直接用于原文件（LSP 行号正确性由该不变式保证）。
    """
    pp = Preprocessor(include_paths=include_paths)
    text = pp.process_file(path)
    result = parse(text)
    return text, result
