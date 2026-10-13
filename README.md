# Towers of Hanoi — Batch Solver

A command-line program that solves the Towers of Hanoi from an
**arbitrary starting position**. Given the pieces on the three towers and a
target tower, it produces the (optimal) list of moves that ends with all
pieces correctly stacked on the target tower.

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

Python 3, no dependencies.

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
disk space).
