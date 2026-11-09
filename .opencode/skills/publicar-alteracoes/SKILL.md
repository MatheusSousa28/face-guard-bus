---
name: publicar-alteracoes
description: Revisa, confirma, commita e publica alterações selecionadas no GitHub e no Hugging Face Space.
---

# Skill: publicar-alteracoes

Use este procedimento quando o usuário solicitar a publicação do projeto FaceGuard Bus. O destino Hugging Face padrão é:

`https://huggingface.co/spaces/MatheusSousa28/FaceGuard-Bus`

O processo cria um commit local e publica esse commit no GitHub e no Space. Esta skill não autoriza por si só commit ou publicação: é obrigatório cumprir as confirmações abaixo durante cada execução.

## Regras inegociáveis

- **Nunca** commitar ou publicar sem mostrar a lista exata de arquivos para GitHub e Hugging Face, obter a mensagem exata do commit e receber uma confirmação explícita para prosseguir.
- Não faça commit nem publicação ao configurar, explicar ou testar a skill. Só execute esses passos quando o usuário invocar o fluxo e aprovar naquela execução.
- Nunca solicite, mostre, registre em arquivo, passe como argumento de comando, ou inclua em URL o token do Hugging Face. Use credenciais já armazenadas pelo `hf auth login`/credential helper. Não coloque tokens no `.env` do projeto.
- Nunca inclua `.env`, credenciais, bancos locais, chaves, caches, arquivos de ambiente virtual ou outros artefatos privados. Se houver dúvida sobre um arquivo, pare e pergunte; não o descarte nem altere.
- Não use `git add -A`, `git add .`, `git commit -am`, `git reset`, `git checkout`, `git clean`, `--force` ou comandos que sobrescrevam histórico/alterações existentes sem deixar explícita a situação para o usuário e pedir sua autorização.
- Não remova nem desfaça mudanças staged ou unstaged do usuário. Se o index contiver alterações fora da seleção aprovada, pare e pergunte como proceder; nunca limpe o index automaticamente.
- Não diga que uma publicação teve sucesso sem confirmar o resultado do push para cada destino.

## Fluxo obrigatório

### 1. Inspecionar sem alterar

Use o terminal para verificar, no mínimo:

- diretório/repositório atual e branch;
- `git status --short`, separando alterações staged, unstaged, deletadas e não rastreadas;
- `git diff --name-status` e `git diff --cached --name-status`;
- remotos Git (`git remote -v`), sem imprimir ou expor credenciais embutidas em URLs;
- existência dos arquivos de autenticação/CLI sem ler ou revelar conteúdo secreto.

Não faça `fetch`, `pull`, `add`, `commit` ou `push` nesta etapa. Não trate um arquivo não rastreado como aprovado automaticamente.

### 2. Conferir destinos e autenticação

- GitHub: identificar o remoto de destino configurado; normalmente `origin`. Confirmar que aponta ao repositório esperado. Se não existir ou houver dúvida, perguntar ao usuário.
- Hugging Face: conferir o remoto existente. Se estiver ausente, propor/configurar um remoto chamado `huggingface` para o Space padrão acima **somente após autorização**. Nunca substituir um remoto existente sem perguntar.
- Verificar a sessão Hugging Face usando `hf auth whoami` (ou o executável conhecido no ambiente, por exemplo `~/.venvs/hf-cli/bin/hf auth whoami`). O comando só pode mostrar a identidade, nunca o token. Se não autenticado, parar e orientar o usuário a autenticar localmente.
- Confirmar branch de destino e estratégia de push. Para Spaces, usar a branch configurada pelo Space, normalmente `main`. Não presumir destino se divergir do branch local/remoto.
- O token de Hugging Face é usado pela autenticação local do CLI/credential helper no push Git HTTPS; não construir URL com token nem enviar conteúdo por API alternativa.

### 3. Apresentar manifesto e pedir uma confirmação única

Monte a lista exata de arquivos candidatos por estado do Git, incluindo adições, edições e exclusões. Revise nomes e, quando necessário, diff/conteúdo para detectar segredos e artefatos impróprios.

Mostre claramente:

1. destino GitHub (remoto e branch);
2. destino Hugging Face (Space, remoto e branch);
3. lista exata que irá para o GitHub;
4. lista exata que irá para o Hugging Face;
5. arquivos encontrados que foram excluídos da publicação e motivo;
6. estado do index e qualquer bloqueio.

Como a publicação usa o mesmo commit para ambos os destinos, as duas listas devem ser idênticas. Se for tecnicamente necessário que difiram, explique e peça aprovação explícita das duas listas antes de continuar.

Após revisar os arquivos e destinos, apresente em uma única mensagem o manifesto exato (destinos, branches, arquivos a publicar e arquivos excluídos), proponha uma mensagem de commit adequada ao que foi alterado e peça uma única confirmação que autorize tanto essa mensagem quanto a publicação. Use uma pergunta direta, por exemplo: **“Sugestão de commit: `...`. Posso usar essa mensagem e publicar estes arquivos no GitHub e no Hugging Face?”**

Não faça perguntas separadas para selecionar arquivos, obter mensagem e confirmar publicação. A pergunta única deve deixar explícitos os arquivos, destinos e a mensagem sugerida, e permitir ao usuário corrigir qualquer item. Só prossiga se a resposta aprovar claramente a mensagem proposta e autorizar commit e publicação. Se o usuário corrigir a mensagem, lista ou destinos, atualize o manifesto e solicite confirmação da versão corrigida; isso substitui, não se soma, à confirmação anterior. Nunca invente ou altere a mensagem após ela ser aprovada.

### 4. Preparar e validar o commit

- Antes de staged, conferir novamente o estado do index. Se houver conteúdo staged não aprovado, parar e pedir orientação; não o desmarcar.
- Adicionar arquivos aprovados um por um/por caminho explícito, sem glob amplo e sem `git add -A`.
- Inspecionar `git diff --cached --name-status` e `git diff --cached` para confirmar que o conteúdo staged corresponde exatamente ao manifesto aprovado, sem segredos.
- Se aparecer arquivo extra, diff inesperado, conflito ou alteração concorrente, parar antes do commit e pedir nova aprovação.
- Criar o commit usando exatamente a mensagem confirmada. Use comando de terminal equivalente a `git commit -m "MENSAGEM_EXATA"`, preservando aspas/newlines conforme o texto literal.
- Confirmar o commit criado (`git log -1 --format=%H%n%s`) e verificar que a mensagem/arquivos correspondem à aprovação. Não criar segundo commit para corrigir mensagem sem nova autorização.

### 5. Publicar nos dois destinos

- Fazer push do mesmo commit para o remoto GitHub e o remoto Hugging Face, para as branches aprovadas. O push ao Hugging Face usa a autenticação local do token; nunca revelar o token.
- Não usar force push sem a permissão do usuário. Se houver rejeição por histórico divergente, conflito, falha de autenticação ou branch incorreta, parar; não rebasear, mesclar, sobrescrever ou mudar branch sem consentimento. Se o usuário permiir, faça o force, desde que você deixe explicito o motivo.
- Se um destino aceitar e o outro falhar, informar claramente o estado parcial e o hash do commit. Não afirmar sucesso total; não apagar/reverter o destino já atualizado. Perguntar antes de qualquer tentativa que altere o estado.
- Após cada push, verificar saída/status e, se disponível sem credenciais, confirmar referência/commit remoto. Relatar cada destino separadamente.

### 6. Relatar resultado

Informar: mensagem literal do commit, hash, arquivos publicados, branch e resultado individual do GitHub e do Hugging Face. Informar também arquivos não publicados e quaisquer falhas. Não incluir tokens nem dados secretos na resposta.

## Configuração e uso - para o usuário

1. Esta skill fica em `.opencode/skills/publicar-alteracoes/SKILL.md`.
2. O comando OpenCode fica em `.opencode/commands/publicar-alteracoes.md` (diretório `commands`, no plural).
3. Para autenticar Hugging Face, instale `huggingface_hub` no ambiente local e execute `hf auth login`; faça isso diretamente no terminal e não compartilhe o token. Verifique com `hf auth whoami`.
4. Configure os remotos GitHub e Hugging Face uma vez, ou autorize a skill a propor sua configuração quando invocada. O token não deve estar no remote URL.
5. No OpenCode, invoque `/publicar-alteracoes`; revise o manifesto, a sugestão de mensagem de commit e confirme ou corrija tudo na mesma resposta.
6. A skill não executa publicação na sua própria configuração nem apenas porque o token está autenticado.
