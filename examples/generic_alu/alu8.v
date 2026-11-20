module alu8 (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire [2:0] opcode,
    output reg  [7:0] result,
    output reg        zero,
    output reg        carry
);
    always @(*) begin
        carry = 1'b0;
        case (opcode)
            3'b000: {carry, result} = a + b;           // ADD
            3'b001: {carry, result} = a - b;           // SUB
            3'b010: result = a & b;                    // AND
            3'b011: result = a | b;                    // OR
            3'b100: result = a ^ b;                    // XOR
            3'b101: result = ~a;                       // NOT A
            3'b110: result = a << 1;                   // SLL
            3'b111: result = a >> 1;                   // SRL
            default: result = 8'h00;
        endcase
        zero = (result == 8'h00);
    end
endmodule
