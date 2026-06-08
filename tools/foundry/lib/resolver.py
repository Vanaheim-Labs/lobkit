#!/usr/bin/env python3
"""
Foundry Workspace Resolver (v2 — agent-routed)

Routing is based on which agent is asking, not which channel they're in.
Any agent can check in from any channel they're a member of — the manifest
controls which workspaces that agent is permitted to write to.

Resolution order:
  1. Explicit workspace name ("check this into Heimdall") → exact match
  2. Agent's default workspace (defaultFor includes this agent) → auto-route
  3. Agent is permitted on exactly one workspace → auto-route
  4. Agent is permitted on multiple → ask the user

Usage:
    python3 resolver.py resolve <agent_id>
    python3 resolver.py resolve <agent_id> --workspace heimdall
    python3 resolver.py workspace heimdall
    python3 resolver.py list
    python3 resolver.py agents <agent_id>
"""

import json
import sys
import os

MANIFEST_PATH = os.path.expanduser(
    "~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json"
)


def load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def resolve_for_agent(agent_id, explicit_workspace=None, manifest=None):
    """Resolve which workspace an agent should check in to.

    Returns: (workspace_id, workspace_config, resolution_method) or (None, None, reason)
    """
    if manifest is None:
        manifest = load_manifest()

    # 1. Explicit workspace name
    if explicit_workspace:
        ws_id, ws = get_workspace(explicit_workspace, manifest)
        if ws is None:
            return None, None, f"workspace '{explicit_workspace}' not found"
        if agent_id not in ws.get("agents", []):
            return None, None, f"agent '{agent_id}' not permitted on workspace '{explicit_workspace}'"
        return ws_id, ws, "explicit"

    # 2. Agent's default workspace
    for ws_id, ws in manifest["workspaces"].items():
        if agent_id in ws.get("defaultFor", []):
            return ws_id, ws, "default"

    # 3. Agent permitted on exactly one workspace
    permitted = []
    for ws_id, ws in manifest["workspaces"].items():
        if agent_id in ws.get("agents", []):
            permitted.append((ws_id, ws))

    if len(permitted) == 1:
        return permitted[0][0], permitted[0][1], "only_permitted"

    if len(permitted) == 0:
        return None, None, f"agent '{agent_id}' not permitted on any workspace"

    # 4. Multiple workspaces — need explicit choice
    names = [ws.get("name", ws_id) for ws_id, ws in permitted]
    return None, None, f"agent '{agent_id}' permitted on multiple workspaces: {', '.join(names)}. Specify which one."


def get_workspace(workspace_name, manifest=None):
    """Get workspace config by name (case-insensitive)."""
    if manifest is None:
        manifest = load_manifest()

    name_lower = workspace_name.lower()

    if name_lower in manifest["workspaces"]:
        return name_lower, manifest["workspaces"][name_lower]

    for ws_id, ws in manifest["workspaces"].items():
        if ws.get("name", "").lower() == name_lower:
            return ws_id, ws

    return None, None


def agent_workspaces(agent_id, manifest=None):
    """List all workspaces an agent is permitted on."""
    if manifest is None:
        manifest = load_manifest()

    results = []
    for ws_id, ws in manifest["workspaces"].items():
        if agent_id in ws.get("agents", []):
            is_default = agent_id in ws.get("defaultFor", [])
            results.append({
                "id": ws_id,
                "name": ws.get("name", ws_id),
                "vault": vault_path(ws),
                "board": board_id(ws),
                "isDefault": is_default,
            })
    return results


def vault_path(workspace_config):
    """Get the expanded vault path for a workspace."""
    return os.path.expanduser(workspace_config["vault"])


def board_id(workspace_config):
    """Get the board ID for a workspace."""
    return workspace_config["board"]


def notification_config(workspace_config):
    """Get the notification config for a workspace."""
    return workspace_config.get("notifications", {})


def should_notify(workspace_config, event_type):
    """Check if a workspace should deliver a notification for an event type."""
    notif = notification_config(workspace_config)
    if not notif.get("channel"):
        return False
    return notif.get("on", {}).get(event_type, False)


def notification_channel(workspace_config):
    """Get the notification channel for a workspace."""
    return notification_config(workspace_config).get("channel")


def list_workspaces(manifest=None):
    """List all workspaces."""
    if manifest is None:
        manifest = load_manifest()

    results = []
    for ws_id, ws in manifest["workspaces"].items():
        results.append({
            "id": ws_id,
            "name": ws.get("name", ws_id),
            "vault": vault_path(ws),
            "board": board_id(ws),
            "agents": ws.get("agents", []),
            "defaultFor": ws.get("defaultFor", []),
            "autoDispatch": ws.get("autoDispatch", False),
        })
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: resolver.py <command> [args...]")
        print("Commands: resolve, workspace, list, agents")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "resolve":
        if len(sys.argv) < 3:
            print("Usage: resolver.py resolve <agent_id> [--workspace <name>]")
            sys.exit(1)
        agent_id = sys.argv[2]
        explicit_ws = None
        if "--workspace" in sys.argv:
            idx = sys.argv.index("--workspace")
            if idx + 1 < len(sys.argv):
                explicit_ws = sys.argv[idx + 1]

        ws_id, ws, method = resolve_for_agent(agent_id, explicit_ws)
        if ws:
            print(json.dumps({
                "workspace_id": ws_id,
                "name": ws.get("name", ws_id),
                "vault": vault_path(ws),
                "board": board_id(ws),
                "resolution": method,
            }, indent=2))
        else:
            print(json.dumps({"error": method}))
            sys.exit(1)

    elif cmd == "workspace":
        if len(sys.argv) < 3:
            print("Usage: resolver.py workspace <name>")
            sys.exit(1)
        ws_id, ws = get_workspace(sys.argv[2])
        if ws:
            print(json.dumps({
                "workspace_id": ws_id,
                "name": ws.get("name", ws_id),
                "vault": vault_path(ws),
                "board": board_id(ws),
                "agents": ws.get("agents", []),
                "defaultFor": ws.get("defaultFor", []),
                "autoDispatch": ws.get("autoDispatch", False),
            }, indent=2))
        else:
            print(json.dumps({"error": f"Workspace '{sys.argv[2]}' not found"}))
            sys.exit(1)

    elif cmd == "list":
        for ws in list_workspaces():
            print(json.dumps(ws))

    elif cmd == "agents":
        if len(sys.argv) < 3:
            print("Usage: resolver.py agents <agent_id>")
            sys.exit(1)
        for ws in agent_workspaces(sys.argv[2]):
            print(json.dumps(ws))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
