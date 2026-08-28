# Hardware

Sizing depends almost entirely on how many cameras run inference, and at what
rate. Everything else — database, dashboard, event bus — is small.

**The figures below are engineering estimates from the model sizes and target
frame rates, not measurements from this system.** Phase 3 replaces them with
benchmarks taken from real hardware. Treat them as a purchasing guide, and
verify before committing to a large install.

---

## The number that actually matters

Not camera FPS. **Inference FPS** — how many frames per second per camera the
system actually runs the detector on (`AI_TARGET_FPS`, default 10).

A 25 fps camera does not need 25 inferences per second to measure how long
someone sits at a table. Stay time comes from timestamps, so reducing the
inference rate costs tracking robustness during fast movement, not timing
accuracy. 8–10 fps is a good balance for a café; 5 fps is usually still fine for
a room where people sit still.

This is the first knob to turn when a machine is struggling.

---

## Recommended configurations

### 1 camera

| | |
|---|---|
| CPU | 4-core x86-64 (Intel N100, i3-12100, Ryzen 3) |
| RAM | 8 GB |
| Storage | 128 GB SSD |
| GPU | Not required |
| Example | Intel NUC / Beelink mini PC, ~€200–300 |

CPU-only inference with YOLO11n at 5–10 fps is realistic here. This is the
typical single-café install.

### 4 cameras

| | |
|---|---|
| CPU | 6–8 core (i5-12400, Ryzen 5 5600) |
| RAM | 16 GB |
| Storage | 256 GB SSD |
| GPU | NVIDIA GTX 1650 / RTX 3050 (6 GB) recommended |
| Example | Small form-factor desktop, ~€600–900 |

CPU-only is possible at a reduced rate, but a low-end GPU costs little and
removes the ceiling.

### 8 cameras

| | |
|---|---|
| CPU | 8+ core (i7, Ryzen 7) |
| RAM | 32 GB |
| Storage | 512 GB NVMe |
| GPU | NVIDIA RTX 3060 (12 GB) or better |
| Example | Tower workstation, ~€1200–1800 |

A GPU is required in practice at this size.

### 16 cameras

| | |
|---|---|
| CPU | 12+ core |
| RAM | 64 GB |
| Storage | 1 TB NVMe |
| GPU | RTX 4070 or two mid-range GPUs |
| Notes | Run two AI worker processes, splitting the cameras between them |

The architecture supports this — workers are independent processes sharing one
consumer group — but a 16-camera venue should be benchmarked before purchase.

---

## Networking

- Cameras on a **wired** network. Wi-Fi cameras drop frames in a room full of
  customers' phones, and RTSP over congested Wi-Fi produces exactly the
  intermittent artefacts that make tracking unstable.
- A separate VLAN for the cameras if the venue's router supports it. IP cameras
  are the least-patched devices in most buildings.
- Gigabit between the cameras and the server. Four 1080p H.264 streams are
  roughly 16–32 Mbit/s, which is comfortable, but switch capacity matters.

## Camera placement

Placement affects accuracy more than any hardware choice.

- **Entrance camera:** covering the door, angled so people cross the frame
  rather than walking straight at the lens. A head-on view makes it hard to tell
  entering from leaving.
- **Room cameras:** elevated (2.5–3 m), tilted down. Higher is better for
  separating people who overlap from the camera's viewpoint.
- **Table analytics (Phase 9):** overhead views give reliable occupancy;
  wall-mounted views give an approximation, and the UI will say which.
- Avoid pointing a camera at a window or a bright doorway. Backlit silhouettes
  are the most common cause of missed detections in a real café.

## Power

Cafés lose power, and staff switch things off at closing time by pulling the
plug. A small UPS for the server and the network switch prevents the database
corruption that eventually follows repeated unclean shutdowns. PostgreSQL is
configured with data checksums so that if corruption does occur it is reported
rather than silently read back.
