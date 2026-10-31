// Run after: (cd web2 && python3 -m http.server 8766)  — needs Playwright + Chromium
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
  for (const v of [{ name: 'phone', viewport: { width: 390, height: 844 }, touch: true }, { name: 'pc', viewport: { width: 1280, height: 800 } }]) {
    const c = await b.newContext({ viewport: v.viewport, hasTouch: !!v.touch, isMobile: !!v.touch });
    const p = await c.newPage(); const errs = [];
    p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await p.goto('http://localhost:8766/index.html');
    await p.waitForFunction(() => !document.getElementById('go').disabled, null, { timeout: 30000 });
    await p.waitForTimeout(300); await p.screenshot({ path: `/home/claude/rhythm/v2_menu_${v.name}.png` });
    if (v.touch) { const bb = await p.locator('#go').boundingBox(); await p.touchscreen.tap(bb.x + bb.width / 2, bb.y + bb.height / 2); } else await p.click('#go');
    await p.waitForFunction(() => window.__sb.state === 'play');
    // bot: hit every ball at its time & place; skip every 9th; every 13th is tapped at the WRONG place
    const r = await p.evaluate(() => new Promise(res => {
      const S = window.__sb; let i = 0, wrong = 0, chordMin = 9; const objs = S.objs;
      for (let k = 1; k < objs.length; k++) { if (objs[k].t - objs[k - 1].t < 0.012) chordMin = Math.min(chordMin, Math.abs(objs[k].x - objs[k - 1].x)); }
      (function tick() {
        const t = S.songTime();
        while (i < objs.length && objs[i].t < 25 && t >= objs[i].t) {
          if (i % 9 === 4) { /* skip */ }
          else if (i % 13 === 6) { S.hitAt(objs[i].x > 0.5 ? objs[i].x - 0.4 : objs[i].x + 0.4, null); wrong++; }
          else S.hitAt(objs[i].x, null);
          i++;
        }
        if (i < objs.length && objs[i].t < 25) requestAnimationFrame(tick); else res({ n: i, wrong, chordMin: chordMin.toFixed(2) });
      })();
    }));
    await p.screenshot({ path: `/home/claude/rhythm/v2_play_${v.name}.png` });
    const F = await p.evaluate(() => window.__sb.F);
    if (v.touch) await p.touchscreen.tap(F.x + F.w * 0.3, F.line + 10); else await p.mouse.click(F.x + F.w * 0.3, F.line + 10);
    const tapX = await p.evaluate(() => window.__lastTapX);
    const st = await p.evaluate(() => { const s = window.__sb.st; return { perfect: s.perfect, great: s.great, good: s.good, miss: s.miss, max: s.max }; });
    console.log(v.name, JSON.stringify(st), JSON.stringify(r), 'tapX', tapX && tapX.toFixed(2), 'errors', errs);
    await c.close();
  }
  await b.close();
})();
