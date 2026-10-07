#!/usr/bin/env bash
# ============================================================================
# RTLens 一键安装脚本 (macOS / Linux)
#
#   方式一（GitHub 一行命令）:
#     curl -fsSL https://raw.githubusercontent.com/Kylanfang/RTLens/main/install.sh | bash
#
#   方式二（已下载仓库后本地运行）:
#     bash install.sh
#
#   环境变量:
#     RTLENS_PROJECT   要让 MCP 自动索引的 Verilog 工程目录（可选）
#     RTLENS_TOOL      只配置指定工具: zcode/claude-code/cursor/cline/windsurf/generic（默认 auto）
#     RTLENS_INSTALL_DIR  未在仓库内运行时的下载位置（默认 ~/rtlens）
#     RTLENS_SKIP_PIP  非空则跳过 pip install
# ============================================================================
set -euo pipefail

REPO_URL="https://github.com/Kylanfang/RTLens"
PYTHON=""
INSTALL_DIR="${RTLENS_INSTALL_DIR:-$HOME/rtlens}"
TOOL="${RTLENS_TOOL:-auto}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)"

say()  { printf '\n==> %s\n' "$1"; }
ok()   { printf '  [OK] %s\n' "$1"; }
warn() { printf '  [!!] %s\n' "$1"; }
fail() { printf '  [XX] %s\n' "$1"; exit 1; }

# ---------- 1. Python ----------
say "检查 Python (需要 3.8+)"
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            PYTHON="$cand"; break
        fi
    fi
done
[ -n "$PYTHON" ] || fail "未找到 Python 3.8+，请先安装"
ok "Python: $($PYTHON -c 'import sys; print(sys.executable)')"

# ---------- 2. 定位源码 ----------
say "定位 RTLens 源码"
RTLENS_ROOT=""
for cand in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$PWD"; do
    cand="$(cd "$cand" && pwd)"
    if [ -f "$cand/rtlens/__init__.py" ] && [ -f "$cand/pyproject.toml" ]; then
        RTLENS_ROOT="$cand"; break
    fi
done
if [ -z "$RTLENS_ROOT" ]; then
    say "下载 RTLens 到 $INSTALL_DIR"
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    else
        mkdir -p "$INSTALL_DIR"
        curl -fsSL "$REPO_URL/archive/refs/heads/main.zip" -o /tmp/rtlens-install.zip
        unzip -q -o /tmp/rtlens-install.zip -d /tmp/rtlens-install
        inner="$(find /tmp/rtlens-install -maxdepth 2 -name pyproject.toml -exec dirname {} \; | head -1)"
        cp -R "$inner"/. "$INSTALL_DIR"/
    fi
    RTLENS_ROOT="$INSTALL_DIR"
    [ -f "$RTLENS_ROOT/rtlens/__init__.py" ] || fail "下载内容里找不到 rtlens 包"
    ok "下载完成: $RTLENS_ROOT"
else
    ok "使用本地源码: $RTLENS_ROOT"
fi

# ---------- 3. pip 安装（可选） ----------
if [ -z "${RTLENS_SKIP_PIP:-}" ]; then
    say "pip install -e .（失败不阻塞——RTLens 纯标准库）"
    "$PYTHON" -m pip install -e "$RTLENS_ROOT" --quiet 2>/dev/null && ok "pip 安装成功" || warn "pip 安装失败，将使用 cwd 方式运行"
else
    say "跳过 pip（RTLENS_SKIP_PIP）"
fi

# ---------- 4. 自检 ----------
say "自检"
ver="$("$PYTHON" -c "import sys; sys.path.insert(0, '$RTLENS_ROOT'); import rtlens; print(rtlens.__version__)" 2>/dev/null)" \
    || fail "rtlens 导入失败"
ok "rtlens v$ver 导入正常"

# ---------- 5. 写入 MCP 配置 ----------
say "写入 MCP 配置 (tool=$TOOL)"
setup_args=(-m rtlens setup --tool "$TOOL" --pkg-dir "$RTLENS_ROOT" --skip-install)
if [ -n "${RTLENS_PROJECT:-}" ]; then
    setup_args+=(--project "$RTLENS_PROJECT")
fi
if (cd "$RTLENS_ROOT" && "$PYTHON" "${setup_args[@]}"); then
    ok "配置完成"
else
    warn "自动配置未完全成功；可手动运行: $PYTHON -m rtlens setup"
fi

# ---------- 6. 摘要 ----------
echo
echo "================================================"
ok "RTLens 安装完成"
echo "  源码:   $RTLENS_ROOT"
echo "  Python: $PYTHON"
[ -n "${RTLENS_PROJECT:-}" ] && echo "  工程:   $RTLENS_PROJECT"
echo
echo "  下一步:"
echo "   1. 重启你的 AI 工具（ZCode / Claude Code / Cursor 等）"
echo "   2. 在 AI 中尝试: 「搜索 counter 模块」「检查端口连接」"
echo "   3. Web 看板:  $PYTHON -m rtlens web -r <工程目录>"
echo "   4. LSP 服务:  $PYTHON -m rtlens lsp"
echo "================================================"
