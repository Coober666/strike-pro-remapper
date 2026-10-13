"""Bounded local-library inspection. Never discovers or opens removable cards."""
from pathlib import Path
import wave


def local_file(library, folders, reference):
    if not isinstance(reference, str) or len(reference) > 512:
        raise ValueError('Invalid asset reference')
    parts = reference.replace('\\', '/').split('/')
    if any(not p or p in ('.', '..') or any(c in p for c in ':*?"<>|') or
           any(ord(c) < 32 for c in p) for p in parts):
        raise ValueError('Unsafe asset reference')
    root = Path(library).resolve()
    matches = []
    for folder in folders:
        path = root / folder / '/'.join(parts)
        path.resolve().relative_to(root)
        if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
            raise ValueError('Linked assets are not supported')
        if path.is_file():
            matches.append(path)
    if len(matches) > 1:
        raise ValueError('Ambiguous asset: exists in both instruments and samples')
    return matches[0] if matches else None


def wav_info(path):
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                         audio.getframerate(), audio.getnframes())
        if channels not in (1, 2) or width not in (2, 3) or not 8000 <= rate <= 192000 or frames < 1:
            raise ValueError('Expected nonempty mono/stereo 16/24-bit PCM WAV')
        # Seek to the last declared frame to detect truncation without loading audio.
        audio.setpos(frames - 1)
        if len(audio.readframes(1)) != channels * width:
            raise ValueError('Truncated WAV data')
    return {'channels': channels, 'width': width, 'rate': rate, 'frames': frames,
            'bytes': path.stat().st_size, 'pcm_bytes': frames * channels * width}
