// Song-select test: run after (cd web2 && python3 -m http.server 8767) — needs Playwright + Chromium
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
  const c = await b.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const p = await c.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('http://localhost:8767/index.html');
  await p.waitForFunction(() => !document.getElementById('go').disabled, null, { timeout: 30000 });
  await p.waitForTimeout(300); await p.screenshot({ path: '/home/claude/rhythm/v3_menu.png' });
  const slugs = await p.evaluate(() => [...document.querySelectorAll('.si')].map(x => x.dataset.slug));
  for (const slug of slugs) {
    await p.locator(`.si[data-slug="${slug}"]`).scrollIntoViewIfNeeded();
    const bb = await p.locator(`.si[data-slug="${slug}"]`).boundingBox();
    await p.touchscreen.tap(bb.x + bb.width / 2, bb.y + bb.height / 2);
    await p.waitForFunction(() => !document.getElementById('go').disabled, null, { timeout: 30000 });
    const gb = await p.locator('#go').boundingBox(); await p.touchscreen.tap(gb.x + gb.width / 2, gb.y + gb.height / 2);
    await p.waitForFunction(() => window.__sb.state === 'play', null, { timeout: 30000 });
    const r = await p.evaluate(() => new Promise(res => {
      const S = window.__sb, objs = S.objs; let i = 0; const tEnd = objs[0].t + 12;
      (function tick() { const t = S.songTime();
        while (i < objs.length && objs[i].t < tEnd && t >= objs[i].t) { if (i % 7 !== 3) S.hitAt(objs[i].x, null); i++; }
        if (i < objs.length && objs[i].t < tEnd) requestAnimationFrame(tick); else res({ n: i, first: objs[0].t.toFixed(1) }); })();
    }));
    const st = await p.evaluate(() => { const s = window.__sb.st; return { perfect: s.perfect, miss: s.miss }; });
    const exp = r.n - Math.floor((r.n + 3) / 7);
    const title = await p.evaluate(() => document.querySelector('.si.on b').textContent);
    console.log(slug.padEnd(16), title.padEnd(12), 'played', r.n, 'from', r.first + 's', 'perfect', st.perfect, '(expected', exp + ')', 'miss', st.miss);
    if (slug === 'waltz-3-4') await p.screenshot({ path: '/home/claude/rhythm/v3_play_waltz.png' });
    await p.click('#quit');
  }
  console.log('errors', errs);
  await b.close();
})();
