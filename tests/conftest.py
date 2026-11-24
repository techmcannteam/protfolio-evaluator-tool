"""Tests use local fixtures only; fail if anything attempts a network connection."""

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Offline tests must not make network/provider calls")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
