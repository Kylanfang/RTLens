"""RTLens 自动配置模块：一键检测环境、安装依赖、配置 MCP、自测验证。

用法：
  python3 -m rtlens setup              # 自动检测并配置
  python3 -m rtlens setup --tool auto # 同上（显式）
  python3 -m rtlens setup --tool claude-code  # 只配 Claude Code
  python3 -m rtlens setup --tool cursor       # 只配 Cursor
  python3 -m rtlens setup --tool generic      # 写 mcp.json 到当前目录
  python3 -m rtlens setup --project /path/to/rtl  # 指定 Verilog 工程目录
  python3 -m rtlens setup --list-tools         # 只列出检测到的工具
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 颜色输出
def _c(text: str, color: str = "") -> str:
    if not sys.stdout.isatty():
        return text
    colors = {"green": "32", "yellow": "33", "red": "31", "blue": "34", "cyan": "36", "dim": "90"}
    code = colors.get(color, "")
    return f"\033[{code}m{text}\033[0m" if code else text

def _ok(msg: str):   print(f"  {_c('✓', 'green')} {msg}")
def _warn(msg: str): print(f"  {_c('⚠', 'yellow')} {msg}")
def _fail(msg: str): print(f"  {_c('✗', 'red')} {msg}")
def _info(msg: str): print(f"  {_c('→', 'cyan')} {msg}")
def _header(msg: str): print(f"\n{_c('━' * 50, 'dim')}\n  {_c(msg, 'blue')}\n{_c('━' * 50, 'dim')}")


def check_python() -> bool:
    """检查 Python 版本 >= 3.8"""
    ver = sys.version_info
    ok = ver >= (3, 8)
    if ok:
        _ok(f"Python {ver.major}.{ver.minor}.{ver.micro} ({platform.system()})")
    else:
        _fail(f"Python {ver.major}.{ver.minor} 过低，需要 3.8+")
    return ok


def check_pip() -> bool:
    """检查 pip 是否可用"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.decode().strip()
            _ok(f"pip 可用: {version_line.split(',')[0]}")
            return True
    except Exception:
        pass
    _fail("pip 不可用，请安装 pip")
    return False


def check_psutil() -> bool:
    """检查 psutil 是否可用（性能监控需要）"""
    try:
        import psutil
        _ok(f"psutil {psutil.__version__} 可用（性能监控就绪）")
        return True
    except ImportError:
        _warn("psutil 未安装，性能监控将不可用。运行: pip install psutil")
        return False


def check_rtlens_importable() -> bool:
    """检查 rtlens 是否可导入"""
    try:
        import rtlens
        _ok(f"rtlens v{rtlens.__version__} 已安装")
        return True
    except ImportError:
        _info("rtlens 尚未安装，尝试 pip install -e . ...")
        return False


def install_rtlens(pkg_dir: str) -> bool:
    """pip install -e . 安装 rtlens"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", pkg_dir],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120
        )
        if result.returncode == 0:
            _ok("rtlens 安装成功")
            return True
        else:
            output = result.stdout.decode(errors="replace")
            _fail(f"安装失败:\n{output[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        _fail("安装超时（120s），请手动运行 pip install -e .")
        return False
    except Exception as e:
        _fail(f"安装异常: {e}")
        return False


def check_verible() -> bool:
    """检查 Verible 是否可用（可选，不影响核心功能）"""
    try:
        result = subprocess.run(
            ["verible-verilog-ls", "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
        )
        if result.returncode == 0:
            ver = result.stdout.decode().strip()
            _ok(f"Verible 可用: {ver}")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    _warn("Verible 未安装（Lint/语法检查功能不可用，其他功能正常）")
    _info("安装 Verible: https://github.com/chipsalliance/verible")
    return False


# ---- AI 工具检测 ----

# 各 AI 工具的 MCP 配置文件路径检测规则
AI_TOOL_CONFIGS = {
    "claude-code": {
        "name": "Claude Code",
        "detect_paths": [
            "~/.claude",
            ".claude",
        ],
        "config_file": "mcp_servers.json",
        "config_paths": [
            "~/.claude/mcp_servers.json",   # 用户级
            ".claude/mcp_servers.json",      # 项目级
        ],
    },
    "cursor": {
        "name": "Cursor",
        "detect_paths": [
            "~/.cursor",
            ".cursor",
        ],
        "config_file": "mcp.json",
        "config_paths": [
            "~/.cursor/mcp.json",
            ".cursor/mcp.json",
        ],
    },
    "cline": {
        "name": "Cline (VS Code)",
        "detect_paths": [
            "~/.vscode/extensions/saoudrizwan.claude-dev-*",
        ],
        "config_file": "cline_mcp_settings.json",
        "config_paths": [
            # macOS
            "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
            # Linux
            "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
            # Windows
            "~/AppData/Roaming/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
        ],
    },
    "windsurf": {
        "name": "Windsurf",
        "detect_paths": [
            "~/.codeium/windsurf",
            "~/.windsurf",
        ],
        "config_file": "mcp_config.json",
        "config_paths": [
            "~/.codeium/windsurf/mcp_config.json",
        ],
    },
    "generic": {
        "name": "通用 MCP",
        "detect_paths": [],
        "config_file": "mcp.json",
        "config_paths": ["mcp.json"],
    },
    "workbuddy": {
        "name": "Workbuddy（字节跳动 AI 编程 IDE）",
        "detect_paths": [
            "~/.workbuddy",
            ".workbuddy",
            "~/.config/workbuddy",
        ],
        "config_file": "mcp.json",
        "config_paths": [
            # 项目级（推荐，跟随工程走）
            ".workbuddy/mcp.json",
            # 用户级
            "~/.workbuddy/mcp.json",
            "~/.config/workbuddy/mcp.json",
        ],
    },
    # v6.1.0: ZCode —— 配置结构与其余工具不同：
    #   ~/.zcode/cli/config.json 用嵌套的 {"mcp": {"servers": {...}}} 结构，
    #   且 schema 严格（未知字段会导致 server 被丢弃），需要专用写入逻辑。
    "zcode": {
        "name": "ZCode",
        "detect_paths": [
            "~/.zcode",
        ],
        "config_file": "config.json",
        "config_paths": [
            "~/.zcode/cli/config.json",   # 用户级
        ],
        "nested": True,
    },
}


def detect_ai_tools() -> List[str]:
    """检测已安装的 AI 工具，返回 tool_id 列表"""
    found = []
    for tool_id, config in AI_TOOL_CONFIGS.items():
        if tool_id == "generic":
            continue
        for path in config["detect_paths"]:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded) or (
                "*" in expanded and any(Path(expanded).parent.glob(Path(expanded).name))
            ):
                found.append(tool_id)
                break
    return found


def list_tools() -> None:
    """列出检测到的 AI 工具"""
    _header("检测到的 AI 工具")
    found = detect_ai_tools()
    if not found:
        _warn("未检测到已知 AI 工具")
        _info("支持的工具: Claude Code, Cursor, Cline (VS Code), Windsurf, Workbuddy, ZCode")
        _info("可使用 --tool generic 写入 mcp.json 到当前目录")
        return
    for tid in found:
        config = AI_TOOL_CONFIGS[tid]
        _ok(f"{config['name']} — 配置路径: {config['config_file']}")


def _build_server_config(project_root: str, rtlens_dir: str) -> Dict:
    """构建单个 MCP server 配置（command/args/cwd）。"""
    python_exe = sys.executable
    args = ["-m", "rtlens", "mcp"]
    if project_root:
        args.extend(["--root", project_root])
    server_config: Dict = {
        "command": python_exe,
        "args": args,
    }
    # 如果 rtlens 不是全局安装，设置 cwd（保证 -m 能找到包）
    if rtlens_dir and os.path.isdir(rtlens_dir):
        server_config["cwd"] = rtlens_dir
    return server_config


def generate_mcp_config(tool_id: str, project_root: str, rtlens_dir: str) -> Optional[Dict]:
    """生成 MCP 配置 JSON

    Args:
        tool_id: AI 工具 ID
        project_root: Verilog 工程根目录（用于自动索引）
        rtlens_dir: rtlens 安装目录（用于 pip install -e . 的位置）

    Returns:
        MCP 配置 dict，或 None 如果工具不支持
    """
    config = AI_TOOL_CONFIGS.get(tool_id)
    if not config:
        return None
    server_config = _build_server_config(project_root, rtlens_dir)
    if config.get("nested"):
        # ZCode 形态：{"mcp": {"servers": {"rtlens": {...}}}}，schema 严格
        server_config = {
            "type": "stdio",
            **server_config,
            "timeoutMs": 60000,
        }
        return {"mcp": {"servers": {"rtlens": server_config}}}
    return {"mcpServers": {"rtlens": server_config}}


def write_mcp_config(tool_id: str, project_root: str, rtlens_dir: str) -> Optional[str]:
    """写入 MCP 配置文件

    Returns:
        写入的文件路径，或 None 如果失败
    """
    config = AI_TOOL_CONFIGS.get(tool_id)
    if not config:
        _fail(f"未知工具: {tool_id}")
        return None

    new_config = generate_mcp_config(tool_id, project_root, rtlens_dir)
    if not new_config:
        return None

    # ZCode 等嵌套结构工具：合并进 mcp.servers，保留用户已有配置
    if config.get("nested"):
        return _write_nested_mcp_config(config, new_config)

    # 尝试各配置路径
    for path in config["config_paths"]:
        expanded = os.path.expanduser(path)
        # 创建父目录
        parent = os.path.dirname(expanded)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                continue
        
        # 读取已有配置并合并
        existing = {}
        if os.path.isfile(expanded):
            try:
                with open(expanded, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                _info(f"发现已有配置: {expanded}")
            except (json.JSONDecodeError, IOError):
                _warn(f"已有配置损坏，将覆盖: {expanded}")
        
        # 合并 mcpServers
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["rtlens"] = new_config["mcpServers"]["rtlens"]
        
        # 写入
        try:
            with open(expanded, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
                f.write("\n")
            _ok(f"MCP 配置已写入: {expanded}")
            return expanded
        except (IOError, OSError) as e:
            _warn(f"无法写入 {expanded}: {e}")
            continue
    
    _fail(f"无法写入任何配置路径")
    return None


def _write_nested_mcp_config(config: Dict, new_config: Dict) -> Optional[str]:
    """v6.1.0: 写入嵌套结构（ZCode）的 MCP 配置 — {"mcp": {"servers": {...}}}。

    与扁平 mcpServers 工具不同：只更新 mcp.servers.rtlens 一个键，
    用户已有的其他 server / 其他配置项原样保留。
    """
    for path in config["config_paths"]:
        expanded = os.path.expanduser(path)
        parent = os.path.dirname(expanded)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                continue
        existing: Dict = {}
        if os.path.isfile(expanded):
            try:
                with open(expanded, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                _info(f"发现已有配置: {expanded}")
            except (json.JSONDecodeError, IOError):
                _warn(f"已有配置损坏，将覆盖: {expanded}")
        # 深合并 mcp.servers.rtlens（不动其他键）
        mcp = existing.setdefault("mcp", {})
        if not isinstance(mcp, dict):
            _warn(f"{expanded} 中 mcp 字段不是对象，跳过该路径")
            continue
        servers = mcp.setdefault("servers", {})
        servers["rtlens"] = new_config["mcp"]["servers"]["rtlens"]
        try:
            with open(expanded, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
                f.write("\n")
            _ok(f"MCP 配置已写入: {expanded}")
            return expanded
        except (IOError, OSError) as e:
            _warn(f"无法写入 {expanded}: {e}")
            continue
    _fail(f"无法写入任何配置路径")
    return None


def find_project_root(start_dir: str = ".") -> Optional[str]:
    """自动检测 Verilog 工程根目录（含 .v/.sv 文件的目录）"""
    start = os.path.abspath(start_dir)
    
    # 向上查找含 .v/.sv 文件的目录
    current = start
    for _ in range(5):
        v_files = []
        try:
            for entry in os.listdir(current):
                if entry.endswith((".v", ".sv", ".vh", ".svh")):
                    v_files.append(entry)
        except OSError:
            break
        
        if v_files:
            return current
        
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    # 检查当前目录下是否有子目录含 .v 文件
    try:
        for entry in os.listdir(start):
            full = os.path.join(start, entry)
            if os.path.isdir(full):
                for sub in os.listdir(full):
                    if sub.endswith((".v", ".sv")):
                        return start
    except OSError:
        pass
    
    return None


def find_rtlens_dir() -> str:
    """找到 rtlens 包的安装目录"""
    try:
        import rtlens
        return os.path.dirname(os.path.dirname(rtlens.__file__))
    except ImportError:
        # 回退：当前文件的上上级目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def self_test(rtlens_dir: str) -> bool:
    """运行自测试：索引示例工程、查询符号、验证 MCP 工具可用"""
    _header("自测试")
    
    # 找到示例工程
    examples_dir = os.path.join(rtlens_dir, "examples")
    test_dir = None
    for candidate in ["soc_mini", "hierarchy", "counter"]:
        path = os.path.join(examples_dir, candidate)
        if os.path.isdir(path):
            test_dir = path
            break
    
    if not test_dir:
        # 使用 examples 本身
        if os.path.isdir(examples_dir):
            test_dir = examples_dir
        else:
            _warn("找不到示例工程，跳过自测试")
            return True  # 不算失败
    
    _info(f"测试目录: {test_dir}")
    
    # 测试 1: 索引
    try:
        result = subprocess.run(
            [sys.executable, "-m", "rtlens", "index", test_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30
        )
        if result.returncode == 0:
            output = result.stdout.decode(errors="replace")
            _ok(f"索引成功\n{output.strip()}")
        else:
            _fail(f"索引失败: {result.stderr.decode(errors='replace')[:200]}")
            return False
    except subprocess.TimeoutExpired:
        _fail("索引超时")
        return False
    
    # 测试 2: 查询符号
    try:
        result = subprocess.run(
            [sys.executable, "-m", "rtlens", "query", test_dir, "PLL"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15
        )
        if result.returncode == 0:
            output = result.stdout.decode(errors="replace")
            if "PLL" in output:
                _ok("符号查询成功")
            else:
                _warn("符号查询返回但未找到 PLL（可能示例不同）")
        else:
            _warn(f"符号查询失败（不影响核心功能）")
    except subprocess.TimeoutExpired:
        _warn("符号查询超时")
    
    # 测试 3: MCP 服务器响应（通过 stdio 模拟）
    _info("测试 MCP 服务器响应...")
    try:
        # 发送 initialize 请求并检查响应
        init_request = (json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"capabilities": {}}
        }) + "\n").encode("utf-8")
        
        result = subprocess.run(
            [sys.executable, "-m", "rtlens", "mcp", "--root", test_dir],
            input=init_request,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
        if result.returncode == 0 or result.stdout:
            try:
                response = json.loads(result.stdout.decode(errors="replace").strip().split("\n")[0])
                if response.get("id") == 1:
                    _ok("MCP 服务器响应正常")
                    # 测试 tools/list
                    list_request = (json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {}
                    }) + "\n").encode("utf-8")
                    result2 = subprocess.run(
                        [sys.executable, "-m", "rtlens", "mcp", "--root", test_dir],
                        input=init_request + list_request,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
                    )
                    lines = result2.stdout.decode(errors="replace").strip().split("\n")
                    for line in lines:
                        try:
                            resp = json.loads(line)
                            if resp.get("id") == 2 and "result" in resp:
                                tools = resp["result"].get("tools", [])
                                _ok(f"MCP 工具列表: {len(tools)} 个工具可用")
                                break
                        except json.JSONDecodeError:
                            continue
                else:
                    _warn("MCP 响应格式异常")
            except (json.JSONDecodeError, IndexError):
                _warn("MCP 响应解析失败（可能仍在运行）")
        else:
            _warn("MCP 服务器未返回数据（可能需要完整 JSON-RPC 会话）")
    except subprocess.TimeoutExpired:
        _warn("MCP 测试超时（服务器可能在等待更多输入，这是正常的）")
    except Exception as e:
        _warn(f"MCP 测试异常: {e}")
    
    return True


def print_summary(configs_written: List[str], project_root: Optional[str]) -> None:
    """打印安装摘要"""
    _header("安装摘要")
    
    print(f"  {'状态':12s} {_c('✓ 完成', 'green')}")
    print(f"  {'版本':12s} v{__get_version()}")
    
    if project_root:
        print(f"  {'工程目录':12s} {project_root}")
    
    if configs_written:
        print(f"\n  {_c('已写入 MCP 配置:', 'cyan')}")
        for path in configs_written:
            print(f"    {path}")
    else:
        _warn("未写入任何 MCP 配置")
    
    print(f"\n  {_c('下一步:', 'cyan')}")
    print(f"    1. 重启您的 AI 工具（Claude Code / Cursor / 等）")
    print(f"    2. 在 AI 中尝试: 「搜索 PLL 模块」或「检查端口连接」")
    print(f"    3. Web UI: python3 -m rtlens web --root {project_root or '.'}")
    print(f"    4. 实时监控: 打开 Web UI 后点击「📊 实时监控」标签")
    print()


def __get_version() -> str:
    try:
        from rtlens import __version__
        return __version__
    except ImportError:
        return "5.0.0"


def run_setup(
    tool: str = "auto",
    project_root: Optional[str] = None,
    pkg_dir: Optional[str] = None,
    skip_install: bool = False,
) -> bool:
    """主入口：执行完整安装配置流程
    
    Args:
        tool: AI 工具 ID（auto / claude-code / cursor / cline / windsurf / workbuddy / zcode / generic）
        project_root: Verilog 工程目录（None=自动检测）
        pkg_dir: rtlens 包目录（None=自动查找）
        skip_install: 跳过 pip install 步骤
    """
    print()
    print("  " + _c("╔══════════════════════════════════════════╗", "blue"))
    print("  " + _c("║        RTLens 自动配置向导 v5.0         ║", "blue"))
    print("  " + _c("╚══════════════════════════════════════════╝", "blue"))
    print()
    
    # 1. 环境检查
    _header("环境检查")
    if not check_python():
        return False
    
    if not check_pip():
        return False
    
    check_psutil()
    
    # 2. 安装检查
    _header("安装检查")
    if not check_rtlens_importable() and not skip_install:
        if not pkg_dir:
            pkg_dir = find_rtlens_dir()
        _info(f"安装目录: {pkg_dir}")
        if not install_rtlens(pkg_dir):
            _fail("安装失败，请手动运行: pip install -e .")
            return False
    elif skip_install:
        _info("跳过安装步骤")
    
    # Verible（可选）
    _header("可选依赖")
    check_verible()
    
    # 3. 工程目录检测
    _header("工程目录")
    if project_root:
        if os.path.isdir(project_root):
            _ok(f"指定目录: {project_root}")
        else:
            _warn(f"目录不存在: {project_root}，将自动检测")
            project_root = None
    
    if not project_root:
        detected = find_project_root()
        if detected:
            _ok(f"自动检测到: {detected}")
            project_root = detected
        else:
            _warn("未检测到 Verilog 工程目录")
            _info("MCP 启动后可通过 index_file 工具手动索引")
            _info("或运行: python3 -m rtlens setup --project /path/to/rtl")
    
    # 4. MCP 配置
    _header("MCP 配置")
    configs_written = []
    
    rtlens_dir = pkg_dir or find_rtlens_dir()
    
    if tool == "auto":
        detected_tools = detect_ai_tools()
        if not detected_tools:
            _warn("未检测到 AI 工具")
            _info("可用 --tool claude-code / cursor / cline / windsurf / workbuddy / zcode / generic 手动指定")
            _info("使用 generic 将在当前目录写入 mcp.json")
            detected_tools = ["generic"]
        
        for tid in detected_tools:
            config = AI_TOOL_CONFIGS.get(tid, {})
            _info(f"配置 {config.get('name', tid)}...")
            path = write_mcp_config(tid, project_root, rtlens_dir)
            if path:
                configs_written.append(path)
    else:
        config = AI_TOOL_CONFIGS.get(tool)
        if not config:
            _fail(f"未知工具: {tool}")
            _info(f"支持: {', '.join(AI_TOOL_CONFIGS.keys())}")
            return False
        _info(f"配置 {config['name']}...")
        path = write_mcp_config(tool, project_root, rtlens_dir)
        if path:
            configs_written.append(path)
    
    # 5. 自测试
    success = self_test(rtlens_dir)
    
    # 6. 摘要
    print_summary(configs_written, project_root)
    
    if success:
        print(f"  {_c('✓ 全部完成！', 'green')}\n")
    
    return success


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RTLens 自动配置")
    parser.add_argument("--tool", default="auto",
                        choices=["auto", "claude-code", "cursor", "cline", "windsurf", "workbuddy", "zcode", "generic"],
                        help="AI 工具 ID")
    parser.add_argument("--project", default=None, help="Verilog 工程目录")
    parser.add_argument("--pkg-dir", default=None, help="rtlens 包目录")
    parser.add_argument("--skip-install", action="store_true", help="跳过 pip install")
    parser.add_argument("--list-tools", action="store_true", help="列出检测到的工具")
    args = parser.parse_args()
    
    if args.list_tools:
        list_tools()
    else:
        run_setup(
            tool=args.tool,
            project_root=args.project,
            pkg_dir=args.pkg_dir,
            skip_install=args.skip_install,
        )
