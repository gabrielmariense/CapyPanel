# Listas de impressoras

Uma lista de impressoras é um arquivo JSON com grupos, impressoras e suas tags, exatamente como uma
lista de hosts guarda hosts. A ferramenta Impressoras mostra uma lista por vez e salva cada edição
nela na hora.

As listas dos dois tipos ficam separadas. Cada arquivo registra de que tipo é, então abrir uma
lista de impressoras no Hosts, ou uma lista de hosts no Impressoras, é recusado com "“{path}” não é
uma lista de impressoras." em vez de uma janela cheia de linhas vazias.

## Onde elas ficam

O CapyPanel guarda uma pasta para cada tipo de lista, nas duas pastas de listas:

| Pasta | Onde |
|---|---|
| **Listas de impressoras compartilhadas** | `C:\ProgramData\CapyPanel\lists\printers` |
| **Suas listas de impressoras** | `C:\ProgramData\CapyPanel\users\<você@DOMÍNIO>\lists\printers` |

O Hosts usa `lists\hosts` nos mesmos dois lugares. Todo o resto funciona como nos hosts: uma lista
salva numa dessas pastas aparece sozinha, a pasta compartilhada é de todos no PC e a sua é privada,
e no modo portátil as duas ficam dentro da pasta `userdata` do próprio app. Veja
[Listas de hosts](../hosts/host-lists.pt-BR.md#onde-as-listas-ficam) para as regras de nome e o que
as permissões do Windows decidem.

## O menu de listas

O nome da lista aberta fica no topo do painel de grupos. O menu dele traz todas as listas de
impressoras que o CapyPanel encontrou ou que você adicionou, depois **Nova lista de impressoras**,
**Abrir uma lista de impressoras** (Ctrl+O) e **Gerenciar listas de impressoras…**, que abre
**Configurações > Impressoras > Listas de impressoras**.

## Grupos e tags

Os grupos se aninham o quanto você quiser, impressoras sem grupo próprio ficam em **Sem grupo**, e
as tags atravessam os grupos. Arrastar, **Mover para**, **Gerenciar grupos…** e remover um grupo
funcionam como no Hosts, que [Listas de hosts](../hosts/host-lists.pt-BR.md) descreve.

## Configurações

**Configurações > Impressoras** tem três seções:

- **Inicialização > Lista ao iniciar:** qual lista de impressoras abre com a ferramenta, e
  **Mostrar primeiro**, o que essa lista mostra quando abre. Cada lista guarda a própria resposta.
- **Atualizar:** a comunidade SNMP, o nível baixo de suprimento e como a coluna Toner aparece,
  tudo em [Verificando impressoras](checking.pt-BR.md).
- **Listas de impressoras:** a tabela de todas as listas com o tipo e o que você pode fazer com
  cada uma, com **Nova…**, **Adicionar existente…** e **Remover**. É a mesma página do Listas de
  hosts, inclusive no que o **Remover** pergunta, como
  [Listas de hosts](../hosts/host-lists.pt-BR.md#configuracoes-hosts-listas-de-hosts) explica.
