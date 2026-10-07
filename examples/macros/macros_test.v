// macros_test.v — 宏预处理示例
// 测试 `define / `ifdef / `include 等编译器指令

`define BUS_WIDTH 32
`define ADDR_WIDTH 16
`define MAX_DEPTH 1024

`ifdef SIMULATION
    `define CLK_PERIOD 10
`else
    `define CLK_PERIOD 20
`endif

module macro_demo #(
    parameter DW = `BUS_WIDTH,
    parameter AW = `ADDR_WIDTH,
    parameter DEPTH = `MAX_DEPTH
) (
    input wire              clk,
    input wire              rst_n,
    input wire  [AW-1:0]    addr,
    input wire  [DW-1:0]    wdata,
    input wire              wen,
    output reg  [DW-1:0]    rdata,
    output reg              valid
);

    // 使用宏定义的时钟周期
    // `CLK_PERIOD 会被预处理器展开为 10 或 20

    reg [DW-1:0] mem [0:DEPTH-1];
    reg [AW-1:0]  rptr, wptr;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rptr <= 0;
            wptr <= 0;
            valid <= 1'b0;
        end else begin
            if (wen) begin
                mem[wptr] <= wdata;
                wptr <= wptr + 1;
            end
            rdata <= mem[rptr];
            rptr <= rptr + 1;
            valid <= 1'b1;
        end
    end

endmodule
