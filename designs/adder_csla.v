`timescale 1ns/1ps
// Dynamically added 4th implementation: Carry Select Adder
// Declares module name 'adder_csla' to demonstrate automatic discovery,
// compatibility matching, wrapper synthesis, and regression execution!
module adder_csla (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire       cin,
    output wire [3:0] sum,
    output wire       cout
);
    // Lower 2-bit ripple stage
    wire [1:0] sum_low;
    wire       c_mid;
    assign {c_mid, sum_low} = a[1:0] + b[1:0] + cin;

    // Upper 2-bit Carry Select stages (precomputed for c_mid=0 and c_mid=1)
    wire [1:0] sum_hi_0, sum_hi_1;
    wire       cout_0, cout_1;
    assign {cout_0, sum_hi_0} = a[3:2] + b[3:2] + 1'b0;
    assign {cout_1, sum_hi_1} = a[3:2] + b[3:2] + 1'b1;

    assign sum  = { (c_mid ? sum_hi_1 : sum_hi_0), sum_low };
    assign cout = c_mid ? cout_1 : cout_0;
endmodule