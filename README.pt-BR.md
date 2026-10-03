<p align="right">
  <a href="README.md"><img src="https://flagcdn.com/24x18/us.png" width="24" height="18" alt="English" title="English"></a>
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/24x18/br.png" width="24" height="18" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

# CapyPanel

Um app de desktop para Windows feito para equipes de TI: mantenha os computadores da sua rede em
uma lista organizada e abra a tela remota de qualquer um deles com as ferramentas que você já usa.

- **Listas de hosts** com grupos aninhados, tags e observações. Uma lista é um arquivo JSON
  simples: tenha uma pessoal, compartilhe uma numa pasta de rede ou publique uma lista padrão
  para todos no PC.
- **Tela remota (VNC)** pelo UltraVNC Viewer ou pelo RealVNC Viewer, aberta com um clique duplo
  ou Enter, para um host ou vários de uma vez.
- **Perfis de conexão** dizem como cada host é acessado: qual visualizador, qual login (usuário e
  senha, ou só senha) e opções como o plugin SecureVNC do UltraVNC. Defina um num grupo e todos
  os hosts dentro dele o seguem.
- **As senhas ficam na memória**, uma por perfil, até o CapyPanel fechar; nunca são salvas. Antes
  de enviar uma senha do Windows, o CapyPanel confere se o servidor pede uma.
- **Inglês e português (Brasil)**, trocados na hora. **Sete temas**, do Windows nativo ao visual
  próprio do CapyPanel.

Feito para qualquer organização: nada fica preso à rede, às ferramentas ou ao idioma de uma
empresa.

> **Situação: alfa (0.9.0).** Já dá para usar, e cresce uma funcionalidade por vez. Roda a partir
> do código-fonte; ainda não há instalador.

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
