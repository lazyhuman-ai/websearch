import argparse

from app.agent import DeepResearchAgent
from app.logging_utils import configure_logging


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run the minimal deep research agent")
    parser.add_argument("question", nargs="?", default="", help="Research question")
    parser.add_argument("--output-dir", default="research_outputs", help="Directory for saved markdown")
    parser.add_argument(
        "--no-save-markdown",
        action="store_true",
        help="Do not save markdown to disk",
    )
    parser.add_argument(
        "--show-tools",
        action="store_true",
        help="Print the tool schemas instead of running research",
    )
    args = parser.parse_args()

    agent = DeepResearchAgent()
    if args.show_tools:
        import json

        print(json.dumps(agent.tools.list_descriptions(), ensure_ascii=False, indent=2))
        return
    if not args.question:
        parser.error("question is required unless --show-tools is used")

    response = agent.run(
        question=args.question,
        save_markdown=not args.no_save_markdown,
        output_dir=args.output_dir,
    )
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
