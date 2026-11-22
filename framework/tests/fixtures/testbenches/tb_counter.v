`timescale 1ns/1ps

// Testbench for 4-bit Synchronous Up/Down Counter with Reference Vector Loading
module tb_counter;
    reg        clk;
    reg        rst_n;
    reg        en;
    reg        up_down;
    reg        load;
    reg  [3:0] data_in;
    wire [3:0] count;
    wire       max_tick;
    wire       min_tick;

    // Reference vectors loaded via $readmemh
    reg [15:0] ref_vectors [0:25];
    integer i;
    integer pass_count;
    integer fail_count;

    reg [3:0] exp_count;
    reg       exp_max;
    reg       exp_min;

    // DUT instantiation
    counter_updown_4bit uut (
        .clk(clk),
        .rst_n(rst_n),
        .en(en),
        .up_down(up_down),
        .load(load),
        .data_in(data_in),
        .count(count),
        .max_tick(max_tick),
        .min_tick(min_tick)
    );

    // 10ns Clock generation
    always #5 clk = ~clk;

    initial begin
        clk = 0;
        pass_count = 0;
        fail_count = 0;

        $display("=== TESTBENCH_START ===");
        $readmemh("counter_ref.mem", ref_vectors);

        for (i = 0; i < 26; i = i + 1) begin
            // Extract stimulus
            rst_n   = ref_vectors[i][15];
            en      = ref_vectors[i][14];
            up_down = ref_vectors[i][13];
            load    = ref_vectors[i][12];
            data_in = ref_vectors[i][11:8];

            // Extract expected responses
            exp_count = ref_vectors[i][7:4];
            exp_max   = ref_vectors[i][3];
            exp_min   = ref_vectors[i][2];

            // Synchronize with clock edge
            @(posedge clk);
            #1; // Settling time

            // Verification check
            if (count === exp_count && max_tick === exp_max && min_tick === exp_min) begin
                pass_count = pass_count + 1;
            end else begin
                fail_count = fail_count + 1;
                $display("FAIL [vec %0d]: expected count=%0d max=%b min=%b, got count=%0d max=%b min=%b",
                         i, exp_count, exp_max, exp_min, count, max_tick, min_tick);
            end

            $display("VEC idx=%0d clk=%b rst_n=%b en=%b up_down=%b load=%b data_in=%0d count=%0d max_tick=%b min_tick=%b",
                     i, clk, rst_n, en, up_down, load, data_in, count, max_tick, min_tick);
        end

        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_count + fail_count, pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
