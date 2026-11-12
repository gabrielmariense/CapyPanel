# Verificando hosts

O CapyPanel pode verificar se os seus PCs estão ligados, quem está logado neles e o que cada PC é.
As respostas aparecem nas colunas **Status** e **Usuário** e no painel de detalhes. Elas ficam só
na memória, nunca no arquivo da lista, e somem quando o CapyPanel fecha; editar o endereço de um
host as apaga. Para guardá-las, exporte-as pelo **Relatório** (veja
[Exportar hosts para uma planilha](host-lists.pt-BR.md#exportar-hosts-para-uma-planilha)).

## Verificar os seus hosts

1. Clique em **Atualizar todos** na barra de ferramentas (**F5**). Ele verifica todos os hosts que
   a tabela mostra: o grupo escolhido com seus subgrupos, uma tag, Todos os hosts, Sem grupo ou os
   resultados de uma pesquisa.
2. Para verificar só alguns, use o botão direito num host para **Atualizar host**, em vários para
   **Atualizar {n} hosts**, ou num grupo para **Atualizar grupo**.
3. A barra de status mostra o andamento, 8 hosts por vez, com um botão **Parar**.

??? note "Mais sobre o Atualizar"

    - O **Atualizar todos** roda as verificações marcadas: clique com o botão direito nele para o
      painel **Atualizar todos os hosts exibidos**, marque status e usuários logados e clique em
      **Executar**. O CapyPanel lembra as marcações, e o **F5** as roda sem abrir o painel (ele é
      ignorado enquanto uma verificação já está rodando).
    - O **Atualizar host** lê o status, os usuários logados e os dados do PC de um host. O
      **Atualizar {n} hosts** e o **Atualizar grupo** leem status e usuários logados; os dados do PC
      são lidos um PC por vez.
    - Verificar quem está logado em mais de 50 hosts pergunta antes.
    - Um host sem endereço, cujo nome não é um nome de computador, é pulado com um aviso na barra de
      status.

## Ler o status de um host

| Status | O que significa |
|---|---|
| **Online** | Um ping, ou uma das portas em que o CapyPanel conecta, respondeu |
| **Offline** | Nada respondeu em 2 segundos |
| **Host não encontrado** | O nome ou endereço não existe |
| **Não verificado** (cinza) | Ninguém o atualizou ainda. Esses hosts ficam por último na ordenação |

Passe o mouse sobre um status para ver quando ele foi verificado e qual endereço respondeu. O painel
de detalhes diz isso embaixo do nome do host, como "Online · verificado em 10:41". O status não usa
conta nenhuma e não precisa de direitos de administrador.

??? note "Como o status é verificado"

    As portas são a 445 (compartilhamento de arquivos do Windows), a 22 (SSH) e a porta de cada
    ferramenta, como a 5900 do VNC e a 3389 da Área de Trabalho Remota. Uma conexão recusada conta
    como resposta. Todos os endereços do nome são tentados, cabo e Wi-Fi: um PC que só responde no
    endereço do Wi-Fi pode estar com o cabo solto.

    Quando um PC não respondeu, os detalhes dizem isso uma vez embaixo do nome, como "Offline ·
    verificado em 10:41", e **Logados** e **Dados do PC** mostram um só traço ou uma linha com o
    motivo.

## Verificar o status sozinho

**Configurações > Hosts > Geral > Atualizar o status sozinho** verifica o status dos hosts exibidos
**a cada minuto**, a cada **5**, **15** ou **30 minutos**, ou num intervalo **Personalizado…** de 1 a
120. Começa **Desligado**. "Só ping e portas: nenhuma conta é usada. O Atualizar da barra sempre
funciona."

## Ver quem está logado

A coluna **Usuário** mostra quem está logado, como `DOMÍNIO\usuário`, com "(desconectado)" para
uma sessão desconectada, ou **Ninguém**. O painel de detalhes lista cada sessão em **Logados**: o
usuário, uma etiqueta **Ativo** ou **Desconectado**, se a pessoa está no computador (**Console**) ou
na **Área de Trabalho Remota**, de qual PC ela veio e desde quando.

É preciso uma conta de administrador em cada host. Nada é instalado nos hosts, e funciona qualquer
que seja o idioma deles.

??? note "Mais sobre os usuários logados"

    - As sessões ativas vêm primeiro. Antes de qualquer verificação a seção diz **Não verificado**;
      sem ninguém logado, **Ninguém logado**; e quando a verificação falha, o motivo (veja a tabela
      no fim), com a explicação completa na dica.
    - **Exibir > Mostrar domínio dos usuários** vem ligado e é lembrado. Desligue para ver só
      `usuário` na coluna, no painel de detalhes e nas pesquisas; ao passar o mouse, o
      `DOMÍNIO\usuário` completo continua aparecendo, então um "admin" local não passa pelo do
      domínio.
    - Depois que alguém faz logoff, a pessoa pode aparecer como desconectada por um tempo ou sumir,
      como na aba Usuários do Gerenciador de Tarefas. É assim que o Windows informa.
    - O CapyPanel lê isso pelo próprio serviço de sessões remotas do Windows.

## Quando um host recusa a sua conta

Por padrão o CapyPanel usa a sua própria conta do Windows. Quando hosts respondem **Sem direitos de
administrador** ou **Conta recusada**:

1. Quando o Atualizar termina, o CapyPanel pede outra conta em **Conta para outros PCs**, dizendo
   os hosts a que ela se refere (os cinco primeiros, e depois quantos mais).
2. Digite-a. Ela é tentada num host por vez até um aceitar; se um host a recusar antes disso, o
   CapyPanel para e pergunta de novo, para uma senha digitada errada não bloquear a conta.
3. Esses hosts são verificados de novo, e a conta vira uma linha de **Configurações > Hosts >
   Credenciais > Contas**.

Depois que um host aceitou a conta, um host que ainda a recusa mostra o erro dele e o Atualizar
continua. Os hosts que recusaram da última vez são tentados por último, para não pararem o próximo
Atualizar antes de ele começar.

O **Comandos como** do painel de detalhes diz qual conta cada host acaba usando. Veja
[Contas para outros PCs](connecting.pt-BR.md#usar-outra-conta-em-alguns-pcs) para dar uma conta própria a um
PC, um grupo, uma tag ou a todos os PCs.

## Ler os dados de um PC

![A seção Dados do PC no painel de detalhes: última reinicialização, espaço livre, Windows, modelo, número de série, memória e BIOS](../images/commands-pc-facts-dark-pt-BR.png)

Selecione um host e fique nele por um instante: o painel de detalhes termina com os **Dados do
PC**, o que o PC diz sobre si mesmo. São a **Última reinicialização**, **Livre em C:**, **Windows**
(como em "Windows 11 Pro 25H2 · 26200.9168"), **Modelo**, **Número de série**, **Memória** e
**BIOS**. O **Ler de novo** lê tudo outra vez.

Eles nunca são lidos pelo **Atualizar todos**, então uma lista de centenas de hosts fica em paz.

??? note "Mais sobre os dados do PC"

    - Até serem lidos, a seção diz "Ainda não lido", com um botão **Ler**. O espaço livre e a última
      reinicialização chegam primeiro, enquanto o título diz "Dados do PC · lendo…"; o resto vem
      alguns segundos depois.
    - Cada dado é lido à parte, então um que falha não leva os outros junto: um dado que não pôde
      ser lido diz o motivo em âmbar no lugar dele. Clique nessa linha para copiá-la. O log do
      aplicativo diz qual parte falhou.
    - O **Atualizar host**, e o **Comandos ▾ > Verificar > Dados do PC** da barra de ferramentas ou
      da janela Comandos, também os leem (veja [Comandos em um host](commands.pt-BR.md)).

??? note "Como o CapyPanel lê outros PCs"

    O status usa ping e portas, e os usuários logados usam o serviço de sessões remotas do Windows.
    Os dados do PC, os programas instalados, as unidades mapeadas e a ferramenta
    [Perfis de usuário](../profiles/user-profiles.pt-BR.md) leem o PC pelo **WMI**, o serviço de
    gerenciamento do próprio Windows, que todo PC com Windows responde. Nada é instalado nem aberto
    no outro PC.

    No seu próprio PC, o CapyPanel fala com o WMI sozinho, pelos objetos de script do Windows. Ele
    só abre o PowerShell para isso quando não consegue fazer isso no seu PC de jeito nenhum, e nunca
    porque a leitura de um PC falhou. O log do aplicativo diz, a cada início, de que jeito ele lê.

    As **Configurações > Hosts > Conexão > Ler dados dos PCs com** definem o jeito para todos no seu
    PC:

    | Opção | O que faz |
    |---|---|
    | **Automático (recomendado)** | WMI direto, e pelo PowerShell só quando isso não dá neste PC. O "em uso:" ao lado diz o jeito que ele está usando |
    | **WMI direto** | Sempre fala com o WMI sozinho e nunca abre o PowerShell, mesmo quando não consegue; nesse caso as leituras falham e dizem por quê |
    | **WMI pelo PowerShell** | Abre o PowerShell no seu PC para falar com o WMI, como o CapyPanel fazia antes da 0.24. Um caminho de volta, caso a leitura direta dê problema na sua rede |

    Os dois jeitos fazem as mesmas perguntas ao outro PC e recebem as mesmas respostas; só muda o que
    abre no seu próprio PC.

## Mensagens que você pode ver

| Mensagem | O que significa | O que fazer |
|---|---|---|
| **Inacessível** | A porta 445 (compartilhamento de arquivos do Windows) não respondeu: o PC está desligado, fora da rede, bloqueia o compartilhamento de arquivos ou não é Windows | Confira se o PC está ligado e na rede |
| **Sem direitos de administrador** | A conta não é administradora nesse host | Use outra conta (veja acima) |
| **Conta recusada** | O host recusou a conta | Confira a conta, ou use outra |
| **Não foi possível ler** | O host respondeu, mas as sessões não puderam ser lidas | Passe o mouse para ver o motivo; tente de novo mais tarde |
| "Sem acesso: precisa de uma conta de administrador neste PC" | Um dado do PC precisa de uma conta de administrador | Use uma conta de administrador para esse host |
| "Não foi possível ler: o Windows não deixou o PowerShell abrir no seu PC (um antivírus pode bloqueá-lo)" | Foi o seu próprio PC que recusou abrir o PowerShell, não o que você estava lendo | Confira o antivírus do seu PC, ou ponha o **Ler dados dos PCs com** em **WMI direto** |
