`timescale 1ns/1ps

// Deliberately incorrect interface: declared as 'adder' but has 8-bit sum instead of required 4-bit sum
module adder (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire       cin,
    output wire [7:0] sum,
    output wire       cout
);
    assign {cout, sum} = a + b + cin;
endmodule
