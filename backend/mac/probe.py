"""Probes: one signed request to a deployed step's URL, to show it really answers from AWS.

Lambda function URLs here only accept requests signed with AWS SigV4 (the landing-zone rule),
so a plain curl gets 403. MaC signs with its own AWS credentials and reports what AWS sent
back: the status, the body, and the request id that Lambda stamps on every response.
Only URLs a run recorded as a step output are ever probed, never arbitrary ones.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .spec import Probe

LAMBDA_URL = re.compile(r"^[a-z0-9]+\.lambda-url\.([a-z0-9-]+)\.on\.aws$")
BODY_LIMIT = 4000


def region_of(url: str, default: str) -> str:
    match = LAMBDA_URL.match(urllib.parse.urlsplit(url).hostname or "")
    return match.group(1) if match else default


def target(url: str, probe: Probe) -> str:
    return url.rstrip("/") + probe.path


def curl_command(url: str, probe: Probe, region: str) -> str:
    """What a person with AWS keys in their shell can paste to make the same request."""
    parts = ["curl -sS", f"--aws-sigv4 'aws:amz:{region}:lambda'",
             '--user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY"']
    if probe.method == "POST":
        parts += ["-X POST", "-H 'Content-Type: application/json'", f"-d '{json.dumps(probe.body or {})}'"]
    return " ".join([*parts, f"'{target(url, probe)}'"])


def send(url: str, probe: Probe, region: str, timeout: int = 20) -> dict:
    """Signs and sends the probe. Never raises: a failure (DNS, 403, timeout) is the answer."""
    import boto3  # local: only needed when probing
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    full = target(url, probe)
    data = json.dumps(probe.body or {}).encode("utf-8") if probe.method == "POST" else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    result = {"url": full, "method": probe.method, "probe": probe.name, "expect": probe.expect,
              "region": region, "served_by_aws": bool(LAMBDA_URL.match(urllib.parse.urlsplit(full).hostname or "")),
              "status": None, "ok": False, "request_id": None, "body": None, "error": None,
              "curl": curl_command(url, probe, region), "checked": time.time()}
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        result["error"] = "no AWS credentials on this server, so the request can't be signed"
        return result
    request = AWSRequest(method=probe.method, url=full, data=data, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", region).add_auth(request)
    req = urllib.request.Request(full, data=data, method=probe.method, headers=dict(request.headers.items()))
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw, response_headers = resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        status, raw, response_headers = e.code, e.read(), e.headers
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        result["error"] = f"no answer: {reason}"  # e.g. the service was undone and the name is gone
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return result
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["status"] = status
    result["ok"] = status == probe.expect
    result["request_id"] = response_headers.get("x-amzn-RequestId") or response_headers.get("x-amz-request-id")
    text = raw[:BODY_LIMIT].decode("utf-8", "replace")
    try:
        result["body"] = json.loads(text)
    except ValueError:
        result["body"] = text
    return result
