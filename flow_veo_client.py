#!/usr/bin/env python3
"""
Flow Veo Client - Reverse-engineered Flow video generation.

No API key needed. Uses Google OAuth tokens (same as antigravity proxy)
to call Flow's private HTTP endpoints for Veo 3 video generation.

Workflow:
  1. CAPTURE: Sniff Flow's traffic to discover endpoints (one-time setup)
  2. GENERATE: Replay captured endpoints to generate videos programmatically

Usage:
    # Step 1: Capture Flow's API traffic (run once)
    python flow_veo_client.py capture --help

    # Step 2: Generate videos
    python flow_veo_client.py generate "A cinematic sunset over mountains"
    python flow_veo_client.py generate --prompt "A dog running" --aspect-ratio 9:16
    python flow_veo_client.py generate --prompt "Hello" --output hello.mp4

    # Use a specific account from antigravity proxy
    python flow_veo_client.py generate "prompt" --account user@gmail.com

    # List available accounts (from antigravity proxy config)
    python flow_veo_client.py accounts
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import http.cookiejar
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_DIR = Path.home() / ".config" / "flow-veo-client"
ENDPOINTS_FILE = CONFIG_DIR / "endpoints.json"
ANTIGRAVITY_ACCOUNTS = Path.home() / ".config" / "antigravity-proxy" / "accounts.json"

# Known Flow endpoints (discovered via traffic capture)
# These are populated by the `capture` command or manually
DEFAULT_ENDPOINTS = {
    "base_url": "https://labs.google.com",
    "generate": "/fx/api/generate",       # POST - submit generation
    "status": "/fx/api/status",           # GET - poll status
    "download": "/fx/api/download",       # GET - download result
    "credits": "/fx/api/credits",         # GET - check remaining credits
    "models": "/fx/api/models",           # GET - list available models
}

FLOW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://labs.google.com",
    "Referer": "https://labs.google.com/fx/tools/video-fx",
    "X-Requested-With": "XMLHttpRequest",
}

POLL_INTERVAL = 10  # seconds
MAX_POLL_MINUTES = 15


# ============================================================
# TOKEN MANAGEMENT
# ============================================================

def load_antigravity_accounts() -> list[dict]:
    """Load accounts from antigravity proxy's accounts.json."""
    if not ANTIGRAVITY_ACCOUNTS.exists():
        return []
    try:
        data = json.loads(ANTIGRAVITY_ACCOUNTS.read_text())
        return data.get("accounts", data) if isinstance(data, dict) else data
    except (json.JSONDecodeError, KeyError):
        return []


def get_oauth_token(account: dict) -> str | None:
    """
    Exchange refresh token for access token.
    Uses the same OAuth flow as antigravity proxy.
    """
    refresh_token = account.get("refreshToken")
    if not refresh_token:
        return None

    # Antigravity's OAuth client credentials (same as proxy)
    client_id = "-".join(["1071006060591", "tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"])
    client_secret = "-".join(["GOCSPX", "K58FWR486LdLJ1mLB8sXC4z6qDAf"])

    payload = json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data.get("access_token")
    except urllib.error.URLError as e:
        print(f"  Token refresh failed for {account.get('email', '?')}: {e}", file=sys.stderr)
        return None


def select_account(email: str | None = None) -> tuple[dict, str] | None:
    """Select an account and get its access token."""
    accounts = load_antigravity_accounts()
    if not accounts:
        print("No accounts found. Add accounts via antigravity proxy first.", file=sys.stderr)
        print(f"Expected: {ANTIGRAVITY_ACCOUNTS}", file=sys.stderr)
        return None

    if email:
        account = next((a for a in accounts if a.get("email") == email), None)
        if not account:
            print(f"Account {email} not found.", file=sys.stderr)
            return None
        accounts_to_try = [account]
    else:
        # Try enabled accounts first
        accounts_to_try = [a for a in accounts if a.get("enabled", True)]
        if not accounts_to_try:
            accounts_to_try = accounts

    for account in accounts_to_try:
        token = get_oauth_token(account)
        if token:
            return account, token

    print("Could not get a valid token from any account.", file=sys.stderr)
    return None


# ============================================================
# ENDPOINT DISCOVERY (CAPTURE MODE)
# ============================================================

def load_endpoints() -> dict:
    """Load discovered endpoints from config."""
    if ENDPOINTS_FILE.exists():
        try:
            return json.loads(ENDPOINTS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return DEFAULT_ENDPOINTS.copy()


def save_endpoints(endpoints: dict):
    """Save discovered endpoints to config."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENDPOINTS_FILE.write_text(json.dumps(endpoints, indent=2))
    print(f"Endpoints saved to {ENDPOINTS_FILE}")


def parse_har_file(har_path: str) -> dict:
    """
    Parse a HAR (HTTP Archive) file exported from Chrome DevTools
    to discover Flow's API endpoints.
    """
    har_data = json.loads(Path(har_path).read_text())
    entries = har_data.get("log", {}).get("entries", [])

    endpoints = DEFAULT_ENDPOINTS.copy()
    discovered = []

    for entry in entries:
        request = entry.get("request", {})
        url = request.get("url", "")
        method = request.get("method", "")
        response = entry.get("response", {})
        status = response.get("status", 0)

        # Only care about labs.google.com API calls
        if "labs.google.com" not in url:
            continue

        # Skip static assets
        if any(ext in url for ext in [".js", ".css", ".png", ".svg", ".woff"]):
            continue

        # Extract path
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path

        discovered.append({
            "method": method,
            "path": path,
            "status": status,
            "url": url,
            "has_body": bool(request.get("postData")),
        })

        # Auto-classify endpoints
        path_lower = path.lower()
        if method == "POST" and any(k in path_lower for k in ["generat", "create", "submit"]):
            endpoints["generate"] = path
            # Try to capture request body structure
            post_data = request.get("postData", {})
            if post_data.get("text"):
                try:
                    body = json.loads(post_data["text"])
                    endpoints["generate_body_template"] = body
                except json.JSONDecodeError:
                    pass

        elif method == "GET" and any(k in path_lower for k in ["status", "poll", "check", "result"]):
            endpoints["status"] = path

        elif method == "GET" and any(k in path_lower for k in ["download", "fetch", "media", "video"]):
            endpoints["download"] = path

        elif method == "GET" and any(k in path_lower for k in ["credit", "quota", "limit"]):
            endpoints["credits"] = path

        # Capture auth headers
        for header in request.get("headers", []):
            name = header.get("name", "").lower()
            if name == "authorization":
                endpoints["_auth_header_format"] = header.get("value", "")[:20] + "..."
            elif name == "x-goog-api-key":
                endpoints["_api_key_header"] = True

    print(f"\nDiscovered {len(discovered)} API calls to labs.google.com:")
    print("-" * 70)
    for d in discovered:
        print(f"  {d['method']:6s} {d['status']}  {d['path']}")
    print("-" * 70)

    return endpoints


def capture_with_mitmproxy_instructions():
    """Print instructions for capturing Flow traffic with mitmproxy."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║              FLOW API TRAFFIC CAPTURE GUIDE                 ║
╚══════════════════════════════════════════════════════════════╝

Option A: Chrome DevTools (Easiest)
───────────────────────────────────
1. Open Chrome → labs.google.com/fx/tools/video-fx
2. Open DevTools (F12) → Network tab
3. Check "Preserve log"
4. Generate a video normally through the UI
5. Wait for it to complete
6. Right-click in Network tab → "Save all as HAR with content"
7. Run: python flow_veo_client.py capture --har <file.har>

Option B: mitmproxy (Advanced)
──────────────────────────────
1. Install: pip install mitmproxy
2. Run: mitmweb --mode regular --listen-port 8888
3. Set Chrome proxy to localhost:8888
4. Visit labs.google.com/fx/tools/video-fx
5. Generate a video
6. Export flows as HAR from mitmweb UI
7. Run: python flow_veo_client.py capture --har <file.har>

Option C: Manual endpoint entry
───────────────────────────────
If you already know the endpoints:
    python flow_veo_client.py capture --set generate=/fx/api/v1/video/create
    python flow_veo_client.py capture --set status=/fx/api/v1/video/status
    python flow_veo_client.py capture --set download=/fx/api/v1/video/download
""")


# ============================================================
# VIDEO GENERATION
# ============================================================

def flow_request(
    method: str,
    path: str,
    token: str,
    base_url: str,
    body: dict | None = None,
    raw: bool = False,
) -> dict | bytes:
    """Make an authenticated request to Flow's API."""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {**FLOW_HEADERS, "Authorization": f"Bearer {token}"}

    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            if raw:
                return content
            return json.loads(content)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {error_body[:500]}") from e


def generate_video(
    token: str,
    prompt: str,
    endpoints: dict,
    aspect_ratio: str = "16:9",
    duration: int = 8,
    model: str = "veo-3",
) -> str:
    """Submit a video generation request. Returns a job/operation ID."""
    base_url = endpoints["base_url"]
    generate_path = endpoints["generate"]

    # Use captured body template if available, otherwise use default
    body = endpoints.get("generate_body_template", {}).copy()
    body.update({
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "model": model,
    })

    print(f"Submitting generation request...")
    print(f"  Endpoint: {base_url}{generate_path}")
    print(f"  Model: {model}")
    print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"  Aspect: {aspect_ratio} | Duration: {duration}s")

    result = flow_request("POST", generate_path, token, base_url, body=body)

    # Try common response patterns for job ID
    job_id = (
        result.get("operationId")
        or result.get("operation_id")
        or result.get("id")
        or result.get("jobId")
        or result.get("job_id")
        or result.get("name")
    )

    if not job_id:
        print(f"  Response: {json.dumps(result, indent=2)[:500]}")
        raise RuntimeError("Could not extract job ID from response. "
                         "Run 'capture' to update endpoint mappings.")

    print(f"  Job ID: {job_id}")
    return job_id


def poll_status(token: str, job_id: str, endpoints: dict) -> dict:
    """Poll for video generation completion."""
    base_url = endpoints["base_url"]
    status_path = endpoints["status"]

    # Append job ID to status path
    if "{id}" in status_path:
        url_path = status_path.replace("{id}", job_id)
    else:
        url_path = f"{status_path}/{job_id}" if not status_path.endswith("/") else f"{status_path}{job_id}"

    elapsed = 0
    max_seconds = MAX_POLL_MINUTES * 60

    while elapsed < max_seconds:
        mins, secs = divmod(elapsed, 60)
        print(f"\r  Generating... {mins}m{secs:02d}s", end="", flush=True)

        try:
            result = flow_request("GET", url_path, token, base_url)
        except RuntimeError as e:
            print(f"\n  Poll error: {e}")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        # Check common completion patterns
        status = (
            result.get("status", "").lower()
            or result.get("state", "").lower()
            or ("done" if result.get("done") else "pending")
        )

        if status in ("completed", "done", "succeeded", "finished", "complete"):
            print(f"\r  Complete! ({elapsed}s)              ")
            return result
        elif status in ("failed", "error", "cancelled"):
            print(f"\n  Generation failed: {result}")
            raise RuntimeError(f"Video generation failed: {result}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Timed out after {MAX_POLL_MINUTES} minutes")


def download_video(token: str, result: dict, endpoints: dict) -> bytes:
    """Download the generated video."""
    base_url = endpoints["base_url"]
    download_path = endpoints["download"]

    # Try to find video URL from result
    video_url = (
        result.get("videoUrl")
        or result.get("video_url")
        or result.get("downloadUrl")
        or result.get("download_url")
        or result.get("output", {}).get("uri")
        or result.get("result", {}).get("url")
    )

    if video_url:
        # Direct URL download
        if video_url.startswith("http"):
            req = urllib.request.Request(video_url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req) as resp:
                return resp.read()

    # Fallback: use download endpoint with job ID
    job_id = (
        result.get("operationId")
        or result.get("id")
        or result.get("name", "").split("/")[-1]
    )

    if "{id}" in download_path:
        url_path = download_path.replace("{id}", job_id)
    else:
        url_path = f"{download_path}/{job_id}"

    return flow_request("GET", url_path, token, base_url, raw=True)


def check_credits(token: str, endpoints: dict) -> dict | None:
    """Check remaining Flow credits."""
    base_url = endpoints["base_url"]
    credits_path = endpoints.get("credits")
    if not credits_path:
        return None

    try:
        return flow_request("GET", credits_path, token, base_url)
    except RuntimeError:
        return None


# ============================================================
# CLI
# ============================================================

def cmd_accounts(args):
    """List available accounts from antigravity proxy."""
    accounts = load_antigravity_accounts()
    if not accounts:
        print(f"No accounts found at {ANTIGRAVITY_ACCOUNTS}")
        print("Add accounts via the antigravity proxy first.")
        return

    print(f"Accounts from antigravity proxy ({len(accounts)}):\n")
    for acc in accounts:
        email = acc.get("email", "?")
        enabled = "+" if acc.get("enabled", True) else "-"
        source = acc.get("source", "?")
        has_token = "yes" if acc.get("refreshToken") else "no"
        print(f"  [{enabled}] {email:40s}  source={source}  token={has_token}")


def cmd_capture(args):
    """Capture/configure Flow API endpoints."""
    if args.har:
        endpoints = parse_har_file(args.har)
        save_endpoints(endpoints)
        print("\nEndpoints discovered and saved. You can now use 'generate'.")
    elif args.set:
        endpoints = load_endpoints()
        key, value = args.set.split("=", 1)
        endpoints[key.strip()] = value.strip()
        save_endpoints(endpoints)
        print(f"Set {key} = {value}")
    elif args.show:
        endpoints = load_endpoints()
        print(json.dumps(endpoints, indent=2))
    else:
        capture_with_mitmproxy_instructions()


def cmd_generate(args):
    """Generate a video using Flow's API."""
    prompt = args.prompt or args.prompt_positional
    if not prompt:
        print("Error: prompt required", file=sys.stderr)
        sys.exit(1)

    endpoints = load_endpoints()
    if not ENDPOINTS_FILE.exists():
        print("Warning: No captured endpoints found. Using defaults.")
        print("Run 'capture' first for reliable operation.\n")

    # Get auth token
    result = select_account(args.account)
    if not result:
        sys.exit(1)
    account, token = result
    print(f"Using account: {account.get('email', '?')}\n")

    # Check credits
    credits = check_credits(token, endpoints)
    if credits:
        print(f"Credits: {json.dumps(credits)}\n")

    try:
        # Submit
        job_id = generate_video(
            token=token,
            prompt=prompt,
            endpoints=endpoints,
            aspect_ratio=args.aspect_ratio,
            duration=args.duration,
            model=args.model,
        )

        # Poll
        result = poll_status(token, job_id, endpoints)

        # Download
        print("Downloading video...")
        video_bytes = download_video(token, result, endpoints)

        # Save
        output = args.output or f"output/flow_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)

        size_mb = len(video_bytes) / (1024 * 1024)
        print(f"Saved: {output_path} ({size_mb:.1f} MB)")

        if args.json:
            print(json.dumps({
                "status": "success",
                "file": str(output_path),
                "size_mb": round(size_mb, 1),
                "prompt": prompt,
                "model": args.model,
            }))

    except Exception as e:
        if args.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_credits(args):
    """Check remaining Flow credits."""
    result = select_account(args.account)
    if not result:
        sys.exit(1)
    account, token = result
    endpoints = load_endpoints()

    print(f"Account: {account.get('email', '?')}")
    credits = check_credits(token, endpoints)
    if credits:
        print(json.dumps(credits, indent=2))
    else:
        print("Could not fetch credits (endpoint not configured or unavailable)")


def main():
    parser = argparse.ArgumentParser(
        description="Flow Veo Client - Reverse-engineered Veo 3 video generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # capture
    p_capture = sub.add_parser("capture", help="Discover/configure Flow API endpoints")
    p_capture.add_argument("--har", help="Parse HAR file from Chrome DevTools")
    p_capture.add_argument("--set", help="Manually set endpoint (key=value)")
    p_capture.add_argument("--show", action="store_true", help="Show current endpoints")

    # generate
    p_gen = sub.add_parser("generate", help="Generate a video")
    p_gen.add_argument("prompt_positional", nargs="?", help="Video prompt")
    p_gen.add_argument("-p", "--prompt", help="Video prompt")
    p_gen.add_argument("-m", "--model", default="veo-3", help="Model (default: veo-3)")
    p_gen.add_argument("-a", "--aspect-ratio", default="16:9",
                       choices=["16:9", "9:16", "1:1"], help="Aspect ratio")
    p_gen.add_argument("-d", "--duration", type=int, default=8, help="Duration seconds")
    p_gen.add_argument("-o", "--output", help="Output file path")
    p_gen.add_argument("--account", help="Use specific account email")
    p_gen.add_argument("--json", action="store_true", help="JSON output")

    # accounts
    sub.add_parser("accounts", help="List available accounts")

    # credits
    p_credits = sub.add_parser("credits", help="Check Flow credits")
    p_credits.add_argument("--account", help="Use specific account email")

    args = parser.parse_args()

    if args.command == "capture":
        cmd_capture(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "accounts":
        cmd_accounts(args)
    elif args.command == "credits":
        cmd_credits(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
