`timescale 1ns/1ps

// Self-Checking Testbench for 4-bit ALU
module tb_alu;
    reg  [3:0] a;
    reg  [3:0] b;
    reg  [2:0] opcode;
    wire [3:0] alu_out;
    wire       cout;
    wire       zero;

    integer pass_count;
    integer fail_count;

    alu_4bit uut (
        .a(a),
        .b(b),
        .opcode(opcode),
        .alu_out(alu_out),
        .cout(cout),
        .zero(zero)
    );

    task check_alu;
        input [3:0] exp_out;
        input       exp_cout;
        input       exp_zero;
        input [127:0] test_name;
        begin
            #5;
            if ((alu_out === exp_out) && (cout === exp_cout) && (zero === exp_zero)) begin
                pass_count = pass_count + 1;
            end else begin
                fail_count = fail_count + 1;
                $display("FAIL [%0s]: got out=%b cout=%b zero=%b | exp out=%b cout=%b zero=%b",
                         test_name, alu_out, cout, zero, exp_out, exp_cout, exp_zero);
            end
        end
    endtask

    initial begin
        $display("=== TESTBENCH_START ===");
        pass_count = 0;
        fail_count = 0;

        // Opcode 000: ADD
        a = 4'd5; b = 4'd3; opcode = 3'b000;
        check_alu(4'd8, 1'b0, 1'b0, "ADD_NO_CARRY");

        a = 4'd12; b = 4'd7; opcode = 3'b000;
        check_alu(4'd3, 1'b1, 1'b0, "ADD_WITH_CARRY");

        // Opcode 001: SUB
        a = 4'd10; b = 4'd4; opcode = 3'b001;
        check_alu(4'd6, 1'b0, 1'b0, "SUB_NORMAL");

        a = 4'd5; b = 4'd5; opcode = 3'b001;
        check_alu(4'd0, 1'b0, 1'b1, "SUB_ZERO_FLAG");

        // Opcode 010: AND
        a = 4'b1100; b = 4'b1010; opcode = 3'b010;
        check_alu(4'b1000, 1'b0, 1'b0, "BITWISE_AND");

        // Opcode 011: OR
        a = 4'b1100; b = 4'b0011; opcode = 3'b011;
        check_alu(4'b1111, 1'b0, 1'b0, "BITWISE_OR");

        // Opcode 100: XOR
        a = 4'b1100; b = 4'b1010; opcode = 3'b100;
        check_alu(4'b0110, 1'b0, 1'b0, "BITWISE_XOR");

        // Opcode 101: NOT A
        a = 4'b1010; b = 4'b0000; opcode = 3'b101;
        check_alu(4'b0101, 1'b0, 1'b0, "BITWISE_NOT");

        // Opcode 110: SHL
        a = 4'b1011; b = 4'b0000; opcode = 3'b110;
        check_alu(4'b0110, 1'b1, 1'b0, "SHIFT_LEFT");

        // Opcode 111: SHR
        a = 4'b1010; b = 4'b0000; opcode = 3'b111;
        check_alu(4'b0101, 1'b0, 1'b0, "SHIFT_RIGHT");

        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_count + fail_count, pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
