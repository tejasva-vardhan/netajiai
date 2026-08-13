from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.application.routing import RoutingDecision
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base, EvidenceAssetRecord, LocationSampleRecord
from backend.app.infrastructure.routing import SyntheticMpRoutingResolver


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("digilocker:routing-citizen", identity_verified=True)


def _seed_asset(
    session: Session, *, latitude: float, longitude: float, accuracy: float
) -> EvidenceAssetRecord:
    now = datetime.now(timezone.utc)
    location = LocationSampleRecord(
        citizen_id=_principal().subject_ref,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy,
        source="device_gps",
        captured_at=now,
        server_received_at=now,
    )
    session.add(location)
    session.flush()
    asset = EvidenceAssetRecord(
        id=uuid4(),
        citizen_id=_principal().subject_ref,
        creation_idempotency_key=str(uuid4()),
        asset_type="photo",
        content_type="image/jpeg",
        byte_size=100,
        client_sha256="a" * 64,
        object_key=f"evidence/{uuid4()}",
        status="verified",
        capture_source="native_camera",
        capture_attestation_hash="b" * 64,
        device_captured_at=now,
        server_received_at=now,
        location_sample_id=location.id,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    session.commit()
    return asset


def test_synthetic_routing_activates_only_inside_bounded_fixture():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        inside = _seed_asset(session, latitude=23.2599, longitude=77.4126, accuracy=30)
        outside = _seed_asset(session, latitude=28.6139, longitude=77.2090, accuracy=30)
        resolver = SyntheticMpRoutingResolver(session)

        active = resolver.resolve(_principal(), (inside.id,))
        mapped = resolver.resolve(_principal(), (outside.id,))

    assert active == RoutingDecision(
        state="active",
        jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
        snapshot_ref="synthetic-mp-routing-v1",
        reason_code="synthetic_zone_match",
    )
    assert mapped.state == "mapping_in_progress"
    assert mapped.reason_code == "jurisdiction_not_mapped"


def test_synthetic_routing_does_not_activate_low_accuracy_location():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        asset = _seed_asset(session, latitude=23.2599, longitude=77.4126, accuracy=251)
        decision = SyntheticMpRoutingResolver(session).resolve(_principal(), (asset.id,))

    assert decision.state == "mapping_in_progress"
    assert decision.reason_code == "location_accuracy_too_low"
