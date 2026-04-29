import os
import json
import threading
import time
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from core.downloader import download_video, get_transcript
from core.segmenter import segment_with_gemini
from core.validator import validate_timestamps
from core.clipper import cut_clips

app = Flask(__name__, static_folder="static")
CORS(app)

# In-memory progress store per job
jobs = {}

def run_pipeline(job_id, youtube_url, gemini_key, num_clips, min_dur, max_dur, per_clip_durations):
    def update(stage, status, message, extra=None):
        if job_id not in jobs:
            jobs[job_id] = {"stages": [], "clips": [], "error": None}
        entry = {"stage": stage, "status": status, "message": message}
        if extra:
            entry.update(extra)
        # Update existing stage or append
        existing = next((s for s in jobs[job_id]["stages"] if s["stage"] == stage), None)
        if existing:
            existing.update(entry)
        else:
            jobs[job_id]["stages"].append(entry)

    try:
        jobs[job_id] = {"stages": [], "clips": [], "error": None}

        # Stage 1: Fetch metadata + download
        update("download", "active", "Fetching video and transcript from YouTube...")
        video_path, meta = download_video(youtube_url, job_id)
        update("download", "done", f"Video downloaded — {meta['title'][:50]}", {"meta": meta})

        # Stage 2: Transcript
        update("transcript", "active", "Extracting transcript with timestamps...")
        transcript = get_transcript(youtube_url, video_path, job_id)
        update("transcript", "done", f"Transcript extracted — {len(transcript)} lines")

        # Stage 3: AI Segmentation
        update("segmentation", "active", "Gemini is analysing and segmenting the video...")
        segments = segment_with_gemini(
            transcript, meta, gemini_key,
            num_clips, min_dur, max_dur, per_clip_durations
        )
        update("segmentation", "done", f"AI returned {len(segments)} clip plans")

        # Stage 4: Validate timestamps
        update("validation", "active", "Validating timestamps against transcript...")
        segments = validate_timestamps(segments, transcript)
        update("validation", "done", "All timestamps verified")

        # Stage 5: Cut clips
        for i, seg in enumerate(segments):
            update(f"clip_{i+1}", "active", f"Cutting clip {i+1} of {len(segments)}...")
            clip_path = cut_clips(video_path, seg, job_id, i+1)
            seg["clip_path"] = clip_path
            seg["clip_index"] = i + 1
            jobs[job_id]["clips"].append({
                "index": i + 1,
                "path": clip_path,
                "title": seg.get("title", f"Clip {i+1}"),
                "tags": seg.get("tags", []),
                "filename": os.path.basename(clip_path)
            })
            update(f"clip_{i+1}", "done", f"Clip {i+1} ready")

        jobs[job_id]["status"] = "complete"

    except Exception as e:
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["status"] = "error"


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/process", methods=["POST"])
def process():
    data = request.json
    youtube_url = data.get("url")
    gemini_key = data.get("gemini_key")
    num_clips = int(data.get("num_clips", 3))
    min_dur = int(data.get("min_dur", 60))
    max_dur = int(data.get("max_dur", 120))
    per_clip_durations = data.get("per_clip_durations", None)

    if not youtube_url or not gemini_key:
        return jsonify({"error": "URL and Gemini key required"}), 400

    job_id = f"job_{int(time.time())}"
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, youtube_url, gemini_key, num_clips, min_dur, max_dur, per_clip_durations)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})

@app.route("/api/progress/<job_id>")
def progress(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])

@app.route("/api/download/<job_id>/<filename>")
def download_clip(job_id, filename):
    output_dir = os.path.join("workspace", "output", job_id)
    return send_file(
        os.path.join(output_dir, filename),
        as_attachment=True,
        download_name=filename
    )

@app.route("/api/preview/<job_id>/<filename>")
def preview_clip(job_id, filename):
    output_dir = os.path.join("workspace", "output", job_id)
    return send_file(
        os.path.join(output_dir, filename),
        mimetype="video/mp4"
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
