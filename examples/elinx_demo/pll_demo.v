// pll_demo.v — eLinx PLL demo instantiating GTP_PLL primitive
module pll_demo (
    input  wire clkin,
    input  wire rst_n,
    output wire clkout,
    output wire locked
);

    // GTP_PLL primitive instantiation
    GTP_PLL #(
        .FCLK("50"),
        .DUTY("50"),
        .CLKOS_DIV(2)
    ) u_pll (
        .CLKIN(clkin),
        .CLKFB(1'b0),
        .RESET(rst_n),
        .CLKFBSEL(1'b0),
        .USDYPHS(1'b0),
        .USDYSTEP(1'b0),
        .DPDYSTEP(1'b0),
        .DSDDYSTEP(1'b0),
        .PSDYSTEP(1'b0),
        .XSEL(1'b0),
        .PHASEBWD(1'b0),
        .PSDWEN(1'b0),
        .PSDN(1'b0),
        .DEVIATION(1'b0),
        .SSCDPHSEL(1'b0),
        .RESET_PSD(1'b0),
        .CLKSEL(1'b0),
        .CLKSWITCH(1'b0),
        .CLKOP(clkout),
        .LOCK(locked)
    );

endmodule
