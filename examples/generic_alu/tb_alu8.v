`timescale 1ns/1ps

module tb_alu8;
    reg  [7:0] a;
    reg  [7:0] b;
    reg  [2:0] opcode;
    wire [7:0] result;
    wire       zero;
    wire       carry;

    alu8 uut (
        .a(a),
        .b(b),
        .opcode(opcode),
        .result(result),
        .zero(zero),
        .carry(carry)
    );

    integer pass_count = 0;
    integer fail_count = 0;

    task check_op(input [7:0] in_a, input [7:0] in_b, input [2:0] op, input [7:0] exp_res, input exp_zero);
        begin
            a = in_a;
            b = in_b;
            opcode = op;
            #5;
            if (result === exp_res && zero === exp_zero) begin
                pass_count = pass_count + 1;
            end else begin
                $display("ASSERTION FAILED @ %0t: a=%h b=%h op=%b -> got res=%h zero=%b, exp res=%h zero=%b",
                         $time, a, b, opcode, result, zero, exp_res, exp_zero);
                fail_count = fail_count + 1;
            end
        end
    endtask

    initial begin
        $display("=== TESTBENCH_START ===");
        
        // ADD
        check_op(8'h10, 8'h20, 3'b000, 8'h30, 1'b0);
        check_op(8'hFF, 8'h01, 3'b000, 8'h00, 1'b1);
        
        // SUB
        check_op(8'h50, 8'h20, 3'b001, 8'h30, 1'b0);
        check_op(8'h20, 8'h20, 3'b001, 8'h00, 1'b1);
        
        // AND / OR / XOR
        check_op(8'hAA, 8'h55, 3'b010, 8'h00, 1'b1);
        check_op(8'hAA, 8'h55, 3'b011, 8'hFF, 1'b0);
        check_op(8'hAA, 8'hFF, 3'b100, 8'h55, 1'b0);
        
        // NOT
        check_op(8'h00, 8'h00, 3'b101, 8'hFF, 1'b0);
        
        // SHIFT
        check_op(8'h01, 8'h00, 3'b110, 8'h02, 1'b0);
        check_op(8'h80, 8'h00, 3'b111, 8'h40, 1'b0);

        if (fail_count == 0) begin
            $display("ALL %0d TESTS PASSED", pass_count);
        end else begin
            $display("TESTS FAILED: %0d failed out of %0d", fail_count, (pass_count + fail_count));
        end

        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
