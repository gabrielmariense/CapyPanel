# Code signing policy

CapyPanel is applying to SignPath Foundation to sign its releases. Once the project is accepted,
every release will carry this line:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

Until then, releases aren't signed, and Windows may say the publisher is unknown the first time you
run CapyPanel (see [Download and updates](download.md#download-capypanel)). The SHA-256 beside each
zip lets you check the download either way.

## What gets signed

- Only CapyPanel's own release files, built from this repository's source code by GitHub Actions.
  Nothing built on anyone's own PC is signed.
- Each release is signed only after the project's approver approves that signing request.

## Team roles

| Role | What it means | Members |
|---|---|---|
| Authors | May change the source code without another person's review | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |
| Reviewers | Review changes from anyone else, such as pull requests, before they're merged | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |
| Approvers | Approve each signing request | [Gabriel "GMErebos" Mariense](https://github.com/gabrielmariense) |

Everyone with access to the repository signs in to GitHub with two-factor authentication.

## Privacy

CapyPanel sends no usage data anywhere.

- On its own, it only asks GitHub (api.github.com) for the newest release: at every start by
  default, or once a day, once a week or never, as **Settings > CapyPanel > General > Updates**
  says. It downloads a release from GitHub only when you click **Install and restart**.
- Everything else it contacts is what you set up: the PCs and printers in your lists, and Doc360
  MPS (mps.doc360.com.br) if you add your account for it.
- The documentation, source code and **Report a problem** links in the Help menu and in About
  open in your browser.
