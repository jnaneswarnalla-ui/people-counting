
const videoInput = document.getElementById("videoInput");
const videoForm = document.getElementById("videoForm");
const dropzone = document.getElementById("dropzone");
const fileLabel = document.getElementById("fileLabel");
const fileDetails = document.getElementById("fileDetails");
const selectedFile = document.getElementById("selectedFile");
const selectedName = document.getElementById("selectedName");
const selectedSize = document.getElementById("selectedSize");
const processBtn = document.getElementById("processBtn");
const clearBtn = document.getElementById("clearBtn");
const removeFile = document.getElementById("removeFile");
const message = document.getElementById("message");
const progressArea = document.getElementById("progressArea");
const results = document.getElementById("results");
const outputVideo = document.getElementById("outputVideo");
const outputPlaceholder = document.getElementById("outputPlaceholder");
const downloadBtn = document.getElementById("downloadBtn");

const MAX_SIZE = 500 * 1024 * 1024;
const ALLOWED_EXTENSIONS = ["mp4", "avi", "mov", "mkv"];

// Leave empty when the backend serves this page (same origin).
// If the frontend is hosted separately, set: window.API_BASE = "https://your-backend.com"
const API_BASE = window.API_BASE || "";

let selectedVideo = null;
let currentRun = 0;   // lets us cancel polling when the user clears the video

// Display messages.
function showMessage(text, type = "") {
    message.textContent = text;
    message.className = `message ${type}`;
}

// Clear the previous video's results.
function clearResults() {
    results.hidden = true;

    outputVideo.pause();
    outputVideo.removeAttribute("src");
    outputVideo.load();
    outputVideo.hidden = true;

    outputPlaceholder.hidden = false;

    downloadBtn.hidden = true;
    downloadBtn.removeAttribute("href");

    document.getElementById("entries").textContent = "—";
    document.getElementById("exits").textContent = "—";
    document.getElementById("occupancy").textContent = "—";
    document.getElementById("resultVideoName").textContent = "";
}

// Validate the selected video.
function validateVideo(file) {
    if (!file) {
        return "Please select a video first.";
    }

    const extension = file.name.split(".").pop().toLowerCase();

    if (!ALLOWED_EXTENSIONS.includes(extension)) {
        return "Please select an MP4, AVI, MOV or MKV video.";
    }

    if (file.size > MAX_SIZE) {
        return "The video must not exceed 500 MB.";
    }

    if (file.size === 0) {
        return "The selected video is empty.";
    }

    return "";
}

// Select a video.
function selectVideo(file) {
    clearResults();
    showMessage("");
    selectedVideo = null;

    if (!file) {
        resetFileDetails();
        return;
    }

    const error = validateVideo(file);

    if (error) {
        videoInput.value = "";
        resetFileDetails();
        showMessage(error, "error");
        return;
    }

    selectedVideo = file;

    fileLabel.textContent = file.name;
    fileDetails.textContent = "Video selected successfully";

    selectedFile.hidden = false;
    selectedName.textContent = file.name;
    selectedSize.textContent =
        `${(file.size / (1024 * 1024)).toFixed(2)} MB`;
}

function resetFileDetails() {
    fileLabel.textContent = "Choose a video from your computer";
    fileDetails.textContent = "MP4, AVI, MOV or MKV · Up to 500 MB";

    selectedFile.hidden = true;
    selectedName.textContent = "";
    selectedSize.textContent = "";
}

// File picker.
videoInput.addEventListener("change", () => {
    selectVideo(videoInput.files[0]);
});

// Drag-and-drop support.
["dragenter", "dragover"].forEach(eventName => {
    dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.add("drag-over");
    });
});

["dragleave", "drop"].forEach(eventName => {
    dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.remove("drag-over");
    });
});

dropzone.addEventListener("drop", event => {
    const file = event.dataTransfer.files[0];

    if (!file) return;

    const transfer = new DataTransfer();
    transfer.items.add(file);
    videoInput.files = transfer.files;

    selectVideo(file);
});

// Remove the selected video.
function clearSelection() {
    currentRun++;
    selectedVideo = null;
    videoInput.value = "";

    resetFileDetails();
    clearResults();

    progressArea.hidden = true;
    processBtn.disabled = false;

    showMessage("Ready to select another video.");
}

removeFile.addEventListener("click", clearSelection);
clearBtn.addEventListener("click", clearSelection);

// Upload the video, then poll the backend until processing finishes.
videoForm.addEventListener("submit", async event => {
    event.preventDefault();

    if (!selectedVideo) {
        showMessage("Please select a video first.", "error");
        return;
    }

    const run = ++currentRun;
    clearResults();
    showMessage("");
    window.showProcessing(true, "Uploading video...");

    const formData = new FormData();
    formData.append("video", selectedVideo);
    formData.append("direction", document.getElementById("lineDirection").value);
    formData.append("position", document.getElementById("linePosition").value / 100);
    formData.append("invert", document.getElementById("invertDirection").checked);

    try {
        const response = await fetch(`${API_BASE}/api/process`, {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || "Upload failed.");
        }

        const { job_id } = await response.json();

        while (run === currentRun) {
            await new Promise(resolve => setTimeout(resolve, 1500));
            if (run !== currentRun) return;

            const poll = await fetch(`${API_BASE}/api/jobs/${job_id}`);
            if (!poll.ok) throw new Error("Lost connection to the server.");
            const job = await poll.json();

            if (job.status === "error") {
                throw new Error(job.error || "Processing failed.");
            }

            if (job.status === "done") {
                const result = job.result;
                result.video_name = job.video_name;
                result.output_url = API_BASE + result.output_url;
                displayResults(result);
                break;
            }

            const text = job.status === "queued"
                ? "Waiting in queue..."
                : `Processing video... ${job.progress}%`;
            window.showProcessing(true, text);
        }
    } catch (error) {
        if (run === currentRun) showMessage(error.message, "error");
    } finally {
        if (run === currentRun) window.showProcessing(false);
    }
});

// Call this function after the backend returns real results.
//
// Expected response:
// {
//   video_name: "video1.mp4",
//   entries: 45,
//   exits: 18,
//   occupancy: 27,
//   output_url: "/outputs/video1_processed.mp4"
// }

function displayResults(data) {
    if (
        !data ||
        !Number.isInteger(data.entries) ||
        !Number.isInteger(data.exits) ||
        !Number.isInteger(data.occupancy) ||
        !data.output_url
    ) {
        showMessage("The backend returned invalid results.", "error");
        return;
    }

    document.getElementById("entries").textContent = data.entries;
    document.getElementById("exits").textContent = data.exits;
    document.getElementById("occupancy").textContent = data.occupancy;

    document.getElementById("resultVideoName").textContent =
        "Results for: " + (data.video_name || selectedVideo?.name || "Video");

    // Display this video's processed output.
    outputVideo.pause();
    outputVideo.src = data.output_url;
    outputVideo.hidden = false;
    outputVideo.load();

    outputPlaceholder.hidden = true;

    downloadBtn.href = data.output_url;
    downloadBtn.download = "processed_video.mp4";
    downloadBtn.hidden = false;

    results.hidden = false;

    showMessage("Video processing completed successfully.", "success");

    results.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

// Helpers for your teammate's backend integration.
window.displayResults = displayResults;

window.showProcessing = function (isProcessing, text = "Processing video...") {
    progressArea.hidden = !isProcessing;
    processBtn.disabled = isProcessing;

    document.getElementById("progressText").textContent = text;
};
