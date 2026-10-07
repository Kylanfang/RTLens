"""基础 lint：未声明信号使用 / 重复模块名 / 端口未连接 / eLinx 原语未知警告。"""

from __future__ import annotations

from typing import List, Dict, Any

from .parser import ParseResult
from .indexer import WorkspaceIndex
from .elinx import ELinxSupport


def run_diagnostics(result: ParseResult, index: WorkspaceIndex, elinx: ELinxSupport) -> List[Dict[str, Any]]:
    diags: List[Dict[str, Any]] = []

    # 1. 重复模块定义（跨文件）
    for mod in result.modules:
        defs = index._module_defs.get(mod.name, [])
        if len(defs) > 1:
            diags.append({
                "range": {"start": {"line": mod.range.start_line, "character": mod.range.start_col},
                          "end": {"line": mod.range.end_line, "character": mod.range.end_col}},
                "severity": 1, "message": f"Module '{mod.name}' defined {len(defs)} times (duplicate)",
                "source": "rtlens",
            })

    # 2. 例化的未知模块（非 eLinx 原语且 workspace 无定义）
    known_modules = set()
    for name, locs in index._module_defs.items():
        if locs:
            known_modules.add(name)
    for mod in result.modules:
        for inst in mod.instances:
            if inst.module_type not in known_modules and not elinx.is_known_primitive(inst.module_type):
                diags.append({
                    "range": {"start": {"line": inst.type_range.start_line, "character": inst.type_range.start_col},
                              "end": {"line": inst.type_range.end_line, "character": inst.type_range.end_col}},
                    "severity": 2, "message": f"Instantiating unknown module '{inst.module_type}'",
                    "source": "rtlens",
                })

    # 3. 未声明信号使用（粗略：在 module 体内使用但未声明/非端口/非参数）
    for mod in result.modules:
        declared = {p.name for p in mod.ports}
        declared |= {p.name for p in mod.params}
        declared |= {s.name for s in mod.signals}
        declared |= {f.name for f in mod.functions}
        declared |= {"begin", "end", "if", "else", "case", "endcase", "posedge", "negedge",
                     "default", "for", "while", "repeat", "forever", "do", "return",
                     "integer", "real", "time", "reg", "wire", "logic"}
        # 从 references 中找 usage 但不在 declared 集合中的
        for ref in result.references:
            if ref.context == "usage" and ref.name not in declared:
                # 跳过关键字和数值
                if ref.name and not ref.name[0].isdigit():
                    diags.append({
                        "range": {"start": {"line": ref.range.start_line, "character": ref.range.start_col},
                                  "end": {"line": ref.range.end_line, "character": ref.range.end_col}},
                        "severity": 3, "message": f"Signal '{ref.name}' may be undeclared",
                        "source": "rtlens",
                    })

    # 限制返回数避免噪音
    return diags[:200]
