import sqlite3

SORTABLE = {
    "name": "customers.name",
    "created": "customers.created_at",
    "spend": "totals.lifetime_spend",
}


def list_customers(
    conn: sqlite3.Connection, region: str, sort: str = "name", descending: bool = False
) -> list[tuple]:
    try:
        column = SORTABLE[sort]
    except KeyError:
        raise ValueError(f"cannot sort by {sort!r}") from None
    direction = "DESC" if descending else "ASC"
    query = (
        "SELECT customers.name, customers.created_at, totals.lifetime_spend "
        "FROM customers JOIN totals ON totals.customer_id = customers.id "
        "WHERE customers.region = ? "
        "ORDER BY " + column + " " + direction
    )
    return conn.execute(query, (region,)).fetchall()
