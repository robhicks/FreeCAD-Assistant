# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import os

# Modules to introspect at runtime inside FreeCAD
_MODULES = ["FreeCAD", "FreeCADGui", "Part", "PartDesign", "Sketcher", "Draft", "Mesh"]


def introspect_modules():
    """Introspect FreeCAD modules and extract API documentation chunks.

    Must be called inside FreeCAD's Python interpreter.
    Returns list of chunk dicts.
    """
    chunks = []
    for mod_name in _MODULES:
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue

        for attr_name in sorted(dir(mod)):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
            except Exception:
                continue

            doc = getattr(obj, "__doc__", None) or ""
            if not doc.strip():
                continue

            # Truncate very long docstrings
            if len(doc) > 1500:
                doc = doc[:1500] + "..."

            chunk_id = f"api:{mod_name}.{attr_name}"
            text = f"{mod_name}.{attr_name}\n\n{doc.strip()}"

            tags = [mod_name]
            if callable(obj):
                tags.append("callable")
            if isinstance(obj, type):
                tags.append("class")

            chunks.append({
                "id": chunk_id,
                "text": text,
                "metadata": {
                    "module": mod_name,
                    "type": "api",
                    "tags": tags,
                },
            })

    return chunks


def load_recipes():
    """Load curated code recipes from recipes.json.

    Returns list of chunk dicts.
    """
    recipes_path = os.path.join(os.path.dirname(__file__), "recipes.json")
    if not os.path.exists(recipes_path):
        return []

    with open(recipes_path, "r", encoding="utf-8") as f:
        recipes = json.load(f)

    chunks = []
    for i, recipe in enumerate(recipes):
        title = recipe.get("title", f"Recipe {i}")
        code = recipe.get("code", "")
        description = recipe.get("description", "")
        tags = recipe.get("tags", [])

        text = f"{title}\n\n{description}\n\n```python\n{code}\n```"
        chunk_id = f"recipe:{i}:{title.lower().replace(' ', '_')[:40]}"

        chunks.append({
            "id": chunk_id,
            "text": text,
            "metadata": {
                "module": tags[0] if tags else "general",
                "type": "recipe",
                "tags": tags,
            },
        })

    return chunks


def build_chunks():
    """Build unified chunk list from API introspection and recipes."""
    chunks = introspect_modules()
    chunks.extend(load_recipes())
    return chunks
