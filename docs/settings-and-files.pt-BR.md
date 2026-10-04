# Configurações e arquivos

Abra as Configurações em **Arquivo > Configurações…** (Ctrl+,). **OK** salva e fecha, **Salvar**
salva e mantém as Configurações abertas, e **Cancelar** fecha e descarta o que não foi salvo.

## Geral

- **Abrir ao iniciar:** qual lista de hosts abre quando o CapyPanel inicia (veja
  [Listas de hosts](host-lists.pt-BR.md#qual-lista-abre-ao-iniciar)).
- **Idioma:** English ou Português (Brasil), trocado sem reiniciar. Também em **Exibir > Idioma**.
  A própria janela de Configurações muda de idioma na próxima vez que você abri-la.
- **Onde o CapyPanel guarda os arquivos:** os arquivos compartilhados, os seus arquivos e os logs,
  cada um com um botão **Abrir pasta**.

## Listas de hosts

A mesma tabela e os mesmos botões de **Arquivo > Listas de hosts…** (veja
[Listas de hosts](host-lists.pt-BR.md#a-janela-listas-de-hosts)). A lista que você escolher abre
quando você clica em OK ou Salvar.

## Conexões

- **Perfis de conexão:** adicione, edite, duplique e exclua perfis, e escolha o padrão. Veja
  [Conectando](connecting.pt-BR.md#gerenciar-perfis).
- **Ferramentas remotas:** onde cada ferramenta está instalada, definido uma vez para todos no
  PC. Cada um mostra **✓ Encontrado** (sozinho), **✓ Sua escolha** ou **✗ Não encontrado**, só
  com os botões que fazem sentido: **Alterar caminho…** ou **Localizar…** para escolher o `.exe`
  (de uma cópia portátil, por exemplo), **Encontrar automaticamente** para esquecer essa escolha e
  **Baixar** para abrir o site do visualizador quando ele não está instalado. O Remote Desktop
  Connection vem com o Windows, então normalmente mostra **✓ Encontrado** e não tem Baixar. Como
  nos perfis, só quem o Windows deixa gravar na pasta pode alterá-los.

Como em todas as Configurações, nada nesta página é gravado até você clicar em OK ou Salvar. Sair
da página com alterações não salvas pergunta antes: **Salvar alterações**, **Descartar
alterações** ou **Continuar editando**.

## Aparência

| Tema | Visual |
|---|---|
| Windows — seguir o tema do sistema / escuro / claro | Visual nativo do Windows, com sua cor de destaque |
| CapyPanel — escuro / claro | O visual próprio do CapyPanel, igual em todo computador |
| Graphite, Paper | Mais dois visuais próprios do CapyPanel |

Também em **Exibir > Tema**. Os temas só mudam o visual, nunca o que o app faz.

## Onde o CapyPanel guarda os arquivos

O CapyPanel guarda tudo de todos os usuários de um PC numa só pasta, `C:\ProgramData\CapyPanel`,
com uma pasta privada por usuário:

| O quê | Onde |
|---|---|
| Lista de hosts padrão, compartilhada por todos no PC | `hosts.json` |
| Perfis de conexão, seus arquivos de configurações, e qual é o padrão | `profiles\` |
| Definições de visualizadores adicionadas pela sua empresa, e onde cada visualizador está instalado | `tools\` |
| Suas configurações e sua lista pessoal | `users\<você@DOMÍNIO>\` |
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
