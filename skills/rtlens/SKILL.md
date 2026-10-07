---
name: rtlens
description: Evidence-first Verilog/SystemVerilog code intelligence for real RTL projects — index a whole codebase in seconds and answer structural questions with exact file:line citations instead of grep-and-guess. Use when the user asks about module hierarchy, port definitions or port-connection mismatches, signal drivers and usages, who instantiates what, where a symbol is defined or referenced, what testbenches to re-run after changing files, parsing simulation logs (iverilog/verilator/VCS) by module, generating testbench or instantiation skeletons, or summarizing an RTL design for review. Also use before editing unfamiliar Verilog/SV files to ground facts. This skill is the fact/evidence layer only — when the deliverable is a diagram, hand off to hw-topo for RTL/Verilog/SystemVerilog topology diagrams or to archify for non-RTL general architecture diagrams, and do not draw here. Its CLI reports 0-based line numbers while specs handed to hw-topo are 1-based, so any cross-tool citation must state which basis it uses.
license: MIT
metadata:
  version: "6.2.0"
  author: rtlens project
  backend: python (zero dependencies, bundled)
---

# RTLens

A bundled zero-dependency Verilog/SystemVerilog analyzer. It indexes an RTL tree into a symbol database (modules/ports/params/signals/instances/macros with exact 0-based line numbers) and answers structural queries deterministically. **Every answer it prints is transcribed from the index — cite its file:line outputs as evidence instead of recalling module names from memory.**

## Bootstrap

The Python package ships inside this plugin. Locate the CLI root and smoke-test it once per session:

```bash
# PKG_ROOT = the directory containing this skill's package (two levels above this SKILL.md)
cd <PKG_ROOT>            # contains rtlens/ python package + pyproject.toml
python -m rtlens --version   # → rtlens v6.2.0  (needs Python ≥3.8; zero pip installs)
```

If `python` is unavailable or `<3.8`, stop and tell the user instead of guessing syntax by hand.
Optional: Verible binaries (syntax/lint/format) are NOT bundled; all commands below work without them.

## Command cookbook

All commands run with cwd = `<PKG_ROOT>`. `<RTL>` is the user's project root. `-D NAME` (repeatable, `+define+` semantics) is **required when the project guards ports/code with `` `ifdef`` config macros** — index results differ per define set.

```bash
# 1) Index + overview (always first; re-run after any file edit)
python -m rtlens index <RTL> [-D SIM -D W=8]

# 2) One-page design context for AI (ports/params/instances per module)
python -m rtlens context -r <RTL> [-m <module>]

# 3) Symbol lookup: definitions + all references
python -m rtlens query <RTL> <name>

# 4) Port-connection audit (missing/extra/count; severity: error vs warning vs suspect)
python -m rtlens check -r <RTL>

# 5) Signal driver→usage trace (file optional but improves precision)
python -m rtlens trace <signal> -r <RTL> -f <subdir/file.v>

# 6) Design metrics (fan-in/out, hierarchy depth, port density)
python -m rtlens metrics -r <RTL>

# 7) Generate skeletons from REAL port lists
python -m rtlens template testbench <module> -r <RTL>
python -m rtlens template instance   <module> -r <RTL> [-n u_inst]

# 8) Single-file AST dump (fast sanity check on one file)
python -m rtlens parse <file.v>

# 9) Machine-readable evidence pack (the single exit for "the same RTL facts")
python -m rtlens evidence <RTL> [--json] [-o <file>] [-D NAME]
```

**9) `evidence` is the single exit for "the same RTL facts".** 它产出 `rtlens.evidence/1` 契约的机器可读证据包,供 hw-topo 等下游工具消费(本包是**规范版本**,契约全文见 `docs/EVIDENCE_CONTRACT.md`)。`--json` 才把 JSON 打到 stdout,否则输出人类可读摘要;`-o <file>` 落盘;`-D NAME` 与 `index` 同义,参与 `` `ifdef`` 求值(证据包内容随 define 集变化)。下游必须消费这个出口,而不是自己再扫一遍源码;行号请用包内 `line0`/`line1` 双基准字段。

## Workflow

1. **Index before you speak.** Any structural claim about the codebase (module exists, port named X, who drives Y) must come after `index` + the matching query. Never assert a module/port name the CLI did not print.
2. **Read context, then drill.** For "understand/review/modify this design": run `context` first, pick the module of interest, then `query`/`trace` for specifics.
3. **Before editing an instantiation**, run `check -r <RTL>` and quote the relevant issue (or its absence) in your reply.
4. **After editing files**, re-run `index` before further queries — stale-index answers are the main corruption source.
5. **Regression triage**: when the user changed files and asks what to re-run, prefer impact-based reasoning — index, then `query` the changed modules to find who instantiates them upward to testbench roots (names containing tb/test/bench).
6. **Simulation log errors**: paste the log into your analysis by mapping each `file.v:line` hit to the owning module via `query`/`parse` of that file — never attribute errors to a module without checking the line falls inside its range.

## Evidence rules

- Cite `file:line` exactly as the CLI prints (0-based lines, same as the tool's convention; convert to 1-based only when displaying to the user, and say so).
- If a query returns empty, report "not found in index" — do not fall back to guessing from training data.
- Port-check issues carry `severity`: `extra_port`/`port_count_mismatch` = error (will not compile), `missing_port` = warning (legal unconnected), `definition_parse_suspect` = info (definition may be incompletely parsed; verify manually). Repeat the severity when reporting.
- Multi-definition modules (`definitions: N`) mean several same-named definitions exist; a connection is only flagged when it matches **no** definition.
- **证据基准确认(state the basis)。** 引用行号时必须说明是 **0-based**(CLI 原生,即本工具打印的值)还是 **1-based**(人看/编辑器/跨工具)。给用户看时转 1-based 并说明"已转 1-based";跨工具传递证据**一律**用 `evidence` 出口的双基准字段 `line0`/`line1`,**不要自己 ±1**——转换只发生在下游适配器里一次。基准不明的行号不得进入任何交付物。

## Known boundaries (say these out loud when relevant)

- No elaboration: parameter values and widths stay as source text (`[W-1:0]`); RTLens cannot verify width matches. For that, defer to verilator/yosys.
- `` `ifdef`` macros accumulate across files in index order (single compilation unit semantics); pass `-D` to match the intended build configuration.
- Assertion/class/UVM constructs are not modeled; driver/usage classification inside procedural blocks is heuristic (precise on `<=`/`=` at paren depth 0).

## Quick reference: what to reach for

| Question | Command |
|---|---|
| "这个模块有哪些端口/参数？" | `context -m <module>` |
| "这个信号谁驱动的？" | `trace <signal> -f <file>` |
| "这个模块被谁例化？层级？" | `query <RTL> <module>`（看 instantiation 引用） |
| "端口连对了吗？" | `check` |
| "帮我写 testbench/例化" | `template ...`（基于真实端口生成） |
| "改了这个文件要重跑什么？" | 重新 `index` + `query` 改动模块向上追例化链 |
| "把同一份事实给别的工具/出图用" | `evidence <RTL> --json`（`rtlens.evidence/1`，含 `line0`/`line1` 双基准） |
