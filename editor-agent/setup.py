#!/usr/bin/env python3
"""Create or update the editor agent's Managed Agents objects from the files in editor-agent/ and record
their IDs in editor-agent/lock.json (a guarded setup script: it never creates a second copy of an object
that lock.json already tracks, and it never archives or deletes anything).

  python3 editor-agent/setup.py                      plan only: show what would be created / updated
  python3 editor-agent/setup.py --apply              create or update agent, environment, memory store
  python3 editor-agent/setup.py --apply --deployment also create / update the daily deployment
                                                     (reads the GitHub token file; the schedule starts firing!)
  python3 editor-agent/setup.py --apply --deployment --refresh-token   push a rotated GitHub token
  python3 editor-agent/setup.py --pause | --unpause  pause / resume the daily schedule
  python3 editor-agent/setup.py --show               print the IDs and the deployment's next runs

Auth: ANTHROPIC_API_KEY="$(cat /Users/zyser/Documents/work/key/global_analysis)" python3 editor-agent/setup.py ...
Creating agents, environments, memory stores and deployments costs nothing; sessions (runs) cost money.
"""
from __future__ import annotations

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import agentlib as L  # noqa: E402


def plan(lock: dict, with_deployment: bool) -> list[tuple[str, str]]:
    steps = []
    a = lock.get("agent") or {}
    steps.append(("agent", "create" if not a.get("id") else ("update" if a.get("digest") != L.digest(L.agent_params()) else "unchanged")))
    e = lock.get("environment") or {}
    steps.append(("environment", "create" if not e.get("id") else ("update" if e.get("digest") != L.digest(L.environment_params()) else "unchanged")))
    m = lock.get("memory_store") or {}
    steps.append(("memory_store", "create + seed %d files" % len(L.memory_seed()) if not m.get("id") else ("update" if m.get("digest") != L.digest(L.memory_params()) else "unchanged")))
    if with_deployment:
        d = lock.get("deployment") or {}
        steps.append(("deployment", "create (starts the daily schedule)" if not d.get("id") else ("update" if d.get("digest") != L.deployment_digest() else "unchanged")))
    return steps


def apply(lock: dict, with_deployment: bool, refresh_token: bool) -> None:
    c = L.client()

    p = L.agent_params()
    a = lock.get("agent") or {}
    if not a.get("id"):
        r = c.beta.agents.create(**p)
        lock["agent"] = {"id": r.id, "version": r.version, "digest": L.digest(p)}
        print("agent created: %s v%s" % (r.id, r.version))
    elif a.get("digest") != L.digest(p):
        r = c.beta.agents.update(a["id"], version=a["version"], **p)   # 409 if someone changed it elsewhere
        lock["agent"] = {"id": r.id, "version": r.version, "digest": L.digest(p)}
        print("agent updated: %s v%s" % (r.id, r.version))
    L.save_lock(lock)

    p = L.environment_params()
    e = lock.get("environment") or {}
    if not e.get("id"):
        r = c.beta.environments.create(**p)
        lock["environment"] = {"id": r.id, "digest": L.digest(p)}
        print("environment created: %s" % r.id)
    elif e.get("digest") != L.digest(p):
        r = c.beta.environments.update(e["id"], **p)
        lock["environment"] = {"id": r.id, "digest": L.digest(p)}
        print("environment updated: %s (applies to new sessions)" % r.id)
    L.save_lock(lock)

    p = L.memory_params()
    m = lock.get("memory_store") or {}
    if not m.get("id"):
        r = c.beta.memory_stores.create(**p)
        lock["memory_store"] = {"id": r.id, "name": p["name"], "digest": L.digest(p)}
        L.save_lock(lock)
        print("memory store created: %s" % r.id)
        import anthropic

        for path, content in L.memory_seed().items():
            try:
                c.beta.memory_stores.memories.create(r.id, path=path, content=content)
                print("  seeded %s" % path)
            except anthropic.ConflictError:
                print("  %s already exists, kept" % path)
    elif m.get("digest") != L.digest(p):
        r = c.beta.memory_stores.update(m["id"], **p)
        lock["memory_store"] = {"id": r.id, "name": p["name"], "digest": L.digest(p)}
        print("memory store updated: %s" % r.id)
    L.save_lock(lock)

    if with_deployment:
        d = lock.get("deployment") or {}
        want = L.deployment_digest()
        if not d.get("id") or d.get("digest") != want or refresh_token:
            params = L.deployment_params(lock, L.github_token())
            if not d.get("id"):
                r = c.beta.deployments.create(**params)
                print("deployment created: %s (status %s)" % (r.id, r.status))
            else:
                r = c.beta.deployments.update(d["id"], **params)
                print("deployment updated: %s" % r.id)
            lock["deployment"] = {"id": r.id, "digest": want}
            L.save_lock(lock)
            print("next runs:", ", ".join(str(x) for x in (r.schedule.upcoming_runs_at or [])[:3]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--deployment", action="store_true", help="include the scheduled deployment")
    ap.add_argument("--refresh-token", action="store_true", help="re-send the deployment with the current GitHub token")
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--unpause", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    lock = L.load_lock()

    if a.pause or a.unpause:
        L.require(lock, "deployment")
        c = L.client()
        r = (c.beta.deployments.pause if a.pause else c.beta.deployments.unpause)(lock["deployment"]["id"])
        print("deployment %s: status %s, paused_reason %s" % (r.id, r.status, r.paused_reason))
        return 0
    if a.show:
        for k in ("agent", "environment", "memory_store", "deployment"):
            print("%-13s %s" % (k, (lock.get(k) or {}).get("id", "-")))
        if (lock.get("deployment") or {}).get("id"):
            r = L.client().beta.deployments.retrieve(lock["deployment"]["id"])
            print("deployment status %s; next runs %s" % (r.status, ", ".join(str(x) for x in (r.schedule.upcoming_runs_at or [])[:3])))
        return 0

    steps = plan(lock, a.deployment)
    for what, action in steps:
        print("%-13s %s" % (what, action))
    if not a.apply:
        print("(plan only; add --apply to make these changes)")
        return 0
    apply(lock, a.deployment, a.refresh_token)
    print("lock file: %s" % L.LOCK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
