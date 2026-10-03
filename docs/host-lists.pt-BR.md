# Listas de hosts

Uma lista de hosts é um arquivo JSON com grupos, hosts e suas tags. O CapyPanel mostra uma lista
por vez e salva cada edição nela na hora.

## Grupos e tags

- **Grupos** se aninham o quanto você quiser ("Matriz › Financeiro › 3º andar"). Remover um
  grupo remove os grupos e hosts dentro dele, depois de perguntar.
- **Tags** atravessam os grupos ("quiosque", "3-andar"). Clique numa tag no painel da esquerda
  para ver todos os hosts que a têm. Tags que você já usou são sugeridas enquanto digita, com a
  grafia mantida.
- **Observações** guardam o que mais valer a pena saber sobre um host.

## Três tipos de lista

| Tipo | Onde fica | Quem pode alterar |
|---|---|---|
| **Padrão** | `C:\ProgramData\CapyPanel\hosts.json`, compartilhada por todos no PC | Quem o Windows deixa gravar nela: quem a criou e os administradores. Os demais a abrem somente leitura. Criada vazia quando não existe |
| **Pessoal** | Sua própria pasta do CapyPanel (veja [Configurações e arquivos](settings-and-files.pt-BR.md)) | Só você. Criada na primeira vez que for necessária |
| **Compartilhada** | Onde você escolher, por exemplo uma pasta de rede | Quem o Windows deixa gravar o arquivo |

As permissões do Windows decidem se uma lista abre somente leitura, para todos os tipos. Uma lista
somente leitura ainda pode ser navegada e usada para conectar; só a edição fica desligada.

Qualquer usuário pode criar arquivos no ProgramData, então **uma lista padrão criada por outro
usuário (que não seja administrador) não é aberta**: ela poderia mandar a sua senha para o
computador errado. As Configurações a mostram como "Criada por outro usuário: não é usada", e um
administrador pode substituí-la ou excluí-la.

**Arquivo > Listas recentes** mostra as listas que você abriu, cada uma com seu tipo e caminho.

## Qual lista abre ao iniciar

Escolha em **Configurações > Geral > Abrir ao iniciar**: a última lista usada (a escolha padrão),
a lista padrão, sua lista pessoal ou qualquer lista que você já abriu. Se essa lista não existir,
o CapyPanel abre a próxima que conseguir (a padrão, depois a pessoal) e avisa.

## Listas compartilhadas e edição ao mesmo tempo

Quando duas pessoas editam a mesma lista compartilhada, o CapyPanel nunca sobrescreve as
alterações da outra. Se o arquivo mudou desde que você o abriu, sua edição não é salva e você
escolhe: salvar sua versão como cópia ou recarregar a lista com as alterações da outra pessoa.

## O formato do arquivo

As listas são JSON legível com uma versão de esquema. Versões mais antigas do CapyPanel mantêm os
campos que não conhecem ao salvar, e uma lista gravada por uma versão mais nova é recusada em vez
de ser danificada.
