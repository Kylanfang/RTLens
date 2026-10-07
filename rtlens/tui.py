"""交互式终端 (TUI) — 纯 stdlib cmd 模块，Windows/Mac/Linux 通用。

启动：python -m rtlens tui --root ./examples/hierarchy

命令：
  stats                 索引统计
  find <关键词>          搜索符号（模糊）
  module <名字>          模块详情（端口/参数/信号/实例）
  ports <模块>           列出端口
  signals <模块>         列出内部信号
  instances <模块>       列出模块内部实例化
  whoinst <模块>         谁实例化了此模块
  refs <名字>            查找引用
  tree <顶层模块>        ASCII 层级树
  drivers <文件> <信号>   信号驱动源
  macros                宏定义列表
  primitives            eLinx GTP 原语列表
  constraints [信号]    引脚约束
  load <目录>            索引新目录
  help                  帮助
  quit / exit           退出
"""

from __future__ import annotations

import cmd
import os
import sys
from typing import Optional

from .indexer import WorkspaceIndex
from .elinx import ELinxSupport


# ANSI 颜色（Windows 10+ 支持 VT；老系统会显示原始码但不影响功能）
_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "blue": "\033[34m",
}


def _c(color: str, text: str) -> str:
    return f"{_C.get(color, '')}{text}{_C['reset']}"


def _enable_vt():
    """Windows 下启用 VT100 转义码支持。"""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


class RTLensShell(cmd.Cmd):
    intro = _c("bold", "RTLens 交互终端") + " — 输入 " + _c("cyan", "help") + " 查看命令，" + _c("cyan", "quit") + " 退出\n"
    prompt = _c("green", "rtlens> ") + _C["reset"]

    def __init__(self, index: WorkspaceIndex, elinx: ELinxSupport):
        super().__init__()
        self.idx = index
        self.elx = elinx

    # ---- 基础命令 ----

    def do_help(self, arg):
        print()
        print(_c("bold", "命令列表："))
        print(f"  {_c('cyan', 'stats')}                  索引统计")
        print(f"  {_c('cyan', 'find')} <关键词>           搜索符号（模糊匹配）")
        print(f"  {_c('cyan', 'module')} <名字>            模块详情（端口/参数/信号/实例）")
        print(f"  {_c('cyan', 'ports')} <模块>             列出端口")
        print(f"  {_c('cyan', 'signals')} <模块>           列出内部信号")
        print(f"  {_c('cyan', 'instances')} <模块>         列出模块内部实例化")
        print(f"  {_c('cyan', 'whoinst')} <模块>           谁实例化了此模块")
        print(f"  {_c('cyan', 'refs')} <名字>              查找引用")
        print(f"  {_c('cyan', 'tree')} <顶层模块>          ASCII 层级树")
        print(f"  {_c('cyan', 'drivers')} <文件> <信号>     信号驱动源")
        print(f"  {_c('cyan', 'macros')}                  宏定义列表")
        print(f"  {_c('cyan', 'primitives')}              eLinx GTP 原语列表")
        print(f"  {_c('cyan', 'constraints')} [信号]       引脚约束")
        print(f"  {_c('cyan', 'load')} <目录>              索引新目录")
        print(f"  {_c('cyan', 'rename')} <文件> <行> <列> <新名>  跨文件重命名")
        print(f"  {_c('cyan', 'codelens')} <文件>          代码透镜（引用计数）")
        print(f"  {_c('cyan', 'dectree')} <文件>           层级符号树")
        print(f"  {_c('cyan', 'quit')}                    退出")
        print()

    def do_quit(self, arg):
        print(_c("dim", "再见"))
        return True

    do_exit = do_quit
    do_EOF = do_quit

    def emptyline(self):
        pass

    # ---- 查询命令 ----

    def do_stats(self, arg):
        s = self.idx.stats
        print()
        print(_c("bold", "索引统计"))
        print(f"  文件数:     {_c('yellow', str(s.files))}")
        print(f"  模块数:     {_c('yellow', str(s.modules))}")
        print(f"  端口数:     {_c('yellow', str(s.ports))}")
        print(f"  信号数:     {_c('yellow', str(s.signals))}")
        print(f"  参数数:     {_c('yellow', str(s.params))}")
        print(f"  实例化数:   {_c('yellow', str(s.instances))}")
        print(f"  函数/任务:  {_c('yellow', str(s.functions))}")
        print(f"  宏定义数:   {_c('yellow', str(s.macros))}")
        print()

    def do_find(self, arg):
        if not arg.strip():
            print(_c("red", "用法: find <关键词>"))
            return
        syms = self.idx.workspace_symbols(arg.strip(), limit=50)
        if not syms:
            print(_c("dim", "  未找到匹配符号"))
            return
        print(f"\n  找到 {_c('yellow', str(len(syms)))} 个符号：\n")
        for s in syms:
            kind_str = _c("magenta", f"[{s.kind}]")
            file_str = _c("dim", f"{os.path.basename(s.file)}:{s.range.start_line}")
            print(f"  {kind_str} {_c('bold', s.name)}  {file_str}  {s.detail}")
        print()

    def do_module(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: module <名字>"))
            return
        mod = self.idx.get_module(name)
        if not mod:
            print(_c("red", f"  未找到模块 '{name}'"))
            return
        print()
        print(f"  {_c('bold', 'module ' + mod.name)}")
        # 端口
        if mod.ports:
            print(f"\n  {_c('cyan', '端口')} ({len(mod.ports)})")
            for p in mod.ports:
                dir_str = _c("yellow", p.direction or "?") if p.direction else _c("dim", "?")
                w = f"[{p.width}]" if p.width and p.width != "1" else ""
                print(f"    {dir_str:12s} {p.data_type or 'wire':8s} {w:8s} {_c('bold', p.name)}")
        # 参数
        if mod.params:
            print(f"\n  {_c('cyan', '参数')} ({len(mod.params)})")
            for p in mod.params:
                print(f"    parameter {p.name} = {p.detail or '?'}")
        # 信号
        if mod.signals:
            print(f"\n  {_c('cyan', '内部信号')} ({len(mod.signals)})")
            for s in mod.signals:
                w = f"[{s.width}]" if s.width and s.width != "1" else ""
                print(f"    {s.data_type or 'wire':8s} {w:8s} {s.name}")
        # 实例
        if mod.instances:
            print(f"\n  {_c('cyan', '实例化')} ({len(mod.instances)})")
            for inst in mod.instances:
                print(f"    {_c('magenta', inst.module_type)}  {_c('bold', inst.inst_name)}")
                for c in inst.connections:
                    print(f"      .{_c('dim', c.port_name)}({c.signal_text})")
        print()

    def do_ports(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: ports <模块>"))
            return
        mod = self.idx.get_module(name)
        if not mod:
            print(_c("red", f"  未找到模块 '{name}'"))
            return
        print(f"\n  {_c('cyan', mod.name)} 端口 ({len(mod.ports)})\n")
        for p in mod.ports:
            dir_str = _c("yellow", p.direction or "?")
            w = f"[{p.width}]" if p.width and p.width != "1" else ""
            print(f"    {dir_str:12s} {p.data_type or 'wire':8s} {w:8s} {_c('bold', p.name)}")
        print()

    def do_signals(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: signals <模块>"))
            return
        mod = self.idx.get_module(name)
        if not mod:
            print(_c("red", f"  未找到模块 '{name}'"))
            return
        print(f"\n  {_c('cyan', mod.name)} 内部信号 ({len(mod.signals)})\n")
        for s in mod.signals:
            w = f"[{s.width}]" if s.width and s.width != "1" else ""
            print(f"    {s.data_type or 'wire':8s} {w:8s} {_c('bold', s.name)}")
        print()

    def do_instances(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: instances <模块>"))
            return
        mod = self.idx.get_module(name)
        if not mod:
            print(_c("red", f"  未找到模块 '{name}'"))
            return
        print(f"\n  {_c('cyan', mod.name)} 内部实例化 ({len(mod.instances)})\n")
        for inst in mod.instances:
            print(f"    {_c('magenta', inst.module_type)}  {_c('bold', inst.inst_name)}  {_c('dim', f'({len(inst.connections)} 连接)')}")
            for c in inst.connections:
                print(f"      .{c.port_name}({c.signal_text})")
        print()

    def do_whoinst(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: whoinst <模块>"))
            return
        insts = self.idx.who_instantiates(name)
        if not insts:
            print(_c("dim", f"  没有找到实例化 '{name}' 的地方"))
            return
        print(f"\n  {_c('cyan', name)} 被以下位置实例化 ({len(insts)})：\n")
        for s in insts:
            print(f"    {_c('magenta', f'[{s.kind}]')} {_c('bold', s.name)}  {_c('dim', f'{os.path.basename(s.file)}:{s.range.start_line}')}")
        print()

    def do_refs(self, arg):
        name = arg.strip()
        if not name:
            print(_c("red", "用法: refs <名字>"))
            return
        refs = self.idx.find_references(name)
        if not refs:
            print(_c("dim", f"  未找到 '{name}' 的引用"))
            return
        print(f"\n  {_c('cyan', name)} 的引用 ({len(refs)})：\n")
        for r in refs[:30]:
            ctx_str = _c("magenta", f"[{r.context}]")
            print(f"    {ctx_str} {r.name}  {_c('dim', f'{os.path.basename(r.file)}:{r.range.start_line}')}")
        if len(refs) > 30:
            print(f"  ... 还有 {len(refs) - 30} 条")
        print()

    def do_tree(self, arg):
        top = arg.strip()
        if not top:
            print(_c("red", "用法: tree <顶层模块>"))
            return
        hierarchy = self.idx.get_hierarchy(top)
        if not hierarchy:
            print(_c("red", f"  未找到模块 '{top}'"))
            return
        print()
        _print_tree(hierarchy, prefix="")
        print()

    def do_drivers(self, arg):
        parts = arg.strip().split()
        if len(parts) < 2:
            print(_c("red", "用法: drivers <文件路径> <信号名>"))
            return
        fp, sig = parts[0], parts[1]
        drivers = self.idx.get_signal_drivers(fp, sig)
        if not drivers:
            print(_c("dim", f"  未找到 '{sig}' 在 {os.path.basename(fp)} 中的驱动"))
            return
        print(f"\n  {_c('cyan', sig)} 在 {os.path.basename(fp)} 的驱动源 ({len(drivers)})：\n")
        for d in drivers:
            print(f"    [{d.context}] {d.name}  {_c('dim', f'{d.range.start_line}:{d.range.start_col}')}")
        print()

    def do_macros(self, arg):
        macros = self.idx.get_macros()
        if not macros:
            print(_c("dim", "  无宏定义"))
            return
        print(f"\n  宏定义 ({len(macros)})：\n")
        for k, v in macros.items():
            print(f"    {_c('bold', '`' + k)} = {v.detail or ''}  {_c('dim', os.path.basename(v.file))}")
        print()

    def do_primitives(self, arg):
        prims = sorted(self.elx.stub_modules.keys())
        print(f"\n  eLinx GTP 原语 ({len(prims)})：\n")
        for p in prims:
            ports = self.elx.get_stub_ports(p)
            print(f"    {_c('magenta', p):16s} {_c('dim', f'({len(ports)} 端口)')}")
        print()

    def do_constraints(self, arg):
        sig = arg.strip()
        if sig:
            c = self.elx.get_pin(sig)
            if c:
                print(f"\n  {_c('bold', sig)} → {_c('yellow', c.pin)}  {c.iostandard or ''} {c.drive or ''} {c.slew or ''}\n")
            else:
                print(_c("dim", f"  未找到 '{sig}' 的约束"))
            return
        all_c = self.elx.get_all_constraints()
        if not all_c:
            print(_c("dim", "  无约束（用 load 加载 .pcf/.xdc 后再查）"))
            return
        print(f"\n  引脚约束 ({len(all_c)})：\n")
        for c in all_c:
            print(f"    {_c('bold', c.signal):16s} → {_c('yellow', c.pin or '?'):8s} {c.iostandard or ''} {c.drive or ''} {c.slew or ''}")
        print()

    def do_load(self, arg):
        path = arg.strip()
        if not path:
            print(_c("red", "用法: load <目录>"))
            return
        if not os.path.isdir(path):
            print(_c("red", f"  目录不存在: {path}"))
            return
        count = self.idx.index_directory(path)
        s = self.idx.stats
        print(f"  {_c('green', '✓')} 索引 {count} 个文件 | 模块 {s.modules} | 端口 {s.ports} | 信号 {s.signals} | 实例 {s.instances}")

    # ---- 默认 ----

    def default(self, line):
        print(_c("red", f"  未知命令: {line.strip()}  (输入 help 查看命令列表)"))

    # ---- v2.0.0 新增命令 ----

    def do_rename(self, arg):
        """跨文件重命名符号: rename <文件> <行> <列> <新名>"""
        parts = arg.strip().split()
        if len(parts) != 4:
            print(_c("red", "用法: rename <文件路径> <行号> <列号> <新名>"))
            print(_c("dim", "  例: rename examples/counter/counter.v 5 10 my_counter"))
            return
        fp, line_s, col_s, new_name = parts
        try:
            line = int(line_s)
            col = int(col_s)
        except ValueError:
            print(_c("red", "  行号和列号必须是整数"))
            return
        if fp not in self.idx._files:
            print(_c("red", f"  文件未索引: {fp}"))
            print(_c("dim", "  提示: 先 load 目录或打开文件"))
            return
        result = self.idx.rename_symbol(fp, line, col, new_name)
        if not result:
            print(_c("red", "  未找到可重命名的符号"))
            return
        changes = result.get("changes", {})
        total = sum(len(edits) for edits in changes.values())
        print(f"  {_c('green', '✓')} 重命名 → {new_name}")
        print(f"  {_c('dim', '影响')} {len(changes)} 个文件 / {total} 处修改:")
        for f, edits in changes.items():
            short = os.path.basename(f)
            print(f"    {_c('cyan', short)}: {len(edits)} 处")

    def do_codelens(self, arg):
        """代码透镜: codelens <文件>"""
        fp = arg.strip()
        if not fp:
            print(_c("red", "用法: codelens <文件路径>"))
            return
        if fp not in self.idx._files:
            print(_c("red", f"  文件未索引: {fp}"))
            return
        lenses = self.idx.get_code_lens(fp)
        if not lenses:
            print(_c("dim", "  无代码透镜"))
            return
        for lens in lenses:
            rng = lens.get("range", {}).get("start", {})
            cmd = lens.get("command", {})
            title = cmd.get("title", "")
            ln = rng.get("line", 0)
            print(f"  {_c('cyan', f'L{ln}')}: {title}")

    def do_dectree(self, arg):
        """层级符号树: dectree <文件>"""
        fp = arg.strip()
        if not fp:
            print(_c("red", "用法: dectree <文件路径>"))
            return
        if fp not in self.idx._files:
            print(_c("red", f"  文件未索引: {fp}"))
            return
        tree = self.idx.document_symbol_tree(fp)
        if not tree:
            print(_c("dim", "  无符号"))
            return
        for node in tree:
            _print_symbol_node(node, 0)


def _print_tree(node: dict, prefix: str, is_last: bool = True, is_root: bool = True):
    """递归渲染 ASCII 层级树。

    节点结构（get_hierarchy 返回）：
      根: {"module": "top", "instances": [{"instance":"u1","type":"counter","file":"...","sub":{...}}]}
    非根节点可能同时携带 type/instance/file（来自父的 instances 列表项）和 module/instances（来自 sub）
    """
    mod_name = node.get("module", "?")
    if is_root:
        print(f"  {_c('bold', mod_name)}")
    else:
        connector = "└── " if is_last else "├── "
        inst = node.get("instance", "")
        type_name = node.get("type", "") or mod_name
        file = node.get("file", "")
        label = f"{_c('magenta', type_name)}  {_c('dim', inst)}"
        if file:
            label += f"  {_c('dim', f'({os.path.basename(file)})')}"
        print(f"  {prefix}{connector}{label}")
        prefix += "    " if is_last else "│   "

    children = node.get("instances", [])
    for i, child in enumerate(children):
        # 合并 child 的元信息(type/instance/file)与其 sub 的结构(module/instances)
        sub = child.get("sub", {})
        merged = {**sub, "instance": child.get("instance", ""), "type": child.get("type", ""), "file": child.get("file", "")}
        _print_tree(merged, prefix, i == len(children) - 1, is_root=False)


def _print_symbol_node(node: dict, depth: int):
    """递归渲染层级符号树（document_symbol_tree 返回）。"""
    prefix = "  " + ("  " * depth)
    connector = "├── " if depth > 0 else ""
    name = node.get("name", "?")
    detail = node.get("detail", "")
    kind = node.get("kind", 0)
    kind_names = {2: "module", 7: "port", 13: "signal", 14: "param", 12: "func", 6: "conn", 15: "inst"}
    kind_label = kind_names.get(kind, "?")
    line_info = ""
    rng = node.get("range", {}).get("start", {})
    if rng:
        ln = rng.get("line", 0)
        line_info = f" {_c('dim', f'L{ln}')}"
    label = f"{prefix}{connector}{_c('bold', name)}"
    if detail:
        label += f"  {_c('dim', detail)}"
    label += f"  {_c('cyan', f'[{kind_label}]')}{line_info}"
    print(label)
    for child in node.get("children", []):
        _print_symbol_node(child, depth + 1)


def run_tui(index_root: Optional[str] = None, include_paths=None, stub_dir=None):
    _enable_vt()
    idx = WorkspaceIndex(include_paths=include_paths)
    elx = ELinxSupport(stub_dir=stub_dir)
    if index_root and os.path.isdir(index_root):
        count = idx.index_directory(index_root)
        s = idx.stats
        print(f"[rtlens] 已索引 {count} 个文件 | 模块 {s.modules} | 信号 {s.signals} | 实例 {s.instances}\n")
    shell = RTLensShell(idx, elx)
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\n" + _c("dim", "再见"))
