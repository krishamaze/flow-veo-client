# flow-veo-client

Reverse-engineered [Flow](https://labs.google.com/fx/tools/video-fx) video generation client. No API key needed — uses your existing Google OAuth tokens (from antigravity proxy) to call Flow's private HTTP endpoints for Veo 3 video generation.

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  This Client │────▶│  Flow's Private  │────▶│  Veo 3 Generation   │
│  (Python)    │     │  HTTP Endpoints  │     │  (labs.google.com)  │
└─────────────┘     └──────────────────┘     └─────────────────────┘
        │
        ▼
  Uses OAuth tokens from
  antigravity proxy accounts
```

## Setup

### 1. Prerequisites

- Antigravity proxy with accounts configured (`~/.config/antigravity-proxy/accounts.json`)
- Flow credits on your Google account

### 2. Capture Flow's API Endpoints (One-Time)

The client needs to know Flow's private endpoints. Capture them from your browser:

```bash
# Option A: Export HAR from Chrome DevTools
# 1. Open labs.google.com/fx/tools/video-fx
# 2. Open DevTools (F12) → Network → Preserve log
# 3. Generate a video through the UI
# 4. Right-click → Save all as HAR
python flow_veo_client.py capture --har traffic.har

# Option B: Manually set endpoints (if you know them)
python flow_veo_client.py capture --set generate=/fx/api/v1/video/create
python flow_veo_client.py capture --set status=/fx/api/v1/video/status/{id}

# View current endpoints
python flow_veo_client.py capture --show
```

## Usage

```bash
# Generate a video
python flow_veo_client.py generate "A cinematic sunset over mountains"

# Vertical (Reels/TikTok)
python flow_veo_client.py generate -p "A dancer" -a 9:16

# Specific account
python flow_veo_client.py generate "prompt" --account user@gmail.com

# Custom output
python flow_veo_client.py generate "prompt" -o my_video.mp4

# Check credits
python flow_veo_client.py credits

# List accounts
python flow_veo_client.py accounts

# Pipeline mode (JSON output)
python flow_veo_client.py generate "prompt" --json
```

## Commands

| Command | Description |
|---------|-------------|
| `capture` | Discover/configure Flow API endpoints |
| `generate` | Generate a video |
| `accounts` | List available OAuth accounts |
| `credits` | Check remaining Flow credits |

## Architecture

- **Zero dependencies** — stdlib only (no pip install needed)
- **Reuses antigravity proxy accounts** — same OAuth tokens, no extra auth
- **HAR-based discovery** — parse browser traffic to find endpoints
- **Endpoint config** — saved to `~/.config/flow-veo-client/endpoints.json`

## License

MIT
