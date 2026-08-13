output "task_definition_arns" {
  description = "ECS task definition ARNs, keyed by runtime."
  value       = { for name, task in aws_ecs_task_definition.runtime : name => task.arn }
}

output "service_names" {
  description = "ECS service names, keyed by runtime."
  value       = { for name, service in aws_ecs_service.runtime : name => service.name }
}

output "evidence_bucket_name" {
  description = "Private evidence bucket name."
  value       = try(aws_s3_bucket.evidence[0].bucket, null)
}

output "kafka_bootstrap_servers" {
  description = "Kafka bootstrap servers supplied by the deployment environment."
  value       = lookup(var.common_environment, "KAFKA_BOOTSTRAP_SERVERS", null)
}

output "log_group_names" {
  description = "CloudWatch log groups, keyed by runtime."
  value       = { for name, group in aws_cloudwatch_log_group.runtime : name => group.name }
}
