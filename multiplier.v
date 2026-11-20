module multiplier(input [15:0]opd_a , input [15:0]opd_b,output [15:0] product);
    wire sign_a,sign_b,sign_c;
    xor ( sign_c,sign_a,sign_b );
    wire [7:0] reg_ep_a,reg_ep_b;
    wire [7:0]reg_ep_c;
    assign reg_ep_a[7] = reg_ep_a[6];
    assign reg_ep_b[7] = reg_ep_b[6];
    wire [10:0] frac_opd_a,frac_opd_b,frac_opd_c;
    wire exp1;
    decoder decoder_A( opd_a , sign_a , reg_ep_a[6:0] , frac_opd_a );
    decoder decoder_B( opd_b , sign_b , reg_ep_b[6:0] , frac_opd_b );
    PLAM Posit_fact_multiplier( frac_opd_a ,  frac_opd_b,  frac_opd_c , exp1 );

    assign reg_ep_c = reg_ep_a + reg_ep_b + exp1 ;
    encoder encoder_Out( reg_ep_c , frac_opd_c , sign_c , product);
endmodule
