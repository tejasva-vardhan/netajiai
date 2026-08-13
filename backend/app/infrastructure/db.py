"""SQLAlchemy persistence boundary for the first greenfield schema.

The application owns current state; domain events are append-only evidence and
the outbox is the reliable handoff to workers. No API should return these ORM
objects directly.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ComplaintRecord(Base):
    __tablename__ = "complaints"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    citizen_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    creation_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    creation_request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    routing_snapshot_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    routing_reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sla_policy_version: Mapped[str] = mapped_column(
        String(120), nullable=False, default="synthetic-sla.v1"
    )
    response_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=72 * 60 * 60
    )
    post_escalation_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30 * 24 * 60 * 60
    )
    execution_zone_state: Mapped[str] = mapped_column(
        String(64), nullable=False, default="mapping_in_progress"
    )
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    public_disclosure_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    disclosure_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="verified_citizen"
    )
    disclosure_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disclosure_policy_version: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    issue_cluster_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("issue_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    issue_cluster_supporter_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_complaints_citizen_creation_idempotency",
            "citizen_id",
            "creation_idempotency_key",
            unique=True,
        ),
    )

    events: Mapped[list["ComplaintEventRecord"]] = relationship(
        back_populates="complaint", lazy="raise"
    )


class IssueClusterRecord(Base):
    """Opaque deterministic candidate cluster; no raw location is stored."""

    __tablename__ = "issue_clusters"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="candidate", index=True
    )
    supporter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    members: Mapped[list["IssueClusterMemberRecord"]] = relationship(
        back_populates="cluster", lazy="raise"
    )

    __table_args__ = (
        Index(
            "ix_issue_clusters_issue_window",
            "issue_type",
            "window_start",
        ),
    )


class IssueClusterMemberRecord(Base):
    """Complaint membership with a keyed supporter reference, never raw identity."""

    __tablename__ = "issue_cluster_members"

    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cluster_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("issue_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supporter_ref_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cluster: Mapped[IssueClusterRecord] = relationship(
        back_populates="members", lazy="raise"
    )

    __table_args__ = (
        Index("ix_issue_cluster_members_cluster_supporter", "cluster_id", "supporter_ref_hash"),
    )


class ComplaintEventRecord(Base):
    __tablename__ = "complaint_events"

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    complaint: Mapped[ComplaintRecord] = relationship(back_populates="events", lazy="raise")

    __table_args__ = (
        Index("ix_complaint_events_complaint_occurred", "complaint_id", "occurred_at"),
        Index(
            "uq_complaint_events_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaint_events.event_id", ondelete="RESTRICT"),
        nullable=False, unique=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    message_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    citizen_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LocationSampleRecord(Base):
    __tablename__ = "location_samples"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    citizen_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    accuracy_m: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    evidence_assets: Mapped[list["EvidenceAssetRecord"]] = relationship(
        back_populates="location_sample", lazy="raise"
    )


class EvidenceAssetRecord(Base):
    __tablename__ = "evidence_assets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    citizen_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    creation_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    creation_request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    client_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    capture_source: Mapped[str] = mapped_column(String(40), nullable=False)
    capture_attestation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    location_sample_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("location_samples.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    upload_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    multipart_upload_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    part_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    part_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multipart_cleanup_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    multipart_cleanup_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    multipart_cleanup_last_error: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    location_sample: Mapped[LocationSampleRecord | None] = relationship(
        back_populates="evidence_assets", lazy="raise"
    )

    __table_args__ = (
        Index(
            "uq_evidence_assets_citizen_creation_idempotency",
            "citizen_id",
            "creation_idempotency_key",
            unique=True,
        ),
        Index("ix_evidence_assets_citizen_status", "citizen_id", "status"),
        Index("ix_evidence_assets_review_status_received", "status", "server_received_at", "id"),
    )


class ComplaintEvidenceRecord(Base):
    """Durable many-to-many link between a complaint and verified evidence."""

    __tablename__ = "complaint_evidence"

    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_assets.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_complaint_evidence_asset", "evidence_asset_id"),
    )


class EvidenceReviewEventRecord(Base):
    """Immutable audit record for each human media-review decision."""

    __tablename__ = "evidence_review_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    evidence_asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_assets.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_evidence_review_events_asset_idempotency",
            "evidence_asset_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_evidence_review_events_asset_occurred", "evidence_asset_id", "occurred_at"),
    )


class EvidenceUploadPartRecord(Base):
    __tablename__ = "evidence_upload_parts"

    evidence_asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_assets.id", ondelete="CASCADE"), primary_key=True
    )
    part_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    etag: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentityVerificationRecord(Base):
    __tablename__ = "identity_verifications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    subject_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    consent_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    verified_claims: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_identity_verifications_subject_status", "subject_ref", "status"),
    )


class IdentityAuthorizationStateRecord(Base):
    __tablename__ = "identity_authorization_states"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    subject_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code_verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2_000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_identity_authorization_states_expiry", "expires_at"),
        Index("ix_identity_authorization_states_subject", "subject_ref"),
    )


class NotificationDeliveryRecord(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    complaint_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    destination_ref_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    template_key: Mapped[str] = mapped_column(String(120), nullable=False)
    template_version: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_receipt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_notification_deliveries_complaint_status", "complaint_id", "status"),
    )


class WorkflowSignalReceiptRecord(Base):
    __tablename__ = "workflow_signal_receipts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    signal_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_workflow_signal_receipts_complaint_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_workflow_signal_receipts_complaint_status", "complaint_id", "status"),
    )


class CitizenResolutionResponseRecord(Base):
    """Private, append-only citizen outcome for a reported department fix."""

    __tablename__ = "citizen_resolution_responses"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_signal_receipts.signal_id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_citizen_resolution_responses_complaint_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_citizen_resolution_responses_complaint_created",
            "complaint_id",
            "created_at",
        ),
    )


class DepartmentReplyRecord(Base):
    """Private, append-only department response and weak-reply signal."""

    __tablename__ = "department_replies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    classification_reason: Mapped[str] = mapped_column(String(120), nullable=False)
    classification_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    proof_claim_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("closure_proof_claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_department_replies_complaint_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_department_replies_complaint_text_hash",
            "complaint_id",
            "response_text_hash",
        ),
    )


class SilenceEventRecord(Base):
    """Private, append-only proof that a workflow deadline elapsed silently."""

    __tablename__ = "silence_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index(
            "uq_silence_events_complaint_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_silence_events_complaint_observed",
            "complaint_id",
            "observed_at",
        ),
    )


class ClosureProofClaimRecord(Base):
    """Redacted, durable proof claim used by the closure workflow."""

    __tablename__ = "closure_proof_claims"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    complaint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proof_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proof_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    verifier: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_closure_proof_claims_complaint_idempotency",
            "complaint_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "uq_closure_proof_claims_complaint_reference",
            "complaint_id",
            "proof_reference_hash",
            unique=True,
        ),
        Index("ix_closure_proof_claims_complaint_status", "complaint_id", "status"),
    )


class VoiceDraftRequestRecord(Base):
    """Citizen-scoped idempotency binding without a generated draft payload."""

    __tablename__ = "voice_draft_requests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    citizen_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    audio_asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evidence_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_voice_draft_requests_citizen_idempotency",
            "citizen_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_voice_draft_requests_citizen_created", "citizen_id", "created_at"),
    )


class SchemeRecord(Base):
    __tablename__ = "scheme_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scheme_key: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    jurisdiction_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    search_terms: Mapped[str] = mapped_column(String(1_000), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sources: Mapped[list["SchemeSourceRecord"]] = relationship(
        back_populates="scheme", lazy="raise"
    )

    __table_args__ = (
        Index("uq_scheme_records_key_language_version", "scheme_key", "language", "version", unique=True),
        Index("ix_scheme_records_review_validity", "review_status", "effective_from", "effective_until"),
    )


class SchemeSourceRecord(Base):
    __tablename__ = "scheme_sources"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scheme_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scheme_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2_000), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    scheme: Mapped[SchemeRecord] = relationship(back_populates="sources", lazy="raise")

    __table_args__ = (
        Index("uq_scheme_sources_scheme_hash", "scheme_id", "document_hash", unique=True),
    )
