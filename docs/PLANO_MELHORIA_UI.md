# 🎨 PLANO DE MELHORIA UI/UX - JURIX
## Correções Críticas e Implementações Prioritárias

---

## 🚨 **PROBLEMAS CRÍTICOS IDENTIFICADOS**

### 1. **Skip Link Mal Posicionado**
- **Problema**: Skip link aparece dentro da sidebar, visível e com diagramação quebrada
- **Causa**: Está dentro do `<body>` mas a sidebar está por cima
- **Solução**: Mover skip-link para antes do workspace, garantir z-index > sidebar, adicionar `clip-path` ou `clip` para ocultar completamente até o foco

### 2. **Contraste Sidebar (WCAG Violation)**
- **Problema**: Texto preto/escuro no fundo azul escuro (`--color-gray-900`)
- **Causa**: `sidebar-header h1` não tem `color` definida, herdando do body
- **Solução**: Definir `color: var(--color-text-inverse)` explicitamente no `.sidebar-header h1`

### 3. **Inconsistências Visuais**
- Sidebar usa `gray-900` mas deveria ter texto branco/claro
- Títulos de seção (`h3`) usam `gray-400` que pode não ter contraste suficiente
- Falta padronização de espaçamento e hierarquia tipográfica

---

## 🌓 **FEATURE: DARK MODE Toggle**

### Especificações:
1. **Toggle Switch** na sidebar (abaixo de Sistema)
2. **Persistência**: `localStorage.getItem('jurix-theme')`
3. **Tipografia Ajustada**: 
   - Dark: texto claro (`gray-50` a `gray-300`)
   - Light: texto escuro (`gray-700` a `gray-900`)
4. **Variáveis CSS**: `[data-theme="dark"]` com `--color-*` sobrescritas
5. **Transição suave**: `transition: background-color 300ms, color 300ms`

### Design do Toggle:
- **Swiss minimal**: Switch horizontal (iOS style) ou toggle vertical (Material)
- **Ícones**: ☀️ (light) / 🌙 (dark)
- **Posição**: Sidebar footer, antes das estatísticas

---

## 🔍 **MELHORIAS DE BUSCA (UX)**

### Estado Atual:
- Busca simples por ementa/número/tipo
- Sem filtros avançados

### Melhorias Planejadas:
1. **Autocomplete/Typeahead**: Sugestões ao digitar
2. **Filtros visuais**: 
   - Por status (Consolidado, Em Revisão)
   - Por período (slider de anos)
   - Por tipo (Lei, Decreto, etc.)
3. **Resultados destacados**: Match highlighting no texto
4. **Ordenação**: Por relevância, data, número

---

## ✅ **CHECKLIST SWISS DESIGN**

### Tipografia:
- [ ] Hierarquia clara (tamanho + peso)
- [ ] Leading generoso (1.6-1.8)
- [ ] Sem fontes decorativas (apenas Inter + JetBrains Mono)

### Cor:
- [ ] Paleta monocromática + 1 acento (Azul Jurix)
- [ ] Contraste WCAG AA mínimo (4.5:1)
- [ ] Cor funcional, não decorativa

### Espaçamento:
- [ ] Grid de 8px consistente
- [ ] Espaço branco estratégico (32px+ entre seções)
- [ ] Max-width para leitura (800px texto, 1200px layout)

### Geometria:
- [ ] Border-radius mínimo (6px primário, 12px secundário)
- [ ] Sombras sutis (3 níveis)
- [ ] Sem gradientes decorativos

---

## 📋 **ORDEM DE IMPLEMENTAÇÃO**

### Fase 1: Correções Críticas (Prioridade Máxima)
1. ✅ Fix skip-link (reposicionar, ocultar corretamente)
2. ✅ Fix contraste sidebar (texto branco no h1)
3. ✅ Padronizar cores da sidebar (texto inverso consistente)

### Fase 2: Dark Mode (Alta Prioridade)
1. ✅ Criar variáveis CSS para dark mode
2. ✅ Implementar toggle na sidebar
3. ✅ Persistência localStorage
4. ✅ Ajustar tipografia para dark/light

### Fase 3: Melhorias de Consistência (Média Prioridade)
1. ✅ Revisar todos os componentes seguindo Swiss Design
2. ✅ Padronizar espaçamentos
3. ✅ Validar contraste em todos elementos

### Fase 4: Busca Avançada (Baixa Prioridade - Futuro)
1. ⏳ Autocomplete
2. ⏳ Filtros visuais
3. ⏳ Resultados destacados

---

## 🎯 **MÉTRICAS DE SUCESSO**

- [ ] Skip link completamente oculto até Tab (não visível na sidebar)
- [ ] Contraste sidebar: mínimo 7:1 (WCAG AAA)
- [ ] Dark mode funcional em todas páginas
- [ ] Tipografia ajusta automaticamente no modo escuro
- [ ] 100% de consistência visual (Swiss Design audit)

---

## 📝 **NOTAS TÉCNICAS**

### CSS Variables para Dark Mode:
```css
[data-theme="dark"] {
    --color-bg-primary: #0f172a;
    --color-bg-secondary: #1e293b;
    --color-text: #f1f5f9;
    --color-text-secondary: #cbd5e1;
    /* ... */
}
```

### JavaScript Toggle:
```javascript
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const newTheme = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('jurix-theme', newTheme);
}
```

---

**Data de criação**: 2025-01-XX
**Status**: Em execução
**Responsável**: Senior Frontend Engineer

