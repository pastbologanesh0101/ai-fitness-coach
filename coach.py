#!/usr/bin/env python3
"""AI Fitness Coach — a rule-based weekly workout plan generator.

No LLM or network calls are used. Plans are produced entirely from a local
exercise database (data/exercises.json) combined with a small set of
fitness-coaching rules encoded below (splits, set/rep/rest schemes by goal,
and volume scaling by experience level).

This tool provides general, educational workout guidance only. It is not
personalized medical, physical-therapy, or professional coaching advice.
Consult a qualified professional before starting a new exercise program,
especially if you have an injury or health condition.
"""

import argparse
import json
import os

# ---------------------------------------------------------------------------
# Constants / rule tables
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "exercises.json")

VALID_GOALS = ("strength", "hypertrophy", "endurance", "general_fitness")
VALID_LEVELS = ("beginner", "intermediate", "advanced")
VALID_EQUIPMENT = ("bodyweight", "dumbbells", "full_gym")
MIN_DAYS = 1
MAX_DAYS = 6

# Equipment tiers: an exercise is usable if its required equipment tier is
# less than or equal to the equipment the user says they have available.
# bodyweight (0) <= dumbbells (1) <= full_gym (2)
EQUIPMENT_RANK = {"bodyweight": 0, "dumbbells": 1, "full_gym": 2}

# Sets / reps / rest prescribed purely by training goal.
GOAL_PARAMS = {
    "strength": {"sets": 5, "reps": "3-5", "rest_seconds": 180},
    "hypertrophy": {"sets": 3, "reps": "8-12", "rest_seconds": 75},
    "endurance": {"sets": 2, "reps": "15-20", "rest_seconds": 30},
    "general_fitness": {"sets": 3, "reps": "10-15", "rest_seconds": 60},
}

# Volume scaling by experience level: applied as a delta to the goal's base
# set count, and beginners get simpler progression guidance while advanced
# lifters get an extra accessory exercise per day (more total volume).
LEVEL_SET_DELTA = {"beginner": -1, "intermediate": 0, "advanced": 1}
LEVEL_ADDS_BONUS_EXERCISE = {"beginner": False, "intermediate": False, "advanced": True}

PROGRESSION_NOTES = {
    "beginner": (
        "Progression: focus on learning good form. Once you can complete all "
        "sets/reps with good technique, add a small amount of weight or one "
        "extra rep next session."
    ),
    "intermediate": (
        "Progression: aim to add reps or weight most weeks. Track your lifts "
        "and increase load roughly every 1-2 weeks once reps feel manageable."
    ),
    "advanced": (
        "Progression: use planned overload (weight, reps, or sets) week to "
        "week, and include periodic lighter deload weeks to manage fatigue."
    ),
}

# Muscle groups covered by the plan generator.
MUSCLE_GROUPS = (
    "chest", "back", "shoulders", "quads", "hamstrings",
    "glutes", "calves", "biceps", "triceps", "core",
)

# Day-type -> ordered list of muscle groups trained that day.
DAY_TYPE_MUSCLES = {
    "full_body": [
        "chest", "back", "quads", "hamstrings", "glutes",
        "calves", "shoulders", "biceps", "triceps", "core",
    ],
    "upper": ["chest", "back", "shoulders", "biceps", "triceps"],
    "lower": ["quads", "hamstrings", "glutes", "calves", "core"],
    "push": ["chest", "shoulders", "triceps"],
    "pull": ["back", "biceps", "core"],
    "legs": ["quads", "hamstrings", "glutes", "calves"],
}

# days_per_week -> ordered sequence of day types for the week.
# Chosen so that the union of muscle groups trained across the week always
# covers every entry in MUSCLE_GROUPS, regardless of goal.
SPLIT_BY_DAYS = {
    1: ["full_body"],
    2: ["upper", "lower"],
    3: ["push", "pull", "legs"],
    4: ["upper", "lower", "upper", "lower"],
    5: ["push", "pull", "legs", "upper", "lower"],
    6: ["push", "pull", "legs", "push", "pull", "legs"],
}

SPLIT_NAME_BY_DAYS = {
    1: "full_body",
    2: "upper_lower",
    3: "push_pull_legs",
    4: "upper_lower",
    5: "push_pull_legs_upper_lower",
    6: "push_pull_legs",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(goal, level, days_per_week, equipment):
    """Validate CLI/programmatic inputs, raising ValueError with a clear
    message on the first problem found."""
    if goal not in VALID_GOALS:
        raise ValueError(
            f"Invalid goal '{goal}'. Must be one of: {', '.join(VALID_GOALS)}"
        )
    if level not in VALID_LEVELS:
        raise ValueError(
            f"Invalid level '{level}'. Must be one of: {', '.join(VALID_LEVELS)}"
        )
    if equipment not in VALID_EQUIPMENT:
        raise ValueError(
            f"Invalid equipment '{equipment}'. Must be one of: {', '.join(VALID_EQUIPMENT)}"
        )
    if not isinstance(days_per_week, int) or isinstance(days_per_week, bool):
        raise ValueError(f"days_per_week must be an integer, got {days_per_week!r}")
    if days_per_week < MIN_DAYS or days_per_week > MAX_DAYS:
        raise ValueError(
            f"days_per_week must be between {MIN_DAYS} and {MAX_DAYS} (got {days_per_week})"
        )


# ---------------------------------------------------------------------------
# Exercise database
# ---------------------------------------------------------------------------

def load_exercise_database(path=None):
    """Load the exercise database from disk into a list of dicts."""
    path = path or DEFAULT_DB_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def equipment_allowed(exercise_equipment, selected_equipment):
    """True if an exercise requiring `exercise_equipment` can be performed
    given the user only has `selected_equipment` available."""
    return EQUIPMENT_RANK[exercise_equipment] <= EQUIPMENT_RANK[selected_equipment]


def _candidates_for(database, muscle_group, equipment):
    matches = [
        ex for ex in database
        if ex["muscle_group"] == muscle_group and equipment_allowed(ex["equipment"], equipment)
    ]
    # Deterministic ordering: compound exercises first, then alphabetical.
    matches.sort(key=lambda ex: (0 if ex["type"] == "compound" else 1, ex["name"]))
    return matches


class ExercisePicker:
    """Deterministically rotates through available exercises for a muscle
    group so that a multi-day plan doesn't repeat the same exercise for a
    muscle group on every single day, without relying on randomness."""

    def __init__(self, database, equipment):
        self.database = database
        self.equipment = equipment
        self._counters = {}

    def pick(self, muscle_group, exclude_names=()):
        candidates = _candidates_for(self.database, muscle_group, self.equipment)
        candidates = [c for c in candidates if c["name"] not in exclude_names]
        if not candidates:
            # Fall back to allowing repeats if excluding leaves nothing.
            candidates = _candidates_for(self.database, muscle_group, self.equipment)
        if not candidates:
            raise ValueError(
                f"No exercises available for muscle group '{muscle_group}' "
                f"with equipment '{self.equipment}'"
            )
        idx = self._counters.get(muscle_group, 0) % len(candidates)
        self._counters[muscle_group] = self._counters.get(muscle_group, 0) + 1
        return candidates[idx]


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def _sets_for(goal, level):
    base = GOAL_PARAMS[goal]["sets"]
    delta = LEVEL_SET_DELTA[level]
    return max(2, base + delta)


def generate_plan(goal, level, days_per_week, equipment, database=None):
    """Generate a full weekly workout plan as a plain-data dict.

    Raises ValueError if any input is invalid.
    """
    validate_inputs(goal, level, days_per_week, equipment)
    database = database if database is not None else load_exercise_database()

    goal_params = GOAL_PARAMS[goal]
    reps = goal_params["reps"]
    rest_seconds = goal_params["rest_seconds"]
    sets = _sets_for(goal, level)

    day_types = SPLIT_BY_DAYS[days_per_week]
    picker = ExercisePicker(database, equipment)

    days = []
    for day_number, day_type in enumerate(day_types, start=1):
        muscle_list = DAY_TYPE_MUSCLES[day_type]
        used_names = []
        exercises = []

        for muscle_group in muscle_list:
            exercise = picker.pick(muscle_group, exclude_names=used_names)
            used_names.append(exercise["name"])
            exercises.append({
                "name": exercise["name"],
                "muscle_group": muscle_group,
                "equipment": exercise["equipment"],
                "type": exercise["type"],
                "sets": sets,
                "reps": reps,
                "rest_seconds": rest_seconds,
            })

        if LEVEL_ADDS_BONUS_EXERCISE[level]:
            bonus_muscle = muscle_list[0]
            bonus_exercise = picker.pick(bonus_muscle, exclude_names=used_names)
            used_names.append(bonus_exercise["name"])
            exercises.append({
                "name": bonus_exercise["name"],
                "muscle_group": bonus_muscle,
                "equipment": bonus_exercise["equipment"],
                "type": bonus_exercise["type"],
                "sets": max(2, sets - 1),
                "reps": reps,
                "rest_seconds": rest_seconds,
                "bonus": True,
            })

        days.append({
            "day_number": day_number,
            "day_type": day_type,
            "exercises": exercises,
        })

    return {
        "goal": goal,
        "level": level,
        "days_per_week": days_per_week,
        "equipment": equipment,
        "split_name": SPLIT_NAME_BY_DAYS[days_per_week],
        "progression_note": PROGRESSION_NOTES[level],
        "days": days,
    }


def muscle_groups_covered(plan):
    """Return the set of muscle groups trained anywhere in the plan."""
    covered = set()
    for day in plan["days"]:
        for exercise in day["exercises"]:
            covered.add(exercise["muscle_group"])
    return covered


def total_sets(plan):
    """Return the total number of sets prescribed across the whole week."""
    return sum(
        exercise["sets"]
        for day in plan["days"]
        for exercise in day["exercises"]
    )


# ---------------------------------------------------------------------------
# Formatting / CLI
# ---------------------------------------------------------------------------

DAY_TYPE_LABELS = {
    "full_body": "Full Body",
    "upper": "Upper Body",
    "lower": "Lower Body",
    "push": "Push (Chest/Shoulders/Triceps)",
    "pull": "Pull (Back/Biceps/Core)",
    "legs": "Legs (Quads/Hamstrings/Glutes/Calves)",
}


def format_plan(plan):
    lines = []
    lines.append("=" * 60)
    lines.append("AI FITNESS COACH — WEEKLY WORKOUT PLAN")
    lines.append("=" * 60)
    lines.append(f"Goal:            {plan['goal']}")
    lines.append(f"Experience:      {plan['level']}")
    lines.append(f"Days per week:   {plan['days_per_week']}")
    lines.append(f"Equipment:       {plan['equipment']}")
    lines.append(f"Split:           {plan['split_name']}")
    lines.append("")

    for day in plan["days"]:
        label = DAY_TYPE_LABELS.get(day["day_type"], day["day_type"])
        lines.append(f"Day {day['day_number']}: {label}")
        lines.append("-" * 60)
        for ex in day["exercises"]:
            bonus_tag = " [bonus]" if ex.get("bonus") else ""
            lines.append(
                f"  - {ex['name']:<32} {ex['sets']} sets x {ex['reps']} reps"
                f"   rest {ex['rest_seconds']}s   ({ex['muscle_group']}){bonus_tag}"
            )
        lines.append("")

    lines.append("Progression guidance:")
    lines.append(f"  {plan['progression_note']}")
    lines.append("")
    lines.append(
        "Note: this plan is general, educational workout guidance generated "
        "by simple rules. It is not personalized medical, physical-therapy, "
        "or professional coaching advice. Consult a qualified professional "
        "before starting a new exercise program."
    )
    return "\n".join(lines)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="coach.py",
        description="AI Fitness Coach — rule-based weekly workout plan generator.",
    )
    parser.add_argument("--goal", required=True, choices=VALID_GOALS, help="Training goal")
    parser.add_argument("--level", required=True, choices=VALID_LEVELS, help="Experience level")
    parser.add_argument("--days", required=True, type=int, help="Training days per week (1-6)")
    parser.add_argument("--equipment", required=True, choices=VALID_EQUIPMENT, help="Available equipment")
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        plan = generate_plan(args.goal, args.level, args.days, args.equipment)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    print(format_plan(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
