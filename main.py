import argparse

from voice_lab.app.application import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VoiceLab")
    parser.add_argument(
        "--formant-lab",
        action="store_true",
        help="Launch the isolated experimental pitch/formant prototype.",
    )
    parser.add_argument(
        "--voice-analysis-lab",
        action="store_true",
        help="Launch the isolated experimental passive source analysis lab.",
    )
    parser.add_argument(
        "--target-planner-lab",
        action="store_true",
        help="Launch the isolated experimental adaptive target planner lab.",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            formant_lab=args.formant_lab,
            voice_analysis_lab=args.voice_analysis_lab,
            target_planner_lab=args.target_planner_lab,
        )
    )
