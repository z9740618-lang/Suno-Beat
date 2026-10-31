"""Auto-chart generator: stems + beat grid -> lane notes for 3 difficulties.

usage: python3 pipeline/chart.py <stems_dir> <title> <out_chart.json> [disc|lanes] [--suno=songs/<slug>/suno.json] [--bpm=<rough tempo>]
  --suno: Suno's analysis for songs made through Suno MCP. When given, Suno's beats, time signature
          and word timings replace the audio-only guesses (tempo, singing spans, phrase heads).
  --bpm : rough tempo hint for songs without Suno analysis (audio-only tracking confuses double/half tempo).
  disc  (default): sparse charts for the portrait disc game (web2) - big discs, wide hit areas
  lanes          : denser 4-lane charts for the first prototype (web)
  stems_dir: Demucs htdemucs (4-stem) output folder containing drums/bass/other/vocals.wav
"""
import librosa, numpy as np, json, sys, scipy.signal as sg
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
OPTS = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
STEMS_DIR, TITLE, OUT = ARGS[0], ARGS[1], ARGS[2]
PROFILE = ARGS[3] if len(ARGS) > 3 else 'disc'
SUNO = json.load(open(OPTS['suno'])) if 'suno' in OPTS else None

SR = 22050
HOP = 256
D = STEMS_DIR.rstrip('/') + '/'
LANES = ['kick', 'snare', 'hat', 'guitar'] + (['vocal'] if PROFILE == 'disc' else [])

def load(name):
    return librosa.load(D + name + '.wav', sr=SR, mono=True)[0]

drums, other, vocals, bass = load('drums'), load('other'), load('vocals'), load('bass')

# ---------- beat grid ----------
if SUNO:
    beats = np.array([b[0] for b in SUNO['beats']], float)
    tempo = float(SUNO['bpm']) if SUNO.get('bpm') else 60 / float(np.median(np.diff(beats)))
    TS = int(SUNO.get('time_signature') or 4)
else:
    # audio alone can't tell double/half tempo apart: pass --bpm=<rough tempo> (e.g. from the Suno prompt);
    # 120 is only a neutral default
    tempo, beats = librosa.beat.beat_track(y=drums, sr=SR, units='time', start_bpm=float(OPTS.get('bpm', 120)), tightness=200)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beats)
    TS = 4
BEAT = float(np.median(np.diff(beats)))      # seconds per beat
SLOW16 = BEAT / 4 >= 0.14                     # 16ths are playable (<= ~107 BPM): allow them for syncopation
# 16th-note grid by interpolating between tracked beats (follows live tempo drift)
grid16 = []
for a, b in zip(beats[:-1], beats[1:]):
    grid16 += [a + (b - a) * k / 4 for k in range(4)]
grid16.append(beats[-1])
grid16 = np.array(grid16)
gidx = np.arange(len(grid16))           # 0,4,8.. = beats
beat_ix = gidx % 4                       # 0 beat, 2 = 8th, 1/3 = 16th

# ---------- onset envelopes (one estimator for every lane) ----------
HOP = 128
def bandpass(y, lo, hi):
    if lo is None: b, a = sg.butter(4, hi / (SR / 2), 'low')
    elif hi is None: b, a = sg.butter(4, lo / (SR / 2), 'high')
    else: b, a = sg.butter(4, [lo / (SR / 2), hi / (SR / 2)], 'band')
    return sg.filtfilt(b, a, y)
def onset(y):
    o = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024)
    return np.clip(o / (np.percentile(o, 99.5) + 1e-9), 0, 1.5)
env = {
    'kick': onset(bandpass(drums, None, 140)),
    'snare': onset(bandpass(drums, 180, 1800)),
    'hat': onset(bandpass(drums, 6000, None)),
    'guitar': onset(other),
    'vocal': onset(vocals),
}
vrms = librosa.feature.rms(y=vocals, hop_length=HOP)[0]
vgate = 20 * np.log10(vrms + 1e-9) > (20 * np.log10(vrms.max()) - 30)
n = min(len(vgate), len(env['vocal'])); env['vocal'] = env['vocal'][:n] * vgate[:n]
ftime = librosa.frames_to_time(np.arange(len(env['kick'])), sr=SR, hop_length=HOP)

# estimator latency: compare kick envelope peaks with sample-accurate waveform attacks
lp = bandpass(drums, None, 150)
ew = sg.filtfilt(*sg.butter(2, 60 / (SR / 2)), np.abs(sg.hilbert(lp)))
dd = np.diff(ew); wp, _ = sg.find_peaks(dd, height=np.percentile(dd, 99.7), distance=int(.15 * SR))
kp, _ = sg.find_peaks(env['kick'], height=.35, distance=int(.07 * SR / HOP)); kt = ftime[kp]
lat = [kt[np.argmin(np.abs(kt - x / SR))] - x / SR for x in wp]
LAT = float(np.median([v for v in lat if abs(v) < .12])) + 0.004   # perceived hit ~4ms before steepest rise
print(f'estimator latency {LAT*1000:.1f} ms -> shifting all envelopes earlier')
ftime = ftime - LAT

# ---------- align beat grid to actual drum hits ----------
ks = env['kick'] + env['snare']
pk, _ = sg.find_peaks(ks, height=0.3, distance=int(0.07 * SR / HOP))
pt = ftime[pk]
offs = []
for b in beats:
    j = np.argmin(np.abs(pt - b))
    if abs(pt[j] - b) < 0.11:
        offs.append(pt[j] - b)
OFFSET = float(np.median(offs)) if offs else 0.0
if SUNO and abs(OFFSET) > 0.04:   # Suno's beats are trusted; only nudge them, never move them a lot
    OFFSET = 0.0
print(f'grid offset correction {OFFSET*1000:.1f} ms (from {len(offs)} beats)')
beats = beats + OFFSET
grid16 = grid16 + OFFSET

# ---------- pick peaks & snap to grid ----------
low_y, mid_y = bandpass(drums, None, 120), bandpass(drums, 180, 1800)
def seg_rms(y, t):
    i = max(0, int(t * SR)); return np.sqrt(np.mean(y[i:i + int(.05 * SR)] ** 2) + 1e-12)

def peaks_to_grid(e, thr, allowed=None):
    pk, _ = sg.find_peaks(e, height=thr, distance=int(0.07 * SR / HOP))
    d = {}
    for p in pk:
        t = ftime[min(p, len(ftime) - 1)]
        gi = int(np.argmin(np.abs(grid16 - t)))
        if abs(t - grid16[gi]) > 0.04: continue
        if allowed is not None and beat_ix[gi] not in allowed: continue
        snap_err.append(t - grid16[gi])
        d[gi] = max(d.get(gi, 0), float(e[p]))
    return d

snap_err = []
cands = {l: {} for l in LANES}
# drum body hits -> kick or snare by low/mid energy balance (exclusive)
body = onset(bandpass(drums, None, 1800))
ratios = {}
for gi, s_ in peaks_to_grid(body, .25).items():
    ratios[gi] = (20 * np.log10(seg_rms(low_y, grid16[gi]) / seg_rms(mid_y, grid16[gi])), s_)
rv = np.array([v[0] for v in ratios.values()])
SPLIT = float(np.median(rv))  # alternating kick/snare -> median sits between the two clusters
for gi, (r, s_) in ratios.items():
    cands['kick' if r > SPLIT else 'snare'][gi] = s_
cands['hat'] = peaks_to_grid(env['hat'], .25)
cands['guitar'] = peaks_to_grid(env['guitar'], .2)
# ---------- vocal melody (disc profile) ----------
# Sung syllables become the main notes; instruments only fill the space where nobody sings.
inst_ok = np.ones(len(grid16), bool)
def clean_words(words):
    """Suno word timings minus obviously broken ones (very long, or starting far after the next word)."""
    w = [(s_, e_) for _, s_, e_, _ in words if e_ > s_]
    keep = []
    for i, (s_, e_) in enumerate(w):
        nxt = w[i + 1][0] if i + 1 < len(w) else None
        if e_ - s_ > 1.5 or (nxt is not None and s_ - nxt > 0.5): continue
        keep.append((s_, e_))
    return keep
heads = set()
if 'vocal' in LANES and SUNO:
    # singing = where Suno says words are sung; phrase heads = starts of Suno's word chunks
    words = clean_words(SUNO.get('words', []))
    singing = np.zeros(len(grid16), bool)
    for s_, e_ in words:
        singing |= (grid16 >= s_ - 0.05) & (grid16 <= e_ + 0.05)
    for i in range(len(grid16)):
        inst_ok[i] = not singing[max(0, i - 4): i + 5].any()
    raw = peaks_to_grid(env['vocal'], .2, allowed={0, 1, 2, 3} if SLOW16 else {0, 2})
    cands['vocal'] = {gi: v for gi, v in raw.items() if singing[gi]}      # syllables only while really singing
    for s_, _ in words:
        gi = int(np.argmin(np.abs(grid16 - s_)))
        # snap the phrase head to the nearest 8th within 120ms
        okpos = (0, 1, 2, 3) if SLOW16 else (0, 2)
        best = min((g for g in range(max(0, gi - 2), min(len(grid16), gi + 3)) if beat_ix[g] in okpos),
                   key=lambda g: abs(grid16[g] - s_), default=None)
        if best is not None and abs(grid16[best] - s_) <= 0.12:
            cands['vocal'][best] = max(cands['vocal'].get(best, 0), 2.0); heads.add(best)
    print(f'singing on {singing.mean()*100:.0f}% of the song (Suno lyrics, {len(words)} words), '
          f'instruments allowed on {inst_ok.mean()*100:.0f}%, phrase heads {len(heads)}')
elif 'vocal' in LANES:
    cands['vocal'] = peaks_to_grid(env['vocal'], .2, allowed={0, 2})
    vdb = 20 * np.log10(vrms + 1e-9); vdb -= vdb.max()
    vt = librosa.frames_to_time(np.arange(len(vdb)), sr=SR, hop_length=HOP) - LAT
    singing = np.array([vdb[(vt >= grid16[i]) & (vt < grid16[i] + 0.08)].max(initial=-99) > -25 for i in range(len(grid16))])
    for i in range(len(grid16)):          # keep a beat of air on both sides of every sung phrase
        inst_ok[i] = not singing[max(0, i - 4): i + 5].any()
    print(f'singing on {singing.mean()*100:.0f}% of the song, instruments allowed on {inst_ok.mean()*100:.0f}%')
# chord changes: chroma novelty of the guitar stem sampled on the 8th grid
chroma = librosa.feature.chroma_cqt(y=other, sr=SR, hop_length=512)
ct = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=SR, hop_length=512) - LAT
def chroma_at(t0, t1):
    m = (ct >= t0) & (ct < t1); v = chroma[:, m].mean(1) if m.any() else np.zeros(12)
    return v / (np.linalg.norm(v) + 1e-9)
g8 = [gi for gi in range(0, len(grid16) - 2, 2)]
prev = None; nov = {}
for gi in g8:
    cur = chroma_at(grid16[gi], grid16[gi + 2])
    if prev is not None: nov[gi] = 1 - float(cur @ prev)
    prev = cur
nv = np.array(list(nov.values())); thr = np.percentile(nv, 85)
for gi, v in nov.items():
    if v >= thr:
        cands['guitar'][gi] = max(cands['guitar'].get(gi, 0), 1.0 + v)   # chord change outranks plain onsets

# bar phase: Suno's majority downbeat (its bar numbers glitch locally, so recount with the time signature);
# otherwise the beat phase where kick is most common
if SUNO:
    ones = [i for i, b in enumerate(SUNO['beats']) if b[1] == 1]
    PHASE = int(np.argmax(np.bincount(np.array(ones) % TS, minlength=TS))) if ones else 0
else:
    kb = [gi // 4 for gi in cands['kick'] if beat_ix[gi] == 0]
    PHASE = int(np.argmax(np.bincount(np.array(kb) % 4, minlength=4))) if kb else 0
bars = beats[PHASE::TS]

# strength -> percentile rank within lane so one threshold works for every lane
rank = {}
for lane, d in cands.items():
    if not d: rank[lane] = {}; continue
    v = np.array(list(d.values())); order = v.argsort().argsort() / max(1, len(v) - 1)
    rank[lane] = dict(zip(d.keys(), order))

# ---------- difficulty rules ----------
# pos: allowed 16th positions in a beat (0 = on the beat, 2 = off-beat 8th)
# gap: min distance between notes of the same part, ggap: between any two notes (both in 16ths)
RULES_LANES = {
    'easy':   dict(pos={0},          maxsim=1, gap=4, ggap=0, nps=1.8, lanes={'kick', 'snare', 'guitar'}),
    'normal': dict(pos={0, 2},       maxsim=2, gap=2, ggap=0, nps=3.5, lanes=set(LANES)),
    'hard':   dict(pos={0, 1, 2, 3}, maxsim=2, gap=1, ggap=0, nps=5.5, lanes=set(LANES)),
}
# Disc game: big discs need room, so density stays low except on HARD.
# Density is set per BEAT (so it follows the song's tempo), clamped to a per-second range.
# Gaps are in seconds so fast songs automatically get fewer off-beat notes.
RULES_DISC = {
    'easy':   dict(pos={0, 2}, maxsim=1, chords=0.00, npb=0.30, nps_lo=0.5, nps_hi=1.0, gap_s=0.60, ggap_s=0.45,
                   lanes={'kick', 'snare', 'guitar', 'vocal'}),
    'normal': dict(pos={0, 2}, maxsim=2, chords=0.06, npb=0.55, nps_lo=0.9, nps_hi=1.8, gap_s=0.30, ggap_s=0.28, lanes=set(LANES)),
    'hard':   dict(pos={0, 2}, maxsim=2, chords=0.12, npb=1.00, nps_lo=1.6, nps_hi=3.2, gap_s=0.16, ggap_s=0.16, lanes=set(LANES)),
}
MAX_EMPTY_BEATS = 8      # never leave more than 2 bars (in 4/4) without a note if anything playable is there
RULES = RULES_DISC if PROFILE == 'disc' else RULES_LANES
BONUS = {'kick': .35, 'snare': .35, 'vocal': .1, 'guitar': 0, 'hat': -.05}
if PROFILE == 'disc':   # sparse charts: keep guitar (chord changes) in the mix so EASY isn't drums only
    BONUS = {'kick': .3, 'snare': .3, 'vocal': .4, 'guitar': .14, 'hat': -.05}
PRIO = {'snare': 5, 'kick': 4, 'vocal': 3, 'guitar': 2, 'hat': 1}
dur = len(drums) / SR

def eligible(rule):
    """(grid index, lane, score) for every candidate this difficulty may use."""
    out = []
    for lane in rule['lanes']:
        for gi, rk in rank[lane].items():
            if lane != 'vocal' and not inst_ok[gi]: continue      # instruments only between sung phrases
            # slow songs: 16ths allowed (EASY only for phrase heads, so a syncopated sung entry still lands)
            slow_ok = SLOW16 and 'ggap_s' in rule and (rule is not RULES_DISC['easy'] or gi in heads)
            if beat_ix[gi] in rule['pos'] or slow_ok:
                out.append((gi, lane, rk + BONUS[lane] + (1.0 if gi in heads else 0)))
    return out

def build(rule, q):
    by_g = {}
    for gi, lane, sc in eligible(rule):
        if sc >= q: by_g.setdefault(gi, []).append((lane, sc))
    use_s = 'ggap_s' in rule
    notes, last, last_any = [], {l: -1e9 for l in LANES}, -1e9
    for gi in sorted(by_g):
        pos = grid16[gi] if use_s else gi
        if pos - last_any < (rule['ggap_s'] if use_s else rule['ggap']): continue
        picked = 0
        for lane, sc in sorted(by_g[gi], key=lambda x: (-x[1] if x[0] == 'vocal' else 0, -PRIO[x[0]], -x[1])):
            if picked >= rule['maxsim']: break
            if pos - last[lane] < (rule['gap_s'] if use_s else rule['gap']): continue
            notes.append({'t': round(float(grid16[gi]), 4), 'lane': LANES.index(lane), 'gi': gi, 'sc': sc})
            last[lane] = pos; picked += 1
        if picked: last_any = pos
    return notes

def limit_chords(notes, rule):
    """Cap simultaneous notes at a share of the chart: drop the weaker half of the weakest chords."""
    by = {}
    for n in notes: by.setdefault(n['gi'], []).append(n)
    chords = sorted((g for g in by.values() if len(g) > 1), key=lambda g: min(x['sc'] for x in g))
    allow = int(rule['chords'] * len(notes))
    drop = set()
    for g in chords[:max(0, len(chords) - allow)]:
        drop.add(id(min(g, key=lambda x: x['sc'])))
    return [n for n in notes if id(n) not in drop]

def fill_gaps(notes, rule):
    """Long stretches without notes feel broken: add the best playable candidate inside each one."""
    elig = sorted(eligible(rule), key=lambda x: -x[2])
    times = lambda: sorted(n['t'] for n in notes)
    for _ in range(200):
        t = times()
        edges = [elig_t0] + t + [elig_t1]
        gaps = [(b - a, a, b) for a, b in zip(edges[:-1], edges[1:]) if b - a > MAX_EMPTY_BEATS * BEAT]
        if not gaps: break
        added = False
        for _, a, b in sorted(gaps, reverse=True):
            mid = (a + b) / 2
            cand = [(abs(grid16[gi] - mid) / (b - a) - sc * 0.3, gi, lane) for gi, lane, sc in elig
                    if a + rule['ggap_s'] * 2 < grid16[gi] < b - rule['ggap_s'] * 2]
            if cand:
                _, gi, lane = min(cand)
                notes.append({'t': round(float(grid16[gi]), 4), 'lane': LANES.index(lane), 'gi': gi}); added = True
        if not added: break
    notes.sort(key=lambda n: (n['t'], n['lane']))
    return notes

all_c = [grid16[gi] for d in cands.values() for gi in d]
elig_t0, elig_t1 = (min(all_c), max(all_c)) if all_c else (0, dur)
charts = {}
for k, r in RULES.items():
    target = r['nps'] if 'nps' in r else min(r['nps_hi'], max(r['nps_lo'], r['npb'] / BEAT))
    lo, hi = 0.0, 3.0
    for _ in range(30):                       # binary search threshold to hit target density
        mid = (lo + hi) / 2
        if len(build(r, mid)) / dur > target: lo = mid
        else: hi = mid
    notes = build(r, hi)
    if 'ggap_s' in r:
        notes = limit_chords(notes, r)
        notes = fill_gaps(notes, r)
    for n in notes: n.pop('gi', None); n.pop('sc', None)
    charts[k] = notes

out = {
    'title': TITLE, 'bpm': round(tempo, 1), 'time_signature': TS, 'beat_source': 'suno' if SUNO else 'audio',
    'duration': round(dur, 2),
    'lanes': LANES, 'beats': [round(float(b), 4) for b in beats],
    'bars': [round(float(b), 4) for b in bars], 'charts': charts,
}
json.dump(out, open(OUT, 'w'))

se = np.abs(np.array(snap_err)) * 1000
print(f'tempo {tempo:.1f}  beats {len(beats)}  dur {dur:.1f}s  kick/snare split {SPLIT:.1f}dB  bar phase {PHASE}')
print(f'snap error ms: median {np.median(se):.1f}  p90 {np.percentile(se, 90):.1f}')
for k, n in charts.items():
    cnt = np.bincount([x["lane"] for x in n], minlength=len(LANES))
    print(f'{k:6s} notes {len(n):4d}  nps {len(n)/dur:4.1f}  ' + str(dict(zip(LANES, cnt.tolist()))))
