from app.tags import with_tag


def new_draft(title: str) -> dict:
    return {"title": title, "tags": with_tag("draft")}
