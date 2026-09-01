// Outputs are the stack's return values: printed after apply, and readable
// later with `terraform output`. They are how the application learns the
// queue URL and bucket names that Terraform generated.
//
// `terraform output -json` is the practical form — it feeds a script that
// writes the .env for a deployment.

output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnets, for the load balancer and for tasks when no NAT gateway exists."
  // [*] is a splat: collects one attribute from every instance a count
  // created, producing a list.
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnets, for RDS and for tasks when a NAT gateway exists."
  value       = aws_subnet.private[*].id
}

output "ingestion_queue_url" {
  description = "SQS URL the indexing worker polls."
  value       = aws_sqs_queue.ingestion.id
}

output "ingestion_dlq_url" {
  description = "Dead-letter queue. Anything here failed three times and needs looking at."
  value       = aws_sqs_queue.ingestion_dlq.id
}

output "raw_bucket" {
  description = "Bucket documents are uploaded to."
  value       = aws_s3_bucket.docs["raw"].id
}

output "processed_bucket" {
  description = "Bucket for processed output and backups."
  value       = aws_s3_bucket.docs["processed"].id
}

output "nat_gateway_enabled" {
  description = "Whether the expensive path is on. Worth seeing on every apply."
  value       = var.use_nat_gateway
}

output "account_id" {
  description = "Account being deployed into — a cheap check that it is the one you meant."
  value       = data.aws_caller_identity.current.account_id
}

output "api_url" {
  description = "Public URL of the API."
  value       = "http://${aws_lb.main.dns_name}"
}

output "db_endpoint" {
  description = "RDS endpoint. Private, so reachable only from inside the VPC."
  value       = aws_db_instance.main.endpoint
}

output "ecs_cluster" {
  description = "Cluster name, for `aws ecs` commands and log tailing."
  value       = aws_ecs_cluster.main.name
}

output "log_groups" {
  description = "CloudWatch log groups for the API and the indexing worker."
  value = {
    api    = aws_cloudwatch_log_group.api.name
    worker = aws_cloudwatch_log_group.worker.name
  }
}

// ecr_repository_url now lives in the shared stack, which owns the
// registry so a teardown here cannot delete the images.
