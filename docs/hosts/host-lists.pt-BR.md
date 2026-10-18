# Listas de hosts

Uma lista de hosts é um arquivo JSON com grupos, hosts e suas tags. O CapyPanel mostra uma lista
por vez e salva cada edição nela na hora. Para colocar muitos hosts de uma vez, ou para tirá-los
num arquivo CSV, veja [Importando e exportando hosts](importing.pt-BR.md).

## Grupos e tags

- **Grupos** se aninham o quanto você quiser ("Matriz › Financeiro › 3º andar").
- **Tags** atravessam os grupos ("quiosque", "3-andar"). Clique numa tag no painel de grupos
  para ver todos os hosts que a têm. Tags que você já usou são sugeridas enquanto digita, com a
  grafia mantida.
- **Notas** guardam o que mais valer a pena saber sobre um host. Elas aparecem no painel de
  detalhes, e a pesquisa sempre as cobre.
- **Sem grupo** é onde um host fica quando você não o colocou em nenhum. "Sem grupo (4)" aparece
  embaixo de "Todos os hosts" no painel de grupos, com quantos hosts estão sem grupo, e os hosts
  arrastados para lá saem do grupo em que estavam.

Uma lista nova começa com um grupo, **Grupo padrão**.

## Organizar grupos e hosts

Os grupos mantêm a ordem que você der a eles. No painel de grupos:

- arraste um grupo para cima ou para baixo para movê-lo, ou solte-o sobre outro grupo para
  colocá-lo dentro dele;
- arraste um grupo até o título **Grupos**, que se ilumina quando você chega nele, para movê-lo
  para o nível superior;
- arraste os hosts selecionados da tabela de hosts para um grupo para movê-los para lá.

Clique com o botão direito num grupo > **Mover para** lista **Grupos** — o topo do painel, dentro
de nada — e todos os grupos em que esse pode entrar, desenhados como uma árvore; o próprio grupo e
os subgrupos dele não aparecem, e o lugar atual fica marcado. Para hosts, clique com o botão
direito neles > **Mover para** lista **Sem grupo** primeiro, e depois a mesma árvore. Um grupo que
você recolheu continua recolhido enquanto
você trabalha, e mover um grupo para dentro de um recolhido abre o caminho até ele, para o que você
moveu continuar visível.

Toda mudança é salva na hora. Numa lista somente leitura, arrastar fica desligado.

**Inventário > Gerenciar grupos…** mostra a árvore inteira numa janela, sob uma raiz **Grupos**
com linhas de árvore, com **Mover para**, **Mover para cima**, **Mover para baixo** e
**Classificar de A a Z**, uma ordenação única que você pode reorganizar depois. Arrastar também
funciona lá: solte um grupo sobre **Grupos**, ou abaixo da última linha, para tirá-lo de todos os
grupos. Nada muda até você clicar em **OK**.
Listas criadas antes da versão 0.13.0 mostram os grupos na ordem em que foram criados;
Classificar de A a Z os coloca em ordem uma vez.

## Remover um grupo

Clique com o botão direito num grupo > **Remover selecionado**, ou pressione Del com um grupo
escolhido. Um grupo vazio só pede confirmação. Um grupo com algo dentro pergunta antes o que fazer
— "“3º andar” contém 2 grupos e 7 hosts. O que fazer com eles?" — e oferece duas saídas:

- **Mover para ▸** escolhe para onde eles vão, na mesma árvore de mover hosts: **Sem grupo** ou
  qualquer grupo que não esteja sendo removido. O grupo acima deste fica marcado, então a resposta
  de sempre é um clique. Nada é excluído; os grupos de dentro vão junto com os hosts deles, e com
  **Sem grupo** eles acabam direto embaixo de **Grupos**.
- **Remover tudo:** o grupo, todos os grupos dentro dele e todos os hosts deles.

Cancelar é o botão padrão, então Enter ou Esc deixa a lista como está.

## Onde as listas ficam

O CapyPanel guarda as listas em duas pastas, criadas no primeiro início:

| Pasta | Onde | Para quem |
|---|---|---|
| **Listas compartilhadas** | `C:\ProgramData\CapyPanel\lists` | Todos no PC. A **lista padrão** é o `default.json` ali |
| **Suas listas** | `C:\ProgramData\CapyPanel\users\<você@DOMÍNIO>\lists` | Só você e os administradores. Sua **lista pessoal** é o `personal.json` ali |

**Toda lista salva numa dessas pastas aparece sozinha** — não há nada para adicionar. Coloque um
arquivo na pasta compartilhada e todos no PC o têm no menu de listas; coloque um na sua e ele é só
seu. No modo portátil as duas pastas ficam dentro da pasta `userdata` do próprio app (veja
[Configurações e arquivos](../settings-and-files.pt-BR.md#modo-portatil)).

Uma lista de antes da versão 0.19, quando elas eram arquivos `hosts.json`, é copiada para dentro
das pastas uma vez, sozinha.

As listas se chamam "Padrão", "Pessoal", e cada uma das outras pelo nome do arquivo sem o `.json`.
Duas listas com o mesmo nome mostram o nome da pasta delas depois, e o caminho inteiro está sempre
na dica.

As permissões do Windows decidem se uma lista abre somente leitura, para toda lista onde ela
estiver. Uma lista somente leitura ainda pode ser navegada e usada para conectar; só a edição fica
desligada. Uma lista em qualquer outro lugar — numa pasta de rede, por exemplo — é adicionada uma
vez e fica no menu de listas desde então.

Qualquer usuário pode criar arquivos no ProgramData, então **uma lista compartilhada criada por
outro usuário que não seja administrador não é aberta**: ela poderia mandar a sua senha para o
computador errado. Ela fica fora do menu de listas, é registrada no log e aparece nas Configurações
como "Não usada: criada por outro usuário", onde um administrador pode substituí-la ou excluí-la.

## O menu de listas

O nome da lista aberta fica no topo do painel de grupos, e no título da janela. Clique nele e o
menu traz:

- **todas as listas que o CapyPanel encontrou ou que você adicionou**, com a aberta marcada e o
  caminho de cada uma na dica. Escolha uma para trocar para ela;
- **Nova lista…**, embaixo delas, e **Abrir lista…** (Ctrl+O), que abre qualquer arquivo de lista
  de qualquer lugar e o mantém no menu desde então;
- **Gerenciar listas de hosts…**, que abre
  [Configurações > Hosts > Listas de hosts](#configuracoes-hosts-listas-de-hosts).

## Criar uma lista nova

**Nova lista…**, no menu de listas ou na página das Configurações, abre a **Nova lista de hosts**:
um **Nome** e **Para:**

- **Todos neste PC (compartilhada)** salva na pasta de listas compartilhadas. Só quem o Windows
  deixa gravar nessa pasta pode escolher isso; para os outros fica apagado, com um aviso dizendo
  por quê.
- **Só eu (pessoal)** salva na sua própria pasta de listas.
- **Outro lugar, como uma pasta de rede…** pergunta onde numa janela de arquivos.

Um nome já usado pergunta antes de substituir esse arquivo por uma lista vazia. A lista nova abre
na hora.

## Configurações > Hosts > Listas de hosts

As mesmas listas do menu de listas, como uma tabela de **Lista**, **Tipo** e **Acesso**:

| Coluna | O que ela diz |
|---|---|
| **Lista** | O nome da lista, e "(em uso)" na que está aberta. O caminho dela está na dica |
| **Tipo** | **Compartilhada** (na pasta compartilhada), **Sua** (na sua) ou **Adicionada** (uma lista de outro lugar) |
| **Acesso** | **Leitura/gravação**, **Somente leitura**, **Criada ao abrir** para uma lista padrão ou pessoal que ainda não existe, **Arquivo não encontrado**, ou **Não usada: criada por outro usuário** |

**Nova…**, **Adicionar existente…** e **Remover** ficam embaixo da tabela. O botão direito numa
linha acrescenta **Abrir**, **Salvar uma cópia…** e **Abrir pasta**. Um clique duplo, ou o
**Abrir**, abre uma lista; adicionar uma ou salvar uma cópia não abre.

Como a página diz embaixo da tabela: "Listas salvas numa pasta de listas aparecem aqui sozinhas;
Remover pergunta se o arquivo também deve ser excluído." O **Remover** pergunta o que você quis
dizer:

- **Remover das minhas listas** não mexe no arquivo. Uma lista que mora numa pasta de listas fica
  escondida só para você, e **Adicionar existente…** ou **Abrir lista…** a traz de volta.
- **Excluir o arquivo** move o arquivo para a **Lixeira**, para todos que o usam. A pergunta mostra
  o caminho numa linha antes.
- **Cancelar** é o botão padrão.

Uma lista cujo arquivo não pode ser excluído, ou que não está lá, é simplesmente tirada das suas
listas. Remover a lista que você tem aberta abre a lista padrão. A lista padrão e a pessoal não
podem ser removidas.

## Qual lista abre ao iniciar

Escolha em **Configurações > Hosts > Geral > Inicialização > Abrir ao iniciar**: a última lista
usada (a escolha padrão), a lista padrão, sua lista pessoal ou qualquer outra lista que você tenha.
Se essa lista não abrir, o CapyPanel abre a próxima que conseguir — a lista padrão, depois a sua
lista pessoal — e avisa.

## O que uma lista mostra primeiro

Cada lista guarda a própria resposta, em **Configurações > Hosts > Geral > Inicialização > Mostrar
primeiro**:

- **Todos os hosts**, a lista inteira;
- **Onde parei**, o grupo, a tag ou a visão que estava aberta quando você fechou;
- **Um grupo escolhido ▸**, escolhido na árvore, ou Sem grupo.

A configuração é para a lista aberta agora, e o aviso embaixo dela diz isso. Sem nenhuma lista
aberta ela lê "Abra uma lista de hosts para escolher o que ela mostra primeiro." O menu de botão
direito de um grupo define a mesma coisa: **Mostrar este grupo primeiro** é uma marcação, e clicar
de novo a tira.

## Listas compartilhadas e edição ao mesmo tempo

Quando duas pessoas editam a mesma lista compartilhada, o CapyPanel nunca sobrescreve as
alterações da outra. Se o arquivo mudou desde que você o abriu, sua edição não é salva e você
escolhe: salvar sua versão como cópia ou recarregar a lista com as alterações da outra pessoa.

## O formato do arquivo

As listas são JSON legível com uma versão de esquema. Versões mais antigas do CapyPanel mantêm os
campos que não conhecem ao salvar, e uma lista gravada por uma versão mais nova é recusada em vez
de ser danificada.
