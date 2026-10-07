"""内置 Verilog/SystemVerilog 语法解析器（容错式，零依赖）。

不是完整的语法验证器——目标是**从源码中提取 LSP 所需的结构化信息**：
- module 定义（端口、参数、位置）
- 信号声明（wire/reg/logic，含位宽）
- 模块例化（类型、实例名、端口连接）
- assign / always 驱动目标（用于 references 与 driver 分析）
- function / task / typedef / enum / package
- 所有标识符引用位置（用于 find-references）

编辑中间态（语法不完整）也绝不抛异常。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict

from .lexer import Token, TokenKind, lex, strip_comments


# ---------- 数据结构 ----------

@dataclass
class Range:
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def contains(self, line: int, col: int) -> bool:
        if line < self.start_line or line > self.end_line:
            return False
        if line == self.start_line and col < self.start_col:
            return False
        if line == self.end_line and col >= self.end_col:
            return False
        return True


@dataclass
class Symbol:
    name: str
    kind: str                 # module/port/signal/parameter/instance/function/task/typedef/enum/package/macro
    range: Range
    name_range: Range
    detail: str = ""          # 例如 "input wire [7:0]" / "parameter = 32"
    parent: str = ""          # 所属 module 名
    width: str = ""           # "[7:0]" 或 ""
    direction: str = ""       # input/output/inout（port）
    data_type: str = ""       # wire/reg/logic/int 等
    children: List["Symbol"] = field(default_factory=list)


@dataclass
class PortConnection:
    port_name: str            # .port(sig) 中的 port；位置连接时为空
    signal_text: str          # 连接表达式原文
    range: Range


@dataclass
class Instance:
    module_type: str
    inst_name: str
    range: Range
    name_range: Range
    type_range: Range
    parent: str
    connections: List[PortConnection] = field(default_factory=list)


@dataclass
class Reference:
    name: str
    range: Range
    context: str              # declaration / usage / port_connection / instantiation / driver


@dataclass
class ModuleInfo:
    name: str
    range: Range
    name_range: Range
    ports: List[Symbol] = field(default_factory=list)
    params: List[Symbol] = field(default_factory=list)
    signals: List[Symbol] = field(default_factory=list)
    instances: List[Instance] = field(default_factory=list)
    functions: List[Symbol] = field(default_factory=list)


@dataclass
class MacroDef:
    name: str
    value: str
    range: Range
    name_range: Range
    args: List[str] = field(default_factory=list)


@dataclass
class IncludeRef:
    path: str
    range: Range


@dataclass
class ParseResult:
    modules: List[ModuleInfo] = field(default_factory=list)
    packages: List[Symbol] = field(default_factory=list)
    package_details: List[ModuleInfo] = field(default_factory=list)  # v6.0.1: package body (functions, params)
    interfaces: List[ModuleInfo] = field(default_factory=list)   # v6.0.1: interface as ModuleInfo
    typedefs: List[Symbol] = field(default_factory=list)         # v6.0.1: typedef tracking
    macros: List[MacroDef] = field(default_factory=list)
    includes: List[IncludeRef] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def all_module_symbols(self) -> List[Symbol]:
        out: List[Symbol] = []
        for m in self.modules:
            s = Symbol(name=m.name, kind="module", range=m.range, name_range=m.name_range,
                       detail=f"module ({len(m.ports)} ports)")
            s.children = m.ports + m.params + m.signals + m.functions
            out.append(s)
        return out


# ---------- 解析器 ----------

_DECL_TYPE_WORDS = {"wire", "reg", "logic", "tri", "tri0", "tri1", "wand", "wor", "integer", "real", "time", "bit", "genvar"}
_DIR_WORDS = {"input", "output", "inout"}
_MOD_WORDS = {"signed", "unsigned", "automatic", "static", "const", "var"}
_BUILTIN_TYPE_WORDS = {"int", "shortint", "longint", "byte", "shortreal", "string", "event", "chandle", "realtime"}

# 赋值操作符：IDENT 后紧跟这些符号（且不在条件括号内）→ 该 IDENT 是驱动点（driver）
_ASSIGN_OPS = {"<=", "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
               "<<=", ">>=", "<<<=", ">>>="}


class Parser:
    def __init__(self, text: str):
        self.text = text
        # 预切分为行：_text_of 按行列取原文时需要，O(n) 只做一次。
        # 原先在 _text_of 内每次调用都 split 全文 → O(n^2)，12MB 文件退化成数百秒。
        self.lines = text.split("\n")
        self.lex_result = lex(text)
        self.tokens = strip_comments(self.lex_result.tokens)
        self.i = 0
        self.result = ParseResult()

    # ---- token 工具 ----
    def peek(self, k: int = 0) -> Token:
        idx = min(self.i + k, len(self.tokens) - 1)
        return self.tokens[idx]

    def next(self) -> Token:
        t = self.peek()
        if self.i < len(self.tokens) - 1:
            self.i += 1
        return t

    def at_keyword(self, *words: str) -> bool:
        t = self.peek()
        return t.kind == TokenKind.KEYWORD and t.text in words

    def at_symbol(self, *syms: str) -> bool:
        t = self.peek()
        return t.kind == TokenKind.SYMBOL and t.text in syms

    def at_directive(self, *names: str) -> bool:
        t = self.peek()
        return t.kind == TokenKind.DIRECTIVE and t.text in names

    @staticmethod
    def rng(t: Token) -> Range:
        return Range(t.line, t.col, t.end_line, t.end_col)

    @staticmethod
    def rng2(a: Token, b: Token) -> Range:
        return Range(a.line, a.col, b.end_line, b.end_col)

    # ---- 顶层 ----
    def _skip_to_semicolon(self):
        """消费 token 直到含分号（用于 module 头 import 子句等）。"""
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
            self.next()
        if self.at_symbol(";"):
            self.next()

    def parse(self) -> ParseResult:
        guard = 0
        while self.peek().kind != TokenKind.EOF and guard < 200000:
            guard += 1
            t = self.peek()
            try:
                if t.kind == TokenKind.KEYWORD and t.text in ("module", "macromodule"):
                    self.parse_module()
                elif t.kind == TokenKind.KEYWORD and t.text == "interface":
                    self.parse_interface()
                elif t.kind == TokenKind.KEYWORD and t.text == "package":
                    self.parse_package()
                elif t.kind == TokenKind.DIRECTIVE:
                    self.parse_directive()
                elif t.kind == TokenKind.KEYWORD and t.text == "typedef":
                    td = self.parse_typedef(parent="")
                    if td:
                        self.result.typedefs.append(td)
                else:
                    self.next()
            except Exception as e:  # 容错：记录错误继续
                self.result.errors.append(f"parse error at {t.line}:{t.col}: {e}")
                self.next()
        return self.result

    # ---- 编译指令 ----
    def parse_directive(self):
        t = self.next()
        name = t.text
        if name == "`define":
            self._parse_define(t)
        elif name == "`include":
            self._parse_include(t)
        # `ifdef/`ifndef/`else/`elsif/`endif/`timescale/`default_nettype 等跳过该行剩余 token
        else:
            self._skip_to_eol()

    def _skip_to_eol(self):
        base = self.peek(-1).line if self.i > 0 else self.peek().line
        while self.peek().kind != TokenKind.EOF and self.peek().line == base:
            self.next()

    def _parse_define(self, dir_tok: Token):
        t = self.peek()
        if t.kind != TokenKind.IDENT or t.line != dir_tok.line:
            return
        name_tok = self.next()
        args: List[str] = []
        # 带参宏：`define FOO(a,b) ...
        if self.at_symbol("(") and self.peek().line == name_tok.line:
            self.next()
            while not self.at_symbol(")") and self.peek().kind != TokenKind.EOF:
                tt = self.next()
                if tt.kind == TokenKind.IDENT:
                    args.append(tt.text)
        # 取宏体（本行剩余）
        parts: List[str] = []
        while self.peek().kind != TokenKind.EOF and self.peek().line == name_tok.line:
            parts.append(self.next().text)
        value = " ".join(parts)
        self.result.macros.append(MacroDef(
            name=name_tok.text, value=value,
            range=self.rng2(dir_tok, self.peek()),
            name_range=self.rng(name_tok), args=args))

    def _parse_include(self, dir_tok: Token):
        t = self.peek()
        if t.kind == TokenKind.STRING and t.line == dir_tok.line:
            self.next()
            path = t.text.strip('"')
            self.result.includes.append(IncludeRef(path=path, range=self.rng2(dir_tok, t)))
        elif t.kind == TokenKind.SYMBOL and t.text == "<":
            parts = []
            while self.peek().kind != TokenKind.EOF and not self.at_symbol(">"):
                parts.append(self.next().text)
            if self.at_symbol(">"):
                end_t = self.next()
                self.result.includes.append(IncludeRef(path="".join(parts), range=self.rng2(dir_tok, end_t)))

    # ---- package ----
    def parse_package(self):
        start = self.next()  # package
        t = self.peek()
        if t.kind != TokenKind.IDENT:
            return
        name_tok = self.next()
        sym = Symbol(name=name_tok.text, kind="package",
                     range=self.rng2(start, name_tok), name_range=self.rng(name_tok),
                     detail="package")
        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
        # v6.0.1: 解析包体 — 之前只是粗扫到 endpackage，跳过了 typedef/function/parameter
        pkg_mod = ModuleInfo(name=name_tok.text, range=self.rng2(start, name_tok),
                             name_range=self.rng(name_tok))
        self._parse_package_body(pkg_mod)
        self.result.package_details.append(pkg_mod)    # v6.0.1: store for indexer
        # endpackage
        if self.at_keyword("endpackage"):
            end_t = self.next()
            sym.range = self.rng2(start, end_t)
        self.result.packages.append(sym)

    def _parse_package_body(self, mod: ModuleInfo):
        """v6.0.1: 解析包体 — 参数、localparam、typedef、function、信号声明。"""
        while self.peek().kind != TokenKind.EOF:
            t = self.peek()
            if t.kind == TokenKind.KEYWORD and t.text == "endpackage":
                return
            if t.kind == TokenKind.KEYWORD and t.text in ("package", "module", "macromodule", "interface"):
                return
            try:
                if t.kind == TokenKind.KEYWORD:
                    w = t.text
                    if w in _DECL_TYPE_WORDS or w in _DIR_WORDS or w in _BUILTIN_TYPE_WORDS:
                        self._parse_signal_decl(mod); continue
                    if w in ("parameter", "localparam"):
                        self._parse_body_param(mod); continue
                    if w in ("function", "task"):
                        self._parse_function(mod); continue
                    if w == "typedef":
                        td = self.parse_typedef(parent=mod.name)
                        if td:
                            mod.functions.append(td)
                            self.result.typedefs.append(td)    # v6.0.1: track in result
                        continue
                    if w in ("always", "always_ff", "always_comb", "always_latch", "initial", "final"):
                        self._parse_process_block(mod); continue
                    if w in ("generate", "endgenerate"):
                        self.next(); continue
                    self.next(); continue
                if t.kind == TokenKind.DIRECTIVE:
                    self.parse_directive(); continue
                if t.kind == TokenKind.IDENT:
                    if self._is_user_type_decl():
                        self._parse_signal_decl(mod); continue
                    self.next(); continue
                self.next()
            except Exception as e:
                self.result.errors.append(f"package body error at {t.line}:{t.col}: {e}")
                self.next()

    # ---- typedef / enum ----
    def parse_typedef(self, parent: str):
        start = self.next()  # typedef
        name_tok: Optional[Token] = None
        is_enum = False
        depth = 0
        guard = 0
        while self.peek().kind != TokenKind.EOF and guard < 2000:
            guard += 1
            t = self.peek()
            if t.kind == TokenKind.KEYWORD and t.text == "enum":
                is_enum = True
            if t.kind == TokenKind.SYMBOL and t.text == "{":
                depth += 1
            elif t.kind == TokenKind.SYMBOL and t.text == "}":
                depth -= 1
            elif t.kind == TokenKind.IDENT and depth == 0:
                name_tok = t
            elif t.kind == TokenKind.SYMBOL and t.text == ";" and depth == 0:
                self.next()
                break
            self.next()
        if name_tok is not None:
            self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
            return Symbol(name=name_tok.text, kind="enum" if is_enum else "typedef",
                          range=self.rng2(start, name_tok), name_range=self.rng(name_tok),
                          detail="enum" if is_enum else "typedef", parent=parent)
        return None

    # ---- module ----
    def parse_module(self):
        start = self.next()  # module
        t = self.peek()
        if t.kind != TokenKind.IDENT:
            return
        name_tok = self.next()
        mod = ModuleInfo(name=name_tok.text,
                         range=self.rng2(start, name_tok),
                         name_range=self.rng(name_tok))
        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))

        # SystemVerilog 头部 import 子句：module m import pkg::*; #(...)(...)
        # 必须在 #/( 之前吃掉，否则整个参数与端口列表会被"跳到分号"兜底吞掉
        while self.at_keyword("import"):
            self._skip_to_semicolon()

        # 参数列表 #(...)
        if self.at_symbol("#"):
            self.next()
            if self.at_symbol("("):
                self._parse_param_list(mod)

        # 端口列表 (...)
        if self.at_symbol("("):
            self._parse_port_list(mod)

        # 直到分号
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
            self.next()
        if self.at_symbol(";"):
            self.next()

        # module 体
        self._parse_module_body(mod)

        # endmodule
        if self.at_keyword("endmodule"):
            end_t = self.next()
            mod.range = self.rng2(start, end_t)
        self.result.modules.append(mod)

    # ---- interface (v6.0.1) ----
    def parse_interface(self):
        """Parse SystemVerilog interface — treated like a ModuleInfo for indexing."""
        start = self.next()  # interface
        t = self.peek()
        if t.kind != TokenKind.IDENT:
            return
        name_tok = self.next()
        iface = ModuleInfo(name=name_tok.text,
                           range=self.rng2(start, name_tok),
                           name_range=self.rng(name_tok))
        # Add "interface" to detail so callers can distinguish from modules
        iface_detail = f"interface ({0} ports)"
        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))

        # SystemVerilog 头部 import 子句（同 module）
        while self.at_keyword("import"):
            self._skip_to_semicolon()

        # 参数列表 #(...)
        if self.at_symbol("#"):
            self.next()
            if self.at_symbol("("):
                self._parse_param_list(iface)

        # 端口列表 (...)
        if self.at_symbol("("):
            self._parse_port_list(iface)

        # 直到分号
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
            # Don't cross into endinterface
            if self.at_keyword("endinterface"):
                break
            self.next()
        if self.at_symbol(";"):
            self.next()

        # interface body — reuse module body parser (handles signals, instances, etc.)
        # but stop at endinterface instead of endmodule
        self._parse_interface_body(iface)

        # endinterface
        if self.at_keyword("endinterface"):
            end_t = self.next()
            iface.range = self.rng2(start, end_t)
        # Update detail with actual port count
        iface_detail = f"interface ({len(iface.ports)} ports)"
        self.result.interfaces.append(iface)

    def _parse_interface_body(self, mod: ModuleInfo):
        """Parse interface body — reuses _parse_module_body with endinterface guard."""
        # Temporarily make _parse_module_body treat endinterface like endmodule
        # by calling it — it already returns on endmodule/module/macromodule;
        # we add endinterface as a return trigger here
        while self.peek().kind != TokenKind.EOF:
            t = self.peek()
            if t.kind == TokenKind.KEYWORD and t.text == "endinterface":
                return
            if t.kind == TokenKind.KEYWORD and t.text in ("module", "macromodule", "interface"):
                return
            # Delegate one token's worth of processing to module body logic
            try:
                if t.kind == TokenKind.KEYWORD:
                    w = t.text
                    if w in _DECL_TYPE_WORDS or w in _DIR_WORDS or w in _BUILTIN_TYPE_WORDS:
                        self._parse_signal_decl(mod); continue
                    if w in ("parameter", "localparam"):
                        self._parse_body_param(mod); continue
                    if w == "assign":
                        self._parse_assign(mod); continue
                    if w in ("function", "task"):
                        self._parse_function(mod); continue
                    if w == "import":
                        self._skip_to_semicolon(); continue
                    if w == "typedef":
                        td = self.parse_typedef(parent=mod.name)
                        if td:
                            mod.functions.append(td)
                            self.result.typedefs.append(td)    # v6.0.1: also track in result
                        continue
                    if w in ("always", "always_ff", "always_comb", "always_latch", "initial", "final"):
                        self._parse_process_block(mod); continue
                    if w in ("generate", "endgenerate"):
                        self.next(); continue
                    if w == "modport":
                        self._parse_modport(mod); continue
                    self.next(); continue
                if t.kind == TokenKind.DIRECTIVE:
                    self.parse_directive(); continue
                if t.kind == TokenKind.IDENT:
                    if self._is_user_type_decl():
                        self._parse_signal_decl(mod); continue
                    if self._try_parse_instance(mod):
                        continue
                    self.next(); continue
                self.next()
            except Exception as e:
                self.result.errors.append(f"interface body error at {t.line}:{t.col}: {e}")
                self.next()

    def _parse_modport(self, mod: ModuleInfo):
        """Parse modport declaration inside interface."""
        self.next()  # modport
        if self.peek().kind != TokenKind.IDENT:
            return
        name_tok = self.next()  # modport name
        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
        # Skip to end of modport declaration (;)
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
            self.next()
        if self.at_symbol(";"):
            self.next()

    def _parse_param_list(self, mod: ModuleInfo):
        self.next()  # (
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(")"):
            if self.at_keyword("parameter", "localparam"):
                kind_tok = self.next()
                # 跳过类型与位宽
                while self.peek().kind in (TokenKind.KEYWORD,) and self.peek().text in _MOD_WORDS | _DECL_TYPE_WORDS | _BUILTIN_TYPE_WORDS | {"signed", "unsigned", "type"}:
                    self.next()
                # SystemVerilog: parameter type T = ... 中 T 后可能跟限定类型值
                if self.at_symbol("["):
                    self._skip_brackets()
                while True:
                    t = self.peek()
                    if t.kind == TokenKind.IDENT:
                        name_tok = self.next()
                        val = ""
                        if self.at_symbol("="):
                            self.next()
                            parts: List[str] = []
                            depth = 0
                            while self.peek().kind != TokenKind.EOF:
                                if depth == 0 and (self.at_symbol(",") or self.at_symbol(")")):
                                    break
                                if self.at_symbol("(", "["):
                                    depth += 1
                                elif self.at_symbol(")", "]"):
                                    if depth == 0:
                                        break
                                    depth -= 1
                                parts.append(self.next().text)
                            val = " ".join(parts)
                        sym = Symbol(name=name_tok.text, kind="parameter",
                                     range=self.rng2(kind_tok, self.peek(-1) if self.i else name_tok),
                                     name_range=self.rng(name_tok),
                                     detail=f"parameter = {val}" if val else "parameter",
                                     parent=mod.name)
                        mod.params.append(sym)
                        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
                    if self.at_symbol(","):
                        self.next()
                        continue
                    break
            else:
                self.next()
        if self.at_symbol(")"):
            self.next()

    def _skip_brackets(self):
        """跳过匹配的 [...] 对"""
        if not self.at_symbol("["):
            return
        depth = 0
        while self.peek().kind != TokenKind.EOF:
            if self.at_symbol("["):
                depth += 1
            elif self.at_symbol("]"):
                depth -= 1
                if depth == 0:
                    self.next()
                    return
            self.next()

    def _read_width(self) -> str:
        """读取可选位宽 [msb:lsb]，返回原文"""
        if not self.at_symbol("["):
            return ""
        start = self.peek()
        self._skip_brackets()
        end = self.peek(-1)
        return self._text_of(start, end)

    def _try_read_user_type(self) -> str:
        """尝试读取用户定义类型（SystemVerilog）。

        支持两种形式：
        - 限定类型：Type::Name（可多层 Type::Sub::Name）
        - 裸用户类型：Type name（当前 IDENT 后紧跟另一个 IDENT，则前者是类型）

        返回类型字符串；若当前 token 不是类型则返回空串。
        调用方应在已处理方向/关键字类型/位宽后、即将把 IDENT 当名称时调用。
        """
        t = self.peek()
        if t.kind != TokenKind.IDENT:
            return ""
        nxt = self.peek(1)
        # Type::Name 模式
        if nxt.kind == TokenKind.SYMBOL and nxt.text == "::":
            parts = [t.text]
            self.next()  # Type
            while self.at_symbol("::"):
                self.next()  # ::
                if self.peek().kind == TokenKind.IDENT:
                    parts.append(self.next().text)
                else:
                    break
            return "::".join(parts)
        # 裸用户类型 Type name（紧跟另一个 IDENT 才算类型）
        if nxt.kind == TokenKind.IDENT:
            return self.next().text
        return ""

    def _is_user_type_decl(self) -> bool:
        """判断当前位置是否开启一个用户类型信号声明（非例化）。

        - Type::Name ...  → True
        - Type name ; / Type name [  → True（排除 ModuleName inst ( 的例化）
        """
        t = self.peek()
        if t.kind != TokenKind.IDENT:
            return False
        nxt = self.peek(1)
        if nxt.kind == TokenKind.SYMBOL and nxt.text == "::":
            return True
        if nxt.kind == TokenKind.IDENT:
            after = self.peek(2)
            if after.kind == TokenKind.SYMBOL and after.text in ("(", "#"):
                return False  # ModuleName inst_name ( → 例化
            return True
        return False

    def _text_of(self, a: Token, b: Token) -> str:
        """取 token a..b 之间的源码原文（近似，用位置切片）。"""
        lines = self.lines
        try:
            if a.line == b.end_line:
                return lines[a.line][a.col:b.end_col]
            parts = [lines[a.line][a.col:]]
            for ln in range(a.line + 1, b.end_line):
                parts.append(lines[ln])
            parts.append(lines[b.end_line][:b.end_col])
            return "\n".join(parts)
        except Exception:
            return ""

    def _parse_port_list(self, mod: ModuleInfo):
        """ANSI 端口列表 (input clk, output reg [7:0] q, ...)"""
        self.next()  # (
        pending_dir = ""
        pending_type = ""
        pending_width = ""
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(")"):
            t = self.peek()
            if t.kind == TokenKind.KEYWORD and t.text in _DIR_WORDS:
                pending_dir = self.next().text
                pending_type = ""
                pending_width = ""
                continue
            if t.kind == TokenKind.KEYWORD and (t.text in _DECL_TYPE_WORDS or t.text in _MOD_WORDS or t.text in _BUILTIN_TYPE_WORDS):
                w = self.next().text
                if w in _DECL_TYPE_WORDS or w in _BUILTIN_TYPE_WORDS:
                    pending_type = w
                continue
            if self.at_symbol("["):
                pending_width = self._read_width()
                continue
            if t.kind == TokenKind.IDENT:
                # SystemVerilog: 限定类型 Type::Name 或裸用户类型 Type
                qt = self._try_read_user_type()
                if qt:
                    pending_type = qt
                    continue
                name_tok = self.next()
                # 端口后可能跟位选/数组维度，跳过
                if self.at_symbol("["):
                    self._skip_brackets()
                sym = Symbol(name=name_tok.text, kind="port",
                             range=self.rng(name_tok), name_range=self.rng(name_tok),
                             detail=f"{pending_dir} {pending_type} {pending_width}".strip(),
                             parent=mod.name, width=pending_width,
                             direction=pending_dir, data_type=pending_type)
                mod.ports.append(sym)
                self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
                # 重置类型/位宽（方向保持：verilog 允许省略后续端口方向沿用上一个）
                pending_type = ""
                pending_width = ""
                continue
            self.next()
        if self.at_symbol(")"):
            self.next()

    def _parse_module_body(self, mod: ModuleInfo):
        depth = 0
        while self.peek().kind != TokenKind.EOF:
            t = self.peek()
            try:
                if t.kind == TokenKind.KEYWORD:
                    w = t.text
                    if w == "endmodule":
                        return
                    if w in ("module", "macromodule"):
                        # 嵌套 module（非法但容错）：结束当前
                        return
                    if w == "import":
                        # 包导入：跳过整条语句，不把包名记成信号引用
                        self._skip_to_semicolon()
                        continue
                    if w in _DECL_TYPE_WORDS or w in _DIR_WORDS or w in _BUILTIN_TYPE_WORDS:
                        self._parse_signal_decl(mod)
                        continue
                    if w in ("parameter", "localparam"):
                        self._parse_body_param(mod)
                        continue
                    if w == "assign":
                        self._parse_assign(mod)
                        continue
                    if w in ("function", "task"):
                        self._parse_function(mod)
                        continue
                    if w == "typedef":
                        td = self.parse_typedef(parent=mod.name)
                        if td:
                            self.result.typedefs.append(td)    # v6.0.1: track in result
                        continue
                    if w in ("always", "always_ff", "always_comb", "always_latch", "initial", "final"):
                        self._parse_process_block(mod)
                        continue
                    if w == "generate":
                        self.next()
                        continue
                    if w == "endgenerate":
                        self.next()
                        continue
                    self.next()
                    continue
                if t.kind == TokenKind.DIRECTIVE:
                    self.parse_directive()
                    continue
                if t.kind == TokenKind.IDENT:
                    # SystemVerilog 用户类型信号声明（Type::Name x / T x）优先于例化判断
                    if self._is_user_type_decl():
                        self._parse_signal_decl(mod)
                        continue
                    # 可能是例化：Ident [#(...)] name (...);
                    if self._try_parse_instance(mod):
                        continue
                    self.next()
                    continue
                self.next()
            except Exception as e:
                self.result.errors.append(f"body parse error at {t.line}:{t.col}: {e}")
                self.next()

    def _parse_signal_decl(self, mod: ModuleInfo):
        """wire/reg/logic/input/output/int/... 或用户类型 声明（module 体内）"""
        first = self.next()
        direction = first.text if first.text in _DIR_WORDS else ""
        data_type = ""
        if direction:
            # input wire [7:0] xxx —— 继续吃类型
            if self.peek().kind == TokenKind.KEYWORD and self.peek().text in _DECL_TYPE_WORDS | _BUILTIN_TYPE_WORDS:
                data_type = self.next().text
            elif self.peek().kind == TokenKind.KEYWORD and self.peek().text in _MOD_WORDS:
                pass  # signed/unsigned 等修饰符，留给下面处理
            else:
                # SystemVerilog 用户类型: input my_pkg::packet_t x  /  input T x
                qt = self._try_read_user_type()
                if qt:
                    data_type = qt
        else:
            data_type = first.text
            # 用户类型首 token 是 IDENT — 可能是 Type::Name，继续读完整限定名
            if first.kind == TokenKind.IDENT and self.at_symbol("::"):
                while self.at_symbol("::"):
                    self.next()
                    if self.peek().kind == TokenKind.IDENT:
                        data_type += "::" + self.next().text
                    else:
                        break
        # genvar 不算信号
        if data_type == "genvar":
            # 消费到分号
            while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
                self.next()
            if self.at_symbol(";"):
                self.next()
            return
        # signed/unsigned
        while self.peek().kind == TokenKind.KEYWORD and self.peek().text in _MOD_WORDS:
            self.next()
        width = self._read_width()
        # SystemVerilog: 用户类型可能在位宽之后才出现，如 localparam 之后
        # 但一般声明顺序是 type [width] name，此处已处理
        # 标识符列表
        while self.peek().kind != TokenKind.EOF:
            t = self.peek()
            if t.kind == TokenKind.IDENT:
                name_tok = self.next()
                # 数组维度
                if self.at_symbol("["):
                    self._skip_brackets()
                # 初始化值 = ...
                if self.at_symbol("="):
                    self.next()
                    depth = 0
                    while self.peek().kind != TokenKind.EOF:
                        if depth == 0 and (self.at_symbol(",") or self.at_symbol(";")):
                            break
                        if self.at_symbol("(", "["):
                            depth += 1
                        elif self.at_symbol(")", "]"):
                            depth -= 1
                        self.next()
                kind = "port" if direction else "signal"
                sym = Symbol(name=name_tok.text, kind=kind,
                             range=self.rng2(first, name_tok), name_range=self.rng(name_tok),
                             detail=f"{direction} {data_type} {width}".strip(),
                             parent=mod.name, width=width, direction=direction, data_type=data_type)
                if direction:
                    # 非 ANSI 风格的端口重复声明：去重
                    if not any(p.name == name_tok.text for p in mod.ports):
                        mod.ports.append(sym)
                else:
                    mod.signals.append(sym)
                self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
                if self.at_symbol(","):
                    self.next()
                    continue
                if self.at_symbol(";"):
                    self.next()
                return
            if self.at_symbol(";"):
                self.next()
                return
            self.next()

    def _parse_body_param(self, mod: ModuleInfo):
        kind_tok = self.next()  # parameter / localparam
        while self.peek().kind == TokenKind.KEYWORD and self.peek().text in _MOD_WORDS | _BUILTIN_TYPE_WORDS | _DECL_TYPE_WORDS | {"type"}:
            self.next()
        if self.at_symbol("["):
            self._skip_brackets()
        while self.peek().kind != TokenKind.EOF:
            t = self.peek()
            if t.kind == TokenKind.IDENT:
                name_tok = self.next()
                val = ""
                if self.at_symbol("="):
                    self.next()
                    parts: List[str] = []
                    depth = 0
                    while self.peek().kind != TokenKind.EOF:
                        if depth == 0 and (self.at_symbol(",") or self.at_symbol(";")):
                            break
                        if self.at_symbol("(", "["):
                            depth += 1
                        elif self.at_symbol(")", "]"):
                            depth -= 1
                        parts.append(self.next().text)
                    val = " ".join(parts)
                sym = Symbol(name=name_tok.text, kind="parameter",
                             range=self.rng2(kind_tok, name_tok), name_range=self.rng(name_tok),
                             detail=f"{kind_tok.text} = {val}" if val else kind_tok.text,
                             parent=mod.name)
                mod.params.append(sym)
                self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
                if self.at_symbol(","):
                    self.next()
                    continue
            if self.at_symbol(";"):
                self.next()
                return
            if t.kind == TokenKind.IDENT:
                continue
            self.next()

    def _parse_assign(self, mod: ModuleInfo):
        self.next()  # assign
        # 抓 LHS 作为 driver
        t = self.peek()
        if t.kind == TokenKind.IDENT:
            self.result.references.append(Reference(t.text, self.rng(t), "driver"))
        # 整句扫到分号，期间记录所有 IDENT 为 usage
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
            tok = self.next()
            if tok.kind == TokenKind.IDENT:
                ctx = "driver" if tok is t else "usage"
                if tok is not t:
                    self.result.references.append(Reference(tok.text, self.rng(tok), "usage"))
        if self.at_symbol(";"):
            self.next()

    def _parse_process_block(self, mod: ModuleInfo):
        """always/initial 块：扫描内部赋值目标作为 driver，其余 IDENT 为 usage。"""
        kw = self.next()
        # 敏感表
        if self.at_symbol("@"):
            self.next()
            if self.at_symbol("("):
                depth = 0
                while self.peek().kind != TokenKind.EOF:
                    if self.at_symbol("("):
                        depth += 1
                    elif self.at_symbol(")"):
                        depth -= 1
                        if depth == 0:
                            self.next()
                            break
                    tok = self.next()
                    if tok.kind == TokenKind.IDENT:
                        self.result.references.append(Reference(tok.text, self.rng(tok), "usage"))
        # 块体：begin...end 或单语句
        self._scan_statement_block()

    def _scan_statement_block(self):
        """扫描 always/initial 块体。

        关键：区分赋值目标（driver）与读取（usage）。
        IDENT 后紧跟赋值操作符（<=  =  += 等）且当前不在条件括号内 → driver；
        其余 → usage。括号深度用于区分 `if (a <= b)`（比较，usage）与 `a <= b`（赋值，driver）。
        """
        if self.at_keyword("begin"):
            depth = 0
            paren_depth = 0
            while self.peek().kind != TokenKind.EOF:
                t = self.next()
                if t.kind == TokenKind.KEYWORD:
                    if t.text == "begin":
                        depth += 1
                    elif t.text == "end":
                        depth -= 1
                        if depth <= 0:
                            return
                    elif t.text == "function":
                        self.i -= 1
                        return
                elif t.kind == TokenKind.IDENT:
                    nxt = self.peek()
                    if (nxt.kind == TokenKind.SYMBOL and nxt.text in _ASSIGN_OPS
                            and paren_depth == 0):
                        self.result.references.append(Reference(t.text, self.rng(t), "driver"))
                    else:
                        self.result.references.append(Reference(t.text, self.rng(t), "usage"))
                elif t.kind == TokenKind.SYMBOL:
                    if t.text == "(":
                        paren_depth += 1
                    elif t.text == ")":
                        paren_depth = max(0, paren_depth - 1)
                elif t.kind == TokenKind.DIRECTIVE:
                    self.i -= 1
                    self.parse_directive()
        else:
            # 单语句
            paren_depth = 0
            while self.peek().kind != TokenKind.EOF and not self.at_symbol(";"):
                t = self.next()
                if t.kind == TokenKind.IDENT:
                    nxt = self.peek()
                    if (nxt.kind == TokenKind.SYMBOL and nxt.text in _ASSIGN_OPS
                            and paren_depth == 0):
                        self.result.references.append(Reference(t.text, self.rng(t), "driver"))
                    else:
                        self.result.references.append(Reference(t.text, self.rng(t), "usage"))
                elif t.kind == TokenKind.SYMBOL:
                    if t.text == "(":
                        paren_depth += 1
                    elif t.text == ")":
                        paren_depth = max(0, paren_depth - 1)
            if self.at_symbol(";"):
                self.next()

    def _parse_function(self, mod: ModuleInfo):
        kw = self.next()  # function / task
        # 跳过返回类型/自动性
        while self.peek().kind == TokenKind.KEYWORD and self.peek().text in _MOD_WORDS | _BUILTIN_TYPE_WORDS | _DECL_TYPE_WORDS:
            self.next()
        if self.at_symbol("["):
            self._skip_brackets()
        t = self.peek()
        # v6.0.1: 部分代码用 Verilog 关键字作 task/function 名（如 PicoRV32 的 task expect;）
        # 此时 expect 被词法器标为 KEYWORD，需也接受作为函数名
        if t.kind == TokenKind.IDENT or (t.kind == TokenKind.KEYWORD and t.text not in ("endfunction", "endtask")):
            name_tok = self.next()
            end_kw = "endfunction" if kw.text == "function" else "endtask"
            end_tok = name_tok
            # 扫到 endfunction/endtask
            depth = 0
            guard = 0
            while self.peek().kind != TokenKind.EOF and guard < 50000:
                guard += 1
                tk = self.next()
                if tk.kind == TokenKind.KEYWORD and tk.text in ("function", "task"):
                    depth += 1
                elif tk.kind == TokenKind.KEYWORD and tk.text in ("endfunction", "endtask"):
                    if depth == 0:
                        end_tok = tk
                        break
                    depth -= 1
                elif tk.kind == TokenKind.IDENT:
                    self.result.references.append(Reference(tk.text, self.rng(tk), "usage"))
            sym = Symbol(name=name_tok.text, kind="function" if kw.text == "function" else "task",
                         range=self.rng2(kw, end_tok), name_range=self.rng(name_tok),
                         detail=kw.text, parent=mod.name)
            mod.functions.append(sym)
            self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))

    def _try_parse_instance(self, mod: ModuleInfo) -> bool:
        """尝试解析模块例化：Type [#(...)] name [(...)] ;
        识别策略（保守）：IDENT 后跟 [ #( ... ) ] IDENT ( 形式。
        """
        start_i = self.i
        type_tok = self.peek()
        if type_tok.kind != TokenKind.IDENT:
            return False
        j = self.i + 1

        def tok(k: int) -> Token:
            idx = min(k, len(self.tokens) - 1)
            return self.tokens[idx]

        # 参数覆盖 #(...)
        if tok(j).kind == TokenKind.SYMBOL and tok(j).text == "#":
            j += 1
            if tok(j).kind == TokenKind.SYMBOL and tok(j).text == "(":
                depth = 0
                while j < len(self.tokens) - 1:
                    if tok(j).text == "(":
                        depth += 1
                    elif tok(j).text == ")":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
        # 实例名
        name_tok = tok(j)
        if name_tok.kind != TokenKind.IDENT:
            return False
        # 数组维度
        k = j + 1
        if tok(k).kind == TokenKind.SYMBOL and tok(k).text == "[":
            depth = 0
            while k < len(self.tokens) - 1:
                if tok(k).text == "[":
                    depth += 1
                elif tok(k).text == "]":
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
        # 左括号
        if not (tok(k).kind == TokenKind.SYMBOL and tok(k).text == "("):
            return False

        # 确认是例化：推进 main index 并解析连接
        self.next()  # type
        while self.i < j:
            self.next()  # 参数覆盖部分
        self.next()  # 实例名
        while self.i < k:
            self.next()  # 数组维度
        # 解析端口连接
        connections: List[PortConnection] = []
        self.next()  # (
        while self.peek().kind != TokenKind.EOF and not self.at_symbol(")"):
            if self.at_symbol("."):
                self.next()
                pn = self.peek()
                if pn.kind == TokenKind.IDENT:
                    self.next()
                    pname = pn.text
                    self.result.references.append(Reference(pname, self.rng(pn), "port_connection"))
                    if self.at_symbol("("):
                        self.next()
                        parts: List[str] = []
                        depth = 0
                        first = self.peek()
                        while self.peek().kind != TokenKind.EOF:
                            if depth == 0 and self.at_symbol(")"):
                                break
                            if self.at_symbol("(", "["):
                                depth += 1
                            elif self.at_symbol(")", "]"):
                                depth -= 1
                            tt = self.next()
                            parts.append(tt.text)
                            if tt.kind == TokenKind.IDENT:
                                self.result.references.append(Reference(tt.text, self.rng(tt), "usage"))
                        last = self.peek()
                        if self.at_symbol(")"):
                            self.next()
                        connections.append(PortConnection(
                            port_name=pname, signal_text=" ".join(parts),
                            range=self.rng2(first, last)))
                    else:
                        # SystemVerilog 隐式命名连接：.rst_ni 等价 .rst_ni(rst_ni)
                        connections.append(PortConnection(
                            port_name=pname, signal_text=pname, range=self.rng(pn)))
                elif pn.kind == TokenKind.SYMBOL and pn.text == "*":
                    # SystemVerilog 通配连接 .*（隐式连接全部同名端口，静态无法逐一核对）
                    self.next()
                    connections.append(PortConnection(
                        port_name="*", signal_text="*", range=self.rng(pn)))
                else:
                    self.next()
            else:
                # 位置连接
                first = self.peek()
                parts: List[str] = []
                depth = 0
                while self.peek().kind != TokenKind.EOF:
                    if depth == 0 and (self.at_symbol(",") or self.at_symbol(")")):
                        break
                    if self.at_symbol("(", "["):
                        depth += 1
                    elif self.at_symbol(")", "]"):
                        depth -= 1
                    tt = self.next()
                    parts.append(tt.text)
                    if tt.kind == TokenKind.IDENT:
                        self.result.references.append(Reference(tt.text, self.rng(tt), "usage"))
                if parts:
                    connections.append(PortConnection(
                        port_name="", signal_text=" ".join(parts),
                        range=self.rng2(first, self.peek(-1))))
            if self.at_symbol(","):
                self.next()
        if self.at_symbol(")"):
            self.next()
        if self.at_symbol(";"):
            self.next()

        inst = Instance(module_type=type_tok.text, inst_name=name_tok.text,
                        range=self.rng2(type_tok, self.peek(-1)),
                        name_range=self.rng(name_tok), type_range=self.rng(type_tok),
                        parent=mod.name, connections=connections)
        mod.instances.append(inst)
        self.result.references.append(Reference(type_tok.text, self.rng(type_tok), "instantiation"))
        self.result.references.append(Reference(name_tok.text, self.rng(name_tok), "declaration"))
        return True


def parse(text: str) -> ParseResult:
    return Parser(text).parse()
