variable "region" {
  description = "Must match the region the load balancer lives in: an ALB can only use a certificate from its own region."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  type    = string
  default = "fip"
}

variable "domain" {
  description = "The registered domain. DNS is hosted at the registrar, so the validation record is added there by hand."
  type        = string
  default     = "sathwikap.com"
}
