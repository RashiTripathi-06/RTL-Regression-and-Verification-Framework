`timescale 1ns/1ps

// 4-bit Unsigned Multiplier
// Demonstrates Stage 3 NO MATCH handling (no matching testbench in project)
module multiplier_4bit (
    input  wire [3:0] a,
    input  wire [3:0] b,
    output wire [7:0] p
);
    assign p = a * b;
endmodule
