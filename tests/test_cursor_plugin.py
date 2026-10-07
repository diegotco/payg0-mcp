"""
The Cursor plugin (.cursor-plugin/plugin.json + mcp.json) stays consistent:
every placeholder in mcp.json is a declared variable, no secret is committed,
and it points at the hosted server with the header the server reads.
"""
import json
import re
import tomllib
from pathlib import Path

from payg0_mcp import client

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / ".cursor-plugin" / "plugin.json").read_text())
MCP_CONFIG = json.loads((ROOT / "mcp.json").read_text())


def test_name_is_kebab_case():
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", MANIFEST["name"])


def test_paths_are_relative_and_exist():
    for field in ("logo", "mcpServers"):
        path = MANIFEST[field]
        assert not path.startswith("/") and ".." not in path
        assert (ROOT / path).is_file(), f"{field} points at a missing file: {path}"


def test_version_and_license_match_the_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert MANIFEST["version"] == project["version"]
    assert MANIFEST["license"] == project["license"]


def test_every_placeholder_is_a_required_variable():
    placeholders = set(re.findall(r"\$\{([A-Z0-9_]+)\}", json.dumps(MCP_CONFIG)))
    variables = MANIFEST["variables"]
    assert placeholders, "mcp.json should take the API key from a variable"
    assert placeholders == set(variables["properties"])
    assert placeholders <= set(variables["required"])


def test_points_at_the_hosted_server_with_the_header_it_reads():
    server = MCP_CONFIG["mcpServers"]["payg0"]
    assert server["url"] == "https://mcp.payg0.io/mcp"
    key = client.resolve_api_key({name: "pyg0_test_x" for name in server["headers"]})
    assert key == "pyg0_test_x"


def test_no_api_key_is_committed():
    for path in (ROOT / ".cursor-plugin" / "plugin.json", ROOT / "mcp.json"):
        assert not re.search(r"pyg0_(live|test)_\w", path.read_text())
