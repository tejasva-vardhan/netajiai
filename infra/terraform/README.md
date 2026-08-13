# AI Neta AWS launch profile

This directory contains a parameterized Terraform launch profile for the
limited-budget AWS baseline in the redesign plan:

- ECS/Fargate task definitions and services for the API, outbox, Kafka event,
  Temporal, and evidence-cleanup runtimes;
- immutable image references, non-root/read-only containers, private subnets,
  CloudWatch logs, health checks, deployment circuit breakers, and no ECS Exec;
- private, versioned, KMS-encrypted evidence storage with public access blocked
  and incomplete multipart uploads aborted after one day;
- a pre-existing managed Kafka cluster supplied through runtime configuration;
  this profile does not create a broker; and
- separate runtime IAM roles with narrowly scoped S3, KMS, and secret-read
  permissions.

The module defaults to `enable_launch_profile = false`. It does not create a
cluster, VPC, ALB, database, KMS key, or secret values implicitly. This keeps
local validation free of AWS mutations and makes network, residency, budget,
secret ownership, and provider approvals explicit launch gates.

The task definition uses the immutable image digest and the container’s
non-root UID 999. Fargate task CPU/memory, `awslogs`, and read-only filesystem
settings follow the AWS ECS task-definition/security guidance. See the [ECS
task definition documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html),
[Fargate logging guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html),
[ECS security guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-tasks-containers.html),
and [S3 public-access guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html).

Each task receives a runtime-specific `SERVICE_NAME` so API, outbox, event,
Temporal, and evidence-cleanup telemetry remain distinguishable.

## Validate without creating resources

```bash
cd infra/terraform
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
AWS_ACCESS_KEY_ID=disabled AWS_SECRET_ACCESS_KEY=disabled \
AWS_SESSION_TOKEN=disabled AWS_EC2_METADATA_DISABLED=true \
terraform plan -var-file=terraform.tfvars.example
```

The example plan is intentionally empty because `enable_launch_profile` is
false. The dummy credential values above are used only so the AWS provider can
evaluate an empty plan; they do not grant access and must never be used when
the profile is enabled. Before enabling it, platform/security/finance owners must provide the
real private network, immutable ECR digest, KMS key, ALB target group, bucket
name, scoped Secret Manager ARNs, approved OTLP endpoint, and budget alarms.
The API task also requires `COMPOSITION_MODULE` in its common environment.
That deployment-owned Python module must expose `build_adapters(settings)` and
return `backend.app.runtime.RuntimeAdapters`.
Never put secret values in `.tfvars`, state, or this repository. Use a remote
encrypted state backend with locking after the account/bootstrap decision is
approved.

When enabling the profile, provide `KAFKA_BOOTSTRAP_SERVERS`,
`KAFKA_TOPIC`, and `KAFKA_CONSUMER_GROUP` in `common_environment`, plus the
TLS/SASL credentials required by the selected managed Kafka service through the
runtime-scoped secret manager. Kafka retention and dead-letter handling are
platform-owned settings on that cluster; this module does not provision the
managed broker itself.

The profile does not include live operations hierarchy/contact data or telecom
providers. Those remain deferred exactly as recorded in the redesign plan.
