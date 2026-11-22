`timescale 1ns/1ps

// Incompatible testbench expecting a 32-bit DSP multiply-accumulate unit
module tb_incompatible;
    reg clk, rst;
    reg [31:0] operand_a, operand_b;
    wire [63:0] mac_acc_out;

    dsp_mac_unit uut (
        .clk(clk),
        .rst(rst),
        .operand_a(operand_a),
        .operand_b(operand_b),
        .mac_acc_out(mac_acc_out)
    );

    initial begin
        $display("=== TESTBENCH_START ===");
        #50;
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
