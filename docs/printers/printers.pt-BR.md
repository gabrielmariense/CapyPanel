# A ferramenta Impressoras

Impressoras é a segunda ferramenta do CapyPanel: um inventário das impressoras que você
administra, com o que é preciso para diferenciar uma da outra e um jeito de abrir a página web de
qualquer uma. Abra-a pelo bloco **Impressoras** da página inicial, pelo ícone de impressora na
barra lateral ou com **Ctrl+2**.

Ela tem as próprias listas, separadas das da ferramenta Hosts (veja
[Listas de impressoras](printer-lists.pt-BR.md)).

## A janela

![A janela Impressoras: grupos à esquerda, as impressoras no meio, os detalhes de uma à direita](../images/printers-dark-pt-BR.png)

| Parte | O que mostra |
|---|---|
| **Barra de ferramentas** | **Abrir página web**, **Atualizar**, **Inventário** e **Relatório** |
| **Painel de grupos** (esquerda) | O nome da lista aberta no topo, como um menu, depois "Todas as impressoras" e os grupos e tags da lista |
| **Painel de impressoras** (meio) | A caixa de pesquisa acima das impressoras do grupo ou da tag que você escolheu |
| **Painel de detalhes** (direita) | Tudo que se sabe sobre a impressora selecionada. Clique em qualquer valor para copiá-lo |
| **Barra de status** | Qual lista está aberta, onde ela está, quantas impressoras tem e quantas estão selecionadas |

O **Atualizar** lê o status e os suprimentos de todas as impressoras exibidas, por SNMP, e
preenche as colunas **Status** e **Toner**. Ele tem uma página própria:
[Verificando impressoras](checking.pt-BR.md).

O **Inventário** guarda **Adicionar impressora…** (Ctrl+N), **Adicionar grupo…** e **Gerenciar
grupos…**, os mesmos três do Hosts.

### A tabela

As colunas são **Nome**, **Endereço**, **Status**, **Toner**, **Marca**, **Modelo**, **Nº de
série**, **Patrimônio** e **Tags**, nessa ordem. Nº de série e Patrimônio começam escondidas:
clique com o botão direito nos títulos das colunas para mostrá-las. Status e Toner ficam vazias
até você atualizar. Esse mesmo menu, e o **Copiar ▸** de uma impressora, listam as
colunas nessa ordem. As colunas não podem ser arrastadas para outra posição, em nenhuma das duas
ferramentas.

Clique no título de uma coluna para ordenar por ela, e de novo para inverter. Números dentro dos
nomes são ordenados como números, então "P2" vem antes de "P10"; maiúsculas e minúsculas não
importam, e impressoras empatadas ficam em ordem de nome.

## Adicionar uma impressora

**Inventário > Adicionar impressora…** (Ctrl+N) pede:

- **Nome** e **Endereço**, sendo o endereço um IP ou um nome de rede. Uma impressora sem endereço é
  acessada pelo nome dela.
- **Grupo** e **Tags**, que funcionam como no Hosts.
- **Marca** e **Modelo**. Marca é um menu com as marcas mais comuns (Brother, Canon, Epson, HP,
  Kyocera, Lexmark, Ricoh, Samsung, Xerox, Zebra), e você pode digitar qualquer outra.
- **Nº de série** e **Patrimônio**, os dois números de que você precisa ao abrir um chamado ou
  fazer um inventário. Marca e nº de série são salvos em maiúsculas.
- **Contadores de páginas**, que diz de onde virão as contagens: **SNMP**, perguntado à própria
  impressora, ou **Doc360 MPS**, o portal de impressão gerenciada. Nada lê contadores ainda; a
  configuração registra de onde eles serão lidos.
- **Notas**, para o que mais houver.

**Editar selecionado…** (F2) abre a mesma janela para impressoras que já estão na lista.

O painel de **detalhes** mostra tudo isso, em **Conexão** (endereço, grupo), **Suprimentos**,
**Impressora** (marca, modelo, nº de série, patrimônio), **Contadores de páginas** (origem e o
total da própria impressora), **Tags** e **Notas**. O status, as mensagens da impressora e os
suprimentos chegam com uma atualização, e com ela também a chance de copiar para a sua lista a
marca, o modelo ou o nº de série que a impressora informa.

## Abrir a página web de uma impressora

Quase toda impressora tem uma página web própria, com configurações, contadores e suprimentos. O
**Abrir página web** abre essa página no seu navegador padrão, e um clique duplo na impressora ou a
tecla **Enter** fazem o mesmo. Clique com o botão direito numa impressora e esse item aparece em
negrito, porque é o que o clique duplo faz.

Um endereço que começa com `https://` abre com https, exatamente como você digitou, com porta e
tudo, então `https://prn-01.example.com:8443` chega a uma impressora cuja página web está em outra
porta. Qualquer outro abre com http. O campo **Endereço** diz isso na dica dele: "Comece com
https:// se a página web da impressora precisar; senão ela abre com http."

O CapyPanel abre no máximo dez páginas de uma vez. Selecione mais e a barra de status diz "10
páginas web abertas. Só as 10 primeiras abrem de uma vez."

Só o endereço é passado ao navegador. O CapyPanel não busca nada na impressora e não faz login em
lugar nenhum.

## Encontrar uma impressora

A caixa de pesquisa acima da tabela cobre todas as colunas à mostra, mais as notas, e o texto dela
diz quais são, como em "Pesquisar nome, endereço, marca, modelo, tags, notas". O **Ctrl+F** leva
até ela. Mostrar ou esconder uma coluna muda o que a pesquisa cobre.

As tags filtram o que a tabela mostra, e você pode escolher várias de uma vez: a tabela então
mantém só as impressoras que têm todas elas. Uma faixa colorida acima da tabela diz quais, como em
"Só impressoras com todas estas tags: 2-andar, colorida · 4 de 37 exibidas", com um botão
**Limpar**; o título **Tags** mostra quantas estão escolhidas e oferece um **×** para limpá-las. As
tags escolhidas continuam quando você troca de grupo e enquanto você pesquisa. Quando nada
corresponde, a tabela diz "Nenhuma impressora deste grupo tem todas as tags escolhidas." e oferece
**Limpar tags**.

Uma tag filtra dentro do grupo que você escolheu. Para ver uma tag na lista inteira, escolha
**Todas as impressoras** primeiro.

## Relatório

O **Relatório** grava as impressoras que você escolher, com as colunas que você escolher, num
arquivo CSV. Ele funciona exatamente como o dos hosts, então
[Importando e exportando hosts](../hosts/importing.pt-BR.md#exportando-hosts) descreve a janela
inteira.

O que muda é o que entra nele. As colunas são agrupadas em **Impressora** (nome, endereço, grupo,
marca, modelo), **Detalhes** (nº de série, patrimônio, contadores de páginas, tags, notas) e
**Última verificação** (status e toner, em texto). A predefinição que vem pronta é **Todos os
detalhes**.

Marcar Status ou Toner deixa a janela atualizar essas impressoras ali mesmo, e ela diz quantas
nunca foram verificadas. Sem nenhuma das duas marcada o botão se explica: "Marque Status ou Toner
para lê-las".

As impressoras a exportar são os mesmos tipos de escolha do Hosts: os resultados da pesquisa ou as
tags escolhidas enquanto uma das duas está ativa, as impressoras selecionadas quando você tem mais
de uma, todas as impressoras, as que não estão em grupo nenhum, cada grupo com os subgrupos dele e
cada tag, todas elas contadas.
