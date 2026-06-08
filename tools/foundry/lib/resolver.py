#!/usr/bin/env python3
"""
Foundry Workspace Resolver

Resolves channel IDs → workspaces, and provides vault/board paths
for any workspace in the manifest.

Usage:
    # Resolve channel to default workspace
    python3 resolver.py resolve-channel C0AQFJDT2HE

    # Get workspace details
    python3 resolver.py workspace heimdall

    # List all workspaces
    python3 resolver.py list

    # Check if a channel can route to a specific workspace
    python3 resolver.py can-route C0AQFJDT2HE heimdall
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


def resolve_channel(channel_id, manifest=None):
    """Resolve a channel ID to its default workspace.
    
    Returns: (workspace_id, workspace_config) or (None, None)
    """
    if manifest is None:
        manifest = load_manifest()

    for ws_id, ws in manifest["workspaces"].items():
        for ch in ws.get("channels", []):
            if channel_id in ch.get("ids", []) and ch.get("default", False):
                return ws_id, ws

    # No default found — check if channel is in ANY workspace (non-default)
    for ws_id, ws in manifest["workspaces"].items():
        for ch in ws.get("channels", []):
            if channel_id in ch.get("ids", []):
                return ws_id, ws

    return None, None


def get_workspace(workspace_name, manifest=None):
    """Get workspace config by name (case-insensitive).
    
    Returns: (workspace_id, workspace_config) or (None, None)
    """
    if manifest is None:
        manifest = load_manifest()

    name_lower = workspace_name.lower()

    # Exact match on ID
    if name_lower in manifest["workspaces"]:
        return name_lower, manifest["workspaces"][name_lower]

    # Match on display name
    for ws_id, ws in manifest["workspaces"].items():
        if ws.get("name", "").lower() == name_lower:
            return ws_id, ws

    return None, None


def can_route(channel_id, workspace_name, manifest=None):
    """Check if a channel is permitted to route to a workspace."""
    if manifest is None:
        manifest = load_manifest()

    ws_id, ws = get_workspace(workspace_name, manifest)
    if ws is None:
        return False

    for ch in ws.get("channels", []):
        if channel_id in ch.get("ids", []):
            return True

    return False


def vault_path(workspace_config):
    """Get the expanded vault path for a workspace."""
    return os.path.expanduser(workspace_config["vault"])


def board_id(workspace_config):
    """Get the board ID for a workspace."""
    return workspace_config["board"]


def list_workspaces(manifest=None):
    """List all workspaces with their details."""
    if manifest is None:
        manifest = load_manifest()

    results = []
    for ws_id, ws in manifest["workspaces"].items():
        channels = []
        for ch in ws.get("channels", []):
            channels.extend(ch.get("ids", []))
        results.append({
            "id": ws_id,
            "name": ws.get("name", ws_id),
            "vault": vault_path(ws),
            "board": board_id(ws),
            "channels": channels,
            "agents": ws.get("agents", []),
            "autoDispatch": ws.get("autoDispatch", False),
        })
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: resolver.py <command> [args...]")
        print("Commands: resolve-channel, workspace, list, can-route")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "resolve-channel":
        if len(sys.argv) < 3:
            print("Usage: resolver.py resolve-channel <channel_id>")
            sys.exit(1)
        ws_id, ws = resolve_channel(sys.argv[2])
        if ws:
            print(json.dumps({
                "workspace_id": ws_id,
                "name": ws.get("name", ws_id),
                "vault": vault_path(ws),
                "board": board_id(ws),
            }, indent=2))
        else:
            print(json.dumps({"error": f"No workspace found for channel {sys.argv[2]}"}))
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
                "autoCheckin": ws.get("autoCheckin", False),
                "autoDispatch": ws.get("autoDispatch", False),
            }, indent=2))
        else:
            print(json.dumps({"error": f"Workspace '{sys.argv[2]}' not found"}))
            sys.exit(1)

    elif cmd == "list":
        for ws in list_workspaces():
            print(json.dumps(ws))

    elif cmd == "can-route":
        if len(sys.argv) < 4:
            print("Usage: resolver.py can-route <channel_id> <workspace>")
            sys.exit(1)
        result = can_route(sys.argv[2], sys.argv[3])
        print(json.dumps({"can_route": result}))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
