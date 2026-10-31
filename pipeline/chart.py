"""Auto-chart generator: stems + beat grid -> lane notes for 3 difficulties.

usage: python3 pipeline/chart.py <stems_dir> <title> <out_chart.json>
  stems_dir: Demucs htdemucs (4-stem) output folder containing drums/bass/other/vocals.wav
"""
import librosa, numpy as np, json, sys, scipy.signal as sg
STEMS_DIR, TITLE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

SR = 22050
HOP = 256
D = STEMS_DIR.rstrip('/') + '/'
LANES = ['kick', 'snare', 'hat', 'guitar']

def load(name):
    return librosa.load(D + name + '.wav', sr=SR, mono=True)[0]

drums, other, vocals, bass = load('drums'), load('other'), load('vocals'), load('bass')

# ---------- beat grid ----------
tempo, beats = librosa.beat.beat_track(y=drums, sr=SR, units='time', start_bpm=180, tightness=200)
tempo = float(np.atleast_1d(tempo)[0])
beats = np.asarray(beats)
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
OFFSET = float(np.median(offs))
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

# bar phase: downbeat = the beat phase where kick is most common
kb = [gi // 4 for gi in cands['kick'] if beat_ix[gi] == 0]
PHASE = int(np.argmax(np.bincount(np.array(kb) % 4, minlength=4))) if kb else 0
bars = beats[PHASE::4]

# strength -> percentile rank within lane so one threshold works for every lane
rank = {}
for lane, d in cands.items():
    if not d: rank[lane] = {}; continue
    v = np.array(list(d.values())); order = v.argsort().argsort() / max(1, len(v) - 1)
    rank[lane] = dict(zip(d.keys(), order))

# ---------- difficulty rules ----------
RULES = {
    'easy':   dict(pos={0},          maxsim=1, gap=4, nps=1.8, lanes={'kick', 'snare', 'guitar'}),
    'normal': dict(pos={0, 2},       maxsim=2, gap=2, nps=3.5, lanes=set(LANES)),
    'hard':   dict(pos={0, 1, 2, 3}, maxsim=2, gap=1, nps=5.5, lanes=set(LANES)),
}
BONUS = {'kick': .35, 'snare': .35, 'vocal': .1, 'guitar': 0, 'hat': -.05}
PRIO = {'snare': 5, 'kick': 4, 'vocal': 3, 'guitar': 2, 'hat': 1}
dur = len(drums) / SR

def build(rule, q):
    by_g = {}
    for lane in rule['lanes']:
        for gi, rk in rank[lane].items():
            if beat_ix[gi] in rule['pos'] and rk + BONUS[lane] >= q:
                by_g.setdefault(gi, []).append((lane, rk))
    notes, last = [], {l: -99 for l in LANES}
    for gi in sorted(by_g):
        picked = 0
        for lane, rk in sorted(by_g[gi], key=lambda x: (-PRIO[x[0]], -x[1])):
            if picked >= rule['maxsim']: break
            if gi - last[lane] < rule['gap']: continue
            notes.append({'t': round(float(grid16[gi]), 4), 'lane': LANES.index(lane)})
            last[lane] = gi; picked += 1
    return notes

charts = {}
for k, r in RULES.items():
    lo, hi = 0.0, 1.5
    for _ in range(25):                       # binary search threshold to hit target density
        mid = (lo + hi) / 2
        if len(build(r, mid)) / dur > r['nps']: lo = mid
        else: hi = mid
    charts[k] = build(r, hi)

out = {
    'title': TITLE, 'bpm': round(tempo, 1), 'duration': round(dur, 2),
    'lanes': LANES, 'beats': [round(float(b), 4) for b in beats],
    'bars': [round(float(b), 4) for b in bars], 'charts': charts,
}
json.dump(out, open(OUT, 'w'))

se = np.abs(np.array(snap_err)) * 1000
print(f'tempo {tempo:.1f}  beats {len(beats)}  dur {dur:.1f}s  kick/snare split {SPLIT:.1f}dB  bar phase {PHASE}')
print(f'snap error ms: median {np.median(se):.1f}  p90 {np.percentile(se, 90):.1f}')
for k, n in charts.items():
    cnt = np.bincount([x["lane"] for x in n], minlength=4)
    print(f'{k:6s} notes {len(n):4d}  nps {len(n)/dur:4.1f}  ' + str(dict(zip(LANES, cnt.tolist()))))
