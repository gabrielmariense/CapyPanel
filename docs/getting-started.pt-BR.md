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
código-fonte, por exemplo `CapyPanel 0.10.1 (abc1234)`. Informe-a ao relatar um problema.

Para abrir telas remotas você também precisa de um visualizador VNC: o
[UltraVNC](https://uvnc.com) ou o
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). Veja
[Conectando](connecting.pt-BR.md).

## A janela principal

| Parte | O que mostra |
|---|---|
| **Grupos** (esquerda) | "Todos os computadores", depois seus grupos e os grupos dentro deles. Abaixo, suas tags |
| **Hosts** (meio) | Os hosts do grupo ou da tag selecionada |
| **Informações** (direita) | Os detalhes do host selecionado, incluindo o perfil de conexão e de onde ele vem |
| **Barra de status** | Qual lista está aberta, onde ela está, quantos hosts tem e quantos estão selecionados |

Cada painel pode ser escondido pelo menu **Exibir**.

## Adicione seus primeiros hosts

1. **Inventário > Adicionar grupo…** (Ctrl+Shift+N) cria um grupo. Com um grupo selecionado, o
   novo fica dentro dele.
2. **Inventário > Adicionar host…** (Ctrl+N) adiciona um host ao grupo selecionado:
   - **Nome:** como o host aparece na lista.
   - **Endereço:** um nome de computador ou endereço IP. Deixe em branco se o nome *for* o nome
     do computador (por exemplo `PC-1234`).
   - **Tags:** digite uma tag e pressione Enter; Backspace numa caixa vazia traz a última tag de
     volta para edição.
   - **Perfil de conexão:** como acessar o host. "Do grupo" segue o perfil do grupo.
3. Dê um clique duplo no host, ou selecione-o e pressione Enter, para abrir a tela remota.

As edições são salvas no arquivo da lista na hora; não há botão Salvar.

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| Enter (na lista de hosts) | Abrir a tela remota dos hosts selecionados |
| Ctrl+M | Conexão manual a um endereço que não está na lista |
| Ctrl+Shift+C | Copiar os endereços dos hosts selecionados |
| Ctrl+N / Ctrl+Shift+N | Adicionar host / Adicionar grupo |
| F2 / Del | Editar / remover a seleção |
| Ctrl+O | Abrir uma lista de hosts |
| Ctrl+, | Configurações |
| Ctrl+Q | Sair |
