# Live-Mutating ASCII Game — Plan

## Concept

A terminal game (Python, curses) where **Claude is the game designer in real time**.
The player runs a script and plays with arrow keys + space bar. Meanwhile, Claude
edits game files from a separate Claude Code session, and the running game
hot-reloads those changes instantly. The game morphs between different simple 2D
ASCII game styles — chase, dodge, snake, breakout, shooter, puzzle — keeping
things novel.

## How Claude interacts with the running game

This is the core architectural question. Claude Code has tools to **read and write
files** and **run shell commands**. The running game can **watch files for changes**.
That's the bridge.

```
┌──────────────┐         file write          ┌──────────────────┐
│  Claude Code  │ ──── edits rules.py ──────▶ │  game.py (running)│
│  (AI agent)   │                             │  watches file mtime│
│               │ ──── edits announce.txt ──▶ │  reads announcements│
│               │                             │                    │
│               │ ◀── reads state.json ────── │  writes game state │
└──────────────┘                              └──────────────────┘
```

Three file-based channels:

1. **`rules.py`** — Claude writes this; game hot-reloads it. Contains all game
   logic: configuration, entity definitions, tick behavior, rendering overrides,
   input handling. When this file changes, the game re-imports it and calls
   `on_reload()`.

2. **`announce.txt`** — Claude writes short messages here; the game displays them
   as banners/toasts. Used to narrate rule changes ("Enemies now chase you
   faster!", "Welcome to Snake mode.").

3. **`state.json`** — The game writes this every N ticks. Contains player
   position, score, lives, tick count, current phase, and any custom state.
   Claude reads this to understand what's happening and make informed decisions
   about what to change next.

No sockets, no IPC, no extra processes. Just files. This is robust, simple, and
plays to Claude Code's strengths.

## Architecture

### `game.py` — The Engine (stable, rarely changes)

A generic curses game loop. It does NOT contain game logic. It provides:

- **Input**: Collects arrow keys and space bar each frame. Stores the last
  directional input and a `space_pressed` flag in state.
- **Tick loop**: Runs at a configurable tick rate. Each tick:
  1. Collect input
  2. Check if `rules.py` mtime changed → if so, reload it
  3. Check if `announce.txt` changed → if so, read and queue message
  4. Call `rules.on_tick(state, cfg)` — this is where ALL game logic lives
  5. Call `rules.render(state, cfg)` or use default grid renderer
  6. Write `state.json` periodically
- **State**: A plain dict. Persists across rule reloads. The rules module owns
  what keys exist in it; the engine just carries the dict forward.
- **Rendering**: Default renderer draws a 2D grid from `state["grid"]` (a list
  of strings). Rules can populate this grid however they want. The engine also
  draws a HUD line (score, lives, message) and handles terminal-too-small.
- **Reload**: When `rules.py` changes, the engine re-imports it and calls
  `rules.on_reload(state, prev_cfg, new_cfg)`. The rules module migrates state
  as needed (e.g., resizing the grid, adding new entity lists).

### `rules.py` — The Brain (Claude edits this live)

This is the file Claude rewrites to change the game. It exports:

- `get_config()` → dict of settings (grid size, tick rate, title, etc.)
- `on_reload(state, prev_cfg, cfg)` → called when rules file changes; migrate state
- `on_tick(state, cfg)` → called every frame; ALL game logic goes here
  - Move player based on `state["input_dir"]` and `state["space"]`
  - Move enemies / entities
  - Check collisions
  - Update score, lives, etc.
  - Populate `state["grid"]` for rendering
- `render_hud(state, cfg)` → optional; return a string for the HUD line

Because `on_tick` owns everything, Claude can make the game do literally anything:
a Pac-Man chase one minute, Snake the next, Breakout after that.

### `announce.txt` — Claude's voice in the game

A plain text file. The game reads it when mtime changes and displays the content
as a banner for a few seconds. Claude writes here to narrate transitions:

```
The walls are shifting...
```

### `state.json` — Game tells Claude what's happening

Written by the engine every ~30 ticks. Example:

```json
{
  "tick": 1542,
  "score": 230,
  "lives": 2,
  "player": [12, 8],
  "phase": "chase",
  "enemy_count": 4,
  "items_collected": 23,
  "custom": {}
}
```

Claude reads this to make informed decisions: "player has been in chase mode for
500 ticks, time to switch it up" or "score is high, increase difficulty."

## Controls

- **Arrow keys**: Movement (the meaning depends on current rules — could be
  grid movement, continuous movement, aiming, etc.)
- **Space bar**: Action (the meaning depends on current rules — could be shoot,
  drop, activate, jump, etc.)
- **q**: Quit

## Game Flow

1. Player sets up the venv and starts `python game.py`
2. Player tells Claude "go" in the Claude Code session
3. Claude reads `state.json` to see initial state
4. Claude begins editing `rules.py` to evolve the game:
   - Start simple (collect dots, avoid enemies)
   - Gradually introduce new mechanics
   - Periodically shift to entirely different game modes
   - Use `announce.txt` to narrate changes
5. Claude reads `state.json` periodically to adapt (difficulty, pacing, variety)
6. The game never stops — it just keeps morphing

## What Claude can change (examples)

| Mutation | How |
|---|---|
| Speed up/slow down | Change `tick_ms` in config |
| Add/remove enemies | Modify entity spawn logic in `on_tick` |
| Change enemy AI | Rewrite movement logic |
| Fog of war | Only render cells near player |
| Wrap-around edges | Change boundary logic |
| Switch to Snake | Player leaves a trail, grows on eat, dies on self-collision |
| Switch to Breakout | Player is a paddle at bottom, ball bounces, bricks at top |
| Switch to Shooter | Player at bottom, enemies descend, space fires bullets |
| Add gravity | Entities fall unless on a platform |
| Add portals | Pairs of cells that teleport |
| Boss fight | Single large enemy with health bar |
| Maze generation | Replace random walls with a proper maze |
| Peaceful mode | No enemies, just exploration and collection |

## File Structure

```
game1/
├── PLAN.md          ← this file
├── requirements.txt ← just curses (stdlib), maybe none needed
├── game.py          ← the engine (player runs this)
├── rules.py         ← the brain (Claude edits this live)
├── announce.txt     ← Claude's in-game messages
└── state.json       ← game writes this for Claude to read
```

## Venv Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # likely empty, curses is stdlib
python game.py
```

## Key Design Decisions

1. **Files, not sockets.** Claude Code can edit files and run commands. File
   watching is the simplest, most reliable bridge. No daemon processes needed.

2. **Rules own all logic.** The engine is a dumb loop. This means Claude can
   change *anything* about the game without touching the engine.

3. **State survives reloads.** The state dict persists. Rules must handle
   migration in `on_reload` (add missing keys, adjust for new grid sizes, etc.).

4. **Grid-based rendering.** The engine renders `state["grid"]` — a list of
   strings, one per row. Rules populate this however they want. Simple, flexible,
   and works for any 2D ASCII game.

5. **Announce is separate from rules.** Claude can send a message without
   changing game logic, and vice versa. Decoupled.
