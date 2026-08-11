#!/usr/bin/env python3
import os
import random
import sys
import time

import db
import ai
from topics import TOPICS, DOMAINS, CLI_PRACTICE_TOPICS, COMPARISON_PAIRS


def check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n⚠️  ANTHROPIC_API_KEY environment variable not set.")
        print("Set it with:  export ANTHROPIC_API_KEY='sk-ant-...'")
        print("(add that line to your ~/.zshrc to make it permanent)\n")
        sys.exit(1)


def print_menu():
    streak = db.get_streak_info()
    if streak["current_streak"] > 0:
        streak_line = f"🔥 {streak['current_streak']}-day streak" + (
            "" if streak["studied_today"] else " (study today to keep it going!)"
        )
    else:
        streak_line = "No streak yet — study today to start one!"

    print(f"\n=== CCNA Tutor === [AI: {ai.get_provider().upper()}]")
    print(streak_line)
    print("1. Quiz me (spaced repetition)")
    print("2. Explain a topic")
    print("3. Flashcard mode")
    print("4. Comparison drill (X vs Y)")
    print("5. CLI command practice")
    print("6. Packet Tracer lab")
    print("7. Troubleshooting case")
    print("8. Real-world scenario")
    print("9. Mock exam (timed)")
    print("10. View progress")
    print("11. Review mistakes")
    print("12. Backup / restore progress")
    print("13. Switch AI provider (Claude / Gemini / Groq)")
    print("14. Quit")


def switch_provider_flow():
    current = ai.get_provider()
    print(f"\nCurrent provider: {current.upper()}")
    print("1. Claude")
    print("2. Gemini")
    print("3. Groq")
    choice = input("> ").strip()

    provider_map = {"1": "claude", "2": "gemini", "3": "groq"}
    key_env_map = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}

    if choice not in provider_map:
        print("Invalid choice.")
        return

    new_provider = provider_map[choice]
    if new_provider == current:
        print("Already on that provider — no change.")
        return

    required_key = key_env_map.get(new_provider)
    if required_key and not os.environ.get(required_key):
        print(f"\n⚠️  {required_key} not set. Set it first with:")
        print(f"   export {required_key}='your-key-here'")
        return

    ai.set_provider(new_provider)
    print(f"Switched — now using {new_provider.upper()} for all AI calls.")


def pick_from_list(items):
    """Prints a numbered list with a back option. Returns the chosen item, or None if backed out."""
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item}")
    print("  0. Back")
    choice = input("\nPick a number: ").strip().lower()
    if choice in ("0", "", "b", "back"):
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(items):
        return items[int(choice) - 1]
    print("Invalid choice.")
    return None


def ask_and_grade(topic: str, question: str, silent: bool = False, allow_quit: bool = False,
                   update_progress: bool = True):
    """
    Shared retrieval step: show question, get answer, grade, update DB.
    Returns the score (0/1/2), None if skipped, or "QUIT" if allow_quit and the user bails out.
    silent=True (used by the timed mock exam) skips confidence rating and self-explanation
    follow-ups, so the clock isn't held up by extra prompts.
    update_progress=False (used by the post-explanation check question) still grades and logs
    the attempt for your history, but does NOT touch topic_progress — meaning it won't affect
    your accuracy stats or spaced-repetition schedule. Testing yourself right after reading
    something is fundamentally different from testing yourself after a spaced interval, so the
    two shouldn't be averaged into the same mastery number.
    """
    print(f"\nQ: {question}")
    prompt = "\nYour answer (or type 'quit' to exit the exam early): " if allow_quit else "\nYour answer: "
    answer = input(prompt).strip()

    if allow_quit and answer.lower() in ("quit", "exit"):
        return "QUIT"

    if not answer:
        print("Skipped.")
        return None

    # Confidence rating — collected BEFORE grading, so seeing the result can't bias it.
    confidence = None
    if not silent:
        conf_raw = input(
            "How confident were you? [1] Guessing  [2] Somewhat sure  [3] Very sure: "
        ).strip()
        confidence = int(conf_raw) if conf_raw in ("1", "2", "3") else 2

    if not silent:
        print("Grading...")
    result = ai.grade_answer(topic, question, answer)
    score = result.get("score", 0)
    feedback = result.get("feedback", "")

    label = {0: "❌ Incorrect", 1: "🟡 Partial", 2: "✅ Correct"}[score]
    print(f"\n{label}")
    print(feedback)

    if update_progress:
        db.update_after_answer(topic, score)
    log_question = question if update_progress else f"[POST-EXPLAIN CHECK] {question}"
    db.log_session(topic, log_question, answer, score, feedback, confidence=confidence)

    # Self-explanation follow-up on mistakes — the "generation effect": re-explaining a
    # concept in your own words after correction cements it far better than just reading it.
    if not silent and score < 2:
        self_exp = input("\nIn your own words, explain the correct concept now: ").strip()
        if self_exp:
            print("\nChecking...")
            response = ai.check_self_explanation(topic, feedback, self_exp)
            print(f"\n{response}")

    return score


def quiz_flow():
    due = db.get_due_topics()
    if not due:
        print("\nNothing due right now — nice. Come back later, or explain a topic instead.")
        return

    topic = due[0]["topic"]
    difficulty = db.get_mastery_level(topic)
    print(f"\n--- Topic: {topic} (difficulty: {difficulty}) ---")
    print("Generating question...")
    question = ai.generate_question(topic, difficulty)
    ask_and_grade(topic, question)


def explain_flow():
    print("\nTopics:")
    for i, t in enumerate(TOPICS, 1):
        print(f"  {i}. {t}")
    print("  0. Back")
    choice = input("\nPick a number (or type a custom question): ").strip()

    if choice.lower() in ("0", "b", "back"):
        return

    if choice.isdigit() and 1 <= int(choice) <= len(TOPICS):
        topic = TOPICS[int(choice) - 1]

        depth_choice = input("Depth — (q)uick refresher or (n)ormal full explanation? [n]: ").strip().lower()
        depth = "quick" if depth_choice == "q" else "normal"

        past_mistakes = db.get_past_mistakes(topic)
        if past_mistakes:
            print(f"(Tailoring this to {len(past_mistakes)} thing(s) you've missed on this topic before)")

        print(f"\nExplaining: {topic}...\n")
        explanation = ai.explain_topic(topic, depth=depth, past_mistakes=past_mistakes)
        print(explanation)

        # Let confusion get resolved BEFORE testing on it, not after.
        while True:
            followup = input(
                "\nAnything confusing here? Type a question, or press Enter to continue: "
            ).strip()
            if not followup:
                break
            print("\nThinking...\n")
            print(ai.explain_topic(topic, follow_up=f"In the context of {topic}: {followup}"))

        mnemonic_choice = input("\nWant a mnemonic to help remember this? [y/N]: ").strip().lower()
        if mnemonic_choice == "y":
            print("\nGenerating mnemonic...\n")
            print(ai.generate_mnemonic(topic))

        # Testing effect: quiz immediately on what was just explained, while it's fresh.
        check = input("\nReady for a quick check question on this? [Y/n]: ").strip().lower()
        if check != "n":
            print("\nGenerating a question on what you just read...")
            question = ai.generate_question(topic, difficulty="beginner")
            ask_and_grade(topic, question, update_progress=False)
    else:
        print("\nAsking...\n")
        print(ai.explain_topic("custom", follow_up=choice))


def flashcard_flow():
    raw = input("\nHow many flashcards? [5]: ").strip()
    count = int(raw) if raw.isdigit() and int(raw) > 0 else 5

    due = db.get_due_topics()
    pool = [r["topic"] for r in due] if due else TOPICS

    correct = 0
    print(f"\n=== Flashcard Session: {count} card(s) ===")
    for i in range(count):
        topic = random.choice(pool)
        print(f"\n--- Card {i + 1}/{count} | {topic} ---")
        card = ai.generate_flashcard(topic)
        print(f"Q: {card['front']}")
        input("(press Enter to reveal the answer)")
        print(f"A: {card['back']}")

        rating = input("Did you get it right? [y/n/p = partial]: ").strip().lower()
        score = 2 if rating == "y" else (1 if rating == "p" else 0)
        if score == 2:
            correct += 1

        db.update_after_answer(topic, score)
        db.log_session(topic, f"[FLASHCARD] {card['front']}", card["back"], score, "Self-assessed")

    print(f"\nFlashcard session done: {correct}/{count} marked correct.")


def comparison_drill_flow():
    print("\nComparison pairs:")
    for i, (a, b) in enumerate(COMPARISON_PAIRS, 1):
        print(f"  {i}. {a}  vs  {b}")
    print("  0. Back")
    choice = input("\nPick a number: ").strip().lower()

    if choice in ("0", "", "b", "back"):
        return

    if not (choice.isdigit() and 1 <= int(choice) <= len(COMPARISON_PAIRS)):
        print("Invalid choice.")
        return

    topic_a, topic_b = COMPARISON_PAIRS[int(choice) - 1]
    label = f"{topic_a} vs {topic_b}"
    print(f"\n--- Comparison Drill: {label} ---")
    print("Generating question...")
    question = ai.generate_comparison_question(topic_a, topic_b)

    score = ask_and_grade_comparison(label, topic_a, topic_b, question)
    return score


def ask_and_grade_comparison(label: str, topic_a: str, topic_b: str, question: str):
    """Same shape as ask_and_grade, but routes through the comparison-specific grader."""
    print(f"\nQ: {question}")
    answer = input("\nYour answer: ").strip()
    if not answer:
        print("Skipped.")
        return None

    conf_raw = input("How confident were you? [1] Guessing  [2] Somewhat sure  [3] Very sure: ").strip()
    confidence = int(conf_raw) if conf_raw in ("1", "2", "3") else 2

    print("\nGrading...")
    result = ai.grade_comparison_answer(topic_a, topic_b, question, answer)
    score = result.get("score", 0)
    feedback = result.get("feedback", "")

    label_text = {0: "❌ Incorrect", 1: "🟡 Partial", 2: "✅ Correct"}[score]
    print(f"\n{label_text}")
    print(feedback)

    db.update_after_answer(label, score)
    db.log_session(label, question, answer, score, feedback, confidence=confidence)

    if score < 2:
        self_exp = input("\nIn your own words, explain the correct distinction now: ").strip()
        if self_exp:
            print("\nChecking...")
            response = ai.check_self_explanation(label, feedback, self_exp)
            print(f"\n{response}")

    return score


def cli_practice_flow():
    print("\nCLI-practicable topics:")
    topic = pick_from_list(CLI_PRACTICE_TOPICS)
    if topic is None:
        return

    print(f"\n--- CLI Practice: {topic} ---")
    print("Generating a task...")
    scenario = ai.generate_cli_scenario(topic)
    print(f"\nTask: {scenario}")

    print("\nType your Cisco IOS commands, one per line.")
    print("Enter a blank line when you're done:\n")
    lines = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line)

    if not lines:
        print("Skipped.")
        return

    commands = "\n".join(lines)
    print("\nGrading your commands...")
    result = ai.grade_cli_commands(topic, scenario, commands)
    score = result.get("score", 0)
    feedback = result.get("feedback", "")

    label = {0: "❌ Incorrect", 1: "🟡 Partial", 2: "✅ Correct"}[score]
    print(f"\n{label}")
    print(feedback)

    db.update_after_answer(topic, score)
    db.log_session(topic, f"[CLI PRACTICE] {scenario}", commands, score, feedback)


def packet_tracer_lab_flow():
    print("\nLab-practicable topics:")
    topic = pick_from_list(CLI_PRACTICE_TOPICS)
    if topic is None:
        return

    mastery = db.get_mastery_level(topic)
    print(f"\n--- Packet Tracer Lab: {topic} (scaffold level: {mastery}) ---")
    print("Generating your lab brief...")
    lab_brief = ai.generate_packet_tracer_lab(topic, mastery)
    print(f"\n{lab_brief}")

    print("\nGo build this in Packet Tracer now.")
    confirm = input("Type 'done' when finished, or anything else to cancel: ").strip().lower()
    if confirm != "done":
        print("No worries — come back to this lab whenever you're ready.")
        return

    # Retrieval check — testing effect applied right after hands-on practice: answer from
    # memory, not by glancing back at Packet Tracer. This is real evidence of understanding,
    # so (unlike the post-explanation check) it DOES count toward this topic's mastery tracking.
    print("\n--- Quick Recall Check (answer from memory — don't peek at Packet Tracer!) ---")
    questions = ai.generate_lab_retrieval_questions(topic, lab_brief)
    ask_and_grade(topic, questions)

    # Reflection — Kolb's experiential learning cycle: concrete experience -> reflective
    # observation. Not graded; this is self-report journaling, which is genuinely valuable
    # on its own even without a right/wrong check.
    print("\n--- Quick Reflection ---")
    reflection = {
        "What was the trickiest part of this lab?": input("What was the trickiest part of this lab? ").strip(),
        "What would you do differently next time?": input("What would you do differently next time? ").strip(),
        "How does this connect to a real-world scenario?": input("How does this connect to a real-world scenario? ").strip(),
    }

    if any(reflection.values()):
        print("\nThinking...")
        response = ai.respond_to_reflection(topic, reflection)
        print(f"\n{response}")
        db.log_lab_reflection(topic, lab_brief, reflection, response)
        print("\n✅ Lab and reflection logged.")
    else:
        print("\nSkipped reflection — that's okay, the lab and recall check still count.")


def troubleshooting_flow():
    print("\nTroubleshooting-practicable topics:")
    topic = pick_from_list(CLI_PRACTICE_TOPICS)
    if topic is None:
        return

    print(f"\n--- Troubleshooting Case: {topic} ---")
    print("Generating a broken-network scenario...")
    scenario = ai.generate_troubleshooting_case(topic)
    print(f"\n{scenario}")

    answer = input("\nWhat's the root cause, and how would you fix it?\n> ").strip()
    if not answer:
        print("Skipped.")
        return

    print("\nGrading your diagnosis...")
    result = ai.grade_troubleshooting_answer(topic, scenario, answer)
    score = result.get("score", 0)
    feedback = result.get("feedback", "")

    label = {0: "❌ Incorrect", 1: "🟡 Partial", 2: "✅ Correct"}[score]
    print(f"\n{label}")
    print(feedback)

    db.update_after_answer(topic, score)
    db.log_session(topic, f"[TROUBLESHOOTING] {scenario}", answer, score, feedback)


def realworld_scenario_flow():
    print("\nTopics:")
    topic = pick_from_list(TOPICS)
    if topic is None:
        return

    print(f"\n--- Real-World Scenario: {topic} ---")
    print("Generating scenario...")
    scenario = ai.generate_realworld_scenario(topic)
    print(f"\n{scenario}")

    answer = input("\nYour answer: ").strip()
    if not answer:
        print("Skipped.")
        return

    print("\nGrading...")
    result = ai.grade_realworld_scenario(topic, scenario, answer)
    score = result.get("score", 0)
    feedback = result.get("feedback", "")

    label = {0: "❌ Incorrect", 1: "🟡 Partial", 2: "✅ Correct"}[score]
    print(f"\n{label}")
    print(feedback)

    db.update_after_answer(topic, score)
    db.log_session(topic, f"[REAL-WORLD SCENARIO] {scenario}", answer, score, feedback)


def _build_mock_exam_topic_list(total_questions: int):
    """Distributes questions across domains proportional to the real CCNA blueprint weights."""
    counts = {}
    for domain, info in DOMAINS.items():
        counts[domain] = round(info["weight"] * total_questions)

    diff = total_questions - sum(counts.values())
    if diff != 0:
        biggest_domain = max(counts, key=lambda d: counts[d])
        counts[biggest_domain] += diff

    exam_list = []
    for domain, count in counts.items():
        topics_in_domain = DOMAINS[domain]["topics"]
        for _ in range(count):
            exam_list.append((domain, random.choice(topics_in_domain)))

    random.shuffle(exam_list)
    return exam_list


def mock_exam_flow():
    raw = input("\nHow many questions? [15]: ").strip()
    total_questions = int(raw) if raw.isdigit() and int(raw) > 0 else 15

    exam_list = _build_mock_exam_topic_list(total_questions)

    print(f"\n=== Mock Exam: {total_questions} questions, mixed domains, timed ===")
    input("Press Enter when you're ready to start the clock...")
    start_time = time.time()

    correct_count = 0
    partial_count = 0
    domain_breakdown = {d: {"correct": 0, "partial": 0, "wrong": 0, "total": 0} for d in DOMAINS}
    questions_completed = 0

    for i, (domain, topic) in enumerate(exam_list, 1):
        difficulty = db.get_mastery_level(topic)
        print(f"\n--- Question {i}/{total_questions} | {domain} | {topic} ---")
        question = ai.generate_question(topic, difficulty)
        score = ask_and_grade(topic, question, silent=True, allow_quit=True)

        if score == "QUIT":
            print(f"\nExam ended early — {questions_completed}/{total_questions} questions completed.")
            break

        questions_completed += 1
        domain_breakdown[domain]["total"] += 1
        if score == 2:
            correct_count += 1
            domain_breakdown[domain]["correct"] += 1
        elif score == 1:
            partial_count += 1
            domain_breakdown[domain]["partial"] += 1
        else:
            domain_breakdown[domain]["wrong"] += 1

    if questions_completed == 0:
        print("\nNo questions completed — exam cancelled, nothing recorded.")
        return

    elapsed_seconds = int(time.time() - start_time)
    minutes, seconds = divmod(elapsed_seconds, 60)

    score_percent = round(((correct_count + 0.5 * partial_count) / questions_completed) * 100, 1)

    print("\n=== Mock Exam Results ===")
    print(f"Score: {score_percent}%  ({correct_count} correct, {partial_count} partial, "
          f"{questions_completed - correct_count - partial_count} wrong out of {questions_completed})")
    print(f"Time: {minutes}m {seconds}s")
    print(f"{'PASS-LIKE (≥82%)' if score_percent >= 82 else 'BELOW TARGET (aim for 82%+)'}")

    print("\nBy domain:")
    for domain, stats in domain_breakdown.items():
        if stats["total"] == 0:
            continue
        d_score = round(((stats["correct"] + 0.5 * stats["partial"]) / stats["total"]) * 100, 0)
        print(f"  {domain:<32} {d_score:>5.0f}%  ({stats['total']} question(s))")

    db.log_mock_exam(questions_completed, correct_count, partial_count, score_percent,
                      elapsed_seconds, domain_breakdown)


def progress_flow():
    streak = db.get_streak_info()
    print(f"\n🔥 Current streak: {streak['current_streak']} day(s)  |  "
          f"Best ever: {streak['longest_streak']} day(s)  |  "
          f"Studied today: {'Yes' if streak['studied_today'] else 'Not yet'}")

    rows = db.get_all_progress()
    print(f"\n{'Topic':<35} {'Attempts':<10} {'Accuracy':<10} {'Next Due'}")
    print("-" * 75)
    for r in rows:
        acc = f"{(r['correct']/r['attempts']*100):.0f}%" if r["attempts"] else "—"
        due = r["next_due"] if r["next_due"] else "now"
        print(f"{r['topic']:<35} {r['attempts']:<10} {acc:<10} {due}")

    history = db.get_mock_exam_history(limit=5)
    if history:
        print(f"\n{'Mock Exam History (last 5)':<50}")
        print(f"{'Date':<12} {'Score':<10} {'Time'}")
        print("-" * 40)
        for h in history:
            minutes, seconds = divmod(h["elapsed_seconds"], 60)
            print(f"{h['timestamp']:<12} {h['score_percent']:<10} {minutes}m {seconds}s")

    calibration = db.get_calibration_report()
    if calibration:
        print("\n=== Confidence Calibration ===")
        conf_labels = {1: "Guessing", 2: "Somewhat sure", 3: "Very sure"}
        for conf in (1, 2, 3):
            stats = calibration["by_confidence"].get(conf)
            if stats:
                print(f"  {conf_labels[conf]:<15} avg accuracy: {stats['avg_accuracy']}%  ({stats['count']} answers)")
        if calibration["overconfident_topics"]:
            flagged = ", ".join(f"{t} ({c}x)" for t, c in calibration["overconfident_topics"].items())
            print(f"  ⚠️  Confidently WRONG on: {flagged}")
            print("     (You rated yourself 'very sure' but got it wrong — worth extra review.)")


def review_mistakes_flow():
    raw = input("\nHow many recent mistakes to review? [20]: ").strip()
    limit = int(raw) if raw.isdigit() and int(raw) > 0 else 20

    mistakes = db.get_review_mistakes(limit=limit)
    if not mistakes:
        print("\nNo mistakes logged yet — either you're doing great, or you haven't studied yet. 🙂")
        return

    score_label = {0: "❌ Incorrect", 1: "🟡 Partial"}
    conf_label = {1: "😬 was guessing", 2: "🤔 somewhat sure", 3: "😤 was very sure"}
    print(f"\n=== Last {len(mistakes)} Mistake(s), Most Recent First ===")
    for i, m in enumerate(mistakes, 1):
        conf_note = f" | {conf_label[m['confidence']]}" if m["confidence"] else ""
        print(f"\n--- #{i} | {m['topic']} | {m['timestamp']} | {score_label[m['score']]}{conf_note} ---")
        print(f"Q: {m['question']}")
        print(f"Your answer: {m['your_answer']}")
        print(f"Feedback: {m['feedback']}")


def backup_restore_flow():
    print("\n1. Export backup (save your progress to a file)")
    print("2. Import backup (restore from a file — REPLACES current data)")
    choice = input("> ").strip()

    if choice == "1":
        path = input("Save backup as [progress_backup.json]: ").strip() or "progress_backup.json"
        db.export_backup(path)
        print(f"\n✅ Backup saved to {path}")
        print("Copy this file to back it up elsewhere, or move it to another machine to restore there.")

    elif choice == "2":
        path = input("Restore from file [progress_backup.json]: ").strip() or "progress_backup.json"
        if not os.path.exists(path):
            print(f"\n⚠️  File not found: {path}")
            return
        confirm = input(
            f"\n⚠️  This REPLACES all current progress with the contents of '{path}'. "
            f"Type 'yes' to confirm: "
        ).strip().lower()
        if confirm != "yes":
            print("Cancelled — nothing changed.")
            return
        db.import_backup(path)
        print(f"\n✅ Restored from {path}")

    else:
        print("Invalid choice.")


def main():
    check_api_key()
    db.init_db()

    while True:
        print_menu()
        choice = input("> ").strip()
        try:
            if choice == "1":
                quiz_flow()
            elif choice == "2":
                explain_flow()
            elif choice == "3":
                flashcard_flow()
            elif choice == "4":
                comparison_drill_flow()
            elif choice == "5":
                cli_practice_flow()
            elif choice == "6":
                packet_tracer_lab_flow()
            elif choice == "7":
                troubleshooting_flow()
            elif choice == "8":
                realworld_scenario_flow()
            elif choice == "9":
                mock_exam_flow()
            elif choice == "10":
                progress_flow()
            elif choice == "11":
                review_mistakes_flow()
            elif choice == "12":
                backup_restore_flow()
            elif choice == "13":
                switch_provider_flow()
            elif choice == "14":
                print("Good luck studying. Bye!")
                break
            else:
                print("Invalid choice.")
        except ai.AIServiceError as e:
            print(f"\n⚠️  {e}")
            print("Back to the menu — nothing was lost, try again when ready.")


if __name__ == "__main__":
    main()
