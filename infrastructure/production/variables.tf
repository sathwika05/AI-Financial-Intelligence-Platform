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
  description = <<-EOT
    Fargate CPU units for the API task. 256 = 0.25 vCPU.

    The API accepts uploads and queues work; it does not hold a parse
    open. Parsing still happens on this task, in a background task, so
    this is not the 512 it was before Docling -- but it is not the 2048
    the worker needs either, because nothing here is waiting on it.
  EOT

  type    = number
  default = 1024
}

variable "api_memory" {
  description = <<-EOT
    Fargate memory (MiB). Must be a valid pairing with cpu; 2048 CPU
    permits 4096 to 16384.

    A parse held 2.4GiB resident, and background work on this task can
    still hit that. 2048 would be killed; 3072 leaves room without paying
    for the worker's headroom twice.
  EOT

  type    = number
  default = 3072
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Logs are kept forever by default in AWS, and that is a slow, quiet cost."
  type        = number
  default     = 7
}

variable "sec_user_agent" {
  description = <<-EOT
    Identifies this deployment to SEC EDGAR, which rejects anonymous
    requests. Format is a name and a contact address, for example
    "Example Research team@example.com". Leave empty to disable the
    EDGAR collector entirely.
  EOT

  type    = string
  default = ""
}

variable "langsmith_project_url" {
  description = <<-EOT
    Deep link to this deployment's LangSmith project, copied from the
    LangSmith UI. There is no stable public URL that can be built from the
    project name alone, so it is pasted rather than derived. Leave empty
    to hide the link.
  EOT

  type    = string
  default = ""
}

variable "worker_cpu" {
  description = <<-EOT
    Fargate CPU units for the ingestion worker.

    This is the task that meets a scanned filing: it parses whatever
    lands in the bucket, and parsing is entirely CPU-bound because
    Docling runs a layout model over every rendered page. One 10-K
    measured 6.6 cores locally. Nothing is waiting on a connection here,
    so slow is survivable -- but too small is not, and an OOM kill reads
    as a crash rather than a limit.
  EOT

  type    = number
  default = 2048
}

variable "worker_memory" {
  description = <<-EOT
    Fargate memory (MiB) for the worker. 2048 CPU permits 4096 to 16384.

    A parse held 2.4GiB resident, and the worker has no other work to
    interleave, so this is sized to that with room rather than to an
    average.
  EOT

  type    = number
  default = 4096
}
