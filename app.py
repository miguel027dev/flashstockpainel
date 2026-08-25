import csv
import io
import os
import secrets
import hmac
import tempfile
from pathlib import Path
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, abort, send_file, g
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image, ImageOps
from sqlalchemy import or_, func, text
from sqlalchemy.orm import selectinload

from config import Config
from extensions import db, migrate
from menu import MENU
from models import *
# Importações explícitas das entidades de controle de acesso.
# Evita inconsistências em deploys onde imports por wildcard podem não expor
# as classes esperadas durante o bootstrap inicial.
from models import Permission, UserAccessProfile, UserPermission
from services.audit import audit
from services.erp import (
    recalc_order, add_order_event, reserve_order_stock, release_order_stock, consume_order_stock,
    dashboard_metrics, pendencies, stock_analytics, supplier_ranking
)
from services.ofx import parse_ofx
from services.backup import GlobalBackupManager, BackupError

app = Flask(__name__)
app.config.from_object(Config)
app.config.setdefault("MAX_CONTENT_LENGTH", 32 * 1024 * 1024)

# Render termina HTTPS no proxy e encaminha a requisição para o Gunicorn.
# ProxyFix faz o Flask respeitar protocolo/host/IP originais com segurança para 1 proxy.
if os.getenv("TRUST_PROXY", "1" if os.getenv("RENDER") else "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db.init_app(app)
migrate.init_app(app, db)

D = Decimal

backup_manager = GlobalBackupManager(
    db_path=app.config["SQLITE_PATH"],
    backup_dir=app.config["BACKUP_DIR"],
    project_root=os.path.dirname(os.path.abspath(__file__)),
    interval_seconds=app.config["AUTO_BACKUP_INTERVAL_SECONDS"],
    auto_keep=app.config["AUTO_BACKUP_KEEP"],
    manual_keep=app.config["MANUAL_BACKUP_KEEP"],
    max_storage_mb=app.config["BACKUP_MAX_STORAGE_MB"],
)

PERMISSION_DEFS = [
    ("dashboard.view", "Dashboard", "Principal", "Visualizar indicadores e visão geral"),
    ("commercial.orders", "Pedidos de venda", "Comercial", "Criar, consultar e operar pedidos"),
    ("commercial.customers", "Clientes", "Comercial", "Cadastrar e consultar clientes"),
    ("commercial.catalog", "Catálogo interno", "Comercial", "Consultar catálogo e etiquetas"),
    ("commercial.discounts", "Descontos e gerência", "Comercial", "Regras de desconto e gestores"),
    ("commissions.view", "Comissões", "Comercial", "Consultar comissões e projeções"),
    ("products.manage", "Produtos", "Cadastros", "Cadastrar produtos, fotos, fornecedores e listas"),
    ("stock.manage", "Estoque", "Operação", "Movimentar estoque, inventário e reservas"),
    ("purchases.manage", "Compras", "Operação", "Pedidos de compra e recebimentos"),
    ("finance.manage", "Financeiro", "Financeiro", "Caixa, receber, pagar e conciliação"),
    ("logistics.manage", "Logística", "Operação", "Entregas, romaneios e transportadoras"),
    ("services.manage", "Serviços e montagem", "Operação", "OS, agenda e pagamentos de montagem"),
    ("reports.view", "Relatórios", "Gestão", "Relatórios e projeções"),
    ("crm.manage", "CRM", "Comercial", "Funil comercial e follow-ups"),
    ("callcenter.manage", "Call Center", "Comercial", "Fila de contatos e Kanban"),
    ("director_ai.view", "Diretor IA", "Gestão", "Consultas gerenciais inteligentes"),
    ("people.manage", "Pessoas", "Administração", "Funcionários, departamentos e cargos"),
    ("users.manage", "Usuários e acessos", "Administração", "Criar profissionais e definir permissões"),
    ("settings.manage", "Configurações", "Administração", "Empresa, estabelecimentos e parâmetros"),
    ("fiscal.manage", "Fiscal", "Administração", "NF-e, CFOPs e numeração"),
    ("contracts.manage", "Contratos e jurídico", "Administração", "Contratos e rotinas jurídicas"),
    ("installer.portal", "Portal do montador", "Operação", "Acesso ao portal mobile de montagem"),
    ("audit.view", "Auditoria", "Administração", "Consultar histórico crítico do sistema"),
]

ROLE_DEFAULTS = {
    "ADMIN": "*",
    "DESENVOLVEDOR": "*",
    "DIRETOR": "*",
    "GERENTE": {p[0] for p in PERMISSION_DEFS if p[0] not in {"users.manage", "settings.manage", "audit.view"}},
    "VENDEDOR": {"dashboard.view", "commercial.orders", "commercial.customers", "commercial.catalog", "commercial.discounts", "commissions.view", "crm.manage", "callcenter.manage"},
    "ESTOQUE": {"dashboard.view", "commercial.catalog", "products.manage", "stock.manage", "purchases.manage", "logistics.manage"},
    "FINANCEIRO": {"dashboard.view", "finance.manage", "commissions.view", "reports.view"},
    "MONTADOR": {"installer.portal", "services.manage"},
}

PATH_PERMISSION_RULES = [
    ("/dashboard", "dashboard.view"),
    ("/pedidos", "commercial.orders"),
    ("/solicitacoes-site", "commercial.orders"),
    ("/clientes", "commercial.customers"),
    ("/admin/catalogo", "commercial.catalog"),
    ("/etiquetas", "commercial.catalog"),
    ("/descontos", "commercial.discounts"),
    ("/gerentes", "commercial.discounts"),
    ("/comissoes", "commissions.view"),
    ("/produtos", "products.manage"),
    ("/fornecedores", "products.manage"),
    ("/troca-codigo", "products.manage"),
    ("/cadastro", "products.manage"),
    ("/estoque", "stock.manage"),
    ("/pendencias", "stock.manage"),
    ("/compras", "purchases.manage"),
    ("/financeiro", "finance.manage"),
    ("/logistica", "logistics.manage"),
    ("/servicos", "services.manage"),
    ("/montagens", "services.manage"),
    ("/devolucoes", "commercial.orders"),
    ("/cancelamentos", "commercial.orders"),
    ("/relatorios", "reports.view"),
    ("/crm", "crm.manage"),
    ("/call-center", "callcenter.manage"),
    ("/diretor-ia", "director_ai.view"),
    ("/funcionarios", "people.manage"),
    ("/usuarios", "users.manage"),
    ("/estabelecimentos", "settings.manage"),
    ("/empresa", "settings.manage"),
    ("/fiscal", "fiscal.manage"),
    ("/contratos", "contracts.manage"),
    ("/portal-montador", "installer.portal"),
    ("/auditoria", "audit.view"),
]

PUBLIC_PATH_PREFIXES = ("/static/", "/media/produtos/", "/produto/", "/catalogo", "/orcamento")
PUBLIC_EXACT_PATHS = {"/", "/sobre", "/admin", "/login", "/logout", "/healthz"}

CADASTRO_SCOPE_PERMISSIONS = {
    "campanhas": "commercial.orders", "situacoes-pedido": "commercial.orders", "motivos-bloqueio": "commercial.orders",
    "categorias": "products.manage", "dominios": "products.manage", "subcategorias": "products.manage", "marcas": "products.manage",
    "modelos": "products.manage", "origens-fornecedor": "products.manage", "unidades": "products.manage", "catalogos-prontos": "products.manage",
    "cores": "products.manage", "feriados": "settings.manage",
    "formas-pagamento": "finance.manage", "condicoes-pagamento": "finance.manage", "categorias-financeiras": "finance.manage",
    "tipos-despesa": "finance.manage", "boletos": "finance.manage", "centros-custo": "finance.manage", "borderos": "finance.manage", "fretes-pagar": "finance.manage",
    "motivos-retorno": "logistics.manage", "transportadoras": "logistics.manage",
    "tipos-os": "services.manage", "valores-montagem": "services.manage", "pagamentos-montagem": "services.manage",
    "departamentos": "people.manage", "cargos": "people.manage", "perfis": "users.manage",
    "mensagens-carrinho": "settings.manage", "cfops": "fiscal.manage", "numeracao-nfe": "fiscal.manage",
    "juridico": "contracts.manage", "tipos-contrato": "contracts.manage",
}

def permission_for_path(path):
    if path in PUBLIC_EXACT_PATHS or path.startswith(PUBLIC_PATH_PREFIXES):
        return None
    if path.startswith("/cadastro/"):
        scope = path.split("/", 3)[2] if len(path.split("/")) > 2 else ""
        return CADASTRO_SCOPE_PERMISSIONS.get(scope, "settings.manage")
    if path == "/pedidos/kanban":
        return "callcenter.manage"
    if path.startswith("/pedidos/") and path.endswith("/aprovar"):
        return "commercial.discounts"
    if path == "/relatorios/projecao":
        return "commissions.view"
    for prefix, key in PATH_PERMISSION_RULES:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None

def user_permission_keys(user):
    if not user:
        return set()
    if user.is_admin:
        return {p[0] for p in PERMISSION_DEFS}
    profile = getattr(user, "access_profile", None)
    if profile and profile.customized:
        return {link.permission.key for link in user.permission_links if link.permission}
    role_name = user.role.name.upper() if user.role else ""
    defaults = ROLE_DEFAULTS.get(role_name, set())
    return {p[0] for p in PERMISSION_DEFS} if defaults == "*" else set(defaults)

def user_has_permission(user, key):
    return bool(user and (user.is_admin or key in user_permission_keys(user)))

def menu_permission(href):
    if href == "/dashboard": return "dashboard.view"
    if href == "/pedidos/kanban": return "callcenter.manage"
    if href == "/relatorios/projecao": return "commissions.view"
    if href == "/solicitacoes-site": return "commercial.orders"
    if href.startswith("/pedidos") or href in {"/devolucoes", "/cancelamentos"}: return "commercial.orders"
    if href == "/clientes": return "commercial.customers"
    if href in {"/admin/catalogo", "/etiquetas"}: return "commercial.catalog"
    if href in {"/descontos", "/gerentes"}: return "commercial.discounts"
    if href.startswith("/comissoes") or href == "/relatorios/projecao": return "commissions.view"
    if href.startswith("/estoque") or href == "/pendencias": return "stock.manage"
    if href == "/compras": return "purchases.manage"
    if href.startswith("/financeiro"): return "finance.manage"
    if href.startswith("/logistica"): return "logistics.manage"
    if href in {"/servicos", "/montagens"}: return "services.manage"
    if href == "/relatorios": return "reports.view"
    if href == "/crm": return "crm.manage"
    if href.startswith("/call-center") or href == "/pedidos/kanban": return "callcenter.manage"
    if href == "/diretor-ia": return "director_ai.view"
    if href == "/funcionarios": return "people.manage"
    if href == "/usuarios": return "users.manage"
    if href in {"/estabelecimentos", "/empresa"}: return "settings.manage"
    if href.startswith("/fiscal"): return "fiscal.manage"
    if href == "/contratos": return "contracts.manage"
    if href == "/portal-montador": return "installer.portal"
    if href.startswith("/cadastro/"):
        scope = href.split("/", 3)[2] if len(href.split("/")) > 2 else ""
        return CADASTRO_SCOPE_PERMISSIONS.get(scope, "settings.manage")
    if href.startswith("/fornecedores") or href.startswith("/produtos") or href.startswith("/troca-codigo"): return "products.manage"
    return None


@app.after_request
def response_performance_headers(response):
    """Cache de assets estáticos sem congelar HTML dinâmico do catálogo/ERP."""
    path = request.path
    if path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=2592000")
    elif path in PUBLIC_EXACT_PATHS or path.startswith(("/catalogo", "/produto/", "/sobre")):
        response.headers.setdefault("Cache-Control", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # O painel não é divulgado nas páginas públicas e também não deve ser indexado.
    if path == "/admin" or path.startswith("/admin/"):
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    return response


@app.before_request
def csrf_protect():
    if request.endpoint in {"static", "healthz"}:
        return
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not app.testing:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf_token", "")):
            abort(400, description="Token CSRF inválido ou ausente.")
    required_permission = permission_for_path(request.path)
    if required_permission and session.get("user_id"):
        user = g_user()
        if user and not user_has_permission(user, required_permission):
            abort(403)



def dec(value, default="0"):
    try:
        return Decimal(str(value or default).replace(",", "."))
    except InvalidOperation:
        return Decimal(default)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def safe_next_url(value):
    """Aceita somente redirecionamentos internos para evitar open redirect no login."""
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not value.startswith("/"):
        return None
    return value


def ensure_order_receivable(order):
    existing = FinancialEntry.query.filter_by(order_id=order.id, entry_type="RECEBER").first()
    if not existing:
        db.session.add(FinancialEntry(
            entry_type="RECEBER", description=f"Pedido {order.number} — {order.customer.name}",
            amount=order.total, due_date=date.today()+timedelta(days=30), status="ABERTO",
            order_id=order.id, customer_id=order.customer_id, category="Vendas"
        ))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("admin_entry", next=request.path))
        user = g_user()
        if not user or not user.active:
            session.clear()
            return redirect(url_for("admin_entry"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not g_user().is_admin:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def developer_or_admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        user = g_user()
        role_name = user.role.name.upper() if user and user.role else ""
        if role_name not in {"ADMIN", "DESENVOLVEDOR"}:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def g_user():
    # Evita consultar o mesmo usuário várias vezes durante uma única requisição.
    if hasattr(g, "_flashstock_user"):
        return g._flashstock_user
    uid = session.get("user_id")
    g._flashstock_user = db.session.get(User, uid) if uid else None
    return g._flashstock_user


MENU_ICONS = {
    "/dashboard": "bi-grid-1x2-fill",
    "/pedidos": "bi-cart3",
    "/solicitacoes-site": "bi-globe2",
    "/cadastro/campanhas": "bi-megaphone-fill",
    "/admin/catalogo": "bi-grid-fill",
    "/etiquetas": "bi-upc-scan",
    "/servicos": "bi-tools",
    "/troca-codigo": "bi-arrow-repeat",
    "/clientes": "bi-people-fill",
    "/devolucoes": "bi-arrow-left-right",
    "/cancelamentos": "bi-x-octagon",
    "/comissoes": "bi-cash-stack",
    "/comissoes/painel": "bi-bar-chart-fill",
    "/relatorios/projecao": "bi-graph-up-arrow",
    "/descontos": "bi-percent",
    "/gerentes": "bi-person-badge",
    "/produtos": "bi-box-seam",
    "/fornecedores": "bi-truck",
    "/estoque": "bi-boxes",
    "/estoque/inventario": "bi-clipboard2-check",
    "/estoque/necessidade": "bi-exclamation-diamond",
    "/estoque/reservas": "bi-arrow-left-right",
    "/pendencias": "bi-bell-fill",
    "/estoque/sugestoes": "bi-lightbulb",
    "/compras": "bi-bag-check-fill",
    "/financeiro/caixa": "bi-wallet2",
    "/financeiro/receber": "bi-arrow-down-circle-fill",
    "/financeiro/recebimentos": "bi-cash-coin",
    "/financeiro/conciliacao": "bi-bank",
    "/financeiro/pagar": "bi-arrow-up-circle-fill",
    "/financeiro/contas": "bi-credit-card-2-front",
    "/logistica/prontos": "bi-box2-heart",
    "/logistica/romaneios": "bi-signpost-split-fill",
    "/montagens": "bi-calendar2-check",
    "/relatorios": "bi-file-earmark-bar-graph-fill",
    "/crm": "bi-diagram-3-fill",
    "/call-center": "bi-headset",
    "/pedidos/kanban": "bi-kanban-fill",
    "/diretor-ia": "bi-cpu-fill",
    "/funcionarios": "bi-person-lines-fill",
    "/usuarios": "bi-shield-lock-fill",
    "/estabelecimentos": "bi-shop",
    "/empresa": "bi-building",
    "/fiscal/nfe": "bi-receipt-cutoff",
    "/contratos": "bi-file-earmark-text-fill",
    "/portal-montador": "bi-phone-fill",
    "/ajuda": "bi-question-circle-fill",
    "/auditoria": "bi-fingerprint",
    "/sistema/backups": "bi-database-fill-check",
}

GROUP_ICONS = {
    "PRINCIPAL": "bi-house-door-fill",
    "COMERCIAL": "bi-bag-fill",
    "COTAS E COMISSÕES": "bi-currency-dollar",
    "CADASTROS": "bi-folder2-open",
    "ESTOQUE": "bi-box-seam-fill",
    "COMPRAS": "bi-cart-check-fill",
    "FINANCEIRO": "bi-piggy-bank-fill",
    "LOGÍSTICA": "bi-truck-flatbed",
    "SERVIÇOS": "bi-tools",
    "RELATÓRIOS": "bi-file-earmark-bar-graph",
    "JURÍDICO": "bi-briefcase-fill",
    "CRM": "bi-diagram-2-fill",
    "CALL CENTER": "bi-headphones",
    "DIRETOR IA": "bi-stars",
    "PESSOAS & SEGURANÇA": "bi-people-fill",
    "CONFIGURAÇÕES": "bi-sliders",
    "FISCAL": "bi-receipt",
    "CONTRATOS": "bi-file-earmark-text",
    "PORTAL DO MONTADOR": "bi-phone",
    "AJUDA": "bi-life-preserver",
    "SISTEMA": "bi-gear-wide-connected",
}

@app.context_processor
def inject_globals():
    user = g_user()
    permission_keys = user_permission_keys(user) if user else set()
    visible_menu = []
    if user:
        for group, items in MENU:
            allowed_items = []
            for label, href in items:
                key = menu_permission(href)
                if key is None or user.is_admin or key in permission_keys:
                    allowed_items.append((label, href))
            if allowed_items:
                visible_menu.append((group, allowed_items))
    system_items = []
    if user and (user.is_admin or "audit.view" in permission_keys):
        system_items.append(("Auditoria", "/auditoria"))
    if user and user.role and user.role.name.upper() in {"ADMIN", "DESENVOLVEDOR"}:
        system_items.append(("Backup Global", "/sistema/backups"))
    if system_items:
        visible_menu.append(("SISTEMA", system_items))
    quote_cart = session.get("quote_cart", {})
    return {
        "MENU": visible_menu,
        "MENU_ICONS": MENU_ICONS,
        "GROUP_ICONS": GROUP_ICONS,
        "current_user": user,
        "company_name": app.config["COMPANY_NAME"],
        "today": date.today(),
        "ano": date.today().year,
        "csrf_token": session.get("csrf_token", ""),
        "quote_cart_count": sum(int(v) for v in quote_cart.values()) if isinstance(quote_cart, dict) else 0,
        "current_permission_keys": permission_keys,
    }


@app.template_filter("money")
def money(v):
    try:
        value = Decimal(str(v or 0))
        s = f"{value:,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


@app.template_filter("num")
def num(v):
    try:
        return f"{Decimal(str(v or 0)):.2f}".replace(".", ",")
    except Exception:
        return "0,00"


@app.template_filter("filesize")
def filesize(v):
    try:
        n = float(v or 0)
    except Exception:
        n = 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def _presentation(product):
    if product.presentation:
        return product.presentation
    pres = ProductPresentation(product_id=product.id, public_visible=True, featured=False)
    db.session.add(pres)
    db.session.flush()
    return pres


def _cover_image(product):
    if not product.images:
        return None
    return next((img for img in product.images if img.cover), product.images[0])


def _save_product_images(product, files):
    saved = 0
    existing = len(product.images)
    for upload in files:
        if not upload or not upload.filename:
            continue
        if existing + saved >= 8:
            break
        try:
            img = Image.open(upload.stream)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=84, method=6)
            data = out.getvalue()
            if len(data) > 4 * 1024 * 1024:
                continue
            pi = ProductImage(
                product_id=product.id,
                filename=(upload.filename or f"produto-{product.id}.webp")[:255],
                content_type="image/webp",
                data=data,
                sort_order=existing + saved,
                cover=(existing == 0 and saved == 0),
            )
            db.session.add(pi)
            saved += 1
        except Exception:
            continue
    return saved


def _store_products_query():
    # Carrega apresentação e imagens em lote para evitar N+1 no catálogo público.
    return (
        Product.query
        .options(selectinload(Product.presentation), selectinload(Product.images))
        .outerjoin(ProductPresentation)
        .filter(
            Product.active.is_(True),
            or_(ProductPresentation.id.is_(None), ProductPresentation.public_visible.is_(True))
        )
    )


@app.route("/")
def root():
    featured = _store_products_query().filter(ProductPresentation.featured.is_(True)).order_by(Product.updated_at.desc()).limit(6).all()
    if not featured:
        featured = _store_products_query().order_by(Product.updated_at.desc()).limit(6).all()
    categories = [r[0] for r in db.session.query(Product.category).filter(Product.active.is_(True), Product.category.isnot(None), Product.category != "").distinct().order_by(Product.category).all()]
    return render_template("store/index.html", featured=featured, categories=categories)


@app.route("/catalogo")
def store_catalog():
    q = request.args.get("q", "").strip()[:120]
    category = request.args.get("categoria", "").strip()[:120]
    sort = request.args.get("ordem", "recentes")
    try:
        page = max(1, int(request.args.get("pagina", "1")))
    except ValueError:
        page = 1
    per_page = 24

    query = _store_products_query()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.brand.ilike(like), Product.model.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if sort == "preco-menor":
        query = query.order_by(Product.sale_price.asc(), Product.id.desc())
    elif sort == "preco-maior":
        query = query.order_by(Product.sale_price.desc(), Product.id.desc())
    elif sort == "nome":
        query = query.order_by(Product.name.asc(), Product.id.asc())
    else:
        query = query.order_by(Product.updated_at.desc(), Product.id.desc())

    total = query.enable_eagerloads(False).order_by(None).count()
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages
    products = query.offset((page - 1) * per_page).limit(per_page).all()
    categories = [r[0] for r in db.session.query(Product.category).filter(Product.active.is_(True), Product.category.isnot(None), Product.category != "").distinct().order_by(Product.category).all()]
    return render_template(
        "store/catalog.html", products=products, categories=categories, current_category=category,
        q=q, sort=sort, page=page, pages=pages, total=total
    )


@app.route("/produto/<int:product_id>")
def store_product(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.active or (product.presentation and not product.presentation.public_visible):
        abort(404)
    related = _store_products_query().filter(Product.id != product.id)
    if product.category:
        related = related.filter(Product.category == product.category)
    related = related.order_by(Product.updated_at.desc()).limit(4).all()
    return render_template("store/product.html", product=product, related=related, cover=_cover_image(product))


@app.get("/media/produtos/<int:image_id>")
def product_image_media(image_id):
    image = db.get_or_404(ProductImage, image_id)
    product = image.product
    private = (not product.active) or (product.presentation and not product.presentation.public_visible)
    user = g_user()
    if private and not (user and (user_has_permission(user, "products.manage") or user_has_permission(user, "commercial.catalog"))):
        abort(404)
    resp = Response(image.data, mimetype=image.content_type or "image/webp")
    stamp = int(image.created_at.timestamp()) if image.created_at else 0
    resp.set_etag(f"product-image-{image.id}-{len(image.data)}-{stamp}")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp.make_conditional(request)


@app.route("/sobre")
def store_about():
    return render_template("store/about.html")


@app.post("/orcamento/adicionar/<int:product_id>")
def quote_add(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.active or (product.presentation and not product.presentation.public_visible):
        abort(404)
    cart = dict(session.get("quote_cart", {}))
    key = str(product_id)
    cart[key] = min(int(cart.get(key, 0)) + max(1, int(request.form.get("quantity") or 1)), 99)
    session["quote_cart"] = cart
    session.modified = True
    flash(f"{product.name} adicionado ao orçamento.", "success")
    return redirect(safe_next_url(request.form.get("next")) or url_for("quote_cart"))


@app.post("/orcamento/remover/<int:product_id>")
def quote_remove(product_id):
    cart = dict(session.get("quote_cart", {}))
    cart.pop(str(product_id), None)
    session["quote_cart"] = cart
    session.modified = True
    return redirect(url_for("quote_cart"))


@app.route("/orcamento")
def quote_cart():
    cart = session.get("quote_cart", {}) or {}
    ids = [int(k) for k in cart.keys() if str(k).isdigit()]
    products = (Product.query.options(selectinload(Product.images), selectinload(Product.presentation)).filter(Product.id.in_(ids)).all() if ids else [])
    items = [{"product": p, "quantity": int(cart.get(str(p.id), 1))} for p in products]
    estimated_total = sum((Decimal(str(i["product"].sale_price or 0)) * i["quantity"] for i in items), Decimal("0"))
    return render_template("store/quote.html", items=items, estimated_total=estimated_total)


@app.post("/orcamento/enviar")
def quote_submit():
    cart = session.get("quote_cart", {}) or {}
    ids = [int(k) for k in cart.keys() if str(k).isdigit()]
    if not ids:
        flash("Adicione pelo menos um produto antes de enviar.", "warning")
        return redirect(url_for("store_catalog"))
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    if not name or not phone:
        flash("Informe nome e telefone para continuar.", "danger")
        return redirect(url_for("quote_cart"))
    quote = PublicQuote(
        number=f"ORC-{datetime.utcnow():%Y%m%d%H%M%S%f}",
        name=name, phone=phone, email=(request.form.get("email") or "").strip() or None,
        city=(request.form.get("city") or "").strip() or None,
        neighborhood=(request.form.get("neighborhood") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(quote)
    db.session.flush()
    for pid in ids:
        product = db.session.get(Product, pid)
        if product:
            db.session.add(PublicQuoteItem(quote_id=quote.id, product_id=pid, quantity=dec(cart.get(str(pid), 1), "1")))
    lead = Lead(name=name, phone=phone, email=quote.email, stage="NOVO", estimated_value=0, notes="Origem: catálogo público")
    db.session.add(lead)
    db.session.commit()
    session.pop("quote_cart", None)
    return render_template("store/quote_success.html", quote=quote)


@app.route("/solicitacoes-site")
@login_required
def site_requests():
    status = request.args.get("status", "").strip()
    query = PublicQuote.query.order_by(PublicQuote.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    quotes = query.limit(300).all()
    counts = dict(db.session.query(PublicQuote.status, func.count(PublicQuote.id)).group_by(PublicQuote.status).all())
    return render_template("site_requests.html", quotes=quotes, counts=counts, current_status=status)


@app.post("/solicitacoes-site/<int:quote_id>/status")
@login_required
def site_request_status(quote_id):
    quote = db.get_or_404(PublicQuote, quote_id)
    allowed = {"NOVO", "EM_ATENDIMENTO", "ORCAMENTO_ENVIADO", "CONVERTIDO", "ENCERRADO"}
    new_status = request.form.get("status", "NOVO")
    if new_status not in allowed:
        abort(400)
    before = {"status": quote.status}
    quote.status = new_status
    audit("UPDATE", "PublicQuote", quote.id, before=before, after={"status": quote.status})
    db.session.commit()
    flash("Situação da solicitação atualizada.", "success")
    return redirect(url_for("site_requests"))


@app.post("/solicitacoes-site/<int:quote_id>/cliente")
@login_required
def site_request_create_customer(quote_id):
    quote = db.get_or_404(PublicQuote, quote_id)
    customer = None
    if quote.phone:
        customer = Customer.query.filter_by(phone=quote.phone).first()
    if not customer and quote.email:
        customer = Customer.query.filter(func.lower(Customer.email) == quote.email.lower()).first()
    if not customer:
        customer = Customer(name=quote.name, phone=quote.phone, email=quote.email, city=quote.city, neighborhood=quote.neighborhood, notes=f"Origem: solicitação {quote.number} do catálogo público")
        db.session.add(customer)
        db.session.flush()
        audit("CREATE", "Customer", customer.id, after={"name": customer.name, "source": quote.number})
    quote.status = "EM_ATENDIMENTO"
    db.session.commit()
    flash("Cliente vinculado/criado a partir da solicitação.", "success")
    return redirect(url_for("customers", q=quote.phone or quote.name))


@app.route("/admin", methods=["GET", "POST"])
def admin_entry():
    if session.get("user_id") and request.method == "GET":
        user = g_user()
        if user and user.active:
            destination = safe_next_url(request.args.get("next"))
            if destination:
                return redirect(destination)
            if user_has_permission(user, "dashboard.view"):
                return redirect(url_for("dashboard"))
            if user_has_permission(user, "installer.portal"):
                return redirect(url_for("installer_portal"))
            return render_template("error.html", code=403, message="Seu usuário ainda não possui módulos liberados.")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            session["csrf_token"] = secrets.token_urlsafe(32)
            audit("LOGIN", "User", user.id, after={"email": user.email})
            db.session.commit()
            destination = safe_next_url(request.args.get("next"))
            if destination:
                return redirect(destination)
            if user_has_permission(user, "dashboard.view"):
                return redirect(url_for("dashboard"))
            if user_has_permission(user, "installer.portal"):
                return redirect(url_for("installer_portal"))
            return redirect(url_for("help_page"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return admin_entry()
    target = url_for("admin_entry")
    if request.args.get("next"):
        target += "?next=" + request.args.get("next")
    return redirect(target)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin_entry"))


@app.route("/dashboard")
@login_required
def dashboard():
    metrics = dashboard_metrics()
    pending = pendencies()[:8]
    recent_orders = SalesOrder.query.order_by(SalesOrder.created_at.desc()).limit(8).all()
    stage_counts = dict(db.session.query(Lead.stage, func.count(Lead.id)).group_by(Lead.stage).all())
    return render_template("dashboard.html", metrics=metrics, pending=pending, recent_orders=recent_orders, stage_counts=stage_counts)


# --------------------------- Cadastros principais ---------------------------
@app.route("/clientes", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        c = Customer(
            name=request.form["name"].strip(), document=request.form.get("document"), phone=request.form.get("phone"),
            email=request.form.get("email"), zip_code=request.form.get("zip_code"), address=request.form.get("address"),
            neighborhood=request.form.get("neighborhood"), city=request.form.get("city"), state=request.form.get("state"),
            notes=request.form.get("notes")
        )
        db.session.add(c); db.session.flush(); audit("CREATE", "Customer", c.id, after={"name":c.name}); db.session.commit()
        flash("Cliente cadastrado.", "success"); return redirect(url_for("customers"))
    q = request.args.get("q", "").strip()
    query = Customer.query
    if q:
        query = query.filter(or_(Customer.name.ilike(f"%{q}%"), Customer.document.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    return render_template("customers.html", customers=query.order_by(Customer.name).all())


@app.post("/clientes/<int:item_id>/toggle")
@login_required
def customer_toggle(item_id):
    c = db.get_or_404(Customer, item_id); before={"active":c.active}; c.active=not c.active; audit("UPDATE","Customer",c.id,before, {"active":c.active}); db.session.commit(); return redirect(url_for("customers"))


@app.route("/fornecedores", methods=["GET", "POST"])
@login_required
def suppliers():
    if request.method == "POST":
        s=Supplier(name=request.form["name"].strip(),document=request.form.get("document"),phone=request.form.get("phone"),email=request.form.get("email"),lead_time_days=int(request.form.get("lead_time_days") or 7))
        db.session.add(s); db.session.flush(); audit("CREATE","Supplier",s.id,after={"name":s.name}); db.session.commit(); return redirect(url_for("suppliers"))
    return render_template("suppliers.html", suppliers=Supplier.query.order_by(Supplier.name).all(), ranking=supplier_ranking())


def _apply_product_form(product, form):
    product.sku = (form.get("sku") or product.sku or "").strip()
    product.name = (form.get("name") or product.name or "").strip()
    product.category = (form.get("category") or "").strip() or None
    product.subcategory = (form.get("subcategory") or "").strip() or None
    product.brand = (form.get("brand") or "").strip() or None
    product.model = (form.get("model") or "").strip() or None
    product.color = (form.get("color") or "").strip() or None
    product.unit = (form.get("unit") or "UN").strip() or "UN"
    product.supplier_id = form.get("supplier_id") or None
    product.sale_price = dec(form.get("sale_price"))
    product.cost_price = dec(form.get("cost_price"))
    product.minimum_stock = dec(form.get("minimum_stock"))
    product.reorder_point = dec(form.get("reorder_point"))
    product.location_code = (form.get("location_code") or "").strip() or None
    product.active = form.get("active", "on") == "on"
    pres = _presentation(product)
    pres.description = (form.get("description") or "").strip() or None
    pres.material = (form.get("material") or "").strip() or None
    pres.finish = (form.get("finish") or "").strip() or None
    pres.width_min = dec(form.get("width_min"))
    pres.width_max = dec(form.get("width_max"))
    pres.height_min = dec(form.get("height_min"))
    pres.height_max = dec(form.get("height_max"))
    pres.depth_min = dec(form.get("depth_min"))
    pres.depth_max = dec(form.get("depth_max"))
    pres.production_days = int(form.get("production_days") or 0) or None
    pres.featured = form.get("featured") == "on"
    pres.public_visible = form.get("public_visible", "on") == "on"
    pres.catalog_note = (form.get("catalog_note") or "").strip() or None
    return pres


@app.route("/produtos", methods=["GET", "POST"])
@login_required
def products():
    if request.method == "POST":
        sku = (request.form.get("sku") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not sku or not name:
            flash("SKU e nome são obrigatórios.", "danger")
            return redirect(url_for("products"))
        if Product.query.filter_by(sku=sku).first():
            flash("Já existe um produto com esse SKU.", "danger")
            return redirect(url_for("products"))
        p = Product(sku=sku, name=name)
        db.session.add(p)
        db.session.flush()
        _apply_product_form(p, request.form)
        for est in Establishment.query.filter_by(active=True).all():
            db.session.add(StockItem(product_id=p.id, establishment_id=est.id, quantity_physical=0, quantity_reserved=0))
        saved = _save_product_images(p, request.files.getlist("images"))
        audit("CREATE", "Product", p.id, after={"sku": p.sku, "name": p.name, "images": saved})
        db.session.commit()
        flash("Produto criado e publicado no catálogo conforme a configuração.", "success")
        return redirect(url_for("products"))
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        query = query.filter(or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%"), Product.brand.ilike(f"%{q}%")))
    return render_template(
        "products.html",
        products=query.order_by(Product.updated_at.desc()).all(),
        suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all(),
    )


@app.route("/produtos/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def product_edit(item_id):
    p = db.get_or_404(Product, item_id)
    pres = _presentation(p)
    if request.method == "POST":
        new_sku = (request.form.get("sku") or "").strip()
        duplicate = Product.query.filter(Product.sku == new_sku, Product.id != p.id).first()
        if duplicate:
            flash("Esse SKU já está em uso por outro produto.", "danger")
            return redirect(url_for("product_edit", item_id=p.id))
        before = {"sku": p.sku, "name": p.name, "active": p.active}
        _apply_product_form(p, request.form)
        for image_id in request.form.getlist("delete_image"):
            if str(image_id).isdigit():
                image = ProductImage.query.filter_by(id=int(image_id), product_id=p.id).first()
                if image:
                    db.session.delete(image)
        db.session.flush()
        saved = _save_product_images(p, request.files.getlist("images"))
        cover_id = request.form.get("cover_image_id")
        images = ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order, ProductImage.id).all()
        if images:
            chosen = next((img for img in images if str(img.id) == str(cover_id)), images[0])
            for img in images:
                img.cover = img.id == chosen.id
        audit("UPDATE", "Product", p.id, before=before, after={"sku": p.sku, "name": p.name, "images_added": saved})
        db.session.commit()
        flash("Produto atualizado.", "success")
        return redirect(url_for("product_edit", item_id=p.id))
    db.session.commit()
    return render_template("product_edit.html", product=p, presentation=pres, suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all())


@app.post("/produtos/<int:item_id>/toggle")
@login_required
def product_toggle(item_id):
    p = db.get_or_404(Product, item_id)
    p.active = not p.active
    audit("UPDATE", "Product", p.id, after={"active": p.active})
    db.session.commit()
    return redirect(url_for("products"))


@app.post("/produtos/<int:product_id>/imagem/<int:image_id>/excluir")
@login_required
def product_image_delete(product_id, image_id):
    image = ProductImage.query.filter_by(id=image_id, product_id=product_id).first_or_404()
    was_cover = image.cover
    db.session.delete(image)
    db.session.flush()
    if was_cover:
        first = ProductImage.query.filter_by(product_id=product_id).order_by(ProductImage.sort_order, ProductImage.id).first()
        if first:
            first.cover = True
    audit("DELETE", "ProductImage", image_id, after={"product_id": product_id})
    db.session.commit()
    flash("Foto removida.", "success")
    return redirect(url_for("product_edit", item_id=product_id))


@app.route("/admin/catalogo")
@login_required
def admin_catalog():
    return render_template("catalog.html", products=Product.query.filter_by(active=True).order_by(Product.category, Product.name).all())


@app.route("/etiquetas")
@login_required
def labels():
    ids = [int(x) for x in request.args.getlist("id") if x.isdigit()]
    products = Product.query.filter(Product.id.in_(ids)).all() if ids else Product.query.filter_by(active=True).limit(24).all()
    return render_template("labels.html", products=products)


# -------------------------------- Pedidos ----------------------------------
@app.route("/pedidos")
@login_required
def orders():
    query = SalesOrder.query.order_by(SalesOrder.created_at.desc())
    if request.args.get("filtro") == "bloqueados": query = query.filter_by(blocked=True)
    return render_template("orders.html", orders=query.limit(300).all())


@app.route("/pedidos/novo", methods=["GET", "POST"])
@login_required
def order_new():
    if request.method == "POST":
        customer_id=int(request.form["customer_id"]); establishment_id=int(request.form["establishment_id"])
        order=SalesOrder(
            number=f"PV-{datetime.utcnow():%Y%m%d%H%M%S%f}", customer_id=customer_id, seller_id=g_user().id,
            establishment_id=establishment_id, discount_percent=dec(request.form.get("discount_percent")),
            freight_cost=dec(request.form.get("freight_cost")), installation_cost=dec(request.form.get("installation_cost")),
            expected_delivery_date=parse_date(request.form.get("expected_delivery_date")), notes=request.form.get("notes")
        )
        db.session.add(order); db.session.flush()
        pids=request.form.getlist("product_id[]"); qtys=request.form.getlist("quantity[]"); prices=request.form.getlist("unit_price[]")
        for pid,qty,price in zip(pids,qtys,prices):
            if not pid or dec(qty) <= 0: continue
            p=db.session.get(Product,int(pid));
            if not p: continue
            db.session.add(SalesOrderItem(order_id=order.id,product_id=p.id,quantity=dec(qty),unit_price=dec(price) if price else p.sale_price,unit_cost=p.cost_price))
        db.session.flush(); recalc_order(order)
        limit = dec(g_user().role.discount_limit if g_user().role else 0)
        if dec(order.discount_percent) > limit:
            order.approval_status="PENDING"; order.status="AGUARDANDO_APROVACAO"
        else:
            order.approval_status="APPROVED"; order.status="CONFIRMADO"; reserve_order_stock(order); ensure_order_receivable(order)
        order.commission_cost=(dec(order.total)*D("0.03")).quantize(D("0.01")); recalc_order(order)
        add_order_event(order,g_user().id,"CRIACAO",f"Pedido {order.number} criado")
        if order.approval_status=="PENDING": add_order_event(order,g_user().id,"APROVACAO","Desconto acima do limite; aguardando aprovação")
        audit("CREATE","SalesOrder",order.id,after={"number":order.number,"total":str(order.total),"discount":str(order.discount_percent)})
        db.session.commit(); flash("Pedido criado.","success"); return redirect(url_for("order_detail", order_id=order.id))
    return render_template("order_form.html", customers=Customer.query.filter_by(active=True).order_by(Customer.name).all(), products=Product.query.filter_by(active=True).order_by(Product.name).all(), establishments=Establishment.query.filter_by(active=True).all())


@app.route("/pedidos/<int:order_id>")
@login_required
def order_detail(order_id):
    order=db.get_or_404(SalesOrder,order_id)
    events=OrderEvent.query.filter_by(order_id=order.id).order_by(OrderEvent.created_at.desc()).all()
    return render_template("order_detail.html", order=order, events=events)


@app.post("/pedidos/<int:order_id>/aprovar")
@login_required
def order_approve(order_id):
    order=db.get_or_404(SalesOrder,order_id)
    if order.approval_status != "APPROVED":
        order.approval_status="APPROVED"; order.approved_by_id=g_user().id; order.status="CONFIRMADO"; reserve_order_stock(order); ensure_order_receivable(order)
        add_order_event(order,g_user().id,"APROVACAO",f"Desconto aprovado por {g_user().name}")
        audit("APPROVE","SalesOrder",order.id,after={"discount":str(order.discount_percent)})
        db.session.commit()
    return redirect(url_for("order_detail",order_id=order.id))


@app.post("/pedidos/<int:order_id>/status")
@login_required
def order_status(order_id):
    order=db.get_or_404(SalesOrder,order_id); old=order.status; new=request.form.get("status",old)
    if old != new:
        if new=="CANCELADO" and old!="CANCELADO":
            release_order_stock(order)
            for e in FinancialEntry.query.filter_by(order_id=order.id).filter(FinancialEntry.status=="ABERTO").all(): e.status="CANCELADO"
            for c in Commission.query.filter_by(order_id=order.id).all(): c.status="CANCELADA"
        if new=="ENTREGUE" and old!="ENTREGUE": consume_order_stock(order)
        order.status=new; add_order_event(order,g_user().id,"STATUS",f"Status alterado: {old} → {new}")
        audit("STATUS","SalesOrder",order.id,{"status":old},{"status":new}); db.session.commit()
    return redirect(url_for("order_detail",order_id=order.id))


@app.post("/pedidos/<int:order_id>/bloqueio")
@login_required
def order_block(order_id):
    order=db.get_or_404(SalesOrder,order_id); order.blocked=not order.blocked; order.block_reason=request.form.get("reason") if order.blocked else None
    add_order_event(order,g_user().id,"BLOQUEIO", "Pedido bloqueado" if order.blocked else "Bloqueio removido")
    audit("BLOCK","SalesOrder",order.id,after={"blocked":order.blocked,"reason":order.block_reason}); db.session.commit(); return redirect(url_for("order_detail",order_id=order.id))


@app.post("/pedidos/<int:order_id>/separar/<int:item_id>")
@login_required
def order_pick(order_id,item_id):
    item=db.get_or_404(SalesOrderItem,item_id)
    if item.order_id != order_id: abort(404)
    item.picked_quantity=min(dec(item.quantity), dec(request.form.get("picked_quantity")))
    order=item.order
    if all(dec(i.picked_quantity)>=dec(i.quantity) for i in order.items):
        if order.status not in {"PRONTO_ENTREGA","ENTREGUE"}:
            order.status="PRONTO_ENTREGA"; add_order_event(order,g_user().id,"SEPARACAO","Todos os itens foram separados")
    audit("PICK","SalesOrderItem",item.id,after={"picked":str(item.picked_quantity)}); db.session.commit(); return redirect(url_for("order_detail",order_id=order_id))


@app.route("/pedidos/kanban")
@login_required
def orders_kanban():
    statuses=["NOVO","AGUARDANDO_APROVACAO","CONFIRMADO","SEPARANDO","PRONTO_ENTREGA","EM_ROTA","ENTREGUE"]
    data={s:SalesOrder.query.filter_by(status=s).order_by(SalesOrder.created_at.desc()).limit(50).all() for s in statuses}
    return render_template("order_kanban.html", statuses=statuses, data=data)


@app.route("/troca-codigo", methods=["GET", "POST"])
@login_required
def code_change():
    if request.method == "POST":
        p = db.get_or_404(Product, int(request.form["product_id"]))
        old = p.sku
        new = request.form["new_sku"].strip()
        if Product.query.filter(Product.sku == new, Product.id != p.id).first():
            flash("Já existe um produto com esse código.", "danger")
        else:
            p.sku = new
            audit("CODE_CHANGE", "Product", p.id, {"sku": old}, {"sku": new, "reason": request.form.get("reason")})
            db.session.commit(); flash(f"Código alterado: {old} → {new}", "success")
        return redirect(url_for("code_change"))
    return render_template("code_change.html", products=Product.query.order_by(Product.name).all())


@app.route("/cancelamentos")
@login_required
def cancellations():
    orders = SalesOrder.query.filter_by(status="CANCELADO").order_by(SalesOrder.updated_at.desc()).all()
    return render_template("cancellations.html", orders=orders)


@app.route("/descontos", methods=["GET", "POST"])
@login_required
def discount_rules():
    if request.method == "POST":
        role = db.get_or_404(Role, int(request.form["role_id"]))
        before = {"discount_limit": str(role.discount_limit)}
        role.discount_limit = dec(request.form.get("discount_limit"))
        audit("UPDATE", "Role", role.id, before, {"discount_limit": str(role.discount_limit)})
        db.session.commit(); flash("Limite de desconto atualizado.", "success")
        return redirect(url_for("discount_rules"))
    pending = SalesOrder.query.filter_by(approval_status="PENDING").order_by(SalesOrder.created_at.desc()).all()
    return render_template("discounts.html", roles=Role.query.order_by(Role.name).all(), pending=pending)


@app.route("/gerentes")
@login_required
def managers():
    users = User.query.join(Role, User.role_id == Role.id).filter(Role.name.in_(["GERENTE", "DIRETOR", "ADMIN"])).order_by(User.name).all()
    return render_template("managers.html", users=users)


# -------------------------------- Estoque ----------------------------------
@app.route("/estoque", methods=["GET","POST"])
@login_required
def stock():
    if request.method=="POST":
        product_id=int(request.form["product_id"]); est_id=int(request.form["establishment_id"]); qty=dec(request.form["quantity"]); typ=request.form.get("movement_type","AJUSTE")
        row=StockItem.query.filter_by(product_id=product_id,establishment_id=est_id).first()
        if not row: row=StockItem(product_id=product_id,establishment_id=est_id,quantity_physical=0,quantity_reserved=0); db.session.add(row); db.session.flush()
        row.quantity_physical=dec(row.quantity_physical)+qty
        db.session.add(StockMovement(product_id=product_id,establishment_id=est_id,movement_type=typ,quantity=qty,notes=request.form.get("notes"),user_id=g_user().id))
        audit("STOCK","Product",product_id,after={"delta":str(qty),"type":typ}); db.session.commit(); flash("Movimento registrado.","success"); return redirect(url_for("stock"))
    return render_template("stock.html", rows=stock_analytics(), products=Product.query.filter_by(active=True).order_by(Product.name).all(), establishments=Establishment.query.filter_by(active=True).all())


@app.route("/estoque/inventario")
@login_required
def inventory():
    return render_template("inventory.html", stocks=StockItem.query.join(Product).order_by(Product.name).all())


@app.post("/estoque/inventario/<int:stock_id>")
@login_required
def inventory_adjust(stock_id):
    row=db.get_or_404(StockItem,stock_id); counted=dec(request.form.get("counted")); delta=counted-dec(row.quantity_physical)
    before={"physical":str(row.quantity_physical)}; row.quantity_physical=counted
    db.session.add(StockMovement(product_id=row.product_id,establishment_id=row.establishment_id,movement_type="INVENTARIO",quantity=delta,notes="Ajuste por inventário",user_id=g_user().id))
    audit("INVENTORY","StockItem",row.id,before,{"physical":str(counted)}); db.session.commit(); return redirect(url_for("inventory"))


@app.route("/estoque/necessidade")
@login_required
def purchase_need():
    rows=[r for r in stock_analytics() if dec(r["stock"].available) <= dec(r["stock"].product.minimum_stock)]
    return render_template("stock_analysis.html", title="Necessidade de Compra", rows=rows, mode="need")


@app.route("/estoque/sugestoes")
@login_required
def purchase_suggestions():
    rows=[r for r in stock_analytics() if r["suggested"]>0]
    return render_template("stock_analysis.html", title="Sugestão de Compras", rows=rows, mode="suggestion")


@app.route("/estoque/reservas", methods=["GET", "POST"])
@login_required
def stock_reservations():
    if request.method == "POST":
        product_id = int(request.form["product_id"])
        source_id = int(request.form["source_id"])
        destination_id = int(request.form["destination_id"])
        qty = dec(request.form.get("quantity"))
        if source_id == destination_id:
            flash("Origem e destino precisam ser diferentes.", "danger")
            return redirect(url_for("stock_reservations"))
        if qty <= 0:
            flash("Informe uma quantidade maior que zero.", "danger")
            return redirect(url_for("stock_reservations"))
        source = StockItem.query.filter_by(product_id=product_id, establishment_id=source_id).with_for_update().first()
        destination = StockItem.query.filter_by(product_id=product_id, establishment_id=destination_id).with_for_update().first()
        if not source or dec(source.quantity_reserved) < qty:
            flash("A origem não possui reserva suficiente para a transferência.", "danger")
            db.session.rollback()
            return redirect(url_for("stock_reservations"))
        if not destination:
            destination = StockItem(product_id=product_id, establishment_id=destination_id, quantity_physical=0, quantity_reserved=0)
            db.session.add(destination)
            db.session.flush()
        source.quantity_reserved = dec(source.quantity_reserved) - qty
        destination.quantity_reserved = dec(destination.quantity_reserved) + qty
        user = g_user()
        db.session.add_all([
            StockMovement(product_id=product_id, establishment_id=source_id, movement_type="TRANSFER_RESERVA_SAIDA", quantity=-qty, reference_type="TRANSFERENCIA_RESERVA", notes=f"Transferência para estabelecimento #{destination_id}", user_id=user.id),
            StockMovement(product_id=product_id, establishment_id=destination_id, movement_type="TRANSFER_RESERVA_ENTRADA", quantity=qty, reference_type="TRANSFERENCIA_RESERVA", notes=f"Transferência do estabelecimento #{source_id}", user_id=user.id),
        ])
        audit("TRANSFER", "StockReservation", product_id, before={"source": source_id, "destination": destination_id}, after={"quantity": str(qty)})
        db.session.commit()
        flash("Reserva transferida com sucesso.", "success")
        return redirect(url_for("stock_reservations"))
    rows=StockItem.query.filter(StockItem.quantity_reserved>0).join(Product).order_by(Product.name).all()
    products=Product.query.filter_by(active=True).order_by(Product.name).all()
    establishments=Establishment.query.filter_by(active=True).order_by(Establishment.name).all()
    return render_template("reservations.html", rows=rows, products=products, establishments=establishments)


@app.route("/pendencias")
@login_required
def pending_center():
    return render_template("pendencies.html", items=pendencies())


# -------------------------------- Compras ----------------------------------
@app.route("/compras", methods=["GET","POST"])
@login_required
def purchases():
    if request.method=="POST":
        po=PurchaseOrder(number=f"PC-{datetime.utcnow():%Y%m%d%H%M%S}",supplier_id=int(request.form["supplier_id"]),expected_at=parse_date(request.form.get("expected_at")))
        db.session.add(po); db.session.flush(); total=D("0")
        for pid,qty,cost in zip(request.form.getlist("product_id[]"),request.form.getlist("quantity[]"),request.form.getlist("unit_cost[]")):
            if not pid or dec(qty)<=0: continue
            item=PurchaseOrderItem(purchase_order_id=po.id,product_id=int(pid),quantity=dec(qty),unit_cost=dec(cost)); db.session.add(item); total += dec(qty)*dec(cost)
        po.total=total; audit("CREATE","PurchaseOrder",po.id,after={"number":po.number,"total":str(total)}); db.session.commit(); return redirect(url_for("purchases"))
    return render_template("purchases.html", purchases=PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all(), suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all(), products=Product.query.filter_by(active=True).order_by(Product.name).all(), ranking=supplier_ranking())


@app.post("/compras/<int:po_id>/receber")
@login_required
def purchase_receive(po_id):
    po=db.get_or_404(PurchaseOrder,po_id)
    if po.status!="RECEBIDO":
        est=Establishment.query.filter_by(active=True).first()
        if not est: flash("Cadastre um estabelecimento primeiro.","danger"); return redirect(url_for("purchases"))
        for item in po.items:
            stock=StockItem.query.filter_by(product_id=item.product_id,establishment_id=est.id).first()
            if not stock: stock=StockItem(product_id=item.product_id,establishment_id=est.id,quantity_physical=0,quantity_reserved=0); db.session.add(stock); db.session.flush()
            stock.quantity_physical=dec(stock.quantity_physical)+dec(item.quantity)
            db.session.add(StockMovement(product_id=item.product_id,establishment_id=est.id,movement_type="ENTRADA_COMPRA",quantity=item.quantity,reference_type="COMPRA",reference_id=po.id,user_id=g_user().id))
        po.status="RECEBIDO"; po.received_at=date.today();
        db.session.add(FinancialEntry(entry_type="PAGAR",description=f"Compra {po.number} — {po.supplier.name}",amount=po.total,due_date=date.today()+timedelta(days=30),purchase_order_id=po.id,supplier_id=po.supplier_id,status="ABERTO"))
        audit("RECEIVE","PurchaseOrder",po.id,after={"received_at":str(po.received_at)}); db.session.commit()
    return redirect(url_for("purchases"))


# ------------------------------- Financeiro --------------------------------
@app.route("/financeiro/<kind>", methods=["GET","POST"])
@login_required
def finance(kind):
    mapping={"receber":"RECEBER","pagar":"PAGAR"}
    if kind in mapping:
        typ=mapping[kind]
        if request.method=="POST":
            e=FinancialEntry(entry_type=typ,description=request.form["description"],amount=dec(request.form["amount"]),due_date=parse_date(request.form["due_date"]) or date.today(),category=request.form.get("category"),cost_center=request.form.get("cost_center"))
            db.session.add(e); db.session.flush(); audit("CREATE","FinancialEntry",e.id,after={"type":typ,"amount":str(e.amount)}); db.session.commit(); return redirect(url_for("finance",kind=kind))
        entries=FinancialEntry.query.filter_by(entry_type=typ).order_by(FinancialEntry.due_date.desc()).all()
        return render_template("finance.html", kind=kind, entries=entries)
    if kind=="caixa":
        metrics=dashboard_metrics(); accounts=FinancialAccount.query.filter_by(active=True).all(); return render_template("cash.html",metrics=metrics,accounts=accounts)
    if kind=="contas":
        if request.method=="POST":
            a=FinancialAccount(name=request.form["name"],account_type=request.form.get("account_type","CAIXA"),bank_name=request.form.get("bank_name")); db.session.add(a); db.session.commit(); return redirect(url_for("finance",kind="contas"))
        return render_template("accounts.html",accounts=FinancialAccount.query.order_by(FinancialAccount.name).all())
    if kind=="recebimentos":
        entries=FinancialEntry.query.filter_by(entry_type="RECEBER").order_by(FinancialEntry.created_at.desc()).all(); return render_template("finance.html",kind="receber",entries=entries,title="Recebimento de Pedidos")
    if kind=="conciliacao":
        return redirect(url_for("reconciliation"))
    abort(404)


@app.post("/financeiro/lancamento/<int:entry_id>/baixar")
@login_required
def finance_pay(entry_id):
    e=db.get_or_404(FinancialEntry,entry_id); e.status="PAGO"; e.paid_at=date.today()
    if e.order_id:
        order=e.order
        if order and e.entry_type=="RECEBER" and order.seller_id:
            existing=Commission.query.filter_by(order_id=order.id,user_id=order.seller_id).first()
            if not existing:
                amount=(dec(order.total)*D("0.03")).quantize(D("0.01")); db.session.add(Commission(order_id=order.id,user_id=order.seller_id,base_amount=order.total,percent=3,amount=amount,status="LIBERADA"))
    audit("SETTLE","FinancialEntry",e.id,after={"status":"PAGO"}); db.session.commit(); return redirect(request.referrer or url_for("dashboard"))


@app.route("/financeiro/conciliacao", methods=["GET","POST"])
@login_required
def reconciliation():
    account=FinancialAccount.query.order_by(FinancialAccount.id).first()
    if request.method=="POST":
        if not account:
            account=FinancialAccount(name="Conta principal",account_type="BANCO"); db.session.add(account); db.session.flush()
        f=request.files.get("ofx")
        if not f: flash("Selecione um arquivo OFX/QFX.","danger"); return redirect(url_for("reconciliation"))
        text=f.read().decode("latin-1",errors="ignore"); imported=0
        for tx in parse_ofx(text):
            if BankTransaction.query.filter_by(external_id=tx["external_id"]).first(): continue
            bt=BankTransaction(account_id=account.id,external_id=tx["external_id"],tx_date=tx["date"],description=tx["description"],amount=tx["amount"])
            # sugestão automática por valor e proximidade de data
            typ="RECEBER" if tx["amount"]>0 else "PAGAR"; target=abs(tx["amount"])
            match=FinancialEntry.query.filter(FinancialEntry.entry_type==typ,FinancialEntry.status=="ABERTO",FinancialEntry.amount.between(target-D("0.01"),target+D("0.01")),FinancialEntry.due_date.between(tx["date"]-timedelta(days=5),tx["date"]+timedelta(days=5))).first()
            if match: bt.reconciled_entry_id=match.id
            db.session.add(bt); imported+=1
        audit("IMPORT","BankTransaction",after={"count":imported}); db.session.commit(); flash(f"{imported} transações importadas.","success"); return redirect(url_for("reconciliation"))
    txs=BankTransaction.query.order_by(BankTransaction.tx_date.desc()).limit(300).all()
    return render_template("reconciliation.html",transactions=txs,accounts=FinancialAccount.query.all())


@app.post("/financeiro/conciliacao/<int:tx_id>/confirmar")
@login_required
def reconcile_confirm(tx_id):
    tx=db.get_or_404(BankTransaction,tx_id)
    if tx.reconciled_entry:
        tx.reconciled_entry.status="PAGO"; tx.reconciled_entry.paid_at=tx.tx_date; audit("RECONCILE","BankTransaction",tx.id,after={"entry_id":tx.reconciled_entry_id}); db.session.commit()
    return redirect(url_for("reconciliation"))


# ------------------------------- Comissões ---------------------------------
@app.route("/comissoes")
@login_required
def commissions():
    return render_template("commissions.html", commissions=Commission.query.order_by(Commission.created_at.desc()).all())


@app.route("/comissoes/painel")
@login_required
def commission_panel():
    rows=db.session.query(User.name,func.coalesce(func.sum(Commission.amount),0),func.count(Commission.id)).join(Commission,Commission.user_id==User.id).group_by(User.id,User.name).all()
    return render_template("commission_panel.html",rows=rows)


# ---------------------------------- CRM ------------------------------------
@app.route("/crm", methods=["GET","POST"])
@login_required
def crm():
    if request.method=="POST":
        lead=Lead(name=request.form["name"],phone=request.form.get("phone"),email=request.form.get("email"),estimated_value=dec(request.form.get("estimated_value")),owner_id=g_user().id,next_follow_up=parse_date(request.form.get("next_follow_up")),notes=request.form.get("notes")); db.session.add(lead); db.session.flush(); audit("CREATE","Lead",lead.id,after={"name":lead.name}); db.session.commit(); return redirect(url_for("crm"))
    stages=["NOVO","CONTATO","ORCAMENTO","NEGOCIACAO","VENDA","PERDIDO"]
    data={s:Lead.query.filter_by(stage=s).order_by(Lead.updated_at.desc()).all() for s in stages}
    return render_template("crm.html",stages=stages,data=data)


@app.post("/crm/<int:lead_id>/stage")
@login_required
def crm_stage(lead_id):
    l=db.get_or_404(Lead,lead_id); old=l.stage; l.stage=request.form.get("stage",l.stage); l.lost_reason=request.form.get("lost_reason") if l.stage=="PERDIDO" else None; audit("STAGE","Lead",l.id,{"stage":old},{"stage":l.stage}); db.session.commit(); return redirect(url_for("crm"))


@app.route("/call-center")
@login_required
def call_center():
    leads=Lead.query.order_by(Lead.next_follow_up.asc().nullslast(),Lead.updated_at.desc()).all(); return render_template("call_center.html",leads=leads)


# -------------------------- Serviços / Montagem ----------------------------
@app.route("/servicos", methods=["GET","POST"])
@login_required
def services():
    if request.method=="POST":
        so=ServiceOrder(number=f"OS-{datetime.utcnow():%Y%m%d%H%M%S}",customer_id=request.form.get("customer_id") or None,order_id=request.form.get("order_id") or None,service_type=request.form.get("service_type") or "MONTAGEM",scheduled_date=parse_date(request.form.get("scheduled_date")),assigned_user_id=request.form.get("assigned_user_id") or None,value=dec(request.form.get("value")),notes=request.form.get("notes")); db.session.add(so); db.session.flush()
        if so.service_type=="MONTAGEM":
            sched=datetime.combine(so.scheduled_date,datetime.min.time()) if so.scheduled_date else None; db.session.add(Installation(service_order_id=so.id,installer_id=so.assigned_user_id,scheduled_at=sched))
        audit("CREATE","ServiceOrder",so.id,after={"number":so.number}); db.session.commit(); return redirect(url_for("services"))
    return render_template("services.html",services=ServiceOrder.query.order_by(ServiceOrder.created_at.desc()).all(),customers=Customer.query.filter_by(active=True).all(),orders=SalesOrder.query.order_by(SalesOrder.created_at.desc()).limit(200).all(),installers=User.query.join(Role,User.role_id==Role.id).filter(Role.name.in_(["MONTADOR","ADMIN","DIRETOR"])).all())


@app.route("/montagens")
@login_required
def installations():
    return render_template("installations.html",installations=Installation.query.order_by(Installation.scheduled_at.asc()).all())


@app.route("/portal-montador")
@login_required
def installer_portal():
    q=Installation.query
    if not g_user().is_admin: q=q.filter_by(installer_id=g_user().id)
    return render_template("installer_portal.html",installations=q.order_by(Installation.scheduled_at.asc()).all())


@app.post("/portal-montador/<int:installation_id>")
@login_required
def installer_update(installation_id):
    ins=db.get_or_404(Installation,installation_id)
    if not g_user().is_admin and ins.installer_id != g_user().id: abort(403)
    fields=["checklist_product","checklist_parts","checklist_leveling","checklist_alignment","checklist_clean","checklist_customer_ok"]
    for f in fields: setattr(ins,f,request.form.get(f)=="on")
    ins.notes=request.form.get("notes")
    if request.form.get("action")=="start" and not ins.started_at: ins.started_at=datetime.utcnow(); ins.status="EM_EXECUCAO"
    if request.form.get("action")=="complete":
        if ins.checklist_complete: ins.completed_at=datetime.utcnow(); ins.status="CONCLUIDA"
        else: flash("Conclua todos os itens do checklist antes de finalizar.","danger")
    audit("CHECKLIST","Installation",ins.id,after={f:getattr(ins,f) for f in fields}|{"status":ins.status}); db.session.commit(); return redirect(url_for("installer_portal"))


# -------------------------------- Logística --------------------------------
@app.route("/logistica/<kind>", methods=["GET","POST"])
@login_required
def logistics(kind):
    if kind=="prontos":
        orders=SalesOrder.query.filter(SalesOrder.status.in_(["PRONTO_ENTREGA","EM_ROTA"])).all(); return render_template("logistics.html",kind=kind,orders=orders,deliveries=Delivery.query.order_by(Delivery.scheduled_date.desc()).all())
    if kind=="romaneios":
        if request.method=="POST":
            oid=int(request.form["order_id"]); d=Delivery(order_id=oid,carrier=request.form.get("carrier"),manifest_number=request.form.get("manifest_number") or f"ROM-{datetime.utcnow():%Y%m%d%H%M}",scheduled_date=parse_date(request.form.get("scheduled_date"))); db.session.add(d); db.session.flush(); audit("CREATE","Delivery",d.id,after={"order":oid}); db.session.commit(); return redirect(url_for("logistics",kind="romaneios"))
        return render_template("logistics.html",kind=kind,orders=SalesOrder.query.filter(SalesOrder.status.in_(["CONFIRMADO","SEPARANDO","PRONTO_ENTREGA"])).all(),deliveries=Delivery.query.order_by(Delivery.created_at.desc()).all())
    abort(404)


# ------------------------------ Devoluções ---------------------------------
@app.route("/devolucoes", methods=["GET","POST"])
@login_required
def returns():
    if request.method=="POST":
        rr=ReturnRequest(order_id=request.form.get("order_id") or None,kind=request.form.get("kind","DEVOLUCAO"),reason=request.form.get("reason")); db.session.add(rr); db.session.flush(); audit("CREATE","ReturnRequest",rr.id,after={"kind":rr.kind}); db.session.commit(); return redirect(url_for("returns"))
    return render_template("returns.html",returns=ReturnRequest.query.order_by(ReturnRequest.created_at.desc()).all(),orders=SalesOrder.query.order_by(SalesOrder.created_at.desc()).limit(200).all())


# ----------------------------- Contratos/Fiscal -----------------------------
@app.route("/contratos", methods=["GET","POST"])
@login_required
def contracts():
    if request.method=="POST":
        c=Contract(number=request.form["number"],customer_id=request.form.get("customer_id") or None,contract_type=request.form.get("contract_type"),status=request.form.get("status","RASCUNHO"),start_date=parse_date(request.form.get("start_date")),end_date=parse_date(request.form.get("end_date")),value=dec(request.form.get("value")),notes=request.form.get("notes")); db.session.add(c); db.session.flush(); audit("CREATE","Contract",c.id,after={"number":c.number}); db.session.commit(); return redirect(url_for("contracts"))
    return render_template("contracts.html",contracts=Contract.query.order_by(Contract.created_at.desc()).all(),customers=Customer.query.filter_by(active=True).all())


@app.route("/fiscal/nfe", methods=["GET","POST"])
@login_required
def fiscal_nfe():
    if request.method=="POST":
        f=FiscalDocument(order_id=request.form.get("order_id") or None,number=request.form.get("number"),series=request.form.get("series"),cfop=request.form.get("cfop"),status="PENDENTE"); db.session.add(f); db.session.flush(); audit("CREATE","FiscalDocument",f.id,after={"number":f.number}); db.session.commit(); return redirect(url_for("fiscal_nfe"))
    return render_template("fiscal.html",docs=FiscalDocument.query.order_by(FiscalDocument.created_at.desc()).all(),orders=SalesOrder.query.order_by(SalesOrder.created_at.desc()).limit(200).all())


# --------------------------- Usuários/estrutura -----------------------------
def _permission_groups():
    groups = {}
    for key, name, group, description in PERMISSION_DEFS:
        groups.setdefault(group, []).append({"key": key, "name": name, "description": description})
    return groups


def _set_user_permissions(user, selected_keys):
    selected = {k for k in selected_keys if any(k == d[0] for d in PERMISSION_DEFS)}
    profile = user.access_profile
    if not profile:
        profile = UserAccessProfile(user_id=user.id, customized=True)
        db.session.add(profile)
    else:
        profile.customized = True
    UserPermission.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    if selected:
        permissions = Permission.query.filter(Permission.key.in_(selected)).all()
        for permission in permissions:
            db.session.add(UserPermission(user_id=user.id, permission_id=permission.id))


@app.route("/usuarios", methods=["GET","POST"])
@login_required
def users():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        selected_role = db.session.get(Role, int(request.form.get("role_id"))) if str(request.form.get("role_id") or "").isdigit() else None
        if selected_role and selected_role.name.upper() in {"ADMIN", "DIRETOR", "DESENVOLVEDOR"} and not g_user().is_admin:
            abort(403)
        if not email or not password or not request.form.get("name"):
            flash("Nome, e-mail e senha inicial são obrigatórios.", "danger")
            return redirect(url_for("users"))
        if User.query.filter_by(email=email).first():
            flash("Já existe um usuário com esse e-mail.", "danger")
            return redirect(url_for("users"))
        u = User(
            name=request.form["name"].strip(), email=email,
            role_id=request.form.get("role_id") or None,
            establishment_id=request.form.get("establishment_id") or None,
            department_id=request.form.get("department_id") or None,
            job_title_id=request.form.get("job_title_id") or None,
            active=True,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        _set_user_permissions(u, request.form.getlist("permissions"))
        audit("CREATE", "User", u.id, after={"email": u.email, "permissions": request.form.getlist("permissions")})
        db.session.commit()
        flash("Profissional cadastrado com login próprio e acessos definidos.", "success")
        return redirect(url_for("users"))
    return render_template(
        "users.html",
        users=User.query.order_by(User.name).all(),
        roles=Role.query.order_by(Role.name).all(),
        establishments=Establishment.query.all(),
        departments=Department.query.order_by(Department.name).all(),
        jobs=JobTitle.query.order_by(JobTitle.name).all(),
        permission_groups=_permission_groups(),
    )


@app.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@login_required
def user_edit(user_id):
    u = db.get_or_404(User, user_id)
    if u.is_admin and not g_user().is_admin:
        abort(403)
    if request.method == "POST":
        selected_role = db.session.get(Role, int(request.form.get("role_id"))) if str(request.form.get("role_id") or "").isdigit() else None
        if selected_role and selected_role.name.upper() in {"ADMIN", "DIRETOR", "DESENVOLVEDOR"} and not g_user().is_admin:
            abort(403)
        email = (request.form.get("email") or "").strip().lower()
        duplicate = User.query.filter(func.lower(User.email) == email, User.id != u.id).first()
        if duplicate:
            flash("Esse e-mail já pertence a outro usuário.", "danger")
            return redirect(url_for("user_edit", user_id=u.id))
        before = {"email": u.email, "role": u.role.name if u.role else None, "active": u.active}
        u.name = (request.form.get("name") or u.name).strip()
        u.email = email
        u.role_id = request.form.get("role_id") or None
        u.establishment_id = request.form.get("establishment_id") or None
        u.department_id = request.form.get("department_id") or None
        u.job_title_id = request.form.get("job_title_id") or None
        u.active = request.form.get("active") == "on"
        password = request.form.get("password") or ""
        if password:
            u.set_password(password)
        _set_user_permissions(u, request.form.getlist("permissions"))
        audit("UPDATE", "User", u.id, before=before, after={"email": u.email, "active": u.active, "permissions": request.form.getlist("permissions")})
        db.session.commit()
        flash("Usuário e permissões atualizados.", "success")
        return redirect(url_for("user_edit", user_id=u.id))
    selected = user_permission_keys(u) if u.access_profile else set()
    return render_template(
        "user_edit.html", user_edit=u, selected_permissions=selected,
        roles=Role.query.order_by(Role.name).all(), establishments=Establishment.query.all(),
        departments=Department.query.order_by(Department.name).all(), jobs=JobTitle.query.order_by(JobTitle.name).all(),
        permission_groups=_permission_groups(), role_defaults=ROLE_DEFAULTS,
    )


@app.post("/usuarios/<int:user_id>/toggle")
@login_required
def user_toggle(user_id):
    u = db.get_or_404(User, user_id)
    if u.is_admin and not g_user().is_admin:
        abort(403)
    if u.id == g_user().id:
        flash("Você não pode desativar sua própria conta.", "warning")
        return redirect(url_for("users"))
    u.active = not u.active
    audit("UPDATE", "User", u.id, after={"active": u.active})
    db.session.commit()
    return redirect(url_for("users"))


@app.route("/funcionarios", methods=["GET","POST"])
@login_required
def employees():
    if request.method=="POST":
        e=Employee(name=request.form["name"],document=request.form.get("document"),phone=request.form.get("phone"),email=request.form.get("email"),department_id=request.form.get("department_id") or None,job_title_id=request.form.get("job_title_id") or None); db.session.add(e); db.session.flush(); audit("CREATE","Employee",e.id,after={"name":e.name}); db.session.commit(); return redirect(url_for("employees"))
    return render_template("employees.html",employees=Employee.query.order_by(Employee.name).all(),departments=Department.query.all(),jobs=JobTitle.query.all())


@app.route("/estabelecimentos", methods=["GET","POST"])
@login_required
def establishments():
    if request.method=="POST":
        e=Establishment(name=request.form["name"],code=request.form.get("code"),address=request.form.get("address")); db.session.add(e); db.session.flush()
        for p in Product.query.all(): db.session.add(StockItem(product_id=p.id,establishment_id=e.id,quantity_physical=0,quantity_reserved=0))
        audit("CREATE","Establishment",e.id,after={"name":e.name}); db.session.commit(); return redirect(url_for("establishments"))
    return render_template("establishments.html",items=Establishment.query.order_by(Establishment.name).all())


@app.route("/empresa", methods=["GET","POST"])
@login_required
def company():
    c=Company.query.first()
    if request.method=="POST":
        if not c: c=Company(name=request.form.get("name") or "Flash Stock"); db.session.add(c)
        before={"name":c.name} if c.id else None
        for f in ["name","trade_name","document","phone","email","address"]: setattr(c,f,request.form.get(f))
        db.session.flush(); audit("UPDATE","Company",c.id,before,{"name":c.name}); db.session.commit(); flash("Dados salvos.","success"); return redirect(url_for("company"))
    return render_template("company.html",company=c)


# ----------------------------- CRUD universal ------------------------------
SCOPE_TITLES = {
    "campanhas":"Campanhas","troca-codigo":"Troca de Código","situacoes-pedido":"Situações do Pedido","cancelamentos":"Cancelamentos",
    "motivos-bloqueio":"Motivos de Bloqueio","regras-desconto":"Regras de Desconto","gerentes":"Gerentes","categorias":"Categorias",
    "dominios":"Domínios (listas)","subcategorias":"Subcategorias","marcas":"Marcas","modelos":"Modelos","origens-fornecedor":"Origens de Fornecedor",
    "unidades":"Unidades","catalogos-prontos":"Catálogos Prontos","formas-pagamento":"Formas de Pagamento","condicoes-pagamento":"Condições de Pagamento",
    "cores":"Cores","feriados":"Feriados","categorias-financeiras":"Categorias Financeiras","tipos-despesa":"Tipos de Despesa","boletos":"Boletos",
    "centros-custo":"Centros de Custo","borderos":"Borderôs de Pagamento","fretes-pagar":"Fretes a pagar","motivos-retorno":"Motivos de Retorno",
    "transportadoras":"Transportadoras","tipos-os":"Tipos de OS","valores-montagem":"Valores de Montagem","pagamentos-montagem":"Pagamentos de Montagem",
    "juridico":"Jurídico","departamentos":"Departamentos","cargos":"Cargos","perfis":"Perfis","mensagens-carrinho":"Mensagens do Carrinho",
    "cfops":"CFOPs de Emissão","numeracao-nfe":"Numeração de NF-e","tipos-contrato":"Tipos de Contrato"
}

@app.route("/cadastro/<scope>", methods=["GET","POST"])
@login_required
def registry(scope):
    if scope not in SCOPE_TITLES: abort(404)
    # sincroniza alguns cadastros estruturais com tabelas próprias
    if request.method=="POST":
        name=request.form["name"].strip(); code=request.form.get("code"); description=request.form.get("description")
        r=RegistryItem(scope=scope,name=name,code=code,description=description); db.session.add(r)
        if scope=="departamentos" and not Department.query.filter_by(name=name).first(): db.session.add(Department(name=name))
        if scope=="cargos" and not JobTitle.query.filter_by(name=name).first(): db.session.add(JobTitle(name=name))
        if scope=="perfis" and not Role.query.filter_by(name=name.upper()).first(): db.session.add(Role(name=name.upper(),description=description,discount_limit=dec(request.form.get("extra") or 5)))
        db.session.flush(); audit("CREATE","RegistryItem",r.id,after={"scope":scope,"name":name}); db.session.commit(); return redirect(url_for("registry",scope=scope))
    items=RegistryItem.query.filter_by(scope=scope).order_by(RegistryItem.name).all(); return render_template("registry.html",scope=scope,title=SCOPE_TITLES[scope],items=items)

@app.post("/cadastro/<scope>/<int:item_id>/toggle")
@login_required
def registry_toggle(scope,item_id):
    r=db.get_or_404(RegistryItem,item_id)
    if r.scope!=scope: abort(404)
    r.active=not r.active; audit("UPDATE","RegistryItem",r.id,after={"active":r.active}); db.session.commit(); return redirect(url_for("registry",scope=scope))


# -------------------------------- Reports ----------------------------------
@app.route("/relatorios")
@login_required
def reports():
    metrics=dashboard_metrics(); stock_rows=stock_analytics(); suppliers=supplier_ranking();
    return render_template("reports.html",metrics=metrics,stock_rows=stock_rows,suppliers=suppliers)

@app.route("/relatorios/projecao")
@login_required
def sales_projection():
    today=date.today(); start=today.replace(day=1); elapsed=max(today.day,1); sales=db.session.query(func.coalesce(func.sum(SalesOrder.total),0)).filter(SalesOrder.created_at>=start,SalesOrder.status!="CANCELADO").scalar(); days=(date(today.year+(today.month==12),(today.month%12)+1,1)-start).days; projection=dec(sales)/D(str(elapsed))*D(str(days)); return render_template("projection.html",sales=sales,projection=projection,elapsed=elapsed,days=days)

@app.route("/relatorios/pedidos.csv")
@login_required
def orders_csv():
    out=io.StringIO(); w=csv.writer(out,delimiter=";"); w.writerow(["numero","cliente","status","total","lucro","margem"])
    for o in SalesOrder.query.order_by(SalesOrder.created_at.desc()).all(): w.writerow([o.number,o.customer.name,o.status,str(o.total),str(o.gross_profit),str(o.margin_percent)])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=pedidos.csv"})


# ------------------------------- Diretor IA --------------------------------
@app.route("/diretor-ia", methods=["GET","POST"])
@login_required
def director_ai():
    answer=None; question=""
    if request.method=="POST":
        question=request.form.get("question","").lower().strip(); m=dashboard_metrics(); p=pendencies(); s=stock_analytics(); ranking=supplier_ranking()
        if "estoque" in question or "acabar" in question or "ruptura" in question:
            risky=[r for r in s if r["days_to_zero"] is not None and r["days_to_zero"]<14][:8]
            answer="Produtos com maior risco de ruptura: " + (", ".join(f"{r['stock'].product.name} (~{r['days_to_zero']:.0f} dias)" for r in risky) or "nenhum risco relevante calculado agora.")
        elif "fornecedor" in question:
            top=ranking[:5]; answer="Ranking atual por pontualidade/volume: " + "; ".join(f"{r['supplier'].name}: {r['punctuality']:.0f}% no prazo" if r['punctuality'] is not None else f"{r['supplier'].name}: sem histórico suficiente" for r in top)
        elif "receber" in question or "pagar" in question or "caixa" in question:
            answer=f"Em aberto: {money(m['receivable'])} a receber e {money(m['payable'])} a pagar. Existem {m['overdue']} lançamentos vencidos."
        elif "lucro" in question or "margem" in question:
            answer=f"No mês, lucro bruto calculado de {money(m['profit_month'])}, com margem de {num(m['margin'])}%. Faturamento: {money(m['sales_month'])}."
        elif "problema" in question or "pend" in question:
            answer=f"Há {len(p)} pendências prioritárias detectadas. Principais: " + "; ".join(x['title'] for x in p[:6])
        else:
            answer=f"Resumo: faturamento do mês {money(m['sales_month'])}, lucro {money(m['profit_month'])}, {m['orders_month']} pedidos e {len(p)} pendências. Pergunte por estoque, ruptura, fornecedores, contas, lucro ou margem."
    return render_template("director_ai.html",answer=answer,question=question)


# --------------------------- Busca global / API -----------------------------
@app.get("/api/search")
@login_required
def global_search():
    q=request.args.get("q","").strip()
    if len(q)<2: return jsonify([])
    results=[]
    user=g_user()
    if user_has_permission(user,"commercial.customers"):
        for c in Customer.query.filter(or_(Customer.name.ilike(f"%{q}%"),Customer.phone.ilike(f"%{q}%"),Customer.document.ilike(f"%{q}%"))).limit(5):
            results.append({"type":"Cliente","title":c.name,"subtitle":c.phone or c.document or "","url":url_for("customers")})
    if user_has_permission(user,"products.manage") or user_has_permission(user,"commercial.catalog"):
        for p in Product.query.filter(or_(Product.name.ilike(f"%{q}%"),Product.sku.ilike(f"%{q}%"))).limit(5):
            results.append({"type":"Produto","title":p.name,"subtitle":p.sku,"url":url_for("products") if user_has_permission(user,"products.manage") else url_for("admin_catalog")})
    if user_has_permission(user,"commercial.orders"):
        for o in SalesOrder.query.filter(SalesOrder.number.ilike(f"%{q}%")).limit(5):
            results.append({"type":"Pedido","title":o.number,"subtitle":o.customer.name,"url":url_for("order_detail",order_id=o.id)})
    return jsonify(results[:12])


@app.route("/auditoria")
@login_required
def audit_logs():
    return render_template("audit.html",logs=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all())


@app.route("/sistema/backups")
@developer_or_admin_required
def backups_page():
    backups = backup_manager.list_backups()
    state = backup_manager._load_state()
    return render_template(
        "backups.html",
        backups=backups,
        backup_state=state,
        interval_minutes=app.config["AUTO_BACKUP_INTERVAL_SECONDS"] // 60,
        backup_dir=app.config["BACKUP_DIR"],
    )


@app.post("/sistema/backups/criar")
@developer_or_admin_required
def backup_create():
    try:
        result = backup_manager.create_backup(mode="manual", note=f"Criado por {g_user().email}")
        flash(f"Backup global criado: {result['filename']}", "success")
    except Exception as exc:
        flash(f"Não foi possível criar o backup: {exc}", "danger")
    return redirect(url_for("backups_page"))


@app.get("/sistema/backups/<path:filename>/download")
@developer_or_admin_required
def backup_download(filename):
    try:
        path = backup_manager.resolve_backup(filename)
    except BackupError as exc:
        abort(404, description=str(exc))
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/zip")


@app.post("/sistema/backups/<path:filename>/restaurar")
@developer_or_admin_required
def backup_restore_saved(filename):
    if (request.form.get("confirmation") or "").strip().upper() != "RESTAURAR":
        flash("Digite RESTAURAR para confirmar a restauração global.", "danger")
        return redirect(url_for("backups_page"))
    try:
        path = backup_manager.resolve_backup(filename)
        db.session.remove()
        db.engine.dispose()
        result = backup_manager.restore_backup(path)
        session.clear()
        flash(f"Backup restaurado. Um ponto de retorno foi criado: {result['pre_restore_backup']}", "success")
        return redirect(url_for("admin_entry"))
    except Exception as exc:
        flash(f"Falha ao restaurar backup: {exc}", "danger")
        return redirect(url_for("backups_page"))


@app.post("/sistema/backups/importar")
@developer_or_admin_required
def backup_import():
    if (request.form.get("confirmation") or "").strip().upper() != "RESTAURAR":
        flash("Digite RESTAURAR para confirmar a importação.", "danger")
        return redirect(url_for("backups_page"))
    upload = request.files.get("backup_file")
    if not upload or not upload.filename:
        flash("Selecione um arquivo .zip de backup.", "danger")
        return redirect(url_for("backups_page"))
    if not upload.filename.lower().endswith(".zip"):
        flash("O arquivo precisa ser um backup ZIP da Flash Stock.", "danger")
        return redirect(url_for("backups_page"))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="flashstock-import-", suffix=".zip", delete=False) as tmp:
            upload.save(tmp)
            temp_path = Path(tmp.name)
        backup_manager.validate_backup(temp_path)
        imported_name = f"flashstock-imported-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        imported_path = Path(app.config["BACKUP_DIR"]) / imported_name
        imported_path.write_bytes(temp_path.read_bytes())
        db.session.remove()
        db.engine.dispose()
        result = backup_manager.restore_backup(imported_path)
        session.clear()
        flash(f"Backup importado e restaurado. Ponto de retorno: {result['pre_restore_backup']}", "success")
        return redirect(url_for("admin_entry"))
    except Exception as exc:
        flash(f"Backup inválido ou falha na restauração: {exc}", "danger")
        return redirect(url_for("backups_page"))
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.post("/sistema/backups/<path:filename>/excluir")
@developer_or_admin_required
def backup_delete(filename):
    try:
        backup_manager.delete_backup(filename)
        flash("Backup excluído.", "success")
    except Exception as exc:
        flash(f"Não foi possível excluir: {exc}", "danger")
    return redirect(url_for("backups_page"))


@app.route("/ajuda")
@login_required
def help_page():
    return render_template("help.html")


@app.get("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"ok": True, "database": "ok"}), 200
    except Exception:
        return jsonify({"ok": False, "database": "error"}), 503


@app.errorhandler(403)
def forbidden(e): return render_template("error.html",code=403,message="Você não tem permissão para acessar esta área."),403
@app.errorhandler(404)
def not_found(e): return render_template("error.html",code=404,message="Página não encontrada."),404


def bootstrap_data():
    db.create_all()
    if not Role.query.first():
        db.session.add_all([
            Role(name="ADMIN",description="Acesso total",discount_limit=100), Role(name="DESENVOLVEDOR",description="Manutenção técnica e backup",discount_limit=100),
            Role(name="DIRETOR",description="Diretoria",discount_limit=30), Role(name="GERENTE",description="Gerência",discount_limit=10), Role(name="VENDEDOR",description="Comercial",discount_limit=5),
            Role(name="ESTOQUE",description="Operação de estoque",discount_limit=0), Role(name="FINANCEIRO",description="Financeiro",discount_limit=0),
            Role(name="MONTADOR",description="Portal de montagem",discount_limit=0),
        ])
        db.session.commit()
    # Upgrade idempotente: bancos existentes também recebem o perfil técnico.
    if not Role.query.filter_by(name="DESENVOLVEDOR").first():
        db.session.add(Role(name="DESENVOLVEDOR", description="Manutenção técnica e backup", discount_limit=100))
        db.session.commit()
    existing_permissions = {p.key for p in Permission.query.all()}
    for key, name, group, description in PERMISSION_DEFS:
        if key not in existing_permissions:
            db.session.add(Permission(key=key, name=name, group_name=group, description=description))
    db.session.commit()
    if not Establishment.query.first(): db.session.add(Establishment(name="Loja Principal",code="LOJA-01")); db.session.commit()
    if not Company.query.first(): db.session.add(Company(name=app.config["COMPANY_NAME"],trade_name=app.config["COMPANY_NAME"])); db.session.commit()
    admin_email=app.config["ADMIN_EMAIL"].lower()
    if not User.query.filter_by(email=admin_email).first():
        role=Role.query.filter_by(name="ADMIN").first(); est=Establishment.query.first(); u=User(name="Administrador",email=admin_email,role_id=role.id,establishment_id=est.id); u.set_password(app.config["ADMIN_PASSWORD"]); db.session.add(u); db.session.commit()


@app.cli.command("init-db")
def init_db_command():
    """Cria as tabelas iniciais e garante dados-base/admin de forma idempotente."""
    bootstrap_data()
    # Índices auxiliares do catálogo público. CREATE INDEX IF NOT EXISTS é seguro em bancos já existentes.
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_product_category_public ON product(category, active)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_product_updated_public ON product(updated_at DESC)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_product_presentation_public ON product_presentation(public_visible, featured, product_id)"))
    db.session.commit()
    print("Banco Flash Stock inicializado com sucesso.")


@app.cli.command("create-admin")
def create_admin_command():
    """Garante a existência do administrador configurado nas variáveis de ambiente."""
    bootstrap_data()
    print(f"Administrador garantido: {app.config['ADMIN_EMAIL']}")


# Útil somente no desenvolvimento local. No Render o start_render.sh executa init-db
# antes de iniciar o Gunicorn, evitando inicialização concorrente em cada worker.
with app.app_context():
    if os.getenv("AUTO_CREATE_DB", "0") == "1":
        bootstrap_data()

# Um único worker é recomendado com SQLite. O agendador usa lock de arquivo e
# fingerprint do snapshot, então só cria um ZIP a cada 30 min se os dados mudaram.
if app.config.get("AUTO_BACKUP_ENABLED") and not app.testing:
    is_reloader_parent = os.getenv("FLASK_DEBUG") == "1" and os.getenv("WERKZEUG_RUN_MAIN") != "true"
    if not is_reloader_parent:
        backup_manager.start_scheduler()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
