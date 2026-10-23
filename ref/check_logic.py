#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Compares the frame-by-frame state of the original (node js_trace.js) and of
the Python port (cubemaze.py) for random joypad scripts and for scripts that
solve the mazes (solver inputs, written by solve.py).
Usage: check_logic.py <seeds> <frames> [random|solve]"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cubemaze  # noqa: E402


def same(a, b, path="", tol=2e-6):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol or (print(f"  {path}: js={a} py={b}") and False)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            print(f"  {path}: lengths {len(a)} / {len(b)}")
            return False
        return all(same(x, y, f"{path}[{i}]") for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, dict):
        return all(same(a[k], b[k], f"{path}.{k}") for k in a)
    return a == b or (print(f"  {path}: js={a} py={b}") and False)


def check(seed, frames, inputs=None):
    arg = inputs or "random"
    js = subprocess.run(["node", os.path.join(HERE, "js_trace.js"), str(seed), str(frames), arg],
                        capture_output=True, text=True, check=True).stdout.split("\n")
    ins = cubemaze.random_inputs(seed, frames) if not inputs else json.load(open(inputs))[:frames]
    py = cubemaze.run(seed, ins)
    stats = {"ph": set(), "rot": 0, "clears": 0, "lv": set()}
    for f, (lj, sp) in enumerate(zip(js, py)):
        sj = json.loads(lj)
        if not same(sj, sp):
            print(f"seed {seed}: diverge at frame {f}")
            return False, stats
        stats["ph"].add(sp["ph"])
        stats["lv"].add(sp["lv"])
        stats["rot"] = max(stats["rot"], sp["rot"])
    stats["clears"] = sum(1 for a, b in zip(py, py[1:]) if a["ph"] == 2 and b["ph"] in (3, 4))
    return True, stats


if __name__ == "__main__":
    seeds, frames = int(sys.argv[1]), int(sys.argv[2])
    mode = sys.argv[3] if len(sys.argv) > 3 else "random"
    ok = 0
    for s in range(1, seeds + 1):
        inputs = None
        if mode == "solve":
            inputs = os.path.join(HERE, f"solve_{s}.json")
            subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), str(s), str(frames), inputs], check=True)
        r, st = check(s, frames, inputs)
        ok += r
        if seeds <= 5 or not r:
            print(f"seed {s}: {'ok' if r else 'FAIL'} {st}")
    print(f"{ok}/{seeds} sequências idênticas ao original ({frames} quadros cada)")
