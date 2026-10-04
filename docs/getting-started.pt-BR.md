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
código-fonte, por exemplo `CapyPanel 0.13.0 (abc1234)`. Informe-a ao relatar um problema.

A Área de Trabalho Remota funciona de cara, com o cliente que já vem no Windows. Para o VNC você
também precisa de um visualizador: o [UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). Veja
[Conectando](connecting.pt-BR.md).

## A janela principal

| Parte | O que mostra |
|---|---|
| **Grupos** (esquerda) | "Todos os computadores" fixo no topo, com quantos hosts a lista tem. Depois seus grupos e os grupos dentro deles, e abaixo suas tags |
| **Hosts** (meio) | Os hosts do grupo ou da tag selecionada |
| **Informações** (direita) | Os detalhes do host selecionado, incluindo o perfil de conexão e de onde ele vem |
| **Barra de status** | Qual lista está aberta, onde ela está, quantos hosts tem e quantos estão selecionados |

Cada painel pode ser escondido pelo menu **Exibir**. Para trocar de lista, use **Arquivo > Listas
de hosts…** (veja [Listas de hosts](host-lists.pt-BR.md#a-janela-listas-de-hosts)).

## Adicione seus primeiros hosts

1. Uma lista nova começa com um grupo, **Grupo padrão**. **Inventário > Adicionar grupo…**
   (Ctrl+Shift+N) cria outro; com um grupo selecionado, o novo fica dentro dele.
2. **Inventário > Adicionar host…** (Ctrl+N) adiciona um host ao grupo selecionado:
   - **Nome:** como o host aparece na lista.
   - **Endereço:** um nome de computador ou endereço IP. Deixe em branco se o nome *for* o nome
     do computador (por exemplo `PC-1234`).
   - **Tags:** digite uma tag e pressione Enter; Backspace numa caixa vazia traz a última tag de
     volta para edição.
   - **Perfil de conexão:** como acessar o host. "Do grupo" segue o perfil do grupo.
3. Dê um clique duplo no host, ou selecione-o e pressione Enter, para abrir uma conexão com ele
   pelo perfil dele.

Clique com o botão direito num host para abri-lo, editá-lo ou removê-lo, ou para copiar o
endereço ou o nome. O botão direito num espaço vazio oferece **Adicionar grupo…** no painel de
grupos, e **Adicionar host…** e **Adicionar grupo…** na lista de hosts. Para mover hosts para
outro grupo, arraste-os até ele (veja [Listas de hosts](host-lists.pt-BR.md#organizar-grupos-e-hosts)).

As edições são salvas no arquivo da lista na hora; não há botão Salvar.

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| Enter (na lista de hosts) | Abrir uma conexão com os hosts selecionados |
| Ctrl+M | Conexão manual a um endereço que não está na lista |
| Ctrl+Shift+C | Copiar os endereços dos hosts selecionados |
| Ctrl+N / Ctrl+Shift+N | Adicionar host / Adicionar grupo |
| F2 / Del | Editar / remover a seleção |
| Ctrl+O | Janela Listas de hosts |
| Ctrl+, | Configurações |
| Ctrl+Q | Sair |
