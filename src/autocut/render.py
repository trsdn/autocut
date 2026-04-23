"""ffmpeg render: speed → cut → fade → audio chain."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def render(
    *,
    ffmpeg: str,
    src: Path,
    dst: Path,
    keep: list[tuple[float, float]],
    speed: float = 1.0,
    fade: float = 0.040,
    highpass_hz: int = 80,
    compressor_threshold_db: float = -22.0,
    compressor_ratio: float = 2.5,
    deess_db: float = -2.5,
    loudnorm_i: float = -16.0,
    loudnorm_tp: float = -1.5,
    crf: int = 20,
    preset: str = "medium",
    audio_bitrate: str = "160k",
) -> float:
    """Render cut video with speed change and clean audio chain.
    `keep` timestamps are expressed in the POST-speed timeline."""
    parts: list[str] = []
    n = len(keep)

    if abs(speed - 1.0) < 1e-6:
        parts.append(f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
        parts.append(f"[0:a]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
    else:
        parts.append(f"[0:v]setpts=PTS/{speed},split={n}"
                     + "".join(f"[vs{i}]" for i in range(n)))
        parts.append(f"[0:a]atempo={speed},asplit={n}"
                     + "".join(f"[as{i}]" for i in range(n)))

    labels: list[str] = []
    for i, (s, e) in enumerate(keep):
        dur = e - s
        fd = min(fade, dur / 3)
        parts.append(
            f"[vs{i}]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        parts.append(
            f"[as{i}]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:curve=tri:st=0:d={fd:.3f},"
            f"afade=t=out:curve=tri:st={dur-fd:.3f}:d={fd:.3f}[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")

    concat = "".join(labels) + f"concat=n={n}:v=1:a=1[vc][ac]"
    audio_chain_parts = [f"[ac]highpass=f={highpass_hz}"]
    if compressor_ratio > 1.0:
        audio_chain_parts.append(
            f"acompressor=threshold={compressor_threshold_db}dB:"
            f"ratio={compressor_ratio}:attack=10:release=200:makeup=2"
        )
    if deess_db < 0:
        audio_chain_parts.append(f"equalizer=f=6500:t=q:w=3:g={deess_db}")
    audio_chain_parts.append(f"loudnorm=I={loudnorm_i}:TP={loudnorm_tp}:LRA=11")
    audio_post = ",".join(audio_chain_parts) + "[aout]"

    filter_complex = ";".join(parts + [concat, audio_post])

    cmd = [
        ffmpeg, "-y", "-hide_banner",
        "-i", str(src),
        "-filter_complex", filter_complex,
        "-map", "[vc]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(dst),
    ]

    r = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise RuntimeError("ffmpeg render failed")

    out = subprocess.check_output(
        [ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(dst)],
        text=True,
    ).strip()
    return float(out)
