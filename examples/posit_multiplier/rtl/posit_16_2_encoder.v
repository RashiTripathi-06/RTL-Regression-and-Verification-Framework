`timescale 1ns/1ps

module posit_16_2_encoder (
    input         is_zero,
    input         is_nar,
    input         sign,
    input  [4:0]  regime_val,
    input  [1:0]  exponent,
    input  [10:0] fraction,
    output [15:0] posit_out
);
    wire [15:0] normal_out;
    // reg_ep: [7:2] is 6-bit regime, [1:0] is 2-bit exponent
    wire [7:0] reg_ep = {1'b0, regime_val, exponent};

    encoder core_encoder (
        .reg_ep(reg_ep),
        .sum(fraction),
        .sign(sign),
        .product(normal_out)
    );

    // Handle Posit special exception cases:
    // 1. Zero Exception -> 16'h0000
    // 2. NaR (Not a Real) Exception -> 16'h8000
    assign posit_out = is_zero ? 16'h0000 :
                       is_nar  ? 16'h8000 :
                       normal_out;

endmodule
