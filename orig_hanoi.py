#!/usr/bin/env python3
"""Solve the Towers of Hanoi from an arbitrary legal position.

Usage:
    python3 hanoi.py <input_file> <output_file>

The input file has four lines: the target tower (A, B or C), then the
pieces on towers A, B and C, bottom to top.  Entries are separated by
spaces and/or commas; an entry is a single piece number or a contiguous
run lo-hi.  Piece 1 is the largest.

The output file has one line per move: the source tower followed by the
destination tower, e.g. "AC".
"""

import re
import sys

SOLVE = 0      # (SOLVE, piece, target): get pieces piece..n onto target
MOVE = 1       # (MOVE, piece, source, dest): move that piece
CLASSICAL = 2  # (CLASSICAL, piece, src, dst, aux): move the full stack of
               # pieces piece..n from src to dst using aux

_SPLIT = re.compile(r"[\s,]+")
_MOVE_LINES = [[a + b + "\n" for b in "ABC"] for a in "ABC"]


def die(message):
    print(f"hanoi: {message}", file=sys.stderr)
    sys.exit(1)


def parse_tower_line(line, name):
    pieces = []
    for token in _SPLIT.split(line.strip()):
        if not token:
            continue
        try:
            if "-" in token:
                lo_s, hi_s = token.split("-")
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(token)
        except ValueError:
            die(f"tower {name}: malformed entry {token!r}")
        if lo < 1 or hi < lo:
            die(f"tower {name}: malformed entry {token!r}")
        pieces.extend(range(lo, hi + 1))
    return pieces


def load_input(path):
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError as e:
        die(f"cannot read {path}: {e}")
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) > 4:
        die("input must have 4 lines: target tower, then towers A, B and C")
    lines += [""] * (4 - len(lines))
    target = lines[0].strip().upper()
    if target not in "ABC":
        die(f"target tower must be A, B or C, got {lines[0].strip()!r}")
    towers = [parse_tower_line(lines[i], name) for i, name in enumerate("ABC", 1)]
    return "ABC".index(target), towers


def build_pegs(towers):
    n = max((max(t) if t else 0) for t in towers)
    pegs = bytearray(n + 1)
    for tower, pieces in enumerate(towers):
        for piece in pieces:
            if pegs[piece]:
                die(f"piece {piece} is listed on more than one tower")
            pegs[piece] = tower + 1
    for piece in range(1, n + 1):
        if not pegs[piece]:
            die(f"piece {piece} is missing from all towers")
        pegs[piece] -= 1
    return n, pegs


def generate_moves(n, pegs, target):
    # A piece only moves onto a larger piece or an empty tower, so the
    # largest remaining piece i can leave its tower only when every
    # smaller piece is stacked on the third tower; it then moves exactly
    # once, and the smaller pieces follow as a full classical stack move.
    stack = [(SOLVE, 1, target)]
    push, pop = stack.append, stack.pop
    while stack:
        task = pop()
        kind = task[0]
        if kind == MOVE:
            yield task[2], task[3]
        elif kind == SOLVE:
            piece, t = task[1], task[2]
            if piece > n:
                continue
            p = pegs[piece]
            if p == t:
                push((SOLVE, piece + 1, t))
            else:
                q = 3 - p - t
                push((CLASSICAL, piece + 1, q, t, p))
                push((MOVE, piece, p, t))
                push((SOLVE, piece + 1, q))
        else:
            piece, f, t, a = task[1], task[2], task[3], task[4]
            if piece > n:
                continue
            push((CLASSICAL, piece + 1, a, t, f))
            push((MOVE, piece, f, t))
            push((CLASSICAL, piece + 1, f, a, t))


def write_moves(n, pegs, target, out):
    buf = []
    append = buf.append
    for source, dest in generate_moves(n, pegs, target):
        append(_MOVE_LINES[source][dest])
        if len(buf) >= 65536:
            out.write("".join(buf))
            buf.clear()
            append = buf.append
    if buf:
        out.write("".join(buf))


def main(argv):
    if len(argv) != 3:
        die(f"usage: python3 {argv[0]} <input_file> <output_file>")
    target, towers = load_input(argv[1])
    n, pegs = build_pegs(towers)
    try:
        with open(argv[2], "w") as out:
            write_moves(n, pegs, target, out)
    except OSError as e:
        die(f"cannot write {argv[2]}: {e}")


if __name__ == "__main__":
    main(sys.argv)
