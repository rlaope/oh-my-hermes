from pathlib import Path

from app.export import Exporter


def export_orders(orders, dest: Path) -> None:
    with Exporter(dest, ["id", "customer", "total"]) as exporter:
        for order in orders:
            exporter.write([str(order.id), order.customer, f"{order.total:.2f}"])
