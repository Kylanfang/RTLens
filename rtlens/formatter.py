"""代码格式化：基本缩进 + 端口对齐 + begin/end 对齐。

不做激进重排，只做安全可预测的格式化（不改变语义）。
"""

from __future__ import annotations

import re


def format_verilog(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    indent = 0
    in_module = False
    in_always = False
    in_begin = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue

        # 减少缩进的关键字
        if re.match(r"^\s*(endmodule|endcase|endfunction|endtask|endgenerate|end|endinterface|endpackage|endclocking)", stripped, re.I):
            indent = max(0, indent - 1)
        elif re.match(r"^\s*(else|endcase|default)", stripped, re.I) and in_begin == 0:
            pass  # 保持

        # 输出
        out.append("    " * indent + stripped)

        # 增加缩进的关键字
        if re.match(r"^\s*(module|package|interface|clocking|function|task|generate|case|casex|casez)\b", stripped, re.I):
            indent += 1
            in_module = True
        elif re.match(r"^\s*(begin)\b", stripped, re.I):
            in_begin += 1
            indent += 1
        elif re.match(r"^\s*(always|always_ff|always_comb|always_latch|initial|final)\b", stripped, re.I):
            in_always = True
        elif re.match(r"^\s*(if|else|for|while|repeat|forever|do)\b", stripped, re.I) and not stripped.endswith(";"):
            indent += 1
        elif re.match(r"^\s*(end)\b", stripped, re.I):
            in_begin = max(0, in_begin - 1)
            indent = max(0, indent - 1)

    # 空行折叠：最多连续 1 个空行
    result: list[str] = []
    prev_blank = False
    for line in out:
        if not line.strip():
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        result.append(line)
    # 去尾部空白
    result = [r.rstrip() for r in result]
    return "\n".join(result) + "\n"
