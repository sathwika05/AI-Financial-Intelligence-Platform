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

variable "openai_api_key" {
  description = <<-EOT
    Embeddings only. Chat models take their key from the llm_providers
    table, encrypted, changeable from the admin screen -- but embeddings
    cannot work that way: the client is built when the module loads,
    before there is a database to ask.

    Fixed to one provider on purpose. Vectors from different embedding
    models are not comparable, so changing this invalidates every chunk
    already stored. Without it nothing indexes and no question is
    answered.
  EOT

  type      = string
  sensitive = true
}

variable "jwt_secret" {
  description = <<-EOT
    Signs session tokens. Without it the API starts and every login
    fails, which reads as a broken deployment rather than a missing
    setting.

    Any long random string: `openssl rand -hex 32`. Changing it signs out
    everyone, which is the correct behaviour and worth knowing before you
    rotate it.
  EOT

  type      = string
  sensitive = true
}

variable "alpha_vantage_api_key" {
  description = <<-EOT
    News for the seeding script, which the Rebuild the corpus button
    runs. Nothing else in the running application uses it.

    Empty is survivable: only that button fails. It is here because that
    button truncates four tables before it fetches, so discovering the
    key is missing afterwards is an expensive way to find out.
  EOT

  type      = string
  sensitive = true
  default   = ""
}

variable "finnhub_api_key" {
  description = <<-EOT
    The seeding script's second news source, read straight from the
    environment rather than through config.py. Same reasoning as
    alpha_vantage_api_key.
  EOT

  type      = string
  sensitive = true
  default   = ""
}

variable "langsmith_api_key" {
  description = <<-EOT
    Traces every graph run to LangSmith. Without it the deployment runs
    blind: LANGSMITH_PROJECT_URL still puts a link in the admin panel,
    but it opens a project nothing reports to.

    Required whenever langsmith_tracing is true, and checked at plan
    time rather than left to the task. setup_langsmith() runs at import
    in main.py and raises when tracing is on with no key, so the wrong
    combination does not degrade tracing -- it crash-loops the service.
  EOT

  type      = string
  sensitive = true
  default   = ""
}

variable "langsmith_tracing" {
  description = <<-EOT
    Whether to send traces at all. On by default: an unobservable
    production deployment is the thing this project is least able to
    afford, and turning it off is the decision that should be typed out.

    Traces are billed per run by LangSmith, so this is the lever to pull
    if that matters more than the visibility.
  EOT

  type    = bool
  default = true
}

variable "langchain_project" {
  description = <<-EOT
    Which LangSmith project the traces land in. Must name the same
    project as langsmith_project_url, or the admin panel links to one
    place while the runs arrive in another.
  EOT

  type    = string
  default = "ai-financial-intelligence-platform"
}

variable "llm_key_encryption_secret" {
  description = <<-EOT
    Encrypts provider API keys stored in the llm_providers table.

    Must be a urlsafe base64 32-byte Fernet key:
    `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

    Changing it makes every key already stored unreadable -- the rows
    survive, the values cannot be decrypted, and each provider has to be
    re-entered. Worth knowing before rotating it.
  EOT

  type      = string
  sensitive = true
}
