"""Presentation metadata shared by the agent picker and workspace canvas."""

from html import escape


def catalog_values(meta, field):
    values = meta.get(field, [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return set()
    return {value.strip().casefold() for value in values
            if isinstance(value, str) and value.strip()}


def agent_tooltip(meta):
    name = str(meta.get("name") or "Agent")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        description = "No description has been provided for this agent."
    parts = [f"<b>{escape(name)}</b>", escape(description.strip()).replace("\n", "<br>")]
    for field, title in (("groups", "Groups"), ("keywords", "Keywords")):
        values = sorted(catalog_values(meta, field))
        if values:
            parts.append(f"{title}: {escape(', '.join(values))}")
    return "<br><br>".join(parts)
