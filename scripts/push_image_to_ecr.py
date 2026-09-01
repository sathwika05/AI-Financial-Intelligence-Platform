"""
Push an image to ECR in 20 MiB parts.

    skopeo copy --format v2s2 --dest-compress \
        docker-daemon:fip-app:v3 dir:/tmp/v3export

    ECR_TAG=v3 ECR_EXPORT=/tmp/v3export \
        uv run python scripts/push_image_to_ecr.py

Why this exists
---------------
`docker push` and `skopeo` send each layer as one continuous stream. This
image's largest layer is 3.3 GB, and the network here closes any upload
after 60-80 MB, with no resume -- so every attempt restarted from zero and
none ever finished.

ECR's own API takes a layer in parts of at most 20 MiB, each its own
request. A dropped connection costs one part, which is retried. Nothing
larger than 20 MiB is ever in flight, and 195 parts went up with no
retries on the same network that had failed every time before.

It also skips blobs ECR already holds, so a rebuilt image usually sends
only the layer that changed.

`docker push` cannot be used for a later tag either: it computes its own
layer digests, which do not match the ones skopeo's compression produced,
so ECR sees every layer as missing and tries to send 4.36 GB again.
"""
import hashlib
import json
import os
import sys
import time

import boto3
from botocore.config import Config

REPO = os.getenv("ECR_REPO", "fip-prod-app")
TAG = os.getenv("ECR_TAG", "v1")
EXPORT = os.getenv("ECR_EXPORT", "/tmp/fipexport")
REGION = os.getenv("AWS_REGION", "us-east-1")

PART = 20 * 1024 * 1024      # ECR's documented maximum
ATTEMPTS = 12

ecr = boto3.client(
    "ecr",
    region_name=REGION,
    # A stalled part should fail fast and be retried rather than hold the
    # whole upload open.
    config=Config(
        connect_timeout=20,
        read_timeout=120,
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)


def already_there(digests: list[str]) -> set[str]:
    """Which blobs ECR already holds, so a retry does not resend them."""
    found: set[str] = set()

    for i in range(0, len(digests), 100):
        response = ecr.batch_check_layer_availability(
            repositoryName=REPO, layerDigests=digests[i:i + 100]
        )
        for layer in response.get("layers", []):
            if layer.get("layerAvailability") == "AVAILABLE":
                found.add(layer["layerDigest"])

    return found


def upload_blob(path: str, digest: str) -> None:
    size = os.path.getsize(path)
    upload_id = ecr.initiate_layer_upload(repositoryName=REPO)["uploadId"]

    sent = 0
    part_no = 0
    total_parts = (size + PART - 1) // PART

    with open(path, "rb") as f:
        while sent < size:
            chunk = f.read(PART)
            if not chunk:
                break

            part_no += 1
            first, last = sent, sent + len(chunk) - 1

            for attempt in range(1, ATTEMPTS + 1):
                try:
                    ecr.upload_layer_part(
                        repositoryName=REPO,
                        uploadId=upload_id,
                        partFirstByte=first,
                        partLastByte=last,
                        layerPartBlob=chunk,
                    )
                    break
                except Exception as e:
                    if attempt == ATTEMPTS:
                        raise

                    wait = min(2 ** attempt, 30)
                    print(
                        f"      part {part_no}/{total_parts} attempt {attempt} "
                        f"failed ({type(e).__name__}); retrying in {wait}s",
                        flush=True,
                    )
                    time.sleep(wait)

            sent += len(chunk)
            print(
                f"      {part_no}/{total_parts}  "
                f"{sent/1e6:.0f}/{size/1e6:.0f} MB  ({100*sent/size:.0f}%)",
                flush=True,
            )

    # ECR reassembles the parts and checks the result against this digest,
    # so a missing or misordered part is refused rather than stored.
    ecr.complete_layer_upload(
        repositoryName=REPO, uploadId=upload_id, layerDigests=[digest]
    )


def blob_path(digest: str) -> str:
    bare = os.path.join(EXPORT, digest.split(":", 1)[1])

    return bare if os.path.exists(bare) else os.path.join(
        EXPORT, digest.replace(":", "_")
    )


def main() -> int:
    manifest_raw = open(os.path.join(EXPORT, "manifest.json"), "rb").read()
    manifest = json.loads(manifest_raw)

    blobs = [manifest["config"]] + manifest["layers"]
    print(f"  {REPO}:{TAG} — {len(blobs)} blob(s)")

    present = already_there([b["digest"] for b in blobs])
    print(f"  already in ECR: {len(present)}")

    for i, blob in enumerate(blobs, 1):
        digest = blob["digest"]

        if digest in present:
            print(f"  [{i}/{len(blobs)}] {digest[:20]}... already there")
            continue

        path = blob_path(digest)
        print(
            f"  [{i}/{len(blobs)}] {digest[:20]}...  "
            f"{os.path.getsize(path)/1e6:.0f} MB"
        )
        upload_blob(path, digest)
        print("      done")

    print("  registering manifest")
    ecr.put_image(
        repositoryName=REPO,
        imageManifest=manifest_raw.decode("utf-8"),
        imageManifestMediaType=manifest["mediaType"],
        imageTag=TAG,
    )
    print(f"  {REPO}:{TAG} complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
