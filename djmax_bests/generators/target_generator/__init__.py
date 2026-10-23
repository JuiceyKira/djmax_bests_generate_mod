"""Target-DJPower generator: project a button's top 100 at a goal total.

`target_plan.build_plan()` does the analysis (which records to play), and
`target_generate.generate_target_image()` renders the projection with the bests layout.
"""
from .target_generate import generate_target_image
from .target_plan import (BucketPlan, PlanEntry, Pattern, TargetPlan, build_plan,
                          design_floor_units, difficulty_key,
                          format_difficulty, format_mean_difficulty, total_from_raw)

__all__ = [
    "BucketPlan",
    "PlanEntry",
    "Pattern",
    "TargetPlan",
    "build_plan",
    "design_floor_units",
    "difficulty_key",
    "format_difficulty",
    "format_mean_difficulty",
    "generate_target_image",
    "total_from_raw",
]
