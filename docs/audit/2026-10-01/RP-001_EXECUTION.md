# RP-001 — atualização Django: execução interrompida para revisão

Data: 01/10/2026. Implementação autorizada pelo usuário após a criação do plano. Branch `ui/pro-polish`, HEAD `1895d3f`; nenhum commit, push, merge ou troca de branch.

## Mudança preparada

- `C:/Jurix/requirements.txt`: Django 5.0.9 → 5.2.17.
- `C:/Jurix/README.md`: três referências à versão atualizadas para 5.2 LTS, preservando o estilo.
- `C:/Jurix/src/tests/test_dependencies.py`: dois testes de pin LTS/piso de patch e correspondência entre Django instalado e declarado.

Versão confirmada na [tabela oficial](https://www.djangoproject.com/download/); [release notes 5.2](https://docs.djangoproject.com/en/5.2/releases/5.2/) confirmam suporte a Python 3.12.

## Execuções efetivas

- Baseline Python antes da mudança: **699 passed, 6 skipped, 7 warnings**, 47,57 s.
- Baseline JavaScript: **152 testes aprovados**, exit code 0. Não foi repetido depois da falha Python.
- Baseline direcionado dependências/deploy/headers/settings: **18 passed**, 6,54 s.
- `pip install --dry-run Django==5.2.17`: resolver aprovou; dependências necessárias já satisfeitas.
- Django 5.2.17 instalado com `--no-deps --target` em diretório temporário exclusivo. Testes executados com PYTHONPATH apontando para esse diretório; `.venv` ativo não atualizado.
- Suite Python com Django 5.2.17 isolado: **700 passed, 6 skipped, 1 failed, 7 warnings**, 53,52 s.
- `manage.py check` com Django isolado: aprovado.
- `manage.py makemigrations --check --dry-run` com Django isolado: nenhuma alteração detectada. Nenhuma migration aplicada.
- Ruff lint e format-check somente em `test_dependencies.py`: aprovados; `git diff --check`: aprovado.
- `pip check` do ambiente ativo original: sem dependências quebradas. Não é SCA. Scanner `pip_audit` não instalado; SCA não executado nem novas ferramentas instaladas.

## Resultado da validação

Na primeira execução da suíte com o Django isolado, `C:/Jurix/src/tests/test_attachment_service.py:201`, `test_resource_limits_enforced_in_process` falhou: o subprocesso declarou `CPU_LIMIT_INSTALLED`, executou o cálculo e terminou com returncode **20** em vez de ser interrompido pelo limite de CPU. Essa primeira execução foi simultânea à suíte Node com Chromium.

Sem alterar código ou teste de contenção, uma execução isolada do teste passou (**1 passed**, 5,47 s) e uma segunda suíte Python completa, sem Chromium concorrente, passou (**701 passed, 6 skipped, 7 warnings**, 62,20 s). A causa da primeira falha **não foi provada**; a diferença de concorrência é contexto, não diagnóstico. Nenhum teste foi enfraquecido, removido ou marcado skip; o controle de recursos não foi alterado.

RP-001 passou o gate de suíte na repetição. Não foi identificada falha estável no limite de CPU; a primeira execução falha fica registrada para acompanhamento em RP-043. Não houve alteração de contenção.

## Estado preservado

O ambiente isolado usou Django **5.2.17**. O ambiente virtual principal continua em Django **5.0.9** até a atualização e reinicialização segura do servidor local. O novo teste de correspondência de pin passou na suíte isolada.

`.env`, banco real, documentos/normas, configs locais e migrations intactos. Os hashes SHA256 de `jurix-rag.js`, `chat.security.test.mjs` e `GOAL.md` permaneceram iguais aos registrados antes da implementação. Apenas README, requirements e teste de dependências foram modificados por RP-001; arquivos de auditoria novos permanecem não rastreados.
