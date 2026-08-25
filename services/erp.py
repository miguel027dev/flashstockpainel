from datetime import date, timedelta, datetime
from decimal import Decimal
from sqlalchemy import func, case
from extensions import db
from models import (
    Product, StockItem, StockMovement, SalesOrder, SalesOrderItem, OrderEvent,
    FinancialEntry, PurchaseOrder, Supplier, Installation, Lead, Commission, BankTransaction
)

D = Decimal


def recalc_order(order):
    subtotal = sum((D(str(i.quantity)) * D(str(i.unit_price)) for i in order.items), D("0"))
    cogs = sum((D(str(i.quantity)) * D(str(i.unit_cost)) for i in order.items), D("0"))
    discount_percent = D(str(order.discount_percent or 0))
    discount_amount = (subtotal * discount_percent / D("100")).quantize(D("0.01"))
    total = subtotal - discount_amount
    profit = total - cogs - D(str(order.freight_cost or 0)) - D(str(order.installation_cost or 0)) - D(str(order.commission_cost or 0))
    margin = (profit / total * D("100")) if total else D("0")
    order.subtotal = subtotal
    order.cogs = cogs
    order.discount_amount = discount_amount
    order.total = total
    order.gross_profit = profit
    order.margin_percent = margin.quantize(D("0.01"))
    return order


def add_order_event(order, user_id, event_type, message, metadata=None):
    db.session.add(OrderEvent(order_id=order.id, user_id=user_id, event_type=event_type, message=message, metadata_json=metadata or {}))


def reserve_order_stock(order):
    for item in order.items:
        stock = StockItem.query.filter_by(product_id=item.product_id, establishment_id=order.establishment_id).first()
        if not stock:
            stock = StockItem(product_id=item.product_id, establishment_id=order.establishment_id, quantity_physical=0, quantity_reserved=0)
            db.session.add(stock)
            db.session.flush()
        stock.quantity_reserved = D(str(stock.quantity_reserved or 0)) + D(str(item.quantity))
        db.session.add(StockMovement(
            product_id=item.product_id, establishment_id=order.establishment_id, movement_type="RESERVA",
            quantity=item.quantity, reference_type="PEDIDO", reference_id=order.id, notes=f"Reserva do pedido {order.number}"
        ))


def release_order_stock(order):
    for item in order.items:
        stock = StockItem.query.filter_by(product_id=item.product_id, establishment_id=order.establishment_id).first()
        if stock:
            stock.quantity_reserved = max(D("0"), D(str(stock.quantity_reserved or 0)) - D(str(item.quantity)))


def consume_order_stock(order):
    for item in order.items:
        stock = StockItem.query.filter_by(product_id=item.product_id, establishment_id=order.establishment_id).first()
        if stock:
            stock.quantity_reserved = max(D("0"), D(str(stock.quantity_reserved or 0)) - D(str(item.quantity)))
            stock.quantity_physical = D(str(stock.quantity_physical or 0)) - D(str(item.quantity))
            db.session.add(StockMovement(
                product_id=item.product_id, establishment_id=order.establishment_id, movement_type="SAIDA_VENDA",
                quantity=-D(str(item.quantity)), reference_type="PEDIDO", reference_id=order.id, notes=f"Saída do pedido {order.number}"
            ))


def dashboard_metrics():
    today = date.today()
    month_start = today.replace(day=1)
    sales_month = db.session.query(func.coalesce(func.sum(SalesOrder.total), 0)).filter(SalesOrder.created_at >= month_start, SalesOrder.status != "CANCELADO").scalar()
    profit_month = db.session.query(func.coalesce(func.sum(SalesOrder.gross_profit), 0)).filter(SalesOrder.created_at >= month_start, SalesOrder.status != "CANCELADO").scalar()
    orders_month = SalesOrder.query.filter(SalesOrder.created_at >= month_start, SalesOrder.status != "CANCELADO").count()
    receivable = db.session.query(func.coalesce(func.sum(FinancialEntry.amount), 0)).filter_by(entry_type="RECEBER", status="ABERTO").scalar()
    payable = db.session.query(func.coalesce(func.sum(FinancialEntry.amount), 0)).filter_by(entry_type="PAGAR", status="ABERTO").scalar()
    low_stock = 0
    for s in StockItem.query.join(Product).filter(Product.active.is_(True)).all():
        if D(str(s.available)) <= D(str(s.product.minimum_stock or 0)):
            low_stock += 1
    overdue = FinancialEntry.query.filter(FinancialEntry.status == "ABERTO", FinancialEntry.due_date < today).count()
    return {
        "sales_month": sales_month, "profit_month": profit_month, "orders_month": orders_month,
        "receivable": receivable, "payable": payable, "low_stock": low_stock, "overdue": overdue,
        "margin": (D(str(profit_month)) / D(str(sales_month)) * 100) if sales_month else D("0"),
    }


def pendencies():
    today = date.today()
    items = []
    for e in FinancialEntry.query.filter(FinancialEntry.status == "ABERTO", FinancialEntry.due_date < today).order_by(FinancialEntry.due_date).limit(50):
        items.append({"severity":"danger", "type":"Financeiro", "title":f"{e.entry_type.title()} vencido", "detail":f"{e.description} — R$ {e.amount}", "href":f"/financeiro/{'receber' if e.entry_type=='RECEBER' else 'pagar'}"})
    for o in SalesOrder.query.filter_by(approval_status="PENDING").order_by(SalesOrder.created_at).limit(30):
        items.append({"severity":"warning", "type":"Comercial", "title":"Desconto aguardando aprovação", "detail":f"Pedido {o.number} — {o.discount_percent}%", "href":f"/pedidos/{o.id}"})
    for s in StockItem.query.join(Product).filter(Product.active.is_(True)).all():
        if D(str(s.available)) <= D(str(s.product.minimum_stock or 0)):
            items.append({"severity":"warning", "type":"Estoque", "title":"Estoque baixo", "detail":f"{s.product.name}: {s.available} disponível", "href":"/estoque"})
    late = SalesOrder.query.filter(SalesOrder.expected_delivery_date < today, SalesOrder.status.notin_(["ENTREGUE","CANCELADO"])).limit(30).all()
    for o in late:
        items.append({"severity":"danger", "type":"Logística", "title":"Pedido atrasado", "detail":f"{o.number} — entrega prevista {o.expected_delivery_date.strftime('%d/%m/%Y')}", "href":f"/pedidos/{o.id}"})
    for i in Installation.query.filter(Installation.scheduled_at < datetime.utcnow(), Installation.status.notin_(["CONCLUIDA","CANCELADA"])).limit(30):
        items.append({"severity":"warning", "type":"Montagem", "title":"Montagem pendente", "detail":f"Montagem #{i.id}", "href":"/montagens"})
    return items[:100]


def stock_analytics():
    rows = []
    today = date.today()
    cutoff = datetime.utcnow() - timedelta(days=90)
    sold = dict(db.session.query(SalesOrderItem.product_id, func.coalesce(func.sum(SalesOrderItem.quantity),0))
                .join(SalesOrder).filter(SalesOrder.created_at >= cutoff, SalesOrder.status != "CANCELADO")
                .group_by(SalesOrderItem.product_id).all())
    last_sold = dict(db.session.query(SalesOrderItem.product_id, func.max(SalesOrder.created_at))
                     .join(SalesOrder).filter(SalesOrder.status != "CANCELADO")
                     .group_by(SalesOrderItem.product_id).all())
    for stock in StockItem.query.join(Product).order_by(Product.name).all():
        qty90 = D(str(sold.get(stock.product_id, 0)))
        avg = qty90 / D("90")
        available = D(str(stock.available))
        days_to_zero = float(available / avg) if avg > 0 and available >= 0 else None
        last = last_sold.get(stock.product_id)
        stagnant_days = (datetime.utcnow() - last).days if last else 999
        suggested = max(D("0"), D(str(stock.product.reorder_point or stock.product.minimum_stock or 0)) - available)
        rows.append({"stock":stock, "avg":avg, "days_to_zero":days_to_zero, "stagnant_days":stagnant_days, "suggested":suggested})
    return rows


def supplier_ranking():
    suppliers = Supplier.query.filter_by(active=True).all()
    rows = []
    for s in suppliers:
        orders = PurchaseOrder.query.filter_by(supplier_id=s.id).all()
        total = sum((D(str(o.total or 0)) for o in orders), D("0"))
        received = [o for o in orders if o.received_at]
        on_time = [o for o in received if not o.expected_at or o.received_at <= o.expected_at]
        punctuality = (len(on_time) / len(received) * 100) if received else None
        delays = [(o.received_at - o.expected_at).days for o in received if o.expected_at and o.received_at > o.expected_at]
        avg_delay = sum(delays) / len(delays) if delays else 0
        rows.append({"supplier":s,"orders":len(orders),"total":total,"punctuality":punctuality,"avg_delay":avg_delay})
    return sorted(rows, key=lambda r: (r["punctuality"] if r["punctuality"] is not None else -1, r["total"]), reverse=True)
