from app.sweep import run_once


def test_run_once_is_a_safe_no_op_until_plan_6():
    assert run_once() == 0
    assert run_once() == 0


def test_main_runs_one_sweep_and_logs_the_result(capsys):
    from app.sweep import main

    main()  # configure_logging writes JSON lines to stdout
    assert "0 order(s) released" in capsys.readouterr().out
