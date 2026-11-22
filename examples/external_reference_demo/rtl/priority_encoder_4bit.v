module priority_encoder_4bit (
    input  wire [3:0] req,
    output reg  [1:0] grant,
    output reg        valid
);
    // 4-bit Priority Encoder:
    // Highest active bit of req determines grant[1:0].
    // If no request is active (req == 0), valid is 0.
    always @(*) begin
        if (req[3]) begin
            grant = 2'b11;
            valid = 1'b1;
        end else if (req[2]) begin
            grant = 2'b10;
            valid = 1'b1;
        end else if (req[1]) begin
            grant = 2'b01;
            valid = 1'b1;
        end else if (req[0]) begin
            grant = 2'b00;
            valid = 1'b1;
        end else begin
            grant = 2'b00;
            valid = 1'b0;
        end
    end
endmodule
