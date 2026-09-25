# Checklist UX para release

## Navegação

- [ ] foco visível;
- [ ] tab order lógico;
- [ ] command palette fechável pelo teclado;
- [ ] navegação sem mouse.

## Chat

- [ ] pergunta longa não quebra layout;
- [ ] resposta streaming tem estado provisório;
- [ ] erro de Ollama é compreensível;
- [ ] fontes são distinguíveis da resposta;
- [ ] fallback de grounding explica falta de evidência.

## Estados de dependência

- [ ] Redis indisponível;
- [ ] Ollama indisponível;
- [ ] SAPL indisponível;
- [ ] timeout;
- [ ] 429;
- [ ] 500;
- [ ] sessão expirada.

## Acessibilidade

A implementação não deve declarar conformidade WCAG sem teste automatizado e
manual documentado. A suíte deve incluir teclado, leitor de tela e foco.

## Mobile

Testar largura reduzida, conteúdo jurídico extenso, tabelas, fontes maiores e
scroll da área de chat.
