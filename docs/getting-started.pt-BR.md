# Primeiros passos

## Rodar o CapyPanel

O CapyPanel roda no Windows 10 22H2 ou no Windows 11. Ainda não há instalador, então ele roda a
partir do código-fonte com o [uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

A primeira execução baixa o Python e as bibliotecas de que o CapyPanel precisa; as seguintes
abrem na hora. A versão aparece na barra de título, seguida do commit quando você roda pelo
código-fonte, por exemplo `CapyPanel 0.17.0 (abc1234)`. Informe-a ao relatar um problema.

A Área de Trabalho Remota funciona de cara, com o cliente que já vem no Windows. Para o VNC você
também precisa de um visualizador: o [UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). Veja
[Conectando](connecting.pt-BR.md).

## A janela principal

| Parte | O que mostra |
|---|---|
| **Barra de ferramentas** (topo) | **Conectar**, e **Atualizar** para verificar os hosts exibidos (veja [Verificando hosts](checking.pt-BR.md)) |
| **Grupos** (esquerda) | "Todos os hosts" fixo no topo, com quantos hosts a lista tem. Depois **Grupos**, com um botão **+** para adicionar um, e **Tags** |
| **Pesquisa** (acima dos hosts) | Encontra um host em qualquer lugar da lista, seja o que for que esteja escolhido à esquerda (veja [Pesquisando hosts](searching.pt-BR.md)) |
| **Hosts** (meio) | Os hosts do grupo ou da tag selecionada, com **Status** e **Usuário** |
| **Detalhes** (direita) | O host selecionado: o nome e o status dele, depois **Conexão** (endereço, grupo, perfil), quem está **logado**, as **tags** e as **notas**. Clique em qualquer valor para copiá-lo. Sem nada selecionado, quantos hosts estão exibidos e quantos deles estão online, offline, não encontrados ou não verificados |
| **Barra de status** | Qual lista está aberta, onde ela está, quantos hosts tem, quantos estão online depois que algo foi verificado e quantos estão selecionados |

A barra de ferramentas, a barra de status e os painéis em volta da tabela de hosts podem ser
escondidos pelo menu **Exibir**, e os painéis podem ser arrastados para ficar mais largos ou mais
estreitos. Para trocar de lista, use **Arquivo > Listas de hosts…** (veja
[Listas de hosts](host-lists.pt-BR.md#a-janela-listas-de-hosts)).

A janela é sua para organizar. Clique com o botão direito nos títulos das colunas da tabela de
hosts para escolher quais aparecem, ou em **Ajustar colunas ao conteúdo**, no fim desse menu, para
ajustar todas ao texto delas; um clique duplo na borda de uma coluna ajusta só ela. As larguras
são salvas para a próxima vez, e nada as redimensiona por trás — nem uma atualização, nem trocar
de lista. **Exibir > Redefinir layout** devolve os painéis, as colunas e o que você escondeu ao
estado inicial, e não mexe nas suas configurações.

## Adicione seus primeiros hosts

1. Uma lista nova começa com um grupo, **Grupo padrão**. **Inventário > Adicionar grupo…**
   (Ctrl+Shift+N) cria outro; com um grupo selecionado, o novo fica dentro dele. Já o **+** ao
   lado do título **Grupos**, e o botão direito no título ou num espaço vazio, adicionam um no
   nível superior.
2. **Inventário > Adicionar host…** (Ctrl+N) adiciona um host ao grupo selecionado:
   - **Nome:** como o host aparece na lista.
   - **Endereço:** um nome de computador ou endereço IP. Deixe em branco se o nome *for* o nome
     do computador (por exemplo `PC-1234`).
   - **Tags:** digite uma tag e pressione Enter; Backspace numa caixa vazia traz a última tag de
     volta para edição.
   - **Perfil de conexão:** como acessar o host. "Do grupo" segue o perfil do grupo.
3. Dê um clique duplo no host, selecione-o e pressione Enter, ou clique em **Conectar** na barra
   de ferramentas, para abrir uma conexão com ele pelo perfil dele.

Clique com o botão direito num host para conectar, verificá-lo, mostrá-lo no grupo dele, copiar o
endereço ou o nome, ou editá-lo ou removê-lo. O botão direito num espaço vazio oferece
**Adicionar grupo…** no painel de grupos, e **Adicionar host…** e **Adicionar grupo…** na lista de
hosts. Para mover hosts para outro grupo, arraste-os até ele (veja
[Listas de hosts](host-lists.pt-BR.md#organizar-grupos-e-hosts)). Remover um grupo pergunta o que
fazer com os grupos e hosts dentro dele (veja
[Listas de hosts](host-lists.pt-BR.md#remover-um-grupo)).

As edições são salvas no arquivo da lista na hora; não há botão Salvar.

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| Enter (na lista de hosts) | Abrir uma conexão com os hosts selecionados |
| Ctrl+F / Esc | Pesquisar na lista inteira / encerrar a pesquisa |
| Ctrl+G | Mostrar o host selecionado no grupo dele |
| Ctrl+M | Conexão manual a um endereço que não está na lista |
| Ctrl+Shift+C | Copiar os endereços dos hosts selecionados |
| Ctrl+N / Ctrl+Shift+N | Adicionar host / Adicionar grupo |
| F2 / Del | Editar / remover a seleção |
| Ctrl+O | Janela Listas de hosts |
| Ctrl+, | Configurações |
| Ctrl+Q | Sair |
