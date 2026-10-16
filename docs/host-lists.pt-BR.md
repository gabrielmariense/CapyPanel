# Listas de hosts

Uma lista de hosts é um arquivo JSON com grupos, hosts e suas tags. O CapyPanel mostra uma lista
por vez e salva cada edição nela na hora. Para colocar muitos hosts de uma vez, ou para tirá-los
num arquivo CSV, veja [Importando e exportando hosts](importing.pt-BR.md).

## Grupos e tags

- **Grupos** se aninham o quanto você quiser ("Matriz › Financeiro › 3º andar").
- **Tags** atravessam os grupos ("quiosque", "3-andar"). Clique numa tag no painel da esquerda
  para ver todos os hosts que a têm. Tags que você já usou são sugeridas enquanto digita, com a
  grafia mantida.
- **Notas** guardam o que mais valer a pena saber sobre um host. Elas aparecem no painel de
  detalhes, e a pesquisa sempre as cobre.
- **Sem grupo** é onde um host fica quando você não o colocou em nenhum. "Sem grupo (4)" aparece
  embaixo de "Todos os hosts" no painel da esquerda, com quantos hosts estão sem grupo, e os hosts
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

## Três tipos de lista

| Tipo | Onde fica | Quem pode alterar |
|---|---|---|
| **Padrão** | `C:\ProgramData\CapyPanel\hosts.json`, compartilhada por todos no PC | Quem o Windows deixa gravar nela: quem a criou e os administradores. Os demais a abrem somente leitura. Criada vazia quando não existe |
| **Pessoal** | Sua própria pasta do CapyPanel (veja [Configurações e arquivos](settings-and-files.pt-BR.md)) | Só você. Criada na primeira vez que for necessária |
| **Adicionada** | Onde você escolher, por exemplo uma pasta de rede compartilhada | Quem o Windows deixa gravar o arquivo |

As permissões do Windows decidem se uma lista abre somente leitura, para todos os tipos. Uma lista
somente leitura ainda pode ser navegada e usada para conectar; só a edição fica desligada.

Qualquer usuário pode criar arquivos no ProgramData, então **uma lista padrão criada por outro
usuário (que não seja administrador) não é aberta**: ela poderia mandar a sua senha para o
computador errado. A janela Listas de hosts a mostra como "Não usada: criada por outro usuário",
e um administrador pode substituí-la ou excluí-la.

## A janela Listas de hosts

**Arquivo > Listas de hosts…** (Ctrl+O) mostra todas as listas que você abriu ou adicionou, com o
tipo e se você pode editá-las. A lista em uso fica em negrito e marcada "(em uso)"; passe o mouse
sobre uma lista para ver onde ela está. Dê um clique duplo numa lista, ou selecione-a e clique em
**Abrir**, para trocar para ela.

- **Adicionar existente…** adiciona um arquivo de lista de qualquer lugar, como uma pasta de rede.
- **Nova…** cria uma lista vazia.
- **Copiar lista atual para…** salva uma cópia da lista aberta em outro lugar.
- **Remover da lista** só esquece a lista aqui; nunca exclui o arquivo. O CapyPanel para de
  oferecê-la e não a abre mais ao iniciar, mesmo que tenha sido a última que você usou. Adicione-a
  de novo quando quiser. A lista padrão e a pessoal não podem ser removidas.

A janela guarda as listas nas suas configurações, não nos arquivos de lista. **Configurações >
Listas de hosts** mostra a mesma tabela.

## Qual lista abre ao iniciar

Escolha em **Configurações > Geral > Abrir ao iniciar**: a última lista usada (a escolha padrão),
a lista padrão, sua lista pessoal ou qualquer lista que você adicionou. Se essa lista não existir,
o CapyPanel abre a próxima que conseguir (a padrão, depois a pessoal) e avisa.

## O que uma lista mostra primeiro

Cada lista guarda a própria resposta, em **Configurações > Geral > Inicialização > Mostrar
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
