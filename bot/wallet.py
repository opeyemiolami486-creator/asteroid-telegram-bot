from __future__ import annotations

import hashlib
import secrets

from .models import Wallet


class LocalWalletProvider:
    """Temporary hackathon wallet format; replace with the reference site's format."""

    def create(self) -> Wallet:
        private_key = secrets.token_hex(32)
        address = "testwallet_" + hashlib.sha256(private_key.encode()).hexdigest()[:40]
        return Wallet(address=address, private_key=private_key)
