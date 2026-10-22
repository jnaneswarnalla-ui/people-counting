"""People counting logic (ported from the Colab notebook, Cell 23)."""
import os
import subprocess

import cv2
import supervision as sv
from trackers import ByteTrackTracker

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"


def _to_browser_mp4(raw_path, final_path):
    """OpenCV's mp4v output will not play in browsers. Re-encode to H.264."""
    cmd = [
        FFMPEG, "-y", "-i", raw_path,
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
        final_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(raw_path)
    except Exception as exc:
        print("ffmpeg failed, using raw OpenCV output:", exc)
        os.replace(raw_path, final_path)


def process_video(model, input_path, output_path, direction="horizontal",
                  position=0.5, invert=False, conf=0.35, device="cpu",
                  progress_cb=None):
    if direction not in ("horizontal", "vertical"):
        raise ValueError("direction must be 'horizontal' or 'vertical'")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError("Cannot open the uploaded video")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if fps <= 0:
        fps = 25

    raw_path = output_path + ".raw.mp4"
    writer = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise ValueError("Could not create output video")

    tracker = ByteTrackTracker(track_activation_threshold=0.25,
                               minimum_consecutive_frames=1)

    entry_count = exit_count = 0
    initial_occupancy = None
    occupancy = 0
    frame_number = 0
    people_in_frame = 0
    person_states = {}
    last_crossing_frame = {}
    tracked_people = set()

    line_value = int(height * position) if direction == "horizontal" \
        else int(width * position)

    box_annotator = sv.BoxAnnotator()
    label_annotator = sv.LabelAnnotator()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model.predict(frame, classes=[0], conf=conf,
                                    device=device, verbose=False)
            detections = sv.Detections.from_ultralytics(results[0])

            if frame_number == 0:
                initial_occupancy = len(detections)
                occupancy = initial_occupancy

            tracked = tracker.update(detections)

            valid_people = []
            if tracked.tracker_id is not None:
                for box, track_id in zip(tracked.xyxy, tracked.tracker_id):
                    track_id = int(track_id)
                    if track_id < 0:
                        continue
                    valid_people.append((box, track_id))
                    tracked_people.add(track_id)

            people_in_frame = len(detections)

            # Line-crossing detection (bottom-centre of each person)
            for box, track_id in valid_people:
                x1, y1, x2, y2 = box
                cx, cy = int((x1 + x2) / 2), int(y2)
                coordinate = cy if direction == "horizontal" else cx
                side = "negative" if coordinate < line_value else "positive"

                if track_id not in person_states:
                    person_states[track_id] = side
                    continue

                prev = person_states[track_id]
                if prev != side:
                    if frame_number - last_crossing_frame.get(track_id, -9999) >= 10:
                        # horizontal: above->below = IN
                        # vertical:   right->left  = IN
                        if direction == "horizontal":
                            is_in = (prev == "negative" and side == "positive")
                        else:
                            is_in = (prev == "positive" and side == "negative")
                        if invert:
                            is_in = not is_in
                        if is_in:
                            entry_count += 1
                        else:
                            exit_count += 1
                        last_crossing_frame[track_id] = frame_number
                    person_states[track_id] = side

            occupancy = initial_occupancy + entry_count - exit_count

            # Draw counting line
            if direction == "horizontal":
                cv2.line(frame, (0, line_value), (width, line_value), (0, 255, 0), 3)
            else:
                cv2.line(frame, (line_value, 0), (line_value, height), (0, 255, 0), 3)

            # Boxes and IDs
            if tracked.tracker_id is not None:
                valid_tracked = tracked[tracked.tracker_id >= 0]
                labels = [f"ID {int(t)}" for t in valid_tracked.tracker_id]
                frame = box_annotator.annotate(scene=frame, detections=valid_tracked)
                frame = label_annotator.annotate(scene=frame,
                                                 detections=valid_tracked,
                                                 labels=labels)

            # Transparent statistics panel
            overlay = frame.copy()
            cv2.rectangle(overlay, (15, 15), (365, 150), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.35, frame, 0.65, 0)
            font, aa = cv2.FONT_HERSHEY_SIMPLEX, cv2.LINE_AA
            cv2.putText(frame, f"Occupancy: {occupancy}", (25, 42), font, 0.6, (0, 255, 255), 2, aa)
            cv2.putText(frame, f"People in Frame: {people_in_frame}", (25, 72), font, 0.6, (255, 255, 255), 2, aa)
            cv2.putText(frame, f"Unique IDs: {len(tracked_people)}", (25, 102), font, 0.6, (255, 255, 255), 2, aa)
            cv2.putText(frame, f"IN: {entry_count}", (25, 132), font, 0.6, (0, 255, 0), 2, aa)
            cv2.putText(frame, f"OUT: {exit_count}", (190, 132), font, 0.6, (0, 0, 255), 2, aa)

            writer.write(frame)
            frame_number += 1

            if progress_cb and frame_number % 5 == 0:
                progress_cb(frame_number, total_frames)
    finally:
        cap.release()
        writer.release()

    if frame_number == 0:
        raise ValueError("The video contains no readable frames")

    if progress_cb:
        progress_cb(frame_number, total_frames or frame_number)
    _to_browser_mp4(raw_path, output_path)

    return {
        "initial_occupancy": initial_occupancy,
        "entries": entry_count,
        "exits": exit_count,
        "occupancy": occupancy,
        "people_tracked": len(tracked_people),
        "frames_processed": frame_number,
    }
