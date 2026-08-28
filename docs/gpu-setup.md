# GPU setup

The system runs on CPU by default. A GPU is optional for one or two cameras and
effectively required from about four (see [hardware.md](hardware.md)).

`AI_DEVICE=auto` — the default — uses CUDA when it is genuinely available and
falls back to CPU otherwise. It never fails to start because a GPU is missing.

## NVIDIA Container Toolkit (Docker)

Required only if the AI worker runs in Docker and should use the GPU.

### Linux

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### Windows

Use WSL2 with a recent NVIDIA driver on the Windows host. Do not install a
driver inside WSL. Docker Desktop with the WSL2 backend then exposes the GPU.

## Enabling it

Uncomment the `reservations.devices` block, nested under the same
`deploy.resources` key as the worker's CPU/memory limit (Phase 10), in
`docker-compose.ai.yml`, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml up -d ai-worker
```

Set `AI_DEVICE=cuda` in `.env` to make a missing GPU a loud failure instead of a
silent CPU fallback — worth doing on a machine that was bought for its GPU,
where quietly running at a tenth of the speed is the worse outcome.

## Without Docker

`ai_worker/requirements.txt` installs the CPU build of torch by default (from
PyTorch's own CPU-only package index). For a GPU, install a CUDA-enabled torch
build matching your driver *before* running `pip install -r requirements.txt`
— pip keeps whichever compatible version is already satisfied rather than
downgrading it back to CPU:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124  # match your CUDA version
pip install -r ai_worker/requirements.txt
```

## Checking what it chose

`worker_starting` logs the *requested* device (`auto`, `cpu`, or `cuda`) as
configured. The line that reports what was actually resolved and loaded is
`detector_loaded`, once the model has finished loading:

```
worker_starting id=worker-1 cafe=... device=auto target_fps=10.0
detector_loaded model=yolo11n.pt device=cpu confidence=0.50
```

Tracking (`AI_TRACKER=bytetrack`, or `botsort`) builds one tracker per camera
right after the detector loads, and needs no model weights of its own —
ByteTrack and BoT-SORT are Kalman-filter/IoU math, not neural networks. A
tracker failing to build (rare; would indicate an ultralytics version
mismatch) degrades the same way a failed detector does: that camera keeps
capturing and previewing, just without `track_count` in its `camera_stats`.

If `AI_DEVICE=auto` resolved to `cpu` on a machine you expected to have a
working GPU, `torch.cuda.is_available()` is returning False — check the driver
and the Container Toolkit installation above before assuming the software is
at fault.

## When the model does not load at all

A missing model is not a startup crash: the worker falls back to capture-only
mode automatically (camera capture and the live preview keep working; there is
just no detection). Look for one of:

```
detector_device_unavailable error=AI_DEVICE=cuda was requested but no CUDA device is available...
detector_load_failed model=yolo11n.pt device=cpu -- continuing in capture-only mode
```

The most common cause on a fresh install is no internet access at the moment
the model weights are first downloaded (~5 MB, from GitHub). Once downloaded,
the weights are cached in `AI_MODELS_DIR` (the `ai_models` Docker volume) and
never re-fetched, so the café can go fully offline afterward.

`/api/v1/events/` will show `worker_started` with `"capabilities": ["camera_capture"]`
(no `"person_detection"`, no `"multi_object_tracking"`) whenever this happens —
the authoritative, honest signal, checked at runtime rather than assumed from
configuration. Tracking has no separate toggle: it runs automatically
whenever detection does, so the two capabilities always appear together.

## Tuning

1. **Lower `AI_TARGET_FPS` first.** From 10 to 6 is a 40% load reduction and
   costs very little in a room where people sit.
2. **Use a smaller model.** YOLO11n over YOLO11s over YOLO11m. In a fixed indoor
   scene the accuracy difference for person detection is small.
3. **Split cameras across two workers.** They are independent processes; the
   consumer group handles the rest.
4. **Watch the event stream depth** on the dashboard health panel. A growing
   backlog is the earliest sign the machine is over-subscribed — earlier than
   anything customers would notice.
