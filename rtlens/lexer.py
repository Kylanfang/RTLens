"""Verilog/SystemVerilog 词法分析器（零依赖，纯 stdlib）。

产出带行列位置的 Token 流，供 parser / indexer / diagnostics 使用。
设计目标：
- 容忍语法错误（LSP 场景下文件经常处于编辑中间态）
- 保留注释与编译指令位置信息
- Windows / Linux / macOS 换行符均兼容（\\r\\n / \\n / \\r）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


class TokenKind(Enum):
    IDENT = auto()        # 标识符
    NUMBER = auto()       # 数字（含 4'b1010 / 32'hFF / 1.5 等）
    STRING = auto()       # 字符串字面量
    KEYWORD = auto()      # 关键字
    SYMBOL = auto()       # 符号/运算符
    DIRECTIVE = auto()    # `define `include `ifdef 等编译指令
    COMMENT_LINE = auto()   # // 注释
    COMMENT_BLOCK = auto()  # /* */ 注释
    EOF = auto()


KEYWORDS = frozenset("""
module endmodule macromodule
input output inout ref
wire tri tri0 tri1 trireg wand wor
reg logic bit
integer real realtime time shortreal
genvar parameter localparam specparam
assign deassign defparam
always always_ff always_comb always_latch initial final
begin end fork join join_any join_none
if else case casex casez endcase default
for forever repeat while do
function endfunction task endtask return
generate endgenerate
posedge negedge edge
or and nand nor xor xnor not buf bufif0 bufif1 notif0 notif1
pullup pulldown
signed unsigned
supply0 supply1
typedef enum struct union packed
interface endinterface modport clocking endclocking
package endpackage import export
program endprogram
class endclass extends implements virtual pure this super new
automatic static const var type
void int shortint longint byte chandle string event
covergroup endgroup coverpoint cross bins binsof illegal_bins ignore_bins
property endproperty sequence endsequence
assert assume cover restrict expect
unique unique0 priority
inside dist
break continue
wait wait_order
disable
alias
bind
checker endchecker
config endconfig
primitive endprimitive table endtable
specify endspecify
use liblist
rand randc randsequence
solve before
constraint
soft
forever
accept_on reject_on sync_accept_on sync_reject_on
s_always s_eventually s_nexttime s_until s_until_with
global
let
matches tagged
strong weak
implies iff
first_match throughout within intersect
untyped
wildcard
with
""".split())

# 多字符运算符（按长度从长到短匹配）
MULTI_SYMBOLS = [
    ">>>=", "<<<=", ">>>", "<<<", "**",
    "==?", "!=?", "===", "!==", "==", "!=", "<=", ">=", "&&", "||",
    "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    ">>=", "<<=", ">>", "<<", "->", "=>", "->>", "|->", "|=>", "#-", "##",
    "->>",
    "::", "':", ".'",
]


@dataclass
class Token:
    kind: TokenKind
    text: str
    line: int       # 0-based
    col: int        # 0-based（字符偏移）
    end_line: int = 0
    end_col: int = 0

    def __post_init__(self):
        if self.end_line == 0 and self.end_col == 0:
            self.end_line = self.line
            self.end_col = self.col + len(self.text)

    def contains(self, line: int, col: int) -> bool:
        if line < self.line or line > self.end_line:
            return False
        if line == self.line and col < self.col:
            return False
        if line == self.end_line and col >= self.end_col:
            return False
        return True

    def __repr__(self):
        return f"Token({self.kind.name}, {self.text!r}, {self.line}:{self.col})"


@dataclass
class LexResult:
    tokens: List[Token] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_" or c == "$"


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c in "_$"


# 多字符符号按长度从长到短预排序，供主循环匹配使用。
# 关键优化：原先在 while 主循环内每字符都 sorted() 一次，
# 12MB 文件退化成 O(n·m·log m)。提到模块级只排一次，结果等价。
MULTI_SYMBOLS_SORTED = sorted(MULTI_SYMBOLS, key=len, reverse=True)


def lex(text: str) -> LexResult:
    """将源码切分为 Token 流。任何异常输入都不会抛错——错误记入 LexResult.errors。"""
    result = LexResult()
    tokens = result.tokens
    n = len(text)
    i = 0
    line = 0
    col = 0

    def advance(k: int = 1):
        nonlocal i, line, col
        for _ in range(k):
            if i < n:
                if text[i] == "\n":
                    line += 1
                    col = 0
                else:
                    col += 1
                i += 1

    while i < n:
        c = text[i]

        # 空白
        if c in " \t\r\n":
            advance()
            continue

        start_line, start_col = line, col

        # 行注释
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = i
            while j < n and text[j] != "\n":
                j += 1
            tok_text = text[i:j]
            tokens.append(Token(TokenKind.COMMENT_LINE, tok_text, start_line, start_col, start_line, start_col + len(tok_text)))
            advance(j - i)
            continue

        # 块注释
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = i + 2
            while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                j += 1
            j = min(j + 2, n)
            tok_text = text[i:j]
            end_l = start_line + tok_text.count("\n")
            if "\n" in tok_text:
                end_c = len(tok_text) - tok_text.rfind("\n") - 1
            else:
                end_c = start_col + len(tok_text)
            tokens.append(Token(TokenKind.COMMENT_BLOCK, tok_text, start_line, start_col, end_l, end_c))
            advance(j - i)
            continue

        # 编译指令 `xxx（到行尾为一个 token 的头部，只取指令名）
        if c == "`":
            j = i + 1
            while j < n and _is_ident_char(text[j]):
                j += 1
            name = text[i:j]
            tokens.append(Token(TokenKind.DIRECTIVE, name, start_line, start_col, start_line, start_col + len(name)))
            advance(j - i)
            continue

        # 字符串
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"' or text[j] == "\n":
                    break
                j += 1
            j = min(j + 1, n)
            tok_text = text[i:j]
            tokens.append(Token(TokenKind.STRING, tok_text, start_line, start_col, start_line, start_col + len(tok_text)))
            advance(j - i)
            continue

        # 数字：含 sized literal（如 8'hFF）、小数、科学计数
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            # 形如 4'b1010：先匹配 size
            while j < n and (text[j].isalnum() or text[j] in "_'?xXzZ"):
                j += 1
            if j < n and text[j] == "." and j + 1 < n and text[j + 1].isdigit():
                j += 1
                while j < n and (text[j].isdigit() or text[j] == "_"):
                    j += 1
            # 科学计数
            if j < n and text[j] in "eE" and j + 1 < n and (text[j + 1].isdigit() or (text[j + 1] in "+-" and j + 2 < n and text[j + 2].isdigit())):
                j += 2
                while j < n and (text[j].isdigit() or text[j] == "_"):
                    j += 1
            tok_text = text[i:j]
            tokens.append(Token(TokenKind.NUMBER, tok_text, start_line, start_col, start_line, start_col + len(tok_text)))
            advance(j - i)
            continue

        # 标识符 / 关键字
        if _is_ident_start(c):
            j = i
            while j < n and _is_ident_char(text[j]):
                j += 1
            word = text[i:j]
            kind = TokenKind.KEYWORD if word in KEYWORDS else TokenKind.IDENT
            tokens.append(Token(kind, word, start_line, start_col, start_line, start_col + len(word)))
            advance(j - i)
            continue

        # 转义标识符 \xxx （以空白结尾）
        if c == "\\":
            j = i + 1
            while j < n and text[j] not in " \t\r\n":
                j += 1
            tok_text = text[i:j]
            tokens.append(Token(TokenKind.IDENT, tok_text, start_line, start_col, start_line, start_col + len(tok_text)))
            advance(j - i)
            continue

        # 多字符符号
        matched = False
        for sym in MULTI_SYMBOLS_SORTED:
            if text.startswith(sym, i):
                tokens.append(Token(TokenKind.SYMBOL, sym, start_line, start_col, start_line, start_col + len(sym)))
                advance(len(sym))
                matched = True
                break
        if matched:
            continue

        # 单字符符号
        tokens.append(Token(TokenKind.SYMBOL, c, start_line, start_col, start_line, start_col + 1))
        advance()

    tokens.append(Token(TokenKind.EOF, "", line, col, line, col))
    return result


def strip_comments(tokens: List[Token]) -> List[Token]:
    return [t for t in tokens if t.kind not in (TokenKind.COMMENT_LINE, TokenKind.COMMENT_BLOCK)]
