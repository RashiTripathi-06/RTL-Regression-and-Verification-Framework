module tb_multiplier;

    reg  [15:0] a, b;
    wire [15:0] product;

    multiplier dut (
        .opd_a(a),
        .opd_b(b),
        .product(product)
    );

    integer j;
    integer total_count, fail_count;
    integer logfile;

    initial begin
        $dumpfile("multiplier_exhaustive.vcd");
        $dumpvars(0, tb_multiplier);

        logfile = $fopen("fail_log.txt", "w");
        total_count = 0;
        fail_count = 0;

        a = 16'h4800;

        for (j = 0; j <= 16'hFFFF; j = j + 1) begin
            b = j[15:0];
            #1; 

            if (product === 16'hxxxx) begin
                $fdisplay(logfile, "FAIL (X): a=%h b=%h product=%h", a, b, product);
                fail_count = fail_count + 1;
            end

            total_count = total_count + 1;
        end

        $display("Sweep complete: %0d cases tested, %0d failures logged", total_count, fail_count);
        $fclose(logfile);
        $finish;
    end

endmodule