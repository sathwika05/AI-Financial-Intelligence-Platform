// Inputs to the stack. Set them in terraform.tfvars, on the command line
// with -var, or via TF_VAR_<name> environment variables.
//
// A variable with no `default` is required, and Terraform will prompt for
// it rather than guess — which is what you want for anything that costs
// money or cannot be changed later.

variable "project" {
  description = "Name prefix for every resource, so the stack is identifiable on a shared account."
  type        = string
  default     = "fip"

  // Validation runs during `plan`, so a bad value fails in seconds rather
  // than halfway through creating resources.
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project))
    error_message = "project must be lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment, used in names and tags."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

// ---------------------------------------------------------------------------
// Networking
// ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR for the VPC. /16 leaves room to add subnets later."
  type        = string
  default     = "10.0.0.0/16"
}

variable "use_nat_gateway" {
  description = <<-EOT
    Whether Fargate runs in private subnets behind a NAT Gateway.

    false puts tasks in public subnets with a public IP, reachable only
    through their security group. That is weaker isolation, and it is the
    default because a NAT Gateway costs roughly $32/month whether or not a
    byte flows through it — on a stack meant to be destroyed between
    sessions, it is usually the largest line on the bill.

    Set true for anything long-lived or handling real data.
  EOT
  type        = bool
  default     = false
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance size. db.t4g.micro is the cheapest that runs pgvector comfortably."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "findb"
}

variable "db_username" {
  description = "Master username."
  type        = string
  default     = "finuser"
}

variable "db_password" {
  description = "Master password. No default on purpose — Terraform prompts rather than shipping a known value."
  type        = string
  // sensitive hides it from plan and apply output. It is still stored in
  // plain text in the state file, which is the main reason to move state
  // to an encrypted S3 backend before this stack matters.
  sensitive = true
}

variable "db_deletion_protection" {
  description = "Blocks `terraform destroy` from deleting the database. Leave false while you are tearing the stack down regularly."
  type        = bool
  default     = false
}

// ---------------------------------------------------------------------------
// Application
// ---------------------------------------------------------------------------

variable "container_image" {
  description = "Image for the API and the indexing worker, e.g. an ECR URI or a public tag."
  type        = string
  default     = ""
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task. 256 = 0.25 vCPU."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Fargate memory (MiB). Must be a valid pairing with cpu."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Logs are kept forever by default in AWS, and that is a slow, quiet cost."
  type        = number
  default     = 7
}
