// The image registry, moved here from production/.
//
// It was in the same state as the VPC and the database, so a teardown
// after a demo deleted it -- and with force_delete, the images inside.
// Rebuilding that meant pushing 4.36 GB over a connection that needed a
// chunked uploader and several hours to manage it once.
//
// Here it survives every destroy. Storage is about $0.87/month for the
// images the lifecycle policy keeps, which is cheaper than doing that
// upload again even once.
//
// Layers are shared, so keeping this also makes iteration cheap: a code
// change touches only the last layer, and a push sends tens of megabytes
// because ECR already holds the rest.
resource "aws_ecr_repository" "app" {
  name = "${var.project}-prod-app"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true

  tags = {
    Name = "${var.project}-prod-app"
  }
}

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
