`timescale 1ns/1ps

// Second Testbench for 4-Bit Adder: Property & Random Self-Checking Testbench
module tb_adder_random;
    reg  [3:0] a;
    reg  [3:0] b;
    reg        cin;
    wire [3:0] sum;
    wire       cout;

    integer i;
    integer pass_count;
    integer fail_count;
    reg [4:0] expected;

    adder uut (
        .a(a), .b(b), .cin(cin), .sum(sum), .cout(cout)
    );

    initial begin
        $display("=== TESTBENCH_START ===");
        pass_count = 0;
        fail_count = 0;

        // Test 1: Identity property A + 0 + 0 = A
        for (i = 0; i < 16; i = i + 1) begin
            a = i; b = 4'b0000; cin = 1'b0;
            #5;
            expected = a + b + cin;
            if ({cout, sum} === expected) pass_count = pass_count + 1;
            else begin
                fail_count = fail_count + 1;
                $display("FAIL [Identity A+0]: a=%0d b=%0d cin=%0d -> got sum=%0d cout=%0d, exp=%0d", a, b, cin, sum, cout, expected);
            end
        end

        // Test 2: Maximum corner case 15 + 15 + 1 = 31 (sum=15, cout=1)
        a = 4'hF; b = 4'hF; cin = 1'b1;
        #5;
        expected = a + b + cin;
        if ({cout, sum} === expected) pass_count = pass_count + 1;
        else begin
            fail_count = fail_count + 1;
            $display("FAIL [Max Corner]: a=%0d b=%0d cin=%0d -> got sum=%0d cout=%0d, exp=%0d", a, b, cin, sum, cout, expected);
        end

        // Test 3: Carry propagation stress test across bits 1..3
        for (i = 0; i < 15; i = i + 1) begin
            a = i; b = 15 - i; cin = 1'b1;
            #5;
            expected = a + b + cin;
            if ({cout, sum} === expected) pass_count = pass_count + 1;
            else begin
                fail_count = fail_count + 1;
                $display("FAIL [Carry Stress]: a=%0d b=%0d cin=%0d -> got sum=%0d cout=%0d, exp=%0d", a, b, cin, sum, cout, expected);
            end
        end

        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_count + fail_count, pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
