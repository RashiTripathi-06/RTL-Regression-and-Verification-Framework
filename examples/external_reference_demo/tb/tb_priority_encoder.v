`timescale 1ns/1ps

module tb_priority_encoder;
    reg  [3:0] req;
    wire [1:0] grant;
    wire       valid;

    integer pass_count;
    integer fail_count;

    priority_encoder_4bit uut (
        .req(req),
        .grant(grant),
        .valid(valid)
    );

    initial begin
        $display("=== TESTBENCH_START ===");
        pass_count = 0;
        fail_count = 0;

        // Vector 1: No request active
        req = 4'b0000; #10;
        if (valid !== 1'b0) begin
            $display("[FAIL] req=0: valid should be 0, got %b", valid);
            fail_count = fail_count + 1;
        end else begin
            $display("[PASS] req=0: valid=0 as expected");
            pass_count = pass_count + 1;
        end

        // Vector 2: Bit 0 active
        req = 4'b0001; #10;
        if (valid !== 1'b1 || grant !== 2'b00) begin
            $display("[FAIL] req=1: expected grant=00, got %b", grant);
            fail_count = fail_count + 1;
        end else begin
            $display("[PASS] req=1: grant=00 valid=1");
            pass_count = pass_count + 1;
        end

        // Vector 3: Bit 3 active (highest priority)
        req = 4'b1001; #10;
        if (valid !== 1'b1 || grant !== 2'b11) begin
            $display("[FAIL] req=9: expected grant=11, got %b", grant);
            fail_count = fail_count + 1;
        end else begin
            $display("[PASS] req=9: grant=11 valid=1");
            pass_count = pass_count + 1;
        end

        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_count + fail_count, pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
