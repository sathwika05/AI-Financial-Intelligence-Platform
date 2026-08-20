// RDS PostgreSQL with pgvector.

// A subnet group tells RDS which subnets it may place the instance in. Two
// AZs are required even for a single-AZ instance, which is why network.tf
// always builds two of each.
resource "aws_db_subnet_group" "main" {
  name = "${local.name_prefix}-db-subnet"

  // Private subnets: the database should have no route to the internet.
  // It is reachable only from the app security group, which is enforced
  // separately by aws_security_group.db.
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnet"
  }
}

// A parameter group is the only way to change Postgres settings on RDS —
// there is no postgresql.conf to edit.
resource "aws_db_parameter_group" "main" {
  name   = "${local.name_prefix}-pg16"
  family = "postgres16"

  parameter {
    name = "shared_preload_libraries"
    // pgvector itself does not need preloading, but pg_stat_statements is
    // the first thing you want when a query is slow, and adding it later
    // forces a reboot.
    value = "pg_stat_statements"
    // Static parameters only take effect after a restart, and RDS refuses
    // to apply them otherwise.
    apply_method = "pending-reboot"
  }

  parameter {
    // Log statements slower than 1s. Cheap, and it is how you find the
    // vector query that is not using its index.
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = {
    Name = "${local.name_prefix}-pg16"
  }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-db"

  engine = "postgres"
  // Major version only. RDS applies minor upgrades in the maintenance
  // window, and pinning the full version means Terraform would try to
  // revert them on the next apply.
  engine_version = "16"

  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.main.name

  // No public endpoint. Reaching it from a laptop means a bastion or a
  // session-manager tunnel, which is the correct amount of friction.
  publicly_accessible = false

  // Single AZ: this stack is destroyed between sessions, so paying double
  // for a standby buys nothing.
  multi_az = false

  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = var.db_deletion_protection

  // Applies changes immediately rather than waiting for the maintenance
  // window. Right for a disposable stack; would cause unplanned downtime
  // on something real.
  apply_immediately = true

  // The pgvector extension still has to be created inside the database —
  // RDS does not do it, and neither does Terraform. backend/main.py runs
  // CREATE EXTENSION IF NOT EXISTS vector at startup, so the API creates
  // it on first boot.

  tags = {
    Name = "${local.name_prefix}-db"
  }
}

// Connection string assembled here rather than by hand, so the task
// definition cannot drift from the instance Terraform actually created.
//
// Marked sensitive so it does not appear in plan or apply output. It is
// still in state in plain text: encrypt the backend before this matters.
locals {
  database_url      = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.main.endpoint}/${var.db_name}"
  sync_database_url = "postgresql+psycopg2://${var.db_username}:${var.db_password}@${aws_db_instance.main.endpoint}/${var.db_name}"
}
