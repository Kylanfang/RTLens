# Third-Party Notices

## Verible

本仓库在 `rtlens/verible/` 目录捆绑了 Verible 的二进制可执行文件
（verible-verilog-syntax / verible-verilog-lint / verible-verilog-format），
用于增强语法检查、Lint 与格式化能力。这些二进制是**可选依赖**——
不存在时 RTLens 自动使用内置 Python 解析器，核心功能不受影响。

- 项目主页: https://github.com/chipsalliance/verible
- 版权所有: Copyright 2017-2023 Google Inc. / CHIPS Alliance
- 许可证: Apache License 2.0 — https://www.apache.org/licenses/LICENSE-2.0

Verible 以独立进程方式调用，不与 RTLens 的 Python 代码静态/动态链接。

## psutil（可选）

RTLens 代码本身零第三方依赖。性能监控面板在检测到 psutil 时启用进程级
内存/CPU 采样；未安装时自动降级，不影响任何核心功能。

- 项目主页: https://github.com/giampaolo/psutil
- 许可证: BSD 3-Clause
