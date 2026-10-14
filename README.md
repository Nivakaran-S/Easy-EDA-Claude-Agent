# Easy-EDA-Claude-Agent

[![tests](https://github.com/Nivakaran-S/Easy-EDA-Claude-Agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Nivakaran-S/Easy-EDA-Claude-Agent/actions/workflows/tests.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Let Claude design printed circuit boards in **EasyEDA Pro**: pick parts from the
live LCSC library, draw a readable schematic, push it to the PCB, place, route,
outline, run DRC and export the fabrication files, all through MCP while you
watch the editor.

This is a fork of [eda-agent](https://github.com/salitronic/eda-agent) by George
Saliba (Apache-2.0), focused on the EasyEDA Pro backend and hardened against
**EasyEDA Pro 3.2** (international, `pro.easyeda.com`), which upstream did not
run against. The Altium Designer and KiCad backends are still here, unchanged;
their documentation lives in [`docs/UPSTREAM_README.md`](docs/UPSTREAM_README.md).

> **Experimental.** It drives a real editor and can modify, save or delete
> design data. Work on a copy until you trust a workflow.

## What it can do

Verified live on EasyEDA Pro 3.2.206, Windows 11, driven from Claude Code:

| Stage | Tools | Status |
|---|---|---|
| Find parts in the LCSC library | `easyeda_search_devices` | works |
| Place parts from a plan | `easyeda_emit_plan`, `easyeda_run_plan` | works |
| Read where pins landed | `easyeda_get_schematic_pin_positions` | works |
| Wire nets, rail glyphs | `easyeda_emit_connections`, `easyeda_run_plan` | works, avoids other nets' pins |
| ERC, save schematic | `easyeda_run_erc`, `easyeda_save_schematic` | works |
| Schematic to PCB | `easyeda_import_schematic_changes` | works |
| Place footprints | `easyeda_modify_pcb_components` | works |
| Tracks, vias, pads | `easyeda_add_line`, `easyeda_add_via`, `easyeda_add_pad` | works |
| Board outline, silkscreen | `easyeda_add_polyline`, `easyeda_add_text`, `easyeda_add_arc` | works |
| Copper pour, fill, keepout | `easyeda_add_zone`, `easyeda_add_fill`, `easyeda_add_region` | works |
| Dimensions | `easyeda_add_dimension` | works |
| DRC, board statistics | `easyeda_run_drc`, `easyeda_get_board_statistics`, `easyeda_get_board_outline` | works |
| BOM, pick and place, netlist, DXF | `easyeda_export_bom`, `easyeda_export_pick_and_place`, `easyeda_export_netlist`, `easyeda_export_dxf` | works |
| Gerber | `easyeda_export_gerber` | needs EasyEDA's user session loaded, see [limitations](#known-limitations) |
| Autorouting | `easyeda_auto_route` | not available in EasyEDA 3.2 |

Anything without a named tool is reachable through `easyeda_invoke`, which calls
any method of EasyEDA's extension API directly and builds polygons from
`{"$polygon": [x, y, "L", x, y, ...]}`.

## How it works

```
Claude Code ──MCP/stdio──> eda-agent (Python) <──WebSocket── EasyEDA Pro extension
                           127.0.0.1:49620       dials out   (extensions/easyeda)
```

The extension runs inside EasyEDA Pro and connects out to the local server, so
EasyEDA has to be open with the extension enabled before any tool can reach it.
Coordinates are in mils throughout.

## Setup

Requirements: Windows, Python 3.11+, Node.js (only to rebuild the extension),
and **EasyEDA Pro 3.2.x, international edition**.

> Use a client whose region matches your account. A 4.x China-line client
> pointed at `pro.easyeda.com` calls `/api/v5`, which that server does not have:
> library search returns nothing, placement hangs and cloud saves silently fail.
> The fix is the matching client, not code.

1. Install the server:

   ```bash
   git clone https://github.com/Nivakaran-S/Easy-EDA-Claude-Agent.git
   cd Easy-EDA-Claude-Agent
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   ```

2. Build the extension (or use a prebuilt `.eext` from a release):

   ```bash
   .venv\Scripts\python extensions/easyeda/build.py
   ```

3. In EasyEDA Pro: **Settings > Extensions > Import**, choose
   `extensions/easyeda/eda-agent-bridge.eext`, enable it, and allow
   **external interaction** when asked. Without that permission the editor
   never opens a socket.

4. Register the server with Claude Code:

   ```bash
   claude mcp add -s user eda-agent -- <repo>\.venv\Scripts\python.exe -m eda_agent --backend easyeda --no-dashboard
   ```

5. Open a project in EasyEDA, then **eda-agent > Connect to eda-agent** from
   the top menu. In Claude Code, `easyeda_ping` should answer with
   `build_matches: true`.

## Designing a board

The schematic comes from a plan, not from placing parts one by one:

1. Describe the circuit. Claude writes a `DesignPlan` (parts with LCSC numbers,
   nets) and checks it with `design_validate_plan`.
2. `easyeda_search_devices` resolves each part to a library uuid.
3. `easyeda_emit_plan` + `easyeda_run_plan` place the symbols.
4. `easyeda_get_schematic_pin_positions` reads the real pin positions, and
   `easyeda_emit_connections` turns them into wires and rail glyphs.
5. `easyeda_run_erc`, `easyeda_save_schematic`, then
   `easyeda_import_schematic_changes` to bring it to the board.
6. Place footprints, draw the outline with `easyeda_add_polyline` on
   `BOARD_OUTLINE`, route with `easyeda_add_line`, pour ground with
   `easyeda_add_zone`, then `easyeda_run_drc` and the exports.

Always read pin numbers back after placing a part. LED and diode symbols in the
LCSC library do not agree on whether pin 1 is the anode.

## Known limitations

- **No autorouter.** `pcb_Document.autoRouting` is declared in EasyEDA's types
  and absent at runtime. Tracks are drawn segment by segment.
- **Gerber and cloud save need the user session.** Both read the logged-in user
  from EasyEDA's `/api/user`. When that request keeps getting reset, they fail
  with `Cannot read properties of null (reading 'user_uuid')` or "the editor
  declined to save". Reload the client or change network, then retry.
- **Slow cloud calls.** Library search, placement and opening documents can take
  over 15 s on a weak link; they get a 60 s budget plus 15 s per placed part.
  A timeout is not proof of failure: read the design back before retrying.
- **Updating the extension needs a full restart.** EasyEDA keeps the old build
  running in each open document's host after a re-import. Bump the version,
  import, quit EasyEDA completely and reopen it.
- **3.2 API quirks handled here:** none of the API enums are injected as
  globals (a table generated from EasyEDA's own `api-types.d.ts` stands in);
  lines and arcs are refused off copper (drawn as polylines instead); fill,
  region and pour need a closed ring; arcs need an explicit interaction mode,
  without which the editor hangs.

## Other backends

The upstream Altium Designer and KiCad backends ship unchanged and are chosen
with `--backend altium` (the default) or `--backend kicad`. The Altium backend
registers around 450 tools (480+ with both backends registered) over a
DelphiScript bridge. Setup, the tool catalogue and their limitations are in
[`docs/UPSTREAM_README.md`](docs/UPSTREAM_README.md) and
[`docs/BACKENDS.md`](docs/BACKENDS.md).

### Altium DelphiScript engine can crash

Some Altium tool paths raise a DelphiScript error and halt the polling loop.
In Altium's Script IDE press the red **Stop** button (or **Ctrl+F3**), then
restart the loop with **File > Run Script... > StartMCPServer > Run**. Details
are in [`docs/UPSTREAM_README.md`](docs/UPSTREAM_README.md).

## Changes from upstream

See the commit history. In short: EasyEDA 3.2 support (enum fallbacks, closed
rings, off-copper fallbacks, export file names, arc arguments), longer budgets
for cloud-bound commands, polyline outlines in the outline and statistics
readers, copper-only `layer_count`, the pin-position tool, obstacle-aware wiring
and rail-glyph placement in the connection emitter, and polygon support in
`easyeda_invoke`. Regression tests are in `tests/test_easyeda_3_2_fixes.py`.

## Development

```bash
.venv\Scripts\python -m pytest -n auto tests
```

After editing `extensions/easyeda/main.js`, bump the version in
`extensions/easyeda/extension.json` and rebuild; EasyEDA ignores a re-import of a
version it already has. `python scripts/gen_tool_reference.py` regenerates
[`docs/TOOL_REFERENCE.md`](docs/TOOL_REFERENCE.md), the list of every tool.

More: [`docs/BACKENDS.md`](docs/BACKENDS.md),
[`extensions/easyeda/README.md`](extensions/easyeda/README.md),
[`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md).

## License and credit

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). Original work
copyright George Saliba ([salitronic/eda-agent](https://github.com/salitronic/eda-agent));
modifications by Nivakaran-S.

Not affiliated with, endorsed by or sponsored by EasyEDA, JLCPCB, LCSC, Altium
Limited, the KiCad project or Anthropic. Their names are trademarks of their
respective owners.
