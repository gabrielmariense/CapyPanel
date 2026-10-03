<h1 align="center">CapyPanel</h1>

<p align="center">
  <a href="README.md"><img src="https://flagcdn.com/40x30/us.png" width="40" height="30" alt="English" title="English"></a>
  &nbsp;
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/40x30/br.png" width="40" height="30" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

O CapyPanel reúne numa só janela todos os computadores que você administra. É um app de desktop
para Windows feito para equipes de TI: organize seus hosts em listas e abra a tela remota de
qualquer um deles com o visualizador VNC que você já usa.

Feito para qualquer organização: nada fica preso à rede, às ferramentas ou ao idioma de uma
empresa.

> **Situação: alfa (0.10.0).** Já dá para usar, e cresce uma funcionalidade por vez. Roda a partir
> do código-fonte; ainda não há instalador.

## Funcionalidades

### Lançadas

- Tela remota (UltraVNC, RealVNC)
- Perfis de conexão
- Listas de hosts compartilhadas

### Em desenvolvimento

- Área de Trabalho Remota (RDP)
- Usuários conectados

### Planejadas

- SSH
- Busca e status
- Ações nos hosts

## Documentação

Também online, com busca: **[gabrielmariense.github.io/CapyPanel/pt-BR](https://gabrielmariense.github.io/CapyPanel/pt-BR/)**.

- [Primeiros passos](docs/getting-started.pt-BR.md): rode o CapyPanel e adicione seus primeiros
  hosts
- [Listas de hosts](docs/host-lists.pt-BR.md): grupos, tags e as listas padrão, pessoal e
  compartilhadas
- [Conectando](docs/connecting.pt-BR.md): visualizadores VNC, perfis de conexão e senhas
- [Configurações e arquivos](docs/settings-and-files.pt-BR.md): o que cada configuração faz e
  onde o CapyPanel guarda os arquivos
- [Desenvolvimento](docs/development.pt-BR.md): compilar, testar e traduzir

## Início rápido (pelo código-fonte)

Você precisa do Windows 10 22H2 ou 11 e do [uv](https://docs.astral.sh/uv/), que instala o Python
e todo o resto:

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

Para abrir telas remotas, instale o [UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). O CapyPanel os abre; nunca
os distribui nem baixa.

## Licença

[GPL-3.0](LICENSE).
