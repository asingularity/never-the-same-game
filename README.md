# A Live-Mutating ASCII Game

A terminal game where an AI agent (Claude) acts as game designer **in real time**.
You play a 2D ASCII game with arrow keys and space bar. Meanwhile, Claude watches
how you play and rewrites the game's rules while it's running — changing mechanics,
swapping game modes, adjusting difficulty — all through hot-reloaded code.

The game never stops. It just keeps changing.

"I understand now. My fundamental mistake was trying to encode transitions in the code. I am the transition system. I should make many small rapid edits, each changing ONE dimension, every few seconds. The cumulative effect IS the smooth morph." - Claude Opus

![Claude editing game rules in real time while the player plays](docs/screenshot_example.png)

## How to play

```bash
python3 -m venv venv
source venv/bin/activate
python game.py
```

Make sure your terminal is at least **70 columns wide** — the game area is 40
columns, and a rules-summary sidebar is displayed to its right.

Controls:
- **Arrow keys** — move (meaning changes as the game evolves)
- **Space** — action (stun, shoot, etc. — changes as the game evolves)
- **q** — quit

## How it works

The project has two participants: you (the player) and Claude (the game designer).

You run `game.py` in your terminal. In a separate session, Claude is running in
Claude Code. When you say "go", Claude starts editing `rules.py` — the file that
contains all game logic — and the running game hot-reloads those changes instantly.

Three files bridge the player and the AI:

```
  Claude Code                              game.py (your terminal)
 +--------------+                         +----------------------+
 |              |-- writes rules.py ----->| watches mtime,       |
 |  reads state |                         | re-imports on change  |
 |  to see how  |-- writes announce.txt ->| shows as in-game     |
 |  you're doing|                         | banner messages       |
 |              |<- reads state.json -----| writes every ~30 ticks|
 +--------------+                         +----------------------+
```

- **`rules.py`** — All game logic. Claude edits this continuously to change the
  game. The engine detects the file change and re-imports it without restarting.
- **`announce.txt`** — Claude writes messages here. The game displays them as
  temporary banners ("The walls are shifting...", "You are now a snake.").
- **`state.json`** — The game writes your position, score, lives, and the full
  board state here. Claude reads it to understand what's happening and decide
  what to change next.

No sockets, no daemons, no extra processes. Just file reads and writes.

## The mutation system

Claude doesn't just tweak parameters — it continuously morphs the game through
four types of changes, defined in `meta_rules.md`:

| Type | What changes | Cadence |
|------|-------------|---------|
| **Type 1** | Numerical difficulty (speed, enemy count, spawn rates) | Every ~10 seconds |
| **Type 2** | Qualitative addition keeping mechanics (new enemy type, wall pattern) | Every ~30-60 seconds |
| **Type 3** | Mechanic change keeping game type (new scoring, new movement mode) | Every ~2-3 minutes |
| **Type 4** | Fundamental game type shift (chase becomes snake becomes shooter) | Every ~5 minutes |

The key design principle: **changes are smooth and continuous**. A Type 4 change
doesn't happen all at once — it unfolds over a minute by changing one dimension
at a time:

1. Game visual look / game board
2. Game mechanic / dynamic
3. Player visual look / feel
4. Player's controls-to-mechanic mapping
5. Scoring mechanism and rules

There is always a Type 4 change in progress. Claude is the transition system —
it makes many small rapid edits to `rules.py`, each changing one thing. The
cumulative effect is a smooth morph. A rules-summary sidebar on the right side
of the game area shows the current state of the rules at all times.

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

This is the file Claude edits live. It exports:

- `get_config()` — Returns a dict of settings (grid size, tick rate, lives, etc.)
- `on_tick(state, cfg)` — Called every frame. Delegates to isolated sub-functions
  for player movement, player action, enemy AI, items/scoring, and grid rendering.
  Each sub-function can be surgically edited independently.
- `on_reload(state, prev_cfg, cfg)` — Called when the file is hot-reloaded.
  Ensures new state keys exist with safe defaults.
- `render_hud(state, cfg)` — Custom HUD line.

The rules module builds `state["grid"]` with a sidebar appended to each row,
showing the current rules in a few words.

### State

Game state is a plain Python dict that persists across rule reloads. The engine
carries it forward; the rules module defines what keys exist in it. This means
Claude can add new state keys (trail, bullets, gravity) without touching the
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

The build process:

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
   avoid ghosts, space to stun). Structured with isolated sub-functions for
   each game aspect (movement, action, enemies, items, rendering) so that
   Claude can surgically edit one dimension at a time during play.

4. **Meta-rules** — Defined `meta_rules.md` specifying how Claude should evolve
   the game: four types of changes at different cadences, smooth continuous
   transitions, one dimension changing at a time, adaptive difficulty, and a
   sidebar showing current rules.

5. **Tests** — 53 unit tests covering config normalization, rules loading,
   hot-reload (including state persistence across reloads and broken-file
   resilience), input handling, game logic (movement, wall collision, item
   collection, enemy contact, stun mechanics, game over), announce reading,
   state.json serialization, and tick processing. All tests run against pure
   functions — no curses mocking needed.

6. **Live play** — Ran the game, said "go", and Claude started continuously
   editing `rules.py` in real time. The hot-reload worked — each edit appeared
   in the running game within a frame.

## Running tests

```bash
source venv/bin/activate
python -m unittest test_game -v
```

## Files

```
game1/
├── README.md                       ← this file
├── PLAN.md                         ← architecture and design document
├── meta_rules.md                   ← rules for how Claude mutates the game
├── game.py                         ← the engine (you run this)
├── rules.py                        ← game logic (Claude edits this live)
├── announce.txt                    ← Claude's in-game messages
├── state.json                      ← game state (written by engine, read by Claude)
├── test_game.py                    ← unit tests
└── docs/
    └── screenshot_example.png      ← screenshot of live editing
```
