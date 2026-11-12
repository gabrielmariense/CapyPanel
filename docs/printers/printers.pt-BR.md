# A ferramenta Impressoras

O Impressoras guarda as impressoras que você administra, mostra em que estado cada uma está e abre
a página web de qualquer uma. Abra-o pelo bloco **Impressoras** da página inicial, pelo ícone de
impressora na barra lateral ou com **Ctrl+2**.

![A janela Impressoras: grupos à esquerda, as impressoras no meio, os detalhes de uma à direita](../images/printers-dark-pt-BR.png)

Como um Atualizar lê o status e o toner tem uma página própria:
[Verificando impressoras](checking.pt-BR.md).

## Adicionar uma impressora

1. **Inventário > Adicionar impressora…** (Ctrl+N).
2. Digite um **Nome** e o **Endereço**, um IP ou um nome de rede. Isso basta: um Atualizar lê a
   marca, o modelo, o nº de série e o toner na própria impressora.
3. Clique em **Adicionar**.

Os outros campos são opcionais:

| Campo | Para que serve |
|---|---|
| **Grupo** e **Tags** | Onde ela fica na lista, como no Hosts |
| **Marca** e **Modelo** | Preenchidos à mão, ou copiados do que a impressora informa |
| **Nº de série** e **Patrimônio** | Os dois números de que você precisa ao abrir um chamado ou fazer um inventário |
| **Contadores de páginas** | De onde vem a contagem de páginas: **SNMP** ou **Doc360 MPS** |
| **Notas** | O que mais houver |

??? note "Mais sobre os campos"

    - A **Marca** é um menu com as marcas mais comuns (Brother, Canon, Epson, HP, Kyocera,
      Lexmark, Ricoh, Samsung, Xerox, Zebra), e você pode digitar qualquer outra. Marca e nº de
      série são salvos em maiúsculas.
    - **Contadores de páginas** é **SNMP**, perguntado à própria impressora, ou **Doc360 MPS**, o
      portal de impressão gerenciada (veja
      [Contar páginas pelo Doc360 MPS](checking.pt-BR.md#contar-paginas-pelo-doc360-mps)). Um
      Atualizar lê a contagem da origem que você escolher aqui.
    - Uma impressora sem endereço é acessada pelo nome dela.
    - O **Editar selecionado…** (F2) abre a mesma janela para uma impressora que já está na lista,
      com **Salvar** no lugar de **Adicionar**.

## Abrir a página web de uma impressora

Quase toda impressora tem uma página web própria, com configurações, contadores e suprimentos.
Clique em **Abrir página web** na barra de ferramentas, dê um clique duplo na impressora ou aperte
**Enter**. Ela abre no seu navegador padrão.

Se a página da impressora precisar de https, comece o endereço com `https://`. Qualquer outro abre
com http.

??? note "Mais sobre páginas web"

    - Um endereço que começa com `https://` abre exatamente como você digitou, com porta e tudo,
      então `https://prn-01.example.com:8443` chega a uma impressora cuja página web está em outra
      porta. O campo **Endereço** diz isso na dica dele.
    - O CapyPanel abre no máximo dez páginas de uma vez.
    - Só o endereço é passado ao navegador. O CapyPanel não busca nada na impressora e não faz
      login em lugar nenhum.

## Encontrar uma impressora

Digite na caixa de pesquisa acima da tabela (**Ctrl+F**). Para filtrar dentro do grupo em que você
está, escolha uma tag à esquerda; escolha várias para manter só as impressoras que têm todas elas.
Para ver uma tag na lista inteira, escolha **Todas as impressoras** primeiro.

??? note "O que a pesquisa cobre"

    - Todas as colunas à mostra menos Toner, mais as notas; a caixa diz quais são, como em
      "Pesquisar nome, endereço, status, modelo, tags, notas". Mostrar ou esconder uma coluna muda
      o que ela cobre.
    - O status é pesquisado como a coluna o mostra.
    - Com tags escolhidas, uma faixa colorida acima da tabela diz quais, como em "Só impressoras
      com todas estas tags: 2-andar, colorida · 4 de 37 exibidas", com um botão **Limpar**. O
      título **Tags** mostra quantas estão escolhidas e oferece um **×** para limpá-las. As tags
      escolhidas continuam quando você troca de grupo e enquanto você pesquisa.

## Manter impressoras em listas, grupos e tags

O Impressoras tem as próprias listas, separadas das da ferramenta Hosts. O nome da lista aberta
fica no topo do painel de grupos; o menu dele troca de lista e traz **Nova lista de impressoras**,
**Abrir uma lista de impressoras** (Ctrl+O) e **Gerenciar listas de impressoras…**.

Grupos, tags, arrastar, **Mover para ▸**, **Tags ▸** e **Gerenciar grupos…** funcionam exatamente
como no Hosts: veja [Listas de hosts](../hosts/host-lists.pt-BR.md).

??? note "Onde ficam as listas de impressoras"

    Uma lista de impressoras é um arquivo JSON com grupos, impressoras e suas tags. O CapyPanel
    guarda uma pasta para as listas de impressoras nas duas pastas de listas:

    | Pasta | Onde |
    |---|---|
    | **Listas de impressoras compartilhadas** | `C:\ProgramData\CapyPanel\lists\printers` |
    | **Suas listas de impressoras** | `C:\ProgramData\CapyPanel\users\<você@DOMÍNIO>\lists\printers` |

    O Hosts usa `lists\hosts` nos mesmos dois lugares. Uma lista salva numa dessas pastas aparece
    sozinha, a pasta compartilhada é de todos no PC e a sua é privada, e no modo portátil as duas
    ficam dentro da pasta `userdata` do próprio app. Cada arquivo registra de que tipo de lista é.
    [Listas de hosts](../hosts/host-lists.pt-BR.md) traz as regras de nome e o que as permissões do
    Windows decidem.

??? note "Configurações › Impressoras › Geral"

    As **Listas de impressoras** são a tabela de todas as listas com o tipo e o que você pode fazer
    com cada uma, com **Nova…**, **Adicionar existente…** e **Remover**. É a mesma tabela do
    Listas de hosts, inclusive no que o **Remover** pergunta (veja
    [Listas de hosts](../hosts/host-lists.pt-BR.md)). Embaixo dela, **Lista ao iniciar** diz qual
    lista de impressoras abre com a ferramenta, e **Mostrar primeiro** o que essa lista mostra
    quando abre. Cada lista guarda a própria resposta.

    As outras duas páginas do Impressoras, **Avisos e suprimentos** e **Conexão**, estão explicadas
    em [Verificando impressoras](checking.pt-BR.md).

## Exportar impressoras para uma planilha

1. Clique em **Relatório** na barra de ferramentas.
2. Escolha as impressoras e as colunas.
3. Salve o arquivo CSV, ou copie-o.

A janela funciona como a dos hosts (veja
[Exportar hosts para uma planilha](../hosts/host-lists.pt-BR.md#exportar-hosts-para-uma-planilha)).
As colunas vêm em três grupos: **Impressora** (nome, endereço, grupo, marca, modelo, nº de série),
**Detalhes** (patrimônio, contadores de páginas, tags, notas) e **Última verificação** (status,
toner em texto, o modelo do toner, o total de páginas, o endereço MAC e a versão do firmware). A
predefinição que vem pronta é **Todos os detalhes**.

??? note "O que as colunas do relatório trazem"

    - O **modelo do toner** é o nome que a impressora dá aos toners e às tintas dela, que costuma
      incluir o cartucho, como "Black Cartridge HP CF258A"; vários vêm juntos, separados por "; ".
    - O **total de páginas** vem em dígitos simples, para uma planilha ler como número.
    - Marcar qualquer coluna em Última verificação deixa a janela atualizar essas impressoras ali
      mesmo, com um botão que diz quantas são, como **Atualizar 12 impressoras**; ela também diz
      quantas nunca foram verificadas.
    - Uma impressora cujos contadores vêm do Doc360 MPS fica com o número do portal, "20500 (de
      outubro de 2026)" no começo de um mês, ou "Erro" quando o portal não tinha nenhum para ela
      (veja [Contar páginas pelo Doc360 MPS](checking.pt-BR.md#contar-paginas-pelo-doc360-mps)).
    - As impressoras a exportar são os mesmos tipos de escolha do Hosts: os resultados da pesquisa
      ou as tags escolhidas enquanto uma das duas está ativa, as impressoras selecionadas quando
      você tem mais de uma, todas as impressoras, as que não estão em grupo nenhum, cada grupo com
      os subgrupos dele e cada tag, todas elas contadas.

## A janela em detalhe

??? note "A janela, parte por parte"

    | Parte | O que mostra |
    |---|---|
    | **Barra de ferramentas** | **Abrir página web**, **Atualizar todas**, **Inventário** e **Relatório** |
    | **Painel de grupos** (esquerda) | O nome da lista aberta no topo, como um menu, depois "Todas as impressoras" e os grupos e tags da lista |
    | **Painel de impressoras** (meio) | A caixa de pesquisa acima das impressoras do grupo ou da tag que você escolheu |
    | **Painel de detalhes** (direita) | Tudo que se sabe sobre a impressora selecionada, abaixo do nome e do status dela, com um botão **Atualizar** e um **Página web**. Clique em qualquer valor para copiá-lo |
    | **Barra de status** | A lista aberta e as contagens dela, como no Hosts: o tipo, o nome de uma lista compartilhada, quantas impressoras ela tem, quantas estão online depois que alguma foi atualizada e quantas estão selecionadas. Deixe o mouse sobre ela para ver o caminho do arquivo da lista; um clique o copia |

    O **Inventário** guarda **Adicionar impressora…** (Ctrl+N), **Adicionar grupo…** e
    **Gerenciar grupos…**, os mesmos três do Hosts.

??? note "As colunas da tabela"

    - As colunas são **Nome**, **Endereço**, **Status**, **Toner**, **Marca**, **Modelo**, **Nº de
      série**, **Patrimônio** e **Tags**, nessa ordem. Marca, Nº de série e Patrimônio começam
      escondidas: clique com o botão direito nos títulos das colunas para mostrá-las.
    - O **Modelo** põe a marca na frente, como em "ZEBRA ZD421", a não ser que o modelo já comece
      com ela.
    - Antes de uma atualização, o **Status** diz **Não verificado** em cinza, e essas impressoras
      ficam por último na ordenação.
    - As palavras longas de status são encurtadas só na coluna, como **Saída cheia**, **Saída quase
      cheia**, **Saída ausente**, **Pede assistência**, **Coletor quase cheio** e **Suprimento
      baixo**; a dica, o painel de detalhes e as notificações trazem as palavras completas.
    - Clique no título de uma coluna para ordenar por ela, e de novo para inverter. Números dentro
      dos nomes são ordenados como números, então "P2" vem antes de "P10"; maiúsculas e minúsculas
      não importam, e empates ficam em ordem de nome. As colunas não podem ser arrastadas para outra
      posição, em nenhuma das duas ferramentas.

??? note "Menus do botão direito"

    O menu de uma impressora tem **Abrir página web** em negrito (é o que o clique duplo faz),
    **Atualizar impressora** (ou **Atualizar {n} impressoras** com várias selecionadas), **Copiar
    ▸**, **Editar selecionado…** para uma impressora, **Mover para ▸**, **Tags ▸** e **Remover**. O
    **Copiar ▸** lista as colunas na ordem da tabela. O menu de um grupo termina com **Atualizar
    grupo**, que lê as impressoras dele e as dos grupos de dentro.

??? note "O painel de detalhes"

    Embaixo do nome da impressora ficam o status, com a hora da última verificação, e dois botões:
    **Atualizar**, para esta impressora, e **Página web**, esmaecido só quando nem o endereço nem o
    nome dela formam um endereço web.

    As seções são **Conexão** (endereço, grupo, endereço MAC), **Suprimentos**, **Impressora**
    (marca, modelo, nº de série, patrimônio, firmware), **Contadores de páginas** (origem e o total
    da própria impressora), **Tags** e **Notas**. Clique em qualquer valor para copiá-lo. O status,
    as mensagens e os suprimentos chegam com uma atualização, e com ela também a chance de copiar
    para a sua lista o que a impressora informa (veja
    [Verificando impressoras](checking.pt-BR.md#verificar-as-suas-impressoras)).

    **Exibir > Personalizar o painel de detalhes…**, ou o botão direito no painel, pode esconder
    qualquer seção, cada uma descrita pelo que mostra: Conexão "Endereço, grupo, MAC", Suprimentos
    "Toner, tinta e o resto, com os níveis", Impressora "Marca, modelo, nº de série, firmware",
    Contadores de páginas "Total de páginas e a origem", e Tags e Notas. "Sempre aparecem: o nome
    da impressora e o status."

## Mensagens que você pode ver

| Mensagem | O que significa | O que fazer |
|---|---|---|
| "“{path}” não é uma lista de impressoras." | O arquivo que você abriu é uma lista de hosts | Abra-o no Hosts |
| "10 páginas web abertas. Só as 10 primeiras abrem de uma vez." | Havia mais de dez impressoras selecionadas | Abra as outras numa segunda vez |
| "Marque uma coluna em Última verificação para lê-las" | O botão de atualizar do Relatório não tem nada para ler | Marque uma coluna em Última verificação |
