// soc_mini.v — 迷你 SoC 子系统（v3.0 演示用）
// 包含：PLL、FIFO、UART_TX、寄存器堆、总线、顶层 SoC
// 用于展示 RTLens v3.0 的设计分析、模板生成、信号追踪等功能

// ============================================================
// Module: pll_wrapper
// ============================================================
module pll_wrapper (
    input  wire        clk_ref,
    input  wire        rst_n,
    output wire        clk_out,
    output wire        locked
);
    // Simplified PLL model
    assign clk_out = clk_ref;
    assign locked  = rst_n;
endmodule

// ============================================================
// Module: fifo_sync
// ============================================================
module fifo_sync #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              wr_en,
    input  wire  [WIDTH-1:0] wr_data,
    input  wire              rd_en,
    output wire  [WIDTH-1:0] rd_data,
    output wire              empty,
    output wire              full
);
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [$clog2(DEPTH)-1:0] wr_ptr, rd_ptr;
    reg [$clog2(DEPTH+1)-1:0] count;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= 0;
            count  <= 0;
        end else if (wr_en && !full) begin
            mem[wr_ptr] <= wr_data;
            wr_ptr <= (wr_ptr == DEPTH-1) ? 0 : wr_ptr + 1;
            count  <= count + 1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_ptr <= 0;
        end else if (rd_en && !empty) begin
            rd_ptr <= (rd_ptr == DEPTH-1) ? 0 : rd_ptr + 1;
            count  <= count - 1;
        end
    end

    assign rd_data = mem[rd_ptr];
    assign empty   = (count == 0);
    assign full    = (count == DEPTH);
endmodule

// ============================================================
// Module: uart_tx
// ============================================================
module uart_tx #(
    parameter CLK_FREQ = 50_000_000,
    parameter BAUD_RATE = 115200
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tx_start,
    input  wire [7:0]  tx_data,
    output reg         tx_busy,
    output reg         txd
);
    localparam CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;
    localparam IDLE = 0, START = 1, DATA = 2, STOP = 3;

    reg [1:0]  state;
    reg [15:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  data_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            tx_busy <= 0;
            txd     <= 1;
            clk_cnt <= 0;
            bit_idx <= 0;
        end else begin
            case (state)
                IDLE: begin
                    txd     <= 1;
                    tx_busy <= 0;
                    if (tx_start) begin
                        data_reg <= tx_data;
                        tx_busy  <= 1;
                        state    <= START;
                    end
                end
                START: begin
                    txd <= 0;
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 0;
                        state   <= DATA;
                    end else begin
                        clk_cnt <= clk_cnt + 1;
                    end
                end
                DATA: begin
                    txd <= data_reg[bit_idx];
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 0;
                        if (bit_idx == 7) begin
                            bit_idx <= 0;
                            state   <= STOP;
                        end else begin
                            bit_idx <= bit_idx + 1;
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 1;
                    end
                end
                STOP: begin
                    txd <= 1;
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 0;
                        tx_busy <= 0;
                        state   <= IDLE;
                    end else begin
                        clk_cnt <= clk_cnt + 1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

// ============================================================
// Module: reg_file
// ============================================================
module reg_file #(
    parameter ADDR_W = 4,
    parameter DATA_W = 32
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              wr_en,
    input  wire [ADDR_W-1:0] wr_addr,
    input  wire [DATA_W-1:0] wr_data,
    input  wire [ADDR_W-1:0] rd_addr,
    output wire [DATA_W-1:0] rd_data
);
    reg [DATA_W-1:0] regs [0:(1<<ADDR_W)-1];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integer i;
            for (i = 0; i < (1<<ADDR_W); i = i + 1)
                regs[i] <= 0;
        end else if (wr_en) begin
            regs[wr_addr] <= wr_data;
        end
    end

    assign rd_data = regs[rd_addr];
endmodule

// ============================================================
// Module: soc_mini (top)
// ============================================================
module soc_mini (
    input  wire        clk_ref,
    input  wire        rst_n,
    input  wire        uart_rx,       // (simulated as input for now)
    input  wire [7:0]  gpio_in,
    output wire        uart_txd,
    output wire [7:0]  gpio_out,
    output wire        pll_locked
);
    // Internal signals
    wire        clk_sys;
    wire        locked;
    wire [7:0]  fifo_rd_data;
    wire        fifo_empty, fifo_full;
    wire        tx_busy;
    wire [31:0] reg_rd_data;
    wire [7:0]  gpio_reg;

    // PLL
    pll_wrapper u_pll (
        .clk_ref   (clk_ref),
        .rst_n     (rst_n),
        .clk_out   (clk_sys),
        .locked    (locked)
    );

    // FIFO
    fifo_sync #(
        .WIDTH (8),
        .DEPTH (16)
    ) u_fifo (
        .clk     (clk_sys),
        .rst_n   (rst_n & locked),
        .wr_en   (1'b0),         // TODO: connect to bus
        .wr_data (gpio_in),
        .rd_en   (1'b0),         // TODO: connect to bus
        .rd_data (fifo_rd_data),
        .empty   (fifo_empty),
        .full    (fifo_full)
    );

    // UART TX
    uart_tx #(
        .CLK_FREQ  (50_000_000),
        .BAUD_RATE (115200)
    ) u_uart (
        .clk       (clk_sys),
        .rst_n     (rst_n & locked),
        .tx_start  (1'b0),
        .tx_data   (gpio_in),
        .tx_busy   (tx_busy),
        .txd       (uart_txd)
    );

    // Register file
    reg_file #(
        .ADDR_W (4),
        .DATA_W (32)
    ) u_regfile (
        .clk     (clk_sys),
        .rst_n   (rst_n & locked),
        .wr_en   (1'b0),
        .wr_addr (4'h0),
        .wr_data (32'h0),
        .rd_addr (4'h0),
        .rd_data (reg_rd_data)
    );

    assign gpio_out  = gpio_in ^ 8'hFF;  // Simple invert
    assign pll_locked = locked;

endmodule
