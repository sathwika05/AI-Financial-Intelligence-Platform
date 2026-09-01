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

  // One secret holding everything the tasks need to be told privately.
  // jsonencode rather than a hand-written string, so a value containing a
  // quote or a backslash -- which API keys do -- cannot break the JSON.
  secret_string = jsonencode({
    DATABASE_URL      = local.database_url
    SYNC_DATABASE_URL = local.sync_database_url

    OPENAI_API_KEY = var.openai_api_key
    JWT_SECRET     = var.jwt_secret

    // Empty is allowed: these are only read by the seeding script, and a
    // deployment that never presses Rebuild does not need them.
    ALPHA_VANTAGE_API_KEY = var.alpha_vantage_api_key
    FINNHUB_API_KEY       = var.finnhub_api_key

    LANGSMITH_API_KEY = var.langsmith_api_key

    // Encrypts provider API keys in the llm_providers table. Until now it
    // was not passed at all, so production silently used the development
    // key baked into the image -- meaning anything encrypted in
    // production was readable by anyone holding that image.
    LLM_KEY_ENCRYPTION_SECRET = var.llm_key_encryption_secret
  })

  // Tracing on with no key is not a degraded deployment, it is a dead
  // one: setup_langsmith() runs at import in main.py and raises, so ECS
  // gets a task that cannot start and retries forever. Caught here, at
  // plan time, where it costs nothing.
  lifecycle {
    precondition {
      condition     = !var.langsmith_tracing || var.langsmith_api_key != ""
      error_message = "langsmith_tracing is true, so langsmith_api_key must be set. Set the key, or set langsmith_tracing = false."
    }
  }
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

  statement {
    sid = "OpenAnExecSession"
    // ECS Exec: a shell in the running task, over an SSM channel the task
    // opens outward. Nothing listens, no port is exposed, and the database
    // stays unreachable from anywhere but these tasks.
    //
    // It is how the first account gets created and how the benchmark
    // corpus is restored: both have to run inside the VPC, because that is
    // the only place the database can be reached from.
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    // The channel is created by the agent for itself; there is no
    // narrower resource to name.
    resources = ["*"]
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
  // 60 seconds, the default, is shorter than this application's slowest
  // honest answer. A ranking question runs intent, planning, SQL, vector
  // retrieval, live market data, reranking, scoring, analysis and review --
  // the analysis node alone measured 28 seconds on a four-company ranking.
  //
  // The load balancer gave up first and returned a 5xx while the task
  // carried on and logged 200, so the failure looked like a broken
  // application from the browser and like success from the logs.
  idle_timeout = 300

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

// The certificate lives in the shared stack, which survives a teardown.
// Looked up rather than passed in, so recreating this stack needs no
// manual wiring -- and a certificate that is not ISSUED will fail the
// plan here rather than producing a listener that serves nothing.
data "aws_acm_certificate" "wildcard" {
  domain      = "*.${var.domain}"
  statuses    = ["ISSUED"]
  most_recent = true
}

// Port 80 no longer serves the application: it sends callers to 443.
//
// A redirect rather than closing the port. People type a bare hostname
// and browsers still default to http, so refusing 80 outright reads as
// "the site is down" -- and the login form is the one page that must
// never be reachable unencrypted.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = data.aws_acm_certificate.wildcard.arn

  // A current policy rather than the default, which still permits TLS 1.0
  // and 1.1. Nothing this application talks to needs them.
  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"

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
    // Tracing itself. The URL above only says where a person should look;
    // these two decide whether anything is there to look at, and which
    // project it lands in.
    { name = "LANGSMITH_TRACING", value = tostring(var.langsmith_tracing) },
    { name = "LANGCHAIN_PROJECT", value = var.langchain_project },
    // The sidecar, over the task's shared loopback. Set here rather than
    // left to the image: the .env baked into it names a Docker Compose
    // host that does not exist in AWS, and environment beats dotenv.
    { name = "REDIS_URL", value = "redis://localhost:6379/0" },
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
    // Credentials, so they arrive the same way the database URLs do --
    // pulled from Secrets Manager at task start rather than sitting in
    // the task definition, where anyone who can describe the task can
    // read them.
    {
      name      = "OPENAI_API_KEY"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:OPENAI_API_KEY::"
    },
    {
      name      = "JWT_SECRET"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:JWT_SECRET::"
    },
    {
      name      = "ALPHA_VANTAGE_API_KEY"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:ALPHA_VANTAGE_API_KEY::"
    },
    {
      name      = "FINNHUB_API_KEY"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:FINNHUB_API_KEY::"
    },
    {
      name      = "LANGSMITH_API_KEY"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:LANGSMITH_API_KEY::"
    },
    {
      name      = "LLM_KEY_ENCRYPTION_SECRET"
      valueFrom = "${aws_secretsmanager_secret.app.arn}:LLM_KEY_ENCRYPTION_SECRET::"
    },
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory

  // The image is built on an Apple Silicon machine, so it is arm64.
  // Fargate defaults to X86_64 and an unpinned task dies with
  // "exec format error" - which reads as a broken image, not a wrong
  // architecture. Graviton is also about 20% cheaper.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

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
    },
    // Redis, alongside the app rather than as its own service.
    //
    // Containers in one task share a network namespace, so the app reaches
    // this on localhost and nothing else can: no subnet, no security
    // group, no ElastiCache bill. The cache dies with the task, which is
    // what a cache is for.
    //
    // Not essential: Redis failing must not kill the API. Every call is
    // already wrapped -- caching degrades to recomputing. The exception is
    // the rate limiter, which fails open, so without this the public API
    // has no throttle at all.
    {
      name      = "redis"
      image     = "public.ecr.aws/docker/library/redis:7-alpine"
      essential = false

      // A cache with a bound. Without maxmemory it grows until the task
      // hits its memory limit and ECS kills everything in it.
      command = [
        "redis-server",
        "--maxmemory", "256mb",
        "--maxmemory-policy", "allkeys-lru",
        "--save", ""
      ]

      memoryReservation = 256

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "redis"
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
  // Sized apart from the API. This is the task that meets a scanned
  // filing and has nothing else to do; the API queues work and answers,
  // so it does not need the same headroom and should not be billed for
  // it.
  cpu    = var.worker_cpu
  memory = var.worker_memory

  // Same image as the API, so the same architecture.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.container_image
      essential = true

      // The venv's interpreter directly, not `uv run`. uv re-syncs the
      // project on every invocation, and .python-version pins a release
      // the base image does not ship -- so `uv run` judged the venv wrong,
      // deleted it, and reinstalled 212 packages before the worker could
      // poll anything. Two and a half minutes, on every task start.
      command = [
        "/code/.venv/bin/python", "-m", "backend.ingestion.queue_worker"
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
    },
    // Redis, alongside the app rather than as its own service.
    //
    // Containers in one task share a network namespace, so the app reaches
    // this on localhost and nothing else can: no subnet, no security
    // group, no ElastiCache bill. The cache dies with the task, which is
    // what a cache is for.
    //
    // Not essential: Redis failing must not kill the API. Every call is
    // already wrapped -- caching degrades to recomputing. The exception is
    // the rate limiter, which fails open, so without this the public API
    // has no throttle at all.
    {
      name      = "redis"
      image     = "public.ecr.aws/docker/library/redis:7-alpine"
      essential = false

      // A cache with a bound. Without maxmemory it grows until the task
      // hits its memory limit and ECS kills everything in it.
      command = [
        "redis-server",
        "--maxmemory", "256mb",
        "--maxmemory-policy", "allkeys-lru",
        "--save", ""
      ]

      memoryReservation = 256

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "redis"
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

  // Required for `aws ecs execute-command`. Off by default, and it takes
  // a new deployment to come into effect.
  enable_execute_command = true

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

  // Required for `aws ecs execute-command`. Off by default, and it takes
  // a new deployment to come into effect.
  enable_execute_command = true

  network_configuration {
    subnets          = var.use_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = !var.use_nat_gateway
  }
}
