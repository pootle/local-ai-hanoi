"""Tests for hanoi.py: legality, final position, optimality and scale."""

import io
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from itertools import product
from pathlib import Path

import hanoi

HERE = Path(__file__).parent


def random_pegs(n, rng):
    pegs = bytearray(n + 1)
    for i in range(1, n + 1):
        pegs[i] = rng.randrange(3)
    return pegs


def replay(n, pegs, target, moves):
    """Return an error string if the move list is illegal or ends wrong."""
    towers = [[] for _ in range(3)]
    for piece in range(1, n + 1):
        towers[pegs[piece]].append(piece)
    for source, dest in moves:
        if not towers[source]:
            return f"move from empty tower {source}"
        piece = towers[source].pop()
        if towers[dest] and towers[dest][-1] > piece:
            return f"piece {piece} placed on top of a smaller piece"
        towers[dest].append(piece)
    if towers[target] != list(range(1, n + 1)):
        return "target tower is not the full stack"
    if any(towers[t] for t in range(3) if t != target):
        return "pieces remain on the other towers"
    return None


def replay_stream(n, pegs, target, path):
    """Replay an output file without loading it: same checks as replay()."""
    towers = [[] for _ in range(3)]
    for piece in range(1, n + 1):
        towers[pegs[piece]].append(piece)
    pending = b""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            data = pending + chunk
            rem = len(data) % 3
            if rem:
                pending = data[-rem:]
                data = data[:-rem]
            else:
                pending = b""
            for i in range(0, len(data), 3):
                source, dest = data[i] - 65, data[i + 1] - 65
                if not towers[source]:
                    return "move from an empty tower"
                piece = towers[source].pop()
                if towers[dest] and towers[dest][-1] > piece:
                    return f"piece {piece} placed on top of a smaller piece"
                towers[dest].append(piece)
    if pending:
        return "incomplete line"
    if towers[target] != list(range(1, n + 1)):
        return "target tower is not the full stack"
    if any(towers[t] for t in range(3) if t != target):
        return "pieces remain on the other towers"
    return None


def bfs_dists(n, start):
    """Shortest move count from start to every state (state = tower per piece)."""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        state = queue.popleft()
        d = dist[state]
        tops = [-1, -1, -1]
        for i in range(n):
            t = state[i]
            if i > tops[t]:
                tops[t] = i
        for src in range(3):
            piece = tops[src]
            if piece < 0:
                continue
            for dst in range(3):
                if dst == src or tops[dst] > piece:
                    continue
                nxt = state[:piece] + (dst,) + state[piece + 1:]
                if nxt not in dist:
                    dist[nxt] = d + 1
                    queue.append(nxt)
    return dist


def check_optimal(n, start, label):
    pegs = bytearray(n + 1)
    for i, t in enumerate(start, 1):
        pegs[i] = t
    dists = bfs_dists(n, start)
    for target in range(3):
        got = sum(1 for _ in hanoi.generate_moves(n, pegs, target))
        want = dists[(target,) * n]
        assert got == want, f"{label}: target {target}: got {got}, want {want}"


def test_replay_random():
    rng = random.Random(20261013)
    for n, count in ((1, 20), (2, 20), (3, 20), (4, 20), (5, 20),
                     (6, 20), (8, 15), (10, 10), (12, 8), (14, 6)):
        for _ in range(count):
            pegs = random_pegs(n, rng)
            for target in range(3):
                moves = list(hanoi.generate_moves(n, pegs, target))
                error = replay(n, pegs, target, moves)
                assert error is None, f"n={n} target={target} pegs={bytes(pegs[1:])}: {error}"


def test_optimality_exhaustive():
    for n in range(1, 6):
        for start in product(range(3), repeat=n):
            check_optimal(n, start, f"n={n} start={start}")


def test_optimality_sampled():
    rng = random.Random(99)
    for n, count in ((6, 50), (7, 30), (8, 12), (11, 2)):
        for _ in range(count):
            start = tuple(rng.randrange(3) for _ in range(n))
            check_optimal(n, start, f"n={n} start={start}")


def test_spec_example():
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "in.txt"
        outp = Path(tmp) / "out.txt"
        inp.write_text("C\n1 3 5-9 11\n\n2,4,10\n")
        result = subprocess.run(
            [sys.executable, str(HERE / "hanoi.py"), str(inp), str(outp)],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        lines = outp.read_text().splitlines()
        assert all(len(l) == 2 and l[0] in "ABC" and l[1] in "ABC" for l in lines)
        moves = [(ord(l[0]) - 65, ord(l[1]) - 65) for l in lines]
        pegs = bytearray(12)
        for piece in (1, 3, 5, 6, 7, 8, 9, 11):
            pegs[piece] = 0
        for piece in (2, 4, 10):
            pegs[piece] = 2
        error = replay(11, pegs, 2, moves)
        assert error is None, error
        check_optimal(11, tuple(pegs[1:]), "spec example")


def test_classical_counts():
    for n in range(1, 13):
        pegs = bytearray(n + 1)
        moves = list(hanoi.generate_moves(n, pegs, 1))
        assert len(moves) == 2 ** n - 1, f"n={n}: {len(moves)} != {2 ** n - 1}"
        error = replay(n, pegs, 1, moves)
        assert error is None, error


def test_fast_block_matches_reference():
    # The fast path precomputes classical blocks as bytes; every block must
    # decode to exactly the moves the reference generator produces.
    w = hanoi._FastWriter(io.BytesIO(), 64)
    pegs = bytearray(18)
    for m in range(1, 18):
        for f in range(3):
            for t in range(3):
                if f == t:
                    continue
                for piece in range(1, m + 1):
                    pegs[piece] = f
                data = w.block(m, f, t)
                got = [(data[i] - 65, data[i + 1] - 65) for i in range(0, len(data), 3)]
                expected = list(hanoi.generate_moves(m, pegs, t))
                assert got == expected, f"m={m} f={f} t={t}"


def test_fast_writer_matches_reference():
    # The streamed output of the fast writer must equal the reference
    # generator, for classical and scattered positions, including blocks
    # larger than the sink buffer and streaming above the cap size
    # (chunk 8 MB caps blocks at 2^21 pieces).  Compared byte-by-byte so
    # the test itself stays memory-light (this also keeps the parent
    # process's peak RSS from skewing the RUSAGE_CHILDREN readings that
    # test_scale relies on).
    cases = [(22, bytearray(23), 1)]
    pegs_b = bytearray(23)
    for piece in range(1, 23):
        pegs_b[piece] = 1
    cases.append((22, pegs_b, 0))
    pegs20 = bytearray(21)
    for tower, pieces in enumerate(([1, 5, 9, 13, 17, 20],
                                    [2, 6, 10, 14, 18],
                                    [3, 7, 11, 15, 16, 19])):
        for piece in pieces:
            pegs20[piece] = tower
    cases.append((20, pegs20, 1))
    for n, pegs, target in cases:
        out = io.BytesIO()
        hanoi.write_moves(n, pegs, target, out, 8)
        data = out.getvalue()
        i = 0
        for s, d in hanoi.generate_moves(n, pegs, target):
            if data[i] != 65 + s or data[i + 1] != 65 + d:
                raise AssertionError(f"n={n} target={target} move {i // 3}")
            i += 3
        assert i == len(data), f"n={n} target={target} length mismatch"


def test_sink_buffering():
    w = hanoi._FastWriter(io.BytesIO(), 64)
    w.extend(b"ab\n")
    w.extend(b"x" * (1 << 21))  # bigger than the sink buffer
    w.extend(b"cd\n")
    w.flush()
    assert w._out.getvalue() == b"ab\n" + b"x" * (1 << 21) + b"cd\n"


def test_scale():
    n = 500_000
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "in.txt"
        outp = Path(tmp) / "out.txt"

        inp.write_text("A\n" + " ".join(map(str, range(1, n + 1))) + "\n\n\n")
        t0 = time.monotonic()
        subprocess.run([sys.executable, str(HERE / "hanoi.py"), str(inp), str(outp)],
                       check=True, capture_output=True)
        solved_in = time.monotonic() - t0
        assert outp.read_text() == ""
        peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        print(f"    500k already-solved pieces: {solved_in:.2f}s, peak {peak_mb:.0f} MB")
        assert peak_mb < 300

        b = " ".join(map(str, range(n - 19, n + 1, 2)))
        c = " ".join(map(str, range(n - 18, n + 1, 2)))
        inp.write_text(f"A\n1-{n - 20}\n{b}\n{c}\n")
        t0 = time.monotonic()
        subprocess.run([sys.executable, str(HERE / "hanoi.py"), str(inp), str(outp)],
                       check=True, capture_output=True)
        moved_in = time.monotonic() - t0
        lines = outp.read_text().splitlines()
        assert lines and all(len(l) == 2 and l[0] in "ABC" and l[1] in "ABC" for l in lines)
        moves = [(ord(l[0]) - 65, ord(l[1]) - 65) for l in lines]
        pegs = bytearray(n + 1)
        for piece in range(n - 19, n + 1, 2):
            pegs[piece] = 1
        for piece in range(n - 18, n + 1, 2):
            pegs[piece] = 2
        error = replay(n, pegs, 0, moves)
        assert error is None, error
        print(f"    500k pieces, {len(moves)} moves: {moved_in:.2f}s")

        # Full classical stack of 25 pieces: 33,554,431 moves (~100 MB),
        # streamed above the 4 MB sink with 48 MB memoized blocks.
        inp.write_text("B\n1-25\n\n\n")
        t0 = time.monotonic()
        subprocess.run([sys.executable, str(HERE / "hanoi.py"), str(inp), str(outp)],
                       check=True, capture_output=True)
        classic_in = time.monotonic() - t0
        assert outp.stat().st_size == 3 * (2**25 - 1)
        error = replay_stream(25, bytearray(26), 1, outp)
        assert error is None, error
        peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        print(f"    25-piece classical, {2**25 - 1} moves: {classic_in:.2f}s, "
              f"peak {peak_mb:.0f} MB")
        assert peak_mb < 1536

        # 28 pieces: 268,435,455 moves (~805 MB); only run with room to
        # spare, and verify without a full Python replay (spot checks).
        if shutil.disk_usage(tmp).free > 2.5 * (1 << 30):
            inp.write_text("B\n1-28\n\n\n")
            t0 = time.monotonic()
            subprocess.run([sys.executable, str(HERE / "hanoi.py"), str(inp), str(outp)],
                           check=True, capture_output=True)
            big_in = time.monotonic() - t0
            assert outp.stat().st_size == 3 * (2**28 - 1)
            with open(outp, "rb") as fh:
                assert fh.read(2) == b"AC"
                fh.seek(3 * ((1 << 27) - 1))
                assert fh.read(2) == b"AB"  # middle move: piece 1, A to B
                fh.seek(-3, 2)
                assert fh.read(2) == b"CB"
            with open(outp, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    assert not chunk.translate(None, b"ABC\n")
            print(f"    28-piece classical, {2**28 - 1} moves: {big_in:.2f}s "
                  f"= {(2**28 - 1) / big_in / 1e6:.0f}M moves/s")


def test_invalid_input():
    bad = [
        "D\n1\n\n\n",
        "A\n1 1\n\n\n",
        "A\n1 3\n\n\n",
        "A\n0\n\n\n",
        "A\n1 3-2\n\n\n",
        "A\n1 x\n\n\n",
        "A\n1 5-\n\n\n",
        "A\n1\n2\n3\n4\n",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o.txt"
        result = subprocess.run([sys.executable, str(HERE / "hanoi.py")],
                                capture_output=True, text=True)
        assert result.returncode != 0 and "usage" in result.stderr
        for i, text in enumerate(bad):
            inp = Path(tmp) / f"in{i}.txt"
            inp.write_text(text)
            result = subprocess.run(
                [sys.executable, str(HERE / "hanoi.py"), str(inp), str(out)],
                capture_output=True, text=True)
            assert result.returncode != 0, f"case {text!r} should fail"


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t0 = time.monotonic()
        t()
        print(f"ok {t.__name__} ({time.monotonic() - t0:.1f}s)")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
