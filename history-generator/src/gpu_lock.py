"""Process-wide mutex serializing GPU-bound inference calls.

The API server can run multiple episode jobs concurrently -- one background thread per
slug, see api.py's _active_slugs -- and each job now calls both Ollama (script/outline/
image-prompt generation) and ComfyUI (per-segment image rendering) against the same
physical GPU. Sharing one RTX 5090 between two independent inference servers works, but
interleaving Ollama token generation with ComfyUI diffusion steps would contend for VRAM
and compute unpredictably, so this lock forces the two workloads to never run at the same
time, system-wide -- at the cost of some wall-clock time when multiple episodes are
queued at once. The CLI path (main.py) only ever runs one job per process, so this lock
is a no-op there in practice.
"""

import threading

gpu_lock = threading.Lock()
