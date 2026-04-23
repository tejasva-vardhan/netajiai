# main.py
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

from typing import Any, Dict, List, Literal, Optional
import os
import json
from datetime import datetime
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile, File, Form, Header
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload
try:
    from pydub import AudioSegment
except Exception as exc:
    AudioSegment = None  # type: ignore[assignment]
    print(f"WARNING: Optional audio dependency pydub unavailable: {exc}")
import speech_recognition as sr

from bot import AINetaBot
from auth import get_current_user, get_optional_current_user, router as auth_router
from database import Base, apply_schema_patches, engine, get_db, SessionLocal
from email_service import (
    DEV_SAFE_INBOX,
    INTENDED_ROLE_LABELS,
    get_department_routing,
    parse_escalation_level,
    send_complaint_email,
)
from geo_utils import (
    FALLBACK_CITY_NAME,
    _resolve_default_city_id,
    resolve_city_id_for_request,
)
import models as _orm_models  # noqa: F401 — register all SQLAlchemy models on Base.metadata
from models import City, Complaint, Department, OfficerMapping, State, User

# File to store all complaints as backup
COMPLAINTS_FILE = "complaints_data.json"


app = FastAPI(title="AI NETA")
_admin_auth_warned = False

# CORS: comma-separated browser origins (e.g. https://yourapp.vercel.app).
# If unset or empty, allow all origins as a safe deployment fallback.
_allowed_origins_env = (os.getenv("ALLOWED_ORIGINS") or "").strip()
if _allowed_origins_env:
    _cors_list = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
else:
    _cors_list = ["*"]
    print(
        "INFO: ALLOWED_ORIGINS not set — defaulting to allow all origins ['*']. "
        "Set ALLOWED_ORIGINS in production (comma-separated, e.g. https://yourapp.vercel.app)."
    )

_cors_allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


def require_admin_api_key(x_api_key: Optional[str] = Header(default=None, alias="x-api-key")) -> None:
    """
    API-key guard for admin/superadmin endpoints.
    Set ADMIN_API_KEY in environment and send it as header: x-api-key.
    """
    global _admin_auth_warned
    expected = (os.getenv("ADMIN_API_KEY") or "").strip()
    if not expected:
        if not _admin_auth_warned:
            print("WARNING: ADMIN_API_KEY is not set; admin endpoints are currently unsecured.")
            _admin_auth_warned = True
        return
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin API key")

def load_complaints():
    """Load existing complaints from JSON file"""
    if os.path.exists(COMPLAINTS_FILE):
        try:
            with open(COMPLAINTS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict) and "complaints" in data:
                        return data
                    elif isinstance(data, list):
                        return {"complaints": data}
                    else:
                        return {"complaints": []}
                else:
                    return {"complaints": []}
        except (json.JSONDecodeError, FileNotFoundError):
            return {"complaints": []}
    else:
        initial_data = {"complaints": []}
        with open(COMPLAINTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2)
        return initial_data

def save_complaint_to_file(complaint_json):
    """Save complaint to single JSON file with safe key access"""
    
    try:
        print("\n🔍 [DEBUG] save_complaint_to_file called")
        
        # Handle both {'complaint': {...}} and raw {...}
        if 'complaint' in complaint_json:
            complaint_data = complaint_json['complaint']
            print(f"🔍 [DEBUG] Found nested complaint structure")
        else:
            complaint_data = complaint_json
            print(f"🔍 [DEBUG] Using flat structure")
        
        # Load existing complaints
        all_complaints = load_complaints()
        
        # Add timestamp
        complaint_data['saved_at'] = datetime.now().isoformat()
        
        # Add to list
        all_complaints["complaints"].append(complaint_data)
        
        # Save back to file
        with open(COMPLAINTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_complaints, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ SUCCESS: Complaint {complaint_data.get('complaint_id', 'N/A')} saved to {COMPLAINTS_FILE}")
        print(f"📊 Total complaints: {len(all_complaints['complaints'])}")
        
    except Exception as e:
        print(f"\n❌ Error saving complaint: {e}")
        import traceback
        traceback.print_exc()


# --- Admin API: complaints list + status (database + JSON backup) ---


def _photo_public_path(photo_path: Optional[str]) -> Optional[str]:
    """Map stored relative path to URL path served by StaticFiles mounts."""
    if not photo_path:
        return None
    normalized = str(photo_path).replace("\\", "/").strip()
    if normalized.startswith("uploads/"):
        rest = normalized[len("uploads/") :].lstrip("/")
        return f"/media/uploads/{rest}" if rest else None
    if normalized.startswith("photos/"):
        rest = normalized[len("photos/") :].lstrip("/")
        return f"/media/photos/{rest}" if rest else None
    if "/" not in normalized and "\\" not in normalized:
        return f"/media/uploads/{normalized}"
    return None


def _escalation_matrix_payload(
    level_1_email: str,
    level_2_email: str,
    level_3_email: str,
) -> Dict[str, Any]:
    """L1/L2/L3 roles + contact emails for public tracking."""
    return {
        "L1": {
            "role": INTENDED_ROLE_LABELS[1],
            "email": level_1_email or None,
        },
        "L2": {
            "role": INTENDED_ROLE_LABELS[2],
            "email": level_2_email or None,
        },
        "L3": {
            "role": INTENDED_ROLE_LABELS[3],
            "email": level_3_email or None,
        },
    }


def _track_response_from_db_row(c: Complaint, db: Session) -> Dict[str, Any]:
    issue_type = c.issue_type or ""
    routing = get_department_routing(db, c.city_id, issue_type)
    esc = parse_escalation_level(c.escalation_level)
    created = c.created_at.isoformat() if c.created_at else None
    dept_name = (c.department or "").strip() or routing.department_name
    l1 = routing.level_1_email or ""
    l2 = routing.level_2_email or ""
    l3 = routing.level_3_email or ""
    return {
        "complaint_id": c.complaint_id,
        "status": c.status or "submitted",
        "issue_type": issue_type,
        "created_at": created,
        "department": dept_name,
        "escalation_level": esc,
        "current_level_label": INTENDED_ROLE_LABELS.get(esc, INTENDED_ROLE_LABELS[1]),
        "escalation_matrix": _escalation_matrix_payload(l1, l2, l3),
    }


def _track_response_from_serialized_admin_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Same shape as _track_response_from_db_row using admin-list JSON."""
    esc = parse_escalation_level(item.get("escalation_level", 1))
    l1 = item.get("level_1_email") or ""
    l2 = item.get("level_2_email") or ""
    l3 = item.get("level_3_email") or ""
    dept_name = (item.get("department") or "").strip() or ""
    return {
        "complaint_id": item["complaint_id"],
        "status": item.get("status") or "submitted",
        "issue_type": item.get("issue_type") or "",
        "created_at": item.get("created_at"),
        "department": dept_name,
        "escalation_level": esc,
        "current_level_label": INTENDED_ROLE_LABELS.get(esc, INTENDED_ROLE_LABELS[1]),
        "escalation_matrix": _escalation_matrix_payload(l1, l2, l3),
    }


@app.get("/api/track/{complaint_id}")
def api_track_complaint(complaint_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Public tracking: complaint details plus L1/L2/L3 escalation matrix.
    Checks PostgreSQL first, then complaints_data.json (legacy backup rows).
    """
    cid = (complaint_id or "").strip()
    if not cid:
        raise HTTPException(status_code=404, detail="Complaint not found")

    row = (
        db.query(Complaint)
        .options(joinedload(Complaint.user))
        .filter(Complaint.complaint_id == cid)
        .first()
    )
    if row:
        return _track_response_from_db_row(row, db)

    for item in _complaints_from_json_file(db):
        if item.get("complaint_id") == cid:
            return _track_response_from_serialized_admin_item(item)

    raise HTTPException(status_code=404, detail="Complaint not found")


def _serialize_db_complaint(c: Complaint, db: Session) -> Dict[str, Any]:
    created = c.created_at.isoformat() if c.created_at else None
    photo_pp = _photo_public_path(c.photo_path)
    issue_type = c.issue_type or ""
    routing = get_department_routing(db, c.city_id, issue_type)
    l1 = routing.level_1_email or ""
    return {
        "complaint_id": c.complaint_id,
        "created_at": created,
        "department": c.department or "",
        "issue_type": c.issue_type or "",
        "routed_email": l1,
        "level_1_email": l1,
        "level_2_email": routing.level_2_email or "",
        "level_3_email": routing.level_3_email or "",
        "severity": c.severity or "normal",
        "escalation_level": c.escalation_level,
        "location": c.location or "",
        "latitude": getattr(c, "latitude", None),
        "longitude": getattr(c, "longitude", None),
        "description": c.description or "",
        "status": c.status or "submitted",
        "photo_path": c.photo_path,
        "photo_url": photo_pp,
        "source": "database",
        "citizen_user_id": c.user.user_id if c.user else None,
        "phone": c.user.phone if c.user else None,
    }


def _complaints_from_json_file(db: Session) -> List[Dict[str, Any]]:
    data = load_complaints()
    items = data.get("complaints", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        cid = raw.get("complaint_id")
        if not cid:
            continue
        cd = raw.get("complaint_data", {}) or {}
        dept = raw.get("department")
        if isinstance(dept, dict):
            dept = dept.get("name") or ""
        elif dept is None:
            dept = ""
        st = raw.get("status", {})
        if isinstance(st, dict):
            status_val = st.get("current") or "submitted"
        else:
            status_val = str(st) if st else "submitted"
        photo = cd.get("photo_path")
        created = raw.get("saved_at") or (raw.get("metadata") or {}).get("submitted_at")
        user_block = raw.get("user", {}) or {}
        issue_type = cd.get("issue_type") or ""
        raw_cid = cd.get("city_id")
        city_id_for_route: int | None = None
        if raw_cid is not None:
            try:
                city_id_for_route = int(raw_cid)
            except (TypeError, ValueError):
                city_id_for_route = None
        routing = get_department_routing(db, city_id_for_route, issue_type)
        l1 = routing.level_1_email or ""
        sev = raw.get("severity") or cd.get("severity") or "normal"
        esc = parse_escalation_level(raw.get("escalation_level", cd.get("escalation_level", 1)))
        out.append(
            {
                "complaint_id": cid,
                "created_at": created,
                "department": str(dept),
                "issue_type": cd.get("issue_type") or "",
                "routed_email": l1,
                "level_1_email": l1,
                "level_2_email": routing.level_2_email or "",
                "level_3_email": routing.level_3_email or "",
                "severity": sev,
                "escalation_level": esc,
                "location": cd.get("location") or "",
                "latitude": cd.get("latitude"),
                "longitude": cd.get("longitude"),
                "description": cd.get("description") or "",
                "status": status_val,
                "photo_path": photo,
                "photo_url": _photo_public_path(photo),
                "source": "json",
                "citizen_user_id": user_block.get("user_id"),
                "phone": user_block.get("phone"),
            }
        )
    return out


def _public_marker_from_admin_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    """Safe, map-ready public complaint marker payload."""
    lat = item.get("latitude")
    lng = item.get("longitude")
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return None
    return {
        "complaint_id": item.get("complaint_id"),
        "latitude": lat_f,
        "longitude": lng_f,
        "issue_type": (item.get("issue_type") or "").strip(),
        "department_name": (item.get("department") or "").strip(),
        "status": (item.get("status") or "submitted").strip(),
    }


class ComplaintStatusUpdate(BaseModel):
    status: Literal["pending", "in_progress", "resolved"]


class OfficerAssignBody(BaseModel):
    city_id: int
    department_id: int
    level_1_email: Optional[str] = None
    level_2_email: Optional[str] = None
    level_3_email: Optional[str] = None


@app.get("/api/complaints")
def api_list_all_complaints(
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    All complaints for the admin dashboard: primary source PostgreSQL,
    plus any entries only present in complaints_data.json.
    """
    rows = (
        db.query(Complaint)
        .options(joinedload(Complaint.user))
        .order_by(Complaint.created_at.desc())
        .all()
    )
    db_list = [_serialize_db_complaint(c, db) for c in rows]
    seen_ids = {item["complaint_id"] for item in db_list}

    for item in _complaints_from_json_file(db):
        if item["complaint_id"] not in seen_ids:
            db_list.append(item)
            seen_ids.add(item["complaint_id"])

    # Newest first: parse ISO dates where possible
    def sort_key(x: Dict[str, Any]) -> str:
        return x.get("created_at") or ""

    db_list.sort(key=sort_key, reverse=True)
    return {"complaints": db_list}


@app.get("/api/admin/analytics")
def api_admin_analytics(
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    SLA analytics for admin dashboard:
    - total complaints
    - status breakdown
    - department complaint + escalation distribution
    """
    rows = (
        db.query(Complaint)
        .options(joinedload(Complaint.user))
        .order_by(Complaint.created_at.desc())
        .all()
    )
    combined = [_serialize_db_complaint(c, db) for c in rows]
    seen_ids = {item["complaint_id"] for item in combined}
    for item in _complaints_from_json_file(db):
        if item["complaint_id"] not in seen_ids:
            combined.append(item)
            seen_ids.add(item["complaint_id"])

    status_breakdown: Dict[str, int] = {}
    dept_map: Dict[str, Dict[str, Any]] = {}

    for item in combined:
        status_raw = str(item.get("status") or "submitted").strip().lower()
        status_key = status_raw if status_raw else "submitted"
        status_breakdown[status_key] = status_breakdown.get(status_key, 0) + 1

        dept_name = str(item.get("department") or "").strip() or "Unassigned / General"
        esc = parse_escalation_level(item.get("escalation_level", 1))
        if dept_name not in dept_map:
            dept_map[dept_name] = {
                "department_name": dept_name,
                "total_complaints": 0,
                "stuck_at_l1": 0,
                "stuck_at_l2": 0,
                "stuck_at_l3": 0,
            }
        dept_row = dept_map[dept_name]
        dept_row["total_complaints"] += 1
        if esc == 1:
            dept_row["stuck_at_l1"] += 1
        elif esc == 2:
            dept_row["stuck_at_l2"] += 1
        else:
            dept_row["stuck_at_l3"] += 1

    department_stats = sorted(
        dept_map.values(), key=lambda x: x["total_complaints"], reverse=True
    )
    return {
        "total_complaints": len(combined),
        "status_breakdown": status_breakdown,
        "department_stats": department_stats,
    }


@app.get("/api/public/complaints")
def api_public_complaints_map(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Public transparency map dataset.
    Returns only safe fields and excludes citizen contact / escalation emails.
    """
    rows = (
        db.query(Complaint)
        .options(joinedload(Complaint.user))
        .order_by(Complaint.created_at.desc())
        .all()
    )
    db_list = [_serialize_db_complaint(c, db) for c in rows]
    seen_ids = {item["complaint_id"] for item in db_list}
    for item in _complaints_from_json_file(db):
        if item["complaint_id"] not in seen_ids:
            db_list.append(item)
            seen_ids.add(item["complaint_id"])

    public_rows: List[Dict[str, Any]] = []
    for item in db_list:
        marker = _public_marker_from_admin_item(item)
        if marker:
            public_rows.append(marker)

    return {"complaints": public_rows}


@app.patch("/api/complaints/{complaint_id}")
def api_update_complaint_status(
    complaint_id: str,
    body: ComplaintStatusUpdate,
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Update workflow status (officer dashboard). Database rows only."""
    c = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Complaint not found in database")

    c.status = body.status
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "complaint_id": c.complaint_id, "status": c.status}


# --- Super Admin: platform onboarding (cities + officer routing) ---


def _list_cities_payload(db: Session) -> Dict[str, Any]:
    """All cities with state names (no INNER JOIN — avoids empty list if data is inconsistent)."""
    rows = (
        db.query(City)
        .options(joinedload(City.state))
        .order_by(City.name.asc())
        .all()
    )
    cities_out: List[Dict[str, Any]] = []
    for c in rows:
        st = c.state
        cities_out.append(
            {
                "id": c.id,
                "name": c.name,
                "state_id": c.state_id,
                "state_name": st.name if st else None,
            }
        )
    return {"cities": cities_out}


@app.get("/api/cities")
def api_public_list_cities(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Public list of cities for the citizen chat city picker (same data as superadmin)."""
    return _list_cities_payload(db)


@app.get("/api/superadmin/cities")
def api_superadmin_list_cities(
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """All cities with their parent state (for dashboards and citizen city picker)."""
    return _list_cities_payload(db)


@app.get("/api/superadmin/departments")
def api_superadmin_list_departments(
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """All departments (for officer onboarding form dropdowns)."""
    rows = db.query(Department).order_by(Department.name).all()
    return {
        "departments": [
            {"id": d.id, "name": d.name, "keyword": d.keyword} for d in rows
        ]
    }


@app.post("/api/superadmin/officers")
def api_superadmin_assign_officer(
    body: OfficerAssignBody,
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Assign or update the escalation chain (L1/L2/L3) for a (city, department) pair.
    """
    def _norm(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        t = str(s).strip()
        if not t:
            return None
        if "@" not in t:
            raise HTTPException(status_code=400, detail="Each provided email must contain @")
        return t

    e1 = _norm(body.level_1_email)
    e2 = _norm(body.level_2_email)
    e3 = _norm(body.level_3_email)
    if not any([e1, e2, e3]):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of level_1_email, level_2_email, level_3_email",
        )

    city = db.query(City).filter(City.id == body.city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    dept = db.query(Department).filter(Department.id == body.department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    existing = (
        db.query(OfficerMapping)
        .filter(
            OfficerMapping.city_id == body.city_id,
            OfficerMapping.department_id == body.department_id,
        )
        .first()
    )
    if existing:
        existing.level_1_email = e1
        existing.level_2_email = e2
        existing.level_3_email = e3
        db.add(existing)
    else:
        db.add(
            OfficerMapping(
                city_id=body.city_id,
                department_id=body.department_id,
                level_1_email=e1,
                level_2_email=e2,
                level_3_email=e3,
            )
        )
    db.commit()
    return {"ok": True, "city_id": body.city_id, "department_id": body.department_id}


@app.get("/api/superadmin/officers")
def api_superadmin_list_officer_mappings(
    _auth: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """All officer routes with city and department names."""
    rows = (
        db.query(OfficerMapping)
        .options(
            joinedload(OfficerMapping.city).joinedload(City.state),
            joinedload(OfficerMapping.department),
        )
        .all()
    )
    rows.sort(
        key=lambda om: (
            (om.city.name or "") if om.city else "",
            (om.department.name or "") if om.department else "",
        )
    )
    out: List[Dict[str, Any]] = []
    for om in rows:
        c = om.city
        d = om.department
        st = c.state if c else None
        out.append(
            {
                "id": om.id,
                "city_id": om.city_id,
                "city_name": c.name if c else "",
                "state_name": st.name if st else "",
                "department_id": om.department_id,
                "department_name": d.name if d else "",
                "department_keyword": d.keyword if d else "",
                "level_1_email": om.level_1_email or "",
                "level_2_email": om.level_2_email or "",
                "level_3_email": om.level_3_email or "",
            }
        )
    return {"officers": out}


def _ensure_default_city_if_empty() -> None:
    """
    If the cities table is empty, insert a default state + city so the UI always has a row.
    Full department/officer seed still comes from `seed.py` when you need email routing.
    """
    db = SessionLocal()
    try:
        if db.query(City).first() is not None:
            return
        st = db.query(State).filter(State.name == "Madhya Pradesh").first()
        if st is None:
            st = State(name="Madhya Pradesh")
            db.add(st)
            db.flush()
        db.add(City(name="Shivpuri", state_id=st.id))
        db.commit()
        print("✅ Inserted default geography: Madhya Pradesh / Shivpuri (table was empty)")
    except Exception as exc:
        db.rollback()
        print(f"⚠️ Could not ensure default city: {exc}")
    finally:
        db.close()


def _ensure_fallback_city_if_missing() -> None:
    """Ensure General India Helpdesk exists for unregistered-city GPS hits."""
    db = SessionLocal()
    try:
        if db.query(City).filter(City.name == FALLBACK_CITY_NAME).first() is not None:
            return
        st = db.query(State).filter(State.name == "Pan-India").first()
        if st is None:
            st = State(name="Pan-India")
            db.add(st)
            db.flush()
        db.add(City(name=FALLBACK_CITY_NAME, state_id=st.id))
        db.commit()
        print(f"✅ Inserted fallback city {FALLBACK_CITY_NAME!r} (Pan-India)")
    except Exception as exc:
        db.rollback()
        print(f"⚠️ Could not ensure fallback city: {exc}")
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database schema on application startup."""
    try:
        Base.metadata.create_all(bind=engine)
        apply_schema_patches()
        _ensure_default_city_if_empty()
        _ensure_fallback_city_if_missing()
    except Exception as exc:
        # Keep uvicorn running so GET /health can report DB status; fix DATABASE_URL / start Postgres.
        print(f"❌ Database initialization failed (API will be degraded): {exc}")

    os.makedirs("uploads", exist_ok=True)

    # Initialize JSON file on startup
    if not os.path.exists(COMPLAINTS_FILE):
        with open(COMPLAINTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"complaints": []}, f, ensure_ascii=False, indent=2)
        print(f"✅ Created {COMPLAINTS_FILE}")


def _create_bot() -> AINetaBot:
    """Create a singleton-like bot instance using the GROQ API key."""
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set in the environment (.env).")
    return AINetaBot(api_key=groq_api_key)


_bot: AINetaBot | None = None


def get_bot() -> AINetaBot:
    """Lazy singleton so the app can load (admin, /health, /api/complaints) without GROQ."""
    global _bot
    if _bot is None:
        _bot = _create_bot()
    return _bot


def _get_bot_or_503() -> AINetaBot:
    try:
        return get_bot()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


class ChatRequest(BaseModel):
    user_id: str
    phone: str
    message: str
    latitude: float | None = None
    longitude: float | None = None
    city_id: int | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str
    reply: str
    response_json: Dict[str, Any] | None = Field(default=None, alias="json")
    error: str | None = None
    transcript: str | None = None
    field: str | None = None
    summary_data: Dict[str, Any] | None = None
    collected_so_far: Dict[str, Any] | None = None


def _transcribe_audio_file(upload: UploadFile) -> str | None:
    """
    Convert uploaded browser audio (webm) to wav and run STT.

    Note: Wrapped in try/finally to always cleanup temp files.
    """
    if AudioSegment is None:
        print("❌ [STT] pydub is unavailable; voice transcription disabled on this server")
        return None

    recognizer = sr.Recognizer()

    unique_id = uuid4().hex
    webm_path = f"temp_voice_{unique_id}.webm"
    wav_path = f"temp_voice_{unique_id}.wav"

    try:
        audio_bytes = upload.file.read()
        with open(webm_path, "wb") as f:
            f.write(audio_bytes)

        # Convert webm -> wav (pydub export is synchronous)
        audio_segment = AudioSegment.from_file(webm_path, format="webm")
        audio_segment.export(wav_path, format="wav")

        # Run speech recognition on the wav file
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        # Try Hindi first, then English
        try:
            text = recognizer.recognize_google(audio_data, language="hi-IN")
            print(f"📝 [STT] Hindi transcript: {text}")
            return text
        except Exception:
            pass

        try:
            text = recognizer.recognize_google(audio_data, language="en-IN")
            print(f"📝 [STT] English transcript: {text}")
            return text
        except sr.UnknownValueError:
            print("❌ [STT] Could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"❌ [STT] Google service error: {e}")
            return None
    except Exception as exc:
        print(f"❌ [STT] Error processing audio: {exc}")
        return None
    finally:
        # Cleanup temp files
        for path in (webm_path, wav_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"⚠️ [STT] Failed to delete temp file {path}: {e}")


def _persist_complaint_if_any(
    db: Session,
    bot_response: Dict[str, Any],
    city_id: int | None = None,
    authenticated_user: User | None = None,
) -> None:
    """
    If the bot has registered a complaint, persist it to PostgreSQL.
    """
    if bot_response.get("type") != "complaint_registered":
        return

    complaint_wrapper = _extract_response_json(bot_response)
    if not complaint_wrapper:
        return

    # Support both {"complaint": {...}} and flat {...}
    complaint_payload = complaint_wrapper.get("complaint") or complaint_wrapper

    user_payload = complaint_payload.get("user", {})
    complaint_data = complaint_payload.get("complaint_data", {})
    status_payload = complaint_payload.get("status", {}) or {}
    department_payload = complaint_payload.get("department")

    resolved_city_id = city_id if city_id is not None else _resolve_default_city_id(db)

    # Upsert user
    if authenticated_user is not None:
        user = authenticated_user
    else:
        user = (
            db.query(User)
            .filter(User.user_id == user_payload.get("user_id"))
            .first()
        )
        if not user:
            user = User(
                user_id=user_payload.get("user_id") or "unknown",
                phone=user_payload.get("phone"),
            )
            db.add(user)
            db.flush()  # get user.id

    # Normalize department
    if isinstance(department_payload, dict):
        department_name = department_payload.get("name")
    else:
        department_name = department_payload

    complaint = Complaint(
        complaint_id=complaint_payload.get("complaint_id"),
        user_id=user.id,
        city_id=resolved_city_id,
        issue_type=complaint_data.get("issue_type") or "",
        description=complaint_data.get("description") or "",
        location=complaint_data.get("location") or "",
        latitude=complaint_data.get("latitude"),
        longitude=complaint_data.get("longitude"),
        photo_path=complaint_data.get("photo_path"),
        department=department_name,
        status=status_payload.get("current") or "submitted",
        severity=str(complaint_data.get("severity") or "normal"),
        escalation_level=parse_escalation_level(
            complaint_data.get("escalation_level", complaint_payload.get("escalation_level", 1))
        ),
    )

    db.add(complaint)
    db.commit()

    # Embed city_id in JSON backup for admin routing of legacy file-only rows
    if isinstance(complaint_wrapper, dict) and "complaint" in complaint_wrapper:
        inner = complaint_wrapper["complaint"]
        if isinstance(inner, dict):
            cd = inner.setdefault("complaint_data", {})
            if isinstance(cd, dict) and resolved_city_id is not None:
                cd["city_id"] = resolved_city_id
    elif isinstance(complaint_wrapper, dict):
        cd = complaint_wrapper.setdefault("complaint_data", {})
        if isinstance(cd, dict) and resolved_city_id is not None:
            cd["city_id"] = resolved_city_id

    # Also save to JSON file as backup
    save_complaint_to_file(complaint_wrapper)


def _extract_response_json(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Backward/forward compatible JSON field lookup for bot payloads.
    """
    candidate = payload.get("response_json")
    if isinstance(candidate, dict):
        return candidate
    candidate = payload.get("json")
    if isinstance(candidate, dict):
        return candidate
    return None


@app.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> ChatResponse:
    """
    Main chat endpoint for AI NETA.
    """
    print(f"\n🔍 [API] Received message from user {payload.user_id}: {payload.message}")
    b = _get_bot_or_503()
    if payload.latitude is not None and payload.longitude is not None:
        b.set_user_coordinates(payload.user_id, payload.latitude, payload.longitude)

    try:
        city_id = resolve_city_id_for_request(
            db,
            payload.latitude,
            payload.longitude,
            payload.city_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        bot_response = b.process_message(
            user_message=payload.message,
            user_id=payload.user_id,
            phone=payload.phone,
        )

        print(f"🔍 [API] Bot response type: {bot_response.get('type')}")
        if bot_response.get("type") == "complaint_registered":
            print(
                f"🔍 [API] Complaint registered! JSON keys: "
                f"{(_extract_response_json(bot_response) or {}).keys()}"
            )
        elif bot_response.get("type") == "error":
            print(f"🔍 [API] Error: {bot_response.get('error')}")

    except Exception as exc:
        print(f"🔍 [API] Exception: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        _persist_complaint_if_any(
            db,
            bot_response,
            city_id=city_id,
            authenticated_user=current_user,
        )
        if bot_response.get("type") == "complaint_registered":
            print("🔍 [API] Complaint persisted to database and JSON file")

            # Schedule email notification in the background
            complaint_wrapper = _extract_response_json(bot_response) or {}
            complaint_payload = complaint_wrapper.get("complaint") or complaint_wrapper

            complaint_info = complaint_payload.get("complaint_data", {}) or {}
            issue_type = complaint_info.get("issue_type") or "default"

            background_tasks.add_task(
                send_complaint_email,
                complaint_payload,
                issue_type,
                city_id,
            )
    except Exception as exc:
        print(f"Error persisting complaint or scheduling email: {exc}")

    return ChatResponse(**bot_response)


@app.post("/chat/voice", response_model=ChatResponse)
async def chat_voice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    user_id: str = Form("web_citizen_1"),
    phone: str = Form("9876543210"),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    city_id: int | None = Form(None),
) -> ChatResponse:
    """
    Voice endpoint:
    - accepts audio upload
    - transcribes to text (STT)
    - passes the text into the SAME bot.process_message flow as /chat
    """
    try:
        b = _get_bot_or_503()
        if latitude is not None and longitude is not None:
            b.set_user_coordinates(user_id, latitude, longitude)
        transcript = _transcribe_audio_file(file)
        if not transcript:
            raise HTTPException(status_code=400, detail="Could not transcribe audio.")

        try:
            resolved_city_id = resolve_city_id_for_request(db, latitude, longitude, city_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        bot_response = b.process_message(
            user_message=transcript,
            user_id=user_id,
            phone=phone,
        )

        _persist_complaint_if_any(
            db,
            bot_response,
            city_id=resolved_city_id,
            authenticated_user=current_user,
        )

        if bot_response.get("type") == "complaint_registered":
            complaint_wrapper = _extract_response_json(bot_response) or {}
            complaint_payload = complaint_wrapper.get("complaint") or complaint_wrapper
            complaint_info = complaint_payload.get("complaint_data", {}) or {}
            issue_type = complaint_info.get("issue_type") or "default"
            background_tasks.add_task(
                send_complaint_email,
                complaint_payload,
                issue_type,
                resolved_city_id,
            )

        bot_response_with_transcript = dict(bot_response)
        bot_response_with_transcript["transcript"] = transcript
        return ChatResponse(**bot_response_with_transcript)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@app.post("/chat/photo", response_model=ChatResponse)
async def chat_photo(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    user_id: str = Form("web_citizen_1"),
    phone: str = Form("9876543210"),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    city_id: int | None = Form(None),
) -> ChatResponse:
    """
    Accept an image upload during the photo-consent step, save under uploads/,
    update bot session state, and return the same complaint_summary as the text flow.
    """
    try:
        b = _get_bot_or_503()
        if latitude is not None and longitude is not None:
            b.set_user_coordinates(user_id, latitude, longitude)
        content = await file.read()
        bot_response = b.save_uploaded_photo(
            user_id=user_id,
            file_bytes=content,
            original_filename=file.filename,
            content_type=file.content_type,
        )

        try:
            resolved_city_id = resolve_city_id_for_request(db, latitude, longitude, city_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        _persist_complaint_if_any(
            db,
            bot_response,
            city_id=resolved_city_id,
            authenticated_user=current_user,
        )

        if bot_response.get("type") == "complaint_registered":
            complaint_wrapper = _extract_response_json(bot_response) or {}
            complaint_payload = complaint_wrapper.get("complaint") or complaint_wrapper
            complaint_info = complaint_payload.get("complaint_data", {}) or {}
            issue_type = complaint_info.get("issue_type") or "default"
            background_tasks.add_task(
                send_complaint_email,
                complaint_payload,
                issue_type,
                resolved_city_id,
            )

        return ChatResponse(**bot_response)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@app.get("/api/config")
def api_public_config() -> Dict[str, Any]:
    """
    Non-secret values for clients (admin banner, etc.).
    `dev_safe_inbox` matches the SMTP recipient lock in email_service.
    """
    return {"dev_safe_inbox": DEV_SAFE_INBOX}


@app.get("/")
def root_status() -> Dict[str, str]:
    return {"status": "online", "message": "AI Neta API is live"}


@app.get("/health")
def health_check() -> Dict[str, Any]:
    """
    Liveness + quick dependency checks. Use this before debugging Next.js `socket hang up` proxy errors.
    """
    out: Dict[str, Any] = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api": "ok",
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        out["database"] = "connected"
    except Exception as exc:
        out["status"] = "degraded"
        out["database"] = "disconnected"
        out["database_error"] = str(exc)[:300]
    out["groq_configured"] = bool(os.getenv("GROQ_API_KEY"))
    return out


@app.get("/complaints/{user_id}")
def get_user_complaints(user_id: str, db: Session = Depends(get_db)):
    """Get all complaints for a user"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return {"complaints": []}
    
    complaints = db.query(Complaint).filter(Complaint.user_id == user.id).all()
    return {"complaints": complaints}


@app.get("/api/user/complaints")
def api_my_complaints(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Authenticated citizen endpoint: fetch complaints for current logged-in user.
    """
    rows = (
        db.query(Complaint)
        .filter(Complaint.user_id == current_user.id)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return {"complaints": [_serialize_db_complaint(c, db) for c in rows]}


# Static media for admin "View photo" links (served after API routes)
os.makedirs("uploads", exist_ok=True)
os.makedirs("photos", exist_ok=True)
app.mount("/media/uploads", StaticFiles(directory="uploads"), name="media_uploads")
app.mount("/media/photos", StaticFiles(directory="photos"), name="media_photos")