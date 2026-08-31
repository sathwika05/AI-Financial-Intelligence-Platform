// ECS Fargate: the API service behind an ALB, and the indexing worker that
// polls SQS. Both run the same image with a different command.

// ---------------------------------------------------------------------------
// Secrets
//
// Environment variables on a task definition are visible to anyone who can
// describe the task. Anything secret goes in Secrets Manager and is
// injected by the agent at start, so it never appears in the definition.
// ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "app" {
  name = "${local.name_prefix}-app-secrets"

  // Deleted secrets are normally retained for 7-30 days and the name stays
  // reserved, so a destroy/apply cycle fails on the name already existing.
  // Zero makes the stack genuinely re-creatable.
  recovery_window_in_days = 0

  tags = {
    Name = "${local.name_prefix}-app-secrets"
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    DATABASE_URL      = local.database_url
    SYNC_DATABASE_URL = local.sync_database_url
  })
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

// Created explicitly rather than letting ECS make it, so retention is set.
// An implicitly created log group keeps logs forever, which is a cost that
// grows quietly and is easy to miss.
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name_prefix}/api"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.name_prefix}-api-logs"
  }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name_prefix}/worker"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.name_prefix}-worker-logs"
  }
}

// ---------------------------------------------------------------------------
// IAM
//
// Two roles, and the distinction matters:
//
//   execution role  used by the ECS agent to pull the image and fetch
//                   secrets, before the container starts
//   task role       used by the application itself once running
//
// Putting S3 and SQS permissions on the execution role is a common mistake
// that appears to work, because the agent is more privileged than the task
// needs to be.
// ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

// The managed policy above covers ECR and logs but not Secrets Manager.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${local.name_prefix}-execution-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

// What the application may do: read uploads, write processed output, and
// consume the queue. Scoped to these buckets and this queue rather than
// wildcards, so a mistake cannot reach anything else in the account.
data "aws_iam_policy_document" "task" {
  statement {
    sid     = "ReadRawDocuments"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.docs["raw"].arn,
      "${aws_s3_bucket.docs["raw"].arn}/*",
    ]
  }

  statement {
    sid       = "WriteProcessedDocuments"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.docs["processed"].arn}/*"]
  }

  statement {
    sid = "ConsumeIngestionQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      // Lets the worker extend visibility on a document that is taking
      // longer than the timeout, instead of it being redelivered mid-run.
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.ingestion.arn]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.name_prefix}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

// ---------------------------------------------------------------------------
// Load balancer
// ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

resource "aws_lb_target_group" "api" {
  name     = "${local.name_prefix}-api-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id
  // Required for Fargate: targets register by IP, not instance id.
  target_type = "ip"

  health_check {
    path = "/health"
    // The API creates tables and enables pgvector during lifespan startup,
    // so it needs longer than the default before the first check.
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name = "${local.name_prefix}-api-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

// ---------------------------------------------------------------------------
// Cluster and services
// ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name = "containerInsights"
    // Off by default: Container Insights bills per metric and this stack
    // is short-lived. Turn on when you need the dashboards.
    value = "disabled"
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

locals {
  // Non-secret configuration, shared by both task definitions. The queue
  // URL and bucket names come from the resources above rather than being
  // typed, so they cannot go stale.
  app_environment = [
    { name = "APP_ENV", value = var.environment },
    { name = "DEPLOYMENT_MODE", value = "full" },
    { name = "AWS_REGION", value = var.region },
    { name = "INGESTION_QUEUE_URL", value = aws_sqs_queue.ingestion.id },
    { name = "RAW_BUCKET", value = aws_s3_bucket.docs["raw"].id },
    { name = "PROCESSED_BUCKET", value = aws_s3_bucket.docs["processed"].id },
    // SEC requires every EDGAR request to name its caller and give a
    // contact address. Not a secret -- it is sent in the clear on every
    // request, and it exists so SEC can get in touch, not to authorise
    // anything. Empty turns the collector off rather than sending an
    // anonymous request, which SEC refuses and which gets the address
    // blocked for everyone behind it.
    { name = "SEC_USER_AGENT", value = var.sec_user_agent },
    // Where the admin UI links out to. Console URLs, not credentials --
    // they name a log group and a project, and both pages demand their
    // own sign-in. Built from the resources above so they cannot name a
    // log group this deployment does not have.
    {
      name  = "CLOUDWATCH_LOGS_URL"
      value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#logsV2:log-groups/log-group/${replace(aws_cloudwatch_log_group.api.name, "/", "$252F")}"
    },
    { name = "LANGSMITH_PROJECT_URL", value = var.langsmith_project_url },
  ]

  app_secrets = [
    {
      name = "DATABASE_URL"
      // The :: suffix selects a key from the JSON secret. The trailing
      // fields are version stage and version id, left empty for latest.
      valueFrom = "${aws_secretsmanager_secret.app.arn}:DATABASE_URL::"
    },
    {
      name      = "SYNC_DATABASE_URL"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:SYNC_DATABASE_URL::"
    },
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.container_image
      essential = true

      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]

      environment = local.app_environment
      secrets     = local.app_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

// Same image, different command: the worker polls SQS instead of serving
// HTTP, so it needs no port, no load balancer and no health check.
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  // The worker parses whatever lands in the bucket, so it needs what the
  // API needs. Sized to the same numbers rather than left at the default:
  // one 10-K used 6.6 cores and 2.4GiB, and this is the task that will
  // meet a scanned filing.
  cpu    = var.api_cpu
  memory = var.api_memory

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.container_image
      essential = true

      command = [
        "uv", "run", "python", "-m", "backend.ingestion.queue_worker"
      ]

      environment = local.app_environment
      secrets     = local.app_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    // Public subnets when there is no NAT gateway, private when there is.
    // Either way the security group is what actually restricts access.
    subnets          = var.use_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = !var.use_nat_gateway
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  // The service registers targets with the listener's target group, and
  // creating it before the listener exists fails.
  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  // Scale on queue depth later; one worker is enough to start, and SQS
  // holds anything it cannot keep up with.
  desired_count = 1
  launch_type   = "FARGATE"

  network_configuration {
    subnets          = var.use_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = !var.use_nat_gateway
  }
}
