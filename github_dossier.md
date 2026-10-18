# VERIFIED GITHUB PROJECT DOSSIER — Chinmay Maheshwari (@Chinmay0608)

The following technical facts, features, dependencies, and architectures are extracted directly from the candidate's real GitHub repositories.
When tailoring or refining resume points, USE ONLY these verified facts. NEVER invent outside systems or fake metrics.

## Project: distributed-order-processing
- **Repository**: https://github.com/Chinmay0608/distributed-order-processing
- **Primary Tech**: HTML
- **Verified Modules/Files**: .agents/rules/graphify.md, .agents/rules/ponytail.md, .agents/rules/ui-ux-pro-max.md, .agents/skills/ponytail/SKILL.md, .agents/skills/ui-ux-pro-max/SKILL.md, .agents/workflows/graphify.md, .gitignore, BUILD_ORDER.md, Distributed_Order_Processing_HLD.pdf, GEMINI.md, README.md, docker-compose.yml

**Key Architecture & Code Details (from README):**
```text
# Distributed Order Processing System

A production-grade distributed order processing engine built to eliminate inventory overselling under high-concurrency burst traffic and orchestrate asynchronous order fulfillment. It implements **distributed concurrency control via Redis (Redisson)**, **idempotent transaction intake with SHA-256 payload fingerprinting**, **asynchronous event streaming with Apache Kafka**, **transactional saga compensation for payment failures**, and an **interactive system telemetry dashboard**.

---

## Architecture Overview

<p align="center">
  <img src="frontend/public/preview-distributed-order-processing.png" alt="Distributed Order Processing System Architecture & Workflow" width="100%" />
</p>

<details>
<summary><b>View Text Blueprint (ASCII Diagram)</b></summary>

```
                            [ React Frontend (Vite) ]
                           (http://localhost:3000)
                                      │
                         REST API (HTTP / JSON)
                                      │
                                      ▼
                        [ Module 1: order-service ]
                           (http://localhost:8080)
                         ┌────────────┴────────────┐
                         │                         │
                         ▼                         ▼
         [ Redis: lock:inventory:{productId} ]   [ MongoDB: orders & products ]
         (Redisson distributed lock: 500ms wait)  (Atomic $gte stock check & update)
                         │
                  Kafka Event: order-placed
                         │
                         ▼
                     [ Apache Kafka Cluster ]
                         │
                         ▼
                     [ Module 2: processing-service ]
           
```

--------------------------------------------------

## Project: job-portal-system
- **Description**: Full Stack Job Portal using MERN Stack
- **Live Demo**: https://job-portal-system-alpha.vercel.app
- **Repository**: https://github.com/Chinmay0608/job-portal-system
- **Primary Tech**: JavaScript
- **Verified Dependencies**: @google/genai, @xenova/transformers, axios, bcryptjs, bullmq, cheerio, cloudinary, cookie-parser, cors, dotenv, express, express-async-handler, express-mongo-sanitize, express-rate-limit, express-validator
- **Verified Modules/Files**: .agent/mcp.json, .agent/skills/ui-ux-pro-max/SKILL.md, .agent/skills/ui-ux-pro-max/data/charts.csv, .agent/skills/ui-ux-pro-max/data/colors.csv, .agent/skills/ui-ux-pro-max/data/icons.csv, .agent/skills/ui-ux-pro-max/data/landing.csv, .agent/skills/ui-ux-pro-max/data/products.csv, .agent/skills/ui-ux-pro-max/data/react-performance.csv, .agent/skills/ui-ux-pro-max/data/stacks/astro.csv, .agent/skills/ui-ux-pro-max/data/stacks/flutter.csv, .agent/skills/ui-ux-pro-max/data/stacks/html-tailwind.csv, .agent/skills/ui-ux-pro-max/data/stacks/jetpack-compose.csv

**Key Architecture & Code Details (from README):**
```text
# SkillBridge 🚀

**Bridging talent and opportunity in one intelligent job portal.**

SkillBridge is an enterprise-grade full-stack job portal built for candidates, recruiters, and administrators to connect, apply, manage applications, and aggregate global career opportunities. Powered by a high-performance MERN architecture, Redis caching, AI-assisted career coaching, and automated multi-provider job aggregation.

---

## 🌟 Live Demo & Preview

- **Web App**: [https://job-portal-system-alpha.vercel.app](https://job-portal-system-alpha.vercel.app)
- **Backend API**: Hosted on Render with distributed cron execution and Mongo Atlas.

---

## 🚀 Key Highlights

- 🤖 **DHRUV AI Career Coach**: Voice-enabled AI assistant supporting hands-free Speech-to-Text (STT) and Text-to-Speech (TTS) voice readback for interactive career guidance, resume suggestions, and job matching.
- 🔄 **Single Data Engine (SDE) Sync**: Multi-provider live job aggregator (Adzuna API, Greenhouse, Lever ATS) featuring automated hash deduplication (`HashOptimizer`), domain signature verification (`SignatureVerifier`), and company lifecycle management (`LifecycleManager`).
- ⚡ **High-Performance Architecture**: Multi-level Redis caching, distributed cron locks (`SET NX EX`), and BullMQ background queues for zero-latency email dispatching.
- 🔒 **Enterprise Security**: Signed Cloudinary resume delivery, strict CORS controls, brute-force rate-limiting, and transparent Cookie Consent management.
- 🎨 **Modern Responsive UI**: Clean Tailwind CSS design system with custom dropdowns, glassmorphism advisory modals, and PWA capabilities.

---

## 🏗 System Architecture & Workflow

```mermaid
graph LR
    %% Custom Styles
    classDef client fill:#61DAFB,stroke:#333,stroke-width:2px,color:#000
    classDef api fill:#404
```

--------------------------------------------------

## Project: trao-ai-interview-prep-kit
- **Description**: Trao: Autonomous AI Interview Prep Kit generator with deterministic coverage engine, Next.js builder, and batch evaluation CLI
- **Live Demo**: https://trao-ai-interview-prep-kit-client.vercel.app
- **Repository**: https://github.com/Chinmay0608/trao-ai-interview-prep-kit
- **Primary Tech**: TypeScript
- **Verified Dependencies**: typescript
- **Verified Modules/Files**: .env.example, .gitignore, README.md, client/next-env.d.ts, client/next.config.mjs, client/package.json, client/postcss.config.js, client/src/app/globals.css, client/src/app/layout.tsx, client/src/app/page.tsx, client/src/components/auth/AuthPage.tsx, client/src/components/builder/KitBuilder.tsx

**Key Architecture & Code Details (from README):**
```text
# AI Interview Prep Kit

> **TRAO Engineering Assessment Submission**  
> **Document Type:** `ENGINEERING_ASSESSMENT`  
> **Assessment ID:** `FS-AI-INTERVIEW-01`  
> **AI Use Disclosure:** `assistive-permitted` (Used assistively for code structuring, testing acceleration, and refinement)  
> **Repository:** [https://github.com/Chinmay0608/trao-ai-interview-prep-kit](https://github.com/Chinmay0608/trao-ai-interview-prep-kit)

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Tech Stack & Justification](#2-tech-stack--justification)
3. [System Architecture](#3-system-architecture)
4. [Local Setup Instructions](#4-local-setup-instructions)
5. [Deployed Setup / Production URLs](#5-deployed-setup--production-urls)
6. [Batch Evaluation CLI](#6-batch-evaluation-cli)
7. [LLM Provider & Exact Model Configuration](#7-llm-provider--exact-model-configuration)
8. [Retrieval Approach & Grounding Sources](#8-retrieval-approach--grounding-sources)
9. [Research & Generation Sequencing](#9-research--generation-sequencing)
10. [Pipeline Step Breakdown](#10-pipeline-step-breakdown)
11. [State Representation: Generated, Edited & Pinned Items](#11-state-representation-generated-edited--pinned-items)
12. [Deterministic Schedule Allocation Logic](#12-deterministic-schedule-allocation-logic)
13. [Creative Features](#13-creative-features)
14. [Key Design Decisions](#14-key-design-decisions)
15. [Engineering Trade-offs](#15-engineering-trade-offs)
16. [Known Limitations](#16-known-limitations)
17. [Verification & Test Results](#17-verification--test-results)

---

## 1. Project Overview

The **AI Interview Prep Kit** is an end-to-end, production-ready system that transforms three basic user inputs:
1. **Job Description (JD)** (plain text, 100 – 50,000 characters)
2. **Compa
```

--------------------------------------------------

## Project: portfolio
- **Live Demo**: https://portfolio-skillbridge1.vercel.app
- **Repository**: https://github.com/Chinmay0608/portfolio
- **Primary Tech**: HTML
- **Verified Modules/Files**: distributed-order-preview.png, distributed-order-preview.svg, index.html, mindvault-preview.png, resume.pdf, skillbridge-preview.png

--------------------------------------------------
