# Plano de Melhoria UI/UX - Chatbot Jurix
## Baseado em Swiss Design System

### 📐 Análise do Problema Atual

**Problemas Identificados:**
1. Interface muito vazia, elementos concentrados no centro
2. Sidebar pequena e subutilizada
3. Caixa de input com design básico (quadrado cinza)
4. Command palette não executa comandos ao clicar
5. Emojis no command palette (inconsistente com profissionalismo)

### 🎯 Objetivos - Swiss Design Principles

1. **Hierarquia Visual Clara**
   - Aumentar largura da sidebar (280px → 320px)
   - Melhorar espaçamento vertical (grid de 8px)
   - Expandir área de conteúdo do chat

2. **Tipografia como Hierarquia**
   - Melhorar contraste e tamanhos
   - Usar JetBrains Mono para código/comandos

3. **Espaço em Branco (Whitespace)**
   - Aumentar padding/margin no welcome state
   - Melhorar respiração entre elementos
   - Reduzir concentração no centro

4. **Funcionalidade Purificada**
   - Input elegante estilo Gemini
   - SVG icons consistentes (sem emojis)
   - Command palette funcional (clique + Enter)

### 🏗️ Estrutura Proposta

#### Layout
```
┌─────────────────────────────────────────────┐
│ Sidebar (320px) │ Chat Area (flex-1)        │
│                 │                            │
│ - Logo          │ Top Bar                    │
│ - Sections      │ Messages Container         │
│ - Stats         │   (expanded, centered)     │
│                 │ Input Area (Gemini-style)  │
└─────────────────────────────────────────────┘
```

#### Sidebar (320px width)
- Mais espaço para navegação
- Seções mais espaçadas
- Stats card mais proeminente

#### Chat Area
- Welcome state: conteúdo expandido horizontalmente
- Mensagens: max-width 900px (centralizado)
- Input: estilo Gemini (elegante, arredondado)

#### Command Palette
- SVG icons ao invés de emojis
- Clique executa comando imediatamente
- Visual consistente com tema

### 🎨 Design Tokens (Swiss Design)

- **Espaçamento**: Grid de 8px
- **Largura Sidebar**: 320px (era 280px)
- **Max-width Chat**: 900px (centralizado)
- **Border Radius**: 16px (input), 12px (cards)
- **Shadows**: Sutil, hierárquico

