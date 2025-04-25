from typing import TypeVar, Generic
import threading

K = TypeVar("K")
V = TypeVar("V")


class ThreadSafeDict(Generic[K, V]):
    """
    A thread-safe dictionary. Thread-safe iteration is exposed via the context
    manager.
    """

    def __init__(self):
        self._dict: dict[K, V] = {}
        self._lock = threading.Lock()

    def get(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            return self._dict.get(key, default)

    def set(self, key: K, value: V) -> None:
        with self._lock:
            self._dict[key] = value

    def delete(self, key: K) -> None:
        with self._lock:
            if key in self._dict:
                del self._dict[key]

    def items(self) -> list[tuple[K, V]]:
        with self._lock:
            return list(self._dict.items())

    def keys(self) -> list[K]:
        with self._lock:
            return list(self._dict.keys())

    def values(self) -> list[V]:
        with self._lock:
            return list(self._dict.values())

    def __contains__(self, key: K) -> bool:
        with self._lock:
            return key in self._dict

    def __len__(self) -> int:
        with self._lock:
            return len(self._dict)

    def __enter__(self) -> dict[K, V]:
        self._lock.acquire()
        return self._dict

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
