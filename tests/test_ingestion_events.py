"""
The S3 -> SQS -> Fargate path, minus AWS.

Terraform has provisioned this since the infrastructure went in: a raw
bucket, an ingestion queue with a dead-letter queue, a bucket notification
publishing s3:ObjectCreated:* to that queue, and a task role that can read
the bucket and consume the queue. No code ever produced to or consumed
from any of it — the fetcher wrote straight to Postgres.

Parsing is tested against the real shape of an S3 event notification.
Getting this wrong means a poison message that fails, returns to the
queue, fails again, and eventually fills the dead-letter queue.
"""
import json

import pytest


def _event(bucket: str, *keys: str) -> str:
    return json.dumps(
        {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "s3": {
                        "bucket": {"name": bucket},
                        "object": {"key": key},
                    },
                }
                for key in keys
            ]
        }
    )


class TestParsingS3Events:
    def test_one_object_is_read_from_the_notification(self):
        from backend.ingestion.events import parse_s3_event

        refs = parse_s3_event(_event("raw-bucket", "news/AAPL/123.json"))

        assert len(refs) == 1
        assert refs[0].bucket == "raw-bucket"
        assert refs[0].key == "news/AAPL/123.json"

    def test_a_batched_notification_yields_every_object(self):
        """S3 may put several records in one message."""
        from backend.ingestion.events import parse_s3_event

        refs = parse_s3_event(_event("raw", "a.json", "b.json", "c.json"))

        assert [ref.key for ref in refs] == ["a.json", "b.json", "c.json"]

    def test_a_url_encoded_key_is_decoded(self):
        """
        S3 URL-encodes the key, so a space arrives as '+' and a slash as
        %2F. Fetching the raw form would 404 on every document whose
        title had a space in it.
        """
        from backend.ingestion.events import parse_s3_event

        body = json.dumps(
            {
                "Records": [
                    {
                        "eventName": "ObjectCreated:Put",
                        "s3": {
                            "bucket": {"name": "raw"},
                            "object": {"key": "news/Q3+earnings%2Fapple.json"},
                        },
                    }
                ]
            }
        )

        refs = parse_s3_event(body)

        assert refs[0].key == "news/Q3 earnings/apple.json"

    def test_the_s3_test_event_is_ignored(self):
        """
        S3 posts one s3:TestEvent when a notification is created. It has no
        Records, and treating it as a failure would send the very first
        message to the dead-letter queue.
        """
        from backend.ingestion.events import parse_s3_event

        body = json.dumps(
            {
                "Service": "Amazon S3",
                "Event": "s3:TestEvent",
                "Bucket": "raw-bucket",
            }
        )

        assert parse_s3_event(body) == []

    def test_malformed_json_raises_rather_than_silently_dropping(self):
        """
        A message that cannot be parsed must fail loudly: silently
        returning nothing would delete it from the queue as though it had
        been handled.
        """
        from backend.ingestion.events import MalformedEvent, parse_s3_event

        with pytest.raises(MalformedEvent):
            parse_s3_event("{not json")

    def test_a_record_missing_its_object_is_skipped_not_fatal(self):
        """One odd record must not discard the others in the batch."""
        from backend.ingestion.events import parse_s3_event

        body = json.dumps(
            {
                "Records": [
                    {"eventName": "ObjectCreated:Put", "s3": {}},
                    {
                        "eventName": "ObjectCreated:Put",
                        "s3": {
                            "bucket": {"name": "raw"},
                            "object": {"key": "good.json"},
                        },
                    },
                ]
            }
        )

        refs = parse_s3_event(body)

        assert [ref.key for ref in refs] == ["good.json"]
