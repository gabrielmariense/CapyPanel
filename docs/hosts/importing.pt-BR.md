# Importando e exportando hosts

Os hosts não precisam ser digitados um a um. **Inventário > Importar hosts…** lê uma lista que
você cola ou um arquivo CSV, e o **Relatório** da barra de ferramentas grava o que você tem de
volta em CSV. Os dois usam o mesmo formato, então uma lista pode fazer o caminho de ida e volta.

## Importando hosts

**Inventário > Importar hosts…** abre a janela **Importar hosts**. Nada muda na sua lista até
você clicar em **Adicionar {n} hosts**, e a janela avisa isso embaixo da prévia.

### Trazendo a lista

Cole uma lista na caixa de cima ou clique em **Abrir um arquivo CSV…** para ler um arquivo `.csv`
ou `.txt`. De qualquer um dos jeitos as linhas preenchem a tabela de prévia abaixo. Três formatos
são entendidos, e o botão **Formatos…** mostra cada um com um exemplo:

| Formato | Como é |
|---|---|
| **Nomes de host** | Um nome de computador por linha |
| **Nome e endereço** | Um nome e, depois, o nome do computador na rede ou o endereço IP, separados por vírgula, ou duas colunas copiadas do Excel |
| **CSV com cabeçalho** | Uma primeira linha dando nome às colunas: `nome, endereço, grupo, tags, notas` |

Com cabeçalho as colunas podem vir em qualquer ordem, e os nomes delas funcionam em português ou
em inglês (`name, address, group, tags, notes`). Numa célula de grupo, `/` separa os níveis
("Matriz/Recepção"); numa célula de tags, `;` separa as tags. As colunas que o CapyPanel não usa
são ignoradas, e o resumo diz quais: "Colunas ignoradas: …".

Uma lista com mais do que um nome e um endereço, e sem linha de cabeçalho, não pode ser lida,
porque o CapyPanel não adivinha qual coluna é qual. Ele diz "Esta lista precisa de uma linha de
cabeçalho." e aponta para Formatos….

### Conferindo antes de entrar

A tabela de prévia mostra **Nome**, **Endereço**, **Grupo**, **Tags**, **Notas** e um **Aviso**
para cada linha. Clique com o botão direito numa linha:

- **Editar célula** (F2) altera o valor sob o ponteiro; dois cliques fazem o mesmo.
- **Colocar no grupo ▸** coloca as linhas selecionadas num grupo, escolhido na árvore.
- **Definir tags…** dá as mesmas tags às linhas selecionadas, separadas por `;`.
- **Deixar fora da importação** (Del) tira as linhas desta importação. O arquivo não é alterado.
- **Adicionar uma linha abaixo** digita um host à mão.

Editar na tabela reescreve o texto colado acima como CSV com uma linha de cabeçalho, para que os
dois sempre coincidam. O CapyPanel pergunta antes de fazer isso na primeira vez.

### Onde os hosts vão parar

**Hosts sem grupo vão para:** escolhe onde ficam as linhas que não nomeiam grupo nenhum: **Sem
grupo** ou qualquer grupo da lista. Começa no grupo que estava escolhido quando você abriu a
janela.

Um grupo nomeado no arquivo que ainda não existe é criado pela importação. A prévia o marca ("Um
grupo novo: a importação o cria") e o resumo diz o nome: "Grupo novo: …".

### O que é adicionado

O resumo conta três coisas: "{n} hosts serão adicionados." e, quando se aplicam, "{n} ignorados."
e "{n} não podem ser adicionados."

- Um host que já está na sua lista é **ignorado**, nunca sobrescrito. A linha dele diz o que
  repete, como "Já está na lista, em “Recepção”", ou "Mesmo nome da linha 7" para uma repetição
  dentro do próprio arquivo.
- Uma linha que **não pode ser adicionada** diz por quê: "Sem nome", "Não é um nome de computador
  nem um endereço IP" ou "Sem endereço: o nome precisa ser o nome do computador na rede".
- As tags e as notas entram junto com os hosts.

**Adicionar {n} hosts** adiciona e fecha a janela; a barra de status diz quantos entraram.

## Exportando hosts

O **Relatório**, na barra de ferramentas, abre a janela **Relatório**. Ela só lê a sua lista, então
funciona também numa lista somente leitura.

### Hosts, colunas e predefinições

- **Hosts:** uma caixa de seleção com tudo que você pode exportar, cada item com quantos hosts
  tem: os **resultados da pesquisa** enquanto uma pesquisa está ativa, as **tags escolhidas**
  enquanto houver alguma, os **hosts selecionados** quando você tem mais de um selecionado,
  **Todos os hosts**, **Sem grupo**, cada grupo (com os hosts dos grupos de dentro dele) e
  **Tag: {tag}** para cada tag. Ela abre no que a janela está mostrando, sempre.
- **Colunas:** marque o que cada linha deve ter, agrupado em **Host** (Nome, Endereço, Grupo),
  **Tags e notas** (Tags, Notas) e **Última verificação** (Status, Usuários logados). As marcações
  são guardadas assim que você as muda, então fechar a janela nunca as perde.
- **Predefinição:** **Para importar** marca os campos dos próprios hosts, "que Importar hosts lê
  de volta: para levar hosts a uma lista". Guarde o seu próprio conjunto com **Salvar como
  predefinição…** e tire um com **Excluir**. Um nome já usado pergunta "Já existe uma predefinição
  chamada “{name}”. Substituí-la?", com Cancelar como padrão. Marcações que não correspondem a
  nenhuma predefinição aparecem como **Personalizado**.

### Status e usuários logados

Essas duas colunas vêm da última verificação (veja [Verificando hosts](checking.pt-BR.md)), então
um host que ninguém verificou é exportado vazio. Marcar uma delas oferece **Atualizar**, que
verifica esses hosts agora e mostra "Verificando 3 de 12…" com um botão **Parar** enquanto corre.

Com **Usuários logados** marcado, um aviso fica na tela: "Inclui quem estava logado em cada PC.
Mantenha o arquivo privado."

### Copiar, ou Exportar… para um arquivo

A **Prévia** mostra as linhas que vão sair. Depois:

- **Copiar** coloca todas as linhas na área de transferência com tabulações entre as colunas, para
  colar direto no Excel. Ele diz quantos hosts copiou e de onde, e a janela fica aberta, então
  outra parte da lista pode sair em seguida.
- **Exportar…** salva um CSV com o nome da lista, e da parte dela que você escolheu, diz
  "Relatório salvo: 12 hosts de Todos os hosts." com o arquivo embaixo, e oferece **Abrir arquivo**
  ou **Abrir pasta**.

**Fechar**, embaixo, é a única saída: não há nada para cancelar, já que cada escolha daqui é
guardada assim que é feita. A barra de status repete o que saiu.

O arquivo usa o separador de colunas que o Excel deste PC espera, vírgula ou ponto e vírgula onde
esse é o separador local, com as tags separadas pelo outro caractere. Ele é gravado de um jeito que
abre os nomes acentuados corretamente.

O que o Relatório grava é lido de volta pelo Importar hosts, o que faz do **Para importar** um
jeito de copiar hosts entre listas, ou de guardar uma cópia de uma lista antes de uma mudança
grande.
