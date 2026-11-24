"""Tests use local fixtures only; fail if anything attempts a network connection."""

import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setenv(
        "AGENT_ROSTER_PATH", str(Path(__file__).parent / "fixtures/agent-roster.json")
    )
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Offline tests must not make network/provider calls")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
