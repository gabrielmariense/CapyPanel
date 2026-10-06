# Verificando hosts

O CapyPanel pode verificar se os hosts estão ligados e quem está logado neles. Os resultados
aparecem nas colunas **Status** e **Usuário** da tabela de hosts e no painel **Informações**. Eles
ficam só na memória: nunca no arquivo da lista, e somem quando o CapyPanel fecha. Editar o
endereço de um host apaga os resultados dele.

## Atualizar

**Atualizar**, à direita da barra de ferramentas, verifica todos os hosts que a tabela mostra: o
grupo escolhido à esquerda com seus subgrupos, uma tag ou Todos os hosts. Não é preciso selecionar
nada.

- Clique nele e escolha **Status** ou **Usuários logados**.
- Clique com o botão direito para marcar os dois e clique em **Executar**. O CapyPanel lembra o
  que você marcou.

Para verificar só alguns hosts, selecione-os e use o botão direito > **Verificar**. O botão
direito num grupo verifica os hosts dele, incluindo os subgrupos.

O CapyPanel verifica 8 hosts por vez; a barra de status mostra o andamento e um botão **Parar**.
Verificar quem está logado em mais de 50 hosts pergunta antes. Um host sem endereço, cujo nome não
é um nome de computador, é pulado com um aviso na barra de status.

## Status

| Status | Significado |
|---|---|
| **Online** | Um ping, ou uma das portas em que o CapyPanel conecta, respondeu |
| **Offline** | Nada respondeu em 2 segundos |
| **Host não encontrado** | O nome ou endereço não existe |

As portas são a 445 (compartilhamento de arquivos do Windows), a 22 (SSH) e a porta de cada
ferramenta, como a 5900 do VNC e a 3389 da Área de Trabalho Remota. Uma conexão recusada conta
como resposta. Todos os endereços do nome são tentados, cabo e Wi-Fi. Passe o mouse sobre um
status para ver quando ele foi verificado e qual endereço respondeu: um PC que só responde no
endereço do Wi-Fi pode estar com o cabo solto.

O status não usa conta nenhuma e não precisa de direitos de administrador.

### Status automático

**Configurações > Geral > Atualizar** pode verificar o status dos hosts exibidos a cada alguns
minutos (de 1 a 120, 5 por padrão). Ele só faz ping e tenta portas, nunca lê usuários logados,
então nenhuma conta é usada. Vem desligado: nada é verificado sozinho a menos que você o ligue.

## Usuários logados

A coluna **Usuário** mostra quem está logado, como `DOMÍNIO\usuário`, com "(desconectado)" para
uma sessão desconectada, ou **Ninguém**. O painel Informações lista cada sessão: o usuário, se
está no computador ou na Área de Trabalho Remota, ativa ou desconectada, desde quando e de qual
PC.

O CapyPanel lê isso pelo próprio serviço de sessões remotas do Windows: nada é instalado nos
hosts, e funciona qualquer que seja o idioma deles. É preciso uma conta de administrador em cada
host.

| Aparece | Significado |
|---|---|
| **Inacessível** | A porta 445 (compartilhamento de arquivos do Windows) não respondeu: o PC está desligado, fora da rede, bloqueia o compartilhamento de arquivos ou não é Windows |
| **Não é administrador lá** | A conta não é administradora nesse host |
| **Conta recusada** | O host recusou a conta |
| **Não foi possível ler** | O host respondeu, mas as sessões não puderam ser lidas |

Depois que alguém faz logoff, a pessoa pode aparecer como desconectada por um tempo ou sumir, como
na aba Usuários do Gerenciador de Tarefas. É assim que o Windows informa.

### Qual conta é usada

Por padrão, o seu próprio login do Windows. Se hosts responderem **Não é administrador lá** ou
**Conta recusada**, o CapyPanel pede outra conta (`DOMÍNIO\usuário` e senha) e tenta de novo só
nesses hosts. Essa conta:

- fica na memória até o CapyPanel fechar, nunca é salva e só é usada para ler quem está logado;
- é tentada num host por vez: se um host a recusar, o CapyPanel para e pergunta de novo em vez de
  tentá-la nos outros, para a conta não ser bloqueada;
- é esquecida, como as senhas, com **Conectar > Esquecer as senhas digitadas**.

Em PCs fora de um domínio, o Administrador interno é a única conta local que o Windows aceita
remotamente.
