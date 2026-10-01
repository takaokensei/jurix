# Runbook — reparação de colofões OCR

## Escopo e segurança

O comando `repair_legal_colophons` propõe reparos somente quando o último artigo da versão
segmentada coincide com o último artigo analisado do OCR e o texto absorveu assinatura ou
metadados editoriais. Ele nunca usa a data de sessão como vigência. O dry-run é somente leitura
no corpus; `--manifest-out` grava apenas o manifesto solicitado pelo operador.

Não execute `--apply` em desenvolvimento/produção como parte de testes ou inicialização. A revisão
jurídica dos casos e a janela operacional continuam obrigatórias; este runbook não declara os sete
casos anteriores como reparados.

## 1. Preparar manifesto

```powershell
.venv/Scripts/python.exe manage.py repair_legal_colophons --all --manifest-out .\repair-plan.json
```

Guarde o manifesto em armazenamento de operação aprovado. Ele contém IDs, hashes SHA-256 de
origem/artigo, identificação do SAPL, datas SAPL já registradas, datas extraídas do OCR e uma
indicação de divergência. Não contém o texto integral do OCR.

Revise cada linha com responsável jurídico: compare o PDF oficial do SAPL com a proposta OCR;
confirme artigo, redação, data de publicação e se a cláusula de vigência realmente diz “na data de
sua publicação”. Uma divergência de publicação bloqueia aplicação automática até decisão explícita.

## 2. Backup e aprovação

1. Faça backup consistente do banco e dos documentos associados seguindo a política operacional.
2. Verifique a integridade do backup e registre operador, horário e identificador do snapshot.
3. Um segundo revisor aprove exatamente o manifesto, fora deste arquivo. Calcule SHA-256:

```powershell
Get-FileHash .\repair-plan.json -Algorithm SHA256
```

O valor da flag esperado pelo comando é o campo `sha256` dentro do JSON (digest canônico dos dados),
não o hash binário do arquivo. Registre ambos no ticket. Não altere o manifesto depois da revisão.

## 3. Aplicação controlada

Execute somente após janela e aprovação operacional próprias:

```powershell
.venv/Scripts/python.exe manage.py repair_legal_colophons --all --apply `
  --approved-manifest .\repair-plan.json `
  --expected-manifest-sha256 <sha256-canonico-do-manifesto> `
  --backup-verified
```

O comando recalcula a proposta antes de cada gravação, aborta se o estado estiver stale, mantém IDs
dos dispositivos/eventos, invalida embeddings afetados e incrementa o cache somente após sucesso.
Não reexecute com um manifesto antigo. Prepare outro dry-run e obtenha outra aprovação.

## 4. Verificação e reversão

- Rode novo dry-run para o mesmo escopo: a contagem corrigível deve ser zero, salvo novos dados.
- Confira integridade do corpus, links de eventos, texto consolidado, datas e embeddings pendentes.
- Se algo divergir, interrompa ingestão/consumidores conforme procedimento operacional e restaure o
  snapshot validado. Não use SQL genérico para inverter texto/datas: a reversão exige snapshot ou
  plano compensatório revisado, pois embeddings/cache e eventos dependem da revisão do dispositivo.
- Registre manifesto, seu digest, backup, operador, revisor, comandos, saída sanitizada e validações.

## Limites conhecidos

- A data de publicação “SAPL” no manifesto é a já armazenada pelo Jurix; não há consulta de rede ao
  SAPL durante o dry-run. OCR e dado persistido divergentes são destacados, nunca reconciliados
  silenciosamente.
- A cláusula de vigência e as datas precisam de conferência jurídica humana. O comando não prova
  que a cópia local é a publicação oficial vigente.
- Os testes do comando usam somente normas sintéticas no banco temporário do pytest.
