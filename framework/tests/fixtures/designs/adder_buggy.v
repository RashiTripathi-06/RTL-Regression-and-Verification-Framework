// Deliberately incorrect: carry propagation into bit 3 is missing.
module adder(
    input wire [3:0] a,
    input wire [3:0] b,
    input wire cin,
    output wire [3:0] sum,
    output wire cout
);
    wire [3:0] c;
    assign c[0] = cin;
    assign c[1] = (a[0] & b[0]) | ((a[0] ^ b[0]) & c[0]);
    assign c[2] = (a[1] & b[1]) | ((a[1] ^ b[1]) & c[1]);
    assign c[3] = (a[2] & b[2]); // intentional bug
    assign sum = a ^ b ^ c;
    assign cout = (a[3] & b[3]) | ((a[3] ^ b[3]) & c[3]);
endmodule
