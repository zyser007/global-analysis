"""Shared helpers for editor-agent/setup.py and editor-agent/run_once.py.

Definitions live in version-controlled files next to this module (agent/agent.json + agent/system_prompt.md,
environment.json, memory_store.json + memory_seed/, deployment.json + kickoff/). The IDs of the objects
created from them are recorded in lock.json. Secrets are never stored here: the Anthropic API key comes from
ANTHROPIC_API_KEY, the GitHub token is read from deployment.json's github_token_file only when a session or
deployment is created, and neither is ever printed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
LOCK = HERE / "lock.json"
CONSOLE = "https://platform.claude.com/workspaces/%s/sessions/%s"


def read_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def read_text(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8").strip() + "\n"


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def load_lock() -> dict:
    if LOCK.exists():
        return json.loads(LOCK.read_text(encoding="utf-8"))
    return {"console_workspace": "default"}


def save_lock(lock: dict) -> None:
    lock["updated_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = LOCK.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(LOCK)


# ----------------------------------------------------------------------------- definitions -> API params
def agent_params() -> dict:
    d = read_json("agent/agent.json")
    p = {k: v for k, v in d.items() if k != "system_file"}
    p["system"] = read_text(d["system_file"])
    return p


def environment_params() -> dict:
    return read_json("environment.json")


def memory_params() -> dict:
    d = read_json("memory_store.json")
    return {"name": d["name"], "description": d["description"]}


def memory_seed() -> dict[str, str]:
    d = read_json("memory_store.json")
    root = HERE / d["seed_dir"]
    return {"/" + p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}


def kickoff_events() -> list[dict]:
    """One plain user.message. There is no outcome / rubric grader any more: it cost a revision loop per run and
    could only see files; verify.sh + check.py are the gate. kickoff/run-checklist.md documents a good run."""
    k = read_json("deployment.json")["kickoff"]
    return [{"type": "user.message", "content": [{"type": "text", "text": read_text(k["message_file"])}]}]


def github_token() -> str:
    """Read the fine-grained PAT at run time. Never print or log the value."""
    path = pathlib.Path(read_json("deployment.json")["github_token_file"]).expanduser()
    if not path.exists():
        sys.exit("GitHub token file not found: %s (create it first, see editor-agent/README.md)" % path)
    tok = path.read_text(encoding="utf-8").strip()
    if not tok or len(tok.split()) != 1:
        sys.exit("GitHub token file %s is empty or malformed" % path)
    return tok


def session_resources(lock: dict, token: str) -> list[dict]:
    dep = read_json("deployment.json")
    mem = read_json("memory_store.json")
    repo = dict(dep["repository"])
    repo.update(type="github_repository", authorization_token=token)
    return [
        repo,
        {"type": "memory_store", "memory_store_id": lock["memory_store"]["id"], "access": mem["session_access"],
         "instructions": mem["session_instructions"]},
    ]


def deployment_params(lock: dict, token: str) -> dict:
    dep = read_json("deployment.json")
    return {
        "name": dep["name"],
        "description": dep["description"],
        "agent": lock["agent"]["id"],          # string form: each firing uses the agent's latest version
        "environment_id": lock["environment"]["id"],
        "initial_events": kickoff_events(),
        "schedule": dep["schedule"],
        "budget": dep["budget"],
        "resources": session_resources(lock, token),
        "metadata": dep.get("metadata", {}),
    }


def deployment_digest() -> str:
    """Hash of everything in the deployment except the token, to tell whether an update is needed."""
    dep = read_json("deployment.json")
    return digest({"dep": dep, "events": kickoff_events(), "mem": read_json("memory_store.json")})


def client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit('ANTHROPIC_API_KEY is not set. Run as: ANTHROPIC_API_KEY="$(cat /Users/zyser/Documents/work/key/global_analysis)" python3 ...')
    import anthropic

    return anthropic.Anthropic()


def require(lock: dict, *names: str) -> None:
    missing = [n for n in names if not (lock.get(n) or {}).get("id")]
    if missing:
        sys.exit("lock.json has no %s yet: run editor-agent/setup.py --apply first" % ", ".join(missing))


def console_url(lock: dict, session_id: str) -> str:
    return CONSOLE % (lock.get("console_workspace") or "default", session_id)


def money(amount: Any) -> str:
    """BetaMonetaryAmount {amount: '123' (cents), currency} -> '$1.23'."""
    if amount is None:
        return "n/a"
    cents = getattr(amount, "amount", None) if not isinstance(amount, dict) else amount.get("amount")
    try:
        return "$%.2f" % (int(cents) / 100)
    except (TypeError, ValueError):
        return str(cents)
