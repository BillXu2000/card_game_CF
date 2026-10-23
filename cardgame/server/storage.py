"""Tiny JSON-file persistence under the data directory."""
from __future__ import annotations

import json
import os
from pathlib import Path


class Storage:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        (self.root / "rooms").mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def load_json(self, rel: str):
        p = self.path(rel)
        if not p.exists():
            return None
        with p.open(encoding="utf-8") as f:
            return json.load(f)

    def save_json(self, rel: str, data) -> None:
        p = self.path(rel)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)

    def append_jsonl(self, rel: str, record) -> None:
        with self.path(rel).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def load_jsonl(self, rel: str) -> list:
        p = self.path(rel)
        if not p.exists():
            return []
        out = []
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        break  # torn write at the end of the file
        return out

    def write_jsonl(self, rel: str, records) -> None:
        p = self.path(rel)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp, p)

    def delete(self, rel: str) -> None:
        try:
            self.path(rel).unlink()
        except FileNotFoundError:
            pass
