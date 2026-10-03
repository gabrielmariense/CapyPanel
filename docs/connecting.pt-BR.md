# Conectando

O CapyPanel abre telas remotas por visualizadores VNC que você mesmo instala. Ele nunca os
distribui, empacota ou baixa.

## Visualizadores suportados

| Visualizador | Como o CapyPanel entrega a senha |
|---|---|
| **UltraVNC Viewer** | Na linha de comando (o único jeito que o UltraVNC aceita). Administradores do seu PC podem ver linhas de comando; o log nunca mostra a senha |
| **RealVNC Viewer** | Por um pipe privado que só a sua conta do Windows pode abrir, lido uma vez. Nada é gravado em disco nem vai para a linha de comando |

O CapyPanel encontra sozinho um visualizador instalado: onde o Windows registrou a instalação
(qualquer pasta), as pastas de Arquivos de Programas de costume, depois o seu PATH. Uma cópia
portátil descompactada em outro lugar não é encontrada automaticamente; quando falta um
visualizador, o CapyPanel pede para instalá-lo ou localizar o `.exe`, e lembra o caminho para a
sua conta.

## Perfis de conexão

Uma rede costuma misturar várias configurações: servidores VNC que pedem uma conta do Windows (o
MS-Logon do UltraVNC), servidores que pedem só uma senha VNC, plugins de criptografia, RealVNC em
Raspberry Pis. Um **perfil de conexão** diz qual delas um host usa:

- o **visualizador**;
- o **login**: usuário e senha, ou só senha;
- **opções** que o visualizador oferece, como o **plugin SecureVNC** do UltraVNC.

### Gerenciar perfis

- Os perfis são gerenciados em **Configurações > Conexões** (também em **Conectar > Perfis de
  conexão…**): adicionar, editar, duplicar, excluir. Cada um tem um nome, um visualizador, um
  login (só os que esse visualizador suporta), as opções do visualizador (como o SecureVNC) e uma
  porta, em branco para a do próprio visualizador.
- O CapyPanel começa com um perfil por visualizador, **UltraVNC** e **RealVNC**, ambos com
  "usuário e senha". São perfis comuns: altere ou exclua como qualquer outro.
- Todos os perfis ficam juntos em `C:\ProgramData\CapyPanel\profiles\`, junto da lista padrão,
  para que todos no PC vejam os mesmos e seja fácil conferi-los. **As permissões do Windows
  decidem quem pode alterá-los**: depois que o CapyPanel cria a pasta, ela fica somente leitura
  para os outros usuários. Um arquivo de perfil criado por outro usuário (que não seja
  administrador) é ignorado.
- **O perfil padrão**, usado pelos hosts cujos grupos não definem nenhum, é escolhido na mesma
  página e salvo na mesma pasta, então é o mesmo para todos.
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

Quando você clica em Salvar, o CapyPanel copia o arquivo para junto do perfil
(`profiles\<id>.vnc`). Ele é usado **exatamente como foi salvo**, inclusive o plugin de
criptografia; só o `host` é esvaziado, já que o endereço vem do host que você abre. Enquanto um
perfil tem arquivo, as opções dele (como o SecureVNC) ficam desligadas: quem decide é o arquivo.
Ao conectar, o visualizador recebe uma cópia temporária, apagada um minuto depois, e o arquivo
compartilhado nunca é alterado.

### Escolher um perfil

- **Num grupo:** clique com o botão direito no grupo > **Perfil de conexão**. Todos os hosts
  dentro dele o seguem, inclusive os de grupos aninhados, a menos que definam o próprio.
- **Em hosts:** no campo **Perfil de conexão** do host, ou clique com o botão direito em um ou
  mais hosts > **Perfil de conexão**.
- **"Do grupo"** significa que o host segue o grupo mais próximo que define um perfil. Hosts sem
  perfil em lugar nenhum usam o padrão.

O painel **Informações** mostra o perfil de cada host e de onde ele vem, por exemplo
"Raspberry Pis (do grupo “Raspberries”)".

Uma lista guarda só o ID do perfil. Quando um host ou grupo cita um perfil que o seu PC não tem,
ele segue o perfil do grupo (ou o padrão), e o menu do botão direito mostra o que falta como "não
disponível neste PC".

## Senhas

- O CapyPanel pede a senha de um perfil na primeira vez que você conecta com ele e **a lembra na
  memória, por perfil**, até fechar. Hosts com outro perfil nunca a recebem.
- As senhas **nunca são salvas** em disco.
- **Conectar > Esquecer as senhas digitadas** as apaga, por exemplo depois de um erro de
  digitação: o CapyPanel não consegue saber quando um visualizador recusa uma senha.
- Senhas VNC clássicas têm no máximo 8 caracteres, então a caixa de senha de um perfil UltraVNC
  "só senha" para em 8.

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

**Conectar > Conexão manual…** (Ctrl+M) abre um endereço que não está na lista, com o perfil e a
porta que você escolher. Deixe a porta em "Padrão" para usar a do perfil.
