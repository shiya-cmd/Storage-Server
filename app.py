import os
import uuid
import threading
import subprocess
from queue import Queue
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

video_queue = Queue()
job_status = {}  # job_id → status

# ----------------------------
# Compression Function
# ----------------------------
def compress_video(input_path, output_path):
    command = [
        "ffmpeg",
        "-i", input_path,

        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease",

        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "slow",

        "-profile:v", "high",
        "-level", "4.1",

        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "128k",

        "-movflags", "+faststart",

        output_path
    ]

    result = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        print("FFmpeg ERROR:\n", result.stderr) 
    
    return result.returncode == 0


# ----------------------------
# Worker Thread
# ----------------------------
def worker():
    while True:
        job_id, file_path = video_queue.get()

        temp_output = file_path.replace(".mp4", "_compressed.mp4")

        try:
            print(f"Processing: {file_path}")
            job_status[job_id] = "processing"

            result = compress_video(file_path, temp_output)

            if result == "completed" and os.path.exists(temp_output):
                os.remove(file_path)
                os.rename(temp_output, file_path)

                job_status[job_id] = "completed"
                print(f"Compressed: {file_path}")

            elif result == "timeout":
                job_status[job_id] = "timeout"
                print(f"Timeout: {file_path}")

                if os.path.exists(temp_output):
                    os.remove(temp_output)

            else:  # failed
                job_status[job_id] = "failed"
                print(f"Compression failed, keeping original: {file_path}")

                if os.path.exists(temp_output):
                    os.remove(temp_output)

        except Exception as e:
            job_status[job_id] = f"error: {str(e)}"
            print("Worker error:", e)

            if os.path.exists(temp_output):
                os.remove(temp_output)

        finally:
            video_queue.task_done()


# Start background worker
threading.Thread(target=worker, daemon=True).start()


# ----------------------------
# Upload Endpoint
# ----------------------------
@app.route("/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file"}), 400

    file = request.files["video"]

    job_id = str(uuid.uuid4())
    filename = f"{job_id}.mp4"
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    file.save(filepath)

    # Add to queue
    job_status[job_id] = "queued"
    video_queue.put((job_id, filepath))

    return jsonify({
        "status": "uploaded",
        "video_url": f"/video/{filename}",
        "job_id": job_id
    })


# ----------------------------
# Status Endpoint (optional)
# ----------------------------
@app.route("/status/<job_id>")
def get_status(job_id):
    return jsonify({
        "job_id": job_id,
        "status": job_status.get(job_id, "not_found")
    })


# ----------------------------
# Serve Video
# ----------------------------
@app.route("/video/<filename>")
def serve_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ----------------------------
# Run App
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
