"""
All LLM calls live here. Everything else in this app (db.py, topics.py)
is free local logic — this is the only file that costs money.

Supports two providers, toggleable at runtime (see set_provider / get_provider):
  - "claude": Anthropic Haiku 4.5, paid per token, ~cents for typical study use
  - "gemini": Google Gemini Flash, has a genuinely free daily tier — good fallback
              when you'd rather not touch the Claude credit balance.
Every function below (generate_question, grade_answer, explain_topic, etc.) is
provider-agnostic — they all just call _call(), which routes to whichever
provider is currently active.
"""

import json
import os
import time
import warnings
import anthropic

# These are harmless, cosmetic warnings from the underlying libraries (old Python version
# notices, OpenSSL version notices, and Gemini's "thought_signature" internal-reasoning
# notice) — none of them affect correctness, they just clutter the terminal. Silencing them.
warnings.filterwarnings("ignore")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
GEMINI_MODEL = "gemini-flash-latest"  # rolling alias — always points to Google's current stable Flash model,
                                       # so this won't break every time they deprecate a specific version
GROQ_MODEL = "llama-3.3-70b-versatile"  # genuinely free tier, no card, no expiration —
                                         # Groq's free tier exists to showcase their hardware,
                                         # so it isn't deprioritized under load the way Gemini's is

_provider = os.environ.get("AI_PROVIDER", "claude").lower()  # "claude", "gemini", or "groq"

_claude_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_gemini_client = None  # lazily created — only touched if you actually switch to Gemini
_groq_client = None    # lazily created — only touched if you actually switch to Groq


def get_provider() -> str:
    return _provider


def set_provider(name: str):
    global _provider
    name = name.lower().strip()
    if name not in ("claude", "gemini", "groq"):
        raise ValueError("provider must be 'claude', 'gemini', or 'groq'")
    _provider = name


def _call_claude(system: str, user: str, max_tokens: int) -> str:
    resp = _claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


def _clean_gemini_text(text: str) -> str:
    """Gemini sometimes assumes a math-rendering display and outputs LaTeX-style
    notation (e.g. $\\rightarrow$) that just looks like garbage in a plain terminal.
    Swap the common ones for their plain-text equivalents."""
    replacements = {
        r"$\rightarrow$": "→", r"\\rightarrow": "→",
        r"$\leftarrow$": "←", r"\\leftarrow": "←",
        r"$\times$": "×", r"\\times": "×",
        r"$\le$": "≤", r"\\le": "≤",
        r"$\ge$": "≥", r"\\ge": "≥",
    }
    for latex, plain in replacements.items():
        text = text.replace(latex, plain)
    return text


def _call_gemini(system: str, user: str, max_tokens: int) -> str:
    """
    Supports both Google Python SDKs so this works regardless of which one you installed:
      - google-genai      (current, recommended — 'from google import genai')
      - google-generativeai (older/legacy — 'import google.generativeai as genai')
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    try:
        from google import genai
        from google.genai import types
        global _gemini_client
        if _gemini_client is None:
            _gemini_client = genai.Client(api_key=api_key)
        resp = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return _clean_gemini_text(resp.text.strip())
    except ImportError:
        import google.generativeai as genai_legacy
        genai_legacy.configure(api_key=api_key)
        model = genai_legacy.GenerativeModel(GEMINI_MODEL, system_instruction=system)
        resp = model.generate_content(
            user, generation_config={"max_output_tokens": max_tokens}
        )
        return _clean_gemini_text(resp.text.strip())


class AIServiceError(Exception):
    """Raised when the AI provider fails after retries — meant to be caught and
    shown as a friendly message, not a raw traceback."""
    pass


def _call_groq(system: str, user: str, max_tokens: int) -> str:
    """Groq's API is OpenAI-compatible; the official 'groq' package mirrors that shape."""
    global _groq_client
    from groq import Groq
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    resp = _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content.strip()


def _call(system: str, user: str, max_tokens: int = 600, retries: int = 2) -> str:
    last_error = None
    for attempt in range(retries + 1):
        try:
            if _provider == "gemini":
                return _call_gemini(system, user, max_tokens)
            elif _provider == "groq":
                return _call_groq(system, user, max_tokens)
            return _call_claude(system, user, max_tokens)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))  # 2s, then 4s before giving up

    raise AIServiceError(
        f"{_provider.upper()} didn't respond after {retries + 1} tries "
        f"(likely temporarily overloaded or a connection issue). "
        f"Try again in a moment, or switch providers via Settings > Switch AI provider.\n"
        f"Underlying error: {last_error}"
    )


def generate_question(topic: str, difficulty: str = "beginner") -> str:
    """
    difficulty scales with mastery (db.get_mastery_level): beginner / intermediate / advanced.
    This is the 'desirable difficulty' lever — questions get harder as you improve,
    instead of staying static forever.
    """
    difficulty_guidance = {
        "beginner": "Test basic recall and understanding of the core concept. Straightforward, one clear concept.",
        "intermediate": "Present a short applied scenario (e.g. two devices, a specific config) and ask what "
                         "happens or what's wrong. Require connecting 2 related facts, not just recall.",
        "advanced": "Present a realistic troubleshooting or design scenario with a subtle gotcha "
                    "(edge case, common misconfiguration, or a case where the obvious answer is wrong). "
                    "Require reasoning through multiple steps.",
    }
    system = (
        "You are a CCNA exam tutor. Generate ONE open-ended CCNA study question "
        "about the given topic, requiring a typed explanation, not a multiple-choice guess. "
        f"Difficulty level: {difficulty}. {difficulty_guidance[difficulty]} "
        "Keep it realistic to actual CCNA exam style. "
        "Output ONLY the question text, nothing else — no preamble, no answer."
    )
    return _call(system, f"Topic: {topic}", max_tokens=200)


def grade_answer(topic: str, question: str, answer: str) -> dict:
    system = (
        "You are a CCNA exam tutor grading a student's typed answer. "
        "Be accurate and fair — CCNA has precise technical details "
        "(administrative distances, port states, timers, command syntax) that matter. "
        "In your feedback: don't just say right/wrong — briefly explain the REASONING "
        "behind the correct answer, so the student learns something even if they got it right. "
        "If wrong, gently correct the specific misconception, don't just restate the right answer. "
        "Respond with ONLY valid JSON, no markdown fences, matching this schema exactly: "
        '{"score": 0 or 1 or 2, "feedback": "3-5 sentences, direct, specific, and explanatory"} '
        "where score 0 = wrong/misconceived, 1 = partially correct or incomplete, "
        "2 = correct and sufficiently complete for CCNA level."
    )
    user = f"Topic: {topic}\nQuestion: {question}\nStudent's answer: {answer}"
    raw = _call(system, user, max_tokens=350)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def explain_topic(topic: str, depth: str = "normal", past_mistakes=None, follow_up: str = None) -> str:
    """
    depth: 'quick' (short refresher) or 'normal' (full teach with analogy + scenario + gotchas)
    past_mistakes: list of {question, your_answer, feedback} from db.get_past_mistakes,
                   used to personalize what gets extra emphasis — this is the 'learns from you' part.
    """
    if follow_up:
        system = (
            "You are a CCNA exam tutor. Answer the student's question clearly and precisely, "
            "at CCNA candidate level. Use a real-world analogy if it helps clarify. No fluff."
        )
        return _call(system, follow_up, max_tokens=700)

    depth_instructions = {
        "quick": (
            "Give a SHORT refresher: 1 real-world analogy in one sentence, then 4-6 bullet points "
            "of the most exam-critical facts only. No long sections, no headers beyond the analogy."
        ),
        "normal": (
            "Structure the explanation as:\n"
            "1. Open with ONE concrete real-world analogy that makes the concept click immediately "
            "(e.g. comparing VLANs to separate mailrooms in one office building).\n"
            "2. A short real-life scenario showing the concept in action on an actual network "
            "(specific device names/IPs are fine, keep it concrete not abstract).\n"
            "3. The core technical facts, concise, CCNA-exam-relevant only.\n"
            "4. 2-3 common exam gotchas or misconceptions, clearly flagged.\n"
            "Keep it readable — short paragraphs / bullets, not a wall of headers."
        ),
    }

    system = (
        "You are a CCNA exam tutor who teaches the way a good human tutor does: "
        "concrete analogies before abstract rules, real scenarios before terminology, "
        "and plain language. Be correct and precise, but never dry or reference-manual-like.\n\n"
        + depth_instructions[depth]
    )

    user = f"Explain: {topic}"
    if past_mistakes:
        mistake_summary = "\n".join(
            f"- Q: {m['question']}\n  Their answer: {m['your_answer']}\n  What they got wrong: {m['feedback']}"
            for m in past_mistakes
        )
        user += (
            f"\n\nIMPORTANT — this student has specifically struggled with these past questions "
            f"on this topic. Make sure your explanation directly addresses and clears up these "
            f"exact points of confusion, not just a generic overview:\n{mistake_summary}"
        )

    return _call(system, user, max_tokens=2500)


def generate_cli_scenario(topic: str) -> str:
    """Presents a networking task requiring actual Cisco IOS configuration commands."""
    system = (
        "You are a CCNA exam tutor running a hands-on CLI practice drill. "
        "Give ONE short, concrete network configuration task for the given topic — "
        "e.g. specific VLAN numbers, interface names (e.g. GigabitEthernet0/1), IP addresses, "
        "or ACL numbers/conditions to use. State the task clearly enough that it has one correct "
        "command sequence, but don't give the commands. "
        "Output ONLY the task description, nothing else — no preamble, no commands, no answer."
    )
    return _call(system, f"Topic: {topic}", max_tokens=200)


def grade_cli_commands(topic: str, scenario: str, commands: str) -> dict:
    """Grades typed Cisco IOS commands against a scenario. Lenient on valid shorthand/abbreviations."""
    system = (
        "You are a CCNA exam tutor grading a student's typed Cisco IOS commands against a task. "
        "Check: correct mode (global config vs interface vs line config), correct command syntax, "
        "correct order where order matters, and whether the commands actually accomplish the task. "
        "Cisco IOS allows valid abbreviations (e.g. 'int' for 'interface', 'conf t' for "
        "'configure terminal') — do NOT penalize valid shorthand. "
        "In feedback: if something's wrong, show what the correct command should be and why. "
        "Respond with ONLY valid JSON, no markdown fences, matching this schema exactly: "
        '{"score": 0 or 1 or 2, "feedback": "3-5 sentences, direct, specific, shows correct syntax if wrong"} '
        "where score 0 = wrong/would not work, 1 = partially correct or incomplete, "
        "2 = correct and would accomplish the task on a real device."
    )
    user = f"Topic: {topic}\nTask: {scenario}\nStudent's commands:\n{commands}"
    raw = _call(system, user, max_tokens=400)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def generate_troubleshooting_case(topic: str) -> str:
    """Presents a broken-network scenario with realistic command output containing a hidden root cause."""
    system = (
        "You are a CCNA exam tutor creating a network troubleshooting case study. "
        "Create ONE realistic troubleshooting scenario for the given topic: briefly describe the "
        "network setup, state the symptom (what's not working from the user/admin's perspective), "
        "and include realistic-looking command output (e.g. show ip route, show interfaces, "
        "show vlan brief, show ip ospf neighbor, ping results — whatever fits the topic) that "
        "contains ONE specific, deliberate misconfiguration causing the issue. "
        "Do NOT reveal the root cause or the fix — the student has to find it. "
        "Output ONLY the scenario, symptom, and command output. No preamble, no answer, no hints."
    )
    return _call(system, f"Topic: {topic}", max_tokens=600)


def grade_troubleshooting_answer(topic: str, scenario: str, answer: str) -> dict:
    """Grades a student's diagnosis + proposed fix against the actual root cause."""
    system = (
        "You are a CCNA exam tutor grading a student's network troubleshooting diagnosis. "
        "Check whether they correctly identified the root cause shown in the command output, "
        "and whether their proposed fix would actually resolve it. "
        "Give partial credit if they identified the right general area (e.g. 'it's a routing issue') "
        "but missed the exact cause or gave an incomplete/imprecise fix. "
        "In feedback: state the actual root cause clearly, and the correct fix (with the real command "
        "if applicable), even if the student got it right — reinforce the reasoning either way. "
        "Respond with ONLY valid JSON, no markdown fences: "
        '{"score": 0 or 1 or 2, "feedback": "3-5 sentences, direct, states the real root cause and fix"} '
        "where score 0 = wrong diagnosis, 1 = right general area but incomplete/imprecise, "
        "2 = correctly identified root cause and a working fix."
    )
    user = f"Topic: {topic}\nScenario:\n{scenario}\n\nStudent's diagnosis and fix:\n{answer}"
    raw = _call(system, user, max_tokens=400)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def generate_realworld_scenario(topic: str) -> str:
    """
    Generates a practical scenario question, randomly drawing from three real CCNA-style formats:
    network topology/packet-flow diagrams, workplace triage situations, or applied design problems.
    """
    system = (
        "You are a CCNA exam tutor creating a practical, real-world scenario question. "
        "Naturally choose whichever ONE of these three styles best fits the given topic:\n\n"
        "1. TOPOLOGY / PACKET-FLOW: Draw a small network topology using a clear ASCII diagram "
        "(routers, switches, PCs — label interfaces like Gi0/0, and include IP addresses/VLANs "
        "as relevant). Then ask a specific question about packet flow, device behavior, or the "
        "outcome of a given configuration (e.g. 'will R1 and R2 form an OSPF neighbor relationship?', "
        "'which interface does this packet exit?').\n\n"
        "2. WORKPLACE TRIAGE: Describe a realistic IT support/admin situation — a user complaint, "
        "an outage, a request from a manager — and ask what the correct first step, priority, or "
        "decision would be.\n\n"
        "3. APPLIED DESIGN: Describe a business requirement (a new department, a security need, "
        "a growing office) and ask the student to design or justify a technical solution.\n\n"
        "Pick whichever style fits the topic most naturally. Output ONLY the scenario and question "
        "— no preamble, no answer, no hint about which style you picked, no markdown headers."
    )
    return _call(system, f"Topic: {topic}", max_tokens=700)


def grade_realworld_scenario(topic: str, scenario: str, answer: str) -> dict:
    """Grades a real-world scenario answer — could be a packet-flow answer, a triage decision, or a design choice."""
    system = (
        "You are a CCNA exam tutor grading a student's answer to a practical scenario question. "
        "The scenario may involve packet-flow/topology reasoning, workplace triage judgment, or "
        "applied network design — grade against whichever applies. Check technical correctness "
        "AND practical soundness (e.g. for triage questions, did they prioritize sensibly; for "
        "design questions, is the solution actually appropriate for the stated requirement). "
        "In feedback: explain the correct reasoning or approach clearly, even if they got it right. "
        "Respond with ONLY valid JSON, no markdown fences: "
        '{"score": 0 or 1 or 2, "feedback": "3-5 sentences, direct and specific"} '
        "where score 0 = wrong/unsound, 1 = partially correct or reasonable but incomplete, "
        "2 = correct and well-reasoned."
    )
    user = f"Topic: {topic}\nScenario:\n{scenario}\n\nStudent's answer:\n{answer}"
    raw = _call(system, user, max_tokens=400)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def generate_mnemonic(topic: str) -> str:
    """A short memory aid (acronym/phrase/rhyme) for topics that are mostly rote memorization."""
    system = (
        "You are a CCNA tutor. Create ONE short, memorable mnemonic device (acronym, phrase, or "
        "rhyme) to help remember the given topic's key facts (e.g. OSI layer order, port numbers, "
        "STP port states). Briefly explain how each part of the mnemonic maps to what it represents. "
        "Keep it concise. Output ONLY the mnemonic and its brief mapping — no preamble."
    )
    return _call(system, f"Topic: {topic}", max_tokens=300)


def generate_flashcard(topic: str) -> dict:
    """One atomic, single-fact flashcard (not a broad concept) — for fast rote-recall drilling."""
    system = (
        "You are a CCNA tutor creating a flashcard. Pick ONE atomic, specific fact about the given "
        "topic — a port number, a timer value, an administrative distance, a specific term's exact "
        "definition — something testable in a single short fact, not a broad concept. "
        'Respond with ONLY valid JSON, no markdown fences: {"front": "short question", "back": "short answer"}'
    )
    raw = _call(system, f"Topic: {topic}", max_tokens=150)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def generate_comparison_question(topic_a: str, topic_b: str) -> str:
    """Targets CCNA's classic confusion pairs (OSPF vs EIGRP, TCP vs UDP, etc.)."""
    system = (
        "You are a CCNA tutor creating a question that tests the ability to distinguish between two "
        "related-but-different concepts that students commonly confuse. Ask a question that "
        "specifically requires contrasting them — e.g. when to use one vs the other, a key "
        "differentiating behavior, or a scenario where picking the wrong one causes a problem. "
        "Output ONLY the question, nothing else."
    )
    return _call(system, f"Compare: {topic_a} vs {topic_b}", max_tokens=250)


def grade_comparison_answer(topic_a: str, topic_b: str, question: str, answer: str) -> dict:
    system = (
        "You are a CCNA tutor grading a student's answer to a comparison question between two "
        "related concepts. Check whether they correctly captured the actual distinguishing factor, "
        "not just definitions of each in isolation. "
        "Respond with ONLY valid JSON, no markdown fences: "
        '{"score": 0 or 1 or 2, "feedback": "3-5 sentences, direct and specific"} '
        "where score 0 = wrong/missed the distinction, 1 = partially correct, "
        "2 = correctly captured the real distinguishing factor."
    )
    user = f"Comparing: {topic_a} vs {topic_b}\nQuestion: {question}\nStudent's answer: {answer}"
    raw = _call(system, user, max_tokens=350)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        return json.loads(raw[start:end])


def check_self_explanation(topic: str, original_feedback: str, self_explanation: str) -> str:
    """After a wrong/partial answer, the student re-explains the concept in their own words —
    the 'generation effect'. This gives brief confirmation/correction on that re-explanation."""
    system = (
        "You are a CCNA tutor. The student got a question wrong or partially right, received "
        "corrective feedback, and is now re-explaining the concept in their own words to reinforce "
        "learning. Give a SHORT (1-3 sentence) response: confirm if their explanation is now "
        "accurate, or gently point out what's still off if it isn't. Be encouraging either way."
    )
    user = f"Topic: {topic}\nOriginal corrective feedback: {original_feedback}\nStudent's self-explanation: {self_explanation}"
    return _call(system, user, max_tokens=200)


def generate_packet_tracer_lab(topic: str, mastery: str) -> str:
    """
    Generates a hands-on Packet Tracer lab brief, scaffolded by mastery level
    (Vygotsky's zone of proximal development — heavy guidance early, more
    autonomy as competence grows on this topic).
    """
    scaffold_guidance = {
        "beginner": (
            "Give detailed, explicit step-by-step instructions (device names, exact IPs/VLANs, "
            "exact interfaces) broken into 3-4 small numbered steps. Assume the student needs "
            "clear direction at each step."
        ),
        "intermediate": (
            "Give a topology and a list of 3-5 objectives to achieve, but do NOT specify exact "
            "commands — describe WHAT to accomplish, letting the student figure out HOW."
        ),
        "advanced": (
            "Give a single higher-level design goal and constraints (e.g. 'build a redundant "
            "Layer 3 design with OSPF between two switches, no single point of failure') without "
            "breaking it into steps — let the student plan their own approach."
        ),
    }
    system = (
        "You are a CCNA tutor designing a hands-on Cisco Packet Tracer lab activity for the given "
        "topic. The student will build this themselves in Packet Tracer (a separate program), not "
        "here. Include a clear topology description (device names, connections) using an ASCII "
        "diagram, and specify the goal(s).\n\n"
        f"{scaffold_guidance.get(mastery, scaffold_guidance['beginner'])}\n\n"
        "Output ONLY the lab brief — topology + instructions — nothing else. No preamble, no answer key."
    )
    return _call(system, f"Topic: {topic}", max_tokens=700)


def generate_lab_retrieval_questions(topic: str, lab_brief: str) -> str:
    """
    1-2 short recall questions testing whether the student actually internalized what they
    just built — meant to be answered from memory, without looking back at Packet Tracer.
    This is the testing effect applied right after hands-on practice.
    """
    system = (
        "You are a CCNA tutor. The student just finished building the following hands-on lab in "
        "Packet Tracer. Write 1-2 SHORT recall questions testing specific details of what they "
        "configured (an exact command, a specific value, or why a particular choice was made) — "
        "questions they should be able to answer from memory, without looking back at the lab "
        "brief or Packet Tracer. Output ONLY the question(s), nothing else."
    )
    return _call(system, f"Topic: {topic}\nLab they just completed:\n{lab_brief}", max_tokens=250)


def respond_to_reflection(topic: str, reflection_answers: dict) -> str:
    """
    Brief, warm engagement with the student's self-reflection after a hands-on lab —
    not graded, just closes the loop (Kolb's 'reflective observation' stage).
    """
    system = (
        "You are a supportive CCNA tutor. The student just reflected on a hands-on Packet Tracer "
        "lab they completed. Respond briefly (2-4 sentences) — acknowledge something specific "
        "they said, and if relevant, briefly connect their reflection to why it matters for "
        "real-world networking or the exam. Warm, conversational — no grading, no right/wrong framing."
    )
    user = f"Topic: {topic}\n" + "\n".join(f"{q}: {a}" for q, a in reflection_answers.items() if a)
    return _call(system, user, max_tokens=250)
