// The `terraform` block configures Terraform itself rather than any cloud
// resource. It runs before anything else and cannot reference variables,
// which is why the region is set on the provider below instead of here.
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      // Pessimistic constraint: allows 5.x patch and minor updates, refuses
      // 6.0. Provider majors rename and remove arguments, so an unpinned
      // provider can break a stack that has not otherwise changed.
      version = "~> 5.0"
    }
  }

  // State records what Terraform believes exists, and is how `destroy`
  // knows what to remove. Kept local here because this stack is created
  // and destroyed by one person from one machine.
  //
  // Move to S3 with DynamoDB locking the moment a second person or CI can
  // run apply — two concurrent applies against local state corrupt it, and
  // the resources are then orphaned: still billing, no longer tracked.
  //
  // backend "s3" {
  //   bucket         = "fip-terraform-state"
  //   key            = "app/terraform.tfstate"
  //   region         = "us-east-1"
  //   dynamodb_table = "fip-terraform-locks"
  //   encrypt        = true
  // }
}

// A `provider` block configures how Terraform talks to a cloud. Credentials
// are deliberately absent: the AWS provider reads them from the environment
// or ~/.aws/credentials, so keys never enter a file that gets committed.
provider "aws" {
  region = var.region

  // Applied to every resource this provider creates, on top of each
  // resource's own tags. Worth having before the first apply — untagged
  // resources are hard to attribute on a bill and easy to leave running.
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      // Anything without this tag was made by hand and will survive
      // `terraform destroy`, which is exactly how surprise bills happen.
    }
  }
}

// A `data` block reads something that already exists rather than creating
// it. This one asks which availability zones the account can actually use,
// so the subnets below do not hardcode zone names that differ per region.
data "aws_availability_zones" "available" {
  state = "available"
}

// Reads the account ID and region currently in use. Useful for building
// ARNs and for asserting in an output which account you are about to
// deploy into.
data "aws_caller_identity" "current" {}
