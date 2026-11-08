#!/bin/sh
# Bit-exact check of voice-dac's interrupt paths: OLD (a git ref, default
# voice-dac-core-0.12) against the working tree. Needs m68k-linux-gnu-as/-ld/
# -objdump/-objcopy/-nm and python3. Usage: run.sh [ref] [cases]
set -e
here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../.." && pwd)
ref=${1:-voice-dac-core-0.12}; n=${2:-100}
work=$(mktemp -d); mkdir "$work/h"
git -C "$repo" show "$ref:voice-dac/os1.74/voice-dac.s" > "$work/old.s"
cp "$repo/voice-dac/os1.74/voice-dac.s" "$work/new.s"
cp "$here"/*.py "$work/"
cd "$work"
python3 gen.py
for v in old new; do m68k-linux-gnu-as -mcpu=54455 -o h/$v.o h/$v.s && m68k-linux-gnu-ld -o h/$v h/$v.o; done
cp h/new.s h/new.orig.s
python3 drive.py "$n"
SAT32=1 python3 drive.py "$n"
python3 scen.py
python3 neg.py
