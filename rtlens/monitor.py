"""性能监控器：采集 MCP / API 每次操作的真实耗时与状态。

设计原则：
- 全部真实测量，不编造任何数据
- 线程安全（MCP 可能被并发调用）
- 内存有界（滚动窗口，不无限增长）
- 零依赖（纯 stdlib）
"""

from __future__ import annotations

import os
import time
import json
import hashlib
import tempfile
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

try:
    import psutil  # 可选：仅用于进程级内存/CPU 采样，缺失时优雅降级
except ImportError:
    psutil = None


@dataclass
class OperationRecord:
    """单次操作的完整记录。"""
    op_type: str          # index_file / batch_index / search_symbol / ...
    tool_name: str        # MCP 工具名或 API 端点名
    duration_ms: float     # 实际耗时
    success: bool          # 是否成功
    files_affected: int    # 涉及文件数
    symbols_affected: int  # 涉及符号数
    error: str            # 失败原因（成功时为空）
    timestamp: float      # time.time() 时间戳
    detail: str           # 附加信息（如文件路径、查询关键词）

    def to_dict(self) -> dict:
        return {
            "op_type": self.op_type,
            "tool_name": self.tool_name,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "files_affected": self.files_affected,
            "symbols_affected": self.symbols_affected,
            "error": self.error,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }


@dataclass
class OpTypeStats:
    """按操作类型聚合的统计。"""
    count: int = 0
    success_count: int = 0
    fail_count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    avg_ms: float = 0.0
    last_ms: float = 0.0
    last_time: float = 0.0

    def update(self, duration_ms: float, success: bool, timestamp: float):
        self.count += 1
        if success:
            self.success_count += 1
        else:
            self.fail_count += 1
        self.total_ms += duration_ms
        self.min_ms = min(self.min_ms, duration_ms) if self.min_ms != float("inf") else duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        self.avg_ms = self.total_ms / self.count
        self.last_ms = duration_ms
        self.last_time = timestamp

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_ms": round(self.total_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.min_ms != float("inf") else 0,
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
            "last_ms": round(self.last_ms, 2),
            "last_time": self.last_time,
            "error_rate": round(self.fail_count / self.count * 100, 1) if self.count > 0 else 0,
        }


class PerformanceMonitor:
    """全局性能监控器（单例）。

    用法：
        monitor = PerformanceMonitor()
        # 方式一：手动记录
        monitor.record("index_file", "index_file", 15.3, True, files_affected=1)
        # 方式二：上下文管理器
        with monitor.track("search_symbol", "search_symbol") as t:
            results = index.workspace_symbols("clk")
            t.files_affected = len(results)
    """

    def __init__(self, history_size: int = 200):
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=history_size)
        self._stats: Dict[str, OpTypeStats] = {}
        self._start_time = time.time()
        self._total_ops = 0
        self._total_files_processed = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._process = psutil.Process(os.getpid()) if psutil is not None else None
        self._peak_memory_mb = 0.0
        # v5.1.1: 跨进程监控桥接 —— MCP 进程把快照写到文件，Web 看板读该文件
        # 让 workbuddy 拉起的 MCP stdio 进程的实时数据能在外部浏览器看板显示
        self._bridge_path: Optional[str] = None
        self._bridge_min_interval: float = 1.0
        self._bridge_last_write: float = 0.0
        self._bridge_lock = threading.Lock()

    def record(self, op_type: str, tool_name: str, duration_ms: float,
               success: bool = True, files_affected: int = 0, symbols_affected: int = 0,
               error: str = "", detail: str = ""):
        """记录一次操作。"""
        ts = time.time()
        rec = OperationRecord(
            op_type=op_type, tool_name=tool_name, duration_ms=duration_ms,
            success=success, files_affected=files_affected,
            symbols_affected=symbols_affected, error=error,
            timestamp=ts, detail=detail,
        )
        with self._lock:
            self._history.append(rec)
            if op_type not in self._stats:
                self._stats[op_type] = OpTypeStats()
            self._stats[op_type].update(duration_ms, success, ts)
            self._total_ops += 1
            self._total_files_processed += files_affected
            # 更新峰值内存
            try:
                if self._process is not None:
                    mem = self._process.memory_info().rss / 1024 / 1024
                    if mem > self._peak_memory_mb:
                        self._peak_memory_mb = mem
            except Exception:
                pass
        # v5.1.1: 桥接 —— 节流地把快照写文件，让外部看板能看到本进程的实时数据
        self._maybe_write_bridge()

    def track(self, op_type: str, tool_name: str, detail: str = ""):
        """上下文管理器：自动计时。"""
        return _TrackContext(self, op_type, tool_name, detail)

    def record_cache(self, hit: bool):
        """记录缓存命中/未命中。"""
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def get_snapshot(self) -> dict:
        """获取当前监控快照（全部真实数据）。"""
        with self._lock:
            uptime = time.time() - self._start_time
            # 内存（psutil 可选，缺失时跳过采样）
            try:
                if self._process is not None:
                    mem_mb = self._process.memory_info().rss / 1024 / 1024
                    cpu_percent = self._process.cpu_percent(interval=0.1)
                else:
                    mem_mb, cpu_percent = 0, 0
            except Exception:
                mem_mb = 0
                cpu_percent = 0
            # 最近操作列表
            recent = [r.to_dict() for r in list(self._history)[-50:]]
            # 按类型统计
            stats = {k: v.to_dict() for k, v in self._stats.items()}
            # 吞吐量
            total_cache = self._cache_hits + self._cache_misses
            ops_per_min = (self._total_ops / uptime * 60) if uptime > 0 else 0
            files_per_min = (self._total_files_processed / uptime * 60) if uptime > 0 else 0

            return {
                "uptime_seconds": round(uptime, 1),
                "uptime_display": _format_duration(uptime),
                "total_operations": self._total_ops,
                "total_files_processed": self._total_files_processed,
                "ops_per_minute": round(ops_per_min, 1),
                "files_per_minute": round(files_per_min, 1),
                "memory_mb": round(mem_mb, 1),
                "peak_memory_mb": round(self._peak_memory_mb, 1),
                "cpu_percent": round(cpu_percent, 1),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_hit_rate": round(self._cache_hits / total_cache * 100, 1) if total_cache > 0 else 0,
                "recent_operations": recent,
                "operation_stats": stats,
                "operation_count": len(self._history),
                "timestamp": time.time(),
            }

    # ---- v5.1.1: 跨进程监控桥接 ----
    def enable_bridge(self, path: str, min_interval: float = 1.0):
        """启用桥接：每次 record 后把快照原子写到 path，供外部 Web 看板读取。"""
        self._bridge_path = path
        self._bridge_min_interval = min_interval
        # 立即写一次，让看板第一时间能连上
        self._write_bridge(force=True)

    def disable_bridge(self):
        self._bridge_path = None

    def _maybe_write_bridge(self):
        path = self._bridge_path
        if not path:
            return
        now = time.time()
        with self._bridge_lock:
            if now - self._bridge_last_write < self._bridge_min_interval:
                return
            self._bridge_last_write = now
        self._write_bridge()

    def _write_bridge(self, force: bool = False):
        path = self._bridge_path
        if not path:
            return
        try:
            snap = self.get_snapshot()
            snap["bridge_pid"] = os.getpid()
            snap["source"] = "mcp_process"
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            # 原子写：临时文件 + os.replace
            fd, tmp = tempfile.mkstemp(dir=d or ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False)
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass  # 桥接是 best-effort，不能影响主流程


def bridge_snapshot_path(root: Optional[str], pid: Optional[int] = None) -> str:
    """根据项目根目录返回该工程对应的监控桥接快照文件路径。

    不同工程隔离：对 root 做哈希，避免路径中的特殊字符 / 超长。
    Web 看板与 MCP 进程用同一 root 即可读到同一文件。

    v5.2.0: 当 root 为 None 时（MCP 不带 --root 启动），用 PID 隔离，
    避免多个无 root 的 MCP 进程共用 standalone.json 互相覆盖。
    """
    base = os.path.join(os.path.expanduser("~"), ".rtlens", "monitor")
    if root:
        key = hashlib.md5(os.path.normpath(os.path.abspath(root)).encode()).hexdigest()[:12]
        return os.path.join(base, f"{key}.json")
    # v5.2.0: 无 root 时用 PID 隔离；pid=None 时回退到旧名（兼容测试）
    if pid is not None:
        return os.path.join(base, f"standalone_{pid}.json")
    return os.path.join(base, "standalone.json")


def read_bridge_snapshot(root: Optional[str], max_age_seconds: float = 300.0) -> Optional[dict]:
    """读取外部进程（通常是 MCP stdio）写入的监控快照。

    返回 None 表示：没有桥接文件，或文件已过期（MCP 进程已退出超过 max_age_seconds）。
    存在则返回带 source='mcp_process' 和 bridge_age_seconds 的快照字典。

    v5.2.0: 当 root 为 None 时，扫描 monitor 目录下所有 standalone_*.json，
    返回最新写入的一个（支持多个无 root 的 MCP 进程共存）。
    """
    if root:
        path = bridge_snapshot_path(root)
        return _read_single_bridge(path, max_age_seconds)
    # v5.2.0: 无 root 时扫描所有 standalone_*.json，返回最新的
    base = os.path.join(os.path.expanduser("~"), ".rtlens", "monitor")
    best_data = None
    best_mtime = 0.0
    try:
        if not os.path.isdir(base):
            return None
        for fname in os.listdir(base):
            if not fname.startswith("standalone_") or not fname.endswith(".json"):
                continue
            fpath = os.path.join(base, fname)
            mtime = os.path.getmtime(fpath)
            age = time.time() - mtime
            if age > max_age_seconds:
                continue
            if mtime > best_mtime:
                data = _read_single_bridge(fpath, max_age_seconds)
                if data is not None:
                    best_data = data
                    best_mtime = mtime
    except Exception:
        pass
    return best_data


def _read_single_bridge(path: str, max_age_seconds: float) -> Optional[dict]:
    """读取单个桥接快照文件。"""
    try:
        if not os.path.isfile(path):
            return None
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        if age > max_age_seconds:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["bridge_age_seconds"] = round(age, 1)
        data["source"] = "mcp_process"
        return data
    except Exception:
        return None


class _TrackContext:
    """track() 上下文管理器。"""

    def __init__(self, monitor: PerformanceMonitor, op_type: str, tool_name: str, detail: str = ""):
        self._monitor = monitor
        self._op_type = op_type
        self._tool_name = tool_name
        self._detail = detail
        self._start = 0.0
        self.files_affected = 0
        self.symbols_affected = 0
        self._success = True
        self._error = ""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self._start) * 1000
        if exc_type:
            self._success = False
            self._error = str(exc_val)[:200]
        self._monitor.record(
            self._op_type, self._tool_name, duration_ms,
            success=self._success, files_affected=self.files_affected,
            symbols_affected=self.symbols_affected,
            error=self._error, detail=self._detail,
        )
        return False  # 不吞异常

    def fail(self, error: str):
        """手动标记失败。"""
        self._success = False
        self._error = error[:200]


def _format_duration(seconds: float) -> str:
    """格式化运行时长。"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m{secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins}m"


# 全局单例
_monitor: Optional[PerformanceMonitor] = None


def get_monitor() -> PerformanceMonitor:
    """获取全局监控器实例。"""
    global _monitor
    if _monitor is None:
        _monitor = PerformanceMonitor()
    return _monitor
