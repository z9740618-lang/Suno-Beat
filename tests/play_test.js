// Run from the repo root after: (cd web && python3 -m http.server 8765)  — needs Playwright + Chromium
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
  const vps = [
    { name: 'iphone_portrait', viewport: { width: 390, height: 844 }, touch: true },
    { name: 'phone_land', viewport: { width: 844, height: 390 }, touch: true },
    { name: 'pc', viewport: { width: 1280, height: 720 } },
  ];
  for (const v of vps) {
    const c = await b.newContext({ viewport: v.viewport, hasTouch: !!v.touch, isMobile: !!v.touch });
    const p = await c.newPage(); const errs = [];
    p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await p.goto('http://localhost:8765/index.html');
    await p.waitForFunction(() => !document.getElementById('go').disabled, null, { timeout: 30000 });
    await p.waitForTimeout(400);
    await p.screenshot({ path: `s4_menu_${v.name}.png` });
    // press a settings stepper via real tap/click (checks hit-testing in rotated layout)
    const before = await p.textContent('#speedV');
    if (v.touch) { const bb = await p.locator('button[data-s=speed][data-d="1"]').boundingBox(); await p.touchscreen.tap(bb.x + bb.width / 2, bb.y + bb.height / 2); }
    else await p.click('button[data-s=speed][data-d="1"]');
    const after = await p.textContent('#speedV');
    if (v.touch) { const bb = await p.locator('#go').boundingBox(); await p.touchscreen.tap(bb.x + bb.width / 2, bb.y + bb.height / 2); } else await p.click('#go');
    await p.waitForFunction(() => window.__stembeat.state === 'play', null, { timeout: 15000 });
    const chart = await (await fetch('http://localhost:8765/chart.json')).json();
    const notes = chart.charts.normal.filter(n => n.t < 25);
    await p.evaluate((notes) => new Promise(res => {
      const S = window.__stembeat; let i = 0;
      (function tick() { const t = S.songTime();
        while (i < notes.length && t >= notes[i].t) { if (i % 9 !== 4) S.judge(notes[i].lane); i++; }
        if (i < notes.length) requestAnimationFrame(tick); else res(); })();
    }), notes);
    await p.screenshot({ path: `s4_play_${v.name}.png` });
    let laneMap = '';
    if (v.touch) {   // tap the 4 thumb zones as a user holding the phone sideways would see them
      const virt = await p.evaluate(() => window.__stembeat.virt);
      const res = [];
      for (let l = 0; l < 4; l++) {
        const frac = (l + 0.5) / 4;
        const [x, y] = virt ? [v.viewport.width * 0.05, v.viewport.height * frac] : [v.viewport.width * frac, v.viewport.height * 0.95];
        await p.touchscreen.tap(x, y); res.push(await p.evaluate(() => window.__lastLane));
      }
      laneMap = `virt=${virt} lanes=${res.join(',')}`;
    }
    const st = await p.evaluate(() => { const s = window.__stembeat.st; return { perfect: s.perfect, miss: s.miss }; });
    console.log(v.name, `speed ${before}->${after}`, JSON.stringify(st), 'notes', notes.length, laneMap, 'errors', errs);
    await c.close();
  }
  await b.close();
})();
