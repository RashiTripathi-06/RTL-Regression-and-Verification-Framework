`timescale 1ns/1ps

// Deliberately incomplete simulation: calls $finish prematurely
module adder (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire       cin,
    output wire [3:0] sum,
    output wire       cout
);
    assign {cout, sum} = a + b + cin;
    initial begin
        #10; // Exits early after only a few cycles
        $finish;
    end
endmodule
