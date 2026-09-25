# Plano de fechamento das lacunas PIBIC — Jurix 2.0

Este plano traduz o cronograma do projeto para tarefas verificáveis no repositório atual.

## Fase 1 — agora até outubro de 2026

**Corpus e base experimental**

- executar a ingestão via SAPL com alvo de 300 normas;
- selecionar 20 normas-piloto dentro do corpus;
- gerar `pilot.jsonl` com trilha de revisão;
- revisar o gold standard e congelar a versão usada nas métricas;
- registrar cobertura, duplicatas, falhas de PDF/OCR e normas sem texto integral.

**Aceite:** 300 normas ou um relatório explícito de cobertura inferior a 300; 20 pilotos identificados; origem SAPL registrada em cada item.

## Fase 2 — novembro/dezembro de 2026

**Avaliação do parser e eventos**

- anotar dispositivos no piloto;
- calcular Precision, Recall e F1 por tipo de dispositivo;
- anotar e avaliar `REVOGA`, `ALTERA`, `ADICIONA`, `REGULAMENTA`, `REFERENCIA`;
- registrar matriz de confusão e casos de erro.

**Aceite:** notebook/artefato reprodutível com métricas por classe e versão do corpus.

## Fase 3 — janeiro de 2027

**RAG temporal e auditável**

- consultas por data;
- linha do tempo normativa;
- citação obrigatória;
- logs de fontes e estado temporal;
- benchmark municipal como gate principal.

**Aceite:** respostas rastreáveis ao corpus municipal; benchmark federal não substitui o benchmark principal.

## Fase 4 — fevereiro/março de 2027

Comparar modelos locais e em nuvem com métricas de qualidade, latência, custo e privacidade; depois avaliar AirLLM em hardware restrito.

## Fase 5 — abril/maio de 2027

Construir dataset JSONL de pelo menos 500 exemplos revisados, executar LoRA/QLoRA e implementar a etapa de privacidade/anonimização prevista no plano.

## Fase 6 — junho/agosto de 2027

Preparar artigo, notebooks reproduzíveis, documentação pública, demonstração e relatório final PIBIC/PROPESQ.

## Métricas mínimas

Além das métricas do parser/eventos, registrar Recall@k/MRR para recuperação, precisão de citação, groundedness, correção temporal, latência e taxa de respostas insuficientes corretamente recusadas.

## Regra de escopo

O produto e o experimento principal continuam focados em **legislação municipal de Natal/RN**. O arquivo `README` e os componentes de UI não devem sugerir que o corpus atual contém jurisprudência do STF ou um conjunto federal que não tenha sido ingerido.
