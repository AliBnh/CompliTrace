from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import perf_counter

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


@dataclass
class _Sample:
    name: str
    value: float


class _Registry:
    def __init__(self) -> None:
        self._samples: dict[str, _Sample] = {}
        self._lock = Lock()

    def set(self, name: str, value: float) -> None:
        with self._lock:
            self._samples[name] = _Sample(name=name, value=value)

    def inc(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            sample = self._samples.get(name)
            if sample is None:
                self._samples[name] = _Sample(name=name, value=amount)
            else:
                sample.value += amount

    def render(self) -> bytes:
        with self._lock:
            lines = [f"{sample.name} {sample.value}" for sample in self._samples.values()]
        return ("\n".join(lines) + "\n").encode("utf-8")


_REGISTRY = _Registry()


class Counter:
    def __init__(self, name: str, _documentation: str, labelnames: tuple[str, ...] | list[str] | None = None):
        self._name = name
        self._labelnames = tuple(labelnames or ())
        _REGISTRY.set(self._name, 0.0)

    def inc(self, amount: float = 1.0) -> None:
        _REGISTRY.inc(self._name, amount)

    def labels(self, **labels: str):
        if self._labelnames:
            suffix = "_" + "_".join(str(labels.get(name, "")) for name in self._labelnames)
            return _LabeledCounter(f"{self._name}{suffix}")
        return self


class _LabeledCounter:
    def __init__(self, name: str):
        self._name = name
        _REGISTRY.set(self._name, 0.0)

    def inc(self, amount: float = 1.0) -> None:
        _REGISTRY.inc(self._name, amount)


class Histogram:
    def __init__(self, name: str, _documentation: str):
        self._name = name
        _REGISTRY.set(self._name, 0.0)

    def observe(self, value: float) -> None:
        _REGISTRY.set(self._name, value)

    def time(self):
        histogram = self

        class _Timer:
            def __enter__(self_inner):
                self_inner._start = perf_counter()
                return self_inner

            def __exit__(self_inner, _exc_type, _exc, _tb):
                histogram.observe(perf_counter() - self_inner._start)

        return _Timer()


def generate_latest() -> bytes:
    return _REGISTRY.render()
