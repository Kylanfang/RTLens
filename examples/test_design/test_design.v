// test_design.v — RTLens MCP 工具测试专用工程
//
// 设计：一个简化的数据处理芯片，包含 ALU、寄存器堆、移位寄存器、流水线封装、顶层。
// 结构：
//   test_chip_top (顶层)
//     ├── pipeline_stage (流水线封装)
//     │     ├── alu_core (ALU)
//     │     └── register_file (寄存器堆)
//     └── shift_register (移位寄存器)
//
// 测试要点：
//   - 5 个模块 / 2 层层级 → analyze_design / get_design_metrics
//   - parameter + localparam 混用 → generate_instantiation（验证 localparam 被过滤）
//   - 多种端口方向和位宽 → get_module_info / generate_testbench
//   - 内部信号 clk_sys / alu_result / reg_rd → trace_signal
//   - shift_register 有一个故意留的未连接端口 → check_port_mismatches

// ============================================================
// Module: alu_core
// 功能：4 操作 ALU（ADD / SUB / AND / OR），带进位输出
// ============================================================
module alu_core #(
    parameter WIDTH = 8              // 数据位宽，可覆盖
) (
    input  wire [WIDTH-1:0]  a,      // 操作数 A
    input  wire [WIDTH-1:0]  b,      // 操作数 B
    input  wire [1:0]        op,     // 操作码
    output wire [WIDTH-1:0]  result, // 运算结果
    output wire              carry   // 进位/借位
);
    // localparam：不可覆盖，用于验证 generate_instantiation 正确过滤
    localparam OP_ADD = 2'b00;
    localparam OP_SUB = 2'b01;
    localparam OP_AND = 2'b10;
    localparam OP_OR  = 2'b11;

    // 组合逻辑
    assign {carry, result} = (op == OP_ADD) ? {1'b0, a + b} :
                             (op == OP_SUB) ? {1'b0, a - b} :
                             (op == OP_AND) ? {1'b0, a & b} :
                                             {1'b0, a | b};
endmodule

// ============================================================
// Module: register_file
// 功能：双端口寄存器堆（1 写 1 读）
// ============================================================
module register_file #(
    parameter ADDR_W = 4,           // 地址位宽（16 个寄存器）
    parameter DATA_W = 8            // 数据位宽
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              wr_en,
    input  wire [ADDR_W-1:0] wr_addr,
    input  wire [DATA_W-1:0] wr_data,
    input  wire [ADDR_W-1:0] rd_addr,
    output wire [DATA_W-1:0] rd_data
);
    reg [DATA_W-1:0] mem [0:(1<<ADDR_W)-1];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integer i;
            for (i = 0; i < (1<<ADDR_W); i = i + 1)
                mem[i] <= 0;
        end else if (wr_en) begin
            mem[wr_addr] <= wr_data;
        end
    end

    assign rd_data = mem[rd_addr];
endmodule

// ============================================================
// Module: shift_register
// 功能：参数化移位寄存器，支持并行加载和串行输出
// ============================================================
module shift_register #(
    parameter DEPTH = 4              // 移位深度
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        load_en,     // 并行加载使能
    input  wire [DEPTH-1:0] parallel_in, // 并行输入
    input  wire        shift_en,    // 移位使能
    output wire        serial_out,  // 串行输出
    output wire [DEPTH-1:0] current  // 当前移位寄存器值
    // 注意：这个模块多了一个 current 端口，顶层会故意不连它
    // 用于测试 check_port_mismatches 工具
);
    reg [DEPTH-1:0] data_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_reg <= 0;
        end else if (load_en) begin
            data_reg <= parallel_in;
        end else if (shift_en) begin
            data_reg <= data_reg >> 1;
        end
    end

    assign serial_out = data_reg[0];
    assign current    = data_reg;
endmodule

// ============================================================
// Module: pipeline_stage
// 功能：流水线封装，内部例化 alu_core 和 register_file
// ============================================================
module pipeline_stage #(
    parameter WIDTH = 8
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire [1:0]        op,
    input  wire              wr_en,
    input  wire [3:0]        wr_addr,
    input  wire [3:0]        rd_addr,
    output wire [WIDTH-1:0]  pipeline_out,
    output wire              alu_carry
);
    // ALU 结果寄存（流水线寄存器）
    wire [WIDTH-1:0] alu_result;
    reg  [WIDTH-1:0] alu_result_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            alu_result_reg <= 0;
        else
            alu_result_reg <= alu_result;
    end

    // 例化 ALU
    alu_core #(
        .WIDTH(WIDTH)
    ) u_alu (
        .a      (a),
        .b      (b),
        .op     (op),
        .result (alu_result),
        .carry  (alu_carry)
    );

    // 例化寄存器堆
    register_file #(
        .ADDR_W(4),
        .DATA_W(WIDTH)
    ) u_regfile (
        .clk     (clk),
        .rst_n   (rst_n),
        .wr_en   (wr_en),
        .wr_addr (wr_addr),
        .wr_data (alu_result_reg),
        .rd_addr (rd_addr),
        .rd_data (pipeline_out)
    );
endmodule

// ============================================================
// Module: test_chip_top (顶层)
// 功能：例化 pipeline_stage 和 shift_register
// ============================================================
module test_chip_top (
    input  wire        clk_ref,
    input  wire        rst_n,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    input  wire [1:0]  op,
    input  wire        wr_en,
    input  wire [3:0]  wr_addr,
    input  wire [3:0]  rd_addr,
    input  wire        shift_load,
    input  wire [3:0]  shift_data,
    input  wire        shift_en,
    output wire [7:0]  result_out,
    output wire        carry_out,
    output wire        shift_serial
);
    // 内部信号
    wire [7:0] pipeline_data;
    wire       alu_carry;

    // 例化流水线
    pipeline_stage #(
        .WIDTH(8)
    ) u_pipeline (
        .clk          (clk_ref),
        .rst_n        (rst_n),
        .a            (a),
        .b            (b),
        .op           (op),
        .wr_en        (wr_en),
        .wr_addr      (wr_addr),
        .rd_addr      (rd_addr),
        .pipeline_out (pipeline_data),
        .alu_carry     (alu_carry)
    );

    // 例化移位寄存器
    // 故意不连 current 端口 — 用于测试 check_port_mismatches
    shift_register #(
        .DEPTH(4)
    ) u_shift (
        .clk         (clk_ref),
        .rst_n       (rst_n),
        .load_en     (shift_load),
        .parallel_in (shift_data),
        .shift_en    (shift_en),
        .serial_out  (shift_serial)
        // .current 故意不连
    );

    assign result_out = pipeline_data;
    assign carry_out  = alu_carry;

endmodule
