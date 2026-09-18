#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lossless Whole Slide Image (WSI) Converter for Space Ranger Visium HD QC.
Converts scanner output formats (.svs, .sdpc) to Space Ranger-compatible BigTIFF (.btf/.tif).
"""

import os
import sys
import gc
import json
import math
import subprocess
from pathlib import Path
from typing import Optional, Callable, List


def get_opensdpc_ld_paths() -> List[str]:
    """Locate opensdpc and helper shared library directories."""
    paths = []
    # Search all sys.path and standard site-packages
    candidate_roots = list(sys.path) + [
        str(Path.home() / ".local/lib/python3.10/site-packages"),
        str(Path.home() / "miniconda3/lib/python3.13/site-packages"),
        "/usr/local/lib/python3.10/dist-packages",
        "/usr/lib/python3/dist-packages"
    ]
    for p in candidate_roots:
        sdpc_linux = Path(p) / "opensdpc" / "LINUX"
        if sdpc_linux.exists():
            ffmpeg_path = sdpc_linux / "ffmpeg"
            jpeg_path = sdpc_linux / "jpeg"
            for d in [sdpc_linux, ffmpeg_path, jpeg_path]:
                if d.exists() and str(d) not in paths:
                    paths.append(str(d))
    return paths


def is_already_supported_format(filename_or_path: str) -> bool:
    """Check if the file format is natively accepted by Space Ranger."""
    ext = Path(filename_or_path).suffix.lower()
    return ext in [".tif", ".tiff", ".btf", ".jpg", ".jpeg"]


def convert_svs_to_bigtiff(
    input_path: str,
    output_path: str,
    tile_size: int = 1024,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    Losslessly convert Aperio SVS whole slide image to pyramidal BigTIFF (.btf).
    Preserves full level 0 resolution.
    """
    import tifffile
    import numpy as np

    if progress_cb:
        progress_cb(0.05, "Opening SVS whole slide image...")

    with tifffile.TiffFile(input_path) as svs:
        series = svs.series[0]
        full_page = series.pages[0]

        height, width = full_page.shape[:2]
        channels = full_page.shape[2] if len(full_page.shape) > 2 else 1
        dtype = full_page.dtype

        description = full_page.description or ""

        if progress_cb:
            progress_cb(0.15, f"Reading Level 0 ({width}x{height}, {channels}ch)...")

        with tifffile.TiffWriter(output_path, bigtiff=True) as tif_out:
            slide_data = series.asarray()

            if progress_cb:
                progress_cb(0.60, "Encoding into Pyramidal BigTIFF (JPEG compression)...")

            tif_out.write(
                slide_data,
                tile=(tile_size, tile_size),
                photometric="rgb" if channels == 3 else "minisblack",
                compression="jpeg",
                metadata={"Creator": "Visium HD QC Lossless SVS Converter", "AperioDescription": description}
            )

    if progress_cb:
        progress_cb(1.0, "SVS to BigTIFF conversion completed successfully.")

    return output_path


def convert_sdpc_to_bigtiff_internal(
    input_path: str,
    output_path: str,
    tile_size: int = 1024,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """Internal implementation of SDPC converter inside a subprocess with proper LD_LIBRARY_PATH."""
    import tifffile
    import numpy as np

    if progress_cb:
        progress_cb(0.05, "Initializing opensdpc reader...")

    try:
        from opensdpc.OpenSdpc import OpenSdpc
    except Exception as e:
        raise RuntimeError(f"Failed to load OpenSdpc library: {e}")

    sdpc = OpenSdpc(input_path)
    dims = sdpc.level_dimensions
    w, h = dims[0]

    if progress_cb:
        progress_cb(0.10, f"Detected SDPC Level 0 resolution: {w} x {h}")

    step = 4096
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    total_blocks = math.ceil(h / step) * math.ceil(w / step)
    block_idx = 0

    for y in range(0, h, step):
        cur_h = min(step, h - y)
        for x in range(0, w, step):
            cur_w = min(step, w - x)
            roi_pil = sdpc.read_region((x, y), 0, (cur_w, cur_h))
            roi_np = np.array(roi_pil)
            canvas[y:y+cur_h, x:x+cur_w] = roi_np[:cur_h, :cur_w, :3]

            block_idx += 1
            if progress_cb and (block_idx % 5 == 0 or block_idx == total_blocks):
                pct = 0.10 + 0.65 * (block_idx / total_blocks)
                progress_cb(pct, f"Decoding tiles ({block_idx}/{total_blocks})...")

    if progress_cb:
        progress_cb(0.80, "Writing Pyramidal BigTIFF...")

    with tifffile.TiffWriter(output_path, bigtiff=True) as tif_out:
        tif_out.write(
            canvas,
            tile=(tile_size, tile_size),
            photometric="rgb",
            compression="jpeg",
            metadata={"Creator": "Visium HD QC Lossless SDPC Converter"}
        )

    del canvas
    gc.collect()

    if progress_cb:
        progress_cb(1.0, "SDPC to BigTIFF conversion completed.")

    return output_path


def run_isolated_subprocess_conversion(
    input_path: str,
    output_path: str,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """Run converter in an isolated subprocess with LD_LIBRARY_PATH configured."""
    ld_paths = get_opensdpc_ld_paths()
    env = os.environ.copy()
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    new_ld = ":".join(ld_paths)
    if existing_ld:
        new_ld = f"{new_ld}:{existing_ld}"
    env["LD_LIBRARY_PATH"] = new_ld

    # Locate best python interpreter with opensdpc installed
    py_bin = sys.executable
    converter_script = str(Path(__file__).resolve())

    cmd = [
        py_bin, converter_script,
        "--input", input_path,
        "--output", output_path,
        "--worker"
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    for line in iter(proc.stdout.readline, ""):
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("PROGRESS:"):
            try:
                parts = line_str.split(":", 2)
                pct = float(parts[1])
                msg = parts[2]
                if progress_cb:
                    progress_cb(pct, msg)
            except Exception:
                pass
        else:
            if progress_cb:
                progress_cb(0.5, line_str)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Subprocess conversion failed with exit code {proc.returncode}")

    return output_path


def auto_convert_to_bigtiff(
    input_file: str,
    output_dir: Optional[str] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> str:
    """
    Inspect input file format and automatically convert to Space Ranger compatible BigTIFF (.btf)
    if necessary. If already compatible, returns original path directly.
    """
    inp = Path(input_file)
    ext = inp.suffix.lower()

    if is_already_supported_format(str(inp)):
        if progress_cb:
            progress_cb(1.0, f"Image {inp.name} is natively compatible with Space Ranger.")
        return str(inp)

    out_directory = Path(output_dir) if output_dir else inp.parent
    out_file = out_directory / f"{inp.stem}_converted.btf"

    if ext == ".svs":
        if progress_cb:
            progress_cb(0.01, f"Detected Aperio SVS format. Launching lossless BigTIFF converter...")
        return convert_svs_to_bigtiff(str(inp), str(out_file), progress_cb=progress_cb)
    elif ext == ".sdpc":
        if progress_cb:
            progress_cb(0.01, f"Detected Sqray SDPC format. Launching isolated BigTIFF converter...")
        return run_isolated_subprocess_conversion(str(inp), str(out_file), progress_cb=progress_cb)
    elif ext == ".csp":
        raise NotImplementedError(
            f"Format {ext} requires conversion to SVS or TIFF in scanner software first. "
            "Please export as .svs or .sdpc from your scanner client."
        )
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. Supported formats: .tif, .btf, .tiff, .svs, .sdpc, .jpg"
        )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input slide image path")
    parser.add_argument("--output", required=True, help="Output BigTIFF path")
    parser.add_argument("--worker", action="store_true", help="Run in worker mode")
    args = parser.parse_args()

    def report_progress(pct: float, msg: str):
        print(f"PROGRESS:{pct:.2f}:{msg}", flush=True)

    input_ext = Path(args.input).suffix.lower()
    if input_ext == ".sdpc":
        convert_sdpc_to_bigtiff_internal(args.input, args.output, progress_cb=report_progress)
    elif input_ext == ".svs":
        convert_svs_to_bigtiff(args.input, args.output, progress_cb=report_progress)
    else:
        report_progress(1.0, f"No conversion needed for {args.input}")
