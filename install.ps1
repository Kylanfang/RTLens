# ============================================================================
# RTLens 一键安装脚本 (PowerShell)
#
#   方式一（GitHub 一行命令，推荐）:
#     irm https://raw.githubusercontent.com/Kylanfang/RTLens/main/install.ps1 | iex
#
#   方式二（已下载仓库后本地运行）:
#     powershell -ExecutionPolicy Bypass -File install.ps1
#
#   可选参数（本地运行时）:
#     -ProjectRoot "D:\path\to\your\rtl"   要让 MCP 自动索引的 Verilog 工程目录
#     -Tool zcode                          只配置指定工具（zcode/claude-code/cursor/cline/windsurf/workbuddy/generic）
#     -InstallDir "$env:USERPROFILE\rtlens"  未在仓库内运行时的下载位置
#     -SkipPip                             跳过 pip install（直接以 cwd 方式运行）
#
# 脚本行为：
#   1. 定位/下载 RTLens 源码（仓库内运行则直接使用当前源码）
#   2. pip install -e .（失败不阻塞——RTLens 零依赖，cwd 方式也能跑）
#   3. python -m rtlens setup --tool <tool> --project <root>  自动写 MCP 配置并自测
# ============================================================================

param(
    [string]$ProjectRoot = "",
    [string]$Tool = "auto",
    [string]$InstallDir = "",
    [switch]$SkipPip
)

$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$RepoUrl = "https://github.com/Kylanfang/RTLens"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red }

# ---------- 1. 定位 Python ----------
Write-Step "检查 Python (需要 3.8+)"
$Python = $null
foreach ($cand in @("py -3", "python", "python3")) {
    try {
        $ver = (Invoke-Expression "$cand --version") 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 8) {
                # 解析为绝对路径，写入 MCP 配置时更稳
                $exe = (Invoke-Expression "$cand -c 'import sys;print(sys.executable)'") 2>$null
                if ($exe -and (Test-Path $exe)) { $Python = $exe } else { $Python = $cand }
                break
            }
        }
    } catch { continue }
}
if (-not $Python) {
    Write-Fail "未找到 Python 3.8+。请安装: https://www.python.org/downloads/"
    exit 1
}
$PythonFull = $Python
Write-Ok "Python: $PythonFull"

# ---------- 2. 定位 RTLens 源码 ----------
Write-Step "定位 RTLens 源码"
$RtlensRoot = $null
# 2a. 脚本自身在仓库内（下载/clone 后 -File 运行，或 iex 于仓库目录）
$scriptDir = if ($MyInvocation.MyCommand.Path) { Split-Path $MyInvocation.MyCommand.Path } else { (Get-Location).Path }
foreach ($cand in @($scriptDir, (Join-Path $scriptDir ".."), (Get-Location).Path)) {
    $candFull = [IO.Path]::GetFullPath($cand)
    if ((Test-Path (Join-Path $candFull "rtlens\__init__.py")) -and
        (Test-Path (Join-Path $candFull "pyproject.toml"))) {
        $RtlensRoot = $candFull; break
    }
}
# 2b. 不在仓库内 → clone 或下载 zip
if (-not $RtlensRoot) {
    if (-not $InstallDir) { $InstallDir = Join-Path $env:USERPROFILE "rtlens" }
    if (Test-Path (Join-Path $InstallDir "rtlens\__init__.py")) {
        $RtlensRoot = $InstallDir
        Write-Ok "使用已有目录: $RtlensRoot"
    } else {
        Write-Step "下载 RTLens 到 $InstallDir"
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            & git clone --depth 1 $RepoUrl $InstallDir
            if ($LASTEXITCODE -ne 0) { Write-Fail "git clone 失败"; exit 1 }
        } else {
            $zip = Join-Path $env:TEMP "rtlens-install.zip"
            Invoke-WebRequest -Uri "$RepoUrl/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
            $tmpExtract = Join-Path $env:TEMP "rtlens-install-extract"
            if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $tmpExtract -Force
            # zip 内通常是 RTLens-main/ 单层目录
            $inner = Get-ChildItem $tmpExtract | Select-Object -First 1
            New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
            if (Test-Path (Join-Path $inner.FullName "rtlens")) {
                Copy-Item (Join-Path $inner.FullName "*") $InstallDir -Recurse -Force
            } else {
                Copy-Item (Join-Path $tmpExtract "*") $InstallDir -Recurse -Force
            }
        }
        $RtlensRoot = $InstallDir
        if (-not (Test-Path (Join-Path $RtlensRoot "rtlens\__init__.py"))) {
            Write-Fail "下载内容里找不到 rtlens 包；请手动检查 $RtlensRoot"
            exit 1
        }
        Write-Ok "下载完成: $RtlensRoot"
    }
} else {
    Write-Ok "使用本地源码: $RtlensRoot"
}

# ---------- 3. 安装（零依赖，pip 失败不影响使用） ----------
if (-not $SkipPip) {
    Write-Step "pip install -e .（失败不阻塞——RTLens 纯标准库，cwd 方式也能运行）"
    try {
        & $PythonFull -m pip install -e $RtlensRoot --quiet 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Ok "pip 安装成功" } else { Write-Warn2 "pip 安装失败，将使用 cwd 方式运行（功能不受影响）" }
    } catch { Write-Warn2 "pip 不可用，将使用 cwd 方式运行（功能不受影响）" }
} else {
    Write-Step "跳过 pip（-SkipPip）"
}

# ---------- 4. 快速自检 ----------
Write-Step "自检"
# 注意：PowerShell 5.1 向原生进程传参会 mangle 内嵌双引号，
# 路径走环境变量、python 代码内只用单引号
$env:RTLENS_CHECK_PATH = $RtlensRoot
$verOut = & $PythonFull -c 'import os, sys; sys.path.insert(0, os.environ.get(''RTLENS_CHECK_PATH'')); import rtlens; print(rtlens.__version__)' 2>$null
if ($LASTEXITCODE -eq 0 -and $verOut) {
    Write-Ok "rtlens v$verOut 导入正常（零依赖模式可用）"
} else {
    Write-Fail "rtlens 导入失败，请把问题反馈到 $RepoUrl/issues"
    exit 1
}

# ---------- 5. 写入 MCP 配置 ----------
Write-Step "写入 MCP 配置 (tool=$Tool)"
$setupArgs = @("-m", "rtlens", "setup", "--tool", $Tool, "--pkg-dir", $RtlensRoot, "--skip-install")
if ($ProjectRoot) { $setupArgs += @("--project", $ProjectRoot) }
$setupProc = Start-Process -FilePath $PythonFull -ArgumentList $setupArgs -WorkingDirectory $RtlensRoot -NoNewWindow -Wait -PassThru
if ($setupProc.ExitCode -eq 0) {
    Write-Ok "配置完成"
} else {
    Write-Warn2 "自动配置未完全成功；可手动运行: $PythonFull -m rtlens setup"
}

# ---------- 6. 摘要 ----------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Ok "RTLens 安装完成"
Write-Host "  源码:   $RtlensRoot"
Write-Host "  Python: $PythonFull"
if ($ProjectRoot) { Write-Host "  工程:   $ProjectRoot" }
Write-Host ""
Write-Host "  下一步:" -ForegroundColor Cyan
Write-Host "   1. 重启你的 AI 工具（ZCode / Claude Code / Cursor 等）"
Write-Host "   2. 在 AI 中尝试: 「搜索 counter 模块」「检查端口连接」"
Write-Host "   3. Web 看板:  $PythonFull -m rtlens web -r <工程目录>"
Write-Host "   4. LSP 服务:  $PythonFull -m rtlens lsp"
Write-Host "================================================"
