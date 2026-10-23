// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Alex Moncks
// Runs the original Cube Maze 3D source (orig/cubemaze.src.js, by
// harukaappscreate) in node with a stub of its runtime, a seeded random
// generator and a scripted joypad, and prints one JSON line per frame with
// the game state. ref/cubemaze.py replays the same script and must print the
// same lines (check_logic.py compares them).
//
// The only change to the source: the shuffle `[...I4].sort(() => M.random()
// - 0.5)` (whose order depends on the engine's sort) becomes a Fisher-Yates
// over the same random generator, so that Python can reproduce it.
//
// Usage: node js_trace.js <seed> <frames> <inputs.json|random>
// DUMP=<file>: also writes every frame's cls colour and spr calls (for ref_frames.py).
'use strict';
const fs = require('fs');
const path = require('path');

const seed = +(process.argv[2] || 1), frames = +(process.argv[3] || 600);
const inArg = process.argv[4] || 'random';

// 32-bit xorshift, the same in ref/cubemaze.py
let rs = seed >>> 0 || 1;
const rnd = () => {
  rs ^= rs << 13; rs >>>= 0; rs ^= rs >>> 17; rs ^= rs << 5; rs >>>= 0;
  return rs / 4294967296;
};

let src = fs.readFileSync(path.join(__dirname, '..', 'orig', 'cubemaze.src.js'), 'utf8');
const shuf = '[...I4].sort(() => M.random() - 0.5)';
if (!src.includes(shuf)) throw new Error('shuffle not found');
src = src.replace(shuf, 'SHUF()');

// runtime stub
const pcg = {};
for (let i = 0; i < 256; i++) pcg[String.fromCharCode(i)] = { pat: [0, 0, 0, 0, 0, 0, 0, 0] };
// GLYPHS=<playload glyphs.js>: the engine's font, read as data (the preview countdown reads it)
if (process.env.GLYPHS)
  for (const line of fs.readFileSync(process.env.GLYPHS, 'utf8').split('\n')) {
    const m = line.match(/^\s*(\{.*\}),?\s*$/);
    if (m) { const g = JSON.parse(m[1]); if (g.ch.length == 1 && pcg[g.ch]) pcg[g.ch].pat = g.rows; }
  }
let held = [0, 0, 0, 0, 0, 0], prev = [0, 0, 0, 0, 0, 0];
const btn = (i) => !!held[i];
const btnp = (i) => !!(held[i] && !prev[i]);
const DUMP = process.env.DUMP ? fs.openSync(process.env.DUMP, 'w') : null;
let frameSpr = [], frameCls = 0;
const spr = (x, y, str, col) => { if (DUMP) frameSpr.push([x, y, str, col]); };
const cls = (c) => { frameCls = c; };
const play = () => {};
const indexedDB = { open: () => ({}) };
const Mx = Object.create(Math);
Mx.random = rnd;
const SHUF = () => {
  const a = [0, 1, 2, 3];
  for (let i = 3; i > 0; i--) { const j = (rnd() * (i + 1)) | 0; [a[i], a[j]] = [a[j], a[i]]; }
  return a;
};

const body = src.replace('const M = Math,', 'const M = Mx,') +
  '\nreturn { tick, st: () => ({ ph, lv, unl, T, cur, gl, st, act, rot, el, prv, ' +
  'mA: mA ? [mA[0], mA[1], +mA[2].toFixed(6)] : 0, rA: rA ? +rA[2].toFixed(6) : 0, ' +
  'cQ: cQ.map((v) => +v.toFixed(6)), G: G.slice(), sc, best: best.slice() }) };';
const game = new Function('pcg', 'spr', 'cls', 'play', 'btn', 'btnp', 'indexedDB', 'Mx', 'SHUF', body)(
  pcg, spr, cls, play, btn, btnp, indexedDB, Mx, SHUF);

// inputs: list of 6-bit masks per frame, or a random script from its own generator
let inputs;
if (inArg === 'random') {
  let r2 = (seed * 2654435761) >>> 0 || 7;
  const rn = () => { r2 ^= r2 << 13; r2 >>>= 0; r2 ^= r2 >>> 17; r2 ^= r2 << 5; r2 >>>= 0; return r2; };
  inputs = [];
  let cur = 0, left = 0;
  for (let f = 0; f < frames; f++) {
    if (left-- <= 0) {
      const k = rn() % 16;
      cur = k < 4 ? 1 << k : k < 6 ? 16 : k == 6 ? 32 * (rn() % 9 == 0) : 0;
      left = 1 + (rn() % 24);
    }
    inputs.push(cur);
  }
} else inputs = JSON.parse(fs.readFileSync(inArg, 'utf8'));

const norm = (o) => JSON.stringify(o, (k, v) => (typeof v === 'number' && !Number.isInteger(v) ? +v.toFixed(6) : v));
for (let f = 0; f < frames; f++) {
  prev = held;
  held = [0, 1, 2, 3, 4, 5].map((i) => (inputs[f] >> i) & 1);
  frameSpr = [];
  game.tick();
  if (DUMP) fs.writeSync(DUMP, JSON.stringify({ cls: frameCls, spr: frameSpr }) + '\n');
  const s = game.st();
  s.G = Array.from(s.G, (x) => x | 0);
  console.log(norm(s));
}
