# Pesquisando hosts

A caixa acima da tabela de hosts encontra um host em qualquer lugar da lista aberta, seja qual for
o grupo ou a tag escolhida à esquerda. Digite parte de um nome; maiúsculas e minúsculas não
importam. **Ctrl+F** leva até a caixa.

## O que ela pesquisa

A caixa lista exatamente o que ela cobre, "Pesquisar nome, endereço, status, usuário, tags,
notas" quando todas as colunas estão visíveis:

- o **nome** do computador, sempre;
- o **endereço**, o **status**, os **usuários** logados e as **tags**, cada um enquanto a coluna
  dele estiver visível. O status é pesquisado como a coluna o diz, então digitar "online" ou "não
  verificado" lista os hosts com esse status;
- as **notas**, sempre, mesmo sem ter uma coluna própria.

Esconder ou mostrar uma coluna refaz a pesquisa. O status e os usuários vêm da última atualização
(veja [Verificando hosts](checking.pt-BR.md)), então um host que não foi
verificado não é encontrado por quem está nele.

## Enquanto você pesquisa

- O que você digitou fica marcado como num marca-texto onde houver correspondência: nas colunas da
  tabela e nas notas, no painel de detalhes.
- Os resultados vêm da lista inteira, então nada fica escolhido no painel de grupos. O painel de
  detalhes diz em que grupo está o host selecionado, e o CapyPanel nunca salta para lá por conta
  própria.
- A barra de status acrescenta **N resultados**.
- **Atualizar todos** verifica só os resultados, e o status automático, só os hosts exibidos.
- O **Relatório** oferece os resultados como o que exportar, contados, enquanto a
  pesquisa está ativa (veja [Importando e exportando hosts](importing.pt-BR.md)).

Uma pesquisa que não encontra nada diz isso na tabela: "Nenhum host corresponde a “…”."

## Seguir para os resultados e encerrar a pesquisa

- **Seta para baixo** ou **Enter** na caixa leva ao primeiro resultado. Nenhum dos dois conecta,
  então um erro de digitação não chega ao PC errado. Na tabela, o clique duplo e o Enter conectam
  como sempre.
- **Esc** encerra a pesquisa de onde você estiver, e o **×** na caixa a limpa. Das duas formas
  você volta para o grupo ou a tag que estava escolhido antes.
- Escolher um grupo ou uma tag à esquerda encerra a pesquisa, e trocar de lista de hosts também.
