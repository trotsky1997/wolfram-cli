#!/usr/bin/env python3
"""Low-friction Wolfram Alpha CLI with project-local persistence and follow-up sessions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import requests

DEFAULT_APPID = os.environ.get("WOLFRAM_APPID", "3H4296-5YPAGQUJK7")
DEFAULT_USER_AGENT = os.environ.get("WOLFRAM_USER_AGENT", "Wolfram Android App")
ENDPOINT = os.environ.get("WOLFRAM_ENDPOINT", "https://api.wolframalpha.com/v2/query.jsp")
DEFAULT_TIMEOUT_SECONDS = 30
STATE_VERSION = 2
MAX_HISTORY_ITEMS = 100
DEFAULT_SESSION_NAME = "default"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".pi" / "skills" / "wolfram-cli" / "SKILL.md").exists():
            return candidate
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return current


def data_dir() -> Path:
    return repo_root() / ".pi" / "wolfram"


def runs_dir() -> Path:
    return data_dir() / "runs"


def state_path() -> Path:
    return data_dir() / "state.json"


def ensure_dirs() -> None:
    runs_dir().mkdir(parents=True, exist_ok=True)


def fresh_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "last_entry_id": None,
        "current_session_id": None,
        "entries": [],
        "sessions": [],
    }


@dataclass
class QueryOptions:
    input_text: str
    formats: list[str]
    assumption: str | None = None
    podstate: str | None = None
    includepodid: list[str] | None = None
    excludepodid: list[str] | None = None
    timeout_profile: str = "default"


class WolframClient:
    def __init__(self, appid: str = DEFAULT_APPID, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.appid = appid
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def query(self, options: QueryOptions) -> dict[str, Any]:
        params: dict[str, Any] = {
            "appid": self.appid,
            "input": options.input_text,
            "output": "json",
            "format": ",".join(options.formats),
        }
        if options.assumption:
            params["assumption"] = options.assumption
        if options.podstate:
            params["podstate"] = options.podstate
        if options.includepodid:
            params["includepodid"] = ",".join(options.includepodid)
        if options.excludepodid:
            params["excludepodid"] = ",".join(options.excludepodid)
        params.update(timeout_profile_params(options.timeout_profile))

        response = self.session.get(ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        if "queryresult" not in payload:
            raise RuntimeError(payload.get("message", "Unexpected response shape"))
        return payload["queryresult"]


def timeout_profile_params(profile: str) -> dict[str, str]:
    if profile == "fast":
        return {"podtimeout": "1.5", "scantimeout": "1.5", "parsetimeout": "1.5"}
    if profile == "full":
        return {}
    return {}


def slugify(value: str, limit: int = 40) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_"}:
            cleaned.append("-")
    text = "".join(cleaned).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    return (text or "query")[:limit]


def new_session(name: str | None = None) -> dict[str, Any]:
    timestamp = iso_now()
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name or DEFAULT_SESSION_NAME,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_entry_id": None,
        "entry_ids": [],
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        state = fresh_state()
    state.setdefault("version", STATE_VERSION)
    state.setdefault("created_at", iso_now())
    state.setdefault("updated_at", iso_now())
    state.setdefault("entries", [])
    state.setdefault("last_entry_id", None)
    state.setdefault("sessions", [])
    state.setdefault("current_session_id", None)

    # Migrate old flat history into a default session.
    if state["entries"] and not state["sessions"]:
        session = new_session(DEFAULT_SESSION_NAME)
        session["entry_ids"] = [entry.get("id") for entry in state["entries"] if entry.get("id")]
        session["last_entry_id"] = state.get("last_entry_id") or (session["entry_ids"][-1] if session["entry_ids"] else None)
        for entry in state["entries"]:
            entry.setdefault("session_id", session["id"])
        state["sessions"] = [session]
        state["current_session_id"] = session["id"]

    for session in state["sessions"]:
        session.setdefault("entry_ids", [])
        session.setdefault("created_at", iso_now())
        session.setdefault("updated_at", iso_now())
        session.setdefault("last_entry_id", session["entry_ids"][-1] if session["entry_ids"] else None)
        session.setdefault("name", DEFAULT_SESSION_NAME)

    if state["sessions"] and not state["current_session_id"]:
        state["current_session_id"] = state["sessions"][-1]["id"]
    return state


def load_state() -> dict[str, Any]:
    ensure_dirs()
    path = state_path()
    if not path.exists():
        return fresh_state()
    with path.open("r", encoding="utf-8") as fh:
        return normalize_state(json.load(fh))


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    state = normalize_state(state)
    state["version"] = STATE_VERSION
    state["updated_at"] = iso_now()
    with state_path().open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def first_non_empty(values: list[str]) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def pod_plaintexts(pod: dict[str, Any] | None) -> list[str]:
    if not pod:
        return []
    texts: list[str] = []
    for subpod in pod.get("subpods", []):
        text = subpod.get("plaintext")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def pick_primary_pod(pods: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred_ids = [
        "Result",
        "ExactResult",
        "DecimalApproximation",
        "Solution",
        "SymbolicSolution",
        "IndefiniteIntegral",
        "DefiniteIntegral",
        "Input",
    ]
    for pod in pods:
        if pod.get("primary") and pod_plaintexts(pod):
            return pod
    for preferred_id in preferred_ids:
        for pod in pods:
            if pod.get("id") == preferred_id and pod_plaintexts(pod):
                return pod
    for pod in pods:
        if pod_plaintexts(pod):
            return pod
    return None


def pod_states(pod: dict[str, Any]) -> list[dict[str, str]]:
    states = []
    for state in pod.get("states", []):
        name = state.get("name")
        token = state.get("input")
        if name and token:
            states.append({"name": name, "input": token})
    return states


def collect_assumptions(qr: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for assumption in qr.get("assumptions", []):
        result.append(
            {
                "word": assumption.get("word"),
                "type": assumption.get("type"),
                "template": assumption.get("template"),
                "choices": [
                    {
                        "name": value.get("name"),
                        "desc": value.get("desc"),
                        "token": value.get("input"),
                    }
                    for value in assumption.get("values", [])
                ],
            }
        )
    return result


def collect_notes(qr: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    warnings = qr.get("warnings")
    if isinstance(warnings, dict) and warnings.get("text"):
        notes.append(warnings["text"])
    for tip in qr.get("tips", []):
        text = tip.get("text")
        if text:
            notes.append(text)
    timedout = qr.get("timedout")
    if timedout:
        notes.append(f"Timed out scanners: {timedout}")
    timedout_pods = qr.get("timedoutpods")
    if timedout_pods:
        notes.append(f"Partial result, timed out pods: {timedout_pods}")
    if qr.get("parsetimedout"):
        notes.append("Parsing timed out before Wolfram Alpha could interpret the full query.")
    return notes


def simplify_pods(qr: dict[str, Any], include_images: bool = False, include_mathml: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pod in qr.get("pods", []):
        item: dict[str, Any] = {
            "id": pod.get("id"),
            "title": pod.get("title"),
            "primary": bool(pod.get("primary")),
            "states": pod_states(pod),
            "subpods": [],
        }
        for subpod in pod.get("subpods", []):
            entry: dict[str, Any] = {"title": subpod.get("title")}
            text = subpod.get("plaintext")
            if text:
                entry["plaintext"] = text
            if include_images and subpod.get("img"):
                entry["img"] = subpod["img"]
            if include_mathml and subpod.get("mathml"):
                entry["mathml"] = subpod["mathml"]
            item["subpods"].append(entry)
        items.append(item)
    return items


def build_available_actions(qr: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for assumption in qr.get("assumptions", []):
        word = assumption.get("word") or "query"
        for value in assumption.get("values", []):
            actions.append(
                {
                    "type": "assumption",
                    "label": f"Treat {word!r} as {value.get('desc') or value.get('name')}",
                    "token": value.get("input"),
                    "word": word,
                    "name": value.get("name"),
                    "desc": value.get("desc"),
                }
            )
    for pod in qr.get("pods", []):
        pod_id = pod.get("id")
        pod_title = pod.get("title")
        for state in pod_states(pod):
            actions.append(
                {
                    "type": "podstate",
                    "label": f"Show {pod_title or pod_id} as {state['name']}",
                    "token": state["input"],
                    "pod_id": pod_id,
                    "pod_title": pod_title,
                    "name": state["name"],
                }
            )
    for index, action in enumerate(actions, start=1):
        action["index"] = index
    return actions


def detect_kind(command: str, qr: dict[str, Any]) -> str:
    if command in {"solve", "convert"}:
        return command
    datatypes = (qr.get("datatypes") or "").lower()
    if "financial" in datatypes:
        return "lookup"
    if any(pod.get("id") == "Result" for pod in qr.get("pods", [])):
        return "result"
    return "ask"


def build_result(command: str, qr: dict[str, Any], detail: str = "brief") -> dict[str, Any]:
    pods = qr.get("pods", [])
    main_pod = pick_primary_pod(pods)
    answer_lines = pod_plaintexts(main_pod)
    assumptions = collect_assumptions(qr)
    result = {
        "success": bool(qr.get("success")),
        "kind": detect_kind(command, qr),
        "interpretation": qr.get("inputstring"),
        "answer": first_non_empty(answer_lines),
        "alternatives": answer_lines[1:],
        "primary_pod": {
            "id": main_pod.get("id"),
            "title": main_pod.get("title"),
        }
        if main_pod
        else None,
        "follow_up_needed": bool(assumptions),
        "choices": assumptions,
        "available_actions": build_available_actions(qr),
        "notes": collect_notes(qr),
        "partial": bool(qr.get("parsetimedout") or qr.get("timedout") or qr.get("timedoutpods")),
    }
    if detail == "full":
        result["pods"] = simplify_pods(qr)
        result["meta"] = {
            "datatypes": qr.get("datatypes"),
            "timing": qr.get("timing"),
            "parsetiming": qr.get("parsetiming"),
            "numpods": qr.get("numpods"),
            "sbsallowed": qr.get("sbsallowed"),
        }
    return result


def choose_step_state(qr: dict[str, Any]) -> tuple[str | None, str | None]:
    for pod in qr.get("pods", []):
        for state in pod_states(pod):
            if "step" in state["name"].lower() or "step" in state["input"].lower():
                return state["input"], pod.get("id")
    return None, None


def query_to_request(command: str, query: str, detail: str, timeout_profile: str) -> dict[str, Any]:
    return {
        "command": command,
        "query": query,
        "detail": detail,
        "timeout_profile": timeout_profile,
        "formats": ["plaintext"],
    }


def build_followup_options(entry: dict[str, Any], action: dict[str, Any]) -> QueryOptions:
    request = entry.get("request", {})
    formats = request.get("formats") or ["plaintext"]
    options = QueryOptions(
        input_text=entry["query"],
        formats=formats,
        timeout_profile=request.get("timeout_profile", "default"),
    )
    if action["type"] == "assumption":
        token = action.get("token")
        options.assumption = unquote_plus(token) if token else None
    elif action["type"] == "podstate":
        options.podstate = action.get("token")
        if action.get("pod_id"):
            options.includepodid = [action["pod_id"]]
    else:
        raise RuntimeError(f"Unknown action type: {action['type']}")
    return options


def run_ask(client: WolframClient, query: str, detail: str, timeout_profile: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    options = QueryOptions(input_text=query, formats=["plaintext"], timeout_profile=timeout_profile)
    raw = client.query(options)
    return build_result("ask", raw, detail=detail), raw, query_to_request("ask", query, detail, timeout_profile)


def run_solve(
    client: WolframClient,
    problem: str,
    detail: str,
    timeout_profile: str,
    show_steps: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    options = QueryOptions(input_text=problem, formats=["plaintext"], timeout_profile=timeout_profile)
    raw = client.query(options)
    result = build_result("solve", raw, detail=detail)
    result["steps"] = []
    if show_steps:
        step_state, pod_id = choose_step_state(raw)
        if step_state:
            step_raw = client.query(
                QueryOptions(
                    input_text=problem,
                    formats=["plaintext"],
                    timeout_profile=timeout_profile,
                    podstate=step_state,
                    includepodid=[pod_id] if pod_id else None,
                )
            )
            steps: list[str] = []
            for pod in simplify_pods(step_raw):
                for subpod in pod.get("subpods", []):
                    text = subpod.get("plaintext")
                    if text:
                        steps.append(text)
            if steps:
                result["steps"] = steps
            else:
                result["notes"].append("Requested steps, but Wolfram Alpha did not return plaintext step details.")
        else:
            result["notes"].append("No step-by-step state was available for this problem.")
    request = query_to_request("solve", problem, detail, timeout_profile)
    request["show_steps"] = show_steps
    return result, raw, request


def run_convert(
    client: WolframClient,
    value: str,
    target_unit: str | None,
    detail: str,
    timeout_profile: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    query = f"{value} in {target_unit}" if target_unit else value
    options = QueryOptions(input_text=query, formats=["plaintext"], timeout_profile=timeout_profile)
    raw = client.query(options)
    request = query_to_request("convert", query, detail, timeout_profile)
    request["source_value"] = value
    request["target_unit"] = target_unit
    return build_result("convert", raw, detail=detail), raw, request


def run_inspect(client: WolframClient, query: str, timeout_profile: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    formats = ["plaintext", "image", "mathml"]
    options = QueryOptions(input_text=query, formats=formats, timeout_profile=timeout_profile)
    raw = client.query(options)
    result = build_result("ask", raw, detail="full")
    result["raw_keys"] = sorted(raw.keys())
    request = query_to_request("inspect", query, "full", timeout_profile)
    request["formats"] = formats
    return result, raw, request


def session_label(session: dict[str, Any]) -> str:
    return f"{session['name']} ({session['id']})"


def find_session(state: dict[str, Any], spec: str | None) -> dict[str, Any] | None:
    if spec:
        for session in state.get("sessions", []):
            if session["id"] == spec or session["name"] == spec:
                return session
        return None
    current_id = state.get("current_session_id")
    for session in state.get("sessions", []):
        if session["id"] == current_id:
            return session
    return state.get("sessions", [])[-1] if state.get("sessions") else None


def ensure_session(state: dict[str, Any], spec: str | None) -> dict[str, Any]:
    session = find_session(state, spec)
    if session:
        state["current_session_id"] = session["id"]
        return session
    session = new_session(spec or DEFAULT_SESSION_NAME)
    state.setdefault("sessions", []).append(session)
    state["current_session_id"] = session["id"]
    return session


def get_entry(state: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    for entry in state.get("entries", []):
        if entry.get("id") == entry_id:
            return entry
    return None


def session_entries(state: dict[str, Any], session: dict[str, Any]) -> list[dict[str, Any]]:
    ids = set(session.get("entry_ids", []))
    return [entry for entry in state.get("entries", []) if entry.get("id") in ids]


def last_entry_for_session(state: dict[str, Any], session: dict[str, Any]) -> dict[str, Any] | None:
    entry_id = session.get("last_entry_id")
    if entry_id:
        entry = get_entry(state, entry_id)
        if entry:
            return entry
    entries = session_entries(state, session)
    return entries[-1] if entries else None


def persist_run(
    command: str,
    query: str,
    args: dict[str, Any],
    result: dict[str, Any],
    raw: dict[str, Any],
    request: dict[str, Any],
    session_spec: str | None,
) -> dict[str, Any]:
    state = load_state()
    session = ensure_session(state, session_spec)
    entry_id = uuid.uuid4().hex[:10]
    timestamp = iso_now()
    raw_file = runs_dir() / f"{timestamp.replace(':', '-')}-{entry_id}-{slugify(query)}.json"
    with raw_file.open("w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    entry = {
        "id": entry_id,
        "timestamp": timestamp,
        "command": command,
        "query": query,
        "args": args,
        "request": request,
        "result": result,
        "raw_path": str(raw_file.relative_to(repo_root())),
        "session_id": session["id"],
    }
    entries = state.get("entries", [])
    entries.append(entry)
    state["entries"] = entries[-MAX_HISTORY_ITEMS:]
    state["last_entry_id"] = entry_id
    session["entry_ids"] = [*session.get("entry_ids", []), entry_id][-MAX_HISTORY_ITEMS:]
    session["last_entry_id"] = entry_id
    session["updated_at"] = timestamp
    state["current_session_id"] = session["id"]
    save_state(state)
    return {"entry": entry, "session": session}


def format_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result.get("answer"):
        lines.append(f"Answer: {result['answer']}")
    else:
        lines.append("Answer: <none>")
    if result.get("alternatives"):
        lines.append("Alternatives:")
        for item in result["alternatives"]:
            lines.append(f"- {item}")
    if result.get("interpretation"):
        lines.append(f"Interpretation: {result['interpretation']}")
    if result.get("primary_pod"):
        pod = result["primary_pod"]
        lines.append(f"Primary pod: {pod.get('id')} ({pod.get('title')})")
    if result.get("steps"):
        lines.append("Steps:")
        for step in result["steps"]:
            lines.append(f"- {step}")
    if result.get("notes"):
        lines.append("Notes:")
        for note in result["notes"]:
            lines.append(f"- {note}")
    if result.get("available_actions"):
        lines.append("Available follow-ups:")
        for action in result["available_actions"]:
            lines.append(f"- {action['index']}. {action['label']}")
    if result.get("pods"):
        lines.append("Pods:")
        for pod in result["pods"]:
            marker = " [primary]" if pod.get("primary") else ""
            lines.append(f"- {pod.get('id')} - {pod.get('title')}{marker}")
            for subpod in pod.get("subpods", []):
                text = subpod.get("plaintext")
                if text:
                    wrapped = textwrap.shorten(text.replace("\n", " "), width=120, placeholder="...")
                    lines.append(f"  - {wrapped}")
    return "\n".join(lines)


def print_history(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No saved Wolfram queries yet."
    lines = []
    for entry in entries:
        answer = entry.get("result", {}).get("answer") or "<none>"
        answer = textwrap.shorten(answer.replace("\n", " "), width=80, placeholder="...")
        lines.append(
            f"{entry['timestamp']} {entry['id']} {entry['command']} [{entry.get('session_id','-')}] :: {entry['query']} -> {answer}"
        )
    return "\n".join(lines)


def print_sessions(state: dict[str, Any]) -> str:
    sessions = state.get("sessions", [])
    if not sessions:
        return "No Wolfram sessions yet."
    current_id = state.get("current_session_id")
    lines = []
    for session in sessions:
        marker = " *current" if session["id"] == current_id else ""
        lines.append(
            f"{session['id']} {session['name']} entries={len(session.get('entry_ids', []))} last={session.get('last_entry_id')}{marker}"
        )
    return "\n".join(lines)


def print_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "No follow-up actions available."
    return "\n".join(f"{action['index']}. {action['label']}" for action in actions)


def add_common_query_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--detail", choices=["brief", "full"], default="brief")
    parser.add_argument("--timeout-profile", choices=["fast", "default", "full"], default="default")
    parser.add_argument("--session", help="Session name or id; created if missing")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--no-save", action="store_true", help="Do not persist the run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Wolfram CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="General Wolfram query")
    ask.add_argument("query", nargs="+", help="Question or expression")
    add_common_query_flags(ask)

    solve = subparsers.add_parser("solve", help="Math-oriented query")
    solve.add_argument("problem", nargs="+", help="Problem statement")
    solve.add_argument("--steps", action="store_true", help="Try to fetch step-by-step output")
    add_common_query_flags(solve)

    convert = subparsers.add_parser("convert", help="Unit conversion helper")
    convert.add_argument("value", nargs="+", help="Value with source unit, e.g. '10 km'")
    convert.add_argument("--to", dest="target_unit", help="Target unit, e.g. 'miles'")
    add_common_query_flags(convert)

    inspect_cmd = subparsers.add_parser("inspect", help="Return a fuller normalized response")
    inspect_cmd.add_argument("query", nargs="+", help="Question or expression")
    add_common_query_flags(inspect_cmd)

    history = subparsers.add_parser("history", help="Show saved Wolfram runs")
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--session", help="Filter by session name or id")
    history.add_argument("--json", action="store_true", help="Emit JSON")

    last = subparsers.add_parser("last", help="Show the last saved Wolfram run")
    last.add_argument("--session", help="Session name or id")
    last.add_argument("--json", action="store_true", help="Emit JSON")

    sessions_cmd = subparsers.add_parser("sessions", help="List saved Wolfram sessions")
    sessions_cmd.add_argument("--json", action="store_true", help="Emit JSON")

    use_session = subparsers.add_parser("use-session", help="Switch the current Wolfram session")
    use_session.add_argument("session", help="Session name or id; created if missing")
    use_session.add_argument("--json", action="store_true", help="Emit JSON")

    choices = subparsers.add_parser("choices", help="List available follow-up actions from the last result")
    choices.add_argument("--session", help="Session name or id")
    choices.add_argument("--entry", help="Explicit entry id instead of the session last entry")
    choices.add_argument("--json", action="store_true", help="Emit JSON")

    apply_cmd = subparsers.add_parser("apply", help="Apply a numbered follow-up action from the last result")
    apply_cmd.add_argument("index", type=int, help="Action number from `choices`")
    apply_cmd.add_argument("--session", help="Session name or id")
    apply_cmd.add_argument("--entry", help="Explicit entry id instead of the session last entry")
    apply_cmd.add_argument("--json", action="store_true", help="Emit JSON")
    apply_cmd.add_argument("--no-save", action="store_true", help="Do not persist the run")

    return parser


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    result = payload.get("result") if "result" in payload else payload
    if isinstance(result, dict) and ("answer" in result or "available_actions" in result):
        print(format_result(result))
    elif isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)
    session_name = payload.get("session_name")
    if session_name:
        print(f"\nSession: {session_name}")
    entry_id = payload.get("entry_id")
    if entry_id:
        print(f"Saved entry: {entry_id}")
    raw_path = payload.get("raw_path")
    if raw_path:
        print(f"Raw response: {raw_path}")


def resolve_entry(state: dict[str, Any], session_spec: str | None, entry_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    session = ensure_session(state, session_spec)
    entry = get_entry(state, entry_id) if entry_id else last_entry_for_session(state, session)
    if not entry:
        raise RuntimeError(f"No saved entry found for session {session_label(session)}")
    return session, entry


def apply_saved_action(client: WolframClient, entry: dict[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    actions = entry.get("result", {}).get("available_actions", [])
    action = next((item for item in actions if item.get("index") == index), None)
    if not action:
        raise RuntimeError(f"Action {index} not found on entry {entry['id']}")
    options = build_followup_options(entry, action)
    raw = client.query(options)
    request = dict(entry.get("request", {}))
    request["followup_from_entry"] = entry["id"]
    request["followup_action"] = action
    result = build_result(entry.get("command", "ask"), raw, detail=request.get("detail", "brief"))
    return result, raw, request


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        state = load_state()

        if args.command == "sessions":
            if args.json:
                print(json.dumps({"current_session_id": state.get("current_session_id"), "sessions": state.get("sessions", [])}, ensure_ascii=False, indent=2))
            else:
                print(print_sessions(state))
            return 0

        if args.command == "use-session":
            session = ensure_session(state, args.session)
            save_state(state)
            payload = {"result": {"message": f"Using session {session_label(session)}"}, "session_name": session_label(session)}
            emit(payload, args.json)
            return 0

        if args.command == "history":
            session = find_session(state, args.session) if args.session else None
            entries = session_entries(state, session) if session else state.get("entries", [])
            entries = entries[-args.limit :]
            if args.json:
                print(json.dumps({"entries": entries}, ensure_ascii=False, indent=2))
            else:
                print(print_history(entries))
            return 0

        if args.command == "last":
            session = ensure_session(state, args.session) if args.session else find_session(state, None)
            entry = last_entry_for_session(state, session) if session else (state.get("entries", [])[-1] if state.get("entries") else None)
            if not entry:
                print("No saved Wolfram queries yet.", file=sys.stderr)
                return 1
            payload = {
                "result": entry.get("result", {}),
                "entry_id": entry["id"],
                "raw_path": entry["raw_path"],
                "session_name": session_label(session) if session else None,
            }
            emit(payload, args.json)
            return 0

        if args.command == "choices":
            session, entry = resolve_entry(state, args.session, args.entry)
            actions = entry.get("result", {}).get("available_actions", [])
            if args.json:
                print(json.dumps({"session": session, "entry": entry["id"], "actions": actions}, ensure_ascii=False, indent=2))
            else:
                print(print_actions(actions))
            return 0

        client = WolframClient()
        if args.command == "ask":
            query = " ".join(args.query)
            result, raw, request = run_ask(client, query, args.detail, args.timeout_profile)
            session_spec = args.session
        elif args.command == "solve":
            query = " ".join(args.problem)
            result, raw, request = run_solve(client, query, args.detail, args.timeout_profile, args.steps)
            session_spec = args.session
        elif args.command == "convert":
            query = " ".join(args.value)
            result, raw, request = run_convert(client, query, args.target_unit, args.detail, args.timeout_profile)
            session_spec = args.session
        elif args.command == "inspect":
            query = " ".join(args.query)
            result, raw, request = run_inspect(client, query, args.timeout_profile)
            session_spec = args.session
        else:
            session, source_entry = resolve_entry(state, args.session, args.entry)
            result, raw, request = apply_saved_action(client, source_entry, args.index)
            query = source_entry["query"]
            session_spec = session["id"]

        payload: dict[str, Any] = {"result": result}
        if not args.no_save:
            saved = persist_run(args.command, query, vars(args), result, raw, request, session_spec)
            payload["entry_id"] = saved["entry"]["id"]
            payload["raw_path"] = saved["entry"]["raw_path"]
            payload["session_name"] = session_label(saved["session"])
        emit(payload, getattr(args, "json", False))
        return 0
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None:
            try:
                body = response.json()
            except Exception:
                body = response.text
            print(json.dumps({"status": response.status_code, "error": body}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())