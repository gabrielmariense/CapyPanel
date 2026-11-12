# Contribuindo com o CapyPanel

Como compilar, testar e traduzir o CapyPanel. In English: [CONTRIBUTING.md](CONTRIBUTING.md).

## Preparação

Você precisa do Windows 10 22H2 ou 11 e do [uv](https://docs.astral.sh/uv/). O uv instala o
Python 3.13 e todas as dependências nas versões exatas do `uv.lock`.

```
uv sync                     # instala exatamente as versões do uv.lock
uv run capypanel            # abre o app
uv run pytest -n auto --dist loadgroup   # testes, espalhados por todos os núcleos, como no CI
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
entendeu, incluindo o endereço MAC e a versão do firmware. O `--public` usa "public" sem
perguntar; o `--v3` lê por SNMP v3 no lugar, pedindo o usuário e os tipos e as senhas da
autenticação e da criptografia, sem mostrar as senhas; o `--brand-data` também imprime a área de
dados da Ricoh ou da Brother como números brutos; e o `--firmware` imprime todos os lugares
padrão onde uma impressora pode guardar a versão do firmware, um por linha, para descobrir qual
deles bate com a versão da página web dela. O nº de série sai só como o tamanho dele, e o
endereço MAC só como a metade do fabricante, para a saída poder ser colada numa issue.

## Site da documentação

As páginas em `docs/` também são publicadas como site com o
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/), sempre que mudam na `main`. Cada
página em inglês (`nome.md`) tem a versão em português ao lado (`nome.pt-BR.md`); mude as duas
juntas. As páginas sobre o app inteiro ficam em `docs/`, e as páginas de uma ferramenta numa pasta
própria: `docs/hosts/`, `docs/printers/` e `docs/profiles/`. Cada página abre com as tarefas em
passos numerados curtos, dobra os detalhes em caixas `??? note` e termina com uma tabela "Mensagens
que você pode ver". Para ver o site enquanto escreve:

```
uv run --only-group docs mkdocs serve
```

## Versões

As versões são `0.MENOR.CORREÇÃO` até a 1.0: uma funcionalidade nova aumenta MENOR, uma alteração
só de correções aumenta CORREÇÃO. A barra de título acrescenta um número de build e o commit à
versão, como em `0.26.0 build 514 (abc1234)`, tanto pelo código-fonte quanto no exe. O número de
build conta todos os commits que levaram a ele, então um número maior é sempre um build mais novo.
Pelo código-fonte, a versão vem do próprio `pyproject.toml` do repositório, então já está certa
logo depois de um pull, mesmo antes do `uv sync`.

## Gerar o download

```
uv sync --locked --group build
uv run python scripts/build_exe.py
```

Isso gera a `dist/CapyPanel/` (o CapyPanel.exe e as bibliotecas dele) com o PyInstaller, roda o
autoteste do exe gerado (`CapyPanel.exe --self-test`) e, só se ele passar, grava o
`dist/CapyPanel-<versão>-windows-x64.zip` com o `.sha256` ao lado.

O GitHub Actions roda o mesmo build em todo pull request que mexe no app ou no empacotamento, e
guarda o zip com a execução por alguns dias, para testar antes de uma versão. Na tag de uma versão
(`v0.26.0`) ele também cria um rascunho de release com o zip e o SHA-256; ninguém o vê até alguém
que mantém o projeto publicá-lo.
