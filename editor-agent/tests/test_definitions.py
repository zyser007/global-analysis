"""Offline checks of the Managed Agents definitions in editor-agent/ (no API calls, no secrets)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agentlib", HERE / "agentlib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

FAKE = "github_pat_FAKE_FOR_TESTS"
LOCK = {"agent": {"id": "agent_x", "version": 1}, "environment": {"id": "env_x"}, "memory_store": {"id": "memstore_x"}}


def test_agent_definition():
    p = L.agent_params()
    assert p["model"] == {"id": "claude-sonnet-5-5", "effort": "medium"}
    assert "Hard limits" in p["system"] and "force" in p["system"]
    for must in ("git stash", "30 `web_search`", "15 `web_fetch`", "brief.py", "show.py", "apply_changes.py",
                 "verify.sh", "publish.sh", "issue.py", "Never print whole files"):
        assert must in p["system"], must
    ts = p["tools"][0]
    assert ts["type"] == "agent_toolset_20260401"
    assert ts["default_config"]["permission_policy"] == {"type": "auto"}
    cfg = {c["name"]: c for c in ts["configs"]}
    assert cfg["web_search"]["enabled"] and cfg["web_fetch"]["enabled"]
    assert "allowed_domains" not in cfg["web_search"] or "blocked_domains" not in cfg["web_search"]
    assert "multiagent" not in p and "mcp_servers" not in p


def test_environment_definition():
    e = L.environment_params()
    assert e["config"]["type"] == "cloud"
    net = e["config"]["networking"]
    if net["type"] == "limited":   # limited networking would also limit web_search / web_fetch
        assert net.get("allowed_hosts") and net.get("allow_package_managers")
    assert e["config"]["packages"]["type"] == "packages"
    assert all(re.match(r"^[A-Za-z0-9_.-]+==[0-9.]+$", x) for x in e["config"]["packages"]["pip"])


def test_deployment_definition():
    d = L.read_json("deployment.json")
    assert d["schedule"] == {"type": "cron", "expression": "0 7 * * *", "timezone": "Asia/Bangkok"}
    assert d["budget"] == {"type": "limit", "max_list_cost": {"amount": "300", "currency": "USD"}}
    assert d["repository"]["url"] == "https://github.com/zyser007/global-analysis"
    assert d["repository"]["checkout"] == {"type": "branch", "name": "main"}
    params = L.deployment_params(LOCK, FAKE)
    assert params["agent"] == "agent_x" and params["environment_id"] == "env_x"
    repo = params["resources"][0]
    assert repo["type"] == "github_repository" and repo["authorization_token"] == FAKE
    assert params["resources"][1] == {"type": "memory_store", "memory_store_id": "memstore_x", "access": "read_write",
                                      "instructions": L.read_json("memory_store.json")["session_instructions"]}
    assert len(params["resources"][1]["instructions"]) <= 4096


def test_kickoff_events():
    ev = L.kickoff_events()
    assert [e["type"] for e in ev] == ["user.message", "user.define_outcome"]
    out = ev[1]
    assert out["rubric"]["type"] == "text" and out["rubric"]["content"].count("\n1. ") == 1
    assert 1 <= out["max_iterations"] <= 20
    assert len(re.findall(r"^\d+\. \*\*", out["rubric"]["content"], re.M)) >= 8


def test_token_never_in_digest_or_lock():
    assert FAKE not in L.deployment_digest()
    lock_file = HERE / "lock.json"
    if lock_file.exists():
        txt = lock_file.read_text(encoding="utf-8")
        assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|sk-ant-", txt)


def test_no_secrets_in_definitions():
    pat = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9-]{10,}")
    for f in list(HERE.glob("*.json")) + list(HERE.glob("agent/*")) + list(HERE.glob("kickoff/*")) + list(HERE.glob("memory_seed/*")):
        assert not pat.search(f.read_text(encoding="utf-8")), f


def test_memory_seed():
    seed = L.memory_seed()
    assert {"/README.md", "/known-issues.md", "/open-decisions.md", "/watchlist.md", "/sources.md"} <= set(seed)
    assert all(len(v.encode("utf-8")) < 100_000 for v in seed.values())


def test_schema_files_are_valid():
    import jsonschema

    for f in (HERE / "schema").glob("*.json"):
        jsonschema.Draft202012Validator.check_schema(json.loads(f.read_text(encoding="utf-8")))


def test_prompt_tools_exist():
    for name in ("brief.py", "show.py", "apply_changes.py", "check.py", "verify.sh", "publish.sh", "issue.py", "e2e.sh", "visual_check.py"):
        assert (HERE / name).exists(), name
