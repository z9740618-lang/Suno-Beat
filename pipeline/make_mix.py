"""Loudness-match a song for the game: two-pass EBU R128 normalisation to -12 LUFS, -1 dBTP, 160k MP3.
usage: python3 pipeline/make_mix.py <in.wav> <out.mp3>"""
import json, re, subprocess, sys
src, dst = sys.argv[1], sys.argv[2]
r = subprocess.run(['ffmpeg', '-hide_banner', '-i', src, '-af', 'loudnorm=I=-12:TP=-1:LRA=11:print_format=json',
                    '-f', 'null', '-'], capture_output=True, text=True).stderr
m = json.loads(re.search(r'\{[^{}]*"input_i"[^{}]*\}', r, re.S).group(0))
af = (f"loudnorm=I=-12:TP=-1:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
      f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', src, '-af', af,
                '-ar', '48000', '-ac', '2', '-b:a', '160k', dst], check=True)
print(f'{src}: {m["input_i"]} LUFS -> -12')
