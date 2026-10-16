# Configurações e arquivos

Abra as Configurações em **Arquivo > Configurações…** (Ctrl+,). A janela tem dois botões:
**Salvar**, que salva e a deixa aberta, e **Fechar**. O Fechar pergunta antes quando algo não está
salvo, e nenhum dos dois é o botão padrão, então o Enter nunca salva nem fecha sem querer.

## Geral

- **Abrir ao iniciar:** qual lista de hosts abre quando o CapyPanel inicia (veja
  [Listas de hosts](host-lists.pt-BR.md#qual-lista-abre-ao-iniciar)).
- **Idioma:** English ou Português (Brasil). Ele muda assim que você escolhe — a janela de
  Configurações inclusive — sem reiniciar e sem nada para salvar. Também em **Exibir > Idioma**.
- **Atualizar:** verificar o status dos hosts exibidos a cada alguns minutos. Vem desligado;
  veja [Verificando hosts](checking.pt-BR.md#status-automatico).
- **Mostrar primeiro:** o que a lista aberta mostra quando ela abre — Todos os hosts, onde você
  parou ou um grupo. Cada lista guarda a própria escolha (veja
  [Listas de hosts](host-lists.pt-BR.md#o-que-uma-lista-mostra-primeiro)).
- **Onde o CapyPanel guarda os arquivos:** os arquivos compartilhados, os seus arquivos e os logs,
  cada um com um botão **Abrir pasta**. Os caminhos estão ali para ler, não para selecionar; passe
  o mouse num deles para vê-lo inteiro.

## Listas de hosts

A mesma tabela e os mesmos botões de **Arquivo > Listas de hosts…** (veja
[Listas de hosts](host-lists.pt-BR.md#a-janela-listas-de-hosts)). A lista que você escolher abre
quando você clica em Salvar.

## Conexões

- **Perfis de conexão:** adicione, edite, duplique e exclua perfis, e escolha o padrão, com um
  botão **Abrir pasta** para a pasta em que eles ficam. Veja
  [Conectando](connecting.pt-BR.md#gerenciar-perfis). O CapyPanel enche essa pasta no primeiro
  início com os perfis que vêm com ele — RealVNC, Remote Desktop e UltraVNC — e um arquivo de
  configurações, `_profiles.json`, que registra o perfil padrão e quais perfis de fábrica já foram
  adicionados, para que um que você exclua não volte. Onde o Windows não deixa você criar a pasta,
  a página mostra os perfis de fábrica e diz "Estes são os perfis que vêm com o app: a pasta ainda
  não existe."
- **Ferramentas remotas:** onde cada ferramenta está instalada, definido uma vez para todos no
  PC. Cada um mostra **✓ Encontrado** (sozinho), **✓ Sua escolha** ou **✗ Não encontrado**, só
  com os botões que fazem sentido: **Alterar caminho…** ou **Localizar…** para escolher o `.exe`
  (de uma cópia portátil, por exemplo), **Encontrar automaticamente** para esquecer essa escolha e
  **Baixar** para abrir o site do visualizador quando ele não está instalado. O Remote Desktop
  Connection vem com o Windows, então normalmente mostra **✓ Encontrado** e não tem Baixar. Como
  nos perfis, só quem o Windows deixa gravar na pasta pode alterá-los.

Embaixo de cada pasta desta página — a dos perfis e a das ferramentas remotas — uma linha diz
quais arquivos o CapyPanel não está usando e por quê, como "2 arquivos ignorados: broken.json (não
pode ser lido), clinicas.json (feito por outro usuário)". Passe o mouse nela para ver os caminhos
inteiros e os erros; ela fica escondida quando todos os arquivos estão em uso.

Como em todas as Configurações, nada nesta página é gravado até você clicar em Salvar. Sair da
página, ou fechar as Configurações, com alterações não salvas pergunta antes: **Salvar
alterações**, **Descartar alterações** ou **Continuar editando**.

## Aparência

| Tema | Visual |
|---|---|
| Windows — seguir o tema do sistema / escuro / claro | Visual nativo do Windows, com sua cor de destaque |
| CapyPanel — escuro / claro | O visual próprio do CapyPanel, igual em todo computador |
| Graphite, Paper | Mais dois visuais próprios do CapyPanel |

Também em **Exibir > Tema**. Os temas mudam só as cores — a fonte, o tamanho dela e os cantos
arredondados são os mesmos em todos — e nunca mudam o que o app faz.

Os temas do Windows seguem a cor de destaque do seu Windows (**Configurações > Personalização >
Cores**), e tudo o que vem dela continua legível com qualquer uma que você escolher: os títulos
das seções, o botão padrão, os destaques e o título Grupos quando você arrasta um grupo até ele. Os
visuais próprios do CapyPanel mantêm os destaques deles, iguais em todo computador.

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
