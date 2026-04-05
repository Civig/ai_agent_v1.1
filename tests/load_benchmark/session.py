from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


@dataclass(frozen=True)
class Credential:
    username: str
    password: str


@dataclass(frozen=True)
class SessionSnapshot:
    username: str
    cookies: dict[str, str]
    csrf_token: str

    def build_session(self) -> requests.Session:
        session = requests.Session()
        for key, value in self.cookies.items():
            session.cookies.set(key, value)
        return session


def parse_user_file(path: Path) -> list[Credential]:
    credentials: list[Credential] = []
    for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        username, separator, password = line.partition(":")
        if not separator or not username.strip() or not password.strip():
            raise ValueError(f"Invalid credentials line {index}: expected username:password")
        credentials.append(Credential(username=username.strip(), password=password.strip()))
    if not credentials:
        raise ValueError("Credentials file is empty")
    return credentials


def login_and_snapshot(
    *,
    host: str,
    username: str,
    password: str,
    verify: bool,
    timeout_seconds: int,
) -> SessionSnapshot:
    session = requests.Session()
    base = host.rstrip("/")
    session.get(f"{base}/login", timeout=timeout_seconds, verify=verify)
    response = session.post(
        f"{base}/login",
        data={"username": username, "password": password},
        timeout=timeout_seconds,
        allow_redirects=False,
        verify=verify,
    )
    if response.status_code not in {302, 303}:
        raise RuntimeError(f"Login failed for {username}: HTTP {response.status_code}")

    user_response = session.get(
        f"{base}/api/user",
        timeout=timeout_seconds,
        verify=verify,
        headers={"Accept": "application/json"},
    )
    if user_response.status_code != 200:
        raise RuntimeError(f"Authenticated user check failed for {username}: HTTP {user_response.status_code}")

    csrf_token = session.cookies.get("csrf_token", "")
    if not csrf_token:
        raise RuntimeError(f"CSRF token cookie is missing for {username}")

    return SessionSnapshot(
        username=username,
        cookies={cookie.name: cookie.value for cookie in session.cookies},
        csrf_token=csrf_token,
    )


def build_shared_session_pool(
    *,
    host: str,
    username: str,
    password: str,
    verify: bool,
    timeout_seconds: int,
    concurrency: int,
) -> list[SessionSnapshot]:
    snapshot = login_and_snapshot(
        host=host,
        username=username,
        password=password,
        verify=verify,
        timeout_seconds=timeout_seconds,
    )
    return [snapshot for _ in range(concurrency)]


def build_multi_session_pool(
    *,
    host: str,
    credentials: Iterable[Credential],
    verify: bool,
    timeout_seconds: int,
    concurrency: int,
) -> list[SessionSnapshot]:
    snapshots: list[SessionSnapshot] = []
    credential_list = list(credentials)
    if len(credential_list) < concurrency:
        raise ValueError("Not enough credentials for requested concurrency in multi-session mode")
    for credential in credential_list[:concurrency]:
        snapshots.append(
            login_and_snapshot(
                host=host,
                username=credential.username,
                password=credential.password,
                verify=verify,
                timeout_seconds=timeout_seconds,
            )
        )
    return snapshots
