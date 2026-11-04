#!/usr/bin/env python3
"""Start ONE editor run by hand and watch it, or look at runs. Each run is a paid session capped at the
budget in deployment.json ($3.00 list cost).

  python3 editor-agent/run_once.py session           start one session with the deployment's settings, follow it
  python3 editor-agent/run_once.py deployment-run    trigger the deployment now (manual run), follow its session
  python3 editor-agent/run_once.py follow SESSION_ID follow a running or finished session (no new cost)
  python3 editor-agent/run_once.py runs              list the deployment's recent runs with status and cost
  python3 editor-agent/run_once.py pending SESSION_ID [--allow]   answer tool calls that wait for approval
                                                     (deny by default; scheduled runs nobody watches can stop there)

Options: --yes skips the "this costs money" question; --deny-paused answers every paused tool call with deny
without asking (default when stdin is not a terminal).

Auth: ANTHROPIC_API_KEY="$(cat /Users/zyser/Documents/work/key/global_analysis)" python3 editor-agent/run_once.py ...
The GitHub token is read from the file named in deployment.json at the moment a session is created; it is
never printed. Watch the same run in the Console: the URL is printed when the session starts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import agentlib as L  # noqa: E402

BKK = dt.timezone(dt.timedelta(hours=7))


def stamp() -> str:
    return dt.datetime.now(BKK).strftime("%H:%M:%S")


def short(s: object, n: int = 160) -> str:
    t = " ".join(str(s).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def describe_tool(ev) -> str:
    inp = ev.input or {}
    name = ev.name
    if name == "bash":
        return "bash: " + short(inp.get("command", ""), 200)
    if name == "web_search":
        return "web_search: " + short(inp.get("query", ""))
    if name == "web_fetch":
        return "web_fetch: " + short(inp.get("url", ""))
    if name in ("read", "write", "edit"):
        return "%s: %s" % (name, inp.get("file_path") or inp.get("path") or "")
    if name in ("glob", "grep"):
        return "%s: %s" % (name, short(inp.get("pattern", "")))
    return "%s: %s" % (name, short(json.dumps(inp, ensure_ascii=False)))


def outstanding(c, sid: str) -> list:
    evs = list(c.beta.sessions.events.list(session_id=sid))
    answered = {getattr(e, "tool_use_id", None) for e in evs if e.type == "user.tool_confirmation"}
    return [e for e in evs if e.type in ("agent.tool_use", "agent.mcp_tool_use")
            and getattr(e, "evaluated_permission", None) == "ask" and e.id not in answered]


def confirm_call(c, sid: str, ev, allow: bool) -> None:
    event = {"type": "user.tool_confirmation", "tool_use_id": ev.id, "result": "allow" if allow else "deny"}
    if not allow:
        event["deny_message"] = "Denied by the operator. Stay inside your hard limits; if you need this, open an issue instead."
    try:
        c.beta.sessions.events.send(session_id=sid, events=[event])
    except Exception as e:  # already answered elsewhere, or the session moved on
        print("   (could not answer: %s)" % short(e, 160))


class Follower:
    def __init__(self, c, lock: dict, session_id: str, deny_paused: bool):
        self.c, self.lock, self.sid, self.deny_paused = c, lock, session_id, deny_paused
        self.seen: set[str] = set()
        self.counts = {"web_search": 0, "web_fetch": 0, "bash": 0, "other": 0}

    def answer_pending(self) -> None:
        """Answer the tool calls that are really still waiting (asked by the server, not yet confirmed)."""
        s = self.c.beta.sessions.retrieve(self.sid)
        if s.status != "idle":
            return
        for ev in outstanding(self.c, self.sid):
            print("[%s] ?? waiting for approval: %s" % (stamp(), describe_tool(ev)))
            allow = False
            if not self.deny_paused and sys.stdin.isatty():
                allow = input("   allow this call? [y/N] ").strip().lower() == "y"
            confirm_call(self.c, self.sid, ev, allow)
            print("   -> %s" % ("allowed" if allow else "denied"))

    def handle(self, ev) -> bool:
        """Print one event; return True when following should stop."""
        if getattr(ev, "id", None):
            if ev.id in self.seen:
                return False
            self.seen.add(ev.id)
        t = ev.type
        if t == "agent.message":
            for b in ev.content or []:
                if getattr(b, "type", "") == "text":
                    print("[%s] agent: %s" % (stamp(), b.text.strip()))
        elif t in ("agent.tool_use", "agent.mcp_tool_use"):
            name = getattr(ev, "name", "")
            self.counts[name if name in self.counts else "other"] += 1
            mark = {"deny": " [DENIED]", "ask": " [WAITING]"}.get(getattr(ev, "evaluated_permission", None) or "", "")
            print("[%s] -> %s%s" % (stamp(), describe_tool(ev), mark))
        elif t == "agent.tool_result":
            if getattr(ev, "is_error", False):
                txt = " ".join(getattr(b, "text", "") for b in (ev.content or []))
                print("[%s]    tool error: %s" % (stamp(), short(txt, 300)))
        elif t == "agent.thread_context_compacted":
            print("[%s] (context compacted)" % stamp())
        elif t == "span.outcome_evaluation_end":
            print("[%s] == grader, iteration %s: %s - %s" % (stamp(), ev.iteration, ev.result, short(ev.explanation, 600)))
        elif t == "session.usage":
            print("[%s] usage: list cost %s" % (stamp(), L.money(getattr(ev.usage, "list_cost", None))))
        elif t == "session.error":
            print("[%s] !! session error: %s" % (stamp(), short(getattr(ev.error, "message", ev.error), 400)))
        elif t == "session.status_idle":
            reason = getattr(ev.stop_reason, "type", "?")
            if reason == "requires_action":
                self.answer_pending()
                return False
            print("[%s] session idle (%s)" % (stamp(), reason))
            return True
        elif t == "session.status_terminated":
            print("[%s] session terminated" % stamp())
            return True
        return False

    def run(self) -> None:
        backoff = 2
        while True:
            try:
                with self.c.beta.sessions.events.stream(session_id=self.sid) as stream:
                    # consolidation: replay what happened before / while we were disconnected
                    for ev in self.c.beta.sessions.events.list(session_id=self.sid):
                        if self.handle(ev):
                            return
                    for ev in stream:
                        if self.handle(ev):
                            return
                        backoff = 2
                s = self.c.beta.sessions.retrieve(self.sid)
                if s.status in ("idle", "terminated"):
                    return
            except KeyboardInterrupt:
                print("\nstopped following; the session keeps running: %s" % L.console_url(self.lock, self.sid))
                raise SystemExit(130)
            except Exception as e:  # dropped stream: reconnect
                print("[%s] (stream dropped: %s; reconnecting)" % (stamp(), short(e, 120)))
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def summary(self) -> None:
        s = self.c.beta.sessions.retrieve(self.sid)
        u = s.usage
        stu = getattr(u, "server_tool_use", None)
        print("\n=== session %s: %s" % (self.sid, s.status))
        print("list cost      %s (budget %s)" % (L.money(getattr(u, "list_cost", None)),
                                                 L.money(getattr(getattr(s, "budget", None), "max_list_cost", None))))
        print("tokens         in %s, out %s, cache read %s" % (u.input_tokens, u.output_tokens, u.cache_read_input_tokens))
        print("web searches   %s (calls seen here: search %d, fetch %d, bash %d)" % (
            getattr(stu, "web_search_requests", None), self.counts["web_search"], self.counts["web_fetch"], self.counts["bash"]))
        if getattr(u, "active_seconds", None):
            print("active time    %.1f min" % (u.active_seconds / 60))
        for o in s.outcome_evaluations or []:
            print("outcome        %s: %s" % (getattr(o, "outcome_id", "?"), getattr(o, "result", "?")))
        print("console        %s" % L.console_url(self.lock, self.sid))


def confirm(what: str, yes: bool) -> None:
    budget = L.money(L.read_json("deployment.json")["budget"]["max_list_cost"])
    print("%s: a paid session (tokens + $10 per 1,000 searches + $0.08 per session-hour), capped at %s." % (what, budget))
    if yes:
        return
    if not sys.stdin.isatty() or input("Start it? type yes: ").strip().lower() != "yes":
        sys.exit("not started")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["session", "deployment-run", "follow", "runs", "pending"])
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--deny-paused", action="store_true")
    ap.add_argument("--allow", action="store_true", help="pending: allow instead of deny")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    lock = L.load_lock()

    if a.command == "session":
        L.require(lock, "agent", "environment", "memory_store")
        confirm("Manual test session", a.yes)
        dep = L.read_json("deployment.json")
        c = L.client()
        s = c.beta.sessions.create(
            agent=lock["agent"]["id"],
            environment_id=lock["environment"]["id"],
            title="World Globe Editor - manual %s" % dt.datetime.now(BKK).strftime("%Y-%m-%d %H:%M"),
            resources=L.session_resources(lock, L.github_token()),
            budget=dep["budget"],
            initial_events=L.kickoff_events(),
            metadata={"trigger": "manual", "repo": "zyser007/global-analysis"},
        )
        print("session %s (%s)\nwatch: %s" % (s.id, s.status, L.console_url(lock, s.id)))
        f = Follower(c, lock, s.id, a.deny_paused)
        f.run()
        f.summary()
    elif a.command == "deployment-run":
        L.require(lock, "deployment")
        confirm("Manual deployment run", a.yes)
        c = L.client()
        r = c.beta.deployments.run(lock["deployment"]["id"])
        if not r.session_id:
            print("run %s failed to start: %s" % (r.id, r.error))
            return 1
        print("run %s -> session %s\nwatch: %s" % (r.id, r.session_id, L.console_url(lock, r.session_id)))
        f = Follower(c, lock, r.session_id, a.deny_paused)
        f.run()
        f.summary()
    elif a.command == "follow":
        if not a.session_id:
            ap.error("follow needs SESSION_ID")
        c = L.client()
        f = Follower(c, lock, a.session_id, a.deny_paused)
        f.run()
        f.summary()
    elif a.command == "runs":
        L.require(lock, "deployment")
        c = L.client()
        for i, r in enumerate(c.beta.deployment_runs.list(deployment_id=lock["deployment"]["id"], limit=a.limit)):
            if i >= a.limit:
                break
            line = "%s  %-8s %s" % (r.created_at.astimezone(BKK).strftime("%Y-%m-%d %H:%M"), r.trigger_context.type, r.id)
            if r.session_id:
                s = c.beta.sessions.retrieve(r.session_id)
                line += "  %s %-10s %s  %s" % (r.session_id, s.status, L.money(getattr(s.usage, "list_cost", None)),
                                                ",".join(getattr(o, "result", "?") for o in (s.outcome_evaluations or [])) or "-")
            else:
                line += "  FAILED %s" % (getattr(r.error, "type", r.error),)
            print(line)
    elif a.command == "pending":
        if not a.session_id:
            ap.error("pending needs SESSION_ID")
        c = L.client()
        s = c.beta.sessions.retrieve(a.session_id)
        if s.status != "idle":
            print("session is %s; nothing to answer" % s.status)
            return 0
        waiting = outstanding(c, a.session_id)
        for e in waiting:
            print(("allow " if a.allow else "deny  ") + describe_tool(e))
            confirm_call(c, a.session_id, e, a.allow)
        print("%d call(s) answered" % len(waiting))
    return 0


if __name__ == "__main__":
    sys.exit(main())
