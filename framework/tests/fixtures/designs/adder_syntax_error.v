// Deliberately malformed design for COMPILE ERROR demonstration.
module adder(
    input wire [3:0] a,
    input wire [3:0] b,
    input wire cin,
    output wire [3:0] sum,
    output wire cout
);
    assign {cout, sum} = a + b + cin
endmodule
