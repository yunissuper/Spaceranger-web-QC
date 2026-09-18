# Developer & Architecture Guide - Visium HD RNA Quantity QC Platform

This document outlines the technical architecture, mathematical modeling, and REST API contract for the Visium HD Single-Cell RNA Quantity QC Platform.

---

## 1. System Architecture Overview

```
                      +---------------------------------------+
                      |         Web Browser Client            |
                      |  (Bootstrap 5 + Resumable Chunk Uploader)|
                      +-------------------+-------------------+
                                          |
                                HTTP / WebSocket
                                          |
                                          v
                      +---------------------------------------+
                      |       FastAPI Application Engine      |
                      |          (Dynamic Port: 20100)        |
                      +---------+-------------------+---------+
                                |                   |
                      Chunk Reassembly      Background Worker
                                |                   |
                                v                   v
                      +---------+----+    +---------+---------+
                      | Upload Cache |    | Lossless WSI      |
                      | (TIFF/SVS/   |--->| Converter         |
                      |  SDPC/BTF)   |    | (SVS/SDPC -> BTF) |
                      +--------------+    +---------+---------+
                                                    |
                                                    v
                                          +---------+---------+
                                          | Space Ranger 4.x  |
                                          | (StarDist Segment)|
                                          +---------+---------+
                                                    |
                                          Metrics Extraction
                                          & 10x QC Evaluation
                                                    |
                                                    v
                                          +---------+---------+
                                          | JSON Result &     |
                                          | Web Summary View  |
                                          +-------------------+
```

---

## 2. Mathematical Formulation & 10x Genomics Step 2.6

The calculation strictly adheres to the **10x Genomics Visium HD FFPE Tissue Preparation Handbook (Quality Assessment Step 2.6: RNA Quantity per Cell Estimation)**:

### 2.1 Standardized Unit Conversions
All inputs are normalized into standard scientific base units:
- **Concentration ($C$)**: Normalized to $\text{ng}/\mu\text{L}$
  $$\text{ng}/\mu\text{L} = \begin{cases} C, & \text{unit} = \text{ng}/\mu\text{L} \\ C \times 10^{-3}, & \text{unit} = \text{ng}/\text{mL} \\ C \times 10^{3}, & \text{unit} = \mu\text{g}/\mu\text{L} \\ C \times 10^{6}, & \text{unit} = \text{mg}/\mu\text{L} \end{cases}$$
- **Volume ($V$)**: Normalized to $\mu\text{L}$
  $$\mu\text{L} = \begin{cases} V, & \text{unit} = \mu\text{L} \\ V \times 1000, & \text{unit} = \text{mL} \end{cases}$$

### 2.2 Total RNA Quantification
$$\text{Total RNA Extracted (pg)} = C_{\text{ng}/\mu\text{L}} \times V_{\mu\text{L}} \times 1000$$

### 2.3 Per-Section RNA Allocation
Given $N_{\text{sections}}$ used during nucleic acid extraction:
$$\text{RNA per Section (pg)} = \frac{\text{Total RNA Extracted (pg)}}{N_{\text{sections}}}$$

### 2.4 Single-Cell RNA Estimation
Let $K_{\text{nuclei}}$ denote the total number of nuclei segmented by the Space Ranger deep learning model:
$$\text{RNA per Cell (Actual)} = \frac{\text{RNA per Section (pg)}}{K_{\text{nuclei}}}$$

### 2.5 5 µm Standard Equivalent Normalization
When a user cuts sections at non-standard thicknesses ($T \neq 5\ \mu\text{m}$), the cellular RNA yield is scaled according to slice volume to enable a direct comparison against the official 10x criteria:
$$\text{RNA per Cell (Normalized to } 5\ \mu\text{m)} = \text{RNA per Cell (Actual)} \times \left(\frac{5.0}{T}\right)$$

### 2.6 10x Quality Decision Tree
- **$> 0.75\ \text{pg/cell}$**: **Better Quality (Recommended)** — High transcript density, optimal UMI recovery.
- **$0.4 - 0.75\ \text{pg/cell}$**: **Moderate Quality (Proceed with Caution)** — Adequate for research-grade runs; sequencing depth may need to be increased.
- **$< 0.4\ \text{pg/cell}$**: **Poor Quality (Not Recommended)** — High risk of assay failure due to severe degradation or excessive formalin crosslinking.

---

## 3. REST API Contract

### `POST /api/upload/init`
Initialize an upload session.
```json
{
  "file_id": "f_sample_tif_123456",
  "filename": "sample_he.tif",
  "filesize": 104857600,
  "chunk_size": 10485760,
  "total_chunks": 10
}
```

### `GET /api/upload/status?file_id=<FILE_ID>`
Returns already uploaded chunk indices to support seamless resume across network hiccups.

### `POST /api/upload/chunk`
Multipart form upload of an individual chunk binary.

### `POST /api/upload/finish`
Triggers server-side sequential reassembly and validation of all chunks into the final TIFF file.

### `POST /api/analyze`
Submits a background task to invoke `spaceranger segment`.
```json
{
  "file_id": "f_sample_tif_123456",
  "filename": "sample_he.tif",
  "sample_name": "Breast_Tumor_01",
  "section_thickness_um": 5.0,
  "section_count": 2,
  "qubit_concentration": 12.5,
  "qubit_unit": "ng/ul",
  "elution_volume": 30.0,
  "volume_unit": "ul",
  "threads": 32
}
```

### `GET /api/job/{job_id}`
Polls job state, execution logs, and full quantitative QC metrics.

---

## 4. Contributing

1. Fork the repository and create a feature branch (`feature/your-feature-name`).
2. Commit your modifications with clear, descriptive commit messages.
3. Verify that the interactive installer (`setup.sh`) passes environmental checks.
4. Submit a Pull Request.
