import json
import google.generativeai as genai


def segment_with_gemini(transcript, meta, gemini_key, num_clips, min_dur, max_dur, per_clip_durations=None):
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel("gemini-1.5-pro")

    # Build transcript text
    transcript_text = "\n".join(
        f"[{line['timestamp']}] {line['text']}" for line in transcript
    )

    # Build duration instructions
    if per_clip_durations:
        dur_instructions = "Per-clip duration requirements:\n"
        for i, d in enumerate(per_clip_durations):
            dur_instructions += f"  Clip {i+1}: {d['min']}s to {d['max']}s\n"
    else:
        dur_instructions = f"Each clip must be between {min_dur} and {max_dur} seconds total."

    prompt = f"""You are a professional video editor. You will receive a YouTube video transcript with timestamps and your job is to split it into exactly {num_clips} short-form clips suitable for TikTok and YouTube Shorts.

VIDEO TITLE: {meta['title']}
VIDEO DESCRIPTION: {meta['description'][:500]}

TRANSCRIPT:
{transcript_text}

INSTRUCTIONS:
1. Split into exactly {num_clips} clips.
2. {dur_instructions}
3. Each clip must be a COMPLETE standalone narrative — clear beginning, middle, and payoff.
4. You may SKIP lines between segments as long as the story remains coherent and complete.
5. Identify one HOOK moment from ANY part of the video (not necessarily the beginning) that is shocking, surprising, or creates strong curiosity. This will play at the START of clip 1 before the main body.
6. For clips 2 onwards, include a BRIDGE — the last 4-6 seconds of the previous clip — to orient new viewers.
7. No clip should start or end mid-sentence.
8. Suggest a punchy title and relevant hashtags for each clip.

OUTPUT FORMAT:
Return ONLY a valid JSON array. No markdown. No explanation. No backticks. Just the raw JSON.

[
  {{
    "clip": 1,
    "hook": {{"start": "MM:SS", "end": "MM:SS"}},
    "segments": [
      {{"start": "MM:SS", "end": "MM:SS"}},
      {{"start": "MM:SS", "end": "MM:SS"}}
    ],
    "title": "Punchy clip title here",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
  }},
  {{
    "clip": 2,
    "bridge": {{"start": "MM:SS", "end": "MM:SS"}},
    "segments": [
      {{"start": "MM:SS", "end": "MM:SS"}}
    ],
    "title": "Punchy clip title here",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
  }}
]

CRITICAL RULES:
- Every timestamp MUST exist in the transcript provided.
- hook must come from OUTSIDE clip 1's main segments.
- Return exactly {num_clips} clip objects.
- Timestamps must be in MM:SS format or HH:MM:SS for videos over 1 hour.
- JSON must be valid and parseable.
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    segments = json.loads(raw)
    return segments
