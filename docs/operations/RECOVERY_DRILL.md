# PostgreSQL recovery drill

Status: local PostgreSQL drill completed 2026-08-10
Scope: greenfield PostgreSQL/PostGIS schema through Alembic head `0026_voice_draft_request_binding`

This runbook verifies that a PostgreSQL backup can be restored into an
isolated database and that the restored schema retains the migration state.
It is a release-readiness check, not a substitute for the production RDS
point-in-time recovery and restore exercise.

## Local drill

Use a disposable restore database name that is not used by the application.
The commands below assume the repository's local PostgreSQL service is exposed
on port `5435` and that the password is supplied through the local environment.

```bash
docker compose up -d postgres

DATABASE_URL='postgresql+psycopg://postgres:<local-password>@localhost:5435/aineta' \
  uv run --directory backend alembic upgrade head

docker compose exec -T postgres dropdb -U postgres --if-exists aineta_restore_check
docker compose exec -T postgres createdb -U postgres aineta_restore_check

docker compose exec -T postgres pg_dump -U postgres -d aineta -Fc \
  | docker compose exec -T postgres pg_restore -U postgres --no-owner \
      --dbname=aineta_restore_check

docker compose exec -T postgres psql -U postgres -d aineta -Atc \
  'SELECT version_num FROM alembic_version'
docker compose exec -T postgres psql -U postgres -d aineta_restore_check -Atc \
  'SELECT version_num FROM alembic_version'
docker compose exec -T postgres psql -U postgres -d aineta -Atc \
  "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
docker compose exec -T postgres psql -U postgres -d aineta_restore_check -Atc \
  "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"

docker compose exec -T postgres dropdb -U postgres aineta_restore_check
docker compose stop postgres
```

The drill passed when both migration queries returned `0026_voice_draft_request_binding` and
both table-count queries match. The recorded local result was:

```text
restore_check version=0026_voice_draft_request_binding public_tables=24
```

The restored database also retained the append-only
`citizen_resolution_responses` table and its
`citizen_resolution_responses_append_only` trigger.

## Production recovery procedure

Before production launch, platform engineering must:

1. Enable encrypted RDS automated backups and point-in-time recovery with the
   approved retention period.
2. Run the release migration as an explicit job, record the resulting Alembic
   head, and do not run schema creation from API startup.
3. Restore a recent snapshot or point-in-time copy into an isolated account or
   subnet using a separate database name and credentials.
4. Verify the migration head, complaint/event/outbox foreign keys, append-only
   triggers, indexes, and representative redacted projections.
5. Rebuild any derived read models from their authoritative events before
   directing traffic to the restored environment. The current baseline has no
   public analytics read model to rebuild; this step becomes mandatory when
   transparency projections are introduced.
6. Record measured RPO/RTO, operator, restore timestamp, backup identifier, and
   validation queries in the incident/recovery record.

Never restore a production backup into a developer database or expose raw
citizen data while validating the restore. Use managed secret access, private
network paths, least-privilege restore credentials, and the approved retention
and deletion policy.

## Outstanding action

**Production recovery prerequisite — Platform/security:** provide the production RDS backup,
restore, cross-account access, encryption-key, and RPO/RTO policies; run this
drill against staging before enabling citizen traffic. Load and failover tests
also require a deployed API/database environment and are not represented by
this local schema-only drill.
