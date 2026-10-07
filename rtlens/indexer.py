"""工作区索引器：跨文件符号表 + 例化图。

- 对一个目录（eLinx 工程）的全部 .v/.sv 文件做索引
- 维护：module 定义表、信号引用表、例化关系图
- 支持 LSP 查询：definition / references / documentSymbol / hover / workspaceSymbol
- 支持 AI 查询：谁例化了 X / X 的层级树 / 信号驱动力
"""

from __future__ import annotations

import os
import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .parser import parse, ParseResult, ModuleInfo, Symbol, Instance, Reference, Range, PortConnection
from .preprocessor import Preprocessor
from .verible_backend import VeribleBackend, find_verible_binary
from .monitor import get_monitor


# v6.0.3: 厂商原语/IP 识别 —— 实战工程（verilog-ethernet/pcie/uart）审计发现：
# 未解析例化类型中绝大部分是 Xilinx / Intel / Lattice 原语或外部 IP 核，
# 与真正的拼写错误混在一起无法区分。这里按命名模式归类，供
# classify_module_type() / list_unresolved_modules() 使用。
import re as _re

VENDOR_PRIMITIVE_PATTERNS = [
    # Xilinx 7-series / UltraScale / UltraScale+ 原语
    _re.compile(r'^(BUFG|BUFGCE|BUFGCE_CTRL|BUFGCTRL|BUFG_GT|BUFG_GT_SYNC|BUFGMUX|BUFR|BUFH|BUFHCE|BUFIO|BUFIO2|BUFIOCE|BUFMRCE)$'),
    _re.compile(r'^(IBUF|IBUFG|IBUFGDS)$'),
    _re.compile(r'^IBUFDS[A-Z0-9_]*$'),
    _re.compile(r'^(OBUF|OBUFT|OBUFTDS|OBUFDS)$'),
    _re.compile(r'^OBUFDS[A-Z0-9_]*$'),
    _re.compile(r'^(IOBUF|IOBUFDS)$'),
    _re.compile(r'^IOBUF[A-Z0-9_]*$'),
    _re.compile(r'^(I|O)DELAY(E?[23])?(_?CTRL)?$'),
    _re.compile(r'^IODELAY[23]?$'),
    _re.compile(r'^(I|O)DDR(DR)?[23]?$'),
    _re.compile(r'^(ISERDES|OSERDES)(E[23])?$'),
    _re.compile(r'^(MMCM|PLL)(E[1-5])?_(BASE|ADV)$'),
    _re.compile(r'^DCM(_SP|_ADV|_BASE)?$'),
    _re.compile(r'^(PLLE[1-4]_(ADV|BASE)|PHY_CONTROL|PHASER_?(IN|OUT|REF)(_CTRL)?)$'),
    _re.compile(r'^(GT[HEPE][1-4]?_(CHANNEL|COMMON)|GTYE4_CHANNEL|GTPE2_CHANNEL)$'),
    _re.compile(r'^(XADC|SYSMON|STARTUPE[23]|BSCANE2|CAPTUREE2|DNA_PORT|EFUSE_USR|FRAME_ECC|ICAP|KEY_CLEAR|USR_ACCESS)$'),
    _re.compile(r'^(PCIE[0-9A-Z]?C?_[A-Z0-9_]*|pcie[0-9][a-z0-9]*_[a-z0-9_]+)$'),      # Xilinx PCIe 硬核 IP
    _re.compile(r'^(GT[HE]_COMMON|IBUFDS_GTE[234]|OBUFDS_GTE[234])$'),
    # Intel/Altera 原语
    _re.compile(r'^(alt_[a-z0-9_]+|altsyncram|altpll|altddio_[a-z]+|altera_[a-z0-9_]+)$'),
    _re.compile(r'^ALT_[A-Z0-9_]+$'),
    _re.compile(r'^(cyclone[0-9a-z_]*|stratix[0-9a-z_]*)$'),
    _re.compile(r'^(fiftyfivenm_[a-z0-9_]+|twentynm_[a-z0-9_]+|arriav[a-z0-9_]*|agilex[0-9a-z_]*)$'),
    # 收发器 PCS/PMA 类 IP 核（Xilinx/Intel 生成名，如 ten_gig_eth_pcs_pma_v2_6）
    _re.compile(r'^[A-Za-z0-9_]*pcs_pma[A-Za-z0-9_]*$'),
    _re.compile(r'^(ten_gig|gig_eth|xl|tri_mode|xxv|aurora|cpri|jesd)[a-z0-9_]*_(v\d+_\d+|\d+)$'),
    # Lattice iCE40 / ECP 原语
    _re.compile(r'^SB_[A-Z0-9_]+$'),
    _re.compile(r'^(EHXPLLL|ECP[0-9A-Z_]*PLL|DP8467A)$'),
    # 开源 ASIC 平台原语库
    _re.compile(r'^prim_[a-z0-9_]+$'),        # lowRISC prim 库（prim_buf/prim_clock_gating/prim_fifo_sync…）
    _re.compile(r'^sky130_[a-z0-9_]+$'),      # SkyWater sky130 PDK 单元（sky130_fd_sc_hd__... 也匹配）
    _re.compile(r'^sky130_fd_[a-z0-9_]+$'),
    _re.compile(r'^techcell_[a-z0-9_]+$'),
]

def is_vendor_primitive(module_type: str) -> bool:
    """判断例化类型名是否是已知的 FPGA 厂商原语 / 硬核 IP。"""
    return any(p.match(module_type) for p in VENDOR_PRIMITIVE_PATTERNS)


@dataclass(slots=True)
class IndexedFile:
    path: str
    text: str          # 原文（未展开）—— LSP 文档同步用
    expanded: str      # 预处理后
    result: ParseResult
    version: int = 0


@dataclass(slots=True)
class SymbolLocation:
    name: str
    kind: str
    file: str
    range: Range
    name_range: Range
    detail: str = ""
    parent: str = ""
    container: str = ""     # module 名


@dataclass(slots=True)
class RefLocation:
    name: str
    file: str
    range: Range
    context: str


@dataclass
class IndexStats:
    files: int = 0
    modules: int = 0
    ports: int = 0
    signals: int = 0
    params: int = 0
    instances: int = 0
    functions: int = 0
    macros: int = 0
    interfaces: int = 0    # v6.0.1
    typedefs: int = 0      # v6.0.1
    packages: int = 0      # v6.0.1


class WorkspaceIndex:
    """线程安全的工作区索引。"""

    def __init__(self, include_paths: Optional[List[str]] = None,
                 verible_executable: Optional[str] = None,
                 defines: Optional[Dict[str, str]] = None):
        """defines: +define+ 语义的内置宏（{"SIM": "1"}），参与 `ifdef 求值与宏展开。"""
        self._lock = threading.RLock()
        self._files: Dict[str, IndexedFile] = {}        # path -> IndexedFile
        self._module_defs: Dict[str, List[SymbolLocation]] = defaultdict(list)
        self._all_symbols: Dict[str, List[SymbolLocation]] = defaultdict(list)  # name -> locations
        self._all_refs: Dict[str, List[RefLocation]] = defaultdict(list)        # name -> refs
        self._instances: Dict[str, List[SymbolLocation]] = defaultdict(list)    # module_type -> instantiation sites
        self._instantiates: Dict[str, List[str]] = defaultdict(list)             # module -> list of child module types
        self._macros: Dict[str, SymbolLocation] = {}
        self._packages: List[SymbolLocation] = []
        self._interfaces: List[SymbolLocation] = []    # v6.0.1
        self._typedefs: List[SymbolLocation] = []      # v6.0.1
        # v4.5: per-file 符号索引 — document_symbols() 从 O(n) 降到 O(1)
        self._file_symbols: Dict[str, List[SymbolLocation]] = defaultdict(list)
        # v4.5: per-file 统计 — _recompute_stats() 从 O(n) 降到 O(files)
        self._file_stats: Dict[str, IndexStats] = {}
        # v5.0: batch mode flag — skip per-file _recompute_stats during bulk indexing
        self._batch_mode = False
        #: 上一次 index_directory() 是否因为 max_files 上限而提前停止。
        #: 为 True 表示"还可能存在未索引的文件"，调用方必须如实披露，
        #: 不能把截断后的索引当成完整证据。
        self.last_index_truncated = False
        # v5.0: content hash cache for incremental reindex (path -> (mtime, hash))
        self._file_cache: Dict[str, tuple] = {}
        self._pp = Preprocessor(include_paths=include_paths, builtin_macros=defines or None)
        self.include_paths = include_paths or []
        self.defines = dict(defines) if defines else {}
        self.stats = IndexStats()

        # Verible 后端（如果可用）
        if verible_executable is None:
            verible_executable = find_verible_binary()
        self._verible: Optional[VeribleBackend] = None
        if verible_executable:
            backend = VeribleBackend(verible_executable)
            if backend.available:
                self._verible = backend

    # ---- 索引操作 ----
    def index_file(self, path: str, text: Optional[str] = None, version: int = 0):
        """索引单个文件。text=None 时从磁盘读取。

        始终使用 Python 解析器做索引（快 + 有引用追踪/端口连接/行号）。
        verible 只在 syntax_check / lint / format 工具被显式调用时使用。

        v5.0 优化：
        - 批量模式下跳过 _recompute_stats()，在 index_directory() 结束时统一调用一次
        - 增量缓存：文件 mtime+hash 未变则跳过重新解析
        - 安全索引：先解析再移除旧条目（parse 失败不丢已有索引）
        - 大文件守卫：>50MB 跳过并记录警告
        """
        path = os.path.normpath(path)
        with self._lock:
            # v5.0: 增量缓存检查 — 仅当从磁盘读取时启用
            if text is None:
                try:
                    st = os.stat(path)
                    mtime = st.st_mtime
                    cached = self._file_cache.get(path)
                    if cached and cached[0] == mtime:
                        get_monitor().record_cache(hit=True)
                        return  # 文件未修改，跳过
                    get_monitor().record_cache(hit=False)
                except OSError:
                    return
                # v5.0: 大文件守卫 — 超过 50MB 跳过避免内存爆炸
                MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
                if st.st_size > MAX_FILE_SIZE:
                    import sys as _sys
                    print(f"rtlens: skipping large file ({st.st_size // 1024 // 1024}MB): {path}", file=_sys.stderr)
                    return
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    return
                # 更新缓存
                self._file_cache[path] = (mtime, hashlib.md5(text.encode()).hexdigest())
            # v5.0: 安全索引 — 先解析，成功后再移除旧条目
            #   之前是先 remove 再 parse，parse 崩溃会丢已有索引（反馈中的核心 bug）
            try:
                self._pp._included.discard(path)
                # 快照当前已有的宏名 — process_text 不清空 macros（跨文件累积以支持 .vh），
                # 快照后新增的宏才属于本文件
                _macros_before = set(self._pp.macros.keys())
                expanded = self._pp.process_text(text, base_dir=os.path.dirname(path))
                result = parse(expanded)
            except Exception as e:
                import sys as _sys
                print(f"rtlens: parse error in {path}: {e}", file=_sys.stderr)
                return  # 保留已有索引不变
            old = self._files.get(path)
            if old:
                self._remove_file_entries(path)
            self._files[path] = IndexedFile(path=path, text=text, expanded=expanded, result=result, version=version)
            self._add_file_entries(path, result)
            # 合并预处理器的宏定义到索引（预处理器吃掉了 `define，parser 看不到）
            # 只合并本文件新增的宏（start_line < 0 是内置宏哨兵，跳过）
            fs_entry = self._file_stats.get(path)
            for mname, mdef in self._pp.macros.items():
                if mname in _macros_before:
                    continue  # 由更早的文件定义，不重复归入本文件
                if mdef.range.start_line < 0:
                    continue  # 内置宏哨兵
                self._macros[mname] = SymbolLocation(
                    mname, "macro", path, mdef.range, mdef.name_range,
                    detail=f"`{mname} = {mdef.value}" if mdef.value else f"`{mname}")
                if fs_entry is not None:
                    fs_entry.macros += 1
            # v5.0: 批量模式下跳过逐文件统计重算
            if not self._batch_mode:
                self._recompute_stats()

    def _parse_with_verible(self, path: str, text: str) -> Optional[ParseResult]:
        """用 verible 解析文件，转换为 ParseResult。"""
        if not self._verible:
            return None
        try:
            result = self._verible.parse_string(text)
        except Exception:
            return None
        if not result or not result.get("modules"):
            return None
        # 转换 verible 模块 → ParseResult（符号均带真实行列号）
        modules = []
        refs = []
        for vm in result["modules"]:
            mod = ModuleInfo(
                name=vm["name"],
                range=Range(vm.get("line", 0), vm.get("col", 0), vm.get("end_line", 0), vm.get("end_col", 0)),
                name_range=Range(vm.get("line", 0), vm.get("col", 0), vm.get("end_line", 0), vm.get("end_col", 0)),
                ports=[Symbol(
                    name=p["name"], kind="port",
                    range=Range(p.get("line", 0), p.get("col", 0), p.get("end_line", 0), p.get("end_col", 0)),
                    name_range=Range(p.get("line", 0), p.get("col", 0), p.get("end_line", 0), p.get("end_col", 0)),
                    direction=p.get("direction", "input"),
                    data_type=p.get("data_type", "wire"),
                    width=p.get("width", ""),
                    detail=f'{p.get("direction", "input")} {p.get("data_type", "wire")} {p.get("width", "")}',
                    parent=vm["name"]
                ) for p in vm.get("ports", [])],
                params=[Symbol(
                    name=p["name"], kind="parameter",
                    range=Range(p.get("line", 0), p.get("col", 0), p.get("end_line", 0), p.get("end_col", 0)),
                    name_range=Range(p.get("line", 0), p.get("col", 0), p.get("end_line", 0), p.get("end_col", 0)),
                    detail=p.get("detail", "parameter"),
                    parent=vm["name"]
                ) for p in vm.get("params", [])],
                signals=[Symbol(
                    name=s["name"], kind="signal",
                    range=Range(s.get("line", 0), s.get("col", 0), s.get("end_line", 0), s.get("end_col", 0)),
                    name_range=Range(s.get("line", 0), s.get("col", 0), s.get("end_line", 0), s.get("end_col", 0)),
                    data_type=s.get("data_type", "wire"),
                    width=s.get("width", ""),
                    parent=vm["name"]
                ) for s in vm.get("signals", [])],
                instances=[Instance(
                    module_type=inst["module_type"],
                    inst_name=inst["inst_name"],
                    range=Range(inst.get("line", 0), inst.get("col", 0), inst.get("end_line", 0), inst.get("end_col", 0)),
                    name_range=Range(inst.get("line", 0), inst.get("col", 0), inst.get("end_line", 0), inst.get("end_col", 0)),
                    type_range=Range(inst.get("line", 0), inst.get("col", 0), inst.get("end_line", 0), inst.get("end_col", 0)),
                    parent=vm["name"],
                    connections=[PortConnection(
                        port_name=c.get("port_name", ""),
                        signal_text=c.get("signal_text", ""),
                        range=Range(c.get("line", 0), c.get("col", 0), c.get("end_line", 0), c.get("end_col", 0)),
                    ) for c in inst.get("connections", [])],
                ) for inst in vm.get("instances", [])],
            )
            modules.append(mod)
            for r in vm.get("references", []):
                refs.append(Reference(r["name"], Range(r["line"], r["col"], r["end_line"], r["end_col"]), r["context"]))
        return ParseResult(modules=modules, references=refs)

    def index_directory(self, root: str, extensions=(".v", ".sv", ".vh", ".svh"), max_files: int = 5000):
        """递归索引目录。extensions 可为 tuple 或 list。

        Python 解析器单文件 <1ms，串行即可，无需并发。

        v5.0 优化：
        - 批量模式：全部文件索引完后统一调用一次 _recompute_stats()
        - 增量索引：通过 mtime 缓存跳过未修改文件
        v5.3.0: 清空虚拟文件池，确保磁盘模式不被虚拟文件污染
        """
        root = os.path.normpath(root)
        # v5.3.0: 清空虚拟文件池（磁盘模式不应使用 index_code 的虚拟文件）
        self._pp.set_virtual_files({})
        self._pp._included.clear()
        # 统一 extensions 为 tuple（兼容 list 参数）
        if isinstance(extensions, list):
            extensions = tuple(extensions)
        # v5.0: 启用批量模式 — 跳过逐文件统计重算
        self._batch_mode = True
        count = 0
        truncated = False
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # 跳过常见无关目录
                dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".svn"}]
                for fn in filenames:
                    if fn.endswith(extensions):
                        # 先看上限再看文件：这样"恰好 max_files 个文件"不会被
                        # 误判成截断，而"确实还有第 max_files+1 个"会被精确识别。
                        # 静默截断是契约违反（见 docs/EVIDENCE_CONTRACT.md），
                        # 所以这个布尔值必须精确，不能靠 count >= max_files 猜。
                        if count >= max_files:
                            truncated = True
                            break
                        fp = os.path.join(dirpath, fn)
                        self.index_file(fp)
                        count += 1
                if truncated:
                    break
        finally:
            # v5.0: 统一计算一次统计
            self._batch_mode = False
            self._recompute_stats()
            # 供调用方（如 evidence）如实披露覆盖不完整，见 self.last_index_truncated。
            self.last_index_truncated = truncated
        return count

    def remove_file(self, path: str):
        path = os.path.normpath(path)
        with self._lock:
            self._remove_file_entries(path)
            self._files.pop(path, None)
            self._file_cache.pop(path, None)  # v5.0: clean cache
            if not self._batch_mode:
                self._recompute_stats()

    def safe_switch_workspace(self, root: str) -> dict:
        """v5.0: 安全切换工作区 — 先索引新目录，成功后再替换旧索引。

        之前的 switch_workspace 先清空再索引，如果索引过程中超时/崩溃，
        整个工作区索引就被清空了（反馈中报告的核心稳定性 bug）。
        """
        root = os.path.normpath(root)
        if not os.path.isdir(root):
            return {"error": f"directory not found: {root}"}
        # 在临时实例上索引新目录
        tmp = WorkspaceIndex(include_paths=self.include_paths, defines=self.defines or None,
                            verible_executable=self._verible.executable if self._verible else None)
        try:
            count = tmp.index_directory(root)
        except Exception as e:
            return {"error": f"indexing failed: {e}", "files_indexed": 0}
        # 索引成功，原子替换
        with self._lock:
            old_files = dict(self._files)
            self._files = tmp._files
            self._module_defs = tmp._module_defs
            self._all_symbols = tmp._all_symbols
            self._all_refs = tmp._all_refs
            self._instances = tmp._instances
            self._instantiates = tmp._instantiates
            self._macros = tmp._macros
            self._packages = tmp._packages
            self._interfaces = tmp._interfaces     # v6.0.1
            self._typedefs = tmp._typedefs           # v6.0.1
            self._file_symbols = tmp._file_symbols
            self._file_stats = tmp._file_stats
            self._file_cache = tmp._file_cache
            self._pp = tmp._pp
            self.stats = tmp.stats
        return {"files_indexed": count, "stats": {
            "modules": self.stats.modules, "ports": self.stats.ports,
            "signals": self.stats.signals, "instances": self.stats.instances,
        }, "old_files_preserved": len(old_files)}

    def batch_index_files(self, paths: List[str]) -> dict:
        """v5.0: 批量索引多个文件 — 一次调用完成，减少 MCP 通道开销。

        返回每文件的索引状态 + 汇总统计。
        """
        results = {"indexed": 0, "skipped": 0, "errors": [], "total": len(paths)}
        self._batch_mode = True
        try:
            for p in paths:
                before = len(self._files)
                self.index_file(p)
                after = len(self._files)
                if after > before or (before > 0 and p in self._files):
                    results["indexed"] += 1
                else:
                    results["skipped"] += 1
        finally:
            self._batch_mode = False
            self._recompute_stats()
        results["stats"] = {
            "files": self.stats.files, "modules": self.stats.modules,
            "ports": self.stats.ports, "signals": self.stats.signals,
            "instances": self.stats.instances,
        }
        return results

    def index_code_batch(self, files: List[dict]) -> dict:
        """v5.3.0: 从文本内容批量索引 — 聊天窗口直传代码的专用入口。

        与 batch_index_files 的区别：
        - 不需要文件在磁盘上
        - 自动构建虚拟文件池，使 `include 指令能从传入的文件中解析
        - 清空 _included 确保每批干净状态
        """
        # v5.3.0: 构建虚拟文件池 — 在索引任何文件之前注册全部文件
        virtual_pool: Dict[str, str] = {}
        for item in files:
            fpath = item.get("path", "")
            fcontent = item.get("content", "")
            if fpath and fcontent:
                virtual_pool[fpath] = fcontent
        # 设置虚拟文件池到预处理器
        self._pp.set_virtual_files(virtual_pool)
        # 清空 include 追踪集，确保干净批次
        self._pp._included.clear()

        results = []
        self._batch_mode = True
        try:
            for item in files:
                fpath = item.get("path", "")
                fcontent = item.get("content", "")
                if not fpath:
                    results.append({"path": fpath, "status": "error", "error": "path is required"})
                    continue
                if not fcontent:
                    results.append({"path": fpath, "status": "error", "error": "content is required"})
                    continue
                before_modules = self.stats.modules
                self.index_file(fpath, text=fcontent)
                after_modules = self.stats.modules
                results.append({
                    "path": fpath,
                    "status": "indexed",
                    "modules_delta": after_modules - before_modules,
                })
        finally:
            self._batch_mode = False
            self._recompute_stats()
            # 不清除虚拟文件池 — 保留以备后续单文件追加索引时 include 仍可解析
        return {
            "indexed": len([r for r in results if r["status"] == "indexed"]),
            "errors": len([r for r in results if r["status"] == "error"]),
            "total_files": len(self._files),
            "stats": {
                "modules": self.stats.modules,
                "ports": self.stats.ports,
                "signals": self.stats.signals,
                "instances": self.stats.instances,
                "macros": self.stats.macros,
            },
            "files": results,
        }

    def _add_file_entries(self, path: str, result: ParseResult):
        fs = IndexStats(files=1)
        file_syms: List[SymbolLocation] = []
        for mod in result.modules:
            fs.modules += 1
            loc = SymbolLocation(mod.name, "module", path, mod.range, mod.name_range,
                                 detail=f"module ({len(mod.ports)} ports)")
            self._module_defs[mod.name].append(loc)
            self._all_symbols[mod.name].append(loc)
            file_syms.append(loc)
            # module 内部符号
            for p in mod.ports:
                fs.ports += 1
                sl = SymbolLocation(p.name, "port", path, p.range, p.name_range,
                                     detail=p.detail, parent=mod.name, container=mod.name)
                self._all_symbols[p.name].append(sl)
                file_syms.append(sl)
            for p in mod.params:
                fs.params += 1
                sl = SymbolLocation(p.name, "parameter", path, p.range, p.name_range,
                                     detail=p.detail, parent=mod.name, container=mod.name)
                self._all_symbols[p.name].append(sl)
                file_syms.append(sl)
            for s in mod.signals:
                fs.signals += 1
                sl = SymbolLocation(s.name, "signal", path, s.range, s.name_range,
                                     detail=s.detail, parent=mod.name, container=mod.name)
                self._all_symbols[s.name].append(sl)
                file_syms.append(sl)
            for f in mod.functions:
                fs.functions += 1
                sl = SymbolLocation(f.name, "function", path, f.range, f.name_range,
                                     detail=f.detail, parent=mod.name, container=mod.name)
                self._all_symbols[f.name].append(sl)
                file_syms.append(sl)
            # 例化
            for inst in mod.instances:
                fs.instances += 1
                sl = SymbolLocation(inst.inst_name, "instance", path, inst.range, inst.name_range,
                                     detail=f"instance of {inst.module_type}", parent=mod.name, container=mod.name)
                self._instances[inst.module_type].append(sl)
                file_syms.append(sl)
                if inst.module_type not in self._instantiates[mod.name]:
                    self._instantiates[mod.name].append(inst.module_type)
        # 包
        for pkg in result.packages:
            loc = SymbolLocation(pkg.name, "package", path, pkg.range, pkg.name_range, detail="package")
            self._packages.append(loc)
            self._all_symbols[pkg.name].append(loc)
            file_syms.append(loc)
            fs.packages += 1    # v6.0.1
        # v6.0.1: 包体细节 — 函数和参数索引为可搜索符号
        for pkg_detail in result.package_details:
            for func in pkg_detail.functions:
                # Skip typedefs stored in functions list (already indexed via result.typedefs)
                if hasattr(func, 'kind') and func.kind in ("typedef", "enum"):
                    continue
                sl = SymbolLocation(func.name, func.kind if hasattr(func, 'kind') else "function",
                                     path, func.range, func.name_range,
                                     detail=func.detail or "function", parent=pkg_detail.name, container=pkg_detail.name)
                self._all_symbols[func.name].append(sl)
                file_syms.append(sl)
                fs.functions += 1
            for param in pkg_detail.params:
                sl = SymbolLocation(param.name, "parameter", path, param.range, param.name_range,
                                     detail=param.detail or "parameter", parent=pkg_detail.name, container=pkg_detail.name)
                self._all_symbols[param.name].append(sl)
                file_syms.append(sl)
                fs.params += 1
        # v6.0.1: interface — 索引为可搜索符号（类似 module）
        for iface in result.interfaces:
            loc = SymbolLocation(iface.name, "interface", path, iface.range, iface.name_range,
                                 detail=f"interface ({len(iface.ports)} ports)")
            self._module_defs[iface.name].append(loc)  # interface 可被例化，加入 module_defs
            self._all_symbols[iface.name].append(loc)
            self._interfaces.append(loc)
            file_syms.append(loc)
            fs.interfaces += 1
            # interface 内部符号
            for p in iface.ports:
                fs.ports += 1
                sl = SymbolLocation(p.name, "port", path, p.range, p.name_range,
                                     detail=p.detail, parent=iface.name, container=iface.name)
                self._all_symbols[p.name].append(sl)
                file_syms.append(sl)
            for s in iface.signals:
                fs.signals += 1
                sl = SymbolLocation(s.name, "signal", path, s.range, s.name_range,
                                     detail=s.detail, parent=iface.name, container=iface.name)
                self._all_symbols[s.name].append(sl)
                file_syms.append(sl)
            for inst in iface.instances:
                fs.instances += 1
                sl = SymbolLocation(inst.inst_name, "instance", path, inst.range, inst.name_range,
                                     detail=f"instance of {inst.module_type}", parent=iface.name, container=iface.name)
                self._instances[inst.module_type].append(sl)
                file_syms.append(sl)
        # v6.0.1: typedef — 索引为可搜索符号
        for td in result.typedefs:
            loc = SymbolLocation(td.name, td.kind, path, td.range, td.name_range,
                                 detail=td.detail or td.kind)
            self._all_symbols[td.name].append(loc)
            self._typedefs.append(loc)
            file_syms.append(loc)
            fs.typedefs += 1
        # 宏
        for m in result.macros:
            fs.macros += 1
            self._macros[m.name] = SymbolLocation(m.name, "macro", path, m.range, m.name_range,
                                                   detail=f"`{m.name} = {m.value}" if m.value else f"`{m.name}")
        # 引用
        for ref in result.references:
            self._all_refs[ref.name].append(RefLocation(ref.name, path, ref.range, ref.context))
        # v4.5: per-file 索引
        self._file_symbols[path] = file_syms
        self._file_stats[path] = fs

    def _remove_file_entries(self, path: str):
        def filt(d: dict):
            for k in list(d.keys()):
                d[k] = [v for v in d[k] if v.file != path]
                if not d[k]:
                    del d[k]
        filt(self._module_defs)
        filt(self._all_symbols)
        filt(self._all_refs)
        filt(self._instances)
        self._packages = [p for p in self._packages if p.file != path]
        self._macros = {k: v for k, v in self._macros.items() if v.file != path}
        self._interfaces = [i for i in self._interfaces if i.file != path]    # v6.0.1
        self._typedefs = [t for t in self._typedefs if t.file != path]      # v6.0.1
        # v4.5: targeted _instantiates removal — only remove modules defined in this file
        idx = self._files.get(path)
        if idx:
            for mod in idx.result.modules:
                # Check if any other file still defines this module
                if mod.name not in self._module_defs:
                    self._instantiates.pop(mod.name, None)
                # else: another file defines the same module name, keep its entries
        # v4.5: clean per-file caches
        self._file_symbols.pop(path, None)
        self._file_stats.pop(path, None)

    def _recompute_stats(self):
        # v4.5: O(files) 而非 O(all_symbols) — 直接汇总 per-file 统计
        s = IndexStats(files=len(self._files))
        for fs in self._file_stats.values():
            s.modules += fs.modules
            s.ports += fs.ports
            s.signals += fs.signals
            s.params += fs.params
            s.instances += fs.instances
            s.functions += fs.functions
            s.macros += fs.macros
            s.interfaces += fs.interfaces    # v6.0.1
            s.typedefs += fs.typedefs        # v6.0.1
            s.packages += fs.packages        # v6.0.1
        self.stats = s

    # ---- 查询 ----
    def find_definition(self, file: str, line: int, col: int) -> Optional[SymbolLocation]:
        """在某个文件指定位置，找该处标识符的定义位置（跨文件）。"""
        file = os.path.normpath(file)
        idx = self._files.get(file)
        if not idx:
            return None
        # 该位置上是哪个标识符
        name = self._ident_at(file, line, col)
        if not name:
            return None
        # 优先：同文件同 module 的局部符号
        mod_name = self._module_at(file, line)
        candidates: List[SymbolLocation] = []
        if mod_name:
            candidates = [s for s in self._all_symbols.get(name, []) if s.container == mod_name]
        if not candidates:
            candidates = list(self._all_symbols.get(name, []))
        # 如果是例化的类型名，去 module 定义
        ref = self._ref_at(file, line, col)
        if ref and ref.context == "instantiation":
            mod_locs = self._module_defs.get(name, [])
            if mod_locs:
                return mod_locs[0]
        if candidates:
            # 同文件优先
            same_file = [c for c in candidates if c.file == file]
            if same_file:
                return same_file[0]
            return candidates[0]
        if name in self._macros:
            return self._macros[name]
        mod_locs = self._module_defs.get(name, [])
        if mod_locs:
            return mod_locs[0]
        return None

    def find_references(self, name: str) -> List[RefLocation]:
        refs = list(self._all_refs.get(name, []))
        # 加上声明位置（declaration 也是引用之一）
        for sl in self._all_symbols.get(name, []):
            refs.append(RefLocation(name, sl.file, sl.name_range, "declaration"))
        # 去重：Python parser 已把声明计入 references，避免 declaration 重复计数
        seen = set()
        out = []
        for r in refs:
            key = (r.file, r.range.start_line, r.range.start_col, r.context)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    def document_symbols(self, file: str) -> List[SymbolLocation]:
        # v4.5: O(1) per-file lookup instead of O(all_symbols)
        file = os.path.normpath(file)
        return list(self._file_symbols.get(file, []))

    def workspace_symbols(self, query: str, limit: int = 100) -> List[SymbolLocation]:
        q = query.lower()
        out: List[SymbolLocation] = []
        for name, locs in self._all_symbols.items():
            if q in name.lower():
                out.extend(locs)
            if len(out) >= limit:
                break
        return out[:limit]

    def get_module(self, name: str) -> Optional[ModuleInfo]:
        locs = self._module_defs.get(name, [])
        if not locs:
            return None
        idx = self._files.get(locs[0].file)
        if not idx:
            return None
        return next((m for m in idx.result.modules if m.name == name), None)

    def who_instantiates(self, module_type: str) -> List[SymbolLocation]:
        return list(self._instances.get(module_type, []))

    # v6.0.3: 外部模块分类 + 未解析模块清单（实战审计驱动的新能力）
    def classify_module_type(self, module_type: str) -> str:
        """分类例化类型：workspace（本工程定义）/ vendor_primitive（厂商原语或硬核 IP）/ unknown（可能拼写错误或缺文件）。"""
        if module_type in self._module_defs:
            return "workspace"
        if is_vendor_primitive(module_type):
            return "vendor_primitive"
        return "unknown"

    def list_unresolved_modules(self, suggest: bool = True) -> List[dict]:
        """列出全工程未被解析的例化类型。

        实战中（verilog-ethernet 461 文件）未解析类型里 BUFG/MMCM/SB_IO 等
        厂商原语占绝大多数，但真正的拼写错误也藏在其中。本方法把两类分开，
        并对 unknown 类给出相近模块名的拼写建议（difflib）。
        """
        import difflib
        results = []
        for mtype, locs in self._instances.items():
            if mtype in self._module_defs:
                continue
            entry = {
                "module_type": mtype,
                "kind": self.classify_module_type(mtype),
                "instances": len(locs),
                "files": sorted({l.file for l in locs}),
            }
            if suggest and entry["kind"] == "unknown":
                # 常见后缀（参数化 IP 生成名如 pcie4_uscale_plus_0）去掉 _数字 后再匹配
                base = _re.sub(r'_\d+$', '', mtype)
                candidates = list(self._module_defs.keys())
                close = difflib.get_close_matches(mtype, candidates, n=3, cutoff=0.75)
                close_base = difflib.get_close_matches(base, candidates, n=3, cutoff=0.75)
                merged = []
                for c in close + close_base:
                    if c not in merged:
                        merged.append(c)
                if merged:
                    entry["suggestions"] = merged
            results.append(entry)
        # 排序：unknown（疑似拼写错误）优先，其次按例化次数
        results.sort(key=lambda e: (e["kind"] != "unknown", -e["instances"]))
        return results

    # v6.0.4: 变更影响分析（增量回归的实际入口）
    def _resolve_indexed_file(self, path: str) -> Optional[str]:
        """把外部传入的文件路径解析到索引中的路径（精确→后缀→文件名）。"""
        p = os.path.normpath(path)
        if p in self._files:
            return p
        norm = p.replace("\\", "/")
        suf = [f for f in self._files if f.replace("\\", "/").endswith(norm)]
        if len(suf) == 1:
            return suf[0]
        base = norm.rsplit("/", 1)[-1]
        same = [f for f in self._files if f.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] == base]
        if len(suf) >= 1:
            return suf[0]
        if len(same) == 1:
            return same[0]
        return None

    def analyze_change_impact(self, changed_files: List[str], max_depth: int = 30) -> dict:
        """变更影响分析：改了哪些文件 → 波及哪些模块 → 要重跑哪些 testbench。

        验证回归的时间大头在于「全量重跑」；本方法沿例化关系反向 BFS，
        把改动文件的模块上溯到根（无人例化者），并用 testbench 命名启发式
        （tb/test/bench）圈出建议重跑的仿真顶层。
        """
        resolved: Dict[str, str] = {}
        unresolved: List[str] = []
        for f in changed_files:
            r = self._resolve_indexed_file(f)
            if r is None:
                unresolved.append(f)
            else:
                resolved[f] = r

        # 1) 改动文件里定义了哪些模块/接口
        changed_modules: List[str] = []
        for f, rp in resolved.items():
            idx = self._files.get(rp)
            if not idx:
                continue
            for mod in idx.result.modules:
                changed_modules.append(mod.name)
            for iface in idx.result.interfaces:
                changed_modules.append(iface.name)

        # 2) 反向 BFS：改动模块 → 谁例化了它 → 一路上溯到根
        impacted: set = set(changed_modules)
        depth_map: Dict[str, int] = {m: 0 for m in changed_modules}
        parents: Dict[str, List[str]] = {}
        roots: set = set()
        frontier = list(changed_modules)
        d = 0
        while frontier and d < max_depth:
            d += 1
            nxt = []
            for m in frontier:
                ups = sorted({loc.parent for loc in self._instances.get(m, []) if loc.parent})
                if not ups:
                    roots.add(m)
                    continue
                parents[m] = ups
                for p in ups:
                    if p not in impacted:
                        impacted.add(p)
                        depth_map[p] = d
                        nxt.append(p)
            frontier = nxt
        for m in frontier:  # 超过 max_depth 的剩余节点也算根（防截断误导）
            roots.add(m)

        # 改动模块本身若是顶层（如直接改 testbench），也是根
        for m in changed_modules:
            if not any(loc.parent for loc in self._instances.get(m, [])):
                roots.add(m)

        # 3) testbench 启发式 + 波及文件清单
        tb_pat = _re.compile(r'(tb|test|bench)', _re.I)
        testbenches = sorted(m for m in roots if tb_pat.search(m))
        impacted_files: set = set()
        for m in impacted:
            for loc in self._module_defs.get(m, []):
                impacted_files.add(loc.file)

        return {
            "changed_files": {f: rp for f, rp in resolved.items()},
            "unresolved_files": unresolved,
            "changed_modules": sorted(set(changed_modules)),
            "impacted_modules": sorted(impacted - set(changed_modules)),
            "impacted_files": sorted(impacted_files),
            "root_modules": sorted(roots),
            "testbenches": testbenches,
            "max_upward_depth": (max(depth_map.values()) if depth_map else 0),
        }

    def get_hierarchy(self, top: str, depth: int = 10) -> dict:
        def build(mod_name: str, d: int) -> dict:
            mod = self.get_module(mod_name)
            if not mod or d <= 0:
                return {"module": mod_name, "instances": []}
            children = []
            for inst in mod.instances:
                children.append({
                    "instance": inst.inst_name,
                    "type": inst.module_type,
                    "file": locs[0].file if (locs := self._module_defs.get(inst.module_type)) else "",
                    "sub": build(inst.module_type, d - 1)
                })
            return {"module": mod_name, "instances": children}
        return build(top, depth)

    def get_signal_drivers(self, file: str, signal: str) -> List[RefLocation]:
        """找到信号的所有驱动点（assign/always 中的赋值目标）。"""
        file = os.path.normpath(file)
        return [r for r in self._all_refs.get(signal, []) if r.context == "driver" and r.file == file]

    def get_macros(self) -> Dict[str, SymbolLocation]:
        return dict(self._macros)

    def get_stats(self) -> IndexStats:
        return self.stats

    # ---- 重命名支持（参考 rust-analyzer rename）----

    def prepare_rename(self, file: str, line: int, col: int) -> Optional[dict]:
        """检查光标位置是否可重命名，返回当前符号的范围和名称。"""
        name = self._ident_at(file, line, col)
        if not name:
            return None
        # 找到该标识符在文件中的位置
        idx = self._files.get(file)
        if not idx:
            return None
        lines = idx.expanded.split("\n")
        if line >= len(lines):
            return None
        ln = lines[line]
        # 找到 col 附近的标识符范围（防越界）
        start = min(col, len(ln) - 1) if len(ln) > 0 else 0
        if start < 0:
            return None
        while start > 0 and (ln[start - 1].isalnum() or ln[start - 1] in "_$"):
            start -= 1
        end = min(col + 1, len(ln))
        while end < len(ln) and (ln[end].isalnum() or ln[end] in "_$"):
            end += 1
        return {
            "range": {
                "start": {"line": line, "character": start},
                "end": {"line": line, "character": end},
            },
            "placeholder": ln[start:end],
        }

    def rename_symbol(self, file: str, line: int, col: int, new_name: str) -> Optional[dict]:
        """跨文件重命名符号，返回所有文件的 TextEdit。

        参考 rust-analyzer: 找到定义→找所有引用→生成 TextEdit
        """
        name = self._ident_at(file, line, col)
        if not name:
            return None

        # 收集所有需要修改的位置（按文件分组）
        edits: Dict[str, List[dict]] = defaultdict(list)

        # 1. 定义处
        defs = self._all_symbols.get(name, [])
        for sym in defs:
            r = sym.name_range
            edits[sym.file].append({
                "range": {
                    "start": {"line": r.start_line, "character": r.start_col},
                    "end": {"line": r.end_line, "character": r.end_col},
                },
                "newText": new_name,
            })

        # 2. 引用处
        refs = self._all_refs.get(name, [])
        for ref in refs:
            r = ref.range
            edits[ref.file].append({
                "range": {
                    "start": {"line": r.start_line, "character": r.start_col},
                    "end": {"line": r.end_line, "character": r.end_col},
                },
                "newText": new_name,
            })

        # 3. 宏定义里的引用
        macro = self._macros.get(name)
        if macro:
            r = macro.name_range
            edits[macro.file].append({
                "range": {
                    "start": {"line": r.start_line, "character": r.start_col},
                    "end": {"line": r.end_line, "character": r.end_col},
                },
                "newText": new_name,
            })

        if not edits:
            return None

        return {"changes": {fp: el for fp, el in edits.items()}}

    # ---- 代码透镜（Code Lens）----

    def get_code_lens(self, file: str) -> List[dict]:
        """为文件中的每个模块/实例生成代码透镜。

        参考 rust-analyzer: 显示引用计数、实现列表
        """
        idx = self._files.get(file)
        if not idx:
            return []
        lenses = []
        for mod in idx.result.modules:
            # 模块定义处显示"被实例化 N 次"
            insts = self.who_instantiates(mod.name)
            if insts:
                lenses.append({
                    "range": {
                        "start": {"line": mod.name_range.start_line, "character": mod.name_range.start_col},
                        "end": {"line": mod.name_range.end_line, "character": mod.name_range.end_col},
                    },
                    "command": {
                        "title": f"被实例化 {len(insts)} 次",
                        "command": "rtlens.showReferences",
                        "arguments": [file, mod.name_range.start_line, mod.name_range.start_col, mod.name],
                    },
                })
            # 模块内部实例化处显示"查看子模块"
            for inst in mod.instances:
                lens_range = inst.name_range
                lenses.append({
                    "range": {
                        "start": {"line": lens_range.start_line, "character": lens_range.start_col},
                        "end": {"line": lens_range.end_line, "character": lens_range.end_col},
                    },
                    "command": {
                        "title": f"→ {inst.module_type}",
                        "command": "rtlens.gotoModule",
                        "arguments": [inst.module_type],
                    },
                })
        return lenses

    # ---- Inlay Hints ----

    def get_inlay_hints(self, file: str, start_line: int, end_line: int) -> List[dict]:
        """在实例化端口连接处显示参数名提示。

        参考 rust-analyzer inlay hints: 显示函数参数名
        Verilog: 按位置连接的端口显示 .port_name(信号)
        """
        idx = self._files.get(file)
        if not idx:
            return []
        hints = []
        for mod in idx.result.modules:
            for inst in mod.instances:
                if not (start_line <= inst.range.start_line <= end_line):
                    continue
                # 如果是按位置连接（无 .port_name），显示端口名
                for i, conn in enumerate(inst.connections):
                    if not conn.port_name and i < len(self._get_module_ports(inst.module_type)):
                        port_name = self._get_module_ports(inst.module_type)[i]
                        hints.append({
                            "position": {"line": conn.range.start_line, "character": conn.range.start_col},
                            "label": f".{port_name}",
                            "kind": 2,  # parameter
                        })
        return hints

    def _get_module_ports(self, module_type: str) -> List[str]:
        """获取模块的端口名列表（按声明顺序）。"""
        mod = self.get_module(module_type)
        if not mod:
            # 检查是否是 eLinx 原语
            return []
        return [p.name for p in mod.ports]

    # ---- 文档符号树（层级结构）----

    def document_symbol_tree(self, file: str) -> List[dict]:
        """返回带层级的文档符号（参考 rust-analyzer documentSymbol）。

        module
        ├── port1 (port)
        ├── port2 (port)
        ├── signal1 (signal)
        ├── instance1 (instance)
        │   ├── .port(sig)
        │   └── .port(sig)
        └── always_block
        """
        idx = self._files.get(file)
        if not idx:
            return []
        symbols = []
        for mod in idx.result.modules:
            children = []
            # 端口
            for p in mod.ports:
                children.append({
                    "name": p.name,
                    "kind": 7,  # Property → port
                    "range": _range_to_lsp(p.range),
                    "selectionRange": _range_to_lsp(p.name_range),
                    "detail": f"{p.direction or ''} {p.data_type or ''} {p.width or ''}".strip(),
                })
            # 参数
            for p in mod.params:
                children.append({
                    "name": p.name,
                    "kind": 14,  # Constant → parameter
                    "range": _range_to_lsp(p.range),
                    "selectionRange": _range_to_lsp(p.name_range),
                    "detail": p.detail or "",
                })
            # 信号
            for s in mod.signals:
                children.append({
                    "name": s.name,
                    "kind": 13,  # Variable → signal
                    "range": _range_to_lsp(s.range),
                    "selectionRange": _range_to_lsp(s.name_range),
                    "detail": f"{s.data_type or ''} {s.width or ''}".strip(),
                })
            # 实例
            for inst in mod.instances:
                inst_children = []
                for c in inst.connections:
                    inst_children.append({
                        "name": f".{c.port_name}({c.signal_text})",
                        "kind": 6,  # Object → connection
                        "range": _range_to_lsp(c.range),
                        "selectionRange": _range_to_lsp(c.range),
                    })
                children.append({
                    "name": f"{inst.module_type} {inst.inst_name}",
                    "kind": 2,  # Class → instance
                    "range": _range_to_lsp(inst.range),
                    "selectionRange": _range_to_lsp(inst.name_range),
                    "detail": inst.module_type,
                    "children": inst_children,
                })
            # 函数/任务
            for f in mod.functions:
                children.append({
                    "name": f.name,
                    "kind": 12,  # Function
                    "range": _range_to_lsp(f.range),
                    "selectionRange": _range_to_lsp(f.name_range),
                    "detail": f.detail or "",
                })

            symbols.append({
                "name": mod.name,
                "kind": 2,  # Class → module
                "range": _range_to_lsp(mod.range),
                "selectionRange": _range_to_lsp(mod.name_range),
                "detail": f"module ({len(mod.ports)} ports, {len(mod.signals)} signals, {len(mod.instances)} instances)",
                "children": children,
            })
        return symbols

    # ---- 内部工具 ----
    def _ident_at(self, file: str, line: int, col: int) -> Optional[str]:
        idx = self._files.get(file)
        if not idx:
            return None
        # 在展开后文本里找该位置上的标识符
        lines = idx.expanded.split("\n")
        if line < 0 or line >= len(lines):
            return None
        ln = lines[line]
        # 向左找标识符起始
        end = min(col + 1, len(ln))
        start = min(col, len(ln) - 1) if len(ln) > 0 else 0
        if start < 0 or len(ln) == 0:
            return None
        while start > 0 and (ln[start - 1].isalnum() or ln[start - 1] in "_$"):
            start -= 1
        while end < len(ln) and (ln[end].isalnum() or ln[end] in "_$"):
            end += 1
        word = ln[start:end]
        return word if word and (word[0].isalpha() or word[0] == "_") else None

    def _module_at(self, file: str, line: int) -> Optional[str]:
        idx = self._files.get(file)
        if not idx:
            return None
        for mod in idx.result.modules:
            if mod.range.contains(line, 0):
                return mod.name
        return None

    def _ref_at(self, file: str, line: int, col: int) -> Optional[RefLocation]:
        for r in self._all_refs.values():
            for ref in r:
                if ref.file == file and ref.range.contains(line, col):
                    return ref
        return None



def _range_to_lsp(r: Range) -> dict:
    """将内部 Range 转为 LSP Range 格式。"""
    return {
        "start": {"line": r.start_line, "character": r.start_col},
        "end": {"line": r.end_line, "character": r.end_col},
    }
