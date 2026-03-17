"""
yzli/kanban — Routes FastAPI
CRUD kanban + auto-trigger agents + move logic.
"""

import json
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sys
import httpx

_root = Path(__file__).parent.parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from core_v2.db import q, run, log_db
from core_v2.bus import bus
from core_v2.config import oc_gateway, DISCORD_MC_CHANNEL

_OC_URL, _OC_TOKEN = oc_gateway()
_OC_HEADERS = {"Authorization": f"Bearer {_OC_TOKEN}", "Content-Type": "application/json"}

router = APIRouter(tags=["kanban"])

COLUMNS = ["Backlog", "In Progress", "Done", "Live"]


async def oc_invoke(tool: str, args: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{_OC_URL}/tools/invoke",
            headers=_OC_HEADERS,
            json={"tool": tool, "args": args, "sessionKey": "main"}
        )
        data = r.json()
        if not data.get("ok"):
            raise HTTPException(500, f"OpenClaw: {data.get('error','unknown')}")
        return data.get("result", {}).get("details", {})


class TaskIn(BaseModel):
    title: str
    description: Optional[str] = None
    project_slug: Optional[str] = None
    client_slug: Optional[str] = None
    column_name: str = "Backlog"
    priority: str = "normal"
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    cells: Optional[str] = None
    linked_agents: Optional[str] = None
    initial_prompt: Optional[str] = None


class TaskMove(BaseModel):
    card_id: int
    to_column: str
    moved_by: str = "user"


# ─── Board ────────────────────────────────────────────────────────────────────

@router.get("")
def get_kanban(client_slug: Optional[str] = None, project_slug: Optional[str] = None):
    if project_slug:
        rows = q("SELECT * FROM kanban_cards WHERE project_slug=? ORDER BY priority DESC, created_at", (project_slug,))
    elif client_slug:
        rows = q("SELECT * FROM kanban_cards WHERE client_slug=? ORDER BY priority DESC, created_at", (client_slug,))
    else:
        rows = q("SELECT k.*, c.name as client_name FROM kanban_cards k LEFT JOIN clients c ON k.client_slug=c.slug ORDER BY k.priority DESC, k.created_at")
    board = {col: [] for col in COLUMNS}
    for r in rows:
        col = r["column_name"] if r["column_name"] in COLUMNS else "Backlog"
        board[col].append(r)
    return board


# ─── Tasks CRUD ───────────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(client_slug: Optional[str] = None, project_slug: Optional[str] = None):
    if project_slug:
        return q("SELECT * FROM kanban_cards WHERE project_slug=?", (project_slug,))
    if client_slug:
        return q("SELECT * FROM kanban_cards WHERE client_slug=?", (client_slug,))
    return q("SELECT * FROM kanban_cards ORDER BY updated_at DESC")


@router.get("/tasks/{task_id}")
def get_task(task_id: int):
    row = q("SELECT * FROM kanban_cards WHERE id=?", (task_id,), one=True)
    if not row:
        raise HTTPException(404)
    row["history"] = q("SELECT * FROM kanban_history WHERE card_id=? ORDER BY moved_at DESC LIMIT 20", (task_id,))
    return row


@router.post("/tasks", status_code=201)
async def create_task(t: TaskIn):
    lid = run(
        "INSERT INTO kanban_cards (title,description,project_slug,client_slug,column_name,priority,assignee,due_date,cells,linked_agents,initial_prompt) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (t.title, t.description, t.project_slug, t.client_slug, t.column_name, t.priority, t.assignee, t.due_date, t.cells, t.linked_agents, t.initial_prompt)
    )
    await bus.emit("task.created", {"id": lid, "title": t.title, "column": t.column_name}, "success")
    log_db(t.assignee or "kanban-module", f"Task created: {t.title}")
    return q("SELECT * FROM kanban_cards WHERE id=?", (lid,), one=True)


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, t: TaskIn):
    run(
        "UPDATE kanban_cards SET title=?,description=?,column_name=?,priority=?,assignee=?,due_date=?,updated_at=datetime('now') WHERE id=?",
        (t.title, t.description, t.column_name, t.priority, t.assignee, t.due_date, task_id)
    )
    await bus.emit("task.updated", {"id": task_id, "title": t.title}, "info")
    return q("SELECT * FROM kanban_cards WHERE id=?", (task_id,), one=True)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    if not q("SELECT id FROM kanban_cards WHERE id=?", (task_id,), one=True):
        raise HTTPException(404)
    run("DELETE FROM kanban_cards WHERE id=?", (task_id,))
    await bus.emit("task.deleted", {"id": task_id}, "warn")
    return {"deleted": task_id}


# ─── Move ────────────────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/move")
async def move_task(task_id: int, move: TaskMove):
    if move.to_column not in COLUMNS:
        raise HTTPException(400, f"Invalid column: {move.to_column}")
    row = q("SELECT * FROM kanban_cards WHERE id=?", (task_id,), one=True)
    if not row:
        raise HTTPException(404)
    from_col = row["column_name"]
    run("UPDATE kanban_cards SET column_name=?,updated_at=datetime('now') WHERE id=?", (move.to_column, task_id))
    run("INSERT INTO kanban_history (card_id,from_column,to_column,moved_by) VALUES (?,?,?,?)",
        (task_id, from_col, move.to_column, move.moved_by))
    await bus.emit("task.moved", {"id": task_id, "title": row["title"], "from": from_col, "to": move.to_column}, "info")
    log_db(move.moved_by, f"Task moved: '{row['title']}' → {move.to_column}")
    # Auto-trigger agents when moving to "In Progress"
    if move.to_column == "In Progress":
        asyncio.create_task(_trigger_task_agents(task_id))
    return {"id": task_id, "from": from_col, "to": move.to_column}


async def _trigger_task_agents(task_id: int) -> dict:
    """Spawn agent(s) pour une tâche passée In Progress."""
    row = q("SELECT * FROM kanban_cards WHERE id=?", (task_id,), one=True)
    if not row:
        return {"agent_count": 0}

    linked_agents = []
    try:
        linked_agents = json.loads(row.get("linked_agents") or "[]")
        if not isinstance(linked_agents, list):
            linked_agents = []
    except Exception:
        linked_agents = []

    if not linked_agents:
        return {"agent_count": 0}

    title = row.get("title", "")
    initial_prompt = row.get("initial_prompt", "") or ""
    client_slug = row.get("client_slug", "") or ""

    task_prompt = f"""Tu es un agent Mission Control chargé d'exécuter la tâche suivante.

## Tâche : {title}
**Client :** {client_slug}

## Prompt initial
{initial_prompt}

Exécute cette tâche. À la fin, fournis une synthèse de ce qui a été accompli."""

    session_keys = []
    for agent_slug in linked_agents:
        if len(agent_slug) > 30:
            continue
        role = q("SELECT * FROM agent_roles WHERE slug=?", (agent_slug,), one=True)
        model = role["model"] if role else "anthropic/claude-sonnet-4-6"
        full_prompt = task_prompt
        if role:
            full_prompt = (
                f"# Rôle : {role['name']}\nNiveau : {role['level']} | Modèle : {role['model']}\n\n"
                f"**Mission :** {role['mission']}\n\n---\n\n"
            ) + task_prompt
        try:
            result = await oc_invoke("sessions_spawn", {
                "task": full_prompt,
                "mode": "run",
                "runtime": "subagent",
                "model": model,
                "delivery": {"mode": "announce", "channel": "discord", "to": DISCORD_MC_CHANNEL},
            })
            sk = result.get("childSessionKey", "unknown")
            session_keys.append(sk)
        except Exception as e:
            log_db("kanban-module", f"Spawn failed for {agent_slug}: {e}", "error")

    await bus.emit("task.triggered", {"task_id": task_id, "title": title, "agent_count": len(session_keys)}, "success")
    return {"agent_count": len(session_keys)}


@router.post("/tasks/{task_id}/trigger")
async def trigger_task(task_id: int):
    if not q("SELECT id FROM kanban_cards WHERE id=?", (task_id,), one=True):
        raise HTTPException(404)
    result = await _trigger_task_agents(task_id)
    return {"status": "triggered", "task_id": task_id, **result}
