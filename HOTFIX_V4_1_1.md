# Flash Stock ERP V4.1.1 Hotfix

Corrige falha de deploy durante `init-db`:

`NameError: name 'Permission' is not defined`

Alterações:
- importação explícita de `Permission`, `UserAccessProfile` e `UserPermission`;
- validação das entidades de controle de acesso antes do bootstrap;
- inicialização via `python -m flask`;
- mantém Pillow no `requirements.txt`;
- não exige apagar o SQLite existente.

No Railway, substitua o projeto inteiro pela versão hotfix e faça um novo deploy/rebuild.
