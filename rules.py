"""Live-mutating chase game with adaptive difficulty and rules sidebar.

Claude edits this file during play to evolve the game through 4 types of changes:
  Type 1 (every ~10s): numerical tweaks (speed, enemy count, item rates)
  Type 2 (every ~30-60s): qualitative additions (new enemy type, wall patterns)
  Type 3 (every ~2-3min): mechanic changes (new scoring, new movement modes)
  Type 4 (every ~5min): fundamental game type shift

All changes are smooth and gradual. A rules summary box shows on the right.
"""

import random

# ── Sidebar width ──
SIDEBAR_W = 24
SEPARATOR = " | "


def get_config():
    return {
        "title": "Shift Chase",
        "width": 40,
        "height": 20,
        "tick_ms": 130,
        "lives": 3,
        "wall_density": 0.04,
        "enemy_count": 3,
        "max_items": 8,
        "item_spawn_chance": 0.20,
        "stun_radius": 3,
        "stun_duration": 10,
        "invuln_ticks": 8,
    }


# ── Initialization ───────────────────────────────────────────────────

def _ensure_initialized(state, cfg):
    if "_initialized" in state:
        return
    rng = random.Random()
    state["_rng"] = rng
    state["player"] = None
    state["enemies"] = []
    state["items"] = set()
    state["walls"] = set()
    state["powerups"] = set()
    state["invuln"] = 0
    state["speed_timer"] = 0
    state["combo"] = 0
    state["combo_timer"] = 0
    state["portals"] = []
    state["_fog_radius"] = 0
    # Difficulty tracking
    state["_deaths"] = 0
    state["_score_at"] = {}  # tick -> score, sampled periodically
    state["_last_death_tick"] = 0
    # Rules description for sidebar
    state["_rules_desc"] = [
        "RULES:",
        "Collect * for pts",
        "Avoid g (ghosts)",
        "Space: stun nearby",
        "Arrows: move",
        "",
        "ACTIVE:",
        "Chase mode",
        "3 ghosts",
    ]
    _build_walls(state, rng, cfg)
    state["player"] = _random_empty(state, rng, cfg)
    for _ in range(cfg.get("enemy_count", 3)):
        pos = _random_empty(state, rng, cfg)
        if pos:
            state["enemies"].append({"x": pos[0], "y": pos[1], "stun": 0})
    for _ in range(4):
        pos = _random_empty(state, rng, cfg)
        if pos:
            state["items"].add(pos)
    state["_initialized"] = True


def _build_walls(state, rng, cfg):
    w, h = cfg["width"], cfg["height"]
    walls = set()
    for x in range(w):
        walls.add((x, 0))
        walls.add((x, h - 1))
    for y in range(h):
        walls.add((0, y))
        walls.add((w - 1, y))
    density = cfg.get("wall_density", 0.04)
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            if rng.random() < density:
                walls.add((x, y))
    state["walls"] = walls


def _random_empty(state, rng, cfg):
    w, h = cfg["width"], cfg["height"]
    walls = state.get("walls", set())
    items = state.get("items", set())
    powerups = state.get("powerups", set())
    enemies = {(e["x"], e["y"]) for e in state.get("enemies", [])}
    player = state.get("player")
    for _ in range(300):
        x = rng.randint(1, w - 2)
        y = rng.randint(1, h - 2)
        pos = (x, y)
        if pos in walls or pos in items or pos in powerups or pos in enemies:
            continue
        if player and pos == player:
            continue
        return pos
    return (1, 1)


# ── Reload handler ───────────────────────────────────────────────────

def on_reload(state, prev_cfg, cfg):
    if not state.get("_initialized"):
        return
    rng = state.get("_rng", random.Random())
    if prev_cfg.get("width") != cfg.get("width") or prev_cfg.get("height") != cfg.get("height"):
        _build_walls(state, rng, cfg)
        state["player"] = _random_empty(state, rng, cfg)
        for enemy in state.get("enemies", []):
            pos = _random_empty(state, rng, cfg)
            if pos:
                enemy["x"], enemy["y"] = pos
        state["items"] = set()
        state["powerups"] = set()
        state["portals"] = []
    enemies = state.get("enemies", [])
    target = cfg.get("enemy_count", 3)
    while len(enemies) < target:
        pos = _random_empty(state, rng, cfg)
        if pos:
            enemies.append({"x": pos[0], "y": pos[1], "stun": 0})
        else:
            break
    if len(enemies) > target:
        del enemies[target:]
    # Ensure new state keys exist
    state.setdefault("powerups", set())
    state.setdefault("speed_timer", 0)
    state.setdefault("combo", 0)
    state.setdefault("combo_timer", 0)
    state.setdefault("portals", [])
    state.setdefault("_fog_radius", 0)
    state.setdefault("_deaths", 0)
    state.setdefault("_score_at", {})
    state.setdefault("_last_death_tick", 0)
    state.setdefault("_rules_desc", ["RULES:", "Chase mode"])


# ── Main tick ────────────────────────────────────────────────────────

def on_tick(state, cfg):
    _ensure_initialized(state, cfg)
    rng = state["_rng"]
    state["tick"] = state.get("tick", 0) + 1
    tick = state["tick"]

    # ── Invulnerability ──
    if state.get("invuln", 0) > 0:
        state["invuln"] -= 1

    # ── Speed timer ──
    if state.get("speed_timer", 0) > 0:
        state["speed_timer"] -= 1

    # ── Fog ──
    fog = state.get("_fog_radius", 0)

    # ── Player movement ──
    dx, dy = state.get("input_dir", (0, 0))
    moves = 2 if state.get("speed_timer", 0) > 0 else 1
    for _ in range(moves):
        if dx != 0 or dy != 0:
            px, py = state["player"]
            nx, ny = px + dx, py + dy
            if (nx, ny) not in state["walls"]:
                state["player"] = (nx, ny)

    # ── Space bar: stun ──
    if state.get("space"):
        px, py = state["player"]
        radius = cfg.get("stun_radius", 3)
        duration = cfg.get("stun_duration", 10)
        for enemy in state["enemies"]:
            dist = abs(enemy["x"] - px) + abs(enemy["y"] - py)
            if dist <= radius:
                enemy["stun"] = duration

    # ── Combo ──
    if state["combo_timer"] > 0:
        state["combo_timer"] -= 1
    else:
        state["combo"] = 0

    # ── Item collection ──
    px, py = state["player"]
    if (px, py) in state["items"]:
        state["items"].discard((px, py))
        state["combo"] += 1
        state["combo_timer"] = 15
        points = 10 * state["combo"]
        state["score"] = state.get("score", 0) + points

    # ── Powerup collection ──
    powerups = state.get("powerups", set())
    if (px, py) in powerups:
        powerups.discard((px, py))
        state["speed_timer"] = 30

    # ── Portal system ──
    if state.get("portals") and len(state["portals"]) == 2:
        px, py = state["player"]
        p1, p2 = state["portals"]
        if (px, py) == tuple(p1) and not state.get("_just_ported"):
            state["player"] = tuple(p2)
            state["_just_ported"] = True
        elif (px, py) == tuple(p2) and not state.get("_just_ported"):
            state["player"] = tuple(p1)
            state["_just_ported"] = True
        else:
            state["_just_ported"] = False

    # ── Enemy collision (pre-move) ──
    if not _check_enemy_collision(state, rng, cfg):
        # ── Enemy movement (every 2nd tick) ──
        if tick % 2 == 0:
            for enemy in state["enemies"]:
                if enemy.get("stun", 0) > 0:
                    enemy["stun"] -= 1
                    continue
                _move_enemy(state, enemy, rng, cfg)
            # ── Enemy collision (post-move) ──
            _check_enemy_collision(state, rng, cfg)

    # ── Spawn items ──
    max_items = cfg.get("max_items", 8)
    chance = cfg.get("item_spawn_chance", 0.20)
    if len(state["items"]) < max_items and rng.random() < chance:
        pos = _random_empty(state, rng, cfg)
        if pos:
            state["items"].add(pos)

    # ── Spawn powerups ──
    if len(powerups) < 1 and rng.random() < 0.03:
        pos = _random_empty(state, rng, cfg)
        if pos:
            powerups.add(pos)
    state["powerups"] = powerups

    # ── Extra life at milestones ──
    if "last_life_at" not in state:
        state["last_life_at"] = 0
    milestone = (state["score"] // 150) * 150
    if milestone > 0 and milestone > state["last_life_at"]:
        state["lives"] = state.get("lives", 1) + 1
        state["last_life_at"] = milestone

    # ── Difficulty tracking ──
    if tick % 60 == 0:
        state["_score_at"][tick] = state["score"]

    # ── Build grid with sidebar ──
    _build_grid(state, cfg)


# ── Collision ────────────────────────────────────────────────────────

def _check_enemy_collision(state, rng, cfg):
    px, py = state["player"]
    for enemy in state["enemies"]:
        if (enemy["x"], enemy["y"]) == (px, py):
            if state.get("invuln", 0) <= 0:
                state["lives"] = state.get("lives", 1) - 1
                state["invuln"] = cfg.get("invuln_ticks", 8)
                state["_deaths"] = state.get("_deaths", 0) + 1
                state["_last_death_tick"] = state["tick"]
                if state["lives"] <= 0:
                    state["game_over"] = True
                else:
                    state["player"] = _random_empty(state, rng, cfg)
                return True
            return False
    return False


# ── Enemy AI ─────────────────────────────────────────────────────────

def _move_enemy(state, enemy, rng, cfg):
    px, py = state["player"]
    x, y = enemy["x"], enemy["y"]
    walls = state["walls"]
    mercy = state.get("lives", 3) <= 1

    # Random chance
    rand_chance = 0.4 if mercy else 0.25
    if rng.random() < rand_chance:
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        rng.shuffle(dirs)
        for ddx, ddy in dirs:
            if (x + ddx, y + ddy) not in walls:
                enemy["x"], enemy["y"] = x + ddx, y + ddy
                return
        return

    # Chase or flee
    options = []
    for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + ddx, y + ddy
        if (nx, ny) not in walls:
            dist = abs(nx - px) + abs(ny - py)
            options.append((dist, ddx, ddy))
    if options:
        if mercy:
            options.sort(reverse=True)
        else:
            options.sort()
        _, ddx, ddy = options[0]
        enemy["x"], enemy["y"] = x + ddx, y + ddy


# ── HUD ──────────────────────────────────────────────────────────────

def render_hud(state, cfg):
    title = cfg.get("title", "Game")
    combo = state.get("combo", 0)
    combo_str = f"  x{combo}" if combo > 1 else ""
    spd = " SPD" if state.get("speed_timer", 0) > 0 else ""
    return f"{title}  Score:{state.get('score',0)}  Lives:{state.get('lives',0)}{combo_str}{spd}"


# ── Grid with sidebar ────────────────────────────────────────────────

def _build_grid(state, cfg):
    w, h = cfg["width"], cfg["height"]
    walls = state.get("walls", set())
    items = state.get("items", set())
    powerups = state.get("powerups", set())
    portals = set()
    for p in state.get("portals", []):
        portals.add(tuple(p))
    enemies = {(e["x"], e["y"]) for e in state.get("enemies", [])}
    player = state.get("player", (1, 1))
    invuln = state.get("invuln", 0)
    speedy = state.get("speed_timer", 0) > 0
    fog = state.get("_fog_radius", 0)
    px, py = player

    # Build sidebar lines
    desc = state.get("_rules_desc", ["RULES:", "Chase mode"])
    sidebar = []
    for i in range(h):
        if i < len(desc):
            line = desc[i][:SIDEBAR_W].ljust(SIDEBAR_W)
        else:
            line = " " * SIDEBAR_W
        sidebar.append(line)

    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            pos = (x, y)
            if fog > 0 and (x - px) ** 2 + (y - py) ** 2 > fog * fog:
                row.append(" ")
                continue
            if pos == player:
                if invuln > 0 and state.get("tick", 0) % 2 == 1:
                    row.append(".")
                elif speedy:
                    row.append("&")
                else:
                    row.append("@")
            elif pos in enemies:
                row.append("g")
            elif pos in portals:
                row.append("%")
            elif pos in powerups:
                row.append("O")
            elif pos in items:
                row.append("*")
            elif pos in walls:
                row.append("#")
            else:
                row.append(".")
        game_row = "".join(row)
        rows.append(game_row + SEPARATOR + sidebar[y])
    state["grid"] = rows
