from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.ai.fakes import FakeAgentOrchestrator
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base, EvidenceAssetRecord, VoiceDraftRequestRecord
from backend.app.infrastructure.speech import FixtureSpeechToText


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed_verified_audio(engine, citizen_id: str):
    audio_id = uuid4()
    now = datetime.now(timezone.utc)
    with sessionmaker(engine)() as session:
        session.add(
            EvidenceAssetRecord(
                id=audio_id,
                citizen_id=citizen_id,
                creation_idempotency_key=f"audio:{audio_id}",
                creation_request_fingerprint="a" * 64,
                asset_type="audio",
                content_type="audio/mp4",
                byte_size=512,
                client_sha256="b" * 64,
                object_key=f"evidence/{citizen_id}/{audio_id}",
                status="verified",
                capture_source="native_microphone",
                capture_attestation_hash="c" * 64,
                device_captured_at=now,
                server_received_at=now,
                uploaded_at=now,
                verified_at=now,
                verification_signals={"reason_codes": []},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return audio_id


def test_voice_draft_transcribes_owned_verified_audio_and_extracts_structured_draft():
    engine = _engine()
    Base.metadata.create_all(engine)
    citizen_id = "digilocker:voice-citizen"
    audio_id = _seed_verified_audio(engine, citizen_id)
    speech = FixtureSpeechToText(
        text="Gali mein bada pothole hai",
        language="hi-IN",
    )
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            citizen_id, identity_verified=True
        ),
        ai_orchestrator=FakeAgentOrchestrator(),
        speech_to_text=speech,
    )

    client = TestClient(app)
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "voice-draft-1",
    }
    response = client.post(
        "/api/v1/complaints/voice-draft",
        headers=headers,
        json={"audio_asset_id": str(audio_id), "language": "hi-IN"},
    )
    retry = client.post(
        "/api/v1/complaints/voice-draft",
        headers=headers,
        json={"audio_asset_id": str(audio_id), "language": "hi-IN"},
    )

    assert response.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == response.json()
    assert response.json() == {
        "draft": {
            "issue_type": "road",
            "description": "Gali mein bada pothole hai",
            "language": "hi-IN",
            "missing_fields": [],
            "confidence": 0.8,
        },
        "transcription_language": "hi-IN",
        "transcription_confidence": 0.96,
        "transcription_provider": "fixture-stt-v1",
        "transcription_model": "fixture-hindi-en-v1",
    }
    # The idempotency binding prevents key reuse with a different request, but
    # the transcript-derived read-back is intentionally not persisted. A retry
    # re-runs the bounded, non-authoritative voice-draft flow.
    assert speech.calls == 2
    with Session(engine) as session:
        stored = session.query(VoiceDraftRequestRecord).one()
        assert stored.request_fingerprint
        assert stored.audio_asset_id == audio_id
        assert "Gali mein bada pothole hai" not in stored.__dict__


def test_voice_draft_rejects_cross_citizen_audio_and_fails_closed_without_stt():
    engine = _engine()
    Base.metadata.create_all(engine)
    audio_id = _seed_verified_audio(engine, "digilocker:owner")

    other_app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "digilocker:other", identity_verified=True
        ),
        ai_orchestrator=FakeAgentOrchestrator(),
        speech_to_text=FixtureSpeechToText(text="Paani jama hai"),
    )
    other_response = TestClient(other_app).post(
        "/api/v1/complaints/voice-draft",
        headers={"Idempotency-Key": "voice-draft-other"},
        json={"audio_asset_id": str(audio_id), "language": "hi-IN"},
    )
    assert other_response.status_code == 422

    unconfigured_app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "digilocker:owner", identity_verified=True
        ),
        ai_orchestrator=FakeAgentOrchestrator(),
    )
    unavailable_response = TestClient(unconfigured_app).post(
        "/api/v1/complaints/voice-draft",
        headers={"Idempotency-Key": "voice-draft-unconfigured"},
        json={"audio_asset_id": str(audio_id), "language": "hi-IN"},
    )
    assert unavailable_response.status_code == 503
