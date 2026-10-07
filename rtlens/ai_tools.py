"""AI 工具模块：模板生成 / 信号追踪 / 设计度量 / 端口检查 / 语义搜索。

这是 v3.0 的核心——让 AI agent（如 Codex）无需 grep 即可获取结构化的设计信息。
所有方法基于索引器内存中的符号表，查询复杂度 O(1) ~ O(n)，无文件 I/O。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from .indexer import WorkspaceIndex


class AITools:
    """AI agent 调用的工具集，所有方法操作 WorkspaceIndex 的内存索引。"""

    def __init__(self, index: WorkspaceIndex):
        self.index = index

    # ---- 1. 设计总览 ----

    def analyze_design(self) -> Dict[str, Any]:
        """全设计总览：模块列表 / 层级 / 依赖图 / 复杂度。

        替代 `grep -r "module" *.v` —— 一次调用拿到全部结构化信息。
        """
        stats = self.index.stats
        modules = []
        for name, locs in sorted(self.index._module_defs.items()):
            mod = self.index.get_module(name)
            if not mod:
                continue
            ports = len(mod.ports)
            inst_count = len(mod.instances)
            who_insts = self.index.who_instantiates(name)
            is_top = len(who_insts) == 0
            modules.append({
                "name": name,
                "file": locs[0].file,
                "ports": ports,
                "params": len(mod.params),
                "instances": inst_count,
                "instantiated_by": [s.container for s in who_insts],
                "is_top_module": is_top,
                "line": mod.range.start_line,
            })
        # 找顶层模块
        top_modules = [m["name"] for m in modules if m["is_top_module"]]
        return {
            "summary": {
                "files": stats.files,
                "modules": stats.modules,
                "ports": stats.ports,
                "signals": stats.signals,
                "instances": stats.instances,
                "top_modules": top_modules,
            },
            "modules": modules,
        }

    # ---- 2. 模块详情（AI 版，比 LSP get_module 更丰富）----

    def get_module_info(self, name: str) -> Optional[Dict[str, Any]]:
        """模块完整情报：端口 / 参数 / 信号 / 实例 / 被谁例化 / 依赖谁。

        替代 AI agent 需要多次 grep 才能拼凑出的模块全貌。
        """
        mod = self.index.get_module(name)
        if not mod:
            return None
        who_insts = self.index.who_instantiates(name)
        deps = []
        for inst in mod.instances:
            if inst.module_type not in deps:
                deps.append(inst.module_type)
        return {
            "name": mod.name,
            "ports": [{
                "name": p.name, "direction": p.direction,
                "width": p.width, "type": p.data_type,
                "detail": p.detail,
            } for p in mod.ports],
            "params": [{
                "name": p.name, "detail": p.detail,
            } for p in mod.params],
            "signals": [{"name": s.name, "detail": s.detail} for s in mod.signals],
            "instances": [{
                "name": inst.inst_name, "type": inst.module_type,
                "named_connection": all(c.port_name for c in inst.connections),
                "connections": [{
                    "port": c.port_name or f"(positional {i})",
                    "signal": c.signal_text,
                } for i, c in enumerate(inst.connections)],
            } for inst in mod.instances],
            "dependencies": deps,
            "instantiated_by": [{"module": s.container, "file": s.file} for s in who_insts],
            "is_top_module": len(who_insts) == 0,
        }

    # ---- 3. 实例化模板生成 ----

    def generate_instantiation(self, module_name: str, inst_name: str = "u_inst") -> str:
        """生成模块实例化代码模板。

        替代 AI agent 手写实例化代码时需要反复 grep 端口列表。
        """
        mod = self.index.get_module(module_name)
        if not mod:
            # 检查是否是原语
            if module_name in self.index._elinx and self.index._elinx.stub_modules:
                pass
            return f"// module '{module_name}' not found in index"
        lines = []
        # 参数（只覆盖 parameter，不覆盖 localparam）
        real_params = [p for p in mod.params if not p.detail.startswith("localparam")]
        if real_params:
            lines.append(f"    #(")
            for i, p in enumerate(real_params):
                val = p.detail.split("= ")[1] if "= " in p.detail else ""
                comma = "," if i < len(real_params) - 1 else ""
                lines.append(f"        .{p.name}({val}){comma}  // {p.detail}")
            lines.append(f"    )")
        lines.append(f"    {inst_name} (")
        for i, p in enumerate(mod.ports):
            comma = "," if i < len(mod.ports) - 1 else ""
            # 生成默认连接名：端口名小写 + _i/_o 后缀
            default = p.name
            if p.direction == "input":
                default = p.name + "_i"
            elif p.direction == "output":
                default = p.name + "_o"
            elif p.direction == "inout":
                default = p.name + "_io"
            lines.append(f"        .{p.name}({default}){comma}  // {p.detail}")
        lines.append(f"    );")
        header = f"    {module_name}"
        return header + "\n" + "\n".join(lines)

    # ---- 4. Testbench 模板生成 ----

    def generate_testbench(self, module_name: str) -> str:
        """生成 testbench 骨架代码。

        替代 AI agent 从零写 testbench 时需要 grep 模块端口。
        """
        mod = self.index.get_module(module_name)
        if not mod:
            return f"// module '{module_name}' not found in index"
        lines = []
        lines.append(f"`timescale 1ns / 1ps")
        lines.append(f"")
        lines.append(f"module tb_{module_name};")
        lines.append(f"")
        # 声明信号：DUT 输入→reg（TB 驱动），DUT 输出→wire（TB 监视）
        for p in mod.ports:
            w = p.width.strip() if p.width else ""
            width = f"{w} " if w and w.startswith("[") else (f"[{w}] " if w else "")
            if p.direction == "input":
                lines.append(f"    reg {width}{p.name}_i;")
            elif p.direction == "output":
                lines.append(f"    wire {width}{p.name}_o;")
            elif p.direction == "inout":
                lines.append(f"    wire {width}{p.name}_io;")
        lines.append(f"")
        # 实例化 DUT（只覆盖 parameter，不覆盖 localparam）
        lines.append(f"    // DUT")
        real_params = [p for p in mod.params if not p.detail.startswith("localparam")]
        if real_params:
            lines.append(f"    {module_name} #(")
            for i, p in enumerate(real_params):
                comma = "," if i < len(real_params) - 1 else ""
                val = p.detail.split("= ")[1] if "= " in p.detail else ""
                lines.append(f"        .{p.name}({val}){comma}")
            lines.append(f"    ) u_dut (")
        else:
            lines.append(f"    {module_name} u_dut (")
        for i, p in enumerate(mod.ports):
            comma = "," if i < len(mod.ports) - 1 else ""
            suffix = "_i" if p.direction == "input" else ("_o" if p.direction == "output" else "_io")
            lines.append(f"        .{p.name}({p.name}{suffix}){comma}")
        lines.append(f"    );")
        lines.append(f"")
        # 时钟生成（如果有 clk）
        has_clk = any(p.name in ("clk", "clock", "CLK") for p in mod.ports)
        if has_clk:
            clk_name = "clk" if any(p.name == "clk" for p in mod.ports) else "clock"
            lines.append(f"    // Clock generation")
            lines.append(f"    initial {clk_name}_i = 0;")
            lines.append(f"    always #5 {clk_name}_i = ~{clk_name}_i;")
            lines.append(f"")
        # 测试序列
        lines.append(f"    // Test sequence")
        lines.append(f"    initial begin")
        lines.append(f"        // Initialize")
        for p in mod.ports:
            if p.direction == "input":
                lines.append(f"        {p.name}_i = 0;")
        lines.append(f"")
        if has_clk:
            lines.append(f"        // Wait for reset")
            lines.append(f"        #20;")
        lines.append(f"")
        lines.append(f"        // TODO: Add test cases here")
        lines.append(f"")
        lines.append(f"        // Finish")
        lines.append(f"        $finish;")
        lines.append(f"    end")
        lines.append(f"")
        lines.append(f"endmodule")
        return "\n".join(lines)

    # ---- 5. 信号追踪 ----

    def trace_signal(self, signal_name: str, file: str = "", limit: int = 0) -> Dict[str, Any]:
        """追踪信号：从驱动源到所有使用点。

        替代 AI agent 多次 grep 追踪信号流向。
        limit>0 时对 drivers/usages 各截断到 limit 条并置 truncated 标志
        （全局信号如 clk/rst_n 在大型设计中引用可达数千条，全量返回浪费 token）。
        """
        drivers = []
        usages = []
        for ref in self.index._all_refs.get(signal_name, []):
            entry = {
                "file": ref.file,
                "line": ref.range.start_line,
                "col": ref.range.start_col,
                "context": ref.context,
            }
            if ref.context == "driver":
                drivers.append(entry)
            elif ref.context == "usage":
                usages.append(entry)
            elif ref.context == "declaration":
                pass  # skip declarations
            else:
                usages.append(entry)

        # 如果指定了文件，过滤（路径规范化，兼容 / 与 \ 分隔符）
        if file:
            import os as _os
            file = _os.path.normpath(file)
            drivers = [d for d in drivers if d["file"] == file]
            usages = [u for u in usages if u["file"] == file]

        truncated = False
        if limit and limit > 0:
            if len(drivers) > limit:
                drivers = drivers[:limit]
                truncated = True
            if len(usages) > limit:
                usages = usages[:limit]
                truncated = True

        return {
            "signal": signal_name,
            "drivers": drivers,
            "usages": usages,
            "driver_count": len(drivers),
            "usage_count": len(usages),
            "truncated": truncated,
        }

    # ---- 6. 设计度量 ----

    def get_design_metrics(self) -> Dict[str, Any]:
        """设计复杂度度量：模块数 / 层级深度 / 扇入扇出 / 端口密度。"""
        stats = self.index.stats
        module_metrics = []
        max_depth = 0
        total_fanout = 0
        for name in sorted(self.index._module_defs.keys()):
            mod = self.index.get_module(name)
            if not mod:
                continue
            fan_in = len(self.index.who_instantiates(name))
            fan_out = len(mod.instances)
            total_fanout += fan_out
            port_density = len(mod.ports) / max(1, (mod.range.end_line - mod.range.start_line))
            # 层级深度（递归向上找）
            depth = self._calc_depth(name, set())
            max_depth = max(max_depth, depth)
            module_metrics.append({
                "name": name,
                "fan_in": fan_in,
                "fan_out": fan_out,
                "ports": len(mod.ports),
                "lines": mod.range.end_line - mod.range.start_line,
                "port_density": round(port_density, 2),
                "hierarchy_depth": depth,
            })
        return {
            "overall": {
                "files": stats.files,
                "modules": stats.modules,
                "total_instances": stats.instances,
                "total_ports": stats.ports,
                "max_hierarchy_depth": max_depth,
                "avg_fanout": round(total_fanout / max(1, stats.modules), 2),
            },
            "modules": module_metrics,
        }

    def _calc_depth(self, module_name: str, visited: set) -> int:
        """递归计算模块在例化树中的深度（0=顶层）。"""
        if module_name in visited:
            return 0
        visited.add(module_name)
        parents = self.index.who_instantiates(module_name)
        if not parents:
            return 0
        return 1 + max(self._calc_depth(p.container, visited) for p in parents)

    # ---- 7. 端口连接检查 ----

    def _module_port_sets(self, name: str) -> List[set]:
        """收集该模块名**所有**定义的端口名集合。

        同名多定义（仿真模型 vs RTL、vendored 库副本）时 get_module 只取第一份，
        逐份收集后由调用方按"所有定义都算缺才报缺 / 全部定义都没有才报多"的策略核对。
        """
        sets: List[set] = []
        for loc in self.index._module_defs.get(name, []):
            fidx = self.index._files.get(loc.file)
            if not fidx:
                continue
            for m in fidx.result.modules:
                if m.name == name:
                    sets.append({p.name for p in m.ports})
        return sets

    def check_port_mismatches(self) -> List[Dict[str, Any]]:
        """检查所有实例化的端口连接是否匹配模块定义。

        v6.1.2:
        - 多定义模块：缺失取各定义交集、多余对并集核对（连接对任一定义合法即不报）
        - 每条 issue 带 severity：extra_port/port_count_mismatch=error（编译不过），
          missing_port=warning（合法悬空），definition_parse_suspect=info（解析存疑）
        """
        issues = []
        for name in self.index._module_defs:
            port_sets = self._module_port_sets(name)
            if not port_sets:
                continue
            union_ports = set().union(*port_sets)
            max_defined = max(len(s) for s in port_sets)
            n_defs = len(port_sets)
            # 找所有实例化此模块的地方
            for inst_file_key, fidx in self.index._files.items():
                for file_mod in fidx.result.modules:
                    for inst in file_mod.instances:
                        if inst.module_type != name:
                            continue
                        base: Dict[str, Any] = {
                            "module": name,
                            "instance": inst.inst_name,
                            "file": inst_file_key,
                            "line": inst.range.start_line,
                        }
                        if n_defs > 1:
                            base["definitions"] = n_defs
                        named_ports = {c.port_name for c in inst.connections if c.port_name}
                        # SystemVerilog .* 通配连接：无法静态逐一核对，跳过
                        if "*" in named_ports:
                            continue
                        # 定义解析存疑守卫：实例连接的未知端口数超过最大定义的端口总数，
                        # 说明模块定义的端口列表大概率解析不完整（前沿 SV 语法），
                        # 报单条 suspect 提示而不是几十条逐端口误报
                        unknown_conn = named_ports - union_ports
                        if named_ports and len(unknown_conn) > max(4, max_defined):
                            issues.append({
                                **base,
                                "type": "definition_parse_suspect",
                                "severity": "info",
                                "defined_port_count": max_defined,
                                "connected_port_count": len(named_ports),
                                "hint": "模块定义端口数远少于实例连接数——定义可能含未支持的 "
                                        "SystemVerilog 语法而解析不完整；逐端口 mismatch 已抑制，"
                                        "建议启用 verible 后端或人工核对定义",
                            })
                            continue
                        # 缺失端口：对每一份定义都缺才报（只检查命名连接）
                        if named_ports:
                            missing = set.intersection(*[(s - named_ports) for s in port_sets])
                            if missing:
                                issues.append({
                                    **base,
                                    "type": "missing_port",
                                    "severity": "warning",
                                    "missing_ports": sorted(missing),
                                })
                        # 多余端口：任何一份定义都没有这个端口才报
                        extra = named_ports - union_ports
                        if extra:
                            issues.append({
                                **base,
                                "type": "extra_port",
                                "severity": "error",
                                "extra_ports": sorted(extra),
                            })
                        # 端口数量不匹配（位置连接）：与任一定义的数量匹配即可
                        if not named_ports and inst.connections:
                            if not any(len(inst.connections) == len(s) for s in port_sets):
                                issues.append({
                                    **base,
                                    "type": "port_count_mismatch",
                                    "severity": "error",
                                    "expected": (sorted(len(s) for s in port_sets)
                                                 if n_defs > 1 else len(port_sets[0])),
                                    "actual": len(inst.connections),
                                })
        return issues

    # ---- 8. 语义搜索 ----

    def search_code(self, query: str, kind: str = "") -> List[Dict[str, Any]]:
        """语义搜索：按名称模糊匹配符号（不用 grep，走索引）。

        kind 可选: module / port / signal / parameter / instance / function / macro / ""
        """
        results = []
        q = query.lower()
        for sym_name, locs in self.index._all_symbols.items():
            if q not in sym_name.lower():
                continue
            for loc in locs:
                if kind and loc.kind != kind:
                    continue
                results.append({
                    "name": loc.name,
                    "kind": loc.kind,
                    "file": loc.file,
                    "line": loc.range.start_line,
                    "detail": loc.detail,
                    "container": loc.container,
                })
        # 也搜宏
        for mname, mloc in self.index._macros.items():
            if q not in mname.lower():
                continue
            if kind and kind != "macro":
                continue
            results.append({
                "name": mloc.name,
                "kind": "macro",
                "file": mloc.file,
                "line": mloc.range.start_line,
                "detail": mloc.detail,
            })
        return results

    # ---- 9. AI 上下文提取 ----

    def get_context_for_ai(self, file: str = "", module: str = "") -> str:
        """提取结构化上下文，供 AI agent 理解代码库。

        生成一段紧凑的文本摘要，包含模块端口/参数/实例/依赖关系——
        AI agent 读完这一段就能理解设计结构，无需 grep。
        """
        lines = []
        lines.append("=== Verilog Design Context (auto-generated by RTLens) ===")
        lines.append("")

        if module:
            info = self.get_module_info(module)
            if not info:
                return f"module '{module}' not found"
            lines.append(f"Module: {module}")
            lines.append(f"  Top module: {'yes' if info['is_top_module'] else 'no'}")
            lines.append(f"  Ports ({len(info['ports'])}):")
            for p in info["ports"]:
                lines.append(f"    {p['direction']:6s} {p['width']:8s} {p['name']}  // {p['detail']}")
            if info["params"]:
                lines.append(f"  Parameters ({len(info['params'])}):")
                for p in info["params"]:
                    lines.append(f"    {p['name']}  // {p['detail']}")
            if info["signals"]:
                lines.append(f"  Internal signals ({len(info['signals'])}):")
                for s in info["signals"]:
                    lines.append(f"    {s['name']}  // {s['detail']}")
            if info["instances"]:
                lines.append(f"  Sub-modules ({len(info['instances'])}):")
                for inst in info["instances"]:
                    lines.append(f"    {inst['type']} {inst['name']}")
            if info["instantiated_by"]:
                lines.append(f"  Instantiated by:")
                for p in info["instantiated_by"]:
                    lines.append(f"    {p['module']} in {p['file']}")
            if info["dependencies"]:
                lines.append(f"  Depends on: {', '.join(info['dependencies'])}")
            return "\n".join(lines)

        # 全设计摘要
        design = self.analyze_design()
        s = design["summary"]
        lines.append(f"Design overview: {s['files']} files, {s['modules']} modules, "
                     f"{s['ports']} ports, {s['instances']} instances")
        if s["top_modules"]:
            lines.append(f"Top module(s): {', '.join(s['top_modules'])}")
        lines.append("")
        lines.append("Modules:")
        for m in design["modules"]:
            lines.append(f"  {m['name']:20s} | {m['ports']}p {m['instances']}i | "
                         f"inst_by={m['instantiated_by']} | {m['file']}")
        return "\n".join(lines)
