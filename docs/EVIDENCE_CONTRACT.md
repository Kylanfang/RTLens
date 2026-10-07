# RTLens Evidence Contract v1

> **状态:冻结(frozen)** · schema id `rtlens.evidence/1` · 拥有者:RTLens
> 消费者:hw-topo(硬件拓扑 SVG 插件)、任何需要"同一份 RTL 事实"的下游工具。
>
> 本文件是两个 DSH 插件(rtlens / hw-topo)之间**唯一**的数据契约。改这里 = 改接口。

## 0. 为什么存在这份契约

rtlens 与 hw-topo 各自实现了一套"从 RTL 源码提取结构事实"的能力。两套实现的**事实一致**
(实测同一 fixture:3 文件 / 6 模块 / 7 例化,数字完全相同),但**坐标系统不同**:

| 事实 | hw-topo 内置扫描器 | RTLens 索引 |
|---|---|---|
| `module dma_engine` | `dma_engine.v:4` | `…\dma_engine.v:3` |
| `module hsb_top` | `hsb_top.v:6` | `…\hsb_top.v:5` |
| `instance hsb_top dut` | `dma_engine.v:50` | `…\dma_engine.v:49` |

即:**1-based + root 相对 POSIX** vs **0-based + 绝对 Windows 路径**。

后果不是"不好看",而是**致命**:把 rtlens 的行号直接喂进 hw-topo 的 `verify` 反幻觉门禁,
13 个元素全部判 `broken`,`hallucinationRisk = 1.0`,门禁拒绝交付(exit 1)——
**两个反幻觉门禁互相指控对方在造假,尽管底层事实完全一致。**

契约的作用:让坐标转换只发生**一次**,发生在唯一一处边界上,且**永不靠猜**。

## 1. 核心规则(硬性)

| # | 规则 | 违反后果 |
|---|---|---|
| **R1** | 行号**双基准同时给出**:`line0`(0-based,LSP/词法器原生)与 `line1`(1-based,编辑器/人类/hw-topo spec)。恒有 `line1 == line0 + 1`。 | 消费方各自假设基准 → 全局差 1 → 证据全废 |
| **R2** | 证据路径 `file` 恒为 **root 相对 POSIX**(正斜杠、无盘符、无前导 `/`、无 `..`)。绝对路径另有字段 `absPath`,不得混用。 | 跨机器/跨平台不可复现;`resolveInsideRoot` 拒绝读取 |
| **R3** | 每个源文件带 `sha256`(原始字节)。 | 无法检测源码漂移,`verify` 的 `broken` 判定失去依据 |
| **R4** | 证据中**禁止出现裸 `line` 字段**。消费方必须显式选 `line0` 或 `line1`。 | 默认值猜测 → 回到 R1 的坑 |
| **R5** | 同一个 spec 的 `scan` 与 `verify` **必须同后端**;后端身份写入 `provenance`。 | 两个后端交叉验证 → 假 `broken` 洪水 |
| **R6** | 降级**必须显式**:`provenance.degraded = true` + `reason`,并出现在回执、HTML、wiki 中。 | 静默降级 = 用户以为拿到了索引级证据,实际是正则级 |

### 关于 R1 的强制做法

`line1` 不是"转换出来的方便字段",而是**契约的一部分**:生产者必须同时产出两者,
消费者必须挑一个并**写明挑了哪个**。这样任何一方都无法"默认"成错误的基准。

## 2. `rtlens.evidence/1` 结构

由 `python -m rtlens evidence <root> --json` 产出。

```jsonc
{
  "schema": "rtlens.evidence/1",
  "tool": { "name": "rtlens", "version": "6.2.0" },
  "root": { "abs": "D:\\proj", "separator": "\\" },
  "generatedAt": "2026-10-06T03:36:04.483Z",
  "defines": { "SIM": "1" },              // 参与 `ifdef 求值;索引结果随 define 集变化
  "stats": {
    "files": 3, "modules": 6, "ports": 29, "signals": 11,
    "params": 4, "instances": 7, "interfaces": 0, "packages": 0,
    "topModules": ["tb_hsb_top"]
  },
  "files": [
    { "path": "dma_engine.v", "absPath": "D:\\proj\\dma_engine.v",
      "bytes": 1431, "lines": 61, "sha256": "<64 hex>" }
  ],
  "modules": [
    {
      "name": "dma_engine", "kind": "module", "role": "leaf-or-mid",
      "file": "dma_engine.v",
      "line0": 3, "line1": 4,                 // module 声明行
      "endLine0": 40, "endLine1": 41,         // endmodule 行
      "portCount": 7,
      "definitions": 1,                       // 同名多定义时的总数
      "ports":  [ { "name": "clk_i", "direction": "input", "width": "",
                    "dataType": "wire", "detail": "input wire clk_i",
                    "line0": 4, "line1": 5 } ],
      "params": [ { "name": "W", "detail": "parameter W = 8", "line0": 7, "line1": 8 } ],
      "signals":[ { "name": "state", "detail": "reg [1:0] state", "line0": 12, "line1": 13 } ],
      "instantiatedBy": ["tb_hsb_top"],
      "instances": [                          // 嵌套便利视图,条目与顶层 instances[] 同构
        { "parent": "dma_engine", "type": "fifo_sync", "instance": "u_fifo",
          "file": "dma_engine.v",
          "line0": 25, "line1": 26, "endLine0": 27, "endLine1": 28,
          "resolution": "declared", "connectionCount": 4,
          "connections": [ { "port": "clk_i", "signal": "clk_i",
                             "line0": 25, "line1": 26 } ] }
      ]
    }
  ],
  "instances": [                              // 权威全量列表;消费方优先用它
    { "parent": "hsb_top", "type": "dma_engine", "instance": "u_dma",
      "file": "hsb_top.v", "line0": 50, "line1": 51,
      "endLine0": 55, "endLine1": 56,
      "resolution": "declared",              // declared | vendor-primitive | external
      "connectionCount": 4,
      "connections": [ /* 同上 */ ] }
  ],
  "unresolved": [
    { "type": "SB_IO", "classification": "vendor-primitive",   // vendor-primitive | unknown(仅两档)
      "file": "port_bench.v", "line0": 25, "line1": 26,
      "count": 1, "parents": ["port_bench"],
      "suggestions": ["SB_IO_OD"] }          // 可选:相似名建议
  ],
  "diagnostics": {
    "parseErrors": 0,
    "elaborated": false,
    "signalsTruncatedModules": 0,             // 仅为可读性汇总;权威标记在各元素上
    "connectionsTruncatedInstances": 0        // 同上,与 signals 汇总对称
  }
}
```

### 字段语义要点

- `role`:`top`(无人例化)/ `leaf-or-mid`(被例化)。纯启发式,由"谁例化了谁"决定。
- `resolution`:`declared` = 类型在本树内有定义;`vendor-primitive` = 命中厂商原语模式;
  `external` = 树外未知依赖(如 OpenTitan `prim_*`、`sky130_*` 之外的第三方 IP)。
  **`external` / `vendor-primitive` 不是错误**,是如实分类。
  RTLens 内部枚举是 `workspace|vendor_primitive|unknown`,契约枚举是
  `declared|vendor-primitive|external`;这是**固定名字映射**,不是猜测。
- ⚠️ **两个枚举必须分清**(实现中最易写错处):

  | 字段 | 取值 | 含义 |
  |---|---|---|
  | `instances[].resolution` | `declared` \| `vendor-primitive` \| `external` | **该例化点的类型**能否在本树内找到定义 |
  | `unresolved[].classification` | `vendor-primitive` \| `unknown` | **未解析类型本身**的归类(只有两档;能解析的类型根本不会出现在 `unresolved` 里) |

  二者名字相似但定义域不同:`resolution` 有三档,`classification` 只有两档。
  适配器必须分别校验取值,不接受越界值。
- 可选字段(生产者**有则给、无则省略**,消费方必须容忍缺失):
  `ports[]/params[]/signals[].detail`(原始源码文本片段)、
  `unresolved[].suggestions`(相似名建议)、
  `files[]/modules[]/instances[]` 上的截断标记(见下)。
- **截断必须显式**:单模块 `signals` 超过 `--max-signals`(默认 256)时,
  该模块带 `"signalsTruncated": true`;单个例化的连接超过 `--max-connections`
  (默认 256)时带 `"connectionsTruncated": true`。两个上限各有一个
  `diagnostics` 汇总(`signalsTruncatedModules` / `connectionsTruncatedInstances`),
  汇总为 0 表示**这批上限内没截断**,不代表元素级标记可以省略。
  `connectionCount` 恒为**真实总数**(不是数组长度),
  因此消费方可以据此判断自己是否看到了全部。**任何静默截断都是契约违反。**
- `connections[].port` 在**位置连接**时为空字符串(如 `fifo u(.a(x))` 之外的 `fifo u(x, y)`)。
  这是如实转录,不得靠猜补出端口名。
- `diagnostics.outsideRootFiles` / `outsideRootCount`:**仅当**有 root 之外的文件被索引时出现
  (例如 `-I` 引入的外部 include)。这些文件被整体排除出 `files[]/modules[]/instances[]`
  ——因为它们的证据指针无法被下游的 `resolveInsideRoot` 解析——并在此如实计数。
  出现该字段说明证据覆盖**不完整**,消费方应据此提示用户。
- `diagnostics.filesCapped`:**仅当**索引因为 `--max-files` 上限提前停止时出现
  (值恒为 `true`)。它与 `outsideRootFiles` 是同一类事实:覆盖**不完整**。
  `stats.files == --max-files` 并不足以判断——工程恰好只有上限那么多文件时不算截断,
  因此生产者必须精确识别"确实还有第 N+1 个文件"才置位。**不得靠猜。**
- `modules[].instances[]` 与顶层 `instances[]` **同构同字段**(都用 `instance` 表示实例名):
  顶层是权威全量列表,嵌套视图只是按父模块分组的便利投影。消费方**优先用顶层**。
- **实例行号的精确定义**(实测踩过,必须统一):`instances[].line0/line1` =
  实例化**语句起始行,即类型 token 所在行**,**不是**实例名所在行。参数化例化写成多行时两者不同:

  ```verilog
  21:     counter #(            <-- line0=20 / line1=21  证据指向这一行
  22:         .WIDTH(CNT_WIDTH)
  23:     ) u_counter (         <-- 实例名在这一行
  24:         .clk(clk),
  ```

  两个生产者(rtlens 索引 / hw-topo 内置扫描器)都取类型 token 行,因此**天然一致**;
  但任何新消费者若假设"指向实例名那行"就会得到错位的证据。实例名可通过
  `instance` 字段取到,无需从行号反推。
- `endLine0/endLine1` = 该例化语句的收尾行(连接列表右括号所在行),
  恒有 `line0 <= endLine0`。模块的 `endLine0` = `endmodule` 所在行。
- `defines` / 索引行为:`` `ifdef`` 的求值依赖 `-D`;不同的 define 集**会产生不同的索引结果**。
  因此 `defines` 必须随证据一起传递,并进入下游的 `provenance`——否则同一个 root 会得出
  两份不同的"事实"。
- `definitions > 1`:同名模块多处定义(PicoRV32 的 `top` 有 4 处)。hw-topo 侧取首个定义,
  `verify` 按"候选集"匹配而非单点匹配。
- `diagnostics.elaborated` 恒为 `false`:**不做 elaboration**。参数化位宽保持源码文本
  (`[W-1:0]`),宽度是否匹配由 verilator/yosys 判定,不是本契约的职责。

## 3. hw-topo bundle 映射(适配器职责)

hw-topo 内部证据包(bundle)结构保持不变,由适配器从 `rtlens.evidence/1` **纯转录**得到:

| bundle 字段 | 来源 | 转换 |
|---|---|---|
| `modules[].line` | `modules[].line1` | 直取(禁止 `line0 + 1` 之外的运算) |
| `modules[].endLine` | `modules[].endLine1` | 直取 |
| `modules[].file` | `modules[].file` | 直取(已是 root 相对 POSIX) |
| `modules[].ports` | `modules[].ports[].name` | 取名字数组 |
| `modules[].params` | `modules[].params[].name` | 取名字数组 |
| `instantiations[]` | `instances[]` | `{parent,type,instance,file,line: line1}` |
| `unresolved[]` | `unresolved[]` | `classification` 直传 |
| `files[]` | `files[]` | `path`/`bytes`/`lines`/`sha256` 直取 |
| `stats.*` | `stats.*` | `instantiations←instances`,`unresolvedVendor/Unknown←unresolved` 计数 |
| `provenance` | 新增 | 见 §4 |

**适配器不得引入任何启发式**:不做正则补扫、不做名称归一化、不猜缺失字段。
转录不完整就报错退出,而不是"尽力而为"。

## 4. provenance(可追溯性)

两个方向都要记录,并进入 `spec.meta.derivedFrom` 与 `receipt`:

```jsonc
"provenance": {
  "backend": "rtlens",              // rtlens | builtin
  "degraded": false,
  "reason": null,                   // degraded=true 时必填
  "evidenceSchema": "rtlens.evidence/1",
  "tool": { "name": "rtlens", "version": "6.2.0" },
  "defines": { "SIM": "1" },
  "rootAbs": "D:\\proj"
}
```

降级场景:`rtlens` 不可用(python 缺失 / 版本不符 / CLI 失败)时回落到内置正则扫描器,
此时:

```jsonc
{ "backend": "builtin", "degraded": true,
  "reason": "rtlens unavailable: python not on PATH",
  "evidenceSchema": null }
```

**降级 = 证据等级下降**(正则容错提取 vs 位置不变的词法解析 + 引用追踪)。
hw-topo 是 hw-topo 的兜底,不是等价替代;回执、HTML 横幅、wiki 页眉都必须写明。

## 5. 版本与兼容

- `schema` 字符串是**唯一**的漂移守卫。适配器启动时断言:
  - 不匹配 `rtlens.evidence/1` → **拒绝**(exit 2),不尝试兼容解析。
  - `rtlens` 主版本升级需同步升 schema 号(`rtlens.evidence/2`)。
- 新增**可选**字段不需要升号;消费方必须容忍未知字段。
- 删除/改义字段必须升号。
- 契约双方各自保留一份本文件;RTLens 仓库内这份是**规范版本(canonical)**。

## 6. 负面测试(必须长期保持)

`verify` 门禁的 off-by-one 回归:把一份通过验证的 spec 的 `line` 全部减 1、`file` 换成绝对
Windows 路径(= 模拟"没走适配器、直接把 rtlens 坐标灌进 spec"),`verify` **必须**失败:

```
elements 13 · backed 0 · broken 13 · hallucinationRisk 1.0 · exit 1
```

这条测试是把"不兼容"钉死不再复发的锚点。它存在的原因就是本文件 §0 那张表。
