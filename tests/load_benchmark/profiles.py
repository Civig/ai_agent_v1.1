from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    concurrency: int
    recommended_mode: str
    default_ramp_up_seconds: int
    default_max_time_seconds: int
    default_warmup: bool
    default_quiet_window_seconds: int
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PROFILE_FILE = Path(__file__).with_name("profiles.json")
EXPECTED_PROFILE_NAMES = ("5", "10", "20", "50", "100", "200")


def _validate_profile_payload(payload: dict[str, object]) -> BenchmarkProfile:
    profile = BenchmarkProfile(
        name=str(payload["name"]),
        concurrency=int(payload["concurrency"]),
        recommended_mode=str(payload["recommended_mode"]),
        default_ramp_up_seconds=int(payload["default_ramp_up_seconds"]),
        default_max_time_seconds=int(payload["default_max_time_seconds"]),
        default_warmup=bool(payload["default_warmup"]),
        default_quiet_window_seconds=int(payload["default_quiet_window_seconds"]),
        notes=str(payload.get("notes") or ""),
    )
    if profile.name != str(profile.concurrency):
        raise ValueError(f"Profile {profile.name} must match concurrency {profile.concurrency}")
    if profile.concurrency <= 0:
        raise ValueError(f"Profile {profile.name} must have positive concurrency")
    if profile.recommended_mode not in {"shared-session", "multi-session"}:
        raise ValueError(f"Profile {profile.name} has invalid recommended_mode")
    if profile.default_ramp_up_seconds < 0 or profile.default_max_time_seconds <= 0:
        raise ValueError(f"Profile {profile.name} has invalid timing values")
    if profile.default_quiet_window_seconds < 0:
        raise ValueError(f"Profile {profile.name} has invalid quiet window")
    return profile


def load_profiles(profile_path: Path | None = None) -> dict[str, BenchmarkProfile]:
    source = profile_path or PROFILE_FILE
    raw = json.loads(source.read_text(encoding="utf-8"))
    items = raw.get("profiles")
    if not isinstance(items, list):
        raise ValueError("profiles.json must contain a 'profiles' list")

    profiles: dict[str, BenchmarkProfile] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each profile entry must be an object")
        profile = _validate_profile_payload(item)
        if profile.name in profiles:
            raise ValueError(f"Duplicate profile name: {profile.name}")
        profiles[profile.name] = profile

    if tuple(profiles.keys()) != EXPECTED_PROFILE_NAMES:
        raise ValueError(
            "profiles.json must define exactly profiles "
            + ", ".join(EXPECTED_PROFILE_NAMES)
        )
    return profiles


def get_profile(name: str, profile_path: Path | None = None) -> BenchmarkProfile:
    profiles = load_profiles(profile_path=profile_path)
    try:
        return profiles[str(name)]
    except KeyError as exc:
        raise KeyError(f"Unknown benchmark profile: {name}") from exc
