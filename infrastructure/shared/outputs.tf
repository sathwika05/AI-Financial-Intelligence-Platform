output "certificate_arn" {
  description = "Passed to production/ as the ALB listener's certificate."
  value       = aws_acm_certificate.wildcard.arn
}

output "validation_record" {
  description = "Add this CNAME at the registrar to prove the domain is yours."
  value = {
    for o in aws_acm_certificate.wildcard.domain_validation_options :
    o.domain_name => {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  }
}

output "certificate_status" {
  value = aws_acm_certificate.wildcard.status
}

output "ecr_repository_url" {
  description = "Push images here; production/ points container_image at a tag of this."
  value       = aws_ecr_repository.app.repository_url
}
