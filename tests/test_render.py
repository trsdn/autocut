"""ffmpeg filter graph construction for the final render."""
from __future__ import annotations

import subprocess

import pytest

from autocut.render import render


class _Result:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture
def captured(monkeypatch):
    """Run render() without ffmpeg, capturing the command it would have run."""
    calls: dict[str, list] = {"run": [], "probe": []}

    def fake_run(cmd, **kwargs):
        calls["run"].append(cmd)
        return _Result(0)

    def fake_check_output(cmd, **kwargs):
        calls["probe"].append(cmd)
        return "42.5\n"

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    return calls


def filter_graph(calls) -> str:
    cmd = calls["run"][0]
    return cmd[cmd.index("-filter_complex") + 1]


def test_render_returns_the_probed_output_duration(tmp_path, captured):
    out = render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
                 keep=[(0.0, 5.0)])

    assert out == pytest.approx(42.5)


def test_the_duration_is_probed_with_ffprobe_not_ffmpeg(tmp_path, captured):
    render(ffmpeg="/opt/bin/ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 5.0)])

    assert captured["probe"][0][0] == "/opt/bin/ffprobe"


def test_a_failing_ffmpeg_raises_rather_than_reporting_success(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Result(1, "boom"))

    with pytest.raises(RuntimeError, match="ffmpeg render failed"):
        render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
               keep=[(0.0, 5.0)])


# --------------------------------------------------------------------------
# Splitting and speed
# --------------------------------------------------------------------------
def test_streams_are_split_once_per_kept_segment(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0), (2.0, 3.0), (5.0, 6.0)])

    graph = filter_graph(captured)
    assert "[0:v]split=3[vs0][vs1][vs2]" in graph
    assert "[0:a]asplit=3[as0][as1][as2]" in graph


def test_unit_speed_adds_no_resampling_filters(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], speed=1.0)

    graph = filter_graph(captured)
    assert "setpts=PTS/" not in graph
    assert "atempo" not in graph


def test_non_unit_speed_scales_both_video_and_audio(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], speed=1.05)

    graph = filter_graph(captured)
    assert "[0:v]setpts=PTS/1.05,split=1[vs0]" in graph
    assert "[0:a]atempo=1.05,asplit=1[as0]" in graph


# --------------------------------------------------------------------------
# Trimming, fading and concat
# --------------------------------------------------------------------------
def test_each_segment_is_trimmed_to_its_keep_range(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(1.5, 4.25)])

    graph = filter_graph(captured)
    assert "[vs0]trim=start=1.500:end=4.250,setpts=PTS-STARTPTS[v0]" in graph
    assert "[as0]atrim=start=1.500:end=4.250" in graph


def test_segments_are_concatenated_in_order(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0), (2.0, 3.0)])

    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]" in filter_graph(captured)


def test_audio_fades_in_at_the_start_and_out_at_the_end_of_each_segment(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 3.0)], fade=0.040)

    graph = filter_graph(captured)
    assert "afade=t=in:curve=tri:st=0:d=0.040" in graph
    # 3.0 s segment, 0.04 s fade -> fade-out starts at 2.96.
    assert "afade=t=out:curve=tri:st=2.960:d=0.040" in graph


def test_the_fade_is_clamped_so_it_cannot_exceed_a_third_of_a_short_segment(tmp_path, captured):
    """Without clamping, the in/out fades on a 90 ms cut would overlap."""
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 0.09)], fade=0.040)

    graph = filter_graph(captured)
    assert "afade=t=in:curve=tri:st=0:d=0.030" in graph
    assert "afade=t=out:curve=tri:st=0.060:d=0.030" in graph


# --------------------------------------------------------------------------
# Audio post chain
# --------------------------------------------------------------------------
def test_the_audio_chain_runs_highpass_then_loudnorm(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], highpass_hz=80, loudnorm_i=-16.0, loudnorm_tp=-1.5)

    graph = filter_graph(captured)
    assert "[ac]highpass=f=80" in graph
    assert "loudnorm=I=-16.0:TP=-1.5:LRA=11[aout]" in graph
    assert graph.index("highpass") < graph.index("loudnorm")


def test_the_compressor_is_omitted_at_a_ratio_of_one(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], compressor_ratio=1.0)

    assert "acompressor" not in filter_graph(captured)


def test_the_compressor_is_included_above_a_ratio_of_one(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], compressor_ratio=2.5, compressor_threshold_db=-22.0)

    assert "acompressor=threshold=-22.0dB:ratio=2.5" in filter_graph(captured)


def test_the_de_esser_is_omitted_when_its_gain_is_not_a_cut(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], deess_db=0.0)

    assert "equalizer" not in filter_graph(captured)


def test_the_de_esser_notches_sibilance_when_negative(tmp_path, captured):
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=tmp_path / "b.mp4",
           keep=[(0.0, 1.0)], deess_db=-2.5)

    assert "equalizer=f=6500:t=q:w=3:g=-2.5" in filter_graph(captured)


# --------------------------------------------------------------------------
# Output options
# --------------------------------------------------------------------------
def test_encoder_settings_are_forwarded_and_the_graph_outputs_are_mapped(tmp_path, captured):
    dst = tmp_path / "out.mp4"
    render(ffmpeg="ffmpeg", src=tmp_path / "a.mp4", dst=dst,
           keep=[(0.0, 1.0)], crf=18, preset="slow", audio_bitrate="192k")

    cmd = captured["run"][0]
    assert cmd[cmd.index("-crf") + 1] == "18"
    assert cmd[cmd.index("-preset") + 1] == "slow"
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "[vc]" in cmd and "[aout]" in cmd
    # Web-friendly: move the moov atom to the front.
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert cmd[-1] == str(dst)
