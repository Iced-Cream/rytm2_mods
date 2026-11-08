# vd_bitexact

Checks that a change to voice-dac's audio-interrupt code keeps its output byte for byte. It extracts the
pan pass, the 1-pole pair, `bq_run` and the sum from two versions of `voice-dac/os1.74/voice-dac.s` (a git
ref and the working tree) into one standalone harness each (`gen.py`). Both harnesses run on the same
random blocks (`drive.py`): voices, PRE words, VCA words, slot map, owners, POL, the main-bus mask, and
1-pole and biquad coefficients, with extreme values. The state (filter states, `pan_cache`) carries over
between blocks, and every output byte of every block is compared.

The harness runs in `cfsim.py`, a small interpreter of the ColdFire V4e instructions these paths use,
taken from objdump's disassembly. Its EMAC is fractional, saturating and truncating (MACSR 0xa0).
`SAT32=1` swaps its 48-bit accumulator for one that clamps at full scale after each step, so the result
doesn't rest on one reading of the EMAC's saturation. (QEMU 8.2's `cfv4e` decodes `mac` with a `d16(Ay)`
load wrongly, so it can't run these paths.)

`neg.py` plants a bug in each of the four parts and checks the harness catches it. `scen.py` counts the
instructions executed per block in fixed scenarios. These are instructions, not cycles, and not a unit's
CPU reading.

    tools/vd_bitexact/run.sh [ref] [cases]

## In the emulator: mk_selfcheck.py

    python3 tools/vd_bitexact/mk_selfcheck.py OLD.s voice-dac/os1.74/voice-dac.s OUT.s

This writes a debug source (emulator only, never released) whose vs_body runs OLD's pan pass through
its sum on each block's inputs, keeps what it wrote, puts the inputs back, then runs the new code on the
same inputs and compares. The counters `voice_dac_sc_n`, `_sc_bad`, `_sc_where` and `_sc_blk` (see the
script) are in the build's map, so a timing difference between two images can be told apart from a
difference in the values.
