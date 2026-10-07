#!/usr/bin/env python3
"""快速验证 Web UI + API 端到端能工作。"""
import sys, os, json, threading, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rtlens.api import run_api, _STATE
from rtlens.indexer import WorkspaceIndex
from rtlens.elinx import ELinxSupport

# 在后台线程启动 API
_STATE.index = WorkspaceIndex()
_STATE.elinx = ELinxSupport()
root = os.path.join(os.path.dirname(__file__), "..", "examples", "hierarchy")
_STATE.index.index_directory(root)

from http.server import HTTPServer
from rtlens.api import _Handler
srv = HTTPServer(("127.0.0.1", 38765), _Handler)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
time.sleep(0.5)

def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:38765{path}") as r:
        return r.read().decode("utf-8")

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {name}")
    else:
        FAIL += 1; print(f"  ✗ {name} {detail}")

print("\n[Web UI 端到端测试]")
html = get("/")
check("根路径返回 HTML", "<!DOCTYPE html>" in html)
check("HTML 含 RTLens 标题", "RTLens" in html)
check("HTML 含层级树 tab", "hierarchy" in html)
check("HTML 含模块详情 tab", "module" in html.lower())
check("HTML 含原语 tab", "primitives" in html)

print("\n[API 端到端测试]")
stats = json.loads(get("/api/stats"))
check("stats 有 modules 字段", "modules" in stats and stats["modules"] >= 3, str(stats))

mod = json.loads(get("/api/module/counter"))
check("module counter 有名字", mod["name"] == "counter")
check("module counter 有端口", len(mod["ports"]) == 5, f"got {len(mod['ports'])}")
check("module counter 有信号", len(mod["signals"]) >= 1)

hier = json.loads(get("/api/hierarchy/top"))
check("hierarchy top 有子节点", len(hier["instances"]) == 2, f"got {len(hier['instances'])}")

refs = json.loads(get("/api/references/counter"))
check("references counter 非空", len(refs) >= 1)

prims = json.loads(get("/api/primitives"))
check("primitives 有 14 个", len(prims) == 14, f"got {len(prims)}")

# 索引 elinx_demo 并查约束
mac = json.loads(get("/api/macros"))
check("macros 端点可调", isinstance(mac, list))

print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
print(f"{'='*50}")
srv.shutdown()
sys.exit(1 if FAIL > 0 else 0)
