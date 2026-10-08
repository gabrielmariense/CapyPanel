# Listas de hosts

Uma lista de hosts é um arquivo JSON com grupos, hosts e suas tags. O CapyPanel mostra uma lista
por vez e salva cada edição nela na hora.

## Grupos e tags

- **Grupos** se aninham o quanto você quiser ("Matriz › Financeiro › 3º andar").
- **Tags** atravessam os grupos ("quiosque", "3-andar"). Clique numa tag no painel da esquerda
  para ver todos os hosts que a têm. Tags que você já usou são sugeridas enquanto digita, com a
  grafia mantida.
- **Observações** guardam o que mais valer a pena saber sobre um host.

Uma lista nova começa com um grupo, **Grupo padrão**.

## Organizar grupos e hosts

Os grupos mantêm a ordem que você der a eles. No painel de grupos:

- arraste um grupo para cima ou para baixo para movê-lo, ou solte-o sobre outro grupo para
  colocá-lo dentro dele;
- arraste os hosts selecionados da tabela de hosts para um grupo para movê-los para lá.

Toda mudança é salva na hora. Numa lista somente leitura, arrastar fica desligado.

**Inventário > Gerenciar grupos…** mostra a árvore inteira numa janela, com **Mover para cima**,
**Mover para baixo** e **Ordenar de A a Z**, uma ordenação única que você pode reorganizar depois.
Arrastar também funciona lá, e nada muda até você clicar em **OK**. Listas criadas antes da versão
0.13.0 mostram os grupos na ordem em que foram criados; Ordenar de A a Z os coloca em ordem uma
vez.

## Remover um grupo

Clique com o botão direito num grupo > **Remover**, ou pressione Del com um grupo escolhido. Um
grupo vazio só pede confirmação. Um grupo com grupos ou hosts dentro pergunta o que fazer com
eles:

- **Mover para "3º andar"** — o grupo acima dele — ou **Mover para o nível mais alto**. Essa é a
  opção padrão: os hosts dele vão para esse grupo, os grupos dele sobem um nível e nada é
  excluído.
- **Remover tudo:** o grupo, todos os grupos dentro dele e todos os hosts deles.

Um grupo no nível mais alto não consegue subir os próprios hosts, porque todo host precisa de um
grupo e "Todos os hosts" é a lista inteira, não um grupo. Nesse caso a opção de mover fica
desligada, com um aviso explicando; mova esses hosts para outro grupo antes para mantê-los.

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
computador errado. A janela Listas de hosts a mostra como "Criada por outro usuário: não é usada",
e um administrador pode substituí-la ou excluí-la.

## A janela Listas de hosts

**Arquivo > Listas de hosts…** (Ctrl+O) mostra todas as listas que você abriu ou adicionou, com o
tipo e se você pode editá-las. A lista em uso fica em negrito e marcada "(em uso)"; passe o mouse
sobre uma lista para ver onde ela está. Dê um clique duplo numa lista, ou selecione-a e clique em
**Abrir**, para trocar para ela.

- **Adicionar existente…** adiciona um arquivo de lista de qualquer lugar, como uma pasta de rede.
- **Nova…** cria uma lista vazia.
- **Copiar lista atual para…** salva uma cópia da lista aberta em outro lugar.
- **Remover da lista** só esquece a lista aqui; nunca exclui o arquivo. A lista padrão e a pessoal
  não podem ser removidas.

A janela guarda as listas nas suas configurações, não nos arquivos de lista. **Configurações >
Listas de hosts** mostra a mesma tabela.

## Qual lista abre ao iniciar

Escolha em **Configurações > Geral > Abrir ao iniciar**: a última lista usada (a escolha padrão),
a lista padrão, sua lista pessoal ou qualquer lista que você adicionou. Se essa lista não existir,
o CapyPanel abre a próxima que conseguir (a padrão, depois a pessoal) e avisa.

## Listas compartilhadas e edição ao mesmo tempo

Quando duas pessoas editam a mesma lista compartilhada, o CapyPanel nunca sobrescreve as
alterações da outra. Se o arquivo mudou desde que você o abriu, sua edição não é salva e você
escolhe: salvar sua versão como cópia ou recarregar a lista com as alterações da outra pessoa.

## O formato do arquivo

As listas são JSON legível com uma versão de esquema. Versões mais antigas do CapyPanel mantêm os
campos que não conhecem ao salvar, e uma lista gravada por uma versão mais nova é recusada em vez
de ser danificada.
