"""Check auto charts against Suno's own analysis (songs/<slug>/suno.json).

usage: python3 pipeline/compare.py slug [slug ...]
Reads songs/<slug>/chart.json (from chart.py) and songs/<slug>/suno.json.
"""
import json, sys, numpy as np

def clean_words(words):
    """Drop sung words whose timing is obviously broken (huge spans, jumps far past the next word)."""
    w = [(s, e) for txt, s, e, ok in words if e > s]
    out = []
    for i, (s, e) in enumerate(w):
        if e - s > 1.5:
            continue
        nxt = w[i + 1][0] if i + 1 < len(w) else None
        if nxt is not None and s - nxt > 0.5:   # starts well after the following word -> misplaced
            continue
        out.append((s, e))
    return np.array(out) if out else np.zeros((0, 2))

def sung_spans(ws, join_gap=0.8):
    spans = []
    for s, e in ws:
        if spans and s - spans[-1][1] <= join_gap:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    return spans

def report(slug):
    c = json.load(open(f'songs/{slug}/chart.json'))
    su = json.load(open(f'songs/{slug}/suno.json'))
    lanes = c['lanes']; dur = c['duration']
    sb = np.array([b[0] for b in su['beats']]); ob = np.array(c['beats'])
    ratio = (60 / np.median(np.diff(ob))) / su['bpm']
    # beat agreement: our beats vs nearest Suno beat
    d = np.array([np.min(np.abs(sb - x)) for x in ob])
    ws = clean_words(su['words']); spans = sung_spans(ws)
    sung_cov = sum(e - s for s, e in spans) / dur
    print(f'\n== {slug}  {c["title"]}  ({dur:.0f}s)')
    print(f'tempo  ours {60/np.median(np.diff(ob)):.1f}  suno {su["bpm"]} (x{ratio:.2f})  '
          f'beat match median {np.median(d)*1000:.0f}ms, within 50ms {np.mean(d < .05)*100:.0f}%   '
          f'singing per Suno lyrics {sung_cov*100:.0f}% of song ({len(ws)}/{len(su["words"])} words usable)')
    for k, notes in c['charts'].items():
        t = np.array([n['t'] for n in notes]); ln = [lanes[n['lane']] for n in notes]
        nps = len(t) / dur; npb = nps / (su['bpm'] / 60)
        parts = {l: ln.count(l) for l in lanes if ln.count(l)}
        chords = int(np.sum(np.diff(t) < 0.012)) if len(t) > 1 else 0
        win2 = max((np.sum((t >= x) & (t < x + 2)) for x in t), default=0)
        gaps = np.diff(np.concatenate([[0], t, [dur]]))
        voc = t[[l == 'vocal' for l in ln]] if 'vocal' in lanes else np.array([])
        inst = t[[l != 'vocal' for l in ln]]
        ws0 = ws[:, 0] if len(ws) else np.array([])
        # Suno "words" are space-separated chunks (a Japanese phrase), so compare at two levels:
        # is the vocal note during actual singing, and are chunk starts (phrase heads) charted?
        during = lambda x: any(s - 0.08 <= x <= e + 0.08 for s, e in ws)
        v_in = np.mean([during(x) for x in voc]) * 100 if len(voc) and len(ws) else float('nan')
        heads = np.mean([np.min(np.abs(voc - w)) < 0.08 for w in ws0]) * 100 if len(voc) and len(ws0) else float('nan')
        in_song = lambda x: any(s - 0.3 <= x <= e + 0.3 for s, e in spans)
        i_bad = np.mean([in_song(x) for x in inst]) * 100 if len(inst) else 0
        print(f'  {k:6s} {len(t):4d} notes  {nps:.2f}/s  {npb:.2f}/beat  max {win2} in 2s  longest gap {gaps.max():.1f}s  chords {chords}  '
              f'| vocal notes during singing {v_in:.0f}%  phrase heads charted {heads:.0f}%  instr. inside singing {i_bad:.0f}%  | {parts}')

if __name__ == '__main__':
    for s in sys.argv[1:]:
        report(s)
