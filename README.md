# Towers of Hanoi — Batch Solver

A command-line program that solves the Towers of Hanoi from an
**arbitrary starting position**. Given the pieces on the three towers and a
target tower, it produces the (optimal) list of moves that ends with all
pieces correctly stacked on the target tower. There is also an animated
web front end for playing with positions by hand (see below).

## AI coding

This was written using local LLM as an experiment to compare with other online AIs.
For the original (minimal RAM version):

```
Plan phase took 3m 33s
build phase took 4m 53s
```

[The prompt is here](prompt.md)

A couple of questions from the AI were also asked and answered during planning.

### HW spec

PC (built before the great price hikes fortunately!)
- GPU nvidia 5090 
- CPU: AMD Ryzen 9 9950X3D
- RAM: 128GB

### SW spec

Using qwen3.8 27b with 6bit quantization. 
Context set to 128k. k & v set to use 8 bit int rather than 16bit float.
opencode 1.1.23

## Requirements

Python 3, no dependencies. Works on Linux, macOS and Windows.

## Usage

```
python3 hanoi.py [--chunk <MB>] <input_file> <output_file>
```

`--chunk <MB>` (default 64) bounds the memory used for precomputed move
blocks: a few times the chunk size, never more than ~1 GB. Larger values
are slightly faster for very long runs; smaller values use less memory.

## Input

The input file has 4 lines:

| Line | Contents |
|------|----------|
| 1    | Target tower: `A`, `B` or `C` |
| 2    | Pieces on tower A, bottom to top |
| 3    | Pieces on tower B, bottom to top |
| 4    | Pieces on tower C, bottom to top |

Each tower line is a list of entries separated by spaces and/or commas. An
entry is a single piece number or a contiguous run `lo-hi`. An empty line is
an empty tower. Piece `1` is the largest; pieces are numbered `1..n` and
every piece appears exactly once.

Example (`example_input.txt`):

```
C
1 3 5-9 11

2,4,10
```

Tower A holds `1 3 5 6 7 8 9 11`, tower B is empty, tower C holds
`2 4 10`, and the game is complete when all pieces are on C.

## Output

The output file contains one line per move; each line is 2 characters: the
source tower followed by the destination tower of the piece to move, e.g.
`AC`. If the pieces are already stacked on the target tower the output file
is empty.

Example (first moves of the example input above):

```
AC
AB
CA
CB
...
```

## Algorithm

Working from the largest piece down: a piece can only be placed on a larger
piece or an empty tower, so the largest remaining piece can leave its tower
only when every smaller piece is stacked on the third tower. It then moves
exactly once, and the smaller pieces follow as a classical stack move. This
yields the unique minimum-move solution.

Moves are generated and written as they are produced (streaming), so memory
is bounded regardless of the number of moves. Full-stack ("classical")
sections of the solution are emitted as precomputed byte blocks — a 25-piece
classical move is one 100 MB block, built from a handful of smaller blocks
and cached up to the `--chunk` size — so output speed is limited only by
disk bandwidth.

Typical timings on a modern laptop (page-cache writes):

| Input | Moves | Output | Time |
|-------|-------|--------|------|
| 500,000 pieces, already solved | 0 | 0 B | 0.15 s |
| 500,000 pieces, scattered | 748,982 | 2.2 MB | 0.08 s |
| 25 pieces, full stack | 33,554,431 | 100 MB | 0.20 s |
| 28 pieces, full stack | 268,435,455 | 805 MB | 0.31 s (~870 M moves/s) |

## Web animation

`hanoi_web.py` serves an animated version of the same solver in a web
browser. No dependencies and no build step:

```
python3 hanoi_web.py [port]        # default 8000
```

By default it listens on all network interfaces, so any other machine on
the local network can open `http://<server's IP>:8000/` — the LAN address
is printed on startup. Use `python3 hanoi_web.py --local` to restrict
access to the machine itself. (If the server PC's firewall asks whether to
allow the connection, say yes for private networks; on Windows the prompt
appears the first time the server starts.) If the chosen port happens to
be in use or inside a Hyper-V excluded port range on Windows, pass a
different one.

The page starts with a fresh classic game (8 pieces, A → C). The board is
drawn as SVG discs on three towers; **Play** animates the optimal solution
one move at a time, with the speed slider ranging from 0.2 to 4 moves/s.

- **New game** starts a classic game (1–32 pieces, any target tower) or a
  custom starting position — the same piece-list syntax as the file input,
  one line per tower.
- **Stop** pauses mid-solution. You can then move pieces by hand: click a
  piece (only the top of each tower is selectable), then click a tower.
  Illegal moves are rejected. **Play** again resumes the optimal solution
  from wherever the pieces are.
- The header offers three colour themes (light / dark / grey); the choice
  is remembered.

The browser never holds the whole solution: the page asks the server for
batches of 256 moves at a time, and after any manual move it sends the
current position back so the server re-solves from there. The piece count
is capped at 32 for rendering; for big jobs use `hanoi.py` as before.

The front end has its own tests:

```
python3 test_hanoi_web.py
```

which start a throwaway server and exercise the JSON API end to end —
batching and offsets, resuming from arbitrary positions, session expiry,
input validation, and agreement of every served batch with the reference
generator.

### Minimal install

To run the web service on another machine, copy just two files from this
repo into any folder: `hanoi_web.py` and `hanoi.py` (the solver it
imports). No package manager, no dependencies:

```
python hanoi_web.py 8000      # Windows
python3 hanoi_web.py 8000     # Linux / macOS
```

Then open http://127.0.0.1:8000/ on that machine, or
http://<that machine's IP>:8000/ from any other machine on the network.
Everything else in this repo — the tests, `orig_hanoi.py`, examples and
docs — is not needed to run the service.

## `orig_hanoi.py`

`orig_hanoi.py` is the original, minimal implementation, kept for reference.
It streams moves one at a time without precomputing any move blocks, so it
uses the least RAM of the two. In exchange it is much slower — it is bound
by per-move Python work (~5 M moves/s) rather than by disk, so it is the
wrong choice for anything large. Use `hanoi.py` for real jobs; `orig_hanoi.py`
only makes sense if memory is at an absolute premium. It accepts the same
input format and produces the same output (it has no `--chunk` option).

## Tests

```
python3 test_hanoi.py
```

Covers move legality and final position (replay of generated moves),
optimality against BFS over the full state space (exhaustive for n ≤ 5,
sampled up to n = 11), classical 2ⁿ−1 move counts, byte-for-byte agreement
of the fast streaming writer with the reference generator, the example
above, invalid-input handling, and scale runs (500,000 pieces; a fully
replayed 25-piece classical run; a 28-piece / 805 MB run when there is
disk space). On Windows the standard `resource` module is unavailable, so
`test_scale` omits the peak-RAM figures; everything else is identical.
