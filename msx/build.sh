#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
#
# build.sh - builds Cube Maze 3D for MSX2 + V9968 + geo3d v2.0 (z80asm 1.8, python3)
#   out/CUBEMAZE_98.ROM  V9968 at 98h, geo3d at 9Dh/9Fh (openMSX fork -ext geo3d,
#                        blueMSX+ V9968-geo3d)
#   out/CUBEMAZE_88.ROM  the V9968 cartridge with the geo3d v2.0 build at 88h
# 128 KB ASCII16 MegaROMs: bank 0 the code, 1-4 the tables (gen_assets.py).
set -e
cd "$(dirname "$0")"
PY=${PY:-python3}
mkdir -p out
$PY gen_assets.py
for p in 98 88; do
  printf 'PORT_BASE: equ 0x%s\n' $p > out/ports.asm
  if ! z80asm -I music -o out/bank0_$p.bin --list=out/cubemaze_$p.lst --label=out/labels_$p.txt asm/cubemaze.asm 2> out/asm_$p.err || [ -s out/asm_$p.err ]; then
    head -40 out/asm_$p.err
    exit 1
  fi
  $PY - "$p" <<'PYEOF'
import sys
p = sys.argv[1]
b0 = open(f"out/bank0_{p}.bin", "rb").read()
assert len(b0) == 0x4000, len(b0)
rom = b0
for n in (1, 2, 3, 4):
    b = open(f"out/bank{n}.bin", "rb").read()
    assert len(b) == 0x4000
    rom += b
rom += bytes(0x20000 - len(rom))
open(f"out/CUBEMAZE_{p}.ROM", "wb").write(rom)
PYEOF
  if ! $PY ../../tools/mapper_guess.py --expect ASCII16 --margin 16 out/CUBEMAZE_$p.ROM > out/mapper_$p.txt; then
    cat out/mapper_$p.txt; echo "out/CUBEMAZE_$p.ROM does not read as ASCII16 to a mapper guesser"; exit 1
  fi
done
lab() { grep -i "^$1:" out/labels_98.txt | head -1 | sed 's/.*\$//'; }
printf 'bank 0: %d bytes free\n' $((0x8000 - 0x$(lab bank0_end)))
md5sum out/CUBEMAZE_98.ROM out/CUBEMAZE_88.ROM
