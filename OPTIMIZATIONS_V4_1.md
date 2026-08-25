# Flash Stock ERP V4.1 — otimizações

## Entrada pública
- loader bloqueante removido;
- cursor customizado removido e cursor nativo restaurado;
- home não depende mais de imagens do Postimg;
- imagens principais usam as fotos do próprio catálogo armazenadas no sistema;
- fallback visual local quando não há fotos cadastradas;
- renderização abaixo da dobra usa `content-visibility` para reduzir custo inicial;
- animações mantidas, porém com IntersectionObserver e sem esconder conteúdo quando o JS falhar;
- service worker atualizado para V4.1.

## Catálogo
- paginação de 24 produtos por página em vez de carregar até 200 de uma vez;
- `selectinload` para apresentação/fotos, evitando N+1 no grid;
- dimensões das imagens informadas para reduzir layout shift;
- cache de imagens de produto por 1 ano, com ETag/304;
- índices auxiliares criados por `flask --app app init-db`.

## Login / entrada administrativa
- CSS dedicado de ~5 KB;
- sem Google Fonts, Bootstrap Icons ou JavaScript na tela de login;
- layout mobile simplificado;
- consulta de login usa índice do e-mail normalizado;
- usuário atual é reutilizado durante a mesma requisição.

## Permissões e páginas internas
- menu calcula as permissões uma vez por renderização;
- `g_user()` mantém cache do usuário durante a requisição;
- verificações de acesso deixam de buscar o mesmo usuário repetidamente.

## Após atualizar
Execute uma vez:

```bash
python3 -m flask --app app init-db
```

Isso cria também os novos índices do catálogo em bancos SQLite já existentes.
