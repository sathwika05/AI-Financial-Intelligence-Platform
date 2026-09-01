// One wildcard certificate for the whole domain.
//
// Wildcard rather than a single name so a later api. or benchmark.
// subdomain needs no new certificate and no new DNS validation. It does
// not cover the apex -- *.sathwikap.com matches fintel.sathwikap.com but
// not sathwikap.com itself, which is fine: an apex record pointing at a
// load balancer needs an ALIAS, and the registrar's DNS does not have one.
//
// ACM certificates are free and renew themselves while in use, so this
// costs nothing to keep between demos.
resource "aws_acm_certificate" "wildcard" {
  domain_name       = "*.${var.domain}"
  validation_method = "DNS"

  lifecycle {
    // Replace before removing, so a rotation never leaves the listener
    // pointing at a certificate that no longer exists.
    create_before_destroy = true
  }

  tags = {
    Name = "${var.project}-wildcard"
  }
}
