# ctrl-all

Port of rytm-mods-src `mods/0014-ctrl-all` (MrScruff; hardware-verified there).

Hold TRK and turn a knob on a sound page (SYNTH, SAMPLE, FILTER, AMP, LFO) or the TRIG page: the
same step goes to that parameter on all twelve sound tracks, so their differences are kept and each
track stops at its own limits. On the SYNTH page each track gets the step on the same knob position,
limited to the selected track's machine's range. Stock behaviour (selected track only) with the FX
track selected, while a trig key is held (so parameter locks stay on one track), and on FX or global
pages.

## How it hooks

One site, the same as rytm-mods' detour: `param_apply_delta_dispatch`, 0x400378c2, in
param_apply_delta after the track lookup. The 6 stock bytes (`move.l %a2@,%a0; pea -1`) become
`jmp ctrl_all_gate`. The gate checks FX track, TRK held, no trig key held and a sound or TRIG set; if
all pass it calls each track's set's own delta handler for tracks 0..11 and returns through
param_apply_delta's epilogue, otherwise it re-emits the two instructions and resumes at 0x400378c8.

In rytm-mods this address is the end of a chain: 0002, 0003, 0004 and 0013 detour the instructions
just before it (0x400378a6..0x400378bc), so the parameters those mods add stay single-track. Here
those are separate sites owned by their own mods; none of them is ported yet.

## Changes from rytm-mods

- The stub's code is unchanged. `ctrl_all_gate` is `.globl`; nothing else is.
- It runs from the elemod DDR area instead of cave13 (0x40029838).
- Symbols come from `../include/ar2-1.73.inc`.

## Test (on a unit)

1. FILTER page: note FRQ on two tracks. On one, hold TRK and turn FRQ: the other track's FRQ moves by
   the same amount. The FILTER, AMP, LFO, SAMPLE and TRIG pages do not depend on the machine.
2. SYNTH page: give two tracks the same machine (e.g. XT CLASSIC on LT and MT), then repeat with a
   SYNTH knob: both move.
3. With the FX track selected, or with a trig key held, only the selected track changes.

On the SYNTH page a track whose machine differs from the selected track's may not follow (seen on
the unit: BD PLASTIC selected, SD's DEC unchanged). The code is rytm-mods' own, so 0014 behaves the
same way there: the step goes by the selected machine's parameter id, clamped to its range.

## Results so far

- Hardware: R2T1 (sha256 869cac19...0cae5) flashed by Iced-Cream, 2026-10-13. Works on the FILTER
  page (FRQ) and on the SYNTH page between two tracks with the same machine (XT CLASSIC on LT and
  MT). BD PLASTIC -> SD, SYNTH DEC: SD did not follow (see Test).
- `.run` 172 B, 1 site, no relocations; lint OK; links with core-ar2 0.1.
- The 170 B of code (plus 2 B alignment) linked into the image are byte-identical to the stub in
  rytm-mods-src's default build (cave13, 0x40029838). The site reads `jmp 0x47be01cc` in place of
  `jmp 0x40029838`.
- rytm-emu (3c4c42c), build R2T1: with TRK held, 14 turn events reach the site; the gate takes the
  all-tracks path every time (0 resumes at 0x400378c8) and calls the sound set's delta handler
  (0x400a95dc) 168 times = 14 x 12 tracks; stock calls it 14 times. The selected track's value
  moves exactly as on stock. The emulator's screen does not show the other tracks' values change -
  and neither does it for rytm-mods' own hardware-verified build (pixel-identical screens) - so the
  cross-track result needs the unit.
