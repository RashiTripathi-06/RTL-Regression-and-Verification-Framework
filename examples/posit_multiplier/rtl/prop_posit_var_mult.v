`timescale 1ns/1ps

module prop_posit_var_mult #(
    parameter N = 16,
    parameter ES = 2
) (
    input  [N-1:0] a,
    input  [N-1:0] b,
    output [N-1:0] result
);

    multiplier u_multiplier (
        .opd_a(a),
        .opd_b(b),
        .product(result)
    );

endmodule
