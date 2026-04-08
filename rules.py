"""Live-mutating game. Claude edits this file continuously during play.

Each edit changes ONE thing. The cumulative effect is smooth game evolution.
"""

import random

SIDEBAR_W = 24
SEP = " | "


def get_config():
    return {
        "title": "Shift Chase",
        "width": 40,
        "height": 20,
        "tick_ms": 120,
        "lives": 3,
    }


def _ensure_init(state, cfg):
    if "_init" in state:
        return
    rng = random.Random()
    state["_rng"] = rng
    w, h = cfg["width"], cfg["height"]

    # Walls: border only, few interior
    walls = set()
    for x in range(w):
        walls.add((x, 0)); walls.add((x, h - 1))
    for y in range(h):
        walls.add((0, y)); walls.add((w - 1, y))
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            if rng.random() < 0.03:
                walls.add((x, y))
    state["walls"] = walls

    # Player
    state["player"] = _empty(state, rng, cfg)
    state["player_char"] = "@"
    state["trail"] = []  # for snake-like mechanics later

    # Enemies
    state["enemies"] = []
    for _ in range(3):
        pos = _empty(state, rng, cfg)
        state["enemies"].append({"x": pos[0], "y": pos[1], "stun": 0})

    # Items
    state["items"] = set()
    for _ in range(5):
        pos = _empty(state, rng, cfg)
        state["items"].add(pos)

    # Misc
    state["invuln"] = 0
    state["combo"] = 0
    state["combo_timer"] = 0
    state["bullets"] = []
    state["shoot_cooldown"] = 0
    state["powerups"] = set()

    # Sidebar
    state["_desc"] = [
        "CURRENT RULES:",
        "",
        "You are @",
        "Collect * = 10 pts",
        "Avoid g (ghosts)",
        "Space: stun nearby",
        "Arrows: move 4-dir",
        "",
        "SCORING:",
        "Combo: chain * fast",
        "+1 life per 200 pts",
    ]

    state["_init"] = True


def _empty(state, rng, cfg):
    w, h = cfg["width"], cfg["height"]
    occ = state.get("walls", set()) | state.get("items", set()) | state.get("powerups", set())
    occ |= {(e["x"], e["y"]) for e in state.get("enemies", [])}
    p = state.get("player")
    for _ in range(300):
        x, y = rng.randint(1, w-2), rng.randint(1, h-2)
        if (x, y) not in occ and (x, y) != p:
            return (x, y)
    return (1, 1)


def on_reload(state, prev_cfg, cfg):
    state.setdefault("trail", [])
    state.setdefault("bullets", [])
    state.setdefault("shoot_cooldown", 0)
    state.setdefault("powerups", set())
    state.setdefault("player_char", "@")
    state.setdefault("combo", 0)
    state.setdefault("combo_timer", 0)
    state.setdefault("invuln", 0)
    state.setdefault("_desc", ["RULES:", "Reloading..."])


# ── PLAYER MOVEMENT ──────────────────────────────────────────────────

def _move_player(state, cfg):
    dx, dy = state.get("input_dir", (0, 0))
    if dx == 0 and dy == 0:
        return
    px, py = state["player"]
    nx, ny = px + dx, py + dy
    if (nx, ny) not in state["walls"]:
        state["player"] = (nx, ny)


# ── PLAYER ACTION (space bar) ────────────────────────────────────────

def _player_action(state, cfg):
    if not state.get("space"):
        return
    px, py = state["player"]
    # Stun nearby enemies
    for e in state.get("enemies", []):
        if abs(e["x"] - px) + abs(e["y"] - py) <= 3:
            e["stun"] = 10


# ── ENEMY MOVEMENT ───────────────────────────────────────────────────

def _move_enemies(state, cfg):
    if state["tick"] % 2 != 0:
        return
    rng = state["_rng"]
    px, py = state["player"]
    mercy = state.get("lives", 3) <= 1
    for e in state.get("enemies", []):
        if e.get("stun", 0) > 0:
            e["stun"] -= 1
            continue
        x, y = e["x"], e["y"]
        if rng.random() < (0.4 if mercy else 0.25):
            for ddx, ddy in rng.sample([(-1,0),(1,0),(0,-1),(0,1)], 4):
                if (x+ddx, y+ddy) not in state["walls"]:
                    e["x"], e["y"] = x+ddx, y+ddy
                    break
            continue
        opts = []
        for ddx, ddy in [(-1,0),(1,0),(0,-1),(0,1)]:
            nx, ny = x+ddx, y+ddy
            if (nx, ny) not in state["walls"]:
                opts.append((abs(nx-px)+abs(ny-py), ddx, ddy))
        if opts:
            opts.sort(reverse=mercy)
            _, ddx, ddy = opts[0]
            e["x"], e["y"] = x+ddx, y+ddy


# ── COLLISION ────────────────────────────────────────────────────────

def _check_enemy_collision(state, cfg):
    px, py = state["player"]
    for e in state.get("enemies", []):
        if (e["x"], e["y"]) == (px, py) and state.get("invuln", 0) <= 0:
            state["lives"] = state.get("lives", 1) - 1
            state["invuln"] = 8
            if state["lives"] <= 0:
                state["game_over"] = True
            else:
                state["player"] = _empty(state, state["_rng"], cfg)
            return True
    return False


# ── ITEMS & SCORING ──────────────────────────────────────────────────

def _handle_items(state, cfg):
    rng = state["_rng"]
    # Combo decay
    if state.get("combo_timer", 0) > 0:
        state["combo_timer"] -= 1
    else:
        state["combo"] = 0
    # Collect
    px, py = state["player"]
    if (px, py) in state["items"]:
        state["items"].discard((px, py))
        state["combo"] = state.get("combo", 0) + 1
        state["combo_timer"] = 15
        state["score"] = state.get("score", 0) + 10 * state["combo"]
    # Spawn
    if len(state["items"]) < 8 and rng.random() < 0.20:
        pos = _empty(state, rng, cfg)
        state["items"].add(pos)
    # Life milestone
    state.setdefault("_last_life", 0)
    m = (state["score"] // 200) * 200
    if m > 0 and m > state["_last_life"]:
        state["lives"] = state.get("lives", 1) + 1
        state["_last_life"] = m


# ── MAIN TICK ────────────────────────────────────────────────────────

def on_tick(state, cfg):
    _ensure_init(state, cfg)
    state["tick"] = state.get("tick", 0) + 1
    if state.get("invuln", 0) > 0:
        state["invuln"] -= 1

    _move_player(state, cfg)
    _player_action(state, cfg)
    _handle_items(state, cfg)
    if not _check_enemy_collision(state, cfg):
        _move_enemies(state, cfg)
        _check_enemy_collision(state, cfg)

    _build_grid(state, cfg)


# ── HUD ──────────────────────────────────────────────────────────────

def render_hud(state, cfg):
    t = cfg.get("title", "Game")
    c = f" x{state.get('combo',0)}" if state.get("combo", 0) > 1 else ""
    return f"{t}  Score:{state.get('score',0)}  Lives:{state.get('lives',0)}{c}"


# ── GRID RENDERING ───────────────────────────────────────────────────

def _build_grid(state, cfg):
    w, h = cfg["width"], cfg["height"]
    walls = state.get("walls", set())
    items = state.get("items", set())
    powerups = state.get("powerups", set())
    enemies = {(e["x"], e["y"]) for e in state.get("enemies", [])}
    trail = set(state.get("trail", []))
    player = state.get("player", (1, 1))
    pchar = state.get("player_char", "@")
    invuln = state.get("invuln", 0)
    bullets = {(b["x"], b["y"]) for b in state.get("bullets", [])}

    desc = state.get("_desc", ["RULES:"])
    sidebar = []
    for i in range(h):
        sidebar.append(desc[i][:SIDEBAR_W].ljust(SIDEBAR_W) if i < len(desc) else " " * SIDEBAR_W)

    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            pos = (x, y)
            if pos == player:
                if invuln > 0 and state["tick"] % 2 == 1:
                    row.append(".")
                else:
                    row.append(pchar)
            elif pos in trail:
                row.append("o")
            elif pos in bullets:
                row.append("|")
            elif pos in enemies:
                row.append("g")
            elif pos in powerups:
                row.append("O")
            elif pos in items:
                row.append("*")
            elif pos in walls:
                row.append("#")
            else:
                row.append(".")
        rows.append("".join(row) + SEP + sidebar[y])
    state["grid"] = rows
