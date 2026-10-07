// top.v — top-level module instantiating counter and sub
`include "defines.v"
`define CLK_FREQ 50000000

module top #(
    parameter CNT_WIDTH = 8
) (
    input wire        clk,
    input wire        rst_n,
    input wire        enable,
    output wire [CNT_WIDTH-1:0] count,
    output reg        overflow,
    output wire       led
);

    // Internal signals
    wire ovf_int;
    wire [CNT_WIDTH-1:0] cnt_int;

    // Instantiate counter
    counter #(
        .WIDTH(CNT_WIDTH)
    ) u_counter (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(cnt_int),
        .overflow(ovf_int)
    );

    // Instantiate sub module
    sub u_sub (
        .in_data(cnt_int),
        .out_data(led)
    );

    assign count = cnt_int;
    assign overflow = ovf_int;

endmodule
