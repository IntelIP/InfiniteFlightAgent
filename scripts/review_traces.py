"""Review remote conversations and optionally enqueue them in LangSmith.

Read-only by default. --enqueue creates/reuses the named review queue and adds threads.
No model calls, FlightAware calls, or SimBrief actions. Existing trace contents remain in
LangSmith; the local report contains ids and objective workflow signals only.
"""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langsmith import Client

from ifdispatcher.config import setting
from ifdispatcher.observability import summarize
from langchain_core.messages import messages_from_dict

RUBRIC = {
    "ifd_task_completed": "Did the conversation fulfill the original user request, including feasibility/arrival constraints?",
    "ifd_unnecessary_clarification": "Did it ask for information already settled or duplicate the dispatch approval?",
    "ifd_incorrect_number": "Did prose disagree with tool evidence for times, fuel, load or thrust?",
    "ifd_manual_intervention": "Did the user have to recover an operation that the tools could safely complete?",
}


def workflow_signals(outputs: dict) -> dict:
    serialized = []
    for item in outputs.get("messages", []):
        data = item.get("kwargs") or item.get("data") or item
        kind = data.get("type") or data.get("role")
        if kind == "tool":
            serialized.append(
                {
                    "type": "tool",
                    "data": {
                        k: v
                        for k, v in data.items()
                        if k in ("content", "name", "tool_call_id", "id")
                    },
                }
            )
    return summarize(messages_from_dict(serialized), set())


async def review(client, project_name: str, days: int, limit: int, enqueue: bool) -> dict:
    project = client.read_project(project_name=project_name)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    runs = await client.runs.query(
        project_ids=[str(project.id)],
        min_start_time=since,
        is_root=True,
        filter='has(tags, "remote")',
        page_size=limit,
        selects=["ID", "START_TIME", "END_TIME", "OUTPUTS", "EXTRA", "ERROR", "TAGS"],
    )
    threads = {}
    for run in runs.items or []:
        metadata = (run.extra or {}).get("metadata", {})
        thread = metadata.get("thread_id")
        if thread and (thread not in threads or run.start_time > threads[thread]["start_time"]):
            threads[thread] = {
                "thread_id": thread,
                "run_id": str(run.id),
                "start_time": run.start_time,
                "signals": workflow_signals(run.outputs or {}),
                "exception": bool(run.error),
            }
    queue_id = None
    if enqueue and threads:
        queue = next(client.list_annotation_queues(name="Infinite Flight release review"), None)
        if queue is None:
            queue = client.create_annotation_queue(
                name="Infinite Flight release review",
                description="Failed/recovered and representative dispatcher conversations, reviewed as whole threads.",
                rubric_instructions="Read the original request and final result. No exception is not proof of completion. Score 1 for yes, 0 for no. Distinguish generated plans from feasible flights. Review both before/after cases when present.",
                rubric_items=[
                    {"feedback_key": key, "description": desc} for key, desc in RUBRIC.items()
                ],
            )
        queue_id = str(queue.id)
        await client.annotation_queues.items.create(
            queue_id,
            extend_trace_retention=False,
            items=[
                {"item_type": "THREAD", "thread_id": thread, "project_id": str(project.id)}
                for thread in threads
            ],
        )
    return {
        "project": project_name,
        "project_id": str(project.id),
        "since": since.isoformat(),
        "sample_limit": limit,
        "returned_turns": len(runs.items or []),
        "next_cursor": runs.next_cursor,
        "queue_id": queue_id,
        "rubric": RUBRIC,
        "threads": list(threads.values()),
        "note": "A bounded sample, not an overall success rate. Human feedback is not auto-invented.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or not 1 <= args.days <= 365:
        parser.error("limit must be 1..100 and days 1..365")
    client = Client(api_key=setting("LANGSMITH_API_KEY"))
    result = asyncio.run(
        review(
            client,
            setting("LANGSMITH_PROJECT") or "infinite-flight-dispatcher",
            args.days,
            args.limit,
            args.enqueue,
        )
    )
    text = json.dumps(result, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
