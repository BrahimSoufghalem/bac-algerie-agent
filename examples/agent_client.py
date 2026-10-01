"""External agent client: environment secrets, TLS, no browser session, bounded complete reads."""

import os, json
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

        def bounded(payload):
            if (
                len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                > self.max_context_chars
            ):
                raise ValueError(
                    "Whole serialized lesson exceeds caller context. Read individual complete parts; never truncate or claim complete coverage."
                )
            return payload

        if result.get("content_complete"):
            return bounded(result)
        parts = self.get(result["parts_url"])["items"]
        assembled = {
            "tool": "get_lesson",
            "node_id": id,
            "content_complete": False,
            "content": "",
            "part_ids": [],
            "assets": [],
            "sources": [],
        }
        seen = {"assets": set(), "sources": set()}
        for p in parts:
            chunk = self.get("/api/agent/parts/" + p["id"])
            if not assembled["part_ids"]:
                assembled.update(
                    {
                        k: chunk[k]
                        for k in ("node", "document", "ancestors")
                        if k in chunk
                    }
                )
            assembled["content"] += ("\n\n" if assembled["part_ids"] else "") + chunk[
                "content"
            ]
            assembled["part_ids"].append(p["id"])
            for field, key in (("assets", "id"), ("sources", "source_id")):
                for item in chunk.get(field, []):
                    identity = item.get(key) or json.dumps(item, sort_keys=True)
                    if identity not in seen[field]:
                        seen[field].add(identity)
                        assembled[field].append(item)
            bounded(assembled)
        if not parts:
            raise ValueError(
                "No lossless lesson parts available; do not claim complete coverage"
            )
        assembled["content_complete"] = True
        return bounded(assembled)


if __name__ == "__main__":
    client = LibraryClient(os.environ["LIBRARY_URL"], os.environ["LIBRARY_TOKEN"])
    try:
        for item in client.search(os.environ.get("LIBRARY_QUERY", "الحرارة")):
            print(item["id"], item.get("title", ""))
    finally:
        client.close()
