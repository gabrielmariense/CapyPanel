# A ferramenta Perfis de usuário

Cada pessoa que entra num PC com Windows deixa um perfil para trás: uma pasta em `C:\Users` e uma
entrada no registro do Windows. Em PCs compartilhados eles se acumulam por anos e enchem o disco. A
ferramenta **Perfis de usuário** (**Ctrl+3**) mostra os perfis de um PC, diz quais podem ser
excluídos e por que os outros não, calcula o tamanho deles e exclui os que você marcar, em vários
PCs ao mesmo tempo.

Ela usa os hosts da lista aberta no Hosts, e lê cada PC com a conta que o **Comandos como** dele
diz, que precisa ser administradora lá (veja
[Usar outra conta em alguns PCs](../hosts/connecting.pt-BR.md#usar-outra-conta-em-alguns-pcs)).
Nada é instalado nem executado nos PCs, e escanear só lê.

## Escanear os perfis de um PC

![A aba Hosts: os hosts do grupo escolhido com status, perfis, quantos podem ser excluídos e o escaneamento; Andamento e o host selecionado à direita](../images/profiles-hosts-tab-dark-pt-BR.png)

1. Na aba **Hosts**, escolha um grupo à esquerda.
2. Dê um clique duplo num host, ou aperte **Enter**, para escaneá-lo numa aba própria.
3. Para escanear vários, escolha-os e clique em **Escanear** na barra de ferramentas ("Escanear 3
   hosts"): cada um abre numa aba por trás.

Um host que não está na lista também pode ser escaneado: digite o nome dele na caixa de pesquisa, e
a tabela oferece o **Escanear** com ele.

??? note "Mais sobre a aba Hosts e as abas"

    - A tabela mostra **Nome**, **Endereço**, **Status**, **Perfis**, **Podem ser excluídos**
      (**Excluíveis** quando estreita) e **Escaneamento**, que diz quando um host foi escaneado ou
      em que pé está o escaneamento dele ("escaneando…", "excluindo 2 de 3", "não respondeu"). A
      caixa **Pesquisar nome, endereço** procura em todos os hosts da lista, seja qual for o grupo.
      A aba nunca escaneia sozinha.
    - **Clique do meio** num host, ou **Ctrl+Enter**, para abri-lo numa aba por trás e ficar na
      lista. O botão direito num host oferece **Abrir**, **Escanear**, **Atualizar host**, **Copiar
      nome** e **Copiar endereço**. O **Atualizar todos** verifica se cada host exibido responde,
      como no Hosts.
    - À direita, o **Andamento** acompanha cada host numa aba, como em "4 hosts em abas · 2
      trabalhando · 2 concluídos". Embaixo dele, **Hosts exibidos** resume o grupo escolhido, e
      **Marcados nas abas** lista os hosts com perfis marcados; um clique vai para a aba dele. Com um
      host escolhido, o cartão mostra o **Endereço**, o **Grupo**, o **Escaneado às** e o **Como**,
      a conta.
    - O painel de grupos aqui é só leitura: os grupos são criados no Hosts.
    - As abas nunca se reordenam sozinhas: uma nova abre na ponta direita, e o **▾** no fim da barra
      de abas lista todas. O botão direito numa aba oferece **Fechar**, **Fechar as outras** e
      **Fechar as concluídas**; um clique do meio também fecha uma. Uma aba não pode ser fechada
      enquanto está excluindo.
    - Até quatro hosts são lidos ou calculados ao mesmo tempo, somando todas as abas; os outros
      aguardam a vez.

## Ver quais perfis podem ser excluídos

![A aba de um host: os filtros, a tabela de perfis com três linhas marcadas contornadas em âmbar, e Marcados para excluir à direita](../images/profiles-host-tab-dark-pt-BR.png)

A aba de um host lista os perfis dele com **Usuário**, **Último uso**, **Tamanho**, **Tipo** e
**Estado**:

| Estado | O que quer dizer |
|---|---|
| **Pode excluir** | "Ninguém está conectado com ele, não é do Windows e fica na pasta Users." |
| **Em uso** | "Esta pessoa está conectada agora. Só pode ser excluído depois que ela sair." |
| **Protegido** | "É do próprio Windows. Nunca é excluído aqui." O Administrador interno é um deles |
| **Fora de Users** | A pasta não fica na pasta Users, e o CapyPanel só exclui perfis lá |
| **Revisar** | "Um registro .bak: um perfil que falhou ao carregar. O CapyPanel nunca exclui estes; o conserto é manual, no registro." |

As linhas que não podem ser excluídas ficam esmaecidas e não têm caixa de marcar. Para ver os
antigos primeiro, ponha o **Sem uso há:** em 3 ou 6 meses, ou um ano.

??? note "Os filtros e as colunas"

    - **Ocultar os do Windows**, ligado de início: "Public, Default, o Administrador interno e
      parecidos: nunca são excluídos aqui".
    - **Só sobras**: "Só registros sem pasta e pastas sem registro".
    - **Sem uso há:** **Qualquer data**, ou pelo menos 1, 3 ou 6 meses, ou 1 ano. Um perfil sem data
      nenhuma fica de fora quando isso está definido. Na ponta direita, quantas linhas aparecem ("12
      de 15 exibidos"), ou quantas estão marcadas.
    - **Usuário** é a conta, como `DOMÍNIO\usuário`; uma que o Windows não reconhece mais mostra o
      nome da pasta e "(desconhecida)". **Último uso** é quando a pessoa entrou ou saiu pela última
      vez, ou a data da própria pasta quando o Windows não anotou nenhuma. **Tipo** é **Perfil**,
      **Registro sem pasta**, **Pasta sem registro** ou **Registro .bak**.
    - O cabeçalho da aba nomeia o host, como "Perfis de usuário em DESK-03", com o endereço, quando
      ele foi escaneado e a conta com que foi lido. O **Escanear de novo** lê o host outra vez.

??? note "Os detalhes de um perfil"

    ![Os detalhes de um perfil: estado, conta e SID, pasta, último uso, tamanho e tipo, com Marcar para excluir](../images/profiles-details-dark-pt-BR.png)

    O **ⓘ** no fim de uma linha, o **Enter**, ou o **Detalhes…** do botão direito na linha abre uma
    janela com o **Estado** e o motivo, a **Conta** e o **SID** dela, a **Pasta** com **Caminho**,
    **Último uso**, **Pasta alterada**, **Tamanho** e **Tipo**. "O Windows não reconhece mais esta
    conta; provavelmente foi apagada." avisa quando a conta não existe mais. O **Marcar para
    excluir**, no pé dela, marca a linha dali mesmo.

## Calcular o tamanho deles

Clique em **Calcular tamanhos** na barra de ferramentas: ele calcula o tamanho de cada perfil
exibido, e só lê. O **Parar o cálculo** para na hora, mantendo os tamanhos já calculados.

## Excluir perfis

1. **Marque** os perfis a excluir: a caixa, o **Espaço**, ou um clique duplo na linha. Uma linha
   marcada fica contornada em âmbar e diz **Será excluído**; o cartão **Marcados para excluir** à
   direita os lista com o total, como "3 perfis · 12,4 GB".
2. Clique em **Excluir 3 perfis…**, no pé do painel da direita ou na barra de ferramentas.
3. Leia a lista, digite **EXCLUIR** na caixa e clique no botão âmbar.

"Isto é **definitivo**. Com perfis locais, a área de trabalho e os documentos de cada pessoa vão
junto: não há lixeira nem cópia."

![Excluindo num host: um perfil excluído, um sendo excluído, um na fila, e o cartão Excluindo perfis com Cancelar o restante](../images/profiles-deleting-dark-pt-BR.png)

??? note "Enquanto exclui"

    - Cada host exclui um perfil por vez, e verifica o host de novo antes de cada um: "quem tiver
      entrado desde o escaneamento é ignorado". As linhas vão de **Na fila** para **Excluindo…** e
      depois **Excluído**, **Ignorado** ou **Falhou**, e o cartão **Excluindo perfis** as conta.
    - O **Cancelar o restante** deixa o perfil em andamento terminar e não começa nenhum outro.
      Quando acaba, o cartão diz **Exclusão concluída**, com o que foi liberado, e **Abrir o
      histórico**.
    - Os perfis do próprio Windows e o Administrador interno nunca são excluídos, e um registro
      `.bak` fica para você consertar à mão.
    - Até **EXCLUIR** ser digitado, o **Cancelar** é o botão padrão; depois, o Enter aperta o âmbar.
    - Sair do CapyPanel enquanto um host exclui pergunta antes (veja
      [Primeiros passos](../getting-started.pt-BR.md#fechar-o-capypanel-ou-deixa-lo-na-bandeja)).

??? note "O histórico"

    Cada exclusão, feita ou não, vai para um histórico próprio, um arquivo por usuário do Windows:
    `logs\<você@DOMÍNIO>.user-profiles.log` na pasta do CapyPanel (veja
    [Configurações e arquivos](../settings-and-files.pt-BR.md#onde-o-capypanel-guarda-os-arquivos)).
    Ele diz quando, em qual PC, de quem era o perfil e como terminou.

??? note "Como os perfis são lidos e excluídos"

    Os perfis são lidos pelo WMI, e excluídos pela própria remoção de perfis do Windows naquele PC,
    pedida também pelo WMI (veja
    [Como o CapyPanel lê outros PCs](../hosts/checking.pt-BR.md#ler-os-dados-de-um-pc)).

## Mensagens que você pode ver

Quando um host não pode ser lido, a aba dele diz o motivo em vermelho, com o **Tentar de novo**.

| Mensagem | O que significa | O que fazer |
|---|---|---|
| "{host} não respondeu" | O PC está desligado ou inacessível | Confira se está ligado, e **Tentar de novo** |
| "{host} recusou a conta {account}" | A conta não é aceita lá | **Tentar outra conta…** |
| "O PowerShell não abriu no seu PC" | O seu próprio PC barrou o PowerShell, muitas vezes um antivírus | Veja [Como o CapyPanel lê outros PCs](../hosts/checking.pt-BR.md#ler-os-dados-de-um-pc) |
| "{host} aguarda a vez" | Quatro hosts já estão sendo lidos ou calculados | Nada: ele começa sozinho |
| "Nenhum host da lista com “…”." | O nome que você digitou não está na lista | **Escanear** assim mesmo, com o botão oferecido |
