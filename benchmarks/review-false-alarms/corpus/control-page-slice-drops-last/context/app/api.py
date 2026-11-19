from app.pagination import page


def list_view(items, request):
    number = int(request.args.get("page", 1))
    return {"items": page(items, number, 20), "page": number}
