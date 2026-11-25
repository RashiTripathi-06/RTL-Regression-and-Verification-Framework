module tb_prop_posit_var_mult;

    reg  [15:0] a, b;
    wire [15:0] result;

    // instantiating the top-level multiplier module
    prop_posit_var_mult #(16, 2) dut (
        .a(a),
        .b(b),
        .result(result)
    );

    integer j;
    integer total_count, fail_count;
    integer logfile;

    initial begin
        // $dumpfile("multiplier_exhaustive.vcd");
        // $dumpvars(0, tb_prop_posit_var_mult);

        logfile = $fopen("fail_log.txt", "w");
        total_count = 0;
        fail_count = 0;

        // a is constant (a=2)
        a = 16'h4800;

        // Vary operand B across all 65,536 combinations from 0000 to ffff
        for (j = 0; j <= 16'hFFFF; j = j + 1) begin
            b = j[15:0];
            #1; // small delay

            // errors
            if (result === 16'hxxxx) begin
                $fdisplay(logfile, "FAIL (X): a=%h b=%h result=%h", a, b, result);
                fail_count = fail_count + 1;
            end

            total_count = total_count + 1;

        end

        $display("Exhaustive 65k sweep complete: %0d cases tested, %0d failures logged", total_count, fail_count);
        $fclose(logfile);
        $finish;
    end

endmodule
