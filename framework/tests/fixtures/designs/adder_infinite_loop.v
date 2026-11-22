`timescale 1ns/1ps

// Deliberately hangs simulation: zero-delay combinational loop triggers TIMEOUT
module adder (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire       cin,
    output wire [3:0] sum,
    output wire       cout
);
    reg osc;
    assign {cout, sum} = a + b + cin;
    initial begin
        osc = 0;
        forever osc = ~osc; // Infinite zero-delay loop
    end
endmodule
