"""Read-only audio measurements with ffmpeg/ffprobe. Files are never modified."""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess

EXT = {'.mp3', '.flac', '.wav', '.aiff', '.aif', '.m4a'}
LOSSLESS = {'flac', 'alac', 'wav', 'pcm_s16le', 'pcm_s24le', 'pcm_s16be', 'pcm_s24be'}
LOUDNESS_FIELDS = ('integrated_lufs', 'true_peak_dbtp', 'loudness_range_lu')


TOOL_TIMEOUT_SECONDS = 30 * 60   # a corrupt file must not hang a job forever


def run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=TOOL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, '', f'{args[0]} timed out')


def missing_tools():
    return [tool for tool in ('ffmpeg', 'ffprobe') if not shutil.which(tool)]


def tool_versions():
    def first_line(tool):
        lines = run([tool, '-version']).stdout.splitlines()
        return lines[0] if lines else ''
    return {'ffmpeg_version': first_line('ffmpeg'), 'ffprobe_version': first_line('ffprobe')}


# --- Hashes ---------------------------------------------------------------------


def sha256_file(path):
    """SHA-256 of the whole file (links renamed files in the analysis history)."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def quick_fingerprint(path):
    """Same audio file = same size and same first/last 256 KB (fast library identity)."""
    size = os.path.getsize(path)
    digest = hashlib.md5(str(size).encode())
    with open(path, 'rb') as handle:
        digest.update(handle.read(262144))
        if size > 524288:
            handle.seek(-262144, os.SEEK_END)
            digest.update(handle.read())
    return digest.hexdigest()


def audio_hash(path):
    """MD5 of the encoded audio stream only, so copies that differ just in tags match."""
    proc = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-c', 'copy', '-f', 'md5', '-'])
    match = re.search(r'MD5=([0-9a-f]{32})', proc.stdout + proc.stderr)
    return match.group(1) if match else None


# --- Loudness -------------------------------------------------------------------


def decoder_problems(stderr):
    """ffmpeg log lines that report decoding problems. Only '[component @ ...]' lines
    count, so metadata such as an artist named 'Futuro Terror' is not a false alarm."""
    return [line.strip() for line in (stderr or '').splitlines()
            if line.lstrip().startswith('[') and re.search(r'(?i)\b(error|invalid|corrupt|overread)', line)]


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def measure(path):
    """Integrated loudness, true peak and loudness range of the first audio stream."""
    row = {'filename': os.path.basename(path), 'path': str(path), 'status': 'ERROR', 'error': '',
           'integrated_lufs': None, 'true_peak_dbtp': None, 'loudness_range_lu': None,
           'duration_seconds': None, 'codec': '', 'sample_rate_hz': None, 'channels': None}
    try:
        probe_proc = run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_streams', '-show_format',
                          '-of', 'json', str(path)])
        if probe_proc.returncode:
            raise ValueError(probe_proc.stderr)
        info = json.loads(probe_proc.stdout)
        stream = info['streams'][0]
        row.update({
            'duration_seconds': _number(stream.get('duration', info.get('format', {}).get('duration'))),
            'codec': stream.get('codec_name', ''),
            'sample_rate_hz': int(stream['sample_rate']) if str(stream.get('sample_rate', '')).isdigit() else None,
            'channels': stream.get('channels'),
        })
        proc = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(path), '-map', '0:a:0', '-vn', '-sn', '-dn',
                    '-af', 'loudnorm=print_format=json', '-f', 'null', '-'])
        if proc.returncode:
            raise ValueError(proc.stderr[-4000:])
        decoder = json.JSONDecoder()
        data = None
        for index, char in enumerate(proc.stderr):
            if char == '{':
                try:
                    obj, _ = decoder.raw_decode(proc.stderr[index:])
                    if 'input_i' in obj:
                        data = obj
                except ValueError:
                    pass
        if data is None:
            raise ValueError('No loudnorm measurements found')
        values = [float(data[k]) for k in ('input_i', 'input_tp', 'input_lra')]
        if not all(math.isfinite(v) for v in values):
            row['status'] = 'SILENCE' if values[0] == -math.inf else 'NON_FINITE'
        else:
            row.update(zip(LOUDNESS_FIELDS, values))
            row['status'] = 'OK'
        problems = decoder_problems(proc.stderr)
        if problems:
            row['error'] = '\n'.join(problems)[-4000:]
    except (ValueError, KeyError, IndexError, OSError) as exc:
        row['error'] = str(exc)
    return row


# --- Quality checks (downloads review) --------------------------------------------


def probe(path):
    proc = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)])
    if proc.returncode:
        return {}
    info = json.loads(proc.stdout or '{}')
    fmt = info.get('format', {})
    tags = {k.lower(): v for k, v in (fmt.get('tags') or {}).items()}
    for stream in info.get('streams', []):
        if stream.get('codec_type') == 'audio':
            tags = tags or {k.lower(): v for k, v in (stream.get('tags') or {}).items()}
    audio = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), {})
    art = any(s.get('codec_type') == 'video' and s.get('disposition', {}).get('attached_pic')
              for s in info.get('streams', []))
    bitrate = audio.get('bit_rate') or fmt.get('bit_rate')
    return {
        'tag_artist': tags.get('artist', ''), 'tag_title': tags.get('title', ''),
        'album': tags.get('album', ''), 'year': (tags.get('date') or tags.get('year') or '')[:4],
        'bitrate_kbps': round(int(bitrate) / 1000) if str(bitrate).isdigit() else None,
        'has_art': art,
    }


def high_frequency(path):
    """RMS level (dB) of the full signal minus the level above 17 kHz and above 19.5 kHz (mono mix).
    A large gap above 19.5 kHz on a lossy file suggests a transcode."""
    band = lambda f: ','.join([f'highpass=f={f}:poles=2'] * 3)
    graph = ('[0:a:0]aformat=channel_layouts=mono,asplit=3[a][b][c];'
             f'[b]{band(17000)}[b2];[c]{band(19500)}[c2];'
             '[a][b2][c2]amerge=inputs=3,astats=measure_overall=none:measure_perchannel=RMS_level[out]')
    proc = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(path), '-filter_complex', graph,
                '-map', '[out]', '-f', 'null', '-'])
    levels = []
    for line in proc.stderr.splitlines():
        if 'RMS level dB' in line:
            try:
                levels.append(float(line.rsplit(':', 1)[1]))
            except ValueError:
                levels.append(-math.inf)
    if len(levels) != 3 or not math.isfinite(levels[0]):
        return {'hf_gap_17k_db': None, 'hf_gap_19k_db': None}
    gap = lambda v: round(levels[0] - v, 1) if math.isfinite(v) else 150.0
    return {'hf_gap_17k_db': gap(levels[1]), 'hf_gap_19k_db': gap(levels[2])}


def _percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(pct / 100 * len(ordered)))]


def loud_sections(path):
    """Short-term loudness (3 s window) of the loud parts: its 95th percentile, and the loudest
    momentary value. Integrated LUFS averages the whole song, so a long quiet intro or break
    can hide how hard the drops hit when mixing."""
    proc = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(path), '-map', '0:a:0', '-vn',
                '-af', 'ebur128=framelog=info', '-f', 'null', '-'])
    momentary, short = [], []
    for match in re.finditer(r'M:\s*(-?[\d.]+)\s+S:\s*(-?[\d.]+)', proc.stderr):
        m, s = float(match.group(1)), float(match.group(2))
        if m > -70 and s > -70:  # skip digital silence and the first 3 s warm-up
            momentary.append(m)
            short.append(s)
    if not short:
        return {'loud_lufs': None, 'momentary_max_lufs': None}
    return {'loud_lufs': round(_percentile(short, 95), 2), 'momentary_max_lufs': round(max(momentary), 2)}


TONE_BANDS = (('tone_low_db', 'lowpass=f=150:poles=2'),
              ('tone_mid_db', 'highpass=f=150:poles=2,lowpass=f=2000:poles=2'),
              ('tone_presence_db', 'highpass=f=2000:poles=2,lowpass=f=8000:poles=2'),
              ('tone_air_db', 'highpass=f=8000:poles=2'))


def tonal_balance(path):
    """Level of four bands (low < 150 Hz, mid, presence 2-8 kHz, air > 8 kHz) relative to the whole
    signal, in dB (always <= 0; closer to 0 means more of the song's energy is there). Equal LUFS
    can still sound different when one song is much darker or brighter than another."""
    split = ';'.join([f'[0:a:0]aformat=channel_layouts=mono,asplit={len(TONE_BANDS) + 1}[t]'
                      + ''.join(f'[b{i}]' for i in range(len(TONE_BANDS)))]
                     + [f'[b{i}]{chain}[f{i}]' for i, (_, chain) in enumerate(TONE_BANDS)])
    graph = (split + ';[t]' + ''.join(f'[f{i}]' for i in range(len(TONE_BANDS)))
             + f'amerge=inputs={len(TONE_BANDS) + 1},astats=measure_overall=none:measure_perchannel=RMS_level[out]')
    proc = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(path), '-filter_complex', graph,
                '-map', '[out]', '-f', 'null', '-'])
    levels = []
    for line in proc.stderr.splitlines():
        if 'RMS level dB' in line:
            try:
                levels.append(float(line.rsplit(':', 1)[1]))
            except ValueError:
                levels.append(-math.inf)
    if len(levels) != len(TONE_BANDS) + 1 or not math.isfinite(levels[0]):
        return {name: None for name, _ in TONE_BANDS}
    return {name: round(level - levels[0], 1) if math.isfinite(level) else -150.0
            for (name, _), level in zip(TONE_BANDS, levels[1:])}


def quality(path, measured):
    """Everything beyond loudness that the analysis keeps: file facts, decode errors, transcode
    check, loud-section level and tonal balance. `measured` is the result of measure()."""
    result = {'corrupt_frames': len([l for l in (measured.get('error') or '').splitlines() if l.strip()])}
    result.update(probe(path))
    result.update(high_frequency(path))
    result.update(loud_sections(path))
    result.update(tonal_balance(path))
    return result


def analyze(path):
    """Loudness plus the quality checks used to pick the best download."""
    row = measure(path)
    result = {k: row.get(k) for k in LOUDNESS_FIELDS + ('status', 'error', 'duration_seconds', 'codec',
                                                         'sample_rate_hz', 'channels')}
    result['corrupt_frames'] = len([l for l in (row.get('error') or '').splitlines() if l.strip()])
    result['audio_md5'] = audio_hash(path)
    result.update(probe(path))
    result.update(high_frequency(path))
    return result
