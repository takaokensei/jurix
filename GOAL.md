# META — JURIX FRONTEND PRO SaaS

Transforme o frontend atual do `takaokensei/jurix` em um produto SaaS jurídico premium, moderno, consistente e altamente polido.

O objetivo NÃO é reescrever a aplicação nem trocar a stack. O objetivo é pegar o frontend existente e elevá-lo progressivamente até um nível visual e de UX comparável a um SaaS comercial cuidadosamente produzido.

O agente deve **editar o código e validar o resultado diretamente no navegador**. Não basta sugerir melhorias ou produzir relatórios.

---

# 0. PRINCÍPIOS ABSOLUTOS

* Preserve Django Templates + JavaScript modular.
* Não introduza React/Vite/SPA sem necessidade real.
* Não altere backend, models, RAG, Celery, tasks ou contratos de API.
* Não substitua o design system existente por outro.
* Preserve CSP, sanitização, segurança e acessibilidade existentes.
* Preserve funcionalidades existentes.
* Priorize qualidade percebida, clareza e consistência.
* Não faça redesign por preferência pessoal sem validar visualmente o resultado.
* Toda mudança deve ser demonstrada funcionando no navegador.

A pergunta central durante todo o trabalho é:

> "Isso parece um produto SaaS profissional ou apenas uma aplicação funcional?"

---

# 1. PROTOCOLO DE LONGA DURAÇÃO

## 1.1 Bootstrap seguro

O repositório pode ter sido obtido por Codeload.

Inicialmente:

1. baixar/usar o projeto;
2. verificar se existe `.git`;
3. caso não exista, executar:

   ```bash
   git init
   git branch -M ui/pro-polish
   git add .
   git commit -m "chore(ui): baseline before frontend polish"
   ```
4. se já existir Git, criar:

   ```bash
   git switch -c ui/pro-polish
   ```

   ou equivalente sem destruir trabalho existente.

Nunca trabalhar sem um ponto de rollback.

## 1.2 Descoberta obrigatória

Antes de alterar qualquer frontend:

* ler `README.md`;
* ler `docs/frontend/`;
* ler `docs/current-status.md` quando relevante;
* ler `docs/archive/prompt_master.md`;
* localizar os principais templates, CSS e JS;
* descobrir as rotas realmente existentes.

Primeira tentativa:

```bash
python manage.py show_urls
```

Se esse comando não existir, descobrir as URLs por inspeção de `urls.py`/rotas Django.

**Nunca assumir uma URL apenas porque apareceu em documentação antiga.**

Registrar as rotas reais utilizadas durante os testes em:

```text
FRONTEND_LOG.md
```

## 1.3 Baseline técnico

Antes de editar:

* executar a suíte de testes existente;
* executar testes JavaScript existentes;
* executar lint/format/checks relevantes;
* registrar resultados;
* iniciar o ambiente local;
* confirmar qual navegador/runner está sendo usado.

Salvar no log:

```text
BASELINE
- Python tests:
- JavaScript tests:
- lint:
- design/token checks:
- browser:
- viewport:
- known environment limitations:
```

Se algum teste já falhar antes das alterações, registrar como **baseline failure** e não tratá-lo automaticamente como regressão.

---

# 2. MEMÓRIA PERSISTENTE

Criar e manter:

```text
FRONTEND_LOG.md
```

Esse arquivo é obrigatório e deve sobreviver a compactação de contexto.

No início de cada ciclo:

1. reler `FRONTEND_LOG.md`;
2. identificar o último trabalho concluído;
3. verificar o backlog restante;
4. escolher apenas o próximo foco.

Depois de cada ciclo registrar:

```text
## Cycle N — DATA

Area:
Goal:
Observed problems:
Changes made:
Browser validation:
Tests:
Console:
Responsive validation:
Visual score:
Regressions:
Next action:
```

Nunca refazer trabalho já concluído apenas porque o contexto anterior foi perdido.

Depois de uma compactação de contexto:

> reler `FRONTEND_LOG.md` ANTES de modificar qualquer arquivo.

---

# 3. BASELINE VISUAL

Antes de mudanças importantes, capturar screenshots das principais telas.

Usar os mesmos viewports antes e depois:

### Desktop

* 1440×900
* 1280×800

### Mobile

* 390×844

Priorizar as rotas realmente existentes, incluindo:

* assistente/chat;
* pesquisa;
* normas;
* detalhe de norma;
* comparação;
* árvore;
* coleções;
* histórico;
* configurações.

Salvar:

```text
docs/ui-audit/before/
docs/ui-audit/after/
```

Manter os nomes dos screenshots idênticos entre `before` e `after`.

Quando o projeto suportar múltiplos temas, validar cada tema suportado. Não inventar suporte a light mode apenas para cumprir a auditoria.

---

# 4. AMBIENTE E DADOS

O agente não deve ficar preso tentando levantar infraestrutura indefinidamente.

Se uma rota depender de:

* dados de banco;
* norma específica;
* Ollama;
* SAPL;
* serviços externos;
* autenticação;
* sessões pré-existentes;

fazer até **2 tentativas razoáveis** para disponibilizar o ambiente.

Se continuar indisponível:

1. registrar no `FRONTEND_LOG.md`;
2. criar fixture/seed/mock **somente local e temporário**, quando isso for seguro;
3. nunca commitar credenciais, fixtures de teste descartáveis ou hacks de ambiente;
4. continuar auditando o restante do frontend.

O ambiente de teste não deve bloquear todo o projeto por causa de uma dependência isolada.

---

# 5. LOOP DE EXECUÇÃO

O agente deve trabalhar continuamente neste ciclo:

```text
AUDITAR
↓
ESCOLHER 1 FOCO
↓
IMPLEMENTAR
↓
RODAR TESTES
↓
ABRIR NO BROWSER
↓
INTERAGIR
↓
INSPECIONAR RESULTADO
↓
CORRIGIR
↓
SCREENSHOT
↓
COMPARAR
↓
COMMIT
↓
REGISTRAR NO FRONTEND_LOG.md
↓
PRÓXIMO FOCO
```

Cada ciclo deve ter escopo pequeno.

Evite alterações gigantes que misturem dez áreas diferentes.

---

# 6. FASEAMENTO

Não ficar duas horas refinando a mesma tela.

Executar nesta ordem.

## FASE A — Shell e sistema visual

Prioridade:

* sidebar;
* topbar;
* navigation;
* command palette;
* logo;
* tokens;
* tipografia;
* superfícies;
* bordas;
* espaçamento;
* foco;
* responsividade global.

Objetivo:

Criar uma linguagem visual forte e consistente para o resto do produto.

Máximo recomendado:

**3 ciclos principais antes de avançar.**

---

## FASE B — Assistente

Testar o fluxo completo:

1. abrir assistente;
2. nova pesquisa;
3. escrever pergunta;
4. enviar;
5. loading;
6. streaming;
7. resposta final;
8. markdown;
9. fontes;
10. copiar resposta;
11. histórico;
12. trocar conversa;
13. excluir conversa;
14. reload/F5;
15. erro/retry;
16. offline quando possível.

Polir especialmente:

* composer;
* textarea;
* send button;
* estados de processamento;
* mensagens;
* fontes;
* ações de mensagem;
* sidebar de histórico;
* welcome state;
* empty state.

---

## FASE C — Normas

Validar:

* `/normas/`;
* detalhe;
* dispositivos;
* timeline;
* compare;
* tree;
* filtros;
* paginação;
* links externos;
* estados vazios;
* loading;
* erro.

Polir especialmente:

* cards;
* metadata;
* hierarquia documental;
* leitura jurídica longa;
* marcadores de alteração;
* timeline;
* comparação;
* árvore normativa.

A interface deve parecer uma ferramenta profissional de pesquisa jurídica, não uma listagem administrativa.

---

## FASE D — Workspace restante

Polir:

* pesquisa;
* coleções;
* histórico;
* configurações;
* dialogs;
* forms;
* selects;
* mensagens;
* estados vazios;
* feedback de ações.

---

## FASE E — Passe final

Fazer uma nova auditoria completa:

* desktop;
* mobile;
* teclado;
* foco;
* console;
* acessibilidade;
* performance;
* loading;
* errors;
* reduced motion;
* screenshots before/after.

Não criar novas funcionalidades nessa fase.

Somente corrigir inconsistências e acabamento.

---

# 7. MOTION DESIGN

As animações devem comunicar estado e melhorar percepção de qualidade.

Priorizar:

* opacity;
* transform;
* pequenas mudanças de escala;
* translate;
* abertura/fechamento de drawers;
* dialogs;
* hover;
* focus;
* loading;
* toast;
* expansão de conteúdo.

Evitar animar propriedades pesadas que gerem layout thrashing.

Sempre que possível:

```css
transform
opacity
```

Usar tokens centralizados para duração/easing.

Exemplo conceitual:

```css
--motion-fast
--motion-normal
--motion-slow
--ease-standard
--ease-emphasized
```

Não espalhar valores arbitrários de easing e duração por dezenas de arquivos.

Padrão preferencial:

* microinterações: ~120–180ms;
* componentes: ~180–250ms;
* transições maiores: ~250–350ms.

Evitar:

* bounce excessivo;
* elasticidade exagerada;
* parallax;
* animações constantes;
* efeitos que atrasem leitura;
* glow permanente;
* efeitos "AI generated" chamativos.

Obrigatório:

```css
@media (prefers-reduced-motion: reduce)
```

Nesse modo, minimizar ou remover motion não essencial.

---

# 8. QUALIDADE VISUAL

Avaliar continuamente estes eixos:

### 1. Hierarquia e tipografia

* títulos;
* subtítulos;
* body;
* metadata;
* contraste;
* ritmo vertical.

### 2. Consistência

* botões;
* inputs;
* cards;
* radius;
* borders;
* icons;
* estados.

### 3. Espaçamento

* alinhamento;
* grid;
* gutters;
* densidade;
* whitespace.

### 4. Estados

* loading;
* empty;
* error;
* success;
* disabled;
* hover;
* focus;
* selected.

### 5. UX

* affordance;
* feedback;
* clareza;
* previsibilidade;
* quantidade de cliques;
* navegação.

### 6. Responsividade

* 390px;
* 768px;
* 1024px;
* desktop largo.

### 7. Motion

* naturalidade;
* duração;
* continuidade;
* ausência de jank.

### 8. Acabamento

* pequenos desalinhamentos;
* ícones;
* microcopy;
* bordas;
* sombras;
* truncamento;
* detalhes.

---

# 9. RUBRICA 0–10

Após cada fase, atribuir nota interna:

```text
Hierarchy / Typography:
Component consistency:
Spacing / Layout:
States:
UX:
Chat:
Responsive:
Accessibility:
Performance:
Motion:
Polish:
```

Usar média apenas como indicador auxiliar.

**Não usar média para esconder uma área ruim.**

Uma área abaixo de 9 continua aberta.

Critério de conclusão da fase:

* nenhum eixo crítico < 9;
* pelo menos duas rodadas consecutivas mantendo o nível;
* testes verdes;
* sem novos erros de console;
* sem overflow horizontal em 390px;
* sem regressões funcionais;
* acessibilidade sem problemas graves.

Atingir 9 não significa parar imediatamente: fazer mais uma revisão visual procurando problemas subjetivamente óbvios que a rubrica não capturou.

---

# 10. BROWSER QA OBRIGATÓRIO

Para cada fluxo modificado:

## Console

Verificar:

* JavaScript errors;
* uncaught exceptions;
* failed requests inesperadas;
* warnings relevantes;
* assets 404.

Não considerar a página "pronta" se houver erro de console causado pela alteração.

## Layout

Verificar:

* overflow;
* elementos cortados;
* texto sobreposto;
* botões fora do viewport;
* sticky/fixed incorreto;
* z-index;
* scroll containers;
* largura máxima.

## Interação

Testar realmente:

* click;
* typing;
* submit;
* keyboard;
* Escape;
* focus;
* hover quando relevante;
* dialogs;
* drawers;
* navigation.

Não confiar apenas em inspeção estática do HTML.

---

# 11. ACCESSIBILITY

Validar, quando disponível:

* keyboard navigation;
* foco visível;
* labels;
* buttons sem texto quando houver aria-label;
* dialogs;
* focus trap;
* retorno de foco;
* contraste;
* reduced motion;
* touch targets.

Executar axe ou ferramenta equivalente quando disponível.

Corrigir problemas graves encontrados.

Não sacrificar acessibilidade apenas para obter aparência melhor.

---

# 12. PERFORMANCE

Evitar:

* listeners duplicados;
* renders desnecessários;
* polling desnecessário;
* animações pesadas;
* manipulação excessiva do DOM;
* imagens desnecessariamente grandes;
* CSS duplicado.

Não transformar microinterações em fonte de jank.

Quando possível, observar Lighthouse/Performance DevTools e corrigir problemas diretamente causados pelo frontend.

---

# 13. DESIGN SYSTEM

Antes de criar qualquer novo estilo:

1. procurar token existente;
2. procurar componente semelhante;
3. procurar CSS existente;
4. reutilizar quando possível.

Não criar:

```css
#123456
```

aleatoriamente quando já existe token equivalente.

Não duplicar:

* button styles;
* card styles;
* modal styles;
* input styles;
* animation rules.

O design system existente deve ficar mais forte ao final, não mais fragmentado.

---

# 14. REGRESSÃO

Após cada ciclo:

```bash
git diff --check
```

Rodar testes relevantes.

Se houver regressão:

1. identificar causa;
2. tentar correção;
3. se a solução continuar piorando o produto, usar:

   ```bash
   git revert
   ```

   ou restaurar o commit do ciclo;
4. registrar a tentativa no log;
5. tentar outra abordagem.

Nunca acumular uma sequência de mudanças apenas porque "talvez depois dê para arrumar".

---

# 15. COMMITS

Cada ciclo relevante deve terminar com commit.

Formato:

```text
ui(shell): refine workspace navigation
ui(chat): polish composer states
ui(normas): improve document hierarchy
ui(motion): standardize interaction transitions
ui(a11y): fix dialog focus handling
```

Commits devem ser pequenos o suficiente para reverter uma área sem destruir o resto.

---

# 16. O QUE NÃO FAZER

Não:

* reescrever o projeto;
* migrar para React apenas por preferência;
* modificar backend sem necessidade;
* remover testes para fazer CI passar;
* esconder erros;
* desabilitar CSP;
* diminuir validações de segurança;
* adicionar dependências pesadas sem justificativa;
* criar mock permanente para mascarar infraestrutura quebrada;
* produzir apenas screenshots bonitas sem funcionalidade;
* fazer mudanças gigantes sem validação intermediária;
* parar porque "já está bom".

---

# 17. CRITÉRIO FINAL DE CONCLUSÃO

O trabalho termina somente quando:

### Funcionalidade

* fluxos principais funcionam;
* navegação funciona;
* chat funciona;
* normas funcionam;
* pesquisa funciona;
* histórico/coleções/configurações funcionam.

### Visual

* hierarquia clara;
* aparência SaaS;
* componentes coerentes;
* espaçamento refinado;
* dark mode consistente;
* sem elementos visualmente "baratos" ou improvisados.

### Motion

* microinterações presentes onde agregam;
* sem exagero;
* sem jank;
* reduced-motion respeitado.

### QA

* sem erros de console introduzidos;
* sem overflow em 390px;
* testes existentes passando;
* `git diff --check` passando;
* axe/Lighthouse sem problemas graves, quando disponíveis.

### Processo

* `FRONTEND_LOG.md` atualizado;
* screenshots before/after;
* commits organizados;
* nenhuma alteração experimental abandonada no código.

---

# 18. COMPORTAMENTO DO AGENTE

Quando terminar uma tarefa, NÃO pergunte o que fazer em seguida.

Consulte:

1. `FRONTEND_LOG.md`;
2. backlog restante;
3. estado atual no navegador;
4. rubrica.

Então escolha automaticamente o próximo maior problema de frontend e continue.

Não fique repetindo melhorias cosméticas na mesma área quando outra fase ainda estiver claramente abaixo do padrão.

Priorize sempre:

```text
BUG
>
REGRESSÃO
>
UX
>
HIERARQUIA
>
CONSISTÊNCIA
>
ESTADOS
>
RESPONSIVIDADE
>
MOTION
>
MICRO-POLISH
```

Continue iterando até atingir os critérios objetivos de conclusão.
