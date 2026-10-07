// positional_demo.v — 演示按位置连接的端口（用于 inlay hints 功能）
// 下方实例化 counter 时使用按位置连接（无 .port_name），
// LSP inlay hints 会在此处显示 .clk、.rst_n 等端口名提示

module positional_demo (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  data_in,
    output wire [7:0]  data_out
);

    // 按位置连接实例化（无 .port_name）
    // inlay hints 会在每一行显示对应的端口名
    counter u_counter (
        clk,            // inlay hint: .clk
        rst_n,          // inlay hint: .rst_n
        1'b1,           // inlay hint: .en
        data_in,        // inlay hint: .data_in
        data_out        // inlay hint: .data_out
    );

endmodule
