import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../../', import.meta.url);
const read = (path) => readFile(new URL(path, root), 'utf8');

function contrastRatio(foreground, background) {
  const luminance = (hex) => {
    const channels = hex.match(/[a-f\d]{2}/gi).map((channel) => parseInt(channel, 16) / 255);
    const linear = channels.map((channel) => channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4);
    return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  };
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test('both workspace shells load semantic tokens before component styles without remote fonts', async () => {
  const [assistant, workspace] = await Promise.all([
    read('src/apps/legislation/templates/legislation/chatbot.html'),
    read('src/apps/legislation/templates/legislation/workspace/base.html'),
  ]);

  for (const template of [assistant, workspace]) {
    assert.doesNotMatch(template, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
    const figma = template.indexOf("'css/jurix-figma.css'");
    const tokens = template.indexOf("'css/jurix-tokens.css'");
    const components = template.indexOf("'css/workspace.css'");
    assert.ok(figma >= 0 && tokens > figma && components > tokens);
  }
});

test('semantic light/dark tokens preserve legacy aliases and use system font stacks', async () => {
  const css = await read('src/apps/core/static/css/jurix-tokens.css');
  for (const token of [
    '--jurix-canvas', '--jurix-surface', '--jurix-text', '--jurix-action',
    '--jurix-type-body', '--jurix-space-4', '--jurix-radius-md',
    '--jurix-motion-fast', '--jurix-focus',
  ]) assert.match(css, new RegExp(`${token}:`));

  assert.match(css, /:root\[data-theme="light"\][\s\S]*?--jurix-canvas:\s*#F7F9FC/);
  assert.match(css, /--figma-bg-root:\s*var\(--jurix-canvas\)/);
  assert.match(css, /--figma-blue-primary:\s*var\(--jurix-action\)/);
  assert.match(css, /--font-sans:\s*system-ui/);
});

test('workspace typography and controls use the shared readable scale', async () => {
  const css = await read('src/apps/core/static/css/workspace.css');
  assert.match(css, /\.workspace-page\s*\{[^}]*font-size:\s*var\(--jurix-type-body(?:,\s*1rem)?\)[^}]*line-height:\s*var\(--jurix-leading-body(?:,\s*1\.65)?\)/);
  assert.match(css, /\.workspace-page-header h1\s*\{[^}]*font-family:\s*var\(--font-sans\)[^}]*font-size:\s*var\(--jurix-type-title(?:,\s*clamp\(1\.5rem,\s*2\.5vw,\s*2rem\))?\)/);
  assert.match(css, /\.workspace-muted\s*\{[^}]*font-size:\s*var\(--jurix-type-caption(?:,\s*\.8125rem)?\)/);
  assert.match(css, /\.workspace-button\s*\{[^}]*min-height:\s*44px/);
  assert.match(css, /\.workspace-nav-item\s*\{[^}]*min-height:\s*44px/);
});

test('semantic text, link, status, and action colors meet WCAG AA on their theme surfaces', async () => {
  const css = await read('src/apps/core/static/css/jurix-tokens.css');
  const dark = css.match(/:root\s*\{([^}]+)\}/)?.[1];
  const light = css.match(/:root\[data-theme="light"\]\s*\{([^}]+)\}/)?.[1];
  assert.ok(dark && light, 'Both semantic themes must define token sets');
  const value = (block, token) => block.match(new RegExp(`${token}:\\s*(#[a-f\\d]{6})`, 'i'))?.[1];

  for (const [tokens, backgrounds] of [[dark, ['#081220', '#111827', '#1E293B']], [light, ['#F7F9FC', '#FFFFFF', '#EAF0F8']]]) {
    for (const token of ['--jurix-text', '--jurix-text-body', '--jurix-text-muted', '--jurix-link']) {
      const foreground = value(tokens, token);
      assert.ok(foreground, `${token} must be a concrete semantic color`);
      for (const background of backgrounds) assert.ok(contrastRatio(foreground, background) >= 4.5, `${token} on ${background} must meet 4.5:1`);
    }
    const action = value(tokens, '--jurix-action');
    assert.ok(contrastRatio(value(tokens, '--jurix-on-action'), action) >= 4.5, 'Action label must meet 4.5:1');
  }
});
