"""Optional Cloudflare R2 storage for generation screenshots (S3-compatible API)."""

from pathlib import Path

from ifdispatcher.config import setting


def r2_configured() -> bool:
    return all(
        setting(k)
        for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    )


def upload(paths: list[str], prefix: str) -> list[str]:
    """Upload files to R2 under prefix/; returns object keys ([] when R2 is not configured)."""
    if not r2_configured():
        return []
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{setting('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=setting("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=setting("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    keys = []
    for path in paths:
        key = f"{prefix}/{Path(path).name}"
        client.upload_file(path, setting("R2_BUCKET"), key)
        keys.append(key)
    return keys
