"""Synthetic history so anyone can try Brainplug without exporting anything.

Chats, notes, documents and messages are generated from templates: none of it is real.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .sources import Item

TOPICS = {
    "python": {
        "chat": ["Pandas groupby question", "Fix my Python loop", "Plot with matplotlib",
                 "Read CSV in pandas", "Merge two dataframes", "Pandas pivot table"],
        "note": ["Python cheat sheet", "Pandas tricks", "Data cleaning checklist"],
        "mail": ["Python assignment group work", "Notebook for the data project"],
        "words": ["python", "pandas", "dataframe", "groupby", "csv", "matplotlib", "loop",
                  "function", "error", "column", "index", "merge", "plot", "numpy"],
    },
    "econometrics": {
        "chat": ["OLS regression assumptions", "Interpret R squared", "Heteroskedasticity test",
                 "Dummy variables in regression", "Panel data basics"],
        "note": ["Econometrics lecture notes", "Regression formulas", "Exam summary econometrics"],
        "mail": ["Question about the regression exercise", "Econometrics exam review"],
        "words": ["regression", "ols", "coefficient", "variance", "residuals", "hypothesis",
                  "significance", "estimator", "heteroskedasticity", "dummy", "model"],
    },
    "finance": {
        "chat": ["How do index funds work", "Compound interest example", "ETF vs mutual fund",
                 "Read a balance sheet", "Bond yields explained"],
        "note": ["Investing principles", "Portfolio ideas", "Valuation notes"],
        "mail": ["Investment club meeting", "Stock pitch feedback"],
        "words": ["etf", "index", "fund", "interest", "portfolio", "stocks", "bonds", "yield",
                  "balance", "sheet", "ebitda", "valuation", "returns", "risk"],
    },
    "printing": {
        "chat": ["PLA vs PETG settings", "First layer not sticking", "Design a phone stand",
                 "Calibrate 3D printer", "Print supports removal"],
        "note": ["3D printer settings log", "Print ideas list", "Filament comparison"],
        "mail": ["Filament order", "3D printed part for the lab"],
        "words": ["printer", "pla", "petg", "layer", "nozzle", "filament", "supports", "stl",
                  "slicer", "bed", "temperature", "infill", "print"],
    },
    "fitness": {
        "chat": ["Push pull legs routine", "Protein intake per day", "Running plan 10k",
                 "Gym routine for beginners", "Creatine questions"],
        "note": ["Workout log", "Running progress", "Meal and protein targets"],
        "mail": ["Gym membership renewal", "10k race registration"],
        "words": ["workout", "routine", "protein", "gym", "running", "muscle", "sets", "reps",
                  "training", "recovery", "squat", "cardio"],
    },
    "travel": {
        "chat": ["3 days in Lisbon", "Greek islands itinerary", "Cheap flights tips",
                 "Weekend in Porto", "Interrail route ideas"],
        "note": ["Trip packing list", "Places to visit", "Summer trip budget"],
        "mail": ["Hotel booking confirmation question", "Summer trip plan with friends"],
        "words": ["trip", "itinerary", "flight", "hotel", "beach", "islands", "museum",
                  "train", "budget", "days", "restaurants", "visit"],
    },
    "career": {
        "chat": ["Improve my CV", "Internship cover letter", "LinkedIn headline ideas",
                 "Prepare interview questions", "Networking message draft"],
        "note": ["Internship applications tracker", "Interview answers", "Career goals"],
        "mail": ["Internship application", "Thank you after the interview", "Coffee chat request"],
        "words": ["cv", "internship", "linkedin", "interview", "cover", "letter", "recruiter",
                  "application", "networking", "headline", "experience", "skills"],
    },
    "startup": {
        "chat": ["Validate my startup idea", "Landing page copy", "Pricing strategy",
                 "Pitch deck structure", "Find first users"],
        "note": ["Startup idea journal", "User interview notes", "Launch checklist"],
        "mail": ["Feedback on the landing page", "Intro to a potential user"],
        "words": ["startup", "users", "mvp", "pricing", "landing", "page", "pitch", "deck",
                  "customers", "growth", "idea", "market", "launch"],
    },
    "cooking": {
        "chat": ["Easy pasta recipe", "Meal prep for the week", "Healthy breakfast ideas",
                 "How to cook rice", "Quick dinner ideas"],
        "note": ["Favourite recipes", "Weekly meal plan", "Shopping list staples"],
        "mail": ["Dinner on Saturday", "Recipe you asked for"],
        "words": ["recipe", "pasta", "chicken", "rice", "cook", "oven", "dinner", "breakfast",
                  "ingredients", "meal", "prep", "minutes"],
    },
}

# Relative weight of each topic over time (start -> end): some rise, some fade.
TRENDS = {
    "python": (1, 5), "econometrics": (3, 2), "finance": (1, 3), "printing": (0, 4),
    "fitness": (3, 0.4), "travel": (2, 2), "career": (1, 4), "startup": (0, 3), "cooking": (2.5, 0),
}
SOURCES = [("chatgpt", "chat", 30), ("claude", "chat", 20), ("gemini", "chat", 8),
           ("obsidian", "note", 16), ("notion", "note", 7), ("word", "note", 4), ("pdf", "note", 2),
           ("gmail", "message", 8), ("whatsapp", "message", 5)]
PEOPLE = ["Marta", "Study group", "Dani", "Family", "Lucía", "Football friends", "Pablo", "Flatmates"]
FILLERS = ["can you explain", "how do I", "what is the best way to", "I am trying to understand",
           "help me with", "quick question about", "why does", "give me an example of"]


def generate(n: int = 600, seed: int = 7, end: datetime | None = None,
             months: int = 18) -> list[Item]:
    rng = random.Random(seed)
    end = end or datetime(2026, 11, 10, tzinfo=timezone.utc)
    start = end - timedelta(days=30 * months)
    span = (end - start).total_seconds()
    names = list(TOPICS)
    notes_by_topic: dict[str, list[str]] = {k: [] for k in names}
    items: list[Item] = []

    def sentence(spec, extra, lo=4, hi=8):
        vocab = spec["words"] + extra
        return " ".join(rng.sample(vocab, k=min(len(vocab), rng.randint(lo, hi))))

    stamps = sorted(rng.random() ** 0.55 for _ in range(n))  # usage grows over time
    for i, t in enumerate(stamps):
        created = start + timedelta(seconds=t * span)
        hour = rng.choice([8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 21, 22, 22, 23, 23, 0])
        created = created.replace(hour=hour, minute=rng.randrange(60))
        if t > 0.6 and rng.random() < 0.5:
            weights = [TRENDS[k][1] for k in names]  # recent months follow the "end" mix
        else:
            weights = [TRENDS[k][0] + (TRENDS[k][1] - TRENDS[k][0]) * t + 0.15 for k in names]
        topic = rng.choices(names, weights=weights)[0]
        if topic == "cooking" and t > 0.68:  # an interest that was dropped...
            topic = "python"
        if topic == "startup" and t < 0.74:  # ...and one that only started recently
            topic = "travel"
        spec = TOPICS[topic]
        other = rng.choice(names) if rng.random() < 0.12 else topic  # some items mix two topics
        if (other == "cooking" and t > 0.68) or (other == "startup" and t < 0.74):
            other = topic
        extra = TOPICS[other]["words"][:10] if other != topic else []
        source, kind, _ = rng.choices(SOURCES, weights=[s[2] for s in SOURCES])[0]

        if kind == "chat":
            turns = rng.choice([1, 1, 2, 2, 3, 4, 6, 9])
            parts, lines, when = [], [], created
            for _ in range(turns):
                lines.append(f"{rng.choice(FILLERS)} {sentence(spec, extra)}?")
                parts.append(when)
                when += timedelta(minutes=rng.randint(1, 15))
            items.append(Item(f"demo-{i}", rng.choice(spec["chat"]), created, source, "chat",
                              "\n".join(lines), parts=parts, size=turns * 2))
        elif kind == "note":
            title = rng.choice(spec["note"])
            links = []
            if notes_by_topic[topic] and rng.random() < 0.7:
                links.append(rng.choice(notes_by_topic[topic]))
            if other != topic and notes_by_topic[other]:
                links.append(rng.choice(notes_by_topic[other]))
            text = ". ".join(sentence(spec, extra, 6, 11) for _ in range(rng.randint(2, 7)))
            items.append(Item(f"demo-{i}", title, created, source, "note", text,
                              links=links, tags=[topic]))
            notes_by_topic[topic].append(title)
        else:
            replies = rng.choice([1, 1, 2, 3])
            parts = [created + timedelta(hours=6 * j) for j in range(replies)]
            text = ". ".join(f"hi, about the {sentence(spec, extra, 5, 9)}" for _ in range(replies))
            title = rng.choice(PEOPLE) if source == "whatsapp" else rng.choice(spec["mail"])
            items.append(Item(f"demo-{i}", title, created, source, "message",
                              text, parts=parts, size=replies * (3 if source == "whatsapp" else 1)))

    items.sort(key=lambda it: it.created)
    return items
