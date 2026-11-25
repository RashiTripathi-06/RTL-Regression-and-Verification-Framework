`timescale 1ns/1ps

module tb_posit_encoder_fully_exhaustive;

    reg        is_zero;
    reg        is_nar;
    reg        sign;
    reg  [4:0] regime_val;
    reg  [1:0] exponent;
    reg [10:0] fraction;

    wire [15:0] posit_out;

    posit_16_2_encoder uut (
        .is_zero(is_zero),
        .is_nar(is_nar),
        .sign(sign),
        .regime_val(regime_val),
        .exponent(exponent),
        .fraction(fraction),
        .posit_out(posit_out)
    );

    integer s, r, e, f;
    reg [31:0] vector_count;

    initial begin
        // $dumpfile("posit_encoder_fully_exhaustive.vcd");
        // $dumpvars(0, tb_posit_encoder_fully_exhaustive);

        vector_count = 0;

    
        // check exceptions
        is_zero = 1'b1; is_nar = 1'b0; sign = 1'b0; regime_val = 5'd0; exponent = 2'd0; fraction = 11'd0;
        #1;
        if (posit_out !== 16'h0000)
            $display("[FAIL] Zero check failed! Got %h (expected 0000)", posit_out);
        else
            $display("[PASS] Zero exception verified: posit_out = %h", posit_out);

        is_zero = 1'b0; is_nar = 1'b1; sign = 1'b0; regime_val = 5'd0; exponent = 2'd0; fraction = 11'd0;
        #1;
        if (posit_out !== 16'h8000)
            $display("[FAIL] NaR check failed! Got %h (expected 8000)", posit_out);
        else
            $display("[PASS] NaR exception verified: posit_out = %h", posit_out);

        // exhaustive loop
        is_zero = 1'b0;
        is_nar  = 1'b0;

        for (s = 0; s <= 1; s = s + 1) begin
            for (r = 0; r < 32; r = r + 1) begin
                for (e = 0; e < 4; e = e + 1) begin
                    for (f = 0; f < 2048; f = f + 1) begin
                        sign       = s[0];
                        regime_val = r[4:0];
                        exponent   = e[1:0];
                        fraction   = f[10:0];
                        
                        #1;
                        vector_count = vector_count + 1;
                    end
                end
            end
        end

        $display("Encoder sweep complete: %0d vectors processed.", vector_count);
        $finish;
    end

endmodule