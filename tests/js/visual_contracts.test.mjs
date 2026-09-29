import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const root = new URL('../../', import.meta.url);

function relativeLuminance(hex) {
  const channels = hex.match(/[a-f\d]{2}/gi).map((channel) => parseInt(channel, 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrastRatio(foreground, background) {
  const values = [relativeLuminance(foreground), relativeLuminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test('muted UI text meets WCAG AA contrast on all primary dark surfaces', async () => {
  const css = await readFile(new URL('src/apps/core/static/css/jurix-figma.css', root), 'utf8');
  const foreground = css.match(/--figma-text-dim:\s*(#[a-f\d]{6})/i)?.[1];
  assert.ok(foreground, 'The dim-text design token must be defined as a six-digit color');

  for (const background of ['#081220', '#111827', '#0F172A']) {
    const ratio = contrastRatio(foreground, background);
    assert.ok(ratio >= 4.5, `${foreground} on ${background} is ${ratio.toFixed(2)}:1; normal text requires 4.5:1`);
  }
});
