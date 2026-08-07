"""Optional payload encryption codec (toggle with ENCRYPT_PAYLOADS=true).

When enabled on the data converter, every payload — workflow args, activity
args/results, AND the `auth-token` header — is encrypted on the wire and at rest
in Event History. That's the counterpoint to the "the JWT is visible in the
Temporal console" note: flip this on and the token (and everything else) is
ciphertext in the UI.

The key here is derived in-repo for the demo. In production it comes from a KMS
and never lives in source.
"""

import base64
import hashlib
from typing import Iterable, List

from cryptography.fernet import Fernet
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

_ENCODING = b"binary/encrypted"
# Demo key: deterministic, derived here. Do NOT do this in production.
_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"circuits-of-time-demo-key").digest())


class EncryptionCodec(PayloadCodec):
    def __init__(self) -> None:
        self._fernet = Fernet(_KEY)

    async def encode(self, payloads: Iterable[Payload]) -> List[Payload]:
        return [
            Payload(
                metadata={"encoding": _ENCODING},
                data=self._fernet.encrypt(p.SerializeToString()),
            )
            for p in payloads
        ]

    async def decode(self, payloads: Iterable[Payload]) -> List[Payload]:
        result: List[Payload] = []
        for p in payloads:
            if p.metadata.get("encoding") != _ENCODING:
                result.append(p)
                continue
            result.append(Payload.FromString(self._fernet.decrypt(p.data)))
        return result
