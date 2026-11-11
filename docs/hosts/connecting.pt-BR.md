# Conectando

O CapyPanel abre telas remotas por visualizadores VNC que você mesmo instala, e pelo cliente de
Área de Trabalho Remota do próprio Windows. Ele nunca os distribui, empacota ou baixa.

## Ferramentas suportadas

| Ferramenta | Como o CapyPanel entrega a senha |
|---|---|
| **UltraVNC Viewer** | Na linha de comando (o único jeito que o UltraVNC aceita). Administradores do seu PC podem ver linhas de comando; o log nunca mostra a senha |
| **RealVNC Viewer** | Por um pipe privado que só a sua conta do Windows pode abrir, lido uma vez. Nada é gravado em disco nem vai para a linha de comando |
| **Remote Desktop Connection** | Não entrega: o próprio cliente de Área de Trabalho Remota pede a senha |

O Remote Desktop Connection vem com o Windows, então o CapyPanel o encontra na `System32`. Um
visualizador VNC instalado ele também encontra sozinho: onde o Windows registrou a instalação
(qualquer pasta), as pastas de Arquivos de Programas de costume, depois o seu PATH. Uma cópia
portátil descompactada em outro lugar não é encontrada automaticamente; quando falta um
visualizador, o CapyPanel pede para instalá-lo ou localizar o `.exe`. O caminho é salvo uma vez
para todos no PC, como em **Configurações > Hosts > Conexão > Ferramentas remotas** (veja
[Configurações e arquivos](../settings-and-files.pt-BR.md#ferramentas-remotas)).

## Perfis de conexão

Uma rede costuma misturar várias configurações: servidores VNC que pedem uma conta do Windows (o
MS-Logon do UltraVNC), servidores que pedem só uma senha VNC, plugins de criptografia, RealVNC em
Raspberry Pis, Área de Trabalho Remota. Um **perfil de conexão** diz qual delas um host usa:

- a **ferramenta**: um visualizador VNC ou o Remote Desktop Connection;
- o **login**: usuário e senha, ou só senha. Na Área de Trabalho Remota a tabela lê "o próprio
  Remote Desktop Connection pede";
- **opções** que a ferramenta oferece, como o **plugin SecureVNC** do UltraVNC.

### Gerenciar perfis

- Os perfis são gerenciados em **Configurações > Hosts > Conexão > Perfis de conexão** (também
  em **Conectar > Perfis de conexão…**): adicionar, editar, duplicar, excluir e restaurar os que vêm
  com o CapyPanel. Cada um tem um nome, uma
  ferramenta, um login (só os que essa ferramenta suporta), as opções da ferramenta (como o
  SecureVNC) e uma porta, em branco para a da própria ferramenta.
- Cada ferramenta vem com um perfil inicial: **UltraVNC** e **RealVNC**, ambos com "usuário e
  senha", e **Remote Desktop**. Um perfil inicial é adicionado uma vez, também num PC que já tinha
  perfis; são perfis comuns, e um que você exclui continua excluído.
- Todos os perfis ficam juntos em `C:\ProgramData\CapyPanel\profiles\`, junto da lista padrão,
  para que todos no PC vejam os mesmos e seja fácil conferi-los. **As permissões do Windows
  decidem quem pode alterá-los**: o CapyPanel cria a pasta no primeiro início, somente leitura
  para os outros usuários. Um arquivo de perfil criado por outro usuário (que não seja
  administrador) é ignorado.
- **Hosts sem perfil usam**, a última linha dessa seção, é o perfil com que um host conecta
  quando não tem um próprio. Ele é salvo na mesma pasta, então é o mesmo para todos.
- Excluir um perfil pergunta antes e diz quantos hosts e grupos da lista aberta o usam. Eles
  passam a seguir o perfil do grupo, ou o padrão.
- Um perfil pode indicar um visualizador que não está instalado neste PC (ele aparece marcado),
  por exemplo para preparar os perfis antes de instalar os visualizadores. O CapyPanel pede o
  visualizador só na hora de conectar.

### Arquivos de configurações do visualizador

Por padrão, um perfil usa as configurações do próprio visualizador, mais as opções do perfil.
Para todo o resto que o visualizador oferece (qualidade, escala, só visualização, tela cheia e
assim por diante), um perfil do **UltraVNC** pode levar um arquivo de configurações:

1. No UltraVNC Viewer, ajuste as opções que quiser e salve a conexão como um arquivo `.vnc`.
2. No editor de perfil, **Configurações do visualizador > Escolher arquivo…** e selecione-o.
   **Usar padrões** volta às configurações do próprio visualizador.

Quando você clica em OK, o CapyPanel copia o arquivo para junto do perfil
(`profiles\<id>.vnc`). Ele é usado **exatamente como foi salvo**, inclusive o plugin de
criptografia; só o `host` é esvaziado, já que o endereço vem do host que você abre. Enquanto um
perfil tem arquivo, as opções dele (como o SecureVNC) ficam desligadas: quem decide é o arquivo.
Ao conectar, o visualizador recebe uma cópia temporária, apagada um minuto depois, e o arquivo
compartilhado nunca é alterado.

### Escolher um perfil

- **Num grupo:** clique com o botão direito no grupo > **Perfil de conexão**. Todos os hosts
  dentro dele o seguem, inclusive os de grupos aninhados, a menos que definam o próprio.
- **Em hosts:** no campo **Perfil de conexão** do próprio host, em **Editar selecionado…** (F2).
  Uma edição pode cobrir vários hosts de uma vez.
- **"Do grupo"** significa que o host segue o grupo mais próximo que define um perfil. Hosts sem
  perfil em lugar nenhum usam o padrão.
- **Só uma vez:** o menu **Conectar** da barra de ferramentas lista **Conectar com RealVNC**,
  **Conectar com Remote Desktop** e assim por diante, um por perfil: os hosts selecionados abrem
  com aquele perfil desta vez, sem serem alterados.

Uma lista guarda só o ID do perfil. Quando um host ou grupo cita um perfil que o seu PC não tem,
ele segue o perfil do grupo (ou o padrão), e o que falta é marcado como "não disponível neste PC"
onde quer que apareça: no campo **Perfil de conexão** do host e no menu **Perfil de conexão** de
um grupo.

### No painel de detalhes

![A seção Conexão do painel de detalhes: endereço, grupo, Conectar com e Comandos como](../images/commands-details-dark-pt-BR.png)

A **Conexão**, no painel de detalhes, mostra o **Endereço** e o **Grupo** do host, e depois dois
menus:

- **Conectar com** é o perfil com que o Conectar o abre. Um clique abre a mesma lista do submenu
  **Perfil de conexão** do botão direito: a escolha do grupo, como "Do grupo “Front desk”:
  UltraVNC", ou um perfil pelo nome, então o perfil de um host pode ser trocado sem abrir o
  **Editar selecionado…**. Uma chavinha ao lado do nome quer dizer que há um login guardado para
  aquele perfil; a dica dela diz o usuário.
- **Comandos como** é a conta que lê quem está logado e executa os comandos do host. Um clique
  oferece **Seguir as Contas**, que diz o que a tabela [Contas](#contas-para-outros-pcs) dá a
  este PC, como "Seguir as Contas: EXAMPLE\admin", depois **Sua conta do Windows**, cada conta da
  tabela e **Outra conta…**. Escolher uma a define só para este PC, e um alfinete ao lado do nome
  diz isso ("Só este PC" na dica). O **Seguir as Contas** tira o alfinete.

O **Comandos como** também está no botão direito de um host, para todos os hosts selecionados, e
no de um grupo, onde define a conta de todos os PCs do grupo.

## Contas para outros PCs

Ler quem está logado num PC e executar os [comandos](commands.pt-BR.md) dele precisam de uma conta
que seja administradora lá. Por padrão, é a sua própria conta do Windows. As **Configurações >
Hosts > Credenciais > Contas** dizem qual outra conta entra em quais PCs:

| Coluna | O que ela mostra |
|---|---|
| **Conta** | O usuário, como `DOMÍNIO\usuário` |
| **Usada para** | **Todos os PCs**, um grupo, como "Grupo Clinic › Front desk", uma tag, ou um PC, como "DESK-02 (198.51.100.20)" |
| **Guardada em** | Onde a senha está: **Gerenciador de Credenciais**, **Temporária**, ou **Pedida quando precisar** quando ainda não foi digitada |

O **Adicionar…** e o **Editar…** abrem uma janela só: **Usuário** ("DOMÍNIO\usuário, ou vazio
para a sua conta do Windows"), **Senha** ("Opcional: pedida na primeira vez que precisar"),
**Usar para**: **Todos os PCs**, **Um PC** (o endereço ou nome, como na lista de hosts), **Um
grupo** ou **Uma tag**, e **Lembrar neste computador**. O **Remover** tira a linha, e a senha
salva dela junto.

Quando várias linhas servem para um PC, a mais específica vale: "A conta do próprio PC vale mais
que a do grupo, a do grupo mais que a da tag, e essas mais que Todos os PCs. PCs que nenhuma delas
nomeia usam a sua conta do Windows." Os grupos e as tags são os da lista aberta. A tabela é só
sua, "guardadas nas suas próprias configurações, nunca nas listas de hosts compartilhadas", então
quem usa a mesma lista mantém as contas próprias.

Quando PCs respondem **Sem direitos de administrador** ou **Conta recusada** enquanto o Atualizar
lê quem está logado, o CapyPanel pede outra conta quando o Atualizar termina, e verifica esses PCs
de novo com ela. Um comando que falhou do mesmo jeito oferece o **Tentar outra conta…**. Os dois
abrem a **Conta para outros PCs**: o usuário, a senha e o **Usar para**: este PC, cada grupo e
tag que eles têm em comum, ou todos os PCs, do mais específico para o mais geral. O que você
escolher vira uma linha da tabela. Uma conta é tentada num PC de cada vez: "Se um computador
recusar a conta, o CapyPanel para e pergunta de novo em vez de tentá-la nos outros, para a conta
não ser bloqueada."

Em PCs que não estão num domínio, o Administrador interno é a única conta local que o Windows
aceita remotamente.

## Área de Trabalho Remota

Um perfil de Área de Trabalho Remota abre o host no cliente de Área de Trabalho Remota do Windows
(`mstsc`), na porta 3389, a menos que o host ou o perfil defina outra. As opções dele são caixas
de seleção no perfil: **Sessão administrativa (só servidores)**, que só faz diferença em
servidores de Serviços de Área de Trabalho Remota, **Tela cheia** e **Usar todos os meus
monitores**. Não há arquivo de configurações para a Área de Trabalho Remota.

O CapyPanel nunca lida com a senha da Área de Trabalho Remota: o cliente a pede, e a verificação
de login abaixo não se aplica. Um login da Área de Trabalho Remota também nunca está nas
**Credenciais salvas**. Se você marcar **Lembrar de mim** no cliente de Área de Trabalho Remota, o
Windows guarda esse login por conta própria, como `TERMSRV/<endereço>`; remova-o por lá, ou no
**Painel de Controle > Gerenciador de Credenciais**.

## Senhas

- No VNC, o CapyPanel pede a senha de um perfil na primeira vez que você conecta com ele e **a
  lembra, por perfil**, até fechar. Hosts com outro perfil nunca a recebem.
- Toda janela que pede uma senha, de um perfil ou de uma conta, tem o **Lembrar neste
  computador**, desmarcado: "O Windows a guarda no Gerenciador de Credenciais para a sua conta do
  Windows. Senão, o CapyPanel a esquece ao fechar e pede uma vez na próxima." Em nenhum dos dois
  casos o CapyPanel grava uma senha num arquivo próprio.
- Senhas VNC clássicas têm no máximo 8 caracteres, então a caixa de senha de um perfil UltraVNC
  "só senha" para em 8.

### Credenciais salvas

Um login em que você marcou o **Lembrar neste computador** fica guardado no **Gerenciador de
Credenciais do Windows**, na sua própria conta do Windows, para o CapyPanel não pedi-lo de novo na
próxima vez que abrir. Isso quer dizer que "o Windows os criptografa para a sua conta, então quem
usar a sua sessão do Windows pode se conectar com eles."

O **Conectar ▾ > Credenciais salvas…**, e o **Gerenciar…** em **Configurações > Hosts >
Credenciais > Senhas > Credenciais salvas**, abrem uma janela com todos os logins que o CapyPanel
guarda: "Todos os logins que o CapyPanel guarda para você. As senhas nunca aparecem aqui." A linha
das configurações diz quantos são e onde estão, como "2 guardados: 1 no Gerenciador de
Credenciais, 1 temporário.", ou "Nenhum guardado."

| Coluna | O que ela mostra |
|---|---|
| **Usada para** | O perfil de conexão, ou os PCs para que uma conta é usada, como "Todos os PCs" |
| **Ferramenta** | O que entra com ela, como "RealVNC Viewer", ou "Hosts › Contas" para uma conta |
| **Usuário** | O nome de usuário, ou "(só senha)" num perfil que só recebe senha |
| **Guardada** | **Gerenciador de Credenciais**, ou **Temporária** até o CapyPanel fechar |

O **Esquecer** descarta o login escolhido, por exemplo depois de um erro de digitação: o CapyPanel
não consegue saber quando um visualizador recusa uma senha. O **Esquecer todas** pergunta antes,
listando cada login em "Salvos no Gerenciador de Credenciais:" e "Temporários:", e então "O
CapyPanel pede de novo quando precisar deles."; o Cancelar é o botão padrão. Um login esquecido
aqui também é apagado do Gerenciador de Credenciais.

Só esses logins são listados. A comunidade SNMP e a conta v3 das impressoras não: elas são
gerenciadas em **Configurações > Impressoras > Conexão**, onde esvaziar o campo as esquece (veja
[Verificando impressoras](../printers/checking.pt-BR.md#a-conta-snmp)).

## A verificação de login

O login VNC clássico por senha usa só os 8 primeiros caracteres da senha, e sua troca pode ser
quebrada offline. Por isso, antes de um perfil UltraVNC de **usuário e senha** conectar, o
CapyPanel pergunta a cada servidor quais tipos de login ele oferece. Ele lê a saudação do servidor
e desliga sem fazer login. Um servidor que não aceita usuário e senha é pulado, com uma mensagem,
e nunca recebe sua senha.

- A verificação leva poucos milissegundos por host numa rede local.
- Um servidor que não pode ser consultado (inacessível, ou recusando conexões) ainda abre no
  visualizador, que mostra o erro real.
- Um servidor com o plugin SecureVNC anuncia só o plugin, não o login por trás dele, então a
  verificação não consegue distinguir os dois tipos nesse caso.

## Abrir vários hosts

Selecione vários hosts e pressione Enter: cada um abre na sua própria janela do visualizador,
agrupados por perfil, então a senha de cada perfil é pedida no máximo uma vez. Abrir mais de cinco
de uma vez pergunta antes.

Um host sem endereço conecta pelo nome só quando o nome é um nome de computador válido. Um nome
como "Ala 2A - Posto" não pode ser usado como endereço, então o CapyPanel avisa e oferece editar o
host.

## Conexão manual

**Conectar > Conexão manual…** (Ctrl+M) alcança um endereço que não está na lista. Ele abre a
janela Comandos com a caixa **Host** vazia: digite o endereço, escolha um **Perfil** e clique em
**Conectar**. Um endereço com porta, como `192.0.2.77:5901`, usa aquela porta. O **Adicionar à
lista de hosts…**, ao lado da caixa, põe o PC na lista aberta, e os comandos da janela funcionam
nele como em qualquer outro host (veja [Comandos em um host](commands.pt-BR.md#a-janela-comandos)).
