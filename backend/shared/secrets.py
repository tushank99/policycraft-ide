"""Read secrets from SSM Parameter Store (SecureString), cached per container.

Lookup order for a secret NAME:
  1. env var NAME            (local dev / tests)
  2. env var NAME_PARAM      -> SSM parameter name, decrypted with aws/ssm (free tier)
"""

import os
from functools import lru_cache


@lru_cache(maxsize=16)
def _read_parameter(param_name: str) -> str:
    import boto3  # imported lazily so unit tests don't need AWS config

    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def get_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    param = os.environ.get(f"{name}_PARAM", "")
    if not param:
        return ""
    return _read_parameter(param)
