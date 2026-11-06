# Comandos em um host

Os comandos de um host são as tarefas de todo dia que você faria por um console ou por uma linha
de comando: abrir o disco C: de um PC, ver o que está instalado nele, mandar uma mensagem para
quem o está usando ou fazer logoff dessa pessoa, reiniciá-lo ou destravar a impressão dele. Eles
funcionam em um host por vez: o que você selecionou ou um endereço que você digita.

Nada é instalado no outro PC e nada seu é executado lá. Todo comando usa as próprias funções
remotas do Windows: o compartilhamento de arquivos, o serviço de sessões, o desligamento remoto,
o spooler de impressão, o gerenciador de serviços e o WMI para os dados do PC e os programas
instalados. A conta é o seu próprio login do Windows, ou a que você digitou para ler os usuários
logados (veja [Qual conta é usada](checking.pt-BR.md#qual-conta-e-usada)).

## Onde eles estão

![A janela Hosts: o botão Comandos na barra de ferramentas e os botões de comando abaixo do nome do host nos Detalhes](../images/commands-details-dark-pt-BR.png)

- **Clique com o botão direito num host:** depois de **Atualizar status** e **Atualizar usuários
  logados**, um submenu por grupo: **Verificar**, **Abrir**, **Usuários**, **Energia** e
  **Impressoras**. Eles funcionam em um host com endereço, então ficam esmaecidos quando você
  selecionou vários ou nenhum.
- **A barra de ferramentas:** **Comandos**, ao lado do Atualizar, abre a
  [janela Comandos](#a-janela-comandos) para o host selecionado. A seta dele lista os mesmos
  grupos e termina com **Todos os comandos…**, que também abre essa janela.
- **O painel de detalhes:** uma fileira de botões abaixo do nome do host. **C$**, a pasta do
  usuário conectado, o Gerenciamento do Computador e Enviar uma mensagem executam um comando
  cada; os dois âmbar abrem **Fazer logoff ou desconectar alguém** e **Reiniciar ou desligar**; e
  **…** guarda todos os comandos. Uma dica nomeia cada um deles. Num painel estreito a fileira
  quebra numa segunda linha.
- **Uma pessoa em Logados:** clique nela com o botão direito nos Detalhes para **Enviar uma
  mensagem para {user}…**, **Desconectar {user}…** e **Fazer logoff de {user}…**, e depois
  **Copiar ▸**.

Os botões e itens de menu em âmbar são os comandos que atrapalham quem está usando o PC. Eles
sempre perguntam antes.

## O que cada comando faz

O **Verificar** lê algo e mostra onde aquela verificação normalmente aparece:

| Comando | O que faz |
|---|---|
| **Executar todas as verificações** | Status, usuários logados e dados do PC, um depois do outro |
| **Status** | Se o PC responde na rede (veja [Verificando hosts](checking.pt-BR.md#status)) |
| **Usuários logados** | Quem está conectado, e desde quando |
| **Dados do PC** | Versão do Windows, modelo, número de série, memória, espaço livre e última reinicialização (veja [Dados do PC](checking.pt-BR.md#dados-do-pc)) |
| **Programas instalados** | Os programas instalados para todos os usuários do PC |

O **Abrir** abre algo no *seu* PC apontado para o outro:

| Comando | O que abre |
|---|---|
| **Compartilhamento C$** (Ctrl+E) | O disco C: do PC no Explorador de Arquivos |
| **Pasta Inicializar** | Os programas que iniciam para todo usuário que entra |
| **Abrir um caminho…** (Ctrl+Shift+O) | Qualquer pasta do PC, como `D:\Logs` |
| **Pasta de {usuário}** (Ctrl+Shift+U) | A pasta de perfil do usuário conectado |
| **Gerenciamento do Computador** (Ctrl+Shift+M) | O Gerenciamento do Computador do Windows, apontado para o PC |
| **Visualizador de Eventos** | Os logs de eventos do PC |
| **Serviços** | Os serviços do Windows no PC |

Uma pasta espera o PC responder antes de o Explorador de Arquivos abrir, porque o próprio
Explorador pode travar por meio minuto num PC desligado. Um caminho que não é uma pasta é
recusado com "não há uma pasta aí.", para que um arquivo nunca seja aberto, e assim executado,
no seu próprio PC. Os três consoles do Windows abrem na hora e mostram o erro deles quando o PC
não pode ser alcançado.

O **Usuários** tem o **Enviar uma mensagem…**. Fazer logoff e Desconectar agem sobre uma pessoa,
então são oferecidos nela: nos Detalhes, ou no botão âmbar de usuários, que lista cada pessoa
conectada como um título, como em "ana.admin  (no PC, ativa, desde 08:05)", com **Fazer
logoff…** e **Desconectar…** embaixo de cada uma. Ele fica esmaecido quando ninguém está
conectado, ou quando ninguém foi verificado ainda.

O **Energia** tem o **Reiniciar…**, o **Desligar…** e o **Cancelar a reinicialização pendente**,
este esmaecido a menos que uma reinicialização pedida pelo CapyPanel ainda esteja aguardando.

O **Impressoras** tem o **Impressoras deste PC** e o **Reiniciar o Spooler de Impressão…**.

## As perguntas e as janelas pequenas

### Abrir um caminho…

A "Abrir uma pasta em {host}" aceita o caminho do jeito que você já o tem: como o Explorador de
Arquivos copia, com aspas e tudo (`"D:\Logs\App"`), em outro disco (`D:\Logs` ou `D$\Logs`), só
no C: (`Users\Public`), ou um caminho `\\PC\compartilhamento\…` inteiro. Uma linha embaixo da
caixa mostra o que vai abrir, como em "Abre \\DESK-02\D$\Logs\App". A caixa guarda as últimas 10
pastas que você abriu.

### Enviar uma mensagem…

A mensagem vai para todos que estão na frente da tela do PC, mostrados como etiquetas ao lado do
**Para:**, cuja dica diz onde cada um está conectado; sessões desconectadas, e a sua, ficam de
fora. Ela aparece na tela deles até clicarem em OK, com o título "Mensagem de {seu usuário do
Windows}", e o Windows mostra cerca de 255 caracteres dela.

### Fazer logoff… e Desconectar…

Os dois perguntam antes, nomeando a pessoa e onde ela está conectada. O Fazer logoff avisa que "O
que não foi salvo se perde."; o Desconectar diz que os programas dela continuam abertos e que ela
volta a eles quando entrar de novo. O Cancelar é o botão pronto para apertar.

### Reiniciar… e Desligar…

![A pergunta Reiniciar: quem está conectado, quando ele reinicia e a mensagem que eles recebem](../images/commands-restart-dark-pt-BR.png)

Esta janela é a pergunta. Ela nomeia quem está conectado e o que essa pessoa tem a perder. O
**Quando** é **Agora**, ou **Em 1 minuto**, **Em 5 minutos** (a escolha de sempre) ou **Em 15
minutos**, cada um com uma mensagem que o Windows mostra a eles com uma contagem regressiva, já
preenchida como "Este PC reinicia em 5 minutos. Salve o seu trabalho." e sua para mudar. Escolha
**Agora** e a caixa de mensagem fica esmaecida, dizendo "Sem mensagem: ele reinicia na hora.", e
o botão vira **Reiniciar agora**.

### Impressoras deste PC

![As impressoras instaladas num host: impressora, driver, porta, status e trabalhos, com Limpar fila e Reiniciar o Spooler de Impressão](../images/commands-printers-dark-pt-BR.png)

Uma janela com **Impressora**, **Driver**, **Porta**, **Status** e **Trabalhos**, e três botões:
o **Limpar fila…** exclui os documentos aguardando na impressora que você escolheu, o **Reiniciar
o Spooler de Impressão…** para todas as impressoras daquele PC por alguns segundos (os documentos
aguardando ficam, e saem quando ele volta), e o **Ler de novo** lê a lista de novo. Os dois
primeiros perguntam antes.

Estas são as impressoras do próprio PC, não as que um usuário adicionou para si de um servidor de
impressão. As impressoras da [ferramenta Impressoras](../printers/printers.pt-BR.md) são outra
coisa: aquelas são as impressoras em si, na rede.

### Programas instalados

**Nome**, **Fabricante**, **Versão** e **Instalado em**, com uma caixa **Pesquisar programas**,
quantos são e quando foram lidos, e depois **Copiar lista**, **Exportar CSV…** e **Ler de novo**.
O CSV abre na planilha que o seu PC usa para arquivos CSV, com a mesma proteção contra uma célula
que uma planilha executaria como fórmula que o relatório de hosts tem.

A lista traz os programas instalados para todos os usuários do PC. As partes do próprio Windows e
as atualizações dele ficam de fora, e o CapyPanel nunca pergunta ao Windows pelo `Win32_Product`,
que repara cada programa que lista enquanto passa por eles.

## O que aconteceu: a faixa acima da tabela

![A faixa acima da tabela de hosts depois de um comando falhar, com Tentar outra conta](../images/commands-strip-failed-dark-pt-BR.png)

Um comando que deu certo diz isso em verde acima da tabela de hosts, como em "Mensagem enviada
para ana.admin em DESK-02.", e a faixa se fecha sozinha depois de alguns segundos.

Um comando que falhou diz isso em vermelho, com o motivo do próprio Windows: "Não foi possível
fazer logoff de bruno.costa em DESK-02: acesso negado. É preciso uma conta de administrador
naquele PC." Essa faixa fica até você fechá-la. Quando o problema foi a conta, o **Tentar outra
conta…** pede outra, a mesma conta que a verificação de usuários logados usa, e executa o
comando de novo.

Abrir uma pasta é a exceção: ela diz "Aberto: \\DESK-02\C$" na barra de status, onde o resto do
que você abre também aparece.

## Uma reinicialização que aguarda

![Um host com uma reinicialização aguardando: a coluna Status e a faixa âmbar nos Detalhes, com Cancelar reinicialização](../images/commands-restart-waiting-dark-pt-BR.png)

Uma reinicialização ou um desligamento com atraso aparece na coluna **Status**, como "Reinicia às
14:37" com um relógio, e nos Detalhes como uma faixa âmbar: "Reinicia às 14:37", "Você pediu às
14:32. ana.admin recebeu a sua mensagem." e **Cancelar reinicialização**. O **Energia > Cancelar
a reinicialização pendente** faz o mesmo pelos menus.

Depois que o PC reinicia, o CapyPanel procura por ele a cada 15 segundos. Assim que ele sumiu e
responde de novo, uma notificação do Windows diz "{host} está online de novo", com "Ele reiniciou
às 14:37 e respondeu de novo às 14:39. Clique para mostrá-lo."; o clique seleciona aquele host. O
CapyPanel para de procurar 20 minutos depois do horário da reinicialização.

## A janela Comandos

![A janela Comandos: os grupos à esquerda, todos os comandos no meio, o que o escolhido encontrou à direita](../images/commands-window-dark-pt-BR.png)

A janela Comandos reúne todos os comandos de um PC num lugar só, com a resposta ao lado. Ela abre
pelo botão **Comandos**, pelo **Todos os comandos…** e pelo **Conectar > Conexão manual…**
(Ctrl+M), que é a mesma janela para um endereço que não está na sua lista.

- **No topo:** o nome e o endereço do host, ou uma caixa **Endereço** quando você digitou um
  (`host:porta` funciona), e depois **Perfil** e **Conectar**. A janela se chama "Comandos" para
  um host seu e "Conexão manual" para um endereço digitado.
- **À esquerda:** uma caixa **Pesquisa** e os cinco grupos; um clique pula para um grupo.
- **No meio:** todos os comandos, um por linha. O que você escolhe cresce para mostrar o que ele
  faz e um botão **Executar**. As setas movem, o Enter executa, e digitar em qualquer lugar
  pesquisa.
- **À direita:** o que o comando encontrou, apresentado como o painel de detalhes apresenta: o
  status, quem está logado, os dados do PC, ou a última resposta com **Tentar outra conta…**. As
  Impressoras deste PC e os Programas instalados aparecem ali como tabelas: clique numa
  impressora com o botão direito para limpar a fila dela ou copiar a linha, e num programa para
  copiar a linha, copiar ou exportar a lista inteira, ou abrir a lista na própria janela com uma
  pesquisa. Os comandos que precisam que você digite algo abrem a janela pequena deles por cima
  desta.
- **Embaixo:** o **Adicionar à lista…** põe um endereço digitado na lista de hosts aberta, com o
  endereço já preenchido. Para um PC que já está na lista ele fica esmaecido, e a dica dele diz
  onde: "Já está nesta lista: em Front desks, como DESK-02".

## Qual conta é usada

O seu próprio login do Windows e, fora isso, a conta que você digitou quando um host respondeu
**Sem direitos de administrador** ou **Conta recusada** ao ler os usuários logados. Aquela
janela, a **Conta para outros PCs**, cobre as duas coisas: como ela diz, a conta é "usada
só para ver quem está conectado e nos comandos que você executa em um host". Onde ela fica
guardada, e como esquecê-la, está em
[Verificando hosts](checking.pt-BR.md#qual-conta-e-usada) e
[Conectando](connecting.pt-BR.md#credenciais-salvas).
