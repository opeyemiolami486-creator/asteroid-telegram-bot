from __future__ import annotations

import json
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .models import Wallet

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58_encode(value: bytes) -> str:
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _B58_ALPHABET[remainder] + encoded
    zeroes = len(value) - len(value.lstrip(b"\0"))
    return "1" * zeroes + encoded


def _b58_decode(value: str) -> bytes:
    number = 0
    for char in value:
        if char not in _B58_ALPHABET:
            raise ValueError("private key is not valid base58")
        number = number * 58 + _B58_ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + raw


def _seed_bytes(value: str | bytes | list[int]) -> bytes:
    if isinstance(value, list):
        raw = bytes(value)
    elif isinstance(value, bytes):
        raw = value
    else:
        text = value.strip()
        if text.startswith("["):
            raw = bytes(json.loads(text))
        elif re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) in {64, 128}:
            raw = bytes.fromhex(text)
        else:
            raw = _b58_decode(text)
    if len(raw) == 64:
        raw = raw[:32]
    if len(raw) != 32:
        raise ValueError("SOLANA_PRIVATE_KEY must contain a 32-byte seed or 64-byte secret key")
    return raw


@dataclass(frozen=True)
class SolanaSigner:
    seed: bytes

    @property
    def address(self) -> str:
        public_key = Ed25519PrivateKey.from_private_bytes(self.seed).public_key().public_bytes_raw()
        return _b58_encode(public_key)

    def sign(self, message: str) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(self.seed).sign(message.encode("utf-8"))


class SolanaWalletProvider:
    """Load a non-custodial Solana pilot key from configuration."""

    def __init__(self, private_key: str | None = None) -> None:
        if not private_key:
            raise ValueError("SOLANA_PRIVATE_KEY is required for Planet Forge mode")
        self.signer = SolanaSigner(_seed_bytes(private_key))

    def create(self) -> Wallet:
        return Wallet(address=self.signer.address, private_key=self.signer.seed.hex())

    def signer_for(self, wallet: Wallet) -> SolanaSigner:
        if wallet.address != self.signer.address:
            raise ValueError("persisted wallet does not match SOLANA_PRIVATE_KEY")
        return self.signer


class DemoWalletProvider:
    """Explicitly non-signing wallet used only by the offline demo target."""

    def create(self) -> Wallet:
        return Wallet(address="demo-wallet", private_key="demo-only")


# Compatibility for imports from earlier versions; it no longer creates fakes.
LocalWalletProvider = SolanaWalletProvider
