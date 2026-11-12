# Política de assinatura de código (Code signing policy)

O CapyPanel se candidatou à SignPath Foundation para assinar as suas versões. Quando o projeto for
aceito, toda versão vai trazer esta linha:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

(Assinatura de código gratuita fornecida pela SignPath.io, certificado da SignPath Foundation.)

Até lá, as versões não são assinadas, e o Windows pode dizer que o editor é desconhecido na
primeira vez que você roda o CapyPanel (veja [Baixar e atualizar](download.pt-BR.md#baixar-o-capypanel)).
O SHA-256 ao lado de cada zip permite conferir o download de qualquer jeito.

## O que é assinado

- Só os arquivos da própria versão do CapyPanel, gerados a partir do código-fonte deste
  repositório pelo GitHub Actions. Nada gerado no PC de alguém é assinado.
- Cada versão só é assinada depois que o aprovador do projeto aprova aquele pedido de assinatura.

## Papéis da equipe

| Papel | O que significa | Membros |
|---|---|---|
| Autores (Authors) | Podem alterar o código-fonte sem revisão de outra pessoa | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |
| Revisores (Reviewers) | Revisam as mudanças de qualquer outra pessoa, como pull requests, antes de entrarem | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |
| Aprovadores (Approvers) | Aprovam cada pedido de assinatura | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |

Todos com acesso ao repositório entram no GitHub com autenticação em dois fatores.

## Privacidade

O CapyPanel não envia dados de uso para lugar nenhum.

- Sozinho, ele só pergunta ao GitHub (api.github.com) qual é a versão mais nova: a cada início por
  padrão, ou uma vez por dia, uma vez por semana ou nunca, como diz **Configurações > CapyPanel >
  Geral > Novas versões**. Ele só baixa uma versão do GitHub quando você clica em **Instalar e
  reiniciar**.
- Todo o resto que ele contata é o que você configura: os PCs e as impressoras das suas listas, e
  o Doc360 MPS (mps.doc360.com.br) se você adicionar a sua conta dele.
- Os links de documentação, código-fonte e **Relatar um problema** no menu Ajuda e no Sobre abrem
  no seu navegador.
