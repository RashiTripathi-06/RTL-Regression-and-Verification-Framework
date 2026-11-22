`timescale 1ns/1ps

// 4-bit synchronous up/down counter with parallel load and active-low asynchronous reset
module counter_updown_4bit (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    input  wire       up_down,   // 1 = up, 0 = down
    input  wire       load,
    input  wire [3:0] data_in,
    output reg  [3:0] count,
    output wire       max_tick,
    output wire       min_tick
);
    assign max_tick = (count == 4'b1111) ? 1'b1 : 1'b0;
    assign min_tick = (count == 4'b0000) ? 1'b1 : 1'b0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 4'b0000;
        end else if (load) begin
            count <= data_in;
        end else if (en) begin
            if (up_down)
                count <= count + 1'b1;
            else
                count <= count - 1'b1;
        end
    end
endmodule
