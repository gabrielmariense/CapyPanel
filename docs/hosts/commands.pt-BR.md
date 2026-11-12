# Comandos em um host

Os comandos de um host são as tarefas de todo dia que você faria por um console: abrir o disco C:
de um PC, ver o que está instalado, mandar uma mensagem para quem o está usando ou fazer logoff
dessa pessoa, reiniciá-lo ou destravar a impressão dele. Eles funcionam em um host por vez. Nada é
instalado no outro PC: todo comando usa as próprias funções remotas do Windows.

![O painel de detalhes: a fileira fixa de botões, os comandos rápidos embaixo dela, e depois Conexão, Logados e Dados do PC](../images/commands-details-dark-pt-BR.png)

## Executar um comando num host

1. Selecione o host.
2. Clique num botão do painel de detalhes, use o botão direito no host, ou abra o **Comandos ▾** da
   barra de ferramentas.
3. Os comandos que atrapalham quem está usando o PC ficam em âmbar, e sempre perguntam antes.

A primeira fileira do painel de detalhes é sempre **Atualizar**, **Comandos** (a
[janela Comandos](#a-janela-comandos)), **Usuários ▾** (fazer logoff ou desconectar alguém) e
**Energia ▾** (reiniciar ou desligar). Os seus [comandos rápidos](#escolher-os-seus-comandos-rapidos)
vêm depois, quatro por fileira.

??? note "Todos os lugares onde um comando começa"

    - **Botão direito num host:** **Conectar** em negrito, **Atualizar host**, os seus quatro
      primeiros comandos rápidos, e depois **Todos os comandos…**, **Copiar ▸**, **Editar…**,
      **Mover para ▸**, **Tags ▸** e **Remover**. Com vários hosts selecionados, o menu traz o que
      funciona em todos eles: **Conectar**, **Atualizar {n} hosts**, **Comandos como ▸**, **Copiar
      ▸**, **Mover para ▸**, **Tags ▸** e **Remover**.
    - **A barra de ferramentas:** o **Comandos** abre a janela Comandos para o host selecionado. A
      seta dele lista todos os comandos por grupo (**Verificar**, **Pastas**, **Ferramentas
      administrativas**, **Usuários**, **Impressoras** e **Energia**) e termina com **Todos os
      comandos…**.
    - **Uma pessoa em Logados:** botão direito nela nos detalhes para **Enviar uma mensagem para
      {user}…**, **Desconectar {user}…** e **Fazer logoff de {user}…**, e depois **Copiar ▸**.
    - Uma dica dá o nome completo de cada botão.

??? note "Qual conta um comando usa"

    A que o **Comandos como** do painel de detalhes diz para o host: o seu próprio login do Windows,
    a não ser que uma conta tenha sido definida para ele (veja
    [Usar outra conta em alguns PCs](connecting.pt-BR.md#usar-outra-conta-em-alguns-pcs)). Os
    comandos usam o compartilhamento de arquivos, o serviço de sessões, o desligamento remoto, o
    spooler de impressão, o gerenciador de serviços e o WMI para os dados do PC, os programas e as
    unidades mapeadas (veja [Como o CapyPanel lê outros PCs](checking.pt-BR.md#ler-os-dados-de-um-pc)).

    Um comando feito para a pessoa no PC, como Enviar uma mensagem ou a pasta do usuário, diz "…
    (ninguém conectado)" e fica esmaecido quando a última atualização do host, de menos de 10
    minutos atrás, não encontrou ninguém. Antes de qualquer atualização, ou depois que ela fica mais
    velha, ele continua utilizável.

## Escolher os seus comandos rápidos

![A janela Personalizar o painel de detalhes na aba Comandos rápidos: todos os comandos por grupo, na ordem da janela Comandos, quatro marcados](../images/customize-dark-pt-BR.png)

1. Abra **Exibir > Personalizar o painel de detalhes…**, ou clique com o botão direito no painel de
   detalhes.
2. Na aba **Comandos rápidos**, marque os comandos que você quer como botões. Cada mudança aparece
   no painel na hora.

Os botões seguem a ordem da janela Comandos, no painel e no menu do botão direito, então um
comando fica sempre no mesmo lugar.

Cada administrador escolhe os seus: a escolha fica nas suas configurações neste PC, nunca na lista.
O CapyPanel começa com **Compartilhamento C$**, **Pasta do usuário**, **Gerenciamento do
Computador** e **Enviar uma mensagem…**, e o **Restaurar padrão…** volta a eles. Os quatro primeiros
também ficam no menu do botão direito do host.

??? note "Mais sobre os comandos rápidos"

    - **Configurações > Hosts > Geral > Painel de detalhes > Comandos rápidos > Escolher…** abre a
      mesma aba.
    - A aba lista todos os comandos por grupo, na ordem da janela Comandos, cada um com o atalho
      em cinza e a palavra que o botão mostra; marcar um não o tira do lugar. Uma linha abaixo da
      tabela os conta, como em "6 de 15 marcados · 2 fileiras no painel", e outra diz "Os quatro
      primeiros marcados também ficam no menu do botão direito de um host."
    - Qualquer um destes pode ser um comando rápido: Status, Usuários logados, Dados do PC,
      Programas instalados, Compartilhamento C$, Pasta do usuário, Pasta Inicializar, Abrir um
      caminho…, Gerenciamento do Computador, Visualizador de Eventos, Serviços, Enviar uma
      mensagem…, Unidades mapeadas, Impressoras deste PC e Reiniciar o Spooler de Impressão….
      "Reiniciar, Desligar, Fazer logoff e Desconectar não podem ser comandos rápidos: eles
      interrompem alguém."

## Abrir as pastas e as ferramentas administrativas de um PC

Estes abrem algo no *seu* PC, apontado para o outro:

| Comando | O que abre |
|---|---|
| **Compartilhamento C$** (Ctrl+E) | O disco C: do PC no Explorador de Arquivos |
| **Pasta de {usuário}** (Ctrl+Shift+U) | A pasta de perfil do usuário conectado |
| **Pasta Inicializar** | Os programas que iniciam para todo usuário que entra |
| **Abrir um caminho…** (Ctrl+Shift+O) | Qualquer pasta do PC, como `D:\Logs` |
| **Gerenciamento do Computador** (Ctrl+Shift+M) | O Gerenciamento do Computador do Windows, apontado para o PC |
| **Visualizador de Eventos** | Os logs de eventos do PC |
| **Serviços** | Os serviços do Windows no PC |

??? note "Mais sobre pastas e caminhos"

    - Uma pasta espera o PC responder antes de o Explorador de Arquivos abrir, porque o próprio
      Explorador pode travar por meio minuto num PC desligado. Os três consoles do Windows abrem na
      hora e mostram o erro deles quando o PC não pode ser alcançado.
    - O **Abrir um caminho…** aceita o caminho do jeito que você já o tem: como o Explorador de
      Arquivos copia, com aspas e tudo (`"D:\Logs\App"`), em outro disco (`D:\Logs` ou `D$\Logs`),
      só no C: (`Users\Public`), ou um caminho `\\PC\compartilhamento\…` inteiro. Uma linha embaixo
      da caixa mostra o que vai abrir, como em "Abre \\DESK-02\D$\Logs\App". A caixa guarda as
      últimas 10 pastas que você abriu.
    - Um caminho que não é uma pasta é recusado, para que um arquivo nunca seja aberto, e assim
      executado, no seu próprio PC.
    - Abrir uma pasta diz "Aberto: \\DESK-02\C$" na barra de status.

## Mandar mensagem, fazer logoff ou desconectar alguém

- O **Enviar uma mensagem…** aparece na tela de todos que estão conectados no PC até clicarem em
  OK, com o título "Mensagem de {seu usuário do Windows}". O Windows mostra cerca de 255 caracteres
  dela.
- **Fazer logoff** e **Desconectar** agem sobre uma pessoa: botão direito nela em **Logados**, ou
  abra o **Usuários ▾**, que lista cada pessoa conectada com **Fazer logoff…** e **Desconectar…**
  embaixo de cada uma.

Os dois perguntam antes, nomeando a pessoa e onde ela está conectada. O Fazer logoff avisa que "O
que não foi salvo se perde."; o Desconectar mantém os programas dela abertos para a próxima vez.

??? note "Mais sobre mensagens e usuários"

    - Os destinatários da mensagem aparecem como etiquetas ao lado do **Para:**, cuja dica diz onde
      cada um está conectado; sessões desconectadas, e a sua, ficam de fora.
    - O **Usuários ▾** fica esmaecido quando ninguém está conectado, ou quando ninguém foi
      verificado ainda.
    - O **Cancelar** é o botão pronto para apertar nas duas perguntas.

## Reiniciar ou desligar um PC

![A pergunta Reiniciar: quem está conectado, o Quando em Agora e a caixa de mensagem esmaecida](../images/commands-restart-dark-pt-BR.png)

1. **Energia ▾ > Reiniciar…** ou **Desligar…**.
2. Escolha o **Quando**: **Agora**, ou **Em 1 minuto**, **Em 5 minutos** ou **Em 15 minutos**, que
   mandam às pessoas conectadas uma mensagem com contagem regressiva.
3. Clique no botão âmbar: **Reiniciar agora**, ou **Reiniciar** com um tempo de espera.

Uma reinicialização com espera aparece na coluna **Status**, como "Reinicia às 14:37", e como uma
faixa âmbar nos detalhes com **Cancelar reinicialização**. Quando o PC responde de novo, uma
notificação do Windows diz "{host} está online de novo".

![Um host com uma reinicialização aguardando: a coluna Status e a faixa âmbar nos Detalhes, com Cancelar reinicialização](../images/commands-restart-waiting-dark-pt-BR.png)

??? note "Mais sobre reinicializações"

    - A janela nomeia quem está conectado e o que essa pessoa tem a perder. Com **Agora**, a caixa
      de mensagem fica esmaecida ("Sem mensagem: ele reinicia na hora.") e uma linha avisa que o PC
      reinicia na hora, sem aviso na tela.
    - A mensagem com espera já vem preenchida como "Este PC reinicia em 5 minutos. Salve o seu
      trabalho." e é sua para mudar.
    - O teclado começa no **Quando**: as setas escolhem, o **Tab** vai para a mensagem e depois para
      o botão âmbar, onde o **Enter** o executa. O Enter em qualquer outro lugar é o **Cancelar**, o
      botão padrão.
    - A faixa âmbar diz "Reinicia às 14:37" e "Você pediu às 14:32. bruno recebeu a sua mensagem."
      O **Energia > Cancelar a reinicialização pendente** faz o mesmo que o **Cancelar
      reinicialização**.
    - Depois da reinicialização, o CapyPanel procura o PC a cada 15 segundos. A notificação
      acrescenta "Ele reiniciou às 14:37 e respondeu de novo às 14:39. Clique para mostrá-lo."; o
      clique seleciona o host. O CapyPanel para de procurar 20 minutos depois do horário da
      reinicialização.

## Consertar a impressão de um PC

![As impressoras instaladas num host: impressora, driver, porta, status e trabalhos, com Limpar fila e Reiniciar o Spooler de Impressão](../images/commands-printers-dark-pt-BR.png)

1. O **Impressoras deste PC** lista as impressoras do PC: **Impressora**, **Driver**, **Porta**,
   **Status** e **Trabalhos**.
2. Escolha uma impressora travada e clique em **Limpar fila…** para excluir os documentos
   aguardando nela.
3. Ou clique em **Reiniciar o Spooler de Impressão…**, que para todas as impressoras daquele PC por
   alguns segundos; os documentos aguardando ficam, e saem quando ele volta.

Os dois perguntam antes. Estas são as impressoras do próprio PC, não as que um usuário adicionou de
um servidor de impressão, nem as impressoras de rede da
[ferramenta Impressoras](../printers/printers.pt-BR.md).

## Ver o que está instalado e mapeado

- O **Programas instalados** lista os programas instalados para todos os usuários do PC: **Nome**,
  **Fabricante**, **Versão** e **Instalado em**, com **Pesquisar programas**, **Copiar lista**,
  **Exportar CSV…** e **Ler de novo**.
- As **Unidades mapeadas** listam as unidades de rede salvas para cada pessoa conectada:
  **Pessoa**, **Unidade** e **Caminho**. "Estas são as unidades que voltam a cada entrada."

![As unidades mapeadas de um host: cada pessoa conectada, as letras de unidade dela e para onde cada uma aponta](../images/commands-drives-dark-pt-BR.png)

??? note "Mais sobre programas e unidades"

    - As partes do próprio Windows e as atualizações dele ficam fora dos programas, e o CapyPanel
      nunca pergunta ao Windows pelo `Win32_Product`, que repara cada programa que lista enquanto
      passa por eles.
    - O CSV dos programas abre na planilha que o seu PC usa para arquivos CSV, com a mesma proteção
      contra fórmulas que o relatório de hosts tem.
    - As unidades mapeadas são lidas da parte de cada pessoa no registro do PC, pelo WMI; nada é
      executado no PC. Uma pessoa sem nenhuma aparece como "Nenhuma unidade salva". O **Copiar
      lista** põe as linhas na área de transferência.

## A janela Comandos

![A janela Comandos: a caixa Host no topo, os grupos à esquerda, todos os comandos no meio, o que o escolhido encontrou à direita](../images/commands-window-dark-pt-BR.png)

A janela Comandos reúne todos os comandos de um PC, com a resposta ao lado. Abra-a pelo botão
**Comandos**, pelo **Todos os comandos…**, ou pelo **Conectar > Conexão manual…** (Ctrl+M) para um
endereço que não está na sua lista.

1. Escolha ou digite o PC na caixa **Host**, no topo.
2. Escolha um comando no meio (setas, ou digite para pesquisar) e aperte **Enter** ou
   **Executar**.
3. Leia a resposta à direita.

É uma janela própria, ao lado da principal: você pode voltar à lista de hosts e deixá-la aberta. Um
clique duplo só escolhe, para um comando arriscado nunca rodar por acidente.

??? note "Mais sobre a janela Comandos"

    - A caixa **Host** lista os hosts que o painel de hosts mostra, como "DESK-02 · 192.0.2.12", e
      em **Recentes** os endereços que você digitou antes; `host:porta` funciona. Escolher outro
      host muda a janela inteira para ele, inclusive o **Perfil**. O título diz "Comandos ·
      DESK-02", ou "Conexão manual · 198.51.100.40" para um endereço digitado. O **Adicionar à
      lista de hosts…** aparece ao lado da caixa para um endereço digitado que a lista aberta não
      tem.
    - À esquerda, uma caixa **Pesquisa** e os seis grupos. No meio, cada comando com o atalho em
      cinza; o escolhido cresce para mostrar o que faz.
    - À direita, a resposta apresentada como o painel de detalhes a apresenta. Impressoras,
      programas e unidades mapeadas aparecem como tabelas: botão direito numa impressora para
      limpar a fila dela ou copiar a linha, e num programa para copiar ou exportar, ou abrir a lista
      na própria janela com uma pesquisa.
    - Pedir os Comandos de outro host vira a janela para esse host, e as respostas de cada host
      ficam guardadas enquanto a janela continua aberta.
    - Ela abre em 1120 × 620 na primeira vez e pode ser redimensionada: mais larga, os comandos e as
      respostas dividem o espaço a mais; mais estreita, as respostas mantêm a largura e a lista de
      comandos rola para o lado. Ela abre de novo no tamanho em que você a deixou.

## Mensagens que você pode ver

![A faixa acima da tabela de hosts depois de um comando falhar, com Tentar outra conta](../images/commands-strip-failed-dark-pt-BR.png)

Um comando que deu certo diz isso em verde acima da tabela de hosts, como em "Mensagem enviada para
bruno em DESK-02.", e a faixa se fecha sozinha. Um que falhou diz isso em vermelho, com o motivo do
próprio Windows, e fica até você fechá-la.

| Mensagem | O que significa | O que fazer |
|---|---|---|
| "Não foi possível fazer logoff de bruno em DESK-02: acesso negado. É preciso uma conta de administrador naquele PC." | A conta não é administradora lá | O **Tentar outra conta…** pede uma, e para quais PCs, e executa o comando de novo |
| "… (ninguém conectado)" num comando esmaecido | A última atualização, de menos de 10 minutos atrás, não achou ninguém no PC | Atualize o host se alguém entrou desde então |
| "não há uma pasta aí." | O caminho em **Abrir um caminho…** não é uma pasta | Confira o caminho |
