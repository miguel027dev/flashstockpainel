from datetime import datetime, date
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


def now():
    return datetime.utcnow()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)


class Company(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    trade_name = db.Column(db.String(160))
    document = db.Column(db.String(32))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    address = db.Column(db.String(255))


class Establishment(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(40), unique=True)
    address = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True, nullable=False)


class Department(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)


class JobTitle(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)


class Role(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    discount_limit = db.Column(db.Numeric(5, 2), default=Decimal("5.00"), nullable=False)


class User(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"))
    job_title_id = db.Column(db.Integer, db.ForeignKey("job_title.id"))
    establishment_id = db.Column(db.Integer, db.ForeignKey("establishment.id"))
    role = db.relationship("Role")
    department = db.relationship("Department")
    job_title = db.relationship("JobTitle")
    establishment = db.relationship("Establishment")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return bool(self.role and self.role.name.upper() in {"ADMIN", "DIRETOR"})


class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    group_name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))


class UserAccessProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    customized = db.Column(db.Boolean, default=True, nullable=False)
    user = db.relationship("User", backref=db.backref("access_profile", uselist=False))


class UserPermission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey("permission.id", ondelete="CASCADE"), nullable=False)
    user = db.relationship("User", backref=db.backref("permission_links", cascade="all, delete-orphan"))
    permission = db.relationship("Permission")
    __table_args__ = (db.UniqueConstraint("user_id", "permission_id", name="uq_user_permission"),)


class Employee(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    document = db.Column(db.String(32))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"))
    job_title_id = db.Column(db.Integer, db.ForeignKey("job_title.id"))
    active = db.Column(db.Boolean, default=True)
    department = db.relationship("Department")
    job_title = db.relationship("JobTitle")


class Customer(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    document = db.Column(db.String(32), index=True)
    phone = db.Column(db.String(40), index=True)
    email = db.Column(db.String(160))
    zip_code = db.Column(db.String(12))
    address = db.Column(db.String(255))
    neighborhood = db.Column(db.String(120))
    city = db.Column(db.String(120))
    state = db.Column(db.String(2))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)


class Supplier(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    document = db.Column(db.String(32))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    lead_time_days = db.Column(db.Integer, default=7)
    active = db.Column(db.Boolean, default=True)


class Product(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(120))
    subcategory = db.Column(db.String(120))
    brand = db.Column(db.String(120))
    model = db.Column(db.String(120))
    color = db.Column(db.String(80))
    unit = db.Column(db.String(30), default="UN")
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"))
    sale_price = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    cost_price = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    minimum_stock = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    reorder_point = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    location_code = db.Column(db.String(80))
    active = db.Column(db.Boolean, default=True)
    supplier = db.relationship("Supplier")

    @property
    def cover_image(self):
        if not getattr(self, "images", None):
            return None
        return next((img for img in self.images if img.cover), self.images[0])


class ProductPresentation(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, unique=True)
    description = db.Column(db.Text)
    material = db.Column(db.String(180))
    finish = db.Column(db.String(180))
    width_min = db.Column(db.Numeric(10, 2), default=0)
    width_max = db.Column(db.Numeric(10, 2), default=0)
    height_min = db.Column(db.Numeric(10, 2), default=0)
    height_max = db.Column(db.Numeric(10, 2), default=0)
    depth_min = db.Column(db.Numeric(10, 2), default=0)
    depth_max = db.Column(db.Numeric(10, 2), default=0)
    production_days = db.Column(db.Integer)
    featured = db.Column(db.Boolean, default=False, nullable=False)
    public_visible = db.Column(db.Boolean, default=True, nullable=False)
    catalog_note = db.Column(db.String(255))
    product = db.relationship("Product", backref=db.backref("presentation", uselist=False, cascade="all, delete-orphan"))


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = db.Column(db.String(255))
    content_type = db.Column(db.String(80), default="image/webp", nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    cover = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    product = db.relationship("Product", backref=db.backref("images", cascade="all, delete-orphan", order_by="ProductImage.sort_order, ProductImage.id"))


class PublicQuote(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(160))
    city = db.Column(db.String(120))
    neighborhood = db.Column(db.String(120))
    notes = db.Column(db.Text)
    status = db.Column(db.String(30), default="NOVO", nullable=False, index=True)
    source = db.Column(db.String(40), default="CATALOGO", nullable=False)
    items = db.relationship("PublicQuoteItem", backref="quote", cascade="all, delete-orphan")


class PublicQuoteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey("public_quote.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), default=1, nullable=False)
    product = db.relationship("Product")


class StockItem(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    establishment_id = db.Column(db.Integer, db.ForeignKey("establishment.id"), nullable=False)
    quantity_physical = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    quantity_reserved = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    product = db.relationship("Product")
    establishment = db.relationship("Establishment")
    __table_args__ = (db.UniqueConstraint("product_id", "establishment_id", name="uq_stock_product_est"),)

    @property
    def available(self):
        return (self.quantity_physical or 0) - (self.quantity_reserved or 0)


class StockMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    establishment_id = db.Column(db.Integer, db.ForeignKey("establishment.id"), nullable=False)
    movement_type = db.Column(db.String(40), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    reference_type = db.Column(db.String(40))
    reference_id = db.Column(db.Integer)
    notes = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    product = db.relationship("Product")
    establishment = db.relationship("Establishment")
    user = db.relationship("User")


class SalesOrder(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    establishment_id = db.Column(db.Integer, db.ForeignKey("establishment.id"), nullable=False)
    status = db.Column(db.String(40), default="NOVO", nullable=False, index=True)
    subtotal = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    discount_amount = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    freight_cost = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    installation_cost = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    commission_cost = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    cogs = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    total = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    gross_profit = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    margin_percent = db.Column(db.Numeric(6, 2), default=0, nullable=False)
    approval_status = db.Column(db.String(30), default="APPROVED", nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    blocked = db.Column(db.Boolean, default=False, nullable=False)
    block_reason = db.Column(db.String(255))
    expected_delivery_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    customer = db.relationship("Customer")
    seller = db.relationship("User", foreign_keys=[seller_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    establishment = db.relationship("Establishment")
    items = db.relationship("SalesOrderItem", backref="order", cascade="all, delete-orphan")


class SalesOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(14, 2), nullable=False)
    picked_quantity = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    product = db.relationship("Product")


class OrderEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    event_type = db.Column(db.String(60), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    metadata_json = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    user = db.relationship("User")


class ReturnRequest(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"))
    kind = db.Column(db.String(30), default="DEVOLUCAO")
    reason = db.Column(db.String(255))
    status = db.Column(db.String(30), default="ABERTA")
    order = db.relationship("SalesOrder")


class PurchaseOrder(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False)
    status = db.Column(db.String(30), default="ABERTO")
    ordered_at = db.Column(db.Date, default=date.today)
    expected_at = db.Column(db.Date)
    received_at = db.Column(db.Date)
    total = db.Column(db.Numeric(14, 2), default=0)
    supplier = db.relationship("Supplier")
    items = db.relationship("PurchaseOrderItem", backref="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey("purchase_order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(14, 2), nullable=False)
    product = db.relationship("Product")


class FinancialAccount(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    account_type = db.Column(db.String(40), default="CAIXA")
    bank_name = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)


class FinancialEntry(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(20), nullable=False)  # RECEBER/PAGAR
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    paid_at = db.Column(db.Date)
    status = db.Column(db.String(30), default="ABERTO", nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"))
    purchase_order_id = db.Column(db.Integer, db.ForeignKey("purchase_order.id"))
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"))
    account_id = db.Column(db.Integer, db.ForeignKey("financial_account.id"))
    category = db.Column(db.String(120))
    cost_center = db.Column(db.String(120))
    order = db.relationship("SalesOrder")
    customer = db.relationship("Customer")
    supplier = db.relationship("Supplier")
    account = db.relationship("FinancialAccount")


class BankTransaction(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("financial_account.id"))
    external_id = db.Column(db.String(120), index=True)
    tx_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    reconciled_entry_id = db.Column(db.Integer, db.ForeignKey("financial_entry.id"))
    source = db.Column(db.String(30), default="OFX")
    account = db.relationship("FinancialAccount")
    reconciled_entry = db.relationship("FinancialEntry")


class Commission(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    base_amount = db.Column(db.Numeric(14, 2), nullable=False)
    percent = db.Column(db.Numeric(5, 2), default=3)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(30), default="PREVISTA")
    order = db.relationship("SalesOrder")
    user = db.relationship("User")


class Lead(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    stage = db.Column(db.String(40), default="NOVO", nullable=False)
    estimated_value = db.Column(db.Numeric(14, 2), default=0)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    next_follow_up = db.Column(db.Date)
    lost_reason = db.Column(db.String(160))
    notes = db.Column(db.Text)
    owner = db.relationship("User")


class ServiceOrder(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"))
    service_type = db.Column(db.String(80), default="MONTAGEM")
    status = db.Column(db.String(30), default="ABERTA")
    scheduled_date = db.Column(db.Date)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    value = db.Column(db.Numeric(14, 2), default=0)
    notes = db.Column(db.Text)
    customer = db.relationship("Customer")
    order = db.relationship("SalesOrder")
    assigned_user = db.relationship("User")


class Installation(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    service_order_id = db.Column(db.Integer, db.ForeignKey("service_order.id"))
    installer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    scheduled_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="AGENDADA")
    checklist_product = db.Column(db.Boolean, default=False)
    checklist_parts = db.Column(db.Boolean, default=False)
    checklist_leveling = db.Column(db.Boolean, default=False)
    checklist_alignment = db.Column(db.Boolean, default=False)
    checklist_clean = db.Column(db.Boolean, default=False)
    checklist_customer_ok = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    service_order = db.relationship("ServiceOrder")
    installer = db.relationship("User")

    @property
    def checklist_complete(self):
        return all([
            self.checklist_product, self.checklist_parts, self.checklist_leveling,
            self.checklist_alignment, self.checklist_clean, self.checklist_customer_ok
        ])


class Delivery(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"), nullable=False)
    carrier = db.Column(db.String(140))
    manifest_number = db.Column(db.String(80))
    scheduled_date = db.Column(db.Date)
    delivered_at = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="AGUARDANDO")
    return_reason = db.Column(db.String(255))
    order = db.relationship("SalesOrder")


class Contract(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(60), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    contract_type = db.Column(db.String(100))
    status = db.Column(db.String(30), default="RASCUNHO")
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    value = db.Column(db.Numeric(14, 2), default=0)
    notes = db.Column(db.Text)
    customer = db.relationship("Customer")


class FiscalDocument(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("sales_order.id"))
    number = db.Column(db.String(40))
    series = db.Column(db.String(20))
    cfop = db.Column(db.String(20))
    status = db.Column(db.String(30), default="PENDENTE")
    access_key = db.Column(db.String(60))
    order = db.relationship("SalesOrder")


class RegistryItem(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(80), nullable=False, index=True)
    code = db.Column(db.String(80))
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    extra_json = db.Column(db.JSON, default=dict)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(80))
    before_json = db.Column(db.JSON)
    after_json = db.Column(db.JSON)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    user = db.relationship("User")
