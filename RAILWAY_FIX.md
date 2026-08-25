# Flash Stock ERP — Railway V4.1.2

## Importante: raiz do repositório

O `Dockerfile`, `requirements.txt`, `app.py`, `models.py`, `wsgi.py` e `railway.json` precisam estar na MESMA raiz que o Railway usa para o serviço.

Correto:

```
repo/
  Dockerfile
  railway.json
  requirements.txt
  app.py
  models.py
  wsgi.py
  templates/
  static/
  scripts/
```

Evite:

```
repo/
  flashstock-erp-sqlite-v4.1.2-railway/
    Dockerfile
    app.py
    ...
```

Se o GitHub estiver no segundo formato, configure em Railway > Settings > Source > Root Directory:

```
/flashstock-erp-sqlite-v4.1.2-railway
```

ou mova o conteúdo da pasta para a raiz do repositório.

## Volume

Monte um Railway Volume em `/data` e use:

```
DATA_DIR=/data
SQLITE_PATH=/data/flashstock.sqlite3
BACKUP_DIR=/data/backups
```

## Build

O Dockerfile valida durante o build:

- Pillow/PIL instalado;
- sintaxe de app.py/models.py/config.py/wsgi.py;
- models Permission, UserAccessProfile e UserPermission importáveis;
- scripts/start_render.sh presente.

Procure no Build Log por:

```
[Build] Pillow OK
[Flash Stock] Models OK: Permission, UserAccessProfile, UserPermission, User, Role
```
