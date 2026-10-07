// counter.v — simple parameterized counter with overflow flag
module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output wire [WIDTH-1:0] count,
    output wire             overflow
);

    reg [WIDTH-1:0] cnt_reg;
    wire [WIDTH-1:0] cnt_next;
    wire ovf_next;

    assign cnt_next = enable ? cnt_reg + 1'b1 : cnt_reg;
    assign overflow = (cnt_reg == {WIDTH{1'b1}}) & enable;
    assign count = cnt_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt_reg <= {WIDTH{1'b0}};
        else
            cnt_reg <= cnt_next;
    end

endmodule
