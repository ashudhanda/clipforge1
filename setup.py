"""ClipForge cross-platform setup — beginners start here.

    python setup.py

What it does (idempotent — safe to run again anytime):
  1. Checks Python >= 3.10
  2. pip install -r requirements.txt
  3. Gets an ffmpeg binary via imageio-ffmpeg (no system ffmpeg needed)
  4. Creates ~/.clipforge/ (config, clips, tmp, assets)
  5. Copies the face-detection model into ~/.clipforge/assets/
  6. Copies config.example.yaml -> ~/.clipforge/config.yaml (if missing)

Optional:
    python setup.py --pre-download-models   also fetch the transcription
                                            model now (slower setup, faster
                                            first run)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ chahiye "
                 f"(mila {sys.version.split()[0]})")
    print("== ClipForge setup ==\n")

    # 1. dependencies
    print("-- Python packages install ho rahe hain (thoda time lagega)...")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r",
         str(REPO / "requirements.txt")])

    # 2. ffmpeg via imageio-ffmpeg (static binary, no system install)
    print("\n-- ffmpeg check...")
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        print("ffmpeg ready:", exe)
    except Exception as e:
        sys.exit(f"imageio-ffmpeg fail: {e}\n"
                 "Agar system ffmpeg hai to config mein ffmpeg_path set karo.")

    # 3. ~/.clipforge skeleton
    home = Path.home() / ".clipforge"
    for d in (home, home / "assets", home / "clips", home / "tmp"):
        d.mkdir(parents=True, exist_ok=True)

    # 4. face model
    src_model = REPO / "assets" / "face_yunet.onnx"
    dst_model = home / "assets" / "face_yunet.onnx"
    if src_model.exists() and not dst_model.exists():
        shutil.copy2(src_model, dst_model)
        print("face model copy ho gaya.")
    elif dst_model.exists():
        print("face model pehle se hai.")

    # 5. config
    dst_cfg = home / "config.yaml"
    if not dst_cfg.exists():
        shutil.copy2(REPO / "config.example.yaml", dst_cfg)
        print("config.yaml ban gayi (~/.clipforge/).")
    else:
        print("config.yaml pehle se hai (chheda nahi).")

    # 6. optional: pre-download transcription model
    if "--pre-download-models" in sys.argv:
        print("\n-- transcription model download ho raha hai...")
        from faster_whisper import WhisperModel
        WhisperModel("base", device="cpu", compute_type="int8")
        print("model ready.")

    # 7. console script hint
    print("\nSetup complete!")
    print("Agla step:  python -m clipforge.cli setup")
    print("(ya: pip install -e .  phir seedha `clipforge` command)")


if __name__ == "__main__":
    main()
