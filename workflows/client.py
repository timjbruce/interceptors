"""One place to connect a Temporal Client — local or Temporal Cloud.

Mirrors the money-transfer demo's `build_client`: it reads TEMPORAL_* env vars
and picks auth automatically — API key first, then mTLS client certs, otherwise
a plain local connection. Copy setcloudenv.example to setcloudenv.sh and source
it (the run scripts do this for you) to target Cloud.
"""

import dataclasses
import os
from typing import Optional, Sequence

import temporalio.converter
from temporalio.client import Client, Interceptor, TLSConfig

from workflows.config import ENCRYPT_PAYLOADS, TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE


async def connect(interceptors: Optional[Sequence[Interceptor]] = None) -> Client:
    cert_path = os.getenv("TEMPORAL_CERT_PATH", "")
    key_path = os.getenv("TEMPORAL_KEY_PATH", "")
    api_key = os.getenv("TEMPORAL_API_KEY", "")

    kwargs: dict = {
        "target_host": TEMPORAL_ADDRESS,
        "namespace": TEMPORAL_NAMESPACE,
    }
    if interceptors:
        kwargs["interceptors"] = list(interceptors)

    if ENCRYPT_PAYLOADS:
        # Encrypt every payload AND header on the wire and in Event History.
        #
        # Two settings are needed, and missing the second is an easy mistake: the
        # data converter's codec covers payloads, while `header_codec_behavior`
        # decides whether headers go through that same codec. It defaults to
        # NO_CODEC, so setting only the converter leaves the delegation-grant
        # header sitting in Event History as readable plaintext.
        from temporalio.common import HeaderCodecBehavior

        from workflows.codec import EncryptionCodec

        kwargs["data_converter"] = dataclasses.replace(
            temporalio.converter.default(), payload_codec=EncryptionCodec()
        )
        kwargs["header_codec_behavior"] = HeaderCodecBehavior.CODEC

    if api_key:
        # Prefer Temporal Cloud API key auth.
        kwargs["api_key"] = api_key
        kwargs["tls"] = True
    elif cert_path and key_path:
        # Fall back to mTLS client certificates.
        with open(cert_path, "rb") as f:
            cert = f.read()
        with open(key_path, "rb") as f:
            key = f.read()
        kwargs["tls"] = TLSConfig(client_cert=cert, client_private_key=key)
    # else: plain local dev server (no TLS).

    return await Client.connect(**kwargs)
