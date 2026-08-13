"""Synthetic routing adapter used until live operations data is approved."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.routing import RoutingDecision
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import EvidenceAssetRecord, LocationSampleRecord


class SyntheticMpRoutingResolver:
    """Resolve only a bounded synthetic MP fixture; never live contacts.

    The active rectangle is a test execution zone around Bhopal. All other
    points, missing points, and low-confidence captures remain in
    ``mapping_in_progress``. This adapter is for controlled development and
    staging demonstrations until verified operations data is supplied.
    """

    _JURISDICTION = "IN-MP-SYNTHETIC-BHOPAL"
    _SNAPSHOT = "synthetic-mp-routing-v1"
    _MIN_ACCURACY_METERS = 250.0
    _LATITUDE_RANGE = (23.10, 23.40)
    _LONGITUDE_RANGE = (77.20, 77.60)

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(
        self,
        principal: AuthenticatedPrincipal,
        evidence_asset_ids: tuple[UUID, ...],
    ) -> RoutingDecision:
        if not evidence_asset_ids:
            return RoutingDecision.mapping_in_progress(reason_code="no_evidence_location")

        rows = list(
            self._session.execute(
                select(LocationSampleRecord)
                .join(
                    EvidenceAssetRecord,
                    EvidenceAssetRecord.location_sample_id == LocationSampleRecord.id,
                )
                .where(
                    EvidenceAssetRecord.id.in_(evidence_asset_ids),
                    EvidenceAssetRecord.citizen_id == principal.subject_ref,
                )
            ).scalars()
        )
        if not rows:
            return RoutingDecision.mapping_in_progress(reason_code="no_evidence_location")

        if any(float(row.accuracy_m) > self._MIN_ACCURACY_METERS for row in rows):
            return RoutingDecision.mapping_in_progress(reason_code="location_accuracy_too_low")

        if all(
            self._LATITUDE_RANGE[0] <= float(row.latitude) <= self._LATITUDE_RANGE[1]
            and self._LONGITUDE_RANGE[0] <= float(row.longitude) <= self._LONGITUDE_RANGE[1]
            for row in rows
        ):
            return RoutingDecision(
                state="active",
                jurisdiction_code=self._JURISDICTION,
                snapshot_ref=self._SNAPSHOT,
                reason_code="synthetic_zone_match",
            )
        return RoutingDecision.mapping_in_progress(reason_code="jurisdiction_not_mapped")
