"""Run destructive, synthetic-only deployment smoke checks and clean them up."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from google.cloud import bigquery
from toolbox_core import ToolboxSyncClient

REPO_ROOT = Path(__file__).parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from productivity_intelligence.response_validation import validate_visible_response  # noqa: E402


def decode_rows(value: str) -> list[dict[str, Any]]:
    decoded = json.loads(value)
    if decoded is None:
        return []
    if isinstance(decoded, dict):
        for key in ("rows", "result", "data"):
            if isinstance(decoded.get(key), list):
                return decoded[key]
        return [decoded]
    if isinstance(decoded, list):
        return decoded
    raise AssertionError(f"unexpected Toolbox response type: {type(decoded).__name__}")


def identity_token(service_account: str, audience: str) -> str:
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not gcloud:
        raise RuntimeError("gcloud executable was not found")
    result = subprocess.run(
        [
            gcloud,
            "auth",
            "print-identity-token",
            f"--impersonate-service-account={service_account}",
            f"--audiences={audience}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def request_json(url: str, *, method: str = "GET", payload: object | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = response.read()
    return json.loads(body) if body else None


def verify_chat_tool_completion(assistant_url: str, marker: str) -> None:
    user_id = "deployment-smoke"
    session_id = f"session-{uuid.uuid4().hex[:10]}"
    session_url = (
        f"{assistant_url.rstrip('/')}/apps/productivity_intelligence/users/"
        f"{user_id}/sessions/{session_id}"
    )
    request_json(session_url, method="POST", payload={})
    try:
        events = request_json(
            f"{assistant_url.rstrip('/')}/run",
            method="POST",
            payload={
                "appName": "productivity_intelligence",
                "userId": user_id,
                "sessionId": session_id,
                "newMessage": {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"Search my notes for nebula launch monitoring. "
                                f"Include the matching note title containing {marker}."
                            )
                        }
                    ],
                },
                "streaming": False,
            },
        )
        assert isinstance(events, list)
        parts = [
            part
            for event in events
            for part in (event.get("content", {}).get("parts", []) or [])
        ]
        tool_names = [
            part.get("functionCall", {}).get("name")
            for part in parts
            if part.get("functionCall")
        ]
        final_text = " ".join(part.get("text", "") for part in parts if part.get("text"))
        assert "search_notes_semantic" in tool_names
        assert marker.lower() in final_text.lower(), "chat did not produce a grounded final answer"
        violations = validate_visible_response("notes_agent", final_text)
        assert not violations, f"chat response contract violations: {violations}"
    finally:
        request_json(session_url, method="DELETE")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--toolbox-url", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--assistant-url")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()

    marker = f"smoke-{uuid.uuid4().hex[:10]}"
    token = identity_token(args.service_account, args.toolbox_url)
    headers = {"Authorization": f"Bearer {token}"}
    client = ToolboxSyncClient(args.toolbox_url, client_headers=headers)
    task_id = note_id = event_id = None
    try:
        create_task = client.load_tool("create_task")
        update_task = client.load_tool("update_task_status")
        delete_task = client.load_tool("delete_task")
        create_note = client.load_tool("create_note")
        search_notes = client.load_tool("search_notes_semantic")
        create_event = client.load_tool("create_event")
        list_events = client.load_tool("list_events")

        task_rows = decode_rows(
            create_task(
                title=f"{marker} deployment task",
                description="Synthetic deployment verification record",
                priority="high",
                due_date="",
            )
        )
        task_id = int(task_rows[0]["id"])
        updated = decode_rows(update_task(task_id=task_id, status="done"))
        assert updated and updated[0]["status"] == "done"

        note_rows = decode_rows(
            create_note(
                title=f"{marker} launch note",
                content="Synthetic note about nebula launch readiness and observability",
                tags="smoke,synthetic",
            )
        )
        note_id = int(note_rows[0]["id"])
        search_result = decode_rows(search_notes(query="nebula launch monitoring"))
        assert any(int(row["id"]) == note_id for row in search_result)
        if args.assistant_url:
            verify_chat_tool_completion(args.assistant_url, marker)

        event_date = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
        event_rows = decode_rows(
            create_event(
                title=f"{marker} verification event",
                date=event_date,
                time="10:00",
                duration_minutes=30,
                description="Synthetic deployment verification record",
            )
        )
        event_id = int(event_rows[0]["id"])
        listed_events = decode_rows(list_events(date=event_date))
        assert any(int(row["id"]) == event_id for row in listed_events)

        bq = bigquery.Client(project=args.project)
        sql = f"""
        SELECT SUM(completed_tasks) AS completed
        FROM `{args.project}.{args.dataset}.task_summary`
        WHERE date = CURRENT_DATE() AND priority = 'high'
        """
        for attempt in range(6):
            rows = list(bq.query(sql, location=args.region).result())
            if rows and (rows[0].completed or 0) >= 1:
                break
            if attempt == 5:
                raise AssertionError("completed task was not visible through BigQuery federation")
            time.sleep(5)

        missing = decode_rows(delete_task(task_id=2_147_483_647))
        assert not missing, "deleting a nonexistent task must return an empty/not-found result"
        checks = "Task CRUD, live analytics, semantic notes, and calendar"
        if args.assistant_url:
            checks += ", ADK tool execution, and final chat response"
        print(f"[OK] {checks} smoke tests passed")
    finally:
        for tool_name, record_id in (
            ("delete_event", event_id),
            ("delete_note", note_id),
            ("delete_task", task_id),
        ):
            if record_id is not None:
                try:
                    id_parameter = tool_name.removeprefix("delete_") + "_id"
                    client.load_tool(tool_name)(**{id_parameter: record_id})
                except Exception as exc:  # cleanup should not mask the primary result
                    print(f"[WARN] Could not clean synthetic {tool_name}: {type(exc).__name__}")
        client.close()


if __name__ == "__main__":
    main()
