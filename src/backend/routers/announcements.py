"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementPayload(BaseModel):
    """Payload for creating or updating announcements."""

    message: str = Field(min_length=3, max_length=400)
    expires_at: str
    start_date: Optional[str] = None


def parse_iso_datetime(raw_value: str, field_name: str) -> datetime:
    """Parse an ISO datetime string into a timezone-aware UTC datetime."""
    try:
        normalized = raw_value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid datetime for '{field_name}'. Use ISO format."
        ) from exc


def serialize_announcement(announcement: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB document fields to API-safe JSON values."""
    return {
        "id": str(announcement["_id"]),
        "message": announcement["message"],
        "start_date": announcement.get("start_date").isoformat() if announcement.get("start_date") else None,
        "expires_at": announcement["expires_at"].isoformat(),
        "created_by": announcement.get("created_by", ""),
        "created_at": announcement.get("created_at").isoformat() if announcement.get("created_at") else None,
        "updated_at": announcement.get("updated_at").isoformat() if announcement.get("updated_at") else None
    }


def ensure_authenticated_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Validate teacher login identity for protected endpoints."""
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get only currently active announcements for public display."""
    now = datetime.now(timezone.utc)
    query = {
        "$and": [
            {"expires_at": {"$gte": now}},
            {
                "$or": [
                    {"start_date": None},
                    {"start_date": {"$lte": now}}
                ]
            }
        ]
    }

    announcements = announcements_collection.find(query).sort("expires_at", 1)
    return [serialize_announcement(doc) for doc in announcements]


@router.get("/all", response_model=List[Dict[str, Any]])
def list_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all announcements for authenticated management screens."""
    ensure_authenticated_teacher(teacher_username)
    announcements = announcements_collection.find({}).sort("updated_at", -1)
    return [serialize_announcement(doc) for doc in announcements]


@router.post("", response_model=Dict[str, Any])
def create_announcement(payload: AnnouncementPayload, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Create a new announcement (authenticated users only)."""
    teacher = ensure_authenticated_teacher(teacher_username)

    expires_at = parse_iso_datetime(payload.expires_at, "expires_at")
    start_date = parse_iso_datetime(payload.start_date, "start_date") if payload.start_date else None

    if start_date and start_date >= expires_at:
        raise HTTPException(status_code=400, detail="start_date must be before expires_at")

    now = datetime.now(timezone.utc)
    document = {
        "message": payload.message.strip(),
        "start_date": start_date,
        "expires_at": expires_at,
        "created_by": teacher["username"],
        "created_at": now,
        "updated_at": now,
    }

    result = announcements_collection.insert_one(document)
    created = announcements_collection.find_one({"_id": result.inserted_id})
    return serialize_announcement(created)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement (authenticated users only)."""
    ensure_authenticated_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    expires_at = parse_iso_datetime(payload.expires_at, "expires_at")
    start_date = parse_iso_datetime(payload.start_date, "start_date") if payload.start_date else None

    if start_date and start_date >= expires_at:
        raise HTTPException(status_code=400, detail="start_date must be before expires_at")

    update_result = announcements_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "message": payload.message.strip(),
                "start_date": start_date,
                "expires_at": expires_at,
                "updated_at": datetime.now(timezone.utc),
            }
        }
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": object_id})
    return serialize_announcement(updated)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, str]:
    """Delete an announcement (authenticated users only)."""
    ensure_authenticated_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    delete_result = announcements_collection.delete_one({"_id": object_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted successfully"}
