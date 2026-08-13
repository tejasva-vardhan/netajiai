"""SQLAlchemy repository adapters for application ports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from sqlalchemy import and_, func, or_, update
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.contracts.complaints import (
    ComplaintTimelineItem,
    ComplaintTrackingResponse,
    CreateComplaintRequest,
    ComplaintResponse,
    DisclosureConsentRequest,
    DisclosureConsentResponse,
    PublicComplaintTrackingResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.workflow_signals import CitizenResolutionOutcome
from backend.app.application.issue_clusters import IssueClusterPolicy
from backend.app.application.routing import RoutingDecision
from backend.app.application.sla import SlaSnapshot
from backend.app.application.routing_activation import RoutingActivationResult
from backend.app.application.complaints import (
    ComplaintNotFound,
    ComplaintSubmissionConflict,
    TransitionIdempotencyConflict,
)
from backend.app.application.disclosure import DisclosureConsentConflict
from backend.app.domain.complaints import (
    ComplaintAggregate,
    ComplaintStatus,
    RoutingAlreadyActive,
)
from backend.app.infrastructure.db import (
    ComplaintEventRecord,
    ComplaintEvidenceRecord,
    CitizenResolutionResponseRecord,
    ComplaintRecord,
    EvidenceAssetRecord,
    IssueClusterMemberRecord,
    IssueClusterRecord,
    LocationSampleRecord,
    SilenceEventRecord,
)
from backend.app.application.admin import AdminComplaintRow, AdminOverviewData
from backend.app.application.transparency import PublicTransparencyData
from backend.app.infrastructure.outbox import append_event_and_outbox


class SqlAlchemyComplaintSubmissionRepository:
    def __init__(
        self,
        session: Session,
        *,
        issue_cluster_policy: IssueClusterPolicy | None = None,
    ) -> None:
        self._session = session
        self._issue_cluster_policy = issue_cluster_policy or IssueClusterPolicy(
            hmac_key="local-development-only-issue-cluster-key-32-bytes"
        )

    def find_by_creation_key(
        self, citizen_id: str, idempotency_key: str
    ) -> ComplaintResponse | None:
        record = self._session.scalar(
            select(ComplaintRecord).where(
                ComplaintRecord.citizen_id == citizen_id,
                ComplaintRecord.creation_idempotency_key == idempotency_key,
            )
        )
        return self._response(record) if record is not None else None

    def find_creation_request_fingerprint(
        self, citizen_id: str, idempotency_key: str
    ) -> str | None:
        return self._session.scalar(
            select(ComplaintRecord.creation_request_fingerprint).where(
                ComplaintRecord.citizen_id == citizen_id,
                ComplaintRecord.creation_idempotency_key == idempotency_key,
            )
        )

    def persist_received(
        self,
        aggregate: ComplaintAggregate,
        request: CreateComplaintRequest,
        principal: AuthenticatedPrincipal,
        routing: RoutingDecision,
        request_fingerprint: str = "",
        sla_snapshot: SlaSnapshot | None = None,
    ) -> ComplaintResponse:
        now = datetime.now(timezone.utc)
        resolved_sla = sla_snapshot or SlaSnapshot(
            policy_version="synthetic-sla.v1",
            response_timeout_seconds=72 * 60 * 60,
            post_escalation_timeout_seconds=30 * 24 * 60 * 60,
        )
        event = aggregate.events[0]
        record = ComplaintRecord(
            id=aggregate.complaint_id,
            citizen_id=principal.subject_ref,
            creation_idempotency_key=event.idempotency_key,
            creation_request_fingerprint=request_fingerprint,
            status=aggregate.status.value,
            version=aggregate.version,
            issue_type=request.issue_type,
            description=request.description,
            jurisdiction_code=routing.jurisdiction_code,
            routing_snapshot_ref=routing.snapshot_ref,
            routing_reason_code=routing.reason_code,
            sla_policy_version=resolved_sla.policy_version,
            response_timeout_seconds=resolved_sla.response_timeout_seconds,
            post_escalation_timeout_seconds=resolved_sla.post_escalation_timeout_seconds,
            execution_zone_state=routing.state,
            escalation_level=0,
            public_disclosure_eligible=False,
            disclosure_mode="verified_citizen",
            created_at=now,
            updated_at=now,
        )
        try:
            self._session.add(record)
            self._session.flush()
            self._session.add_all(
                ComplaintEvidenceRecord(
                    complaint_id=record.id,
                    evidence_asset_id=evidence_asset_id,
                    created_at=now,
                )
                for evidence_asset_id in request.evidence_asset_ids
            )
            self._session.flush()
            cluster = self._assign_issue_cluster(
                record,
                issue_type=request.issue_type,
                evidence_asset_ids=tuple(request.evidence_asset_ids),
                supporter_ref=principal.subject_ref,
                now=now,
            )
            append_event_and_outbox(
                self._session,
                event,
                topic="complaint.lifecycle.v1",
                payload={
                    "complaint_id": str(record.id),
                    "status": record.status,
                    "issue_type": record.issue_type,
                    "jurisdiction_code": record.jurisdiction_code,
                    "execution_zone_state": record.execution_zone_state,
                    "routing_reason_code": routing.reason_code,
                    "routing_snapshot_ref": routing.snapshot_ref,
                    "sla_policy_version": resolved_sla.policy_version,
                    "response_timeout_seconds": resolved_sla.response_timeout_seconds,
                    "post_escalation_timeout_seconds": resolved_sla.post_escalation_timeout_seconds,
                    "evidence_count": len(request.evidence_asset_ids),
                    "issue_cluster_id": str(cluster.id) if cluster is not None else None,
                    "issue_cluster_supporter_count": (
                        cluster.supporter_count if cluster is not None else None
                    ),
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_creation_key(
                principal.subject_ref, event.idempotency_key
            )
            if existing is None:
                raise
            stored_fingerprint = self.find_creation_request_fingerprint(
                principal.subject_ref, event.idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise ComplaintSubmissionConflict(
                    "Complaint idempotency key belongs to another request"
                )
            return existing
        self._session.refresh(record)
        return self._response(record)

    def find_owned(
        self, citizen_id: str, complaint_id: UUID
    ) -> ComplaintTrackingResponse | None:
        record = self._session.scalar(
            select(ComplaintRecord).where(
                ComplaintRecord.id == complaint_id,
                ComplaintRecord.citizen_id == citizen_id,
            )
        )
        if record is None:
            return None
        timeline = self._citizen_timeline(record.id)
        latest_resolution = self._session.scalar(
            select(CitizenResolutionResponseRecord)
            .where(CitizenResolutionResponseRecord.complaint_id == record.id)
            .order_by(
                CitizenResolutionResponseRecord.created_at.desc(),
                CitizenResolutionResponseRecord.id.desc(),
            )
            .limit(1)
        )
        last_resolution_outcome = (
            cast(CitizenResolutionOutcome, latest_resolution.outcome)
            if latest_resolution is not None
            and latest_resolution.outcome
            in {"fully_solved", "partially_solved", "not_solved"}
            else None
        )
        return ComplaintTrackingResponse(
            complaint_id=record.id,
            status=ComplaintStatus(record.status),
            version=record.version,
            issue_type=record.issue_type,
            description=record.description,
            jurisdiction_code=record.jurisdiction_code,
            execution_zone_state=record.execution_zone_state,
            escalation_level=record.escalation_level,
            disclosure_mode=record.disclosure_mode,
            last_citizen_resolution_outcome=last_resolution_outcome,
            issue_cluster_id=record.issue_cluster_id,
            supporter_count=record.issue_cluster_supporter_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
            timeline=timeline,
        )

    def _citizen_timeline(self, complaint_id: UUID) -> list[ComplaintTimelineItem]:
        events = self._session.scalars(
            select(ComplaintEventRecord)
            .where(ComplaintEventRecord.complaint_id == complaint_id)
            .order_by(ComplaintEventRecord.occurred_at, ComplaintEventRecord.event_id)
        ).all()
        timeline_with_order: list[tuple[datetime, str, ComplaintTimelineItem]] = []
        for event in events:
            payload = event.payload or {}
            escalation_level = payload.get("escalation_level")
            if not isinstance(escalation_level, int) or not 0 <= escalation_level <= 4:
                escalation_level = None
            timeline_with_order.append(
                (
                    event.occurred_at,
                    str(event.event_id),
                    ComplaintTimelineItem(
                    event_type=event.event_type,
                    from_status=(
                        ComplaintStatus(event.from_status)
                        if event.from_status is not None
                        else None
                    ),
                    status=ComplaintStatus(event.to_status),
                    escalation_level=escalation_level,
                    occurred_at=event.occurred_at,
                    ),
                )
            )
        silence_events = self._session.scalars(
            select(SilenceEventRecord)
            .where(SilenceEventRecord.complaint_id == complaint_id)
            .order_by(SilenceEventRecord.observed_at, SilenceEventRecord.id)
        ).all()
        for silence in silence_events:
            timeline_with_order.append(
                (
                    silence.observed_at,
                    str(silence.id),
                    ComplaintTimelineItem(
                        event_type="complaint.silence_deadline_breached",
                        reason_code=silence.reason_code,
                        status=ComplaintStatus(silence.status),
                        escalation_level=silence.escalation_level,
                        occurred_at=silence.observed_at,
                    ),
                )
            )
        timeline_with_order.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in timeline_with_order]

    def find_public(self, complaint_id: UUID) -> PublicComplaintTrackingResponse | None:
        record = self._session.scalar(
            select(ComplaintRecord).where(ComplaintRecord.id == complaint_id)
        )
        if record is None:
            return None
        return PublicComplaintTrackingResponse(
            complaint_id=record.id,
            status=ComplaintStatus(record.status),
            version=record.version,
            issue_type=record.issue_type,
            execution_zone_state=record.execution_zone_state,
            escalation_level=record.escalation_level,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def find_routing_activation(
        self, complaint_id: UUID, idempotency_key: str
    ) -> RoutingActivationResult | None:
        event = self._session.scalar(
            select(ComplaintEventRecord).where(
                ComplaintEventRecord.complaint_id == complaint_id,
                ComplaintEventRecord.event_type == "complaint.routing_activated",
                ComplaintEventRecord.idempotency_key == idempotency_key,
            )
        )
        if event is None:
            return None
        record = self._session.get(ComplaintRecord, complaint_id)
        if (
            record is None
            or record.execution_zone_state != "active"
            or not record.jurisdiction_code
            or not record.routing_snapshot_ref
        ):
            return None
        return RoutingActivationResult(
            complaint=self._tracking_response(record),
            decision=RoutingDecision(
                state="active",
                jurisdiction_code=record.jurisdiction_code,
                snapshot_ref=record.routing_snapshot_ref,
                reason_code=record.routing_reason_code or "routing_activated",
            ),
        )

    def transition(
        self,
        complaint_id: UUID,
        *,
        to_status: ComplaintStatus,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        escalation_level: int | None = None,
        public_disclosure_eligible: bool | None = None,
        closure_proof_claim_id: UUID | None = None,
        citizen_resolution_outcome: CitizenResolutionOutcome | None = None,
        request_fingerprint: str = "",
    ) -> ComplaintTrackingResponse | None:
        record = self._session.scalar(
            select(ComplaintRecord)
            .where(ComplaintRecord.id == complaint_id)
            .with_for_update()
        )
        if record is None:
            return None
        existing_event = self._session.scalar(
            select(ComplaintEventRecord).where(
                ComplaintEventRecord.complaint_id == complaint_id,
                ComplaintEventRecord.idempotency_key == idempotency_key,
            )
        )
        if existing_event is not None and request_fingerprint:
            stored_fingerprint = (existing_event.payload or {}).get(
                "request_fingerprint"
            )
            if stored_fingerprint != request_fingerprint:
                raise TransitionIdempotencyConflict(
                    "Transition idempotency key belongs to another request"
                )
        keys = set(
            self._session.scalars(
                select(ComplaintEventRecord.idempotency_key).where(
                    ComplaintEventRecord.complaint_id == complaint_id
                )
            )
        )
        aggregate = ComplaintAggregate(
            complaint_id,
            status=ComplaintStatus(record.status),
            version=record.version,
            _idempotency_keys=keys,
        )
        event = aggregate.transition(
            to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            closure_proof_claim_id=closure_proof_claim_id,
        )
        if event is not None:
            now = event.occurred_at
            record.status = aggregate.status.value
            record.version = aggregate.version
            if escalation_level is not None:
                if not 0 <= escalation_level <= 4:
                    raise ValueError("escalation_level must be between 0 and 4")
                record.escalation_level = escalation_level
            if public_disclosure_eligible is not None:
                record.public_disclosure_eligible = public_disclosure_eligible
            record.updated_at = now
            append_event_and_outbox(
                self._session,
                event,
                topic="complaint.lifecycle.v1",
                payload={
                    "complaint_id": str(complaint_id),
                    "from_status": event.from_status.value if event.from_status else None,
                    "status": event.to_status.value,
                    "escalation_level": record.escalation_level,
                    "public_disclosure_eligible": record.public_disclosure_eligible,
                    "closure_proof_claim_id": str(closure_proof_claim_id)
                    if closure_proof_claim_id is not None
                    else None,
                    "citizen_resolution_outcome": citizen_resolution_outcome,
                    "request_fingerprint": request_fingerprint,
                },
            )
            self._session.commit()
            self._session.refresh(record)
        return ComplaintTrackingResponse(
            complaint_id=record.id,
            status=ComplaintStatus(record.status),
            version=record.version,
            issue_type=record.issue_type,
            description=record.description,
            jurisdiction_code=record.jurisdiction_code,
            execution_zone_state=record.execution_zone_state,
            escalation_level=record.escalation_level,
            disclosure_mode=record.disclosure_mode,
            issue_cluster_id=record.issue_cluster_id,
            supporter_count=record.issue_cluster_supporter_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def activate_routing(
        self,
        complaint_id: UUID,
        *,
        routing: RoutingDecision,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ComplaintTrackingResponse | None:
        record = self._session.scalar(
            select(ComplaintRecord)
            .where(ComplaintRecord.id == complaint_id)
            .with_for_update()
        )
        if record is None:
            return None
        if record.execution_zone_state == "active":
            raise RoutingAlreadyActive("Complaint routing is already active")

        keys = set(
            self._session.scalars(
                select(ComplaintEventRecord.idempotency_key).where(
                    ComplaintEventRecord.complaint_id == complaint_id
                )
            )
        )
        aggregate = ComplaintAggregate(
            complaint_id,
            status=ComplaintStatus(record.status),
            version=record.version,
            _idempotency_keys=keys,
        )
        event = aggregate.activate_routing(
            actor_type=actor_type,
            actor_id=actor_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if event is not None:
            record.version = aggregate.version
            record.execution_zone_state = "active"
            record.jurisdiction_code = routing.jurisdiction_code
            record.routing_snapshot_ref = routing.snapshot_ref
            record.routing_reason_code = routing.reason_code
            record.updated_at = event.occurred_at
            append_event_and_outbox(
                self._session,
                event,
                topic="complaint.lifecycle.v1",
                payload={
                    "complaint_id": str(complaint_id),
                    "status": record.status,
                    "jurisdiction_code": record.jurisdiction_code,
                    "execution_zone_state": record.execution_zone_state,
                    "routing_reason_code": routing.reason_code,
                    "routing_snapshot_ref": routing.snapshot_ref,
                },
            )
            self._session.commit()
            self._session.refresh(record)
        return self._tracking_response(record)

    def set_disclosure_consent(
        self,
        citizen_id: str,
        complaint_id: UUID,
        request: DisclosureConsentRequest,
        *,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> DisclosureConsentResponse:
        record = self._session.scalar(
            select(ComplaintRecord)
            .where(
                ComplaintRecord.id == complaint_id,
                ComplaintRecord.citizen_id == citizen_id,
            )
            .with_for_update()
        )
        if record is None:
            raise ComplaintNotFound("Complaint was not found")

        existing_event = self._session.scalar(
            select(ComplaintEventRecord).where(
                ComplaintEventRecord.complaint_id == complaint_id,
                ComplaintEventRecord.idempotency_key == idempotency_key,
            )
        )
        if existing_event is not None:
            stored_fingerprint = (existing_event.payload or {}).get(
                "request_fingerprint"
            )
            if stored_fingerprint != request_fingerprint:
                raise DisclosureConsentConflict(
                    "Disclosure consent idempotency key belongs to another request"
                )
            if record.disclosure_consent_at is None:
                raise DisclosureConsentConflict(
                    "Disclosure consent is not available for replay"
                )
            return self._disclosure_response(record)

        if record.disclosure_consent_at is not None:
            raise DisclosureConsentConflict(
                "Disclosure consent has already been recorded"
            )

        keys = set(
            self._session.scalars(
                select(ComplaintEventRecord.idempotency_key).where(
                    ComplaintEventRecord.complaint_id == complaint_id
                )
            )
        )
        aggregate = ComplaintAggregate(
            complaint_id,
            status=ComplaintStatus(record.status),
            version=record.version,
            _idempotency_keys=keys,
        )
        event = aggregate.record_disclosure_consent(
            actor_type="citizen",
            actor_id=citizen_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if event is None:
            return self._disclosure_response(record)

        now = event.occurred_at
        record.version = aggregate.version
        record.disclosure_mode = request.mode
        record.public_disclosure_eligible = request.mode == "public_name"
        record.disclosure_consent_at = now
        record.disclosure_policy_version = policy_version
        record.updated_at = now
        append_event_and_outbox(
            self._session,
            event,
            topic="complaint.lifecycle.v1",
            payload={
                "complaint_id": str(complaint_id),
                "status": record.status,
                "public_disclosure_eligible": record.public_disclosure_eligible,
                "disclosure_mode": record.disclosure_mode,
                "disclosure_policy_version": policy_version,
                "request_fingerprint": request_fingerprint,
            },
        )
        self._session.commit()
        self._session.refresh(record)
        return self._disclosure_response(record)

    def _assign_issue_cluster(
        self,
        record: ComplaintRecord,
        *,
        issue_type: str,
        evidence_asset_ids: tuple[UUID, ...],
        supporter_ref: str,
        now: datetime,
    ) -> IssueClusterRecord | None:
        location = self._session.execute(
            select(
                LocationSampleRecord.latitude,
                LocationSampleRecord.longitude,
                LocationSampleRecord.accuracy_m,
                LocationSampleRecord.captured_at,
            )
            .join(
                EvidenceAssetRecord,
                EvidenceAssetRecord.location_sample_id == LocationSampleRecord.id,
            )
            .where(
                EvidenceAssetRecord.id.in_(evidence_asset_ids),
                EvidenceAssetRecord.status == "verified",
            )
            .order_by(LocationSampleRecord.accuracy_m.asc())
            .limit(1)
        ).first()
        if location is None:
            return None

        candidate = self._issue_cluster_policy.candidate(
            issue_type=issue_type,
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            accuracy_m=float(location.accuracy_m),
            captured_at=location.captured_at,
            supporter_ref=supporter_ref,
        )
        if candidate is None:
            return None

        cluster_id = uuid4()
        values = {
            "id": cluster_id,
            "cluster_key": candidate.cluster_key,
            "issue_type": candidate.normalized_issue_type,
            "window_start": candidate.window_start,
            "policy_version": self._issue_cluster_policy.policy_version,
            "status": "candidate",
            "supporter_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            self._session.execute(
                postgresql_insert(IssueClusterRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["cluster_key"])
            )
        elif bind is not None and bind.dialect.name == "sqlite":
            self._session.execute(
                sqlite_insert(IssueClusterRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["cluster_key"])
            )
        else:
            self._session.add(IssueClusterRecord(**values))
            self._session.flush()

        cluster = self._session.scalar(
            select(IssueClusterRecord)
            .where(IssueClusterRecord.cluster_key == candidate.cluster_key)
            .with_for_update()
        )
        if cluster is None:
            raise RuntimeError("Issue cluster could not be created or loaded")

        self._session.add(
            IssueClusterMemberRecord(
                complaint_id=record.id,
                cluster_id=cluster.id,
                supporter_ref_hash=candidate.supporter_ref_hash,
                created_at=now,
            )
        )
        self._session.flush()
        supporter_count = self._session.scalar(
            select(
                func.count(func.distinct(IssueClusterMemberRecord.supporter_ref_hash))
            ).where(IssueClusterMemberRecord.cluster_id == cluster.id)
        ) or 0
        cluster.supporter_count = int(supporter_count)
        cluster.updated_at = now
        self._session.execute(
            update(ComplaintRecord)
            .where(ComplaintRecord.issue_cluster_id == cluster.id)
            .values(issue_cluster_supporter_count=cluster.supporter_count)
        )
        record.issue_cluster_id = cluster.id
        record.issue_cluster_supporter_count = cluster.supporter_count
        return cluster

    def list_complaints(
        self,
        *,
        status: str | None,
        execution_zone_state: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminComplaintRow]:
        query = select(ComplaintRecord)
        if status:
            query = query.where(ComplaintRecord.status == status)
        if execution_zone_state:
            query = query.where(
                ComplaintRecord.execution_zone_state == execution_zone_state
            )
        if after is not None:
            after_updated_at, after_id = after
            query = query.where(
                or_(
                    ComplaintRecord.updated_at < after_updated_at,
                    and_(
                        ComplaintRecord.updated_at == after_updated_at,
                        ComplaintRecord.id < after_id,
                    ),
                )
            )
        records = self._session.scalars(
            query.order_by(ComplaintRecord.updated_at.desc(), ComplaintRecord.id.desc()).limit(limit)
        )
        return [
            AdminComplaintRow(
                complaint_id=record.id,
                status=record.status,
                version=record.version,
                issue_type=record.issue_type,
                execution_zone_state=record.execution_zone_state,
                jurisdiction_code=record.jurisdiction_code,
                escalation_level=record.escalation_level,
                public_disclosure_eligible=record.public_disclosure_eligible,
                issue_cluster_id=record.issue_cluster_id,
                supporter_count=record.issue_cluster_supporter_count,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]

    def summarize_complaints(self) -> AdminOverviewData:
        summary = self._summary_data()
        return AdminOverviewData(
            total_complaints=summary.total_complaints,
            status_counts=summary.status_counts,
            execution_zone_counts=summary.execution_zone_counts,
            escalated_count=summary.escalated_count,
            mapping_in_progress_count=summary.mapping_in_progress_count,
            last_updated_at=summary.last_updated_at,
        )

    def summarize_public(self) -> PublicTransparencyData:
        """Return aggregate facts only; no citizen or case-level fields leave this boundary."""

        return self._summary_data()

    def _summary_data(self) -> PublicTransparencyData:
        status_rows = self._session.execute(
            select(ComplaintRecord.status, func.count(ComplaintRecord.id)).group_by(
                ComplaintRecord.status
            )
        ).all()
        zone_rows = self._session.execute(
            select(
                ComplaintRecord.execution_zone_state,
                func.count(ComplaintRecord.id),
            ).group_by(ComplaintRecord.execution_zone_state)
        ).all()
        status_counts = {str(status): int(count) for status, count in status_rows}
        zone_counts = {str(zone): int(count) for zone, count in zone_rows}
        return PublicTransparencyData(
            total_complaints=sum(status_counts.values()),
            status_counts=status_counts,
            execution_zone_counts=zone_counts,
            escalated_count=int(
                self._session.scalar(
                    select(func.count(ComplaintRecord.id)).where(
                        ComplaintRecord.escalation_level > 0
                    )
                )
                or 0
            ),
            mapping_in_progress_count=zone_counts.get("mapping_in_progress", 0),
            last_updated_at=self._session.scalar(
                select(func.max(ComplaintRecord.updated_at))
            ),
        )

    @staticmethod
    def _response(record: ComplaintRecord) -> ComplaintResponse:
        return ComplaintResponse(
            complaint_id=record.id,
            status=ComplaintStatus(record.status),
            version=record.version,
            execution_zone_state=record.execution_zone_state,
            escalation_level=record.escalation_level,
            created_at=record.created_at,
            issue_cluster_id=record.issue_cluster_id,
            supporter_count=record.issue_cluster_supporter_count,
        )

    @staticmethod
    def _tracking_response(record: ComplaintRecord) -> ComplaintTrackingResponse:
        return ComplaintTrackingResponse(
            complaint_id=record.id,
            status=ComplaintStatus(record.status),
            version=record.version,
            issue_type=record.issue_type,
            description=record.description,
            jurisdiction_code=record.jurisdiction_code,
            execution_zone_state=record.execution_zone_state,
            escalation_level=record.escalation_level,
            disclosure_mode=record.disclosure_mode,
            issue_cluster_id=record.issue_cluster_id,
            supporter_count=record.issue_cluster_supporter_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _disclosure_response(record: ComplaintRecord) -> DisclosureConsentResponse:
        if record.disclosure_consent_at is None or record.disclosure_policy_version is None:
            raise DisclosureConsentConflict("Disclosure consent has not been recorded")
        return DisclosureConsentResponse(
            complaint_id=record.id,
            disclosure_mode=record.disclosure_mode,  # type: ignore[arg-type]
            public_disclosure_eligible=record.public_disclosure_eligible,
            policy_version=record.disclosure_policy_version,
            consented_at=record.disclosure_consent_at,
        )
