# Deploy no Render — Flash Stock V4 SQLite

## 1. Persistent Disk é obrigatório

Esta versão usa SQLite. O arquivo do banco não pode ficar no filesystem temporário do Web Service.

O `render.yaml` configura:

```text
mountPath: /var/data/flashstock
```

Banco:

```text
/var/data/flashstock/flashstock.sqlite3
```

Backups:

```text
/var/data/flashstock/backups
```

## 2. Variáveis

No Render configure:

```env
SECRET_KEY=<chave forte>
ADMIN_EMAIL=<email do administrador>
ADMIN_PASSWORD=<senha inicial forte>
COMPANY_NAME=Flash Stock
DATA_DIR=/var/data/flashstock
SQLITE_PATH=/var/data/flashstock/flashstock.sqlite3
BACKUP_DIR=/var/data/flashstock/backups
AUTO_BACKUP_ENABLED=1
AUTO_BACKUP_INTERVAL_SECONDS=1800
AUTO_BACKUP_KEEP=96
BACKUP_MAX_STORAGE_MB=4096
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
WEB_CONCURRENCY=1
GUNICORN_THREADS=4
```

## 3. Build

```bash
pip install --upgrade pip && pip install -r requirements.txt
```

## 4. Start

```bash
bash scripts/start_render.sh
```

O script executa:

```bash
flask --app app init-db
```

e depois inicia Gunicorn.

## 5. Por que apenas 1 worker?

O SQLite suporta várias leituras, porém tem um único escritor por vez. Para este ERP usamos:

```env
WEB_CONCURRENCY=1
GUNICORN_THREADS=4
```

Assim o servidor continua atendendo requisições concorrentes sem criar vários processos disputando o mesmo arquivo SQLite.

## 6. Backup automático

O próprio Web Service executa o scheduler. A cada 30 minutos ele:

1. cria um snapshot consistente do SQLite;
2. verifica integridade;
3. calcula fingerprint do banco e arquivos persistentes;
4. compara com o último estado;
5. cria um ZIP apenas se algo mudou;
6. aplica retenção automática.

Backups manuais/importação ficam em:

```text
Admin → Sistema → Backup Global
```

Somente usuários com perfil `ADMIN` ou `DESENVOLVEDOR` acessam essa área.
