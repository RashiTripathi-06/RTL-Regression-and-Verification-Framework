module tb_subtractor;

    reg [3:0] a, b;
    wire [4:0] diff;

    subtractor_4bit dut (
        .a(a),
        .b(b),
        .diff(diff)
    );

    integer i, j;
    integer errors;

    initial begin
        errors = 0;

        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                a = i;
                b = j;
                #1;

                if (diff !== ({1'b0, a} - {1'b0, b})) begin
                    errors = errors + 1;
                end
            end
        end

        if (errors == 0)
            $display("PASS: All 256 subtraction cases passed");
        else
            $display("FAIL: %0d mismatches", errors);

        $finish;
    end

endmodule