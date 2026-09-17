"""Unit tests for the AI Fitness Coach rule-based plan generator."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach  # noqa: E402


class EquipmentConstraintTests(unittest.TestCase):
    def test_bodyweight_plan_uses_only_bodyweight_exercises(self):
        plan = coach.generate_plan("general_fitness", "intermediate", 3, "bodyweight")
        for day in plan["days"]:
            for ex in day["exercises"]:
                self.assertEqual(
                    ex["equipment"], "bodyweight",
                    f"{ex['name']} requires {ex['equipment']} but equipment=bodyweight was requested",
                )

    def test_dumbbells_plan_never_uses_full_gym_only_exercises(self):
        plan = coach.generate_plan("hypertrophy", "intermediate", 4, "dumbbells")
        for day in plan["days"]:
            for ex in day["exercises"]:
                self.assertIn(
                    ex["equipment"], ("bodyweight", "dumbbells"),
                    f"{ex['name']} requires {ex['equipment']} but equipment=dumbbells was requested",
                )

    def test_full_gym_plan_may_use_any_equipment_tier(self):
        plan = coach.generate_plan("strength", "advanced", 5, "full_gym")
        equipment_used = {ex["equipment"] for day in plan["days"] for ex in day["exercises"]}
        self.assertTrue(equipment_used.issubset(set(coach.VALID_EQUIPMENT)))
        # A full-gym user should have access to at least one full_gym-tier
        # exercise somewhere across the week.
        self.assertIn("full_gym", equipment_used)


class GoalSetsRepsTests(unittest.TestCase):
    def test_strength_uses_low_reps_and_high_rest(self):
        plan = coach.generate_plan("strength", "intermediate", 3, "full_gym")
        ex = plan["days"][0]["exercises"][0]
        self.assertEqual(ex["reps"], "3-5")
        self.assertEqual(ex["rest_seconds"], 180)

    def test_endurance_uses_high_reps_and_low_rest(self):
        plan = coach.generate_plan("endurance", "intermediate", 3, "full_gym")
        ex = plan["days"][0]["exercises"][0]
        self.assertEqual(ex["reps"], "15-20")
        self.assertEqual(ex["rest_seconds"], 30)

    def test_goals_produce_distinct_rep_and_rest_schemes(self):
        rep_rest_pairs = set()
        for goal in coach.VALID_GOALS:
            plan = coach.generate_plan(goal, "intermediate", 3, "full_gym")
            ex = plan["days"][0]["exercises"][0]
            rep_rest_pairs.add((ex["reps"], ex["rest_seconds"]))
        # All four goals should map to distinct prescriptions.
        self.assertEqual(len(rep_rest_pairs), len(coach.VALID_GOALS))


class SplitStructureTests(unittest.TestCase):
    def test_number_of_days_matches_days_per_week(self):
        for days in range(coach.MIN_DAYS, coach.MAX_DAYS + 1):
            plan = coach.generate_plan("general_fitness", "intermediate", days, "full_gym")
            self.assertEqual(len(plan["days"]), days)

    def test_day_types_match_expected_split_template(self):
        plan = coach.generate_plan("general_fitness", "intermediate", 4, "full_gym")
        day_types = [day["day_type"] for day in plan["days"]]
        self.assertEqual(day_types, coach.SPLIT_BY_DAYS[4])

        plan6 = coach.generate_plan("general_fitness", "intermediate", 6, "full_gym")
        day_types6 = [day["day_type"] for day in plan6["days"]]
        self.assertEqual(day_types6, coach.SPLIT_BY_DAYS[6])


class MuscleGroupCoverageTests(unittest.TestCase):
    def test_all_muscle_groups_covered_across_full_week_for_every_day_count(self):
        for days in range(coach.MIN_DAYS, coach.MAX_DAYS + 1):
            plan = coach.generate_plan("hypertrophy", "intermediate", days, "full_gym")
            covered = coach.muscle_groups_covered(plan)
            self.assertEqual(
                covered, set(coach.MUSCLE_GROUPS),
                f"days={days} plan is missing muscle groups: {set(coach.MUSCLE_GROUPS) - covered}",
            )

    def test_muscle_groups_covered_even_with_bodyweight_only_equipment(self):
        plan = coach.generate_plan("general_fitness", "beginner", 3, "bodyweight")
        covered = coach.muscle_groups_covered(plan)
        self.assertEqual(covered, set(coach.MUSCLE_GROUPS))


class VolumeByLevelTests(unittest.TestCase):
    def test_advanced_has_more_total_weekly_volume_than_beginner(self):
        beginner_plan = coach.generate_plan("hypertrophy", "beginner", 4, "full_gym")
        advanced_plan = coach.generate_plan("hypertrophy", "advanced", 4, "full_gym")
        self.assertGreater(coach.total_sets(advanced_plan), coach.total_sets(beginner_plan))

    def test_beginner_sets_per_exercise_are_lower_than_advanced(self):
        beginner_plan = coach.generate_plan("strength", "beginner", 3, "full_gym")
        advanced_plan = coach.generate_plan("strength", "advanced", 3, "full_gym")
        beginner_sets = beginner_plan["days"][0]["exercises"][0]["sets"]
        advanced_sets = advanced_plan["days"][0]["exercises"][0]["sets"]
        self.assertLess(beginner_sets, advanced_sets)


class InvalidInputTests(unittest.TestCase):
    def test_zero_days_raises_value_error(self):
        with self.assertRaises(ValueError):
            coach.generate_plan("hypertrophy", "intermediate", 0, "full_gym")

    def test_eight_days_raises_value_error(self):
        with self.assertRaises(ValueError):
            coach.generate_plan("hypertrophy", "intermediate", 8, "full_gym")

    def test_invalid_goal_raises_value_error(self):
        with self.assertRaises(ValueError):
            coach.generate_plan("cardio", "intermediate", 3, "full_gym")

    def test_invalid_equipment_raises_value_error(self):
        with self.assertRaises(ValueError):
            coach.generate_plan("hypertrophy", "intermediate", 3, "resistance_bands")


if __name__ == "__main__":
    unittest.main()
