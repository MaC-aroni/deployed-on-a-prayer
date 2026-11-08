"""Remove stale Terraform state locks left in S3 by a run that was killed mid-command.

Usage: mise run mac-unlock            (lists and deletes every .tflock under mac/)
A lock is only ever stale if no Rehearse or Deploy is running; check the console first.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
import boto3  # noqa: E402


def main() -> int:
    bucket, region = os.environ.get("MAC_TF_STATE_BUCKET"), os.environ.get("MAC_TF_STATE_REGION", "us-east-1")
    if not bucket:
        print("MAC_TF_STATE_BUCKET isn't set")
        return 1
    s3 = boto3.client("s3", region_name=region)
    locks = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix="mac/").get("Contents", []) if o["Key"].endswith(".tflock")]
    if not locks:
        print("no locks found")
        return 0
    for key in locks:
        info = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        print(f"{key}\n  held by {info.get('Who')} since {info.get('Created')} ({info.get('Operation')})")
        s3.delete_object(Bucket=bucket, Key=key)
        print("  deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
