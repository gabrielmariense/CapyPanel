# Pesquisando hosts

A caixa acima da tabela de hosts encontra um host em qualquer lugar da lista aberta, seja qual for
o grupo ou a tag escolhida à esquerda. Digite parte de um nome; maiúsculas e minúsculas não
importam. **Ctrl+F** leva até a caixa.

## O que ela pesquisa

Só o que dá para ver: o nome do computador sempre, o endereço enquanto a coluna **Endereço**
estiver visível, e os usuários logados enquanto a coluna **Usuário** estiver visível. A caixa diz
quais, por exemplo "Pesquisar nome, endereço, usuário". Mostrar ou esconder uma coluna refaz a
pesquisa. Tags e observações não são pesquisadas.

Os usuários vêm da última verificação de **Usuários logados** (veja
[Verificando hosts](checking.pt-BR.md)), então um host que não foi verificado não é encontrado por
quem está nele.

## Enquanto você pesquisa

- Os resultados vêm da lista inteira, então uma coluna **Grupo** aparece depois de **Computador**,
  com o caminho completo do grupo de cada host ("Matriz › Financeiro"). Ela não fica no menu de
  colunas.
- O que você digitou fica marcado como num marca-texto nas colunas Computador, Usuário e Endereço.
- Nada fica escolhido no painel da esquerda.
- A barra de status acrescenta **N encontrados**.
- **Atualizar** verifica só os resultados, e o status automático, só os hosts exibidos.

## Seguir para os resultados e encerrar a pesquisa

- **Seta para baixo** ou **Enter** na caixa leva ao primeiro resultado. Nenhum dos dois conecta,
  então um erro de digitação não chega ao PC errado. Na tabela, o clique duplo e o Enter conectam
  como sempre.
- Clique com o botão direito num host > **Mostrar no grupo** (Ctrl+G) abre o grupo em que ele
  está, encerra a pesquisa e mantém o host selecionado.
- **Esc** encerra a pesquisa de onde você estiver, e o **×** na caixa a limpa. Das duas formas
  você volta para o grupo ou a tag que estava escolhido antes.
- Escolher um grupo ou uma tag à esquerda encerra a pesquisa, e trocar de lista de hosts também.
