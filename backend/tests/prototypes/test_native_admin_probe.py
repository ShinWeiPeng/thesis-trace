"""Host-only command contract checks; never invoke sudo or perf."""

from native_admin_probe import capture_argv


def test_admin_capture_is_fixed_bounded_and_drops_workload_privileges():
    argv = capture_argv()
    assert argv[:9] == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/timeout",
        "--signal=INT",
        "--kill-after=1s",
        "5s",
        "/usr/bin/prlimit",
        "--fsize=1048576:1048576",
        "--",
    ]
    assert "--reuid=1000" in argv
    assert "--regid=1000" in argv
    assert "--bounding-set=-all" in argv
    assert "--no-new-privs" in argv
    assert argv[argv.index("-o") + 1] == "-"
    assert not {"-a", "--all-cpus", "-p", "--pid", "--uid", "-g"}.intersection(argv)
