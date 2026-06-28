from pathlib import Path
import json


class JsonFile:
    @staticmethod
    def read(path: str | Path) -> dict:
        path = Path(path)

        if not path.exists():
            return {}

        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def write(path: str | Path, data: dict) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)