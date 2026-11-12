# Conectando

O CapyPanel abre a tela de um host num visualizador VNC que você mesmo instala (UltraVNC ou
RealVNC), ou no cliente de Área de Trabalho Remota do próprio Windows. Ele nunca os distribui,
empacota ou baixa.

## Conectar a um host

1. Dê um clique duplo no host, aperte **Enter** ou clique em **Conectar** na barra de ferramentas.
2. Na primeira vez, o CapyPanel encontra o visualizador sozinho. Se ele não estiver instalado, o
   CapyPanel pede para instalá-lo ou localizar o `.exe`.
3. Digite a senha quando ela for pedida. Ela fica guardada até o CapyPanel fechar, ou no
   Gerenciador de Credenciais do Windows se você marcar **Lembrar neste computador**.

Selecione vários hosts e aperte **Enter** para abrir cada um na sua própria janela; a senha de cada
perfil é pedida no máximo uma vez, e mais de cinco de uma vez pergunta antes.

??? note "As ferramentas, e como elas recebem a senha"

    | Ferramenta | Como o CapyPanel entrega a senha |
    |---|---|
    | **UltraVNC Viewer** | Na linha de comando (o único jeito que o UltraVNC aceita). Administradores do seu PC podem ver linhas de comando; o log nunca mostra a senha |
    | **RealVNC Viewer** | Por um pipe privado que só a sua conta do Windows pode abrir, lido uma vez. Nada é gravado em disco nem vai para a linha de comando |
    | **Remote Desktop Connection** | Não entrega: o próprio cliente de Área de Trabalho Remota pede a senha |

    O Remote Desktop Connection vem com o Windows, então o CapyPanel o encontra na `System32`. Um
    visualizador VNC é encontrado onde o Windows registrou a instalação, nas pastas de Arquivos de
    Programas de costume e depois no seu PATH; uma cópia portátil descompactada em outro lugar não
    é. O caminho é salvo uma vez para todos no PC, como em **Configurações > Hosts > Conexão >
    Ferramentas remotas**.

??? note "Senhas"

    - No VNC, o CapyPanel pede a senha de um perfil na primeira vez que você conecta com ele e a
      lembra, por perfil, até fechar. Hosts com outro perfil nunca a recebem.
    - Toda janela que pede uma senha tem o **Lembrar neste computador**, desmarcado: "O Windows a
      guarda no Gerenciador de Credenciais para a sua conta do Windows. Senão, o CapyPanel a
      esquece ao fechar e pede uma vez na próxima." Em nenhum dos dois casos o CapyPanel grava uma
      senha num arquivo próprio. Uma janela começa marcada: quando um PC recusa uma conta cuja senha
      você tinha lembrado e o CapyPanel a pede de novo, para que digitá-la de novo a mantenha salva.
    - Senhas VNC clássicas têm no máximo 8 caracteres, então a caixa de senha de um perfil UltraVNC
      "só senha" para em 8.

??? note "A verificação de login, antes de o UltraVNC mandar uma senha"

    O login VNC clássico por senha usa só os 8 primeiros caracteres da senha, e sua troca pode ser
    quebrada offline. Por isso, antes de um perfil UltraVNC de **usuário e senha** conectar, o
    CapyPanel pergunta a cada servidor quais tipos de login ele oferece: ele lê a saudação do
    servidor e desliga sem fazer login. Um servidor que não aceita usuário e senha é pulado, com uma
    mensagem, e nunca recebe sua senha.

    - A verificação leva poucos milissegundos por host numa rede local.
    - Um servidor que não pode ser consultado (inacessível, ou recusando conexões) ainda abre no
      visualizador, que mostra o erro real.
    - Um servidor com o plugin SecureVNC anuncia só o plugin, então a verificação não consegue
      distinguir os dois tipos de login nesse caso.

## Escolher como um host conecta

Um **perfil de conexão** diz como um host conecta: a **ferramenta**, o **login** (usuário e senha,
ou só senha) e as **opções** da ferramenta, como o **plugin SecureVNC** do UltraVNC.

- **Para um grupo:** botão direito nele > **Perfil de conexão**. Todos os hosts dentro dele o
  seguem, a menos que definam o próprio.
- **Para um host:** escolha-o em **Conectar com** no painel de detalhes, ou no **Editar
  selecionado…** (F2), que pode cobrir vários hosts de uma vez.
- **Só uma vez:** o menu **Conectar** da barra de ferramentas lista um item por perfil, como
  **Conectar com Remote Desktop**; os hosts selecionados abrem com ele desta vez, sem serem
  alterados.

"Do grupo" significa que o host segue o grupo mais próximo que define um perfil. Hosts sem perfil
em lugar nenhum usam o padrão.

![A seção Conexão do painel de detalhes: endereço, grupo, Conectar com e Comandos como](../images/commands-details-dark-pt-BR.png)

??? note "Mais sobre o Conectar com e o Comandos como"

    - O **Conectar com** abre a mesma lista do menu **Perfil de conexão** de um grupo: a escolha do
      grupo, como "Do grupo “Front desk”: UltraVNC", ou um perfil pelo nome. Uma chavinha ao lado do
      nome quer dizer que há um login guardado para aquele perfil; a dica dela diz o usuário.
    - O **Comandos como** é a conta que lê quem está logado e executa os comandos do host. Ele
      oferece **Seguir as Contas** (o que a tabela Contas dá a este PC), **Sua conta do Windows**,
      cada conta da tabela e **Outra conta…**. Escolher uma a define só para este PC, com um
      alfinete ao lado do nome; o **Seguir as Contas** tira o alfinete. Ele também está no menu do
      botão direito de vários hosts selecionados e no de um grupo.
    - Uma lista guarda só o ID de um perfil. Um host ou grupo que cita um perfil que o seu PC não
      tem segue o perfil do grupo, ou o padrão, e o que falta aparece como "não disponível neste
      PC".

## Configurar os perfis de conexão

Abra **Configurações > Hosts > Conexão > Perfis de conexão** (ou **Conectar > Perfis de
conexão…**) para adicionar, editar, duplicar, excluir ou restaurar os que vêm com o CapyPanel. Cada
perfil tem um nome, uma ferramenta, um login, as opções da ferramenta e uma porta (em branco para a
da própria ferramenta).

O CapyPanel começa com **UltraVNC** e **RealVNC**, ambos com "usuário e senha", e **Remote
Desktop**. **Hosts sem perfil usam**, a última linha, é o perfil dos hosts que não têm um próprio.

??? note "Onde os perfis ficam, e quem pode alterá-los"

    - Todos os perfis ficam em `C:\ProgramData\CapyPanel\profiles\`, então todos no PC veem os
      mesmos. **As permissões do Windows decidem quem pode alterá-los**: o CapyPanel cria a pasta
      somente leitura para os outros usuários, e um arquivo de perfil criado por outro usuário (que
      não seja administrador) é ignorado. O **Hosts sem perfil usam** também é salvo ali.
    - Um perfil inicial é adicionado uma vez, também num PC que já tinha perfis; um que você exclui
      continua excluído.
    - Excluir um perfil pergunta antes, com quantos hosts e grupos da lista aberta o usam. Eles
      passam a seguir o perfil do grupo, ou o padrão.
    - Um perfil pode indicar um visualizador que não está instalado neste PC (ele aparece marcado).
      O CapyPanel pede o visualizador só na hora de conectar.

??? note "UltraVNC: um arquivo de configurações do visualizador"

    Para todo o resto que o UltraVNC oferece (qualidade, escala, só visualização, tela cheia e
    assim por diante), um perfil do UltraVNC pode levar um arquivo de configurações:

    1. No UltraVNC Viewer, ajuste as opções e salve a conexão como um arquivo `.vnc`.
    2. No editor de perfil, **Configurações do visualizador > Escolher arquivo…** e selecione-o.
       **Usar padrões** volta às configurações do próprio visualizador.

    No **Adicionar** ou no **Salvar**, o CapyPanel copia o arquivo para junto do perfil
    (`profiles\<id>.vnc`). Ele é usado **exatamente como foi salvo**, inclusive o plugin de
    criptografia; só o `host` é esvaziado. Enquanto um perfil tem arquivo, as opções dele ficam
    desligadas: quem decide é o arquivo. Ao conectar, o visualizador recebe uma cópia temporária,
    apagada um minuto depois.

??? note "Perfis de Área de Trabalho Remota"

    Um perfil de Área de Trabalho Remota abre o host no `mstsc`, na porta 3389, a menos que o host
    ou o perfil defina outra. As opções dele são **Sessão administrativa (só servidores)**, **Tela
    cheia** e **Usar todos os meus monitores**; não há arquivo de configurações. O CapyPanel nunca
    lida com a senha da Área de Trabalho Remota: o cliente a pede. Se você marcar **Lembrar de mim**
    lá, o Windows guarda esse login por conta própria, como `TERMSRV/<endereço>`; remova-o no
    **Painel de Controle > Gerenciador de Credenciais**.

## Usar outra conta em alguns PCs

Ler quem está logado e executar [comandos](commands.pt-BR.md) precisam de uma conta que seja
administradora naquele PC. Por padrão, é a sua própria conta do Windows. Para usar outra:

1. Abra **Configurações > Hosts > Credenciais > Contas** e clique em **Adicionar…**.
2. Digite o **Usuário** (vazio para a sua conta do Windows) e, se quiser, a **Senha**; senão, ela é
   pedida na primeira vez que precisar.
3. Em **Usar para**, escolha **Todos os PCs**, **Um PC**, **Um grupo** ou **Uma tag**, e depois
   **Adicionar**.

Quando várias linhas servem para um PC, a mais específica vale: "A conta do próprio PC vale mais
que a do grupo, a do grupo mais que a da tag, e essas mais que Todos os PCs." A tabela é só sua,
"guardadas nas suas próprias configurações, nunca nas listas de hosts compartilhadas".

??? note "Mais sobre as contas"

    | Coluna | O que ela mostra |
    |---|---|
    | **Conta** | O usuário, como `DOMÍNIO\usuário` |
    | **Usada para** | **Todos os PCs**, um grupo, como "Grupo Clinic › Front desk", uma tag, ou um PC, como "DESK-02 (198.51.100.20)" |
    | **Guardada em** | Onde a senha está: **Gerenciador de Credenciais**, **Temporária**, ou **Pedida quando precisar** |

    - O **Remover** tira a linha, e a senha salva dela junto. Os grupos e as tags são os da lista
      aberta.
    - Quando PCs respondem **Sem direitos de administrador** ou **Conta recusada**, o CapyPanel
      pede outra conta (depois de um Atualizar, ou com o **Tentar outra conta…** depois de um
      comando que falhou) na **Conta para outros PCs**, com o **Usar para** oferecendo este PC,
      cada grupo e tag que eles têm em comum, ou todos os PCs, do mais específico para o mais
      geral. O **Usar conta** a transforma numa linha da tabela. "Se um computador recusar a conta,
      o CapyPanel para e pergunta de novo em vez de tentá-la nos outros, para a conta não ser
      bloqueada."
    - Em PCs que não estão num domínio, o Administrador interno é a única conta local que o
      Windows aceita remotamente.

## Esquecer uma senha salva

1. **Conectar ▾ > Credenciais salvas…** (ou **Gerenciar…** em **Configurações > Hosts >
   Credenciais**).
2. Escolha o login e clique em **Esquecer**, ou em **Esquecer todas**.

O CapyPanel não consegue saber quando um visualizador recusa uma senha, então é assim que se corrige
um erro de digitação. Um login esquecido aqui também é apagado do Gerenciador de Credenciais.

??? note "Mais sobre as credenciais salvas"

    "Todos os logins que o CapyPanel guarda para você. As senhas nunca aparecem aqui." A janela
    lista **Usada para** (o perfil, ou os PCs para que uma conta é usada), **Ferramenta**,
    **Usuário** ("(só senha)" num perfil que só recebe senha) e **Guardada** (**Gerenciador de
    Credenciais**, ou **Temporária** até o CapyPanel fechar). O Windows os criptografa para a sua
    conta, "então quem usar a sua sessão do Windows pode se conectar com eles."

    O **Esquecer todas** pergunta antes, listando cada login; o Cancelar é o botão padrão. As contas
    SNMP e do Doc360 das impressoras não aparecem: elas são gerenciadas em **Configurações >
    Impressoras > Conexão** (veja
    [Definir a conta SNMP](../printers/checking.pt-BR.md#definir-a-conta-snmp)). Os logins da Área
    de Trabalho Remota também não.

## Conectar a um endereço que não está na lista

**Conectar > Conexão manual…** (Ctrl+M) abre a janela Comandos com a caixa **Host** vazia: digite o
endereço, escolha um **Perfil** e clique em **Conectar**. Um endereço com porta, como
`192.0.2.77:5901`, usa aquela porta. O **Adicionar à lista de hosts…** põe o PC na lista aberta
(veja [A janela Comandos](commands.pt-BR.md#a-janela-comandos)).

## Mensagens que você pode ver

| Mensagem | O que significa | O que fazer |
|---|---|---|
| O nome de um host não pode ser usado como endereço | Ele não tem endereço, e um nome como "Ala 2A - Posto" não é um nome de computador | Edite o host e acrescente o endereço; o CapyPanel oferece isso |
| Um servidor pulado pela verificação de login | Ele não aceita usuário e senha, então nunca recebeu a sua | Use um perfil "só senha" para ele |
| "não disponível neste PC" | Um host ou grupo cita um perfil que este PC não tem | Escolha outro perfil, ou adicione esse |
| O visualizador pede para ser instalado ou localizado | O visualizador VNC não foi encontrado | Instale-o, ou mostre ao CapyPanel onde está o `.exe` |
