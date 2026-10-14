# SPDX-License-Identifier: Apache-2.0
"""Faults found building a three-part board on EasyEDA Pro 3.2.206.

Each test pins one thing that went wrong on the live sheet:

- the connection emitter laid LED_A straight through D1's GND pin,
  shorting the LED on a schematic that looked correct;
- rail glyphs dropped on a part's bottom pin were drawn across the part;
- a polyline board outline read back as "no outline";
- the pin positions the connection pass needs had no tool to read them.
"""

from __future__ import annotations

import asyncio

import pytest

import eda_agent.tools.easyeda as ez
from eda_agent.design.easyeda_emitter import (
    _orthogonal,
    emit_easyeda_connections,
)
from eda_agent.design.plan import DesignPlan


def _plan(nets):
    return DesignPlan(**{
        "spec": "led", "summary": "led",
        "sheets": [{"name": "main", "title": "t", "size": "A4"}],
        "parts": [
            {"refdes": r, "lib_ref": r, "value": r, "footprint": "f",
             "status": "existing", "sheet": "main"}
            for r in ("J1", "R1", "D1")],
        "nets": nets,
    })


def _net(name, pins, **flags):
    return {"name": name,
            "pins": [{"refdes": r, "pin": p} for r, p in pins], **flags}


# The live layout that shorted: R1.2 at (6300,4000), D1.1 at (5200,5000),
# and D1.2 (GND) at (5200,4600) right on the horizontal-first elbow.
_LIVE = {
    ("J1", "1"): (4850.0, 3200.0), ("J1", "2"): (4950.0, 3200.0),
    ("R1", "1"): (6300.0, 3600.0), ("R1", "2"): (6300.0, 4000.0),
    ("D1", "1"): (5200.0, 5000.0), ("D1", "2"): (5200.0, 4600.0),
}


def _wires(plan):
    return [c.arguments["points"] for c in plan.calls
            if c.tool == "easyeda_add_wire"]


def test_wire_never_crosses_a_pin_of_another_net():
    plan = _plan([
        _net("LED_A", [("R1", "2"), ("D1", "1")]),
        _net("GND", [("D1", "2"), ("J1", "2")], is_ground=True),
    ])
    out = emit_easyeda_connections(plan, _LIVE)
    (route,) = _wires(out)
    # The horizontal-first elbow ran x=5200 from y=4000 to 5000, over
    # D1.2. The vertical-first one does not.
    assert route == [[6300.0, 4000.0], [6300.0, 5000.0], [5200.0, 5000.0]]
    assert not out.blockers


def test_net_with_no_clear_route_is_a_blocker_not_a_short():
    # A straight run with a foreign pin sitting on it has no elbow to
    # fall back on.
    positions = {("R1", "2"): (0.0, 0.0), ("D1", "1"): (0.0, 1000.0),
                 ("D1", "2"): (0.0, 500.0), ("J1", "2"): (900.0, 900.0)}
    plan = _plan([
        _net("LED_A", [("R1", "2"), ("D1", "1")]),
        _net("GND", [("D1", "2"), ("J1", "2")], is_ground=True),
    ])
    out = emit_easyeda_connections(plan, positions)
    assert all(w[0] != [0.0, 0.0] for w in _wires(out))  # no LED_A wire
    assert any("LED_A" in b for b in out.blockers)


def test_own_pins_are_not_obstacles():
    assert _orthogonal(0, 0, 0, 100, obstacles=[]) == [[0, 0], [0, 100]]
    # Both elbows blocked: None, never a route through the pin.
    assert _orthogonal(0, 0, 100, 100,
                       obstacles=[(100, 50), (50, 100), (0, 50),
                                  (50, 0)]) is None


def test_rail_glyph_below_its_part_moves_clear_on_a_stub():
    # R1 centred at y=4800 with pin 1 at y=4600: a power glyph points UP,
    # straight into R1's body.
    positions = {("R1", "1"): (6300.0, 4600.0), ("J1", "1"): (4800.0, 4050.0)}
    plan = _plan([_net("VIN", [("J1", "1"), ("R1", "1")], is_power=True)])
    out = emit_easyeda_connections(
        plan, positions,
        part_centers={"R1": (6300.0, 4800.0), "J1": (5000.0, 4000.0)})
    stubs = _wires(out)
    assert stubs == [[[6300.0, 4600.0], [6300.0, 4500.0],
                      [6500.0, 4500.0]]]
    flags = [c.arguments for c in out.calls
             if c.tool == "easyeda_create_net_flag"]
    # J1's side pin keeps its glyph on the pin; R1's moves to the stub end.
    assert {(f["x"], f["y"]) for f in flags} == {
        (4800.0, 4050.0), (6500.0, 4500.0)}


def test_header_pin_off_centre_below_body_still_gets_a_stub():
    # The live J1: pins at x 4850/4950 below a body centred at
    # (4900, 3400). Not a side pin just because x differs from centre.
    positions = {("J1", "1"): (4850.0, 3200.0), ("R1", "1"): (6300.0, 5000.0)}
    plan = _plan([_net("VIN", [("J1", "1"), ("R1", "1")], is_power=True)])
    out = emit_easyeda_connections(
        plan, positions,
        part_centers={"J1": (4900.0, 3400.0), "R1": (6300.0, 4800.0)})
    # Left of centre, so the stub runs left, away from J1.2.
    assert _wires(out) == [[[4850.0, 3200.0], [4850.0, 3100.0],
                            [4650.0, 3100.0]]]


def test_glyph_already_pointing_away_stays_on_the_pin():
    positions = {("R1", "1"): (6300.0, 5000.0), ("J1", "1"): (4800.0, 4050.0)}
    plan = _plan([_net("VIN", [("J1", "1"), ("R1", "1")], is_power=True)])
    out = emit_easyeda_connections(
        plan, positions, part_centers={"R1": (6300.0, 4800.0)})
    assert _wires(out) == []


class _FakeMcp:
    def __init__(self):
        self.tools = {}

    def tool(self, *a, **k):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def tools(monkeypatch):
    replies = {}

    def fake_call(command, params=None, timeout=None):
        return replies.get(command, {"ok": True})

    monkeypatch.setattr(ez, "_call", fake_call)
    mcp = _FakeMcp()
    ez.register_easyeda_tools(mcp)
    return mcp.tools, replies


def test_polyline_outline_is_read(tools):
    fns, replies = tools
    replies["pcb.lines"] = {"ok": True, "lines": []}
    replies["pcb.arcs"] = {"ok": True, "arcs": []}
    # Exactly what pcb_PrimitivePolyline.getAll returned for the live
    # outline: 'L' once, then every point (three legs), plus the left
    # edge drawn separately.
    replies["pcb.polylines"] = {"ok": True, "polylines": [
        {"primitiveType": "Polyline", "layer": 11, "primitiveId": "a",
         "polygon": {"polygon": [0, 30, "L", 540, 30, 540, 370, 0, 370]}},
        {"primitiveType": "Polyline", "layer": 11, "primitiveId": "c",
         "polygon": {"polygon": [0, 370, "L", 0, 30]}},
        {"primitiveType": "Polyline", "layer": 1, "primitiveId": "b",
         "polygon": {"polygon": [0, 0, "L", 9, 9]}},
    ]}
    out = asyncio.run(fns["easyeda_get_board_outline"]())
    assert out["segment_count"] == 4
    assert "polylines_unparsed" not in out
    assert out["bounding_box"]["width"] == 540
    assert out["bounding_box"]["height"] == 340


def test_board_statistics_extent_reads_a_polyline_outline(tools):
    fns, replies = tools
    replies["pcb.lines"] = {"ok": True, "lines": []}
    replies["pcb.arcs"] = {"ok": True, "arcs": []}
    # The live outline after the editor rewrote it: reversed winding.
    replies["pcb.polylines"] = {"ok": True, "polylines": [
        {"primitiveType": "Polyline", "layer": 11, "primitiveId": "c",
         "polygon": {"polygon": [0, 30, "L", 0, 370, 540, 370, 540, 30,
                                 0, 30]}}]}
    out = asyncio.run(fns["easyeda_get_board_statistics"]())
    extent = out["sections"]["board_extent"] if "sections" in out \
        else out["board_extent"]
    assert (extent["width"], extent["height"]) == (540, 340)


def test_layer_count_is_copper_not_every_defined_layer(tools):
    fns, replies = tools
    # The shape of pcb_Layer.getAllLayers on the live two-layer board:
    # 260 rows, of which only Top and Bottom are switched-on copper.
    layers = ([{"id": 1, "type": "SIGNAL", "layerStatus": 1},
               {"id": 2, "type": "SIGNAL", "layerStatus": 1}]
              + [{"id": 15 + i, "type": "SIGNAL", "layerStatus": 0}
                 for i in range(32)]
              + [{"id": 100 + i, "type": "CUSTOM", "layerStatus": 0}
                 for i in range(200)]
              + [{"id": 3 + i, "type": "OTHER", "layerStatus": 1}
                 for i in range(26)])
    replies["pcb.layers"] = {"ok": True, "layers": layers}
    out = asyncio.run(fns["easyeda_get_board_statistics"]())
    assert out["sections"]["layer_count"] == 2
    assert out["sections"]["defined_layer_count"] == 260


def test_pin_positions_come_back_in_mils(tools):
    fns, replies = tools
    replies["sch.pin_positions"] = {"ok": True, "parts": [
        {"designator": "R1", "x": 630, "y": 480, "pins": [
            {"number": "1", "x": 630, "y": 500.00000000000006},
            {"number": "2", "x": 630, "y": 460}]},
        {"designator": "LED?", "x": 1, "y": 1, "pins": []},
    ]}
    out = asyncio.run(fns["easyeda_get_schematic_pin_positions"]())
    assert out["pin_positions"] == {"R1.1": [6300.0, 5000.0],
                                    "R1.2": [6300.0, 4600.0]}
    assert out["part_centers"] == {"R1": [6300.0, 4800.0]}
    assert "note" in out


def test_build_id_cache_expires_when_main_js_changes():
    ez._LOCAL_BUILD.clear()
    first = ez._local_extension_build()
    ez._LOCAL_BUILD.clear()
    ez._LOCAL_BUILD[-1.0] = "stale"
    # A cache entry for another mtime must not answer.
    assert ez._local_extension_build() == first


def test_cloud_bound_lists_agree_between_extension_and_server():
    # If the server waited less than the extension, it would give up on
    # a placement the editor was still completing, the same false
    # failure the longer budget exists to remove.
    import pathlib
    import re
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "extensions" / "easyeda" / "main.js").read_text(
                  encoding="utf-8")
    block = re.search(r"const CLOUD_BOUND = \[(.*?)\];", source, re.S)
    assert block, "CLOUD_BOUND not found in main.js"
    names = set(re.findall(r"'([a-z_.]+)'", block.group(1)))
    assert names == set(ez._CLOUD_BOUND)


def test_cloud_bound_calls_outlast_the_extension_budget(monkeypatch):
    seen = {}

    class _Bridge:
        verified_live = False
        def send_editor_command(self, command, params, timeout):
            seen[command] = timeout
            return {"ok": True}

    import eda_agent.bridge.easyeda_bridge as eb
    monkeypatch.setattr(eb, "get_easyeda_bridge", lambda: _Bridge())
    ez._call("lib.search_devices", {"query": "x"})
    ez._call("sch.place_components", {"components": [{}, {}, {}]},
             timeout=10.0)
    ez._call("pcb.lines")
    assert seen["lib.search_devices"] >= 75.0
    assert seen["sch.place_components"] >= 60.0 + 15.0 * 3
    assert seen["pcb.lines"] == 30.0


def test_rounded_polyline_outline_counts_its_arc_legs(tools):
    fns, replies = tools
    replies["pcb.lines"] = {"ok": True, "lines": []}
    replies["pcb.arcs"] = {"ok": True, "arcs": []}
    # A rectangle with one rounded corner: L legs and an ARC leg, which
    # takes the swept angle before its end point.
    replies["pcb.polylines"] = {"ok": True, "polylines": [
        {"primitiveType": "Polyline", "layer": 11, "primitiveId": "r",
         "polygon": {"polygon": [0, 0, "L", 500, 0, "ARC", 90, 600, 100,
                                 "L", 600, 400, "L", 0, 400, "L", 0, 0]}}]}
    out = asyncio.run(fns["easyeda_get_board_outline"]())
    assert out["segment_count"] == 5
    assert "polylines_unparsed" not in out
    assert out["bounding_box"]["width"] == 600
