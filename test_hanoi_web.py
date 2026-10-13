#!/usr/bin/env python3
"""Tests for the web front end (hanoi_web.py)."""

import json
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

import hanoi_web
from hanoi import build_pegs, generate_moves

SERVER = None
PORT = 0


def _start():
    server = hanoi_web.make_server(("127.0.0.1", 0))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _post(payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/{payload['path']}",
        data=json.dumps(payload["body"]).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _game(**body):
    status, data = _post({"path": "game", "body": body})
    assert status == 200, f"expected 200, got {status}: {data}"
    return data


def _fetch(sid=None, towers=None, limit=10, offset=0, target="A"):
    body = {"limit": limit}
    if sid is not None:
        body["id"] = sid
        body["offset"] = offset
    else:
        body["towers"] = towers
        body["target"] = target
    status, data = _post({"path": "moves", "body": body})
    assert status == 200, f"expected 200, got {status}: {data}"
    return data


def _apply(towers, moves):
    for mv in moves:
        s, d = "ABC".index(mv[0]), "ABC".index(mv[1])
        towers[d].append(towers[s].pop())
    return towers


def test_ui_served():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/") as res:
        assert res.status == 200
        html = res.read().decode()
    assert "Towers of Hanoi" in html
    assert "<script>" in html and "</html>" in html
    for needle in ('src="http', "src='http", 'href="http', "<link"):
        assert needle not in html, f"external resource reference {needle!r}"


def test_classic_game_and_batches():
    g = _game(kind="classic", pieces=5, target="C")
    assert g["n"] == 5 and g["total"] == 31
    assert g["towers"] == [[1, 2, 3, 4, 5], [], []]
    _, pegs = build_pegs(g["towers"])
    reference = ["ABC"[s] + "ABC"[d] for s, d in generate_moves(5, pegs, 2)]
    got, offset = [], 0
    while True:
        batch = _fetch(sid=g["id"], offset=offset, limit=10)
        assert batch["offset"] == offset + len(batch["moves"])
        assert batch["total"] == 31
        assert batch["done"] == (batch["offset"] >= 31)
        got.extend(batch["moves"])
        offset = batch["offset"]
        if batch["done"] and not batch["moves"]:
            break
    assert got == reference, "fetched batches must equal the reference solution"
    assert offset == 31


def test_spec_example_resync():
    towers = [[1, 4, 6, 10, 13, 15, 17, 19, 22],
              [2, 3, 5, 8, 14, 16, 18, 20, 21],
              [7, 9, 11, 12]]
    g = _game(kind="custom",
              a="1 4 6 10 13 15 17 19 22",
              b="2 3 5 8 14 16 18 20 21",
              c="7 9 11 12",
              target="A")
    assert g["n"] == 22
    assert g["total"] == 1826671, "must match the README example"
    reference = ["ABC"[s] + "ABC"[d] for s, d in generate_moves(
        22, build_pegs([list(t) for t in towers])[1], 0)]
    assert len(reference) == 1826671

    pos = [list(t) for t in towers]
    first = _fetch(sid=g["id"], offset=0, limit=5)
    assert first["moves"] == reference[:5]
    _apply(pos, first["moves"])
    # Resuming from the new position must continue the same solution.
    second = _fetch(towers=pos, limit=5)
    assert second["total"] == 1826671 - 5
    assert second["moves"] == reference[5:10]


def test_manual_moves_resume():
    g = _game(kind="classic", pieces=4, target="C")
    reference = ["ABC"[s] + "ABC"[d] for s, d in generate_moves(4, bytearray(5), 2)]
    assert g["total"] == 15
    pos = g["towers"]
    _apply(pos, reference[:3])
    resume = _fetch(towers=pos, target="C")
    assert resume["total"] == 12
    assert resume["moves"] == reference[3:3 + resume["offset"]]


def test_full_playthrough():
    # Mirrors the browser: auto-play in batches, stop, one manual move
    # (the next optimal move), resume, play to completion.
    g = _game(kind="custom", a="1 3 5", b="2", c="4", target="C")
    towers = [list(t) for t in g["towers"]]
    n, pegs = build_pegs(towers)
    reference = ["ABC"[s] + "ABC"[d] for s, d in generate_moves(n, pegs, 2)]
    assert g["total"] == len(reference)

    sid, offset = g["id"], 0
    first = _fetch(sid=sid, offset=offset, limit=7)
    assert first["moves"] == reference[:7]
    _apply(towers, first["moves"])

    mv = reference[7]
    s, d = "ABC".index(mv[0]), "ABC".index(mv[1])
    piece, top = towers[s].pop(), (towers[d][-1] if towers[d] else None)
    assert top is None or piece > top, "the next optimal move must be legal"
    towers[d].append(piece)

    resume = _fetch(towers=towers, target="C")
    assert resume["total"] == len(reference) - 8
    assert resume["moves"] == reference[8:8 + resume["offset"]]
    _apply(towers, resume["moves"])
    sid, offset = resume["id"], resume["offset"]

    applied = 8 + len(resume["moves"])
    while True:
        batch = _fetch(sid=sid, offset=offset, limit=10)
        assert not batch["moves"] or applied + len(batch["moves"]) <= len(reference)
        _apply(towers, batch["moves"])
        applied += len(batch["moves"])
        offset = batch["offset"]
        if batch["done"] and not batch["moves"]:
            break
    assert applied == len(reference)
    assert towers[2] == list(range(1, n + 1)) and not towers[0] and not towers[1]


def test_session_eviction():
    sids = [_game(kind="classic", pieces=2, target="C")["id"]
            for _ in range(hanoi_web.MAX_SESSIONS + 1)]
    status, data = _post({"path": "moves", "body": {"id": sids[0], "offset": 0, "limit": 5}})
    assert status == 404 and "expired" in data["error"]
    status, data = _post({"path": "moves", "body": {"id": sids[-1], "offset": 0, "limit": 5}})
    assert status == 200 and len(data["moves"]) > 0


def test_offset_mismatch_and_unknown_session():
    g = _game(kind="classic", pieces=3, target="B")
    status, data = _post({"path": "moves", "body": {"id": g["id"], "offset": 9, "limit": 5}})
    assert status == 400 and "mismatch" in data["error"]
    status, data = _post({"path": "moves", "body": {"id": "does-not-exist", "offset": 0, "limit": 5}})
    assert status == 404


def test_limit_clamped():
    g = _game(kind="classic", pieces=15, target="C")
    assert g["total"] == 32767
    batch = _fetch(sid=g["id"], offset=0, limit=999999)
    assert len(batch["moves"]) == hanoi_web.MAX_BATCH


def test_invalid_requests():
    status, data = _post({"path": "game", "body": {"kind": "classic", "pieces": 0, "target": "C"}})
    assert status == 400
    status, data = _post({"path": "game", "body": {"kind": "classic", "pieces": 33, "target": "C"}})
    assert status == 400
    status, data = _post({"path": "game", "body": {"kind": "classic", "pieces": 8, "target": "D"}})
    assert status == 400
    status, data = _post({"path": "game", "body": {"kind": "nope", "target": "C"}})
    assert status == 400
    status, data = _post({"path": "game",
                          "body": {"kind": "custom", "a": "1 1", "b": "", "c": "", "target": "A"}})
    assert status == 400
    status, data = _post({"path": "game",
                          "body": {"kind": "custom", "a": "1 3", "b": "", "c": "", "target": "A"}})
    assert status == 400, "missing piece 2 must be rejected"
    status, data = _post({"path": "game",
                          "body": {"kind": "custom", "a": "1 2 3", "b": "4", "c": "10", "target": "A"}})
    assert status == 400, "hole in the piece numbering must be rejected"


def main():
    global SERVER, PORT
    SERVER, PORT = _start()
    tests = [
        test_ui_served,
        test_classic_game_and_batches,
        test_spec_example_resync,
        test_manual_moves_resume,
        test_full_playthrough,
        test_session_eviction,
        test_offset_mismatch_and_unknown_session,
        test_limit_clamped,
        test_invalid_requests,
    ]
    failures = 0
    try:
        for test in tests:
            t0 = time.monotonic()
            try:
                test()
            except Exception:
                failures += 1
                print(f"FAIL {test.__name__}")
                traceback.print_exc()
            else:
                print(f"ok {test.__name__} ({time.monotonic() - t0:.1f}s)")
    finally:
        SERVER.shutdown()
    if failures:
        sys.exit(f"{failures} test(s) failed")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
