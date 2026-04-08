"""Unit tests for the game engine and rules module.

Tests exercise pure functions only — no curses dependency.
"""

import json
import os
import sys
import tempfile
import time
import types
import unittest

# Ensure the project directory is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

import game


# ── Helpers ───────────────────────────────────────────────────────────

def _make_rules_file(tmpdir, source):
    """Write a rules.py to a temp dir and return its path."""
    path = os.path.join(tmpdir, "rules.py")
    with open(path, "w") as f:
        f.write(source)
    return path


def _mock_rules(**funcs):
    """Create a mock rules module with the given functions."""
    mod = types.ModuleType("mock_rules")
    for name, fn in funcs.items():
        setattr(mod, name, fn)
    return mod


def _minimal_rules_source(title="Test Game", width=20, height=12):
    return f'''\
def get_config():
    return {{"title": "{title}", "width": {width}, "height": {height}, "lives": 3}}

def on_tick(state, cfg):
    state["tick"] = state.get("tick", 0) + 1
    w, h = cfg["width"], cfg["height"]
    state["grid"] = ["." * w for _ in range(h)]

def on_reload(state, prev_cfg, cfg):
    state["_reloaded"] = True
'''


# ── Config Normalization ─────────────────────────────────────────────

class TestConfigNormalization(unittest.TestCase):

    def test_defaults_applied(self):
        cfg = game.normalize_config({})
        self.assertEqual(cfg["title"], "Shift Chase")
        self.assertEqual(cfg["width"], 40)
        self.assertEqual(cfg["height"], 20)
        self.assertEqual(cfg["tick_ms"], 120)
        self.assertEqual(cfg["lives"], 3)

    def test_overrides_respected(self):
        cfg = game.normalize_config({"title": "My Game", "width": 50, "lives": 5})
        self.assertEqual(cfg["title"], "My Game")
        self.assertEqual(cfg["width"], 50)
        self.assertEqual(cfg["lives"], 5)
        # Defaults still present
        self.assertEqual(cfg["tick_ms"], 120)

    def test_width_clamped_minimum(self):
        cfg = game.normalize_config({"width": 5})
        self.assertEqual(cfg["width"], 20)

    def test_height_clamped_minimum(self):
        cfg = game.normalize_config({"height": 3})
        self.assertEqual(cfg["height"], 10)

    def test_tick_ms_clamped_minimum(self):
        cfg = game.normalize_config({"tick_ms": 10})
        self.assertEqual(cfg["tick_ms"], 40)

    def test_lives_clamped_minimum(self):
        cfg = game.normalize_config({"lives": 0})
        self.assertEqual(cfg["lives"], 1)

    def test_type_coercion(self):
        cfg = game.normalize_config({"width": "50", "tick_ms": "80"})
        self.assertEqual(cfg["width"], 50)
        self.assertEqual(cfg["tick_ms"], 80)

    def test_extra_keys_passed_through(self):
        cfg = game.normalize_config({"enemy_count": 5, "custom_key": "hello"})
        self.assertEqual(cfg["enemy_count"], 5)
        self.assertEqual(cfg["custom_key"], "hello")


# ── Rules Loading ────────────────────────────────────────────────────

class TestRulesLoading(unittest.TestCase):

    def test_load_valid_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_rules_file(tmpdir, _minimal_rules_source())
            mod = game.load_rules_module(path)
            self.assertTrue(hasattr(mod, "get_config"))
            self.assertTrue(hasattr(mod, "on_tick"))
            cfg = mod.get_config()
            self.assertEqual(cfg["title"], "Test Game")

    def test_load_module_missing_get_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_rules_file(tmpdir, "X = 42\n")
            mod = game.load_rules_module(path)
            cfg = game.get_rules_config(mod)
            self.assertEqual(cfg, {})

    def test_get_rules_config_non_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_rules_file(tmpdir, "def get_config(): return 'not a dict'\n")
            mod = game.load_rules_module(path)
            cfg = game.get_rules_config(mod)
            self.assertEqual(cfg, {})

    def test_load_module_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_rules_file(tmpdir, "def broken(\n")
            with self.assertRaises(SyntaxError):
                game.load_rules_module(path)

    def test_load_rules_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_rules_file(tmpdir, _minimal_rules_source(title="E2E"))
            mod, cfg = game.load_rules(path)
            self.assertEqual(cfg["title"], "E2E")
            self.assertGreaterEqual(cfg["width"], 20)


# ── Hot Reload / File Watching ───────────────────────────────────────

class TestHotReload(unittest.TestCase):

    def test_check_file_changed_detects_change(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("a = 1\n")
            path = f.name
        try:
            mtime = os.path.getmtime(path)
            # Force a different mtime
            os.utime(path, (mtime + 1, mtime + 1))
            changed, new_mtime = game.check_file_changed(path, mtime)
            self.assertTrue(changed)
            self.assertNotEqual(new_mtime, mtime)
        finally:
            os.unlink(path)

    def test_check_file_changed_no_change(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("a = 1\n")
            path = f.name
        try:
            mtime = os.path.getmtime(path)
            changed, new_mtime = game.check_file_changed(path, mtime)
            self.assertFalse(changed)
            self.assertEqual(new_mtime, mtime)
        finally:
            os.unlink(path)

    def test_check_file_changed_missing_file(self):
        changed, mtime = game.check_file_changed("/nonexistent/path.py", 0.0)
        self.assertFalse(changed)
        self.assertEqual(mtime, 0.0)

    def test_reload_preserves_state(self):
        """Write rules v1, run ticks, write rules v2, verify state persists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source(title="V1"))
            announce_path = os.path.join(tmpdir, "announce.txt")

            mod, cfg = game.load_rules(rules_path)
            state = game.init_state(cfg)
            state["score"] = 42

            # Run a tick with v1
            rules_mtime = os.path.getmtime(rules_path)
            mod, cfg, rules_mtime, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path, rules_mtime, 0.0
            )
            self.assertEqual(state["score"], 42)

            # Write v2 with different title
            _make_rules_file(tmpdir, _minimal_rules_source(title="V2"))
            os.utime(rules_path, (rules_mtime + 1, rules_mtime + 1))

            # Run tick — should detect change and reload
            mod, cfg, rules_mtime, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path, rules_mtime - 1, 0.0
            )
            self.assertEqual(cfg["title"], "V2")
            # Score persists across reload
            self.assertEqual(state["score"], 42)

    def test_reload_calls_on_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")

            mod, cfg = game.load_rules(rules_path)
            state = game.init_state(cfg)
            rules_mtime = os.path.getmtime(rules_path)

            # Run one tick to establish state
            mod, cfg, rules_mtime, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path, rules_mtime, 0.0
            )

            # Rewrite with on_reload that sets a flag
            _make_rules_file(tmpdir, _minimal_rules_source(title="Reloaded"))
            os.utime(rules_path, (rules_mtime + 2, rules_mtime + 2))

            mod, cfg, rules_mtime, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path, rules_mtime - 1, 0.0
            )
            self.assertTrue(state.get("_reloaded"))

    def test_reload_with_broken_rules_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")

            mod, cfg = game.load_rules(rules_path)
            state = game.init_state(cfg)
            rules_mtime = os.path.getmtime(rules_path)

            # Write broken rules
            _make_rules_file(tmpdir, "def get_config(:\n")  # syntax error
            os.utime(rules_path, (rules_mtime + 2, rules_mtime + 2))

            # Should not raise; should set error message
            mod2, cfg2, _, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path, rules_mtime - 1, 0.0
            )
            self.assertIn("failed", state.get("message", "").lower())


# ── Input Handling ───────────────────────────────────────────────────

class TestInputHandling(unittest.TestCase):

    def setUp(self):
        self.state = game.init_state(game.normalize_config({}))

    def test_arrow_up(self):
        game.apply_input(self.state, (0, -1), False)
        self.assertEqual(self.state["input_dir"], (0, -1))
        self.assertFalse(self.state["space"])

    def test_arrow_down(self):
        game.apply_input(self.state, (0, 1), False)
        self.assertEqual(self.state["input_dir"], (0, 1))

    def test_arrow_left(self):
        game.apply_input(self.state, (-1, 0), False)
        self.assertEqual(self.state["input_dir"], (-1, 0))

    def test_arrow_right(self):
        game.apply_input(self.state, (1, 0), False)
        self.assertEqual(self.state["input_dir"], (1, 0))

    def test_space_pressed(self):
        game.apply_input(self.state, None, True)
        self.assertEqual(self.state["input_dir"], (0, 0))
        self.assertTrue(self.state["space"])

    def test_no_input(self):
        game.apply_input(self.state, None, False)
        self.assertEqual(self.state["input_dir"], (0, 0))
        self.assertFalse(self.state["space"])


# ── Game Logic (rules.on_tick) ───────────────────────────────────────

class TestGameLogic(unittest.TestCase):

    def _make_state_and_cfg(self):
        import rules
        cfg = game.normalize_config(rules.get_config())
        state = game.init_state(cfg)
        return state, cfg

    def test_first_tick_initializes(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        self.assertIn("player", state)
        self.assertIsNotNone(state["player"])
        self.assertIsInstance(state["grid"], list)
        self.assertTrue(len(state["grid"]) > 0)
        self.assertTrue(len(state["enemies"]) > 0)

    def test_grid_dimensions(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        self.assertEqual(len(state["grid"]), cfg["height"])
        for row in state["grid"]:
            # Row is at least game width (may be wider with sidebar)
            self.assertGreaterEqual(len(row), cfg["width"])

    def test_grid_contains_player(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        all_chars = "".join(state["grid"])
        self.assertIn("@", all_chars)

    def test_grid_contains_walls(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        all_chars = "".join(state["grid"])
        self.assertIn("#", all_chars)

    def test_player_movement(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)  # initialize
        # Place player in a known clear spot
        state["player"] = (5, 5)
        state["walls"] = {(x, 0) for x in range(cfg["width"])}  # only top wall
        state["walls"] |= {(x, cfg["height"] - 1) for x in range(cfg["width"])}
        state["walls"] |= {(0, y) for y in range(cfg["height"])}
        state["walls"] |= {(cfg["width"] - 1, y) for y in range(cfg["height"])}
        state["input_dir"] = (1, 0)
        rules.on_tick(state, cfg)
        self.assertEqual(state["player"], (6, 5))

    def test_player_blocked_by_wall(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)  # initialize
        state["player"] = (5, 5)
        state["walls"].add((6, 5))  # wall to the right
        state["input_dir"] = (1, 0)
        rules.on_tick(state, cfg)
        self.assertEqual(state["player"], (5, 5))

    def test_item_collection(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)  # initialize
        state["player"] = (5, 5)
        state["items"] = {(5, 5)}
        old_score = state["score"]
        state["input_dir"] = (0, 0)
        rules.on_tick(state, cfg)
        self.assertGreater(state["score"], old_score)
        self.assertNotIn((5, 5), state["items"])

    def test_enemy_contact_loses_life(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        state["player"] = (10, 10)
        state["enemies"] = [{"x": 10, "y": 10, "stun": 0}]
        state["invuln"] = 0
        old_lives = state["lives"]
        state["input_dir"] = (0, 0)
        rules.on_tick(state, cfg)
        self.assertLess(state["lives"], old_lives)

    def test_game_over_at_zero_lives(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        state["player"] = (10, 10)
        state["enemies"] = [{"x": 10, "y": 10, "stun": 0}]
        state["invuln"] = 0
        state["lives"] = 1
        state["input_dir"] = (0, 0)
        rules.on_tick(state, cfg)
        self.assertTrue(state["game_over"])

    def test_space_stuns_nearby_enemies(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        state["player"] = (10, 10)
        state["enemies"] = [
            {"x": 11, "y": 10, "stun": 0},  # distance 1, within radius
            {"x": 20, "y": 20, "stun": 0},  # far away
        ]
        state["space"] = True
        state["input_dir"] = (0, 0)
        rules.on_tick(state, cfg)
        self.assertGreater(state["enemies"][0]["stun"], 0)
        self.assertEqual(state["enemies"][1]["stun"], 0)

    def test_stunned_enemies_dont_move(self):
        import rules
        state, cfg = self._make_state_and_cfg()
        rules.on_tick(state, cfg)
        state["enemies"] = [{"x": 10, "y": 10, "stun": 5}]
        state["input_dir"] = (0, 0)
        rules.on_tick(state, cfg)
        # Enemy should still be at same position (stunned)
        self.assertEqual(state["enemies"][0]["x"], 10)
        self.assertEqual(state["enemies"][0]["y"], 10)
        self.assertEqual(state["enemies"][0]["stun"], 4)  # decremented


# ── Announce ─────────────────────────────────────────────────────────

class TestAnnounce(unittest.TestCase):

    def test_read_announce_existing(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello player!\n")
            path = f.name
        try:
            text = game.read_announce(path)
            self.assertEqual(text, "Hello player!")
        finally:
            os.unlink(path)

    def test_read_announce_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            path = f.name
        try:
            text = game.read_announce(path)
            self.assertIsNone(text)
        finally:
            os.unlink(path)

    def test_read_announce_missing(self):
        text = game.read_announce("/nonexistent/announce.txt")
        self.assertIsNone(text)

    def test_announce_queued_via_process_tick(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")
            with open(announce_path, "w") as f:
                f.write("New rules incoming!")

            mod, cfg = game.load_rules(rules_path)
            state = game.init_state(cfg)
            rules_mtime = os.path.getmtime(rules_path)
            announce_mtime = 0.0  # pretend we haven't seen it

            mod, cfg, _, _ = game.process_tick(
                state, cfg, mod, rules_path, announce_path,
                rules_mtime, announce_mtime,
            )
            self.assertEqual(state["message"], "New rules incoming!")


# ── State JSON ───────────────────────────────────────────────────────

class TestStateJson(unittest.TestCase):

    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            state = {"tick": 100, "score": 42, "lives": 2, "grid": ["..."], "game_over": False}
            game.write_state_json(path, state)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["tick"], 100)
            self.assertEqual(data["score"], 42)

    def test_handles_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            state = {"tick": 0, "items": {(1, 2), (3, 4)}}
            game.write_state_json(path, state)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("items", data)

    def test_handles_tuples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            state = {"player": (5, 10)}
            game.write_state_json(path, state)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["player"], [5, 10])

    def test_skips_private_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            state = {"tick": 0, "_rng": "not serializable obj"}
            game.write_state_json(path, state)
            with open(path) as f:
                data = json.load(f)
            self.assertNotIn("_rng", data)

    def test_skips_callables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            state = {"tick": 0, "fn": lambda: None}
            game.write_state_json(path, state)
            with open(path) as f:
                data = json.load(f)
            self.assertNotIn("fn", data)


# ── Process Tick ─────────────────────────────────────────────────────

class TestProcessTick(unittest.TestCase):

    def test_tick_calls_on_tick(self):
        called = {"value": False}

        def on_tick(state, cfg):
            called["value"] = True
            state["tick"] = state.get("tick", 0) + 1

        mod = _mock_rules(on_tick=on_tick, get_config=lambda: {})

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")
            rules_mtime = os.path.getmtime(rules_path)

            cfg = game.normalize_config({})
            state = game.init_state(cfg)

            game.process_tick(
                state, cfg, mod, rules_path, announce_path,
                rules_mtime, 0.0,
            )
            self.assertTrue(called["value"])

    def test_game_over_skips_on_tick(self):
        called = {"value": False}

        def on_tick(state, cfg):
            called["value"] = True

        mod = _mock_rules(on_tick=on_tick, get_config=lambda: {})

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")
            rules_mtime = os.path.getmtime(rules_path)

            cfg = game.normalize_config({})
            state = game.init_state(cfg)
            state["game_over"] = True

            game.process_tick(
                state, cfg, mod, rules_path, announce_path,
                rules_mtime, 0.0,
            )
            self.assertFalse(called["value"])

    def test_on_tick_exception_caught(self):
        def on_tick(state, cfg):
            raise ValueError("boom")

        mod = _mock_rules(on_tick=on_tick, get_config=lambda: {})

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = _make_rules_file(tmpdir, _minimal_rules_source())
            announce_path = os.path.join(tmpdir, "announce.txt")
            rules_mtime = os.path.getmtime(rules_path)

            cfg = game.normalize_config({})
            state = game.init_state(cfg)

            # Should not raise
            game.process_tick(
                state, cfg, mod, rules_path, announce_path,
                rules_mtime, 0.0,
            )
            self.assertIn("boom", state.get("message", ""))


# ── HUD / Status ─────────────────────────────────────────────────────

class TestHudAndStatus(unittest.TestCase):

    def test_default_hud(self):
        cfg = game.normalize_config({"title": "TestHUD"})
        state = game.init_state(cfg)
        state["score"] = 99
        mod = _mock_rules()
        hud = game.build_hud(state, cfg, mod)
        self.assertIn("TestHUD", hud)
        self.assertIn("99", hud)

    def test_custom_hud(self):
        mod = _mock_rules(render_hud=lambda state, cfg: "CUSTOM HUD")
        cfg = game.normalize_config({})
        state = game.init_state(cfg)
        hud = game.build_hud(state, cfg, mod)
        self.assertEqual(hud, "CUSTOM HUD")

    def test_status_line_with_active_message(self):
        state = {"tick": 10, "message": "Hello!", "message_until": 50}
        self.assertEqual(game.build_status_line(state), "Hello!")

    def test_status_line_expired_message(self):
        state = {"tick": 100, "message": "Old", "message_until": 50}
        self.assertEqual(game.build_status_line(state), "")


# ── Init State ───────────────────────────────────────────────────────

class TestInitState(unittest.TestCase):

    def test_has_required_keys(self):
        cfg = game.normalize_config({"lives": 5})
        state = game.init_state(cfg)
        self.assertEqual(state["tick"], 0)
        self.assertEqual(state["score"], 0)
        self.assertEqual(state["lives"], 5)
        self.assertEqual(state["input_dir"], (0, 0))
        self.assertFalse(state["space"])
        self.assertEqual(state["grid"], [])
        self.assertFalse(state["game_over"])


if __name__ == "__main__":
    unittest.main()
