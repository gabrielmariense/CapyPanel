# Novidades

As mudanças de cada versão que você vai notar. As
[versões no GitHub](https://github.com/gabrielmariense/CapyPanel/releases) têm os downloads.

## 0.28.1

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

## 0.28.0

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

## 0.27.1

- Uma atualização não para mais num arquivo que uma atualização anterior deixou para trás. Cópias
  que não conseguiam sair da 0.26.4, com "Acesso negado", atualizam direto para a 0.27.1, sem nada
  para limpar à mão.

## 0.27.0

- **Configurações > Impressoras > Avisos e suprimentos** tem uma tabela **Avisos** nova: marque
  quais problemas contam nos avisos do CapyPanel e quais mandam uma notificação do Windows, motivo
  por motivo. Ela substitui a escolha **Notificação do Windows**, que é levada para a tabela.
- O que avisa por padrão mudou. Uma impressora sem papel ou parada sem dizer o motivo não avisa mais
  (marque **Sem papel** ou **Parada** para trazê-las de volta), uma porta aberta ou uma bandeja
  retirada nunca avisa, e um suprimento no nível baixo agora também manda notificação.

## 0.26.4

- O **Instalar e reiniciar** agora confere a versão nova antes de o CapyPanel fechar, e depois diz
  que o CapyPanel vai abrir de novo sozinho em alguns segundos. Enquanto os arquivos são trocados,
  a tela de abertura diz "Atualizando para a 0.26.4…".
- Uma atualização guarda os arquivos de trabalho na pasta de dados de apps do Windows, nunca ao
  lado da pasta do CapyPanel, e os apaga quando termina. As pastas `CapyPanel.update` e
  `CapyPanel.previous` que atualizações anteriores deixaram ali somem no próximo início.

## 0.26.3

- Nada muda no app: uma versão para testar as janelas de nova versão da 0.26.2.

## 0.26.2

- Quando o CapyPanel encontra sozinho uma versão mais nova, a janela de nova versão abre sozinha
  com as notas, no idioma do CapyPanel. Ele procura mais ou menos um segundo depois de abrir.
- Depois do **Instalar e reiniciar**, o CapyPanel abre com uma janela dizendo que a atualização
  foi instalada, ou por que não foi.

## 0.26.1

- O título da janela mostra só a versão, como em "Padrão — CapyPanel 0.26.1". O número de build e
  o commit ficam em **Ajuda > Sobre o CapyPanel**.

## 0.26.0

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
