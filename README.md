# 🧬 Space Ranger Visium HD RNA Quantity Per Cell QC Web Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Space Ranger: 4.x](https://img.shields.io/badge/Space%20Ranger-4.1.0-brightgreen.svg)](https://www.10xgenomics.com/support/software/space-ranger/latest)
[![Framework: FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)

> **Visium HD 空间转录组单细胞 RNA 含量评估与上机前质控 Web 平台**  
> 一键集成 10x Genomics 官方 **Step 2.6: RNA Quantity per Cell Estimation** 标准规范与 Space Ranger 深度学习形态学细胞核分割模型。

---

## 📖 背景与科学意义 (Background)

在开展 **10x Genomics Visium HD** 空间转录组实验前，FFPE 组织蜡块中**单个细胞的实际有效 RNA 丰度**是决定后续测序 UMI 产出与数据质量的最关键预测指标之一。

若样本虽细胞核密集，但因福尔马林过度交联或严重降解导致单细胞 RNA 匮乏，盲目上机将造成高昂的芯片与测序资源浪费。10x Genomics 官方在《*Visium HD FFPE Tissue Preparation Handbook*》中推出了 **Step 2.6 评估标准**：通过结合连续切片的提取 RNA 总量与 HE 图像深度学习分割出的总细胞核数，定量计算**每细胞 RNA 含量 (pg RNA / cell)**。

本平台提供轻量、直观、开箱即用的现代化 Web 应用，解决大图上传中断、参数单位混乱与公式换算繁琐的痛点。

---

## 🌟 核心特性 (Key Features)

1. **Space Ranger 4.x StarDist 细胞核实例分割**
   - 自动调用 `spaceranger segment` 深度学习管道，精准提取高分辨率显微切片（WSI）上的全部细胞核。
   - 原生支持输出与在线查看 10x `web_summary.html` 报告与矢量细胞轮廓。
2. **多格式扫描切片原生与自动无损转码支持 (`.tif`, `.btf`, `.svs`, `.sdpc`)**
   - 支持主流切片扫描仪输出格式。若用户上传 **`.svs` (Aperio)** 或 **`.sdpc` (胜强/Sqray)**，系统后台自动激活无损转码引擎，将其流式重构为 10x Space Ranger 严格兼容的标准金字塔 BigTIFF (`.btf`)，确保 100% 原始像素精度（Level 0 零损失）。
3. **超大 HE 显微图像分片与断点续传**
   - 采用前端 HTML5 File API 分片技术（每片 10MB），支持数十 GB 级别的显微图像顺畅上传。
   - 包含实时进度条、速率显示、断点记忆与断网自动重试。
4. **多单位自动换算与切片厚度归一化**
   - **Qubit 测定浓度**：支持 `ng/µL`、`ng/mL`、`µg/µL`、`mg/µL` 任意切换。
   - **洗脱体积**：支持 `µL` 与 `mL` 切换。
   - **厚度与张数**：支持自定义切片厚度（如 2 µm、5 µm、10 µm）与提取切片卷数。针对非 5 µm 切片，系统自动根据体积换算为 **5 µm 标准等效归一化值**。
5. **10x 官方标准质控评估与报告依据**
   - **> 0.75 pg / cell**：**Better Quality (优质样本)**，强烈建议上机；
   - **0.4 – 0.75 pg / cell**：**Moderate Quality (中等质量)**，谨慎评估上机；
   - **< 0.4 pg / cell**：**Poor Quality (高风险/不推荐)**，建议重新制样。
6. **一键交互式安装脚本 (`setup.sh`)**
   - 硬件资源自检、依赖包检测、Space Ranger 官方下载向导与端口配置一站式引导。

---

## 🚀 快速上手 (Quick Start)

### 1. 克隆代码库 (Clone Repository)

```bash
# 通过 Git 克隆
git clone https://github.com/yunissuper/Spaceranger-web-QC.git
cd Spaceranger-web-QC

# 或直接通过 wget 下载压缩包
wget https://github.com/yunissuper/Spaceranger-web-QC/archive/refs/heads/main.zip
unzip main.zip && cd Spaceranger-web-QC-main
```

### 2. 运行一键交互式安装向导 (Run Setup Script)

我们提供了友好、严谨的交互式安装脚本，会全自动引导完成环境检测、Space Ranger 部署与 Web 服务启动：

```bash
chmod +x setup.sh
./setup.sh
```

#### 引导步骤概览：
1. **系统环境检测**：检查 CPU 核心、内存（建议 $\ge 32\text{GB}$）与磁盘可用空间；
2. **Python 环境检测**：自动安装 FastAPI、Uvicorn 等必要依赖；
3. **Space Ranger 部署引导**：
   - 自动检测已有 Space Ranger；
   - 若未安装，输出 10x 官方协议下载地址：[10x Genomics Space Ranger Downloads](https://www.10xgenomics.com/support/software/space-ranger/downloads)；
   - 粘贴官网生成的带 Token 下载链接或本地 `.tar.gz` 路径，脚本自动下载解压并加入环境；
4. **端口与网络配置**：交互式设定监听端口（默认 `20100`）；
5. **服务启动**：提供前台运行、后台守护进程 (nohup) 或注册为 Linux Systemd 用户服务。

---

## 📐 算法与计算逻辑 (Formulation)

$$\text{Total RNA Extracted (pg)} = \text{Qubit 浓度 (ng/}\mu\text{L)} \times \text{洗脱体积 (}\mu\text{L)} \times 1000$$

$$\text{RNA per Section (pg)} = \frac{\text{Total RNA Extracted (pg)}}{\text{提取切片张数}}$$

$$\text{RNA per Cell (Actual)} = \frac{\text{RNA per Section (pg)}}{\text{Space Ranger 识别细胞核总数}}$$

$$\text{Normalized to 5}\mu\text{m (pg/cell)} = \text{RNA per Cell (Actual)} \times \left(\frac{5.0}{\text{切片厚度}(\mu\text{m})}\right)$$

---

## 📊 10x Genomics 官方评判准则 (QC Decision Matrix)

| 单细胞 RNA 含量 (pg/cell) | 质量评级 | 官方评估依据与操作建议 |
| :--- | :--- | :--- |
| **> 0.75 pg / cell** | **优质样本 (Better Quality)** | **强烈推荐上机**。转录本丰度优良，测序 UMI 检出率与细胞分群灵敏度极高。 |
| **0.4 – 0.75 pg / cell** | **中等质量 (Moderate Quality)** | **谨慎上机**。存在轻度降解或部分细胞低丰度，建议结合样本稀缺度评估并适当加深测序。 |
| **< 0.4 pg / cell** | **高风险样本 (Poor Quality)** | **不建议上机 (Not Recommended)**。有效 RNA 严重匮乏，极大概率建库失败或 UMI 极低。 |

---

## 🌐 生产环境与外网访问 (Network & Proxy)

Web 服务默认监听在本地 `127.0.0.1:<PORT>`。若需提供给团队成员通过外网或局域网访问：
* **局域网访问**：直接访问 `http://<局域网IP>:<PORT>`
* **外网穿透 (FRP / Nginx)**：
  在反向代理工具中，将对外端口转发至本机的 `127.0.0.1:<PORT>` 即可。

---

## 📂 项目结构 (Project Structure)

```
Spaceranger-web-QC/
├── app.py                 # FastAPI 核心服务与后台异步计算引擎
├── setup.sh               # 交互式全自动硬件检查、环境引导与部署脚本
├── requirements.txt       # Python 依赖清单
├── DEVELOPMENT.md         # 架构设计、接口契约与开发者手册
├── LICENSE                # MIT 开源授权协议
├── .gitignore             # 忽略缓存、切片大图及运行结果
└── static/
    └── index.html         # 响应式 Web 前端 (含分片断点续传、仪表盘与报告展示)
```

---

## 📄 开源许可证 (License)

本项目采用 [MIT License](LICENSE) 授权开源。欢迎贡献代码与提出 Issue！
