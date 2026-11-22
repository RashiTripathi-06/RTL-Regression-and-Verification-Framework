// Deliberately invalid: sum[3] is unknown (X).
module adder(
    input wire [3:0] a,
    input wire [3:0] b,
    input wire cin,
    output wire [3:0] sum,
    output wire cout
);
    wire [4:0] tmp;
    assign tmp = a + b + cin;
    assign sum = {1'bx, tmp[2:0]};
    assign cout = tmp[4];
endmodule
