// defines.v — common macro definitions
`define WIDTH 8
`define MAX_COUNT 255
`define RESET_VAL 0

`ifdef SIMULATION
`define DELAY #1
`else
`define DELAY
`endif
