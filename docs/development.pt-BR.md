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

## Site da documentação

As páginas em `docs/` também são publicadas como site com o
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/), sempre que mudam na `main`. Cada
página em inglês (`nome.md`) tem a versão em português ao lado (`nome.pt-BR.md`). Para ver o site
enquanto escreve:

```
uv run --only-group docs mkdocs serve
```

## Versões

As versões são `0.MENOR.CORREÇÃO` até a 1.0: uma funcionalidade nova aumenta MENOR, uma alteração
só de correções aumenta CORREÇÃO. Rodando pelo código-fonte, a barra de título acrescenta o commit
à versão.
