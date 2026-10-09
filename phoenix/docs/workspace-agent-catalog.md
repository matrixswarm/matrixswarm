# Agent picker metadata

The Swarm Workspace agent picker uses the files in `agents_meta` as its
catalog. Each entry provides a short description, keywords and groups:

```json
{
    "name": "rsync_boy",
    "description": "Schedules filesystem snapshots, MySQL dumps and isolated restore drills with separate success records.",
    "keywords": ["backup", "recovery", "filesystem", "database", "ssh", "schedule"],
    "groups": ["backup"]
}
```

Controls above the picker offer a group selector, clickable keywords, text
search, a match count and **Clear filters**. Multiple selected keywords use OR:
selecting `ssh` and `backup` shows an agent with either keyword. A selected group
and search text further narrow that result. With no filters, all available
agents are shown. Filtering does not remove agents already on the canvas.

Hover either a picker entry or a workspace node for its description, groups
and keywords. Tooltip text is escaped before display. Reopen a workspace after
editing catalog files to load the new descriptions. Existing deployment and
agent configuration data is independent of these presentation fields.

Both metadata generator tools preserve supplied descriptions, keywords and
groups. Catalog metadata is curated; generators do not invent descriptions.
