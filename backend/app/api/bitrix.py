"""Bitrix24 proxy API — proxy webhook calls to Bitrix24 from frontend."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/bitrix", tags=["bitrix24"])

logger = logging.getLogger("scada.bitrix")

HTTPX_TIMEOUT = 15.0


class BitrixTestRequest(BaseModel):
    webhook_url: str


class BitrixTestResponse(BaseModel):
    success: bool
    message: str
    data: dict | None = None


class BitrixUsersRequest(BaseModel):
    webhook_url: str


class BitrixTaskRequest(BaseModel):
    webhook_url: str
    fields: dict
    checklist: list[dict] | None = None


class BitrixFolderRequest(BaseModel):
    webhook_url: str
    folder_id: int


@router.post("/test", response_model=BitrixTestResponse)
async def test_connection(req: BitrixTestRequest):
    """Test Bitrix24 webhook connection via app.info."""
    url = req.webhook_url.rstrip("/") + "/app.info.json"
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if "result" in data:
                return BitrixTestResponse(
                    success=True,
                    message="Bitrix24 connection OK",
                    data=data["result"],
                )
            else:
                return BitrixTestResponse(
                    success=False,
                    message=f"Unexpected response: {data}",
                    data=data,
                )
    except httpx.HTTPStatusError as exc:
        return BitrixTestResponse(success=False, message=f"HTTP {exc.response.status_code}: {exc}")
    except Exception as exc:
        return BitrixTestResponse(success=False, message=f"Error: {exc}")


@router.post("/users/sync")
async def sync_users(req: BitrixUsersRequest):
    """Fetch users from Bitrix24 via user.get."""
    url = req.webhook_url.rstrip("/") + "/user.get.json"
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.post(url, json={"ACTIVE": True})
            resp.raise_for_status()
            data = resp.json()
            users = data.get("result", [])
            mapped = []
            for u in users:
                mapped.append({
                    "id": str(u.get("ID", "")),
                    "name": f"{u.get('LAST_NAME', '')} {u.get('NAME', '')}".strip(),
                    "dept": ", ".join(str(d) for d in u.get("UF_DEPARTMENT", [])),
                    "pos": u.get("WORK_POSITION", ""),
                })
            return {"success": True, "users": mapped, "total": len(mapped)}
    except Exception as exc:
        raise HTTPException(502, f"Bitrix24 error: {exc}")


@router.post("/task")
async def create_task(req: BitrixTaskRequest):
    """Create a task in Bitrix24 via tasks.task.add + optional checklist."""
    url = req.webhook_url.rstrip("/") + "/tasks.task.add.json"
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.post(url, json={"fields": req.fields})
            resp.raise_for_status()
            data = resp.json()
            task_result = data.get("result", {})
            task_data = task_result if isinstance(task_result, dict) else {"task": task_result}
            task_id = task_data.get("task", {}).get("id") if isinstance(task_data.get("task"), dict) else task_data.get("task")

            checklist_results = []
            if req.checklist and task_id:
                chk_url = req.webhook_url.rstrip("/") + "/task.checklistitem.add.json"
                for item in req.checklist:
                    try:
                        chk_resp = await client.post(chk_url, json=[task_id, item])
                        chk_resp.raise_for_status()
                        checklist_results.append({"success": True, "title": item.get("TITLE", "")})
                    except Exception as e:
                        checklist_results.append({"success": False, "title": item.get("TITLE", ""), "error": str(e)})

            return {
                "success": True,
                "task_id": task_id,
                "task": task_data,
                "checklist": checklist_results,
            }
    except Exception as exc:
        raise HTTPException(502, f"Bitrix24 error: {exc}")


@router.post("/folder/scan")
async def scan_folder(req: BitrixFolderRequest):
    """Scan a Bitrix24 Disk folder via disk.folder.getchildren."""
    url = req.webhook_url.rstrip("/") + "/disk.folder.getchildren.json"
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.post(url, json={"id": req.folder_id})
            resp.raise_for_status()
            data = resp.json()
            files = []
            for item in data.get("result", []):
                if item.get("TYPE") == "file":
                    files.append({
                        "id": item.get("ID"),
                        "name": item.get("NAME", ""),
                        "size": item.get("SIZE", 0),
                        "updated": item.get("UPDATE_TIME", ""),
                    })
            return {"success": True, "files": files, "total": len(files)}
    except Exception as exc:
        raise HTTPException(502, f"Bitrix24 error: {exc}")
