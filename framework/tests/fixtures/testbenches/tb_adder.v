`timescale 1ns/1ps

module tb_adder;
    reg  [3:0] a;
    reg  [3:0] b;
    reg        cin;
    wire [3:0] sum;
    wire       cout;

    reg [13:0] lut [0:511];
    integer i;

    adder dut (
        .a(a), .b(b), .cin(cin), .sum(sum), .cout(cout)
    );

    initial begin
        $display("=== TESTBENCH_START ===");
        $readmemh("adder_lut.mem", lut);
        for (i = 0; i < 512; i = i + 1) begin
            {a, b, cin} = lut[i][13:5];
            #1;
            $display("VEC idx=%0d a=%0d b=%0d cin=%0d sum=%b cout=%b",
                     i, a, b, cin, sum, cout);
        end
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
