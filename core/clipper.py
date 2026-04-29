import os
import subprocess
import tempfile

WORKSPACE = "workspace"

def timestamp_to_seconds(ts):
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def cut_segment(video_path, start_ts, end_ts, out_path):
    """Cut a single segment from the source video."""
    start_s = timestamp_to_seconds(start_ts)
    end_s = timestamp_to_seconds(end_ts)
    duration = end_s - start_s

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_s),
        "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",          # Quality: 18=high, 28=lower. 23 is great balance
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def concat_segments(segment_paths, out_path):
    """Concatenate multiple segments into one video."""
    if len(segment_paths) == 1:
        os.rename(segment_paths[0], out_path)
        return out_path

    # Write concat list file
    list_path = out_path + "_list.txt"
    with open(list_path, "w") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    os.remove(list_path)
    return out_path


def apply_crop_and_captions(video_path, out_path, caption_file=None):
    """
    Crop to 85% landscape width (centered) and optionally burn captions.
    This creates the short-form aspect ratio — not full landscape, not portrait.
    """
    # Get video dimensions
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", video_path
    ]
    import json
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    orig_w = int(video_stream["width"])
    orig_h = int(video_stream["height"])

    # 85% of width, centered, keep full height
    new_w = int(orig_w * 0.85)
    # Make width even (required by h264)
    if new_w % 2 != 0:
        new_w -= 1
    x_offset = (orig_w - new_w) // 2

    crop_filter = f"crop={new_w}:{orig_h}:{x_offset}:0"

    if caption_file and os.path.exists(caption_file):
        vf = f"{crop_filter},subtitles={caption_file}:force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1,Alignment=2'"
    else:
        vf = crop_filter

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def generate_captions(video_path, srt_path):
    """Generate SRT captions using Whisper on the clip."""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(video_path, word_timestamps=True)

        with open(srt_path, "w") as f:
            idx = 1
            for seg in result["segments"]:
                start = format_srt_time(seg["start"])
                end = format_srt_time(seg["end"])
                text = seg["text"].strip()
                f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
                idx += 1
        return srt_path
    except Exception:
        return None


def format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cut_clips(video_path, segment_data, job_id, clip_index):
    """
    Full pipeline for one clip:
    1. Cut hook (if clip 1)
    2. Cut bridge (if clip 2+)
    3. Cut all main segments
    4. Concat everything
    5. Crop to 85% width
    6. Burn captions
    """
    out_dir = os.path.join(WORKSPACE, "output", job_id)
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = os.path.join(WORKSPACE, "downloads", job_id, f"tmp_clip_{clip_index}")
    os.makedirs(tmp_dir, exist_ok=True)

    parts = []
    part_idx = 0

    # Cut hook (clip 1 only)
    if "hook" in segment_data and segment_data["hook"]:
        hook = segment_data["hook"]
        hook_path = os.path.join(tmp_dir, f"hook.mp4")
        cut_segment(video_path, hook["start"], hook["end"], hook_path)
        parts.append(hook_path)
        part_idx += 1

    # Cut bridge (clip 2+)
    if "bridge" in segment_data and segment_data["bridge"]:
        bridge = segment_data["bridge"]
        bridge_path = os.path.join(tmp_dir, f"bridge.mp4")
        cut_segment(video_path, bridge["start"], bridge["end"], bridge_path)
        parts.append(bridge_path)
        part_idx += 1

    # Cut main segments
    for i, seg in enumerate(segment_data.get("segments", [])):
        seg_path = os.path.join(tmp_dir, f"seg_{i}.mp4")
        cut_segment(video_path, seg["start"], seg["end"], seg_path)
        parts.append(seg_path)

    # Concatenate all parts
    raw_clip_path = os.path.join(tmp_dir, "raw_clip.mp4")
    concat_segments(parts, raw_clip_path)

    # Generate captions on the raw concat clip
    srt_path = os.path.join(tmp_dir, "captions.srt")
    caption_file = generate_captions(raw_clip_path, srt_path)

    # Apply crop + captions
    safe_title = "".join(c for c in segment_data.get("title", f"clip_{clip_index}") if c.isalnum() or c in " _-")[:40]
    final_filename = f"clip_{clip_index}_{safe_title.replace(' ', '_')}.mp4"
    final_path = os.path.join(out_dir, final_filename)
    apply_crop_and_captions(raw_clip_path, final_path, caption_file)

    return final_path
