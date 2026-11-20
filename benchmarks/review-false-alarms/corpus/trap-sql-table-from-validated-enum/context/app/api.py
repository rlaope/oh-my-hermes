from app.events import count_events
from app.kinds import EventKind


def event_count_view(conn, request):
    try:
        kind = EventKind(request.args["kind"])
    except (KeyError, ValueError):
        return {"error": "kind must be one of: click, view, purchase"}, 400
    since = request.args.get("since", "1970-01-01")
    return {"count": count_events(conn, kind, since)}, 200
