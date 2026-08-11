# CCNA AI Tutor

A terminal-based, AI-powered CCNA study companion I built while prepping for my own CCNA exam — because most study tools either quiz you on flashcards or dump a wall of text on you, and neither actually teaches the way a good tutor does.

## Why I built this

I'm a 4th-year student studying Network Security and Enterprise Architecture, prepping for CCNA on the side. I kept running into the same problem: I could re-read notes all day and still blank out on the actual exam, because re-reading *feels* like learning but doesn't test whether you actually know something.

So I started building a tutor that applies actual learning science instead of just being a chatbot wrapper — spaced repetition, retrieval practice, personalized re-teaching based on your specific mistakes, confidence calibration, and hands-on lab reflection. It grew a lot past the original scope (started as "quiz me on subnetting," ended up as a full adaptive study system with mock exams, CLI practice, and guided Packet Tracer labs) — which is honestly the best part of building your own tools: you find out what you actually need by using it.

## What it does

**Core learning loop**
- Spaced repetition scheduling (SM-2 style) — reviews topics right before you'd naturally forget them, not on a fixed schedule
- Explanations open with a real-world analogy before diving into technical detail, and get personalized to specifically address your past mistakes on that topic
- Every explanation ends in a quick check question — testing yourself right after learning something cements it far better than just reading

**Practice modes**
- **Flashcards** — fast, atomic fact drilling (port numbers, timers, AD values)
- **Comparison drills** — targets CCNA's classic confusion pairs (OSPF vs EIGRP, TCP vs UDP, standard vs extended ACLs)
- **CLI command practice** — real Cisco IOS syntax tasks, graded for correctness
- **Troubleshooting cases** — a broken-network scenario with realistic command output; you diagnose the root cause, not just recall facts
- **Real-world scenarios** — topology/packet-flow diagrams, workplace triage judgment calls, and applied network design questions
- **Packet Tracer guided labs** — hands-on labs scaffolded to your mastery level, with a memory-based recall check afterward and reflection prompts grounded in Kolb's experiential learning cycle

**Exam prep**
- Timed mock exams, question distribution weighted to match the real CCNA blueprint domain percentages
- Confidence rating on every answer, tracked against actual accuracy — flags topics where you're confidently *wrong*, which is more dangerous than knowing you don't know something

**Under the hood**
- Multi-provider AI support (Claude, Gemini, Groq) — swap providers mid-session, automatic retry on failure
- Fully normalized SQLite schema with versioned migrations, so the database structure can evolve without ever losing your study history
- Full backup/restore, study streak tracking, and a mistake-review mode pulling your errors across every practice mode into one place

## Tech stack

- Python 3
- SQLite (normalized schema, foreign keys, indexes, versioned migrations via `PRAGMA user_version`)
- Claude API (Haiku), with optional Gemini and Groq support
- No frameworks — just a clean CLI, because the learning logic mattered more than the interface

## Setup

```bash
pip install anthropic
export ANTHROPIC_API_KEY='sk-ant-...'
python3 main.py
```

Optional: set `GEMINI_API_KEY` or `GROQ_API_KEY` to use those providers instead (switchable at runtime from the Settings menu).

## What I'd build next

- A weak-domain snapshot view outside of mock exams
- Study plan generation based on exam date
- Porting the same engine to other subjects (it's not actually CCNA-specific under the hood — the spaced repetition, mistake tracking, and calibration system would work for any topic list)

## A note on how this was built

I built this iteratively with Claude, going feature by feature as I actually hit friction points in my own studying rather than planning the whole thing upfront — which is reflected in the commit history. Every database schema change was tested against simulated old data before shipping, since losing real study history partway through development would have defeated the whole point.
