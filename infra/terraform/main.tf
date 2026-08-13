locals {
  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    DataClass   = "civic-sensitive"
  }

  runtimes = {
    api = {
      command        = ["uvicorn", "backend.app.runtime:app", "--host", "0.0.0.0", "--port", "8000"]
      cpu            = var.common_cpu
      memory         = var.common_memory
      desired_count  = 1
      container_port = 8000
    }
    outbox = {
      command        = ["aineta-outbox-worker"]
      cpu            = var.common_cpu
      memory         = var.common_memory
      desired_count  = 1
      container_port = null
    }
    events = {
      command        = ["aineta-event-worker"]
      cpu            = var.common_cpu
      memory         = var.common_memory
      desired_count  = 1
      container_port = null
    }
    temporal = {
      command        = ["aineta-temporal-worker"]
      cpu            = var.common_cpu
      memory         = var.common_memory
      desired_count  = 1
      container_port = null
    }
    evidence_cleanup = {
      command        = ["aineta-evidence-cleanup-worker"]
      cpu            = var.common_cpu
      memory         = var.common_memory
      desired_count  = 1
      container_port = null
    }
  }

  base_environment = {
    APP_ENV                     = var.environment
    OBJECT_STORAGE_PROVIDER     = "s3"
    OBJECT_STORAGE_BUCKET       = var.evidence_bucket_name
    OBJECT_STORAGE_REGION       = var.aws_region
    KAFKA_BOOTSTRAP_SERVERS     = lookup(var.common_environment, "KAFKA_BOOTSTRAP_SERVERS", "")
    KAFKA_TOPIC                 = lookup(var.common_environment, "KAFKA_TOPIC", "complaint.lifecycle.v1")
    KAFKA_CONSUMER_GROUP        = lookup(var.common_environment, "KAFKA_CONSUMER_GROUP", "aineta-workflows")
    OTEL_ENABLED                = "true"
    OTEL_EXPORTER               = "otlp_http"
    OTEL_EXPORTER_OTLP_ENDPOINT = lookup(var.common_environment, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
    OTEL_SAMPLE_RATIO           = lookup(var.common_environment, "OTEL_SAMPLE_RATIO", "0.25")
  }

  environment = {
    for runtime_name, _runtime in local.runtimes : runtime_name => merge(
      var.common_environment,
      local.base_environment,
      { SERVICE_NAME = "${var.project_name}-${runtime_name}" },
    )
  }
  secret_arns = distinct(flatten([
    for runtime_secrets in values(var.runtime_secret_arns) : values(runtime_secrets)
  ]))
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect = "Allow"

    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  name              = "/ecs/${var.project_name}/${var.environment}/${each.key}"
  retention_in_days = var.retention_in_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_s3_bucket" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket        = var.evidence_bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket                  = aws_s3_bucket.evidence[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket = aws_s3_bucket.evidence[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket = aws_s3_bucket.evidence[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket = aws_s3_bucket.evidence[0].id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  count = var.enable_launch_profile ? 1 : 0

  bucket = aws_s3_bucket.evidence[0].id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "execution" {
  count = var.enable_launch_profile ? 1 : 0

  statement {
    sid       = "PullImageAndWriteLogs"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = length(local.secret_arns) > 0 ? [1] : []

    content {
      sid       = "ReadRuntimeSecrets"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secret_arns
    }
  }

  dynamic "statement" {
    for_each = var.kms_key_arn != "" ? [1] : []

    content {
      sid       = "DecryptRuntimeSecretsAndLogs"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role" "execution" {
  count = var.enable_launch_profile ? 1 : 0

  name               = "${var.project_name}-${var.environment}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy" "execution" {
  count = var.enable_launch_profile ? 1 : 0

  name   = "${var.project_name}-${var.environment}-ecs-execution"
  role   = aws_iam_role.execution[0].id
  policy = data.aws_iam_policy_document.execution[0].json
}

data "aws_iam_policy_document" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  dynamic "statement" {
    for_each = contains(["api", "evidence_cleanup"], each.key) ? [1] : []

    content {
      sid       = "ListEvidenceBucket"
      effect    = "Allow"
      actions   = ["s3:ListBucket", "s3:ListBucketMultipartUploads"]
      resources = [aws_s3_bucket.evidence[0].arn]
    }
  }

  dynamic "statement" {
    for_each = contains(["api", "evidence_cleanup"], each.key) ? [1] : []

    content {
      sid    = "EvidenceObjectAccess"
      effect = "Allow"
      actions = [
        "s3:AbortMultipartUpload",
        "s3:GetObject",
        "s3:ListMultipartUploadParts",
        "s3:PutObject",
      ]
      resources = ["${aws_s3_bucket.evidence[0].arn}/evidence/*"]
    }
  }

  dynamic "statement" {
    for_each = contains(["api", "evidence_cleanup"], each.key) ? [1] : []

    content {
      sid       = "UseEncryptedManagedResources"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  name               = "${var.project_name}-${var.environment}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  name   = "${var.project_name}-${var.environment}-${each.key}"
  role   = aws_iam_role.runtime[each.key].id
  policy = data.aws_iam_policy_document.runtime[each.key].json
}

resource "aws_ecs_task_definition" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  family                   = "${var.project_name}-${var.environment}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution[0].arn
  task_role_arn            = aws_iam_role.runtime[each.key].arn

  container_definitions = jsonencode([
    merge(
      {
        name                   = each.key
        image                  = var.image_digest
        essential              = true
        command                = each.value.command
        user                   = "999:999"
        readonlyRootFilesystem = true
        environment            = [for name, value in local.environment[each.key] : { name = name, value = value }]
        secrets                = [for name, arn in lookup(var.runtime_secret_arns, each.key, {}) : { name = name, valueFrom = arn }]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            "awslogs-group"         = aws_cloudwatch_log_group.runtime[each.key].name
            "awslogs-region"        = var.aws_region
            "awslogs-stream-prefix" = each.key
          }
        }
      },
      each.value.container_port == null ? {} : {
        portMappings = [{
          containerPort = each.value.container_port
          hostPort      = each.value.container_port
          protocol      = "tcp"
        }]
      },
      each.key == "api" ? {
        healthCheck = {
          command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\""]
          interval    = 30
          timeout     = 5
          retries     = 3
          startPeriod = 20
        }
      } : {}
    )
  ])

  depends_on = [aws_iam_role_policy.execution, aws_iam_role_policy.runtime]
}

resource "aws_ecs_service" "runtime" {
  for_each = var.enable_launch_profile ? local.runtimes : {}

  name                               = "${var.project_name}-${var.environment}-${each.key}"
  cluster                            = var.cluster_arn
  task_definition                    = aws_ecs_task_definition.runtime[each.key].arn
  launch_type                        = "FARGATE"
  desired_count                      = each.value.desired_count
  platform_version                   = "LATEST"
  enable_ecs_managed_tags            = true
  propagate_tags                     = "SERVICE"
  enable_execute_command             = false
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = each.key == "api" ? 60 : null

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.key == "api" && var.api_target_group_arn != "" ? [1] : []

    content {
      target_group_arn = var.api_target_group_arn
      container_name   = "api"
      container_port   = 8000
    }
  }

  depends_on = [aws_iam_role_policy.execution, aws_iam_role_policy.runtime]
}
