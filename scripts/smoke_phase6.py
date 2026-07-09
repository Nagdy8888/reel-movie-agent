"""End-to-end smoke test for Phase 6 auth + chat persistence."""

from __future__ import annotations

import json
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
    """Run auth and chat API checks against a live backend."""
    env = _load_env()
    base = "http://127.0.0.1:8000"
    sb_url = env["SUPABASE_URL"]
    sb_key = env["SUPABASE_KEY"]
    email = "reel-smoke-test@example.com"
    password = "ReelTestPass123!"

    results: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append({"test": name, "ok": ok, "detail": detail})

    r = httpx.get(f"{base}/health", timeout=30)
    record(
        "GET /health",
        r.status_code == 200 and r.json().get("status") == "ok",
        f"status={r.status_code}",
    )

    r = httpx.post(f"{base}/chat", json={"message": "Hello"}, timeout=30)
    record("POST /chat no token -> 401", r.status_code == 401, f"status={r.status_code}")

    r = httpx.get(f"{base}/health", timeout=30)
    has_request_id = bool(r.headers.get("X-Request-ID"))
    headers_ok = has_request_id and bool(r.headers.get("X-Content-Type-Options"))
    record("security headers", headers_ok, f"x-request-id={has_request_id}")

    auth_headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=120) as client:
        signin = client.post(
            f"{sb_url}/auth/v1/token?grant_type=password",
            headers=auth_headers,
            json={"email": email, "password": password},
        )
        token: str | None = signin.json().get("access_token") if signin.status_code == 200 else None
        record("Supabase auth token", bool(token), f"signin_status={signin.status_code}")

        if not token:
            print(
                json.dumps(
                    {
                        "results": results,
                        "error": "could not obtain JWT",
                        "signin_preview": signin.text[:300],
                    },
                    indent=2,
                )
            )
            raise SystemExit(1)

        auth = {"Authorization": f"Bearer {token}"}

        with client.stream(
            "POST",
            f"{base}/chat",
            headers=auth,
            json={"message": "What movies did Tom Hanks act in?"},
            timeout=120,
        ) as chat:
            chat_ok = chat.status_code == 200
            body = "".join(chat.iter_text())

        has_meta = "event: meta" in body and "conversation_id" in body
        has_done = "event: done" in body
        record(
            "POST /chat authed streams SSE",
            chat_ok and has_meta and has_done,
            f"meta={has_meta} done={has_done}",
        )

        conv_id = None
        thread_id = None
        for chunk in body.split("\n\n"):
            if chunk.startswith("event: meta"):
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        meta = json.loads(line[6:])
                        conv_id = meta.get("conversation_id")
                        thread_id = meta.get("thread_id")
        record(
            "meta has conversation_id + thread_id",
            bool(conv_id and thread_id),
            f"conv={bool(conv_id)} thread={bool(thread_id)}",
        )

        r = client.get(f"{base}/chats", headers=auth, timeout=30)
        chats = r.json() if r.status_code == 200 else []
        record(
            "GET /chats lists conversation",
            r.status_code == 200 and len(chats) >= 1,
            f"status={r.status_code} count={len(chats)}",
        )

        if conv_id:
            r = client.get(f"{base}/chats/{conv_id}", headers=auth, timeout=30)
            detail = r.json() if r.status_code == 200 else {}
            msgs = detail.get("messages", [])
            roles = {m.get("role") for m in msgs}
            record(
                "GET /chats/{id} has user+assistant msgs",
                r.status_code == 200 and "user" in roles and "assistant" in roles,
                f"status={r.status_code} roles={sorted(roles)}",
            )

            r = client.delete(f"{base}/chats/{conv_id}", headers=auth, timeout=30)
            record("DELETE /chats/{id} -> 204", r.status_code == 204, f"status={r.status_code}")

            r = client.get(f"{base}/chats/{conv_id}", headers=auth, timeout=30)
            record("GET deleted chat -> 404", r.status_code == 404, f"status={r.status_code}")

    print(json.dumps({"results": results, "all_passed": all(x["ok"] for x in results)}, indent=2))
    if not all(x["ok"] for x in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
