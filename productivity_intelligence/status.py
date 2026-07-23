"""In-process capability status exposed by the readiness endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CapabilityRegistry:
    expected: set[str] = field(default_factory=set)
    loaded: set[str] = field(default_factory=set)
    unavailable: dict[str, str] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def configure(self, expected: set[str]) -> None:
        with self._lock:
            self.expected = set(expected)

    def mark_loaded(self, name: str) -> None:
        with self._lock:
            self.loaded.add(name)
            self.unavailable.pop(name, None)

    def mark_unavailable(self, name: str, reason: str) -> None:
        with self._lock:
            self.loaded.discard(name)
            self.unavailable[name] = reason

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            missing = sorted(self.expected - self.loaded)
            return {
                "ready": not missing,
                "expected_agents": sorted(self.expected),
                "loaded_agents": sorted(self.loaded),
                "missing_agents": missing,
                "unavailable": {
                    name: self.unavailable.get(name, "not loaded") for name in missing
                },
            }


capabilities = CapabilityRegistry()
