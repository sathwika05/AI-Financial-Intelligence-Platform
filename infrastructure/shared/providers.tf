// The permanent stack.
//
// Everything here outlives a demo. `terraform destroy` in production/
// tears down the VPC, database, load balancer and tasks -- but it has no
// idea this state exists, so the certificate and the image registry
// survive to be reused by the next spin-up.
//
// State is local, as in production/. One person, one machine.
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Lifecycle = "permanent"
    }
  }
}
