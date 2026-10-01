"""Bounded process-local immutable-file cache; authorization is checked before lookup."""

from collections import OrderedDict
from threading import RLock
import time


class ContentCache:
    def __init__(self, max_bytes=8_000_000, max_entries=64, ttl=300):
        self.items = OrderedDict()
        self.size = 0
        self.lock = RLock()
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl = ttl
        self.hits = self.misses = self.evictions = 0

    def metrics(self):
        with self.lock:
            return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions, "bytes": self.size, "entries": len(self.items), "scope": "process-local immutable published files; not provider prompt cache"}

    def clear(self):
        with self.lock:
            self.items.clear()
            self.size = 0

    def read(self, path, store):
        with self.lock:
            entry = self.items.pop(path, None)
            if entry:
                self.size -= entry[2]
                if entry[0] + self.ttl > time.monotonic():
                    self.items[path] = entry
                    self.size += entry[2]
                    self.hits += 1
                    return entry[1]
            self.misses += 1
            text = store.read(path).decode()
            size = len(text.encode())
            if size <= self.max_bytes:
                while self.items and (
                    self.size + size > self.max_bytes
                    or len(self.items) >= self.max_entries
                ):
                    self.evictions += 1
                    self.size -= self.items.popitem(last=False)[1][2]
                self.items[path] = (time.monotonic(), text, size)
                self.size += size
            return text
