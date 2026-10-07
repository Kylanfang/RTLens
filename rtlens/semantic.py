"""语义 Token 计算 — 参考 rust-analyzer 的 semanticTokens 实现。

LSP 3.16 semanticTokens 提供比传统语法高亮更精确的着色：
  - 区分 type/value/module/port/parameter/macro/keyword
  - 修饰符: declaration/definition/readonly/static

为 Verilog 提供：
  - module名 → type + declaration
  - 端口名 → parameter + declaration
  - 信号名 → variable
  - 关键字 → keyword
  - 编译指令 → macro
  - 数字 → number
  - 注释 → comment
  - 字符串 → string
"""

from __future__ import annotations
from typing import List, Tuple, Dict

from .lexer import lex, TokenKind, KEYWORDS


# LSP SemanticTokenType 枚举（按索引引用）
TOKEN_TYPES = [
    "namespace",   # 0: module/package name in declaration context
    "type",        # 1: module type reference, typedef, enum
    "class",       # 2: class name
    "function",    # 3: function/task name
    "variable",    # 4: signal/wire/reg name
    "parameter",   # 5: parameter/localparam/port
    "keyword",     # 6: Verilog keyword
    "macro",       # 7: compiler directive (`define, `ifdef)
    "number",      # 8: numeric literal
    "string",      # 9: string literal
    "comment",     # 10: comment
    "operator",    # 11: operator
    "enumMember",  # 12: enum value
]

# LSP SemanticTokenModifier 枚举
TOKEN_MODIFIERS = [
    "declaration",    # 0: 声明处
    "definition",     # 1: 定义处
    "readonly",       # 2: parameter/localparam
    "static",         # 3: static method
    "modification",   # 4: 赋值目标
    "documentation",  # 5: 文档注释
]

# 关键字分类
_KEYWORD_TYPES = {
    "module", "endmodule", "program", "endprogram", "package", "endpackage",
    "interface", "endinterface", "generate", "endgenerate", "begin", "end",
    "case", "endcase", "casex", "casez", "if", "else", "for", "while",
    "function", "endfunction", "task", "endtask", "always", "always_ff",
    "always_comb", "always_latch", "initial", "final", "assign", "typedef",
    "enum", "struct", "union", "class", "endclass",
}


def compute_semantic_tokens(text: str, max_tokens: int = 0) -> List[List[int]]:
    """计算文件的语义 token 列表（LSP 相对位置格式）。

    返回 [[deltaLine, deltaStart, length, tokenType, tokenModifiers], ...]
    max_tokens>0 时截断输出并设截断标志（大文件防护，12MB 可产生数百万 token）。
    """
    result = lex(text)
    # 跳过 EOF 和纯空白 token（WS/NEWLINE）——它们对语义高亮无用，
    # 但在 12MB 文件中可能占 token 总量的 30%+，白白撑大输出。
    _skip = {TokenKind.EOF, getattr(TokenKind, 'WS', None), getattr(TokenKind, 'NEWLINE', None)}
    tokens = [t for t in result.tokens if t.kind not in _skip]

    semantic: List[List[int]] = []
    prev_line = 0
    prev_col = 0
    _kw_set = _KEYWORD_TYPES

    for tok in tokens:
        # lexer 的 line/col 本身就是 0-based，与 LSP 约定一致，不做任何换算
        # （历史版本误以为 lexer 是 1-based 而 -1，导致高亮整体上移一行、首 token delta 为负）
        line = tok.line
        col = tok.col
        length = len(tok.text)

        if tok.kind == TokenKind.KEYWORD:
            ttype = 6  # keyword
        elif tok.kind == TokenKind.COMMENT_LINE or tok.kind == TokenKind.COMMENT_BLOCK:
            ttype = 10  # comment
        elif tok.kind == TokenKind.NUMBER:
            ttype = 8  # number
        elif tok.kind == TokenKind.STRING:
            ttype = 9  # string
        elif tok.kind == TokenKind.DIRECTIVE:
            ttype = 7  # macro
        elif tok.kind == TokenKind.IDENT:
            if tok.text.lower() in _kw_set:
                ttype = 6  # keyword
            else:
                ttype = 4  # variable
        elif tok.kind == TokenKind.SYMBOL:
            ttype = 11  # operator
        else:
            continue

        delta_line = line - prev_line
        delta_col = col - prev_col if delta_line == 0 else col

        semantic.append([delta_line, delta_col, length, ttype, 0])
        prev_line = line
        prev_col = col

        if max_tokens > 0 and len(semantic) >= max_tokens:
            break

    return semantic


def compute_folding_ranges(text: str) -> List[Dict]:
    """计算可折叠区域（module/always/begin/end/case/注释块）。"""
    foldings = []
    lines = text.split("\n")
    stack = []  # (start_line, type)

    for i, line in enumerate(lines):
        # 跳过注释行（避免 begin/end 在注释里误匹配）
        stripped_line = line.strip()
        if stripped_line.startswith("//"):
            # 仍然处理块注释结束
            if "*/" in stripped_line and "/*" not in stripped_line:
                _pop_folding(stack, "comment", i, foldings)
            continue
        stripped = stripped_line.lower()

        # 块注释开始
        if "/*" in stripped and "*/" not in stripped:
            stack.append((i, "comment"))

        # module/function/task/always/begin/case 开始
        for kw in ["module", "function", "task", "package", "interface", "class"]:
            if stripped.startswith(kw + " ") or stripped.startswith(kw + "\t"):
                stack.append((i, kw))
                break

        if "begin" in stripped and not stripped.startswith("//"):
            stack.append((i, "block"))

        if stripped.startswith("case") or stripped.startswith("casex") or stripped.startswith("casez"):
            stack.append((i, "case"))

        # 结束匹配
        if "endmodule" in stripped:
            _pop_folding(stack, "module", i, foldings)
        elif "endfunction" in stripped:
            _pop_folding(stack, "function", i, foldings)
        elif "endtask" in stripped:
            _pop_folding(stack, "task", i, foldings)
        elif "endpackage" in stripped:
            _pop_folding(stack, "package", i, foldings)
        elif "endinterface" in stripped:
            _pop_folding(stack, "interface", i, foldings)
        elif "endclass" in stripped:
            _pop_folding(stack, "class", i, foldings)
        elif "endcase" in stripped:
            _pop_folding(stack, "case", i, foldings)
        elif "end" == stripped or stripped.startswith("end "):
            _pop_folding(stack, "block", i, foldings)

        # 块注释结束
        if "*/" in stripped and "/*" not in stripped:
            _pop_folding(stack, "comment", i, foldings)

    return foldings


def _pop_folding(stack, expected_type, end_line, foldings):
    """从栈顶弹出匹配的折叠区域。"""
    for i in range(len(stack) - 1, -1, -1):
        start, kind = stack[i]
        if kind == expected_type:
            foldings.append({
                "startLine": start,
                "endLine": end_line,
                "kind": "comment" if kind == "comment" else "region",
            })
            del stack[i:]
            return


def compute_selection_ranges(text: str, positions: List[Tuple[int, int]]) -> List[List[Dict]]:
    """为光标位置列表计算选择范围（从窄到宽）。

    参考 rust-analyzer: 光标在标识符上时，逐层扩大选择范围：
    identifier → port/signal declaration → module → file
    """
    result = lex(text)
    tokens = [t for t in result.tokens if t.kind != TokenKind.EOF]

    # 找到模块边界（lexer 坐标 0-based，直接使用）
    module_ranges = []
    mod_start = None
    for tok in tokens:
        if tok.kind == TokenKind.KEYWORD and tok.text == "module":
            mod_start = tok.line
        elif tok.kind == TokenKind.KEYWORD and tok.text == "endmodule":
            if mod_start is not None:
                module_ranges.append((mod_start, tok.line))
                mod_start = None

    output = []
    for pos_line, pos_col in positions:
        ranges = []
        # 找光标所在的 token
        for tok in tokens:
            if tok.line == pos_line and tok.col <= pos_col < tok.col + len(tok.text):
                ranges.append({
                    "start": {"line": tok.line, "character": tok.col},
                    "end": {"line": tok.line, "character": tok.col + len(tok.text)},
                })
                break

        # 找光标所在行
        lines = text.split("\n")
        if pos_line < len(lines):
            line_text = lines[pos_line]
            if line_text.strip():
                ranges.append({
                    "start": {"line": pos_line, "character": 0},
                    "end": {"line": pos_line, "character": len(line_text)},
                })

        # 找光标所在模块
        for ms, me in module_ranges:
            if ms <= pos_line <= me:
                ranges.append({
                    "start": {"line": ms, "character": 0},
                    "end": {"line": me, "character": 0},
                })
                break

        # 整个文件
        total_lines = len(lines)
        ranges.append({
            "start": {"line": 0, "character": 0},
            "end": {"line": total_lines - 1, "character": len(lines[-1]) if lines else 0},
        })

        # 构建 parent 链
        parent_chain = []
        for i, r in enumerate(ranges):
            entry = dict(r)
            if i < len(ranges) - 1:
                entry["parent"] = ranges[i + 1]
            parent_chain.append(entry)

        output.append(parent_chain)

    return output


def compute_document_highlights(text: str, name: str) -> List[Dict]:
    """计算文档内高亮（同一个符号在文件内的所有出现位置）。

    返回 [{range: {start, end}, kind: 1|2|3}, ...]
    kind: 1=text(读), 2=read, 3=write
    """
    result = lex(text)
    highlights = []
    for tok in result.tokens:
        if tok.kind == TokenKind.IDENT and tok.text == name:
            # 简单判断：如果前面是 . 则是端口连接（read）
            # 如果在 assign/always 左侧则是 write
            highlights.append({
                "range": {
                    "start": {"line": tok.line, "character": tok.col},
                    "end": {"line": tok.line, "character": tok.col + len(tok.text)},
                },
                "kind": 1,  # text (默认)
            })
    return highlights
