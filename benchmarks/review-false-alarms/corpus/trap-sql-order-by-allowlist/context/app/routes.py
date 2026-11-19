from app.reports import list_customers


def customers_view(conn, request):
    sort = request.args.get("sort", "name")
    descending = request.args.get("order") == "desc"
    try:
        rows = list_customers(conn, request.args["region"], sort, descending)
    except ValueError as error:
        return {"error": str(error)}, 400
    return {"rows": rows}, 200
