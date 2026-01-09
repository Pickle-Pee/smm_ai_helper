from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.schemas import ImageGenerateRequest, ImageGenerateResponse
from app.services.image_orchestrator import ImageOrchestrator


router = APIRouter(prefix="/images", tags=["images"])
image_orchestrator = ImageOrchestrator()


@router.post("/generate", response_model=ImageGenerateResponse)
async def generate_image(payload: ImageGenerateRequest):
    result = await image_orchestrator.generate(
        platform=payload.platform,
        use_case=payload.use_case,
        message=payload.message,
        brand=payload.brand,
        overlay=payload.overlay,
        variants=payload.variants,
        user_id="anonymous",
        request_id=uuid.uuid4().hex,
    )
    images = [{"url": f"/images/{image_id}.png"} for image_id in result["image_ids"]]
    return {
        "status": "done",
        "mode": result["mode"],
        "preset_id": result["preset_id"],
        "images": images,
    }


@router.get("/{image_id}.png")
async def get_image(image_id: str):
    path = image_orchestrator.resolve_image_path(image_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)
