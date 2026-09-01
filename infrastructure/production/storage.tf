// S3 and SQS for the indexing pipeline:
//
//   S3 (raw) --event--> SQS --poll--> Fargate worker --> RDS --> S3 (processed)
//
// The queue exists so an upload does not have to wait for parsing,
// chunking and embedding, and so a failed document is retried rather than
// lost.

// ---------------------------------------------------------------------------
// Buckets
//
// `for_each` over a map creates one resource per entry, addressed by key:
// aws_s3_bucket.docs["raw"].id. Unlike count, keys are stable — removing
// "processed" later does not renumber and recreate "raw".
// ---------------------------------------------------------------------------

locals {
  buckets = {
    raw       = "Uploaded documents before processing"
    processed = "Parsed output and backups"
  }
}

resource "aws_s3_bucket" "docs" {
  for_each = local.buckets

  // Bucket names are globally unique across all AWS accounts, so the
  // account ID is appended to avoid collisions with someone else's stack.
  bucket = "${local.name_prefix}-${each.key}-${data.aws_caller_identity.current.account_id}"

  // Lets `terraform destroy` remove a bucket that still has objects in it.
  // Correct while this stack is disposable; set false once it holds
  // anything you would miss.
  force_destroy = true

  tags = {
    Name    = "${local.name_prefix}-${each.key}"
    Purpose = each.value
  }
}

// Public access is blocked by default on new buckets, but stated
// explicitly: this is the setting whose absence causes public data leaks,
// and it should be visible in the code rather than assumed.
resource "aws_s3_bucket_public_access_block" "docs" {
  for_each = aws_s3_bucket.docs

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "docs" {
  for_each = aws_s3_bucket.docs

  bucket = each.value.id

  versioning_configuration {
    // Versioning makes an accidental overwrite or delete recoverable.
    status = "Enabled"
  }
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

// The dead-letter queue is declared first because the main queue
// references its ARN.
//
// Without a DLQ, a document that always fails to parse is retried until it
// expires — consuming worker time on every cycle and disappearing with no
// record. With one, it moves aside after a fixed number of attempts and
// can be inspected.
resource "aws_sqs_queue" "ingestion_dlq" {
  name = "${local.name_prefix}-ingestion-dlq"

  message_retention_seconds = 1209600 // 14 days, the maximum

  tags = {
    Name = "${local.name_prefix}-ingestion-dlq"
  }
}

resource "aws_sqs_queue" "ingestion" {
  name = "${local.name_prefix}-ingestion"

  // How long a message stays invisible after a worker picks it up. Must
  // exceed the worst-case processing time, or a slow document becomes
  // visible again and a second worker starts on it in parallel.
  //
  // 300 was sized against chunking and embedding, before Docling and OCR
  // were in the path. A scanned page measures about 7.4s, so 300 covered
  // roughly forty pages -- and a scanned 10-K is far more than forty.
  // 1800 covers around 240.
  //
  // The cost of raising it is that a message whose worker genuinely died
  // waits half an hour before anyone retries it. That is the better
  // trade: a document processed twice at once is worse than one
  // processed late.
  visibility_timeout_seconds = 1800

  // Long polling: wait for a message rather than returning empty
  // immediately. Fewer empty receives, and cheaper.
  receive_wait_time_seconds = 20

  message_retention_seconds = 345600 // 4 days

  // jsonencode builds JSON from HCL, so this stays readable and cannot
  // drift from a hand-written string.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${local.name_prefix}-ingestion"
  }
}

// ---------------------------------------------------------------------------
// Letting S3 publish to the queue
//
// A policy document written as a data source rather than a JSON string:
// Terraform validates the structure, and the ARNs are references instead
// of copied text.
// ---------------------------------------------------------------------------

data "aws_iam_policy_document" "queue_from_s3" {
  statement {
    sid    = "AllowS3ToSendMessages"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingestion.arn]

    // Without this condition any bucket in any account could publish here.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.docs["raw"].arn]
    }
  }
}

resource "aws_sqs_queue_policy" "ingestion" {
  queue_url = aws_sqs_queue.ingestion.id
  policy    = data.aws_iam_policy_document.queue_from_s3.json
}

resource "aws_s3_bucket_notification" "raw_upload" {
  bucket = aws_s3_bucket.docs["raw"].id

  queue {
    queue_arn = aws_sqs_queue.ingestion.arn
    events    = ["s3:ObjectCreated:*"]
  }

  // S3 verifies it can publish at the moment the notification is created,
  // so the policy must already exist. Nothing here references it, so the
  // dependency has to be stated.
  depends_on = [aws_sqs_queue_policy.ingestion]
}
