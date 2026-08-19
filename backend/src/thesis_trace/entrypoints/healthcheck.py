from thesis_trace.bootstrap.application import compose_application


def main() -> int:
    try:
        return 0 if compose_application("collector-healthcheck")() else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
