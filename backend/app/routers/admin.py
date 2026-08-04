from fastapi import APIRouter, HTTPException

from ..agent.copilot import assess

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/requests/{req_id}/copilot")
async def run_copilot(req_id: str):
    try:
        return await assess(req_id)
    except KeyError:
        raise HTTPException(404, "Request not found")
