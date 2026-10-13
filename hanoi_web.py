#!/usr/bin/env python3
"""Animated web front end for the Hanoi solver.

Usage:
    python3 hanoi_web.py [port]        # default 8000
    python3 hanoi_web.py --local [port]

By default the server listens on all network interfaces, so other machines
on the local network can open http://<this machine's IP>:<port>/ .  Use
--local to restrict access to the machine itself.  The UI holds only small
prefetched batches of moves (see POST /api/moves) rather than the whole
solution, so any position the solver accepts can be animated; the piece
count is capped at 32 for rendering.
"""

import json
import secrets
import socket
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from hanoi import HanoiError, build_pegs, count_moves, generate_moves, parse_tower_line

MAX_PIECES = 32
MAX_SESSIONS = 16
MAX_BATCH = 2048
MAX_BODY = 64 * 1024
DEFAULT_PORT = 8000

_sessions = OrderedDict()
_sessions_lock = threading.Lock()


class Gone(Exception):
    """Session expired; the client should resume from its current position."""


def _new_session(n, pegs, target):
    total = count_moves(n, pegs, target)
    sess = {
        "gen": iter(generate_moves(n, pegs, target)),
        "total": total,
        "offset": 0,
    }
    sid = secrets.token_urlsafe(12)
    with _sessions_lock:
        _sessions[sid] = sess
        _sessions.move_to_end(sid)
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    return sid, sess


def _take(sess, limit):
    moves = []
    gen = sess["gen"]
    for _ in range(limit):
        try:
            src, dst = next(gen)
        except StopIteration:
            break
        moves.append("ABC"[src] + "ABC"[dst])
    return moves


class Handler(BaseHTTPRequestHandler):
    server_version = "HanoiWeb/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, content_type):
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise HanoiError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/game":
                self._game(body)
            elif path == "/api/moves":
                self._moves(body)
            else:
                self._json(404, {"error": "not found"})
        except HanoiError as e:
            self._json(400, {"error": str(e)})
        except Gone as e:
            self._json(404, {"error": str(e)})
        except (json.JSONDecodeError, ValueError) as e:
            self._json(400, {"error": "bad request"})

    def _check_target(self, body):
        target = str(body.get("target", "C")).strip().upper()
        if target not in "ABC":
            raise HanoiError(f"target tower must be A, B or C, got {body.get('target')!r}")
        return "ABC".index(target)

    def _limit(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise HanoiError("limit must be a number")
        return max(1, min(value, MAX_BATCH))

    def _game(self, body):
        if not isinstance(body, dict):
            raise HanoiError("expected a JSON object")
        target = self._check_target(body)
        kind = body.get("kind")
        if kind == "classic":
            try:
                n = int(body.get("pieces"))
            except (TypeError, ValueError):
                raise HanoiError("pieces must be a number")
            if not 1 <= n <= MAX_PIECES:
                raise HanoiError(f"pieces must be between 1 and {MAX_PIECES}")
            towers = [list(range(1, n + 1)), [], []]
        elif kind == "custom":
            towers = []
            for field, name in zip("abc", "ABC"):
                line = body.get(field)
                if not isinstance(line, str):
                    raise HanoiError(f"tower {name} must be a string of piece numbers")
                towers.append(parse_tower_line(line, name))
        else:
            raise HanoiError("kind must be 'classic' or 'custom'")
        n, pegs = build_pegs(towers)
        if n > MAX_PIECES:
            raise HanoiError(f"the web UI is limited to {MAX_PIECES} pieces")
        sid, sess = _new_session(n, pegs, target)
        self._json(200, {
            "id": sid,
            "n": n,
            "total": sess["total"],
            "target": "ABC"[target],
            "towers": towers,
        })

    def _moves(self, body):
        if not isinstance(body, dict):
            raise HanoiError("expected a JSON object")
        limit = self._limit(body.get("limit", 256))
        sid = body.get("id")
        if sid is not None:
            if "offset" not in body:
                raise HanoiError("offset is required when id is given")
            with _sessions_lock:
                sess = _sessions.get(sid)
                if sess is None:
                    raise Gone("game session expired; resume from the current position")
                if int(body["offset"]) != sess["offset"]:
                    raise HanoiError("offset mismatch; resume from the current position")
                moves = _take(sess, limit)
                sess["offset"] += len(moves)
                _sessions.move_to_end(sid)
            done = sess["offset"] >= sess["total"]
            self._json(200, {"id": sid, "moves": moves,
                             "offset": sess["offset"], "total": sess["total"], "done": done})
            return
        towers = body.get("towers")
        if not isinstance(towers, list) or len(towers) != 3:
            raise HanoiError("towers must be a list of 3 lists")
        for tower in towers:
            if not isinstance(tower, list) or not all(
                    isinstance(p, int) and not isinstance(p, bool) for p in tower):
                raise HanoiError("towers must contain piece numbers")
        target = self._check_target(body)
        n, pegs = build_pegs(towers)
        if n > MAX_PIECES:
            raise HanoiError(f"the web UI is limited to {MAX_PIECES} pieces")
        sid, sess = _new_session(n, pegs, target)
        with _sessions_lock:
            moves = _take(sess, limit)
            sess["offset"] += len(moves)
        done = sess["offset"] >= sess["total"]
        self._json(200, {"id": sid, "moves": moves,
                         "offset": sess["offset"], "total": sess["total"], "done": done})


def make_server(address=("127.0.0.1", 0)):
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def _lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def main(argv):
    port = DEFAULT_PORT
    local_only = False
    args = argv[1:]
    if args and args[0] == "--local":
        local_only = True
        args = args[1:]
    if args:
        try:
            port = int(args[0])
        except ValueError:
            sys.exit(f"hanoi_web: invalid port: {args[0]!r}")
        if not 1 <= port <= 65535:
            sys.exit("hanoi_web: port must be between 1 and 65535")
    host = "127.0.0.1" if local_only else "0.0.0.0"
    server = make_server((host, port))
    print("Hanoi web animation (Ctrl-C to stop):", flush=True)
    print(f"  this machine:   http://127.0.0.1:{port}/", flush=True)
    if not local_only:
        ip = _lan_ip()
        print(f"  other machines: http://{ip or '127.0.0.1'}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Towers of Hanoi</title>
<style>
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body {
  background: var(--bg); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  display: flex; flex-direction: column;
}
[data-theme="light"] {
  --bg: #f6f3ec; --panel: #fff; --ink: #27221a; --muted: #6d6353;
  --board: #efe8d8; --post: #9b8c6d; --base: #77684b; --accent: #2f7d3b;
  --danger: #c22f2f; --disc-edge: rgba(0,0,0,.30); --shadow: rgba(0,0,0,.12);
}
[data-theme="dark"] {
  --bg: #15171c; --panel: #1d2027; --ink: #e9e7e1; --muted: #9b968b;
  --board: #1a1d24; --post: #4c5871; --base: #333d52; --accent: #57b463;
  --danger: #e5534b; --disc-edge: rgba(255,255,255,.22); --shadow: rgba(0,0,0,.5);
}
[data-theme="gray"] {
  --bg: #e9e9e9; --panel: #f5f5f5; --ink: #1c1c1c; --muted: #5c5c5c;
  --board: #dedede; --post: #777; --base: #4d4d4d; --accent: #2b2b2b;
  --danger: #000; --disc-edge: rgba(0,0,0,.5); --shadow: rgba(0,0,0,.18);
}
header { display: flex; flex-wrap: wrap; gap: 10px 20px; align-items: center; padding: 14px 22px; }
h1 { font-size: 19px; margin: 0; font-weight: 650; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; margin-left: auto; }
button {
  font: inherit; color: var(--ink); background: var(--panel);
  border: 1px solid var(--muted); border-radius: 8px; padding: 7px 14px; cursor: pointer;
}
button:hover:not(:disabled) { border-color: var(--ink); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; min-width: 80px; }
button:disabled { opacity: .45; cursor: default; }
.themes { display: flex; border: 1px solid var(--muted); border-radius: 8px; overflow: hidden; }
.themes button { border: 0; border-radius: 0; padding: 7px 11px; }
.themes button.active { background: var(--muted); color: var(--bg); }
.speed { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; }
.speed input { accent-color: var(--accent); }
main { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 0 16px 18px; }
svg#board { width: 100%; max-width: 960px; height: auto; background: var(--board); border-radius: 14px; box-shadow: 0 1px 4px var(--shadow); }
#statusbar { display: flex; gap: 16px; align-items: baseline; margin-top: 10px; min-height: 22px; font-size: 14px; flex-wrap: wrap; justify-content: center; }
#counter { color: var(--muted); }
#status.error { color: var(--danger); }
.base { fill: var(--base); }
.post { fill: var(--post); }
.tlabel { fill: var(--muted); font-size: 20px; font-weight: 650; }
.targetmark { fill: var(--accent); }
.hit { fill: transparent; cursor: pointer; }
.disc { stroke: var(--disc-edge); stroke-width: 1; cursor: pointer; }
.disc.selected { stroke: var(--accent); stroke-width: 3; }
.disc.mover { pointer-events: none; }
@keyframes shake { 0%, 100% { transform: translateX(0); } 25% { transform: translateX(-5px); } 75% { transform: translateX(5px); } }
.shake { animation: shake .3s ease-in-out 2; }
dialog {
  background: var(--panel); color: var(--ink); border: 1px solid var(--muted);
  border-radius: 12px; padding: 22px 24px; width: min(460px, calc(100vw - 40px));
}
dialog::backdrop { background: rgba(0,0,0,.4); }
dialog h2 { margin: 0 0 12px; font-size: 17px; }
dialog label { display: block; margin: 10px 0; }
dialog input[type="text"], dialog input[type="number"], dialog select {
  font: inherit; margin-left: 8px; padding: 6px 8px; width: 250px; max-width: 62vw;
  background: var(--bg); color: var(--ink); border: 1px solid var(--muted); border-radius: 6px;
}
dialog input[type="number"] { width: 90px; }
dialog .error { color: var(--danger); min-height: 20px; margin: 12px 0 0; }
dialog menu { padding: 0; margin: 14px 0 0; display: flex; justify-content: flex-end; gap: 10px; }
.hint { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Towers of Hanoi</h1>
  <div class="controls">
    <button id="playBtn" class="primary" title="Play / stop the animated optimal solution">Play</button>
    <button id="newBtn" title="Start a new game">New game</button>
    <label class="speed">Speed
      <input id="speed" type="range" min="0" max="1000" value="537">
      <span id="speedLabel"></span>
    </label>
    <div class="themes" role="group" aria-label="Color theme">
      <button data-theme-btn="light">Light</button>
      <button data-theme-btn="dark">Dark</button>
      <button data-theme-btn="gray">Gray</button>
    </div>
  </div>
</header>
<main>
  <svg id="board" viewBox="0 0 960 560" role="img" aria-label="Hanoi board with three towers">
    <g id="static"></g>
    <g id="discs"></g>
  </svg>
  <div id="statusbar">
    <span id="counter"></span>
    <span id="status"></span>
  </div>
</main>
<dialog id="newGame">
  <form id="newForm" method="dialog">
    <h2>New game</h2>
    <label><input type="radio" name="kind" value="classic" checked> Classic: full stack on tower A</label>
    <label><input type="radio" name="kind" value="custom"> Custom starting position</label>
    <div id="classicFields">
      <label>Pieces <input id="pieces" type="number" min="1" max="32" value="8"></label>
    </div>
    <div id="customFields" hidden>
      <label>Tower A <input id="tA" type="text" placeholder="e.g. 1 3 5-9 11" autocomplete="off"></label>
      <label>Tower B <input id="tB" type="text" placeholder="e.g. 2,4,10" autocomplete="off"></label>
      <label>Tower C <input id="tC" type="text" placeholder="e.g. 12 14-20" autocomplete="off"></label>
      <p class="hint">Piece numbers separated by spaces or commas, with ranges like 5-9. Every piece 1..max must appear exactly once.</p>
    </div>
    <label>Target tower
      <select id="target"><option>A</option><option>B</option><option selected>C</option></select>
    </label>
    <p id="gameError" class="error" role="alert"></p>
    <menu>
      <button value="cancel">Cancel</button>
      <button id="startBtn" type="button" class="primary">Start</button>
    </menu>
  </form>
</dialog>
<script>
"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const TOWERS = "ABC";
const $ = (id) => document.getElementById(id);
const VIEW_W = 960, BASE_Y = 470;
const TOWER_X = [160, 480, 800];
const MAX_W = 260, MIN_W = 46;
const BATCH = 256, MAXPIECES = 32;

const state = {
  n: 0, target: 2,
  towers: [[], [], []],
  total: 0, moveCount: 0,
  mode: "paused",
  sid: null, offset: 0,
  queue: [], stale: true,
  anim: null,
  selected: -1,
};
let GEO = { unit: 25, discH: 22 };
let rate = 1;
let inflight = null;
let statusTimer = 0;

function api(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (res) => {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  });
}

function el(name, attrs, parent) {
  const e = document.createElementNS(SVGNS, name);
  for (const k of Object.keys(attrs)) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}

function setupGeometry() {
  const n = Math.max(1, state.n);
  const unit = Math.min(25, (BASE_Y - 60) / n);
  const gap = Math.max(1, unit * 0.15);
  GEO = { unit, discH: unit - gap };
}

function discW(piece) {
  if (state.n <= 1) return MAX_W;
  return MIN_W + (MAX_W - MIN_W) * (state.n - piece) / (state.n - 1);
}

function discColor(piece) {
  const theme = document.documentElement.dataset.theme;
  const k = state.n <= 1 ? 0 : (piece - 1) / (state.n - 1);
  if (theme === "gray") return `hsl(0 0% ${Math.round(78 - 52 * k)}%)`;
  const hue = Math.round(((piece - 1) * 360) / Math.max(1, state.n));
  return `hsl(${hue} 62% ${theme === "dark" ? 60 : 46}%)`;
}

function renderStatic() {
  setupGeometry();
  const g = $("static");
  g.innerHTML = "";
  el("rect", { x: 70, y: BASE_Y, width: VIEW_W - 140, height: 16, rx: 5, class: "base" }, g);
  for (let t = 0; t < 3; t++) {
    const postTop = BASE_Y - Math.max(1, state.n) * GEO.unit - 14;
    el("rect", { x: TOWER_X[t] - 4, y: postTop, width: 8, height: BASE_Y - postTop, rx: 3, class: "post" }, g);
    if (t === state.target)
      el("path", { d: `M ${TOWER_X[t] - 10} ${postTop - 19} h 20 l -10 13 Z`, class: "targetmark" }, g);
    el("text", { x: TOWER_X[t], y: BASE_Y + 42, class: "tlabel", "text-anchor": "middle" }, g)
      .textContent = TOWERS[t];
    const hit = el("rect", { x: TOWER_X[t] - 130, y: 30, width: 260, height: BASE_Y - 30, class: "hit" }, g);
    hit.dataset.tower = String(t);
  }
}

function renderDiscs() {
  const g = $("discs");
  g.innerHTML = "";
  for (let t = 0; t < 3; t++) {
    const stack = state.towers[t];
    for (let i = 0; i < stack.length; i++) {
      const piece = stack[i];
      if (state.anim && state.anim.piece === piece) continue;
      const w = discW(piece);
      const r = el("rect", {
        x: TOWER_X[t] - w / 2,
        y: BASE_Y - (i + 1) * GEO.unit,
        width: w, height: GEO.discH,
        rx: Math.min(5, GEO.discH / 2),
        fill: discColor(piece),
        class: "disc" + (piece === state.selected ? " selected" : ""),
      }, g);
      r.dataset.piece = String(piece);
    }
  }
}

function isSolved() {
  return state.towers.every((tw, t) => t === state.target || tw.length === 0);
}

function idleText() {
  if (isSolved()) return "Solved.";
  if (state.mode === "auto") return "Solving\u2026";
  return "Stopped \u2014 click a piece, then a tower to move it, or press Play.";
}

function setStatus(msg, isError) {
  const s = $("status");
  delete s.dataset.flash;
  clearTimeout(statusTimer);
  s.textContent = msg;
  s.classList.toggle("error", !!isError);
}

function flash(msg) {
  const s = $("status");
  s.textContent = msg;
  s.classList.add("error");
  s.dataset.flash = "1";
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    if (s.dataset.flash) {
      delete s.dataset.flash;
      s.classList.remove("error");
      s.textContent = idleText();
    }
  }, 2600);
}

function updateHud() {
  const toGo = Math.max(0, state.total - state.offset);
  $("counter").textContent = state.total
    ? `move ${state.moveCount} \u00b7 ${toGo} to go`
    : `move ${state.moveCount}`;
}

function updateButtons() {
  $("playBtn").textContent = state.mode === "auto" ? "Stop" : "Play";
  $("playBtn").disabled = isSolved();
}

function applyMove(fromT, toT) {
  const piece = state.towers[fromT].pop();
  state.towers[toT].push(piece);
  state.moveCount++;
  renderDiscs();
  updateHud();
  return piece;
}

const ease = (f) => (f < 0.5 ? 4 * f * f * f : 1 - Math.pow(-2 * f + 2, 3) / 2);

function animateMove(fromT, toT, ms, done) {
  const piece = state.towers[fromT][state.towers[fromT].length - 1];
  const w = discW(piece);
  const h = GEO.discH;
  const anim = { piece, fromT, toT, el: null, raf: 0 };
  state.anim = anim;
  renderDiscs();
  anim.el = el("rect", { width: w, height: h, rx: Math.min(5, h / 2), fill: discColor(piece), class: "disc mover" }, $("discs"));
  const sy = BASE_Y - state.towers[fromT].length * GEO.unit;
  const landY = BASE_Y - (state.towers[toT].length + 1) * GEO.unit;
  const liftY = Math.min(sy, landY) - 0.7 * GEO.unit;
  const phases = [
    { x: TOWER_X[fromT], y: sy, dx: 0, dy: liftY - sy },
    { x: TOWER_X[fromT], y: liftY, dx: TOWER_X[toT] - TOWER_X[fromT], dy: 0 },
    { x: TOWER_X[toT], y: liftY, dx: 0, dy: landY - liftY },
  ];
  const weights = phases.map((p) => Math.hypot(p.dx, p.dy));
  const totalW = weights.reduce((s, x) => s + x, 0) || 1;
  const durs = weights.map((x) => (ms * x) / totalW);
  const starts = [];
  let acc = 0;
  for (const d of durs) { starts.push(acc); acc += d; }
  let pi = 0, start = null;
  function frame(now) {
    if (start === null) start = now;
    const e = now - start;
    if (e >= ms) { finish(); return; }
    while (pi < 2 && e >= starts[pi] + durs[pi]) pi++;
    const p = phases[pi];
    let f = durs[pi] ? (e - starts[pi]) / durs[pi] : 1;
    f = Math.max(0, Math.min(1, f));
    const k = ease(f);
    anim.el.setAttribute("x", p.x + p.dx * k - w / 2);
    anim.el.setAttribute("y", p.y + p.dy * k);
    anim.raf = requestAnimationFrame(frame);
  }
  function finish() {
    state.anim = null;
    cancelAnimationFrame(anim.raf);
    anim.el.remove();
    done();
  }
  anim.raf = requestAnimationFrame(frame);
}

async function fetchBatch() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await api("/api/moves", { id: state.sid, offset: state.offset, limit: BATCH });
      state.offset = res.offset;
      state.total = res.total;
      state.queue.push(...res.moves);
      updateHud();
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

async function resync() {
  if (inflight) await inflight;
  state.stale = false;
  state.queue.length = 0;
  const res = await api("/api/moves", { towers: state.towers, target: "ABC"[state.target], limit: BATCH });
  state.sid = res.id;
  state.offset = res.offset;
  state.total = res.total;
  state.queue.push(...res.moves);
  updateHud();
}

async function tick() {
  if (state.mode !== "auto" || state.anim) return;
  if (state.queue.length === 0) {
    if (state.stale) {
      try { await resync(); } catch (err) { return fail(err.message); }
    }
    if (state.mode !== "auto") return;
    if (state.queue.length === 0) {
      if (state.offset >= state.total) return onSolved();
      try { await fetchBatch(); } catch (err) { return fail(err.message); }
    }
    if (state.mode !== "auto") return;
    if (state.queue.length === 0) return onSolved();
  }
  const mv = state.queue.shift();
  const fromT = mv.charCodeAt(0) - 65;
  const toT = mv.charCodeAt(1) - 65;
  animateMove(fromT, toT, Math.max(120, 1000 / rate), () => {
    applyMove(fromT, toT);
    tick();
  });
}

function onSolved() {
  state.mode = "paused";
  state.selected = -1;
  renderDiscs();
  updateButtons();
  setStatus(`Solved in ${state.moveCount} moves.`);
}

function fail(msg) {
  state.mode = "paused";
  state.stale = true;
  state.queue.length = 0;
  if (state.anim) {
    cancelAnimationFrame(state.anim.raf);
    state.anim.el.remove();
    state.anim = null;
  }
  renderDiscs();
  updateButtons();
  flash(msg);
}

function play() {
  if (state.mode === "auto" || state.anim) return;
  if (isSolved()) { flash("Already solved \u2014 start a new game."); return; }
  state.mode = "auto";
  state.selected = -1;
  renderDiscs();
  updateButtons();
  tick();
}

function stop() {
  state.mode = "paused";
  if (state.anim) {
    const a = state.anim;
    state.anim = null;
    cancelAnimationFrame(a.raf);
    a.el.remove();
    applyMove(a.fromT, a.toT);
    state.selected = -1;
    state.stale = true;
  }
  updateButtons();
  setStatus(idleText());
}

function towerOf(piece) {
  return state.towers.findIndex((tw) => tw.includes(piece));
}

function shakeEl(elm) {
  elm.classList.add("shake");
  setTimeout(() => elm.classList.remove("shake"), 700);
}

function attemptMove(fromT, toT) {
  const piece = state.towers[fromT][state.towers[fromT].length - 1];
  const top = state.towers[toT][state.towers[toT].length - 1];
  if (top !== undefined && piece < top) {
    flash(`Illegal: piece ${piece} cannot be placed on top of smaller piece ${top} (tower ${TOWERS[toT]}).`);
    const elm = $("discs").querySelector(`[data-piece="${top}"]`);
    if (elm) shakeEl(elm);
    return;
  }
  state.selected = -1;
  animateMove(fromT, toT, 320, () => {
    applyMove(fromT, toT);
    state.stale = true;
    setStatus(isSolved() ? `Solved in ${state.moveCount} moves.` : idleText());
    updateButtons();
  });
}

$("board").addEventListener("click", (e) => {
  if (state.mode !== "paused" || state.anim) return;
  const tgt = e.target.closest("[data-piece],[data-tower]");
  if (!tgt) return;
  if (tgt.dataset.piece !== undefined) {
    const piece = +tgt.dataset.piece;
    const t = towerOf(piece);
    const isTop = state.towers[t][state.towers[t].length - 1] === piece;
    if (state.selected >= 0) {
      const st = towerOf(state.selected);
      if (st !== t) { attemptMove(st, t); return; }
    }
    if (!isTop) {
      flash("Only the top piece of a tower can move.");
      shakeEl(tgt);
      return;
    }
    state.selected = piece === state.selected ? -1 : piece;
    renderDiscs();
    setStatus(state.selected >= 0
      ? `Piece ${state.selected} selected \u2014 click a tower to move it, or click it again to cancel.`
      : idleText());
    return;
  }
  if (state.selected < 0) return;
  const t = +tgt.dataset.tower;
  const st = towerOf(state.selected);
  if (st === t) {
    state.selected = -1;
    renderDiscs();
    setStatus(idleText());
    return;
  }
  attemptMove(st, t);
});

function startGameFromDialog() {
  const kind = document.querySelector('input[name="kind"]:checked').value;
  const target = $("target").value;
  const err = $("gameError");
  err.textContent = "";
  let body;
  if (kind === "classic") {
    const n = parseInt($("pieces").value, 10);
    if (!Number.isInteger(n) || n < 1 || n > MAXPIECES) {
      err.textContent = `Pieces must be a whole number from 1 to ${MAXPIECES}.`;
      return;
    }
    body = { kind, pieces: n, target };
  } else {
    body = { kind, target, a: $("tA").value, b: $("tB").value, c: $("tC").value };
  }
  const btn = $("startBtn");
  btn.disabled = true;
  api("/api/game", body)
    .then((g) => {
      $("newGame").close();
      startGame(g);
    })
    .catch((e) => { err.textContent = e.message; })
    .finally(() => { btn.disabled = false; });
}

function startGame(g) {
  if (state.anim) {
    cancelAnimationFrame(state.anim.raf);
    state.anim.el.remove();
    state.anim = null;
  }
  inflight = null;
  state.n = g.n;
  state.towers = g.towers;
  state.target = "ABC".indexOf(g.target);
  state.total = g.total;
  state.moveCount = 0;
  state.sid = g.id;
  state.offset = 0;
  state.queue = [];
  state.stale = false;
  state.mode = "paused";
  state.selected = -1;
  renderStatic();
  renderDiscs();
  updateButtons();
  updateHud();
  setStatus(g.total === 0 ? "Already solved \u2014 start another game." : idleText());
}

function rateFromSlider(v) { return 0.2 * Math.pow(20, v / 1000); }

function updateSpeedLabel() {
  $("speedLabel").textContent = rate >= 0.95
    ? `${rate.toFixed(1)} moves/s`
    : `${(1 / rate).toFixed(1)} s/move`;
}

$("speed").addEventListener("input", (e) => {
  rate = rateFromSlider(+e.target.value);
  updateSpeedLabel();
});

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("hanoi-theme", t); } catch (err) { /* private mode */ }
  document.querySelectorAll("[data-theme-btn]").forEach((b) =>
    b.classList.toggle("active", b.dataset.themeBtn === t));
  renderDiscs();
}

document.querySelectorAll("[data-theme-btn]").forEach((b) => {
  b.addEventListener("click", () => setTheme(b.dataset.themeBtn));
});

$("playBtn").addEventListener("click", () => {
  if (state.mode === "auto") stop();
  else play();
});

$("newBtn").addEventListener("click", () => {
  $("gameError").textContent = "";
  $("newGame").showModal();
});

document.querySelectorAll('input[name="kind"]').forEach((r) => {
  r.addEventListener("change", () => {
    const custom = document.querySelector('input[name="kind"]:checked').value === "custom";
    $("classicFields").hidden = custom;
    $("customFields").hidden = !custom;
  });
});

$("startBtn").addEventListener("click", startGameFromDialog);
$("newForm").addEventListener("submit", (e) => {
  e.preventDefault();
  startGameFromDialog();
});

(function init() {
  let theme = null;
  try { theme = localStorage.getItem("hanoi-theme"); } catch (err) { /* private mode */ }
  if (!theme) theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  setTheme(theme);
  rate = rateFromSlider(+$("speed").value);
  updateSpeedLabel();
  api("/api/game", { kind: "classic", pieces: 8, target: "C" })
    .then(startGame)
    .catch((err) => setStatus(`Cannot reach the solver: ${err.message}`, true));
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main(sys.argv)
