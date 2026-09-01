// Where the image lives. Terraform does not build it — it creates the
// repository, and container_image points at a tag pushed here.

resource "aws_ecr_repository" "app" {
  name = "${local.name_prefix}-app"

  image_scanning_configuration {
    scan_on_push = true
  }

  // Destroy would otherwise fail if the repository still contains images.
  force_delete = true

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

// This image carries PyTorch and the Docling models, so it runs to several
// GB. ECR bills per GB-month, and without this every build accumulates.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 5 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

