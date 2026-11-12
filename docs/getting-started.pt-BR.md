# Primeiros passos

Esta página leva você do primeiro início até a sua primeira lista de PCs, verificada e conectada.
O guia que o CapyPanel mostra na primeira vez que cada ferramenta abre apresenta a própria janela.

## Rodar o CapyPanel

O CapyPanel roda no Windows 10 22H2 ou no Windows 11. Ainda não há instalador, então ele roda a
partir do código-fonte com o [uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

A primeira execução baixa o Python e as bibliotecas de que o CapyPanel precisa; as seguintes abrem
na hora. A Área de Trabalho Remota funciona de cara. Para o VNC você também precisa de um
visualizador: o [UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/).

![A página inicial: a barra lateral à esquerda, a capivara e o nome do app, e um bloco para cada ferramenta](images/home-dark-pt-BR.png)

O CapyPanel abre na página inicial, com um bloco para cada ferramenta: **Hosts** (Ctrl+1),
**Impressoras** (Ctrl+2) e **Perfis de usuário** (Ctrl+3). Clique em **Hosts** para começar.

??? note "Mais sobre o início"

    - A versão aparece na barra de título. Quando você roda pelo código-fonte, ela vem seguida de um
      número de build e do commit, por exemplo `CapyPanel 0.25.0 build 1378 (abc1234)`; um número
      de build maior é um build mais novo. Informe-a ao relatar um problema.
    - A página inicial é o botão de cima da barra lateral, o **Exibir > Início** e o **Ctrl+0**.
      Todas as ferramentas estão sempre lá; não há nada para ligar. Para começar em outro lugar,
      defina **Configurações > CapyPanel > Geral > Abrir ao iniciar** como a última ferramenta usada,
      ou como uma delas pelo nome.
    - Os blocos dizem para que serve cada ferramenta: Hosts "Seus computadores: conecte, veja quem
      está logado, verifique-os.", Impressoras "Suas impressoras: status e toner, páginas web,
      relatórios.", Perfis de usuário "Os perfis de um PC: veja quais podem ser excluídos."

## Adicionar os seus primeiros hosts

![A janela do Hosts: grupos à esquerda, os hosts no meio, os detalhes de um host à direita](images/main-window-dark-pt-BR.png)

1. **Inventário > Adicionar host…** (Ctrl+N).
2. Digite um **Nome** e um **Endereço**, um nome de computador ou endereço IP. Deixe o endereço em
   branco se o nome *for* o nome do computador (por exemplo `PC-1234`).
3. Escolha um **Grupo**, acrescente **Tags** se quiser (digite uma e aperte Enter) e clique em
   **Adicionar**.

As edições são salvas no arquivo da lista na hora; não há botão Salvar. Para adicionar muitos hosts
de uma vez, de uma planilha ou de outro inventário, veja
[Adicionar hosts de uma planilha](hosts/host-lists.pt-BR.md#adicionar-hosts-de-uma-planilha). Para
criar grupos, veja [Listas de hosts](hosts/host-lists.pt-BR.md).

??? note "Mais sobre adicionar hosts"

    - Uma lista nova começa com um grupo, **Grupo padrão**. **Inventário > Adicionar grupo…**
      (Ctrl+Shift+N) cria outro; com um grupo selecionado, o novo fica dentro dele. Já o **+** ao
      lado do título **Grupos**, e o botão direito no título ou num espaço vazio, adicionam um no
      nível superior.
    - **Sem grupo** também é uma opção, para um host que ainda não pertence a lugar nenhum.
    - O **Perfil de conexão** diz como acessar o host; "Do grupo" segue o perfil do grupo (veja
      [Conectando](hosts/connecting.pt-BR.md)).
    - Na caixa Tags, Backspace numa caixa vazia traz a última tag de volta para edição.
    - Uma lista vazia mostra os botões **Adicionar host…** e **Importar hosts…** ali mesmo.

## Verificar e conectar

1. Clique em **Atualizar todos** na barra de ferramentas (F5). A coluna **Status** diz quais hosts
   estão online, e **Usuário** quem está logado.
2. Selecione um host: o painel de detalhes mostra os botões dele, a conexão, quem está logado e o
   que o PC é.
3. Dê um clique duplo no host, ou aperte **Enter**, para abrir a tela dele.

Veja [Verificando hosts](hosts/checking.pt-BR.md), [Conectando](hosts/connecting.pt-BR.md) e
[Comandos em um host](hosts/commands.pt-BR.md) para os próximos passos.

??? note "A janela, parte por parte"

    | Parte | O que mostra |
    |---|---|
    | **Barra lateral** (borda esquerda) | O **Início** (Ctrl+0) no topo, depois um ícone por ferramenta, **Hosts** (Ctrl+1), **Impressoras** (Ctrl+2) e **Perfis de usuário** (Ctrl+3), e **Configurações** (Ctrl+,) embaixo. Onde você está tem um quadrado colorido atrás do ícone |
    | **Barra de ferramentas** (topo) | Os botões da ferramenta aberta. Para o Hosts: **Conectar**, **Atualizar todos**, **Comandos**, **Inventário** e **Relatório** |
    | **Painel de grupos** (esquerda) | O nome da lista aberta no topo, como um menu que troca de lista. Depois "Todos os hosts", com quantos hosts a lista tem, e "Sem grupo", com quantos não estão em nenhum. Depois **Grupos**, com um botão **+** para adicionar um, e **Tags**; arraste a linha acima de Tags para dar mais espaço a um dos dois, e isso fica guardado |
    | **Painel de hosts** (meio) | A caixa de pesquisa acima dos hosts do grupo ou da tag selecionada, com **Status** e **Usuário** |
    | **Painel de detalhes** (direita) | O host selecionado: o nome e o status dele, uma grade de botões para os [comandos](hosts/commands.pt-BR.md) dele, depois **Conexão**, quem está **logado**, os **dados do PC**, as **tags** e as **notas**. Clique em qualquer valor para copiá-lo. Sem nada selecionado, quantos hosts estão exibidos e quantos estão online, offline, não encontrados ou não verificados |
    | **Barra de status** | A lista aberta e as contagens dela, como em "Compartilhada · Clínica · 8 hosts · 3 online · 1 selecionado". Deixe o mouse sobre ela para ver o caminho do arquivo da lista; um clique o copia |

    A barra de menus é a mesma em toda ferramenta. **Arquivo** abre as **Configurações…** (Ctrl+,) e
    o **Sair** (Ctrl+Q). **Exibir** leva ao **Início** e a cada ferramenta, e depois mostra ou
    esconde os painéis, a **Barra de ferramentas** e a **Barra de status**; no Hosts ele também
    guarda **Personalizar o painel de detalhes…** e **Mostrar domínio dos usuários**. Ele fica
    aberto enquanto você marca. **Ajuda** tem **Documentação**, **Relatar um problema** e **Sobre o
    CapyPanel**.

??? note "Organizar a janela"

    - Arraste a borda entre dois painéis para movê-la, ou dê um **clique duplo** na borda direita
      do **painel de grupos** ou do **painel de hosts** para ajustar esse painel ao que tem dentro.
    - Clique com o botão direito nos títulos das colunas da tabela de hosts para escolher quais
      aparecem, ou em **Ajustar colunas ao conteúdo** para ajustar todas ao texto delas; um clique
      duplo na borda de uma coluna ajusta só ela.
    - As larguras são salvas para a próxima vez, e nada as redimensiona por trás, nem uma
      atualização nem trocar de lista.

??? note "O menu do botão direito de um host"

    Clique com o botão direito num host para conectar, para atualizá-lo com **Atualizar host**, para
    executar um dos seus quatro primeiros comandos rápidos ou abrir **Todos os comandos…**, para
    copiar uma coluna em **Copiar ▸**, ou para editá-lo, movê-lo ou removê-lo. Com vários hosts
    selecionados, o menu também escolhe a conta com que os comandos deles rodam, em **Comandos como
    ▸**. O **Copiar** lista todas as colunas que a tabela mostra, uma linha por host selecionado, e
    o **Endereço** mantém o Ctrl+Shift+C. O botão direito num espaço vazio oferece **Adicionar
    grupo…** no painel de grupos, e **Adicionar host…** e **Adicionar grupo…** na lista de hosts.

## Esconder partes do painel de detalhes

1. **Exibir > Personalizar o painel de detalhes…**, ou o botão direito no painel de detalhes.
2. Na aba **Informações**, desmarque o que você não usa: **Conexão**, **Usuários logados**, **Dados
   do PC**, **Tags** ou **Notas**.

"Esconder uma parte não para nenhuma verificação." O pé do painel passa a dizer quantas estão
ocultas, como em "2 partes ocultas · Personalizar…". O nome do host, o status dele e o aviso de
reinício pendente sempre aparecem. A escolha "Vale só para você, neste PC." A outra aba, **Comandos
rápidos**, escolhe os seus botões (veja
[Escolher os seus comandos rápidos](hosts/commands.pt-BR.md#escolher-os-seus-comandos-rapidos)).

## Fechar o CapyPanel, ou deixá-lo na bandeja

O **✕** da janela, o **Arquivo > Sair** (Ctrl+Q) e o Windows fazendo logoff fecham o CapyPanel. Mas
quando a ferramenta Impressoras
[atualiza sozinha](printers/checking.pt-BR.md#atualizar-as-impressoras-sozinho), sair interromperia
isso, então o **✕** pergunta antes: **Manter na bandeja**, **Sair** ou **Cancelar**.

Na bandeja, o ícone do CapyPanel tem a mesma contagem vermelha da barra lateral. Um clique abre a
janela de novo.

![O menu da bandeja: Abrir o CapyPanel, as impressoras que requerem atenção e Sair do CapyPanel](images/tray-menu-dark-pt-BR.png)

??? note "Mais sobre a bandeja e sair"

    - A pergunta diz "Manter o CapyPanel aberto na bandeja?", "A atualização sozinha e os avisos
      continuam funcionando enquanto o CapyPanel estiver na bandeja. Sair os interrompe.", com o
      **Manter na bandeja** como padrão e uma caixa "Não perguntar de novo". Em **Configurações >
      CapyPanel > Geral > Ao fechar** você responde de vez: **Perguntar sempre**, **Manter aberto na
      bandeja** ou **Sair**. Sem nada trabalhando sozinho, o ✕ fecha na hora.
    - O menu da bandeja tem o **Abrir o CapyPanel** em negrito, uma linha por ferramenta com algo a
      relatar, como "3 impressoras requerem atenção…", que abre aquela ferramenta com só esses itens
      listados, e o **Sair do CapyPanel**.
    - Sair enquanto a ferramenta Perfis de usuário exclui perfis pergunta antes: "Sair agora cancela
      os perfis ainda na fila. O perfil sendo excluído em cada host termina primeiro; o CapyPanel
      sai depois disso." O **Cancelar o restante e sair** faz isso; o **Continuar** mantém o
      CapyPanel aberto (veja [Excluir perfis](profiles/user-profiles.pt-BR.md#excluir-perfis)).

## Pedir ajuda, ou relatar um problema

- **Ajuda > Documentação** abre este site, em português quando o app está em português.
- **Ajuda > Relatar um problema** abre uma issue nova no GitHub já com a versão, o Windows, o tema,
  o idioma, o Qt e o Python. Nunca inclui nome de usuário, computador, domínio nem caminho de
  arquivo.
- **Ajuda > Sobre o CapyPanel** abre as Configurações na página **Sobre**, com a versão para copiar,
  as licenças, onde o CapyPanel guarda os arquivos e o **Abrir pasta de logs** (veja
  [Configurações e arquivos](settings-and-files.pt-BR.md#sobre)).

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| Enter (na lista de hosts) | Abrir uma conexão com os hosts selecionados |
| Ctrl+F / Esc | Pesquisar na lista inteira / encerrar a pesquisa |
| F5 | Atualizar os hosts exibidos, verificando o que está marcado no painel do botão Atualizar |
| Ctrl+M | A janela Comandos para um endereço que não está na lista |
| Ctrl+E | Abrir o compartilhamento C$ do host selecionado |
| Ctrl+Shift+O | Abrir um caminho no host selecionado |
| Ctrl+Shift+U | Abrir a pasta do usuário logado |
| Ctrl+Shift+M | O Gerenciamento do Computador, apontado para o host selecionado |
| Ctrl+Shift+C | Copiar os endereços dos hosts selecionados |
| Ctrl+N / Ctrl+Shift+N | Adicionar host / Adicionar grupo |
| F2 / Del | Editar / remover a seleção |
| Ctrl+0 / Ctrl+1 / Ctrl+2 / Ctrl+3 | Início / a ferramenta Hosts / a ferramenta Impressoras / a ferramenta Perfis de usuário |
| Ctrl+O | Abrir um arquivo de lista de hosts |
| Ctrl+, | Configurações |
| Ctrl+Q | Sair |

## Mensagens que você pode ver

| Mensagem | O que significa | O que fazer |
|---|---|---|
| "Algo deu errado. Os detalhes foram salvos no log do aplicativo." | Algo falhou dentro do próprio CapyPanel | **Copiar tudo** e colar no **Relatar um problema**. Um segundo erro entra na mesma janela, e uma repetição é contada ("Este erro aconteceu 3 vezes:") |
| "Esta lista ainda não tem hosts. Adicione um, ou importe vários de uma vez." | A lista está vazia | **Adicionar host…** ou **Importar hosts…** |
