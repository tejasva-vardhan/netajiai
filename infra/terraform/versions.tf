terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.55.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # The disabled validation profile must be runnable in a clean checkout with
  # no AWS credentials. These skips are false as soon as resources are enabled.
  skip_credentials_validation = !var.enable_launch_profile
  skip_requesting_account_id  = !var.enable_launch_profile
  skip_metadata_api_check     = !var.enable_launch_profile

  default_tags {
    tags = local.tags
  }
}
