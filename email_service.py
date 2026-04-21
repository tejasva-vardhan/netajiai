import os
import smtplib

from dotenv import load_dotenv

load_dotenv(override=True)
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, NamedTuple, Tuple

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Department, OfficerMapping

# All complaint notifications go here until government inboxes are approved for production.
# Override with DEV_SAFE_INBOX in the environment (see GET /api/config).
_raw_dev = (os.getenv("DEV_SAFE_INBOX") or "").strip()
DEV_SAFE_INBOX = _raw_dev or "dev-safe-inbox@example.invalid"
DEFAULT_MAIL_FROM = (os.getenv("MAIL_FROM") or "").strip() or "noreply@example.invalid"

# Map common LLM / user variants to canonical Department.keyword values in the DB.
ISSUE_KEYWORD_ALIASES: Dict[str, str] = {
    "garbage": "sanitation",
    "safai": "sanitation",
    "sadak": "road",
    "pani": "water",
    "bijli": "electricity",
    "general": "default",
    "uncategorized": "default",
    "unknown": "default",
    "other": "default",
    "misc": "default",
}


class DepartmentRouting(NamedTuple):
    department_name: str
    level_1_email: str | None
    level_2_email: str | None
    level_3_email: str | None


INTENDED_ROLE_LABELS: Dict[int, str] = {
    1: "L1 Officer (Local Officer — e.g., JE)",
    2: "L2 Officer (Zonal Officer — e.g., AE / Commissioner)",
    3: "L3 Officer (State Head — e.g., Department Secretary)",
}


def normalize_issue_keyword(issue_type: str) -> str:
    k = (issue_type or "").lower().strip()
    if not k:
        k = "default"
    return ISSUE_KEYWORD_ALIASES.get(k, k)


def get_department_routing(
    db: Session,
    city_id: int | None,
    issue_type: str,
) -> DepartmentRouting:
    """
    Resolve department display name and full escalation chain (L1, L2, L3) for city + issue keyword.
    Falls back to DEFAULT_ADMIN_* env vars when no mapping exists.
    """
    fallback_name = os.getenv("DEFAULT_ADMIN_DEPARTMENT_NAME") or "Municipal Corporation Helpdesk"
    fallback_email = os.getenv("DEFAULT_ADMIN_EMAIL") or "admin@aineta.local"

    if city_id is None:
        return DepartmentRouting(fallback_name, fallback_email, None, None)

    canon = normalize_issue_keyword(issue_type)

    def _row_for_keyword(kw: str):
        return (
            db.query(OfficerMapping)
            .join(Department, OfficerMapping.department_id == Department.id)
            .filter(
                OfficerMapping.city_id == city_id,
                Department.keyword == kw,
            )
            .first()
        )

    row = _row_for_keyword(canon)
    if row is None and canon != "default":
        row = _row_for_keyword("default")

    if row:
        dept = row.department
        return DepartmentRouting(
            dept.name if dept else fallback_name,
            row.level_1_email,
            row.level_2_email,
            row.level_3_email,
        )

    return DepartmentRouting(fallback_name, fallback_email, None, None)


def parse_escalation_level(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return n if 1 <= n <= 3 else 1


def _intended_recipient_line(routing: DepartmentRouting, escalation_level: int) -> Tuple[str, str]:
    """
    Pick the label + email this complaint would target at the given escalation level,
    falling back along L1→L2→L3 if the preferred level has no address.
    """
    level = parse_escalation_level(escalation_level)
    emails = (routing.level_1_email, routing.level_2_email, routing.level_3_email)
    primary = emails[level - 1]
    if primary:
        return INTENDED_ROLE_LABELS[level], primary
    for i, em in enumerate(emails, start=1):
        if em:
            return INTENDED_ROLE_LABELS[i], em
    fb = os.getenv("DEFAULT_ADMIN_EMAIL") or "admin@aineta.local"
    return "Default routing (no officer emails on file)", fb


def send_complaint_email(
    complaint_data: Dict[str, Any],
    issue_type: str,
    city_id: int | None = None,
) -> None:
    """
    Send a formatted complaint email via Gmail SMTP.

    Routing uses OfficerMapping + Department in the database (city_id + keyword).
    Recipients are always DEV_SAFE_INBOX until production unlock.
    """
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_username or not smtp_password:
        print("⚠️ SMTP not configured correctly. Skipping email dispatch.")
        return

    # Normalise complaint payload (support both wrapped and flat structures)
    payload = complaint_data.get("complaint") if "complaint" in complaint_data else complaint_data

    complaint_id = payload.get("complaint_id", "N/A")
    complaint_info = payload.get("complaint_data", {}) or {}
    metadata = payload.get("metadata", {}) or {}

    complaint_issue_type = complaint_info.get("issue_type", "default")
    description = complaint_info.get("description", "No description provided.")
    location = complaint_info.get("location", "Unknown location")
    timestamp = metadata.get("submitted_at", "Unknown time")
    severity = complaint_info.get("severity") or payload.get("severity") or "normal"
    escalation_level = parse_escalation_level(
        complaint_info.get("escalation_level", payload.get("escalation_level", 1))
    )

    normalized_issue_type = (issue_type or complaint_issue_type or "default").lower().strip()

    db = SessionLocal()
    try:
        routing = get_department_routing(db, city_id, normalized_issue_type)
    finally:
        db.close()

    intended_label, intended_email = _intended_recipient_line(routing, escalation_level)

    l1 = routing.level_1_email or "—"
    l2 = routing.level_2_email or "—"
    l3 = routing.level_3_email or "—"

    subject = f"New Complaint for {routing.department_name}: {complaint_id}"

    to_email = DEV_SAFE_INBOX

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #222;">
        <h2 style="color: #d32f2f; margin-bottom: 0.5rem;">AI NETA - New Civic Complaint</h2>
        <p style="margin-top: 0.25rem; color: #555;">
          This is an automated alert generated by the AI NETA civic complaint assistant.
        </p>

        <hr style="border: 0; border-top: 1px solid #eee; margin: 1rem 0;" />

        <p>Respected Officer, <strong>{routing.department_name}</strong>,</p>

        <p style="margin-top: 0.5rem;">
          Please find below the details of a new civic complaint received via AI NETA:
        </p>

        <p><strong>Complaint ID:</strong> {complaint_id}</p>
        <p><strong>Issue Type:</strong> {normalized_issue_type}</p>
        <p><strong>Severity:</strong> {severity}</p>
        <p><strong>Escalation level (routing):</strong> {escalation_level}</p>
        <p><strong>Description:</strong><br />{description}</p>
        <p><strong>Location:</strong> {location}</p>
        <p><strong>Submitted At:</strong> {timestamp}</p>

        <hr style="border: 0; border-top: 1px solid #eee; margin: 1rem 0;" />

        <p style="font-size: 0.95rem;"><strong>Escalation chain on file (city + department):</strong></p>
        <ul style="margin: 0.25rem 0 0 1.25rem; font-size: 0.9rem; color: #444;">
          <li><strong>L1</strong> (local): {l1}</li>
          <li><strong>L2</strong> (zonal): {l2}</li>
          <li><strong>L3</strong> (state): {l3}</li>
        </ul>

        <p style="margin-top: 1rem; font-size: 0.95rem;">
          <strong>Intended Recipient:</strong> {intended_label} — <span style="font-family: monospace;">{intended_email}</span>
        </p>

        <hr style="border: 0; border-top: 1px solid #eee; margin: 1rem 0;" />

        <p style="font-size: 0.9rem; color: #777;">
          <strong>Delivery safety lock:</strong> This message was sent only to the developer inbox
          <span style="font-family: monospace;">{DEV_SAFE_INBOX}</span>. Government addresses above are shown for reference only
          and are not used as SMTP recipients yet.
        </p>

        <p style="font-size: 0.9rem; color: #777;">
          This email was sent for monitoring and testing purposes. All complaints are also stored
          in the AI NETA database for tracking and analytics.
        </p>
      </body>
    </html>
    """

    photo_path_raw = complaint_info.get("photo_path")
    attachment_path: str | None = None
    if photo_path_raw:
        candidate = str(photo_path_raw).strip()
        if candidate:
            resolved = candidate if os.path.isabs(candidate) else os.path.normpath(
                os.path.join(os.getcwd(), candidate.replace("/", os.sep))
            )
            if os.path.isfile(resolved):
                attachment_path = resolved

    if attachment_path:
        msg = MIMEMultipart("mixed")
        body_root = MIMEMultipart("alternative")
        body_root.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(body_root)
        try:
            with open(attachment_path, "rb") as img_f:
                image_part = MIMEImage(img_f.read())
            image_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(attachment_path),
            )
            msg.attach(image_part)
        except OSError as attach_err:
            print(f"⚠️ Could not attach complaint photo ({attachment_path}): {attach_err}")
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = DEFAULT_MAIL_FROM
    msg["To"] = to_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        print(f"✅ Complaint email sent successfully for {complaint_id} to {to_email}")
    except Exception as exc:
        # Log the error but do not raise, to avoid crashing the app
        print(f"❌ Failed to send complaint email for {complaint_id}: {exc}")


def send_otp_email(email: str, otp: str) -> None:
    """
    Send OTP to the real user email.
    NOTE: This intentionally bypasses DEV_SAFE_INBOX because OTP must reach the citizen.
    """
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    to_email = (email or "").strip()
    if not to_email:
        raise ValueError("Recipient email is required")
    if not smtp_username or not smtp_password:
        raise RuntimeError("SMTP not configured correctly for OTP delivery.")

    subject = "AI Neta Login OTP"
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.5; color: #222;">
        <h2 style="margin-bottom: 0.4rem;">AI Neta - Email Verification</h2>
        <p>Your one-time password is:</p>
        <p style="font-size: 28px; letter-spacing: 4px; font-weight: 700;">{otp}</p>
        <p>This OTP is valid for 10 minutes.</p>
        <p>If you did not request this, you can ignore this email.</p>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    msg["Subject"] = subject
    msg["From"] = DEFAULT_MAIL_FROM
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
