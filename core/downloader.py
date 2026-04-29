import os
import json
import subprocess
import yt_dlp

WORKSPACE = "workspace"

def download_video(youtube_url, job_id):
    out_dir = os.path.join(WORKSPACE, "downloads", job_id)
    os.makedirs(out_dir, exist_ok=True)
    video_path = os.path.join(out_dir, "video.mp4")

    ydl_opts = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": video_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        meta = {
            "title": info.get("title", ""),
            "description": info.get("description", "")[:2000],
            "duration": info.get("duration", 0),
            "chapters": info.get("chapters", []),
            "uploader": info.get("uploader", ""),
        }

    return video_path, meta


def get_transcript(youtube_url, video_path, job_id):
    """Try YouTube native subtitles first, fallback to Whisper."""
    out_dir = os.path.join(WORKSPACE, "transcripts", job_id)
    os.makedirs(out_dir, exist_ok=True)
    transcript_path = os.path.join(out_dir, "transcript.json")

    # Try native YT subtitles
    try:
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": ["en"],
            "skip_download": True,
            "outtmpl": os.path.join(out_dir, "subs"),
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        # Parse subtitle file
        sub_file = os.path.join(out_dir, "subs.en.json3")
        if os.path.exists(sub_file):
            with open(sub_file) as f:
                raw = json.load(f)
            lines = []
            for event in raw.get("events", []):
                if "segs" in event:
                    start_ms = event.get("tStartMs", 0)
                    text = "".join(s.get("utf8", "") for s in event["segs"]).strip()
                    if text and text != "\n":
                        timestamp = ms_to_timestamp(start_ms)
                        lines.append({"timestamp": timestamp, "text": text, "ms": start_ms})
            if lines:
                with open(transcript_path, "w") as f:
                    json.dump(lines, f, indent=2)
                return lines
    except Exception:
        pass

    # Fallback: Whisper
    return whisper_transcribe(video_path, transcript_path)


def whisper_transcribe(video_path, transcript_path):
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(video_path, word_timestamps=True)
    lines = []
    for seg in result["segments"]:
        timestamp = seconds_to_timestamp(seg["start"])
        lines.append({
            "timestamp": timestamp,
            "text": seg["text"].strip(),
            "ms": int(seg["start"] * 1000)
        })
    with open(transcript_path, "w") as f:
        json.dump(lines, f, indent=2)
    return lines


def ms_to_timestamp(ms):
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def seconds_to_timestamp(s):
    return ms_to_timestamp(int(s * 1000))
