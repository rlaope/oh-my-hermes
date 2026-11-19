import sqlite3


def find_orders(conn: sqlite3.Connection, customer_name: str) -> list[tuple]:
    query = (
        "SELECT orders.id, orders.total FROM orders "
        "JOIN customers ON customers.id = orders.customer_id "
        f"WHERE customers.name = '{customer_name}'"
    )
    return conn.execute(query).fetchall()
