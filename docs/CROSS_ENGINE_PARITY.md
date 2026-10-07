# 跨引擎等价性实测报告

> 目的:回答一个问题——**RTLens 索引与 hw-topo 内置扫描器,是不是同一份事实?**
> 这是 `rtlens.evidence/1` 契约(见 `EVIDENCE_CONTRACT.md`)能否成立的实证基础。
>
> 实测环境:RTLens v6.2.0 · hw-topo-dsh 内置扫描器 · 2026-10-06
> 命令:`rtlens evidence <root> --json` vs `scanRtl(<root>)`,同一棵树、逐元素比对。

## 0. 结论先行

| 维度 | 结论 |
|---|---|
| **坐标一致性** | **100%**。所有两边都报告的事实,`文件 + 行号`完全一致(274 个模块、约 490 个例化,0 处错位)。 |
| **模块覆盖** | **完全一致**。三套工程的模块数、逐模块行号全部相同。 |
| **例化覆盖** | 小幅、双向、且**全部可解释**(见 §2)。 |
| **未解析类型** | picorv32 差 1 个(死 `` `ifdef `` 区),ibex 与 verilog-ethernet 完全一致。 |

**即:契约成立。**坐标可以放心统一;剩余的差异是两套解析器的**已知边界**,不是缺陷。
但差异必须**显式可见**,不允许静默丢失——见 §3。

## 1. 实测数据

| 工程 | RTL 文件 | 模块 rtlens/builtin(完全一致) | 模块坐标错位 | 例化 rtlens/builtin(完全一致) | 例化坐标错位 | 未解析类型 rtlens/builtin(共享) |
|---|---|---|---|---|---|---|
| picorv32-main | 41 | 61 / 61 (61) | **0** | 108 / 106 (105) | **0** | 2 / 2 (1) |
| ibex-master | 33 | 30 / 30 (30) | **0** | 98 / 113 (98) | **0** † | 17 / 17 (17) |
| verilog-ethernet-master | 183 | 183 / 183 (183) | **0** | 247 / 247 (247) | **0** | 15 / 15 (15) |

† ibex 有一处例化(`prim_clock_gating cg_i`)两边报告的位置数不同:rtlens 报 1 处、builtin 报 4 处,
但**交集非空**(都包含 `:397`),属于覆盖差异而非坐标错位,详见 §2.1。

其中 verilog-ethernet(183 文件、183 模块、247 例化,真实量产 RTL)是**逐元素完全一致**,
包括全部行号——这是最强的等价性证据。

## 2. 覆盖差异:逐条溯源

### 2.1 ibex —— 生成块(generate loop)内的例化

```
 138:    for (genvar x = 1; x < 16; x++) begin : gen_data_cg_word_iter
 139:      prim_clock_gating cg_i (          <-- builtin 抓到,rtlens 未报
 ...
 150:    for (genvar x = 1; x < 16; x++) begin : gen_shared_cg_word_iter
 151:      prim_clock_gating cg_i (          <-- 同上
 ...
 364:    for (genvar x = 1; x < NUM_WORDS; x++) begin : gen_cg_word_iter
 365:      prim_clock_gating cg_i (          <-- 同上
 ...
 397:      prim_clock_gating cg_i (          <-- 两边都报,行号一致
```

- **rtlens 行为**:跳过 `for (genvar ...)` 生成块体内的例化(只报 397)。
  这与它的设计一致——**不做 elaboration**;生成块是 elaboration 范畴。
- **builtin 行为**:不区分作用域,4 处全报。
- **谁对?** 都对,是两个不同的取舍。但后果必须知道:**用 rtlens 作后端时,
  生成块内例化的模块(如 ibex 的时钟门控单元、`for (genvar)` 展开的存储体)
  不会出现在拓扑图里。**

### 2.2 picorv32 —— 死 `` `ifdef `` 区的例化

```
 223: `ifdef RISCV_FORMAL
 224:     picorv32_rvfimon rvfi_monitor (   <-- builtin 报为真实例化,rtlens 不报
```

- **builtin 行为**:容错提取,**不区分 `` `ifdef `` 是否激活**,从死分支里也提取(保守超集)。
  未定义 `RISCV_FORMAL` 时,这是一个**幽灵例化**。
- **rtlens 行为**:v6.1.0 起预处理器按行屏蔽未激活分支,因此正确地不报。
- **谁对?** **rtlens 对**。这是 rtlens 作为证据源的实质优势:它尊重编译配置
  (`-D` 参与求值),而不是把源码里所有可能存在的结构都倒出来。
  这也意味着同一个 root 在不同 `-D` 下**应当**得出不同事实——所以 `defines`
  必须随证据传递(契约 §2)。

### 2.3 picorv32 —— 数组化例化

- **rtlens 多报 3 处**(`SB_IO`、`ice40up5k_spram.memory` 等数组化形式),builtin 少报。
- 这与 hw-topo 文档化的边界一致:"数组例化 `u[3:0]` 少报(无误报)"。

### 2.4 差异一览

| 差异方向 | 场景 | 性质 |
|---|---|---|
| builtin 多报 | 死 `` `ifdef `` 区例化(picorv32 ×1) | **幽灵**,builtin 的已知保守行为 |
| builtin 多报 | `generate` 循环体内例化(ibex ×15) | 真实存在,rtlens 的设计取舍(不 elaboration) |
| rtlens 多报 | 数组化例化(picorv32 ×3) | 真实存在,builtin 的容错正则不足 |

**没有任何一条差异是"同一个事实被报成了不同行号"。**这正是契约要保证的东西。

## 3. 对耦合设计的要求(由此报告直接导出)

1. **后端身份必须进 provenance**:`backend: rtlens|builtin` 决定图里有什么、没有什么。
2. **降级必须显式**:`builtin` 只能视为兜底,不是等价替代——它会在死 `` `ifdef `` 区
   产生幽灵节点,而 rtlens 不会。回执/HTML/wiki 必须写明当前是哪个后端。
3. **差异应当可见**:既然两个后端都在本地,`scan` 可提供交叉核对
   (双后端各跑一次并 diff),把上表的三类差异作为**警告级 findings** 附在回执里,
   而不是让用户以为"图里没有就是不存"。这与 hw-topo 既有的
   `disclosed_unverified` 哲学一致:不猜、不静默、把不确定性摆到台面上。
4. **不要试图"融合"两个后端**:任何"取并集"的做法都会引入无法归因的证据,
   反而破坏可追溯性。正确做法是**选一个主后端 + 把差异如实披露**。

## 4. 复现方式

```bash
# 1) 取 RTLens 证据
python -m rtlens evidence <RTL根> --json --compact -o ev.json

# 2) 跨引擎比对（需 node；比对器在 tools/xengine-compare.mjs）
node tools/xengine-compare.mjs <RTL根> ev.json --scan-rtl <hw-topo>/skills/hw-topo/lib/scan-rtl.mjs
# 或用环境变量：HW_TOPO_HOME=<hw-topo-dsh 包根>
```

脚本退出码:0 = 坐标零错位;1 = 存在坐标错位;2 = 用法/IO 错误。
把它接进 CI 即可把"两个插件不兼容"这个 bug 永久钉死。

比对必须同时看两个指标,不可只看总数:
- `COORDINATE CHECK ... VIOLATIONS` —— **必须为 0**;非 0 就是契约被破坏(exit 1)。
- `only-rtlens / only-builtin / partial-overlap` —— 允许非 0,但每一条都要能归类到 §2.4 的某一类。

> **判定口径(避免误报的关键)**:只有当两个引擎对同一个身份(模块名或
> `父>类型.实例名`)报告的行号集合**完全不相交**时,才判为坐标错位——即"一方指向的位置
> 另一方从不指向",这正是 off-by-one 的形态(`{139,151}` vs `{140,152}`)。
> 若集合有交集、只是一方多报了几处,那是**覆盖差异**(生成块 / 死 `ifdef` / 数组化),
> 计入 `partial-overlap`,不判错位。
>
> 按此口径,§1 三套工程的 `VIOLATIONS` 均为 **0**;ibex 的 `prim_clock_gating`
> 属于 `partial-overlap`(交集 `{397}`,builtin 多报生成块内的 3 处)。

