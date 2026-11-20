`timescale 1ns/1ps

// 4-bit Arithmetic Logic Unit (Second DUT Architecture Family)
module alu_4bit (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire [2:0] opcode,
    output reg  [3:0] alu_out,
    output reg        cout,
    output wire       zero
);
    assign zero = (alu_out == 4'b0000);

    always @(*) begin
        cout = 1'b0;
        case (opcode)
            3'b000: {cout, alu_out} = a + b;           // ADD
            3'b001: {cout, alu_out} = {1'b0, a} - {1'b0, b}; // SUB
            3'b010: alu_out = a & b;                   // AND
            3'b011: alu_out = a | b;                   // OR
            3'b100: alu_out = a ^ b;                   // XOR
            3'b101: alu_out = ~a;                      // NOT A
            3'b110: {cout, alu_out} = {a, 1'b0};       // SHL
            3'b111: alu_out = a >> 1;                  // SHR
            default: alu_out = 4'b0000;
        endcase
    end
endmodule
