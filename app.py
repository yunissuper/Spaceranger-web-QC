#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visium HD Single-Cell RNA Quantity QC Platform
Integrates Space Ranger StarDist nucleus segmentation with Qubit fluorometric
quantification to estimate and evaluate RNA quantity per cell (10x Step 2.6).
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from converter import auto_convert_to_bigtiff, is_already_supported_format

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Dynamic data directory configuration:
# 1. Environment variable VISIUM_QC_DATA_DIR or DATA_DIR
# 2. Default fallback: /mnt/ktdb2/yls/10x/visium_qc_app if exists/writable, else BASE_DIR
env_data_dir = os.environ.get("VISIUM_QC_DATA_DIR") or os.environ.get("DATA_DIR")
if env_data_dir:
    DATA_DIR = Path(env_data_dir)
elif Path("/mnt/ktdb2/yls/10x/visium_qc_app").exists() and os.access("/mnt/ktdb2/yls/10x/visium_qc_app", os.W_OK):
    DATA_DIR = Path("/mnt/ktdb2/yls/10x/visium_qc_app")
else:
    DATA_DIR = BASE_DIR

UPLOADS_DIR = DATA_DIR / "uploads"
RUNS_DIR = DATA_DIR / "runs"
JOBS_FILE = DATA_DIR / "jobs.json"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def find_spaceranger_bin() -> str:
    """Dynamically resolve the spaceranger executable."""
    env_bin = os.environ.get("SPACERANGER_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    which_bin = shutil.which("spaceranger")
    if which_bin:
        return which_bin

    # Search common fallback paths
    fallback_paths = [
        Path.home() / "software/10x/spaceranger-4.1.0/spaceranger",
        Path.home() / "software/spaceranger/spaceranger",
        Path("/opt/spaceranger/spaceranger"),
        Path.cwd() / "spaceranger/spaceranger",
        BASE_DIR.parent / "spaceranger-4.1.0/spaceranger",
    ]
    for fb in fallback_paths:
        if fb.exists() and os.access(fb, os.X_OK):
            return str(fb)

    return "spaceranger"

SPACERANGER_BIN = find_spaceranger_bin()

app = FastAPI(
    title="Visium HD RNA Quantity Per Cell QC Platform",
    description="Web platform for estimating single-cell RNA quantity on FFPE sections using Space Ranger and Qubit quantification",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static and runs directories
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/runs", StaticFiles(directory=str(RUNS_DIR)), name="runs")

jobs_db = {}

def load_jobs():
    global jobs_db
    if JOBS_FILE.exists():
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                jobs_db = json.load(f)
        except Exception:
            jobs_db = {}
    else:
        jobs_db = {}

def save_jobs():
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs_db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving jobs: {e}", file=sys.stderr)

load_jobs()

# Conversion multipliers to standard units:
# Concentration -> ng/uL
CONC_TO_NG_UL = {
    "ng/ul": 1.0,
    "ng/ml": 0.001,
    "ug/ul": 1000.0,
    "mg/ul": 1000000.0,
}

# Volume -> uL
VOL_TO_UL = {
    "ul": 1.0,
    "ml": 1000.0,
}

class UploadInitRequest(BaseModel):
    file_id: str
    filename: str
    filesize: int
    chunk_size: int
    total_chunks: int

class AnalyzeRequest(BaseModel):
    file_id: str
    filename: str
    sample_name: Optional[str] = "Sample_1"
    section_thickness_um: float = 5.0
    section_count: int = 2
    qubit_concentration: float
    qubit_unit: str = "ng/ul"
    elution_volume: float
    volume_unit: str = "ul"
    threads: int = 32

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index():
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return FileResponse(str(html_file))
    return HTMLResponse("<h1>Visium HD QC Platform is running. Please place static/index.html.</h1>")

@app.post("/api/upload/init")
def upload_init(req: UploadInitRequest):
    upload_path = UPLOADS_DIR / req.file_id
    upload_path.mkdir(parents=True, exist_ok=True)
    meta_path = upload_path / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(req.dict(), f)
    return {"status": "success", "message": "Upload initialized", "file_id": req.file_id}

@app.get("/api/upload/status")
def upload_status(file_id: str):
    upload_path = UPLOADS_DIR / file_id
    if not upload_path.exists():
        return {"uploaded_chunks": [], "completed": False}

    meta_path = upload_path / "meta.json"
    if not meta_path.exists():
        return {"uploaded_chunks": [], "completed": False}

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    chunks_dir = upload_path / "chunks"
    uploaded_chunks = []
    if chunks_dir.exists():
        for chunk_file in chunks_dir.glob("chunk_*"):
            try:
                idx = int(chunk_file.name.replace("chunk_", ""))
                uploaded_chunks.append(idx)
            except ValueError:
                pass
    uploaded_chunks.sort()

    final_file = upload_path / meta["filename"]
    completed = final_file.exists() and final_file.stat().st_size == meta["filesize"]

    return {
        "file_id": file_id,
        "filename": meta["filename"],
        "filesize": meta["filesize"],
        "total_chunks": meta["total_chunks"],
        "uploaded_chunks": uploaded_chunks,
        "completed": completed
    }

@app.post("/api/upload/chunk")
async def upload_chunk(
    file_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk_file: UploadFile = File(...)
):
    upload_path = UPLOADS_DIR / file_id
    chunks_dir = upload_path / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_target = chunks_dir / f"chunk_{chunk_index}"
    with open(chunk_target, "wb") as f:
        content = await chunk_file.read()
        f.write(content)

    return {"status": "success", "chunk_index": chunk_index}

@app.post("/api/upload/finish")
def upload_finish(file_id: str = Form(...)):
    upload_path = UPLOADS_DIR / file_id
    meta_path = upload_path / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Upload metadata not found")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    filename = meta["filename"]
    total_chunks = meta["total_chunks"]
    final_file = upload_path / filename
    chunks_dir = upload_path / "chunks"

    # Merge chunks in order
    with open(final_file, "wb") as out_f:
        for i in range(total_chunks):
            chunk_file = chunks_dir / f"chunk_{i}"
            if not chunk_file.exists():
                raise HTTPException(status_code=400, detail=f"Chunk {i} missing during merge")
            with open(chunk_file, "rb") as in_f:
                shutil.copyfileobj(in_f, out_f)

    # Clean up chunk fragments
    shutil.rmtree(chunks_dir, ignore_errors=True)

    return {
        "status": "success",
        "message": "File reassembled successfully",
        "file_id": file_id,
        "filename": filename,
        "filesize": final_file.stat().st_size,
        "file_path": str(final_file)
    }

def run_segmentation_task(job_id: str):
    job = jobs_db.get(job_id)
    if not job:
        return

    job["status"] = "running"
    job["started_at"] = time.time()
    save_jobs()

    run_dir = RUNS_DIR / job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_image_path = Path(job["image_path"])
    log_file = run_dir / "execution.log"

    # Pre-processing: Check if image requires format conversion (.svs, .sdpc, etc.)
    with open(log_file, "w", encoding="utf-8") as log_f:
        log_f.write(f"=== Visium HD Pre-Analysis Phase ===\n")
        log_f.write(f"Input file: {raw_image_path.name}\n")
        log_f.flush()

        try:
            def log_progress(pct: float, msg: str):
                log_f.write(f"[{int(pct * 100)}%] {msg}\n")
                log_f.flush()

            image_path = Path(auto_convert_to_bigtiff(
                str(raw_image_path),
                output_dir=str(run_dir),
                progress_cb=log_progress
            ))
            log_f.write(f"Validated Space Ranger input image: {image_path.name}\n\n")
            log_f.flush()
        except Exception as conv_err:
            log_f.write(f"Format conversion error: {conv_err}\n")
            log_f.flush()
            job["status"] = "failed"
            job["error"] = f"Image format conversion failed: {conv_err}"
            job["completed_at"] = time.time()
            save_jobs()
            return

    env = os.environ.copy()
    spaceranger_exec = find_spaceranger_bin()
    bin_dir = str(Path(spaceranger_exec).parent)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    cmd = [
        spaceranger_exec, "segment",
        f"--id={job_id}",
        f"--tissue-image={str(image_path)}",
        f"--localcores={job['threads']}",
        "--localmem=64"
    ]

    with open(log_file, "a", encoding="utf-8") as log_f:
        log_f.write(f"=== Space Ranger Segment Execution Started ===\n")
        log_f.write(f"Binary: {spaceranger_exec}\n")
        log_f.write(f"Command: {' '.join(cmd)}\n")
        log_f.write(f"Working Directory: {str(run_dir)}\n\n")
        log_f.flush()

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(run_dir),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=env,
                text=True
            )
            job["pid"] = process.pid
            save_jobs()

            process.wait()

            if process.returncode != 0:
                job["status"] = "failed"
                job["error"] = f"Space Ranger failed with return code {process.returncode}. Please review execution.log"
                job["completed_at"] = time.time()
                save_jobs()
                return

        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = time.time()
            save_jobs()
            return

    # Process results from outs directory
    outs_dir = run_dir / job_id / "outs"
    metrics_file = outs_dir / "metrics_summary.json"
    geojson_file = outs_dir / "nucleus_segmentations.geojson"
    web_summary_file = outs_dir / "web_summary.html"

    nuclei_count = 0
    if metrics_file.exists():
        try:
            with open(metrics_file, "r") as mf:
                data = json.load(mf)
                nuclei_count = data.get("num_nuclei_detected_by_model", 0)
        except Exception:
            pass

    if nuclei_count == 0 and geojson_file.exists():
        try:
            with open(geojson_file, "r") as gf:
                data = json.load(gf)
                nuclei_count = len(data.get("features", []))
        except Exception:
            pass

    job["nuclei_count"] = nuclei_count
    job["outs_dir"] = str(outs_dir)
    job["web_summary_available"] = web_summary_file.exists()
    job["completed_at"] = time.time()

    # Calculate QC metrics
    # 1. Normalize units
    conc_unit = job.get("qubit_unit", "ng/ul").lower()
    conc_raw = float(job.get("qubit_concentration", 0))
    conc_ng_ul = conc_raw * CONC_TO_NG_UL.get(conc_unit, 1.0)

    vol_unit = job.get("volume_unit", "ul").lower()
    vol_raw = float(job.get("elution_volume", 0))
    vol_ul = vol_raw * VOL_TO_UL.get(vol_unit, 1.0)

    # 2. Total RNA extracted in pg
    total_rna_ng = conc_ng_ul * vol_ul
    total_rna_pg = total_rna_ng * 1000.0

    # 3. RNA per section
    sec_count = max(1, int(job.get("section_count", 1)))
    thickness_um = float(job.get("section_thickness_um", 5.0))
    rna_per_section_pg = total_rna_pg / sec_count

    # 4. RNA per cell (actual section)
    if nuclei_count > 0:
        rna_per_cell_actual = rna_per_section_pg / nuclei_count
        # Normalized to 10x standard 5 um section
        rna_per_cell_norm5um = rna_per_cell_actual * (5.0 / thickness_um)
    else:
        rna_per_cell_actual = 0.0
        rna_per_cell_norm5um = 0.0

    # 5. 10x Genomics official QC evaluation criteria
    # Thresholds: > 0.75 Better, 0.4 - 0.75 Moderate, < 0.4 Poor
    eval_val = rna_per_cell_norm5um if thickness_um != 5.0 else rna_per_cell_actual
    if eval_val >= 0.75:
        qc_grade = "Better"
        qc_grade_cn = "优质样本 (推荐上机)"
        badge_class = "success"
        recommendation = "样本质量优良，单细胞转录本含量丰沛。满足 10x Genomics 官方 Visium HD 上机标准 (> 0.75 pg/cell)，测序将获得极佳的 Median UMI/Gene 检出率与细胞聚类分辨率，强烈推荐进行后续实验。"
    elif eval_val >= 0.4:
        qc_grade = "Moderate"
        qc_grade_cn = "中等质量 (谨慎上机)"
        badge_class = "warning"
        recommendation = "样本质量处于 10x 官方中等灵敏度区间 (0.4 - 0.75 pg/cell)。组织存在轻度降解或部分细胞核区域 RNA 丰度偏低。可结合组织形态稀缺性与项目研究目的评估是否继续上机；如下机建议适当加深测序量。"
    else:
        qc_grade = "Poor"
        qc_grade_cn = "高风险样本 (不推荐上机)"
        badge_class = "danger"
        recommendation = "低于 10x 官方建议警戒线 (< 0.4 pg/cell)。当前样本细胞密度虽高但有效提取的 RNA 极匮乏（通常因福尔马林过度交联、RNA 严重片段化降解或脱蜡不全导致）。上机极可能产生极低的 UMI 分子检出率导致建库失败，官方建议：Not Recommended，建议更换蜡块重制。"

    job["results"] = {
        "conc_ng_ul": round(conc_ng_ul, 4),
        "vol_ul": round(vol_ul, 2),
        "total_rna_ng": round(total_rna_ng, 2),
        "total_rna_pg": round(total_rna_pg, 2),
        "rna_per_section_pg": round(rna_per_section_pg, 2),
        "nuclei_count": nuclei_count,
        "section_thickness_um": thickness_um,
        "section_count": sec_count,
        "rna_per_cell_actual_pg": round(rna_per_cell_actual, 4),
        "rna_per_cell_norm5um_pg": round(rna_per_cell_norm5um, 4),
        "qc_grade": qc_grade,
        "qc_grade_cn": qc_grade_cn,
        "badge_class": badge_class,
        "recommendation": recommendation,
        "web_summary_url": f"/runs/{job_id}/{job_id}/outs/web_summary.html" if web_summary_file.exists() else None
    }
    job["status"] = "completed"
    save_jobs()

@app.post("/api/analyze")
def submit_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    upload_path = UPLOADS_DIR / req.file_id
    final_file = upload_path / req.filename
    if not final_file.exists():
        raise HTTPException(status_code=404, detail="Uploaded image file not found")

    job_id = f"QC_{int(time.time())}_{req.sample_name or 'Sample'}"
    jobs_db[job_id] = {
        "job_id": job_id,
        "sample_name": req.sample_name,
        "file_id": req.file_id,
        "filename": req.filename,
        "image_path": str(final_file),
        "section_thickness_um": req.section_thickness_um,
        "section_count": req.section_count,
        "qubit_concentration": req.qubit_concentration,
        "qubit_unit": req.qubit_unit,
        "elution_volume": req.elution_volume,
        "volume_unit": req.volume_unit,
        "threads": req.threads,
        "status": "queued",
        "created_at": time.time(),
        "started_at": None,
        "completed_at": None,
        "results": None
    }
    save_jobs()

    background_tasks.add_task(run_segmentation_task, job_id)

    return {"status": "success", "job_id": job_id}

@app.get("/api/job/{job_id}")
def get_job_status(job_id: str):
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run_dir = RUNS_DIR / job_id
    log_file = run_dir / "execution.log"
    logs = ""
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                logs = f.read()[-5000:]
        except Exception:
            pass

    return {
        "job": job,
        "latest_logs": logs
    }

@app.get("/api/jobs")
def list_jobs():
    return {"jobs": list(jobs_db.values())}

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description="Visium HD RNA Quantity QC Web Platform")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 20100)), help="Port to listen on")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="Root directory for uploads and runs")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir

    print(f"[*] Starting Visium HD RNA QC Platform on http://{args.host}:{args.port}")
    print(f"[*] Data storage directory: {args.data_dir}")
    print(f"[*] Resolved Space Ranger binary: {SPACERANGER_BIN}")
    uvicorn.run("app:app", host=args.host, port=args.port, workers=args.workers)
