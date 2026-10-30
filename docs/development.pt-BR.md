# Desenvolvimento

## Preparação

Você precisa do Windows 10 22H2 ou 11 e do [uv](https://docs.astral.sh/uv/). O uv instala o
Python 3.13 e todas as dependências nas versões exatas do `uv.lock`.

```
uv sync                     # instala exatamente as versões do uv.lock
uv run capypanel            # abre o app
uv run pytest               # testes
uv run ruff check           # lint
uv run ruff format          # formatação
uv run pyright              # checagem de tipos
```

Todo pull request roda as mesmas verificações no Windows pelo CI, e a `main` só aceita alterações
que passam nelas.

## Estrutura

| Pasta | O que tem |
|---|---|
| `src/capypanel/core/` | A lógica. Nunca importa uma biblioteca de interface (o lint garante) |
| `src/capypanel/ui/` | A interface em Qt (PySide6) |
| `src/capypanel/core/tools/presets/` | Definições dos visualizadores e os perfis iniciais (JSON) |
| `src/capypanel/locale/` | Traduções |
| `tests/` | Espelha `src/` |

## Traduções

Os textos são traduzidos com gettext. Depois de alterar ou adicionar um texto:

```
uv run python scripts/translations.py
```

Depois traduza as novas entradas em cada arquivo `.po` em `src/capypanel/locale/` e rode o script
de novo para compilá-las. Os testes falham enquanto algum texto não estiver traduzido e compilado.

## Ler uma impressora de verdade

Antes de confiar no que a janela mostra, dá para fazer a uma impressora as mesmas perguntas pelo
terminal:

```
uv run python scripts/read_printer.py 192.0.2.5
```

Ele pede a comunidade sem mostrá-la, lê por SNMP (só leitura) e imprime o que o CapyPanel
entendeu. O `--public` usa "public" sem perguntar, e o `--brand-data` também imprime a área de
dados da Ricoh ou da Brother como números brutos. O nº de série sai só como o tamanho dele, para a
saída poder ser colada numa issue.

## Site da documentação

As páginas em `docs/` também são publicadas como site com o
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/), sempre que mudam na `main`. Cada
página em inglês (`nome.md`) tem a versão em português ao lado (`nome.pt-BR.md`); mude as duas
juntas. As páginas sobre o app inteiro ficam em `docs/`, e as páginas de uma ferramenta numa pasta
própria, `docs/hosts/`. Para ver o site enquanto escreve:

```
uv run --only-group docs mkdocs serve
```

## Versões

As versões são `0.MENOR.CORREÇÃO` até a 1.0: uma funcionalidade nova aumenta MENOR, uma alteração
só de correções aumenta CORREÇÃO. Rodando pelo código-fonte, a barra de título acrescenta o commit
à versão.
