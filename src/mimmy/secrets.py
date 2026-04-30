"""AWS Secrets Manager 로더.

운영에선 .env 대신 Secrets Manager의 JSON 시크릿 하나(`mimmy/<env>`)를 읽어
`Settings` 환경변수로 주입한다. 개발에선 .env를 그대로 쓴다.

시크릿 페이로드 예:
{
  "ANTHROPIC_API_KEY": "...",
  "TELEGRAM_BOT_TOKEN": "...",
  "KIWOOM_APP_KEY": "...",
  ...
}
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def hydrate_from_secrets_manager(secret_id: str, region: str) -> None:
    """Secrets Manager에서 값을 가져와 os.environ에 덮어쓴다.

    이미 환경에 설정된 값은 건드리지 않는다(로컬 덮어쓰기 허용).
    """
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError("boto3 not installed — pip install boto3") from e

    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_id)
    payload: dict[str, Any] = json.loads(resp["SecretString"])

    injected = 0
    for k, v in payload.items():
        if k in os.environ:
            continue
        os.environ[k] = str(v)
        injected += 1
    log.info("secrets manager hydrated", extra={"count": injected, "secret_id": secret_id})
