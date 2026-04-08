#!/usr/bin/env python3
"""Engine for the live-mutating ASCII game.

The engine is a dumb loop. ALL game logic lives in rules.py, which is
hot-reloaded when its mtime changes. Communication with Claude happens
through three files: rules.py (logic), announce.txt (messages),
state.json (game state for Claude to read).

The engine is structured so that all logic functions are pure (no curses
dependency) and can be unit-tested directly. Curses is isolated to the
render_curses() and run() functions at the bottom.
"""

import argparse
import curses
import importlib.util
import json
import os
import time

# ── Constants ────────────────────────────────────────────────────────

DIR_KEYS = {
    curses.KEY_UP: (0, -1),
    curses.KEY_DOWN: (0, 1),
    curses.KEY_LEFT: (-1, 0),
    curses.KEY_RIGHT: (1, 0),
}

DEFAULT_CONFIG = {
    "title": "Shift Chase",
    "width": 40,
    "height": 20,
    "tick_ms": 120,
    "lives": 3,
}


# ── Rules Loading ────────────────────────────────────────────────────

def load_rules_module(path):
    """Load a Python module from an absolute file path."""
    spec = importlib.util.spec_from_file_location("rules_live", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load rules module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_rules_config(module):
    """Extract config dict from a loaded rules module."""
    if hasattr(module, "get_config"):
        cfg = module.get_config()
        if isinstance(cfg, dict):
            return cfg
    return {}


def normalize_config(raw):
    """Merge raw config over defaults with validation and clamping."""
    cfg = DEFAULT_CONFIG.copy()
    if raw:
        cfg.update(raw)
    cfg["title"] = str(cfg.get("title", "Shift Chase"))
    cfg["width"] = max(20, int(cfg.get("width", 40)))
    cfg["height"] = max(10, int(cfg.get("height", 20)))
    cfg["tick_ms"] = max(40, int(cfg.get("tick_ms", 120)))
    cfg["lives"] = max(1, int(cfg.get("lives", 3)))
    return cfg


def load_rules(path):
    """Load rules module and return (module, normalized_config)."""
    mod = load_rules_module(path)
    raw = get_rules_config(mod)
    cfg = normalize_config(raw)
    return mod, cfg


# ── File Watchers ────────────────────────────────────────────────────

def check_file_changed(path, last_mtime):
    """Check if a file's mtime has changed. Returns (changed, new_mtime)."""
    try:
        current = os.path.getmtime(path)
    except OSError:
        return False, last_mtime
    if current != last_mtime:
        return True, current
    return False, last_mtime


def read_announce(path):
    """Read announce.txt, return stripped text or None."""
    try:
        with open(path, "r") as f:
            text = f.read().strip()
        return text if text else None
    except OSError:
        return None


# ── State Management ─────────────────────────────────────────────────

def init_state(cfg):
    """Create the initial engine state dict."""
    return {
        "tick": 0,
        "score": 0,
        "lives": cfg.get("lives", 3),
        "input_dir": (0, 0),
        "space": False,
        "grid": [],
        "message": "",
        "message_until": 0,
        "game_over": False,
    }


def set_message(state, text, duration=40):
    """Set a temporary message to display."""
    state["message"] = text
    state["message_until"] = state.get("tick", 0) + duration


def _json_default(obj):
    """JSON serializer for types not supported by default."""
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_state_json(path, state):
    """Write a subset of state to JSON atomically."""
    serializable = {}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        if callable(v):
            continue
        try:
            json.dumps(v, default=_json_default)
            serializable[k] = v
        except (TypeError, ValueError):
            continue
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(serializable, f, default=_json_default, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def apply_input(state, direction, space):
    """Apply player input to state."""
    state["input_dir"] = direction if direction else (0, 0)
    state["space"] = bool(space)


# ── Tick Processing ──────────────────────────────────────────────────

def process_tick(state, cfg, rules_mod, rules_path, announce_path,
                 rules_mtime, announce_mtime):
    """Run one tick. Returns (rules_mod, cfg, rules_mtime, announce_mtime).

    This is the central orchestration function. NO curses calls.
    """
    # Check for rules.py changes
    changed, new_mtime = check_file_changed(rules_path, rules_mtime)
    if changed:
        try:
            new_mod, new_cfg = load_rules(rules_path)
            prev_cfg = cfg.copy()
            if hasattr(new_mod, "on_reload"):
                new_mod.on_reload(state, prev_cfg, new_cfg)
            cfg.clear()
            cfg.update(new_cfg)
            rules_mod = new_mod
            rules_mtime = new_mtime
            set_message(state, "Rules updated")
        except Exception:
            set_message(state, "Reload failed")
            rules_mtime = new_mtime

    # Check for announce.txt changes
    a_changed, a_new_mtime = check_file_changed(announce_path, announce_mtime)
    if a_changed:
        text = read_announce(announce_path)
        if text:
            set_message(state, text, duration=60)
        announce_mtime = a_new_mtime

    # Run game logic
    if not state.get("game_over"):
        try:
            rules_mod.on_tick(state, cfg)
        except Exception as e:
            set_message(state, f"Tick error: {e}")

    return rules_mod, cfg, rules_mtime, announce_mtime


# ── HUD / Status ─────────────────────────────────────────────────────

def build_hud(state, cfg, rules_mod):
    """Build the HUD string."""
    if hasattr(rules_mod, "render_hud"):
        try:
            return rules_mod.render_hud(state, cfg)
        except Exception:
            pass
    title = cfg.get("title", "Game")
    return f"{title}  Score:{state.get('score', 0)}  Lives:{state.get('lives', 0)}  Tick:{state.get('tick', 0)}"


def build_status_line(state):
    """Build the status/message line."""
    if state.get("message") and state.get("message_until", 0) >= state.get("tick", 0):
        return state["message"]
    return ""


# ── Curses Rendering ─────────────────────────────────────────────────

def safe_addstr(stdscr, y, x, text):
    try:
        stdscr.addstr(y, x, text)
    except curses.error:
        pass


def render_curses(stdscr, state, cfg, rules_mod):
    """Render the game to the curses screen."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    grid = state.get("grid", [])
    needed_rows = len(grid) + 3
    needed_cols = cfg.get("width", 20)

    if max_y < needed_rows or max_x < needed_cols:
        msg = f"Terminal too small: need {needed_cols}x{needed_rows}"
        safe_addstr(stdscr, 0, 0, msg[:max_x - 1])
        stdscr.refresh()
        return

    hud = build_hud(state, cfg, rules_mod)
    safe_addstr(stdscr, 0, 0, hud[:max_x - 1])

    status = build_status_line(state)
    if status:
        safe_addstr(stdscr, 1, 0, status[:max_x - 1])

    for i, row in enumerate(grid):
        safe_addstr(stdscr, i + 2, 0, row[:max_x - 1])

    if state.get("game_over"):
        center_y = 2 + len(grid) // 2
        banner = "GAME OVER — arrow key to restart, q to quit"
        safe_addstr(stdscr, center_y, 0, banner[:max_x - 1])

    stdscr.refresh()


# ── Main Loop ────────────────────────────────────────────────────────

def run(stdscr, rules_path, announce_path, state_path):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    rules_mod, cfg = load_rules(rules_path)
    state = init_state(cfg)

    # First tick to initialize game state
    try:
        rules_mod.on_tick(state, cfg)
    except Exception:
        pass

    try:
        rules_mtime = os.path.getmtime(rules_path)
    except OSError:
        rules_mtime = 0.0

    try:
        announce_mtime = os.path.getmtime(announce_path)
    except OSError:
        announce_mtime = 0.0

    while True:
        start = time.monotonic()

        # Collect input
        direction = None
        space = False
        while True:
            key = stdscr.getch()
            if key == -1:
                break
            if key in (ord("q"), ord("Q")):
                return
            if key in DIR_KEYS:
                if state.get("game_over"):
                    state = init_state(cfg)
                    try:
                        rules_mod.on_tick(state, cfg)
                    except Exception:
                        pass
                    break
                direction = DIR_KEYS[key]
            elif key == ord(" "):
                space = True

        apply_input(state, direction, space)

        # Process tick
        rules_mod, cfg, rules_mtime, announce_mtime = process_tick(
            state, cfg, rules_mod, rules_path, announce_path,
            rules_mtime, announce_mtime,
        )

        # Render
        render_curses(stdscr, state, cfg, rules_mod)

        # Write state.json periodically
        if state.get("tick", 0) % 30 == 0:
            write_state_json(state_path, state)

        # Reset one-shot inputs
        state["input_dir"] = (0, 0)
        state["space"] = False

        # Sleep for remainder of tick
        tick_s = cfg.get("tick_ms", 120) / 1000.0
        elapsed = time.monotonic() - start
        if elapsed < tick_s:
            time.sleep(tick_s - elapsed)


def main():
    parser = argparse.ArgumentParser(description="Live-mutating ASCII game engine")
    parser.add_argument("--rules", default="rules.py", help="Path to rules file")
    parser.add_argument("--announce", default="announce.txt", help="Path to announce file")
    parser.add_argument("--state", default="state.json", help="Path to state output file")
    args = parser.parse_args()
    rules_path = os.path.abspath(args.rules)
    announce_path = os.path.abspath(args.announce)
    state_path = os.path.abspath(args.state)
    curses.wrapper(run, rules_path, announce_path, state_path)


if __name__ == "__main__":
    main()
