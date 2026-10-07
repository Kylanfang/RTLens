// sub.v — simple pass-through with registered output
module sub (
    input  wire [7:0] in_data,
    output wire       out_data
);

    reg out_reg;

    assign out_data = out_reg;

    always @(*) begin
        out_reg = in_data[0];
    end

endmodule
