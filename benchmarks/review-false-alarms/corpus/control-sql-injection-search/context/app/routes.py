from app.search import find_orders


def orders_view(conn, request):
    return {"orders": find_orders(conn, request.args["customer"])}, 200
