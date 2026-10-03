# Configurações e arquivos

Abra as Configurações em **Arquivo > Configurações…** (Ctrl+,). As alterações valem quando você
clica em Salvar.

## Geral

- **Abrir ao iniciar:** qual lista de hosts abre quando o CapyPanel inicia (veja
  [Listas de hosts](host-lists.pt-BR.md#qual-lista-abre-ao-iniciar)).
- **Onde o CapyPanel guarda os arquivos:** sua própria pasta e a pasta de logs, cada uma com um
  botão **Abrir pasta**.

## Listas de hosts

Mostra a lista padrão, a pessoal e qualquer outra, se cada uma existe e se você pode editá-la.
Daqui você pode abrir uma lista, **copiar a lista atual** para outro lugar ou criar uma **nova
lista vazia**.

## Conexões

- **Perfis de conexão:** adicione, edite, duplique e exclua perfis, e escolha o padrão. Veja
  [Conectando](connecting.pt-BR.md#gerenciar-perfis).
- **Ferramentas remotas neste PC:** onde cada visualizador foi encontrado, ou "Não encontrado".
  **Localizar…** escolhe o `.exe` manualmente (de uma cópia portátil, por exemplo), salvo só para
  a sua conta; **Automático** volta a encontrá-lo sozinho.

Como em todas as Configurações, nada nesta página é gravado até você clicar em Salvar; Cancelar
descarta todas as alterações.

## Aparência

| Tema | Visual |
|---|---|
| Windows — seguir o tema do sistema / escuro / claro | Visual nativo do Windows, com sua cor de destaque |
| CapyPanel — escuro / claro | O visual próprio do CapyPanel, igual em todo computador |
| Graphite, Paper | Mais dois visuais próprios do CapyPanel |

Também em **Exibir > Tema**. Os temas só mudam o visual, nunca o que o app faz.

## Idioma

English ou Português (Brasil). A troca é imediata, sem reiniciar. Também em **Exibir > Idioma**.

## Onde o CapyPanel guarda os arquivos

O CapyPanel guarda tudo de todos os usuários de um PC numa só pasta, `C:\ProgramData\CapyPanel`,
com uma pasta privada por usuário:

| O quê | Onde |
|---|---|
| Lista de hosts padrão, compartilhada por todos no PC | `hosts.json` |
| Perfis de conexão, seus arquivos de configurações, e qual é o padrão | `profiles\` |
| Definições de visualizadores adicionadas pela sua empresa | `tools\` |
| Suas configurações, lista pessoal e seus caminhos de ferramentas | `users\<você@DOMÍNIO>\` |
| Logs, um arquivo por usuário | `logs\` |
| Definições de visualizadores embutidas e os perfis iniciais | Dentro do app |

- **Sua pasta é privada:** só você, os administradores e o próprio Windows podem abri-la. O
  CapyPanel se recusa a usar uma pasta que outra pessoa criou antes em seu nome.
- **Arquivos compartilhados precisam vir de alguém confiável.** Qualquer usuário pode criar
  arquivos no ProgramData, então o CapyPanel ignora um arquivo compartilhado (lista padrão,
  perfil, definição de visualizador da empresa) criado por outro usuário que não seja
  administrador, e registra isso no log.
- **Os logs nunca contêm senhas.** Eles registram qual visualizador abriu para qual endereço e o
  resultado de cada verificação de login.

### Modo portátil

Um arquivo vazio chamado `capypanel.portable` ao lado do app guarda tudo (configurações, listas,
logs) numa pasta `userdata` ao lado dele, para rodar de um pendrive ou de uma pasta
compartilhada. Quando você roda pelo código-fonte, "ao lado do app" significa a pasta do
repositório.
