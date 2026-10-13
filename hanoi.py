#!/usr/bin/env python3
"""Solve the Towers of Hanoi from an arbitrary legal position.

Usage:
    python3 hanoi.py [--chunk <MB>] <input_file> <output_file>

The input file has four lines: the target tower (A, B or C), then the
pieces on towers A, B and C, bottom to top.  Entries are separated by
spaces and/or commas; an entry is a single piece number or a contiguous
run lo-hi.  Piece 1 is the largest.

The output file has one line per move: the source tower followed by the
destination tower, e.g. "AC".

Moves are streamed to the output file.  Full-stack ("classical") sections
are emitted as precomputed byte blocks, so memory stays bounded (a few
hundred MB by default, tunable with --chunk) while very large outputs run
at disk speed.
"""

import re
import sys

SOLVE = 0      # (SOLVE, piece, target): get pieces piece..n onto target
MOVE = 1       # (MOVE, piece, source, dest): move that piece
CLASSICAL = 2  # (CLASSICAL, piece, src, dst, aux): move the full stack of
               # pieces piece..n from src to dst using aux

_SPLIT = re.compile(r"[\s,]+")
_LINES = [[(a + b + "\n").encode() for b in "ABC"] for a in "ABC"]
_SINK_SIZE = 4 << 20
_MAX_CAP_LEVEL = 25  # keeps peak memory under ~1 GB even for huge --chunk


class HanoiError(ValueError):
    """Invalid game input; the CLI reports it via die(), the web API as 400."""


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
            raise HanoiError(f"tower {name}: malformed entry {token!r}")
        if lo < 1 or hi < lo:
            raise HanoiError(f"tower {name}: malformed entry {token!r}")
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
        raise HanoiError("input must have 4 lines: target tower, then towers A, B and C")
    lines += [""] * (4 - len(lines))
    target = lines[0].strip().upper()
    if target not in "ABC":
        raise HanoiError(f"target tower must be A, B or C, got {lines[0].strip()!r}")
    towers = [parse_tower_line(lines[i], name) for i, name in enumerate("ABC", 1)]
    return "ABC".index(target), towers


def build_pegs(towers):
    n = max((max(t) if t else 0) for t in towers)
    pegs = bytearray(n + 1)
    for tower, pieces in enumerate(towers):
        for piece in pieces:
            if pegs[piece]:
                raise HanoiError(f"piece {piece} is listed on more than one tower")
            pegs[piece] = tower + 1
    for piece in range(1, n + 1):
        if not pegs[piece]:
            raise HanoiError(f"piece {piece} is missing from all towers")
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

def count_moves(n, pegs, target):
    # Number of moves in the optimal solution without generating it: a
    # classical block of m pieces always takes 2^m - 1 moves, so blocks
    # are counted instead of expanded (O(n) even for huge n).
    count = 0
    stack = [(SOLVE, 1, target)]
    push, pop = stack.append, stack.pop
    while stack:
        task = pop()
        kind = task[0]
        if kind == MOVE:
            count += 1
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
            piece = task[1]
            if piece > n:
                continue
            count += (1 << (n - piece + 1)) - 1
    return count


def _build_level(m):
    # The six orientations of the classical block of m pieces, each as one
    # bytes object.  block(m, f, t) = block(m-1, f, a) + line(f, t) +
    # block(m-1, a, t) where a is the third tower, so each level is six
    # C-speed concatenations of the previous level.
    level = {(a, b): _LINES[a][b] for a in range(3) for b in range(3) if a != b}
    for _ in range(2, m + 1):
        nxt = {}
        for a in range(3):
            for b in range(3):
                if a != b:
                    c = 3 - a - b
                    nxt[(a, b)] = level[(a, c)] + _LINES[a][b] + level[(c, b)]
        level = nxt
    return level


class _FastWriter:
    """Streams the move sequence to a binary file.

    Classical sections are emitted as precomputed bytes (see
    _build_level); blocks up to the cap size are memoized, larger ones
    are streamed by expanding the block identity into an explicit stack,
    so memory stays proportional to the cap, not the output size.
    """

    def __init__(self, out, chunk_mb):
        cap_moves = (chunk_mb << 20) // 3 + 1
        self._m_cap = min(max(cap_moves.bit_length() - 1, 1), _MAX_CAP_LEVEL)
        self._out = out
        self._memo = {}
        self._buf = bytearray(_SINK_SIZE)
        self._pos = 0

    def extend(self, data):
        buf, pos = self._buf, self._pos
        if pos + len(data) <= len(buf):
            buf[pos:pos + len(data)] = data
            self._pos = pos + len(data)
            return
        if pos:
            self._out.write(memoryview(buf)[:pos])
            self._pos = 0
        if len(data) > len(buf):
            self._out.write(data)
        else:
            buf[:len(data)] = data
            self._pos = len(data)

    def flush(self):
        if self._pos:
            self._out.write(memoryview(self._buf)[:self._pos])
            self._pos = 0

    def block(self, m, f, t):
        if m == self._m_cap:
            block = self._memo.get((f, t))
            if block is None:
                self._memo = _build_level(m)
            return self._memo[(f, t)]
        return _build_level(m)[(f, t)]

    def emit_block(self, m, f, t):
        # Emit block(m, f, t) = block(m-1, f, a) + line + block(m-1, a, t),
        # iterating the expansion (phase 0/1/2) so the stack stays O(depth).
        stack = [(m, f, t, 0)]
        push, pop = stack.append, stack.pop
        while stack:
            m, f, t, phase = pop()
            if m == 0:
                self.extend(_LINES[f][t])
            elif m <= self._m_cap:
                self.extend(self.block(m, f, t))
            elif phase == 0:
                a = 3 - f - t
                push((m, f, t, 1))
                push((m - 1, f, a, 0))
            elif phase == 1:
                push((m, f, t, 2))
                push((0, f, t, 0))
            else:
                a = 3 - f - t
                push((m - 1, a, t, 0))


def write_moves(n, pegs, target, out, chunk_mb=64):
    w = _FastWriter(out, chunk_mb)
    stack = [(SOLVE, 1, target)]
    push, pop = stack.append, stack.pop
    lines = _LINES
    while stack:
        task = pop()
        kind = task[0]
        if kind == MOVE:
            w.extend(lines[task[2]][task[3]])
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
            w.emit_block(n - piece + 1, f, t)
    w.flush()


def main(argv):
    args = list(argv[1:])
    chunk_mb = 64
    if args and args[0] == "--chunk":
        if len(args) < 2 or not args[1].isdigit() or not 1 <= int(args[1]) <= 1024:
            die("--chunk takes a value in MB between 1 and 1024")
        chunk_mb = int(args[1])
        args = args[2:]
    if len(args) != 2:
        die(f"usage: python3 {argv[0]} [--chunk <MB>] <input_file> <output_file>")
    try:
        target, towers = load_input(args[0])
        n, pegs = build_pegs(towers)
    except HanoiError as e:
        die(str(e))
    try:
        with open(args[1], "wb", buffering=0) as out:
            write_moves(n, pegs, target, out, chunk_mb)
    except OSError as e:
        die(f"cannot write {args[1]}: {e}")


if __name__ == "__main__":
    main(sys.argv)
