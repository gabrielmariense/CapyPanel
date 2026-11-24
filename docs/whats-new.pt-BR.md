# Novidades

As mudanças de cada versão que você vai notar. As
[versões no GitHub](https://github.com/gabrielmariense/CapyPanel/releases) têm os downloads.

## 0.31.0 <a id="whats-new-0310"></a>

- O CapyPanel funciona só com o teclado na janela principal, nas Configurações, no Hosts, no
  Impressoras, no SSH e na Limpeza de perfis. Um anel na cor de destaque do tema mostra onde o
  teclado está, e a tecla de menu ou Shift+F10 abre o menu que o botão direito abre. O **Exibir >
  Classificar por** e o **Exibir > Colunas** classificam uma tabela e escolhem as colunas dela. Veja
  [Atalhos de teclado](getting-started.pt-BR.md#start-keyboard-shortcuts).
- O terminal do SSH pesquisa texto com o **Pesquisar…** (Ctrl+Shift+F), salva tudo num arquivo com o
  **Salvar todo o texto…** e reorganiza as linhas quando a aba muda de largura.
- O terminal também passa o mouse para os programas que pedem, como o htop e o mc, abre um endereço
  web com Ctrl+clique, marca uma aba com um sino quando um servidor toca a campainha nela, e mostra
  o cursor na forma que um programa pede. Configurações › SSH › Geral define o **Tamanho do texto**
  e o **Histórico de rolagem** dele.
- Uma conexão pode ir para uma janela própria, para um segundo monitor, e voltar: **Mover para uma
  nova janela** no menu do botão direito da aba dela ou do terminal. Veja [Mover uma conexão para
  uma janela própria](ssh/ssh.pt-BR.md#ssh-move-a-connection-to-its-own-window).
- O **Conectar numa janela separada** pode abrir o ssh.exe no Windows Terminal ou em outro programa
  de terminal: **Abrir em**, em Configurações › SSH › Geral.
- Na primeira vez que um servidor conecta numa aba, uma faixa avisa que o ssh.exe vai perguntar se
  você confia nele, e que é para digitar yes, não só y.
- O **Importar hosts…** lê as colunas **Porta SSH** e **Login SSH**, e o **Inventário** do SSH
  também o tem. O Relatório do Hosts escreve as duas, marcadas no **Para importar**.
- No Hosts, clique com o botão direito num host para **Abrir no SSH**, ou em vários para **Abrir {n}
  hosts no SSH**.
- O primeiro início de uma cópia portátil termina o guia do Início com um cartão sobre o que a cópia
  guarda ao lado dela, com **Abrir a pasta userdata**.
- A janela principal abre mais cedo num PC lento: cerca de 0,7 s num que medimos.
- Nos temas do Windows, um botão Usuários ou Energia que não pode ser usado fica todo cinza. Antes,
  a palavra dele continuava âmbar, então ele parecia clicável.
- O CapyPanel termina assim que você o fecha, mesmo no meio de uma verificação de hosts, impressoras
  ou servidores. Antes, ele podia continuar rodando sem aparecer até todos os hosts responderem, e
  uma atualização iniciada nesse meio-tempo era recusada.
- Quando outro CapyPanel da mesma pasta ainda está aberto, a atualização agora diz isso. Antes, ela
  dizia que uma conexão SSH estava aberta numa janela separada.
- Trocar de tema não corre mais o risco de fechar o CapyPanel depois de um dos temas do Windows.
- No Impressoras, os detalhes dizem por que uma impressora recusou ou não pôde ser lida, embaixo da
  linha de status. Configurações › Impressoras › Avisos e suprimentos diz o que Offline, Parada e
  Suprimento baixo querem dizer, e o Adicionar impressora diz quando começar um endereço com
  https://.
- O botão **Atualizar** do Relatório, quando está cinza, diz o motivo numa linha embaixo dele.

## 0.30.1 <a id="whats-new-0301"></a>

- No SSH e na Limpeza de perfis, a linha curta ao lado da aba da lista agora é um traço fino na
  cor das bordas do tema, como os da barra de ferramentas, então não parece mais um cursor de
  texto.
- Numa aba do SSH, uma linha longa demais para a aba, que continua na fileira seguinte, agora é
  copiada como uma linha só e colada inteira. Antes, a cópia tinha uma quebra de linha onde ela
  continuava.

## 0.30.0 <a id="whats-new-0300"></a>

- A F1, o **Ajuda > Ajuda desta tela** ou o novo **?** embaixo na barra lateral abre estas páginas
  na parte da tela em que você está. As Configurações têm um **?** embaixo da lista de páginas, e a
  maioria das janelas tem um no começo da fileira de botões. A F1 fica reservada à ajuda, então não
  pode ir para outro comando. Veja [Pedir ajuda, ou relatar um
  problema](getting-started.pt-BR.md#start-get-help-or-report-a-problem).
- Avisos e erros têm **O que isso significa?** embaixo do texto. Ele abre a linha da mensagem nestas
  páginas, com o que ela quer dizer e o que fazer. A faixa vermelha de um comando que falhou, no
  Hosts e na janela Comandos, também leva ao motivo, e a do SSH também, quando uma conexão termina
  com erro.
- O CapyPanel abre mais rápido com uma lista grande de hosts: com 480 hosts, abriu em cerca de 30%
  menos tempo nos nossos testes. Uma ferramenta que você ainda não abriu preenche a lista quando
  você a abre.
- Na Limpeza de perfis, selecione vários perfis com Ctrl ou Shift e um clique, Shift e as setas, ou
  Ctrl+A, e o **Espaço** marca todos. Um clique na caixa de marcar também faz da linha dela a
  atual, então as setas seguem dali.
- No painel da direita da Limpeza de perfis, a última linha de um cartão, como **e mais 7…**, agora
  é um link: o menu dele lista o resto, e escolher um vai até ele.
- Na Limpeza de perfis e no SSH, as setas de rolagem da barra de abas e o **▾** são botões da altura
  das abas, e nenhuma aba aparece cortada embaixo deles. Com só a lista aberta, a linha curta depois
  da aba dela sumiu.
- A janela de um perfil de conexão mantém um tamanho e as mesmas linhas seja qual for a ferramenta.
  Uma linha que a ferramenta não usa fica cinza, e a dica dela diz o motivo. **Configurações do
  visualizador** agora é **Ajustes**.
- O **Adicionar uma conta** mantém o campo de PC, grupo ou tag no lugar, cinza enquanto **Todos os
  PCs** está escolhido, então escolher onde a conta vale não move nada.
- O perfil inicial do UltraVNC agora vem com o **SecureVNC plugin** marcado. Os perfis iniciais são
  gravados no primeiro início de um PC e pelo **Restaurar originais…**; os perfis que já estão num
  PC ficam como estão.
- Verificar se um PC está ligado não conecta mais na porta do VNC, e o CapyPanel pergunta a cada
  servidor UltraVNC os tipos de login dele uma vez enquanto está aberto. Servidores UltraVNC até a
  1.6.1 recusam um PC depois de seis conexões que não fazem login, então um host que você verificava
  muito e abria pouco podia passar a recusar o seu. Se um ainda recusar, espere um minuto e abra-o
  uma vez pelo UltraVNC Viewer, ou reinicie o serviço do UltraVNC nele.
- As janelas crescem até caber o texto quebrado em linhas quando abrem e quando as linhas delas
  mudam. **Abrir uma pasta** com um caminho longo, **Reiniciar** e **Desligar** abriam cortadas
  antes.
- As Configurações abrem em 960 × 740 na primeira vez, então a lista de páginas cabe inteira também
  nos temas do próprio Windows.
- Mensagens mais claras: um salvamento que falha diz para fechar o arquivo no Excel ou em outro
  programa e salvar de novo, e uma lista que sumiu diz que saiu das suas listas. Quando o
  Gerenciador de Credenciais do Windows recusa uma mudança nas configurações do Impressoras, a caixa
  diz que nada foi alterado.
- Quando salvar de quanto em quanto tempo procurar nova versão falhava, escolher a mesma opção de
  novo não fazia nada. Agora tenta de novo.

## 0.29.0 <a id="whats-new-0290"></a>

- O **SSH** é uma quarta ferramenta (Ctrl+4), para os servidores, switches e outros aparelhos que
  você acessa por SSH. Ele mostra a lista de hosts aberta no Hosts, verifica quais hosts respondem
  na porta SSH e abre um terminal em qualquer um deles numa aba ao lado da lista, pelo próprio
  ssh.exe do Windows. Veja [A ferramenta SSH](ssh/ssh.pt-BR.md).
- O **Entrar como** define a conta com que o ssh.exe entra, para um host ou um grupo inteiro, pelo
  painel de detalhes ou pelo botão direito.
- O **Conectar numa janela separada** abre o ssh.exe fora do CapyPanel. Depois de um erro, a
  janela fica aberta até você pressionar uma tecla, para você ler o motivo.
- O **Inventário > Importar impressoras…** adiciona muitas impressoras de uma vez: de uma lista de
  nomes e endereços, de um Relatório de Impressoras ou da própria lista de impressoras do Windows
  (`Get-Printer`). Uma lista de impressoras vazia também oferece o botão.
- Os quatro blocos da página inicial ficam em duas fileiras iguais.
- A Limpeza de perfis também fecha uma aba com Ctrl+Shift+W, como o SSH.
- Na janela Comandos, o **Adicionar à lista de hosts…** está sempre ali. Quando não há nada para
  adicionar, ele fica cinza e a dica diz o motivo, como onde o PC já está na lista.
- Nos menus do Hosts e do Impressoras, os itens de Atualizar usam o U como letra sublinhada, então
  o R continua sendo do Remover.
- As caixas que a Conexão manual abre, como a da senha, aparecem por cima dela, então ela não fica
  mais atrás da janela principal.
- Uma atualização que encontra um arquivo do CapyPanel em uso, por um CapyPanel em outra sessão do
  Windows ou por uma verificação de antivírus, por exemplo, agora para sem mudar nada, e o
  CapyPanel abre como estava. Antes, uma atualização assim podia deixar o CapyPanel sem abrir.

## 0.28.1 <a id="whats-new-0281"></a>

- A ferramenta Perfis de usuário agora se chama **Limpeza de perfis**, um nome que diz para que ela
  serve. A tecla dela, Ctrl+3, continua a mesma.
- No Hosts, o botão direito num ou em vários hosts oferece **Abrir na Limpeza de perfis**: cada um
  abre lá numa aba própria, escaneado.
- Digite na caixa de pesquisa do Hosts um PC que não está na lista, e o **Conectar a {host}…** abre
  a conexão manual com ele preenchido. O botão **Escanear** da Limpeza de perfis agora aparece do
  mesmo jeito, mesmo quando outros hosts correspondem a parte do nome.
- O **Conectar com**, no painel de detalhes, termina com **Perfis de conexão…**, que abre as
  configurações deles.
- As dicas e o guia do Impressoras mostram a tecla que o comando tem agora, então uma tecla que
  você trocou também aparece ali.
- Na Limpeza de perfis, a lista de hosts e os painéis da direita começam na altura do painel de
  grupos.
- O campo onde você aperta uma nova tecla mantém as palavras centralizadas e no lugar quando uma
  tecla é recusada, e numa janela de Configurações estreita a linha que você está mudando continua
  à vista.

## 0.28.0 <a id="whats-new-0280"></a>

- **Configurações > CapyPanel > Atalhos de teclado** é nova: dê a um comando a tecla que você
  quiser, ou tire a tecla dele. Hosts e Impressoras guardam teclas próprias, mesmo para um comando
  que os dois têm, e os menus mostram as suas teclas na hora.
- A janela de atualização é nova. Ela mostra a sua versão e a nova lado a lado, cada mudança na
  sua linha, e o andamento do download embaixo; depois do reinício ela diz **Atualização
  instalada**.
- Procurar uma nova versão funciona nos PCs em que falhava com "CERTIFICATE_VERIFY_FAILED": agora
  o próprio Windows confere o certificado do GitHub, como o Edge faz. Na 0.27.1 com esse erro,
  abra https://api.github.com no Edge uma vez e depois atualize do jeito de sempre.
- Na janela Comandos, o **Perfil**, uma engrenagem para os perfis de conexão e o **Conectar**
  ficam na linha de cima, ao lado do **Host**, e o **Adicionar à lista de hosts…** foi para baixo,
  à esquerda.
- A tabela de Perfis de usuário não tem mais a coluna **Tipo**. O tipo de um perfil continua nos
  detalhes dele.

## 0.27.1 <a id="whats-new-0271"></a>

- Uma atualização não para mais num arquivo que uma atualização anterior deixou para trás. Cópias
  que não conseguiam sair da 0.26.4, com "Acesso negado", atualizam direto para a 0.27.1, sem nada
  para limpar à mão.

## 0.27.0 <a id="whats-new-0270"></a>

- **Configurações > Impressoras > Avisos e suprimentos** tem uma tabela **Avisos** nova: marque
  quais problemas contam nos avisos do CapyPanel e quais mandam uma notificação do Windows, motivo
  por motivo. Ela substitui a escolha **Notificação do Windows**, que é levada para a tabela.
- O que avisa por padrão mudou. Uma impressora sem papel ou parada sem dizer o motivo não avisa mais
  (marque **Sem papel** ou **Parada** para trazê-las de volta), uma porta aberta ou uma bandeja
  retirada nunca avisa, e um suprimento no nível baixo agora também manda notificação.

## 0.26.4 <a id="whats-new-0264"></a>

- O **Instalar e reiniciar** agora confere a versão nova antes de o CapyPanel fechar, e depois diz
  que o CapyPanel vai abrir de novo sozinho em alguns segundos. Enquanto os arquivos são trocados,
  a tela de abertura diz "Atualizando para a 0.26.4…".
- Uma atualização guarda os arquivos de trabalho na pasta de dados de apps do Windows, nunca ao
  lado da pasta do CapyPanel, e os apaga quando termina. As pastas `CapyPanel.update` e
  `CapyPanel.previous` que atualizações anteriores deixaram ali somem no próximo início.

## 0.26.3 <a id="whats-new-0263"></a>

- Nada muda no app: uma versão para testar as janelas de nova versão da 0.26.2.

## 0.26.2 <a id="whats-new-0262"></a>

- Quando o CapyPanel encontra sozinho uma versão mais nova, a janela de nova versão abre sozinha
  com as notas, no idioma do CapyPanel. Ele procura mais ou menos um segundo depois de abrir.
- Depois do **Instalar e reiniciar**, o CapyPanel abre com uma janela dizendo que a atualização
  foi instalada, ou por que não foi.

## 0.26.1 <a id="whats-new-0261"></a>

- O título da janela mostra só a versão, como em "Padrão — CapyPanel 0.26.1". O número de build e
  o commit ficam em **Ajuda > Sobre o CapyPanel**.

## 0.26.0 <a id="whats-new-0260"></a>

A primeira versão que você pode baixar.

- **Um zip para baixar.** Descompacte e rode o **CapyPanel.exe**: sem instalador, sem direitos de
  administrador. Cada versão traz o SHA-256 do zip ao lado (veja
  [Baixar e atualizar](download.pt-BR.md)).
- **Novas versões de dentro do app.** Quando sai uma versão mais nova, um botão **Nova versão**
  aparece na barra de menus. O **Instalar e reiniciar** baixa, confere e troca os arquivos; as suas
  configurações, listas e logins continuam como estão. O CapyPanel procura a cada início, uma vez
  por dia, uma vez por semana ou nunca, como diz **Configurações > CapyPanel > Geral > Novas
  versões**.
- **Guias.** Na primeira vez que cada tela abre, alguns cartões mostram o que há nela, num PC ou
  numa impressora de exemplo, com o resto da janela escurecido. O **Ajuda > Guia desta tela**
  mostra um guia de novo, e o **Ajuda > Mostrar todos os guias de novo** traz todos de volta.
- **Um aviso antes do primeiro uso do Perfis de usuário**, dizendo o que ele exclui. O
  **Continuar** só funciona depois que você marca que entendeu.
- **O que é de todos neste PC.** Nas Configurações, as seções que são as mesmas para todos que
  usam o CapyPanel no PC dizem **Todos neste PC**, e dizem quem pode alterá-las (veja
  [Configurações para todos neste PC](settings-and-files.pt-BR.md#encontrar-uma-configuracao)).
- **Uma cópia por pessoa.** Abrir o CapyPanel de novo traz a janela aberta para a frente,
  inclusive da bandeja.
- **Ao abrir.** Uma tela de abertura aparece enquanto o CapyPanel carrega, e depois a janela vem
  para a frente, pronta para digitar. O primeiro início usa o idioma em que o Windows aparece.
- **Ao fechar.** Com o **Ao fechar** em **Perguntar sempre**, o ✕ pergunta toda vez.
- **Cores.** Os avisos ficam legíveis em todos os temas, inclusive os claros, assim como os pontos
  e as barras de suprimentos do Impressoras. Graphite e Paper têm os mesmos cantos dos outros temas.
- **Os comandos rápidos** seguem uma ordem só, a da janela Comandos, no painel de detalhes e no
  menu do botão direito.
- **O Atualizar todos** continua quando um PC recusa uma conta que outros PCs aceitaram. Os PCs
  que recusaram da última vez são tentados por último.

Corrigido:

- Marcar um comando rápido podia fechar o CapyPanel.
- No Perfis de usuário, o **Último uso** às vezes ficava em branco.
- Nos temas do Windows, as caixas de marcar das listas não mostravam a caixa.
- No Perfis de usuário, o estado que se chamava **Verificar** agora se chama **Revisar**.
