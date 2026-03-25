"""API для скачивания файлов из /opt/scada/reports/."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
import os

router = APIRouter()
REPORTS_DIR = "/opt/scada/reports"

@router.get("/reports/{filename}")
async def download_report(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    ct = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "png": "image/png", "pdf": "application/pdf", "csv": "text/csv",
    }.get(filename.rsplit(".",1)[-1], "application/octet-stream")
    return FileResponse(path, media_type=ct, filename=filename,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.get("/reports/")
async def list_reports():
    if not os.path.exists(REPORTS_DIR): return {"reports": []}
    files = []
    for f in sorted(os.listdir(REPORTS_DIR), reverse=True)[:50]:
        p = os.path.join(REPORTS_DIR, f)
        files.append({"name": f, "url": f"/reports/{f}", "size_kb": round(os.path.getsize(p)/1024,1)})
    return {"reports": files}
