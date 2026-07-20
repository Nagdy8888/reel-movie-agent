"""Production smoke test: health, auth, and two-turn chat artifact refresh."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


def _load_env() -> dict[str, str]:
    """Parse key=value pairs from the repo root ``.env`` file."""
    env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def main() -> None:
    """Verify production backend health and multi-turn chat artifact updates."""
    env = _load_env()
    base = env["NEXT_PUBLIC_API_URL"].rstrip("/")
    sb_url = env["SUPABASE_URL"]
    sb_key = env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
    email = "reel-smoke-test@example.com"
    password = "ReelTestPass123!"
    results: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append({"test": name, "ok": ok, "detail": detail})
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name} — {detail}")

    for path in ("/health", "/ready"):
        response = httpx.get(f"{base}{path}", timeout=30)
        payload = response.json() if response.status_code == 200 else {}
        record(
            f"GET {path}",
            response.status_code == 200 and payload.get("status") == "ok",
            f"status={response.status_code}",
        )

    auth_headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=180) as client:
        signin = client.post(
            f"{sb_url}/auth/v1/token?grant_type=password",
            headers=auth_headers,
            json={"email": email, "password": password},
        )
        token = signin.json().get("access_token") if signin.status_code == 200 else None
        record("Supabase auth token", bool(token), f"signin_status={signin.status_code}")
        if not token:
            print(json.dumps({"results": results}, indent=2))
            sys.exit(1)

        auth = {"Authorization": f"Bearer {token}"}

        def chat_once(message: str, thread_id: str | None = None) -> tuple[int, str]:
            payload: dict[str, str] = {"message": message}
            if thread_id:
                payload["thread_id"] = thread_id
            with client.stream(
                "POST",
                f"{base}/chat",
                headers=auth,
                json=payload,
                timeout=180,
            ) as response:
                body = "".join(response.iter_text())
            return response.status_code, body

        def parse_sse(body: str) -> tuple[list[dict], list[dict], str | None]:
            """Return (sources_events, graph_events, thread_id) from an SSE body."""
            sources_events: list[dict] = []
            graph_events: list[dict] = []
            thread_id_local: str | None = None
            for frame in body.split("\n\n"):
                event_name = "message"
                data_line = ""
                for line in frame.splitlines():
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_line = line[5:].strip()
                if not data_line:
                    continue
                payload = json.loads(data_line)
                if event_name == "meta":
                    thread_id_local = str(payload.get("thread_id", "")) or thread_id_local
                elif event_name == "sources":
                    sources_events.append(payload)
                elif event_name == "graph":
                    graph_events.append(payload)
            return sources_events, graph_events, thread_id_local

        status1, body1 = chat_once("Who starred in The Hunger Games?")
        record("chat turn 1 status", status1 == 200, f"status={status1}")

        sources1_events, graph1_events, thread_id = parse_sse(body1)
        src1 = sources1_events[-1]["sources"] if sources1_events else []
        gr1 = graph1_events[-1] if graph1_events else {}
        titles1 = [source.get("title") for source in src1]
        nodes1 = len(gr1.get("nodes", []))
        record(
            "turn 1 has sources/graph",
            bool(src1) and nodes1 > 0,
            f"titles={titles1} nodes={nodes1}",
        )

        status2, body2 = chat_once("Sci-fi movies about survival", thread_id)
        record(
            "chat turn 2 status",
            status2 == 200,
            f"status={status2} thread={thread_id}",
        )

        sources2_events, graph2_events, _ = parse_sse(body2)
        src2 = sources2_events[-1]["sources"] if sources2_events else []
        gr2 = graph2_events[-1] if graph2_events else {}
        titles2 = [source.get("title") for source in src2]
        nodes2 = len(gr2.get("nodes", []))
        changed = titles2 != titles1 or nodes2 != nodes1
        record(
            "turn 2 refreshes artifacts",
            changed,
            f"titles1={titles1} titles2={titles2} nodes1={nodes1} nodes2={nodes2}",
        )
        record("turn 2 streams answer token", '"token"' in body2, "token present")

    all_passed = all(item["ok"] for item in results)
    print(json.dumps({"results": results, "all_passed": all_passed}, indent=2))
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
