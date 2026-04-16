import os
import uuid
import threading
import subprocess
from queue import Queue
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)


UPLOAD_FOLDER = "uploads"
IMAGE_FOLDER = "images"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

video_queue = Queue()
job_status = {}

# ----------------------------
# Compression Function (Video)
# ----------------------------
def compress_video(input_path, output_path):
    command = [
        "ffmpeg",
        "-y",
        "-i", input_path,

        # Safe universal scaling
        "-vf", "scale='if(gt(iw,1080),1080,iw)':-2",

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

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        stdout, stderr = process.communicate(timeout=300)

        if process.returncode != 0:
            print("FFmpeg ERROR:\n", stderr)
            return "failed"

        return "completed"

    except subprocess.TimeoutExpired:
        print("FFmpeg timeout, killing process...")
        process.kill()
        process.communicate()
        return "timeout"


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
            print(f"Job {job_id} → {result}")

            if result == "completed" and os.path.exists(temp_output):
                os.remove(file_path)
                os.rename(temp_output, file_path)

                job_status[job_id] = "completed"
                print(f"Compressed: {file_path}")

            elif result == "timeout":
                job_status[job_id] = "timeout"
                print(f"Timeout: keeping original {file_path}")

                if os.path.exists(temp_output):
                    os.remove(temp_output)

            else:
                job_status[job_id] = "failed"
                print(f"Compression failed: keeping original {file_path}")

                if os.path.exists(temp_output):
                    os.remove(temp_output)

        except Exception as e:
            job_status[job_id] = f"error: {str(e)}"
            print("Worker error:", e)

            if os.path.exists(temp_output):
                os.remove(temp_output)

        finally:
            video_queue.task_done()


# Start worker
threading.Thread(target=worker, daemon=True).start()


# ----------------------------
# Upload Video
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

    job_status[job_id] = "queued"
    video_queue.put((job_id, filepath))

    return jsonify({
        "status": "uploaded",
        "video_url": f"/video/{filename}",
        "job_id": job_id
    })


# ----------------------------
# Upload Image (NO compression)
# ----------------------------
@app.route("/upload/image", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400

    file = request.files["image"]

    ext = file.filename.split(".")[-1].lower()
    allowed = {"jpg", "jpeg", "png", "webp"}

    if ext not in allowed:
        return jsonify({"error": "Invalid image type"}), 400

    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(IMAGE_FOLDER, filename)

    file.save(filepath)

    return jsonify({
        "status": "uploaded",
        "image_url": f"/image/{filename}"
    })


# ----------------------------
# Status API
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
# Serve Image
# ----------------------------
@app.route("/image/<filename>")
def serve_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)


# ----------------------------
# Run App
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
