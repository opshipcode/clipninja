def timestamp_to_ms(ts):
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return (int(parts[0]) * 60 + int(parts[1])) * 1000
    elif len(parts) == 3:
        return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
    return 0


def snap_to_nearest(ts_ms, transcript):
    """Find the closest real transcript timestamp to the given ms value."""
    closest = min(transcript, key=lambda x: abs(x["ms"] - ts_ms))
    return closest["timestamp"], closest["ms"]


def validate_timestamps(segments, transcript):
    """
    Validate every timestamp in segments against the real transcript.
    Snap any invalid or missing timestamps to the nearest real one.
    """
    real_ms_set = {line["ms"] for line in transcript}

    def validate_ts(ts):
        ms = timestamp_to_ms(ts)
        if ms in real_ms_set:
            return ts
        snapped_ts, snapped_ms = snap_to_nearest(ms, transcript)
        return snapped_ts

    for seg in segments:
        # Validate hook
        if "hook" in seg and seg["hook"]:
            seg["hook"]["start"] = validate_ts(seg["hook"]["start"])
            seg["hook"]["end"] = validate_ts(seg["hook"]["end"])

        # Validate bridge
        if "bridge" in seg and seg["bridge"]:
            seg["bridge"]["start"] = validate_ts(seg["bridge"]["start"])
            seg["bridge"]["end"] = validate_ts(seg["bridge"]["end"])

        # Validate all segments
        for s in seg.get("segments", []):
            s["start"] = validate_ts(s["start"])
            s["end"] = validate_ts(s["end"])

    return segments
