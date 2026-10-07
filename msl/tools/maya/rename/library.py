# tools/maya/rename/library.py
"""The words a name is built of — categories of them, a short row of favorites, the names used
last. No Qt, no Maya.

The built-in lists live here in code; once the user changes the library it lives in the config
(`library`), the way Media's presets do. Works on any MutableMapping (the tool's JsonConfig node,
a dict in the tests).
"""
from __future__ import annotations

DEFAULT_CATEGORIES = {
    "Postfixes": ["front", "back", "low", "top", "mid", "center", "hi", "twist", "side", "corner", "part",
                  "end", "geo", "grp", "jnt", "ctrl", "drv", "offset", "loc", "crv"],
    "Base": ["root", "main", "pelvis", "cog", "spine", "belly", "chest", "neck", "head"],
    "Limbs": ["shoulder", "arm", "elbow", "wrist", "hand", "thumb", "index", "middle", "ring", "pinky",
              "finger", "leg", "knee", "ankle", "foot", "toe", "wing", "tail", "tentacle"],
    "Face": ["face", "jaw", "nose", "eye", "eyelid", "brow", "ear", "teeth", "tongue", "lip"],
    "Other": ["hair", "cloth", "skirt", "sleeve", "item", "object", "squash", "stretch"],
}
DEFAULT_FAVORITES = ["loc", "geo", "grp", "jnt", "ctrl", "crv", "end"]
RECENT_KEPT = 20


class NameLibrary:
    """Categories of words, favorites and recent names over a config node."""

    def __init__(self, store):
        self._store = store

    # ------------------------------------------------------------------ categories

    def categories(self) -> dict:
        saved = self._store.get("categories")
        if isinstance(saved, dict) or hasattr(saved, "keys"):
            result = {str(name): [str(word) for word in (words or [])] for name, words in dict(saved).items()}
            if result:
                return result
        return {name: list(words) for name, words in DEFAULT_CATEGORIES.items()}

    def _save_categories(self, categories: dict) -> None:
        self._store["categories"] = {name: list(words) for name, words in categories.items()}

    def words(self) -> list[str]:
        """Every word once, in the library's order (favorites and recent ones after): for completion."""
        seen, result = set(), []
        for words in list(self.categories().values()) + [self.favorites()]:
            for word in words:
                if word not in seen:
                    seen.add(word)
                    result.append(word)
        return result

    def add_word(self, category: str, word: str) -> bool:
        word = word.strip()
        categories = self.categories()
        if not word or category not in categories or word in categories[category]:
            return False
        categories[category].append(word)
        self._save_categories(categories)
        return True

    def remove_word(self, category: str, word: str) -> None:
        categories = self.categories()
        if word in categories.get(category, []):
            categories[category].remove(word)
            self._save_categories(categories)

    def rename_word(self, category: str, old: str, new: str) -> bool:
        new = new.strip()
        categories = self.categories()
        words = categories.get(category, [])
        if not new or old not in words or (new != old and new in words):
            return False
        words[words.index(old)] = new
        self._save_categories(categories)
        return True

    def move_word(self, category: str, word: str, target: str, before: str = "") -> None:
        """`word` into `target` (another category or the same), before `before` ("" = at the end)."""
        categories = self.categories()
        if word not in categories.get(category, []) or target not in categories:
            return
        categories[category].remove(word)
        words = categories[target]
        if word in words:
            words.remove(word)
        index = words.index(before) if before in words else len(words)
        words.insert(index, word)
        self._save_categories(categories)

    def add_category(self, name: str) -> bool:
        name = name.strip()
        categories = self.categories()
        if not name or name in categories:
            return False
        categories[name] = []
        self._save_categories(categories)
        return True

    def remove_category(self, name: str) -> None:
        categories = self.categories()
        if name in categories and len(categories) > 1:
            del categories[name]
            self._save_categories(categories)

    def rename_category(self, old: str, new: str) -> bool:
        new = new.strip()
        categories = self.categories()
        if not new or old not in categories or (new != old and new in categories):
            return False
        self._save_categories({(new if name == old else name): words for name, words in categories.items()})
        return True

    def duplicates(self) -> dict:
        """{word: [categories]} for words that sit in more than one category."""
        where: dict = {}
        for name, words in self.categories().items():
            for word in words:
                where.setdefault(word, []).append(name)
        return {word: names for word, names in where.items() if len(names) > 1}

    def reset(self) -> None:
        """Back to the built-in lists and favorites (recent names stay)."""
        for key in ("categories", "favorites"):
            if key in self._store:
                del self._store[key]

    # ------------------------------------------------------------------ favorites

    def favorites(self) -> list[str]:
        saved = self._store.get("favorites")
        if saved is None:
            return list(DEFAULT_FAVORITES)
        return [str(word) for word in saved]

    def set_favorites(self, words: list[str]) -> None:
        seen, result = set(), []
        for word in words:
            word = str(word).strip()
            if word and word not in seen:
                seen.add(word)
                result.append(word)
        self._store["favorites"] = result

    def add_favorite(self, word: str) -> bool:
        words = self.favorites()
        if not word.strip() or word in words:
            return False
        self.set_favorites(words + [word])
        return True

    def remove_favorite(self, word: str) -> None:
        self.set_favorites([each for each in self.favorites() if each != word])

    # ------------------------------------------------------------------ recent

    def recent(self) -> list[str]:
        """Templates the user renamed with, newest first."""
        return [str(text) for text in (self._store.get("recent") or [])]

    def remember(self, template: str) -> None:
        template = template.strip()
        if not template:
            return
        texts = [template] + [text for text in self.recent() if text != template]
        self._store["recent"] = texts[:RECENT_KEPT]

    def forget(self, template: str = "") -> None:
        """One recent name out ("" = all of them)."""
        self._store["recent"] = [text for text in self.recent() if template and text != template]
