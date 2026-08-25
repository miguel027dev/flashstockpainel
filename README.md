# Flash Stock ERP + Loja — V4 SQLite

Sistema unificado da Flash Stock com **Flask + Jinja Templates + SQLite**, loja pública, catálogo, ERP administrativo, usuários com permissões individuais e backup global automático.

## O que esta versão entrega

- Loja pública em `/` usando o visual do ZIP original da Flash Stock, otimizado para carregar menos JavaScript.
- Catálogo público em `/catalogo` ligado aos produtos do ERP.
- Página individual de produto com galeria de fotos.
- Orçamento público integrado ao CRM/solicitações do site.
- Área administrativa em `/admin`.
- Usuários internos com e-mail, senha, perfil, estabelecimento e permissões individuais.
- Produtos com até 8 fotos, capa, descrição comercial, medidas, material, acabamento e publicação no catálogo.
- Pedidos, clientes, fornecedores, estoque, compras, financeiro, logística, serviços, CRM, call center, relatórios, fiscal, contratos, pessoas e auditoria.
- **SQLite como banco principal**.
- **Backup global manual e automático**.
- **Importação/restauração de backup** somente para ADMIN e DESENVOLVEDOR.
- Backup automático verifica o sistema a cada 30 minutos e só cria um novo ZIP se os dados/arquivos tiverem mudado.
- Antes de qualquer restauração o sistema cria automaticamente um backup `pre-restore`.

## Banco SQLite

Por padrão local:

```text
data/flashstock.sqlite3
```

No Render com Persistent Disk:

```text
/var/data/flashstock/flashstock.sqlite3
```

O SQLite usa:

- WAL mode;
- foreign keys;
- `busy_timeout`;
- `synchronous=NORMAL`;
- um único worker Gunicorn com múltiplas threads.

Essa configuração é importante porque o sistema possui escrita frequente em pedidos, estoque, financeiro e auditoria.

## Rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Carregue o `.env`:

```bash
set -a
source .env
set +a
```

Inicialize:

```bash
flask --app app init-db
```

Inicie:

```bash
flask --app app run --host=0.0.0.0 --port=5000
```

Acesse:

```text
Loja:  http://127.0.0.1:5000/
Admin: http://127.0.0.1:5000/admin
```

As credenciais iniciais são definidas em:

```env
ADMIN_EMAIL=admin@flashstock.local
ADMIN_PASSWORD=...
```

## Backup global

Depois de entrar como ADMIN ou DESENVOLVEDOR:

```text
/sistema/backups
```

O pacote `.zip` inclui:

- snapshot íntegro do SQLite;
- usuários;
- hashes de senha;
- funcionários;
- cargos/departamentos;
- perfis e permissões;
- clientes;
- fornecedores;
- produtos;
- imagens dos produtos armazenadas no SQLite;
- estoque e movimentos;
- pedidos e timeline;
- compras;
- contas a pagar/receber;
- caixa e conciliação;
- comissões;
- CRM;
- solicitações públicas;
- logística;
- serviços e montagens;
- contratos;
- fiscal;
- configurações;
- auditoria;
- diretórios persistentes de uploads/documentos, quando existirem.

O backup não inclui `.env`, senhas em texto puro ou segredos do servidor.

### Backup automático

Padrão:

```env
AUTO_BACKUP_ENABLED=1
AUTO_BACKUP_INTERVAL_SECONDS=1800
AUTO_BACKUP_KEEP=96
BACKUP_MAX_STORAGE_MB=4096
```

`1800` segundos = 30 minutos.

O scheduler tira um snapshot consistente do SQLite e calcula um fingerprint global. Se nada mudou desde o último backup, nenhum ZIP duplicado é criado.

## Render

Leia `RENDER_DEPLOY.md`.

**SQLite no Render precisa de Persistent Disk.** O `render.yaml` deste projeto já aponta o disco para:

```text
/var/data/flashstock
```

Não rode SQLite de produção no filesystem efêmero do serviço.

## Estrutura

```text
app.py
config.py
models.py
extensions.py
menu.py
services/
  backup.py
  audit.py
  erp.py
  ofx.py
templates/
  store/
  backups.html
  ...
static/
  css/
  js/
scripts/
  start_render.sh
  seed_demo.py
data/                  # ignorado pelo Git
render.yaml
requirements.txt
```

## Visual / otimização

A página pública usa a linguagem visual do template original enviado pelo cliente, mas a V4 removeu GSAP + ScrollTrigger + Lenis do carregamento principal. Os efeitos essenciais agora usam CSS e `IntersectionObserver`, reduzindo JavaScript, requisições externas e consumo de CPU, principalmente no celular.

## Atualização V4.1 — performance

A V4.1 otimiza a entrada pública, login administrativo, catálogo, imagens e verificações de permissão. Consulte `OPTIMIZATIONS_V4_1.md`.
