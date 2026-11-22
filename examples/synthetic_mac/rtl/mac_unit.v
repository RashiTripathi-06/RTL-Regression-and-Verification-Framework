// 8-bit Multiply-Accumulate (MAC) Unit
// Computes: mac_out = (val_a * val_b) + acc_base
module mac_unit (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,
    input  wire [7:0]  val_a,
    input  wire [7:0]  val_b,
    input  wire [15:0] acc_base,
    output reg  [15:0] mac_out,
    output reg         ovf
);

    wire [15:0] mult_wire;
    wire [16:0] sum_wire;

    assign mult_wire = val_a * val_b;
    assign sum_wire = mult_wire + acc_base;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mac_out <= 16'h0000;
            ovf     <= 1'b0;
        end else if (en) begin
            mac_out <= sum_wire[15:0];
            ovf     <= sum_wire[16];
        end
    end

endmodule
