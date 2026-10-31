<h1 align="center">
  <img src="docs/images/capypanel-icon.png" width="96" height="96" alt=""><br>
  CapyPanel
</h1>

<p align="center">Todos os computadores sob seus cuidados, em uma só janela.</p>

<p align="center">
  <a href="README.md"><img src="https://flagcdn.com/40x30/us.png" width="40" height="30" alt="English" title="English"></a>
  &nbsp;
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/40x30/br.png" width="40" height="30" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

O CapyPanel é um app de desktop para Windows feito para equipes de TI: organize em listas os
computadores que você administra, veja quais estão ligados e quem está logado neles, e abra a tela
remota de qualquer um pela Área de Trabalho Remota ou pelo visualizador VNC que você já usa. Ele
guarda também as suas impressoras, com os detalhes de que você precisa e a página web delas a um
clique.

> **Situação: beta (0.21.1).** Roda a partir do código-fonte; ainda não há instalador.

![A página inicial do CapyPanel: a barra lateral, a capivara e um bloco para Hosts e outro para Impressoras](docs/images/home-dark-pt-BR.png)

## O que ele faz

- Hosts
  - Conexão remota: UltraVNC, RealVNC, Área de Trabalho Remota
  - Perfis de conexão
  - Listas compartilhadas, grupos e tags
  - Status e usuários logados
  - Pesquisa, importação e exportação
- Impressoras
  - Listas com marca, modelo, nº de série e patrimônio
  - Status, toner e suprimentos por SNMP
  - Páginas web e relatórios

## Documentação

Também online, com busca: **[gabrielmariense.github.io/CapyPanel/pt-BR](https://gabrielmariense.github.io/CapyPanel/pt-BR/)**.

- [Primeiros passos](docs/getting-started.pt-BR.md): rode o CapyPanel e adicione seus primeiros
  hosts
- [Configurações e arquivos](docs/settings-and-files.pt-BR.md): o que cada configuração faz e
  onde o CapyPanel guarda os arquivos
- [Listas de hosts](docs/hosts/host-lists.pt-BR.md): grupos, tags e as pastas de listas
- [Importando e exportando hosts](docs/hosts/importing.pt-BR.md): muitos hosts de uma vez, entrando
  e saindo em CSV
- [Conectando](docs/hosts/connecting.pt-BR.md): visualizadores VNC, Área de Trabalho Remota, perfis
  de conexão e senhas
- [Verificando hosts](docs/hosts/checking.pt-BR.md): status e usuários logados
- [Pesquisando hosts](docs/hosts/searching.pt-BR.md): encontrar um host em qualquer lugar da lista
- [A ferramenta Impressoras](docs/printers/printers.pt-BR.md): impressoras, os detalhes delas e as
  páginas web
- [Verificando impressoras](docs/printers/checking.pt-BR.md): status, toner e suprimentos por SNMP
- [Listas de impressoras](docs/printers/printer-lists.pt-BR.md): onde as listas de impressoras
  ficam e as configurações delas
- [Desenvolvimento](docs/development.pt-BR.md): compilar, testar e traduzir

## Início rápido (pelo código-fonte)

Você precisa do Windows 10 22H2 ou 11 e do [uv](https://docs.astral.sh/uv/), que instala o Python
e todo o resto:

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

A Área de Trabalho Remota usa o cliente que já vem no Windows. Para o VNC, instale o
[UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/).

## Licença

[GPL-3.0](LICENSE).

Ícones: [Tabler Icons](https://tabler.io/icons) (MIT), aviso em
`src/capypanel/ui/tabler/LICENSE`.
