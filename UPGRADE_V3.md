# Flash Stock ERP V3 — Loja + Catálogo + Acessos

## O que mudou

- `/` agora é a área pública da Flash Stock.
- `/catalogo` é o catálogo público, alimentado pelos produtos do ERP.
- `/produto/<id>` exibe fotos, descrição, medidas, material, acabamento e valor de referência.
- `/orcamento` permite ao visitante montar uma seleção de produtos e enviar uma solicitação.
- `/solicitacoes-site` recebe os orçamentos no ERP e permite converter a solicitação em cliente.
- `/admin` é a entrada da área administrativa.
- Cada profissional possui login próprio (e-mail + senha).
- O administrador escolhe os módulos permitidos para cada usuário.
- O menu administrativo é filtrado conforme as permissões.
- O backend também bloqueia acesso direto a URLs sem permissão.
- Produtos aceitam até 8 fotos. As imagens são convertidas para WebP e salvas no PostgreSQL.

## Atualização de um banco já existente

Não é necessário apagar o banco atual.

O start do Render continua executando:

```bash
flask --app app init-db
```

O `db.create_all()` cria somente as novas tabelas que ainda não existem. As tabelas antigas e os dados atuais permanecem.

## Fotos no Render

As fotos não dependem do filesystem efêmero do Render. Elas são comprimidas e armazenadas na tabela `product_image` como `BYTEA`, portanto continuam disponíveis depois de deploys e reinicializações.

Para catálogos muito grandes, futuramente é recomendável migrar as fotos para object storage, mas esta V3 funciona sem API externa.

## Login

Administrador principal:

- e-mail: variável `ADMIN_EMAIL`
- senha: variável `ADMIN_PASSWORD`

Novos profissionais são cadastrados em **Usuários e acessos**.

## Rotas principais

- `/` — loja pública
- `/catalogo` — catálogo público
- `/orcamento` — seleção/orçamento
- `/admin` — login administrativo
- `/dashboard` — dashboard interno
- `/produtos` — gestão de produtos e fotos
- `/usuarios` — profissionais e permissões
- `/solicitacoes-site` — leads/orçamentos recebidos da loja
