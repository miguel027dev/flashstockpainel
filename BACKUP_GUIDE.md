# Backup Global — Flash Stock

## Tipos

### `auto`
Criado automaticamente quando houver mudança desde a última verificação.

### `manual`
Criado pelo administrador/desenvolvedor pelo painel.

### `pre-restore`
Criado automaticamente imediatamente antes de uma restauração.

## Segurança da restauração

- arquivo ZIP é validado;
- `manifest.json` precisa ser do formato Flash Stock;
- ZIP passa por teste de corrupção;
- SQLite importado passa por `PRAGMA integrity_check`;
- caminhos internos são filtrados para impedir path traversal;
- um backup `pre-restore` é gerado antes da substituição;
- sessão atual é encerrada após restauração, porque usuários/permissões podem ter mudado.

## O que não entra

O `.env` e segredos do servidor não entram no backup. O objetivo é restaurar todo o **estado operacional e cadastral** da Flash Stock sem exportar chaves privadas do ambiente.
