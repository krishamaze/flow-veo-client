# flow-veo-client

Standalone Veo 3 video generation client using Google Vertex AI.

## Setup

```bash
pip install google-genai

# Authenticate
gcloud auth application-default login

# Set your project
export GOOGLE_CLOUD_PROJECT="your-project-id"
```

## Usage

```bash
# Basic generation
python flow_veo_client.py "A cinematic sunset over mountains"

# Vertical video (Reels/TikTok)
python flow_veo_client.py --prompt "A dancer in slow motion" --aspect-ratio 9:16

# Image-to-video
python flow_veo_client.py --prompt "Zoom into the scene" --image reference.jpg

# Without audio
python flow_veo_client.py --prompt "Silent timelapse" --no-audio

# Multiple outputs
python flow_veo_client.py --prompt "A cat" --number 4

# Pipeline mode (JSON output)
python flow_veo_client.py --prompt "Product demo" --json --output demo.mp4
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p, --prompt` | Video description | required |
| `-m, --model` | `veo-3` or `veo-2` | `veo-3` |
| `-a, --aspect-ratio` | `16:9`, `9:16`, `1:1` | `16:9` |
| `-n, --number` | Videos to generate (1-4) | `1` |
| `-d, --duration` | Duration: 5 or 8 seconds | auto |
| `--no-audio` | Disable audio (veo-3 only) | audio on |
| `-i, --image` | Reference image path | none |
| `-o, --output` | Output dir or filename | `output/` |
| `--project` | GCP project ID | `$GOOGLE_CLOUD_PROJECT` |
| `--region` | GCP region | `us-central1` |
| `--json` | JSON output for pipelines | off |

## Integration

```python
from flow_veo_client import get_client, generate_video, save_videos

client = get_client("my-project", "us-central1")
videos = generate_video(client, prompt="A sunset", aspect_ratio="9:16")
save_videos(videos, "output/")
```

## License

MIT
