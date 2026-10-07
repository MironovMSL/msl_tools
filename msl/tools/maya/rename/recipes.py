# tools/maya/rename/recipes.py
"""Recipes: a way of naming kept under a name — the template with its numbering (start, step,
digits, order, "end") — applied with one click. No Qt, no Maya.

The built-in ones live here in code; once the user saves or removes one, the set lives in the
config (`recipes`), the way the name library does."""
from __future__ import annotations

from msl_tools.msl.tools.maya.rename import rules

KEYS = ("template", "start", "step", "padding", "order", "end_last")
DEFAULT_RECIPES = {
    "Fingers": {"template": "{side}_finger_{A}_{#}_jnt", "start": 1, "step": 1, "padding": 2,
                "order": rules.ORDER_CHAINS, "end_last": True},
    "Spine": {"template": "spine_{#}_jnt", "start": 1, "step": 1, "padding": 2, "order": rules.ORDER_CHAINS,
              "end_last": True},
    "Controls": {"template": "{side}_{name}_ctrl", "start": 1, "step": 1, "padding": 2,
                 "order": rules.ORDER_SELECTION, "end_last": False},
    "Offset groups": {"template": "{parent}_offset", "start": 1, "step": 1, "padding": 2,
                      "order": rules.ORDER_SELECTION, "end_last": False},
    "Numbered": {"template": "{name}_{#}", "start": 1, "step": 1, "padding": 2, "order": rules.ORDER_SELECTION,
                 "end_last": False},
}


class RecipeStore:
    """The recipes over a config node (a dict in the tests)."""

    def __init__(self, store, key: str = "recipes"):
        self._store = store
        self._key = key

    def all(self) -> dict:
        saved = self._store.get(self._key)
        if saved is not None and (isinstance(saved, dict) or hasattr(saved, "keys")):
            return {str(name): self._clean(values) for name, values in dict(saved).items()}
        return {name: dict(values) for name, values in DEFAULT_RECIPES.items()}

    @staticmethod
    def _clean(values) -> dict:
        values = dict(values or {})
        return {key: values[key] for key in KEYS if key in values}

    def save(self, name: str, values: dict) -> None:
        recipes = self.all()
        recipes[name.strip()] = self._clean(values)
        self._store[self._key] = recipes

    def remove(self, name: str) -> None:
        recipes = self.all()
        recipes.pop(name, None)
        self._store[self._key] = recipes

    def reset(self) -> None:
        if self._key in self._store:
            del self._store[self._key]

    def matching(self, values: dict) -> list[str]:
        """The recipes whose every setting is the one given (to mark them)."""
        wanted = self._clean(values)
        return [name for name, recipe in self.all().items()
                if recipe and all(wanted.get(key) == value for key, value in recipe.items())]
