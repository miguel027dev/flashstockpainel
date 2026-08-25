import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AUTO_CREATE_DB", "1")
os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))
from app import app
from extensions import db
from models import Customer, Supplier, Product, StockItem, Establishment, User, Role, Lead, FinancialAccount

with app.app_context():
    est=Establishment.query.first()
    if not Customer.query.first():
        db.session.add_all([
            Customer(name="Cliente Demonstração",phone="(11) 99999-0001",city="São Paulo",state="SP"),
            Customer(name="Arquitetura Exemplo",phone="(11) 99999-0002",city="São Paulo",state="SP"),
        ])
    if not Supplier.query.first():
        db.session.add_all([Supplier(name="Fornecedor Madeira Premium",lead_time_days=7),Supplier(name="Ferragens Brasil",lead_time_days=4)])
        db.session.flush()
    suppliers=Supplier.query.all()
    if not Product.query.first():
        products=[
            Product(sku="FS-COZ-001",name="Cozinha Planejada Premium",category="Cozinha",brand="Flash Stock",unit="CJ",sale_price=12990,cost_price=6900,minimum_stock=1,reorder_point=2,location_code="A-01-01",supplier_id=suppliers[0].id),
            Product(sku="FS-PAI-002",name="Painel Living Sob Medida",category="Sala de Estar",brand="Flash Stock",unit="CJ",sale_price=4990,cost_price=2450,minimum_stock=2,reorder_point=4,location_code="B-02-03",supplier_id=suppliers[0].id),
            Product(sku="FS-FER-003",name="Kit Ferragens Silenciosas",category="Ferragens",unit="KIT",sale_price=690,cost_price=310,minimum_stock=10,reorder_point=20,location_code="C-01-02",supplier_id=suppliers[-1].id),
        ]
        db.session.add_all(products); db.session.flush()
        for p in products:
            db.session.add(StockItem(product_id=p.id,establishment_id=est.id,quantity_physical=10 if p.sku.endswith('003') else 3,quantity_reserved=0))
    if not FinancialAccount.query.first(): db.session.add(FinancialAccount(name="Caixa Principal",account_type="CAIXA"))
    if not Lead.query.first():
        seller=User.query.first(); db.session.add(Lead(name="Lead de demonstração",phone="(11) 98888-1111",stage="ORCAMENTO",estimated_value=18000,owner_id=seller.id if seller else None))
    db.session.commit()
    print("Dados de demonstração inseridos.")
