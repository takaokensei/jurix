// Read-only route smoke. Test history is isolated in a fresh browser profile.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const executablePath = [process.env.CHROME_BIN, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p => p && fs.existsSync(p));
const browser = await puppeteer.launch({ executablePath, headless: true });
const base = process.env.JURIX_LIVE_URL || 'http://127.0.0.1:8005';
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  for (const route of ['/assistente/', '/configuracoes/', '/normas/', '/pesquisa/', '/colecoes/', '/historico/']) {
    const response = await page.goto(base + route, { waitUntil: 'networkidle2' });
    assert.equal(response.status(), 200, route);
    assert.equal(await page.$eval('body', body => body.querySelectorAll('.jurix-sidebar').length), 1);
    const styles = await page.$eval('.workspace-brand', el => ({ size: getComputedStyle(el).fontSize, width: document.getElementById('sidebar').getBoundingClientRect().width }));
    assert.equal(styles.size, '17px', route);
    assert.equal(styles.width, 240, route);
    await page.evaluate(() => {
      window.JurixAnonymousHistory.ensureSession('local-sidebar-smoke', 'Teste de pesquisa jurídica');
      window.JurixAnonymousHistory.addMessage('local-sidebar-smoke', 'user', 'Consulta de animais');
    });
    if (route !== '/assistente/') {
      await page.evaluate(() => window.JurixSidebar.refresh());
      assert.ok(await page.$('.jurix-recent-chat'), route);
    } else {
      await page.reload({ waitUntil: 'networkidle2' });
      await page.waitForSelector('.chat-session-item');
      assert.ok(await page.$eval('#chat-sessions-list', el => el.textContent.includes('Teste de pesquisa jurídica')));
    }
    await page.click('[data-search-conversations]');
    await page.waitForSelector('.command-palette-item');
    assert.ok(await page.$eval('#command-palette-results', el => el.textContent.includes('Teste de pesquisa jurídica')), route);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.getElementById('command-palette-overlay').classList.contains('active'));
    await new Promise(resolve => setTimeout(resolve, 300));
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => document.getElementById('sidebar').getBoundingClientRect().width === 72);
    await new Promise(resolve => setTimeout(resolve, 250));
    assert.ok(await page.$eval('.workspace-nav-icon', el => el.getBoundingClientRect().width > 0), route);
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => document.getElementById('sidebar').getBoundingClientRect().width === 240);
    console.log(`PASS ${route}: unified shell, recent chats, search, collapse`);
  }
  for (const route of ['/assistente/', '/configuracoes/']) {
    for (const width of [360, 768]) {
      await page.setViewport({ width, height: 900 });
      await page.goto(base + route, { waitUntil: 'networkidle2' });
      await page.click('#toggle-sidebar');
      await page.waitForFunction(() => document.getElementById('sidebar').classList.contains('is-open'));
      assert.ok(await page.$eval('[data-search-conversations]', el => el.getBoundingClientRect().width >= 44));
      await page.keyboard.press('Escape');
      assert.equal(await page.$eval('#sidebar', el => el.classList.contains('is-open')), false);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      console.log(`PASS ${route} ${width}px: mobile menu, Escape, no horizontal overflow`);
    }
  }
} finally { await browser.close(); }
