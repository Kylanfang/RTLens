// counter.v — 参数化计数器示例（RTLens 演示工程）
// 与 examples/hierarchy/top.v 配套：top.v 例化了本模块。

module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output reg  [WIDTH-1:0] count,
    output reg              overflow
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count    <= {WIDTH{1'b0}};
            overflow <= 1'b0;
        end else if (enable) begin
            if (count == {WIDTH{1'b1}}) begin
                count    <= {WIDTH{1'b0}};
                overflow <= 1'b1;
            end else begin
                count    <= count + 1'b1;
                overflow <= 1'b0;
            end
        end
    end

endmodule
