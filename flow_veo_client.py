#!/usr/bin/env python3
"""
Flow Veo Client - Standalone Veo 3 video generation client.

Uses Google Gen AI SDK to generate videos with synchronized audio
via Vertex AI's Veo 3 model.

Usage:
    python flow_veo_client.py "A cinematic shot of a sunset over mountains"
    python flow_veo_client.py --prompt "A dog running" --aspect-ratio 9:16 --duration 8
    python flow_veo_client.py --prompt "Hello world" --output hello.mp4 --no-audio
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai package not installed.")
    print("Run: pip install google-genai")
    sys.exit(1)


DEFAULT_MODEL = "veo-3"
DEFAULT_REGION = "us-central1"
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_OUTPUT_DIR = "output"
POLL_INTERVAL_SECONDS = 15
MAX_POLL_MINUTES = 10


def get_client(project_id: str, region: str) -> genai.Client:
    """Initialize the Gen AI client for Vertex AI."""
    return genai.Client(
        vertexai=True,
        project=project_id,
        location=region,
    )


def generate_video(
    client: genai.Client,
    prompt: str,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    number_of_videos: int = 1,
    duration_seconds: int | None = None,
    generate_audio: bool = True,
    image_path: str | None = None,
) -> list[bytes]:
    """
    Generate video(s) from a text prompt using Veo 3.

    Args:
        client: Initialized Gen AI client.
        prompt: Text description of the video to generate.
        model: Model ID (default: veo-3).
        aspect_ratio: Video aspect ratio (16:9, 9:16, 1:1).
        number_of_videos: Number of videos to generate (1-4).
        duration_seconds: Video duration in seconds (5 or 8 for veo-3).
        generate_audio: Whether to generate synchronized audio (veo-3 only).
        image_path: Optional reference image path for image-to-video generation.

    Returns:
        List of video bytes.
    """
    config_kwargs = {
        "aspect_ratio": aspect_ratio,
        "number_of_videos": number_of_videos,
    }

    if duration_seconds is not None:
        config_kwargs["duration_seconds"] = duration_seconds

    if model == "veo-3" and generate_audio:
        config_kwargs["generate_audio"] = True

    config = types.GenerateVideosConfig(**config_kwargs)

    generate_kwargs = {
        "model": model,
        "prompt": prompt,
        "config": config,
    }

    # Image-to-video: use a reference image
    if image_path:
        image_bytes = Path(image_path).read_bytes()
        mime = "image/png" if image_path.endswith(".png") else "image/jpeg"
        generate_kwargs["image"] = types.Image(
            image_bytes=image_bytes,
            mime_type=mime,
        )

    print(f"Submitting video generation request...")
    print(f"  Model: {model}")
    print(f"  Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    print(f"  Aspect ratio: {aspect_ratio}")
    print(f"  Audio: {'yes' if generate_audio and model == 'veo-3' else 'no'}")
    if duration_seconds:
        print(f"  Duration: {duration_seconds}s")

    operation = client.models.generate_videos(**generate_kwargs)

    # Poll for completion
    elapsed = 0
    max_seconds = MAX_POLL_MINUTES * 60
    while not operation.done:
        if elapsed >= max_seconds:
            raise TimeoutError(
                f"Video generation timed out after {MAX_POLL_MINUTES} minutes"
            )
        mins, secs = divmod(elapsed, 60)
        print(f"\r  Generating... {mins}m{secs:02d}s elapsed", end="", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        operation = client.operations.get(operation)

    print(f"\r  Generation complete! ({elapsed}s)          ")

    # Download generated videos
    videos = []
    for video in operation.result.generated_videos:
        video_bytes = client.files.download(file=video.video)
        videos.append(video_bytes)

    return videos


def save_videos(videos: list[bytes], output_dir: str, base_name: str = "video") -> list[str]:
    """Save generated videos to disk."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved = []
    for i, video_bytes in enumerate(videos):
        suffix = f"_{i + 1}" if len(videos) > 1 else ""
        filename = f"{base_name}{suffix}.mp4"
        filepath = output_path / filename
        filepath.write_bytes(video_bytes)
        size_mb = len(video_bytes) / (1024 * 1024)
        print(f"  Saved: {filepath} ({size_mb:.1f} MB)")
        saved.append(str(filepath))

    return saved


def main():
    parser = argparse.ArgumentParser(
        description="Generate videos using Google Veo 3 via Vertex AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "A cinematic sunrise over Tokyo"
  %(prog)s --prompt "A cat playing piano" --aspect-ratio 9:16
  %(prog)s --prompt "Ocean waves" --model veo-2 --duration 5
  %(prog)s --prompt "Product showcase" --image reference.jpg
  %(prog)s --prompt "A speech" --no-audio --output speech.mp4
        """,
    )

    parser.add_argument("prompt_positional", nargs="?", help="Video prompt (positional)")
    parser.add_argument("-p", "--prompt", help="Video prompt")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, choices=["veo-3", "veo-2"],
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("-a", "--aspect-ratio", default=DEFAULT_ASPECT_RATIO,
                        choices=["16:9", "9:16", "1:1"],
                        help=f"Aspect ratio (default: {DEFAULT_ASPECT_RATIO})")
    parser.add_argument("-n", "--number", type=int, default=1, choices=[1, 2, 3, 4],
                        help="Number of videos to generate (default: 1)")
    parser.add_argument("-d", "--duration", type=int, choices=[5, 8],
                        help="Duration in seconds (default: model decides)")
    parser.add_argument("--no-audio", action="store_true",
                        help="Disable audio generation (veo-3 only)")
    parser.add_argument("-i", "--image", help="Reference image for image-to-video")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory or filename (default: {DEFAULT_OUTPUT_DIR}/)")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        help="GCP project ID (or set GOOGLE_CLOUD_PROJECT)")
    parser.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_REGION", DEFAULT_REGION),
                        help=f"GCP region (default: {DEFAULT_REGION})")
    parser.add_argument("--json", action="store_true",
                        help="Output result as JSON (for pipeline integration)")

    args = parser.parse_args()

    # Resolve prompt
    prompt = args.prompt or args.prompt_positional
    if not prompt:
        parser.error("A prompt is required. Pass it as an argument or with --prompt.")

    # Validate project
    if not args.project:
        parser.error(
            "GCP project ID required. Set GOOGLE_CLOUD_PROJECT env var or use --project."
        )

    # Resolve output
    output_dir = args.output
    base_name = "video"
    if args.output.endswith(".mp4"):
        output_dir = str(Path(args.output).parent) or "."
        base_name = Path(args.output).stem

    try:
        client = get_client(args.project, args.region)

        videos = generate_video(
            client=client,
            prompt=prompt,
            model=args.model,
            aspect_ratio=args.aspect_ratio,
            number_of_videos=args.number,
            duration_seconds=args.duration,
            generate_audio=not args.no_audio,
            image_path=args.image,
        )

        saved_paths = save_videos(videos, output_dir, base_name)

        if args.json:
            result = {
                "status": "success",
                "model": args.model,
                "prompt": prompt,
                "files": saved_paths,
                "count": len(saved_paths),
            }
            print(json.dumps(result))
        else:
            print(f"\nDone! Generated {len(saved_paths)} video(s).")

    except Exception as e:
        if args.json:
            print(json.dumps({"status": "error", "error": str(e)}))
            sys.exit(1)
        else:
            print(f"\nError: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
