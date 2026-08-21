from thesis_trace.bootstrap.application import compose_application


def main() -> int:
    return compose_application("ai-worker")()


if __name__ == "__main__":
    raise SystemExit(main())
