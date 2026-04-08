# Shift Chase: A Live-Mutating ASCII Game

A terminal game where an AI agent (Claude) acts as game designer **in real time**.
You play a 2D ASCII game with arrow keys and space bar. Meanwhile, Claude watches
how you play and rewrites the game's rules while it's running — changing mechanics,
swapping game modes, adjusting difficulty — all through hot-reloaded code.

The game never stops. It just keeps changing.

![Claude editing game rules in real time while the player plays](docs/screenshot_example.png)

## How to play

```bash
python3 -m venv venv
source venv/bin/activate
python game.py
```

Controls:
- **Arrow keys** — move
- **Space** — action (stun enemies in the default mode)
- **q** — quit

## How it works

The project has two participants: you (the player) and Claude (the game designer).

You run `game.py` in your terminal. In a separate session, Claude is running in
Claude Code. When you say "go", Claude starts editing `rules.py` — the file that
contains all game logic — and the running game hot-reloads those changes instantly.

There are three files that bridge the player and the AI:

```
  Claude Code                              game.py (your terminal)
 ┌──────────────┐                         ┌────────────────────��─┐
 │              │── writes rules.py ────▶ │ watches mtime,       │
 │  reads state │                         │ re-imports on change  │
 │  to see how  │── writes announce.txt ▶ │ shows as in-game     │
 │  you're doing│                         │ banner messages       │
 │              │◀─ reads state.json ──── │ writes every ~30 ticks│
 └──────────────┘                         └──────────────────────┘
```

- **`rules.py`** — All game logic. Claude rewrites this to change the game.
  The engine detects the file change and re-imports it without restarting.
- **`announce.txt`** — Claude writes messages here. The game displays them as
  temporary banners ("Enemies are faster now!", "Welcome to Snake mode.").
- **`state.json`** — The game writes your position, score, lives, and the full
  board state here. Claude reads it to understand what's happening and decide
  what to change next.

No sockets, no daemons, no extra processes. Just file reads and writes.

## Architecture

### The engine (`game.py`)

A curses-based game loop that does **not** contain game logic. It handles:

- Input collection (arrow keys, space bar)
- File-watching (`rules.py` mtime for hot-reload, `announce.txt` for messages)
- Calling `rules.on_tick(state, cfg)` every frame — this is where all game
  logic lives
- Rendering `state["grid"]` (a list of strings, one per row) plus a HUD line
- Writing `state.json` for Claude to read

The engine is structured so that all logic functions are pure (no curses
dependency) and can be unit-tested directly. Curses is isolated to the
`render_curses()` and `run()` functions.

### The rules (`rules.py`)

This is the file Claude edits live. It exports three functions:

- `get_config()` — Returns a dict of settings (grid size, tick rate, lives, etc.)
- `on_tick(state, cfg)` — Called every frame. Contains **all** game logic:
  player movement, enemy AI, collision detection, item spawning, and grid
  construction. Because this function owns everything, Claude can make the game
  do anything — chase, snake, breakout, shooter — just by rewriting this file.
- `on_reload(state, prev_cfg, cfg)` — Called when the file is hot-reloaded.
  Handles state migration (e.g., adjusting enemy count, rebuilding walls for a
  new grid size).

### State

Game state is a plain Python dict that persists across rule reloads. The engine
carries it forward; the rules module defines what keys exist in it. This means
Claude can add new state keys (portals, bullets, gravity) without touching the
engine.

## How it was built

This project was built by a human and Claude working together in Claude Code.

**The problem:** Claude Code can edit files and run shell commands, but it can't
directly control a running terminal UI. A running curses game can't talk to
Claude Code. How do you bridge the two?

**The answer:** Files. The game watches `rules.py` for mtime changes and
re-imports it. Claude edits `rules.py` using its normal file-editing tools. The
game writes `state.json` so Claude can read it. That's the entire communication
protocol.

The build process was:

1. **Plan** — Wrote `PLAN.md` defining the architecture, the three-file
   communication protocol, and the separation between engine (dumb loop) and
   rules (all logic). The key insight was that `importlib` hot-reloading +
   file mtime watching is a natural bridge between Claude Code's file-editing
   tools and a running Python process.

2. **Engine** — Built `game.py` with a clean separation: pure functions for
   rules loading, config normalization, file watching, state management, input
   handling, and tick processing — all testable without curses. The curses code
   is a thin ~30-line rendering layer on top.

3. **Rules** — Built the initial `rules.py` as a chase game (collect stars,
   avoid ghosts, space to stun). All logic lives in `on_tick`, which populates
   `state["grid"]` for the engine to render.

4. **Tests** — 53 unit tests covering config normalization, rules loading,
   hot-reload (including state persistence across reloads and broken-file
   resilience), input handling, game logic (movement, wall collision, item
   collection, enemy contact, stun mechanics, game over), announce reading,
   state.json serialization, and tick processing. All tests run against pure
   functions — no curses mocking needed.

5. **Live test** — Ran the game, said "go", and Claude started editing
   `rules.py` in real time: slowing enemies, increasing item spawns, expanding
   stun radius. The hot-reload worked — changes appeared in the running game
   within a frame.

## Running tests

```bash
source venv/bin/activate
python -m unittest test_game -v
```

## Files

```
game1/
├── README.md        ← this file
├── PLAN.md          ← architecture and design document
├── game.py          ← the engine (you run this)
├── rules.py         ← game logic (Claude edits this live)
├── announce.txt     ← Claude's in-game messages
├── state.json       ← game state (written by engine, read by Claude)
└── test_game.py     ← unit tests
```
