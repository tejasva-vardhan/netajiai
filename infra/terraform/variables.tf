variable "enable_launch_profile" {
  description = "Enable creation of paid AWS resources. Keep false until external launch gates are approved."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "AWS region for the launch profile. The plan currently targets an India region."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Lowercase project identifier used in resource names."
  type        = string
  default     = "ai-neta"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production for this launch profile."
  }
}

variable "cluster_arn" {
  description = "Existing ECS cluster ARN. The profile does not create a cluster implicitly."
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Private subnet IDs for Fargate tasks. Supply at least two subnets in different AZs."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security groups for Fargate tasks. Ingress must be restricted to the approved load balancer/worker paths."
  type        = list(string)
  default     = []
}

variable "api_target_group_arn" {
  description = "Existing ALB target group ARN for the API. The API service is not internet-facing by itself."
  type        = string
  default     = ""
}

variable "image_digest" {
  description = "Immutable backend image reference, including an @sha256 digest. Tags such as latest are rejected."
  type        = string
  default     = ""
}

variable "evidence_bucket_name" {
  description = "Private S3 bucket name for evidence objects. The bucket is protected against accidental destruction."
  type        = string
  default     = ""
}

variable "kms_key_arn" {
  description = "Existing customer-managed KMS key ARN for S3/log encryption and task access."
  type        = string
  default     = ""
}

variable "runtime_secret_arns" {
  description = "Secret Manager ARNs grouped by runtime and exposed only to that runtime. Keys are environment variable names."
  type        = map(map(string))
  default     = {}
  sensitive   = true
}

variable "common_environment" {
  description = "Non-secret application environment overrides. System-owned queue/storage/runtime values take precedence."
  type        = map(string)
  default     = {}
}

variable "retention_in_days" {
  description = "CloudWatch log retention. Keep this bounded for the limited-budget launch profile."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.retention_in_days)
    error_message = "retention_in_days must be an AWS-supported bounded retention value."
  }
}

variable "common_cpu" {
  description = "Fargate CPU units for API and workers unless overridden in the runtime map."
  type        = number
  default     = 512
}

variable "common_memory" {
  description = "Fargate memory in MiB for API and workers unless overridden in the runtime map."
  type        = number
  default     = 1024
}

check "launch_inputs" {
  assert {
    condition = !var.enable_launch_profile || (
      length(trimspace(var.cluster_arn)) > 0 &&
      length(var.subnet_ids) >= 2 &&
      length(var.security_group_ids) >= 1 &&
      length(trimspace(var.api_target_group_arn)) > 0 &&
      can(regex("@sha256:[0-9a-f]{64}$", var.image_digest)) &&
      length(trimspace(var.evidence_bucket_name)) > 0 &&
      can(regex("^arn:[^:]+:kms:[^:]+:[^:]+:key/", var.kms_key_arn)) &&
      length(var.runtime_secret_arns) > 0 &&
      length(trimspace(lookup(var.common_environment, "COMPOSITION_MODULE", ""))) > 0 &&
      length(trimspace(lookup(var.common_environment, "KAFKA_BOOTSTRAP_SERVERS", ""))) > 0
    )

    error_message = "Enabling the launch profile requires an existing ECS cluster, private network inputs, an ALB target group, an immutable image digest, an evidence bucket name, a customer-managed KMS key, runtime-scoped secret ARNs, COMPOSITION_MODULE, and KAFKA_BOOTSTRAP_SERVERS in common_environment."
  }
}

check "production_secret_scoping" {
  assert {
    condition = !var.enable_launch_profile || var.environment != "production" || (
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "DATABASE_URL") &&
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "OIDC_ISSUER") &&
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "DIGILOCKER_CLIENT_SECRET") &&
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "IDENTITY_STATE_ENCRYPTION_KEY") &&
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "PUBLIC_TRACKING_TOKEN_SECRET") &&
      contains(keys(lookup(var.runtime_secret_arns, "api", {})), "TEMPORAL_API_KEY")
    )

    error_message = "Production API secrets must include the database, OIDC, DigiLocker, identity-state, public-tracking, and Temporal credentials under the api runtime scope."
  }
}
