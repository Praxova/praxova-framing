# praxova-framing-mcp

MCP server fronting the [Praxova Framing](../) Blender add-on. Lets an LLM agent (Claude Desktop, etc.) drive lumber placement, on-center duplication, and cut-list generation in a live Blender session.

## Architecture

```
┌──────────────────┐    stdio MCP    ┌────────────────────┐    TCP JSON-RPC    ┌─────────────────────┐
│  Claude Desktop  │────────────────▶│  praxova-framing-  │───────────────────▶│  Blender 5.x        │
│  (or any MCP     │                 │  mcp (this pkg)    │   127.0.0.1:9876   │  (bridge thread)    │
│  client)         │◀────────────────│                    │◀───────────────────│                     │
└──────────────────┘                 └────────────────────┘                    └─────────────────────┘
```

The MCP server is a thin protocol translator. All scene mutation happens on Blender's main thread inside the add-on; this process just relays.

## Install

Requires Python 3.10+ and a working Blender install with the Praxova Framing add-on at v0.3.0+.

```bash
# From the repo root:
uv tool install ./mcp_server
# or:
pipx install ./mcp_server
```

After install, the `praxova-framing-mcp` console script is on your `PATH`.

Verify:

```bash
which praxova-framing-mcp
praxova-framing-mcp --help   # FastMCP help
```

## Configure Claude Desktop

Add to your Claude Desktop config (typical Linux path: `~/.config/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "praxova-framing": {
      "command": "praxova-framing-mcp"
    }
  }
}
```

If you're running the bridge on a non-default port, override via env:

```json
{
  "mcpServers": {
    "praxova-framing": {
      "command": "praxova-framing-mcp",
      "env": {
        "PRAXOVA_BRIDGE_PORT": "9877"
      }
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Workflow

1. Open Blender. The Praxova add-on must be enabled.
2. In the Praxova N-panel: click **Start MCP Bridge**. The status indicator should switch to "Listening on 127.0.0.1:9876".
3. In Claude (or any MCP client), the eight tools are now available. Try: *"Frame a 12-foot wall with 16-inch on-center 2x4 studs."*
4. When done, click **Stop MCP Bridge** in Blender (or just close Blender).

## Tool surface

| Tool | Purpose |
|---|---|
| `list_materials` | Enumerate available lumber sizes/lengths and sheet types. Read-only. |
| `list_objects` | List Praxova-tagged objects in the scene. Read-only. |
| `get_scene_info` | Cursor location, units, active object, save state. Read-only. |
| `add_lumber` | Place one tagged lumber piece (2x4..2x12, 6x6). |
| `add_sheet` | Place one tagged sheet good (PLY/OSB, 1/2"/3/4"). |
| `duplicate_oc` | Duplicate N pieces along local X at a given OC spacing. |
| `generate_cutlist` | Walk the scene and write the cut list to a Text datablock and `.txt` sidecar. |
| `set_imperial_units` | Switch the scene to imperial (inches). Idempotent. |

## Configuration

Environment variables (all optional, read at process start):

| Variable | Default | Purpose |
|---|---|---|
| `PRAXOVA_BRIDGE_HOST` | `127.0.0.1` | Bridge bind address |
| `PRAXOVA_BRIDGE_PORT` | `9876` | Bridge TCP port |

## Development

```bash
cd mcp_server
uv sync                            # or: pip install -e .
python -m praxova_framing_mcp      # run from source
```

Test connectivity (bridge must be running in Blender):

```bash
python ../smoke_test.py            # exercises the bridge directly
```

## License

GPL-2.0-or-later. The MCP server doesn't link `bpy` itself, but is licensed to match the add-on it serves.
