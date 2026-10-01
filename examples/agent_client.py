"""External agent client: environment secrets, TLS, no browser session, bounded complete reads."""

import os
import httpx


class LibraryClient:
    def __init__(self, base_url, token, max_context_chars=200000):
        if not base_url.startswith("https://"):
            raise ValueError("External agent access requires HTTPS")
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        )
        self.max_context_chars = max_context_chars

    def close(self):
        self.http.close()

    def get(self, path, **params):
        if not path.startswith("/api/agent/"):
            raise ValueError("Only scoped agent routes may be used")
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def search(self, query):
        return self.get("/api/agent/search", q=query)["items"]

    def get_lesson(self, id):
        # Whole short lesson; if manifest returned, lossless original element parts.
        result = self.get(
            "/api/agent/get_lesson/" + id, max_chars=min(500000, self.max_context_chars)
        )
        if result.get("content_complete"):
            return result
        parts = self.get(result["parts_url"])["items"]
        bodies = []
        total = 0
        for p in parts:
            chunk = self.get("/api/agent/parts/" + p["id"])
            total += len(chunk["content"])
            if total > self.max_context_chars:
                raise ValueError(
                    "Whole lesson exceeds caller context. Read individual parts; never truncate or claim complete coverage."
                )
            bodies.append(chunk)
        return {
            "tool": "get_lesson",
            "node_id": id,
            "content_complete": True,
            "parts": bodies,
            "content": "\n\n".join(p["content"] for p in bodies),
        }


if __name__ == "__main__":
    client = LibraryClient(os.environ["LIBRARY_URL"], os.environ["LIBRARY_TOKEN"])
    try:
        for item in client.search(os.environ.get("LIBRARY_QUERY", "الحرارة")):
            print(item["id"], item.get("title", ""))
    finally:
        client.close()
