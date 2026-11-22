`timescale 1ns/1ps

module tb_mac_unit;
    reg        clk;
    reg        rst_n;
    reg        en;
    reg  [7:0] val_a;
    reg  [7:0] val_b;
    reg  [15:0] acc_base;
    wire [15:0] mac_out;
    wire       ovf;

    integer pass_count;
    integer fail_count;

    mac_unit dut (
        .clk(clk),
        .rst_n(rst_n),
        .en(en),
        .val_a(val_a),
        .val_b(val_b),
        .acc_base(acc_base),
        .mac_out(mac_out),
        .ovf(ovf)
    );

    always #5 clk = ~clk;

    initial begin
        $display("=== TESTBENCH_START ===");
        clk = 0;
        rst_n = 0;
        en = 0;
        val_a = 0;
        val_b = 0;
        acc_base = 0;
        pass_count = 0;
        fail_count = 0;

        #15 rst_n = 1;
        #10;

        // Vector 0: 3 * 4 + 10 = 22
        @(posedge clk);
        en = 1; val_a = 8'd3; val_b = 8'd4; acc_base = 16'd10;
        @(posedge clk);
        #1;
        if (mac_out === 16'd22 && ovf === 1'b0) begin
            $display("[PASS] Vector 0: 3*4+10 = 22 (mac_out=%0d, ovf=%0b)", mac_out, ovf);
            pass_count = pass_count + 1;
        end else begin
            $display("[FAIL] Vector 0: expected 22, got %0d", mac_out);
            fail_count = fail_count + 1;
        end

        // Vector 1: 10 * 20 + 100 = 300
        @(posedge clk);
        en = 1; val_a = 8'd10; val_b = 8'd20; acc_base = 16'd100;
        @(posedge clk);
        #1;
        if (mac_out === 16'd300 && ovf === 1'b0) begin
            $display("[PASS] Vector 1: 10*20+100 = 300 (mac_out=%0d, ovf=%0b)", mac_out, ovf);
            pass_count = pass_count + 1;
        end else begin
            $display("[FAIL] Vector 1: expected 300, got %0d", mac_out);
            fail_count = fail_count + 1;
        end

        // Vector 2: 255 * 255 + 0 = 65025
        @(posedge clk);
        en = 1; val_a = 8'd255; val_b = 8'd255; acc_base = 16'd0;
        @(posedge clk);
        #1;
        if (mac_out === 16'd65025 && ovf === 1'b0) begin
            $display("[PASS] Vector 2: 255*255+0 = 65025 (mac_out=%0d, ovf=%0b)", mac_out, ovf);
            pass_count = pass_count + 1;
        end else begin
            $display("[FAIL] Vector 2: expected 65025, got %0d", mac_out);
            fail_count = fail_count + 1;
        end

        // Vector 3: Overflow condition 255 * 255 + 1000 = 66025 -> mac_out = 489, ovf = 1
        @(posedge clk);
        en = 1; val_a = 8'd255; val_b = 8'd255; acc_base = 16'd1000;
        @(posedge clk);
        #1;
        if (mac_out === 16'd489 && ovf === 1'b1) begin
            $display("[PASS] Vector 3: 255*255+1000 = 66025 (mac_out=%0d, ovf=%0b)", mac_out, ovf);
            pass_count = pass_count + 1;
        end else begin
            $display("[FAIL] Vector 3: expected 489, got %0d", mac_out);
            fail_count = fail_count + 1;
        end

        $display("=== TESTBENCH_SUMMARY: total=4 pass=%0d fail=%0d ===", pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
